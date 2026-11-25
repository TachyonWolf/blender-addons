# SPDX-License-Identifier: GPL-3.0-or-later
"""Your size (user scale): make yourself smaller or bigger to work at different scales [user, 2026-11-25].

Blender's XR `base_scale` scales the viewer: head, hands and controller poses (spike, ox: base_scale 2 = poses 2x as
far from the navigation origin, so you are 2x as big). It does not move the navigation, so every change moves
`navigation_location` by `scale_math.scale_about`: the pivot (your head, or the point between your hands in the
gesture) stays where it is. Preset buttons (desk Move tab, sidebar) scale about the head. The two-hand gesture
(grip both hands on empty space) scales about the point between the hands; pulling apart makes you smaller.

VR only: the session starts at 1:1; the original base_scale is recorded on the window manager (scene_record, like the
performance options) and put back when VR ends, before a save and after a load that finds a leftover record. The
desk scales with you (desk.size_changed), movement distances and the touch distance / laser length follow `SIZE`
(size_state.py). One viewer change per headset frame: the poses read next frame already have the new scale."""
import time

import bpy
from bpy.app.handlers import persistent
from mathutils import Vector

from . import desk, move, scale_math, scene_record, settings  # scene_record: generated copy
from .action_map import LEFT, RIGHT, buzz
from .hands import HandPose
from .runtime import RUNTIME
from .size_state import SIZE

WM_KEY = "digits_vr_scale_wm"
BASE_SCALE = "xr_session_settings.base_scale"
FRAME_FALLBACK = 0.05          # without counted headset frames, change the size every 50 ms at most
_gesture = {"on": False, "start_size": 1.0, "start_gap": 0.0, "last_frame": -1, "last_time": 0.0, "at_limit": False}


def start(context):
    """Session start: 1:1 (the size is not remembered), the user's own base scale is the 1:1 value."""
    restore(context)
    SIZE.factor = 1.0
    SIZE.original = context.window_manager.xr_session_settings.base_scale
    _gesture.update(on=False, last_frame=-1)
    SIZE.gesturing = False


def teardown():
    """Session over (central teardown): the user's base scale comes back, the size is 1:1 again."""
    restore(bpy.context)
    SIZE.factor, SIZE.gesturing = 1.0, False
    _gesture["on"] = False


def restore(context):
    """Put the recorded base scale back (also leftovers of a crash, after a load). Returns how many."""
    return scene_record.restore(context.window_manager, WM_KEY)


def _apply(context):
    """Write the base scale for the current size (recorded once, so the restore knows the original)."""
    window_manager = context.window_manager
    scene_record.set_values(window_manager, WM_KEY, [(window_manager, BASE_SCALE, SIZE.original * SIZE.factor)],
                            "window_managers")
    if SIZE.factor == 1.0:
        window_manager.xr_session_settings.base_scale = SIZE.original


def set_size(context, state, target, pivot=None):
    """Change your size to `target` (clamped) about the world point `pivot` (default: your head). Returns True when
    the size changed."""
    target = scale_math.clamp_size(target)
    old = SIZE.factor
    if abs(target / old - 1.0) < 1e-6:
        return False
    pivot = Vector(state.viewer_pose_location) if pivot is None else pivot
    state.navigation_location = scale_math.scale_about(Vector(state.navigation_location), pivot, old, target)
    SIZE.factor = target
    _apply(context)
    desk.size_changed(pivot, old, target)
    move.size_changed(state)
    RUNTIME.cache.all_dirty = True
    return True


def preset(context, state, size):
    """A preset button: scale about the head."""
    return set_size(context, state, size)


# ---------------------------------------------------------------------------
# The two-hand gesture
# ---------------------------------------------------------------------------

def _hand_points(context, state):
    return {hand: HandPose(context, state, hand, with_grip_rotation=False).grip_location for hand in (LEFT, RIGHT)}


def gesture_wanted():
    """Both grips are down on empty space (nothing under either hand, not the desk) and the setting is on."""
    return settings.get("size_gesture") and all(hand_state.empty_grip and hand_state.grip_down
                                                for hand_state in RUNTIME.hands.values())


def update(context, state):
    """Once per session tick (controls.update). Returns True while the gesture runs (the timer runs every frame)."""
    if not gesture_wanted():
        _gesture["on"] = SIZE.gesturing = False
        return False
    points = _hand_points(context, state)
    gap = (points[LEFT] - points[RIGHT]).length / SIZE.factor           # between your hands in YOUR space
    if not _gesture["on"]:
        if gap < scale_math.MIN_HAND_GAP:
            return False
        _gesture.update(on=True, start_size=SIZE.factor, start_gap=gap, last_frame=RUNTIME.frame,
                        last_time=time.perf_counter(), at_limit=False)
        SIZE.gesturing = True
        buzz(context, state, LEFT, duration=0.02, amplitude=0.3)
        buzz(context, state, RIGHT, duration=0.02, amplitude=0.3)
        return True
    if gap < scale_math.MIN_HAND_GAP:
        return True                                                     # hands touching: the size holds
    now = time.perf_counter()
    if RUNTIME.frame == _gesture["last_frame"] and now - _gesture["last_time"] < FRAME_FALLBACK:
        return True                                                     # one change per headset frame
    _gesture.update(last_frame=RUNTIME.frame, last_time=now)
    target = scale_math.gesture_size(_gesture["start_size"], _gesture["start_gap"], gap)
    set_size(context, state, target, pivot=(points[LEFT] + points[RIGHT]) / 2)
    limit = target in (scale_math.MIN_SIZE, scale_math.MAX_SIZE)
    if limit and not _gesture["at_limit"]:
        buzz(context, state, LEFT, duration=0.03, amplitude=0.5)
        buzz(context, state, RIGHT, duration=0.03, amplitude=0.5)
    _gesture["at_limit"] = limit
    return True


# ---------------------------------------------------------------------------
# File safety (the base scale is saved in the .blend with the window manager)
# ---------------------------------------------------------------------------

@persistent
def on_save_pre(*_args):
    if RUNTIME.active:
        restore(bpy.context)


@persistent
def on_save_post(*_args):
    if RUNTIME.active:
        _apply(bpy.context)


def after_load():
    """load_post: a record left by a crash is put back."""
    if restore(bpy.context):
        print("digits_vr: the VR base scale left changed was put back")


HANDLERS = (("save_pre", on_save_pre), ("save_post", on_save_post))


def register():
    for name, function in HANDLERS:
        getattr(bpy.app.handlers, name).append(function)


def unregister():
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function in handlers:
            handlers.remove(function)
