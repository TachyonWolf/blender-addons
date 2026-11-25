# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop data (no bpy): the shape tiles, style presets, colours, roles, the suggest-from-name rule and the
words the card shows. The card (bone_workshop_ui.py) and the logic (bone_workshop.py) read it; a new tile or preset
is one entry here."""
import re
from collections import namedtuple

from . import rig_names as rn, widget_meshes as wm  # generated copies

Tile = namedtuple('Tile', 'id label widget icon tip')
Preset = namedtuple('Preset', 'id label shape scale colour tip')
Colour = namedtuple('Colour', 'palette name icon')

# Shapes. widget None = made from its options (N-gon, Gear, Capsule: widget_meshes.parametric)
SHAPES = (
    Tile('ring', "Ring", 'WGT-Ring', 'MESH_CIRCLE', "A circle around the bone. The usual control shape"),
    Tile('sphere', "Sphere", 'SelectionSphere', 'MESH_UVSPHERE', "Three circles, like a ball. Good for tweak bones"),
    Tile('cube', "Cube", 'WGT-Cube', 'MESH_CUBE', "A wire box"),
    Tile('ngon', "N-gon", None, 'SEQ_CHROMA_SCOPE', "A flat shape with as many sides as you want (triangle, "
         "diamond, square, hexagon) or a star"),
    Tile('gear', "Gear", None, 'PREFERENCES', "A gear wheel. Good for bones that only hold settings, like IK/FK "
         "switches"),
    Tile('capsule', "Capsule", None, 'MESH_CAPSULE', "A long rounded shape along the bone. Good for fingers, toes "
         "and tail parts"),
    Tile('arrows4', "4 Arrows", wm.FOUR_ARROWS, 'ARROW_LEFTRIGHT', "A ring with four arrows: this bone moves in "
         "any direction. Good for the Root"),
    Tile('arrow', "Arrow", 'WGT-Arrow', 'SORT_DESC', "An arrow along the bone"),
    Tile('line', "Line", 'WGT-Line', 'IPO_LINEAR', "One line along the bone"),
    Tile('cone', "Cone", 'WGT-Cone', 'MESH_CONE', "A wire cone along the bone. Good for look targets"),
    Tile('ico', "Ico", 'WGT-Ico', 'MESH_ICOSPHERE', "A wire ball with flat sides. The face controls use it"),
    Tile('eye', "Socket", 'WGT-EyeSocket', 'HIDE_OFF', "A circle with four grab tabs"),
    Tile('paw', "Paw", 'SelectionPaw', 'VIEW_PAN', "A paw print. The IK hand and foot controls use it"),
    Tile('pointer', "Pointer", 'WGT-SphereDir', 'TRACKER', "A ball with a line that shows where the bone points"),
    Tile('empty', "Empty", 'WGT-SphereEmpty', 'SPHERE', "Three circles like Blender's Sphere empty"),
)
SHAPE_BY_ID = {t.id: t for t in SHAPES}
TILE_COLUMNS = 3   # icon + name buttons: three fit a 280 px sidebar with the names whole
PARAMETRIC_KIND = {'Ngon': 'ngon', 'Star': 'ngon', 'Gear': 'gear', 'Capsule': 'capsule'}
SHAPE_DEFAULTS = dict(sides=6, flat=False, star=False, inner=0.5, teeth=10, depth=0.25, tooth_width=0.5, hole=True,
                      thickness=0.3)


def widget_of(tile_id, options=SHAPE_DEFAULTS):
    """The widget object name a tile gives with these shape options."""
    o = dict(SHAPE_DEFAULTS, **options)
    if tile_id == 'ngon':
        return wm.ngon_name(o['sides'], o['flat'], o['star'], o['inner'])
    if tile_id == 'gear':
        return wm.gear_name(o['teeth'], o['depth'], o['tooth_width'], o['hole'])
    if tile_id == 'capsule':
        return wm.capsule_name(o['thickness'])
    return SHAPE_BY_ID[tile_id].widget


def options_of(widget):
    """(tile id, shape options) read back from a made-from-numbers widget name, else (tile id or None, {})."""
    m = wm.PARAMETRIC.match(widget or "")
    if m is None:
        return next((t.id for t in SHAPES if t.widget == widget), None), {}
    g = m.groups()
    if g[0]:
        return 'ngon', dict(sides=int(g[1]), flat=bool(g[2]), star=False)
    if g[3]:
        return 'ngon', dict(sides=int(g[4]), inner=int(g[5]) / 100, flat=bool(g[6]), star=True)
    if g[7]:
        return 'gear', dict(teeth=int(g[8]), depth=int(g[9]) / 100, tooth_width=int(g[10]) / 100, hole=bool(g[11]))
    if g[12]:
        return 'capsule', dict(thickness=int(g[13]) / 100)
    return 'arrows4', {}


# Colours: Blender's theme bone colour sets (Default = the theme's normal bone colour)
COLOURS = (
    Colour('DEFAULT', "Default", 'RADIOBUT_OFF'), Colour('THEME01', "Red", 'COLORSET_01_VEC'),
    Colour('THEME02', "Orange", 'COLORSET_02_VEC'), Colour('THEME09', "Yellow", 'COLORSET_09_VEC'),
    Colour('THEME03', "Green", 'COLORSET_03_VEC'), Colour('THEME07', "Teal", 'COLORSET_07_VEC'),
    Colour('THEME04', "Blue", 'COLORSET_04_VEC'), Colour('THEME06', "Purple", 'COLORSET_06_VEC'),
    Colour('THEME05', "Pink", 'COLORSET_05_VEC'),
)
COLOUR_NAMES = {c.palette: c.name for c in COLOURS}
BY_SIDE = {'L': 'THEME04', 'R': 'THEME01', '': 'THEME09'}   # By Side: left blue, right red, middle yellow


def palette_icon(palette):
    """The swatch icon of a palette ('THEME12' -> COLORSET_12_VEC), Default's own, or a plain one for CUSTOM."""
    if palette.startswith('THEME'):
        return f"COLORSET_{palette[5:]}_VEC"
    return 'RADIOBUT_OFF' if palette == 'DEFAULT' else 'COLOR'


PRESETS = (
    Preset('fk', "FK Control", ('ring', {}), 1.2, 'THEME03', "A green ring: a bone you turn by hand"),
    Preset('ik', "IK Control", ('paw', {}), 1.0, 'THEME01', "A red paw: the hand or foot control that pulls the limb"),
    Preset('tweak', "Tweak", ('sphere', {}), 0.5, 'THEME04', "A small blue sphere: fine adjustments"),
    Preset('pole', "Pole", ('ngon', dict(sides=4, flat=False)), 0.4, 'THEME01',
           "A small red diamond: where the elbow or knee points"),
    Preset('face', "Face Control", ('ico', {}), 0.6, 'THEME06', "A purple ball: brows, lips and other face controls"),
    Preset('root', "Root", ('arrows4', {}), 2.4, 'THEME09', "Big yellow arrows: moves the whole character"),
)
PRESET_BY_ID = {p.id: p for p in PRESETS}
PRESET_HINT = "A preset sets shape, size, colour and collection in one click."

FACE_PART = re.compile(r'lip|brow|eye|lid|jaw|mouth|cheek|nose|snout|tongue|muzzle|smile|snarl|puff|lash', re.I)


def suggest(name):
    """The preset a bone's name suggests (one name parse, cheap enough for a redraw), or None for helper bones."""
    if rn.is_helper(name):
        return None
    role, part = rn.split_role(name)[0], rn.parse(name).part.lower()
    if part == 'root':
        return 'root'
    if 'pole' in part:
        return 'pole'
    if role == 'IK':
        return 'ik'
    if role == 'TWK' or 'tweak' in part:
        return 'tweak'
    if FACE_PART.search(part):
        return 'face'
    return 'fk'


# Roles (Name & Role). OTHER: a prefix the row has no button for (FK-, TWK-, ORG-, WGT-)
ROLES = (('', "Control", "A bone you pose by hand: no prefix"),
         ('IK', "IK-", "An IK control: it pulls a chain of bones"),
         ('DEF', "DEF-", "A deform bone: it bends the mesh, you don't pose it (turns Deform on)"),
         ('MCH', "MCH-", "A mechanism bone: it does work for the rig, you don't pose it"))
ROLE_IDS = {r[0] for r in ROLES}


def role_of(name):
    """The bone's role id for the Role row: '', 'IK', 'DEF', 'MCH', or 'OTHER' for FK- / TWK- / ORG- / WGT-."""
    role = rn.split_role(name)[0]
    return role if role in ROLE_IDS else 'OTHER'


def with_role(name, role):
    """The name with its role prefix swapped, the rest kept as it is (no standard renaming): 'Hand.L' -> 'IK-Hand.L'."""
    core = rn.split_role(name)[1]
    return f"{role}-{core}" if role else core


# Words. Every hint the card shows (hints can be turned off), short enough for a 280 px sidebar.
HINTS = dict(
    target="Pick what the buttons below change.",
    shape="Shapes are shared: 40 bones with a Ring use one mesh. Edit Shape makes a copy, so other bones don't change.",
    ngon="3 = triangle, 4 + Point = diamond, 4 + Flat = square. Star turns the sides into points.",
    gear="For bones that only hold settings, like the IK_FK switches.",
    capsule="Runs along the bone. For fingers, toes and tail segments.",
    size="Fit to Mesh sizes the shape to the body around the bone, once, when you click. Bones outside the body (IK "
         "controls, poles) keep their size.",
    colour="Pose: only in Pose Mode. Edit: the bone's own colour. Both: one colour everywhere.",
    collections="Click a row to make it the home: the bone leaves its other collections (FK switch collections stay). "
                "Greyed parents can't be a home.",
    deform="Deform bones bend the mesh. Controls don't.",
    name="Standard names (docs/BONE_NAMES.md) let the tools find bones.",
    edit_shape="Edit the shape's vertices, then press Done Editing Shape.",
    try_it="Try It poses the rig to show the setup working; a click puts the pose back.",
    rig_check="Looks for bones with no shape, names off the standard, DEF bones in control collections, left/right "
              "differences and unused shape meshes.",
)
LINKED = "This rig is linked from another file: make it editable first (Make Adjustable)"
OVERRIDE_EDIT = "This rig is a library override: bones can't be changed in Edit Mode. Edit the original file"
OVERRIDE_DATA = "This rig's bones come from a library: change them in the original file"
