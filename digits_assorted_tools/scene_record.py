# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/scene_record.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings changed TEMPORARILY (Digit's VR: compositor off, raytracing off, objects hidden), recorded in a custom
property of an ID (a scene or the window manager) so a later restore puts back exactly what was there. Same idea
as viewport_modifiers.py (which does it for modifier flags), for any RNA property and for object hiding.

A record is JSON: [[kind, collection, ID full name, path, original value], ...].
- kind "rna": `path` is a dotted property path from the ID ("eevee.use_raytracing"), `collection` a bpy.data
  collection name ("scenes", "window_managers").
- kind "hide": the object's view-layer eye; `path` is [scene name, view layer name], the original is always False
  (only objects that were showing are hidden and recorded).
- kind "modifier": a modifier ADDED for the time being (viewport only); `path` is [modifier name, persistent_uid],
  the original is None (it was not there). Restoring removes it.
- kind "slot": a material slot of an object switched to another material for the time being; `path` is
  [slot index, the stand-in material's full name], the original [slot link, the object-level material's full name or
  None]. Restoring puts both back, only while the slot still shows the stand-in (a slot changed since is left alone)."""
import json
import math

import bpy

RNA, HIDE, MODIFIER, SLOT = "rna", "hide", "modifier", "slot"


def recorded(owner, key):
    try:
        return json.loads(owner.get(key, "[]"))
    except (TypeError, ValueError):
        print(f"scene_record: unreadable record {key!r}, ignored")
        return []


def write_record(owner, key, entries):
    if entries:
        owner[key] = json.dumps(entries)
    elif key in owner:
        del owner[key]


def _find(collection, full_name):
    return next((item for item in getattr(bpy.data, collection) if item.name_full == full_name), None)


def _split(path):
    head, _dot, last = path.rpartition(".")
    return head, last


def _plain(value):
    """A value the JSON record can hold: vectors, colours, quaternions and property arrays become lists."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    try:
        return [_plain(item) for item in value]
    except TypeError:
        return value


def _same(first, second):
    """Equal, with float32 rounding allowed (Blender stores 0.1 as 0.10000000149): a value already at its target is
    never written again."""
    if isinstance(first, float) or isinstance(second, float):
        try:
            return math.isclose(first, second, rel_tol=1e-6, abs_tol=1e-9)
        except TypeError:
            return False
    if isinstance(first, list) and isinstance(second, list):
        return len(first) == len(second) and all(_same(one, other) for one, other in zip(first, second))
    return first == second


def _read(id_block, path):
    head, last = _split(path)
    return _plain(getattr(id_block.path_resolve(head) if head else id_block, last))


def _write(id_block, path, value):
    head, last = _split(path)
    setattr(id_block.path_resolve(head) if head else id_block, last, value)


def set_values(owner, key, changes, collection):
    """changes: [(ID, path, new value)] for IDs of `collection`. Each one whose value differs is set and its old
    value recorded (a path already recorded keeps its first, true original). Returns how many were set."""
    entries = recorded(owner, key)
    known = {tuple(entry[:4]) for entry in entries if entry[0] == RNA}
    done = 0
    for id_block, path, new_value in changes:
        old_value = _read(id_block, path)
        if _same(old_value, _plain(new_value)):
            continue
        if (RNA, collection, id_block.name_full, path) not in known:
            entries.append([RNA, collection, id_block.name_full, path, old_value])
            write_record(owner, key, entries)       # record the original BEFORE changing it: never lose a setting
        _write(id_block, path, new_value)
        done += 1
    write_record(owner, key, entries)
    return done


def original_value(owner, key, collection, id_block, path):
    """The value `path` had before any recorded change (the value now when nothing is recorded for it)."""
    target = (RNA, collection, id_block.name_full, path)
    entry = next((entry for entry in recorded(owner, key) if tuple(entry[:4]) == target), None)
    return entry[4] if entry is not None else _read(id_block, path)


def sync_values(owner, key, changes, collection, keep=()):
    """Bring the record of `collection` to `changes` [(ID, path, target)] with as few writes as possible: a value
    already at its target is never written; a recorded value no longer in `changes` (or whose target is its original)
    gets its original back, alone. Paths in `keep` are left as they are. Originals are recorded once, before the first
    change. Work targets out from original_value(), not from the value now. Returns how many values were written."""
    targets = {(id_block.name_full, path): _plain(new_value) for id_block, path, new_value in changes}
    entries, done = [], 0
    for entry in recorded(owner, key):
        kind, entry_collection, full_name, path, original = entry
        if (kind != RNA or entry_collection != collection or path in keep or
                not _same(targets.get((full_name, path), original), original)):
            entries.append(entry)
            continue
        id_block = _find(collection, full_name)
        if id_block is not None and not _same(_read(id_block, path), original) and _restore_entry(entry):
            done += 1
    write_record(owner, key, entries)
    return done + set_values(owner, key, changes, collection)


def sync_hidden(owner, key, objects, scene, view_layer):
    """Bring the recorded hidden objects to `objects` (this scene and view layer): only objects that leave the list are
    shown again and only new ones are hidden; the others are not touched. Returns how many changed."""
    wanted = {ob.name_full for ob in objects}
    place = [scene.name, view_layer.name]
    entries, done = [], 0
    for entry in recorded(owner, key):
        if entry[0] != HIDE or (entry[3] == place and entry[2] in wanted):
            entries.append(entry)
        elif _restore_entry(entry):
            done += 1
    write_record(owner, key, entries)
    known = {entry[2] for entry in entries if entry[0] == HIDE}
    return done + hide_objects(owner, key, [ob for ob in objects if ob.name_full not in known], scene, view_layer)


def hide_objects(owner, key, objects, scene, view_layer):
    """Hide the given objects (the eye icon) that are showing, and record them. Returns how many."""
    entries = recorded(owner, key)
    done = 0
    for ob in objects:
        try:
            if ob.hide_get(view_layer=view_layer):
                continue
            ob.hide_set(True, view_layer=view_layer)
        except RuntimeError:        # not in this view layer
            continue
        entries.append([HIDE, "objects", ob.name_full, [scene.name, view_layer.name], False])
        done += 1
    write_record(owner, key, entries)
    return done


def record_modifier(owner, key, ob, mod):
    """Record a modifier just added to `ob`, so a restore removes it again."""
    entry = [MODIFIER, "objects", ob.name_full, [mod.name, mod.persistent_uid], None]
    write_record(owner, key, recorded(owner, key) + [entry])


def added_modifier(entry):
    """(object, modifier) of a "modifier" entry: (None, None) when the object is gone, (object, None) when the modifier
    is. Matched by persistent_uid only, so a user's modifier of the same name is never taken for it."""
    ob = _find("objects", entry[2])
    if ob is None:
        return None, None
    return ob, next((mod for mod in ob.modifiers if mod.persistent_uid == entry[3][1]), None)


def swap_slot(owner, key, ob, index, material):
    """Show `material` in slot `index` of `ob` (an object-level slot link, so the object's data is not changed: works
    for library overrides whose mesh is linked) and record the slot's link and object-level material first."""
    slot = ob.material_slots[index]
    link = slot.link
    slot.link = 'OBJECT'            # the object-level material can only be read through an OBJECT link
    original = slot.material.name_full if slot.material is not None else None
    entry = [SLOT, "objects", ob.name_full, [index, material.name_full], [link, original]]
    write_record(owner, key, recorded(owner, key) + [entry])     # recorded before the stand-in goes in
    slot.material = material


def swapped_slot(entry):
    """The material slot of a "slot" entry while it still shows its stand-in, else None."""
    ob = _find("objects", entry[2])
    index, stand_in = entry[3]
    if ob is None or index >= len(ob.material_slots):
        return None
    slot = ob.material_slots[index]
    if slot.link != 'OBJECT' or slot.material is None or slot.material.name_full != stand_in:
        return None
    return slot


def restore_entry(entry):
    """Put back one entry (no record change). Returns True when it was put back."""
    return _restore_entry(entry)


def _restore_entry(entry):
    kind, collection, full_name, path, original = entry
    id_block = _find(collection, full_name)
    if id_block is None:
        return False
    if kind == MODIFIER:
        ob, mod = added_modifier(entry)
        if mod is None or not ob.is_editable:
            return False
        ob.modifiers.remove(mod)
        return True
    if kind == SLOT:
        slot = swapped_slot(entry) if id_block.is_editable else None
        if slot is None:
            return False
        link, material_name = original
        slot.material = _find("materials", material_name) if material_name else None
        slot.link = link
        return True
    if kind == HIDE:
        scene = bpy.data.scenes.get(path[0])
        view_layer = scene.view_layers.get(path[1]) if scene else None
        if view_layer is None:
            return False
        try:
            id_block.hide_set(original, view_layer=view_layer)
        except RuntimeError:
            return False
        return True
    try:
        _write(id_block, path, original)
    except (AttributeError, ValueError, TypeError):
        return False
    return True


def restore(owner, key):
    """Put every recorded original back and drop the record. Returns how many were put back."""
    entries = recorded(owner, key)
    restored = sum(1 for entry in entries if _restore_entry(entry))
    write_record(owner, key, [])
    return restored
