# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller poses, read by polling the session (the same source for hover, select and grab)."""
from mathutils import Quaternion, Vector

from .action_map import HANDS

AIM_FORWARD = Vector((0.0, 0.0, -1.0))   # the aim pose points along its local -Z (OpenXR convention)


class HandPose:
    """A controller's grip and aim pose. with_grip_rotation=False skips one call (hover needs no grip rotation)."""
    __slots__ = ("grip_location", "grip_rotation", "aim_location", "aim_direction")

    def __init__(self, context, state, hand, with_grip_rotation=True):
        index = HANDS.index(hand)
        self.grip_location = Vector(state.controller_grip_location_get(context, index))
        self.grip_rotation = Quaternion(state.controller_grip_rotation_get(context, index)) if with_grip_rotation \
            else None
        self.aim_location = Vector(state.controller_aim_location_get(context, index))
        rotation = Quaternion(state.controller_aim_rotation_get(context, index))
        self.aim_direction = (rotation @ AIM_FORWARD).normalized()


def session_state(context):
    """The XR session state when a session is running, else None (it is None before start and after end)."""
    state = context.window_manager.xr_session_state
    return state if state and state.is_running(context) else None
