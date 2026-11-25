# SPDX-License-Identifier: GPL-3.0-or-later
"""Path generators (Digit's Tools > Object > Path Generators, and the 3D View Add menu): the Geometry Nodes generator
modifiers that make a path for other modifiers to use (Stretch To Curve, Traveling Bulge, Skin, Wireframe...). ONE
table, GENERATORS. No bpy in here: the node group builders in Scripts/ read `controls_for` too (geonodes_common).

Each generator's node group lives in this extension's `assets/` folder (built by Scripts/<builder>/)."""
from collections import namedtuple

# key: operator enum id; label: the Add menu entry and the new object's name; group: the node group (and modifier
# name); object_type: 'CURVE' or 'MESH' (the object that carries the modifier, its own data stays empty);
# add_menu: the Blender Add menu it sits in; controls: the main inputs (the rest go in the group's closed More panel).
Generator = namedtuple("Generator", "key label group asset_file object_type add_menu icon controls description")

GENERATORS = (
    Generator("SPIRAL", "Spiral Curve", "Spiral Curve", "SpiralCurve.blend", 'CURVE', "VIEW3D_MT_curve_add", 'MOD_SCREW',
              ("Shape", "Turns", "Height", "Progress"),
              "A curve object coiled into a flat spiral, helix or cone, or around an Object (a path for Stretch To "
              "Curve, Traveling Bulge...)"),
    Generator("KNOT", "Knot Curve", "Curve to Knot", "CurveToKnot.blend", 'CURVE', "VIEW3D_MT_curve_add", 'CURVE_BEZCURVE',
              ("Knot", "Length", "Progress", "Tightness"),
              "A curve object tied in a knot of exact length (a path for Stretch To Curve)"),
    Generator("MAZE", "Maze", "Maze", "Maze.blend", 'MESH', "VIEW3D_MT_mesh_add", 'MESH_GRID',
              ("Width", "Height", "Seed", "Braid", "Output"),
              "A mesh of points and edges only (no faces) laid out as a maze: its passages (or walls). Add Skin, "
              "Wireframe or Geometry Nodes after it to give it thickness"),
)

BY_KEY = {generator.key: generator for generator in GENERATORS}
BY_GROUP = {generator.group: generator for generator in GENERATORS}


def controls_for(group):
    """The main input names of the node group `group` (base name), None when it is no path generator."""
    generator = BY_GROUP.get(group)
    return generator.controls if generator else None


def enum_items():
    return [(generator.key, generator.label, generator.description, generator.icon, index)
            for index, generator in enumerate(GENERATORS)]
