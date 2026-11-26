# SPDX-License-Identifier: GPL-3.0-or-later
"""A + trigger as ONE gesture for Object, Edit and Pose mode, decided at the RELEASE: a tap toggles (the select tool),
a drag is a box select. Pure (no bpy). The gesture knows the box; what is INSIDE it per mode is box_select.py.
The corners are AT the fingertip [user, 2026-11-25]: the press anchors one, the fingertip moves the opposite one. `reach` is how
far along the aim the moving corner sits (the grips push / pull it: controls._push_box)."""
import math

try:
    from . import box_math
except ImportError:      # the headless pure tests import the modules top-level
    import box_math

TAP, DRAG = 'TAP', 'DRAG'
BOX_START_DISTANCE = 0.03     # m (scaled by your size): the aimed point moved this far with the trigger held = a drag
BOX_START_ANGLE = math.radians(4.0)     # and at least this much turn, so a far tap does not jitter into a drag


def start_distance(reach, scaled_minimum):
    """How far the aimed point must move to be a drag."""
    return max(scaled_minimum, reach * math.tan(BOX_START_ANGLE))


class SelectGesture:
    """One A + trigger press. update(position) each tick with the aimed point; finish() says TAP or DRAG.
    `head` = (location, 3x3 rotation) at the press. `stale_grips`: hands whose grip was already down at the press: they push
    nothing until let go once."""

    def __init__(self, hand, start, mode, generation, min_distance, head, shape=box_math.VOLUME, reach=0.0,
                 stale_grips=(), now=0.0):
        self.hand, self.start, self.point = hand, tuple(start), tuple(start)
        self.mode, self.generation, self.min_distance = mode, generation, min_distance
        self.head, self.shape, self.far = head, shape, False
        self.reach, self.stale_grips, self.last_time = reach, set(stale_grips), now

    def update(self, position):
        self.point = tuple(position)
        if not self.far:
            self.far = sum((a - b) ** 2 for a, b in zip(self.point, self.start)) > self.min_distance ** 2

    @property
    def boxing(self):
        return self.far

    def finish(self):
        return DRAG if self.far else TAP

    def inside(self, points):
        return box_math.inside(self.shape, points, self.start, self.point, self.head)

    def lines(self):
        """Line vertices of the box for drawing (world)."""
        if self.shape == box_math.LASER:
            return box_math.laser_lines(self.start, self.point, self.head)
        return box_math.volume_lines(self.start, self.point, self.head[1])
