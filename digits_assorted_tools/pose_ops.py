"""Reset Pose and Rig Switch operators (the former Reset Pose & Rig Switches add-on).

One click puts bones back to rest AND resets their custom properties (IK/FK switches, foot roll, follow sliders...) to
the defaults set on them; IK/FK snap and parent switch for limbs upgraded by Upgrade Limbs and for the Full Character
Rig's tail and ears (each control's "Limb" property says which bones are involved, so nothing here is rig specific). The buttons are drawn by the shared
rig_switches_ui.py (Selected card); this module has the operators (bl_idnames unchanged, keymaps keep working) and
the Pose > Transform menu entry.
"""

import bpy
from mathutils import Matrix

from .rig_parts import limb_data, reset_property  # generated copy
from .rig_switches_ui import draw_reset_buttons  # generated copy


def is_selected(pose_bone):
    # Blender 5 keeps selection on the pose bone, older versions on the bone
    sel = getattr(pose_bone, "select", None)
    return pose_bone.bone.select if sel is None else sel


def set_selected(pose_bone, value):
    if hasattr(pose_bone, "select"):
        pose_bone.select = value
    else:
        pose_bone.bone.select = value


def use_armature(context, name):
    """The armature a rig panel button works on (a part armature's page: the ponytail), made the active, only selected
    object in Pose Mode when it isn't already. Already in Pose Mode with others (Select Rig): it only becomes the
    active one. Returns it, or None when it can't be (not in the view layer, hidden)."""
    ob = bpy.data.objects.get(name) if name else context.object
    if ob is None or ob.type != 'ARMATURE':
        return None
    if context.mode == 'POSE' and ob.mode == 'POSE':
        context.view_layer.objects.active = ob
        return ob
    if ob.name not in context.view_layer.objects or not ob.visible_get():
        return None
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='POSE')
    return ob


def armature_prop():
    return bpy.props.StringProperty(name="Armature", description="The armature of the control (empty: the active one)",
                                    options={'SKIP_SAVE'})


def reset_transforms(pose_bone):
    pose_bone.location = (0.0, 0.0, 0.0)
    pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    pose_bone.rotation_euler = (0.0, 0.0, 0.0)
    pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    pose_bone.scale = (1.0, 1.0, 1.0)


def reset_properties(pose_bone):
    """Set every custom property that has a default back to it. Returns how many changed."""
    return sum(reset_property(pose_bone, key) for key in list(pose_bone.keys()))


def armatures_in_pose_mode(context):
    objs = getattr(context, "objects_in_mode", None) or [context.object]
    return [o for o in objs if o and o.type == 'ARMATURE']


class POSE_OT_reset_pose_and_properties(bpy.types.Operator):
    """Reset bone transforms and bone custom properties to their defaults"""
    bl_idname = "pose.reset_pose_and_properties"
    bl_label = "Reset Pose and Properties"
    bl_options = {'REGISTER', 'UNDO'}

    only_selected: bpy.props.BoolProperty(
        name="Only Selected",
        description="Reset only the selected bones (otherwise every bone of the rig)",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE'

    def execute(self, context):
        bones = props = 0
        for arm in armatures_in_pose_mode(context):
            for pose_bone in arm.pose.bones:
                if self.only_selected and not is_selected(pose_bone):
                    continue
                reset_transforms(pose_bone)
                props += reset_properties(pose_bone)
                bones += 1
        self.report({'INFO'}, f"Reset {bones} bones, {props} properties")
        return {'FINISHED'}


def draw_menu(self, context):
    self.layout.separator()
    draw_reset_buttons(self.layout.row(align=True))


POLE_TURN_DONE = 0.002  # radians
FK_PASSES = 3  # some forearms copy a share of the hand, so a bone can shift when a later one is placed
TIP_CLOSE_ENOUGH = 0.0002  # metres


def place_bone(context, pose_bone, wanted):
    """Give a pose bone this final matrix, also when its own constraints bend the result."""
    asked = wanted
    for _ in range(4):
        pose_bone.matrix = asked
        context.view_layer.update()
        asked = asked @ pose_bone.matrix.inverted() @ wanted


def set_switch(context, control, key, value):
    control[key] = value
    context.object.update_tag()
    context.view_layer.update()


def snap_to_fk(context, control, limb):
    """FK bones take the pose the IK gives them, then the limb switches to FK."""
    bones = context.object.pose.bones
    pose = {name: bones[name].matrix.copy() for name in limb["fk"]}
    set_switch(context, control, "IK_FK", 0.0)
    for _ in range(FK_PASSES):
        for name in limb["fk"]:
            place_bone(context, bones[name], pose[name])


def turn_about(point, axis, angle):
    return Matrix.Translation(point) @ Matrix.Rotation(angle, 4, axis) @ Matrix.Translation(-point)


def align_pole(context, limb, fk_joint):
    """Turn the pole around the limb's root-to-tip line until the IK bends where the FK bent."""
    bones = context.object.pose.bones
    root, joint, pole = bones[limb["chain"][0]], bones[limb["chain"][1]], bones[limb["pole"]]
    for _ in range(6):
        axis = (bones[limb["chain"][-1]].tail - root.head).normalized()
        now = joint.head - root.head
        wanted = fk_joint - root.head
        now, wanted = now - axis * now.dot(axis), wanted - axis * wanted.dot(axis)
        if now.length < 1e-4 or wanted.length < 1e-4:  # straight limb: no bend to match
            return
        angle = now.angle(wanted)
        if now.cross(wanted).dot(axis) < 0:
            angle = -angle
        if abs(angle) < POLE_TURN_DONE:
            return
        place_bone(context, pole, turn_about(root.head, axis, angle) @ pole.matrix)


def is_part_chain(limb):
    """A part chain's Limb data (tail, ears, ponytail: `part` set, or no pole): it snaps with snap_chain_to_ik."""
    return bool(limb.get("part")) or not limb.get("pole")


def snap_to_ik(context, control, limb):
    """The IK control, hock and pole go where the FK pose is, then the limb switches to IK. A part chain snaps with
    snap_chain_to_ik."""
    if is_part_chain(limb):
        snap_chain_to_ik(context, control, limb)
        return
    bones = context.object.pose.bones
    pose = {name: bones[name].matrix.copy() for name in limb["fk"]}
    tip, target = bones[limb["tip"]], bones[limb["target"]]
    set_switch(context, control, "IK_FK", 1.0)
    tip_to_control = tip.matrix.inverted() @ control.matrix
    place_bone(context, control, pose[limb["tip"]] @ tip_to_control)
    if limb["hock"]:
        hock, hock_target = bones[limb["hock"]], bones[limb["hock_target"]]
        hock_at = pose[limb["fk"][len(limb["chain"])]].translation
        place_bone(context, hock, Matrix.Translation(hock_at - hock_target.matrix.translation) @ hock.matrix)
    align_pole(context, limb, pose[limb["chain"][1]].translation)
    settle_tip(context, control, tip, pose[limb["tip"]].translation)


def pose_before_constraints(context, pose):
    """Give each bone of `pose` ({name: armature-space matrix}, parents first) the own transform that puts it there
    before its constraints: the parent at its `pose` matrix (or where it is now), the bone's rest offset, its basis."""
    bones = context.object.pose.bones
    moved = False
    for name, wanted in pose.items():
        bone = bones[name].bone
        if moved and bone.parent and bone.parent.name not in pose:
            context.view_layer.update()                  # a parent outside `pose` (Head's aim bone) follows the bones set so far
            moved = False
        if bone.parent is None:
            parent_now, offset = Matrix(), bone.matrix_local
        else:
            parent_now = pose[bone.parent.name] if bone.parent.name in pose else bones[bone.parent.name].matrix
            offset = bone.parent.matrix_local.inverted() @ bone.matrix_local
        bones[name].matrix_basis = offset.inverted() @ parent_now.inverted() @ wanted
        moved = True
    context.object.update_tag()
    context.view_layer.update()


def head_turn_basis(bones, control, turned, pose, fk_parent):
    """The world rotation that gives `control` the local turn (its rotation on its own rest) which, added after the
    turned bone's parent pose (the IK Rotation is a LOCAL, mix AFTER copy), leaves that bone at its FK pose."""
    bone = bones[turned]
    parent = bone.parent.name
    base = pose.get(parent, bones[parent].matrix) if fk_parent else bones[parent].matrix   # FK pose first, then the IK's own
    rest = bone.parent.bone.matrix_local.inverted() @ bone.bone.matrix_local
    after_parent = (base @ rest).to_3x3().normalized()
    local = after_parent.inverted() @ pose[turned].to_3x3().normalized()       # the turn the control must add
    control_rest = (control.parent.matrix @ control.parent.bone.matrix_local.inverted() @ control.bone.matrix_local
                    if control.parent else control.bone.matrix_local)
    return (control_rest.to_3x3().normalized() @ local).to_4x4()


def snap_chain_to_ik(context, control, limb):
    """A part chain to IK: the tip control goes to the chain's tip, and the chain bones (the IK's start shape) take the
    pose they showed in FK, so the IK finds its target already reached and nothing jumps (Droop: the FK bend fades out in IK and the
    control's MCH parent turns instead; the control is placed by world matrix, so it works under that turn). A chain
    with a pole (the ponytail) then turns the pole until the chain bends where the FK bent. A control that also turns a
    bone (`turns`: the neck IK's IK-Head adds its local turn to Head by Copy Rotation) takes that bone's FK turn too."""
    bones = context.object.pose.bones
    pose = {name: bones[name].matrix.copy() for name in limb["fk"]}
    tip_end = bones[limb["tip"]].tail.copy()
    set_switch(context, control, "IK_FK", 1.0)
    turned = limb.get("turns")
    if turned:
        pose_before_constraints(context, pose)
        # the control carries the whole turn (IK Rotation adds it to the bone's own pose): clear the bone's own, place the
        # control, then place again on the parent's real IK pose (the IK picks the neck's twist)
        bones[turned].matrix_basis = Matrix()
        for step in range(3):
            place_bone(context, control, Matrix.Translation(tip_end) @ head_turn_basis(bones, control, turned, pose, step == 0))
    else:
        place_bone(context, control, Matrix.Translation(tip_end - control.head) @ control.matrix)
        pose_before_constraints(context, pose)
    if limb.get("pole") and len(limb["chain"]) > 1:
        align_pole(context, limb, pose[limb["chain"][1]].translation)


def settle_tip(context, control, tip, wanted):
    """An IK with locked axes can end a little off its target: nudge the control while that helps.
    At full extension it doesn't, and the control must not drift away."""
    best, best_miss = control.matrix.copy(), (wanted - tip.matrix.translation).length
    for _ in range(4):
        if best_miss < TIP_CLOSE_ENOUGH:
            return
        place_bone(context, control, Matrix.Translation(wanted - tip.matrix.translation) @ best)
        miss = (wanted - tip.matrix.translation).length
        if miss >= best_miss:
            place_bone(context, control, best)
            return
        best, best_miss = control.matrix.copy(), miss


def rotation_path(pose_bone):
    return {'QUATERNION': "rotation_quaternion", 'AXIS_ANGLE': "rotation_axis_angle"}.get(pose_bone.rotation_mode,
                                                                                          "rotation_euler")


def key_bones(pose_bones, names):
    """Keyframe location, rotation and scale of the named bones on the current frame. Returns how many were keyed."""
    keyed = 0
    for name in names:
        pose_bone = pose_bones.get(name)
        if pose_bone is None:
            continue
        for path in ("location", rotation_path(pose_bone), "scale"):
            pose_bone.keyframe_insert(path, group=name)
        keyed += 1
    return keyed


def moved_by_snap(control, limb, to_fk):
    """The bones a snap places: the FK chain going to FK; the IK control, hock and pole going to IK (a part chain's
    control and its bones)."""
    if to_fk:
        return list(limb["fk"])
    if is_part_chain(limb):
        return [control.name] + list(limb["fk"]) + ([limb["pole"]] if limb.get("pole") else [])
    return [name for name in (control.name, limb.get("hock"), limb["pole"]) if name]


class POSE_OT_limb_snap(bpy.types.Operator):
    """Switch this limb to IK or FK, keeping the pose (no jump). With auto-key on, the moved bones and the switch are
    keyed"""
    bl_idname = "pose.limb_snap"
    bl_label = "Snap Limb IK/FK"
    bl_options = {'REGISTER', 'UNDO'}

    bone: bpy.props.StringProperty(name="Control")
    to_fk: bpy.props.BoolProperty(name="To FK", description="Switch to FK (otherwise to IK)")
    arm: armature_prop()

    @classmethod
    def poll(cls, context):
        return context.mode in {'POSE', 'OBJECT'}

    @classmethod
    def description(cls, context, props):
        return ("Switch to FK, keeping the pose" if props.to_fk else "Switch to IK, keeping the pose") + \
            ". With auto-key on, the moved bones and the switch are keyed"

    def execute(self, context):
        ob = use_armature(context, self.arm)
        if ob is None or self.bone not in ob.pose.bones:
            self.report({'WARNING'}, f"Can't pose {self.arm or 'the rig'}: is it hidden?")
            return {'CANCELLED'}
        control = ob.pose.bones[self.bone]
        limb = limb_data(control)
        target = 0.0 if self.to_fk else 1.0
        mode = "FK" if self.to_fk else "IK"
        if control["IK_FK"] == target:
            self.report({'INFO'}, f"Already in {mode}")
            return {'CANCELLED'}
        (snap_to_fk if self.to_fk else snap_to_ik)(context, control, limb)
        if not context.scene.tool_settings.use_keyframe_insert_auto:
            self.report({'INFO'}, f"Snapped to {mode}, no keys (auto-key is off)")
            return {'FINISHED'}
        keyed = key_bones(context.object.pose.bones, moved_by_snap(control, limb, self.to_fk))
        control.keyframe_insert('["IK_FK"]', group=control.name)
        self.report({'INFO'}, f"Snapped to {mode}, keyed {keyed} bones and the switch")
        return {'FINISHED'}


def switch_parent(context, control, index):
    """Make the IK control follow parent `index` of its Limb data, keeping it where it is."""
    where = control.matrix.copy()
    set_switch(context, control, "IK_Parent", index)
    place_bone(context, control, where)


class POSE_OT_limb_parent(bpy.types.Operator):
    """Make this control follow another bone, keeping it where it is"""
    bl_idname = "pose.limb_parent"
    bl_label = "Switch Limb Parent"
    bl_options = {'REGISTER', 'UNDO'}

    bone: bpy.props.StringProperty(name="Control")
    parent: bpy.props.IntProperty(name="Parent", min=0)
    arm: armature_prop()

    @classmethod
    def poll(cls, context):
        return context.mode in {'POSE', 'OBJECT'}

    def execute(self, context):
        ob = use_armature(context, self.arm)
        if ob is None or self.bone not in ob.pose.bones:
            return {'CANCELLED'}
        switch_parent(context, ob.pose.bones[self.bone], self.parent)
        return {'FINISHED'}


classes = (POSE_OT_reset_pose_and_properties, POSE_OT_limb_snap, POSE_OT_limb_parent)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_pose_transform.append(draw_menu)


def unregister():
    bpy.types.VIEW3D_MT_pose_transform.remove(draw_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
