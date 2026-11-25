# SPDX-License-Identifier: GPL-3.0-or-later
"""What Blender draws for an object, in its own space, for picking and the hover glow: surfaces (meshes, filled
curves, text) are picked by their evaluated surface (picking.py: closest_point_on_mesh, scene.ray_cast); the
rest (empties, lights, cameras, curves without faces, bone custom shapes) by their line shape (points, edges).
A collection instance is its instanced objects (parts) plus its own empty shape. Evaluated geometry is cached per
(object, data) until forget() / clear() (the depsgraph says it changed, undo, load)."""
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import pick_math, shape_math

SURFACE_TYPES = {'MESH', 'CURVE', 'FONT', 'SURFACE', 'META'}
MATRIX_TOLERANCE = 1e-4

_geometry = {}   # (object name_full, data name_full) -> (local points K x 3, edges M x 2) or None
_faces = {}      # same key -> the evaluated geometry has faces
_outline = {}    # same key -> (points f32, edges, face normals, plane offsets, first face, second face) or None
_pending = {}    # same key -> generator finishing the outline in small steps (advance())
SMALL_FACES = 5000
OUTLINE_MAX_FACES = 400000   # a bigger mesh gets no outline (never a box); its name tag still shows


def clear():
    _geometry.clear()
    _faces.clear()
    _outline.clear()
    _pending.clear()


def forget(names):
    """Drop the cached geometry of these objects (by name_full)."""
    for key in [key for key in _geometry if key[0] in names]:
        _geometry.pop(key, None)
        _faces.pop(key, None)
        _outline.pop(key, None)
        _pending.pop(key, None)


def _key(ob):
    data = getattr(ob, "data", None)
    return ob.name_full, data.name_full if data else ""


def _mesh_arrays(mesh):
    if mesh is None or not len(mesh.vertices):
        return None
    points = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", points)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edges)
    return points.reshape(-1, 3), pick_math.mesh_edges(len(mesh.vertices), edges)


def shape_geometry(ob):
    """(local points, edge vertex pairs) of an object's evaluated geometry (modifiers, curves, text), cached, or
    None when it has none. Also used for bone custom shapes (the shape object may sit outside the scene: then its
    own mesh data)."""
    key = _key(ob)
    if key in _geometry:
        return _geometry[key]
    geometry, faces = None, False
    if ob.type == 'MESH' and not ob.modifiers:
        geometry, faces = _mesh_arrays(ob.data), bool(len(ob.data.polygons))
    elif ob.type in SURFACE_TYPES:
        evaluated = ob
        try:
            evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            geometry, faces = _mesh_arrays(mesh), bool(mesh and len(mesh.polygons))
        except (RuntimeError, ReferenceError, AttributeError):
            if ob.type == 'MESH':
                geometry, faces = _mesh_arrays(ob.data), bool(len(ob.data.polygons))
        finally:
            try:
                evaluated.to_mesh_clear()
            except RuntimeError:
                pass
    _geometry[key], _faces[key] = geometry, faces
    return geometry


def _evaluated_mesh(ob):
    try:
        return ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    except (RuntimeError, ReferenceError):
        return ob.data


def _read_outline(mesh):
    """The raw arrays of a mesh for its outline, in one go (about 5 ms for 200k faces; attribute reads are far
    faster than the polygon / loop ones). The mesh may be cleared right after."""
    count = len(mesh.polygons)
    points = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.attributes["position"].data.foreach_get("vector", points)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.attributes[".edge_verts"].data.foreach_get("value", edges) if len(edges) else None
    normals = np.empty(count * 3, dtype=np.float32)
    mesh.polygon_normals.foreach_get("vector", normals)
    starts = np.empty(count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    loop_edges = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.attributes[".corner_edge"].data.foreach_get("value", loop_edges)
    loop_verts = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.attributes[".corner_vert"].data.foreach_get("value", loop_verts)
    return points.reshape(-1, 3), edges.reshape(-1, 2), normals.reshape(-1, 3), starts, loop_edges, loop_verts


def _finish_outline(raw):
    """Generator: the rest of the work in small steps (each about 1-3 ms for 200k faces); ends with the data."""
    points, edges, normals, starts, loop_edges, loop_verts = raw
    yield
    totals = np.diff(np.append(starts, len(loop_edges)))
    loop_faces = np.repeat(np.arange(len(starts), dtype=np.int32), totals)
    yield
    offsets = (normals * points[loop_verts[starts]]).sum(axis=1)
    yield
    first, second = shape_math.edge_faces(loop_edges, loop_faces, len(edges))
    yield (points, edges.astype(np.int64), normals, offsets, first, second)


def outline_data(ob):
    """Cached silhouette data of an object's evaluated surface, or None while it is still being built (see
    advance(); the caller shows a small cross meanwhile) or when there is none (no faces, over OUTLINE_MAX_FACES)."""
    key = _key(ob)
    if key in _outline:
        return _outline[key]
    if key in _pending:
        return None
    raw, evaluated = None, ob
    try:
        if ob.type == 'MESH' and not ob.modifiers:
            mesh = ob.data
        else:
            evaluated = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
        if mesh is not None and 0 < len(mesh.polygons) <= OUTLINE_MAX_FACES:
            raw = _read_outline(mesh)
    except (RuntimeError, ReferenceError, AttributeError, KeyError):
        raw = None
    finally:
        if evaluated is not ob:
            try:
                evaluated.to_mesh_clear()
            except RuntimeError:
                pass
    if raw is None:
        _outline[key] = None
    elif len(raw[3]) < SMALL_FACES:       # small: finish now (well under a millisecond)
        for data in _finish_outline(raw):
            pass
        _outline[key] = data
        return data
    else:
        _pending[key] = _finish_outline(raw)
    return None


def advance():
    """Run one small step of the oldest outline being built (called once per tick); True when one just finished."""
    for key, steps in _pending.items():
        data = next(steps, None)
        if data is not None:
            _outline[key] = data
            del _pending[key]
            return True
        return False
    return False


def has_surface(ob):
    """Picked by its surface (faces after modifiers), not by lines."""
    if ob.type == 'MESH':
        return bool(len((_evaluated_mesh(ob) if ob.modifiers else ob.data).polygons))
    if ob.type not in SURFACE_TYPES:
        return False
    shape_geometry(ob)
    return _faces.get(_key(ob), False)


def instance_parts(ob):
    """[(part object, matrix from the part to the instancer's space)] of a collection instance (nested instances
    and parts hidden in the viewport left out), or [] for any other object."""
    collection = ob.instance_collection if ob.instance_type == 'COLLECTION' else None
    if collection is None:
        return []
    offset = Matrix.Translation(-collection.instance_offset)
    return [(part, offset @ part.matrix_world) for part in collection.all_objects
            if not part.hide_viewport and not (part.instance_type == 'COLLECTION' and part.instance_collection)]


def _image_aspect(ob):
    image = ob.data if ob.empty_display_type == 'IMAGE' else None
    width, height = (image.size[0], image.size[1]) if image is not None and image.size[0] else (1, 1)
    longest = max(width, height) or 1
    return width / longest, height / longest


def line_shape(ob):
    """(points, edges) in the object's space of what Blender draws for an object without a surface."""
    if ob.type == 'EMPTY':
        return shape_math.empty_shape(ob.empty_display_type, ob.empty_display_size,
                                      tuple(ob.empty_image_offset), _image_aspect(ob))
    if ob.type == 'LIGHT':
        light = ob.data
        return shape_math.light_shape(light.type, getattr(light, "shadow_soft_size", 0.0),
                                      getattr(light, "shape", 'SQUARE'), getattr(light, "size", 1.0),
                                      getattr(light, "size_y", 1.0), getattr(light, "spot_size", 0.785))
    if ob.type == 'CAMERA':
        return shape_math.camera_shape(tuple(tuple(corner) for corner in ob.data.view_frame(scene=bpy.context.scene)))
    geometry = shape_geometry(ob) if ob.type in SURFACE_TYPES else None
    return geometry if geometry is not None else shape_math.cross()


def outline_shape(ob, eye):
    """(points, edges) in the object's space for the hover glow of a surface seen from `eye` (a point in that
    space): only its silhouette (edges between faces turned toward and away from you, plus boundary edges), a hair
    toward you so it wins the depth test against its own surface. A collection instance: its own empty shape plus
    its parts' outlines. No surface: its line shape. A mesh over OUTLINE_MAX_FACES (an enormous scan): its name tag only."""
    parts = instance_parts(ob)
    if parts:
        shapes = [line_shape(ob)]
        for part, relative in parts:
            part_eye = relative.inverted_safe() @ Vector(eye)
            points, edges = outline_shape(part, part_eye)
            shapes.append((shape_math.place(np.array(relative), points), edges))
        return shape_math.join(*shapes)
    if not has_surface(ob):
        return line_shape(ob)
    data = outline_data(ob)
    if data is None:
        return shape_math.cross()      # being built, or enormous: a small cross, never a box
    points, edges, normals, offsets, first, second = data
    mask = shape_math.silhouette_mask(normals, offsets, first, second, eye)
    ends = shape_math.toward(points[edges[mask].ravel()], eye).astype(np.float64)   # only the outline's own ends
    return ends, np.arange(len(ends), dtype=np.int64).reshape(-1, 2)


def line_points(shape, cross_size=0.005):
    """N x 3 line end points of a shape (pairs); a loose point (zero-length edge) becomes a small cross."""
    points, edges = shape
    real = edges[:, 0] != edges[:, 1]
    pairs = points[edges[real]].reshape(-1, 3)
    loose = [cross for index in edges[~real, 0].tolist() for cross in pick_math.point_cross(points[index], cross_size)]
    return np.vstack((pairs, np.asarray(loose, dtype=np.float64).reshape(-1, 3))).astype(np.float32)


def same_matrix(first, second):
    return all(abs(first[row][column] - second[row][column]) <= MATRIX_TOLERANCE
               for row in range(4) for column in range(4))
