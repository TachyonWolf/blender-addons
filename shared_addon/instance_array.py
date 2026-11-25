# SPDX-License-Identifier: GPL-3.0-or-later
"""Instance Array: the Digit's Modifiers Geometry Nodes group that works like the built-in Array modifier but keeps the
copies as instances of the object's own mesh (built by Scripts/instance_array/build_instance_array.py). This file is
the one place that knows how to recognise it, load it, and turn an exact built-in Array into it. No UI in here.

Used by the Oops Debugger (Digit's Assorted Tools): its Modifiers on Linked Data section leaves Instance Array out
(instances already share the mesh) and its Convert Arrays button uses convert_arrays. Stacked Arrays convert as a
whole trailing run (see convertible_run); Instance Array copies nest, so the stack stays exact.
"""
import re
from collections import Counter

import bpy

from .modifier_setup import append_group, library_file, set_modifier_input

GROUP_NAME = "Instance Array"
ASSET_FILE = "InstanceArray.blend"          # in the Digit's Modifiers extension's bundled assets
MARKER = "digits_instance_array"            # ID property the builder sets on the node group (survives a rename)
COPY_SUFFIX = re.compile(r"\.\d+$")         # "Instance Array.001" after appending a second copy

# Built-in Array settings -> Instance Array input (socket name). Only these are mapped; the rest must be off (SKIPS).
SETTINGS = (("count", "Count"),
            ("use_relative_offset", "Relative Offset"), ("relative_offset_displace", "Factor"),
            ("use_constant_offset", "Constant Offset"), ("constant_offset_displace", "Distance"),
            ("use_object_offset", "Object Offset"), ("offset_object", "Object"))

SKIPS = {"not_last": "a modifier other than an Array after it", "fit": "Fit Length / Fit Curve", "merge": "Merge on",
         "caps": "has caps", "uv_offset": "UV offsets", "library": "linked from a library"}


def is_instance_array(modifier):
    """True for a Geometry Nodes modifier running the Instance Array group (by its marker, else its name)."""
    group = getattr(modifier, "node_group", None) if modifier.type == 'NODES' else None
    if group is None:
        return False
    return bool(group.get(MARKER)) or COPY_SUFFIX.sub("", group.name) == GROUP_NAME


def available():
    """True when the group can be had: already in this file, or its asset file is in an asset library."""
    return GROUP_NAME in bpy.data.node_groups or library_file(ASSET_FILE) is not None


def load_group():
    """The Instance Array node group: this file's, else appended from the Digit's Modifiers assets (None if missing)."""
    return append_group(GROUP_NAME, library_file(ASSET_FILE))


def own_skip_reason(ob, modifier):
    """Why this built-in Array's own settings cannot become an exact Instance Array (a SKIPS key), or None."""
    if ob.library is not None or ob.override_library is not None:
        return "library"
    if modifier.fit_type != 'FIXED_COUNT':
        return "fit"
    if modifier.use_merge_vertices:
        return "merge"
    if modifier.start_cap is not None or modifier.end_cap is not None:
        return "caps"
    if modifier.offset_u != 0.0 or modifier.offset_v != 0.0:
        return "uv_offset"
    return None


def convertible_run(ob):
    """The built-in Arrays at the end of the stack that can all become Instance Arrays, top to bottom. Any modifier
    after an Array would realize (or ignore) its instances, so only a trailing run of convertible Arrays (Instance
    Arrays already in it are fine) is exact. An Array that can't convert, or any other modifier, ends the run."""
    run = []
    for modifier in reversed(ob.modifiers):
        if is_instance_array(modifier):
            continue
        if modifier.type != 'ARRAY' or own_skip_reason(ob, modifier) is not None:
            break
        run.append(modifier)
    return run[::-1]


def skip_reason(ob, modifier):
    """Why this built-in Array cannot become an exact Instance Array (a SKIPS key), or None when it can."""
    return own_skip_reason(ob, modifier) or (None if modifier in convertible_run(ob) else "not_last")


def arrays_of(objects):
    """(convertible [(object name, Array modifier name)], Counter of skip reason text) over the objects' built-in
    Arrays. Names, not objects: the Oops scan cache keeps this across undo steps."""
    convertible, skipped = [], Counter()
    for ob in objects:
        run = convertible_run(ob)
        for modifier in ob.modifiers:
            if modifier.type != 'ARRAY':
                continue
            if modifier in run:
                convertible.append((ob.name, modifier.name))
            else:
                skipped[SKIPS[own_skip_reason(ob, modifier) or "not_last"]] += 1
    return convertible, skipped


def convert_array(ob, array, group):
    """Replace the built-in `array` on `ob` with an Instance Array modifier of `group`, in the same stack slot, with
    the same name, settings and on/off states. Returns the new modifier."""
    values = {name: getattr(array, setting) for setting, name in SETTINGS}
    values["Factor"], values["Distance"] = tuple(values["Factor"]), tuple(values["Distance"])
    states = (array.name, array.show_viewport, array.show_render, array.show_in_editmode, array.show_expanded)
    index = list(ob.modifiers).index(array)
    ob.modifiers.remove(array)
    modifier = ob.modifiers.new(states[0], 'NODES')
    modifier.node_group = group
    modifier.name = states[0]
    modifier.show_viewport, modifier.show_render, modifier.show_in_editmode, modifier.show_expanded = states[1:]
    for name, value in values.items():
        set_modifier_input(modifier, name, value)
    ob.modifiers.move(len(ob.modifiers) - 1, index)
    ob.update_tag()
    return modifier


def convert_arrays(objects):
    """Turn every exact built-in Array on `objects` into an Instance Array (the group is appended once).
    Returns (converted count, Counter of skip reason text); converts nothing when the group can't be had."""
    convertible, skipped = arrays_of(objects)
    group = load_group() if convertible else None
    if group is None:
        return 0, skipped
    for object_name, modifier_name in convertible:
        ob = bpy.data.objects[object_name]
        convert_array(ob, ob.modifiers[modifier_name], group)
    return len(convertible), skipped
