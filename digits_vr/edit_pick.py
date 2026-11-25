# SPDX-License-Identifier: GPL-3.0-or-later
"""Element picking in Edit mode, by Blender's own select mode (tool_settings.mesh_select_mode, also changed on the
desktop): vertex (nearest to the laser / hand), edge (nearest segment) or face (BVH ray / nearest point). The laser
takes the front layer; the hand takes the nearest within the touch distance. Against the cached WORLD points of
edit_state, so object scale and rotation just work. Brute force numpy for vertices and edges (about 0.1 ms at 6k
vertices); faces use a lazy BVH of the visible faces."""
import time

import numpy as np
from mathutils import Vector

from . import desk_qol_math, edit_math, edit_state, pick_math, router, size_state
from .picking import Target

EDIT_VERT = 'EDIT_VERT'      # the Target kind of every Edit mode element (its `element` says which)


def pick(context, pose, behaviour_name):
    """Target of the element under the laser / hand, or None (also None when Edit mode refuses this mesh)."""
    edit_state.sync(context)
    state = edit_state.STATE
    if not state.ready:
        return None
    laser = router.uses_laser(behaviour_name)
    origin, direction = Vector(pose.aim_location), Vector(pose.aim_direction)
    point = origin          # touch picks at the fingertip too [user, 2026-11-25]
    return pick_at(context, laser, origin, direction, point)


def pick_at(context, laser, origin, direction, point, hover=False, kind=None):
    """The pick for a laser ray (`laser`) or a touch point; no sync, no refusal check (the caller did). `hover` = a
    preview (every tick while the hand moves): skipped on big meshes (edit_math.HOVER_MAX_*)."""
    state = edit_state.STATE
    kind = kind or state.kind               # (`kind`: a tool that works on one kind, e.g. the loop cut on edges)
    reach = size_state.laser_length()
    if hover and (len(state.coords) > edit_math.HOVER_MAX_VERTS if kind == edit_math.VERT
                  else len(state.edge_ids) > edit_math.HOVER_MAX_FACES * 2):
        return None
    if kind == edit_math.VERT:
        points = edit_state.pick_points()
        if laser:
            found = edit_math.nearest_to_ray(np.array(origin), np.array(direction), points,
                                             size_state.scaled(edit_math.LASER_PICK_RADIUS), reach)
        else:
            found = edit_math.nearest_to_point(np.array(point), points, size_state.touch_distance())
        index, where = (None, None) if found is None else (int(state.pickable[found]), points[found])
    elif kind == edit_math.EDGE:
        index, where = _edge(context, laser, origin, direction, point, reach, hover)
    else:
        index, where = _face(context, laser, origin, direction, point, reach)
    if index is None:
        return None
    return Target(EDIT_VERT, state.object_name, distance=float((Vector(where) - origin).length) if laser else 0.0,
                  index=index, element=kind)


def _edge(context, laser, origin, direction, point, reach, hover):
    """Face first (a ray hit or the nearest face, then its nearest edge: a few microseconds at any size); when no face
    answers and this is a pull / grip (not a hover), the brute-force nearest edge (36 ms at 250k faces)."""
    state = edit_state.STATE
    face, where = _face(context, laser, origin, direction, point, reach)
    if face is not None:
        edges = edit_state.face_edges(edit_state.face_data(context), face)
        if len(edges):
            heads, tails = state.world[state.all_edges[edges, 0]], state.world[state.all_edges[edges, 1]]
            if laser:
                gap, _along = pick_math.ray_segment_distances(np.array(origin), np.array(direction), heads, tails)
            else:
                gap = pick_math.segment_distances(np.array(point), heads, tails)
            best = int(np.argmin(gap))
            if laser or gap[best] <= size_state.touch_distance():
                return int(edges[best]), (heads[best] + tails[best]) / 2
    if hover:
        return None, None
    heads, tails = state.world[state.edges[:, 0]], state.world[state.edges[:, 1]]
    if laser:
        found = edit_math.nearest_edge_to_ray(np.array(origin), np.array(direction), heads, tails,
                                              size_state.scaled(edit_math.LASER_PICK_RADIUS), reach)
    else:
        found = edit_math.nearest_edge_to_point(np.array(point), heads, tails, size_state.touch_distance())
    return (None, None) if found is None else (int(state.edge_ids[found]), (heads[found] + tails[found]) / 2)


def _face(context, laser, origin, direction, point, reach):
    state = edit_state.STATE
    bvh, owner = edit_state.face_data(context)[:2]
    inverse = np.linalg.inv(state.matrix)
    scale = float(np.abs(np.linalg.det(state.matrix[:3, :3])) ** (1 / 3)) or 1.0
    if laser:
        local_origin = Vector(inverse[:3, :3] @ np.array(origin) + inverse[:3, 3])
        local_direction = Vector(inverse[:3, :3] @ np.array(direction)).normalized()
        hit = bvh.ray_cast(local_origin, local_direction, reach / scale)
    else:
        local_point = Vector(inverse[:3, :3] @ np.array(point) + inverse[:3, 3])
        hit = bvh.find_nearest(local_point, size_state.touch_distance() / scale)
    if hit[0] is None:
        return None, None
    return int(owner[hit[2]]), state.matrix[:3, :3] @ np.array(hit[0]) + state.matrix[:3, 3]


def refused(context):
    """True (with the reason on the desk's note line) when Edit mode in VR can't work on this mesh: no pick, no tool."""
    edit_state.sync(context)
    reason = edit_state.STATE.reason
    if reason:
        desk_qol_math.NOTICE.show(reason, time.perf_counter())
    return bool(reason) or not edit_state.STATE.object_name
