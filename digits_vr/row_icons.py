# SPDX-License-Identifier: GPL-3.0-or-later
"""Small vector icons for the Outliner rows (like Blender's Outliner): collection, mesh, armature, empty, camera, light, curve,
grease pencil, other. Each is a few rounded rects in the panel texture's own shape list (`panel_draw.widget_rects`): no
textures, nothing made in a draw callback. Pure Python (no bpy), tested headless."""
from .panel_layout import rgba

ICON_SIZE = 28
COLOURS = {"collection": "#e8e8e8", "mesh": "#ffb257", "armature": "#e8e8e8", "empty": "#e8e8e8", "camera": "#9fd0ff",
           "light": "#ffe27a", "curve": "#7fe0a0", "gpencil": "#b8e86f", "other": "#c0c0c0"}
TYPE_ICONS = {'MESH': "mesh", 'ARMATURE': "armature", 'EMPTY': "empty", 'CAMERA': "camera", 'LIGHT': "light",
              'CURVE': "curve", 'SURFACE': "curve", 'FONT': "curve", 'CURVES': "curve", 'GREASEPENCIL': "gpencil", 'GPENCIL': "gpencil"}
ICONS = tuple(COLOURS)


def icon_for(object_type):
    """The icon name of an object type ("other" for any type without its own)."""
    return TYPE_ICONS.get(object_type, "other")


def icon_rects(icon, x, y, size=ICON_SIZE, alpha=1.0):
    """Rounded rects (x, y, w, h, radius, colour) of `icon` in a `size` box with its top-left at (x, y)."""
    colour = rgba(COLOURS.get(icon, COLOURS["other"]), alpha)
    u = size / 14.0                                    # the icons are drawn on a 14 x 14 grid
    def part(left, top, width, height, radius=0.0):
        return (x + left * u, y + top * u, width * u, height * u, radius * u, colour)
    if icon == "collection":                           # a folder: tab and body
        return [part(1, 2, 6, 3, 1), part(1, 4, 12, 8, 1.5)]
    if icon == "mesh":                                 # a cube seen square-on: outline and a lighter face
        return [part(1, 1, 12, 12, 1.5), (x + 4 * u, y + 4 * u, 6 * u, 6 * u, 0.5 * u, rgba("#0d1824", alpha))]
    if icon == "armature":                             # a bone: a bar with a ball at each end
        return [part(6, 3, 2, 8, 1), part(4.5, 1, 5, 4, 2), part(4.5, 9, 5, 4, 2)]
    if icon == "empty":                                # a plus
        return [part(6, 1, 2, 12, 1), part(1, 6, 12, 2, 1)]
    if icon == "camera":                               # body, lens, top bump
        return [part(1, 4, 12, 8, 2), part(4, 2, 6, 3, 1), (x + 5 * u, y + 6 * u, 4 * u, 4 * u, 2 * u, rgba("#0d1824", alpha))]
    if icon == "light":                                # a bulb with rays
        return [part(4, 4, 6, 6, 3), part(6.5, 0, 1, 3), part(6.5, 11, 1, 3), part(0, 6.5, 3, 1), part(11, 6.5, 3, 1)]
    if icon == "curve":                                # a curve as a stair of balls
        return [part(1, 9, 4, 4, 2), part(4, 5, 4, 4, 2), part(8, 3, 4, 4, 2), part(10, 1, 3, 3, 1.5)]
    if icon == "gpencil":                              # a pencil: long body, a tip
        return [part(3, 2, 4, 9, 1), part(5, 5, 4, 8, 1), part(3, 11, 2, 2, 0.5)]
    return [part(3, 3, 8, 8, 4)]                       # other: a dot
