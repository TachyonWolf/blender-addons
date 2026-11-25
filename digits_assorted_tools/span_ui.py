# SPDX-License-Identifier: GPL-3.0-or-later
"""Bendy Span Bone card (Digit's Tools > Character Rigs): Add Span Bone (two selected bones, active = end), Flip Span, Reset Spans (all).
All logic is in span_bones (generated copy of Addons/shared_addon/span_bones.py)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty

from . import span_bones as sb  # generated copy
from .selected_ui import selected_names
from .ui_cards import action_row, hints, prop_group, section, status  # generated copy


class DIGITOOLS_PG_span(bpy.types.PropertyGroup):
    segments: IntProperty(name="Segments", default=6, min=1, max=32, description="Bendy bone segments of new spans")
    handles: EnumProperty(name="Handles", items=sb.HANDLE_MODES, default='SMART',
                          description="B-bone start / end handle type of new spans (stored per span; Reset re-applies it)")
    mirror: BoolProperty(name="Mirror", default=True,
                         description="Also span the mirrored bones (Left/Right, .L/.R), and flip the mirrored span")
    disable_deform: BoolProperty(name="Turn Off Deform Under Spans", default=True,
                                 description="Turn Deform off on the two bones the span joins")
    transfer: BoolProperty(name="Move Weights to Span", default=True,
                           description="Their vertex group weights move onto the span(s) (nearest span segment)")
    per_bone: BoolProperty(name="Each Span's Handles", default=True,
                           description="Reset re-applies each span's own handle mode (off: the Handles setting, "
                                       "stored on every span)")


def armature(context):
    """The active armature, or the armature of the active mesh / face rig guide (face_rig_ui.character)."""
    from .face_rig_ui import character
    return character(context)


def add_problem(context):
    """Why Add Span Bone can't run now ('' = it can)."""
    if armature(context) is None:
        return "Select an armature"
    if context.mode not in ('POSE', 'EDIT_ARMATURE'):
        return "Add: Pose or Edit Mode"
    names = selected_names(context)
    if len(names) != 2:
        return f"Add: select 2 bones ({len(names)} selected)"
    if context.active_bone is None or context.active_bone.name not in names:
        return "Add: the active bone is the end"
    return ""


def flip_problem(context):
    arm = armature(context)
    if arm is None:
        return "Select an armature"
    if not any(sb.is_span(arm.data.bones[n]) for n in selected_names(context) if n in arm.data.bones):
        return "Flip: select a span bone (System > Deform)"
    return ""


def reset_problem(context):
    return "" if armature(context) is not None else "Select an armature"


class DIGITOOLS_OT_span_add(bpy.types.Operator):
    """Add a B-bone spanning from the selected bone to the active one (head on it, tail on the active bone,
    Stretch To the active bone), smooth with neighbouring spans"""
    bl_idname = "digits_assorted_tools.span_add"
    bl_label = "Add Span Bone"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = add_problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        arm = armature(context)
        s = context.scene.digit_span
        end = context.active_bone.name
        start = next(n for n in selected_names(context) if n != end)
        made = sb.make_span(arm, start, end, s.segments, s.mirror, s.handles, s.disable_deform, s.transfer)
        self.report({'INFO'}, "Made " + ", ".join(made))
        return {'FINISHED'}


class DIGITOOLS_OT_span_flip(bpy.types.Operator):
    """Swap the direction of the selected span bones (head <-> tail, renamed, weights follow)"""
    bl_idname = "digits_assorted_tools.span_flip"
    bl_label = "Flip Span"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = flip_problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        arm = armature(context)
        s = context.scene.digit_span
        todo = [n for n in selected_names(context) if sb.is_span(arm.data.bones[n])]
        done, flipped = set(), []
        for n in todo:
            if n in done:
                continue
            twin = None
            if s.mirror:
                b = arm.data.bones[n]
                pair = sb.mirror_pair(arm, b['span_from'], b['span_to'])
                twin = next((x.name for x in sb.spans(arm.data.bones) if pair
                             and (x.get('span_from'), x.get('span_to')) == pair), None)
            new = sb.flip_span(arm, n, mirror=s.mirror)
            done.update({n, twin} - {None})
            flipped += new
        self.report({'INFO'}, "Flipped " + ", ".join(flipped))
        return {'FINISHED'}


class DIGITOOLS_OT_span_reset(bpy.types.Operator):
    """Reset all stretch bones of the armature: every Stretch To gets its rest length (from the rest pose) and
    volume back; span bones are also realigned to their bones, with segments, handles, ease and pose reset"""
    bl_idname = "digits_assorted_tools.span_reset"
    bl_label = "Reset Spans"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = reset_problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        s = context.scene.digit_span
        n = sb.reset_spans(armature(context), handles=None if s.per_bone else s.handles)
        self.report({'INFO'}, f"Reset {n['spans']} span bone(s) and {n['stretch']} other Stretch To bone(s)")
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    arm = armature(context)
    s = context.scene.digit_span
    if arm is None:
        status(body, "Select an armature")
    else:
        status(body, f"{len(sb.spans(arm.data.bones))} span · {len(sb.stretch_bones(arm))} stretch bones",
               icon='ARMATURE_DATA')
    row = action_row(body)
    row.operator(DIGITOOLS_OT_span_add.bl_idname, text="Add Span", icon='BONE_DATA')
    row.operator(DIGITOOLS_OT_span_flip.bl_idname, text="Flip")   # three buttons with icons would be cut short
    row.operator(DIGITOOLS_OT_span_reset.bl_idname, text="Reset All")
    hints(body, [add_problem(context), flip_problem(context), reset_problem(context)], context)
    opts = section(body, "digitools_span_options", "Span", icon='BONE_DATA', right=f"{s.segments} segments")
    if opts:
        prop_group(opts, s, ["segments", "handles", "mirror"])
    spanned = section(body, "digitools_span_spanned", "Bones Under Spans", icon='GROUP_BONE')
    if spanned:
        col = prop_group(spanned, s, [("disable_deform", "Turn Off Deform")])
        sub = col.column()
        sub.enabled = s.disable_deform
        sub.use_property_split = False
        sub.prop(s, "transfer", text="Move Weights to Span")
    reset = section(body, "digitools_span_reset", "Reset", icon='FILE_REFRESH', default_closed=True)
    if reset:
        prop_group(reset, s, ["per_bone"])


classes = (DIGITOOLS_PG_span, DIGITOOLS_OT_span_add, DIGITOOLS_OT_span_flip, DIGITOOLS_OT_span_reset)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.digit_span = PointerProperty(type=DIGITOOLS_PG_span)


def unregister():
    del bpy.types.Scene.digit_span
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
