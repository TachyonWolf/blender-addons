# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain maths of the Custom Facing arrow (no bpy; tested): where the dragged tip points, and the 15 degree snap.

The arrow is a trackball: its tip sits on a sphere around the target's centre, and while you drag, the tip follows the
mouse ray on that sphere. One drag can turn the arrow to any direction, with no gimbal lock and no hidden axis."""
from math import asin, atan2, cos, radians, sin, sqrt

from mathutils import Vector

SNAP = radians(15.0)
TINY = 1e-9


def tip_direction(ray_origin, ray_direction, centre, radius, current):
    """Unit direction from `centre` to where the mouse ray meets the sphere of `radius`. A ray through the sphere
    hits it twice: the hit nearer to `current` wins, so the arrow never jumps to the far side. A ray that misses
    uses its closest point to the centre. Returns `current` when the ray goes through the centre."""
    ray = Vector(ray_direction).normalized()
    offset = Vector(ray_origin) - Vector(centre)
    along = offset.dot(ray)
    discriminant = along * along - (offset.dot(offset) - radius * radius)
    if discriminant >= 0.0:
        root = sqrt(discriminant)
        hits = [(offset + ray * t).normalized() for t in (-along - root, -along + root)]
        return max(hits, key=lambda hit: hit.dot(current))
    closest = offset + ray * -along
    return closest.normalized() if closest.length > TINY else Vector(current)


def snap_direction(direction, step=SNAP):
    """`direction` with its compass angle (around Z) and its height angle each rounded to whole `step`s, so the
    six axes and every 15 degrees between them are reachable."""
    direction = Vector(direction).normalized()
    flat = sqrt(direction.x ** 2 + direction.y ** 2)
    height = round(asin(max(-1.0, min(1.0, direction.z)) ) / step) * step
    compass = round(atan2(direction.y, direction.x) / step) * step if flat > 1e-6 else 0.0
    return Vector((cos(height) * cos(compass), cos(height) * sin(compass), sin(height))).normalized()
