# SPDX-License-Identifier: GPL-3.0-or-later
"""Bones In Front While Posing (Digit's Tools > Scene): armatures get "In Front" only while you work on them: in Pose
or Edit mode, or as the rig of a mesh you are weight painting. Everywhere else it is off, so bones stop drawing over
the character.

Blender has no event for a mode change, so this is the one tool with a timer (kept from the former add-on). It exists
only while the preference "Bones In Front While Posing" is on: turning it off removes the timer, and it does nothing
else (no handlers, no msgbus). Disabling the add-on removes the timer too.

TODO: when Blender gets an event (or a reliable msgbus notice) for mode changes, replace the timer with it [user].
"""

import bpy

from .prefs import addon_prefs
from .ui_cards import hints, status

CHECK_INTERVAL = 0.2  # seconds


def is_enabled():
    prefs = addon_prefs()
    return bool(prefs and prefs.bones_in_front)


def armatures_being_worked_on():
    """Armatures in Pose/Edit mode, plus the rigs of a mesh in Weight Paint."""
    working = set()
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE' and obj.mode in {'POSE', 'EDIT'}:
            working.add(obj)
        elif obj.type == 'MESH' and obj.mode == 'WEIGHT_PAINT':
            for mod in obj.modifiers:
                if mod.type == 'ARMATURE' and mod.object:
                    working.add(mod.object)
    return working


def update_in_front():
    """Timer function: set In Front on every armature to match the work being done. Returns the next interval."""
    working = armatures_being_worked_on()
    for obj in bpy.data.objects:
        if obj.type != 'ARMATURE' or obj.library:
            continue
        want = obj in working
        if obj.show_in_front != want:
            obj.show_in_front = want
    return CHECK_INTERVAL


def apply_setting():
    """Start the timer when the preference is on, stop it when off (called on register and when the preference changes)."""
    running = bpy.app.timers.is_registered(update_in_front)
    if is_enabled() and not running:
        bpy.app.timers.register(update_in_front, first_interval=CHECK_INTERVAL, persistent=True)
    elif not is_enabled() and running:
        stop_timer()


def draw_card(layout, context):
    on = is_enabled()
    status(layout, "On: In Front follows your mode" if on else "Off", icon='CHECKMARK' if on else 'X')
    prefs = addon_prefs(context)
    if prefs:
        layout.prop(prefs, "bones_in_front", text="Bones In Front While Posing")
    hints(layout, ["Armatures show in front only in Pose / Edit mode, or as the rig of a mesh in Weight Paint",
                   "While on, one timer checks modes every 0.2 s"], context)


class DIGITOOLS_OT_toggle_bones_in_front(bpy.types.Operator):
    """Turn "Bones In Front While Posing" on or off (the same preference as the Bones In Front card)"""
    bl_idname = "digits_assorted_tools.toggle_bones_in_front"
    bl_label = "Toggle Bones In Front"

    @classmethod
    def poll(cls, context):
        return addon_prefs(context) is not None

    def execute(self, context):
        prefs = addon_prefs(context)
        prefs.bones_in_front = not prefs.bones_in_front
        self.report({'INFO'}, "Bones In Front While Posing: " + ("on" if prefs.bones_in_front else "off"))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(DIGITOOLS_OT_toggle_bones_in_front)
    apply_setting()


def stop_timer():
    if bpy.app.timers.is_registered(update_in_front):
        bpy.app.timers.unregister(update_in_front)


def unregister():
    stop_timer()   # a persistent timer outlives the add-on otherwise, calling code that is no longer loaded
    bpy.utils.unregister_class(DIGITOOLS_OT_toggle_bones_in_front)
    if bpy.app.timers.is_registered(update_in_front):
        bpy.app.timers.unregister(update_in_front)
