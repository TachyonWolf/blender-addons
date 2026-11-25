# SPDX-License-Identifier: GPL-3.0-or-later
"""The name tag floating above what you point at (hover), on an upright quad that faces the head.

All tags share ONE text image (an atlas: one row per name), created once like the desk's screen. Creating a new
GPU image for every new name in the middle of an eye's drawing flashed white over the view (2026-11-25), so now:
- the atlas is made once; a new name is drawn into a free row (least recently used row is reused);
- nothing is ever freed during a frame (the atlas is freed only by clear(), at the session end);
- the drawing state (viewport, blend, depth) is saved and put back around the row render;
- a tag whose size or direction comes out broken, or bigger than MAX_TAG_SIZE, is not drawn.
Per frame: one matrix and one quad draw per tag; nothing while you point at nothing."""
import math
from collections import OrderedDict

import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

FONT = 0
PIXEL_HEIGHT = 56
FONT_SIZE = 36
PADDING = 18
ATLAS_WIDTH = 720           # = the widest tag in pixels
ATLAS_ROWS = 32
ATLAS_HEIGHT = PIXEL_HEIGHT * ATLAS_ROWS
MAX_CHARS = 48
MAX_TAG_SIZE = 3.0          # metres: a tag edge longer than this is a broken frame, skip it
BACKGROUND = (0.04, 0.07, 0.12, 0.78)
TEXT = (0.92, 0.97, 1.0, 1.0)

_atlas = None               # GPUOffScreen(ATLAS_WIDTH, ATLAS_HEIGHT), made on first use inside a draw callback
_rows = OrderedDict()       # label -> (row, width in pixels, batch with this row's texture coordinates)
_image_shader = None
_flat_shader = None


def _label(name):
    return name if len(name) <= MAX_CHARS else name[:MAX_CHARS - 1] + "…"


def _shaders():
    global _image_shader, _flat_shader
    if _image_shader is None:
        _image_shader = gpu.shader.from_builtin('IMAGE')
        _flat_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _image_shader, _flat_shader


def _row_batch(row, width):
    """A unit quad (0..1 x 0..1) showing this row's part of the atlas."""
    image_shader, _flat = _shaders()
    u_right = width / ATLAS_WIDTH
    v_bottom, v_top = row * PIXEL_HEIGHT / ATLAS_HEIGHT, (row + 1) * PIXEL_HEIGHT / ATLAS_HEIGHT
    return batch_for_shader(image_shader, 'TRI_FAN', {
        "pos": ((0, 0), (1, 0), (1, 1), (0, 1)),
        "texCoord": ((0, v_bottom), (u_right, v_bottom), (u_right, v_top), (0, v_top))})


def _render_row(row, label, width):
    """Draw one name into its atlas row. Only inside a draw callback; restores the state it touches."""
    global _atlas
    if _atlas is None:
        _atlas = gpu.types.GPUOffScreen(ATLAS_WIDTH, ATLAS_HEIGHT)
    _image, flat_shader = _shaders()
    viewport = gpu.state.viewport_get()
    blend, depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    bottom = row * PIXEL_HEIGHT
    with _atlas.bind():
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_matrix(Matrix.Identity(4))
            gpu.matrix.load_projection_matrix(Matrix(((2 / ATLAS_WIDTH, 0, 0, -1), (0, 2 / ATLAS_HEIGHT, 0, -1),
                                                      (0, 0, -1, 0), (0, 0, 0, 1))))
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
            # overwrite the whole row (no clear of the atlas: other rows keep their names)
            rect = batch_for_shader(flat_shader, 'TRI_FAN', {"pos": ((0, bottom), (ATLAS_WIDTH, bottom),
                                                                     (ATLAS_WIDTH, bottom + PIXEL_HEIGHT),
                                                                     (0, bottom + PIXEL_HEIGHT))})
            flat_shader.bind()
            flat_shader.uniform_float("color", BACKGROUND)
            rect.draw(flat_shader)
            gpu.state.blend_set('ALPHA')
            blf.size(FONT, FONT_SIZE)
            blf.color(FONT, *TEXT)
            blf.position(FONT, PADDING, bottom + (PIXEL_HEIGHT - FONT_SIZE) / 2 + 8, 0)
            blf.draw(FONT, label)
    gpu.state.viewport_set(*viewport)
    gpu.state.blend_set(blend)
    gpu.state.depth_test_set(depth)


def _entry(label):
    """(row, width, batch) for a label; draws it into a row the first time (reusing the least recently used row)."""
    if label in _rows:
        _rows.move_to_end(label)
        return _rows[label]
    blf.size(FONT, FONT_SIZE)
    width = int(min(ATLAS_WIDTH, blf.dimensions(FONT, label)[0] + 2 * PADDING))
    if len(_rows) >= ATLAS_ROWS:
        row = _rows.popitem(last=False)[1][0]          # reuse the oldest row (nothing is freed)
    else:
        row = len(_rows)
    _render_row(row, label, width)
    _rows[label] = (row, width, _row_batch(row, width))
    return _rows[label]


def matrices(tags):
    """[(batch, model matrix)] of tags [(label, bottom-centre, right, up, height)] (worked out once per frame).
    A tag with a broken or oversized frame is left out. Plain float maths: it runs every headset frame."""
    out = []
    for name, base, right, up, _height in tags:
        if not math.isfinite(sum(base) + sum(right) + sum(up)):      # NaN / inf anywhere spreads into the sum
            continue
        _row, width, batch = _entry(_label(name))
        scale = width / PIXEL_HEIGHT
        x0, x1, x2 = right[0] * scale, right[1] * scale, right[2] * scale
        x_length = math.sqrt(x0 * x0 + x1 * x1 + x2 * x2)
        up_length = math.sqrt(up[0] * up[0] + up[1] * up[1] + up[2] * up[2])
        if not (1e-6 < x_length < MAX_TAG_SIZE and 1e-6 < up_length < MAX_TAG_SIZE):
            continue
        model = Matrix(((x0, up[0], 0, base[0] - x0 / 2), (x1, up[1], 0, base[1] - x1 / 2),
                        (x2, up[2], 1, base[2] - x2 / 2), (0, 0, 0, 1)))
        out.append((batch, model))
    return out


def draw(prepared):
    """Draw the prepared tags (matrices()) for the current eye, over everything."""
    if not prepared or _atlas is None:
        return
    image_shader, _flat = _shaders()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    image_shader.bind()
    image_shader.uniform_sampler("image", _atlas.texture_color)
    for batch, model in prepared:
        gpu.matrix.push()       # push / pop: cheaper than the push_pop() context; try keeps the stack balanced
        try:
            gpu.matrix.multiply_matrix(model)
            batch.draw(image_shader)
        finally:
            gpu.matrix.pop()


def clear():
    """Free the atlas (session end only)."""
    global _atlas
    if _atlas is not None:
        _atlas.free()
        _atlas = None
    _rows.clear()
