# SPDX-License-Identifier: GPL-3.0-or-later
"""Polled controls: each session tick reads grip and trigger per hand, turns them into press / release edges and
calls the tools (select on a trigger pull, grab while the grip is held; a second grip on the same item joins it for
two-hand scale). B toggles fine control. While a hand drags, the session timer runs every main-loop pass and each
grab applies once per headset frame (due()). A hand whose stick turns a grab (On stick) is listed in
RUNTIME.taken_sticks: move.py leaves that stick alone. Movement (move.py) runs from here too."""
import time

from . import annotate, desk, gpencil, move, router, settings, tools, user_scale
from .action_map import RIGHT, buzz, value
from .perf import TIMINGS
from .runtime import RUNTIME

DRAG_FALLBACK = 0.02


def grabs():
    """The running grabs, each once (two hands can hold one)."""
    found = []
    for hand_state in RUNTIME.hands.values():
        if hand_state.grab is not None and hand_state.grab not in found:
            found.append(hand_state.grab)
    return found


def _toggle_fine(context, state):
    RUNTIME.fine_down, pressed, _released = router.button_edge(RUNTIME.fine_down, value(context, state, "fine", RIGHT))
    if pressed:
        settings.put("fine_control", not settings.get("fine_control"))   # running grabs rebase on their next drag
        buzz(context, state, RIGHT, duration=0.03 if settings.get("fine_control") else 0.08, amplitude=0.4)


def _trigger_tool(context, state, hand):
    """A trigger pull on the scene: draws a stroke while Annotate is on (Object mode) or in Draw mode, else selects."""
    mode = router.mode_kind(context.mode)
    action = router.trigger_input(annotate.STATE.on, mode)
    behaviour = router.behaviour(action, mode, settings.get("grab_mode"))
    if behaviour == router.ANNOTATE_STROKE:
        annotate.begin(context, state, hand)
    elif behaviour == router.GP_STROKE:
        gpencil.begin(context, state, hand)
    else:
        tools.select(context, state, hand)


def update(context, state):
    """Returns True while any hand drags (the timer then runs every frame)."""
    _toggle_fine(context, state)
    for hand, hand_state in RUNTIME.hands.items():
        holding = any(other.grab is not None for other in RUNTIME.hands.values())
        hand_state.trigger_amount = value(context, state, "select", hand)
        hand_state.grip_amount = value(context, state, "grab", hand)
        hand_state.trigger_touched = value(context, state, "trigger_touch", hand) > 0.5
        hand_state.trigger_down, pulled, released = router.button_edge(hand_state.trigger_down,
                                                                        hand_state.trigger_amount)
        if pulled and holding:
            pass                                    # a grab owns the triggers: right pushes, left pulls (tools.drag)
        elif pulled and not desk.trigger_pressed(context, state, hand):     # the desk wins over the scene
            _trigger_tool(context, state, hand)
        elif released and annotate.STATE.recorder.hand == hand:
            annotate.end(context)
        elif released and gpencil.STATE.recorder.hand == hand:
            gpencil.end(context)
        hand_state.grip_down, gripped, let_go = router.button_edge(hand_state.grip_down, hand_state.grip_amount,
                                                                   press=0.55, release=0.35)
        if gripped and hand_state.grab is None:
            if not desk.grip_pressed(context, state, hand):               # a desk handle takes the grip first
                grab = tools.start_grab(context, state, hand)
                hand_state.grab = None if grab is tools.EMPTY else grab
                hand_state.empty_grip = grab is tools.EMPTY      # two such grips scale you (user_scale.py)
        if let_go:
            hand_state.empty_grip = False
        if hand_state.grab is not None and let_go:
            grab, hand_state.grab = hand_state.grab, None
            if not tools.release(context, state, grab, hand):
                end(grab, commit=True)
    for grab in grabs():
        if due(grab):
            with TIMINGS.measure("drag"):
                kept = tools.drag(context, state, grab)
            grab.last_frame, grab.last_time = RUNTIME.frame, time.perf_counter()
            if not kept:
                end(grab, commit=False)     # an undo / redo ran: the start data is stale
    running = grabs()
    RUNTIME.taken_sticks = {grab.rotates_on_stick() for grab in running if grab.rotates_on_stick()}
    desk_busy = desk.tick(context, state)
    drawing = annotate.update(context, state)
    drawing = gpencil.update(context, state) or drawing
    resizing = user_scale.update(context, state)
    return move.update(context, state) or desk_busy or bool(running) or drawing or resizing


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
    for grab in grabs():
        end(grab, commit)
