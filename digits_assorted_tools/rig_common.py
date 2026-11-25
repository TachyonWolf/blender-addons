# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by the Setups cards (Camera Rig, Lighting Rig, Bounce Cards): finding a rig from the active object
through tag / pointer custom properties (not names, so appended copies work), selecting a part,
and keying with constant interpolation."""

import bpy
from bpy_extras.anim_utils import action_get_channelbag_for_slot


def pointer(root, key):
    """The object stored in root[key], or None."""
    ob = root.get(key)
    return ob if isinstance(ob, bpy.types.Object) else None


def part_title(label, ob, part_tag, root_name=None):
    """The Selected card heading of a rig object: "Light Rig · Key" for a part (its `part_tag` value), "Light Rig"
    for the rig root (or "Camera Rig · Dolly" when the root has a name, `root_name`)."""
    part = ob.get(part_tag) if ob is not None else None
    part = part if isinstance(part, str) and part.lower() != "rig" else root_name
    return f"{label} · {part.title()}" if part else label


def is_active_part(context, part_tag, name, root_tag=None, root_part=None):
    """True when the active object is the rig part `name` (its `part_tag` value; the rig root counts as `root_part`),
    for the pressed state of the Select Part buttons."""
    ob = context.active_object
    if ob is None:
        return False
    value = ob.get(part_tag)
    if value is None and root_tag is not None and ob.get(root_tag) is not None:
        value = root_part
    return isinstance(value, str) and value.lower() == name.lower()


def find_root(context, root_tag, part_tag, parts_of):
    """The rig root of the active object: the object itself if it has root_tag, else the root in
    the scene whose parts_of(root) contains it (only checked for objects with part_tag)."""
    ob = context.active_object
    if ob is None:
        return None
    if ob.get(root_tag) is not None:
        return ob
    if ob.get(part_tag) is None:
        return None
    for candidate in context.scene.objects:
        if candidate.get(root_tag) is not None and ob in parts_of(candidate):
            return candidate
    return None


def select_only(context, ob):
    """Make ob the only selected and the active object; False if it's missing or hidden."""
    if ob is None or not ob.visible_get():
        return False
    for other in context.view_layer.objects:  # not context.selected_objects: may hold removed objects
        if other.select_get():
            other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    return True


def set_key_interpolation(id_data, data_path, frame, interpolation):
    """Set the interpolation of the keys at `frame` on every channel of data_path (all of a vector)."""
    adt = id_data.animation_data
    if adt is None or adt.action is None:
        return
    channelbag = action_get_channelbag_for_slot(adt.action, adt.action_slot)
    if channelbag is None:
        return
    for fcurve in channelbag.fcurves:
        if fcurve.data_path == data_path:
            for key in fcurve.keyframe_points:
                if key.co.x == frame:
                    key.interpolation = interpolation


def set_constant_interpolation(id_data, data_path, frame):
    set_key_interpolation(id_data, data_path, frame, 'CONSTANT')


def define_props(rig, props, stored):
    """(Re)create every slider (a spec prop dict: name, default, min/max, soft range, subtype,
    description) on the rig as an overridable custom property; stored(name, value) converts a
    spec value to what's stored (e.g. degrees to radians)."""
    for p in props:
        name = p["name"]
        rig[name] = stored(name, p["default"])
        ui = rig.id_properties_ui(name)
        if isinstance(p["default"], bool):
            ui.update(description=p["description"])
        else:
            lo, hi, slo, shi = (stored(name, p[k]) if p["subtype"] == "ANGLE" else p[k]
                                for k in ("min", "max", "soft_min", "soft_max"))
            ui.update(min=lo, max=hi, soft_min=slo, soft_max=shi, subtype=p["subtype"],
                      description=p["description"], default=stored(name, p["default"]))
        rig.property_overridable_library_set(f'["{name}"]', True)


def add_scripted_driver(owner, path, index, rig, variables, expression):
    """Drive owner.<path>[index] (index -1: not an array) with an expression of the rig's custom
    properties. variables: {var: prop name | (prop name, array index)}. Returns the driver, so
    callers can add more variables (e.g. distances)."""
    fcurve = owner.driver_add(path, index)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    for var in list(driver.variables):
        driver.variables.remove(var)
    for name, prop in variables.items():
        var = driver.variables.new()
        var.name, var.type = name, 'SINGLE_PROP'
        var.targets[0].id = rig
        prop, i = prop if isinstance(prop, tuple) else (prop, None)
        var.targets[0].data_path = f'["{prop}"]' + ("" if i is None else f"[{i}]")
    driver.expression = expression
    for mod in list(fcurve.modifiers):
        fcurve.modifiers.remove(mod)
    return driver


def append_collection(context, path, asset_name, parent=None):
    """Append the collection `asset_name` from the .blend `path` as real, editable objects (not an
    instance) into `parent` (default the active collection) and return it."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [asset_name]
    coll = dst.collections[0]
    coll.asset_clear()
    (parent or context.collection).children.link(coll)
    return coll


def append_rig(context, path, asset_name, root_tag, parent=None):
    """append_collection for a rig. Returns (collection, rig root: the object with root_tag)."""
    coll = append_collection(context, path, asset_name, parent)
    return coll, next(o for o in coll.all_objects if o.get(root_tag) is not None)
