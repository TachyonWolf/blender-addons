# SPDX-License-Identifier: GPL-3.0-or-later
"""Save Pose card (Digit's Tools > Character Rigs): quick named pose snapshots stored on the armature object (a JSON custom
property, so they save with the file; no Action or asset library). A pose stores per bone NAME: location, rotation
(with its rotation mode), scale and the bone's custom properties. Applying matches bones by name and skips the missing
ones, so a pose also fits another character on the standard bone names (docs/BONE_NAMES.md); Copy Poses From takes
the poses of another armature in the file."""
import json

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty
from mathutils import Euler, Quaternion

from .bone_chain import rig_for_chain, selected_bones  # generated copy
from .ui_cards import action_row, friendly_name, hints, prop_group, section, shorten, status  # generated copy

POSES_KEY = "digit_saved_poses"  # armature object custom property: JSON {pose name: {bone name: bone data}}


# ---------------------------------------------------------------------------
# Reading and writing poses
# ---------------------------------------------------------------------------

def load_poses(ob):
    return json.loads(ob.get(POSES_KEY, "{}"))


def store_poses(ob, poses):
    ob[POSES_KEY] = json.dumps(poses)


def unique_name(name, taken):
    """name, or 'name 2', 'name 3'... when it is taken."""
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{name} {n}"
    return candidate


def rotation_values(pb):
    """The rotation as stored in the bone's current rotation mode."""
    if pb.rotation_mode == 'QUATERNION':
        return list(pb.rotation_quaternion)
    if pb.rotation_mode == 'AXIS_ANGLE':
        return list(pb.rotation_axis_angle)
    return list(pb.rotation_euler)


def as_quaternion(mode, values):
    if mode == 'QUATERNION':
        return Quaternion(values)
    if mode == 'AXIS_ANGLE':
        return Quaternion(values[1:], values[0])
    return Euler(values, mode).to_quaternion()


def set_rotation(pb, mode, values):
    """Set the rotation; stored in another rotation mode than the bone uses: converted to the bone's own mode."""
    if mode == pb.rotation_mode:
        target = {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(mode, "rotation_euler")
        setattr(pb, target, values)
        return
    quat = as_quaternion(mode, values)
    if pb.rotation_mode == 'QUATERNION':
        pb.rotation_quaternion = quat
    elif pb.rotation_mode == 'AXIS_ANGLE':
        axis, angle = quat.to_axis_angle()
        pb.rotation_axis_angle = (angle, *axis)
    else:
        pb.rotation_euler = quat.to_euler(pb.rotation_mode)


def custom_properties(pb):
    """The bone's plain custom properties (numbers, text, number arrays) as JSON friendly values."""
    values = {}
    for key in pb.keys():
        value = pb[key]
        if hasattr(value, "to_list"):
            value = value.to_list()
        if isinstance(value, (bool, int, float, str, list)):
            values[key] = value
    return values


def set_custom_property(pb, key, value):
    """Set an existing custom property (arrays element by element, so its settings survive)."""
    current = pb[key]
    if isinstance(value, list) and hasattr(current, "__len__") and not isinstance(current, str) and len(current) == len(value):
        for i, v in enumerate(value):
            current[i] = v
    elif not isinstance(value, list):
        pb[key] = value


def read_pose(rig, names=None):
    """{bone name: data} for the rig's pose bones (only `names` when given)."""
    pose = {}
    for pb in rig.pose.bones:
        if names is None or pb.name in names:
            pose[pb.name] = {"mode": pb.rotation_mode, "loc": list(pb.location), "rot": rotation_values(pb),
                             "scale": list(pb.scale), "props": custom_properties(pb)}
    return pose


def apply_pose(rig, pose, names=None):
    """Put the stored pose on the rig by bone name (only `names` when given). Returns (applied, skipped): skipped =
    stored bones the rig doesn't have."""
    applied = skipped = 0
    for name, data in pose.items():
        pb = rig.pose.bones.get(name)
        if pb is None:
            skipped += 1
        elif names is None or name in names:
            pb.location, pb.scale = data["loc"], data["scale"]
            set_rotation(pb, data["mode"], data["rot"])
            for key, value in data["props"].items():
                if key in pb.keys():
                    set_custom_property(pb, key, value)
            applied += 1
    return applied, skipped


def read_exact_pose(rig):
    """Every channel of every pose bone (all three rotation kinds, not only the one in use) and its custom properties:
    a snapshot `apply_exact_pose` puts back exactly, for tools that pose the rig for a moment (Rig Stress Pose Test)."""
    return {pb.name: {"mode": pb.rotation_mode, "loc": tuple(pb.location), "quat": tuple(pb.rotation_quaternion),
                      "euler": tuple(pb.rotation_euler), "axis_angle": tuple(pb.rotation_axis_angle),
                      "scale": tuple(pb.scale), "props": custom_properties(pb)} for pb in rig.pose.bones}


def apply_exact_pose(rig, pose):
    """Put a read_exact_pose snapshot back on the bones that still exist."""
    for name, data in pose.items():
        pb = rig.pose.bones.get(name)
        if pb is None:
            continue
        pb.rotation_mode = data["mode"]
        pb.location, pb.scale = data["loc"], data["scale"]
        pb.rotation_quaternion, pb.rotation_euler = data["quat"], data["euler"]
        pb.rotation_axis_angle = data["axis_angle"]
        for key, value in data["props"].items():
            if key in pb.keys():
                set_custom_property(pb, key, value)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def target_rig(context):
    rig = rig_for_chain(context)
    return rig if rig and not rig.library else None


def only_names(context, rig):
    """Names of the selected bones when 'Selected Bones Only' is on, else None (all bones)."""
    if context.window_manager.digit_pose_selected_only:
        return {b.name for b in selected_bones(rig)}
    return None


class PoseOperator(bpy.types.Operator):
    """Base of the Save Pose buttons: needs an armature (the active one, or the one the active mesh uses)."""
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if target_rig(context):
            return True
        cls.poll_message_set("Select a local armature, or a mesh deformed by one")
        return False


class DIGITOOLS_OT_pose_save(PoseOperator):
    """Save the current pose under the typed name"""
    bl_idname = "digits_assorted_tools.pose_save"
    bl_label = "Save Pose"

    def execute(self, context):
        wm, rig = context.window_manager, target_rig(context)
        poses = load_poses(rig)
        names = only_names(context, rig)
        if names is not None and not names:
            self.report({'WARNING'}, "No bones are selected")
            return {'CANCELLED'}
        name = unique_name(wm.digit_pose_name.strip() or "Pose", poses)
        poses[name] = read_pose(rig, names)
        store_poses(rig, poses)
        self.report({'INFO'}, f"Saved {name}: {len(poses[name])} bones")
        return {'FINISHED'}


class DIGITOOLS_OT_pose_apply(PoseOperator):
    """Put this pose on the armature (bones matched by name, missing ones skipped)"""
    bl_idname = "digits_assorted_tools.pose_apply"
    bl_label = "Apply Pose"

    name: StringProperty()

    def execute(self, context):
        rig = target_rig(context)
        pose = load_poses(rig).get(self.name)
        if pose is None:
            self.report({'WARNING'}, f"No pose called {self.name}")
            return {'CANCELLED'}
        applied, skipped = apply_pose(rig, pose, only_names(context, rig))
        self.report({'WARNING'} if skipped else {'INFO'},
                    f"Applied {self.name}: {applied} bones" + (f", {skipped} not found in this rig" if skipped else ""))
        return {'FINISHED'}


class DIGITOOLS_OT_pose_delete(PoseOperator):
    """Delete this saved pose"""
    bl_idname = "digits_assorted_tools.pose_delete"
    bl_label = "Delete Pose"

    name: StringProperty()

    def execute(self, context):
        rig = target_rig(context)
        poses = load_poses(rig)
        poses.pop(self.name, None)
        store_poses(rig, poses)
        return {'FINISHED'}


class DIGITOOLS_OT_pose_rename(PoseOperator):
    """Rename this saved pose"""
    bl_idname = "digits_assorted_tools.pose_rename"
    bl_label = "Rename Pose"

    name: StringProperty()
    new_name: StringProperty(name="New Name")

    def invoke(self, context, event):
        self.new_name = self.name
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        rig = target_rig(context)
        poses = load_poses(rig)
        new = self.new_name.strip()
        if self.name not in poses or not new or new == self.name:
            return {'CANCELLED'}
        new = unique_name(new, poses)
        store_poses(rig, {(new if key == self.name else key): value for key, value in poses.items()})  # keeps the order
        return {'FINISHED'}


class DIGITOOLS_OT_pose_copy_from(PoseOperator):
    """Copy all saved poses of the chosen armature to this one (same names get a number)"""
    bl_idname = "digits_assorted_tools.pose_copy_from"
    bl_label = "Copy Poses From"

    @classmethod
    def poll(cls, context):
        if not super().poll(context):
            return False
        source = context.window_manager.digit_pose_source
        if source is None or source == target_rig(context):
            cls.poll_message_set("Pick another armature to copy poses from")
            return False
        return True

    def execute(self, context):
        rig, source = target_rig(context), context.window_manager.digit_pose_source
        poses, copied = load_poses(rig), load_poses(source)
        for name, pose in copied.items():
            poses[unique_name(name, poses)] = pose
        store_poses(rig, poses)
        self.report({'INFO'}, f"Copied {len(copied)} poses from {source.name}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def draw_card(layout, context):
    wm = context.window_manager
    rig = target_rig(context)
    poses = load_poses(rig) if rig else {}
    status(layout, f"{friendly_name(rig.name)}: {len(poses)} saved poses" if rig else "Select an armature", icon='ARMATURE_DATA')
    body = section(layout, "savepose_save", "Save")
    if body:
        prop_group(body, wm, ["digit_pose_name", "digit_pose_selected_only"])
        action_row(body).operator(DIGITOOLS_OT_pose_save.bl_idname, icon='ADD')
    body = section(layout, "savepose_poses", "Saved Poses", right=f"{len(poses)} saved")
    if body:
        col = body.column(align=True)
        for name in poses:
            row = col.row(align=True)
            row.operator(DIGITOOLS_OT_pose_apply.bl_idname, text=shorten(name, 22), icon='POSE_HLT').name = name
            row.operator(DIGITOOLS_OT_pose_rename.bl_idname, text="", icon='GREASEPENCIL').name = name
            row.operator(DIGITOOLS_OT_pose_delete.bl_idname, text="", icon='X').name = name
        if not poses:
            hints(body, ["Nothing saved yet"], context)
        else:
            hints(body, ["Bones are matched by name: bones the rig lacks are skipped"], context)
    body = section(layout, "savepose_copy", "Copy From Another Rig", default_closed=True)
    if body:
        prop_group(body, wm, ["digit_pose_source"])
        body.operator(DIGITOOLS_OT_pose_copy_from.bl_idname, icon='COPYDOWN')


classes = (DIGITOOLS_OT_pose_save, DIGITOOLS_OT_pose_apply, DIGITOOLS_OT_pose_delete, DIGITOOLS_OT_pose_rename,
           DIGITOOLS_OT_pose_copy_from)


def is_armature(self, ob):
    return ob.type == 'ARMATURE'


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.digit_pose_name = StringProperty(name="Name", default="Pose", description="Name for the next saved pose")
    wm.digit_pose_selected_only = BoolProperty(
        name="Selected Bones Only", description="Save and apply only the selected bones")
    wm.digit_pose_source = PointerProperty(type=bpy.types.Object, poll=is_armature, name="From",
                                           description="The armature whose saved poses Copy Poses From takes")


def unregister():
    del bpy.types.WindowManager.digit_pose_source
    del bpy.types.WindowManager.digit_pose_selected_only
    del bpy.types.WindowManager.digit_pose_name
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
