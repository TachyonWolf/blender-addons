# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the running box (3D box or laser rectangle) in the headset. update() builds the line batch once per session
tick (overlay.sync); draw() runs once per eye inside overlay.draw. Nothing runs unless an A + trigger drag is going."""
import gpu
from gpu_extras.batch import batch_for_shader

from .runtime import RUNTIME

COLOUR = (1.0, 0.75, 0.2, 0.95)
WIDTH = 3.0
_state = {"batch": None, "shader": None}


def _boxing():
    return [hand_state.gesture for hand_state in RUNTIME.hands.values()
            if hand_state.gesture is not None and hand_state.gesture.boxing]


def visible():
    return bool(_boxing())


def update():
    boxes = _boxing()
    if not boxes:
        _state["batch"] = None
        return
    if _state["shader"] is None:
        _state["shader"] = gpu.shader.from_builtin('UNIFORM_COLOR')
    lines = [point for box in boxes for point in box.lines().tolist()]
    _state["batch"] = batch_for_shader(_state["shader"], 'LINES', {"pos": lines})


def draw():
    batch = _state["batch"]
    if batch is None:
        return
    shader = _state["shader"]
    shader.bind()
    shader.uniform_float("color", COLOUR)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(WIDTH)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
