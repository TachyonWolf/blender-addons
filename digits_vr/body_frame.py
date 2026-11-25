# SPDX-License-Identifier: GPL-3.0-or-later
"""Your body frame: hip height under the head, turning with the body and not the head (the head may turn the dead zone
before it is dragged along). ONE place for the tool belt and for pinned panels (DESIGN "Pinned panels"); it works with the
belt off. OpenXR has no body, so it is worked out from the head each time `update` is called. The maths: belt_math."""
from dataclasses import dataclass, field

from mathutils import Matrix, Quaternion, Vector

from . import belt_math, settings
from .size_state import SIZE


@dataclass
class BodyFrame:
    placed: bool = False           # the frame has faced you once this session
    yaw: float = 0.0
    matrix: Matrix = field(default_factory=lambda: Matrix.Identity(4))     # world: origin at the hips, +Y forward

    def reset(self):
        self.placed = False

    def update(self, state):
        """Follow the head (state = the XR session state). Returns the frame's world matrix."""
        head = Vector(state.viewer_pose_location)
        yaw = belt_math.head_yaw(Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0)))
        if not self.placed:
            self.yaw, self.placed = yaw or 0.0, True
        elif yaw is not None:
            self.yaw = belt_math.follow_yaw(self.yaw, yaw)
        self.matrix = belt_math.belt_frame(head, self.yaw, settings.get("belt_height") * SIZE.factor)
        return self.matrix


BODY = BodyFrame()
