# SPDX-License-Identifier: GPL-3.0-or-later
"""Pinned panels' pure maths (DESIGN "Pinned panels"): a panel's place relative to your body frame (body_frame.py), kept
per unit of your size so walking, turning and scaling yourself carry it along. mathutils only, tested headless."""
from dataclasses import dataclass

from mathutils import Matrix, Quaternion, Vector

MOVED_DISTANCE = 0.002      # m (times your size): a panel this far from where the pin put it was moved by someone else


@dataclass(frozen=True)
class PinOffset:
    """A panel's place in the body frame: location per unit of your size, rotation, scale per unit of your size."""
    location: Vector
    rotation: Quaternion
    scale: float

    def listed(self):
        return list(self.location), list(self.rotation), self.scale


def capture(frame, matrix, size):
    """The offset that puts a panel at `matrix` (world) now."""
    location, rotation, scale = (frame.inverted_safe() @ matrix).decompose()
    return PinOffset(location / size, rotation.normalized(), scale.x / size)


def apply(frame, offset, size):
    """World matrix of a panel with `offset`, for your size `size`."""
    return frame @ Matrix.LocRotScale(offset.location * size, offset.rotation, (offset.scale * size,) * 3)


def moved(matrix, last, size):
    """True when `matrix` is not where the pin last put the panel (a grab, a call, a belt carry...)."""
    return (matrix.translation - last.translation).length > MOVED_DISTANCE * size
