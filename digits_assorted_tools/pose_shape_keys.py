# SPDX-License-Identifier: GPL-3.0-or-later
"""Poses to Shape Keys (Digit's Tools > Character Rigs): bake the rig's pose into shape keys on the meshes it deforms.
Source: the current pose (one key, typed name) or every pose marker of the rig's active action (one key per marker, named
after it). Targets: the selected meshes, or with the rig selected every visible mesh with an Armature modifier pointing
at it. Each key is the mesh with the pose applied (modifiers up to and including the Armature modifier only; later ones,
e.g. Subdivision, are switched off while evaluating), relative to Basis (made when missing). Existing shape keys are
muted while evaluating so they never leak into the result. A key with the same name is replaced. Meshes whose vertex
count still changes are skipped and reported. The user's pose, frame and modifier / shape key states are restored.
Pose reading / restoring and the rig lookup are save_pose's."""
from dataclasses import dataclass, field

import bpy
from bpy.props import EnumProperty, StringProperty

from .save_pose import PoseOperator, apply_pose, read_pose, target_rig
from .ui_cards import action_row, hints, prop_group, section, status  # generated copy

SOURCES = (('CURRENT', "Current Pose", "One key from the pose the rig has now"),
           ('MARKERS', "Each Pose Marker", "One key per pose marker of the rig's active action, named after the marker"))


@dataclass
class Result:
    keys: int = 0
    skipped: list = field(default_factory=list)   # (mesh name, why)

    def summary(self):
        text = f"{self.keys} shape keys written"
        if self.skipped:
            text += "; skipped " + ", ".join(f"{name} ({why})" for name, why in self.skipped)
        return text


# ---------------------------------------------------------------------------
# What to bake
# ---------------------------------------------------------------------------

def armature_modifier(ob, rig):
    """The last Armature modifier of `ob` that points at `rig`, else None."""
    mods = [m for m in ob.modifiers if m.type == 'ARMATURE' and m.object == rig]
    return mods[-1] if mods else None


def target_meshes(context, rig):
    """The meshes to bake onto: with the rig itself active, every visible mesh deformed by it; else the selected
    meshes deformed by it."""
    visible = [ob for ob in context.view_layer.objects if ob.visible_get()]
    found = visible if context.active_object == rig else [ob for ob in visible if ob.select_get()]
    return [ob for ob in found if ob.type == 'MESH' and armature_modifier(ob, rig)]


def marker_poses(rig):
    """[(marker name, frame)] of the rig's active action."""
    action = rig.animation_data.action if rig.animation_data else None
    return [(m.name, m.frame) for m in action.pose_markers] if action else []


def pose_list(source, name, rig):
    """[(key name, frame or None)]: None = the pose as it is now."""
    if source == 'MARKERS':
        return marker_poses(rig)
    return [(name.strip() or "Pose", None)]


# ---------------------------------------------------------------------------
# Baking
# ---------------------------------------------------------------------------

def deformed_coords(ob, depsgraph):
    """Flat list of the evaluated vertex coordinates (object space), or None when the count differs from the mesh's."""
    evaluated = ob.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if len(mesh.vertices) != len(ob.data.vertices):
            return None
        coords = [0.0] * (3 * len(mesh.vertices))
        mesh.vertices.foreach_get("co", coords)
        return coords
    finally:
        evaluated.to_mesh_clear()


def switch_modifiers(ob, mod, also_before=False):
    """Make `mod` the last modifier that runs on `ob` (the ones after it are switched off in the viewport; with
    `also_before` the ones before it too, and `mod` is switched on). Returns the list (modifier, old show_viewport)."""
    saved = []
    after = False
    for m in ob.modifiers:
        saved.append((m, m.show_viewport))
        if m == mod:
            m.show_viewport, after = True, True
        elif after or also_before:
            m.show_viewport = False
    return saved


def restore_states(saved):
    """Put back the (item, value) pairs of switch_modifiers / set_up_evaluation (key blocks: mute; modifiers: show_viewport)."""
    for item, value in saved:
        if hasattr(item, "mute"):
            item.mute = value
        else:
            item.show_viewport = value


def set_up_evaluation(ob, rig):
    """Switch `ob` to 'Armature modifier is the last one, other shape keys silent'. Returns the undo list."""
    saved = switch_modifiers(ob, armature_modifier(ob, rig))
    if ob.data.shape_keys:
        for kb in ob.data.shape_keys.key_blocks[1:]:
            saved.append((kb, kb.mute))
            kb.mute = True
    return saved


def write_key(ob, name, coords):
    """Put `coords` into the shape key `name` (made when missing, otherwise replaced), relative to Basis."""
    if ob.data.shape_keys is None:
        ob.shape_key_add(name="Basis", from_mix=False)
    keys = ob.data.shape_keys
    kb = keys.key_blocks.get(name)
    if kb is None:
        kb = ob.shape_key_add(name=name, from_mix=False)
        kb.value = 0.0   # the API starts new keys at 1, which would apply the pose twice
    kb.data.foreach_set("co", coords)
    kb.relative_key = keys.reference_key


def bake(context, rig, meshes, poses):
    """Write one shape key per (name, frame) in `poses` on every mesh that can take it. Pose, frame, modifier and shape
    key states are put back afterwards. Returns a Result."""
    scene, result = context.scene, Result()
    frame, subframe = scene.frame_current, scene.frame_subframe
    kept_pose, kept_position = read_pose(rig), rig.data.pose_position
    saved = [pair for ob in meshes for pair in set_up_evaluation(ob, rig)]
    baked = {}   # mesh -> {key name: coords}
    try:
        rig.data.pose_position = 'POSE'
        for key_name, key_frame in poses:
            if key_frame is not None:
                scene.frame_set(key_frame)
            context.view_layer.update()
            depsgraph = context.evaluated_depsgraph_get()
            for ob in meshes:
                if ob in baked and baked[ob] is None:
                    continue
                coords = deformed_coords(ob, depsgraph)
                if coords is None:
                    baked[ob] = None
                    result.skipped.append((ob.name, "vertex count changes"))
                else:
                    baked.setdefault(ob, {})[key_name] = coords
    finally:
        restore_states(saved)
        rig.data.pose_position = kept_position
        scene.frame_set(frame, subframe=subframe)
        apply_pose(rig, kept_pose)
    for ob, keys in baked.items():
        for key_name, coords in (keys or {}).items():
            write_key(ob, key_name, coords)
            result.keys += 1
    return result


# ---------------------------------------------------------------------------
# Operator and card
# ---------------------------------------------------------------------------

class DIGITOOLS_OT_pose_shape_keys(PoseOperator):
    """Bake the pose (or every pose marker) into shape keys on the meshes this rig deforms"""
    bl_idname = "digits_assorted_tools.pose_shape_keys"
    bl_label = "Poses to Shape Keys"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        if not target_meshes(context, target_rig(context)):
            cls.poll_message_set("Select meshes deformed by the rig, or the rig itself")
            return False
        return True

    def execute(self, context):
        wm, rig = context.window_manager, target_rig(context)
        poses = pose_list(wm.digit_pskeys_source, wm.digit_pskeys_name, rig)
        if not poses:
            self.report({'WARNING'}, "The rig's active action has no pose markers")
            return {'CANCELLED'}
        result = bake(context, rig, target_meshes(context, rig), poses)
        self.report({'WARNING'} if result.skipped else {'INFO'}, result.summary())
        return {'FINISHED'}


def draw_card(layout, context):
    wm = context.window_manager
    rig = target_rig(context)
    meshes = target_meshes(context, rig) if rig else []
    if rig is None:
        status(layout, "Select a rig or a mesh it deforms")
    else:
        status(layout, f"{len(meshes)} mesh{'' if len(meshes) == 1 else 'es'} deformed by {rig.name}", icon='MESH_DATA')
    action_row(layout).operator(DIGITOOLS_OT_pose_shape_keys.bl_idname, icon='SHAPEKEY_DATA')
    body = section(layout, "pskeys_source", "Poses")
    if body:
        prop_group(body, wm, ["digit_pskeys_source"] + (["digit_pskeys_name"] if wm.digit_pskeys_source == 'CURRENT' else []))
        if wm.digit_pskeys_source == 'MARKERS' and rig:
            count = len(marker_poses(rig))
            hints(body, [f"{count} pose markers in the active action" if count else "The active action has no pose markers"], context)
    hints(layout, ["Only the modifiers up to the Armature modifier go into the keys"], context)


classes = (DIGITOOLS_OT_pose_shape_keys,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.digit_pskeys_source = EnumProperty(name="From", items=SOURCES, description="Which poses become shape keys")
    wm.digit_pskeys_name = StringProperty(name="Name", default="Pose", description="Name of the shape key for the current pose")


def unregister():
    del bpy.types.WindowManager.digit_pskeys_name
    del bpy.types.WindowManager.digit_pskeys_source
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
