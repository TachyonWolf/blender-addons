"""Operators of the rig panel (drawn by the shared rig_switches_ui.py in the Character Rig box): pick a part page
(with Follow Selection on, also select its main control),
show bone collection groups (Shift-click adds or removes), reset switches (one row or a whole part), copy a limb's
switches to the other side, select a part armature's controls and give its tip IK an IK/FK switch. Snap, parent switch
and Reset Pose stay in pose_ops.py."""
import json

import bpy

from . import bone_collections as bc, part_chains as pc, rig_names as rn  # generated copies
from .pose_ops import armature_prop, set_selected, snap_to_fk, snap_to_ik, switch_parent, use_armature
from .rig_parts import (FULL_BODY, OTHER, Entry, forget_cache, limb_data, owner_of, part_switches, reset_property,  # generated copy
                        rig_armatures, rig_map, shown_keys)
from .rig_switches_ui import FOLLOW_PROP, store_part  # generated copy

NO_PICK = (FULL_BODY, "Face", OTHER)   # pages whose pick leaves the selection alone (no one main control)
SWITCH_ENDS = 0.001                    # IK_FK this close to 0 or 1 counts as all FK / all IK


def rig_object(name):
    ob = bpy.data.objects.get(name)
    return ob if ob is not None and ob.type == 'ARMATURE' else None


def limb_pick(control):
    """[bones to select], active first, of a limb page: the IK control in IK, the root-most FK bone in FK, both while
    the switch is partway."""
    fk_root = next(iter(limb_data(control).get("fk") or ()), None)
    if not fk_root or fk_root not in control.id_data.pose.bones:
        return [control.name]
    value = control["IK_FK"]
    if value >= 1 - SWITCH_ENDS:
        return [control.name]
    return [fk_root] if value <= SWITCH_ENDS else [control.name, fk_root]


def depth(bone):
    return len(bone.parent_recursive)


def part_pick(info, name):
    """(armature name, [bones to select], active first) for a part pick with Follow Selection on, or None (Full Body,
    Face, Other, nothing to pick). A limb page: limb_pick; any other page: its root-most control you can see."""
    part = info.parts.get(name)
    if part is None or name in NO_PICK:
        return None
    if part.limb:
        control = owner_of(Entry(part.limb[0], part.limb[1], "IK_FK"))
        return (part.limb[0], limb_pick(control)) if control is not None and "IK_FK" in control else None
    shown = []
    for arm_name, bone_name in (key for key, page in info.bone_parts.items() if page == name):
        ob = rig_object(arm_name)
        bone = ob.data.bones.get(bone_name) if ob is not None else None
        if bone is not None and is_control_shown(bone):
            shown.append((arm_name != part.arm, depth(bone), bone_name, arm_name))
    if not shown:
        return None
    _other_arm, _depth, bone_name, arm_name = min(shown)    # the page's own armature first, then the root-most
    return arm_name, [bone_name]


def select_bones(context, arm_name, names):
    """Make `arm_name` the active armature in Pose Mode (pose_ops.use_armature) and select only `names`, the first
    active. Bones of other armatures in Pose Mode are deselected too. False when it can't be posed."""
    ob = use_armature(context, arm_name)
    if ob is None:
        return False
    for other in context.view_layer.objects:
        if other.type == 'ARMATURE' and other.mode == 'POSE':
            for pb in other.pose.bones:
                set_selected(pb, other == ob and pb.name in names)
    ob.data.bones.active = ob.data.bones[names[0]]
    return True


class POSE_OT_rig_show_part(bpy.types.Operator):
    """Show this part's switches. With Follow Selection on, also select its main control (IK control in IK, the first
    FK bone in FK), and selecting another bone shows that bone's part again"""
    bl_idname = "pose.rig_show_part"
    bl_label = "Show Part"
    bl_options = {'UNDO', 'INTERNAL'}

    rig: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    part: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        rig = rig_object(self.rig)
        follow = getattr(context.window_manager, FOLLOW_PROP, True)
        if rig is not None and follow and context.mode in {'POSE', 'OBJECT'}:
            pick = part_pick(rig_map(rig), self.part)
            if pick is not None:
                select_bones(context, *pick)
        store_part(context, self.part)     # after the pick: the stored bone is the new active one, so no loop
        return {'FINISHED'}


class POSE_OT_rig_show_bones(bpy.types.Operator):
    """Click: show only this group of bones. Shift-click: add or remove it"""
    bl_idname = "pose.rig_show_bones"
    bl_label = "Show Bones"
    bl_options = {'REGISTER', 'UNDO'}

    rig: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    group: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    extend: bpy.props.BoolProperty(name="Extend", description="Add or remove the group instead of showing only it",
                                   options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        rig = rig_object(self.rig)
        if rig is None:
            return {'CANCELLED'}
        names = {self.group}
        if self.extend:
            names = bc.shown_groups(rig) ^ {self.group}
        for arm in rig_armatures(rig):    # part armatures (ears, tails...) use the same collection names
            bc.show_groups(arm, names)
        return {'FINISHED'}


def reset_entries(entries):
    """Put each switch back to its default. Returns how many changed."""
    changed = 0
    for entry in entries:
        owner = owner_of(entry)
        if owner is not None and reset_property(owner, entry.key):
            changed += 1
            owner.id_data.update_tag()
    return changed


class POSE_OT_reset_switches(bpy.types.Operator):
    """Put these switches back to their defaults (one row, or every switch of the part)"""
    bl_idname = "pose.reset_switches"
    bl_label = "Reset Switches"
    bl_options = {'REGISTER', 'UNDO'}

    entries: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})   # JSON [[armature, bone, key], ...]
    rig: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    part: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, props):
        return "Put this part's switches back to their defaults (the pose stays)" if props.part else \
            "Put this row back to its default"

    def execute(self, context):
        if self.entries:
            entries = [Entry(*item) for item in json.loads(self.entries)]
        else:
            rig = rig_object(self.rig)
            info = rig_map(rig) if rig is not None else None
            if info is None or self.part not in info.parts:
                return {'CANCELLED'}
            entries = part_switches(info, self.part)
        changed = reset_entries(entries)
        context.view_layer.update()
        self.report({'INFO'}, f"Reset {changed} switch{'' if changed == 1 else 'es'}")
        return {'FINISHED'}


class POSE_OT_copy_limb_side(bpy.types.Operator):
    """Give the other side's limb the same switches: sliders and Follows, IK or FK (snapped, no jump)"""
    bl_idname = "pose.copy_limb_side"
    bl_label = "Copy To Other Side"
    bl_options = {'REGISTER', 'UNDO'}

    bone: bpy.props.StringProperty(name="Control")
    arm: armature_prop()

    @classmethod
    def poll(cls, context):
        return context.mode in {'POSE', 'OBJECT'}

    def execute(self, context):
        ob = use_armature(context, self.arm)
        if ob is None:
            return {'CANCELLED'}
        bones = ob.pose.bones
        control, twin = bones.get(self.bone), bones.get(rn.flip(self.bone))
        if control is None or twin is None or "Limb" not in twin:
            self.report({'WARNING'}, f"No other side for {self.bone}")
            return {'CANCELLED'}
        for key in shown_keys(control):
            if key != "IK_FK" and key in twin:
                twin[key] = control[key]
        if "IK_Parent" in control and "IK_Parent" in twin and twin["IK_Parent"] != control["IK_Parent"]:
            switch_parent(context, twin, control["IK_Parent"])
        to_fk = control["IK_FK"] < 0.5
        if (twin["IK_FK"] < 0.5) != to_fk:
            (snap_to_fk if to_fk else snap_to_ik)(context, twin, limb_data(twin))
        context.object.update_tag()
        context.view_layer.update()
        return {'FINISHED'}


def is_control_shown(bone):
    """A bone you can see and pose: not hidden, in a visible collection that isn't Deform / Mechanism (FK ponytail
    bones count while their FK collection shows)."""
    return not bone.hide and any(c.is_visible_effectively and not bc.is_rigging(c) for c in bone.collections)


class POSE_OT_rig_select_part(bpy.types.Operator):
    """Select this part's controls you can see (its armature becomes the active object, in Pose Mode)"""
    bl_idname = "pose.rig_select_part"
    bl_label = "Select Controls"
    bl_options = {'REGISTER', 'UNDO'}

    arm: armature_prop()

    @classmethod
    def poll(cls, context):
        return context.mode in {'POSE', 'OBJECT'}

    def execute(self, context):
        ob = use_armature(context, self.arm)
        if ob is None:
            self.report({'WARNING'}, f"Can't pose {self.arm}: is it hidden?")
            return {'CANCELLED'}
        shown = [pb for pb in ob.pose.bones if is_control_shown(pb.bone)]
        for pb in ob.pose.bones:
            set_selected(pb, pb in shown)
        if shown:
            ob.data.bones.active = shown[0].bone
        self.report({'INFO'}, f"Selected {len(shown)} controls of {ob.name}")
        return {'FINISHED'}


class POSE_OT_add_ik_fk_switch(bpy.types.Operator):
    """Give this IK an IK/FK switch like the limbs': IK_FK on the IK control (1 = IK, the pose stays) drives the IK, and
    IK | FK buttons snap without a jump. In FK you pose the chain's own bones"""
    bl_idname = "pose.add_ik_fk_switch"
    bl_label = "Add IK/FK Switch"
    bl_options = {'REGISTER', 'UNDO'}

    arm: armature_prop()
    bone: bpy.props.StringProperty(name="IK Control", options={'SKIP_SAVE'})
    part: bpy.props.StringProperty(name="Part", description="The rig panel page of the switch", options={'SKIP_SAVE'})

    def execute(self, context):
        ob = rig_object(self.arm)
        if ob is None or self.bone not in ob.pose.bones:
            return {'CANCELLED'}
        try:
            names = pc.add_tip_switch(ob, self.bone, self.part or rn.parse(self.bone).part)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        forget_cache()
        ob.update_tag()
        context.view_layer.update()
        self.report({'INFO'}, f"IK/FK switch on {self.bone} ({len(names)} bones)")
        return {'FINISHED'}


classes = (POSE_OT_rig_show_part, POSE_OT_rig_show_bones, POSE_OT_reset_switches, POSE_OT_copy_limb_side,
           POSE_OT_rig_select_part, POSE_OT_add_ik_fk_switch)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
