# SPDX-License-Identifier: GPL-3.0-or-later
"""Hover preview: before you press, each hand shows what its laser would select / grab and (Free mode) what its
grip would grab. Runs from the session timer on the button values controls.py polled. A hand that has not moved
(and whose scene has not changed) is skipped, and at most PICKS_PER_TICK picks run per tick (the others wait for the
next tick), so one tick stays cheap. The laser line itself follows the hand every frame (overlay.py)."""
from . import desk, router, settings, size_state
from .hands import HandPose
from .perf import TIMINGS
from .picking import Picker
from .pick_math import moved_enough
from .runtime import RUNTIME

PICKS_PER_TICK = 1   # one laser OR touch pick per tick
_picks = 0           # picks so far: the hands take turns by it


def update(context, state):
    """Refresh every hand's laser flag and hover targets."""
    global _picks
    grab_mode = settings.get("grab_mode")
    pose_mode = router.mode_kind(context.mode) == router.POSE
    draw_mode = router.mode_kind(context.mode) == router.GP_DRAW
    scene_changed = RUNTIME.cache.all_dirty or bool(RUNTIME.cache.changed)
    picker, picks = None, 0
    if RUNTIME.draw_handle is not None and RUNTIME.frame == RUNTIME.last_pick_frame:
        return     # at most one pick per headset frame (two ticks can fall in one frame below 30 fps)
    if any(hand_state.grabbing for hand_state in RUNTIME.hands.values()):
        clear()      # no hover while dragging: the scene changes every frame (a second grip still picks on press)
        return
    hands = list(RUNTIME.hands.items())
    if _picks % 2:
        hands.reverse()   # take turns per pick, not per tick: ticks per headset frame can stay even (one hand starves)
    for hand, hand_state in hands:
        laser, touch = router.hover_pickers(grab_mode, hand_state.trigger_touched, hand_state.grip_amount,
                                            always_laser=settings.get("always_laser"))
        if desk.laser_reach(hand) is not None or draw_mode:
            laser = touch = False    # the laser is on the desk (the desk wins), or Draw mode: the trigger draws, nothing is picked
        if not (laser or touch):
            hand_state.laser_on, hand_state.last_pose, hand_state.pending = False, None, []
            hand_state.laser_target = hand_state.touch_target = None
            continue
        pose = HandPose(context, state, hand, with_grip_rotation=False)
        now = (tuple(pose.aim_location), tuple(pose.aim_direction))
        if laser != hand_state.laser_on or scene_changed or moved_enough(hand_state.last_pose, now):
            hand_state.laser_on, hand_state.last_pose = laser, now
            if not laser:
                hand_state.laser_target = None
            if not touch:
                hand_state.touch_target = None
            jobs = [kind for kind, wanted in (("laser", laser), ("touch", touch)) if wanted]
            if len(jobs) == 2 and hand_state.touch_next:
                jobs.reverse()     # both wanted and the hand keeps moving: they take turns
            hand_state.pending = jobs
        if not hand_state.pending or picks >= PICKS_PER_TICK:
            continue               # nothing new for this hand (a still hand costs no pick), or it waits a tick
        job = hand_state.pending.pop(0)
        picks += 1
        _picks += 1
        hand_state.touch_next = job == "laser"
        RUNTIME.last_pick_frame = RUNTIME.frame
        with TIMINGS.measure("pick"):
            picker = picker or Picker(context, RUNTIME.cache)
            if job == "laser":
                hand_state.laser_target = picker.laser(pose_mode, pose.aim_location, pose.aim_direction,
                                                       size_state.laser_length())
            else:
                hand_state.touch_target = picker.touch(pose_mode, pose.grip_location, size_state.touch_distance())


def clear():
    for hand_state in RUNTIME.hands.values():
        hand_state.laser_on = False
        hand_state.laser_target = hand_state.touch_target = hand_state.last_pose = None
        hand_state.pending = []
