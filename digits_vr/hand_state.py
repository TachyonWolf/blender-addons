# SPDX-License-Identifier: GPL-3.0-or-later
"""The hands' live finger state (bpy side, no GPU): target curls from the controller inputs once per tick, eased
curls per headset frame (hand_draw.py draws them, poke.py reads the fingertips). Also the VR-only switch of Blender's
own controller marker: always off in VR (our axis, hand_marker.py, replaces it); written through the
Performance record (perf_state.WM_KEY), so the teardown / file save put Blender's own value back."""
import time

from . import hand_model, settings
from .action_map import HANDS, LEFT, RIGHT, value, vector
from .runtime import RUNTIME

THUMB_BUTTONS = {RIGHT: ("toggle", "fine", "stick_click"), LEFT: ("undo_button", "redo_button", "stick_click")}
STICK_PUSH = 0.35
SETTLED = 0.004          # a curl this close to its target snaps to it (the mesh steps are 1/16)
CURLS = {hand: dict(hand_model.REST_CURLS) for hand in HANDS}        # eased, what is drawn
TARGETS = {hand: dict(hand_model.REST_CURLS) for hand in HANDS}
_last = [None]


def reset():
    for hand in HANDS:
        CURLS[hand] = dict(hand_model.REST_CURLS)
        TARGETS[hand] = dict(hand_model.REST_CURLS)
    _last[0] = None


def enabled():
    return RUNTIME.active and settings.get("show_hands")


def thumb_down(context, state, hand):
    stick = vector(context, state, "stick", hand)
    if stick[0] * stick[0] + stick[1] * stick[1] > STICK_PUSH * STICK_PUSH:
        return True
    return any(value(context, state, name, hand) > 0.5 for name in THUMB_BUTTONS[hand])


_thumb = {hand: False for hand in HANDS}


def update(context, state):
    """Once per tick: the target curls from the inputs (the eased curls follow in `animate`). The thumb's four
    inputs are read on every second tick only (the thumb eases over several frames anyway)."""
    poll_thumb = RUNTIME.ticks % 2 == 0
    for hand in HANDS:
        hand_state = RUNTIME.hands[hand]
        if poll_thumb:
            _thumb[hand] = thumb_down(context, state, hand)
        targets = hand_model.targets(hand_state.trigger_amount, hand_state.grip_amount, _thumb[hand])
        if targets != TARGETS[hand]:
            TARGETS[hand] = targets


def animate(now=None):
    """Once per headset frame: ease the curls towards their targets."""
    now = time.perf_counter() if now is None else now
    seconds = 0.0 if _last[0] is None else min(0.1, now - _last[0])
    _last[0] = now
    for hand in HANDS:
        if CURLS[hand] != TARGETS[hand]:       # a settled hand costs nothing
            CURLS[hand] = hand_model.approach(CURLS[hand], TARGETS[hand], seconds)
            if all(abs(TARGETS[hand][name] - amount) < SETTLED for name, amount in CURLS[hand].items()):
                CURLS[hand] = dict(TARGETS[hand])


def changes(window_manager):
    """(ID, path, value) changes for scene_record.set_values: Blender's own controller marker is off in VR; our small axis
    at the fingertip replaces it [user, 2026-11-25]."""
    return [(window_manager, "xr_session_settings.show_controllers", False)]
