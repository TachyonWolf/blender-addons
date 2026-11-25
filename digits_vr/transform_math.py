# SPDX-License-Identifier: GPL-3.0-or-later
"""Hand motion to transforms, with the rig's locks. mathutils only (no bpy), so it is tested headless.

A grab works out one world-space delta per frame and applies it to each item's start: target_world = delta @ start.
- Puppet (one hand): the item keeps its offset to the hand and turns with the wrist:
    delta = T(pivot + move) @ R_wrist @ T(-pivot), pivot = the hand (at the item for Select and Grab);
    with pivot = hand start and factor 1 this is hand_now @ hand_start^-1.
- On stick: the same without the wrist; the stick's rotation turns the item about its own centre.
- Two hands: scale (and move) about the point between the hands; no rotation.
- Fine control scales all of it (move, turn, stick, scale) by FINE_FACTOR.
Objects and pose bones then turn the target into their own local channels (matrix_basis) and keep locked channels
at their start values. Scale changes only once two hands held the item (use_scale)."""
import math

from mathutils import Euler, Matrix, Quaternion, Vector

EULER_ORDERS = ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX')


def hand_matrix(location, rotation):
    """World matrix of a controller pose (location Vector, rotation Quaternion)."""
    return Matrix.Translation(Vector(location)) @ Quaternion(rotation).to_matrix().to_4x4()


FINE_FACTOR = 0.25                  # fine control: motion about 1/4
STICK_SPEED = math.radians(120.0)   # On stick rotation at full deflection, per second
STICK_DEADZONE = 0.2
WORLD_UP = Vector((0.0, 0.0, 1.0))


PUSH_MIN_DISTANCE = 0.05     # m: push / pull never brings the item closer to the hand than this (your space)
PUSH_DEADZONE = 0.1          # a trigger pulled less than this does nothing


def trigger_net(push, pull, deadzone=PUSH_DEADZONE):
    """Net push amount from the right (push) and left (pull) trigger values: right - left, deadzone each."""
    return (push if push > deadzone else 0.0) - (pull if pull > deadzone else 0.0)


def push_offset(hand, centre, net, speed, seconds, factor=1.0, min_distance=PUSH_MIN_DISTANCE):
    """World offset that moves the item's `centre` along the line from `hand` through it: net (-1 pull .. 1 push)
    * speed (m/s) * seconds * factor. The distance never drops below min_distance (an item already closer is not
    pushed in either; it can still be pulled no further or pushed out)."""
    line = Vector(centre) - Vector(hand)
    distance = line.length
    if distance < 1e-9 or net == 0.0:
        return Vector()
    new = max(distance + net * speed * seconds * factor, min(distance, min_distance))
    return line * ((new - distance) / distance)


def hand_delta(hand_start, hand_now):
    return hand_now @ hand_start.inverted_safe()


def partial_rotation(rotation, factor):
    """`factor` of a rotation (slerp from no rotation)."""
    return Quaternion().slerp(rotation, factor) if factor != 1.0 else rotation.copy()


def about(pivot, matrix, move=None):
    """T(pivot + move) @ matrix @ T(-pivot): `matrix` applied about `pivot`, then shifted by `move`."""
    pivot = Vector(pivot)
    end = pivot + Vector(move) if move is not None else pivot
    return Matrix.Translation(end) @ matrix @ Matrix.Translation(-pivot)


def one_hand_delta(hand_start, hand_now, pivot, factor=1.0, use_wrist=True, extra_rotation=None):
    """World delta of a one-hand grab: the hand's move (x factor) and, with use_wrist, the wrist's turn (x factor)
    about `pivot`; `extra_rotation` (On stick) turns about the pivot too."""
    move = (hand_now.translation - hand_start.translation) * factor
    rotation = Quaternion()
    if use_wrist:
        rotation = partial_rotation(hand_now.to_quaternion() @ hand_start.to_quaternion().inverted(), factor)
    if extra_rotation is not None:
        rotation = extra_rotation @ rotation
    return about(pivot, rotation.to_matrix().to_4x4(), move)


def two_hand_delta(starts, nows, factor=1.0, pivot=None):
    """World delta of a two-hand grab: scale by the change of the hands' distance (fine control: that ratio to the
    power `factor`), about the point between the hands (or about `pivot`: a distance grab scales the item about its
    own centre so it stays put), and the hands' middle carries the move. `starts` / `nows` are the two hands'
    locations."""
    start_a, start_b = (Vector(point) for point in starts)
    now_a, now_b = (Vector(point) for point in nows)
    start_gap = (start_b - start_a).length
    ratio = (now_b - now_a).length / start_gap if start_gap > 1e-6 else 1.0
    ratio = max(ratio, 1e-3) ** factor
    middle_start, middle_now = (start_a + start_b) / 2, (now_a + now_b) / 2
    centre = middle_start if pivot is None else Vector(pivot)
    return about(centre, Matrix.Diagonal((ratio, ratio, ratio, 1.0)), (middle_now - middle_start) * factor)


def stick_step(stick, seconds, factor, towards):
    """Rotation for one frame of On stick: x turns about world up, y tips about the horizontal axis across
    `towards` (hand -> item). Inside the deadzone: None."""
    x, y = (value if abs(value) > STICK_DEADZONE else 0.0 for value in stick)
    if not (x or y):
        return None
    step = STICK_SPEED * seconds * factor
    across = Vector(towards).cross(WORLD_UP)
    if across.length < 1e-6:
        across = Vector((1.0, 0.0, 0.0))
    return Quaternion(across.normalized(), y * step) @ Quaternion(WORLD_UP, -x * step)


def moved(start_world, delta):
    return delta @ start_world


def basis_from_parent_space(target, parent_space):
    """matrix_basis that puts an item at `target`, given the matrix that maps its basis to the same space
    (objects: parent world @ matrix_parent_inverse; identity without a parent)."""
    return parent_space.inverted_safe() @ target


class Channels:
    """The local channels of an object or pose bone: location, rotation in its rotation_mode, scale."""

    def __init__(self, location, rotation_mode, rotation_quaternion, rotation_euler, rotation_axis_angle, scale):
        self.location = Vector(location)
        self.rotation_mode = rotation_mode
        self.rotation_quaternion = Quaternion(rotation_quaternion)
        self.rotation_euler = Euler(rotation_euler, rotation_mode if rotation_mode in EULER_ORDERS else 'XYZ')
        self.rotation_axis_angle = tuple(rotation_axis_angle)  # (angle, x, y, z)
        self.scale = Vector(scale)

    @classmethod
    def of(cls, owner):
        """Read the channels of an object or pose bone (anything with these properties)."""
        return cls(owner.location, owner.rotation_mode, owner.rotation_quaternion, owner.rotation_euler,
                   owner.rotation_axis_angle, owner.scale)

    def write(self, owner):
        owner.location = self.location
        if self.rotation_mode == 'QUATERNION':
            owner.rotation_quaternion = self.rotation_quaternion
        elif self.rotation_mode == 'AXIS_ANGLE':
            owner.rotation_axis_angle = self.rotation_axis_angle
        else:
            owner.rotation_euler = self.rotation_euler
        owner.scale = self.scale

    def quaternion(self):
        if self.rotation_mode == 'QUATERNION':
            return self.rotation_quaternion.normalized()
        if self.rotation_mode == 'AXIS_ANGLE':
            angle, *axis = self.rotation_axis_angle
            return Quaternion(Vector(axis).normalized() if Vector(axis).length else Vector((0, 1, 0)), angle)
        return self.rotation_euler.to_quaternion()


class Locks:
    """Which channels are locked: three bools each for location, rotation and scale. Connected bones can't move."""

    def __init__(self, location=(False,) * 3, rotation=(False,) * 3, scale=(False,) * 3):
        self.location = tuple(bool(flag) for flag in location)
        self.rotation = tuple(bool(flag) for flag in rotation)
        self.scale = tuple(bool(flag) for flag in scale)

    @classmethod
    def of(cls, owner, connected=False):
        location = (True,) * 3 if connected else tuple(owner.lock_location)
        return cls(location, tuple(owner.lock_rotation), tuple(owner.lock_scale))


def _locked_euler(start_euler, new_quat, rotation_locks, order):
    new_euler = new_quat.to_euler(order, start_euler)
    return Euler([start_euler[i] if rotation_locks[i] else new_euler[i] for i in range(3)], order)


def channels_from_basis(basis, start, locks, use_scale=False):
    """New Channels for `basis` (a target matrix_basis): locked channels keep their `start` value, the rotation is
    written in the start's rotation mode (euler kept compatible with the start, so no 360 degree flips), scale is
    kept unless `use_scale` (two-hand scale; scale locks still hold). Quaternion and axis-angle with some rotation
    axes locked go through an XYZ euler (an approximation: Blender's own quaternion locks act on the components)."""
    location, new_quat, scale = basis.decompose()
    result = Channels(start.location, start.rotation_mode, start.rotation_quaternion, start.rotation_euler,
                      start.rotation_axis_angle, start.scale)
    result.location = Vector([start.location[i] if locks.location[i] else location[i] for i in range(3)])
    if use_scale:
        result.scale = Vector([start.scale[i] if locks.scale[i] else scale[i] for i in range(3)])
    if all(locks.rotation):
        return result
    mode = start.rotation_mode
    if mode in EULER_ORDERS:
        result.rotation_euler = _locked_euler(start.rotation_euler, new_quat, locks.rotation, mode)
        return result
    start_quat = start.quaternion()
    if any(locks.rotation):
        new_quat = _locked_euler(start_quat.to_euler('XYZ'), new_quat, locks.rotation, 'XYZ').to_quaternion()
    if start_quat.dot(new_quat) < 0:
        new_quat = -new_quat  # same hemisphere as the start: no sudden sign flip in the curves
    if mode == 'QUATERNION':
        result.rotation_quaternion = new_quat
    else:
        axis, angle = new_quat.to_axis_angle()
        result.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
    return result
