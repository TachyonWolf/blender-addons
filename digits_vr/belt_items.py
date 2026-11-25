# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool options panel as a held item (DESIGN "Held items contract"): a thin adapter over the Panel, so the belt can
dock it. The belt only sees the HeldItem interface; the panel's own code (handles, drawing, remembering) is untouched.
Docked, the panel is small (`dock_scale`); `left_belt` (PanelHeldItem) saves its place again once it is out. The desk is not a held item."""
from . import panel_state, settings, tool_options
from .held_item import PanelHeldItem
from .panel_state import TOUCH_REACH
from .size_state import SIZE


class PanelItem(PanelHeldItem):
    """Any Panel as a held item."""
    dock_scale = 0.25           # the belt shows the panel this size relative to you

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
