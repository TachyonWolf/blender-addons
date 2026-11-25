# SPDX-License-Identifier: GPL-3.0-or-later
"""Both thumbstick clicks, polled every other session tick (controls.update calls update()). One router.StickChord
turns them into events, so a two-stick hold never also clicks: RIGHT_CLICK = the desk (open / call / close),
LEFT_CLICK = the hooks in LEFT_CLICK_HANDLERS (planned: Pause), RECENTER at 2 s, FAILSAFE at 6 s (haptic tick each)."""
import time

from . import desk, recenter, router
from .action_map import HANDS, LEFT, RIGHT, buzz, value
from .runtime import RUNTIME

POLL_TICKS = 2                 # ~15 Hz at idle, on the even ticks (move.py reads the sticks on the odd ones)
CHORD = router.StickChord()
LEFT_CLICK_HANDLERS = []       # callables(context, state); the Pause branch adds its toggle here


def start():
    global CHORD
    CHORD = router.StickChord()


def update(context, state):
    if RUNTIME.ticks % POLL_TICKS:
        return
    for event in CHORD.update(value(context, state, "stick_click", LEFT), value(context, state, "stick_click", RIGHT),
                              time.perf_counter()):
        if event == router.RIGHT_CLICK:
            desk.right_click(context, state)
        elif event == router.LEFT_CLICK:
            for handler in LEFT_CLICK_HANDLERS:
                handler(context, state)
        elif event == router.RECENTER:
            recenter.recenter(context, state)
            for hand in HANDS:
                buzz(context, state, hand, duration=0.06, amplitude=0.6)
        elif event == router.FAILSAFE:
            recenter.failsafe(context, state)
            for hand in HANDS:
                buzz(context, state, hand, duration=0.2, amplitude=1.0)
