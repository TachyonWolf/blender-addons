# SPDX-License-Identifier: GPL-3.0-or-later
"""What Sculpt mode shows in the headset, drawn with the overlay's own lines: the brush ring at hands.tool_point
(while the trigger is touched, a stroke runs or the size changes) and, for a stroke without live preview, its path."""
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from .action_map import HANDS
from .hands import tool_point
from .runtime import RUNTIME

NORMAL, INVERT, SMOOTH = (1.0, 0.75, 0.35, 0.95), (1.0, 0.35, 0.3, 0.95), (0.4, 0.7, 1.0, 0.95)
SEGMENTS, WIDTH = 48, 2.5
_batches = {"ring": None, "path": None, "count": -1}


class View:
    """Written by sculpt_stroke each tick, read by the overlay's draw."""
    active = False       # Sculpt mode during VR
    diameter = 0.0       # world size of the ring
    colour = NORMAL
    sizing = False       # B held
    stroke_hand = None
    path = []            # world points of a stroke without live preview


def _unit_circle():
    points = [(0.5 * math.cos(a), 0.5 * math.sin(a), 0.0) for a in (2 * math.pi * i / SEGMENTS for i in range(SEGMENTS + 1))]
    return [point for pair in zip(points, points[1:]) for point in pair]


def ring_hands(stroke_hand, sizing):
    """The hands that show the ring: stroking, a finger on the trigger, or (right hand) while B sizes it."""
    return [hand for hand in HANDS if hand == stroke_hand or RUNTIME.hands[hand].trigger_touched
            or sizing and hand == HANDS[-1]]


def visible():
    return View.active and bool(ring_hands(View.stroke_hand, View.sizing))


def lines(aims, make_batch):
    """[(batch, colour, width, model matrix, in front)] for the overlay, once per headset frame."""
    if not View.active:
        return []
    found = ring_lines(aims, make_batch, ring_hands(View.stroke_hand, View.sizing), View.diameter, View.colour)
    if len(View.path) > 1:
        if _batches["count"] != len(View.path):
            _batches.update(path=make_batch([p for pair in zip(View.path, View.path[1:]) for p in pair]), count=len(View.path))
        found.append((_batches["path"], View.colour, WIDTH + 1, Matrix.Identity(4), True))
    return found


def ring_lines(aims, make_batch, hands, diameter, colour):
    """The brush ball at each of `hands`' tool point: two rings (the select bubble draws the same)."""
    if _batches["ring"] is None:
        _batches["ring"] = make_batch(_unit_circle())
    found, context = [], bpy.context
    for hand in hands:
        rotation = aims[HANDS.index(hand)][1]
        location = tool_point(context, context.window_manager.xr_session_state, hand)
        for turn in (Quaternion(), Quaternion((1, 0, 0), math.pi / 2)):     # two rings: the brush is a ball
            found.append((_batches["ring"], colour, WIDTH,
                          Matrix.LocRotScale(location, rotation @ turn, Vector((diameter,) * 3)), True))
    return found


def colour_of(invert, smooth):
    return SMOOTH if smooth else INVERT if invert else NORMAL


def clear():
    View.active = View.sizing = False
    View.stroke_hand, View.path = None, []
    _batches.update(ring=None, path=None, count=-1)
