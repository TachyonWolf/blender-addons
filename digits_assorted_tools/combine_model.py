# SPDX-License-Identifier: GPL-3.0-or-later
"""Combine Multi Part Model: merge a character's parts and nested swap rigs into one rig and one mesh, and save the
result as a new file. The operator and panel that call it are in the package `__init__`."""

import os

import bpy

from . import combine_bones as cb, output_file as of
from .object_tools import ensure_object_mode, remove_object  # generated copy
from .scene_checks import belongs_to, clear_custom_normals  # generated copy

KEPT_MODIFIERS = {'ARMATURE', 'SUBSURF'}  # never applied
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT'}
SUFFIX = "-Whole"


# ---------------------------------------------------------------------------
# Finding the character (rig_of_object, find_rig, belongs_to come from scene_checks, shared with Oops Debugger / Drivers)
# ---------------------------------------------------------------------------

def protected_objects(names):
    """Objects in the named collections (and their children): never touched."""
    result = set()
    for name in names:
        coll = bpy.data.collections.get(name)
        if coll is not None:
            result.update(coll.all_objects)
    return result


def is_visible(ob, view_layer):
    try:
        return ob.name in view_layer.objects and ob.visible_get(view_layer=view_layer)
    except RuntimeError:
        return False


def split_parts(context, rig, keep_names=(), remove_hidden=False):
    """(parts to merge, spares to delete) of the character, protected collections left out.
    Hidden parts are spares when remove_hidden, else merged like the visible ones."""
    view_layer = context.view_layer
    skip = protected_objects(keep_names)
    parts, spares = [], []
    for ob in context.scene.objects:
        if ob.type not in GEOMETRY_TYPES or ob in skip or not belongs_to(ob, rig):
            continue
        (parts if not remove_hidden or is_visible(ob, view_layer) else spares).append(ob)
    return parts, spares


# ---------------------------------------------------------------------------
# Applying modifiers
# ---------------------------------------------------------------------------

def applicable_modifiers(ob):
    return [m for m in ob.modifiers if m.type not in KEPT_MODIFIERS and m.show_viewport]


def evaluated_mesh(ob):
    """Mesh of the object as evaluated now (modifiers, shape keys), without shape keys."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                           depsgraph=depsgraph)


def coords(mesh):
    flat = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get('co', flat)
    return flat


def shape_keys_rebuildable(ob):
    """Shape keys can be re-made after modifiers when they are all relative to the basis."""
    blocks = ob.data.shape_keys.key_blocks
    return all(b.relative_key == blocks[0] and not b.vertex_group for b in blocks[1:])


def bake_with_shape_keys(ob):
    """Evaluate each shape key on its own and rebuild the keys on the modified mesh.
    Returns (mesh, keys) or None when a modifier changes the vertex count per key."""
    blocks = ob.data.shape_keys.key_blocks
    saved = [(b.value, b.mute, b.slider_max) for b in blocks]
    only_key = ob.show_only_shape_key
    ob.show_only_shape_key = False
    try:
        for b in blocks:
            b.value, b.mute = 0.0, False
        base = evaluated_mesh(ob)
        keys = []
        for b in list(blocks)[1:]:
            b.slider_max = max(b.slider_max, 1.0)
            b.value = 1.0
            mesh = evaluated_mesh(ob)
            keys.append((b, coords(mesh), len(mesh.vertices)))
            bpy.data.meshes.remove(mesh)
            b.value = 0.0
    finally:
        for b, (value, mute, slider_max) in zip(blocks, saved):
            b.value, b.mute, b.slider_max = value, mute, slider_max
        ob.show_only_shape_key = only_key
    if any(count != len(base.vertices) for _, _, count in keys):
        bpy.data.meshes.remove(base)
        return None
    return base, keys


def restore_shape_keys(ob, base, keys, old_blocks):
    ob.data = base
    ob.shape_key_add(name=old_blocks[0].name, from_mix=False)
    for (block, co, _count) in keys:
        new = ob.shape_key_add(name=block.name, from_mix=False)
        new.data.foreach_set('co', co)
        new.value, new.slider_min, new.slider_max = block.value, block.slider_min, block.slider_max
        new.mute, new.interpolation = block.mute, block.interpolation


def apply_modifiers(ob, report):
    """Replace the object's geometry with the result of its modifiers (Armature and Subsurf excepted).
    Armature is skipped so everything is applied in rest pose; modifiers after Armature are applied
    to the rest-pose mesh too (as if they came before it). Modifiers off in the viewport are dropped."""
    mods = applicable_modifiers(ob)
    if not mods:
        return
    hidden = [m for m in ob.modifiers if m.type in KEPT_MODIFIERS and m.show_viewport]
    for m in hidden:
        m.show_viewport = False
    try:
        has_keys = ob.type == 'MESH' and ob.data.shape_keys is not None
        if has_keys:
            old = [(b.name, b.value) for b in ob.data.shape_keys.key_blocks]
            rebuilt = bake_with_shape_keys(ob) if shape_keys_rebuildable(ob) else None
            if rebuilt is not None:
                old_blocks = list(ob.data.shape_keys.key_blocks)
                old_data = ob.data
                restore_shape_keys(ob, *rebuilt, old_blocks)
                if old_data.users == 0:
                    bpy.data.meshes.remove(old_data)
                report.notes.append(f"{ob.name}: shape keys rebuilt after modifiers")
                return
            report.warn(f"{ob.name}: shape keys lost (modifiers change the vertex count or keys are not "
                        f"relative to the basis); baked at current values {[n for n, v in old if v]}")
        mesh = evaluated_mesh(ob)
        old_data = ob.data
        ob.data = mesh
        if old_data.users == 0:
            bpy.data.meshes.remove(old_data)
    finally:
        for m in hidden:
            m.show_viewport = True


def curve_to_mesh_object(ob, report):
    """New mesh object (same place in the scene) from a visible curve/text/surface, or None."""
    if any(m.type == 'ARMATURE' for m in ob.modifiers):
        report.warn(f"{ob.name}: curve deformed by the armature can't be merged, skipped")
        return None
    hidden = [m for m in ob.modifiers if m.type in KEPT_MODIFIERS and m.show_viewport]
    for m in hidden:
        m.show_viewport = False
    mesh = evaluated_mesh(ob)
    for m in hidden:
        m.show_viewport = True
    new = bpy.data.objects.new(ob.name + "_mesh", mesh)
    for coll in ob.users_collection:
        coll.objects.link(new)
    new.parent, new.parent_type, new.parent_bone = ob.parent, ob.parent_type, ob.parent_bone
    new.matrix_parent_inverse = ob.matrix_parent_inverse
    new.matrix_world = ob.matrix_world
    report.notes.append(f"{ob.name}: converted to mesh")
    return new


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

def part_rig(ob, main):
    """The rig that deforms this part: its first Armature modifier's object, its bone parent's armature,
    else the main rig."""
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object
    if ob.parent and ob.parent.type == 'ARMATURE' and ob.parent_type == 'BONE':
        return ob.parent
    return main


def weight_bone_parented(ob):
    """A mesh parented to a bone (no Armature modifier) gets a full-weight group for that bone, and the bone
    becomes a deform bone (the Armature modifier ignores non-deform bones, so the mesh would never move)."""
    if not (ob.parent and ob.parent.type == 'ARMATURE' and ob.parent_type == 'BONE' and ob.parent_bone):
        return
    if any(m.type == 'ARMATURE' for m in ob.modifiers):
        return
    group = ob.vertex_groups.get(ob.parent_bone) or ob.vertex_groups.new(name=ob.parent_bone)
    group.add(range(len(ob.data.vertices)), 1.0, 'REPLACE')
    bone = ob.parent.data.bones.get(ob.parent_bone)
    if bone is not None:
        bone.use_deform = True


def weighted_non_deform_groups(mesh_ob, rig):
    """Names of the mesh's vertex groups that have weight on some vertex but name a bone of `rig` that does not
    deform (so the Armature modifier ignores them). Empty list = every weight works."""
    weighted = {g.group for v in mesh_ob.data.vertices for g in v.groups if g.weight > 0.0}
    bones = rig.data.bones
    return [g.name for g in mesh_ob.vertex_groups if g.index in weighted and g.name in bones and not bones[g.name].use_deform]


def warn_multiple_rigs(ob, report):
    rigs = {m.object.name for m in ob.modifiers if m.type == 'ARMATURE' and m.object}
    if len(rigs) > 1:
        report.warn(f"{ob.name}: deformed by several armatures {sorted(rigs)}; only the first is joined into the rig")


# ---------------------------------------------------------------------------
# Joining swap rigs into the main rig
# ---------------------------------------------------------------------------

def carrying_bone(swap_rig, main):
    """Main-rig bone that carries the swap rig object (bone parent or Child Of constraint), else None."""
    if swap_rig.parent == main and swap_rig.parent_type == 'BONE' and swap_rig.parent_bone in main.data.bones:
        return swap_rig.parent_bone
    for con in swap_rig.constraints:
        if con.type == 'CHILD_OF' and con.target == main and con.subtarget in main.data.bones:
            return con.subtarget
    return None


def rename_clashing_bones(swap_rig, taken, parts):
    """Give the swap rig's bones that clash with `taken` names a unique name, and the same to the
    matching vertex groups of its parts. Returns the number renamed."""
    renamed = 0
    for bone in list(swap_rig.data.bones):
        old = bone.name
        if old not in taken:
            taken.add(old)
            continue
        new, n = f"{old}.{swap_rig.name}"[:60], 1
        while new in taken:
            new = f"{old}.{swap_rig.name}"[:55] + f".{n:03d}"
            n += 1
        bone.name = new  # Blender also fixes constraint subtargets, drivers and groups of deformed meshes
        for ob in parts:
            group = ob.vertex_groups.get(old)
            if group is not None:
                group.name = new
        taken.add(new)
        renamed += 1
    return renamed


def retarget_to(old_rigs, main):
    """Constraints and driver variables that point at a rig about to be joined point at the main rig."""
    for ob in bpy.data.objects:
        for _pb, link in cb.constraint_links(ob):
            if link.target in old_rigs:
                link.target = main
    for _item, _fcurve, target in cb.driver_targets():
        if target.id in old_rigs:
            target.id = main


def reparent_keep_world(objects, rig):
    for ob in objects:
        world = ob.matrix_world.copy()
        ob.parent, ob.parent_type, ob.parent_bone = rig, 'OBJECT', ""
        ob.matrix_world = world


def make_selectable(context, ob):
    """Swap rigs often sit in hidden or excluded collections; join needs them in the view layer, visible."""
    if ob.name not in context.view_layer.objects:
        context.scene.collection.objects.link(ob)
    ob.hide_viewport = ob.hide_select = False
    ob.hide_set(False)


def join_swap_rigs(context, main, swaps, report):
    """Join the swap armatures into the main one (bones keep their world rest position). A swap rig carried
    by a main bone gets its root bones parented to that bone, so it follows as before."""
    taken = {b.name for b in main.data.bones}
    # (carrying bone, root bone names) per rig, read now: the rig objects are gone after the join
    attach = [(carrying_bone(r, main), [b.name for b in r.data.bones if b.parent is None]) for r in swaps]
    for r in swaps:
        if r.animation_data and r.animation_data.action:
            report.warn(f"{r.name}: animation on the rig object is not carried over")
    retarget_to(set(swaps), main)
    datas = [r.data for r in swaps]
    for ob in context.selected_objects:
        ob.select_set(False)
    for r in swaps:
        make_selectable(context, r)
        r.select_set(True)
    main.select_set(True)
    context.view_layer.objects.active = main
    bpy.ops.object.join()
    for data in datas:
        if data.users == 0:
            bpy.data.armatures.remove(data)
    if any(bone for bone, _ in attach):
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = main.data.edit_bones
        for bone, root_names in attach:
            for name in root_names:
                child = edit_bones.get(name)
                if bone and child:
                    child.parent, child.use_connect = edit_bones[bone], False
        bpy.ops.object.mode_set(mode='OBJECT')


def other_users(rig, gone):
    """True if an object that stays uses the rig (Armature modifier or constraint target)."""
    for ob in bpy.data.objects:
        if ob in gone:
            continue
        if any(m.type == 'ARMATURE' and m.object == rig for m in ob.modifiers):
            return True
        if any(link.target == rig for _pb, link in cb.constraint_links(ob)):
            return True
    return False


def subsurf_levels(parts):
    """(max viewport, max render, number of parts with subsurf, set of distinct level pairs)."""
    pairs = [(m.levels, m.render_levels) for ob in parts for m in ob.modifiers if m.type == 'SUBSURF']
    if not pairs:
        return None
    return max(p[0] for p in pairs), max(p[1] for p in pairs), set(pairs)


def uv_name_sets(parts):
    return {tuple(uv.name for uv in ob.data.uv_layers) for ob in parts if ob.type == 'MESH'}


def render_uv_to_uvmap(ob):
    """Make the part's render UV the layer named "UVMap", so a join (which matches UV layers by name) keeps its coordinates.
    The old "UVMap" is kept as "UVMap_Old"; every other layer (e.g. ones used by UV Map nodes) is left alone."""
    layers = ob.data.uv_layers
    render = next((uv for uv in layers if uv.active_render), None)
    if render is None or render.name == "UVMap":
        return False
    old = layers.get("UVMap")
    if old:
        old.name = "UVMap_Old"
    coords = [0.0] * (2 * len(render.data))
    render.data.foreach_get("uv", coords)
    new = layers.new(name="UVMap")
    new.data.foreach_set("uv", coords)
    new.active_render = new.active = True
    return True


def reparent_children(parents, rig, skip=()):
    """Objects left behind under objects that will be deleted go to the rig, keeping their world position."""
    reparent_keep_world([ob for ob in bpy.data.objects if ob.parent in parents and ob not in skip], rig)


class Report:
    def __init__(self):
        self.warnings, self.notes = [], []
        self.merged = self.spares = self.rigs_joined = self.rigs_deleted = 0
        self.saved_path = None
        self.islands = self.manifold = self.seconds = None
        self.island_names = []
        self.thickened = 0
        self.uv_fixed = []

    def warn(self, text):
        self.warnings.append(text)

    def summary(self):
        text = f"Merged {self.merged} parts, deleted {self.spares} spare parts"
        if self.rigs_joined or self.rigs_deleted:
            text += f", joined {self.rigs_joined} swap rigs, deleted {self.rigs_deleted} spare rigs"
        if self.warnings:
            text += f", {len(self.warnings)} warning(s): " + "; ".join(self.warnings)
        return text


def drop_custom_normals(context, ob):
    """Remove the custom split normals so Geometry Nodes modifiers behave."""
    context.view_layer.objects.active = ob
    if ob.data.has_custom_normals:
        clear_custom_normals(ob)


def convert_parts(parts, report):
    """Apply the modifiers of the mesh parts and turn the others into meshes. Returns (originals to delete, objects to merge)."""
    originals, merge = [], []
    for ob in parts:
        if ob.type == 'MESH':
            apply_modifiers(ob, report)
            merge.append(ob)
        else:
            new = curve_to_mesh_object(ob, report)
            if new is not None:
                merge.append(new)
                originals.append(ob)
    return originals, merge


def join_parts(context, rig, parts, merge, originals, spares, spare_rigs, report):
    """Join the swap rigs into `rig`, join the meshes into one, delete what is left over.
    Returns (target, uv_sets, subdivision levels, preserve volume, rigs that were deleted)."""
    levels = subsurf_levels(parts)
    for ob in merge:
        if ob.type == 'MESH' and render_uv_to_uvmap(ob):
            report.uv_fixed.append(ob.name)
    uv_sets = uv_name_sets(merge)
    rig_of_part = {}
    for ob in merge:
        warn_multiple_rigs(ob, report)
        weight_bone_parented(ob)
        rig_of_part[ob] = part_rig(ob, rig)
    swaps = sorted(set(rig_of_part.values()) - {rig}, key=lambda r: r.name)
    taken = {b.name for b in rig.data.bones}
    for r in swaps:
        rename_clashing_bones(r, taken, [ob for ob in merge if rig_of_part[ob] == r])
    for ob in merge:
        for mod in list(ob.modifiers):
            ob.modifiers.remove(mod)
    preserve = any(m.use_deform_preserve_volume for ob in parts for m in ob.modifiers
                   if m.type == 'ARMATURE' and m.object == rig)

    target = merge[0]
    gone_objects = set(spares) | set(originals)
    spare_rigs = {r for r in spare_rigs if not other_users(r, gone_objects | set(merge) | spare_rigs | set(swaps))}
    reparent_children(gone_objects | set(swaps) | spare_rigs, rig, skip=gone_objects | set(swaps) | spare_rigs)
    if swaps:
        join_swap_rigs(context, rig, swaps, report)
        report.rigs_joined = len(swaps)
    for ob in context.selected_objects:
        ob.select_set(False)
    for ob in merge:
        make_selectable(context, ob)
        ob.select_set(True)
    context.view_layer.objects.active = target
    if len(merge) > 1:
        bpy.ops.object.join()
    for ob in originals + list(spares) + list(spare_rigs):
        remove_object(ob)
    report.rigs_deleted = len(spare_rigs)
    report.merged, report.spares = len(parts), len(spares)
    return target, uv_sets, levels, preserve


def finish_target(target, rig, preserve, levels, report):
    """Parent the merged mesh to the rig (keeping its place) and give it an Armature and a Subdivision modifier."""
    world = target.matrix_world.copy()
    target.parent, target.parent_type, target.parent_bone = rig, 'OBJECT', ""
    target.matrix_world = world

    arm = target.modifiers.new("Armature", 'ARMATURE')
    arm.object, arm.use_deform_preserve_volume = rig, preserve
    sub = target.modifiers.new("Subdivision", 'SUBSURF')
    if levels is None:
        report.warn("no part had Subdivision Surface; added one at levels 1 / render 2")
        sub.levels, sub.render_levels = 1, 2
    else:
        sub.levels, sub.render_levels = levels[0], levels[1]
        if len(levels[2]) > 1:
            report.warn(f"subdivision levels differed {sorted(levels[2])}; used highest {levels[0]} / {levels[1]}")


def make_whole(context, rig, keep_names=(), remove_hidden=False, drop_normals=False):
    """Merge the character's parts into one mesh (hidden ones are deleted instead when remove_hidden; custom normals removed when drop_normals). Returns (object, Report) or (None, Report)."""
    report = Report()
    ensure_object_mode(context)
    parts, spares = split_parts(context, rig, keep_names, remove_hidden)
    parts = [ob for ob in parts if ob.library is None]
    if not parts:
        report.warn("no parts to merge")
        return None, report

    part_rigs = {part_rig(ob, rig) for ob in parts}
    spare_rigs = {part_rig(ob, rig) for ob in spares} - part_rigs - {rig}
    pose_positions = {r: r.data.pose_position for r in part_rigs | spare_rigs | {rig}}
    for r in pose_positions:
        r.data.pose_position = 'REST'
    try:
        originals, merge = convert_parts(parts, report)
        if not merge:
            report.warn("nothing could be merged")
            return None, report
        context.view_layer.update()
        target, uv_sets, levels, preserve = join_parts(context, rig, parts, merge, originals, spares, spare_rigs, report)
    finally:
        for r, position in pose_positions.items():
            try:
                r.data.pose_position = position
            except ReferenceError:  # rig was joined or deleted
                pass

    if report.uv_fixed:
        report.notes.append(f"render UV copied to \"UVMap\" on: {', '.join(report.uv_fixed)}")
    if len(uv_sets) > 1:
        report.warn("parts have different UV map names; layers with the same name are joined, the others stay on their own parts")
    target.name = target.data.name = rig.name + "_Whole"
    if drop_normals:
        drop_custom_normals(context, target)
    finish_target(target, rig, preserve, levels, report)
    dead = weighted_non_deform_groups(target, rig)
    if dead:
        report.warn(f"weights on non-deform bones (they will not move the mesh): {dead}")
    return target, report


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def whole_path(filepath, name="", folder="", rig_name=""):
    """The file Combine saves: <file>-Whole.blend next to the file (a never saved file: <rig>-Whole.blend, only when a
    folder is typed), -2, -3 ... if taken, or the typed name / folder. Never an existing path. None: nowhere to save."""
    stem = os.path.splitext(os.path.basename(filepath))[0] if filepath else rig_name
    return of.output_path(name, folder, stem + SUFFIX, ".blend", filepath)


def save_as_whole(name="", folder="", rig_name=""):
    """Save the session as a new file (see whole_path; keeps relative paths valid).
    Returns the path, or None when there is nowhere to save it."""
    path = whole_path(bpy.data.filepath, name, folder, rig_name)
    if path is None:
        return None
    of.make_folder(path)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path
