# SPDX-License-Identifier: GPL-3.0-or-later
"""Sculpt mode's drag brushes without bpy: Grab, Elastic Grab, Snake Hook and Pose. Blender's own versions need one
unbroken mouse drag, which a call per headset frame can't give (docs/spikes/SPIKE-SCULPT.md "Brushes"), and they read
the hand's motion only in the desktop view's plane. These follow Blender's formulas (editors/sculpt_paint/mesh/brushes/
grab.cc, elastic_deform.cc, snake_hook.cc, sculpt_pose.cc) in the object's space, on the base mesh. Each caches what it
needs when the stroke touches the mesh, then moves the cached vertices each frame. Tested headless."""
import math

import numpy as np

GRAB, ELASTIC, SNAKE_HOOK, POSE = 'GRAB', 'ELASTIC_DEFORM', 'SNAKE_HOOK', 'POSE'
DRAG_BRUSHES = frozenset({GRAB, ELASTIC, SNAKE_HOOK, POSE})
ELASTIC_TYPES = ('GRAB', 'GRAB_BISCALE', 'GRAB_TRISCALE')       # the others turn by the mouse's side of the start
# Settings the deformers follow; any other value: the brush is refused, with the setting's name (unsupported())
SUPPORTED = {ELASTIC: ("elastic_deform_type", ELASTIC_TYPES, "Elastic mode"),
             SNAKE_HOOK: ("snake_hook_deform_type", ('FALLOFF',), "Snake Hook mode"),
             POSE: ("pose_deform_type", ('ROTATE_TWIST',), "Pose deformation")}
POSE_ORIGIN = ("pose_origin_type", ('TOPOLOGY',), "Pose origin")
KELVINLET_SCALE = 20.0          # Blender scales Kelvinlet moves by strength x 20
SHEAR_MODULUS = 1.0


def unsupported(brush_type, settings):
    """The label of a brush setting the drag brushes can't follow, or "". settings: {name: value} of the brush."""
    checks = [SUPPORTED[brush_type]] if brush_type in SUPPORTED else []
    if brush_type == POSE:
        checks.append(POSE_ORIGIN)
    for name, allowed, label in checks:
        if settings.get(name, allowed[0]) not in allowed:
            return label
    return ""


# ---- falloff --------------------------------------------------------------------------------------------------------

_PRESETS = {
    'SHARP': lambda p: p * p,
    'SMOOTH': lambda p: 3.0 * p * p - 2.0 * p ** 3,
    'SMOOTHER': lambda p: p ** 3 * (p * (p * 6.0 - 15.0) + 10.0),
    'ROOT': np.sqrt,
    'LIN': lambda p: p,
    'CONSTANT': np.ones_like,
    'SPHERE': lambda p: np.sqrt(np.maximum(2.0 * p - p * p, 0.0)),
    'POW4': lambda p: p ** 4,
    'INVSQUARE': lambda p: p * (2.0 - p),
}


def falloff(preset, table=None):
    """f(share) -> weights: Blender's brush falloff (BKE_brush_curve_strength) for share = distance / radius; 0 from 1 on.
    'CUSTOM' reads `table`: the brush's curve sampled evenly over 0 .. 1 of the share."""
    if preset == 'CUSTOM' and table is not None:
        samples = np.asarray(table, np.float32)
        steps = np.linspace(0.0, 1.0, len(samples), dtype=np.float32)
        shape = lambda p: np.interp(1.0 - p, steps, samples)
    else:
        shape = _PRESETS.get(preset, _PRESETS['SMOOTH'])

    def weights(share):
        share = np.asarray(share, np.float32)
        return np.where(share < 1.0, shape(1.0 - np.minimum(share, 1.0)), 0.0).astype(np.float32)
    return weights


def mirror_signs(axes):
    """The symmetry passes for the mirrored axes (x, y, z bools): sign vectors, the stroke itself first."""
    signs = [np.ones(3, np.float32)]
    for index, on in enumerate(axes):
        if on:
            flipped = [sign.copy() for sign in signs]
            for sign in flipped:
                sign[index] = -1.0
            signs += flipped
    return signs


def kelvinlet(kind, distance, radius, poisson):
    """Blender's regularized Kelvinlet grab fade (BKE_kelvinlet_grab*) at `distance` from the brush, without strength."""
    a = 1.0 / (4.0 * math.pi * SHEAR_MODULUS)
    b = a / (4.0 * (1.0 - poisson))
    c = 2.0 * (3.0 * a - 2.0 * b)
    scales = {'GRAB': 1, 'GRAB_BISCALE': 2, 'GRAB_TRISCALE': 3}[kind]
    radii = [radius * factor for factor in (1.0, 2.0, 4.0)][:scales]
    distance = np.asarray(distance, np.float64)

    def term(scaled):
        spread = np.sqrt(distance * distance + scaled * scaled)
        return (a - b) / spread + b * distance * distance / spread ** 3 + a * scaled * scaled / (2.0 * spread ** 3)
    if scales == 1:
        fade = term(radii[0]) * c
    elif scales == 2:
        fade = (term(radii[0]) - term(radii[1])) * c / (1.0 / radii[0] - 1.0 / radii[1])
    else:
        low, mid, high = (value * value for value in radii)
        weights = (1.0, -(high - low) / (high - mid), (mid - low) / (high - mid))
        fade = sum(weight * term(scaled) for weight, scaled in zip(weights, radii)) * c / sum(
            weight / scaled for weight, scaled in zip(weights, radii))
    return fade.astype(np.float32)


# ---- the brushes ----------------------------------------------------------------------------------------------------

class Settings:
    """What a drag brush reads from Blender's brush, the mesh and the stroke (plain values)."""

    def __init__(self, radius, strength=1.0, weights=None, mirror=(False, False, False), elastic_type='GRAB',
                 poisson=0.4, pose_offset=0.0, smooth_iterations=4):
        self.radius, self.strength = max(float(radius), 1e-9), float(strength)
        self.weights = weights or falloff('SMOOTH')
        self.signs = mirror_signs(mirror)
        self.elastic_type, self.poisson = elastic_type, float(poisson)
        self.pose_offset, self.smooth_iterations = float(pose_offset), int(smooth_iterations)


class Drag:
    """One drag stroke on `start` (n, 3) object-space positions. `factor` (n): 1 - mask, 0 where hidden (None = 1).
    move(positions, tip) writes the positions for the tip at `tip` (object space) into `positions` (n, 3)."""

    def __init__(self, start, tip, settings, factor=None):
        self.start = np.asarray(start, np.float32).reshape(-1, 3)
        self.tip = np.asarray(tip, np.float32)
        self.settings = settings
        self.factor = np.ones(len(self.start), np.float32) if factor is None else np.asarray(factor, np.float32)

    def _near(self, positions, centre, among=None):
        """(indices, weights) of the vertices (of `among`, default all) within the radius of `centre`, weighted by the
        falloff and strength."""
        offset = (positions if among is None else positions[among]) - centre
        distance_sq = np.einsum('ij,ij->i', offset, offset)
        radius = self.settings.radius
        inside = np.flatnonzero(distance_sq < radius * radius)
        indices = inside if among is None else among[inside]
        weights = self.settings.weights(np.sqrt(distance_sq[inside]) / radius) * self.settings.strength * self.factor[indices]
        keep = weights > 0.0
        return indices[keep], weights[keep]


class Grab(Drag):
    """The vertices in the brush at the start follow the hand (falloff x strength)."""

    def __init__(self, start, tip, settings, factor=None):
        super().__init__(start, tip, settings, factor)
        self.passes = [(sign, *self._near(self.start, self.tip * sign)) for sign in settings.signs]
        self.touched = np.unique(np.concatenate([indices for _sign, indices, _weights in self.passes]))

    @property
    def empty(self):
        return not len(self.touched)

    def move(self, positions, tip):
        delta = np.asarray(tip, np.float32) - self.tip
        positions[self.touched] = self.start[self.touched]
        for sign, indices, weights in self.passes:
            positions[indices] += weights[:, None] * (delta * sign)


class ElasticGrab(Drag):
    """Grab with a Kelvinlet fade (no radius limit: the whole mesh gives a little, as in Blender)."""

    def __init__(self, start, tip, settings, factor=None):
        super().__init__(start, tip, settings, factor)
        scale = KELVINLET_SCALE * settings.strength * self.factor
        self.passes = []
        for sign in settings.signs:
            distance = np.linalg.norm(self.start - self.tip * sign, axis=1)
            self.passes.append((sign, kelvinlet(settings.elastic_type, distance, settings.radius, settings.poisson) * scale))
        self.empty = False                  # make() saw the tip touch the mesh

    def move(self, positions, tip):
        delta = np.asarray(tip, np.float32) - self.tip
        positions[:] = self.start
        for sign, fade in self.passes:
            positions += fade[:, None] * (delta * sign)


class SnakeHook(Drag):
    """Each frame the vertices in the brush (as they are now) move with the hand's step: the surface is pulled along.
    Only vertices that moved before, or start in the brush's x range, are looked at (sorted by x once)."""

    def __init__(self, start, tip, settings, factor=None):
        super().__init__(start, tip, settings, factor)
        self.last = self.tip
        self.now = self.start.copy()
        self.order = np.argsort(self.start[:, 0], kind='stable')
        self.sorted_x = self.start[self.order, 0]
        self.moved = np.zeros(len(self.start), bool)
        self.moved_indices = np.zeros(0, np.int64)
        self.empty = not len(self._near(self.start, self.tip)[0])

    def _candidates(self, centre):
        low, high = np.searchsorted(self.sorted_x, (centre[0] - self.settings.radius, centre[0] + self.settings.radius))
        fresh = self.order[low:high]
        return np.concatenate([fresh[~self.moved[fresh]], self.moved_indices])

    def move(self, positions, tip):
        tip = np.asarray(tip, np.float32)
        delta = tip - self.last
        for sign in self.settings.signs:
            indices, weights = self._near(self.now, self.last * sign, self._candidates(self.last * sign))
            self.now[indices] += weights[:, None] * (delta * sign)
            fresh = indices[~self.moved[indices]]
            self.moved[fresh] = True
            self.moved_indices = np.concatenate([self.moved_indices, fresh])
        self.last = tip
        positions[:] = self.now


class Pose(Drag):
    """The part of the mesh in the brush (joined to the vertex under the tip) turns about the centre of its edge, so its
    tip points at the hand. `edges` (m, 2): the mesh's edges. One segment; no IK chain, twist or face sets."""

    def __init__(self, start, tip, settings, factor=None, edges=None):
        super().__init__(start, tip, settings, factor)
        edges = np.asarray(edges, np.int64).reshape(-1, 2)
        self.passes, taken = [], np.zeros(len(self.start), bool)
        for sign in settings.signs:
            part = pose_part(self.start, edges, self.tip * sign, settings, self.factor)
            if part is None or taken[part[2]].any():
                continue                    # nothing there, or the mirror's part is this one (a tip on the mirror plane)
            origin, weights, indices = part
            taken[indices] = True
            self.passes.append((sign, origin, weights, indices))
        self.touched = np.flatnonzero(taken)

    @property
    def empty(self):
        return not self.passes

    def move(self, positions, tip):
        tip = np.asarray(tip, np.float32)
        positions[self.touched] = self.start[self.touched]
        for sign, origin, weights, indices in self.passes:
            axis, angle = turn_between(self.tip * sign - origin, tip * sign - origin)
            if angle > 0.0:
                positions[indices] = rotate(self.start[indices], origin, axis, angle * weights)


def nearest(points, point, usable):
    offset = points - point
    distance_sq = np.einsum('ij,ij->i', offset, offset)
    distance_sq[~usable] = np.inf
    index = int(distance_sq.argmin())
    return index if np.isfinite(distance_sq[index]) else None


def pose_part(start, edges, tip, settings, factor):
    """(origin, weights, indices) of the Pose brush's part for a tip, or None. Blender's flood fill: from the vertex
    nearest the tip through the vertices in the brush; the first vertices outside are in the part too, and their centre
    is the origin. The weights are smoothed at the part's edge."""
    radius = settings.radius
    seed = nearest(start, tip, factor > 0.0)
    if seed is None or np.linalg.norm(start[seed] - tip) > radius:
        return None
    offset = start - tip
    inside = np.einsum('ij,ij->i', offset, offset) < radius * radius
    reached = np.zeros(len(start), bool)
    reached[seed] = True
    both_ways = np.concatenate([edges, edges[:, ::-1]])
    spreading = both_ways[inside[both_ways[:, 0]]]        # edges that leave a vertex inside the brush
    while True:
        grown = reached.copy()
        grown[spreading[reached[spreading[:, 0]], 1]] = True
        if np.array_equal(grown, reached):
            break
        reached = grown
    ring = reached & ~inside
    if ring.any():
        origin = start[ring].mean(axis=0)
    else:                                   # the whole piece is in the brush: turn about its farthest vertex
        distance = np.where(reached, np.einsum('ij,ij->i', offset, offset), -1.0)
        origin = start[int(distance.argmax())]
    away = origin - tip
    length = float(np.linalg.norm(away))
    if length > 1e-9:
        origin = origin + away / length * radius * settings.pose_offset
    weights = smooth_values(reached.astype(np.float32), edges, settings.smooth_iterations) * factor
    indices = np.flatnonzero(weights > 1e-6)
    return origin.astype(np.float32), weights[indices], indices


def smooth_values(values, edges, iterations):
    """Each vertex takes the mean of itself and its neighbours, `iterations` times."""
    count = len(values)
    neighbours = np.bincount(edges.ravel(), minlength=count).astype(np.float32) + 1.0
    for _ in range(iterations):
        summed = values.copy()
        summed += np.bincount(edges[:, 0], weights=values[edges[:, 1]], minlength=count)
        summed += np.bincount(edges[:, 1], weights=values[edges[:, 0]], minlength=count)
        values = (summed / neighbours).astype(np.float32)
    return values


def turn_between(first, second):
    """(unit axis, angle) of the shortest turn from one direction to the other; angle 0 when there is none."""
    first, second = np.asarray(first, np.float64), np.asarray(second, np.float64)
    cross = np.cross(first, second)
    size = float(np.linalg.norm(cross))
    if size < 1e-12 or np.linalg.norm(first) < 1e-12 or np.linalg.norm(second) < 1e-12:
        return np.array((0.0, 0.0, 1.0)), 0.0
    return cross / size, math.atan2(size, float(np.dot(first, second)))


def rotate(points, origin, axis, angles):
    """`points` (k, 3) turned about `origin` and the unit `axis` by `angles` (k,) radians each (Rodrigues)."""
    local = points - origin
    cos, sin = np.cos(angles)[:, None], np.sin(angles)[:, None]
    axis = axis.astype(np.float32)
    along = (local @ axis)[:, None] * axis
    turned = local * cos + np.cross(axis, local) * sin + along * (1.0 - cos)
    return (turned + origin).astype(np.float32)


KINDS = {GRAB: Grab, ELASTIC: ElasticGrab, SNAKE_HOOK: SnakeHook, POSE: Pose}


def make(brush_type, start, tip, settings, factor=None, edges=None):
    """The drag brush for `brush_type` touching the mesh at `tip`, or None when it touches nothing there."""
    points = np.asarray(start, np.float32).reshape(-1, 3)
    offset = points - np.asarray(tip, np.float32)
    if not (np.einsum('ij,ij->i', offset, offset) < settings.radius ** 2).any():
        return None                         # in the air: cheap, as it runs each frame until the tip meets the mesh
    kind = KINDS[brush_type]
    drag = kind(start, tip, settings, factor, edges) if kind is Pose else kind(start, tip, settings, factor)
    return None if drag.empty else drag
