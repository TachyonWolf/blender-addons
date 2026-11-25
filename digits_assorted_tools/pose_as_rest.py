# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply Pose as Rest (logic; the card and operator are in pose_as_rest_ui.py): make the rig's current pose its rest
pose AND move every mesh it deforms along, so nothing changes in the viewport. No UI in here.

For each mesh data deformed by the rig (a shared mesh once), the Armature modifier alone is evaluated and its result is
written back into the mesh: the vertices, and with shape keys the Basis AND every key (each one shown on its own, so
relative keys, values, ranges, vertex groups and drivers of the keys stay exactly as they were; only the coordinates
change). The modifier itself is never removed, so its place in the stack and its settings are untouched; after the
pose is rest it deforms by nothing. Last the rig's pose becomes its rest pose (Blender's own Apply Pose as Rest) and
objects parented to the rig keep their world place (a bone-parented object is corrected when the bone's length changed).
Meshes it cannot do are skipped and reported (SKIPS); things it cannot fix are listed as warnings."""
from contextlib import contextmanager
from dataclasses import dataclass, field

import bpy
import numpy as np

from .pose_shape_keys import armature_modifier, deformed_coords, restore_states, switch_modifiers
from .scene_checks import users_by_data  # generated copy

SIZE_TOLERANCE = 1e-4   # matrix difference under which two users of a shared mesh, or a child before / after, count as equal
ARMATURE_SETTINGS = ("use_vertex_groups", "use_bone_envelopes", "use_deform_preserve_volume", "use_multi_modifier",
                     "vertex_group", "invert_vertex_group")

SKIPS = {"library": "linked from a library", "not_in_view_layer": "not in this scene's view layer",
         "hidden_by_collection": "hidden by its collection", "two_modifiers": "two Armature modifiers on this rig",
         "shared_other_user": "shares its mesh with an object this rig does not deform",
         "shared_differs": "shares its mesh with an object that deforms or sits differently",
         "count_changes": "vertex count changes"}


class CannotPose(Exception):
    """One mesh cannot be read posed; `args[0]` is a SKIPS key."""


@dataclass
class Result:
    meshes: int = 0
    shape_keys: int = 0
    skipped: list = field(default_factory=list)    # (object name, SKIPS text)
    warnings: list = field(default_factory=list)   # plain sentences: what the tool cannot fix

    def summary(self):
        text = f"Pose is now the rest pose; {self.meshes} meshes moved along, {self.shape_keys} shape keys"
        if self.skipped:
            text += ". Skipped: " + ", ".join(f"{name} ({why})" for name, why in self.skipped)
        return text


# ---------------------------------------------------------------------------
# Which meshes
# ---------------------------------------------------------------------------

def deformed_objects(rig):
    """Every mesh object in the file with an Armature modifier on `rig`."""
    return [ob for ob in bpy.data.objects if ob.type == 'MESH' and armature_modifier(ob, rig)]


def armature_look(ob, rig):
    """What decides how `ob` is deformed by `rig`: the modifier's settings and the object's place relative to the rig."""
    mod = armature_modifier(ob, rig)
    relative = rig.matrix_world.inverted_safe() @ ob.matrix_world
    return tuple(getattr(mod, name) for name in ARMATURE_SETTINGS), relative


def same_look(a, b):
    (settings_a, matrix_a), (settings_b, matrix_b) = a, b
    return settings_a == settings_b and all(abs(x - y) < SIZE_TOLERANCE
                                            for row_a, row_b in zip(matrix_a, matrix_b) for x, y in zip(row_a, row_b))


def own_skip_reason(ob, rig, view_layer):
    """Why this object cannot be done by itself (a SKIPS key), or None."""
    if ob.library is not None or ob.data.library is not None or ob.data.override_library is not None:
        return "library"
    if ob.name not in view_layer.objects:
        return "not_in_view_layer"
    if sum(1 for m in ob.modifiers if m.type == 'ARMATURE' and m.object == rig) > 1:
        return "two_modifiers"
    return None


def group_skip_reason(users, rig):
    """Why one shared mesh cannot be done (a SKIPS key), or None: all its users must be deformed by this rig the same way."""
    if any(armature_modifier(ob, rig) is None for ob in users):
        return "shared_other_user"
    first = armature_look(users[0], rig)
    if not all(same_look(first, armature_look(ob, rig)) for ob in users[1:]):
        return "shared_differs"
    return None


def plan_groups(rig, view_layer):
    """([[objects sharing one mesh]], [(object name, why skipped)]): the groups to do, each mesh once."""
    skipped, usable = [], []
    for ob in deformed_objects(rig):
        reason = own_skip_reason(ob, rig, view_layer)
        if reason:
            skipped.append((ob.name, SKIPS[reason]))
        else:
            usable.append(ob)
    groups = []
    for data, users in users_by_data().items():
        mine = [ob for ob in users if ob in usable]
        if not mine:
            continue
        reason = group_skip_reason(users, rig) if len(users) > 1 else None
        if len(users) > 1 and not reason and len(mine) < len(users):
            reason = "shared_other_user"
        if reason:
            skipped += [(ob.name, SKIPS[reason]) for ob in mine]
        else:
            groups.append(mine)
    return groups, skipped


# ---------------------------------------------------------------------------
# Reading the posed shapes
# ---------------------------------------------------------------------------

@contextmanager
def shown(ob):
    """`ob` visible in the viewport while evaluated (the depsgraph skips hidden objects); the hide flags come back after."""
    kept = (ob.hide_viewport, ob.hide_get())
    ob.hide_viewport = False
    ob.hide_set(False)
    try:
        yield ob.visible_get()
    finally:
        ob.hide_viewport = kept[0]
        ob.hide_set(kept[1])


@contextmanager
def showing_key(ob, key_index):
    """Shape key `key_index` of `ob` shown alone, whole (its value, its relative key, its vertex group and mute state
    ignored). Does nothing for a mesh without shape keys. Everything comes back after."""
    keys = ob.data.shape_keys
    if keys is None:
        yield
        return
    kept = (ob.show_only_shape_key, ob.active_shape_key_index,
            [(kb, kb.vertex_group, kb.mute) for kb in keys.key_blocks])
    for kb in keys.key_blocks:
        kb.vertex_group, kb.mute = "", False
    ob.show_only_shape_key, ob.active_shape_key_index = True, key_index
    try:
        yield
    finally:
        ob.show_only_shape_key, ob.active_shape_key_index = kept[0], kept[1]
        for kb, vertex_group, mute in kept[2]:
            kb.vertex_group, kb.mute = vertex_group, mute


def block_count(ob):
    keys = ob.data.shape_keys
    return len(keys.key_blocks) if keys else 1


def posed_blocks(context, rig, ob):
    """[flat posed coordinates] for the mesh of `ob`: one entry, or one per shape key block (Basis first); the Armature
    modifier alone, as the rig is posed now. Raises CannotPose when a vertex count differs or `ob` cannot be shown."""
    saved = switch_modifiers(ob, armature_modifier(ob, rig), also_before=True)
    blocks = []
    try:
        with shown(ob) as visible:
            if not visible:
                raise CannotPose("hidden_by_collection")
            for key_index in range(block_count(ob)):
                with showing_key(ob, key_index):
                    context.view_layer.update()
                    coords = deformed_coords(ob, context.evaluated_depsgraph_get())
                if coords is None:
                    raise CannotPose("count_changes")
                blocks.append(np.array(coords, dtype=np.float32))
    finally:
        restore_states(saved)
    return blocks


def flat_coords(data_block):
    coords = np.empty(len(data_block) * 3, dtype=np.float32)
    data_block.foreach_get("co", coords)
    return coords


def current_blocks(mesh):
    """[flat coordinates] in the same layout as posed_blocks, as the mesh is now."""
    keys = mesh.shape_keys
    return [flat_coords(kb.data) for kb in keys.key_blocks] if keys else [flat_coords(mesh.vertices)]


def write_blocks(mesh, blocks):
    """Put `blocks` (posed_blocks layout) into the mesh; with shape keys also its vertices (= the Basis)."""
    keys = mesh.shape_keys
    if keys:
        for kb, coords in zip(keys.key_blocks, blocks):
            kb.data.foreach_set("co", coords)
    mesh.vertices.foreach_set("co", blocks[0])
    mesh.update()


# ---------------------------------------------------------------------------
# Warnings: what the tool cannot fix
# ---------------------------------------------------------------------------

def mesh_warnings(ob, rig):
    """Sentences about one mesh whose result may not look the same."""
    mod, notes = armature_modifier(ob, rig), []
    before = [m.name for m in ob.modifiers[:list(ob.modifiers).index(mod)] if m.show_viewport]
    if before:
        notes.append(f"{ob.name}: modifiers before the Armature modifier ({', '.join(before)}) now work on the posed shape")
    if any(m.type == 'ARMATURE' and m.object != rig for m in ob.modifiers):
        notes.append(f"{ob.name}: another Armature modifier on a different rig also deforms it")
    if ob.data.shape_keys and mod.use_deform_preserve_volume:
        notes.append(f"{ob.name}: Preserve Volume with shape keys, keys match only approximately when posed")
    if ob.data.has_custom_normals:
        notes.append(f"{ob.name}: custom normals are not turned with the pose")
    return notes


def rig_warnings(rig):
    """Sentences about constraints, drivers and animation on the rig that still act on the new rest pose."""
    notes = []
    constrained = [pb.name for pb in rig.pose.bones if any(c.enabled and c.influence > 0 for c in pb.constraints)]
    if constrained:
        notes.append(f"{len(constrained)} bones have constraints (they act on the new rest pose again): {', '.join(constrained[:5])}")
    animation = rig.animation_data
    drivers = [fc for fc in animation.drivers if fc.data_path.startswith("pose.bones")] if animation else []
    if drivers:
        notes.append(f"{len(drivers)} drivers on bone transforms will move the pose away from rest again")
    if animation and animation.action and any(fc.data_path.startswith("pose.bones") for fc in animation.action.fcurves):
        notes.append("the active action has keys on bones: they now offset from the new rest pose")
    return notes


def child_armatures(rig):
    """Armature objects parented to `rig` (part armatures): their own poses are not touched."""
    return [ob.name for ob in bpy.data.objects if ob.type == 'ARMATURE' and ob.parent == rig]


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def world_matrices(rig):
    return {ob: ob.matrix_world.copy() for ob in bpy.data.objects if ob.parent == rig}


def keep_children_in_place(context, rig, before):
    """Objects parented to the rig keep their world place: a changed one gets its parent inverse matrix corrected."""
    context.view_layer.update()
    for ob, old_world in before.items():
        if all(abs(x - y) < SIZE_TOLERANCE for row_a, row_b in zip(ob.matrix_world, old_world) for x, y in zip(row_a, row_b)):
            continue
        parent_to_local = ob.matrix_parent_inverse @ ob.matrix_basis
        new_parent_world = ob.matrix_world @ parent_to_local.inverted_safe()
        ob.matrix_parent_inverse = new_parent_world.inverted_safe() @ old_world @ ob.matrix_basis.inverted_safe()


def pose_to_rest(context, rig):
    """Blender's Apply Pose as Rest on every bone of `rig`; active object and mode come back after."""
    view_layer = context.view_layer
    kept_active = view_layer.objects.active
    was_posing = context.mode == 'POSE' and kept_active == rig
    view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    try:
        bpy.ops.pose.armature_apply(selected=False)
    finally:
        if not was_posing:
            bpy.ops.object.mode_set(mode='OBJECT')
            view_layer.objects.active = kept_active


def apply_pose_as_rest(context, rig):
    """Do it (see the module doc). Everything is read first and written after, so a refusal leaves the file as it was.
    Returns a Result."""
    result = Result()
    groups, result.skipped = plan_groups(rig, context.view_layer)
    kept_position = rig.data.pose_position
    rig.data.pose_position = 'POSE'
    posed = []   # [(mesh, objects, posed blocks, old blocks)]
    try:
        for objects in groups:
            try:
                blocks = posed_blocks(context, rig, objects[0])
            except CannotPose as problem:
                result.skipped += [(ob.name, SKIPS[problem.args[0]]) for ob in objects]
                continue
            posed.append((objects[0].data, objects, blocks, current_blocks(objects[0].data)))
    finally:
        rig.data.pose_position = kept_position
    children = world_matrices(rig)
    for mesh, objects, blocks, _old in posed:
        write_blocks(mesh, blocks)
    try:
        pose_to_rest(context, rig)
    except RuntimeError:
        for mesh, _objects, _blocks, old in posed:
            write_blocks(mesh, old)
        raise
    keep_children_in_place(context, rig, children)
    for mesh, objects, blocks, _old in posed:
        result.meshes += 1
        result.shape_keys += len(blocks) - 1
        for ob in objects:
            result.warnings += mesh_warnings(ob, rig)
    result.warnings += rig_warnings(rig)
    armatures = child_armatures(rig)
    if armatures:
        result.warnings.append(f"{len(armatures)} part armatures are parented to this rig and keep their own poses")
    return result
