# SPDX-License-Identifier: GPL-3.0-or-later
"""Maths of Edit mode's active tools (numpy, no bpy): how far the hand drove a tool, how far an effect can go before the
mesh folds, and where the points of a loop cut lie."""
import numpy as np

START_TRAVEL = 0.005      # m at user size 1: a hand that moved less drove nothing (a held hand trembles)
FOLD_SHARE = 0.99         # an effect stops this close to the point where an edge collapses
NO_LIMIT = 1e6


def soft(value, dead):
    """`value` with a dead zone round zero, continuous (no jump where it starts)."""
    return float(np.sign(value) * max(0.0, abs(value) - dead))


class HandTravel:
    """How far the hand drove an effect since the start, as one signed number. With an `axis` (unit vector): the travel
    along it. Without: the first real movement sets the axis ("away from the start"), moving back shrinks to zero and
    never below."""

    def __init__(self, dead, axis=None):
        self.dead = dead
        self.given = axis is not None
        self.axis = None if axis is None else np.asarray(axis, float)

    def amount(self, travel):
        travel = np.asarray(travel, float)
        if self.axis is None:
            length = float(np.linalg.norm(travel))
            if length <= self.dead:
                return 0.0
            self.axis = travel / length
        along = soft(float(travel @ self.axis), self.dead)
        return along if self.given else max(0.0, along)


def collapse_limit(origin, dirs, heads, tails):
    """How far points `origin + dirs * amount` (amount > 0) may go before an edge (rows heads -> tails) collapses."""
    if not len(heads):
        return NO_LIMIT
    gap = origin[heads] - origin[tails]
    closing = np.einsum("ij,ij->i", dirs[heads] - dirs[tails], gap)
    length = np.einsum("ij,ij->i", gap, gap)
    shrinks = (length > 1e-14) & (closing < -1e-12 * np.sqrt(length))
    if not shrinks.any():
        return NO_LIMIT
    return FOLD_SHARE * float((length[shrinks] / -closing[shrinks]).min())


def cut_fractions(cuts):
    """Where the cuts sit along each ring edge (0 to 1)."""
    return np.arange(1, cuts + 1) / (cuts + 1)


def cut_points(heads, tails, cuts):
    """(rows, cuts, 3) points of a loop cut on the ring edges heads -> tails."""
    return heads[:, None, :] + cut_fractions(cuts)[None, :, None] * (tails - heads)[:, None, :]


def preview_lines(heads, tails, pairs, cuts):
    """(n, 3) line pairs of a loop cut's preview: `pairs` (m, 2) are ring rows that share a face."""
    points = cut_points(heads, tails, cuts)
    return np.stack((points[pairs[:, 0]], points[pairs[:, 1]]), axis=2).reshape(-1, 3)


def slide(heads, tails, cuts, even, reference_length):
    """(dirs per cut point (rows * cuts, 3), limit): the slide is a share of the aimed edge (length `reference_length`).
    Not even: every ring edge slides by the same share of its own length; even: by the same distance."""
    along = tails - heads
    lengths = np.linalg.norm(along, axis=1)
    if even:
        along = along / np.maximum(lengths, 1e-12)[:, None] * reference_length
        limit = float(lengths.min()) / reference_length
    else:
        limit = 1.0
    return np.repeat(along, cuts, axis=0), FOLD_SHARE * limit / (cuts + 1)
