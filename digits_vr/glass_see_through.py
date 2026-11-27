# SPDX-License-Identifier: GPL-3.0-or-later
"""Glass made see-through for VR (setting glass_in_vr = See-through): EEVEE raytracing is off in VR, so glass looks
solid; an alpha-blended stand-in looks see-through without it [user, 2026-11-27].
- ONE temporary copy per glass material in use ("VR See-through · <name>"), tagged with a custom property (TAG) that
  holds the original's name and library path, so a leftover is always recognised. The ORIGINAL is never edited.
- The copy: render method Blended, no raytraced refraction; each Principled BSDF's transmission becomes alpha
  (alpha = max(ALPHA_FLOOR, alpha x (1 - transmission)), with Math nodes when either is linked); each Glass /
  Refraction BSDF is mixed with a Transparent BSDF (glass weight ALPHA_FLOOR). The floor keeps glass from going
  invisible [user, 2026-11-27: "a 5-10% floor"].
- Only the object's material SLOTS change: each slot is switched to an object-level link holding the copy (works on
  library overrides whose mesh is linked); slot link and material are recorded first (scene_record kind "slot", in
  the Performance record), so every restore path of perf_state (VR end, save, load, undo, render, Clean up) puts
  them back. The original gets a fake user while swapped (recorded, so a fake user it had stays).
- Objects that can't be swapped (linked, not overridden; glass only inside node groups) are hidden instead
  (perf_state.glass_plan). sync() is a diff: nothing changed, nothing written.
- A render while VR runs would use the copies: the render handlers (vr_changes.py) put the originals back first."""
import json

import bpy

from . import scene_record  # scene_record: generated copy

TAG = "digits_vr_see_through"           # copy's custom property: JSON {"name", "library", "fake_user_added"}
NAME_PREFIX = "VR See-through · "
ALPHA_FLOOR = 0.08                      # glass never drops below 8% opacity [user, 2026-11-27: 5-10%; 8% draft]
GLASS_NODE_TYPES = frozenset({'BSDF_GLASS', 'BSDF_REFRACTION'})
_PYTHON_MATH = {'SUBTRACT': lambda first, second: first - second, 'MULTIPLY': lambda first, second: first * second,
                'MAXIMUM': max}


def _library_path(material):
    return material.library.filepath if material.library is not None else ""


def is_copy(material):
    return material is not None and TAG in material


def _tag(copy):
    try:
        return json.loads(copy[TAG])
    except (TypeError, ValueError):
        return {}


def _materials_by_key():
    return {(material.name, _library_path(material)): material for material in bpy.data.materials}


def original_of(material, index=None):
    """The material a copy stands in for (None when it is gone); any other material is its own original."""
    if not is_copy(material):
        return material
    tag = _tag(material)
    index = _materials_by_key() if index is None else index
    return index.get((tag.get("name"), tag.get("library", "")))


def copies():
    return [material for material in bpy.data.materials if TAG in material]


def flags_memo(material_flags):
    """A glass_detect memo where each copy counts as its original: swapped slots stay on the glass list."""
    index = _materials_by_key()
    memo = {}
    for copy in copies():
        original = original_of(copy, index)
        memo[copy.name_full] = material_flags(original) if original is not None else frozenset()
    return memo


# ---------------------------------------------------------------------------
# The copy's shader: transmission -> alpha
# ---------------------------------------------------------------------------

def _value_or_socket(socket):
    return socket.links[0].from_socket if socket.is_linked else socket.default_value


def _math(tree, operation, first, second):
    """first <operation> second: a number when both are numbers, else a Math node's output socket."""
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return _PYTHON_MATH[operation](first, second)
    node = tree.nodes.new('ShaderNodeMath')
    node.operation = operation
    for socket, operand in zip(node.inputs, (first, second)):
        if isinstance(operand, (int, float)):
            socket.default_value = operand
        else:
            tree.links.new(operand, socket)
    return node.outputs[0]


def _set_input(tree, socket, value):
    for link in list(socket.links):
        tree.links.remove(link)
    if isinstance(value, (int, float)):
        socket.default_value = value
    else:
        tree.links.new(value, socket)


def _principled_glass(node):
    transmission = node.inputs.get("Transmission Weight")
    return (transmission is not None and node.inputs.get("Alpha") is not None and
            (transmission.is_linked or transmission.default_value > 0.0))


def _glass_nodes(tree):
    """(Principled BSDFs with transmission, Glass / Refraction BSDFs wired to something) at the top level."""
    if tree is None:
        return [], []
    principled = [node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED' and _principled_glass(node)]
    glass = [node for node in tree.nodes if node.type in GLASS_NODE_TYPES and node.outputs[0].is_linked]
    return principled, glass


def can_see_through(material):
    """True when a copy of `material` can be made see-through (glass only inside node groups can't)."""
    if material is None or not material.use_nodes:
        return False
    principled, glass = _glass_nodes(material.node_tree)
    return bool(principled or glass)


def _transmission_to_alpha(tree, node):
    transmission, alpha = node.inputs["Transmission Weight"], node.inputs["Alpha"]
    clear = _math(tree, 'SUBTRACT', 1.0, _value_or_socket(transmission))
    opacity = _math(tree, 'MAXIMUM', _math(tree, 'MULTIPLY', _value_or_socket(alpha), clear), ALPHA_FLOOR)
    _set_input(tree, transmission, 0.0)
    _set_input(tree, alpha, opacity)


def _mix_with_transparent(tree, node):
    for link in list(node.outputs[0].links):
        target = link.to_socket
        mix = tree.nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 1.0 - ALPHA_FLOOR
        transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
        tree.links.remove(link)
        tree.links.new(node.outputs[0], mix.inputs[1])
        tree.links.new(transparent.outputs[0], mix.inputs[2])
        tree.links.new(mix.outputs[0], target)


def _make_see_through(copy):
    principled, glass = _glass_nodes(copy.node_tree)
    for node in principled:
        _transmission_to_alpha(copy.node_tree, node)
    for node in glass:
        _mix_with_transparent(copy.node_tree, node)
    copy.surface_render_method = 'BLENDED'
    if hasattr(copy, "use_raytrace_refraction"):
        copy.use_raytrace_refraction = False


def _new_copy(original, fake_user_added):
    copy = original.copy()
    copy.name = NAME_PREFIX + original.name
    copy.use_fake_user = False
    copy[TAG] = json.dumps({"name": original.name, "library": _library_path(original),
                            "fake_user_added": fake_user_added})
    _make_see_through(copy)
    return copy


def can_fake_user(material):
    return material.library is None     # a linked material stays: the linked data still uses it


# ---------------------------------------------------------------------------
# Swapping slots (a diff) and cleaning up
# ---------------------------------------------------------------------------

def sync(owner, key, swaps):
    """Bring the recorded slot swaps to `swaps` [(object, slot indices)]: slots that leave the list get their
    original back, new ones get the copy (made once per original), kept ones are not touched; fake users follow;
    copies no slot uses any more are deleted. Returns how many values were written."""
    index = _materials_by_key()
    wanted = {}
    for ob, slots in swaps:
        for slot_index in slots:
            original = original_of(ob.material_slots[slot_index].material, index)
            if original is not None:
                wanted[(ob.name_full, slot_index)] = (ob, original)
    entries, done, kept = [], 0, set()
    for entry in scene_record.recorded(owner, key):
        if entry[0] != scene_record.SLOT:
            entries.append(entry)
            continue
        place = (entry[2], entry[3][0])
        slot = scene_record.swapped_slot(entry)
        target = wanted.get(place)
        if (target is not None and slot is not None and place not in kept and
                original_of(slot.material, index) == target[1]):
            entries.append(entry)
            kept.add(place)
        elif scene_record.restore_entry(entry):
            done += 1
    scene_record.write_record(owner, key, entries)
    originals = {original.name_full: original for _ob, original in wanted.values()}
    fake_users = [(original, "use_fake_user", True) for original in originals.values() if can_fake_user(original)]
    done += scene_record.sync_values(owner, key, fake_users, "materials")
    by_original = {original_of(copy, index).name_full: copy for copy in copies() if original_of(copy, index) is not None}
    for place, (ob, original) in wanted.items():
        if place in kept:
            continue
        copy = by_original.get(original.name_full)
        if copy is None:
            had_fake_user = scene_record.original_value(owner, key, "materials", original, "use_fake_user")
            copy = by_original[original.name_full] = _new_copy(original, can_fake_user(original) and not had_fake_user)
        scene_record.swap_slot(owner, key, ob, place[1], copy)
        done += 1
    return done + remove_unused()


def remove_unused():
    """Delete the copies nothing uses. Returns how many."""
    unused = [copy for copy in copies() if copy.users == 0]
    for copy in unused:
        bpy.data.materials.remove(copy)
    return len(unused)


def count(owner, key):
    """How many objects show see-through copies (recorded slot swaps)."""
    return len({entry[2] for entry in scene_record.recorded(owner, key) if entry[0] == scene_record.SLOT})


def _data_material(ob, slot_index):
    materials = getattr(ob.data, "materials", None)
    return materials[slot_index] if materials is not None and slot_index < len(materials) else None


def clean_up():
    """After every record is restored: any copy still left (a record lost in a crash) is replaced by its original
    wherever it is used, the slot goes back to a data link when the data holds that same material, a fake user the
    copy's tag says was added is cleared, and the copy is deleted. A copy whose original is gone is kept (deleting it
    would empty its slots). Returns how many copies were removed."""
    index = _materials_by_key()
    removed = 0
    for copy in copies():
        original = original_of(copy, index)
        if original is None:
            print(f"digits_vr: {copy.name!r} kept: its original material is gone")
            continue
        slots = [(ob, slot_index) for ob in bpy.data.objects if ob.is_editable
                 for slot_index, slot in enumerate(ob.material_slots) if slot.link == 'OBJECT' and slot.material == copy]
        copy.user_remap(original)
        for ob, slot_index in slots:
            slot = ob.material_slots[slot_index]
            if _data_material(ob, slot_index) == original:
                slot.material = None
                slot.link = 'DATA'
        if _tag(copy).get("fake_user_added") and original.use_fake_user:
            original.use_fake_user = False
        bpy.data.materials.remove(copy)
        removed += 1
    return removed
