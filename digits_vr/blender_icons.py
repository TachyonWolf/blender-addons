# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender's own UI icons for the VR panels: which icon a row, toggle or glyph shows, its tint, and where it sits in the
atlas `images/blender_icons.png`. Blender builds its icons in from SVGs, so `icon_build/build_blender_icons.py` turns
the ones named here into that atlas (white on alpha, so they can be tinted); `icon_draw.py` draws them.
The icons are Blender's (GPL-3.0-or-later, like Blender). Pure Python (no bpy), tested headless."""
import os

CELL = 64                     # atlas pixels per icon (drawn at ICON_SIZE: one mip level down, sharp)
COLUMNS = 8
ICON_SIZE = 32                # pixels on a panel
ATLAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "blender_icons.png")

# How Blender tints an icon (its UI_icons.hh entry): TEXT = the text colour (DEF_ICON), OBJECT = the theme's object
# icon colour (DEF_ICON_OBJECT), COLLECTION = the theme's collection colour (the `blender_collection` part of a colour icon)
TEXT, OBJECT, COLLECTION = 'TEXT', 'OBJECT', 'COLLECTION'
THEME_TINTS = {OBJECT: "icon_object", COLLECTION: "icon_collection"}     # Preferences > Themes > User Interface
DEFAULT_TINTS = {OBJECT: (225 / 255, 150 / 255, 88 / 255, 1.0), COLLECTION: (1.0, 1.0, 1.0, 1.0)}   # Blender 5.3's theme

# Atlas order (row by row, COLUMNS a row). Add new icons at the end, then run the build script.
ICONS = {
    "OUTLINER_COLLECTION": COLLECTION, "OUTLINER_OB_MESH": OBJECT, "OUTLINER_OB_ARMATURE": OBJECT,
    "OUTLINER_OB_EMPTY": OBJECT, "OUTLINER_OB_CAMERA": OBJECT, "OUTLINER_OB_LIGHT": OBJECT, "OUTLINER_OB_CURVE": OBJECT,
    "OUTLINER_OB_SURFACE": OBJECT, "OUTLINER_OB_FONT": OBJECT, "OUTLINER_OB_CURVES": OBJECT,
    "OUTLINER_OB_GREASEPENCIL": OBJECT, "OUTLINER_OB_LATTICE": OBJECT, "OUTLINER_OB_META": OBJECT,
    "OUTLINER_OB_POINTCLOUD": OBJECT, "OUTLINER_OB_VOLUME": OBJECT, "OUTLINER_OB_SPEAKER": OBJECT,
    "OUTLINER_OB_LIGHTPROBE": OBJECT, "OUTLINER_OB_FORCE_FIELD": OBJECT, "OUTLINER_OB_IMAGE": OBJECT,
    "OUTLINER_OB_GROUP_INSTANCE": OBJECT, "OBJECT_DATA": OBJECT,
    "RESTRICT_SELECT_ON": TEXT, "RESTRICT_SELECT_OFF": TEXT, "CHECKBOX_HLT": TEXT, "CHECKBOX_DEHLT": TEXT,
    "DISCLOSURE_TRI_RIGHT": TEXT, "DISCLOSURE_TRI_DOWN": TEXT, "DOWNARROW_HLT": TEXT, "LOOP_BACK": TEXT,
    "ADD": TEXT, "REMOVE": TEXT, "PINNED": TEXT, "UNPINNED": TEXT, "TRIA_LEFT": TEXT, "TRIA_RIGHT": TEXT,
    "MESH_PLANE": TEXT, "MESH_CUBE": TEXT, "MESH_CIRCLE": TEXT, "MESH_UVSPHERE": TEXT, "MESH_ICOSPHERE": TEXT,
    "MESH_CYLINDER": TEXT, "MESH_CONE": TEXT, "MESH_TORUS": TEXT, "MESH_GRID": TEXT, "MESH_MONKEY": TEXT,
    "TRIA_UP": TEXT, "TRIA_DOWN": TEXT,
}
NAMES = tuple(ICONS)

# Blender's Outliner icon of each object type (interface_icons.cc, `ui_icon_from_object_type`); empties: below
TYPE_ICONS = {'MESH': "OUTLINER_OB_MESH", 'ARMATURE': "OUTLINER_OB_ARMATURE", 'EMPTY': "OUTLINER_OB_EMPTY",
              'CAMERA': "OUTLINER_OB_CAMERA", 'LIGHT': "OUTLINER_OB_LIGHT", 'CURVE': "OUTLINER_OB_CURVE",
              'SURFACE': "OUTLINER_OB_SURFACE", 'FONT': "OUTLINER_OB_FONT", 'CURVES': "OUTLINER_OB_CURVES",
              'GREASEPENCIL': "OUTLINER_OB_GREASEPENCIL", 'LATTICE': "OUTLINER_OB_LATTICE", 'META': "OUTLINER_OB_META",
              'POINTCLOUD': "OUTLINER_OB_POINTCLOUD", 'VOLUME': "OUTLINER_OB_VOLUME", 'SPEAKER': "OUTLINER_OB_SPEAKER",
              'LIGHT_PROBE': "OUTLINER_OB_LIGHTPROBE"}
OTHER = "OBJECT_DATA"
COLLECTION_ICON = "OUTLINER_COLLECTION"

# The Assets page's Primitives list (primitive_shapes.BUILDERS names) shows Blender's Add > Mesh icons
PRIMITIVE_ICONS = {"Plane": "MESH_PLANE", "Cube": "MESH_CUBE", "Circle": "MESH_CIRCLE", "UV Sphere": "MESH_UVSPHERE",
                   "Ico Sphere": "MESH_ICOSPHERE", "Cylinder": "MESH_CYLINDER", "Cone": "MESH_CONE", "Torus": "MESH_TORUS",
                   "Grid": "MESH_GRID", "Monkey": "MESH_MONKEY"}

# A dropdown's caret glyph (Widget.caret) is drawn as Blender's icon
CARET_ICONS = {"▼": "DOWNARROW_HLT", "▸": "DISCLOSURE_TRI_RIGHT", "▾": "DISCLOSURE_TRI_DOWN"}


def object_icon(item):
    """The Outliner icon of an object (anything with Blender's object attributes), as Blender's Outliner picks it."""
    if item.type == 'EMPTY':
        if item.instance_type == 'COLLECTION' and item.instance_collection is not None:
            return "OUTLINER_OB_GROUP_INSTANCE"
        if item.empty_display_type == 'IMAGE':
            return "OUTLINER_OB_IMAGE"
        if item.field is not None and item.field.type != 'NONE':
            return "OUTLINER_OB_FORCE_FIELD"
    return TYPE_ICONS.get(item.type, OTHER)


def lock_icon(locked):
    """The Outliner's selectable toggle (hide_select): the arrow, greyed when it can't be selected."""
    return "RESTRICT_SELECT_ON" if locked else "RESTRICT_SELECT_OFF"


def checkbox_icon(on):
    return "CHECKBOX_HLT" if on else "CHECKBOX_DEHLT"


def pin_icon(pinned):
    return "PINNED" if pinned else "UNPINNED"


def disclosure_icon(opened):
    """The Outliner's fold triangle."""
    return "DISCLOSURE_TRI_DOWN" if opened else "DISCLOSURE_TRI_RIGHT"


def caret_icon(caret):
    """Blender's icon for a dropdown caret glyph ("" when it is not one)."""
    return CARET_ICONS.get(caret, "")


def atlas_size():
    """(width, height) of the atlas in pixels."""
    rows = -(-len(NAMES) // COLUMNS)
    return COLUMNS * CELL, rows * CELL


def cell_origin(name):
    """(x, y) pixel of the icon's top-left corner in the atlas (top-left origin, as the build script lays it out)."""
    index = NAMES.index(name)
    return (index % COLUMNS) * CELL, (index // COLUMNS) * CELL


def uv_rect(name):
    """(u0, v0, u1, v1) of the icon in the atlas texture (GL: v = 0 is the bottom row)."""
    width, height = atlas_size()
    x, y = cell_origin(name)
    return x / width, 1.0 - (y + CELL) / height, (x + CELL) / width, 1.0 - y / height


def tint(name, text_colour, theme=None):
    """The colour Blender draws `name` in: text icons follow `text_colour`; object and collection icons take the theme's
    colour (`theme` = {OBJECT: rgba, COLLECTION: rgba} read from the preferences, else Blender's defaults)."""
    kind = ICONS.get(name, TEXT)
    if kind == TEXT:
        return text_colour
    return (theme or DEFAULT_TINTS).get(kind, DEFAULT_TINTS[kind])
