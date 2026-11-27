# SPDX-License-Identifier: GPL-3.0-or-later
"""The snap guide lines in the headset: what a snapped grab lines up with (snap_state.Guides). update() builds one small
line batch per session tick when the guides changed; draw() runs once per eye inside overlay.draw. Nothing runs unless a
snap shows."""
from . import line_draw
from .snap_state import Guides

COLOUR = (0.35, 1.0, 0.55, 0.95)          # what a snap lines up with
MARK_COLOUR = (0.4, 0.85, 1.0, 0.8)       # a candidate point near your hand
ACTIVE_COLOUR = (1.0, 0.9, 0.2, 1.0)      # the point the magnet holds
WIDTH = 2.5
_state = {"batches": [], "version": -1}


def visible():
    return Guides.shown()


def update():
    if _state["version"] == Guides.version:
        return
    _state["version"] = Guides.version
    _state["batches"] = [(line_draw.make_batch(lines.reshape(-1, 3).tolist()), colour, width)
                         for lines, colour, width in ((Guides.marks, MARK_COLOUR, 1.5), (Guides.lines, COLOUR, WIDTH), (Guides.active, ACTIVE_COLOUR, 4.0))
                         if len(lines)]


def draw():
    for batch, colour, width in _state["batches"]:
        line_draw.draw_lines(batch, colour, width)
