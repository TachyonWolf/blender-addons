# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws Blender's own UI icons (blender_icons.py) on the VR panels: one atlas texture, made once when the session starts
(panels.start) and dropped at its end, never in a draw callback. Icons are drawn tinted (IMAGE_COLOR shader), one
batch per colour, into a panel's offscreen when it renders, or as a quad beside a panel (the Pin)."""
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

from . import asset_draw, blender_icons

_state = {"texture": None, "theme": None, "shader": None, "pixels": None}


def load():
    """Read the atlas and the theme's icon colours, make the texture (session start). A missing atlas is logged: the
    panels then show no icons, everything else works. Nothing on the GPU in a headless Blender."""
    _state["theme"] = _theme_tints()
    if _state["texture"] is not None or bpy.app.background:
        return
    image = None
    try:
        image = bpy.data.images.load(blender_icons.ATLAS)
        width, height = image.size
        values = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(values)
        pixels = (values.reshape(height, width, 4) * 255.0 + 0.5).astype(np.uint8)
        texture = asset_draw.texture_from_pixels(pixels)
        texture.filter_mode(True)          # drawn at half the cell size, on whole pixels: a clean 2 x 2 average
        _state["texture"], _state["pixels"] = texture, pixels
    except (RuntimeError, ValueError, SystemError) as error:
        print(f"digits_vr: Blender icons not loaded: {error}")
    finally:
        if image is not None:
            bpy.data.images.remove(image)


def free():
    _state["texture"] = _state["theme"] = _state["pixels"] = None


def cell_pixels(name):
    """The icon's cell of the atlas as a (CELL, CELL, 4) uint8 array, bottom row first (None before the atlas is loaded):
    for a texture of its own (the Primitives tiles)."""
    if _state["pixels"] is None:
        return None
    left, top = blender_icons.cell_origin(name)
    rows = _state["pixels"].shape[0]
    return _state["pixels"][rows - top - blender_icons.CELL:rows - top, left:left + blender_icons.CELL]


def _theme_tints():
    """{OBJECT: rgba, COLLECTION: rgba} from the user's theme (what the desktop Outliner shows), else Blender's defaults."""
    try:
        interface = bpy.context.preferences.themes[0].user_interface
        return {kind: tuple(getattr(interface, attribute)) for kind, attribute in blender_icons.THEME_TINTS.items()}
    except (AttributeError, IndexError):
        return dict(blender_icons.DEFAULT_TINTS)


def tint(name, text_colour):
    return blender_icons.tint(name, text_colour, _state["theme"])


def ready():
    return _state["texture"] is not None


def _shader():
    if _state["shader"] is None:
        _state["shader"] = gpu.shader.from_builtin('IMAGE_COLOR')
    return _state["shader"]


def _corners(name):
    u0, v0, u1, v1 = blender_icons.uv_rect(name)
    return ((u0, v0), (u1, v0), (u1, v1), (u0, v1))


def draw(spots, height):
    """Inside a panel's offscreen (pixel projection, bottom-left origin): `spots` = (name, x, y, size, rgba), x / y = the
    icon's top-left pixel (top-left origin). One batch per colour."""
    if not spots or not ready():
        return
    by_colour = {}
    for name, x, y, size, colour in spots:
        bottom, top = height - (y + size), height - y
        corner_uvs = _corners(name)
        quad = ((x, bottom), (x + size, bottom), (x + size, top), (x, top))
        positions, uvs = by_colour.setdefault(tuple(colour), ([], []))
        for index in (0, 1, 2, 0, 2, 3):
            positions.append(quad[index])
            uvs.append(corner_uvs[index])
    shader = _shader()
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_sampler("image", _state["texture"])
    for colour, (positions, uvs) in by_colour.items():
        shader.uniform_float("color", colour)
        batch_for_shader(shader, 'TRIS', {"pos": positions, "texCoord": uvs}).draw(shader)


def quad_batch(name, corners):
    """Batch of one icon on a quad (4 corners, bottom-left first, any space): build it once, draw it with draw_quad."""
    return asset_draw.textured_quad(_shader(), corners, _corners(name))


def draw_quad(batch, colour):
    if batch is None or not ready():
        return
    shader = _shader()
    shader.bind()
    shader.uniform_sampler("image", _state["texture"])
    shader.uniform_float("color", colour)
    batch.draw(shader)
