# SPDX-License-Identifier: GPL-3.0-or-later
"""The mesh primitives of the Assets page's Primitives list: the catalog (as asset-like tile dicts) and the mesh of
each, built with bmesh at a chosen size and resting on z = 0 (its lowest point). Used by asset_import."""
import math

import bmesh
import bpy
from mathutils import Vector

PRIMITIVE_KIND = "primitives"      # the tile "kind" of a primitive (not a bpy.data collection)
SEGMENTS = 32


def _torus(bm):
    major, minor, rings = 0.35, 0.15, 12
    grid = [[bm.verts.new(((major + minor * math.cos(ring * math.tau / rings)) * math.cos(step * math.tau / SEGMENTS),
                           (major + minor * math.cos(ring * math.tau / rings)) * math.sin(step * math.tau / SEGMENTS),
                           minor * math.sin(ring * math.tau / rings))) for ring in range(rings)] for step in range(SEGMENTS)]
    for step in range(SEGMENTS):
        for ring in range(rings):
            after, below = (step + 1) % SEGMENTS, (ring + 1) % rings
            bm.faces.new((grid[step][ring], grid[after][ring], grid[after][below], grid[step][below]))


BUILDERS = {
    "Plane": lambda bm: bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5),
    "Cube": lambda bm: bmesh.ops.create_cube(bm, size=1.0),
    "Circle": lambda bm: bmesh.ops.create_circle(bm, cap_ends=True, radius=0.5, segments=SEGMENTS),
    "UV Sphere": lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=SEGMENTS, v_segments=16, radius=0.5),
    "Ico Sphere": lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=2, radius=0.5),
    "Cylinder": lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=SEGMENTS, radius1=0.5, radius2=0.5, depth=1.0),
    "Cone": lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=SEGMENTS, radius1=0.5, radius2=0.0, depth=1.0),
    "Torus": _torus,
    "Grid": lambda bm: bmesh.ops.create_grid(bm, x_segments=10, y_segments=10, size=0.5),
    "Monkey": lambda bm: bmesh.ops.create_monkey(bm),
}


def catalog():
    """The primitives as tile dicts (like asset_cache.library_assets gives), in list order."""
    return [{"name": name, "kind": PRIMITIVE_KIND, "file": "", "position": index, "catalog": "", "preview": False,
             "key": f"{PRIMITIVE_KIND}|{name}"} for index, name in enumerate(BUILDERS)]


def make_mesh(name, size):
    """A new mesh of primitive `name`: its longest side is `size` metres, lowest point at z = 0."""
    bm = bmesh.new()
    try:
        BUILDERS[name](bm)
        extent = max(max(vert.co[axis] for vert in bm.verts) - min(vert.co[axis] for vert in bm.verts) for axis in range(3))
        low = min(vert.co.z for vert in bm.verts)
        for vert in bm.verts:
            vert.co = (vert.co - Vector((0.0, 0.0, low))) * (size / extent)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    return mesh
