# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller poses, read by polling the session (the same source for hover, select and grab)."""
from mathutils import Quaternion, Vector

from .action_map import HANDS, LEFT, RIGHT
from .size_state import SIZE

AIM_FORWARD = Vector((0.0, 0.0, -1.0))   # the aim pose points along its local -Z (OpenXR convention)


class HandPose:
    """A controller's grip and aim pose. with_grip_rotation=False skips one call (hover needs no grip rotation);
    with_grip=False leaves grip_location None (a laser-only hover check). aim_location = the fixed fingertip point, where the
    laser starts and picks begin [user, 2026-11-25]."""
    __slots__ = ("grip_location", "grip_rotation", "aim_location", "aim_direction")

    def __init__(self, context, state, hand, with_grip_rotation=True, with_grip=True):
        index = HANDS.index(hand)
        grip = Vector(state.controller_grip_location_get(context, index))
        self.grip_location = grip if with_grip else None
        self.grip_rotation = Quaternion(state.controller_grip_rotation_get(context, index)) \
            if with_grip_rotation and with_grip else None
        rotation = Quaternion(state.controller_aim_rotation_get(context, index))
        self.aim_location = fingertip(grip, rotation, hand)
        self.aim_direction = (rotation @ AIM_FORWARD).normalized()


def aim_pose(context, state, index):
    """(location, rotation) of the laser: from the fixed fingertip point (the one sculpting uses), turned like the aim
    pose. The laser, our axis and the picks (HandPose) all start here [user, 2026-11-25]."""
    location, rotation = drawn_hand_pose(context, state, index)
    return fingertip(location, rotation, HANDS[index]), rotation


def drawn_hand_pose(context, state, index):
    """(location, rotation) of the simple hand: at the grip, turned like the AIM pose, so the pointing finger points
    the way the laser does [user, 2026-11-25]. Drawing and finger poke both use this."""
    return (Vector(state.controller_grip_location_get(context, index)),
            Quaternion(state.controller_aim_rotation_get(context, index)))


# The sculpt point in the hand's own space (m, your size 1): 1 cm beyond the straight index fingertip of the hand model of
# 2026-11-25, chosen once. FIXED on purpose [user]: not read from the finger, which moves to pull the trigger.
TOOL_OFFSETS = {LEFT: Vector((0.0, 0.033, -0.1485)), RIGHT: Vector((0.0, 0.033, -0.1485))}


def fingertip(grip_location, aim_rotation, hand):
    """The fixed point just beyond the index fingertip (world)."""
    return grip_location + aim_rotation @ (TOOL_OFFSETS[hand] * SIZE.factor)


def tool_point(context, state, hand):
    """Where a sculpt stroke, its ring and the size gesture work: a fixed point in front of the hand."""
    return aim_pose(context, state, HANDS.index(hand))[0]


def session_state(context):
    """The XR session state when a session is running, else None (it is None before start and after end)."""
    state = context.window_manager.xr_session_state
    return state if state and state.is_running(context) else None
