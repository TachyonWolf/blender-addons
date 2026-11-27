# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool options panel as a held item (DESIGN "Held items contract"): a thin adapter over the Panel, so the belt can
dock it. The belt only sees the HeldItem interface; the panel's own code (handles, drawing, remembering) is untouched.
Docked, the belt shrinks it to fit its slot (HeldItem.dock_bounds); `left_belt` (PanelHeldItem) saves its place again once it is out.
The desk is a held item too (DESK_ITEM) [user, 2026-11-26]."""
from . import camera_panel, desk, help_panel, panel_state, tool_options
from .held_item import PanelHeldItem
from .panel_state import TOUCH_REACH
from .size_state import SIZE


class PanelItem(PanelHeldItem):
    """Any Panel as a held item."""
    def __init__(self, panel):
        self.panel = panel
        self.name = panel.name
        super().__init__()

    @property
    def shown(self):
        return self.panel.state.open

    @shown.setter
    def shown(self, _value):
        pass                    # open / closed is the panel's own state (the desk's Tool options button)

    def set_matrix(self, matrix):
        self.panel.state.set_matrix(matrix)

    def grip_hit(self, position):
        state = self.panel.state
        return state.open and panel_state.near_handle(state.matrix(), position, self.panel.widgets,
                                                      TOUCH_REACH * SIZE.factor, self.panel.spec) is not None


OPTIONS = PanelItem(tool_options.PANEL)
DESK_ITEM = PanelItem(desk.PANEL)
CAMERA_ITEM = PanelItem(camera_panel.PANEL)        # the Cam view panel docks like the tool options and the desk [user, 2026-11-26]
HELP_ITEM = PanelItem(help_panel.PANEL)              # the Help panel docks too [user, 2026-11-27]
