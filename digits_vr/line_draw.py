# SPDX-License-Identifier: GPL-3.0-or-later
"""The one way a small flat-colour line batch is built and drawn in the headset (box_draw, snap_draw)."""
import gpu
from gpu_extras.batch import batch_for_shader

_shader = [None]


def make_batch(points):
    """A LINES batch of `points` (pairs of positions) for `draw_lines`."""
    if _shader[0] is None:
        _shader[0] = gpu.shader.from_builtin('UNIFORM_COLOR')
    return batch_for_shader(_shader[0], 'LINES', {"pos": points})


def draw_lines(batch, colour, width):
    """One eye: `batch` (from make_batch) in `colour`, on top of the scene, `width` pixels wide."""
    shader = _shader[0]
    shader.bind()
    shader.uniform_float("color", colour)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(width)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
