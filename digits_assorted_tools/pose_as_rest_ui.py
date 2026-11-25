# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply Pose as Rest card (Digit's Tools > Character Rigs) and its operator. The work is in pose_as_rest.py.
Risk 3 (Risky) like the Oops Debugger's: it rewrites the meshes, so it asks first and is one undo step."""
import bpy

from . import scene_checks as sc  # generated copy
from .pose_as_rest import apply_pose_as_rest, plan_groups
from .save_pose import target_rig
from .ui_cards import action_row, hints, status  # generated copy

RISK = 3
LOSS = ("It rewrites the vertices and every shape key of the meshes this rig deforms and makes the pose the rest pose. "
        "Constraints, drivers and animation on the rig then act on the new rest. Ctrl+Z undoes it all.")


class DIGITOOLS_OT_pose_as_rest(bpy.types.Operator):
    """Make the current pose the rest pose and move the meshes it deforms along (shape keys kept, Armature modifiers untouched). Risky: Ctrl+Z undoes it"""
    bl_idname = "digits_assorted_tools.pose_as_rest"
    bl_label = "Apply Pose as Rest"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = target_rig(context)
        if rig is None or rig.type != 'ARMATURE':
            cls.poll_message_set("Select a local armature, or a mesh deformed by one")
        elif context.mode not in {'OBJECT', 'POSE'}:
            cls.poll_message_set("Leave Edit Mode first")
        elif not rig.visible_get():
            cls.poll_message_set("The rig is hidden")
        else:
            return True
        return False

    def invoke(self, context, event):
        groups, _skipped = plan_groups(target_rig(context), context.view_layer)
        message = f"{len(groups)} meshes will move with the pose. {LOSS} Risky: {sc.RISKS[RISK][1]}"
        return context.window_manager.invoke_confirm(self, event, title="Apply pose as rest?", confirm_text="Apply Pose as Rest",
                                                     message=message, icon='WARNING')

    def execute(self, context):
        result = apply_pose_as_rest(context, target_rig(context))
        self.report({'WARNING'} if result.skipped or result.warnings else {'INFO'}, result.summary())
        for warning in result.warnings:
            print("Apply Pose as Rest:", warning)
        return {'FINISHED'}


def draw_card(layout, context):
    rig = target_rig(context)
    if rig is None:
        status(layout, "Select a rig or a mesh it deforms")
    else:
        groups, skipped = plan_groups(rig, context.view_layer)
        status(layout, f"{len(groups)} meshes deformed by {rig.name}" + (f", {len(skipped)} cannot be done" if skipped else ""),
               icon='MESH_DATA')
    row = action_row(layout)
    row.alert = True
    row.operator(DIGITOOLS_OT_pose_as_rest.bl_idname, icon='ERROR')
    hints(layout, [f"Risk {RISK} {sc.RISKS[RISK][0]}: asks first, one undo step",
                   "Armature modifiers stay as they are, shape keys are posed too",
                   "Part armatures: run it on each one"], context)


classes = (DIGITOOLS_OT_pose_as_rest,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
