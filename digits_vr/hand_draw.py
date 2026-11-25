# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the simple hands in the headset (DESIGN "Keyboard and simple hand"): per hand a palm block and 3 capsules per
finger, light grey with a subtle darker edge, in the XR draw region, depth tested. Called from overlay.draw.

Cheap: the capsule template is built once; a hand's whole mesh (fill + edge) is built with a few numpy calls only when
its curls change by a step (cached per curl key, at most CACHE_SIZE kept), so a still hand is two draw calls per eye
(four with the edge) and nothing else. The first eye of a frame works out the two grip matrices, the second reuses them."""
import math

import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import hand_model, hand_state
from .action_map import HANDS
from .hands import drawn_hand_pose
from .perf import TIMINGS
from .size_state import SIZE

FILL = (0.82, 0.84, 0.87)
EDGE = (0.20, 0.23, 0.28)
EDGE_WIDTH = 0.0016                  # metres: how far the edge shell sits outside the hand
LIGHT = (0.35, 0.8, 0.5)
AROUND, LATITUDES = 6, (-90.0, -45.0, 0.0, 0.0, 45.0, 90.0)
CACHE_SIZE = 64

_template = None                     # (unit normals (V, 3), side flags (V, 1), triangle indices (T, 3))
_cache = {}                          # (side, curl key) -> (fill batch, edge batch)
_shader = None
_frame = []                          # [(fill batch, edge batch, matrix)] worked out on the first eye of a frame


def _capsule_template():
    """A capsule as rings: the unit normals of its vertices, which end each belongs to (0 start, 1 end), triangles."""
    normals, sides = [], []
    for latitude, side in zip(LATITUDES, (0, 0, 0, 1, 1, 1)):
        ring = math.cos(math.radians(latitude))
        for step in range(AROUND):
            angle = 2.0 * math.pi * step / AROUND
            normals.append((ring * math.cos(angle), ring * math.sin(angle), math.sin(math.radians(latitude))))
            sides.append((float(side),))
    triangles = []
    for ring_index in range(len(LATITUDES) - 1):
        for step in range(AROUND):
            low, low_next = ring_index * AROUND + step, ring_index * AROUND + (step + 1) % AROUND
            high, high_next = low + AROUND, low_next + AROUND
            triangles += [(low, low_next, high_next), (low, high_next, high)]
    return np.array(normals, dtype=np.float32), np.array(sides, dtype=np.float32), np.array(triangles, dtype=np.int32)


def _basis(start, end):
    """A rotation (rows = the capsule's x, y, z axes) turning the template's +Z along start -> end."""
    axis = np.array(end) - np.array(start)
    axis = axis / np.linalg.norm(axis)
    helper = np.array((0.0, 1.0, 0.0)) if abs(axis[1]) < 0.9 else np.array((1.0, 0.0, 0.0))
    first = np.cross(helper, axis)
    first = first / np.linalg.norm(first)
    return np.array((first, np.cross(axis, first), axis))


def _octagon(centre_z, half_y, half_z, x, shrink=1.0):
    """The 8 corners (CCW seen from +X) of a flat octagon in the Y-Z plane at `x`."""
    hy, hz, cut = half_y * shrink, half_z * shrink, hand_model.PALM_CORNER * shrink
    flat = ((hy, -hz + cut), (hy, hz - cut), (hy - cut, hz), (-hy + cut, hz), (-hy, hz - cut), (-hy, -hz + cut),
            (-hy + cut, -hz), (hy - cut, -hz))
    return [(x, y, centre_z + z) for y, z in flat]


def _prism(centre_z, half_y, half_z):
    """Polygons (lists of points, faces turned outwards) of one beveled octagonal prism."""
    half_x, bevel = hand_model.PALM_HALF_THICKNESS, hand_model.PALM_BEVEL
    shrink = 1.0 - 1.4 * bevel / min(half_y, half_z)
    rings = [_octagon(centre_z, half_y, half_z, x, scale) for x, scale in
             ((half_x, shrink), (half_x - bevel, 1.0), (-half_x + bevel, 1.0), (-half_x, shrink))]
    polygons = [rings[0], rings[3]]
    for low, high in zip(rings, rings[1:]):
        polygons += [[low[index], low[(index + 1) % 8], high[(index + 1) % 8], high[index]] for index in range(8)]
    centre = (0.0, 0.0, centre_z)
    outward = []
    for polygon in polygons:
        mid = [sum(point[axis] for point in polygon) / len(polygon) for axis in range(3)]
        normal = np.cross(np.array(polygon[1]) - polygon[0], np.array(polygon[2]) - polygon[0])
        outward.append(polygon if np.dot(normal, np.array(mid) - centre) > 0 else polygon[::-1])
    return outward


_palm = None                         # (positions, normals, triangles) of the palm, built once


def _palm_mesh():
    """The whole palm as one flat-shaded mesh: palm and wrist."""
    global _palm
    if _palm is None:
        positions, normals, triangles = [], [], []
        for part in hand_model.PALM_PARTS:
            for polygon in _prism(*part):
                normal = np.cross(np.array(polygon[1]) - polygon[0], np.array(polygon[2]) - polygon[0])
                normal = normal / np.linalg.norm(normal)
                base = len(positions)
                positions += polygon
                normals += [normal] * len(polygon)
                triangles += [(base, base + step, base + step + 1) for step in range(1, len(polygon) - 1)]
        _palm = (np.array(positions, dtype=np.float32), np.array(normals, dtype=np.float32), np.array(triangles, dtype=np.int32))
    return _palm


def _mesh(side, curls):
    """(fill batch, edge batch) of one hand pose: every capsule and the palm in one mesh each."""
    global _template
    if _template is None:
        _template = _capsule_template()
    normals, sides, triangles = _template
    parts = hand_model.segments(side, curls)
    starts = np.array([part[0] for part in parts], dtype=np.float32)[:, None, :]
    deltas = np.array([part[1] for part in parts], dtype=np.float32)[:, None, :] - starts
    radii = np.array([part[2] for part in parts], dtype=np.float32)[:, None, None]
    bases = np.array([_basis(part[0], part[1]) for part in parts], dtype=np.float32)
    world_normals = np.einsum('vj,sji->svi', normals, bases)             # template axes -> hand axes
    positions = world_normals * radii + starts + sides[None] * deltas
    count = len(parts) * len(normals)
    palm_positions, palm_normals, palm_triangles = _palm_mesh()
    all_positions = np.concatenate((positions.reshape(-1, 3), palm_positions))
    all_normals = np.concatenate((world_normals.reshape(-1, 3), palm_normals))
    all_triangles = np.concatenate(((triangles[None] + (np.arange(len(parts)) * len(normals))[:, None, None]).reshape(-1, 3),
                                    palm_triangles + count))
    light = np.array(LIGHT, dtype=np.float32)
    light = light / np.linalg.norm(light)
    shade = (0.55 + 0.45 * np.clip(all_normals @ light, 0.0, 1.0))[:, None]
    fill_colour = np.concatenate((np.array(FILL, dtype=np.float32)[None] * shade, np.ones_like(shade)), axis=1)
    edge_colour = np.tile(np.array((*EDGE, 1.0), dtype=np.float32), (len(all_positions), 1))
    shader = _smooth()
    fill = batch_for_shader(shader, 'TRIS', {"pos": all_positions, "color": fill_colour}, indices=all_triangles.astype(np.uint32))
    edge = batch_for_shader(shader, 'TRIS', {"pos": all_positions + all_normals * EDGE_WIDTH, "color": edge_colour},
                            indices=all_triangles.astype(np.uint32))
    return fill, edge


def _smooth():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    return _shader


def _batches(hand):
    key = (1.0 if hand == HANDS[1] else -1.0, hand_model.quantized(hand_state.CURLS[hand]))
    if key not in _cache:
        if len(_cache) >= CACHE_SIZE:
            _cache.clear()
        _cache[key] = _mesh(key[0], hand_model.curls_from_key(key[1]))
    return _cache[key]


def visible():
    return hand_state.enabled()


def clear():
    """The session ended (or the hands were switched off): free the cached meshes."""
    _cache.clear()
    _frame.clear()


def draw(new_frame, context, state):
    """One eye: both hands (inside overlay.draw); timed as "hands" (nested in "draw")."""
    with TIMINGS.measure("hands"):
        _draw(new_frame, context, state)


def _draw(new_frame, context, state):
    if state is None or not hand_state.enabled():
        if _frame:
            clear()
        return
    if new_frame:
        hand_state.animate()
        _frame[:] = []
        scale = (SIZE.factor,) * 3
        for index, hand in enumerate(HANDS):
            matrix = Matrix.LocRotScale(*drawn_hand_pose(context, state, index), scale)
            _frame.append((*_batches(hand), matrix))
    shader = _smooth()
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(True)
    gpu.state.blend_set('NONE')
    for fill, edge, matrix in _frame:
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(matrix)
            gpu.state.face_culling_set('FRONT')
            edge.draw(shader)
            gpu.state.face_culling_set('BACK')
            fill.draw(shader)
        finally:
            gpu.matrix.pop()
    gpu.state.face_culling_set('NONE')
    gpu.state.depth_test_set('NONE')
