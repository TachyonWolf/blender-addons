# SPDX-License-Identifier: GPL-3.0-or-later
"""Thumbnails of the mesh primitives on the Assets page's Primitives list: small shaded drawings made once with numpy
(no bpy, no gpu), the same pixel layout as a stored asset preview ((height, width, 4) uint8, bottom row first)."""
import numpy as np

SIZE = 128
BASE_COLOR = np.array((0.62, 0.69, 0.80))
LIGHT = np.array((-0.4, 0.6, 0.7)) / np.linalg.norm((-0.4, 0.6, 0.7))
_cache = {}


def _grid():
    axis = np.linspace(-1.0, 1.0, SIZE)
    return np.meshgrid(axis, axis)         # x grows to the right, y upward (row 0 = bottom)


def _lit(normal_x, normal_y, normal_z):
    return np.clip(normal_x * LIGHT[0] + normal_y * LIGHT[1] + normal_z * LIGHT[2], 0.0, 1.0) * 0.75 + 0.25


def _ball(x, y, centre_x, centre_y, radius, facets=0):
    """(mask, shade) of a sphere; `facets` > 0 flattens it into planar facets (Ico Sphere)."""
    local_x, local_y = (x - centre_x) / radius, (y - centre_y) / radius
    inside = local_x ** 2 + local_y ** 2 <= 1.0
    depth = np.sqrt(np.clip(1.0 - local_x ** 2 - local_y ** 2, 0.0, 1.0))
    if facets:
        local_x, local_y, depth = (np.round(value * facets) / facets for value in (local_x, local_y, depth))
        length = np.sqrt(local_x ** 2 + local_y ** 2 + depth ** 2) + 1e-6
        local_x, local_y, depth = local_x / length, local_y / length, depth / length
    return inside, _lit(local_x, local_y, depth)


def _ellipse(x, y, centre_y, radius_x, radius_y):
    return ((x / radius_x) ** 2 + ((y - centre_y) / radius_y) ** 2) <= 1.0


def _side_shade(x, half_width):
    return _lit(x / half_width, 0.0, np.sqrt(np.clip(1.0 - (x / half_width) ** 2, 0.0, 1.0)))


def _cube(x, y):
    inside = (np.abs(x) <= 0.69) & (np.abs(y) <= 0.8 - np.abs(x) * 0.5774)
    top = y >= np.abs(x) * 0.5774
    return inside, np.where(top, 1.0, np.where(x < 0, 0.62, 0.38))


def _plane(x, y, lines=False):
    shear = x - y * 0.6
    inside = (np.abs(y) <= 0.4) & (np.abs(shear) <= 0.6)
    shade = np.full_like(x, 0.85)
    if lines:
        shade = np.where((np.abs(((shear + 0.6) * 5) % 1.0 - 0.5) > 0.42) | (np.abs(((y + 0.4) * 5 / 0.8 * 0.8) % 1.0 - 0.5) > 0.42),
                         0.35, shade)
    return inside, shade


def _cylinder(x, y):
    body = (np.abs(x) <= 0.5) & (np.abs(y) <= 0.45)
    top = _ellipse(x, y, 0.45, 0.5, 0.2)
    return body | top | _ellipse(x, y, -0.45, 0.5, 0.2), np.where(top, 0.95, _side_shade(x, 0.5))


def _cone(x, y):
    half = 0.5 * (0.7 - y) / 1.15
    body = (y >= -0.45) & (y <= 0.7) & (np.abs(x) <= half)
    base = _ellipse(x, y, -0.45, 0.5, 0.2)
    return body | base, _side_shade(x, np.maximum(half, 0.05))


def _torus(x, y):
    ring = _ellipse(x, y, 0.0, 0.85, 0.55) & ~_ellipse(x, y, 0.0, 0.38, 0.2)
    return ring, np.clip(0.55 + y * 0.5, 0.25, 1.0)


def _circle(x, y):
    return _ellipse(x, y, 0.0, 0.8, 0.5), np.full_like(x, 0.85)


def _monkey(x, y):
    head, shade = _ball(x, y, 0.0, -0.05, 0.6)
    for side in (-1, 1):
        ear, ear_shade = _ball(x, y, side * 0.68, 0.3, 0.22)
        head, shade = head | ear, np.where(ear, ear_shade, shade)
        eye = (x - side * 0.22) ** 2 + (y - 0.05) ** 2 <= 0.08 ** 2
        shade = np.where(eye, 0.12, shade)
    return head, shade


DRAWINGS = {
    "Plane": _plane, "Cube": _cube, "Circle": _circle, "UV Sphere": lambda x, y: _ball(x, y, 0.0, 0.0, 0.8),
    "Ico Sphere": lambda x, y: _ball(x, y, 0.0, 0.0, 0.8, facets=2), "Cylinder": _cylinder, "Cone": _cone,
    "Torus": _torus, "Grid": lambda x, y: _plane(x, y, lines=True), "Monkey": _monkey,
}


def pixels(name):
    """(SIZE, SIZE, 4) uint8 thumbnail of the primitive `name` (drawn once, then kept)."""
    if name not in _cache:
        x, y = _grid()
        mask, shade = DRAWINGS[name](x, y)
        image = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
        image[..., :3] = (BASE_COLOR * np.asarray(shade)[..., None] * 255).clip(0, 255).astype(np.uint8)
        image[..., 3] = np.where(mask, 255, 0)
        _cache[name] = image
    return _cache[name]
