# SPDX-License-Identifier: GPL-3.0-or-later
"""What is INSIDE a box, per mode, and adding it to the selection (select_gesture.SelectGesture holds the box).
Object mode: the world bounding-box centre of every pickable object (display-hidden types and unselectable objects are
skipped, as picking does). Edit mode: the visible vertices (not hidden, mesh not refused). Pose mode: the middle of each
bone of local armatures in Pose mode; hidden, unselectable and hidden-collection bones are skipped, linked rigs too.
The box ADDS; the select bubble (box_math.Sphere, any `.inside(points)` shape) adds or, with `remove`, deselects. `cache`
(a dict the caller keeps for one stroke) holds the object / bone points, so a stroke works them out once.
Returns whether the selection changed: the caller pushes ONE undo step, or none."""
import bmesh
import numpy as np
from mathutils import Vector

from . import edit_math, edit_select, edit_state, router, selection
from .picking import _bone_visible, is_linked
from .runtime import RUNTIME


def _object_points(context):
    objects = [ob for ob in RUNTIME.cache.pickable_objects(context.scene, context.view_layer)]
    points = np.array([tuple(ob.matrix_world @ (sum((Vector(c) for c in ob.bound_box), Vector()) / 8.0)
                             if ob.type != 'EMPTY' else ob.matrix_world.translation) for ob in objects]).reshape(-1, 3)
    return objects, points


def _bone_points(context):
    bones = [(ob, pose_bone) for ob in selection.pose_armatures(context) if not is_linked(ob)
             for pose_bone in ob.pose.bones if _bone_visible(pose_bone)]
    points = np.array([tuple(ob.matrix_world @ ((pose_bone.head + pose_bone.tail) / 2.0)) for ob, pose_bone in bones]).reshape(-1, 3)
    return bones, points


def _cached(cache, name, make, context):
    if cache is None:
        return make(context)
    if name not in cache:
        cache[name] = make(context)
    return cache[name]


def apply(context, gesture, remove=False, cache=None):
    mode = router.mode_kind(context.mode)
    if mode == router.EDIT:
        return _apply_edit(context, gesture, remove)
    if mode == router.POSE:
        bones, points = _cached(cache, "bones", _bone_points, context)
        changed = False
        for (ob, pose_bone), hit in zip(bones, gesture.inside(points)):
            if hit and pose_bone.select == remove:
                pose_bone.select, changed = not remove, True
        return changed
    if mode != router.OBJECT:
        return False
    objects, points = _cached(cache, "objects", _object_points, context)
    changed = False
    for ob, hit in zip(objects, gesture.inside(points)):
        if hit and ob.select_get(view_layer=context.view_layer) == remove:
            ob.select_set(not remove, view_layer=context.view_layer)
            changed = True
    return changed


def _inside_faces(context, inside):
    """Bmesh indices of the visible faces whose vertices are all inside (from the cached triangulation: no loop over faces)."""
    triangles, owner, start = edit_state.face_topology(context)[:3]
    outside = np.bincount(owner[~inside[triangles].all(axis=1)], minlength=len(start))
    return np.flatnonzero((np.bincount(owner, minlength=len(start)) > 0) & (outside == 0))


def _apply_edit(context, gesture, remove):
    state = edit_state.STATE
    edit_state.sync(context)
    bm = edit_select.live_bmesh(context, state.object_name)
    if bm is None:
        return False
    inside = np.zeros(len(state.world), bool)
    inside[state.pickable] = gesture.inside(edit_state.pick_points())
    kind = state.kind
    if kind == edit_math.VERT:
        elements, wanted = bm.verts, np.flatnonzero(inside)
    elif kind == edit_math.EDGE:                     # an edge is inside when both its ends are
        elements, wanted = bm.edges, state.edge_ids[inside[state.edges[:, 0]] & inside[state.edges[:, 1]]]
    else:                                            # a face when all its vertices are (visible faces only)
        elements, wanted = bm.faces, _inside_faces(context, inside)
    todo = [index for index in wanted.tolist() if elements[index].select == remove]    # only the wanted ones are read
    if not todo:
        return False
    for index in todo:
        elements[index].select_set(not remove)
    bm.select_flush_mode()
    bmesh.update_edit_mesh(context.edit_object.data, loop_triangles=False, destructive=False)
    return True
