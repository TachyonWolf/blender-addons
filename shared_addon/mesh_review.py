# SPDX-License-Identifier: GPL-3.0-or-later
"""Mesh review: read-only mesh checks (numpy on the ORIGINAL mesh data, what Edit Mode shows) and the Mirror seam rule.
No UI and nothing runs by itself: scene_checks registers one review Check per function here, and the Oops Debugger's
Checks card calls them on its scan.

Each check function takes a mesh object (and the scene Scope for shared work) and returns a Hit or None:
    Hit(detail, verts, edges, faces)   # index arrays of the problem elements; detail = short text like "12 edges"
`show_hit()` selects a Hit in Edit Mode. The Mirror seam rule (`mirror_planes`, `seam_edge_mask`) is shared with the
Select Non Manifold (Skip Mirror Seam) operator, so the operator and the Non-Manifold check agree."""
from dataclasses import dataclass, field

import bmesh
import bpy
import numpy as np
from mathutils import kdtree

from . import weight_cleanup
from .deform_metrics import MAX_INFLUENCES, fetch, polygon_loops

SEAM_TOLERANCE = 1e-4        # Mirror modifier with Merge off: how close to the plane counts as on it
DOUBLE_DISTANCE = 1e-4       # metres: vertices closer than this are doubled
SEAM_NEAR_FRACTION = 0.03    # a boundary vertex this close to the plane (as a share of the half-width) was meant to sit on it
SEAM_NEAR_TOLERANCES = 5     # ...or this many times the merge distance, whichever is larger
MIN_FACE_AREA = 1e-8         # square metres
MIN_EDGE_LENGTH = 1e-6       # metres
UV_TOUCH = 1e-6              # UV triangles that overlap by less than this only touch
MAX_UV_PAIRS = 2_000_000     # candidate UV triangle pairs tested at most (stacked-up UVs stop here, reported as "at least")
MAX_UV_WORK = 20_000_000     # triangle pairs sharing a grid cell looked at most (many triangles in one cell stop here, "at least")
PAIR_CHUNK = 200_000         # pairs handled at once (bounds the memory; small enough that known overlaps are skipped soon)
GRID_CELLS = 1024            # the UV grid has at most this many cells a side
MAX_CELL_ENTRIES = 1_000_000 # the UV triangles cover at most this many grid cells in all (bounds the pairing's memory)
MIN_UV_AREA = 1e-12          # UV triangles smaller than this have no inside to overlap with
EMPTY = np.zeros(0, dtype=np.intp)


@dataclass
class Hit:
    detail: str
    verts: np.ndarray = field(default_factory=lambda: EMPTY)
    edges: np.ndarray = field(default_factory=lambda: EMPTY)
    faces: np.ndarray = field(default_factory=lambda: EMPTY)

    @property
    def count(self):
        return len(self.verts) + len(self.edges) + len(self.faces)


# ---------------------------------------------------------------------------
# Mesh arrays
# ---------------------------------------------------------------------------

def mesh_arrays(me):
    """Original mesh data as numpy arrays: co (V,3), edge_verts (E,2), edge_faces (E,) faces per edge."""
    co = fetch(me.vertices, "co", np.float32, (len(me.vertices), 3))
    edge_verts = fetch(me.edges, "vertices", np.intp, (len(me.edges), 2))
    loop_edge = fetch(me.loops, "edge_index", np.intp, len(me.loops))
    edge_faces = np.bincount(loop_edge, minlength=len(me.edges))
    return co, edge_verts, edge_faces


def indices(mask):
    return np.flatnonzero(mask)


# ---------------------------------------------------------------------------
# Mirror seam rule (shared with mesh.select_non_manifold_smart)
# ---------------------------------------------------------------------------

def mirror_planes(obj):
    """[(matrix obj-local -> plane space, axis index, tolerance)] for every enabled Mirror modifier axis."""
    planes = []
    for mod in obj.modifiers:
        if mod.type != 'MIRROR' or not mod.show_viewport:
            continue
        to_plane = obj.matrix_world.copy()
        if mod.mirror_object:
            to_plane = mod.mirror_object.matrix_world.inverted() @ to_plane
        else:
            to_plane.identity()
        tolerance = mod.merge_threshold if mod.use_mirror_merge else SEAM_TOLERANCE
        planes += [(to_plane, axis, tolerance) for axis in range(3) if mod.use_axis[axis]]
    return planes


def seam_edge_mask(planes, co, edge_verts, edge_faces):
    """Bool per edge: a BOUNDARY edge (one face) whose both verts lie on the same plane of an enabled Mirror modifier."""
    seam = np.zeros(len(edge_verts), dtype=bool)
    if not planes or not len(edge_verts):
        return seam
    boundary = edge_faces == 1
    for matrix, axis, tolerance in planes:
        m = np.array(matrix)
        distance = co @ m[axis, :3].astype(np.float32) + np.float32(m[axis, 3])
        on_plane = np.abs(distance) <= tolerance
        seam |= boundary & on_plane[edge_verts[:, 0]] & on_plane[edge_verts[:, 1]]
    return seam


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

@dataclass
class LoopData:
    face: np.ndarray        # face index per loop
    vert: np.ndarray        # vertex per loop
    following: np.ndarray   # the next loop of the same face, per loop
    edge: np.ndarray        # edge per loop

    @property
    def vert_next(self):
        return self.vert[self.following]


def loop_data(me):
    start = fetch(me.polygons, "loop_start", np.intp, len(me.polygons))
    total = fetch(me.polygons, "loop_total", np.intp, len(me.polygons))
    vert = fetch(me.loops, "vertex_index", np.intp, len(me.loops))
    face, following = polygon_loops(start, total, vert)
    return LoopData(face, vert, following, fetch(me.loops, "edge_index", np.intp, len(vert)))


def non_manifold(ob, scope=None):
    """Edges not shared by exactly two faces (wire, boundary, 3+ faces) or between faces that point opposite ways,
    minus the open centre seam of a Mirror modifier. The Show button selects with the operator, which also finds
    vertices joining separate face regions."""
    me = ob.data
    co, edge_verts, edge_faces = mesh_arrays(me)
    bad = edge_faces != 2
    if len(me.polygons):
        loops = loop_data(me)
        forward = (loops.vert == edge_verts[loops.edge, 0]).astype(np.intp)
        same_way = np.bincount(loops.edge, weights=forward, minlength=len(edge_verts))
        bad |= (edge_faces == 2) & (same_way != 1)
    bad &= ~seam_edge_mask(mirror_planes(ob), co, edge_verts, edge_faces)
    edges = indices(bad)
    if not len(edges):
        return None
    return Hit(f"{len(edges)} edges, {len(np.unique(edge_verts[edges]))} verts", edges=edges)


def x_mirror_planes(obj):
    """Planes of enabled Mirror modifiers that mirror on X, as `mirror_planes` returns them."""
    return [plane for plane in mirror_planes(obj) if plane[1] == 0]


def mirror_seam_gaps(ob, scope=None):
    """Where an enabled X Mirror modifier will not close its seam, in three kinds:
    - gap: an open-boundary vertex NEAR the plane but farther from it than the merge distance (merge off: SEAM_TOLERANCE),
      so the two halves leave a crack. "Near" = within max(SEAM_NEAR_FRACTION of the half-width, SEAM_NEAR_TOLERANCES x the
      merge distance): close enough that it was meant to sit on the plane, far enough from the rest that it is no real border.
    - crossing: a vertex on the far side of the plane by more than the merge distance, so the halves overlap.
      The real side is the side the mesh reaches further on.
    - flat: a face whose vertices all lie on the plane; the mirror doubles it inside the mesh.
    The first plane of the mesh with a problem is reported; the clipping option is not considered."""
    me = ob.data
    co, edge_verts, edge_faces = mesh_arrays(me)
    if not len(co):
        return None
    boundary_verts = np.zeros(len(co), dtype=bool)
    boundary_verts[edge_verts[edge_faces == 1].reshape(-1)] = True
    for matrix, _axis, tolerance in x_mirror_planes(ob):
        m = np.array(matrix)
        distance = co @ m[0, :3].astype(np.float32) + np.float32(m[0, 3])
        real_sign = 1.0 if distance.max() >= -distance.min() else -1.0
        side = distance * real_sign                       # positive on the real half
        near = max(SEAM_NEAR_FRACTION * side.max(), SEAM_NEAR_TOLERANCES * tolerance)
        gap = boundary_verts & (side > tolerance) & (side <= near)
        crossing = side < -tolerance
        flat_faces = np.empty(0, dtype=np.intp)
        if len(me.polygons):
            loops = loop_data(me)
            off_plane = np.bincount(loops.face, weights=(np.abs(distance[loops.vert]) > tolerance), minlength=len(me.polygons))
            flat_faces = indices(off_plane == 0)
        verts = indices(gap | crossing)
        if len(verts) or len(flat_faces):
            return Hit(f"{gap.sum()} gap verts, {crossing.sum()} crossing verts, {len(flat_faces)} flat faces",
                       verts=verts, faces=flat_faces)
    return None


def influence_counts(ob, scope):
    """Per vertex: how many deform-bone groups hold a weight above 0 (None when there is no Armature to deform by).
    One pass over the vertices, shared by Unweighted Verts and Too Many Influences."""
    def compute():
        rig = next((m.object for m in ob.modifiers if m.type == 'ARMATURE' and m.object), None)
        if rig is None:
            return None
        deform = {ob.vertex_groups[n].index for n in weight_cleanup.deform_group_names(ob)}
        return np.array([sum(1 for g in v.groups if g.weight > 0 and g.group in deform) for v in ob.data.vertices],
                        dtype=np.intp)
    return scope.memo(("influences", ob.name), compute) if scope else compute()


def unweighted(ob, scope=None):
    counts = influence_counts(ob, scope)
    verts = indices(counts == 0) if counts is not None else EMPTY
    return Hit(f"{len(verts)} verts", verts=verts) if len(verts) else None


def too_many_influences(ob, scope=None):
    counts = influence_counts(ob, scope)
    verts = indices(counts > MAX_INFLUENCES) if counts is not None else EMPTY
    return Hit(f"{len(verts)} verts over {MAX_INFLUENCES}, most {counts[verts].max()}", verts=verts) if len(verts) else None


def doubled(ob, scope=None):
    co = fetch(ob.data.vertices, "co", np.float32, (len(ob.data.vertices), 3))
    tree = kdtree.KDTree(len(co))
    for i, p in enumerate(co.tolist()):
        tree.insert(p, i)
    tree.balance()
    twin = np.zeros(len(co), dtype=bool)
    pairs = 0
    for i, p in enumerate(co.tolist()):
        near = tree.find_range(p, DOUBLE_DISTANCE)
        if len(near) > 1:
            twin[i] = True
            pairs += len(near) - 1
    verts = indices(twin)
    return Hit(f"{len(verts)} verts, {pairs // 2} pairs", verts=verts) if len(verts) else None


def loose(ob, scope=None):
    me = ob.data
    _co, edge_verts, edge_faces = mesh_arrays(me)
    used = np.bincount(edge_verts.reshape(-1), minlength=len(me.vertices))
    verts, edges = indices(used == 0), indices(edge_faces == 0)
    if not len(verts) and not len(edges):
        return None
    return Hit(f"{len(verts)} verts, {len(edges)} edges", verts=verts, edges=edges)


def degenerate(ob, scope=None):
    me = ob.data
    co, edge_verts, _faces = mesh_arrays(me)
    length = np.linalg.norm(co[edge_verts[:, 0]] - co[edge_verts[:, 1]], axis=1) if len(edge_verts) else np.zeros(0)
    edges = indices(length < MIN_EDGE_LENGTH)
    faces = indices(fetch(me.polygons, "area", np.float32, len(me.polygons)) < MIN_FACE_AREA)
    if not len(edges) and not len(faces):
        return None
    return Hit(f"{len(faces)} faces, {len(edges)} edges", edges=edges, faces=faces)


# ---------------------------------------------------------------------------
# UVs (the active UV map)
# ---------------------------------------------------------------------------

def signed_areas(uv, uv_next, face, count):
    """Signed UV area per face (shoelace): positive counter-clockwise."""
    cross = uv[:, 0] * uv_next[:, 1] - uv_next[:, 0] * uv[:, 1]
    return np.bincount(face, weights=cross, minlength=count) / 2


def joined_faces(loops, uv, edge_faces):
    """(face a, face b) pairs sharing an edge whose two UV ends coincide: they sit in the same island."""
    uv_next = uv[loops.following]
    order = np.argsort(loops.edge, kind="stable")
    starts = np.cumsum(edge_faces) - edge_faces
    two = np.flatnonzero(edge_faces == 2)
    a, b = order[starts[two]], order[starts[two] + 1]
    same_dir = loops.vert[a] == loops.vert[b]
    uv_a_start, uv_a_end = uv[a], uv_next[a]
    uv_b_start = np.where(same_dir[:, None], uv[b], uv_next[b])
    uv_b_end = np.where(same_dir[:, None], uv_next[b], uv[b])
    close = (np.abs(uv_a_start - uv_b_start).max(axis=1) < 1e-5) & (np.abs(uv_a_end - uv_b_end).max(axis=1) < 1e-5)
    return loops.face[a[close]], loops.face[b[close]]


def island_labels(count, a, b):
    """Island number (lowest face index in it) per face, joined along the pairs a-b."""
    label = np.arange(count)
    while len(a):
        low = np.minimum(label[a], label[b])
        new = label.copy()
        np.minimum.at(new, a, low)
        np.minimum.at(new, b, low)
        new = new[new]
        if np.array_equal(new, label):
            break
        label = new
    return label


def flipped_faces(area, label):
    """Faces whose UV winding differs from the majority of their island (ties: none flagged)."""
    sign = np.sign(np.where(np.abs(area) > 1e-12, area, 0))
    balance = np.bincount(label, weights=sign, minlength=len(area))
    majority = np.sign(balance)[label]
    return indices((sign != 0) & (majority != 0) & (sign != majority))


def grid_cells(low, high):
    """(first cell, last cell) per box on a square grid: the cell is about a typical box (the median), but never so
    small that the grid has more than GRID_CELLS cells a side or the boxes cover more than MAX_CELL_ENTRIES cells in
    all (the cell doubles until they fit), so no UV layout can make it allocate much."""
    origin = low.min(axis=0)
    extent = float((high.max(axis=0) - origin).max())
    cell = max(float(np.median((high - low).max(axis=1))), extent / GRID_CELLS, UV_TOUCH)
    while True:
        first = np.floor((low - origin) / cell).astype(np.int64)
        last = np.floor((high - origin) / cell).astype(np.int64)
        spans = (last - first + 1).prod(axis=1)
        if spans.sum() <= max(MAX_CELL_ENTRIES, len(low)):
            return first, last, spans
        cell *= 2


def candidate_pairs(low, high):
    """Box pairs (UV triangles) whose boxes overlap, found through a grid of cells (each pair once, from the cell
    holding the corner of the boxes' overlap): yields (i, j, stopped early) in chunks of about PAIR_CHUNK. Stops
    early after MAX_UV_PAIRS overlapping pairs or MAX_UV_WORK pairs looked at (stacked-up UVs), so its time and
    memory stay bounded whatever the UVs are."""
    if not len(low):
        return
    first, last, spans = grid_cells(low, high)
    width = last[:, 0] - first[:, 0] + 1
    tri = np.repeat(np.arange(len(low)), spans)
    step = np.arange(len(tri)) - np.repeat(np.cumsum(spans) - spans, spans)
    cx, cy = first[tri, 0] + step % width[tri], first[tri, 1] + step // width[tri]
    key = cx * (int(last[:, 1].max()) + 2) + cy
    order = np.argsort(key, kind="stable")
    key, tri, cx, cy = key[order], tri[order], cx[order], cy[order]
    start = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])        # each cell's entries sit together
    end = np.r_[start[1:], len(key)]
    after = np.repeat(end, end - start) - np.arange(len(key)) - 1   # entries after this one in its cell
    ends = np.cumsum(after)
    total = work = 0
    begin = 0
    while begin < len(key):
        stop = max(int(np.searchsorted(ends, ends[begin] - after[begin] + PAIR_CHUNK, side="right")), begin + 1)
        counts = after[begin:stop]
        a = np.repeat(np.arange(begin, stop), counts)
        b = a + 1 + np.arange(len(a)) - np.repeat(np.cumsum(counts) - counts, counts)
        begin = stop
        if not len(a):
            continue
        i, j = tri[a], tri[b]
        home = (cx[a] == np.maximum(first[i, 0], first[j, 0])) & (cy[a] == np.maximum(first[i, 1], first[j, 1]))
        near = home & (low[i] < high[j] - UV_TOUCH).all(axis=1) & (low[j] < high[i] - UV_TOUCH).all(axis=1)
        total += int(near.sum())
        work += len(a)
        stopped = total > MAX_UV_PAIRS or work > MAX_UV_WORK
        yield i[near], j[near], stopped
        if stopped:
            return


def triangles_overlap(a, b):
    """Bool per pair of UV triangles (n,3,2): their interiors overlap by more than UV_TOUCH (separating axis test)."""
    apart = np.zeros(len(a), dtype=bool)
    for tri in (a, b):
        edge = tri[:, [1, 2, 0]] - tri
        normal = np.stack([-edge[..., 1], edge[..., 0]], axis=-1)
        length = np.linalg.norm(normal, axis=-1, keepdims=True)
        normal = np.divide(normal, length, out=np.zeros_like(normal), where=length > 0)
        pa = np.einsum('nkc,nvc->nkv', normal, a)
        pb = np.einsum('nkc,nvc->nkv', normal, b)
        apart |= ((pa.max(axis=2) - pb.min(axis=2) < UV_TOUCH) | (pb.max(axis=2) - pa.min(axis=2) < UV_TOUCH)).any(axis=1)
    return ~apart


def real_uv_triangles(me, uv):
    """(UV triangles (n,3,2) float64, face per triangle) of the mesh, without collapsed ones (no inside to overlap)
    and those with NaN or infinite UVs."""
    corners = fetch(me.loop_triangles, "loops", np.intp, (len(me.loop_triangles), 3))
    tri_face = fetch(me.loop_triangles, "polygon_index", np.intp, len(corners))
    tri_uv = uv[corners].astype(np.float64)
    a, b, c = tri_uv[:, 0], tri_uv[:, 1], tri_uv[:, 2]
    with np.errstate(invalid="ignore", over="ignore"):
        area = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])) / 2
    real = np.flatnonzero(np.isfinite(tri_uv).all(axis=(1, 2)) & (area > MIN_UV_AREA))
    return tri_uv[real], tri_face[real]


def stacked_groups(tri_uv, tri_face):
    """Identical UV triangles (stacked copies, e.g. duplicated hair cards) grouped: (group per triangle, first
    triangle of each group, per group: whether it holds triangles of different faces, which then overlap)."""
    points = np.sort(tri_uv[..., 0] + 1j * tri_uv[..., 1], axis=1)   # corner order doesn't matter
    rows = np.concatenate([points.real, points.imag], axis=1)
    _rows, first, group = np.unique(rows, axis=0, return_index=True, return_inverse=True)
    group = group.reshape(-1)
    low_face = np.full(len(first), np.iinfo(np.intp).max, dtype=np.intp)
    high_face = np.full(len(first), -1, dtype=np.intp)
    np.minimum.at(low_face, group, tri_face)
    np.maximum.at(high_face, group, tri_face)
    return group, first, low_face != high_face


def overlapping_faces(me, uv, face_count):
    """(faces whose UV triangles overlap another face's, whether the search stopped early). Stacked copies are
    found at once and searched as one triangle; the search ends when every triangle is known to overlap."""
    tri_uv, tri_face = real_uv_triangles(me, uv)
    hit = np.zeros(face_count, dtype=bool)
    if not len(tri_uv):
        return indices(hit), False
    group, first, group_hit = stacked_groups(tri_uv, tri_face)
    rep_uv, rep_face = tri_uv[first], tri_face[first]
    truncated = False
    for i, j, truncated in candidate_pairs(rep_uv.min(axis=1), rep_uv.max(axis=1)):
        keep = (rep_face[i] != rep_face[j]) & ~(group_hit[i] & group_hit[j])   # known overlaps tell nothing new
        i, j = i[keep], j[keep]
        over = triangles_overlap(rep_uv[i], rep_uv[j])
        group_hit[i[over]] = True
        group_hit[j[over]] = True
        if group_hit.all():
            truncated = False
            break
    hit[tri_face[group_hit[group]]] = True
    return indices(hit), truncated


def uv_problems(ob, scope=None):
    """Faces flipped against their UV island, and faces overlapping another face in UV space."""
    me = ob.data
    uv = uv_loops(me)
    if uv is None or not len(me.polygons):
        return None
    loops = loop_data(me)
    _co, _ev, edge_faces = mesh_arrays(me)
    area = signed_areas(uv, uv[loops.following], loops.face, len(me.polygons))
    flipped = flipped_faces(area, island_labels(len(area), *joined_faces(loops, uv, edge_faces)))
    overlap, truncated = overlapping_faces(me, uv, len(area))
    faces = np.union1d(flipped, overlap)
    if not len(faces):
        return None
    return Hit(f"{len(flipped)} flipped, {len(overlap)}{'+' if truncated else ''} overlapping faces", faces=faces)


def uv_loops(me):
    layer = me.uv_layers.active
    return fetch(layer.uv, "vector", np.float32, (len(me.loops), 2)) if layer else None


# ---------------------------------------------------------------------------
# Show
# ---------------------------------------------------------------------------

def select_mode(hit):
    """Vertex mode when the hit names vertices, else edge mode when it names edges, else face mode."""
    return 'VERT' if len(hit.verts) else 'EDGE' if len(hit.edges) else 'FACE'


def show_hit(context, ob, hit):
    """Enter Edit Mode on `ob` (already the active object) and select exactly the hit's elements."""
    if context.mode != 'EDIT_MESH':
        bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(ob.data)
    bm.select_mode = {select_mode(hit)}
    for elements, wanted in ((bm.verts, hit.verts), (bm.edges, hit.edges), (bm.faces, hit.faces)):
        elements.ensure_lookup_table()
        for index in wanted.tolist():
            elements[index].select_set(True)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
