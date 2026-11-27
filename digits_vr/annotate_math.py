# SPDX-License-Identifier: GPL-3.0-or-later
"""Annotate (M6) without bpy: the colour swatches, the thickness range, how far apart stroke points sit, and the layer
name a colour + thickness draws on. Tested headless."""
import math

# (id, label, hex colour): the desk's swatches
PALETTE = (('red', "Red", "#ff4a4a"), ('orange', "Orange", "#ff9f40"), ('yellow', "Yellow", "#ffe03d"),
           ('green', "Green", "#4ddf6a"), ('blue', "Blue", "#4aa3ff"), ('white', "White", "#ffffff"))
COLOR_IDS = tuple(identifier for identifier, _label, _code in PALETTE)
THICKNESS_RANGE = (1, 10)           # Blender's annotation layer thickness, in pixels
MIN_POINT_DISTANCE = 0.01           # m: a new point only when the hand moved this far from the last one
RING_PER_PIXEL = 0.004             # m of ring diameter per pixel of thickness (the size gesture's mark; a draft look)
LAYER_PREFIX = "VR "                # our layers: Erase last / Clear all touch only these, never the user's own notes


def far_enough(last_point, point, min_distance=MIN_POINT_DISTANCE):
    """True when `point` is at least `min_distance` from `last_point` (None = no point yet: always)."""
    return last_point is None or math.dist(last_point, point) >= min_distance


def layer_name(color_id, thickness):
    """One layer per colour + thickness (an annotation layer has one colour and one thickness)."""
    label = next(label for identifier, label, _code in PALETTE if identifier == color_id)
    return f"{LAYER_PREFIX}{label} {thickness}"


def is_ours(name):
    return name.startswith(LAYER_PREFIX)


def color_code(color_id):
    return next(code for identifier, _label, code in PALETTE if identifier == color_id)


def ring_diameter(thickness, factor=1.0):
    """The world diameter (m) of the ring mark for a thickness, at your size `factor` (the ring is a mark in your space)."""
    return thickness * RING_PER_PIXEL * factor


def thickness_of_diameter(diameter, factor=1.0):
    """The whole-pixel thickness of a world ring `diameter` at your size `factor`, kept within THICKNESS_RANGE."""
    return min(THICKNESS_RANGE[1], max(THICKNESS_RANGE[0], round(diameter / factor / RING_PER_PIXEL)))
