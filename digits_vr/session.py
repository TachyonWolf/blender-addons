# SPDX-License-Identifier: GPL-3.0-or-later
"""Session lifecycle: start, the light per-session timer, and ONE central teardown (A2, A20).

Blender has only `xr_session_start_pre`; there is no end handler. So the timer watches `is_running` and calls
teardown() the moment the session is gone (stopped from our panel, the stock VR panel, SteamVR or a headset crash).
teardown() is also called by unregister() and load_pre. It stops grabs, removes the draw handler, the depsgraph
watch and the timer, and restores the modifier flags. It is safe to call any number of times."""
import math

import bpy
from bpy.app.handlers import persistent

from . import action_map, annotate, belt, body_frame, belt_pocket, edit_actions, edit_state, hand_state, camera_preview, sticks, gpencil, asset_scan, controls, hover, panels, modifier_state, move, overlay, pause, perf_state, perf_stats, scene_record, sculpt_stroke, select_bubble, user_scale
from .hands import session_state
from .perf import TIMINGS
from .runtime import RUNTIME

TICK = 1.0 / 30.0                 # idle: buttons polled and hover checked ~30 times a second
DRAG_TICK = 0.0                   # while a hand drags: every main-loop pass (controls.due() keeps it to one drag per frame)
REASSERT_TICKS = (1, 15, 45)      # re-activate our action set shortly after start (viewport_vr_preview, A4)


def configure_session(context):
    """Viewer options our session wants (Material Preview, annotations shown)."""
    session_settings = context.window_manager.xr_session_settings
    session_settings.shading.type = 'MATERIAL'
    _free_viewer_from_camera(context)


def _free_viewer_from_camera(context):
    """Blender anchors the VR viewer to the scene camera by default, so grabbing the camera carried the user away.
    Pin the start pose where the camera is now (CUSTOM base pose). VR-only: recorded with the Performance tab's window-manager record, so the teardown puts it back."""
    from mathutils import Vector
    window_manager = context.window_manager
    session_settings = window_manager.xr_session_settings
    changes = []        # (cameras / lights / empties and their wires show through the Display tab: display_state.py)
    camera = context.scene.camera
    anchored = session_settings.base_pose_type == 'SCENE_CAMERA' or (
        session_settings.base_pose_type == 'OBJECT' and session_settings.base_pose_object == camera)
    if anchored and camera is not None:
        forward = camera.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
        yaw = math.atan2(forward.y, forward.x) - math.pi / 2
        changes += [(window_manager, "xr_session_settings.base_pose_type", 'CUSTOM'),
                    (window_manager, "xr_session_settings.base_pose_location", tuple(camera.matrix_world.translation)),
                    (window_manager, "xr_session_settings.base_pose_angle", yaw)]
    scene_record.set_values(window_manager, perf_state.WM_KEY, changes, "window_managers")


def start(context):
    """Begin our per-session work (called from xr_session_start_pre, or on load_post when a session survived)."""
    if RUNTIME.active:
        return
    RUNTIME.active = True
    RUNTIME.ticks = 0
    RUNTIME.reset_hands()
    RUNTIME.cache.clear()
    TIMINGS.clear()
    perf_stats.reset()
    modifier_state.hide_for_vr(context.scene)
    perf_state.apply(context.scene)
    panels.start(context)
    body_frame.BODY.reset()
    belt.start(context)
    sticks.start()
    pause.reset()
    camera_preview.mark_dirty()
    asset_scan.start()              # background Blender; skipped when the cache is fresh
    move.start(context)
    user_scale.start(context)
    if on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)
    if not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=TICK)


def teardown(reason="", commit=True):
    """End everything this session started. Idempotent. `commit` keeps a running grab as an undo step."""
    was_active = RUNTIME.active
    if was_active:
        controls.end_all(commit)
    RUNTIME.active = False
    overlay.remove()
    annotate.teardown(commit)
    gpencil.teardown(commit)
    sculpt_stroke.teardown(commit)
    select_bubble.teardown(commit)
    belt.teardown()                 # un-hides pocketed models, undocks items (before the panels close)
    panels.teardown()
    edit_state.clear()
    hand_state.reset()
    asset_scan.stop()
    move.teardown()
    user_scale.teardown()
    if on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(on_depsgraph_update)
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    hover.clear()
    RUNTIME.reset_hands()
    RUNTIME.cache.clear()
    modifier_state.restore_everywhere()
    perf_state.restore_everywhere()
    if was_active and reason:
        print(f"digits_vr: session ended ({reason})")


def tick():
    context = bpy.context
    state = session_state(context)
    if state is None:
        teardown("session no longer running")
        return None
    dragging = False
    with TIMINGS.measure("tick"):
        RUNTIME.ticks += 1
        if RUNTIME.ticks in REASSERT_TICKS:
            action_map.assert_active(context, state)
            configure_session(context)     # the start resets the shading to Solid: set it again once running
            perf_state.apply(context.scene)     # (it resets the viewport compositor too)
        action_map.haptics_tick(context, state)
        try:
            edit_state.sync(context)
            dragging = controls.update(context, state)
            edit_actions.tick(context)
            hover.update(context, state)
            hand_state.update(context, state)
        except (ReferenceError, RuntimeError, AttributeError) as error:   # data gone mid-check: next tick retries
            print(f"digits_vr: tick skipped: {error}")
            RUNTIME.cache.all_dirty = True
        except Exception:                     # a bug in one tool must never freeze every control (2026-11-25: a drop's NameError)
            import traceback
            traceback.print_exc()
            RUNTIME.cache.all_dirty = True
        try:
            overlay.sync()
        except Exception as error:      # a drawing problem must never end the timer: that would stop all VR input
            print(f"digits_vr: drawing skipped: {error}")
        asset_scan.poll(RUNTIME.ticks)
    return DRAG_TICK if dragging else TICK


def on_depsgraph_update(scene, depsgraph):
    if not belt_pocket.only_pockets(depsgraph):      # the belt moving pocketed models is no scene change for the desk
        RUNTIME.scene_updates += 1
    if edit_state.on_depsgraph(depsgraph):
        return                          # editing a mesh: edit_state watches it (the object caches rebuild on leaving)
    if RUNTIME.grabbed:                 # dragging: everything moves each frame; refresh all after the grab
        RUNTIME.cache.all_dirty = True
        return
    camera_preview.mark_dirty()
    with TIMINGS.measure("depsgraph"):
        names = {update.id.original.name_full for update in depsgraph.updates
                 if isinstance(update.id, bpy.types.Object) and (update.is_updated_transform or update.is_updated_geometry)}
        if names:
            RUNTIME.cache.mark_changed(names)
        elif any(isinstance(update.id, (bpy.types.Scene, bpy.types.Collection)) for update in depsgraph.updates):
            RUNTIME.cache.objects = None   # objects added, removed, hidden: rebuild the pickable list
            RUNTIME.cache.version += 1


@persistent
def on_xr_start_pre(*_args):
    context = bpy.context
    state = context.window_manager.xr_session_state
    if state is None:
        return
    RUNTIME.problems = action_map.build(context, state)
    if RUNTIME.problems:
        print("digits_vr: not bound (fine for profiles the runtime lacks):", ", ".join(RUNTIME.problems))
    configure_session(context)
    start(context)


@persistent
def on_load_pre(*_args):
    teardown("file load", commit=False)


@persistent
def on_load_post(*_args):
    edit_state.clear()
    modifier_state.after_load()
    perf_state.after_load()
    user_scale.after_load()
    belt.after_load()
    if session_state(bpy.context):     # the session survived the load: pick it up again
        start(bpy.context)


@persistent
def on_undo_redo(*_args):
    RUNTIME.generation += 1            # running grabs cancel (their start data is stale, A18)
    edit_state.clear()
    RUNTIME.cache.all_dirty = True
    modifier_state.after_undo()
    perf_state.after_undo()
    belt.after_undo()


@persistent
def on_undo(*_args):
    edit_actions.undo_happened()
    on_undo_redo(*_args)


HANDLERS = (("xr_session_start_pre", on_xr_start_pre), ("load_pre", on_load_pre), ("load_post", on_load_post),
            ("undo_post", on_undo), ("redo_post", on_undo_redo))


def register():
    for name, function in HANDLERS:
        getattr(bpy.app.handlers, name).append(function)


def unregister():
    teardown("add-on disabled")
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function in handlers:
            handlers.remove(function)
