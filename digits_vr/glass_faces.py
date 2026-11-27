# SPDX-License-Identifier: GPL-3.0-or-later
"""Glass FACES hidden for VR on objects that are only partly glass (a character mesh with a glass visor slot): hiding
the whole object hid the whole character (2026-11-27). A Geometry Nodes modifier is added LAST in the stack (before a
trailing Subdivision Surface, so GPU subdivision still works) that deletes the faces of the glass slots.
- Viewport only: show_render off, no material change (Render safety rule). Off in Edit mode.
- One node group shared by every object; the slots come in as one integer input, a bit per slot (slot i = 2**i), so
  no object needs a group of its own. Slots from MAX_SLOTS on can't be named: such objects stay visible.
- Only editable meshes: linked objects (not overridden) can't take a modifier and stay visible. Library overrides
  can (an added modifier is local data).
- Every added modifier is recorded in the Performance record (scene_record kind "modifier"), so the restore paths
  of perf_state (VR end, save_pre, load, undo) remove it. sync() is a diff: nothing changed, nothing written."""
import bpy

from . import scene_record  # scene_record: generated copy

GROUP_TAG = "digits_vr_glass_faces"     # node group custom property: the version of the group below
GROUP_VERSION = 1
GROUP_NAME = "VR Hide Glass Faces"
MODIFIER_NAME = "VR glass faces hidden"
SLOTS_INPUT = "Glass slots"
MAX_SLOTS = 31                          # bits of the (signed 32-bit) integer input


def slot_mask(slots):
    return sum(1 << index for index in slots)


def can_hide_faces(ob, slots):
    return ob.type == 'MESH' and ob.is_editable and max(slots) < MAX_SLOTS


def find_group():
    return next((group for group in bpy.data.node_groups if group.get(GROUP_TAG) == GROUP_VERSION), None)


def _build_group():
    """Delete the faces whose material index has its bit set in the slots input: (slots // 2**index) % 2."""
    group = bpy.data.node_groups.new(GROUP_NAME, 'GeometryNodeTree')
    group[GROUP_TAG] = GROUP_VERSION
    group.is_modifier = True
    group.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(SLOTS_INPUT, in_out='INPUT', socket_type='NodeSocketInt')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes, links = group.nodes, group.links
    group_in, group_out = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
    index = nodes.new('GeometryNodeInputMaterialIndex')
    power, divide, modulo = (nodes.new('FunctionNodeIntegerMath') for _ in range(3))
    power.operation, divide.operation, modulo.operation = 'POWER', 'DIVIDE_FLOOR', 'MODULO'
    power.inputs[0].default_value = 2
    modulo.inputs[1].default_value = 2
    delete = nodes.new('GeometryNodeDeleteGeometry')
    delete.domain = 'FACE'
    links.new(index.outputs[0], power.inputs[1])
    links.new(group_in.outputs[SLOTS_INPUT], divide.inputs[0])
    links.new(power.outputs[0], divide.inputs[1])
    links.new(divide.outputs[0], modulo.inputs[0])
    links.new(modulo.outputs[0], delete.inputs["Selection"])        # integer 1 / 0 -> selection
    links.new(group_in.outputs["Geometry"], delete.inputs["Geometry"])
    links.new(delete.outputs["Geometry"], group_out.inputs["Geometry"])
    return group


def _slots_identifier(group):
    return next(item.identifier for item in group.interface.items_tree
                if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == SLOTS_INPUT)


def is_ours(mod):
    return mod.type == 'NODES' and mod.node_group is not None and mod.node_group.get(GROUP_TAG) is not None


def _slots_value(mod):
    return getattr(mod.properties.inputs, _slots_identifier(mod.node_group))


def _set_mask(mod, mask):
    """Write the slots input only when it differs. Returns how many values were written (0 or 1)."""
    value = _slots_value(mod)
    if value.value == mask:
        return 0
    value.value = mask
    return 1


def _add(owner, key, ob, mask):
    group = find_group() or _build_group()
    mod = ob.modifiers.new(MODIFIER_NAME, 'NODES')
    scene_record.record_modifier(owner, key, ob, mod)       # recorded at once: a restore always finds it
    mod.node_group = group
    mod.show_render = mod.show_in_editmode = mod.show_on_cage = mod.show_expanded = False
    _set_mask(mod, mask)
    count = len(ob.modifiers)
    if count > 1 and ob.modifiers[count - 2].type == 'SUBSURF':
        ob.modifiers.move(count - 1, count - 2)


def sync(owner, key, parts):
    """Bring the recorded glass-face modifiers to `parts` [(object, glass slot indices)]: objects that leave the list
    lose theirs, new ones get one, kept ones get their slots input written only when it changed. Objects that can't
    take one are left alone (they stay visible). Returns how many values were written."""
    wanted = {ob.name_full: (ob, slot_mask(slots)) for ob, slots in parts if can_hide_faces(ob, slots)}
    entries, done, kept = [], 0, set()
    for entry in scene_record.recorded(owner, key):
        if entry[0] != scene_record.MODIFIER:
            entries.append(entry)
            continue
        _ob, mod = scene_record.added_modifier(entry)
        target = wanted.get(entry[2])
        if target is not None and mod is not None and is_ours(mod) and entry[2] not in kept:
            done += _set_mask(mod, target[1])
            entries.append(entry)
            kept.add(entry[2])
        elif scene_record.restore_entry(entry):
            done += 1
    scene_record.write_record(owner, key, entries)
    for name, (ob, mask) in wanted.items():
        if name not in kept:
            _add(owner, key, ob, mask)
            done += 1
    return done


def count(owner, key):
    """How many objects have glass faces hidden (recorded modifiers)."""
    return sum(1 for entry in scene_record.recorded(owner, key) if entry[0] == scene_record.MODIFIER)


def clean_up():
    """After every record is restored: remove any of our modifiers still left (a record lost in a crash) and the node
    group. Cheap when VR added none: nothing to do without the group. Returns how many modifiers were removed."""
    group = find_group()
    if group is None:
        return 0
    removed = 0
    if group.users:
        for ob in bpy.data.objects:
            if not ob.is_editable:
                continue
            for mod in [mod for mod in ob.modifiers if is_ours(mod)]:
                ob.modifiers.remove(mod)
                removed += 1
    if not group.users:
        bpy.data.node_groups.remove(group)
    return removed
