# SPDX-License-Identifier: GPL-3.0-or-later
"""Movement math (milestone 4): stick dead zone, walk and flight steps, snap / smooth turn about the head, the
teleport arc and its landing, plane height. mathutils only (no bpy), tested headless.

World space is Blender's (Z up). "Navigation" is the viewer offset: world point = navigation_location +
navigation_rotation @ (point in the tracking space)."""
import math

from mathutils import Quaternion, Vector

DEAD_ZONE = 0.2            # stick radius below which nothing happens
SNAP_PRESS, SNAP_RELEASE = 0.7, 0.4   # a snap turn fires when the stick passes SNAP_PRESS; it re-arms below SNAP_RELEASE
AIM_PRESS, AIM_RELEASE = 0.6, 0.35    # teleport: forward past AIM_PRESS shows the arc; below AIM_RELEASE jumps
ARC_SPEED = 10.0           # m/s the arc leaves the hand with
GRAVITY = 9.8
ARC_STEP = 0.04            # s between arc points
ARC_MAX_TIME = 3.0
MAX_TELEPORT_RANGE = 30.0  # m (horizontal): farther spots are refused
MIN_LANDING_NORMAL = 0.5   # a geometry landing needs a surface this floor-like (normal z): no landing on walls
RING_RADIUS = 0.35
UP = Vector((0.0, 0.0, 1.0))
FORWARD = Vector((0.0, 0.0, -1.0))   # a pose's local forward (OpenXR)


def stick_with_dead_zone(stick_x, stick_y, dead=DEAD_ZONE):
    """The stick with a round dead zone cut out and the rest stretched back to 0..1 (no jump at the edge)."""
    length = math.hypot(stick_x, stick_y)
    if length <= dead:
        return 0.0, 0.0
    scale = min(1.0, (length - dead) / (1.0 - dead)) / length
    return stick_x * scale, stick_y * scale


def heading(rotation):
    """(forward, right) of a viewer rotation as level unit vectors (z = 0). Looking straight up or down uses the
    head's up direction, so the heading never collapses."""
    forward = rotation @ FORWARD
    level = Vector((forward.x, forward.y, 0.0))
    if level.length < 0.2:
        up_axis = rotation @ Vector((0.0, 1.0, 0.0))
        level = Vector((up_axis.x, up_axis.y, 0.0)) * (1.0 if forward.z < 0 else -1.0)
    if level.length < 1e-6:
        level = Vector((0.0, 1.0, 0.0))
    level.normalize()
    return level, Vector((level.y, -level.x, 0.0))


def _basis(rotation, hand_direction):
    """(dead-ahead unit vector, level forward, level right) of the heading: the head's (`rotation`), or the left hand's
    aim `hand_direction`. A hand pointing (nearly) straight up or down takes its level heading from the head."""
    if hand_direction is None:
        level, right = heading(rotation)
        return (rotation @ FORWARD).normalized(), level, right
    direction = hand_direction.normalized()
    level = Vector((direction.x, direction.y, 0.0))
    if level.length < 0.2:
        return (direction,) + heading(rotation)
    level.normalize()
    return direction, level, Vector((level.y, -level.x, 0.0))


def walk_delta(rotation, stick, speed, dt, hand_direction=None):
    """Level step of walking: the stick's up is where you look (or the left hand points), sideways strafes."""
    _ahead, forward, right = _basis(rotation, hand_direction)
    return (forward * stick[1] + right * stick[0]) * (speed * dt)


def fly_delta(rotation, stick, vertical, speed, dt, hand_direction=None, full=False):
    """Flight step. Stick up goes forward along the heading: level (`full` False) or dead ahead, up and down too
    (`full` True). Sideways strafes level; `vertical` (the other stick's up / down, -1..1) goes straight up or down."""
    ahead, level, right = _basis(rotation, hand_direction)
    return ((ahead if full else level) * stick[1] + right * stick[0] + UP * vertical) * (speed * dt)


def turn_about(location, rotation, pivot, angle):
    """New (navigation location, rotation) after turning by `angle` radians about the vertical axis through `pivot`
    (the head: it stays where it is). Positive = to the left (counter-clockwise from above)."""
    turn = Quaternion(UP, angle)
    return pivot - turn @ (pivot - location), (turn @ rotation).normalized()


def snap_edge(held, stick_x, press=SNAP_PRESS, release=SNAP_RELEASE):
    """Snap turning from the stick's x: returns (held direction, fired direction). A push past `press` fires once
    (-1 left, +1 right); the stick must come back below `release` to fire again."""
    if held == 0:
        if abs(stick_x) >= press:
            direction = 1 if stick_x > 0 else -1
            return direction, direction
        return 0, 0
    return (0 if abs(stick_x) < release else held), 0


def smooth_angle(stick_x, degrees_per_second, dt):
    """Radians to turn this frame (to the right for a positive stick x, so the angle is negative)."""
    return -stick_x * math.radians(degrees_per_second) * dt


def height_step(height, stick_y, rate, dt, limit=100.0):
    """Plane height after the stick's up / down for `dt` seconds (m), kept within +-limit."""
    return max(-limit, min(limit, height + stick_y * rate * dt))


def ground_target(floor, ground, max_step):
    """(target floor height, blocked) for Walk on geometry. `ground` is the z of the surface under the head (None =
    nothing there). A step up of at most `max_step` is climbed; a taller one is a wall: blocked, you stay at `floor`.
    A drop (any depth the cast reached) is taken; with no ground you hold your height (no falling into the void)."""
    if ground is None:
        return floor, False
    if ground - floor > max_step:
        return floor, True
    return ground, False


def slide_toward(current, target, speed, dt):
    """`current` moved toward `target` by at most speed * dt (m): the height never snaps."""
    step = speed * dt
    if abs(target - current) <= step:
        return target
    return current + math.copysign(step, target - current)


def arc_points(origin, direction, plane_z, size=1.0):
    """(points, landing) of the teleport arc. The arc leaves `origin` along `direction` at ARC_SPEED, falls under
    gravity and ends where it meets the horizontal plane z = plane_z. landing is None when it never does in time, the
    hand is below the plane or the spot is out of range; the points then show where it got to. `size` (your size)
    stretches the whole arc: speed, gravity and range."""
    velocity = direction.normalized() * (ARC_SPEED * size)
    points = [origin.copy()]
    if origin.z <= plane_z:
        return points, None
    steps = int(ARC_MAX_TIME / ARC_STEP)
    for step in range(1, steps + 1):
        time = step * ARC_STEP
        point = Vector((origin.x + velocity.x * time, origin.y + velocity.y * time,
                        origin.z + velocity.z * time - 0.5 * GRAVITY * size * time * time))
        previous = points[-1]
        if point.z <= plane_z:
            fraction = (previous.z - plane_z) / (previous.z - point.z)
            landing = previous.lerp(point, fraction)
            landing.z = plane_z
            points.append(landing)
            reach = math.hypot(landing.x - origin.x, landing.y - origin.y)
            return points, (landing if reach <= MAX_TELEPORT_RANGE * size else None)
        points.append(point)
    return points, None


def arc_samples(origin, direction, size=1.0, stop_z=-1e9, stride=3):
    """Coarse points of the teleport arc for a ray cast against geometry: every `stride`-th point of the same arc as
    arc_points, from `origin` until it falls below `stop_z` or ARC_MAX_TIME is up (the last point is always kept)."""
    velocity = direction.normalized() * (ARC_SPEED * size)
    points = [origin.copy()]
    for step in range(1, int(ARC_MAX_TIME / ARC_STEP) + 1):
        time = step * ARC_STEP
        point = Vector((origin.x + velocity.x * time, origin.y + velocity.y * time,
                        origin.z + velocity.z * time - 0.5 * GRAVITY * size * time * time))
        done = point.z < stop_z or step == int(ARC_MAX_TIME / ARC_STEP)
        if step % stride == 0 or done:
            points.append(point)
        if done:
            break
    return points


def floor_offset(navigation_z, head_z, eye_height):
    """Navigation z that puts the floor on a plane at height 0: the plane's height is added to it. The tracking space
    is head level (OpenXR LOCAL), so your eyes sit `head_z - navigation_z` above its origin: the floor lies
    `eye_height` below your eyes."""
    return navigation_z - head_z + eye_height


def teleport_location(location, head, landing):
    """New navigation location that puts your head over `landing` (your floor is already on the plane)."""
    return Vector((location.x + landing.x - head.x, location.y + landing.y - head.y, location.z))


def plane_location(location, plane_z, offset):
    """The navigation location with your floor on the plane (`offset` from floor_offset)."""
    return Vector((location.x, location.y, plane_z + offset))


def ring_points(center, radius=RING_RADIUS, segments=24):
    """Line-segment points (pairs) of a horizontal ring around `center`."""
    around = [Vector((center.x + radius * math.cos(math.tau * index / segments),
                      center.y + radius * math.sin(math.tau * index / segments), center.z + 0.01))
              for index in range(segments + 1)]
    return strip_to_segments(around)


def strip_to_segments(points):
    """A line strip as LINES pairs: a-b, b-c, ..."""
    return [point for index in range(len(points) - 1) for point in (points[index], points[index + 1])]
