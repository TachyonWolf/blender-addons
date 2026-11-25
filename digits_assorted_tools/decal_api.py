# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the small, stable Python API other tools use (e.g. Digit's Processes making decals from Texture Studio
captures). No UI, no ray casts. Everything here calls decal_mesh / decal_material; no logic of its own.

    from digits_assorted_tools import decal_api
    decal = decal_api.create_decal({"COLOR": "/path/logo_color.png", "NORMAL": "/path/logo_normal.png"},
                                   "logo", location=(0, 0, 1), size=0.1)       # Unattached
    decal_api.attach(decal, target, point, normal)                               # Placing on target
    decal_api.stick(decal)                                                       # Stuck (returns warnings)
    decal_api.detach(decal)                                                      # Unattached again

Roles: decal_maps.ROLES ids (COLOR, NORMAL, GLOW, ROUGHNESS, METAL, ALPHA, HEIGHT); COLOR is required."""

import bpy

from . import decal_maps, decal_material, decal_mesh
from .decal_recipe import PLACING, STUCK, UNATTACHED  # noqa: F401  (re-exported state ids)

ROLE_IDS = tuple(role for role, _label in decal_maps.ROLES)


SHADINGS = ("LIT", "UNLIT")


def create_decal(maps, name, location=(0.0, 0.0, 0.0), size=0.1, collection=None, context=None, facing="Z",
                 flip=False, shading="LIT", back_maps=None):
    """A new Unattached decal from {role: image file path}: flat, real size (long side `size` metres), at world
    `location`, facing the world axis `facing` ("Z" = up, the default; "-Y", "+X", ...; or any non-zero 3-vector; image up is world Z, or
    Y when facing up or down), image mirrored left to right with `flip`, named `Decal.<name>`. `shading` "LIT"
    (default: lit by the scene) or "UNLIT" (the colour shown as it is: for baked-lighting / photo map sets).
    `back_maps` (optional, {role: path} like `maps`, COLOR needed): the same decal shows them from behind
    (Backfacing), one object for a front + back shot. Give the back shot as captured from behind and mirrored to
    line up with the front (Texture Studio's Front + Back): seen from behind it reads the right way round.
    Returns the object. Raises ValueError without a COLOR map, with an unknown role or shading."""
    for each in (maps, back_maps):
        unknown = set(each or {}) - set(ROLE_IDS)
        if each is not None and (unknown or "COLOR" not in each):
            raise ValueError(f"decal maps need COLOR and roles from {ROLE_IDS}; got {sorted(each)}")
    shading = shading.upper()
    if shading not in SHADINGS:
        raise ValueError(f"decal shading must be one of {SHADINGS}; got {shading!r}")
    context = context or bpy.context
    maps = {**maps, **{decal_maps.back_role(role): path for role, path in (back_maps or {}).items()}}
    images = {role: decal_material.load_image(bpy.path.abspath(path), role) for role, path in maps.items()}
    return decal_mesh.new_decal(context, images, name, size, location, collection, facing, flip, shading)


def attach(decal, target, point, normal, up=None, context=None):
    """Put the decal on `target` at world `point` / surface `normal` (Placing: slides, re-projected)."""
    decal_mesh.attach(context or bpy.context, decal, target, point, normal, up)


def detach(decal):
    """Take the decal off its target: a flat Unattached decal where it is now."""
    decal_mesh.detach(decal)


def stick(decal, context=None):
    """Placing > Stuck (follows rig / shape keys). Returns a list of warning texts (empty = fine)."""
    return decal_mesh.stick(context or bpy.context, decal)


def unstick(decal):
    """Stuck > Placing."""
    decal_mesh.unstick(decal)


def state(decal):
    """UNATTACHED, PLACING or STUCK; None for an object that is not a decal."""
    return decal.digit_decal.state if decal_mesh.is_decal(decal) else None
