# SPDX-License-Identifier: GPL-3.0-or-later
"""Picking math: what a hand touches or a laser points at. numpy + plain tuples (no bpy), tested headless.
Bones are edges: a plain bone is its segment (head, tail) with a reach that grows with bone length, a bone with a
custom shape is its shape's edges, placed by Blender's drawing rule; boxes are world-space AABBs."""
import itertools
import math

import numpy as np

BONE_REACH_FACTOR = 0.25   # a bone can be touched this fraction of its length away from its axis (bones sit inside the mesh)
LASER_BONE_RADIUS = 0.02   # m: least laser reach around a bone
LASER_BONE_FACTOR = 0.12   # ... plus this fraction of the bone's length
GRID_CELL = 0.1            # m: cell size of the touch grid of bones
MAX_BONE_CELLS = 4000      # a bone reaching more cells is checked on every touch query instead
LASER_POINT_RADIUS = 0.05  # m: laser reach around an object without a mesh (empty, light, camera)


def segment_distances(point, heads, tails):
    """Distance from `point` to each segment heads[i]-tails[i] (numpy arrays N x 3). Returns N distances."""
    point = np.asarray(point, dtype=np.float64)
    axis = tails - heads
    length_sq = np.einsum('ij,ij->i', axis, axis)
    along = np.einsum('ij,ij->i', point - heads, axis) / np.where(length_sq > 0, length_sq, 1.0)
    closest = heads + axis * np.clip(along, 0.0, 1.0)[:, None]
    offset = closest - point
    return np.sqrt(np.einsum('ij,ij->i', offset, offset))


def ray_segment_distances(origin, direction, heads, tails):
    """For a ray (origin, unit direction) and N segments: (distance between ray and segment, distance along the
    ray to the closest point). Segments behind the origin get an infinite distance."""
    origin = np.asarray(origin, dtype=np.float64)
    direction = np.asarray(direction, dtype=np.float64)
    axis = tails - heads
    offset = heads - origin
    axis_sq = np.einsum('ij,ij->i', axis, axis)
    axis_dot_dir = axis @ direction
    offset_dot_dir = offset @ direction
    offset_dot_axis = np.einsum('ij,ij->i', offset, axis)
    denominator = axis_sq - axis_dot_dir ** 2           # |dir| = 1
    safe = np.where(np.abs(denominator) > 1e-12, denominator, 1.0)
    along_segment = np.where(np.abs(denominator) > 1e-12,
                             (axis_dot_dir * offset_dot_dir - offset_dot_axis) / safe, 0.0)
    along_segment = np.clip(along_segment, 0.0, 1.0)
    on_segment = heads + axis * along_segment[:, None]
    along_ray = np.maximum((on_segment - origin) @ direction, 0.0)
    on_ray = origin + np.outer(along_ray, direction)
    gap = on_segment - on_ray
    distance = np.sqrt(np.einsum('ij,ij->i', gap, gap))
    behind = (on_segment - origin) @ direction < 0
    return np.where(behind, np.inf, distance), along_ray


def bone_lengths(heads, tails):
    axis = tails - heads
    return np.sqrt(np.einsum('ij,ij->i', axis, axis))


LASER_SHAPE_RADIUS = 0.02  # m: laser reach around a custom shape's edges (the shape is where you see the bone)
SHAPE_TOUCH_REACH = 0.0    # m: touch reach past a custom shape's edges (on top of the touch distance)
NUMPY_TOUCH_EDGES = 32     # more candidate edges than this: one numpy pass instead of a plain-Python loop
LASER_MARGIN = 0.02        # m: a laser's candidate edges are kept while the ray drifts less than this
EDGE_GROUP = 8             # edges per group (box) of a custom shape, for the touch grid and the laser pre-test


def euler_xyz_matrix(angles):
    """3 x 3 rotation of a Blender XYZ Euler (X first, then Y, then Z)."""
    (cos_x, cos_y, cos_z), (sin_x, sin_y, sin_z) = np.cos(angles), np.sin(angles)
    rot_x = np.array([[1, 0, 0], [0, cos_x, -sin_x], [0, sin_x, cos_x]])
    rot_y = np.array([[cos_y, 0, sin_y], [0, 1, 0], [-sin_y, 0, cos_y]])
    rot_z = np.array([[cos_z, -sin_z, 0], [sin_z, cos_z, 0], [0, 0, 1]])
    return rot_z @ rot_y @ rot_x


def shape_offset(translation, rotation_euler, scale_xyz, bone_length, use_bone_size):
    """4 x 4 matrix from a bone's pose space to its custom shape's space, by Blender's drawing rule
    (overlay_armature: translate, then rotate (XYZ Euler), then scale by scale_xyz x (bone length or 1))."""
    offset = np.identity(4)
    offset[:3, :3] = euler_xyz_matrix(np.asarray(rotation_euler, dtype=np.float64)) \
        * (np.asarray(scale_xyz, dtype=np.float64) * (bone_length if use_bone_size else 1.0))
    offset[:3, 3] = translation
    return offset


def display_matrices(world, pose_matrices, offsets):
    """World matrices of custom shapes: armature world @ (own or transform-override bone's) pose matrix @ offset.
    pose_matrices and offsets are N x 4 x 4 (row-major, as mathutils prints them)."""
    return np.asarray(world, dtype=np.float64) @ pose_matrices @ offsets


def place_points(matrices, owners, local_points):
    """World positions of K shape points: local_points K x 3, owners K indexes into matrices (N x 4 x 4)."""
    picked = matrices[owners]
    return np.einsum('kij,kj->ki', picked[:, :3, :3], local_points) + picked[:, :3, 3]


def mesh_edges(vertex_count, edges):
    """(M x 2 vertex index pairs) of a shape: its edges, plus each loose vertex as a zero-length edge (point-like
    shapes and stray points still pick)."""
    edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
    used = np.zeros(vertex_count, dtype=bool)
    used[edges.ravel()] = True
    loose = np.flatnonzero(~used)
    return np.vstack((edges, np.column_stack((loose, loose)))) if len(loose) else edges


def point_cross(centre, size):
    """Three short axis lines (6 points) around a point, so a point-like shape shows in a line drawing."""
    centre = [float(value) for value in centre]
    lines = []
    for axis in range(3):
        for sign in (-size, size):
            point = list(centre)
            point[axis] += sign
            lines.append(tuple(point))
    return lines


class BoneEdges:
    """Bones as world-space edges: a plain bone is one edge head-tail (reach grows with its length), a bone with a
    custom shape is its shape's edges (small fixed reach). Edges are grouped by bone (owners sorted). Everything
    that does not depend on the hand is worked out once, so a pick is a handful of numpy calls (each call costs a
    lot when cold, between headset frames). Picks return (bone index, gap or distance along the ray)."""

    def __init__(self, starts, ends, owners, touch_reach, laser_reach):
        self.starts, self.ends = np.asarray(starts, dtype=np.float64), np.asarray(ends, dtype=np.float64)
        self.owners = np.asarray(owners, dtype=np.int64)
        self.touch_reach, self.laser_reach = np.asarray(touch_reach, float), np.asarray(laser_reach, float)
        self.axis = self.ends - self.starts
        axis_sq = np.einsum('ij,ij->i', self.axis, self.axis)
        self.inverse_sq = np.where(axis_sq > 0, 1.0 / np.where(axis_sq > 0, axis_sq, 1.0), 0.0)
        self.lengths = np.sqrt(axis_sq)
        self.axis_sq = axis_sq
        self.laser_reach_sq = self.laser_reach * self.laser_reach
        self.bone_count = int(self.owners[-1]) + 1 if len(self.owners) else 0
        if self.bone_count:
            # groups: runs of at most EDGE_GROUP edges of one bone (mesh edges in order sit near each other), so
            # the grid and the box / sphere tests skip most of a big shape (a ring around a limb) at once
            new_bone = np.r_[True, self.owners[1:] != self.owners[:-1]]
            run_first = np.flatnonzero(new_bone)[np.cumsum(new_bone) - 1]
            firsts = np.flatnonzero((np.arange(len(self.owners)) - run_first) % EDGE_GROUP == 0)
            self.group_owner = self.owners[firsts]
            self.ranges = list(zip(firsts.tolist(), np.r_[firsts[1:], len(self.owners)].tolist()))
            self.box_min = np.minimum.reduceat(np.minimum(self.starts, self.ends), firsts)
            self.box_max = np.maximum.reduceat(np.maximum(self.starts, self.ends), firsts)
            self.centres = (self.box_min + self.box_max) / 2.0
            self.radii = np.sqrt(np.einsum('ij,ij->i', self.box_max - self.centres, self.box_max - self.centres))
            self.max_touch = np.maximum.reduceat(self.touch_reach, firsts)
            laser_radii = self.radii + np.maximum.reduceat(self.laser_reach, firsts)
            self.laser_sphere_sq = laser_radii ** 2
            self.edge_group = np.cumsum(np.isin(np.arange(len(self.owners)), firsts)) - 1
        self._grid_for, self._cells, self._always = None, {}, []
        self._rows, self._rays = None, []   # laser: plain-Python edge rows, cached candidate rays

    @classmethod
    def from_segments(cls, heads, tails):
        """Plain bones only: one edge per bone, the reach grows with the bone's length."""
        lengths = bone_lengths(np.asarray(heads, float), np.asarray(tails, float))
        return cls(heads, tails, np.arange(len(heads)), BONE_REACH_FACTOR * lengths,
                   LASER_BONE_RADIUS + LASER_BONE_FACTOR * lengths)

    def __len__(self):
        return self.bone_count

    def _grid(self, touch_distance):
        """{cell: [group index]}: every cell an edge group's touch reach box covers (built once per touch distance),
        so a touch query looks at the few groups in one cell."""
        if self._grid_for != touch_distance:
            cells, self._always = {}, []
            lows, highs = (self.box_min.tolist(), self.box_max.tolist())
            for index, reach in enumerate((self.max_touch + touch_distance).tolist()):
                low = [math.floor((lows[index][i] - reach) / GRID_CELL) for i in range(3)]
                high = [math.floor((highs[index][i] + reach) / GRID_CELL) for i in range(3)]
                if math.prod(high[i] - low[i] + 1 for i in range(3)) > MAX_BONE_CELLS:
                    self._always.append(index)     # a huge group: checked on every query instead
                    continue
                for cell in itertools.product(*(range(low[i], high[i] + 1) for i in range(3))):
                    cells.setdefault(cell, []).append(index)
            self._cells, self._grid_for = cells, touch_distance
            rows = np.column_stack((self.starts, self.axis, self.inverse_sq, self.touch_reach)).tolist()
            edge_rows = [tuple(row) + (owner,) for row, owner in zip(rows, self.owners.tolist())]
            self._lists = (edge_rows, lows, highs, self.max_touch.tolist())
        return self._cells

    def nearest_touched(self, point, touch_distance):
        """(bone index, gap) of the bone the point touches best, or None. An edge counts within touch_distance + its
        reach; the gap is the distance past that reach (negative = inside)."""
        if not self.bone_count:
            return None
        groups = self._grid(touch_distance).get(tuple(math.floor(point[i] / GRID_CELL) for i in range(3)), [])
        if self._always:
            groups = groups + self._always
        edge_rows, lows, highs, group_reach = self._lists
        edges = []
        for group in groups:   # exact box test first: a cell holds many groups, most boxes miss the point
            reach, low, high = group_reach[group] + touch_distance, lows[group], highs[group]
            if low[0] - reach <= point[0] <= high[0] + reach and low[1] - reach <= point[1] <= high[1] + reach \
                    and low[2] - reach <= point[2] <= high[2] + reach:
                edges.extend(range(*self.ranges[group]))
        if len(edges) > NUMPY_TOUCH_EDGES:
            return self._touched_numpy(point, touch_distance, np.array(edges))
        point_x, point_y, point_z = point[0], point[1], point[2]
        best_owner, best_gap = None, 0.0
        for edge in edges:     # squared distances, one sqrt per better hit: this loop is the touch pick's cost
            start_x, start_y, start_z, axis_x, axis_y, axis_z, inverse_sq, reach, owner = edge_rows[edge]
            offset_x, offset_y, offset_z = point_x - start_x, point_y - start_y, point_z - start_z
            along = (offset_x * axis_x + offset_y * axis_y + offset_z * axis_z) * inverse_sq
            along = 0.0 if along < 0.0 else 1.0 if along > 1.0 else along
            gap_x, gap_y, gap_z = offset_x - axis_x * along, offset_y - axis_y * along, offset_z - axis_z * along
            limit = reach + touch_distance + best_gap        # best_gap <= 0: only a closer hit can pass
            distance_sq = gap_x * gap_x + gap_y * gap_y + gap_z * gap_z
            if limit >= 0.0 and distance_sq <= limit * limit:
                gap = math.sqrt(distance_sq) - reach - touch_distance
                if best_owner is None or gap < best_gap:
                    best_owner, best_gap = owner, gap
        return None if best_owner is None else (best_owner, best_gap)

    def _touched_numpy(self, point, touch_distance, edges):
        point = np.asarray(point, dtype=np.float64)
        offset = point - self.starts[edges]
        axis = self.axis[edges]
        along = np.clip(np.einsum('ij,ij->i', offset, axis) * self.inverse_sq[edges], 0.0, 1.0)
        gap_vector = offset - axis * along[:, None]
        gaps = np.sqrt(np.einsum('ij,ij->i', gap_vector, gap_vector)) - self.touch_reach[edges] - touch_distance
        best = int(gaps.argmin())
        return (int(self.owners[edges[best]]), float(gaps[best])) if gaps[best] <= 0 else None

    def laser(self, origin, direction, max_length):
        """(bone index, distance along the ray) of the first bone the laser passes close to, or None. The edges
        that can be hit are found with numpy once and kept while the ray stays within LASER_MARGIN of that ray (a
        slowly moving hand); the exact test over those few edges is plain Python (numpy calls cost a lot cold,
        between headset frames, plain Python does not)."""
        if not self.bone_count:
            return None
        origin = (float(origin[0]), float(origin[1]), float(origin[2]))
        direction = (float(direction[0]), float(direction[1]), float(direction[2]))
        rows = self._laser_rows()
        (origin_x, origin_y, origin_z), (dir_x, dir_y, dir_z) = origin, direction
        best_owner, best_along = None, max_length
        for edge in self._laser_candidates(origin, direction, max_length):
            start_x, start_y, start_z, axis_x, axis_y, axis_z, axis_sq, reach_sq, owner = rows[edge]
            offset_x, offset_y, offset_z = start_x - origin_x, start_y - origin_y, start_z - origin_z
            offset_dot_dir = offset_x * dir_x + offset_y * dir_y + offset_z * dir_z
            axis_dot_dir = axis_x * dir_x + axis_y * dir_y + axis_z * dir_z
            denominator = axis_sq - axis_dot_dir * axis_dot_dir          # ~0: a point, or an edge along the ray
            along_edge = 0.0
            if denominator > 1e-12:
                along_edge = (axis_dot_dir * offset_dot_dir
                              - (offset_x * axis_x + offset_y * axis_y + offset_z * axis_z)) / denominator
                along_edge = 0.0 if along_edge < 0.0 else 1.0 if along_edge > 1.0 else along_edge
            along = offset_dot_dir + axis_dot_dir * along_edge
            if along < 0.0 or along > best_along:
                continue
            gap_x, gap_y, gap_z = offset_x + axis_x * along_edge, offset_y + axis_y * along_edge, offset_z + axis_z * along_edge
            if gap_x * gap_x + gap_y * gap_y + gap_z * gap_z - along * along <= reach_sq \
                    and (best_owner is None or along < best_along):
                best_owner, best_along = owner, along
        return None if best_owner is None else (best_owner, best_along)

    def _laser_rows(self):
        if self._rows is None:
            columns = np.column_stack((self.starts, self.axis, self.axis_sq, self.laser_reach_sq)).tolist()
            self._rows = [tuple(row) + (owner,) for row, owner in zip(columns, self.owners.tolist())]
        return self._rows

    def _laser_candidates(self, origin, direction, max_length):
        """Edges a ray within LASER_MARGIN of a cached ray can hit (one cached ray per hand: two kept)."""
        for cached in self._rays:
            cached_origin, cached_direction, cached_length, farthest, edges = cached
            drift = math.dist(origin, cached_origin) + farthest * math.dist(direction, cached_direction)
            if drift <= LASER_MARGIN and max_length <= cached_length:
                return edges
        edges, farthest = self._laser_search(origin, direction, max_length)
        self._rays = [(origin, direction, max_length, farthest, edges)] + self._rays[:1]
        return edges

    def _laser_search(self, origin, direction, max_length):
        """numpy pass: (edges within reach + LASER_MARGIN of the ray, farthest distance any edge can lie along it)."""
        direction = np.asarray(direction, dtype=np.float64)
        origin = np.asarray(origin, dtype=np.float64) - direction * LASER_MARGIN   # covers an origin moved forward
        length = max_length + 2 * LASER_MARGIN
        offset = self.centres - origin
        along_centre = offset @ direction
        distance_sq = np.einsum('ij,ij->i', offset, offset)
        farthest = float(min(max_length, (np.sqrt(distance_sq) + self.radii).max()))
        margin_radii = np.sqrt(self.laser_sphere_sq) + LASER_MARGIN
        near = (distance_sq - along_centre * along_centre <= margin_radii * margin_radii) \
            & (along_centre >= -margin_radii) & (along_centre <= length + margin_radii)
        edges = np.flatnonzero(near[self.edge_group])
        if not len(edges):
            return [], farthest
        distance, along = ray_segment_distances(origin, direction, self.starts[edges], self.ends[edges])
        keep = (distance <= self.laser_reach[edges] + LASER_MARGIN) & (along <= length)
        return edges[keep].tolist(), farthest


def nearest_touched_bone(point, heads, tails, touch_distance):
    """(index, gap) of the bone the point touches best, or None. A bone counts within touch_distance +
    BONE_REACH_FACTOR x its length of its axis; the gap is the distance past that reach (negative = inside)."""
    return BoneEdges.from_segments(heads, tails).nearest_touched(point, touch_distance)


def laser_bone(origin, direction, heads, tails, max_length):
    """(index, distance along the ray) of the first bone the laser passes close to, or None."""
    return BoneEdges.from_segments(heads, tails).laser(origin, direction, max_length)


def box_candidates(point, box_min, box_max, margin):
    """Indexes of the boxes (sequences of min / max corners) within `margin` of `point`, nearest first. Plain Python:
    for the few dozen boxes of a scene it beats numpy's per-call overhead."""
    near = []
    margin_sq = margin * margin
    for index, (low, high) in enumerate(zip(box_min, box_max)):
        gap_sq = 0.0
        for axis in range(3):
            value = point[axis]
            outside = low[axis] - value if value < low[axis] else value - high[axis] if value > high[axis] else 0.0
            gap_sq += outside * outside
        if gap_sq <= margin_sq:
            near.append((gap_sq, index))
    return [index for _gap, index in sorted(near)]


def world_box(corners):
    """(min, max) of 8 world-space corners."""
    points = np.asarray(corners, dtype=np.float64)
    return points.min(axis=0), points.max(axis=0)


def laser_point(origin, direction, points, max_length, radius=LASER_POINT_RADIUS):
    """(index, distance along the ray) of the first point within `radius` of the laser, or None."""
    if len(points) == 0:
        return None
    points = np.asarray(points, dtype=np.float64)
    direction = np.asarray(direction, dtype=np.float64)
    along = (points - np.asarray(origin)) @ direction
    on_ray = np.asarray(origin) + np.outer(along, direction)
    gap = np.sqrt(np.einsum('ij,ij->i', points - on_ray, points - on_ray))
    hits = (gap <= radius) & (along >= 0) & (along <= max_length)
    if not hits.any():
        return None
    along = np.where(hits, along, np.inf)
    index = int(np.argmin(along))
    return index, float(along[index])


def moved_enough(last, now, min_move=0.002, min_turn_dot=0.99999):
    """Hover skip test: has a hand pose (location, direction) changed since the last check? ~2 mm or ~0.25 deg."""
    if last is None:
        return True
    (last_location, last_direction), (location, direction) = last, now
    step_sq = sum((location[i] - last_location[i]) ** 2 for i in range(3))   # plain Python: cheaper than numpy here
    return step_sq > min_move ** 2 or sum(last_direction[i] * direction[i] for i in range(3)) < min_turn_dot


def bounding_sphere(points):
    """(centre, radius) around N x 3 points (box centre; not minimal, just cheap)."""
    if len(points) == 0:
        return np.zeros(3), 0.0
    centre = (points.min(axis=0) + points.max(axis=0)) / 2.0
    return centre, float(np.sqrt(((points - centre) ** 2).sum(axis=1).max()))


def ray_near_sphere(origin, direction, centre, radius, max_length):
    """Cheap pre-test (plain Python, no numpy call overhead): can a ray of max_length pass within radius of
    centre?"""
    offset = [centre[i] - origin[i] for i in range(3)]
    along = sum(offset[i] * direction[i] for i in range(3))
    if along < -radius or along > max_length + radius:
        return False
    return sum(value * value for value in offset) - along * along <= radius * radius


def point_near_sphere(point, centre, radius):
    return sum((point[i] - centre[i]) ** 2 for i in range(3)) <= radius * radius
