# SPDX-License-Identifier: GPL-3.0-or-later
"""Bring an asset into the scene when it is dropped in space. Honours the library's import method:
LINK (the file stays the source), APPEND (a local copy), APPEND_REUSE (a local copy that is reused when this asset was
appended before: tagged with a custom property `digits_vr_source`, as Python cannot read Blender's weak reference).

What a drop does, by kind (asset_state.placement):
- Object: a new object at the hand (a linked one becomes a library override so it can be placed).
- Collection: an instance empty of the collection at the hand (the same result a Link drop gives on the desktop).
- Material: on the active object (its active slot, or a new slot). World: the scene's world.
- Node group: a Geometry Nodes modifier on the active object (Digit's Modifiers, Toony Modifiers).
- Primitive (the Primitives list, primitive_shapes): a new mesh object resting on the drop point (Object mode only).
- Anything else, or no place for it (no active object): nothing is imported and the message says why.
The caller (asset_page) wraps one call in one undo step."""
import os

import bpy

from . import asset_cache, character_link, size_state
from .asset_state import (ADD_MODIFIER, APPEND_REUSE, APPLY_MATERIAL, LINK, PLACE_INSTANCE, PLACE_OBJECT, REFUSE,
                          SET_WORLD, placement)
from .primitive_shapes import PRIMITIVE_KIND, make_mesh

SOURCE_KEY = "digits_vr_source"
PRIMITIVE_SIZE = 0.3      # metres: the longest side of a dropped primitive at your size 1.0 (it scales with you)
MESH_LIKE = ('MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME', 'POINTCLOUD', 'CURVES', 'GREASEPENCIL')


def precheck(context, tile):
    """Why this asset can't be placed right now (a sentence), or "" when it can. Checked before anything is loaded."""
    if tile["kind"] == PRIMITIVE_KIND:
        return "" if context.mode == 'OBJECT' else "Primitives can only be added in Object mode"
    how = placement(tile["kind"])
    if how == REFUSE:
        return f"{asset_cache.KIND_LABELS.get(tile['kind'], tile['kind'])} assets have no place in space yet"
    active = context.active_object
    if how == APPLY_MATERIAL and (active is None or active.library or not hasattr(active.data, "materials")):
        return "Select an object first, then drop the material"
    if how == ADD_MODIFIER and (active is None or active.library or active.type not in MESH_LIKE):
        return "Select a mesh or curve object first, then drop the modifier"
    if how == SET_WORLD and context.scene is None:
        return "No scene to set the world on"
    return ""


def _find_reusable(collection, source):
    return next((item for item in collection if item.library is None and item.get(SOURCE_KEY) == source), None)


def load_datablock(tile, library):
    """The datablock of an asset, linked or appended per the library (or reused). (datablock, was_new)."""
    collection = getattr(bpy.data, tile["kind"])
    source = f"{tile['file']}|{tile['name']}"
    if library.method == APPEND_REUSE:
        existing = _find_reusable(collection, source)
        if existing is not None:
            return existing, False
    link = library.method == LINK
    path = os.path.realpath(tile["file"]) if link else tile["file"]      # symlinked library paths break linking
    with bpy.data.libraries.load(path, link=link, relative=link and bool(bpy.data.filepath), assets_only=True) \
            as (source_names, target):
        if tile["name"] not in getattr(source_names, tile["kind"], ()):
            return None, False
        setattr(target, tile["kind"], [tile["name"]])
    datablock = (getattr(target, tile["kind"]) or [None])[0]
    if datablock is not None and not link:
        if datablock.asset_data is not None:
            datablock.asset_clear()       # a plain local copy, like Blender's own append
        datablock[SOURCE_KEY] = source
    return datablock, True


def _select_only(context, ob):
    for other in context.view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob


def _link_to_scene(context, ob, location):
    context.view_layer.active_layer_collection.collection.objects.link(ob)
    ob.location = location
    _select_only(context, ob)


def _place_object(context, datablock, location, library, was_new):
    ob = datablock
    if library.method == LINK:
        _link_to_scene(context, datablock, location)       # an override needs the object in the scene first
        try:
            ob = datablock.override_create(remap_local_usages=True)      # it replaces the linked one in the scene
        except RuntimeError:
            ob = None
        if ob is None:
            return "Linked: it stays where its file puts it (use Append to move it)"
        ob.location = location
        _select_only(context, ob)
        zero_subdivision([ob])
        return ""
    if not was_new:
        ob = datablock.copy()             # reused: a new object sharing the same data
    _link_to_scene(context, ob, location)
    zero_subdivision([ob])
    return ""


def _place_instance(context, datablock, location):
    empty = bpy.data.objects.new(datablock.name, None)
    empty.instance_type = 'COLLECTION'
    empty.instance_collection = datablock
    _link_to_scene(context, empty, location)
    return _make_adjustable(context, empty)


def _make_adjustable(context, ob):
    """A linked drop becomes adjustable at once (Assorted Tools' Make Adjustable: a library override, posable and
    movable), with its viewport subdivision at 0 [user, 2026-11-25]. "" or why it stays linked."""
    if not character_link.needs_override(ob):
        return ""
    try:
        rig = character_link.make_posable(context, ob)
    except (ValueError, RuntimeError) as error:
        return f"stays linked: {error}"
    root = rig.override_library.hierarchy_root if rig.override_library else None
    zero_subdivision([other for other in bpy.data.objects if other.override_library and root is not None
                      and other.override_library.hierarchy_root == root])
    return ""


def zero_subdivision(objects):
    """Viewport subdivision 0 on these objects (render levels untouched) [user: everything comes in at 0]."""
    for ob in objects:
        for modifier in ob.modifiers:
            if modifier.type in {'SUBSURF', 'MULTIRES'}:
                modifier.levels = 0


def _apply_material(context, datablock):
    ob = context.active_object
    if ob.material_slots and 0 <= ob.active_material_index < len(ob.material_slots):
        ob.material_slots[ob.active_material_index].material = datablock
    else:
        ob.data.materials.append(datablock)
    return f"on {ob.name}"


def _add_modifier(context, datablock):
    ob = context.active_object
    if datablock.bl_idname != 'GeometryNodeTree' or not getattr(datablock, "is_modifier", True):
        return None
    modifier = ob.modifiers.new(datablock.name, 'NODES')
    modifier.node_group = datablock
    return f"on {ob.name}"


def _place_primitive(context, tile, location):
    """A new mesh object of the primitive, resting on `location` (its lowest point there), selected and active."""
    ob = bpy.data.objects.new(tile["name"], make_mesh(tile["name"], size_state.scaled(PRIMITIVE_SIZE)))
    _link_to_scene(context, ob, location)
    return ""


def place(context, tile, library, location):
    """Import `tile` and put it in the scene. (done, message). Does not push the undo step."""
    reason = precheck(context, tile)
    if reason:
        return False, reason
    if tile["kind"] == PRIMITIVE_KIND:
        _place_primitive(context, tile, location)
        return True, f"Added {tile['name']}"
    datablock, was_new = load_datablock(tile, library)
    if datablock is None:
        return False, f"{tile['name']} is no longer in its file; scan the libraries again"
    how, detail = placement(tile["kind"]), ""
    if how == PLACE_OBJECT:
        detail = _place_object(context, datablock, location, library, was_new)
    elif how == PLACE_INSTANCE:
        detail = _place_instance(context, datablock, location)
    elif how == APPLY_MATERIAL:
        detail = _apply_material(context, datablock)
    elif how == SET_WORLD:
        context.scene.world = datablock
        detail = "as the scene's world"
    elif how == ADD_MODIFIER:
        detail = _add_modifier(context, datablock)
        if detail is None:
            return False, f"{tile['name']} is not a modifier (no place for it in space yet)"
    return True, detail if detail.startswith("Linked") else f"Added {tile['name']} {detail}".strip()
