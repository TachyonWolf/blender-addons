# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Mirrored Mesh (core): a primitive built as only the half that a Mirror modifier turns back into the whole.

Pure geometry and placement, no operators or UI (see mirrored_mesh_ui.py). The Mirror modifier is read by
mirror_pivot (`applicable_mirrors`, `mirror_planes_of`), the one place that knows its axes and space.

A primitive may be turned in 90 degree steps so that it mirrors exactly (a Monkey on Z lies down, a Cone on Z lies
along X or Y). `analyse` lists the distinct turns of one primitive and the axes each mirrors exactly; the answer is
cached, so drawing a card never builds a mesh twice."""
import math
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import permutations, product

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from .mirror_pivot import AXIS_LETTERS, applicable_mirrors, mirror_planes_of

SYMMETRY_TOLERANCE = 1e-4   # a mirrored point counts as present when a vertex is this close
FLAT_TOLERANCE = 1e-5       # a primitive with every vertex this close to a plane is flat on it
CUT_DISTANCE = 1e-5         # vertices this close to the plane stay on it when cutting
MONKEY = 'MONKEY'

# Overall width fits these shapes by measuring them, whatever the size the bmesh operator expects
FIT_TO_WIDTH = ('CUBE', 'PLANE', 'GRID', MONKEY)
# Where each primitive's main direction points when unturned, and what to call it: (noun, direction)
MAIN_DIRECTION = {'CUBE': ("Axis", (0, 0, 1)), 'UV_SPHERE': ("Pole", (0, 0, 1)), 'ICO_SPHERE': ("Pole", (0, 0, 1)),
                  'PLANE': ("Faces", (0, 0, 1)), 'CIRCLE': ("Faces", (0, 0, 1)), 'CYLINDER': ("Axis", (0, 0, 1)),
                  'CONE': ("Tip", (0, 0, 1)), 'TORUS': ("Axis", (0, 0, 1)), MONKEY: ("Faces", (0, -1, 0)),
                  'GRID': ("Faces", (0, 0, 1))}
# Which setting counts the round primitive's corners (setting name, what to call them in a message)
CORNER_COUNT = {'CIRCLE': ("segments", "vertices"), 'CYLINDER': ("segments", "vertices"),
                'CONE': ("segments", "vertices"), 'UV_SPHERE': ("segments", "segments"),
                'TORUS': ("major_segments", "major segments")}
# The settings each primitive uses (the redo panel shows only these)
SETTING_NAMES = {'CUBE': ("size",), 'UV_SPHERE': ("size", "segments", "rings"), 'ICO_SPHERE': ("size", "subdivisions"),
                 'PLANE': ("size",), 'CIRCLE': ("size", "segments"), 'CYLINDER': ("size", "segments"),
                 'CONE': ("size", "segments"), 'TORUS': ("size", "major_segments", "minor_segments"),
                 MONKEY: ("size",), 'GRID': ("size", "grid_divisions")}


@dataclass(frozen=True)
class PrimitiveSettings:
    """Size (overall width) and counts of a primitive; hashable, so the analysis can be cached on it."""
    size: float = 2.0
    segments: int = 32
    rings: int = 16
    major_segments: int = 48
    minor_segments: int = 12
    subdivisions: int = 2
    grid_divisions: int = 10


# ---------------------------------------------------------------------------
# Building a full primitive around the origin
# ---------------------------------------------------------------------------

def create_torus(bm, major_segments, minor_segments, major_radius, minor_radius):
    """A torus around Z (bmesh.ops has none): rings of `minor_segments` vertices, outward facing quads."""
    rings = []
    for major in range(major_segments):
        angle = math.tau * major / major_segments
        ring = []
        for minor in range(minor_segments):
            tube_angle = math.tau * minor / minor_segments
            distance = major_radius + minor_radius * math.cos(tube_angle)
            ring.append(bm.verts.new((distance * math.cos(angle), distance * math.sin(angle),
                                      minor_radius * math.sin(tube_angle))))
        rings.append(ring)
    for major in range(major_segments):
        ring, next_ring = rings[major], rings[(major + 1) % major_segments]
        for minor in range(minor_segments):
            following = (minor + 1) % minor_segments
            bm.faces.new((ring[minor], next_ring[minor], next_ring[following], ring[following]))
    return [vert for ring in rings for vert in ring]


def fit_width(verts, width):
    xs = [vert.co.x for vert in verts]
    scale = width / (max(xs) - min(xs))
    for vert in verts:
        vert.co *= scale


def build_primitive(bm, primitive, settings):
    """Add the full primitive, centred on the origin, to `bm`. Returns its vertices."""
    half = settings.size / 2
    ops = bmesh.ops
    if primitive == 'CUBE':
        verts = ops.create_cube(bm, size=1.0)["verts"]
    elif primitive == 'UV_SPHERE':
        verts = ops.create_uvsphere(bm, u_segments=settings.segments, v_segments=settings.rings, radius=half)["verts"]
    elif primitive == 'ICO_SPHERE':
        verts = ops.create_icosphere(bm, subdivisions=settings.subdivisions, radius=half)["verts"]
    elif primitive == 'PLANE':
        verts = ops.create_grid(bm, x_segments=1, y_segments=1, size=1.0)["verts"]
    elif primitive == 'CIRCLE':
        verts = ops.create_circle(bm, cap_ends=True, segments=settings.segments, radius=half)["verts"]
    elif primitive == 'CYLINDER':
        verts = ops.create_cone(bm, cap_ends=True, segments=settings.segments, radius1=half, radius2=half,
                                depth=settings.size)["verts"]
    elif primitive == 'CONE':
        verts = ops.create_cone(bm, cap_ends=True, segments=settings.segments, radius1=half, radius2=0.0,
                                depth=settings.size)["verts"]
    elif primitive == 'TORUS':
        verts = create_torus(bm, settings.major_segments, settings.minor_segments, half * 0.75, half * 0.25)
    elif primitive == MONKEY:
        verts = ops.create_monkey(bm)["verts"]
    else:
        verts = ops.create_grid(bm, x_segments=settings.grid_divisions, y_segments=settings.grid_divisions,
                                size=1.0)["verts"]
    if primitive in FIT_TO_WIDTH:
        fit_width(verts, settings.size)
    return verts


# ---------------------------------------------------------------------------
# Which turns of a primitive mirror exactly
# ---------------------------------------------------------------------------

def turns_90_degrees():
    """The 24 rotations that map the axes onto the axes, unturned first, then the ones with fewest flips."""
    rotations = []
    for order in permutations(range(3)):
        for signs in product((1, -1), repeat=3):
            matrix = Matrix([[signs[row] if order[row] == column else 0 for column in range(3)] for row in range(3)])
            if matrix.determinant() > 0:
                rotations.append(matrix)
    return sorted(rotations, key=lambda matrix: sum(value < 0 for row in matrix for value in row))


ROTATIONS = turns_90_degrees()


def mirrors_exactly(points, axis):
    """True when the points are the same set when mirrored on the plane of `axis` through the origin, and not all
    lying on that plane (a flat shape would just double up)."""
    if all(abs(point[axis]) < FLAT_TOLERANCE for point in points):
        return False
    tree = KDTree(len(points))
    for index, point in enumerate(points):
        tree.insert(point, index)
    tree.balance()
    for point in points:
        mirrored = point.copy()
        mirrored[axis] = -mirrored[axis]
        if tree.find(mirrored)[2] > SYMMETRY_TOLERANCE:
            return False
    return True


@dataclass
class Orientation:
    """One distinct turn of a primitive: its id (position in the analysis), plain name, the rotation matrix and the
    axes (0 X, 1 Y, 2 Z) on which the turned primitive mirrors exactly."""
    key: str
    label: str
    rotation: Matrix
    mirrored_axes: frozenset


def direction_name(rotation, direction):
    """Where `direction` points after the turn, as "+Z" or "-X"."""
    pointing = rotation @ Vector(direction)
    axis = max(range(3), key=lambda index: abs(pointing[index]))
    return f"{'+' if pointing[axis] > 0 else '-'}{AXIS_LETTERS[axis]}"


def orientation_label(primitive, rotation):
    noun, direction = MAIN_DIRECTION[primitive]
    return f"{noun} {direction_name(rotation, direction)}"


def spin_label(primitive, rotation):
    """Tells apart turns whose main direction is the same: where the primitive's top (or side) points."""
    top = (0, 0, 1) if primitive == MONKEY else (1, 0, 0)
    return f"{orientation_label(primitive, rotation)}, {'top' if primitive == MONKEY else 'side'} {direction_name(rotation, top)}"


def point_set_key(points):
    return frozenset(tuple(round(value, 4) + 0.0 for value in point) for point in points)


@lru_cache(maxsize=128)
def analyse(primitive, settings):
    """The distinct turns of the primitive (point sets that differ) with the axes each mirrors exactly."""
    bm = bmesh.new()
    points = [vert.co.copy() for vert in build_primitive(bm, primitive, settings)]
    bm.free()
    seen_sets, distinct = set(), []
    for rotation in ROTATIONS:
        turned = [rotation @ point for point in points]
        point_set = point_set_key(turned)
        if point_set not in seen_sets:
            seen_sets.add(point_set)
            distinct.append((rotation, turned))
    base_labels = [orientation_label(primitive, rotation) for rotation, _turned in distinct]
    orientations, used_labels = [], set()
    for (rotation, turned), base in zip(distinct, base_labels):
        label = spin_label(primitive, rotation) if base_labels.count(base) > 1 else base
        while label in used_labels:
            label += "'"
        used_labels.add(label)
        mirrored_axes = frozenset(axis for axis in range(3) if mirrors_exactly(turned, axis))
        orientations.append(Orientation(str(len(orientations)), label, rotation, mirrored_axes))
    return orientations


def valid_orientations(primitive, settings, axes):
    """The turns on which the primitive mirrors exactly on every one of `axes`. The size never changes the answer,
    so it is left out of the cache key (dragging Size costs nothing)."""
    analysed = analyse(primitive, replace(settings, size=PrimitiveSettings.size))
    return [orientation for orientation in analysed if set(axes) <= orientation.mirrored_axes]


def no_orientation_message(label, primitive, settings, axes):
    letters = "".join(AXIS_LETTERS[axis] for axis in sorted(axes))
    text = f"{label} is not the same mirrored on {letters} in any orientation"
    if primitive in CORNER_COUNT:
        name, noun = CORNER_COUNT[primitive]
        count = getattr(settings, name)
        if count % 2:
            text = f"{label} with {count} {noun} is not the same mirrored on {letters}; use an even count"
    return text


# ---------------------------------------------------------------------------
# The half
# ---------------------------------------------------------------------------

def build_half(primitive, settings, axes, rotation):
    """A new bmesh holding only the + side of the turned primitive on each of `axes` (centre on the origin).
    The caller frees it. A cut may add a loop along the plane."""
    bm = bmesh.new()
    verts = build_primitive(bm, primitive, settings)
    for vert in verts:
        vert.co = rotation @ vert.co
    for axis in axes:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(bm, geom=geom, dist=CUT_DISTANCE, plane_co=Vector(),
                               plane_no=Vector(1 if index == axis else 0 for index in range(3)), clear_inner=True)
    for vert in bm.verts:
        for axis in axes:
            if abs(vert.co[axis]) < CUT_DISTANCE:
                vert.co[axis] = 0.0
    return bm


# ---------------------------------------------------------------------------
# Edit Mode: the planes come from the object's Mirror modifiers
# ---------------------------------------------------------------------------

def mirror_claims(obj):
    """[(MirrorPlanes, axes it supplies)] over the enabled Mirror modifiers in stack order; an axis belongs to the
    first modifier that has it on, so the union of axes is covered once."""
    claimed, claims = set(), []
    for modifier in applicable_mirrors(obj, only_on_cage=False)[0]:
        planes = mirror_planes_of(obj, modifier)
        new_axes = tuple(axis for axis in planes.axes if axis not in claimed)
        if new_axes:
            claims.append((planes, new_axes))
            claimed.update(new_axes)
    return claims


def claimed_axes(claims):
    return tuple(sorted(axis for _planes, axes in claims for axis in axes))


def placement_matrix(obj, claims, cursor_world):
    """Object-local matrix that puts the half at the cursor with the cursor's coordinate on each mirrored axis snapped
    onto its plane, turned like the first claiming modifier's space (the object's, or the Mirror Object's)."""
    snapped = cursor_world.copy()
    for planes, axes in claims:
        to_plane = planes.world_to_plane
        in_plane = to_plane @ snapped
        for axis in axes:
            in_plane[axis] = 0.0
        snapped = to_plane.inverted() @ in_plane
    space = claims[0][0].world_to_plane.inverted()
    return obj.matrix_world.inverted() @ Matrix.Translation(snapped) @ space.to_3x3().to_4x4()


def append_to_edit_mesh(target, source, matrix):
    """Copy `source` (a bmesh) into the Edit Mode bmesh `target` through `matrix`; the copy is the only selection."""
    for element in (*target.verts, *target.edges, *target.faces):
        element.select_set(False)
    new_verts = {vert: target.verts.new(matrix @ vert.co) for vert in source.verts}
    for edge in source.edges:
        if not edge.link_faces:
            target.edges.new([new_verts[vert] for vert in edge.verts]).select_set(True)
    for face in source.faces:
        target.faces.new([new_verts[vert] for vert in face.verts]).select_set(True)
    target.select_flush(True)
    for vert in new_verts.values():
        if not vert.link_edges:
            vert.select_set(True)


def set_mirror_axes(obj, axes):
    modifier = next((mod for mod in obj.modifiers if mod.type == 'MIRROR'), None) or obj.modifiers.new("Mirror", 'MIRROR')
    modifier.use_axis = [axis in axes for axis in range(3)]
    modifier.use_clip = True
    modifier.use_mirror_merge = True


def add_object(context, half, name, axes):
    """A new object at the 3D cursor (world aligned) holding the mesh `half`, with a Mirror modifier on `axes`;
    selected and active."""
    mesh = bpy.data.meshes.new(name)
    half.to_mesh(mesh)
    obj = bpy.data.objects.new(name, mesh)
    obj.location = context.scene.cursor.location
    context.collection.objects.link(obj)
    set_mirror_axes(obj, axes)
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def replace_object_mesh(obj, half, name, axes):
    """Swap the geometry of an object made by `add_object` (same place) and set its Mirror axes."""
    obj.data.clear_geometry()
    half.to_mesh(obj.data)
    obj.name = obj.data.name = name
    set_mirror_axes(obj, axes)


def delete_selected(target):
    bmesh.ops.delete(target, geom=[vert for vert in target.verts if vert.select], context='VERTS')
