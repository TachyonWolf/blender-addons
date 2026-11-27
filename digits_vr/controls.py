# SPDX-License-Identifier: GPL-3.0-or-later
"""Polled controls: each session tick reads grip and trigger per hand, turns them into press / release edges and
calls the tools (select on a trigger pull, grab while the grip is held; a second grip on the same item joins it for
two-hand scale). B toggles fine control. While a hand drags, the session timer runs every main-loop pass and each
grab applies once per headset frame (due()). Movement (move.py) runs from here too."""
import time

from mathutils import Quaternion

from . import annotate, belt, box_math, draw_size, gpencil, gun_shots, held_item, move, panels, router, sculpt_draw, select_bubble, sculpt_stroke, select_gesture, settings, size_state, sticks, tool_gun, tools, user_scale
from .action_map import LEFT, RIGHT, buzz, value
from .belt_state import BELT
from .hands import HandPose
from .perf import TIMINGS
from .runtime import RUNTIME
from .transform_math import trigger_net

DRAG_FALLBACK = 0.02
FINE_POLL_TICKS = 2      # B is read every other tick (~15 Hz), on the odd ticks with the sticks (move.py)


def grabs():
    """The running grabs, each once (two hands can hold one)."""
    found = []
    for hand_state in RUNTIME.hands.values():
        if hand_state.grab is not None and hand_state.grab not in found:
            found.append(hand_state.grab)
    return found


def _toggle_fine(context, state):
    if RUNTIME.ticks % FINE_POLL_TICKS != 1 or sculpt_draw.View.active or select_bubble.active() or draw_size.active():      # Sculpt mode, select bubble, drawing tools: B is the size gesture
        return
    RUNTIME.fine_down, pressed, _released = router.button_edge(RUNTIME.fine_down, value(context, state, "fine", RIGHT))
    if pressed and belt.pin_at_fingertip(context, state, RIGHT):
        return                                  # B with the fingertip at a belt slot: pin / unpin its slot [user]
    if pressed:
        settings.put("fine_control", not settings.get("fine_control"))   # running grabs rebase on their next drag
        buzz(context, state, RIGHT, duration=0.03 if settings.get("fine_control") else 0.08, amplitude=0.4)


def _trigger_tool(context, state, hand):
    """A trigger pull on the scene: draws a stroke while Annotate is on (Object mode) or in Draw mode, else selects."""
    if tool_gun.GUN.held_by == hand:
        gun_shots.press(context, state, hand)
        return
    hand_state = RUNTIME.hands[hand]
    mode = router.mode_kind(context.mode)
    action = router.trigger_input(annotate.is_on(context), mode, select_bubble.wanted(context))
    behaviour = router.behaviour(action, mode, settings.get("grab_mode"))
    if behaviour == router.ANNOTATE_STROKE:
        annotate.begin(context, state, hand)
    elif behaviour == router.GP_STROKE:
        gpencil.begin(context, state, hand)
    elif behaviour == router.SCULPT_STROKE:
        sculpt_stroke.begin(context, state, hand)
    elif behaviour == router.SELECT_BUBBLE:
        select_bubble.begin(context, state, hand)
    elif value(context, state, "toggle", RIGHT) > 0.5:
        hand_state.gesture = _new_gesture(context, state, hand, mode)
    elif mode == router.EDIT and router.edit_behaviour(action, behaviour, settings.get("edit_tool"), False) == router.EDIT_TOOL:
        _take_grab(hand_state, tools.start_edit_tool(context, state, hand))
        if hand_state.grab is not None:
            hand_state.grab.by_trigger = True
        hand_state.empty_grip = False
    else:
        tools.select(context, state, hand)


def _take_grab(hand_state, grab):
    hand_state.grab = None if grab is tools.EMPTY else grab
    hand_state.empty_grip = grab is tools.EMPTY      # two such grips scale you (user_scale.py)


def _new_gesture(context, state, hand, mode):
    """A + trigger: a tap toggles, a drag is a box select (decided at the release). Both boxes start AT the fingertip and
    its corners follow the fingertip, in every mode [user, 2026-11-25]; the grips push the 3D box's far corner out."""
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    return select_gesture.SelectGesture(
        hand, pose.aim_location[:], mode, RUNTIME.generation,
        select_gesture.start_distance(0.0, size_state.scaled(select_gesture.BOX_START_DISTANCE)), _head(state),
        settings.get("box_shape"), 0.0, [other for other, other_state in RUNTIME.hands.items() if other_state.grip_down],
        time.perf_counter())


def _push_box(gesture):
    """A running 3D box: the right grip pushes the moving corner away along the aim, the left pulls it closer."""
    now = time.perf_counter()
    seconds, gesture.last_time = min(now - gesture.last_time, tools.STICK_STEP_MAX), now
    gesture.stale_grips = {hand for hand in gesture.stale_grips if RUNTIME.hands[hand].grip_down}
    if not gesture.boxing or gesture.shape != box_math.VOLUME:
        return
    amounts = {hand: hand_state.grip_amount for hand, hand_state in RUNTIME.hands.items() if hand not in gesture.stale_grips}
    net = trigger_net(amounts.get(RIGHT, 0.0), amounts.get(LEFT, 0.0))
    # straight along the aim from the fingertip (the corner starts AT it, so "away from the hand" has no direction yet)
    gesture.reach = max(0.0, gesture.reach + net * size_state.push_speed() * seconds * tools.motion_factor())


def _head(state):
    """The headset now: (location, 3x3 rotation matrix as nested tuples, your size) (box_math's `head`)."""
    return (tuple(state.viewer_pose_location), tuple(tuple(row) for row in Quaternion(state.viewer_pose_rotation).to_matrix()),
            size_state.SIZE.factor)


def _gesture_ends(context, state, hand, hand_state, released):
    """Follow a running A + trigger gesture; at the release run the tap (toggle) or the box. Undo / redo, a mode change
    cancel it (nothing was changed yet)."""
    gesture = hand_state.gesture
    if gesture.generation != RUNTIME.generation or gesture.mode != router.mode_kind(context.mode):
        hand_state.gesture = None
        return
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    _push_box(gesture)
    gesture.update((pose.aim_location + pose.aim_direction * gesture.reach)[:])
    if gesture.shape == box_math.LASER:
        gesture.head = _head(state)          # the 2D box is seen from where your head is NOW (it turns as you move) [user]
    if released:
        hand_state.gesture = None
        if gesture.finish() == select_gesture.TAP:
            tools.select(context, state, hand, toggle=True)
        else:
            tools.box_select(context, state, hand, gesture)


def _grip_tool(context, state, hand, hand_state):
    """A grip on the scene: takes the tool gun, inverts in Sculpt mode, else grabs."""
    if tool_gun.grip_pressed(context, state, hand):
        return
    if router.behaviour(router.GRAB, router.mode_kind(context.mode), settings.get("grab_mode")) == router.SCULPT_INVERT:
        sculpt_stroke.grip(hand, True)
        return
    _take_grab(hand_state, tools.start_grab(context, state, hand))


def _update_hand(context, state, hand, hand_state, paused):
    """One hand's trigger and grip this tick: their press / release edges start and end the tools."""
    holding = any(other.grab is not None for other in RUNTIME.hands.values())
    hand_state.trigger_amount = value(context, state, "select", hand)
    hand_state.grip_amount = value(context, state, "grab", hand)
    hand_state.trigger_touched = value(context, state, "trigger_touch", hand) > 0.5
    hand_state.trigger_down, pulled, released = router.button_edge(hand_state.trigger_down,
                                                                    hand_state.trigger_amount)
    if hand_state.gesture is not None:
        _gesture_ends(context, state, hand, hand_state, released)
    if released:
        gun_shots.release(hand)
    if pulled and holding and held_item.held_in(hand) is None:
        if hand_state.grab is None and any(grab.tool_item is not None for grab in grabs()):
            panels.trigger_pressed(context, state, hand)      # a tool drag: the other hand changes its settings
    elif pulled and not panels.trigger_pressed(context, state, hand):     # a panel wins over the scene
        if not paused:
            _trigger_tool(context, state, hand)
    elif released and annotate.STATE.recorder.hand == hand:
        annotate.end(context)
    elif released and gpencil.STATE.recorder.hand == hand:
        gpencil.end(context)
    elif released and sculpt_stroke.STATE.recorder.hand == hand:
        sculpt_stroke.end(context)
    elif released and select_bubble.View.hand == hand:
        select_bubble.end(context)
    hand_state.grip_down, gripped, let_go = router.button_edge(hand_state.grip_down, hand_state.grip_amount,
                                                               press=0.55, release=0.35)
    if gripped and any(other.gesture is not None for other in RUNTIME.hands.values()):
        pass                                    # a box owns both grips (_push_box): no grab, no panel, no size gesture
    elif gripped and hand_state.grab is None:
        if sculpt_stroke.STATE.recorder.hand == hand:
            sculpt_stroke.grip(hand, True)      # the stroking hand's grip always inverts, also near a panel
        elif belt.grip_pressed(context, state, hand):
            pass                                # something came off the tool belt (belt.py)
        elif not panels.grip_pressed(context, state, hand) and not paused:     # a panel handle takes the grip first
            _grip_tool(context, state, hand, hand_state)
    if let_go:
        hand_state.empty_grip = False
        sculpt_stroke.grip(hand, False)
        tool_gun.grip_released(hand)
        belt.grip_released(context, state, hand)
    if hand_state.grab is not None and (released if hand_state.grab.by_trigger else let_go):
        grab, hand_state.grab = hand_state.grab, None
        if not tools.release(context, state, grab, hand):
            belt.grab_released(context, state, grab, hand)      # a free belt slot pockets the object
            end(grab, commit=True)


def update(context, state):
    """Returns True while any hand drags (the timer then runs every frame)."""
    paused = settings.get("paused")       # pause.py: scene tools and sticks off, panels and both stick clicks stay live
    if not paused:
        _toggle_fine(context, state)
    for hand, hand_state in RUNTIME.hands.items():
        _update_hand(context, state, hand, hand_state, paused)
    for grab in grabs():
        if due(grab):
            with TIMINGS.measure("drag"):
                kept = tools.drag(context, state, grab)
            grab.last_frame, grab.last_time = RUNTIME.frame, time.perf_counter()
            if not kept:
                end(grab, commit=False)     # an undo / redo ran: the start data is stale
    running = grabs()
    sticks.update(context, state)
    panels_busy = panels.tick(context, state)
    if BELT.running:
        panels_busy = belt.update(context, state) or panels_busy
    if paused:
        return panels_busy or bool(running)
    drawing = annotate.update(context, state)
    drawing = gpencil.update(context, state) or drawing
    drawing = sculpt_stroke.update(context, state) or drawing
    drawing = select_bubble.update(context, state) or drawing
    drawing = draw_size.update(context, state) or drawing
    drawing = gun_shots.update(context, state) or drawing
    resizing = user_scale.update(context, state)
    return move.update(context, state) or panels_busy or bool(running) or drawing or resizing


def due(grab):
    """Drag once per headset frame: the timer runs every main-loop pass while dragging, the overlay's draw counts
    frames. Fallback when no frame was counted for a while (no draw handler): every 20 ms."""
    return grab.last_frame != RUNTIME.frame or time.perf_counter() - grab.last_time > DRAG_FALLBACK


def end(grab, commit):
    """Finish a grab and free every hand that held it."""
    tools.end_grab(grab, commit)
    for hand_state in RUNTIME.hands.values():
        if hand_state.grab is grab:
            hand_state.grab = None


def end_all(commit):
    gun_shots.end(commit)
    for grab in grabs():
        end(grab, commit)
