# SPDX-License-Identifier: GPL-3.0-or-later
"""Deformation metrics: how a posed mesh differs from its rest shape, and weight hygiene. The ONE source for the
stress tests: Scripts/batch_tools/face_stress.py (face poses) and Digit's Assorted Tools' Rig Stress Pose Test
(rig_stress.py). No UI and no posing: callers pose the rig, read positions and ask these functions.

Positions are numpy arrays (V, 3); `Topology` holds the edges and the polygons as flat loop arrays.
    stretch_ratios       posed / rest edge length per edge (stretched > STRETCH_BAD, squashed < SQUASH_BAD)
    face_areas_normals   area and unit normal per polygon (Newell's method, so n-gons work)
    collapsed_faces      faces that shrank below COLLAPSE_RATIO of their rest area
    flipped_faces        faces turned against their neighbours (they agreed at rest)
    spike_scores         a vertex moving apart from its neighbours, in rest edge lengths
    weight_report        deform weights per vertex: too many bones, not summing to 1, tiny, uneven centre, jumps
sync_shared.py copies this file into each add-on / script folder."""
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

try:                                     # inside the add-on package
    from . import rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import rig_names as rn

STRETCH_BAD = 2.5          # an edge longer than this many times its rest length is over-stretched
SQUASH_BAD = 0.35          # shorter than this share of its rest length is squashed
COLLAPSE_RATIO = 0.1       # a face below this share of its rest area has collapsed
SPIKE_BAD = 1.0            # a vertex moved this many rest edge lengths away from where its neighbours went
MAX_INFLUENCES = 4         # more deform-bone weights than this on one vertex is too many (game engines skin with 4)
TINY_WEIGHT = 0.02         # weights below this do almost nothing but cost an influence
UNNORMALIZED = 0.01        # a vertex whose deform weights sum this far from 1
WEIGHT_JUMP = 0.5          # a group's weight changing this much across one edge is a hard seam
CENTRE_X = 1e-4            # a vertex this close to x = 0 sits on the centre line
CENTRE_UNEVEN = 0.01       # ... and should weigh its left and right bones alike, to this much
HIDDEN_FOR_MEASURING = ('SUBSURF', 'MULTIRES', 'NODES')   # measured on the cage: these only smooth or decorate


# ---------------------------------------------------------------------------
# Topology
# ---------------------------------------------------------------------------

def polygon_loops(starts, totals, verts):
    """(face, following) per loop from the polygons' loop starts and sizes: the face each loop belongs to, and the
    next loop of the same face. `verts` = vertex per loop."""
    starts, totals = np.asarray(starts, dtype=np.intp), np.asarray(totals, dtype=np.intp)
    face = np.repeat(np.arange(len(starts)), totals)
    following = np.arange(len(verts)) + 1
    if len(starts):
        following[starts + totals - 1] = starts
    return face, following


@dataclass
class Topology:
    """Edges (E, 2) and polygons as loops: loop_vert (vertex per loop), loop_face, loop_next (next loop in its face)."""
    edges: np.ndarray
    loop_vert: np.ndarray
    loop_face: np.ndarray
    loop_next: np.ndarray
    face_count: int
    first_vert: np.ndarray = field(default=None)   # one vertex of each face (where its problem is reported)

    def __post_init__(self):
        if self.first_vert is None:
            first = np.full(self.face_count, -1, dtype=np.intp)
            first[self.loop_face[::-1]] = self.loop_vert[::-1]   # the lowest loop of each face wins
            self.first_vert = first

    @classmethod
    def from_lists(cls, edges, polys):
        """From edge pairs and polygon vertex tuples (Python lists)."""
        totals = [len(p) for p in polys]
        starts = np.cumsum([0] + totals[:-1]) if polys else np.zeros(0, dtype=np.intp)
        verts = np.array([v for p in polys for v in p], dtype=np.intp)
        face, following = polygon_loops(starts, totals, verts)
        return cls(np.asarray(edges, dtype=np.intp).reshape(-1, 2), verts, face, following, len(polys))

    @classmethod
    def from_mesh(cls, me):
        """From a Blender mesh (original or evaluated)."""
        edges = fetch(me.edges, "vertices", np.intp, (len(me.edges), 2))
        starts = fetch(me.polygons, "loop_start", np.intp, len(me.polygons))
        totals = fetch(me.polygons, "loop_total", np.intp, len(me.polygons))
        verts = fetch(me.loops, "vertex_index", np.intp, len(me.loops))
        face, following = polygon_loops(starts, totals, verts)
        return cls(edges, verts, face, following, len(me.polygons))


def fetch(collection, name, dtype, shape):
    """A Blender collection's attribute as a numpy array (foreach_get)."""
    array = np.empty(shape, dtype=dtype)
    collection.foreach_get(name, array.reshape(-1))
    return array


def mesh_positions(me):
    """Vertex positions (object space) of a mesh as a float64 (V, 3) array."""
    return fetch(me.vertices, "co", np.float32, (len(me.vertices), 3)).astype(np.float64)


@contextmanager
def hidden_modifiers(obj, types=HIDDEN_FOR_MEASURING):
    """Turn the object's viewport modifiers of these types off while inside, then back on exactly as they were."""
    hidden = [m for m in obj.modifiers if m.type in types and m.show_viewport]
    for modifier in hidden:
        modifier.show_viewport = False
    try:
        yield
    finally:
        for modifier in hidden:
            modifier.show_viewport = True


# ---------------------------------------------------------------------------
# Shape metrics
# ---------------------------------------------------------------------------

def edge_lengths(co, edges):
    co = np.asarray(co, dtype=np.float64)
    return np.linalg.norm(co[edges[:, 0]] - co[edges[:, 1]], axis=1) if len(edges) else np.zeros(0)


def stretch_ratios(co, rest_lengths, edges):
    """Posed length / rest length per edge (1 = unchanged; edges of no rest length give 1)."""
    lengths = edge_lengths(co, edges)
    return np.divide(lengths, rest_lengths, out=np.ones_like(lengths), where=rest_lengths > 0)


def summed(index, values, count):
    """Sum of `values` per index 0..count-1 (float, also when empty)."""
    return np.bincount(index, weights=values, minlength=count).astype(np.float64)


def summed_rows(index, rows, count):
    """Sum of the (n, 3) `rows` per index."""
    return np.stack([summed(index, rows[:, k], count) for k in range(3)], axis=1)


def per_face_sum(values, topo):
    """Sum of a (loops, 3) array over each face's loops."""
    return summed_rows(topo.loop_face, values, topo.face_count)


def face_areas_normals(co, topo):
    """(area per face, unit normal per face; zero for a face of no area)."""
    co = np.asarray(co, dtype=np.float64).reshape(-1, 3)
    cross = np.cross(co[topo.loop_vert], co[topo.loop_vert[topo.loop_next]])
    newell = per_face_sum(cross, topo)
    length = np.linalg.norm(newell, axis=1)
    normals = np.divide(newell, length[:, None], out=np.zeros_like(newell), where=length[:, None] > 1e-12)
    return length / 2, normals


def collapsed_faces(areas, rest_areas, ratio=COLLAPSE_RATIO):
    """Bool per face: it had an area at rest and kept less than `ratio` of it."""
    return (rest_areas > 0) & (areas < ratio * np.where(rest_areas > 0, rest_areas, 1))


def neighbour_faces(topo, vertex_count):
    """(face, neighbour) index pairs, each pair once: the faces sharing at least one vertex."""
    order = np.argsort(topo.loop_vert, kind='stable')
    per_vertex = np.bincount(topo.loop_vert, minlength=vertex_count)
    group_start = np.cumsum(per_vertex) - per_vertex
    vertex = topo.loop_vert[order]
    repeats = per_vertex[vertex]
    first = np.repeat(np.arange(len(order)), repeats)
    offset = np.arange(len(first)) - np.repeat(np.cumsum(repeats) - repeats, repeats)
    second = group_start[vertex[first]] + offset
    faces, neighbours = topo.loop_face[order[first]], topo.loop_face[order[second]]
    keep = faces != neighbours
    pairs = np.unique(faces[keep].astype(np.int64) * max(topo.face_count, 1) + neighbours[keep])
    return pairs // max(topo.face_count, 1), pairs % max(topo.face_count, 1)


def neighbour_normals(normals, pairs, face_count):
    """Per face: the summed normals of its neighbour faces (`pairs` from neighbour_faces)."""
    faces, neighbours = pairs
    return summed_rows(faces, normals[neighbours], face_count)


def flipped_faces(normals, rest_normals, topo, vertex_count, pairs=None):
    """Bool per face: it points against its neighbours now, but did not at rest. `pairs`: neighbour_faces, when the
    caller keeps them for many poses."""
    pairs = neighbour_faces(topo, vertex_count) if pairs is None else pairs
    now = np.einsum('ij,ij->i', normals, neighbour_normals(normals, pairs, topo.face_count))
    before = np.einsum('ij,ij->i', rest_normals, neighbour_normals(rest_normals, pairs, topo.face_count))
    has_neighbours = np.bincount(pairs[0], minlength=topo.face_count) > 0
    return has_neighbours & (now < 0) & (before >= 0)


def spike_scores(co, rest, edges):
    """Per vertex: how far it moved apart from the mean move of its edge neighbours, in mean rest edge lengths
    (0 = moves with them). NaN for a vertex with no edges in `edges`."""
    co, rest = np.asarray(co, dtype=np.float64), np.asarray(rest, dtype=np.float64)
    count = len(rest)
    moved = co - rest
    ends = np.concatenate([edges, edges[:, ::-1]]) if len(edges) else np.zeros((0, 2), dtype=np.intp)
    neighbours = np.bincount(ends[:, 0], minlength=count).astype(np.float64)
    neighbour_move = summed_rows(ends[:, 0], moved[ends[:, 1]], count)
    rest_length = summed(ends[:, 0], np.linalg.norm(rest[ends[:, 0]] - rest[ends[:, 1]], axis=1), count)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean_move = neighbour_move / neighbours[:, None]
        mean_length = np.maximum(rest_length / neighbours, 1e-9)
        scores = np.linalg.norm(moved - mean_move, axis=1) / mean_length
    scores[neighbours == 0] = np.nan
    return scores


# ---------------------------------------------------------------------------
# Weight hygiene
# ---------------------------------------------------------------------------

@dataclass
class WeightReport:
    """Vertex indices per weight problem (original mesh). `checked` = the vertices looked at."""
    checked: list = field(default_factory=list)
    too_many: list = field(default_factory=list)        # more than MAX_INFLUENCES deform bones
    unnormalized: list = field(default_factory=list)    # deform weights don't sum to 1
    tiny: list = field(default_factory=list)            # (vertex, group) weights below TINY_WEIGHT
    centre_uneven: list = field(default_factory=list)   # centre-line vertex weighs a left bone and its right twin unlike
    jumps: list = field(default_factory=list)           # (vertex a, vertex b, group, jump) over WEIGHT_JUMP across an edge
    max_jump: float = 0.0


def vertex_weights(obj, deform_names):
    """{vertex index: {group name: weight}} of the deform groups above 0 (vertices with none are left out)."""
    names = {g.index: g.name for g in obj.vertex_groups if g.name in deform_names}
    weights = {}
    for vertex in obj.data.vertices:
        groups = {names[g.group]: g.weight for g in vertex.groups if g.weight > 0 and g.group in names}
        if groups:
            weights[vertex.index] = groups
    return weights


def weight_report(obj, weights, groups=None):
    """Weight hygiene of `weights` (vertex_weights) over the vertices weighted to `groups` (None: all of them)."""
    report = WeightReport()
    in_scope = (lambda name: True) if groups is None else (lambda name: name in groups)
    scoped = {i: w for i, w in weights.items() if any(in_scope(n) for n in w)}
    co_x = {i: obj.data.vertices[i].co.x for i in scoped}
    for i, groups_of in scoped.items():
        report.checked.append(i)
        if len(groups_of) > MAX_INFLUENCES:
            report.too_many.append(i)
        if abs(sum(groups_of.values()) - 1) > UNNORMALIZED:
            report.unnormalized.append(i)
        report.tiny += [(i, n) for n, w in groups_of.items() if w < TINY_WEIGHT]
        if abs(co_x[i]) < CENTRE_X and any(abs(w - groups_of.get(rn.flip(n), 0)) > CENTRE_UNEVEN for n, w in groups_of.items()):
            report.centre_uneven.append(i)
    for edge in obj.data.edges:
        a, b = edge.vertices
        if a not in scoped and b not in scoped:
            continue
        weights_a, weights_b = scoped.get(a, {}), scoped.get(b, {})
        for name in set(weights_a) | set(weights_b):
            if in_scope(name):
                jump = abs(weights_a.get(name, 0) - weights_b.get(name, 0))
                report.max_jump = max(report.max_jump, jump)
                if jump > WEIGHT_JUMP:
                    report.jumps.append((a, b, name, jump))
    return report
