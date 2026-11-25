# SPDX-License-Identifier: GPL-3.0-or-later
"""Drivers (Digit's Tools > Character Rigs): lists the drivers of the selected rig (and, optionally, its meshes'
shape keys and modifiers) grouped per bone / owner, in plain words, with errors in red, a Select Bone button and a
mute switch. The reading is in driver_scan (generated copy of Addons/shared_addon/driver_scan.py).
Nothing runs in the background: the scan runs only while this card is open, is cached, and has a Rescan button."""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import driver_scan as ds
from . import scene_checks as sc
from .ui_cards import hints, prop_group, shorten, status, sub_heading, toggles  # generated copy

MAX_ROWS = 40          # drivers drawn at once; a rig can have hundreds (narrow the search to see the rest)
CACHE = sc.ScanCache()


class DRIVERS_OT_rescan(bpy.types.Operator):
    """Read the drivers again"""
    bl_idname = "driver_tool.rescan"
    bl_label = "Rescan"

    def execute(self, context):
        CACHE.clear()
        return {'FINISHED'}


class DRIVERS_OT_toggle_mute(bpy.types.Operator):
    """Switch this driver off (or on again). Muted drivers stay in the file"""
    bl_idname = "driver_tool.toggle_mute"
    bl_label = "Mute Driver"
    bl_options = {'REGISTER', 'UNDO'}

    id_kind: StringProperty(options={'HIDDEN'})
    id_name: StringProperty(options={'HIDDEN'})
    data_path: StringProperty(options={'HIDDEN'})
    index: IntProperty(options={'HIDDEN'})

    def execute(self, context):
        info = ds.DriverInfo(self.id_kind, self.id_name, self.data_path, self.index, "", "", "", "", False, "")
        fc = ds.find_fcurve(info)
        if fc is None:
            self.report({'WARNING'}, "Driver not found")
            return {'CANCELLED'}
        ds.set_muted(info, not fc.mute)
        CACHE.clear()
        return {'FINISHED'}


class DRIVERS_OT_select_bone(bpy.types.Operator):
    """Select the bone this driver moves"""
    bl_idname = "driver_tool.select_bone"
    bl_label = "Select Bone"
    bl_options = {'REGISTER', 'UNDO'}

    rig: StringProperty(options={'HIDDEN'})
    bone: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig)
        return {'FINISHED'} if rig is not None and sc.select_bone(rig, self.bone) else {'CANCELLED'}


def scan(context, rig):
    wm = context.window_manager
    with_meshes = wm.drivers_with_meshes
    meshes = sc.rig_meshes(rig, context.scene.objects) if with_meshes else []
    return CACHE.get((rig.name, with_meshes), lambda: ds.scan(rig, meshes))


def draw_driver(col, rig, info):
    row = col.row(align=True)
    label = row.row()
    label.alert = info.problem
    label.active = not info.muted
    label.label(text=shorten(info.title, 28))
    if info.bone:
        op = row.operator(DRIVERS_OT_select_bone.bl_idname, text="", icon='BONE_DATA')
        op.rig, op.bone = rig.name, info.bone
    op = row.operator(DRIVERS_OT_toggle_mute.bl_idname, text="",
                      icon='CHECKBOX_DEHLT' if info.muted else 'CHECKBOX_HLT')
    op.id_kind, op.id_name, op.data_path, op.index = info.id_kind, info.id_name, info.data_path, info.index
    detail = col.column()
    detail.active = False
    detail.label(text=shorten(("Muted · " if info.muted else "") + info.what))
    if info.error:
        problem = col.column()
        problem.alert = True
        problem.label(text=shorten(info.error), icon='ERROR')


def draw_card(layout, context):
    rig = sc.find_rig(context)
    if rig is None:
        status(layout, "Select a rig (or one of its meshes)", icon='ARMATURE_DATA')
        return
    wm = context.window_manager
    infos = scan(context, rig)
    errors = sum(1 for info in infos if info.problem)
    head = layout.row(align=True)
    head.label(text=f"{len(infos)} drivers · {errors} with errors", icon='DRIVER')
    head.operator(DRIVERS_OT_rescan.bl_idname, text="", icon='FILE_REFRESH')
    if not infos:
        hints(layout, ["This rig has no drivers"], context)
    prop_group(layout, wm, [("drivers_filter", "Search")])
    toggles(layout, wm, [("drivers_only_problems", "Only Problems"), ("drivers_with_meshes", "Include Meshes")],
            columns=1)
    shown = [info for info in infos if ds.matches(info, wm.drivers_filter, wm.drivers_only_problems)]
    drawn = 0
    for group, rows in ds.group_by_owner(shown).items():
        if drawn >= MAX_ROWS:
            break
        col = sub_heading(layout, group)
        for info in rows[:MAX_ROWS - drawn]:
            draw_driver(col, rig, info)
            drawn += 1
    if len(shown) > drawn:
        hints(layout, [f"Showing {drawn} of {len(shown)}: search to narrow it down"], context)
    elif infos and not shown:
        hints(layout, ["No driver matches"], context)


classes = (DRIVERS_OT_rescan, DRIVERS_OT_toggle_mute, DRIVERS_OT_select_bone)


def register():
    wm = bpy.types.WindowManager
    wm.drivers_filter = StringProperty(name="Search", description="Only drivers whose words contain this")
    wm.drivers_only_problems = BoolProperty(name="Only Problems", description="Only drivers that have errors")
    wm.drivers_with_meshes = BoolProperty(name="Include Meshes", default=True,
                                          description="Also list the drivers on the rig's meshes (shape keys, modifiers)")
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for name in ("filter", "only_problems", "with_meshes"):
        delattr(bpy.types.WindowManager, f"drivers_{name}")
