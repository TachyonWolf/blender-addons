# SPDX-License-Identifier: GPL-3.0-or-later
"""The ONE adapter between this process and Decals: decal_api.create_decal of Digit's Assorted Tools,
create_decal(maps={ROLE: image path}, name, location=(x, y, z), size=long side in metres, context=...) -> an
Unattached decal (attach it later from the Selected card). Roles are decal_maps.ROLES ids (COLOR, NORMAL, GLOW,
ROUGHNESS, METAL, ALPHA, HEIGHT); COLOR is required. `facing` (a world axis, or a 3-vector for Custom) and `flip` are create_decal's too. Without decal_api (an older Digit's Assorted Tools) the
tickbox shows UNAVAILABLE_TEXT and the step is skipped with a note.
"""
from mathutils import Vector

from .. import assorted_tools

DECAL_MODULE = "decal_api"
DECAL_FUNCTION = "create_decal"
UNAVAILABLE_TEXT = "Decals not available yet"
CUSTOM = "CUSTOM"     # the Facing item that uses the vector
FRONT_FACING = "-Y"   # the studio photographs the front from -Y
FACING_ITEMS = [
    ("-Y", "-Y Front", "Faces -Y, like the front photo"),
    ("+Y", "+Y", "Faces +Y"),
    ("+X", "+X", "Faces +X"),
    ("-X", "-X", "Faces -X"),
    ("+Z", "+Z Up", "Lies flat, facing up"),
    ("-Z", "-Z Down", "Lies flat, facing down"),
    (CUSTOM, "Custom", "Faces the direction set with the Direction ball or the arrow in the viewport. Only the decal "
     "turns: the photo stays the studio's front (and back) shot"),
]
DEFAULT_CUSTOM = (0.0, -1.0, 0.0)   # the Custom direction before anyone sets it


def custom_vector(vector):
    """A unit Vector from the Custom property's 3 numbers (-Y when they are all zero)."""
    vector = Vector(vector)
    return vector.normalized() if vector.length > 1e-6 else Vector(DEFAULT_CUSTOM)


def resolved(facing, vector=DEFAULT_CUSTOM):
    """What create_decal gets: the axis name, or for Custom the unit vector (as a tuple)."""
    return tuple(custom_vector(vector)) if facing == CUSTOM else facing


def opposite(facing):
    """What a Back shot's decal faces: "-Y" -> "+Y"; a vector -> its negative."""
    if not isinstance(facing, str):
        return tuple(-component for component in facing)
    return ("+" if facing.startswith("-") else "-") + facing[1:]


def normal_of(facing):
    """The unit Vector a resolved `facing` points along."""
    if isinstance(facing, str):
        return {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}[
            facing.lstrip("+-")] * (-1 if facing.startswith("-") else 1)
    return Vector(facing)


def facing_text(facing):
    return facing if isinstance(facing, str) else "(" + ", ".join(f"{c:.2f}" for c in facing) + ")"


def create_function(context=None):
    """decal_api.create_decal, or None while Digit's Assorted Tools has no Decals."""
    return getattr(assorted_tools.optional_module(DECAL_MODULE, context), DECAL_FUNCTION, None)


def is_available(context=None):
    return create_function(context) is not None


def add_decal(maps_by_role, name, location, size, context=None, facing=FRONT_FACING, flip=False, shading="LIT",
              back_maps=None):
    """An Unattached decal from {role: image path} at `location` facing the world axis `facing`; `size` =
    (width, height) metres of the shot; `flip` mirrors it left to right; `shading` "LIT" or "UNLIT" (baked light);
    `back_maps` {role: image path} of the back shot, shown from behind on the same decal.
    Returns (decal or None, note)."""
    function = create_function(context)
    if function is None:
        return None, f"Decal skipped: {UNAVAILABLE_TEXT} (the images are saved)"
    if "COLOR" not in maps_by_role:
        return None, "Decal skipped: it needs a colour map (tick one in Custom)"
    decal = function(maps_by_role, name, location=tuple(location), size=max(size), context=context, facing=facing,
                     flip=flip, shading=shading, **({"back_maps": back_maps} if back_maps else {}))
    return decal, f"Decal '{decal.name}' added beside the target (facing {facing_text(facing)}), not attached yet"
