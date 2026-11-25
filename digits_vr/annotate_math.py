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
