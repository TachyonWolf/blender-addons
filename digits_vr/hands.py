# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller poses, read by polling the session (the same source for hover, select and grab)."""
from mathutils import Quaternion, Vector

from . import body_offsets, grab_order, settings
from .action_map import HANDS, LEFT, RIGHT
from .size_state import SIZE

AIM_FORWARD = Vector((0.0, 0.0, -1.0))   # the aim pose points along its local -Z (OpenXR convention)


class HandPose:
    """A controller's grip and aim pose. with_grip_rotation=False skips one call (hover needs no grip rotation);
    with_grip=False leaves grip_location None (a laser-only hover check). aim_location = the fixed fingertip point, where the
    laser starts and picks begin [user, 2026-11-25]."""
    __slots__ = ("grip_location", "grip_rotation", "aim_location", "aim_direction", "_hand", "_aim_rotation", "_grip_point")

    def __init__(self, context, state, hand, with_grip_rotation=True, with_grip=True):
        index = HANDS.index(hand)
        grip = Vector(state.controller_grip_location_get(context, index))
        self.grip_location = grip if with_grip else None
        self.grip_rotation = Quaternion(state.controller_grip_rotation_get(context, index)) \
            if with_grip_rotation and with_grip else None
        rotation = Quaternion(state.controller_aim_rotation_get(context, index))
        self.aim_location = fingertip(grip, rotation, hand)
        self.aim_direction = (rotation @ AIM_FORWARD).normalized()
        self._hand, self._aim_rotation, self._grip_point = hand, rotation, grip

    def source_point(self, source):
        """The world point a touch source picks at: the fingertip (also where the laser starts) or just above the palm."""
        return self.aim_location if source == grab_order.FINGER else palm_point(self._grip_point, self._aim_rotation, self._hand)

    @property
    def grab_location(self):
        """The point a grab is held by (its pivot): the first touch source of the mode's order, on or not [user, 2026-11-27]."""
        return self.source_point(grab_order.pivot_source(current_order()))

    def first_hit(self, find_laser, find_touch, sources=None):
        """THE pick of a hand: the first result, over the sources that are on (default: the grab mode's order, first
        priority first), of `find_laser()` for the laser or `find_touch(point)` for a touch source; None when none finds
        anything. Hover, name tag, trigger select and grip grab all pick through this, so they agree [user, 2026-11-27].
        Sources after the first hit are never tried (they cost nothing)."""
        for source in current_sources() if sources is None else sources:
            found = find_laser() if source == grab_order.LASER else find_touch(self.source_point(source))
            if found is not None:
                return found
        return None


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
    return grip_location + aim_rotation @ ((TOOL_OFFSETS[hand] + body_offsets.finger_shift()) * SIZE.factor)


def palm_point(grip_location, aim_rotation, hand):
    """The grab point just above the middle of the palm (world)."""
    return grip_location + aim_rotation @ (body_offsets.palm_shift(hand) * SIZE.factor)


def current_order():
    """The active grab mode's order: ((source, on), ...)."""
    mode = settings.get("grab_mode")
    return grab_order.order_of(settings.get(grab_order.FIELD_OF_MODE[mode]), mode)


def change_order(action, index, step=0):
    """The desk's and sidebar's edits of the active mode's order: action 'toggle' (row `index` on / off) or 'move' (row
    `index` by `step` places, -1 = up). Saved at once."""
    mode = settings.get("grab_mode")
    order = current_order()
    order = grab_order.toggled(order, index) if action == 'toggle' else grab_order.moved(order, index, step)
    settings.put(grab_order.FIELD_OF_MODE[mode], [list(pair) for pair in order])


def current_sources():
    """The sources the active grab mode picks with now, first priority first."""
    return grab_order.active(current_order())


def touch_point(context, state, index, source):
    """Where a touch source is now (world), from the session state: the palm point or the fingertip (name tags)."""
    location, rotation = drawn_hand_pose(context, state, index)
    return palm_point(location, rotation, HANDS[index]) if source == grab_order.PALM else fingertip(location, rotation, HANDS[index])


def palm_in_use():
    """The palm is one of the sources the active grab mode picks with (the palm mark shows)."""
    return grab_order.PALM in current_sources()


def tool_point(context, state, hand):
    """Where a sculpt stroke, its ring and the size gesture work: a fixed point in front of the hand."""
    return aim_pose(context, state, HANDS.index(hand))[0]


def session_state(context):
    """The XR session state when a session is running, else None (it is None before start and after end)."""
    state = context.window_manager.xr_session_state
    return state if state and state.is_running(context) else None
