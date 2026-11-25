# SPDX-License-Identifier: GPL-3.0-or-later
"""Performance options that apply only while VR runs, and their file safety. Same pattern as modifier_state.py,
using the shared scene_record.py: every change is recorded (old value) in a custom property, so the restore puts
back EXACTLY what was there.
- Compositor off: the viewport compositor of the XR view AND of the desktop 3D Views (recorded on the window manager,
  which undo does not touch). The desktop 3D Views also take the headset's shading while VR runs.
- Raytracing off (scene.eevee.use_raytracing) + glass / refractive objects hidden with hide_set while it is off.
- Hide transparent materials: glass AND alpha / blended / transparent objects hidden (same detector, same record:
  an object both options want comes back once).
- Draw distance: the XR view's clip_end (and clip_start kept below it), recorded on the window manager.
- Lower shadow resolution (scene.eevee.shadow_resolution_scale, at most SHADOW_SCALE).
File safety: save_pre restores, save_post applies again; after a load a leftover record is restored (crash,
autosave); undo / redo during VR re-applies, after VR restores. Teardown restores (session.py)."""
import bpy
from bpy.app.handlers import persistent

from . import display_state, glass_detect, hand_state, settings, scene_record  # scene_record: generated copy
from .runtime import RUNTIME

SCENE_KEY = "digits_vr_perf_scene"     # Scene: record of eevee changes + hidden glass objects
WM_KEY = "digits_vr_perf_wm"           # Window manager: record of the compositor change
SHADOW_SCALE = 0.25
CLIP_START_SHARE = 0.1                 # clip_start is at most this share of the new clip_end
OPTIONS = ("compositor_off_in_vr", "raytracing_off_in_vr", "lower_shadows_in_vr", "hide_transparent_in_vr",
           "draw_distance", "show_hands", "hand_marker")
WINDOW_MANAGER_ONLY = ("draw_distance", "hand_marker")     # their change redoes only the window manager part


def apply_window_manager():
    """The window manager's VR changes: compositor, draw distance. Returns how many were made."""
    window_manager = bpy.context.window_manager
    changes = []
    if settings.get("compositor_off_in_vr"):
        changes.append((window_manager, "xr_session_settings.shading.use_compositor", 'DISABLED'))
    distance = settings.get("draw_distance")
    if distance > 0:
        xr_settings = window_manager.xr_session_settings
        changes += [(window_manager, "xr_session_settings.clip_end", distance),
                    (window_manager, "xr_session_settings.clip_start",
                     min(xr_settings.clip_start, distance * CLIP_START_SHARE))]
    changes += display_state.changes(window_manager)
    changes += hand_state.changes(window_manager)
    done = scene_record.set_values(window_manager, WM_KEY, changes, "window_managers")
    return done + scene_record.set_values(window_manager, WM_KEY, _desktop_changes(window_manager), "screens")


def _desktop_changes(window_manager):
    """The desktop 3D Views while VR runs, recorded with the rest:
    - the same shading as the headset: an undo made the headset match the desktop's (user's fix, 2026-11-25);
    - the viewport compositor off (with the option): Blender redraws them on the same thread as the headset, and a
      compositor on 'Always' made every select a quarter-second stall (headset, 2026-11-25)."""
    shading = window_manager.xr_session_settings.shading.type
    compositor_off = settings.get("compositor_off_in_vr")
    changes = []
    for window in window_manager.windows:
        screen = window.screen
        for index, area in enumerate(screen.areas):
            if area.type == 'VIEW_3D':
                path = f"areas[{index}].spaces[0].shading"
                changes.append((screen, path + ".type", shading))
                if compositor_off:
                    changes.append((screen, path + ".use_compositor", 'DISABLED'))
    return changes


def apply(scene):
    """Make the VR-only changes the settings ask for. Returns the number of changes made."""
    done = apply_window_manager()
    changes = []
    if settings.get("raytracing_off_in_vr"):
        changes.append((scene, "eevee.use_raytracing", False))
    if settings.get("lower_shadows_in_vr"):
        changes.append((scene, "eevee.shadow_resolution_scale", min(scene.eevee.shadow_resolution_scale, SHADOW_SCALE)))
    done += scene_record.set_values(scene, SCENE_KEY, changes, "scenes")
    hidden = hide_candidates(scene)
    if hidden:
        done += scene_record.hide_objects(scene, SCENE_KEY, hidden, scene, bpy.context.view_layer)
    return done


def hide_candidates(scene):
    """Objects to hide for VR: ONE detector, ONE list for both options (transparent includes glass)."""
    if settings.get("hide_transparent_in_vr"):
        return glass_detect.transparent_objects(scene)
    if settings.get("raytracing_off_in_vr"):
        return glass_detect.glass_objects(scene)
    return []


def restore_everywhere():
    """Put back every record in the file (teardown and repair). Returns how many values came back."""
    restored = sum(scene_record.restore(scene, SCENE_KEY) for scene in bpy.data.scenes if SCENE_KEY in scene)
    return restored + sum(scene_record.restore(wm, WM_KEY) for wm in bpy.data.window_managers if WM_KEY in wm)


BASE_POSE = ("base_pose_type", "base_pose_location", "base_pose_angle")


def reapply(scene):
    """Restore, then apply again. While VR runs, the viewer's base pose stays where it is now: restoring it to the scene
    camera (Blender's default) put you on the camera after every undo and flung you when it moved (2026-11-25)."""
    window_manager = bpy.context.window_manager
    keep = [(window_manager, "xr_session_settings." + name, scene_record._read(window_manager, "xr_session_settings." + name))
            for name in BASE_POSE] if RUNTIME.active else []
    restore_everywhere()
    apply(scene)
    if keep:
        scene_record.set_values(window_manager, WM_KEY, keep, "window_managers")


def hidden_names(scene):
    """Full names of the objects the Performance options hid for VR (glass, transparent)."""
    return {entry[2] for entry in scene_record.recorded(scene, SCENE_KEY) if entry[0] == scene_record.HIDE}


def hidden_count(scene):
    return sum(1 for entry in scene_record.recorded(scene, SCENE_KEY) if entry[0] == scene_record.HIDE)


def _on_option_changed(_value):
    if RUNTIME.active:
        reapply(bpy.context.scene)


def _on_draw_distance_changed(_value):
    """A slider drag: only the window manager part is redone (no object scan per step)."""
    if RUNTIME.active:
        window_manager = bpy.context.window_manager
        scene_record.restore(window_manager, WM_KEY)
        apply_window_manager()


@persistent
def on_save_pre(*_args):
    if RUNTIME.active:
        restore_everywhere()


@persistent
def on_save_post(*_args):
    if RUNTIME.active:
        apply(bpy.context.scene)


def after_load():
    """Called by session.py's load_post (before it resumes a running session)."""
    restored = restore_everywhere()
    if restored:
        print(f"digits_vr: {restored} performance settings left changed in VR were put back")


def after_undo():
    """Called by session.py's undo_post / redo_post."""
    if RUNTIME.active:
        reapply(bpy.context.scene)
    else:
        restore_everywhere()


HANDLERS = (("save_pre", on_save_pre), ("save_post", on_save_post))


def register():
    for name, function in HANDLERS:
        getattr(bpy.app.handlers, name).append(function)
    for name in OPTIONS:
        settings.LISTENERS.setdefault(name, []).append(
            _on_draw_distance_changed if name in WINDOW_MANAGER_ONLY else _on_option_changed)


def unregister():
    for name in OPTIONS:
        settings.LISTENERS.get(name, []).remove(_on_draw_distance_changed if name in WINDOW_MANAGER_ONLY else _on_option_changed)
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function in handlers:
            handlers.remove(function)
