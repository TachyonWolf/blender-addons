# SPDX-License-Identifier: GPL-3.0-or-later
"""Rename Bones card (Digit's Tools > Rig): the map from rig_rename, its count and clashes, one button. Logic: rig_rename."""
import bpy

from . import rig_rename as rr  # generated copy
from .face_rig_ui import character
from .ui_cards import action_row, section, status  # generated copy

MAX_LINES = 8   # clashes and samples shown on the card
cache = {}


class DIGITOOLS_OT_rename_bones(bpy.types.Operator):
    """Rename this rig's bones to the standard (docs/BONE_NAMES.md). Weights, constraints, drivers, actions, pose assets,
    the Limb data and tool settings follow; bones in a clash keep their names"""
    bl_idname = "digits_assorted_tools.rename_bones"
    bl_label = "Rename Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character(context) is not None and context.mode in ('OBJECT', 'POSE')

    def execute(self, context):
        arm = character(context)
        table, _ = rr.work_out_map(arm)
        lines = rr.report_lines(rr.rename(arm, table))
        cache.clear()
        self.report({'INFO'}, lines[0])
        return {'FINISHED'}


def planned(arm):
    """The map, kept until the rig's bones change (the card asks every redraw)."""
    key = (arm.name, tuple(sorted(arm.data.bones.keys())))
    if key not in cache:
        cache.clear()
        cache[key] = rr.work_out_map(arm)
    return cache[key]


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    arm = character(context)
    if arm is None:
        status(body, "Select the character (or its rig)")
        return
    table, clashes = planned(arm)
    status(body, f"{len(table)} of {len(arm.data.bones)} to rename · {len(clashes)} clashes",
           icon='CHECKMARK' if not table and not clashes else 'ARMATURE_DATA')
    row = action_row(body)
    row.enabled = bool(table)
    row.operator(DIGITOOLS_OT_rename_bones.bl_idname, icon='SORTALPHA')
    if clashes:
        sec = section(body, "digitools_rename_clashes", "Clashes", icon='ERROR')
        if sec:
            for new, olds in list(clashes.items())[:MAX_LINES]:
                sec.label(text=f"{new}: {', '.join(olds)}", icon='ERROR')
    if table:
        sec = section(body, "digitools_rename_preview", "Preview", icon='VIEWZOOM')
        if sec:
            col = sec.column(align=True)
            col.scale_y = 0.8
            for old, new in list(table.items())[:MAX_LINES]:
                col.label(text=f"{old} > {new}")


classes = (DIGITOOLS_OT_rename_bones,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
