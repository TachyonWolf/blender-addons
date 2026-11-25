# SPDX-License-Identifier: GPL-3.0-or-later
"""Grease Pencil drawing without bpy: the radius range, the swatch colour of a material, the layer pager, and the
colours of a new Grease Pencil object. Tested headless."""

RADIUS_RANGE_CM = (0.1, 5.0)        # stroke radius on the desk's slider (Blender's own default radius is 1 cm)
MIN_POINT_DISTANCE = 0.005          # m: finer than Annotate (a drawing wants smoother curves than a note)
MAX_SWATCHES = 8                    # one row of material swatches on the Tools page
LAYER_NAME = "Layer"
OBJECT_NAME = "VR Grease Pencil"


def srgb_hex(linear_rgb):
    """The '#rrggbb' of a linear colour (what a material's colour is stored as), for a swatch."""
    parts = []
    for value in linear_rgb[:3]:
        value = min(1.0, max(0.0, value))
        encoded = value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
        parts.append(round(encoded * 255))
    return "#%02x%02x%02x" % tuple(parts)


def linear_rgb(code):
    """The linear colour of a '#rrggbb' (the way to store it in a material)."""
    parts = []
    for index in (1, 3, 5):
        value = int(code[index:index + 2], 16) / 255.0
        parts.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return tuple(parts)


def step_index(index, count, step):
    """The layer index after `step` (+1 / -1) steps, held at both ends (no wrap)."""
    return min(count - 1, max(0, index + step)) if count else 0


def radius_from_cm(value):
    return min(RADIUS_RANGE_CM[1], max(RADIUS_RANGE_CM[0], value)) / 100.0
