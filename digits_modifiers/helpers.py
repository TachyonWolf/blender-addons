# SPDX-License-Identifier: GPL-3.0-or-later
"""Placing helper objects (empties, plates, rollers, curves, lattices) around a subject object.

`Bounds` says where the subject is; the `*_at` / `at` functions build world matrices; `make_helper`
turns a recipe's Helper spec into a real, named, parented object. Arrow convention for empties:
local +Z (Single Arrow display) points the way the effect works, local X is the line / axis where a
second axis is needed, point-only empties use Plain Axes / Sphere.
"""

import bmesh
import bpy
from mathutils import Matrix, Vector

from .object_tools import select_only  # generated copy
from .modifier_setup import append_group, append_material, library_file, make_path_curve, parent_keep_world, style_helper

WORLD_X, WORLD_Y, WORLD_Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))


class SetupError(Exception):
    """A recipe can't run (nothing selected, group missing...); the message is shown to the user."""


class Bounds:
    """Where a subject object is, in world space. The character stands on world Z and faces -Y.
    `axis` is the subject's longest local axis (0, 1, 2) with `axis_dir` its world direction and
    `axis_len` the world length along it; `unit` converts world lengths to the object's local
    units (modifier distances are local)."""

    def __init__(self, ob):
        self.ob = ob
        corners = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        self.lo = Vector(min(c[i] for c in corners) for i in range(3))
        self.hi = Vector(max(c[i] for c in corners) for i in range(3))
        if (self.hi - self.lo).length < 1e-6:  # nothing to measure: a 1 m box around the origin
            self.lo, self.hi = ob.matrix_world.translation - Vector((.5, .5, .5)), ob.matrix_world.translation + Vector((.5, .5, .5))
        self.dims = self.hi - self.lo
        self.centre = (self.lo + self.hi) / 2
        self.size = max(self.dims)
        scale = ob.matrix_world.to_scale()
        self.unit = 1 / max(sum(abs(s) for s in scale) / 3, 1e-6)
        local = tuple(ob.dimensions) if max(ob.dimensions) > 1e-6 else (1, 1, 1)
        self.axis = max(range(3), key=lambda i: local[i])
        self.axis_len = local[self.axis]
        rotation = ob.matrix_world.to_quaternion().to_matrix()
        self.axis_dir = (rotation @ _unit(self.axis)).normalized()
        self.rotation = rotation

    @property
    def base(self):
        return Vector((self.centre.x, self.centre.y, self.lo.z))

    @property
    def top(self):
        return Vector((self.centre.x, self.centre.y, self.hi.z))

    @property
    def front(self):
        """Middle of the face towards the camera (-Y)."""
        return Vector((self.centre.x, self.lo.y, self.centre.z))

    @property
    def long_horizontal(self):
        """World X or Y, whichever the subject is longer along."""
        return WORLD_X if self.dims.x >= self.dims.y else WORLD_Y

    def local(self, length):
        """A world length in the subject's local units."""
        return length * self.unit

    def local_box(self):
        """(centre, dimensions) of the subject's own bounding box in its local space."""
        pts = [Vector(c) for c in self.ob.bound_box]
        lo = Vector(min(p[i] for p in pts) for i in range(3))
        hi = Vector(max(p[i] for p in pts) for i in range(3))
        return (lo + hi) / 2, hi - lo


def _unit(axis):
    v = Vector((0, 0, 0))
    v[axis] = 1
    return v


def at(location, z=WORLD_Z, x=None, scale=1.0):
    """World matrix at `location` whose local +Z points along `z` and whose local X is as close
    to `x` as that allows (default world X, or world Y when Z is along X)."""
    z = Vector(z).normalized()
    x = Vector(x) if x is not None else WORLD_X.copy()
    x = x - z * x.dot(z)
    if x.length < 1e-6:
        x = WORLD_Y - z * WORLD_Y.dot(z)
    x.normalize()
    y = z.cross(x)
    m = Matrix((x * scale, y * scale, z * scale)).transposed().to_4x4()
    m.translation = location
    return m


def active_bone(subject):
    """(rig, bone name) of the active bone of the armature deforming `subject`, else None."""
    for mod in subject.modifiers:
        if mod.type == 'ARMATURE' and mod.object and mod.object.data.bones.active:
            return mod.object, mod.object.data.bones.active.name
    return None


# ---------------------------------------------------------------------------
# Making the objects
# ---------------------------------------------------------------------------

def _mesh_from_bmesh(name, build):
    bm = bmesh.new()
    build(bm)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def plane_mesh(name, side):
    return _mesh_from_bmesh(name, lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=side / 2))


def sphere_mesh(name, radius):
    return _mesh_from_bmesh(name, lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=radius))


def roller_mesh(name, radius, length):
    """Cylinder whose axis is the local X axis (Roll's default Roller Axis)."""
    def build(bm):
        bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=radius, radius2=radius, depth=length)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(1.5707963, 3, 'Y'))
    return _mesh_from_bmesh(name, build)


def lattice_data(name):
    lattice = bpy.data.lattices.new(name)
    lattice.points_u = lattice.points_v = lattice.points_w = 3
    return lattice


def home_collection(context, subject):
    """The collection new helpers go in: the subject's first one, else the scene's."""
    return subject.users_collection[0] if subject.users_collection else context.scene.collection


def new_object(context, name, data, matrix, subject, parent=True, bone=None, collection=None):
    """Object `name` with `data` at world `matrix`, linked next to the subject (or into
    `collection`), optionally parented to it (or to a bone of its rig) without moving."""
    ob = bpy.data.objects.new(name, data)
    (collection or home_collection(context, subject)).objects.link(ob)
    ob.matrix_world = matrix
    if bone:
        parent_keep_world(context, ob, bone[0], bone[1])
    elif parent:
        parent_keep_world(context, ob, subject)
    return ob


def style_empty(ob, display, size):
    ob.empty_display_type = display
    ob.empty_display_size = size


def make_helper(context, spec, subject, b):
    """The object a recipe's Helper `spec` describes, made for `subject` (bounds `b`)."""
    name = f"{subject.name} {spec.suffix}"
    where = spec.place(b)
    bone = active_bone(subject) if spec.bone else None
    size = spec.size(b) if spec.size else 1.0
    if spec.kind in ('curve', 'local_curve'):
        ob = make_path_curve(context, None, where, name, collection=home_collection(context, subject))
        if spec.kind == 'local_curve':  # points are in the subject's space: the curve sits on it
            ob.matrix_world = subject.matrix_world
        if spec.parent:
            parent_keep_world(context, ob, subject)
        return ob
    if bone:  # follow the bone: same orientation, at its posed head
        where = where.copy()
        where.translation = bone[0].matrix_world @ bone[0].pose.bones[bone[1]].head
    data = {'empty': lambda: None,
            'plane': lambda: plane_mesh(name, size),
            'sphere': lambda: sphere_mesh(name, size),
            'roller': lambda: roller_mesh(name, *size),
            'lattice': lambda: lattice_data(name)}[spec.kind]()
    ob = new_object(context, name, data, where, subject, spec.parent, bone)
    if spec.kind == 'empty':
        style_empty(ob, spec.display, size)
    elif spec.kind == 'lattice':
        ob.show_in_front = True
    if spec.wire:
        style_helper(ob)
    return ob


def option_prop(recipe_key, option_key):
    """Name of the Scene property that stores a recipe option (the sidebar and the popup edit it)."""
    return f"modhelp_{recipe_key}_{option_key}"


def get_group(name, filename):
    """Node group `name` (already in this file, else appended from `filename`: the bundled assets, then the asset libraries)."""
    group = append_group(name, library_file(filename))
    if group is None:
        raise SetupError(f"'{name}' not found: {filename} is missing from the extension's assets and from your asset libraries")
    return group


def get_material(name, filename):
    """Material `name` (already in this file, else appended from `filename`: the bundled assets, then the asset libraries)."""
    material = append_material(name, library_file(filename))
    if material is None:
        raise SetupError(f"'{name}' not found: {filename} is missing from the extension's assets and from your asset libraries")
    return material
