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
    """World line segments (n, 2, 3) the overlay draws: `lines` = what the snap lines up with, `marks` = small crosses on
    the candidate points near the anchor, `active` = a big cross on the point the magnet holds. `version` moves on every
    change (the overlay rebuilds)."""
    lines = np.zeros((0, 2, 3))
    marks = np.zeros((0, 2, 3))
    active = np.zeros((0, 2, 3))
    version = 0

    @classmethod
    def set(cls, lines, marks=(), active=()):
        new = [np.asarray(part, float).reshape(-1, 2, 3) for part in (lines, marks, active)]
        if any(len(part) for part in new) or cls.shown():
            cls.lines, cls.marks, cls.active = new
            cls.version += 1

    @classmethod
    def shown(cls):
        return bool(len(cls.lines) or len(cls.marks) or len(cls.active))

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


def radius():
    """The magnet's reach in the world: snap_math.RADIUS in your space."""
    return snap_math.RADIUS * size_state.scaled(1.0)


MARKER_LENGTH = 0.012      # m at your size 1: the arms of a candidate marker
ACTIVE_LENGTH = 0.03       # m at your size 1: the arms of the marker of the point the magnet holds
MAX_MARKERS = 60


def axis_cross(point, length):
    """Three world-axis segments through `point`."""
    return [[point - axis * length, point + axis * length] for axis in np.eye(3)]


def candidate_marks(snapper, anchor, to_world, metric=None):
    """(marks, active) world segments: a small cross on every candidate point within radius x MARKER_REACH of `anchor`
    (in the snapper's space; `to_world` maps points there to the world), a big one on the point the magnet holds."""
    near = snapper.candidates.near(anchor, radius() * snap_math.MARKER_REACH, metric)
    if len(near) > MAX_MARKERS:
        gaps = snap_math.distances(snapper.candidates.points[near] - anchor, metric)
        near = near[np.argsort(gaps)[:MAX_MARKERS]]
    marks = [segment for index in near for segment in axis_cross(to_world(snapper.candidates.points[index]), size_state.scaled(MARKER_LENGTH))]
    active = axis_cross(to_world(snapper.point), size_state.scaled(ACTIVE_LENGTH)) if snapper.point is not None else []
    return marks, active


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
                    tolerance() / self.scale, radius=radius(), metric=self.rotation)

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
        marks, active = candidate_marks(self.snapper, anchor + correction, lambda point: self.rotation @ point + self.matrix[:3, 3], self.rotation)
        lines = []
        if any(snapped):
            point = self.rotation @ (anchor + correction) + self.matrix[:3, 3]
            lines = guide_lines(point, snapped, (self.rotation / self.scale).T, size_state.scaled(GUIDE_LENGTH))
        Guides.set(lines, marks, active)
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
        self.snapper = (snap_math.AlignSnapper(self.features, candidates, tolerance(), radius=radius())
                        if self.mode == snap_math.ALIGN and candidates is not None else None)

    def apply(self, matrix):
        world = np.array(matrix)
        if self.mode == snap_math.GRID:
            anchor = world[:3, :3] @ self.origin + world[:3, 3]
            correction = snap_math.grid_correction(anchor, self.step)
            Guides.set(guide_lines(anchor + correction, [True, True, True], np.eye(3), size_state.scaled(GUIDE_LENGTH) / 3))
        else:
            moved = self.features @ world[:3, :3].T + world[:3, 3]
            correction, snapped, matches = self.snapper.correct_moved(moved)
            marks, active = candidate_marks(self.snapper, moved[0] + correction, lambda point: point)
            lines = []
            if any(snapped):
                row = next(match[0] for match in matches if match is not None)
                lines = guide_lines(moved[row] + correction, snapped, np.eye(3), size_state.scaled(GUIDE_LENGTH))
            Guides.set(lines, marks, active)
        out = np.array(world)
        out[:3, 3] += correction
        return Matrix(out.tolist())


def _object_corners(ob):
    from mathutils import Vector
    corners = np.array([tuple(ob.matrix_world @ Vector(corner)) for corner in ob.bound_box]) if ob.type != 'EMPTY' else \
        np.array([tuple(ob.matrix_world.translation)])
    return corners


def _with_children(grabbed_objects):
    """The grabbed objects plus every child that moves with them: they snap as one piece and never onto themselves."""
    moving = {ob.name_full: ob for ob in grabbed_objects}
    for ob in grabbed_objects:
        moving.update((child.name_full, child) for child in ob.children_recursive)
    return list(moving.values())


def object_snap(context, grabbed_objects):
    """The ObjectSnap for new Object mode grabs of `grabbed_objects` (objects only: never Pose bones), or None."""
    if mode() == snap_math.OFF or not grabbed_objects:
        return None
    moving = _with_children(grabbed_objects)        # children ride along (Smart select grabs a rig's top parent)
    names = {ob.name_full for ob in moving}
    corners = np.vstack([_object_corners(ob) for ob in moving])
    anchor = context.view_layer.objects.active if context.view_layer.objects.active in grabbed_objects else grabbed_objects[0]
    ordered = [anchor] + [ob for ob in grabbed_objects if ob is not anchor]       # feature 0 = the active one's origin
    features = np.vstack([[tuple(ob.matrix_world.translation) for ob in ordered],
                          snap_math.box_features(corners.min(axis=0), corners.max(axis=0))])
    origin = np.array(tuple(anchor.matrix_world.translation))
    candidates = None
    if mode() == snap_math.ALIGN:
        reach = size_state.scaled(NEARBY)
        points = []
        RUNTIME.cache.pickable_objects(context.scene, context.view_layer)
        for ob in RUNTIME.cache.everything:         # snaps onto everything visible, not only the workspace
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
