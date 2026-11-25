# SPDX-License-Identifier: GPL-3.0-or-later
"""The hand marker's size setting without bpy (DESIGN "Hand marker"): our small XYZ axis
at the fingertip point where the laser starts; 0 = the tiny default size. Blender's own marker is always off in VR
(hand_state.changes) [user, 2026-11-25]. Tested headless."""

DEFAULT = 0.0                       # metres: the stored value of "the default size"
TINY = 0.015                        # m: that default size
RANGE_CM = (0.5, 10.0)              # the desk slider
AXIS_COLOURS = ((1.0, 0.25, 0.25, 1.0), (0.35, 0.9, 0.35, 1.0), (0.3, 0.5, 1.0, 1.0))    # X red, Y green, Z blue
DEFAULT_TEXT = "Tiny"


def is_custom(size):
    return size > 0.0


def length(size):
    """The axis length in metres for the stored size."""
    return size if is_custom(size) else TINY


def valid(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        value == 0 or RANGE_CM[0] / 100.0 - 1e-9 <= value <= RANGE_CM[1] / 100.0 + 1e-9)


def slider_cm(size):
    """(slider value in cm, text shown instead of the value or "")."""
    if not is_custom(size):
        return RANGE_CM[0], DEFAULT_TEXT
    return round(size * 100.0, 1), ""


def axis_vertices():
    """Six points (a unit axis of three lines from the origin) and their colours, for one line batch."""
    points, colours = [], []
    for index, colour in enumerate(AXIS_COLOURS):
        tip = [0.0, 0.0, 0.0]
        tip[index] = 1.0
        points += [(0.0, 0.0, 0.0), tuple(tip)]
        colours += [colour, colour]
    return points, colours
