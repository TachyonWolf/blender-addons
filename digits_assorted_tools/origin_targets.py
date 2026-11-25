# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the Origin Tool puts an origin: one function per snap target, each returning a WORLD-space point (or None
with a reason). Nothing here changes the scene; `origin_move.py` does the moving.

Base and Center of Box use the evaluated bounds (what you see, modifiers included). Center of Mass reads the evaluated
mesh: the centre of its volume when the mesh is closed, else the centre of its surface, else the mean of its points."""
from contextlib import contextmanager

import bmesh
import numpy as np
from mathutils import Vector

from .rig_placement import box_centre, box_corners

CLOSED_VOLUME_MINIMUM = 1e-12   # a closed mesh with less volume than this (flat, or inside out and balanced) uses its surface

TARGETS = (   # (target id, button label, tooltip)
    ('BASE', "Base of Object", "Origin to the bottom centre of the object's bounds (lowest point in world Z)"),
    ('BOX_CENTER', "Center of Box", "Origin to the centre of the object's bounding box"),
    ('MASS', "Center of Mass", "Origin to the centre of the volume (closed mesh) or of the surface (open mesh)"),
    ('PARENT', "Match Parent", "Origin to the parent's origin (a bone parent: the bone's head)"),
    ('SELECTION', "Selection", "Edit Mode: origin to the selected vertex, or the centre of the selected edges / faces"))
TARGET_IDS = tuple(target_id for target_id, _label, _tip in TARGETS)


@contextmanager
def evaluated_arrays(ob, depsgraph):
    """(points (n, 3), triangle point indices (m, 3), closed) of the evaluated mesh in the object's local space."""
    evaluated = ob.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        points = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertices.foreach_get("co", points)
        mesh.calc_loop_triangles()
        triangles = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
        mesh.loop_triangles.foreach_get("vertices", triangles)
        edge_of_loop = np.empty(len(mesh.loops), dtype=np.int64)
        mesh.loops.foreach_get("edge_index", edge_of_loop)
        edge_uses = np.bincount(edge_of_loop, minlength=len(mesh.edges))
        closed = len(mesh.edges) > 0 and bool(np.all(edge_uses == 2))
        yield points.reshape(-1, 3), triangles.reshape(-1, 3), closed
    finally:
        evaluated.to_mesh_clear()


def volume_centre(points, triangles):
    """Centre of the volume of a closed triangle mesh, or None when it has no volume (signed tetrahedra sum)."""
    origin = points.mean(axis=0)
    corner_a, corner_b, corner_c = (points[triangles[:, index]] - origin for index in range(3))
    volumes = np.einsum("ij,ij->i", corner_a, np.cross(corner_b, corner_c)) / 6.0
    total = volumes.sum()
    if abs(total) < CLOSED_VOLUME_MINIMUM:
        return None
    centroids = (corner_a + corner_b + corner_c) / 4.0
    return origin + (centroids * volumes[:, None]).sum(axis=0) / total


def surface_centre(points, triangles):
    """Centre of the surface (area-weighted triangle centres), or None when there is no area."""
    corner_a, corner_b, corner_c = (points[triangles[:, index]] for index in range(3))
    areas = np.linalg.norm(np.cross(corner_b - corner_a, corner_c - corner_a), axis=1) / 2.0
    if areas.sum() <= 0.0:
        return None
    centroids = (corner_a + corner_b + corner_c) / 3.0
    return (centroids * areas[:, None]).sum(axis=0) / areas.sum()


def mass_centre_local(ob, depsgraph):
    """(local point or None, method name) for Center of Mass."""
    with evaluated_arrays(ob, depsgraph) as (points, triangles, closed):
        if len(points) == 0:
            return None, ""
        if closed and len(triangles):
            centre = volume_centre(points, triangles)
            if centre is not None:
                return Vector(centre.tolist()), "volume"
        if len(triangles):
            centre = surface_centre(points, triangles)
            if centre is not None:
                return Vector(centre.tolist()), "surface"
        return Vector(points.mean(axis=0).tolist()), "points"


def bounds_world(ob, depsgraph):
    """(low, high) of the world-space box around the 8 corners of the evaluated bounding box."""
    corners = box_corners(ob.matrix_world, ob.evaluated_get(depsgraph).bound_box)
    return Vector(map(min, zip(*corners))), Vector(map(max, zip(*corners)))


def base_point(ob, depsgraph):
    """Bottom centre of the bounds: the middle of the box in X and Y, the lowest point in Z."""
    low, high = bounds_world(ob, depsgraph)
    return Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))


def box_centre_point(ob, depsgraph):
    return box_centre(box_corners(ob.matrix_world, ob.evaluated_get(depsgraph).bound_box))


def parent_point(ob):
    """World position of the parent's origin (a bone parent: the bone head), or None without a parent."""
    parent = ob.parent
    if parent is None:
        return None
    if ob.parent_type == 'BONE' and parent.pose and ob.parent_bone in parent.pose.bones:
        return parent.matrix_world @ parent.pose.bones[ob.parent_bone].head
    return parent.matrix_world.translation.copy()


def selection_local(edit_mesh):
    """Centre of the selection in a bmesh: the mean of the selected faces' centres if any face is selected, else of
    the selected edges' midpoints, else of the selected vertices. None when nothing is selected."""
    faces = [face.calc_center_median() for face in edit_mesh.faces if face.select]
    if faces:
        return sum(faces, Vector()) / len(faces)
    edges = [(edge.verts[0].co + edge.verts[1].co) / 2 for edge in edit_mesh.edges if edge.select]
    if edges:
        return sum(edges, Vector()) / len(edges)
    verts = [vert.co.copy() for vert in edit_mesh.verts if vert.select]
    return sum(verts, Vector()) / len(verts) if verts else None


def selection_point(ob):
    """World position of the Edit Mode selection of a mesh object in Edit Mode, or None."""
    local = selection_local(bmesh.from_edit_mesh(ob.data))
    return None if local is None else ob.matrix_world @ local


def world_target(ob, target_id, depsgraph):
    """(world point or None, why not) for one object and one snap target."""
    if target_id == 'PARENT':
        point = parent_point(ob)
        return point, "" if point else "no parent"
    if target_id == 'SELECTION':
        point = selection_point(ob)
        return point, "" if point else "nothing selected"
    if target_id == 'MASS':
        local, _method = mass_centre_local(ob, depsgraph)
        return (ob.matrix_world @ local if local else None), "" if local else "no geometry"
    return (base_point if target_id == 'BASE' else box_centre_point)(ob, depsgraph), ""
