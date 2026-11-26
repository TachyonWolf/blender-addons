# SPDX-License-Identifier: GPL-3.0-or-later
"""The snap guide lines in the headset: what a snapped grab lines up with (snap_state.Guides). update() builds one small
line batch per session tick when the guides changed; draw() runs once per eye inside overlay.draw. Nothing runs unless a
snap shows."""
from . import line_draw
from .snap_state import Guides

COLOUR = (0.35, 1.0, 0.55, 0.95)
WIDTH = 2.5
_state = {"batch": None, "version": -1}


def visible():
    return len(Guides.lines) > 0


def update():
    if _state["version"] == Guides.version:
        return
    _state["version"] = Guides.version
    if not len(Guides.lines):
        _state["batch"] = None
        return
    _state["batch"] = line_draw.make_batch(Guides.lines.reshape(-1, 3).tolist())


def draw():
    batch = _state["batch"]
    if batch is None:
        return
    line_draw.draw_lines(batch, COLOUR, WIDTH)
