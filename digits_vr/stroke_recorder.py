# SPDX-License-Identifier: GPL-3.0-or-later
"""The stroke recorder Annotate and Grease Pencil drawing share: while a hand's trigger is held it hands out one
controller-tip point (aim pose) per headset frame, spaced by a minimum distance (in your space: it grows with your size), and notices when an undo made the
running stroke stale. The two tools only differ in where they write the points."""
from . import annotate_math as math_
from .hands import HandPose
from .runtime import RUNTIME
from .size_state import scaled


class StrokeRecorder:
    def __init__(self, min_distance=math_.MIN_POINT_DISTANCE, point_of=None):
        self.min_distance = min_distance
        self.point_of = point_of        # f(context, state, hand) -> world point; None = the controller tip (aim pose)
        self.hand = None                # the hand whose trigger draws the running stroke
        self.last_point = None
        self.last_frame = -1
        self.generation = 0             # RUNTIME.generation at the stroke's start

    @property
    def running(self):
        return self.hand is not None

    @property
    def stale(self):
        """An undo / redo ran since the stroke began: whatever the tool holds is gone."""
        return self.generation != RUNTIME.generation

    def begin(self, hand):
        self.hand, self.last_point, self.last_frame = hand, None, -1
        self.generation = RUNTIME.generation

    def sample(self, context, state, once_per_frame=True):
        """The next point (world space, a tuple), or None: not due this headset frame yet, or too close to the last
        point. The first point of a stroke comes with once_per_frame=False."""
        if once_per_frame:
            if self.last_frame == RUNTIME.frame:
                return None
            self.last_frame = RUNTIME.frame
        point = tuple(self.point_of(context, state, self.hand) if self.point_of else
                      HandPose(context, state, self.hand, with_grip_rotation=False).aim_location)
        if not math_.far_enough(self.last_point, point, scaled(self.min_distance)):
            return None
        self.last_point = point
        return point

    def stop(self):
        self.hand, self.last_point = None, None
