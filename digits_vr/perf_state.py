# SPDX-License-Identifier: GPL-3.0-or-later
"""Performance options that apply only while VR runs, and their file safety. Same pattern as modifier_state.py,
using the shared scene_record.py: every change is recorded (old value) in a custom property, so the restore puts
back EXACTLY what was there.
- Compositor off: the viewport compositor of the XR view AND of the desktop 3D Views (recorded on the window manager,
  which undo does not touch). The desktop 3D Views also take the headset's shading while VR runs.
- EEVEE raytracing is ALWAYS off in VR (scene.eevee.use_raytracing, recorded and restored), with the viewport's
  temporal ghosting stopped (NO_GHOSTING) [user, 2026-11-27: Low and Scene did not work].
- Glass in VR (setting glass_in_vr: Hide / Solid / See-through, default See-through) [user, 2026-11-27]:
  Hide: glass / refractive objects are hidden with hide_set; on an object only partly glass (a character with a glass
  visor) only the glass faces are hidden (glass_faces.py: a viewport-only modifier, same record). Solid: glass shows,
  opaque. See-through: the glass slots show an alpha-blended copy of the material (glass_see_through.py, same
  record), on at most SEE_THROUGH_LIMIT objects; objects that can't take it, or are over the limit, are hidden as with
  Hide. Switching writes only what changes.
- Hide transparent materials: glass AND alpha / blended / transparent objects hidden (same detector, same record:
  an object both options want comes back once).
- Draw distance: the XR view's clip_end (and clip_start kept below it), recorded on the window manager.
- Lower shadow resolution (scene.eevee.shadow_resolution_scale, at most SHADOW_SCALE).
Never flap (2026-11-27: restore-then-apply on each draw distance step froze the computer): apply() changes only the
values whose target differs; a value no option wants changed any more gets its original back alone. Targets are
worked out from the recorded originals.
One flag in the file (FLAG_KEY on the window manager) says VR temp changes may exist: apply() sets it, the full
put-back (vr_changes.put_back_all, teardown) clears it; save and render check it (one property read when clear).
File safety: save_pre restores, save_post applies again; after a load a leftover record is restored (crash,
autosave); undo / redo during VR re-applies, after VR restores. Teardown restores (session.py)."""
import bpy
from bpy.app.handlers import persistent

from . import display_state, glass_detect, glass_faces, glass_see_through, hand_state, settings, scene_record  # scene_record: generated copy
from .runtime import RUNTIME
from .settings_store import GLASS_HIDE, GLASS_SEE_THROUGH

SCENE_KEY = "digits_vr_perf_scene"     # Scene: record of eevee changes + hidden glass objects / faces
WM_KEY = "digits_vr_perf_wm"           # Window manager: record of the compositor change
FLAG_KEY = "digits_vr_temp_changes"    # Window manager: True while VR temp changes may exist in this file
SHADOW_SCALE = 0.25
# The viewport's temporal reprojection (and jittered shadows) blend old frames; in a headset the view moves every
# frame, so moving objects leave trails ("ghosting", 2026-11-27). Viewport-only: renders keep them.
NO_GHOSTING = (("eevee.use_taa_reprojection", False), ("eevee.use_shadow_jitter_viewport", False))
CLIP_START_SHARE = 0.1                 # clip_start is at most this share of the new clip_end
# See-through on at most this many objects; the others are hidden as with Hide (scene order, so the same ones each
# time: no flapping). Each one is a Blended surface EEVEE draws in both eyes every frame [draft, 2026-11-27:
# See-through on a big scene crashed SteamVR's compositor].
SEE_THROUGH_LIMIT = 24
PLAN = {"over_limit": 0}               # see-through objects over the limit, hidden instead (last glass_plan)
OPTIONS = ("compositor_off_in_vr", "glass_in_vr", "lower_shadows_in_vr", "hide_transparent_in_vr",
           "draw_distance", "show_hands", "hand_marker")
WINDOW_MANAGER_ONLY = ("draw_distance", "hand_marker")     # their change redoes only the window manager part


# The VR viewer's start pose (session.py) shares the window manager record; the options never restore it.
BASE_POSE_PATHS = ("xr_session_settings.base_pose_type", "xr_session_settings.base_pose_location",
                   "xr_session_settings.base_pose_angle")


def apply_window_manager():
    """The window manager's VR changes (compositor, draw distance, display, hand marker, desktop views), as a diff.
    Returns how many values were written."""
    window_manager = bpy.context.window_manager
    changes = []
    if settings.get("compositor_off_in_vr"):
        changes.append((window_manager, "xr_session_settings.shading.use_compositor", 'DISABLED'))
    distance = settings.get("draw_distance")
    clip_start = scene_record.original_value(window_manager, WM_KEY, "window_managers", window_manager,
                                             "xr_session_settings.clip_start")
    changes += [(window_manager, "xr_session_settings.clip_end", distance),
                (window_manager, "xr_session_settings.clip_start", min(clip_start, distance * CLIP_START_SHARE))]
    changes += display_state.changes(window_manager)
    changes += hand_state.changes(window_manager)
    done = scene_record.sync_values(window_manager, WM_KEY, changes, "window_managers", keep=BASE_POSE_PATHS)
    return done + scene_record.sync_values(window_manager, WM_KEY, _desktop_changes(window_manager), "screens")


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


def mark_changes():
    """Set the file's flag: VR temp changes may exist (written only when it is not set yet)."""
    window_manager = bpy.data.window_managers[0] if bpy.data.window_managers else None
    if window_manager is not None and not window_manager.get(FLAG_KEY):
        window_manager[FLAG_KEY] = True


def changes_marked():
    return any(window_manager.get(FLAG_KEY) for window_manager in bpy.data.window_managers)


def clear_mark():
    for window_manager in bpy.data.window_managers:
        if FLAG_KEY in window_manager:
            del window_manager[FLAG_KEY]


def apply(scene):
    """Bring the VR-only changes in line with the settings, as a diff: only values whose target differs are written.
    Returns how many values (and objects) changed. Nothing while a render runs (vr_changes.py re-applies after it)."""
    if RUNTIME.rendering:
        return 0
    mark_changes()
    done = apply_window_manager()
    changes = raytracing_changes(scene)
    if settings.get("lower_shadows_in_vr"):
        changes.append((scene, "eevee.shadow_resolution_scale",
                        min(_scene_original(scene, "eevee.shadow_resolution_scale"), SHADOW_SCALE)))
    done += scene_record.sync_values(scene, SCENE_KEY, changes, "scenes")
    whole, parts, swaps = glass_plan(scene)
    done += scene_record.sync_hidden(scene, SCENE_KEY, whole, scene, bpy.context.view_layer)
    done += glass_faces.sync(scene, SCENE_KEY, parts)
    return done + glass_see_through.sync(scene, SCENE_KEY, swaps)


def _scene_original(scene, path):
    return scene_record.original_value(scene, SCENE_KEY, "scenes", scene, path)


def raytracing_changes(scene):
    """The (ID, path, value) changes that keep EEVEE raytracing off in VR, without the viewport's ghosting."""
    return [(scene, path, value) for path, value in NO_GHOSTING] + [(scene, "eevee.use_raytracing", False)]


def glass_plan(scene):
    """(objects to hide, [(object, slots)] whose glass faces to hide, [(object, slots)] to make see-through) for VR:
    ONE detector, ONE list (transparent includes glass; a see-through copy counts as its original). Hide transparent
    hides glass too, whatever Glass in VR says. Objects already hidden for VR stay on the list while they qualify (so
    they are not shown and hidden again). See-through goes on at most SEE_THROUGH_LIMIT objects (PLAN counts the rest)."""
    PLAN["over_limit"] = 0
    memo = glass_see_through.flags_memo(glass_detect.material_flags)
    choice = settings.get("glass_in_vr")
    if settings.get("hide_transparent_in_vr"):
        wanted = glass_detect.GLASS_OR_CLEAR
    elif choice in (GLASS_HIDE, GLASS_SEE_THROUGH):
        wanted = glass_detect.GLASS_ONLY
    else:
        return [], [], []
    whole, parts = glass_detect.split_objects(scene, wanted, memo, also_shown=hidden_names(scene))
    if wanted is glass_detect.GLASS_OR_CLEAR or choice == GLASS_HIDE:
        return whole, parts, []
    hide_whole, hide_parts, swaps = [], [], []
    over = 0
    for ob, slots, is_whole in [(ob, list(range(len(ob.material_slots))), True) for ob in whole] + [
            (ob, slots, False) for ob, slots in parts]:
        can_swap = _can_swap(ob, slots)
        if can_swap and len(swaps) < SEE_THROUGH_LIMIT:
            swaps.append((ob, slots))
            continue
        over += can_swap
        if is_whole:
            hide_whole.append(ob)
        else:
            hide_parts.append((ob, slots))
    PLAN["over_limit"] = over
    return hide_whole, hide_parts, swaps


def _can_swap(ob, slots):
    """See-through works for an editable object (local or a library override) whose glass slots all convert."""
    return ob.is_editable and all(glass_see_through.can_see_through(glass_see_through.original_of(
        ob.material_slots[index].material)) for index in slots)


def restore_records():
    """Put back every record in the file; leftovers without a record stay. Returns how many values came back."""
    restored = sum(scene_record.restore(scene, SCENE_KEY) for scene in bpy.data.scenes if SCENE_KEY in scene)
    return restored + sum(scene_record.restore(wm, WM_KEY) for wm in bpy.data.window_managers if WM_KEY in wm)


def restore_everywhere():
    """Put back every record in the file, then the leftovers found by their tags: glass faces modifiers, see-through
    copies (teardown and repair). Returns how many values came back."""
    return restore_records() + glass_faces.clean_up() + glass_see_through.clean_up()


def reapply(scene):
    """Bring every record in line with the settings for `scene` (option change, undo, failsafe): other scenes' records
    are restored, then apply() diffs this one. Never restore-then-apply: that flapped raytracing, shading and the
    compositor and froze the computer (2026-11-27). The viewer's base pose is never restored here: putting it back on
    the scene camera put you on the camera after every undo and flung you when it moved (2026-11-25)."""
    for other in bpy.data.scenes:
        if other != scene and SCENE_KEY in other:
            scene_record.restore(other, SCENE_KEY)
    apply(scene)


def hidden_names(scene):
    """Full names of the objects the Performance options hid for VR (glass, transparent)."""
    return {entry[2] for entry in scene_record.recorded(scene, SCENE_KEY) if entry[0] == scene_record.HIDE}


def hidden_count(scene):
    """Objects hidden whole for VR."""
    return sum(1 for entry in scene_record.recorded(scene, SCENE_KEY) if entry[0] == scene_record.HIDE)


def part_hidden_count(scene):
    """Objects with only their glass faces hidden for VR."""
    return glass_faces.count(scene, SCENE_KEY)


def see_through_count(scene):
    """Objects showing see-through glass in VR."""
    return glass_see_through.count(scene, SCENE_KEY)


def see_through_over_limit():
    """Objects that could show see-through glass but are hidden: over SEE_THROUGH_LIMIT."""
    return PLAN["over_limit"]


def _on_option_changed(_value):
    if RUNTIME.active:
        reapply(bpy.context.scene)


def _on_draw_distance_changed(_value):
    """Draw distance or hand marker: only the window manager part is diffed (no object scan): a draw distance press
    writes clip_end / clip_start and nothing else."""
    if RUNTIME.active:
        apply_window_manager()


@persistent
def on_save_pre(*_args):
    if RUNTIME.active or changes_marked():
        restore_everywhere()
        clear_mark()        # every module's save_pre puts its part back: the saved file has no flag


@persistent
def on_save_post(*_args):
    if RUNTIME.active:
        apply(bpy.context.scene)


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
