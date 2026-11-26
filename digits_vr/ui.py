# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar tab VR: Start / Stop VR, the settings (grab mode, touch distance, laser length, fine control, heavy modifiers off), movement (mode, turning, speeds, plane height), and a Show in VR toggle for each modifier of the active object. The desk in VR (M3) will show the same settings."""
import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import asset_scan, display_state, display_types, modifier_policy, modifier_state, scale_math, session, settings, user_scale
from .context_helper import view3d_override
from .hands import session_state
from .picking import find_object
from .runtime import RUNTIME
from .size_state import SIZE
from .ui_cards import action_row, card, choice_row, hints, prop_group, status  # generated copy


class DIGITSVR_OT_toggle_vr(bpy.types.Operator):
    """Start or stop the VR session (Material Preview in the headset; heavy modifiers off while it runs)"""
    bl_idname = "digits_vr.toggle_vr"
    bl_label = "Start / Stop VR"

    def execute(self, context):
        override = view3d_override(context)
        if override is None:
            self.report({'ERROR'}, "VR needs a 3D View open")
            return {'CANCELLED'}
        running = session_state(context) is not None
        if not running:
            session.configure_session(context)
        with context.temp_override(**override):
            result = bpy.ops.wm.xr_session_toggle()
        if running:
            session.teardown("stopped from the sidebar")
        return result


class DIGITSVR_OT_show_in_vr(bpy.types.Operator):
    """Show this modifier in VR, or turn it off while VR runs (heavy ones start off)"""
    bl_idname = "digits_vr.show_in_vr"
    bl_label = "Show in VR"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    object_name: StringProperty()
    modifier_uid: IntProperty()
    shown: BoolProperty()

    def execute(self, context):
        ob = find_object(context.blend_data, self.object_name)
        mod = next((item for item in ob.modifiers if item.persistent_uid == self.modifier_uid), None) if ob else None
        if mod is None:
            return {'CANCELLED'}
        modifier_state.set_shown(context.scene, ob, mod, self.shown)
        return {'FINISHED'}


class DIGITSVR_OT_set_size(bpy.types.Operator):
    """Change your size in VR (about your head). 1:1 is your normal size"""
    bl_idname = "digits_vr.set_size"
    bl_label = "Your Size"
    bl_options = {'INTERNAL'}

    size: bpy.props.FloatProperty(default=1.0)

    @classmethod
    def poll(cls, context):
        return session_state(context) is not None

    def execute(self, context):
        user_scale.preset(context, session_state(context), self.size)
        return {'FINISHED'}


class DIGITSVR_OT_reset_plane(bpy.types.Operator):
    """Put the floor plane back at height 0"""
    bl_idname = "digits_vr.reset_plane"
    bl_label = "Reset Plane Height"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        settings.put("plane_height", 0.0)
        return {'FINISHED'}


class DIGITSVR_OT_display(bpy.types.Operator):
    """Show or hide this kind of object (or the floor, annotations) in the VR view; your scene is not changed"""
    bl_idname = "digits_vr.display"
    bl_label = "Display in VR"
    bl_options = {'INTERNAL'}

    key: StringProperty()           # "" = Show all

    def execute(self, _context):
        if self.key:
            display_state.toggle(self.key)
        else:
            display_state.show_all()
        return {'FINISHED'}


def draw_display(layout, context):
    """Display card: one button per item, pressed in = shown in VR (same choices as the desk's Display tab)."""
    hidden = settings.get("display_hidden")
    for group in (display_types.MAIN, display_types.MORE):
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        for item in group:
            grid.operator(DIGITSVR_OT_display.bl_idname, text=item.label, depress=item.key not in hidden).key = item.key
    action_row(layout).operator(DIGITSVR_OT_display.bl_idname, text="Show all", icon='HIDE_OFF').key = ""
    hints(layout, ["Pressed = shown in VR. " + display_types.MESH_WARNING + ".", "VR view only: the scene is not changed."], context)


def draw_modifiers(layout, context):
    ob = context.active_object
    if ob is None or not len(ob.modifiers):
        hints(layout, ["Select an object with modifiers to choose which show in VR"], context)
        return
    scene = context.scene
    scene_choices = modifier_state.choices(scene)
    column = layout.column(align=True)
    for mod in ob.modifiers:
        shown = modifier_state.is_shown(scene, ob, mod, scene_choices)
        row = column.row(align=True)
        row.label(text=mod.name, icon='MODIFIER')
        button = row.operator(DIGITSVR_OT_show_in_vr.bl_idname, text="", depress=shown,
                              icon='HIDE_OFF' if shown else 'HIDE_ON')
        button.object_name, button.modifier_uid, button.shown = ob.name_full, mod.persistent_uid, not shown
    heavy_default = any(mod.type in modifier_policy.HEAVY_TYPES for mod in ob.modifiers)
    hints(layout, ["Heavy modifiers start off in VR" if heavy_default else "",
                   "" if context.window_manager.digits_vr.hide_heavy_modifiers else "Heavy Modifiers Off is unticked: all show"],
          context)


def draw_size(layout, context, vr_settings):
    """Your size: preset buttons (the active one pressed in; none between presets) and the gesture setting."""
    active = scale_math.active_preset(SIZE.factor)
    layout.label(text="Your size" + ("" if active else f" ({SIZE.factor:.2g}x)"))
    for start in (0, 5):
        row = layout.row(align=True)
        for size in scale_math.PRESETS[start:start + 5]:
            row.operator(DIGITSVR_OT_set_size.bl_idname, text=scale_math.preset_label(size),
                         depress=size == active).size = size
    layout.prop(vr_settings, "size_gesture")
    layout.prop(vr_settings, "size_invert")


def draw_panel(layout, context):
    running = session_state(context) is not None
    status(layout, "VR running" if running else "VR off", icon='CHECKMARK' if running else 'INFO')
    action_row(layout).operator(DIGITSVR_OT_toggle_vr.bl_idname, text="Stop VR" if running else "Start VR",
                                icon='CANCEL' if running else 'PLAY')
    if running and RUNTIME.problems:
        hints(layout, [f"{len(RUNTIME.problems)} bindings not available on this headset"], context)
    vr_settings = context.window_manager.digits_vr
    body = card(layout, "digits_vr_settings", "Settings")
    if body:
        choice_row(body, vr_settings, "grab_mode", vertical=True)
        choice_row(body, vr_settings, "grip_target", label="Grip acts on")
        choice_row(body, vr_settings, "finger_poke", label="Finger poke")
        prop_group(body, vr_settings, ["paused", "always_laser", "name_tag", "show_hands", "touch_distance", "laser_length", "push_speed", None, "fine_control", None, "belt_on", "belt_height", "belt_size", "belt_snap_back", None,
                                       "hide_heavy_modifiers"])
    body = card(layout, "digits_vr_move", "Movement")
    if body:
        draw_size(body, context, vr_settings)
        choice_row(body, vr_settings, "move_mode", vertical=True)
        if vr_settings.move_mode == 'TELEPORT':
            choice_row(body, vr_settings, "teleport_land", label="Land on")
        else:
            choice_row(body, vr_settings, "move_heading", label="Heading")
        if vr_settings.move_mode == 'FLY':
            choice_row(body, vr_settings, "fly_pitch", label="Pitch")
        choice_row(body, vr_settings, "turn_style", label="Turning")
        prop_group(body, vr_settings, ["walk_speed", "fly_speed",
                                       "snap_angle" if vr_settings.turn_style == 'SNAP' else "turn_speed",
                                       "plane_height", "eye_height", "geo_slide_speed", "geo_step_height"])
        body.operator(DIGITSVR_OT_reset_plane.bl_idname, icon='LOOP_BACK')
    body = card(layout, "digits_vr_display", "Display", default_closed=True)
    if body:
        draw_display(body, context)
    body = card(layout, "digits_vr_performance", "Performance in VR", default_closed=True)
    if body:
        prop_group(body, vr_settings, ["compositor_off_in_vr", "raytracing_off_in_vr", "hide_heavy_modifiers",
                                       "lower_shadows_in_vr", "hide_transparent_in_vr", "draw_distance"])
        hints(body, ["Raytracing off also hides glass / refractive objects while VR runs.",
                     "Draw distance 0 leaves Blender's value (XR far clip).",
                     "Also lower SteamVR's render resolution for Blender (per-app setting).",
                     "Stats: desk > Performance tab."], context)
    body = card(layout, "digits_vr_assets", "Assets in VR", default_closed=True,
                right="scanning" if asset_scan.scanning() else None)
    if body:
        action_row(body).operator(asset_scan.DIGITSVR_OT_scan_assets.bl_idname, icon='FILE_REFRESH')
        hints(body, ["Libraries come from Preferences > File Paths. The scan runs in a background Blender and is cached; "
                     "it starts with each VR session."], context)
    body = card(layout, "digits_vr_modifiers", "Modifiers in VR", default_closed=True)
    if body:
        draw_modifiers(body, context)


class DIGITSVR_PT_panel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VR"
    bl_label = "Digit's VR"

    def draw(self, context):
        draw_panel(self.layout, context)


classes = (DIGITSVR_OT_toggle_vr, DIGITSVR_OT_show_in_vr, DIGITSVR_OT_set_size, DIGITSVR_OT_reset_plane,
           DIGITSVR_OT_display, DIGITSVR_PT_panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
