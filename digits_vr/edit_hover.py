# SPDX-License-Identifier: GPL-3.0-or-later
"""Hover preview in Edit mode: the vertex / edge / face each hand's laser would select (or its hand would grab in Free
mode) lights up before you press (drawn by edit_cage). Called by hover.update for each hand; a still hand costs no pick
(pick_math.moved_enough) and at most one pick runs per tick."""
from . import edit_loop_preview, edit_math, edit_pick, edit_state
from .hands import HandPose
from .pick_math import moved_enough
from .runtime import RUNTIME


PICK_EVERY = 3     # ticks between two hover picks of a hand (~10 per second): a preview needs no more, Q1 does


def update(context, state, hand, hand_state, laser, touch, may_pick):
    """Refresh `hand_state.edit_hover` = (element, index) or None. Returns True when a pick ran."""
    edit = edit_state.STATE
    kind = edit_math.EDGE if edit_loop_preview.cutting() else None      # the loop cut aims at edges, with the laser only
    touch = touch and kind is None
    if not (laser or touch) or not edit.ready:
        hand_state.laser_on, hand_state.last_pose, hand_state.edit_hover = laser, None, None
        return False
    pose = HandPose(context, state, hand, with_grip_rotation=False, with_grip=touch)
    now = (pose.aim_location, pose.aim_direction)
    changed = (laser != hand_state.laser_on or hand_state.last_pose is None or moved_enough(hand_state.last_pose, now)
               or hand_state.edit_hover_version != edit.version)
    hand_state.laser_on = laser
    if not changed or not may_pick or RUNTIME.ticks - hand_state.edit_hover_tick < PICK_EVERY:
        return False
    hand_state.edit_hover_tick = RUNTIME.ticks
    hand_state.last_pose, hand_state.edit_hover_version = now, edit.version
    found = edit_pick.pick_at(context, False, pose.aim_location, pose.aim_direction, pose.aim_location, hover=True) if touch else None
    if found is None and laser:
        found = edit_pick.pick_at(context, True, pose.aim_location, pose.aim_direction, pose.aim_location, hover=True, kind=kind)
    hand_state.edit_hover = (found.element, found.index) if found else None
    return True
