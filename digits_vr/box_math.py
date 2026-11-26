# SPDX-License-Identifier: GPL-3.0-or-later
"""Box select maths, pure (numpy, no bpy). Two shapes [user, 2026-11-25]:
VOLUME: a 3D box, its corners the aimed point at the pull and now, aligned to the headset's yaw at the start;
LASER: a rectangle seen from the head as it is NOW (a pyramid from the head; it turns as you move), selects THROUGH things like
Blender's box select. Points are world (n, 3); `head` is (location, 3x3 rotation, columns = the head's axes; it looks
down its -Z as in OpenXR)."""
import math

import numpy as np

VOLUME, LASER = 'VOLUME', 'LASER'
MIN_DEPTH = 0.05      # m: a point nearer the head than this is never in a laser box (and the divide stays safe)


def yaw_matrix(head_rotation):
    """3x3 rotation about world Z that turns +Y into the head's flat forward direction."""
    forward = np.asarray(head_rotation, float) @ np.array([0.0, 0.0, -1.0])
    angle = math.atan2(forward[1], forward[0]) - math.pi / 2.0
    cos, sin = math.cos(angle), math.sin(angle)
    return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])


def _yaw_local(points, origin, head_rotation):
    return (np.asarray(points, float) - origin) @ yaw_matrix(head_rotation)      # = R^T (p - origin), per row


def volume_inside(points, start, now, head_rotation):
    """Mask of `points` inside the 3D box with corners `start` and `now`, turned by the head's yaw."""
    start = np.asarray(start, float)
    corner = _yaw_local([now], start, head_rotation)[0]
    local = _yaw_local(points, start, head_rotation)
    low, high = np.minimum(0.0, corner), np.maximum(0.0, corner)
    return np.all((local >= low) & (local <= high), axis=1)


def _head_local(points, head):
    location, rotation = np.asarray(head[0], float), np.asarray(head[1], float)
    return (np.asarray(points, float) - location) @ rotation       # head axes: x right, y up, -z forward


def _ndc(local):
    depth = np.maximum(-local[:, 2], MIN_DEPTH)
    return local[:, :2] / depth[:, None], -local[:, 2]


def laser_inside(points, start, now, head):
    """Mask of `points` inside the rectangle spanned by `start` and `now` as seen from `head` (in front of the head)."""
    corners, _ = _ndc(_head_local([start, now], head))
    low, high = corners.min(axis=0), corners.max(axis=0)
    ndc, depth = _ndc(_head_local(points, head))
    return (depth > MIN_DEPTH) & np.all((ndc >= low) & (ndc <= high), axis=1)


def inside(shape, points, start, now, head):
    if len(points) == 0:
        return np.zeros(0, bool)
    return laser_inside(points, start, now, head) if shape == LASER else volume_inside(points, start, now, head[1])


class Sphere:
    """The select bubble: points within `radius` of `centre` (world). Same `inside(points)` as SelectGesture, so
    box_select.apply takes either."""

    def __init__(self, centre, radius):
        self.centre, self.radius = np.asarray(centre, float), float(radius)

    def inside(self, points):
        if len(points) == 0:
            return np.zeros(0, bool)
        return ((np.asarray(points, float) - self.centre) ** 2).sum(axis=1) <= self.radius ** 2


_EDGES = ((0, 1), (1, 3), (3, 2), (2, 0), (4, 5), (5, 7), (7, 6), (6, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def volume_lines(start, now, head_rotation):
    """(24, 3) line vertices of the 3D box (12 edges) for drawing."""
    start = np.asarray(start, float)
    rotation = yaw_matrix(head_rotation)
    corner = _yaw_local([now], start, head_rotation)[0]
    corners = np.array([[x, y, z] for z in (0.0, corner[2]) for y in (0.0, corner[1]) for x in (0.0, corner[0])])
    world = corners @ rotation.T + start
    return world[np.array(_EDGES).reshape(-1)]


def laser_lines(start, now, head):
    """(8, 3) line vertices of the laser rectangle as seen from `head`: its two drawn corners ARE the start point and the
    point now (the laser tips) [user, 2026-11-25]; the other two lie on their view rays at the mean depth."""
    location, rotation = np.asarray(head[0], float), np.asarray(head[1], float)
    (x0, y0), (x1, y1) = _ndc(_head_local([start, now], head))[0]
    depths = np.maximum(-_head_local([start, now], head)[:, 2], MIN_DEPTH)
    middle = depths.mean()
    corners = np.array([[x0 * depths[0], y0 * depths[0], -depths[0]], [x1 * middle, y0 * middle, -middle],
                        [x1 * depths[1], y1 * depths[1], -depths[1]], [x0 * middle, y1 * middle, -middle]])
    world = corners @ rotation.T + location
    return world[np.array([0, 1, 1, 2, 2, 3, 3, 0])]
