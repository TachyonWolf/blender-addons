# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's state: a PanelState (panel_state.py) plus its open tab. The math helpers below are the shared panel
math bound to the desk's spec. mathutils only (no bpy), so it is tested headless."""
from dataclasses import dataclass

from . import desk_layout, panel_state
from .panel_state import (CALL, CLOSE, OPEN, OPEN_DROP,  # noqa: F401
                          TOUCH_REACH, HandleGrab, PanelState, one_hand_matrix, place_in_front, stick_action)

SCALE_RANGE = desk_layout.SPEC.scale_range


@dataclass
class DeskState(PanelState):
    tab: str = 'grab'
    popup: str = ""                                     # the open pop-up / dropdown list ("" = none)
    selected_sub: str = 'rig'                           # Selected tab: 'rig' or 'mods' (Modifiers)
    options_last: str = 'move'                          # the Options section the Options tab opens on (the one used last)
    grab_more: bool = False                             # Grab tab: the More foldout is open
    extra: int = 0                                      # pixels the desk is taller than normal (top handle; desk_layout.spec_for)

    def spec(self):
        """The desk's PanelSpec at its present height."""
        return desk_layout.spec_for(self.extra)


DESK = DeskState()


def clamp_scale(scale):
    return panel_state.clamp_scale(scale, SCALE_RANGE)


def screen_hit(matrix, origin, direction):
    return panel_state.screen_hit(matrix, origin, direction, DESK.spec())


def near_handle(matrix, point, widgets, reach=TOUCH_REACH):
    return panel_state.near_handle(matrix, point, widgets, reach, DESK.spec())


def two_hand_matrix(start_matrix, start_points, now_points, size=1.0):
    return panel_state.two_hand_matrix(start_matrix, start_points, now_points, size, SCALE_RANGE)
