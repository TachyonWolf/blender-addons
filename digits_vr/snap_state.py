# SPDX-License-Identifier: GPL-3.0-or-later
"""Snapping for grabs (bpy side): builds the snapper ONCE at the grab start (candidates from the connected vertices in Edit
mode, from the other objects in Object mode) and keeps the guide lines the overlay draws. The setting `snap_mode` (Off /
Grid / Align, VR-only: Blender's own snap settings are never written). The maths is snap_math.py (pure)."""
import numpy as np
from mathutils import Matrix

from . import settings, size_state, snap_math
from .runtime import RUNTIME

GUIDE_LENGTH = 0.3       # m at your size 1: the arms of a guide cross
NEARBY = 3.0             # m at your size 1: other objects farther than this are no candidates


class Guides:
    """World line segments (n, 2, 3) of what the snap lines up with; `version` moves on every change (the overlay rebuilds)."""
    lines = np.zeros((0, 2, 3))
    version = 0

    @classmethod
    def set(cls, lines):
        if len(lines) or len(cls.lines):
            cls.lines = np.asarray(lines, float).reshape(-1, 2, 3)
            cls.version += 1

    @classmethod
    def clear(cls):
        cls.set([])


def mode():
    return settings.get("snap_mode")


def _cross(point, axes, length):
    """Two guide segments through `point` along the two axes (rows of `axes`) that are not the snapped one."""
    return [[point - axis * length, point + axis * length] for axis in axes]


def guide_lines(anchor_world, snapped, axes, length):
    """Guide segments for a snap at `anchor_world`: per snapped axis a cross in its plane (a plane), so two snapped axes
    draw a line's worth of crosses meeting, three an exact spot. `axes` (3, 3) = the snap space's axes in the world."""
    lines = []
    for axis, on in enumerate(snapped):
        if on:
            lines += _cross(anchor_world, [axes[other] for other in range(3) if other != axis], length)
    return lines


def tolerance():
    return snap_math.TOLERANCE * size_state.scaled(1.0)


class EditSnap:
    """Snapping of an Edit mode grab, in the object's LOCAL axes (the correction is one offset for the whole set; Mirror X
    twins follow it because they derive from the corrected points)."""

    def __init__(self, ob, matrix, base, anchor_row, selected, bm):
        self.mode = mode()
        self.matrix, self.anchor_row = matrix, anchor_row
        self.rotation = matrix[:3, :3]
        self.base_anchor = base[anchor_row].copy()
        self.scale = float(abs(np.linalg.det(self.rotation)) ** (1 / 3)) or 1.0
        self.step = snap_math.grid_step(size_state.scaled(1.0))
        self.snapper = None
        if self.mode == snap_math.ALIGN:
            around = base[anchor_row]
            neighbours = []
            for vertex in (bm.verts[i] for i in selected):
                for edge in vertex.link_edges:
                    other = edge.other_vert(vertex)
                    if not other.select and not other.hide:
                        neighbours.append(other.co[:])
            if neighbours:
                self.snapper = snap_math.AlignSnapper(
                    base[anchor_row:anchor_row + 1], snap_math.AxisCandidates.from_points(neighbours, around),
                    tolerance() / self.scale)

    @property
    def active(self):
        return self.mode == snap_math.GRID or self.snapper is not None

    def correct(self, moved):
        """`moved` (k, 3) local points of the grab now: the same points plus ONE correction."""
        anchor = moved[self.anchor_row]
        if self.mode == snap_math.GRID:
            world = self.rotation @ anchor + self.matrix[:3, 3]
            correction_world = snap_math.grid_correction(world, self.step)
            correction = np.linalg.solve(self.rotation, correction_world)
            Guides.set(guide_lines(world + correction_world, [True, True, True], np.eye(3), size_state.scaled(GUIDE_LENGTH) / 3))
            return moved + correction
        correction, snapped, _matches = self.snapper.correct_moved(anchor.reshape(1, 3))
        if any(snapped):
            point = self.rotation @ (anchor + correction) + self.matrix[:3, 3]
            Guides.set(guide_lines(point, snapped, (self.rotation / self.scale).T, size_state.scaled(GUIDE_LENGTH)))
        else:
            Guides.clear()
        return moved + correction


def edit_snap(ob, matrix, base, selected, bm, hand_world):
    """The EditSnap for a new Edit grab, or None (Off, or nothing to align to). The anchor = the grabbed vertex nearest
    the hand."""
    if mode() == snap_math.OFF:
        return None
    world = base @ matrix[:3, :3].T + matrix[:3, 3]
    snap = EditSnap(ob, matrix, base, snap_math.nearest_row(world, hand_world), selected, bm)
    return snap if snap.active else None


class ObjectSnap:
    """Snapping of an Object mode grab (world axes): features = the grabbed objects' origins + their box (centre and 8
    corners); candidates = origins and boxes of the other visible objects nearby. `apply(matrix)` -> the grab's world
    matrix with ONE translation correction."""

    def __init__(self, features, origin, candidates):
        self.mode = mode()
        self.features, self.origin = np.asarray(features, float), np.asarray(origin, float)
        self.step = snap_math.grid_step(size_state.scaled(1.0))
        self.snapper = (snap_math.AlignSnapper(self.features, candidates, tolerance())
                        if self.mode == snap_math.ALIGN and candidates is not None else None)

    def apply(self, matrix):
        m = np.array(matrix)
        if self.mode == snap_math.GRID:
            anchor = m[:3, :3] @ self.origin + m[:3, 3]
            correction = snap_math.grid_correction(anchor, self.step)
            Guides.set(guide_lines(anchor + correction, [True, True, True], np.eye(3), size_state.scaled(GUIDE_LENGTH) / 3))
        else:
            moved = self.features @ m[:3, :3].T + m[:3, 3]
            correction, snapped, matches = self.snapper.correct_moved(moved)
            if any(snapped):
                row = next(match[0] for match in matches if match is not None)
                Guides.set(guide_lines(moved[row] + correction, snapped, np.eye(3), size_state.scaled(GUIDE_LENGTH)))
            else:
                Guides.clear()
        out = np.array(m)
        out[:3, 3] += correction
        return Matrix(out.tolist())


def _object_corners(ob):
    from mathutils import Vector
    corners = np.array([tuple(ob.matrix_world @ Vector(corner)) for corner in ob.bound_box]) if ob.type != 'EMPTY' else \
        np.array([tuple(ob.matrix_world.translation)])
    return corners


def object_snap(context, grabbed_objects):
    """The ObjectSnap for new Object mode grabs of `grabbed_objects` (objects only: never Pose bones), or None."""
    if mode() == snap_math.OFF or not grabbed_objects:
        return None
    names = {ob.name_full for ob in grabbed_objects}
    corners = np.vstack([_object_corners(ob) for ob in grabbed_objects])
    features = np.vstack([[tuple(ob.matrix_world.translation) for ob in grabbed_objects],
                          snap_math.box_features(corners.min(axis=0), corners.max(axis=0))])
    origin = np.array(tuple(grabbed_objects[0].matrix_world.translation))
    candidates = None
    if mode() == snap_math.ALIGN:
        reach = size_state.scaled(NEARBY)
        points = []
        for ob in RUNTIME.cache.pickable_objects(context.scene, context.view_layer):
            if ob.name_full in names:
                continue
            box = _object_corners(ob)
            if np.linalg.norm(box.mean(axis=0) - origin) > reach:
                continue
            points += [tuple(ob.matrix_world.translation), *snap_math.box_features(box.min(axis=0), box.max(axis=0)).tolist()]
        if not points:
            return None
        candidates = snap_math.AxisCandidates.from_points(points, origin)
    return ObjectSnap(features, origin, candidates)
