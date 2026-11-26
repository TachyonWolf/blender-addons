# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the running box (3D box or laser rectangle) in the headset. update() builds the line batch once per session
tick (overlay.sync); draw() runs once per eye inside overlay.draw. Nothing runs unless an A + trigger drag is going."""
from . import line_draw
from .runtime import RUNTIME

COLOUR = (1.0, 0.75, 0.2, 0.95)
WIDTH = 3.0
_state = {"batch": None}


def _boxing():
    return [hand_state.gesture for hand_state in RUNTIME.hands.values()
            if hand_state.gesture is not None and hand_state.gesture.boxing]


def visible():
    return bool(_boxing())


def update():
    boxes = _boxing()
    if not boxes:
        _state["batch"] = None
        return
    _state["batch"] = line_draw.make_batch([point for box in boxes for point in box.lines().tolist()])


def draw():
    batch = _state["batch"]
    if batch is None:
        return
    line_draw.draw_lines(batch, COLOUR, WIDTH)
