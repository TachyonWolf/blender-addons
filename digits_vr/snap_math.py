# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapping for grabs in Edit and Object mode, pure (numpy, no bpy). One mode at a time [user, 2026-11-25]:
OFF; GRID: the grabbed set's anchor lands on the world grid (step = 0.1 m x your size, rounded to 1 / 2 / 5);
ALIGN: each axis snaps on its own to the nearest candidate coordinate (one axis = a plane, two = a line, three = an exact
spot), with a release margin so it doesn't flicker. Only the POSITION snaps: ONE correction moves the whole grabbed set.
The candidate list is built ONCE at the grab start; a frame is a few numpy calls on 3 axes."""
import math

import numpy as np

OFF, GRID, ALIGN = 'OFF', 'GRID', 'ALIGN'
MODES = (OFF, GRID, ALIGN)
BASE_STEP = 0.1            # m at your size 1: "about 1/10 m at normal person size"
TOLERANCE = 0.02           # m in your space: how close an axis must come to a candidate to snap
RELEASE = 1.5              # a snapped axis lets go at this many tolerances (no flicker)
MAX_CANDIDATES = 4000      # per axis (nearest kept): the frame cost stays flat on big meshes / scenes


def round_125(value):
    """`value` rounded to the nearest 1, 2 or 5 times a power of ten (so in-between sizes stay neat)."""
    if value <= 0:
        return BASE_STEP
    exponent = math.floor(math.log10(value))
    mantissa = value / 10 ** exponent
    best = min((1.0, 2.0, 5.0, 10.0), key=lambda option: abs(math.log(mantissa / option)))
    return best * 10 ** exponent


def grid_step(user_scale):
    """The world grid step for your size (0.1 m at size 1)."""
    return round_125(BASE_STEP * user_scale)


def grid_correction(anchor, step):
    """Offset that puts `anchor` (3,) on the nearest grid point."""
    anchor = np.asarray(anchor, float)
    return np.round(anchor / step) * step - anchor


class AxisCandidates:
    """Per-axis sorted candidate coordinates (3 arrays). `nearest(axis, value)` -> the candidate nearest `value`."""

    def __init__(self, values):
        self.values = [np.unique(np.asarray(axis, float)) for axis in values]

    @classmethod
    def from_points(cls, points, around=None, limit=MAX_CANDIDATES):
        """Candidates = the coordinates of `points` (n, 3); when there are more than `limit`, the ones nearest `around`."""
        points = np.asarray(points, float).reshape(-1, 3)
        if around is not None and len(points) > limit:
            order = np.argsort(((points - np.asarray(around)) ** 2).sum(axis=1))[:limit]
            points = points[order]
        return cls([points[:, axis] for axis in range(3)])

    def nearest(self, axis, value):
        values = self.values[axis]
        if not len(values):
            return None
        index = int(np.searchsorted(values, value))
        options = values[max(index - 1, 0):index + 1]
        return float(options[np.argmin(np.abs(options - value))])


class AlignSnapper:
    """ALIGN for ONE grab. `features` (m, 3): the points of the grabbed set that may line up (Edit: the vertex nearest your
    hand; Object: the origin and the box's centre / corners), in the same space as the candidates. `correct(shift)`
    takes the grab's current shift of the whole set (3,) and returns (correction (3,), snapped (3,) bools, matches):
    `matches[axis]` = (feature index, candidate value) for the guide lines."""

    def __init__(self, features, candidates, tolerance=TOLERANCE, release=RELEASE):
        self.features = np.asarray(features, float).reshape(-1, 3)
        self.candidates = candidates
        self.tolerance, self.release = tolerance, release
        self.locked = [None, None, None]        # axis -> (feature, candidate value) while snapped

    def correct(self, shift):
        """For a plain shift of every feature."""
        return self.correct_moved(self.features + np.asarray(shift, float))

    def correct_moved(self, moved):
        """For the features' positions now (a rotating grab moves them differently): the same result."""
        correction = np.zeros(3)
        snapped = [False, False, False]
        matches = [None, None, None]
        for axis in range(3):
            held = self.locked[axis]
            if held is not None:
                feature, value = held
                if abs(moved[feature, axis] - value) <= self.tolerance * self.release:     # still within the release margin
                    correction[axis], snapped[axis], matches[axis] = value - moved[feature, axis], True, held
                    continue
                self.locked[axis] = None
            best = None
            for feature in range(len(moved)):
                value = self.candidates.nearest(axis, moved[feature, axis])
                if value is not None and abs(value - moved[feature, axis]) <= self.tolerance:
                    gap = abs(value - moved[feature, axis])
                    if best is None or gap < best[0]:
                        best = (gap, feature, value)
            if best is not None:
                self.locked[axis] = (best[1], best[2])
                correction[axis], snapped[axis], matches[axis] = best[2] - moved[best[1], axis], True, self.locked[axis]
        return correction, snapped, matches


def nearest_row(points, target):
    """Row of `points` (n, 3) nearest `target`."""
    points = np.asarray(points, float)
    return int(np.argmin(((points - np.asarray(target)) ** 2).sum(axis=1)))


def box_features(minimum, maximum):
    """Object mode features of a box: its centre, then its 8 corners (world axes)."""
    minimum, maximum = np.asarray(minimum, float), np.asarray(maximum, float)
    corners = [[x, y, z] for x in (minimum[0], maximum[0]) for y in (minimum[1], maximum[1]) for z in (minimum[2], maximum[2])]
    return np.array([(minimum + maximum) / 2.0] + corners)
