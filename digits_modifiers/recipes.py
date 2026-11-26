# SPDX-License-Identifier: GPL-3.0-or-later
"""The recipe table: for every modifier the helper can set up, which node group / modifier type,
which helper objects it needs (where, how big, what display), and the settings to start from.
Both UIs (sidebar tab and Add Modifier menu) draw from RECIPES; `run_recipe` is the one place
that turns a recipe into objects. Placement functions take the subject's `Bounds`.

Arrow convention: an empty's local +Z (Single Arrow) points the way the effect works, local X is
the line / axis where a second axis is needed, point-only empties are Plain Axes / Sphere.
"""

import math
import re
from dataclasses import dataclass, replace
from functools import partial
from typing import Callable

import bpy
from mathutils import Matrix, Vector

from .helpers import (WORLD_X, WORLD_Y, WORLD_Z, Bounds, SetupError, at, get_group, get_material,
                      home_collection, make_helper, new_object, option_prop, select_only, style_empty)
from .modifier_setup import (add_after_armature, add_before_armature, empty_curve_data, modifier_input, parent_keep_world, set_first_material_slot, set_modifier_input,
                             set_modifier_value)
from .stretch_setup import setup_stretch_to_curve, setup_stretchy_limb
from . import toony_ui  # generated copy
from .toony_ui import modifier_helpers  # noqa: F401  (generated copy; the helper objects of a modifier)


@dataclass(frozen=True)
class Helper:
    """One helper object a modifier needs. `socket`: the modifier input it fills (GN socket name
    or modifier property); `kind`: empty / plane / sphere / roller / curve (world points) / local_curve (points in the
    subject's space, curve placed on it) / lattice; `place(b)`:
    world matrix (curve: list of points); `size(b)`: display size / side / radius; `bone`: follow
    the active bone of the subject's rig; `parent`: parent to the subject; `select`: selected when done;
    `active`: the active object when done (default: the first selected helper)."""
    socket: str
    suffix: str
    kind: str
    place: Callable
    size: Callable = None
    display: str = 'SINGLE_ARROW'
    parent: bool = True
    bone: bool = False
    wire: bool = False
    select: bool = True
    active: bool = False


@dataclass(frozen=True)
class Option:
    """One choice a recipe offers (drawn by both UIs from this table, stored as a Scene property).
    kind: 'enum' (`items` = (id, label, tip)), 'bool', 'int' (min / max) or 'bone' (a bone name picked
    on the rig). `apply(recipe, value)` returns the recipe changed by the choice (dataclasses.replace);
    options without one are read by the recipe's `setup` instead (the rig recipes' bones)."""
    key: str
    label: str
    kind: str
    default: object = None
    tip: str = ""
    items: tuple = ()
    min: int = 1
    max: int = 10
    apply: Callable = None


@dataclass(frozen=True)
class Recipe:
    """key: operator id; section: Toony / Generate / Blender / Rig; group = (node group, library file) or
    modifier = built-in type; settings = ((name, value or fn(b)), ...) in the modifier's own
    units; owner: 'active' puts the modifier on the active object, 'curve' / 'mesh' on a new
    curve / mesh object (generators, film) with `subject_socket` pointing at the active one;
    extra(context, subject, owner, mod, b, made) -> more objects; setup(context, values) replaces it all
    (rig based recipes: returns active, selected, message); options: the Option rows both UIs offer;
    buttons: (operator id, label, icon) tools for objects already set up, drawn in the sidebar's options card;
    controls: the node group's MAIN inputs (socket names, in drawing order; the first one is the header summary):
    the Selected card draws just these and folds the other value inputs under More, and the node group builders
    (geonodes_common.add_more_panel) put every other value input into a closed "More" panel, so both agree.
    Recipes that add their group through `setup` name it in `controls_group`."""
    key: str
    label: str
    section: str
    tip: str
    icon: str = 'MODIFIER'
    group: tuple = None
    modifier: str = None
    helpers: tuple = ()
    settings: tuple = ()
    owner: str = 'active'
    subject_socket: str = None
    extra: Callable = None
    setup: Callable = None
    options: tuple = ()
    buttons: tuple = ()
    controls: tuple = ()
    controls_group: str = None


# ---------------------------------------------------------------------------
# Placements (world matrices from the subject's bounds)
# ---------------------------------------------------------------------------

def arrow(b):
    return 0.2 * b.size


def beside(b, gap):
    """A point to the +X side of the subject, `gap` x its size off its edge, mid height."""
    return Vector((b.hi.x + gap * b.size, b.centre.y, b.centre.z))


def axis_points(b, count=3):
    """Points along the subject's longest local axis, end to end through its centre."""
    return [b.centre + b.axis_dir * ((i / (count - 1) - 0.5) * b.axis_len) for i in range(count)]


def local_axis_points(b, count=3):
    """Like axis_points, in the subject's local space, along its own origin line (the Curve
    modifier reads the mesh in the curve's space and offsets it from the curve's origin, so the
    curve must sit on the mesh and run through its origin)."""
    centre, dims = b.local_box()
    return [_local_axis(b.axis) * (centre[b.axis] + (i / (count - 1) - 0.5) * dims[b.axis]) for i in range(count)]


def axis_frame(b, location):
    """Frame at `location` with Z along the longest local axis (X along the next local axis)."""
    return at(location, z=b.axis_dir, x=b.rotation @ _local_axis((b.axis + 1) % 3))


def _local_axis(index):
    v = Vector((0, 0, 0))
    v[index] = 1
    return v


def lattice_fit(b):
    """Lattice matrix: the subject's own bounding box (local space), scaled with the subject."""
    centre, dims = b.local_box()
    return b.ob.matrix_world @ Matrix.Translation(centre) @ Matrix.Diagonal((*(max(d, 0.01) / 2 for d in dims), 1))  # lattice space spans -1..1


def selected_indices(ob):
    """Selected vertex indices (edit-mode selection), else all of them."""
    picked = [v.index for v in ob.data.vertices if v.select]
    return picked or [v.index for v in ob.data.vertices]


def hook_point(b):
    ob = b.ob
    indices = selected_indices(ob)
    centre = sum((ob.matrix_world @ ob.data.vertices[i].co for i in indices), Vector()) / len(indices)
    return at(centre)


FOLD_LIFTS = (0.002, 0.004)  # Fold 1 / Fold 2 hinge height above the sheet, x the subject's size: folded flat, a flap lies along its hinge's arrow (at that height)


def fold_matrix(b, sign, lift, standing=False):
    """Fold line `sign` (+1 / -1): a quarter of the length from the middle, X along the line,
    `lift` above the top of the (flat) subject: a higher hinge folds later, with a rounder crease.
    The arrow (+Z) is where the flap goes: over the flap = flat (X rotation -90 degrees),
    straight up = `standing`, folded up 90 degrees so the fold shows right away."""
    d = b.long_horizontal * sign
    length = b.dims.x if b.long_horizontal == WORLD_X else b.dims.y
    point = b.centre + d * length / 4
    point.z = b.hi.z + lift
    return at(point, z=WORLD_Z if standing else d, x=d.cross(WORLD_Z))


# ---------------------------------------------------------------------------
# Extras (what the generic steps can't say)
# ---------------------------------------------------------------------------

def fold_lines(context, subject, owner, mod, b, made, folded=True):
    """Fold 1 and Fold 2 empties in a new 'Fold Lines' collection, set on the modifier.
    Fold 1 starts folded up 90 degrees (so it visibly works; `folded` False = flat), Fold 2 flat, ready
    to turn; Fold 2's hinge sits higher, so it folds second, with a rounder crease."""
    collection = bpy.data.collections.new(f"{subject.name} Fold Lines")
    home_collection(context, subject).children.link(collection)
    lines = []
    for number, sign, lift in ((1, 1, FOLD_LIFTS[0]), (2, -1, FOLD_LIFTS[1])):
        line = new_object(context, f"{subject.name} Fold {number}", None,
                          fold_matrix(b, sign, lift * b.size, standing=folded and number == 1), subject,
                          collection=collection)
        style_empty(line, 'SINGLE_ARROW', 0.3 * b.size)
        lines.append(line)
    set_modifier_value(mod, "Fold Lines", collection)
    return lines


def opening_group(context, subject, owner, mod, b, made):
    """Empty 'Opening' vertex group (paint the rim), set as the Opening Group."""
    if "Opening" not in subject.vertex_groups:
        subject.vertex_groups.new(name="Opening")
    set_modifier_input(mod, "Opening Group", "Opening", attribute=True)


def hook_vertices(context, subject, owner, mod, b, made):
    """Hook the selected vertices (else all) so nothing jumps when the empty is created."""
    mod.vertex_indices_set(selected_indices(subject))
    mod.matrix_inverse = made[0].matrix_world.inverted() @ subject.matrix_world


def curve_tilt(context, subject, owner, mod, b, made):
    """Twist the deform curve so the Curve modifier starts without turning the mesh (Blender's
    curve frame for a straight curve depends on the axis: +X 0, +Y 90, +Z 180 degrees; the Y case is
    only exact for meshes centred on their origin line)."""
    for point in made[0].data.splines[0].bezier_points:
        point.tilt = (0.0, math.pi / 2, math.pi)[b.axis]


def film_material(context, subject, owner, mod, b, made):
    """Vacuum Film as the Film object's first material slot (the film renders with that slot)."""
    set_first_material_slot(owner, get_material("Vacuum Film", "VacuumPack.blend"))


def last_in_stack(context, subject, owner, mod, b, made):
    """Recipe extra: move the new modifier to the end of the stack (Instance Array: a later modifier would realize its copies)."""
    owner.modifiers.move(list(owner.modifiers).index(mod), len(owner.modifiers) - 1)


BUBBLES_REFERENCE_SIZE = 2.0  # m: the character size the Bubbles defaults are made for


def setup_bubbles(context, values):
    """Recipe setup: Bubbles last in the stack with the Bubble material in a new slot; on a rigged mesh
    also Bubbles Rest right before the Armature. Sizes scale with the mesh (a glass gets small, many bubbles)."""
    ob = context.active_object
    if ob is None or ob.type != 'MESH':
        raise SetupError("Select a mesh object first")
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    b = Bounds(ob)
    scale = b.size / BUBBLES_REFERENCE_SIZE
    material = get_material("Bubble", "Bubbles.blend")
    mod = ob.modifiers.new("Bubbles", 'NODES')
    mod.node_group = get_group("Bubbles", "Bubbles.blend")
    set_modifier_input(mod, "Bubble Material", material)
    for name, default in (("Min Radius", 0.003), ("Max Radius", 0.018), ("Surface Gap", 0.005)):
        set_modifier_input(mod, name, b.local(default * scale))
    set_modifier_input(mod, "Density", modifier_input(mod, "Density").value / (scale * b.unit) ** 2)
    if material.name not in ob.data.materials:
        ob.data.materials.append(material)
    made = [ob]
    if any(m.type == 'ARMATURE' for m in ob.modifiers) and not any(
            m.type == 'NODES' and m.node_group and m.node_group.name == "Bubbles Rest" for m in ob.modifiers):
        add_before_armature(ob, get_group("Bubbles Rest", "Bubbles.blend"), "Bubbles Rest")
    ob.update_tag()
    return ob, made, f"Bubbles on {ob.name}: " + " > ".join(m.name for m in ob.modifiers)


def lattice_resolution(count, context, subject, owner, mod, b, made):
    """Lattice points per side (the helper lattice is made with 3)."""
    made[0].data.points_u = made[0].data.points_v = made[0].data.points_w = count


def target_collection(context, subject, owner, mod, b, made):
    """Vacuum Pack on a Target Collection: a new collection holding the subject (drop more meshes in)."""
    collection = bpy.data.collections.new(f"{subject.name} Vacuum Target")
    home_collection(context, subject).children.link(collection)
    collection.objects.link(subject)
    set_modifier_value(mod, "Target Collection", collection)


def displace_texture(context, subject, owner, mod, b, made):
    texture = bpy.data.textures.new(f"{subject.name} Displace", 'CLOUDS')
    texture.noise_scale = 0.5
    mod.texture = texture


def taffy_end(b, end):
    """World point 15 % in from one end (0 = low, 1 = high) of the subject's longest axis."""
    return b.centre + b.axis_dir * ((end - 0.5) * 0.7 * b.axis_len)


def taffy_pairs(context, subject, owner, mod, b, made, bone_a="", bone_b=""):
    """Taffy Pull: hang each grab on its rest empty (grab -> rest -> the mesh), both moved to the picked
    bone's posed head and the rest parented to that bone when one is set (on the rig deforming the subject)."""
    rig = next((m.object for m in subject.modifiers if m.type == 'ARMATURE' and m.object), None)
    rest_a, rest_b, grab_a, grab_b = made
    for rest, grab, bone in ((rest_a, grab_a, bone_a), (rest_b, grab_b, bone_b)):
        if bone and rig and bone in rig.pose.bones:
            spot = rig.matrix_world @ rig.pose.bones[bone].head
            rest.matrix_world.translation = grab.matrix_world.translation = spot
            parent_keep_world(context, rest, rig, bone)
        parent_keep_world(context, grab, rest)


def taffy_objects(ob):
    """[(rest, grab), (rest, grab)] of the Taffy Pull modifiers on `ob` (unset ones skipped)."""
    pairs = []
    for mod in ob.modifiers:
        if mod.type == 'NODES' and mod.node_group and mod.node_group.name.startswith("Taffy Pull"):
            for end in "AB":
                rest, grab = modifier_input(mod, f"Rest {end}").value, modifier_input(mod, f"Grab {end}").value
                if rest and grab:
                    pairs.append((rest, grab))
    return pairs


def taffy_owners(context):
    """Objects with a Taffy Pull modifier that are selected, or whose grab / rest empties are."""
    return list(selected_owners(context, "Taffy Pull"))


def re_rest(context, owners):
    """Make the current pose the unstretched start: move each Taffy Pull rest empty of `owners` onto
    its grab, keeping every grab where it is in the world. Returns how many pairs were re-rested."""
    pairs = [pair for ob in owners for pair in taffy_objects(ob)]
    for rest, grab in pairs:
        world = grab.matrix_world.copy()
        rest.matrix_world.translation = world.translation
        context.view_layer.update()
        grab.matrix_world = world
    context.view_layer.update()
    return len(pairs)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

SIMPLE_DEFORM_MODES = (("BEND", "Bend", "angle", math.radians(45), True), ("TWIST", "Twist", "angle", math.radians(45), False),
                       ("TAPER", "Taper", "factor", 0.5, False), ("STRETCH", "Stretch", "factor", 0.5, False))


def _simple_deform(recipe, method):
    """The Simple Deform recipe set to `method`: origin empty with Z along the longest axis (Bend starts at one end)."""
    _method, label, setting, value, from_end = next(m for m in SIMPLE_DEFORM_MODES if m[0] == method)
    place = (lambda b: axis_frame(b, b.centre - b.axis_dir * b.axis_len / 2)) if from_end else \
            (lambda b: axis_frame(b, b.centre))
    return replace(recipe, helpers=(Helper("origin", f"{label} Origin", 'empty', place, arrow),),
                   settings=(("deform_method", method), ("deform_axis", 'Z'), (setting, value)))


ROLL_MODES = {
    "Ground": dict(helpers=(Helper("Roller", "Roller", 'roller',
                                   lambda b: at(Vector((b.centre.x, b.lo.y - 0.3 * b.dims.z - 0.05 * b.dims.y, b.lo.z + 0.3 * b.dims.z)),
                                                z=WORLD_Y, x=WORLD_X),
                                   lambda b: (0.3 * b.dims.z, 1.3 * b.dims.x), parent=False),),
                   settings=(("Radius", lambda b: b.local(0.3 * b.dims.z)),)),
    "Wringer": dict(helpers=(Helper("Roller", "Wringer", 'roller',
                                    lambda b: at(Vector((b.centre.x, b.lo.y - 0.05 * b.dims.y, b.centre.z)), z=WORLD_Y, x=WORLD_X),
                                    lambda b: (0.2 * b.dims.z, 1.3 * b.dims.x), parent=False),),
                    settings=(("Mode", "Wringer"), ("Radius", lambda b: b.local(0.2 * b.dims.z)))),
}

# Crumple: the Tightness option's How Crumpled values
CRUMPLE_TIGHTNESS = {"Soft": 0.2, "Medium": 0.5, "Tight": 0.9}


def _with_setting(recipe, name, value):
    """The recipe with one more (modifier input, value) setting (for options)."""
    return replace(recipe, settings=recipe.settings + ((name, value),))


# Root / Tip bone options of the recipes that work on a part picked by a bone chain
CHAIN_BONES = (Option("root", "Root bone", 'bone', "", "The part starts at this bone's head"),
               Option("tip", "Tip bone", 'bone', "", "Optional last bone (empty = follow the chain straight on)"))

RECIPES = (
    # --- Toony Modifiers (Geometry Nodes assets) ---
    Recipe("black_hole", "Black Hole", "Toony", "Sucks the mesh into a point empty beside it (its Z is the Twist axis)",
           group=("Black Hole", "BlackHole.blend"), controls=("Suck", "Radius", "Softness", "Twist"),
           helpers=(Helper("Center", "Black Hole Centre", 'empty', lambda b: at(beside(b, 0.3)), arrow, 'SPHERE', bone=True),),
           settings=(("Radius", lambda b: b.local(1.5 * b.size)), ("Suck", 0.5))),
    Recipe("bulge", "Bulge", "Toony", "A lump pushed out around an empty on the front of the mesh",
           group=("Bulge", "Bulge.blend"), controls=("Bulge", "Radius", "Softness"),
           helpers=(Helper("Center", "Bulge Centre", 'empty', lambda b: at(b.front), arrow, 'SPHERE', bone=True),),
           settings=(("Radius", lambda b: b.local(0.2 * b.size)), ("Bulge", lambda b: b.local(0.1 * b.size)))),
    Recipe("crumple", "Crumple", "Toony", "Scrunches a flat mesh (after Press / Roll) into a creased paper ball; the Center empty is the spot that stays on top (move it onto the face)",
           group=("Crumple", "Crumple.blend"), controls=("Progress", "How Crumpled"),
           helpers=(Helper("Center", "Crumple Centre", 'empty', lambda b: at(b.centre), arrow, 'SPHERE'),),
           options=(Option("tightness", "Tightness", 'enum', "Medium",
                           items=tuple((k, k, f"How Crumpled {v}") for k, v in CRUMPLE_TIGHTNESS.items()),
                           apply=lambda r, k: _with_setting(r, "How Crumpled", CRUMPLE_TIGHTNESS[k])),
                    Option("seed", "Seed", 'int', 0, "Another number = other creases", min=0, max=999,
                           apply=lambda r, v: _with_setting(r, "Seed", v)))),
    Recipe("deforming_swirl", "Deforming Swirl", "Toony", "Twists the mesh around an empty at its middle; the arrow is the swirl axis",
           group=("Deforming Swirl", "DeformingSwirl.blend"), controls=("Swirl Amount",),
           helpers=(Helper("Center", "Swirl Centre", 'empty', lambda b: at(b.centre), arrow),),
           settings=(("Swirl Amount", (0.0, 0.0, 90.0)),)),
    Recipe("fold", "Fold", "Toony", "Folds a flattened mesh like paper along two empties in a Fold Lines collection (arrow = where the flap goes; Fold 1 starts folded up 90°, rotate each around its X: R X X; a higher hinge folds later, with more room)",
           group=("Fold", "Fold.blend"), controls=("Progress", "Crease Softness"), extra=fold_lines,
           options=(Option("folded", "Start folded", 'bool', True, "Fold 1 starts folded up 90 degrees so it visibly works; off = both lines flat",
                           apply=lambda r, on: replace(r, extra=partial(fold_lines, folded=on))),)),
    Recipe("hole_squeeze", "Hole Squeeze", "Toony", "Squeezes the mesh through a hole empty beside it; the arrow points into the hole, the way the mesh goes in",
           group=("Hole Squeeze", "HoleSqueeze.blend"), controls=("Strength", "Hole Size", "Range", "Softness"),
           helpers=(Helper("Hole", "Hole", 'empty', lambda b: at(beside(b, 0.6), z=WORLD_X), arrow, bone=True),),
           settings=(("Hole Size", lambda b: b.local(0.15 * b.size)), ("Range", lambda b: b.local(0.8 * b.size)))),
    Recipe("imprint", "Imprint", "Toony", "Skin pushes out over a stand-in object inside the mesh (swap it for a paw, a body...)",
           group=("Imprint", "Imprint.blend"), controls=("Strength", "Thickness", "Tightness"),
           helpers=(Helper("Inside Object", "Inside Object", 'sphere', lambda b: at(b.centre),
                           lambda b: 0.3 * min(b.dims), wire=True),)),
    Recipe("inflate", "Inflate", "Toony", "Puffs the mesh along its normals (no helper objects needed)",
           group=("Inflate", "Inflate.blend"), controls=("Strength", "Edge Softness", "Smooth")),
    Recipe("press", "Press", "Toony", "Flattens the mesh under a plate above it, arrow down (move the plate onto her or key Progress)",
           group=("Press", "Press.blend"), controls=("Progress", "Min Thickness", "Spread"),
           helpers=(Helper("Plate", "Press Plate", 'plane', lambda b: at(b.top + Vector((0, 0, 0.2 * b.dims.z)), z=-WORLD_Z),
                           lambda b: 1.3 * max(b.dims.x, b.dims.y), parent=False),)),
    Recipe("roll", "Roll", "Toony", "Flattens the mesh as a roller passes over it: Ground = a cylinder beside it on the floor (animate it across), Wringer = a roller pair fed 0..1 (the roller marks the gap, just before the mesh)",
           group=("Roll", "Roll.blend"), controls=("Mode", "Radius", "Feed", "Gap"), **ROLL_MODES["Ground"],
           options=(Option("mode", "Mode", 'enum', "Ground", items=(("Ground", "Ground", "A roller rolling over the mesh on the floor"),
                                                                    ("Wringer", "Wringer", "The mesh fed through a roller pair")),
                           apply=lambda r, mode: replace(r, **ROLL_MODES[mode])),)),
    Recipe("roll_up", "Roll Up", "Toony", "Rolls a flat mesh up from an Axis empty at its front end; the arrow lies along the sheet, the way the roll travels",
           group=("Roll Up", "RollUp.blend"), controls=("Progress", "Style", "Direction", "Radius"),
           helpers=(Helper("Axis", "Roll Up Axis", 'empty', lambda b: at(Vector((b.centre.x, b.lo.y, b.lo.z)), z=WORLD_Y, x=WORLD_X), arrow),)),
    Recipe("slice", "Slice", "Toony", "Cuts the mesh into capped pieces along an Axis empty (arrow = cut direction) through its middle",
           group=("Slice", "Slice.blend"), controls=("Cuts", "Spacing", "Gap", "Capped"),
           helpers=(Helper("Axis", "Slice Axis", 'empty', lambda b: axis_frame(b, b.centre), arrow),),
           settings=(("Spacing", lambda b: b.local(b.axis_len / 3)),)),
    Recipe("smear", "Smear", "Toony", "Cartoon smear frames from the rig's animation (then run Scripts/smear/setup_smear.py to make the Ghost)",
           group=("Smear", "Smear.blend"), controls=("Strength", "Speed Threshold", "Max Length")),
    Recipe("smoosh", "Smoosh", "Toony", "Squashes the mesh against a glass plane in front of it (normal toward the camera)",
           group=("Smoosh", "Smoosh.blend"), controls=("Factor", "Offset", "Splat", "Outside"),
           helpers=(Helper("Target", "Glass", 'plane',
                           lambda b: at(Vector((b.centre.x, b.lo.y + 0.15 * b.dims.y, b.centre.z)), z=-WORLD_Y),
                           lambda b: 1.3 * max(b.dims.x, b.dims.z), parent=False),),
           settings=(("Factor", 0.999),)),
    Recipe("squash_stretch", "Squash & Stretch", "Toony", "Squash and stretch about an empty at the feet; the arrow is the squash axis",
           group=("Squash & Stretch", "SquashStretch.blend"), controls=("Amount", "Volume", "Bulge"),
           helpers=(Helper("Axis Object", "Squash Axis", 'empty', lambda b: at(b.base), arrow),)),
    Recipe("stretch_around", "Stretch Around", "Toony", "An opening (paint the Opening vertex group on the rim) stretches around a stand-in object entering it",
           group=("Stretch Around", "StretchAround.blend"), controls=("Clearance", "Stretch Reach", "Softness", "Strength"), extra=opening_group,
           helpers=(Helper("Object", "Passing Object", 'sphere',
                           lambda b: at(Vector((b.centre.x, b.lo.y - 0.2 * b.size, b.lo.z + 0.75 * b.dims.z))),
                           lambda b: 0.1 * b.size, parent=False),
                    Helper("Opening Axis", "Opening Axis", 'empty',
                           lambda b: at(Vector((b.centre.x, b.lo.y, b.lo.z + 0.75 * b.dims.z)), z=WORLD_Y),
                           arrow, bone=True))),
    Recipe("stretch_to_curve", "Stretch To Curve", "Toony", "Bends the whole mesh along a curve made along its longest axis (for a bone chain use the Rig section)",
           group=("Stretch To Curve", "StretchToCurve.blend"), controls=("Progress", "Stretch", "Keep Volume", "Roll"),
           helpers=(Helper("Curve", "Stretch Curve", 'curve', axis_points),),
           settings=(("Axis", lambda b: "+" + "XYZ"[b.axis]),)),
    Recipe("taffy_pull", "Taffy Pull", "Toony", "Stretches the whole mesh like taffy: a Sphere grab on a Plain Axes rest empty near each end of its longest axis (or on two picked bones of its rig); move the grabs (selected, G) away from their rests",
           group=("Taffy Pull", "TaffyPull.blend"), controls=("Progress", "Neck", "Volume", "Grab Radius"), extra=taffy_pairs, buttons=(("digits_modifiers.taffy_re_rest", "Re-rest", 'PIVOT_CURSOR'),),
           helpers=tuple(Helper(f"Rest {name}", f"Taffy Rest {name}", 'empty', partial(lambda end, b: at(taffy_end(b, end)), end),
                                lambda b: 0.05 * b.size, 'PLAIN_AXES', select=False) for end, name in ((0, "A"), (1, "B")))
           + tuple(Helper(f"Grab {name}", f"Taffy Grab {name}", 'empty', partial(lambda end, b: at(taffy_end(b, end)), end),
                          lambda b: 0.08 * b.size, 'SPHERE', active=name == "B") for end, name in ((0, "A"), (1, "B"))),
           settings=(("Grab Radius", lambda b: b.local(0.05 * b.axis_len)),),
           options=(Option("bone_a", "Grab A bone", 'bone', "", "Optional (rigged mesh): Rest A + Grab A start at this bone's head (e.g. a hand)",
                           apply=lambda r, bone: replace(r, extra=partial(r.extra, bone_a=bone))),
                    Option("bone_b", "Grab B bone", 'bone', "", "Optional (rigged mesh): Rest B + Grab B start at this bone's head (e.g. a foot)",
                           apply=lambda r, bone: replace(r, extra=partial(r.extra, bone_b=bone))))),
    Recipe("traveling_bulge", "Traveling Bulge", "Toony", "A lump that travels along a path curve made along the mesh's longest axis (key Position)",
           group=("Traveling Bulge", "TravelingBulge.blend"), controls=("Position", "Radius", "Length", "Bulge"),
           helpers=(Helper("Path", "Bulge Path", 'curve', axis_points),),
           settings=(("Radius", lambda b: b.local(0.2 * sorted(b.dims)[1])), ("Length", lambda b: b.local(0.15 * b.axis_len)))),
    Recipe("vacuum_pack", "Vacuum Pack", "Toony", "A new empty Film object that shrink-wraps this mesh in plastic (modifier lives on the Film, first material slot = Vacuum Film)",
           group=("Vacuum Pack", "VacuumPack.blend"), controls=("Tightness", "Taut", "Wrinkles"), owner='mesh', subject_socket="Target",
           extra=film_material,
           options=(Option("target", "Target", 'enum', "Object", items=(("Object", "Object", "Wrap this mesh"),
                                                                       ("Collection", "Collection", "Wrap a new collection holding this mesh (add more meshes to it)")),
                           apply=lambda r, kind: r if kind == "Object" else replace(
                               r, subject_socket=None, extra=lambda *args: film_material(*args) or target_collection(*args))),)),

    # --- Generate (new geometry; the Add Modifier > Generate menu's name) ---
    Recipe("bubbles", "Bubbles", "Generate", "Air bubbles inside the mesh (slime, jelly, soda, ice, glass): Bubbles last in the stack, the Bubble material in a new slot, sizes scaled to the mesh; on a rigged mesh also Bubbles Rest before the Armature",
           icon='MOD_PARTICLES', setup=setup_bubbles, controls_group="Bubbles",
           controls=("Density", "Min Radius", "Max Radius", "Seed")),
    Recipe("instance_array", "Instance Array", "Generate", "Like Array, but the copies stay instances of the mesh (almost no memory, linked duplicates stay cheap): last in the stack. No Merge, Caps or Fit",
           icon='MOD_ARRAY', group=("Instance Array", "InstanceArray.blend"), extra=last_in_stack,
           controls=("Count", "Relative Offset", "Factor", "Constant Offset", "Distance", "Object Offset", "Object")),

    # --- Built-in Blender modifiers that need helper objects ---
    Recipe("lattice", "Lattice", "Blender", "Lattice fitted to the mesh's bounds (3 x 3 x 3 points)", icon='MOD_LATTICE', modifier='LATTICE',
           helpers=(Helper("object", "Lattice", 'lattice', lattice_fit),),
           options=(Option("resolution", "Points per side", 'int', 3, "Lattice points along each axis", min=2, max=10,
                           apply=lambda r, n: replace(r, extra=partial(lattice_resolution, n))),)),
    Recipe("curve", "Curve", "Blender", "Curve modifier with a curve made along the mesh's longest axis", icon='MOD_CURVE', modifier='CURVE',
           helpers=(Helper("object", "Deform Curve", 'local_curve', local_axis_points),),
           settings=(("deform_axis", lambda b: "POS_" + "XYZ"[b.axis]),), extra=curve_tilt),
    _simple_deform(Recipe("simple_deform", "Simple Deform", "Blender", "Simple Deform with an origin empty; its Z arrow is the deform axis",
                          icon='MOD_SIMPLEDEFORM', modifier='SIMPLE_DEFORM',
                          options=(Option("mode", "Mode", 'enum', "BEND", items=tuple((m[0], m[1], f"Simple Deform: {m[1]}") for m in SIMPLE_DEFORM_MODES),
                                          apply=_simple_deform),)), "BEND"),
    Recipe("cast", "Cast", "Blender", "Cast toward a sphere centred on an empty at the mesh's middle", icon='MOD_CAST', modifier='CAST',
           helpers=(Helper("object", "Cast Centre", 'empty', lambda b: at(b.centre), lambda b: b.size / 2, 'SPHERE'),),
           settings=(("factor", 0.5),)),
    Recipe("hook", "Hook", "Blender", "Hooks the selected vertices (else all) to an empty at their centre", icon='HOOK', modifier='HOOK',
           helpers=(Helper("object", "Hook", 'empty', hook_point, lambda b: 0.15 * b.size, 'PLAIN_AXES'),),
           extra=hook_vertices),
    Recipe("wave", "Wave", "Blender", "Wave rippling out from an empty at the mesh's middle", icon='MOD_WAVE', modifier='WAVE',
           helpers=(Helper("start_position_object", "Wave Origin", 'empty', lambda b: at(b.centre), lambda b: 0.15 * b.size, 'PLAIN_AXES'),),
           settings=(("height", lambda b: b.local(0.04 * b.size)), ("width", lambda b: b.local(0.3 * b.size)),
                     ("falloff_radius", lambda b: b.local(b.size)))),
    Recipe("displace", "Displace", "Blender", "Displace by a new Clouds texture, placed by an empty at the mesh's middle (scale it to scale the noise)",
           icon='MOD_DISPLACE', modifier='DISPLACE', extra=displace_texture,
           helpers=(Helper("texture_coords_object", "Displace Coordinates", 'empty',
                           lambda b: at(b.centre, scale=b.size / 2), None, 'PLAIN_AXES'),),
           settings=(("texture_coords", "OBJECT"), ("strength", lambda b: b.local(0.05 * b.size)))),

    # --- Rig based (bones from the sidebar's Rig card) ---
    Recipe("stretch_to_curve_rig", "Stretch To Curve (chain)", "Rig", "Stretch To Curve on the meshes a rig deforms: Selection + Along groups from a bone chain and a curve along it",
           icon='CURVE_PATH', setup=setup_stretch_to_curve,
           options=CHAIN_BONES),
    Recipe("stretchy_limb", "Stretchy Limb", "Rig", "Stretchy Limb on the meshes a rig deforms: chain groups from Root / Mid / Tip bones and a path along the posed limb",
           icon='CURVE_PATH', setup=setup_stretchy_limb, controls_group="Stretchy Limb", controls=("Stretch", "End Part", "Twist"),
           options=(Option("root", "Root bone", 'bone', "", "Limb starts at this bone's head (upper arm = shoulder)"),
                    Option("mid", "Mid bone", 'bone', "", "Optional: the bend at this bone's head (forearm = elbow)"),
                    Option("tip", "Tip bone", 'bone', "", "Limb ends at this bone's tail (forearm = wrist)"))),
)

RECIPES_BY_KEY = {r.key: r for r in RECIPES}


# ---------------------------------------------------------------------------
# Which Toony modifiers an object has, their main inputs, helpers and owners (for the Selected card)
# ---------------------------------------------------------------------------

COMPANION_CONTROLS = {"Vacuum Squeeze": ("Squeeze",)}   # node groups that are no recipe's own: their main inputs


def group_name(recipe):
    """The node group a recipe adds (setup recipes name it in `controls_group`)."""
    return recipe.group[0] if recipe.group else recipe.controls_group


def base_name(name):
    """A datablock name without Blender's ".001" copy suffix."""
    return re.sub(r"\.\d+$", "", name)


def controls_for(group):
    """The main input names of the node group `group` (base name), None when it is not one of the Toony Modifiers."""
    for recipe in RECIPES:
        if recipe.controls and group_name(recipe) == group:
            return recipe.controls
    return COMPANION_CONTROLS.get(group)


def recipe_of(mod):
    """The recipe a Geometry Nodes modifier came from (matched by node group name), else None."""
    if mod.type != 'NODES' or mod.node_group is None:
        return None
    name = base_name(mod.node_group.name)
    return next((r for r in RECIPES if group_name(r) == name), None)


def recipe_info(mod):
    """toony_ui's hook: this table's knowledge of a modifier (main inputs, tool buttons, subject socket), else None."""
    if mod.type != 'NODES' or mod.node_group is None:
        return None
    controls = controls_for(base_name(mod.node_group.name))
    if controls is None:
        return None
    recipe = recipe_of(mod)
    return toony_ui.Info(controls, recipe.buttons if recipe else (), recipe.subject_socket if recipe else None)


toony_ui.recipe_info = recipe_info


def toony_modifiers(ob, group=None):
    """The Toony Modifiers on `ob` (the Geometry Nodes modifiers of the node groups controls_for knows), in stack order;
    only those of node group `group` when given."""
    found = []
    for mod in ob.modifiers:
        if mod.type == 'NODES' and mod.node_group and controls_for(base_name(mod.node_group.name)) is not None:
            if group is None or base_name(mod.node_group.name) == group:
                found.append(mod)
    return found


def helper_owners(context, group=None):
    """{helper object: the object whose Toony modifier (of node group `group`, if given) uses it} over the scene."""
    found = {}
    for ob in context.scene.objects:
        for mod in toony_modifiers(ob, group):
            for _label, helper in modifier_helpers(mod):
                if helper is not ob:
                    found.setdefault(helper, ob)
    return found


def selected_owners(context, group=None):
    """{owner object: [selected helper objects of it]} for the selection (and the active object): objects with a
    Toony modifier (of node group `group`, if given), and the owners of selected helper empties / curves / plates
    (the active object first in each list)."""
    picked = list(dict.fromkeys([*([context.active_object] if context.active_object else []), *context.selected_objects]))
    owners = {ob: [] for ob in picked if toony_modifiers(ob, group)}
    if picked:
        helper_owner = helper_owners(context, group)
        for ob in picked:
            if ob in helper_owner:
                owners.setdefault(helper_owner[ob], []).append(ob)
    return owners


def owner_of(context, ob):
    """The object whose Toony modifier `ob` is a helper of (a Taffy Pull grab -> its mesh), else None."""
    return helper_owners(context).get(ob)


HELPER_LOOKS = {'SPHERE': "sphere empty", 'SINGLE_ARROW': "arrow empty", 'PLAIN_AXES': "axes empty", 'ARROWS': "axes empty"}
HELPER_KINDS = {'plane': "plane", 'sphere': "sphere", 'roller': "roller", 'curve': "curve", 'local_curve': "curve", 'lattice': "lattice"}


def helper_description(spec):
    """One plain line about a Helper for the Helpers It Makes section: "Taffy Grab B · sphere empty"."""
    look = HELPER_LOOKS.get(spec.display, "empty") if spec.kind == 'empty' else HELPER_KINDS.get(spec.kind, spec.kind)
    return f"{spec.suffix} · {look}"
SECTIONS = (("Toony", "Toony Modifiers"), ("Generate", "Generate"), ("Blender", "Blender Modifiers"), ("Rig", "Rig"))


def recipes_in(section):
    return [r for r in RECIPES if r.section == section]


def default_values(recipe):
    """{option key: default} of a recipe."""
    return {option.key: option.default for option in recipe.options}


def option_values(scene, recipe):
    """{option key: value} of a recipe as the user set it (the Scene properties both UIs edit)."""
    return {option.key: getattr(scene, option_prop(recipe.key, option.key)) for option in recipe.options}


def with_options(recipe, values):
    """The recipe changed by the chosen option values (`values` {key: value}; missing = default)."""
    values = {**default_values(recipe), **(values or {})}
    for option in recipe.options:
        if option.apply:
            recipe = option.apply(recipe, values[option.key])
    return recipe


# ---------------------------------------------------------------------------
# Running a recipe
# ---------------------------------------------------------------------------

def _add_modifier(owner, recipe):
    group = get_group(*recipe.group) if recipe.group else None
    return add_after_armature(owner, group, recipe.label, recipe.group[0] if group else None,
                              recipe.modifier or 'NODES')


def _new_owner(context, recipe, subject, b):
    name = f"{subject.name} {recipe.label}"
    data = empty_curve_data(name) if recipe.owner == 'curve' else bpy.data.meshes.new(name)
    return new_object(context, name, data, Matrix.Translation(b.base), subject, parent=False)


def run_recipe(context, recipe, values=None):
    """Do one recipe with its option `values` ({key: value}, default = each option's default).
    Returns (active object, selected objects, message); raises SetupError."""
    values = {**default_values(recipe), **(values or {})}
    if recipe.setup:
        active, selected, message = recipe.setup(context, values)
        select_only(context, selected, active)
        return active, selected, message
    recipe = with_options(recipe, values)
    subject = context.active_object
    if subject is None or subject.type != 'MESH':
        raise SetupError("Select a mesh object first")
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    b = Bounds(subject)
    owner = subject if recipe.owner == 'active' else _new_owner(context, recipe, subject, b)
    mod = _add_modifier(owner, recipe)
    made = [make_helper(context, spec, subject, b) for spec in recipe.helpers]
    for spec, ob in zip(recipe.helpers, made):
        set_modifier_value(mod, spec.socket, ob)
    if recipe.subject_socket:
        set_modifier_value(mod, recipe.subject_socket, subject)
    for name, value in recipe.settings:
        set_modifier_value(mod, name, value(b) if callable(value) else value)
    made += recipe.extra(context, subject, owner, mod, b, made) or [] if recipe.extra else []
    owner.update_tag()
    new_owner = owner is not subject
    shown = [ob for spec, ob in zip(recipe.helpers, made) if spec.select] + made[len(recipe.helpers):]
    selected = ([owner] if new_owner else []) + shown if (shown or new_owner) else [subject]
    active = owner if new_owner or not shown else next(
        (ob for spec, ob in zip(recipe.helpers, made) if spec.active), shown[0])
    select_only(context, selected, active)
    names = ", ".join(ob.name for ob in made) or "no helper objects needed"
    return active, selected, f"{recipe.label} on {owner.name}: {names}"
