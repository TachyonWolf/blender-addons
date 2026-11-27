# SPDX-License-Identifier: GPL-3.0-or-later
"""The size gesture of the sculpt brush and the select bubble: B held, and the hand's height since the press sets the size
(up = bigger, 10 cm doubles it; sculpt_math.sized). One object per tool keeps its own start."""
from . import sculpt_math
from .action_map import RIGHT, buzz, value
from .hands import tool_point
from .size_state import SIZE


class SizeGesture:
    start = None       # (diameter, hand height in your space) at the press, None while B is up

    def update(self, context, state, current, enabled=True):
        """The new world diameter while B is held (and `enabled`), else None. `current()` gives the size at the press."""
        if not enabled or value(context, state, "fine", RIGHT) <= 0.5:
            self.start = None
            return None
        height = tool_point(context, state, RIGHT).z / SIZE.factor
        if self.start is None:
            self.start = (current(), height)
            buzz(context, state, RIGHT, duration=0.02, amplitude=0.3)
        return sculpt_math.sized(self.start[0], height - self.start[1], SIZE.factor)
