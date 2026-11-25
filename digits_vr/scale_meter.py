# SPDX-License-Identifier: GPL-3.0-or-later
"""The scale meter [user, 2026-11-25]: a readout of your size ("0.5x") and a ruler of REAL lengths at that size, in front
of you and below eye level, level with the floor. Shown while the two-hand gesture scales you, and always while the View
tab's Scale meter toggle is on. VR only (drawn by overlay.py through the XR draw handler). Off = visible() is two
cheap reads and nothing else runs: no batch, no tags. The numbers are scale_math's (tested headless).

The ruler is drawn in world units, `RULER_TICKS * step` long, so it looks about 30 cm long to you at any size and its
labels tell the real length it spans."""
import math

from mathutils import Matrix, Quaternion, Vector

import gpu
from gpu_extras.batch import batch_for_shader

from . import scale_math, settings, shape_math
from .size_state import SIZE

COLOUR = (1.0, 0.9, 0.45, 0.95)
WIDTH = 3.0
FORWARD, BELOW = 0.45, 0.32       # m (physical): the ruler's place in front of and below your head
TICK = 0.06                       # tick height, as a part of the ruler's length
_batch = None                     # the unit ruler along +X (0..1), made once


def visible():
    return SIZE.gesturing and settings.get("scale_meter")       # only while you scale [user, 2026-11-25: not always]


def _unit_batch():
    global _batch
    if _batch is None:
        steps = scale_math.RULER_TICKS
        points = [(0, 0, 0), (1, 0, 0)]
        for index in range(steps + 1):
            points += [(index / steps, 0, 0), (index / steps, 0, TICK)]
        _batch = batch_for_shader(gpu.shader.from_builtin('UNIFORM_COLOR'), 'LINES', {"pos": points})
    return _batch


def frame(state):
    """(line item for overlay's frame lines or None, name-tag entries) for this frame."""
    head = Vector(state.viewer_pose_location)
    ahead = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
    flat = math.hypot(ahead.x, ahead.y)
    if flat < 1e-3 or not math.isfinite(flat + head.length):
        return None, []                         # looking straight up / down: no sensible place
    forward = Vector((ahead.x / flat, ahead.y / flat, 0.0))
    right = Vector((forward.y, -forward.x, 0.0))
    size = SIZE.factor
    step = scale_math.ruler_step(size)
    length = step * scale_math.RULER_TICKS
    centre = head + forward * (FORWARD * size) + Vector((0.0, 0.0, -BELOW * size))
    start = centre - right * (length / 2)
    rotation = Matrix((right, forward, Vector((0.0, 0.0, 1.0)))).transposed().to_quaternion()
    model = Matrix.LocRotScale(start, rotation, (length, length, length))
    tags = []
    for text, point in ((scale_math.size_label(size), start), (scale_math.length_label(length), start + right * length)):
        base, tag_right, up, height = shape_math.tag_frame(point, head)
        tags.append((text, base, tag_right, up, height))
    return (_unit_batch(), COLOUR, WIDTH, model, True), tags


def clear():
    global _batch
    _batch = None
