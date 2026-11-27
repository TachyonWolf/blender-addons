# SPDX-License-Identifier: GPL-3.0-or-later
"""Our small XYZ axis at each hand (DESIGN "Hand marker"), drawn at the fingertip point where the laser starts, `hand_marker`
long (hand_marker_math.length), plus a half-size one at the palm grab point while the active grab mode picks with the palm (its order, grab_order.py). The GPU buffer is built once, in `update()` from the session tick (overlay.sync), never in the
draw callback; `draw()` only binds it."""
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import hand_marker_math as marker_math, settings
from .action_map import HANDS
from .hands import aim_pose, drawn_hand_pose, palm_in_use, palm_point
from .runtime import RUNTIME
from .size_state import SIZE

LINE_WIDTH = 3.0
PALM_MARK_SCALE = 0.5      # the palm grab point's axis, against the fingertip one
_batch = [None]
_matrices = []         # [Matrix] per hand, worked out on the first eye of a frame


def visible():
    return RUNTIME.active


def update():
    """Once per tick: build the axis the first time it is wanted; free it when the session is over."""
    if not visible():
        clear()
    elif _batch[0] is None:
        points, colours = marker_math.axis_vertices()
        _batch[0] = batch_for_shader(gpu.shader.from_builtin('FLAT_COLOR'), 'LINES', {"pos": points, "color": colours})


def clear():
    _batch[0] = None
    _matrices.clear()


def draw(new_frame, context, state):
    """One eye (inside overlay.draw): the axis at each hand's aim point (where the laser starts), `hand_marker` metres long (scaled with Your size)."""
    if state is None or _batch[0] is None:
        return
    if new_frame:
        scale = marker_math.length(settings.get("hand_marker")) * SIZE.factor
        _matrices[:] = [Matrix.LocRotScale(*aim_pose(context, state, index), (scale,) * 3) for index in range(len(HANDS))]
        if palm_in_use():       # the same axis, half as long, marks the palm grab point while it is active
            for index, hand in enumerate(HANDS):
                location, rotation = drawn_hand_pose(context, state, index)
                _matrices.append(Matrix.LocRotScale(palm_point(location, rotation, hand), rotation, (scale * PALM_MARK_SCALE,) * 3))
    shader = gpu.shader.from_builtin('FLAT_COLOR')
    shader.bind()
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(LINE_WIDTH)
    for matrix in _matrices:
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(matrix)
            _batch[0].draw(shader)
        finally:
            gpu.matrix.pop()
    gpu.state.line_width_set(1.0)
