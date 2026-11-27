# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the Help panel's pictures, lines and dots into its offscreen (help_layout.py places them). Art: Kenney
"Input Prompts" (CC0, images/kenney/License.txt). Blender does not say which controllers are connected, so it is always the
Meta Quest pair. The pictures are read when the panel opens (never in a draw callback) and dropped when it closes."""
import os

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import asset_draw, help_layout as layout
from .panel_layout import ACCENT, ACTIVE, rgba, rounded_outline

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "kenney")
FILES = {layout.LEFT: "controller_quest_touch_plus_left.png", layout.RIGHT: "controller_quest_touch_plus_right.png"}
DOT_RADIUS, LINE_WIDTH = 8, 2.0
TINT = (0.56, 0.69, 0.79)           # the art is white: toned down so the dots and labels stand out
_pixels, _textures = {}, {}


def load():
    """Read the pictures (the panel opens). A missing one is logged and left out: labels and dots still show."""
    for hand, name in FILES.items():
        if hand in _pixels:
            continue
        image = None
        try:
            image = bpy.data.images.load(os.path.join(FOLDER, name))
            width, height = image.size
            values = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(values)
            values = values.reshape(height, width, 4)
            values[:, :, :3] *= TINT
            _pixels[hand] = (values * 255.0).astype(np.uint8)
        except (RuntimeError, ValueError) as error:
            print(f"digits_vr: controller picture not read: {error}")
        finally:
            if image is not None:
                bpy.data.images.remove(image)


def free():
    _pixels.clear()
    _textures.clear()


def draw(widgets, flat, image_shader, height):
    """Inside a panel's offscreen (pixel projection, bottom-left origin): pictures, then lines, then dots."""
    pictures = [widget for widget in widgets if widget.style == layout.ART]
    if not pictures:
        return
    gpu.state.blend_set('ALPHA')
    for widget in pictures:
        hand = widget.id.rsplit("_", 1)[1]
        if hand not in _textures and hand in _pixels:
            _textures[hand] = asset_draw.texture_from_pixels(_pixels[hand])
        if hand in _textures:
            image_shader.bind()
            image_shader.uniform_sampler("image", _textures[hand])
            asset_draw.image_quad(image_shader, widget.x, widget.y, widget.w, widget.h, height).draw(image_shader)
    lines, dots = [], []
    for widget in widgets:
        if widget.style != layout.LINE:
            continue
        end_x, end_y = widget.x + widget.w, widget.y + widget.h
        lines += [(widget.x, height - widget.y), (end_x, height - end_y)]
        outline = [(x, height - y) for x, y in rounded_outline(end_x - DOT_RADIUS, end_y - DOT_RADIUS, 2 * DOT_RADIUS,
                                                              2 * DOT_RADIUS, DOT_RADIUS)]
        for index, point in enumerate(outline):
            dots += [(end_x, height - end_y), point, outline[(index + 1) % len(outline)]]
    if lines:
        flat.bind()
        gpu.state.line_width_set(LINE_WIDTH)
        flat.uniform_float("color", rgba(ACCENT))
        batch_for_shader(flat, 'LINES', {"pos": lines}).draw(flat)
        gpu.state.line_width_set(1.0)
        flat.uniform_float("color", rgba(ACTIVE))
        batch_for_shader(flat, 'TRIS', {"pos": dots}).draw(flat)
