# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the tool gun (three shaded boxes) and the Measure line in the headset. update() builds the batches once per
session tick (overlay.sync), only when they change; draw() runs once per eye inside overlay.draw. Nothing runs while the
gun is away."""
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import shape_math, tool_gun
from .gun_state import STATE

BODY, GRIP, MUZZLE = (0.80, 0.83, 0.87), (0.24, 0.30, 0.38), (0.50, 0.82, 1.0)
PARTS = (((-0.016, -0.018, -0.12), (0.016, 0.022, 0.06), BODY), ((-0.013, -0.11, 0.015), (0.013, -0.018, 0.05), GRIP),
         ((-0.009, -0.009, -0.16), (0.009, 0.009, -0.12), MUZZLE))          # (min, max, colour), metres, -Z = where it aims
SHADES = (0.75, 0.75, 0.55, 1.0, 0.65, 0.85)                                # faces -X, +X, -Y, +Y, -Z, +Z
LINE_COLOUR, LINE_WIDTH = (1.0, 0.9, 0.45, 0.95), 3.0
_batches = {"gun": None, "line": None, "version": -1}


def visible():
    return tool_gun.GUN.shown


def box_triangles(low, high):
    """[(face index, 6 points)] of a box."""
    faces = []
    for axis in range(3):
        for end, value in enumerate((low[axis], high[axis])):
            second, third = (axis + 1) % 3, (axis + 2) % 3
            corners = []
            for pick_second, pick_third in ((low, low), (high, low), (high, high), (low, high)):
                point = [0.0, 0.0, 0.0]
                point[axis], point[second], point[third] = value, pick_second[second], pick_third[third]
                corners.append(tuple(point))
            faces.append((axis * 2 + end, [corners[index] for index in (0, 1, 2, 0, 2, 3)]))
    return faces


def update():
    if not visible():
        return
    if _batches["gun"] is None:
        points, colours = [], []
        for low, high, colour in PARTS:
            for face, corners in box_triangles(low, high):
                points += corners
                colours += [(*(value * SHADES[face] for value in colour), 1.0)] * len(corners)
        _batches["gun"] = batch_for_shader(gpu.shader.from_builtin('SMOOTH_COLOR'), 'TRIS', {"pos": points, "color": colours})
    if _batches["version"] != STATE.measured_version:
        _batches["version"] = STATE.measured_version
        start, end = STATE.measured.start, STATE.measured.end
        _batches["line"] = None if end is None else batch_for_shader(
            gpu.shader.from_builtin('UNIFORM_COLOR'), 'LINES', {"pos": [tuple(start), tuple(end)]})


def tags(state):
    """The name-tag entries of this frame: the measured distance."""
    measured = STATE.measured
    if not visible() or measured.end is None:
        return []
    base, right, up, height = shape_math.tag_frame((measured.start + measured.end) / 2, Vector(state.viewer_pose_location))
    return [(measured.text, base, right, up, height)]


def draw():
    if not visible():
        return
    batch, line = _batches["gun"], _batches["line"]
    if batch is not None:
        shader = gpu.shader.from_builtin('SMOOTH_COLOR')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.depth_mask_set(True)
        gpu.state.blend_set('NONE')
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(tool_gun.GUN.matrix())
            batch.draw(shader)
        finally:
            gpu.matrix.pop()
        gpu.state.depth_test_set('NONE')
    if line is not None and STATE.measured.end is not None:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        shader.bind()
        shader.uniform_float("color", LINE_COLOUR)
        gpu.state.line_width_set(LINE_WIDTH)
        line.draw(shader)
        gpu.state.line_width_set(1.0)
