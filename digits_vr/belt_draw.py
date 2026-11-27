# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the tool belt in the headset: a see-through green orb at each slot [user, 2026-11-25] (pocketed models are real objects, shrunk, in the scene).
update() runs once per session tick (overlay.sync) and builds everything that needs the GPU; draw() runs once per eye
and only draws (no buffers are built there). Nothing runs while the belt is off or hidden."""
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import belt_math
from .belt_state import BELT
from .size_state import SIZE

import math

SLOT_COLOUR = (0.1, 0.6, 0.25, 0.35)      # a free slot: darker, more solid green [user, 2026-11-25]
FULL_COLOUR = (0.1, 0.6, 0.25, 0.6)       # a slot holding something
PINNED_COLOUR = (1.0, 0.85, 0.15, 0.6)    # a pinned slot, full or empty (B) [user, 2026-11-25]
READY_COLOUR = (0.25, 0.55, 1.0, 0.55)    # blue: let go now and it goes in [user, 2026-11-25]
TOOL_POINT_COLOUR = (1.0, 0.7, 0.42, 0.7)  # orange ball at each tool point while Options > Body offsets is open [user, 2026-11-26]
TOOL_POINT_SIZE = 0.02                     # m across, times Your size
RINGS, SEGMENTS = 8, 16
_gpu = {"shader": None, "orb": None}
_entries = []       # [(batch, colour, model matrix)] for this tick


def visible():
    return BELT.running and BELT.visible


def _orb_triangles():
    """A unit-diameter sphere as triangles."""
    def point(ring, segment):
        polar, around = math.pi * ring / RINGS, 2.0 * math.pi * segment / SEGMENTS
        return (0.5 * math.sin(polar) * math.cos(around), 0.5 * math.sin(polar) * math.sin(around), 0.5 * math.cos(polar))
    triangles = []
    for ring in range(RINGS):
        for segment in range(SEGMENTS):
            a, b = point(ring, segment), point(ring, segment + 1)
            c, d = point(ring + 1, segment), point(ring + 1, segment + 1)
            triangles += [a, c, d, a, d, b]
    return triangles


def _batches():
    if _gpu["shader"] is None:
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        _gpu.update(shader=shader, orb=batch_for_shader(shader, 'TRIS', {"pos": _orb_triangles()}))
    return _gpu["orb"]


def _colour(slot):
    if slot.pinned is not None:
        return PINNED_COLOUR
    if slot.free():
        return READY_COLOUR if slot.index in BELT.ready else SLOT_COLOUR
    return FULL_COLOUR


def update():
    _entries.clear()
    if not visible():
        return
    orb = _batches()
    size = BELT.size_factor()
    for slot in BELT.slots:
        matrix = BELT.slot_matrix(slot.index)
        _entries.append((orb, _colour(slot), matrix @ Matrix.Scale(belt_math.SLOT_HALF * 2 * size, 4)))
    for point in BELT.tool_points:
        _entries.append((orb, TOOL_POINT_COLOUR, Matrix.Translation(point) @ Matrix.Scale(TOOL_POINT_SIZE * SIZE.factor, 4)))


def draw():
    if not _entries:
        return
    shader = _gpu["shader"]
    shader.bind()
    # On top of the scene: a size change about your head leaves your body (and the belt) under
    # the floor when you grow (at 10x the belt hangs 7 m of the world under your eyes), so a depth-tested belt was hidden.
    gpu.state.depth_test_set('NONE')
    gpu.state.depth_mask_set(False)          # see-through: never hides what is behind it
    gpu.state.blend_set('ALPHA')
    for batch, colour, model in _entries:
        shader.uniform_float("color", colour)
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(model)
            batch.draw(shader)
        finally:
            gpu.matrix.pop()
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def clear():
    _entries.clear()
