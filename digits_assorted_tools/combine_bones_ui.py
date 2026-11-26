# SPDX-License-Identifier: GPL-3.0-or-later
"""Combine Bones card (Digit's Tools > Character Rigs): select bones in Pose or Edit Mode, the active one is the main bone; the
button removes the others and adds their weights to it. All logic is in combine_bones (generated copy of
Addons/shared_addon/combine_bones.py)."""
import bpy

from . import combine_bones as cb  # generated copy
from .selected_ui import selected_names
from .ui_cards import action_row, friendly_name, hints, poll_message, status  # generated copy


def plan(context):
    """(armature, main bone, bones to remove, why not): the active armature's selected bones, the active one is the main."""
    arm = context.active_object
    if arm is None or arm.type != 'ARMATURE' or context.mode not in ('POSE', 'EDIT_ARMATURE'):
        return None, None, [], "Select an armature and go to Pose or Edit Mode"
    if arm.library or arm.data.library:
        return arm, None, [], "The armature is linked: make it local first"
    names = selected_names(context, arm)
    main = context.active_bone.name if context.active_bone and context.active_bone.name in names else None
    if main is None:
        return arm, None, [], "Click the main bone last: the active bone must be selected"
    removed = [n for n in names if n != main]
    if not removed:
        return arm, main, [], "Select at least one more bone to remove"
    return arm, main, removed, ""


class DIGITOOLS_OT_combine_bones(bpy.types.Operator):
    """Remove the selected bones except the active one (the main bone). Their vertex group weights are added to the main
    bone's, their children, constraints, drivers and bone-parented objects go to it"""
    bl_idname = "digits_assorted_tools.combine_bones"
    bl_label = "Combine Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, plan(context)[3])

    def execute(self, context):
        arm, main, removed, _why = plan(context)
        lines = cb.report_lines(cb.combine_bones(arm, main, removed))
        self.report({'INFO'}, ". ".join(lines))
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    _arm, main, removed, why = plan(context)
    status(body, f"Into {friendly_name(main)} · {len(removed)} to remove" if main else "Select bones to combine",
           icon='BONE_DATA')
    row = action_row(body)
    row.operator(DIGITOOLS_OT_combine_bones.bl_idname, icon='GROUP_BONE')
    hints(body, [why], context)


classes = (DIGITOOLS_OT_combine_bones,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
