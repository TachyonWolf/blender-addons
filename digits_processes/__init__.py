# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's Processes: chains the user's existing tools into multi-step jobs. Sidebar tab Processes (one tab for the
add-on, like Modifiers and Render Presets), one panel: a dropdown picks the process (the shared tool_picker.py, the
same widget as Digit's Assorted Tools' Tools panel) and the chosen process's card is drawn under it. It uses Digit's
Assorted Tools' code from the installed add-on (assorted_tools.py); a process whose tools are missing says so on its
card instead of failing. No handlers, timers or msgbus.

Adding a process = one line in PROCESSES below (category, label, icon, its ui module with draw_card(layout,
context), register(), unregister()). Processes: Make Object Texture Data Screenshot (texture_screenshot/), Bake to Game Asset (bake_game_asset/).
Shared parts: temp_data.py (remove what a run made), ui_cards.py and tool_picker.py (generated copies of shared_addon/)."""
import bpy
from bpy.props import EnumProperty

from . import prefs
from .bake_game_asset import ui as bake_game_asset_ui
from .texture_screenshot import ui as texture_screenshot_ui
from .tool_picker import ToolPicker, enum_items, tool_id  # generated copy

# One line per process: (category, label, icon, ui module). The dropdown lists categories as headings, processes under them.
PROCESSES = (("Texture", "Make Object Texture Data Screenshot", 'IMAGE_DATA', texture_screenshot_ui),
             ("Export", "Bake to Game Asset", 'EXPORT', bake_game_asset_ui))
CATEGORY_ICONS = {"Texture": 'TEXTURE', "Export": 'EXPORT'}


def process_entries():
    return [(category, label) for category, label, _icon, _ui in PROCESSES]


PICKER = ToolPicker(
    operator_idname="digit_processes.pick_process", menu_idname="DIGITPROCESSES_MT_processes", menu_label="Processes",
    property_name="digit_process", entries=process_entries,
    icon=lambda label: next(icon for _c, name, icon, _u in PROCESSES if name == label),
    category_icons=CATEGORY_ICONS, operator_doc="Show this process in the Processes panel")
PROCESS_ITEMS = enum_items(process_entries())   # kept at module level: Blender reads the list lazily


def draw_process(layout, context, chosen):
    """Draw the card of the chosen process."""
    for _category, label, _icon, process_ui in PROCESSES:
        if tool_id(label) == chosen:
            process_ui.draw_card(layout, context)


class DIGITPROCESSES_PT_panel(bpy.types.Panel):
    """The Processes panel: the process dropdown on top, the chosen process's card under it."""
    bl_label = "Processes"
    bl_idname = "DIGITPROCESSES_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Processes"

    def draw(self, context):
        chosen = context.window_manager.digit_process
        PICKER.draw_dropdown(self.layout, chosen)
        draw_process(self.layout, context, chosen)


CLASSES = (*PICKER.classes, DIGITPROCESSES_PT_panel)


def register():
    bpy.utils.register_class(prefs.DigitProcessesPreferences)
    bpy.types.WindowManager.digit_process = EnumProperty(
        name="Process", items=PROCESS_ITEMS, default=tool_id(PROCESSES[0][1]),
        description="Which process the panel shows")
    for _category, _label, _icon, process_ui in PROCESSES:
        process_ui.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for _category, _label, _icon, process_ui in reversed(PROCESSES):
        process_ui.unregister()
    del bpy.types.WindowManager.digit_process
    bpy.utils.unregister_class(prefs.DigitProcessesPreferences)
