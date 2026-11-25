# SPDX-License-Identifier: GPL-3.0-or-later
"""What Blender draws for objects without a surface (empties, lights, cameras), as local-space line shapes: (points
K x 3, edges M x 2; cached per parameters, never changed in place). numpy only (no bpy), tested headless. Picking (picking.ObjectEdges) and the hover glow
(overlay.py) both use these, so you pick what you see."""
import functools
import math

import numpy as np

CIRCLE_SEGMENTS = 24
LIGHT_MIN_RADIUS = 0.1    # m: a light's circles are at least this big (Blender draws a fixed-size icon)
LIGHT_RAY_LENGTH = 1.0    # m: a sun's direction line, a spot's cone length
BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def _shape(points, edges):
    return np.asarray(points, dtype=np.float64).reshape(-1, 3), np.asarray(edges, dtype=np.int64).reshape(-1, 2)


def join(*shapes):
    """One shape from several (edge indexes shifted)."""
    points, edges, base = [], [], 0
    for shape_points, shape_edges in shapes:
        points.append(shape_points)
        edges.append(shape_edges + base)
        base += len(shape_points)
    if not points:
        return _shape([], [])
    return np.vstack(points), np.vstack(edges)


def lines(pairs):
    """Shape from a flat list of line end points (p0, p1, p2, p3, ...)."""
    count = len(pairs) // 2
    return _shape(pairs, [(2 * index, 2 * index + 1) for index in range(count)])


def circle(radius, axes=(0, 1), centre=(0.0, 0.0, 0.0), segments=CIRCLE_SEGMENTS, radius_b=None):
    """Closed circle (or ellipse with radius_b) in the plane of the two given axes."""
    radius_b = radius if radius_b is None else radius_b
    points = np.tile(np.asarray(centre, dtype=np.float64), (segments, 1))
    angles = np.linspace(0.0, 2 * math.pi, segments, endpoint=False)
    points[:, axes[0]] += radius * np.cos(angles)
    points[:, axes[1]] += radius_b * np.sin(angles)
    return _shape(points, [(index, (index + 1) % segments) for index in range(segments)])


def rectangle(corners):
    """Closed loop through 4 corners."""
    return _shape(corners, [(0, 1), (1, 2), (2, 3), (3, 0)])


def cube_corners(half):
    """8 corners of a cube of half-size `half`, in Blender's bound_box order."""
    signs = ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (1, -1, -1), (1, -1, 1), (1, 1, 1), (1, 1, -1))
    return [(x * half, y * half, z * half) for x, y, z in signs]


def box(corners):
    """The 12 edges of an 8-corner box (Blender's bound_box order)."""
    return _shape(corners, BOX_EDGES)


@functools.lru_cache(maxsize=256)   # shapes are shared: callers must not change the arrays
def empty_shape(display_type, size, image_offset=(-0.5, -0.5), image_aspect=(1.0, 1.0)):
    """Lines of an empty's display type (Blender manual: Circle in XZ, Cone pointing +Y, Single Arrow +Z)."""
    if display_type == 'ARROWS':
        return lines([(0, 0, 0), (size, 0, 0), (0, 0, 0), (0, size, 0), (0, 0, 0), (0, 0, size)])
    if display_type == 'SINGLE_ARROW':
        head = 0.1 * size
        return lines([(0, 0, 0), (0, 0, size), (head, 0, size - head), (0, 0, size), (-head, 0, size - head),
                      (0, 0, size), (0, head, size - head), (0, 0, size), (0, -head, size - head), (0, 0, size)])
    if display_type == 'CIRCLE':
        return circle(size, axes=(0, 2))
    if display_type == 'CUBE':
        return box(cube_corners(size))
    if display_type == 'SPHERE':
        return join(circle(size, (0, 1)), circle(size, (1, 2)), circle(size, (0, 2)))
    if display_type == 'CONE':
        base = circle(size, axes=(0, 2))
        tip = _shape([(0, 2 * size, 0)], np.empty((0, 2)))
        points, edges = join(base, tip)
        spokes = [(index, len(points) - 1) for index in range(0, CIRCLE_SEGMENTS, CIRCLE_SEGMENTS // 4)]
        return points, np.vstack((edges, spokes))
    if display_type == 'IMAGE':
        width, height = size * image_aspect[0], size * image_aspect[1]
        left, bottom = image_offset[0] * width, image_offset[1] * height
        return rectangle([(left, bottom, 0), (left + width, bottom, 0), (left + width, bottom + height, 0),
                          (left, bottom + height, 0)])
    return lines([(-size, 0, 0), (size, 0, 0), (0, -size, 0), (0, size, 0), (0, 0, -size), (0, 0, size)])  # PLAIN_AXES


@functools.lru_cache(maxsize=256)   # shapes are shared: callers must not change the arrays
def light_shape(light_type, radius, area_shape='SQUARE', size=1.0, size_y=1.0, spot_angle=math.radians(45)):
    """Lines of a light: three circles of its radius (at least LIGHT_MIN_RADIUS), plus the area's outline, a sun's
    direction line or a spot's cone (lights shine along -Z)."""
    radius = max(radius, LIGHT_MIN_RADIUS)
    parts = [circle(radius, (0, 1)), circle(radius, (1, 2)), circle(radius, (0, 2))]
    if light_type == 'AREA':
        half_x, half_y = size / 2, (size_y if area_shape in ('RECTANGLE', 'ELLIPSE') else size) / 2
        if area_shape in ('DISK', 'ELLIPSE'):
            parts.append(circle(half_x, (0, 1), radius_b=half_y))
        else:
            parts.append(rectangle([(-half_x, -half_y, 0), (half_x, -half_y, 0), (half_x, half_y, 0),
                                    (-half_x, half_y, 0)]))
    elif light_type == 'SUN':
        parts.append(lines([(0, 0, 0), (0, 0, -LIGHT_RAY_LENGTH)]))
    elif light_type == 'SPOT':
        reach = LIGHT_RAY_LENGTH * math.tan(spot_angle / 2)
        rim = circle(reach, (0, 1), centre=(0, 0, -LIGHT_RAY_LENGTH))
        tip = [(0, 0, 0)] * 4
        ends = [(reach, 0, -LIGHT_RAY_LENGTH), (-reach, 0, -LIGHT_RAY_LENGTH), (0, reach, -LIGHT_RAY_LENGTH),
                (0, -reach, -LIGHT_RAY_LENGTH)]
        parts += [rim, lines([point for pair in zip(tip, ends) for point in pair])]
    return join(*parts)


@functools.lru_cache(maxsize=256)   # shapes are shared: callers must not change the arrays
def camera_shape(frame):
    """Lines of a camera: Camera.view_frame()'s 4 corners (local space, display size applied), the lines from the
    origin to them, and the 'up' triangle over the top edge."""
    frame = np.asarray(frame, dtype=np.float64).reshape(4, 3)
    top = frame[np.argsort(-frame[:, 1])[:2]]          # the two corners with the largest y
    middle = top.mean(axis=0)
    half = abs(top[0, 0] - top[1, 0]) / 2
    triangle = [middle + (-0.7 * half, 0.1 * half, 0), middle + (0, 0.8 * half, 0), middle + (0.7 * half, 0.1 * half, 0)]
    return join(rectangle(frame), lines([point for corner in frame for point in ((0, 0, 0), corner)]),
                _shape(triangle, [(0, 1), (1, 2), (2, 0)]))


def place(matrix, points):
    """Points K x 3 through a 4 x 4 (row-major) matrix."""
    matrix = np.asarray(matrix, dtype=np.float64)
    return np.asarray(points, dtype=np.float64) @ matrix[:3, :3].T + matrix[:3, 3]


# --- silhouette outline (what the hover glow draws for a surface) -------------------------------------------------

def edge_faces(loop_edges, loop_faces, edge_count):
    """Per edge a face that uses it and another one: (first, second) int arrays, -1 where there is none (a boundary
    edge has no second face, a loose edge no face). From the per-loop edge index and the face of each loop. Two
    scatters (the last write wins), no sort: about 2 ms for 800k loops."""
    first = np.full(edge_count, -1, dtype=np.int32)
    second = np.full(edge_count, -1, dtype=np.int32)
    loop_edges, loop_faces = np.asarray(loop_edges), np.asarray(loop_faces)
    first[loop_edges[::-1]] = loop_faces[::-1]      # the lowest face
    second[loop_edges] = loop_faces                 # the highest face
    second[second == first] = -1                    # only one face
    return first, second


def silhouette_mask(normals, offsets, first, second, eye):
    """Which edges are on the outline seen from `eye`: those between a face turned toward it and one turned away,
    plus boundary and loose edges (no second face). Faces are planes (normal, offset = normal . a point on it)."""
    facing = np.empty(len(normals) + 1, dtype=bool)
    facing[:-1] = normals @ np.asarray(eye, dtype=normals.dtype) > offsets
    facing[-1] = False                                # index -1 (no face)
    return (facing[first] != facing[second]) | (second < 0)


def toward(points, eye, fraction=0.003):
    """Points moved a tiny way toward the eye, so a line lying on a surface wins the depth test against it."""
    eye = np.asarray(eye, dtype=points.dtype)
    return points + (eye - points) * points.dtype.type(fraction)


def cross(size=0.05):
    """A small 3-axis cross: stands for an object with no wire shape (never a box)."""
    return lines([sign * axis * size for axis in np.identity(3) for sign in (1, -1)])


def tag_frame(point, head, height_per_metre=0.03, min_height=0.025, max_height=0.6):
    """(bottom-left corner, right vector, up vector, height) of an upright name tag floating above `point`, facing
    `head`; the tag's width = right * width / height. Its height grows with the distance so it reads the same size; it never leans with your head."""
    point, head = np.asarray(point, dtype=np.float64), np.asarray(head, dtype=np.float64)
    view = point - head
    distance = float(np.linalg.norm(view))
    height = min(max_height, max(min_height, height_per_metre * distance))
    flat = np.array([view[0], view[1], 0.0])
    flat = flat / np.linalg.norm(flat) if np.linalg.norm(flat) > 1e-6 else np.array([0.0, 1.0, 0.0])
    right = np.array([flat[1], -flat[0], 0.0])       # flat x up (looking along +flat, right is to the viewer's right)
    up = np.array([0.0, 0.0, 1.0])
    base = point + up * height * 0.8
    return base, right * height, up * height, height
