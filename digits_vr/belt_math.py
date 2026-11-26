# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool belt's pure maths (DESIGN "Tool belt"): where the belt hangs, how it turns with the body and not the head,
where its slots are, which slot a hand is at. mathutils only (no bpy), tested headless.

Belt frame: origin at the waist, +Y forward, +X right, +Z up. Angles are degrees from forward, positive to the right."""
import math

from mathutils import Matrix, Vector

SLOT_ANGLES = (-110.0, -85.0, -60.0, -35.0, 35.0, 60.0, 85.0, 110.0)    # 8 slots, four per hip [user, 2026-11-25]; the angles
SLOT_COUNT = len(SLOT_ANGLES)
BELT_RADIUS = 0.3                       # m from the waist to a slot, at size 1 and belt size 1
SLOT_REACH = 0.12                       # m: a grip this close to a slot takes from it or drops on it
SLOT_HALF = 0.05                        # m: half the side of the slot marker
DEAD_ZONE_DEGREES = 45.0                # the head may turn this far before the belt turns with it
NEAR_BELT = 0.55                        # m: a hand this close to the waist shows the belt
POCKET_ROOM = 0.8                       # a pocketed model's longest side fills this much of a slot [user: shrinks to fit]


def head_yaw(forward):
    """Heading (radians about Z, 0 = +Y) of a head direction, or None when it looks straight up or down."""
    if math.hypot(forward[0], forward[1]) < 1e-3:
        return None
    return math.atan2(-forward[0], forward[1])


def wrap(angle):
    """Angle in (-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def follow_yaw(current, head, dead_zone_degrees=DEAD_ZONE_DEGREES):
    """The belt's heading: unchanged while the head is within the dead zone, else dragged along behind the head."""
    difference = wrap(head - current)
    limit = math.radians(dead_zone_degrees)
    if abs(difference) <= limit:
        return current
    return wrap(current + difference - math.copysign(limit, difference))


def belt_frame(head_location, yaw, drop):
    """World matrix of the belt: under the head by `drop`, turned by `yaw`."""
    return Matrix.Translation((head_location[0], head_location[1], head_location[2] - drop)) @ Matrix.Rotation(yaw, 4, 'Z')


def slot_local(index, radius):
    angle = math.radians(SLOT_ANGLES[index])
    return Vector((math.sin(angle) * radius, math.cos(angle) * radius, 0.0))


def slot_matrix(frame, index, radius, scale=1.0):
    """World matrix of slot `index` (the belt's turn, uniform `scale`)."""
    return frame @ Matrix.Translation(slot_local(index, radius)) @ Matrix.Scale(scale, 4)


def nearest_slot(frame, radius, position, reach, allowed):
    """Index (from `allowed`) of the slot nearest to `position` within `reach`, else None."""
    best, best_distance = None, reach
    for index in allowed:
        distance = ((frame @ slot_local(index, radius)) - Vector(position)).length
        if distance <= best_distance:
            best, best_distance = index, distance
    return best


def snap_back_due(item_position, head_position, limit):
    """An Attached item farther from the head than `limit` goes back to the belt."""
    return (Vector(item_position) - Vector(head_position)).length > limit


def fit_scale(extent, room, grow=False):
    """Uniform scale that makes a thing of longest side `extent` fit `room`. Models never grow (`grow` False); held items
    always fill the same share of the slot, whatever your size (`grow` True)."""
    if extent <= 1e-9:
        return 1.0
    return room / extent if grow else min(1.0, room / extent)


def box_extent(low, high):
    """Longest side of the box from `low` to `high`."""
    return max(abs(high[axis] - low[axis]) for axis in range(3))


def docked_matrix(slot_world, low, high, room):
    """World matrix that puts an item, whose bounding box (in its own space, at scale 1) runs from `low` to `high`, INSIDE the
    slot at `slot_world`: its longest side becomes `room`, its middle sits at the slot's middle. The one fit rule for every item."""
    scale = fit_scale(box_extent(low, high), room, grow=True)
    middle = (Vector(low) + Vector(high)) / 2
    return slot_world @ Matrix.Scale(scale, 4) @ Matrix.Translation(-middle)


def carry_offset(hand_matrix, item_matrix):
    """Item pose relative to the hand that carries it."""
    return hand_matrix.inverted_safe() @ item_matrix
