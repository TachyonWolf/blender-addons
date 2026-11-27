# SPDX-License-Identifier: GPL-3.0-or-later
"""Hover preview: before you press, each hand shows what its laser would select / grab and (Free mode) what its
grip would grab. Runs from the session timer on the button values controls.py polled. A hand that has not moved
(and whose scene has not changed) is skipped, and at most PICKS_PER_TICK picks run per tick (the others wait for the
next tick), so one tick stays cheap. In Object mode a pick has two parts (real surfaces, then bones and lines): in a
busy scene, when the first part used up PART_BUDGET, the second waits for the next tick (Digit's file: ~0.1 ms each).
The laser line itself follows the hand every frame (overlay.py)."""
import time

from . import edit_hover, grab_order, gun_shots, haptics_math, panels, router, settings, size_state, smart_select, tool_gun
from .action_map import buzz
from .hands import HandPose, current_sources
from .perf import TIMINGS
from .picking import LINES, SURFACE, WHOLE, Picker, nearest
from .pick_math import moved_enough
from .runtime import RUNTIME

PICKS_PER_TICK = 1   # one laser OR touch pick per tick
PART_BUDGET = 0.00006     # s: a pick's first part took longer: its second part runs on the next tick
_picks = 0           # picks so far: the hands take turns by it


def update(context, state):
    """Refresh every hand's laser flag and hover targets."""
    global _picks
    if RUNTIME.draw_handle is not None and RUNTIME.frame == RUNTIME.last_pick_frame:
        return     # at most one pick per headset frame (two ticks can fall in one frame below 30 fps)
    hand_states = RUNTIME.hands
    if any(hand_state.grabbing for hand_state in hand_states.values()):
        clear()      # no hover while dragging: the scene changes every frame (a second grip still picks on press)
        return
    always_laser = settings.get("always_laser")
    grab_sources = current_sources()
    mode = router.mode_kind(context.mode)
    pose_mode, draw_mode, edit_mode = mode == router.POSE, mode in router.TRIGGER_DRAWS, mode == router.EDIT
    scene_changed = RUNTIME.cache.all_dirty or bool(RUNTIME.cache.changed)
    picker, picks = None, 0
    hands = list(hand_states.items())
    if _picks % 2:
        hands.reverse()   # take turns per pick, not per tick: ticks per headset frame can stay even (one hand starves)
    for hand, hand_state in hands:
        laser, touch = router.hover_pickers(grab_sources, hand_state.trigger_touched, hand_state.grip_amount,
                                            always_laser=always_laser)
        armed = tool_gun.GUN.held_by == hand       # the gun points all the time and touches nothing
        if armed:
            laser, touch = True, False
        bones = pose_mode and (not armed or gun_shots.picks_bones(context))
        if draw_mode or panels.laser_reach(hand) is not None:
            laser = touch = False    # the laser is on a panel (panels win), or Draw mode: the trigger draws, nothing is picked
        sources = tuple(source for source in grab_sources if (laser if source == grab_order.LASER else touch))   # what hovers now
        if edit_mode:       # no object is hovered; the element under the laser / hand lights up (edit_hover)
            hand_state.laser_target = hand_state.touch_target = hand_state.partial = None
            hand_state.pending = []
            if edit_hover.update(context, state, hand, hand_state, laser, sources, picks < PICKS_PER_TICK):
                picks += 1
                _picks += 1
                RUNTIME.last_pick_frame = RUNTIME.frame
            continue
        if not sources:      # nothing to pick with (the laser line may still show)
            hand_state.laser_on, hand_state.last_pose, hand_state.pending = laser, None, []
            hand_state.laser_target = hand_state.touch_target = hand_state.partial = None
            continue
        pose = HandPose(context, state, hand, with_grip_rotation=False, with_grip=touch)
        now = (pose.aim_location, pose.aim_direction)
        switched = laser != hand_state.laser_on or scene_changed
        if switched or (not hand_state.pending and moved_enough(hand_state.last_pose, now)):
            # A moving hand lets the order's pass in progress finish first (at the pose it started with), else a hand that is
            # never still (VR) would only ever try the first sources: a laser last in the order never hovered (2026-11-27).
            hand_state.laser_on, hand_state.last_pose = laser, now
            if not laser:
                hand_state.laser_target = None
            if not touch:
                hand_state.touch_target = None
            parts = (WHOLE,) if bones else (SURFACE, LINES)
            hand_state.pending = [(source, part, pose) for source in sources for part in parts]
        if not hand_state.pending or picks >= PICKS_PER_TICK:
            continue               # nothing new for this hand (a still hand costs no pick), or it waits a tick
        picks += 1
        _picks += 1
        RUNTIME.last_pick_frame = RUNTIME.frame
        with TIMINGS.measure("pick"):
            picker = picker or Picker(context, RUNTIME.cache)
            _run_pick(context, picker, hand_state, bones)
    _pulse_on_change(context, state)


def _pulse_on_change(context, state):
    """One short pulse when a hand's laser / touch / Edit hover target or the panel button under it CHANGES (never a continuous buzz). Costs one
    settings read per tick while Haptics is off."""
    on = settings.get("haptics")
    for hand, hand_state in RUNTIME.hands.items():
        key = (hand_state.laser_target and hand_state.laser_target.key(),
               hand_state.touch_target and hand_state.touch_target.key(), hand_state.edit_hover, panels.hovered_button(hand))
        if not any(key):
            key = None
        if on and haptics_math.target_changed(hand_state.pulse_key, key):
            buzz(context, state, hand, kind=haptics_math.POINT)
        hand_state.pulse_key = key


def _run_pick(context, picker, hand_state, pose_mode):
    """One pick for a hand: its next part, and the part after it while this tick is still cheap."""
    started = time.perf_counter()
    while hand_state.pending:
        source, part, pose = hand_state.pending.pop(0)
        if source == grab_order.LASER:
            found = picker.laser_part(part, pose_mode, pose.aim_location, pose.aim_direction, size_state.laser_length())
        else:
            found = picker.touch_part(part, pose_mode, pose.source_point(source), size_state.touch_distance())
        if part == SURFACE:
            hand_state.partial = found
            if time.perf_counter() - started < PART_BUDGET and hand_state.pending:
                continue           # cheap scene: the second part now, no extra tick of delay
            return
        if part == LINES:
            found, hand_state.partial = nearest(hand_state.partial, found), None
        found = smart_select.resolve(context, found, preview=True)[0]     # the glow shows what a pick would act on
        if found is None and hand_state.pending:      # nothing from this source: the next one of the order
            if time.perf_counter() - started < PART_BUDGET:
                continue
            return
        hand_state.pending = []                       # the first hit wins: the sources after it are not tried
        hand_state.laser_target, hand_state.touch_target = (found, None) if source == grab_order.LASER else (None, found)
        hand_state.hover_source = source
        return


def clear():
    for hand_state in RUNTIME.hands.values():
        hand_state.laser_on = False
        hand_state.edit_hover = None
        hand_state.laser_target = hand_state.touch_target = hand_state.last_pose = hand_state.partial = None
        hand_state.pending = []
        hand_state.pulse_key = None
