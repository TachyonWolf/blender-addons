# SPDX-License-Identifier: GPL-3.0-or-later
"""The snap guide lines in the headset: what a snapped grab lines up with (snap_state.Guides). update() builds one small
line batch per session tick when the guides changed; draw() runs once per eye inside overlay.draw. Nothing runs unless a
snap shows."""
import gpu
from gpu_extras.batch import batch_for_shader

from .snap_state import Guides

COLOUR = (0.35, 1.0, 0.55, 0.95)
WIDTH = 2.5
_state = {"batch": None, "shader": None, "version": -1}


def visible():
    return len(Guides.lines) > 0


def update():
    if _state["version"] == Guides.version:
        return
    _state["version"] = Guides.version
    if not len(Guides.lines):
        _state["batch"] = None
        return
    if _state["shader"] is None:
        _state["shader"] = gpu.shader.from_builtin('UNIFORM_COLOR')
    _state["batch"] = batch_for_shader(_state["shader"], 'LINES', {"pos": Guides.lines.reshape(-1, 3).tolist()})


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
