# SPDX-License-Identifier: GPL-3.0-or-later
"""What the VR view can hide (the Display tab). Pure Python (no bpy). Each item is a VR-only setting of
`wm.xr_session_settings` (`attr`) and the object types it covers (what picking must skip while it is hidden).
The user's choice is the list of HIDDEN keys (`display_hidden` in settings.json): empty = everything shows."""
from collections import namedtuple

Item = namedtuple("Item", "key label attr types more")

_VIEWPORT = "show_object_viewport_"
ITEMS = (
    Item("armature", "Bones", _VIEWPORT + "armature", ("ARMATURE",), False),
    Item("camera", "Cameras", _VIEWPORT + "camera", ("CAMERA",), False),
    Item("light", "Lights", _VIEWPORT + "light", ("LIGHT",), False),
    Item("empty", "Empties", _VIEWPORT + "empty", ("EMPTY",), False),
    Item("extras", "Extras (wires)", "show_object_extras", ("CAMERA", "LIGHT", "EMPTY"), False),   # camera / light / empty wires
    Item("floor", "Floor", "show_floor", (), False),
    Item("annotation", "Annotations", "show_annotation", (), False),
    Item("mesh", "Meshes", _VIEWPORT + "mesh", ("MESH",), True),
    Item("curve", "Curves", _VIEWPORT + "curve", ("CURVE",), True),
    Item("surf", "Surfaces", _VIEWPORT + "surf", ("SURFACE",), True),
    Item("font", "Text", _VIEWPORT + "font", ("FONT",), True),
    Item("meta", "Metaballs", _VIEWPORT + "meta", ("META",), True),
    Item("curves", "Hair", _VIEWPORT + "curves", ("CURVES",), True),
    Item("pointcloud", "Point clouds", _VIEWPORT + "pointcloud", ("POINTCLOUD",), True),
    Item("volume", "Volumes", _VIEWPORT + "volume", ("VOLUME",), True),
    Item("grease_pencil", "Grease Pencil", _VIEWPORT + "grease_pencil", ("GREASEPENCIL",), True),
    Item("light_probe", "Light probes", _VIEWPORT + "light_probe", ("LIGHT_PROBE",), True),
    Item("lattice", "Lattices", _VIEWPORT + "lattice", ("LATTICE",), True),
    Item("speaker", "Speakers", _VIEWPORT + "speaker", ("SPEAKER",), True),
)
KEYS = tuple(item.key for item in ITEMS)
MAIN = tuple(item for item in ITEMS if not item.more)
MORE = tuple(item for item in ITEMS if item.more)
MESH_WARNING = "Meshes off hides every mesh, even the ones you work on"


def valid_hidden(value):
    return isinstance(value, list) and all(key in KEYS for key in value) and len(set(value)) == len(value)


def toggled(hidden, key):
    """The hidden list after pressing `key` (in table order, so the saved file is stable)."""
    chosen = set(hidden) ^ {key}
    return [item_key for item_key in KEYS if item_key in chosen]


def hides_type(hidden, object_type):
    """True when the Display choices hide objects of this Blender type (picking skips them)."""
    return any(object_type in item.types for item in ITEMS if item.key in hidden)
