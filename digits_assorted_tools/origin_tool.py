# SPDX-License-Identifier: GPL-3.0-or-later
"""Origin Tool card (Digit's Tools > Object): move an object's origin while the mesh stays where it is.

Edit Origin is Blender's own way: the Affect Only: Origins option plus the viewport's Move object gizmo. Turning it on
records the previous values on the scene; turning it off puts back exactly those. The snap buttons (Base, Center of
Box, Center of Mass, Match Parent, Selection) are one operator with a target; `origin_targets.py` finds the point,
`origin_move.py` moves the origin. One undo step per button. No handlers, timers or msgbus."""
import json
from collections import Counter

import bpy
from bpy.props import BoolProperty, EnumProperty

from . import origin_move, origin_targets
from .ui_cards import action_row, hints, prop_group, section, status, wrapped  # generated copy

EDIT_KEY = "digit_edit_origin"   # scene custom property: JSON {"affect_only": bool, "spaces": {space key: [move gizmo, gizmos]}}
CARD_SCAN_LIMIT = 50             # selected objects the card looks at for its notes
NOTE_LINES = 4
MODE_TEXT = {'OBJECT': "Select mesh objects first", 'EDIT_MESH': "Select something in Edit Mode first"}


# ---------------------------------------------------------------------------
# Edit Origin: Affect Only Origins + the Move gizmo, put back exactly on exit
# ---------------------------------------------------------------------------

def view3d_spaces():
    """[(key, 3D View space)] of every screen; the key is stable while the layout is."""
    return [(f"{screen.name}|{area_index}|{space_index}", space)
            for screen in bpy.data.screens for area_index, area in enumerate(screen.areas) if area.type == 'VIEW_3D'
            for space_index, space in enumerate(area.spaces) if space.type == 'VIEW_3D']


def is_editing(scene):
    return EDIT_KEY in scene


def start_editing(scene):
    """Remember the user's values, then turn on Affect Only Origins and Parents (children stay put) and the Move gizmo
    in every 3D View."""
    tool_settings = scene.tool_settings
    spaces = view3d_spaces()
    scene[EDIT_KEY] = json.dumps({"affect_only": tool_settings.use_transform_data_origin,
                                  "skip_children": tool_settings.use_transform_skip_children,
                                  "spaces": {key: [space.show_gizmo_object_translate, space.show_gizmo]
                                             for key, space in spaces}})
    tool_settings.use_transform_data_origin = True
    tool_settings.use_transform_skip_children = True
    for _key, space in spaces:
        space.show_gizmo, space.show_gizmo_object_translate = True, True


def stop_editing(scene):
    """Put back the values start_editing recorded (a 3D View that is gone is skipped)."""
    record = json.loads(scene[EDIT_KEY])
    scene.tool_settings.use_transform_data_origin = record["affect_only"]
    scene.tool_settings.use_transform_skip_children = record.get("skip_children", False)
    for key, space in view3d_spaces():
        if key in record["spaces"]:
            space.show_gizmo_object_translate, space.show_gizmo = record["spaces"][key]
    del scene[EDIT_KEY]


class DIGITOOLS_OT_edit_origin(bpy.types.Operator):
    """Edit Origin on: drag the Move gizmo and only the origin moves, the mesh stays. Off: your settings come back"""
    bl_idname = "digits_assorted_tools.edit_origin"
    bl_label = "Edit Origin"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if is_editing(scene):
            stop_editing(scene)
            self.report({'INFO'}, "Edit Origin off: your settings are back")
        else:
            start_editing(scene)
            self.report({'INFO'}, "Edit Origin on: drag the Move gizmo to move the origin")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Snap buttons
# ---------------------------------------------------------------------------

def plan_moves(objects, target_id, depsgraph):
    """([(object, world point)], Counter of skip reasons): all points are worked out before anything moves."""
    moves, skipped = [], Counter()
    for ob in objects:
        reason = origin_move.skip_reason(ob)
        point, reason = (None, reason) if reason else origin_targets.world_target(ob, target_id, depsgraph)
        if point is None:
            skipped[reason] += 1
        else:
            moves.append((ob, point))
    return moves, skipped


def result_text(result, skipped):
    parts = [f"Origin moved on {result.moved} object{'s' if result.moved != 1 else ''}"]
    if result.followers:
        parts.append(f"{result.followers} linked duplicate{'s' if result.followers != 1 else ''} went along")
    if result.kept_axes:
        parts.append(f"kept the {'/'.join(sorted(result.kept_axes))} axis (Mirror)")
    skipped = skipped + result.skipped
    if skipped:
        parts.append("skipped " + ", ".join(f"{count} ({reason})" for reason, count in skipped.items()))
    return "; ".join(parts)


def move_in_edit_mode(context, moves, keep_mirror_axes):
    """Edit Mode keeps its own copy of the mesh: leave it, move, and go back in with the same objects."""
    edited = [ob for ob, _point in moves]
    bpy.ops.object.mode_set(mode='OBJECT')
    result = origin_move.move_origins(moves, keep_mirror_axes)
    for ob in edited:
        ob.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    return result


class DIGITOOLS_OT_set_origin(bpy.types.Operator):
    bl_idname = "digits_assorted_tools.set_origin"
    bl_label = "Set Origin"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(name="To", items=origin_targets.TARGETS, default='BASE')

    @classmethod
    def description(cls, context, properties):
        return next(tip for target_id, _label, tip in origin_targets.TARGETS if target_id == properties.target)

    @classmethod
    def poll(cls, context):
        return context.mode in MODE_TEXT

    def execute(self, context):
        in_edit_mode = context.mode == 'EDIT_MESH'
        if (self.target == 'SELECTION') != in_edit_mode:
            self.report({'ERROR'}, "Selection works in Edit Mode only; the other targets in Object Mode only")
            return {'CANCELLED'}
        objects = context.objects_in_mode_unique_data if in_edit_mode else context.selected_objects
        moves, skipped = plan_moves(list(objects), self.target, context.evaluated_depsgraph_get())
        keep_mirror_axes = context.scene.origin_tool_keep_mirror
        if not moves:
            self.report({'WARNING'}, "Nothing moved: " + ", ".join(f"{count} {reason}" for reason, count in skipped.items()) if skipped else MODE_TEXT[context.mode])
            return {'CANCELLED'}
        if in_edit_mode:
            result = move_in_edit_mode(context, moves, keep_mirror_axes)
        else:
            result = origin_move.move_origins(moves, keep_mirror_axes)
        self.report({'INFO'}, result_text(result, skipped))
        for warning in sorted(result.warnings)[:NOTE_LINES]:
            self.report({'WARNING'}, warning)
        return {'FINISHED'}


def snap_button(layout, target_id, text=None):
    label = text or next(label for found, label, _tip in origin_targets.TARGETS if found == target_id)
    layout.operator(DIGITOOLS_OT_set_origin.bl_idname, text=label, icon='OBJECT_ORIGIN').target = target_id


class DIGITOOLS_MT_set_origin(bpy.types.Menu):
    bl_idname = "DIGITOOLS_MT_set_origin"
    bl_label = "Origin Tool"

    def draw(self, context):
        self.layout.operator(DIGITOOLS_OT_edit_origin.bl_idname, icon='ORIENTATION_GLOBAL')
        self.layout.separator()
        for target_id in origin_targets.TARGET_IDS:
            if target_id != 'SELECTION':
                snap_button(self.layout, target_id)


def draw_origin_menu(self, context):
    """Object menu line: the Origin Tool submenu (F3 finds every button in it)."""
    self.layout.menu(DIGITOOLS_MT_set_origin.bl_idname, icon='OBJECT_ORIGIN')


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def card_notes(context, keep_mirror_axes):
    """Lines about the selected objects: where a Mirror keeps the origin, and modifiers that react to it."""
    notes = []
    for ob in context.selected_objects[:CARD_SCAN_LIMIT]:
        if ob.type != 'MESH':
            continue
        axes = origin_move.mirror_axes(ob)
        if axes and keep_mirror_axes:
            letters = "/".join(origin_move.AXIS_LETTERS[axis] for axis in sorted(axes))
            notes.append(f'"{ob.name}": Mirror keeps the origin on the {letters} axis')
        notes += origin_move.origin_warnings(ob)
    return notes


def draw_card(layout, context):
    scene = context.scene
    editing = is_editing(scene)
    status(layout, "Edit Origin is on" if editing else "Origin follows your clicks", 'ORIENTATION_GLOBAL' if editing else 'OBJECT_ORIGIN')
    action_row(layout).operator(DIGITOOLS_OT_edit_origin.bl_idname, text="Edit Origin", icon='ORIENTATION_GLOBAL', depress=editing)
    hints(layout, ["Drag the Move gizmo: only the origin moves, the mesh stays. Turning it off puts your settings back"
                   if editing else "Shows the Move gizmo and turns on Affect Only: Origins"], context)
    in_edit_mode = context.mode == 'EDIT_MESH'
    body = section(layout, "origintool_snap", "Snap Origin To", icon='SNAP_ON')
    if body:
        column = body.column(align=True)
        column.scale_y = 1.2
        for target_id in origin_targets.TARGET_IDS:
            row = column.row(align=True)
            row.enabled = (target_id == 'SELECTION') == in_edit_mode and context.mode in MODE_TEXT
            snap_button(row, target_id)
        hints(body, ["Selection is for Edit Mode, the others for Object Mode. Children and linked duplicates keep their look"],
              context)
    options = section(layout, "origintool_options", "Options", icon='PREFERENCES', default_closed=True)
    if options:
        prop_group(options, scene, [("origin_tool_keep_mirror", "Keep Mirror Look")])
        hints(options, ["A Mirror modifier without a mirror object works around the origin, so the origin only moves along "
                        "the axes it does not mirror. Off: it moves freely and the mirrored shape changes"], context)
    notes = card_notes(context, scene.origin_tool_keep_mirror)
    if notes:
        alert = layout.column()
        alert.alert = True
        for note in notes[:NOTE_LINES]:
            wrapped(alert, note, icon='ERROR', context=context)
        if len(notes) > NOTE_LINES:
            layout.label(text=f"... and {len(notes) - NOTE_LINES} more")


classes = (DIGITOOLS_OT_edit_origin, DIGITOOLS_OT_set_origin, DIGITOOLS_MT_set_origin)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.origin_tool_keep_mirror = BoolProperty(
        name="Keep Mirror Look", default=True,
        description="Move the origin only along the axes an origin-based Mirror modifier does not mirror, so the "
                    "mirrored shape keeps its look")


def unregister():
    del bpy.types.Scene.origin_tool_keep_mirror
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
