# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode's active tools on the live edit bmesh: each makes the new geometry ONCE (bmesh.ops, no 3D View needed) and
returns an Effect that says where the new vertices go for an amount (SPIKE-C's cheap path: no op per frame;
edit_tool_drag drives it). A tool that can't run raises Refused with the reason. Mirror X is not applied (Blender's own
extrude / bevel don't mirror either)."""
from dataclasses import dataclass

import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import edit_math, edit_select, edit_tool_math as tool_math, edit_tool_settings as options
from .edit_ring import Ring

PROBE = 1e-3              # the first, tiny amount of inset / bevel, as a share of the selection's size
PROBE_EDGE = 0.1          # ... and at most this share of its shortest edge
MAX_VERTS = edit_math.MAX_GRAB_VERTS
TOO_MANY = f"Too much selected for VR (over {MAX_VERTS} points)"


class Refused(Exception):
    """The tool can't run; the text is for the desk's note line."""


@dataclass
class Effect:
    verts: list                     # the BMVerts the hand drives
    origin: np.ndarray              # where they are at amount 0
    dirs: object = None             # per vertex: the way they go per unit of amount; None = the hand moves them freely
    low: float = -tool_math.NO_LIMIT
    high: float = tool_math.NO_LIMIT
    axis: object = None             # local unit vector the hand's travel counts along (None: the first movement sets it)
    gain: float = 1.0               # amount per local metre of travel
    keeps_zero: bool = False        # amount 0 is a result too (a loop cut in the middle)


# ---- shared with edit_actions ---------------------------------------------------------------------------------------

def selected(bm):
    return ([v for v in bm.verts if v.select], [e for e in bm.edges if e.select], [f for f in bm.faces if f.select])


def select_only(bm, verts):
    edit_select.deselect_all(bm)
    for vertex in verts:
        vertex.select_set(True)
    bm.select_flush(True)


# ---- helpers --------------------------------------------------------------------------------------------------------

def _points(verts):
    return np.array([vertex.co[:] for vertex in verts], np.float64).reshape(-1, 3)


def _limited(verts):
    if len(verts) > MAX_VERTS:
        raise Refused(TOO_MANY)


def _probe(anchors, edges):
    size = float(np.linalg.norm(anchors.max(axis=0) - anchors.min(axis=0)))
    shortest = min((edge.calc_length() for edge in edges), default=size)
    return max(min(size * PROBE if size else shortest * PROBE, shortest * PROBE_EDGE), 1e-6)


def _driven(verts, anchors, probe, reason):
    """The Effect of a tool that ran with the tiny amount `probe`: each vertex slides from its anchor (old position) the
    way it moved; stops before an edge collapses."""
    _limited(verts)
    tree = KDTree(len(anchors))
    for row, anchor in enumerate(anchors):
        tree.insert(anchor, row)
    tree.balance()
    now = _points(verts)
    origin = anchors[[tree.find(point)[1] for point in now]] if len(now) else now
    dirs = (now - origin) / probe
    moving = np.linalg.norm(dirs, axis=1) > 1e-3
    if not moving.any():
        raise Refused(reason)
    verts, origin, dirs = [verts[row] for row in np.flatnonzero(moving)], origin[moving], dirs[moving]
    return Effect(verts, origin, dirs, 0.0, _fold_limit(verts, origin, dirs))


def _fold_limit(verts, origin, dirs):
    """collapse_limit over every edge of the driven vertices (a vertex beside them stays where it is)."""
    rows = {vertex: row for row, vertex in enumerate(verts)}
    still, heads, tails = [], [], []
    for edge in {edge for vertex in verts for edge in vertex.link_edges}:
        ends = []
        for vertex in edge.verts:
            if vertex not in rows:
                rows[vertex] = len(verts) + len(still)
                still.append(vertex.co[:])
            ends.append(rows[vertex])
        heads.append(ends[0])
        tails.append(ends[1])
    still = np.array(still, np.float64).reshape(-1, 3)
    return tool_math.collapse_limit(np.concatenate((origin, still)), np.concatenate((dirs, np.zeros_like(still))),
                                    np.array(heads, int), np.array(tails, int))


def _normal_dirs(verts, faces):
    """Per vertex the way "along the normals": the mean of its faces' normals, longer at corners (even thickness)."""
    for face in faces:
        face.normal_update()
    dirs = {vertex: [] for vertex in verts}
    for face in faces:
        for vertex in face.verts:
            dirs[vertex].append(face.normal)
    out = []
    for normals in dirs.values():
        middle = sum(normals, Vector())
        middle = middle.normalized() if middle.length > 1e-6 else Vector()
        share = sum(middle.dot(normal) for normal in normals) / len(normals) if normals else 0.0
        out.append((middle / max(share, 0.2))[:])
    return np.array(out, np.float64).reshape(-1, 3)


def _mean_axis(faces):
    middle = sum((face.normal for face in faces), Vector())
    return np.array(middle.normalized()) if middle.length > 1e-3 * len(faces) else None


# ---- the tools: (bmesh, {setting: value}, hovered edge index or None) -> Effect ---------------------------------------

def _extrude(bm, values, _edge):
    verts, edges, faces = selected(bm)
    mode = values["edit_extrude_mode"]
    if not verts:
        raise Refused("Nothing selected")
    _limited(verts)
    if mode == 'FACES':
        if not faces:
            raise Refused("Select faces (Extrude: each face)")
        made = bmesh.ops.extrude_discrete_faces(bm, faces=faces)["faces"]
        fresh = [vertex for face in made for vertex in face.verts]
        _limited(fresh)
    elif edges or faces:
        new = bmesh.ops.extrude_face_region(bm, geom=verts + edges + faces)["geom"]     # (the old faces go with it)
        fresh = [item for item in new if isinstance(item, bmesh.types.BMVert)]
        made = [item for item in new if isinstance(item, bmesh.types.BMFace)]
    else:
        fresh, made = bmesh.ops.extrude_vert_indiv(bm, verts=verts)["verts"], []
    select_only(bm, fresh)
    effect = Effect(fresh, _points(fresh))
    if mode != 'FREE' and made:             # (points and edges have no normal to follow: free)
        effect.dirs, effect.axis = _normal_dirs(fresh, made), _mean_axis(made)
    return effect


def _inset(bm, values, _edge):
    faces = selected(bm)[2]
    if not faces:
        raise Refused("Select faces")
    verts = list({vertex: None for face in faces for vertex in face.verts})
    _limited(verts)
    anchors = _points(verts)
    probe = _probe(anchors, {edge for face in faces for edge in face.edges})
    if values["edit_inset_mode"] == 'FACES':
        bmesh.ops.inset_individual(bm, faces=faces, thickness=probe, depth=0.0, use_even_offset=True)
    else:
        bmesh.ops.inset_region(bm, faces=faces, thickness=probe, depth=0.0, use_even_offset=True, use_boundary=True)
    # the selected faces become the INNER faces: their vertices slid inward
    inner = list({vertex: None for face in faces if face.is_valid for vertex in face.verts})
    effect = _driven(inner, anchors, probe, "Nothing to inset")
    edit_select.deselect_all(bm)
    for face in faces:
        face.select_set(True)
    return effect


def _bevel(bm, values, _edge):
    verts, edges, _faces = selected(bm)
    affect = values["edit_bevel_affect"]
    if not (edges if affect == 'EDGES' else verts):
        raise Refused("Select edges" if affect == 'EDGES' else "Select vertices")
    _limited(verts)
    anchors = _points(verts)
    probe = _probe(anchors, {edge for vertex in verts for edge in vertex.link_edges})
    made = bmesh.ops.bevel(bm, geom=verts + edges if affect == 'EDGES' else verts, offset=probe, affect=affect,
                           segments=int(values["edit_bevel_segments"]), profile=float(values["edit_bevel_profile"]),
                           material=-1, loop_slide=True, clamp_overlap=False)
    effect = _driven([vertex for vertex in made["verts"] if vertex.is_valid], anchors, probe, "Nothing to bevel")
    select_only(bm, effect.verts)
    return effect


def _loop_cut(bm, values, edge):
    if edge is None or edge >= len(bm.edges):
        raise Refused("Point at an edge")
    bm.edges.ensure_lookup_table()
    cuts = int(values["edit_loop_cuts"])
    ring = Ring(bm.edges[edge])
    reason = ring.refusal(cuts, MAX_VERTS)
    if reason:
        raise Refused(reason)
    heads, tails = ring.points()
    rows = [_split(bm, item, ends, cuts) for item, ends in zip(ring.edges, ring.ends)]
    loop = []
    for first, second in ring.pairs:
        for one, two in zip(rows[first], rows[second]):
            face = next((face for face in one.link_faces if face in set(two.link_faces)), None)
            if face is not None and bmesh.utils.face_split(face, one, two)[0] is not None:
                loop.append(bm.edges.get((one, two)))
    edit_select.deselect_all(bm)
    for item in loop:
        item.select_set(True)
    aimed = tails[0] - heads[0]
    length = max(float(np.linalg.norm(aimed)), 1e-12)
    dirs, limit = tool_math.slide(heads, tails, cuts, values["edit_loop_even"], length)
    return Effect([vertex for row in rows for vertex in row], tool_math.cut_points(heads, tails, cuts).reshape(-1, 3), dirs,
                  -limit, limit, aimed / length, 1.0 / length, keeps_zero=True)


def _split(bm, edge, ends, cuts):
    """Split one ring edge into cuts + 1 equal parts; the new vertices from its head to its tail."""
    vertex, tail = ends
    made = []
    for left in range(cuts, 0, -1):
        _new, middle = bmesh.utils.edge_split(edge, vertex, 1.0 / (left + 1))
        made.append(middle)
        vertex, edge = middle, bm.edges.get((middle, tail))
    return made


TOOLS = {options.EXTRUDE: _extrude, options.INSET: _inset, options.LOOP_CUT: _loop_cut, options.BEVEL: _bevel}


def run(tool, bm, values, edge=None):
    """Make the new geometry of `tool`. Raises Refused (the mesh may already be changed: restore the snapshot)."""
    effect = TOOLS[tool](bm, values, edge)
    _limited(effect.verts)
    return effect
