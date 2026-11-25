# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode in VR: the cached view of the mesh being edited (cage data and pick points), kept valid by ONE check per
tick. Holds only numpy arrays and names: bmesh objects and their verts die on undo, mode switches, shape key
switches and desktop edits, so they are fetched fresh for each action (edit_grab keeps them for ONE grab and
checks them every frame). Everything drops on: undo / redo (generation), file load, session end, leaving Edit mode,
a shape key switch, a topology change, a desktop edit (depsgraph) and any other change of the validity key."""
import time

import bmesh
import bpy
import numpy as np

from . import desk_qol_math, edit_math
from .picking import is_linked
from .runtime import RUNTIME

EDIT = 'EDIT_MESH'
IGNORE_SECONDS = 0.03       # the depsgraph update our own update_from_editmode causes arrives within this (+ the size term)
IGNORE_PER_FACE = 4e-6      # s: evaluating a big mesh takes longer (0.5 s at 250k faces)


def select_kind(context):
    return edit_math.select_kind(tuple(context.tool_settings.mesh_select_mode))


class EditState:
    def __init__(self):
        self.clear()

    def clear(self):
        self.object_name = ""
        self.key = None
        self.reason = ""                  # why Edit mode in VR refuses this mesh ("" = it works)
        self.version = 0                  # bumped on every change of selection / topology / hide (the cage rebuilds its indices)
        self.coords_version = 0           # bumped when coordinates moved (a drag): the cage refills its position buffer only
        self.stale = False                # the depsgraph saw an edit we did not make
        self.ignore_until = 0.0           # depsgraph updates before this time are ours (update_from_editmode tags one)
        self.why = ""                     # what made the last rebuild (debugging, ox)
        self.grabbing = False
        self.coords = np.zeros((0, 3), np.float32)      # local
        self.edges = np.zeros((0, 2), np.int32)
        self.selected = np.zeros(0, bool)
        self.matrix = np.eye(4)           # object -> world
        self.world = np.zeros((0, 3))     # coords in world space, refreshed with coords
        self.visible = np.zeros(0, bool)  # not hidden: hidden vertices are not drawn, picked or moved
        self.pickable = np.zeros(0, int)  # indices of the visible vertices
        self.world_stale = False          # coords moved since `world` was worked out (a grab moves only a few rows)
        self.pick_cache = None            # (world_version, points of the visible vertices)
        self.kind = edit_math.VERT        # what picking and selecting work on: Blender's own select mode
        self.all_edges = np.zeros((0, 2), np.int32)   # every edge's two vertices (bmesh edge index = row)
        self.edge_ids = np.zeros(0, int)  # bmesh edge index of each drawn (visible) edge
        self.edge_selected = np.zeros(0, bool)
        self.geometry_version = 0         # bumped when coords / hide / topology change (not on a selection change)
        self.topology = (0, 0, 0)         # (edges, faces, loops): a dissolve keeps every vertex and position, only this tells
        self.topology_version = 0         # bumped when topology / hide change (not on a drag): the triangulation cache follows it
        self.topology_cache = None        # lazy, face_topology()
        self.topology_cache_version = -1
        self.face_selected = np.zeros(0, bool)
        self.faces = None                 # lazy, built by the first face pick: (BVHTree, triangle -> bmesh face index)
        self.faces_version = -1

    @property
    def ready(self):
        return bool(self.object_name) and not self.reason


STATE = EditState()


def clear():
    """Drop every cache (undo / redo, load, teardown, mode change). Leaving Edit mode also refreshes the object caches."""
    if STATE.object_name:
        RUNTIME.cache.all_dirty = True
    version = STATE.version
    STATE.clear()
    STATE.version = version + 1


def facts(context, ob, bm):
    me = ob.data
    key = ob.active_shape_key
    matrix = np.array(ob.matrix_world)
    return {"linked": is_linked(ob) or bool(me.library),
            "objects_in_mode": len(context.objects_in_mode),
            "key_locked": bool(me.shape_keys and key is not None and key.lock_shape),
            "faces": len(bm.faces),
            "scale_zero": abs(np.linalg.det(matrix[:3, :3])) < 1e-12}


def validity_key(ob, bm):
    me = ob.data
    key = ob.active_shape_key
    return (ob.name_full, RUNTIME.generation, ob.active_shape_key_index, len(bm.verts), len(bm.edges), len(bm.faces),
            me.total_vert_sel, me.total_edge_sel, me.total_face_sel, me.shape_keys is not None, bool(key and key.lock_shape),
            tuple(bpy.context.tool_settings.mesh_select_mode))


def sync(context):
    """Once per tick. Nothing but a mode string compare outside Edit mode; in Edit mode one cheap key compare."""
    if context.mode != EDIT:
        if STATE.object_name:
            clear()
        return
    ob = context.edit_object
    if ob is None or ob.type != 'MESH':
        clear()
        return
    try:
        bm = bmesh.from_edit_mesh(ob.data)
        key = validity_key(ob, bm)
        if key != STATE.key or STATE.stale:
            STATE.why = "key" if key != STATE.key else "stale"
            _rebuild(context, ob, bm, key)
        STATE.matrix = np.array(ob.matrix_world)
    except (ReferenceError, RuntimeError, ValueError):
        clear()


def _rebuild(context, ob, bm, key):
    me = ob.data
    STATE.stale = False
    STATE.object_name, STATE.key = ob.name_full, key
    STATE.matrix = np.array(ob.matrix_world)
    STATE.reason = edit_math.refusal(facts(context, ob, bm)) or ""
    STATE.version += 1
    if not STATE.reason and len(bm.faces) > edit_math.HOVER_MAX_FACES:
        desk_qol_math.NOTICE.show("Big mesh: no edge / face hover", time.perf_counter())
    STATE.ignore_until = time.perf_counter() + IGNORE_SECONDS + IGNORE_PER_FACE * len(bm.faces)      # update_from_editmode tags a depsgraph update: not a desktop edit
    if STATE.reason:
        return
    ob.update_from_editmode()
    count = len(me.vertices)
    if me.shape_keys is not None:          # me.vertices holds the BASIS: the edit bmesh holds the ACTIVE key (audit A1)
        coords = np.array([vertex.co[:] for vertex in bm.verts], np.float32)
    else:
        coords = np.empty(count * 3, np.float32)
        me.vertices.foreach_get("co", coords)
        coords = coords.reshape(-1, 3)
    edges = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get("vertices", edges)
    selected, hidden, edge_hidden = np.empty(count, bool), np.empty(count, bool), np.empty(len(me.edges), bool)
    edge_selected = np.empty(len(me.edges), bool)
    me.vertices.foreach_get("select", selected)
    me.vertices.foreach_get("hide", hidden)
    me.edges.foreach_get("hide", edge_hidden)
    me.edges.foreach_get("select", edge_selected)
    topology = (len(me.edges), len(me.polygons), len(me.loops))
    same_shape = len(STATE.coords) == len(coords) and np.array_equal(~STATE.visible, hidden) and topology == STATE.topology
    if not (same_shape and np.array_equal(STATE.coords, coords)):
        STATE.geometry_version += 1           # a selection-only change keeps the lazy face data
    if not same_shape:
        STATE.topology_version += 1
    STATE.topology = topology
    STATE.face_selected = np.empty(len(me.polygons), bool)
    me.polygons.foreach_get("select", STATE.face_selected)
    STATE.visible = ~hidden
    STATE.coords, STATE.selected = coords, selected & STATE.visible
    all_edges = edges.reshape(-1, 2)
    STATE.all_edges = all_edges
    shown = ~edge_hidden & STATE.visible[all_edges[:, 0]] & STATE.visible[all_edges[:, 1]]
    STATE.edges, STATE.edge_ids = all_edges[shown], np.flatnonzero(shown)
    STATE.edge_selected = edge_selected[shown]
    STATE.pickable = np.flatnonzero(STATE.visible)
    STATE.kind = select_kind(context)
    STATE.world = edit_math.to_world(STATE.coords, STATE.matrix)
    STATE.world_stale, STATE.pick_cache = False, None


def moved_rows(indices, points):
    """A grab moved these vertices: only their rows of `coords` and `world` change (the rest waits: pick_points())."""
    STATE.coords[indices] = points
    STATE.world[indices] = edit_math.to_world(points, STATE.matrix)
    STATE.world_stale = True
    STATE.coords_version += 1
    STATE.geometry_version += 1


def pick_points():
    """World points of the visible vertices (cached; worked out when a pick needs them)."""
    if STATE.pick_cache is None or STATE.world_stale:
        STATE.pick_cache = STATE.world if len(STATE.pickable) == len(STATE.world) else STATE.world[STATE.pickable]
        STATE.world_stale = False
    return STATE.pick_cache


def face_topology(context):
    """(triangles, owner, loop start, loop count, loop -> edge) of the visible faces, rebuilt only when the topology or the hide
    flags change, not on a drag: `triangles` (n, 3) are vertex indices of Blender's own triangulation, `owner` the bmesh
    face index of each (a concave ngon gets several), and the loop data lists each face's edges."""
    if STATE.topology_cache is not None and STATE.topology_cache_version == STATE.topology_version:
        return STATE.topology_cache
    ob = context.edit_object
    me = ob.data
    ob.update_from_editmode()
    STATE.ignore_until = time.perf_counter() + IGNORE_SECONDS + IGNORE_PER_FACE * len(STATE.coords)
    me.calc_loop_triangles()
    triangles = np.empty(len(me.loop_triangles) * 3, np.int32)
    me.loop_triangles.foreach_get("vertices", triangles)
    owner = np.empty(len(me.loop_triangles), np.int32)
    me.loop_triangles.foreach_get("polygon_index", owner)
    face_hidden = np.empty(len(me.polygons), bool)
    me.polygons.foreach_get("hide", face_hidden)
    keep = ~face_hidden[owner]
    start = np.empty(len(me.polygons), np.int32)
    total = np.empty(len(me.polygons), np.int32)
    loop_edge = np.empty(len(me.loops), np.int32)
    me.polygons.foreach_get("loop_start", start)
    me.polygons.foreach_get("loop_total", total)
    me.loops.foreach_get("edge_index", loop_edge)
    STATE.topology_cache = (triangles.reshape(-1, 3)[keep], owner[keep], start, total, loop_edge)
    STATE.topology_cache_version = STATE.topology_version
    return STATE.topology_cache


def face_data(context):
    """(BVHTree of the visible faces in object space, triangle -> bmesh face index, loop start, loop count, loop -> edge),
    built on the first face pick after the geometry changed (8 ms at 50k faces, 42 ms at 200k)."""
    if STATE.faces is not None and STATE.faces_version == STATE.geometry_version:
        return STATE.faces
    from mathutils.bvhtree import BVHTree
    triangles, owner, start, total, loop_edge = face_topology(context)
    bvh = BVHTree.FromPolygons(STATE.coords.tolist(), triangles.tolist(), all_triangles=True)
    STATE.faces, STATE.faces_version = (bvh, owner, start, total, loop_edge), STATE.geometry_version
    return STATE.faces


def face_triangles(context, face_indices):
    """Local corner points (n * 3, 3) of the real triangulation of the visible faces `face_indices`: what the cage fills."""
    triangles, owner = face_topology(context)[:2]
    return STATE.coords[triangles[np.isin(owner, face_indices)].reshape(-1)]


def face_outline(context, face):
    """Local end points (n * 2, 3) of the edges of face `face`, for a line batch."""
    _triangles, _owner, start, total, loop_edge = face_topology(context)
    return STATE.coords[STATE.all_edges[loop_edge[start[face]:start[face] + total[face]]].reshape(-1)]


def face_edges(faces, face):
    """Bmesh edge indices of face `face` (from the face data of face_data())."""
    _bvh, _owner, start, total, loop_edge = faces
    return loop_edge[start[face]:start[face] + total[face]]


def on_depsgraph(depsgraph):
    """A depsgraph update while editing: an edit we did not make marks the caches stale. True = handled (the object
    caches don't care about the mesh being edited)."""
    if not STATE.object_name:
        return False
    if not STATE.grabbing and time.perf_counter() > STATE.ignore_until and any(update.is_updated_geometry for update in depsgraph.updates):
        STATE.stale = True
    return True

