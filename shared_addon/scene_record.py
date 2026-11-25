# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings changed TEMPORARILY (Digit's VR: compositor off, raytracing off, objects hidden), recorded in a custom
property of an ID (a scene or the window manager) so a later restore puts back exactly what was there. Same idea
as viewport_modifiers.py (which does it for modifier flags), for any RNA property and for object hiding.

A record is JSON: [[kind, collection, ID full name, path, original value], ...].
- kind "rna": `path` is a dotted property path from the ID ("eevee.use_raytracing"), `collection` a bpy.data
  collection name ("scenes", "window_managers").
- kind "hide": the object's view-layer eye; `path` is [scene name, view layer name], the original is always False
  (only objects that were showing are hidden and recorded)."""
import json

import bpy

RNA, HIDE = "rna", "hide"


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
        if old_value == _plain(new_value):
            continue
        if (RNA, collection, id_block.name_full, path) not in known:
            entries.append([RNA, collection, id_block.name_full, path, old_value])
            write_record(owner, key, entries)       # record the original BEFORE changing it: never lose a setting
        _write(id_block, path, new_value)
        done += 1
    write_record(owner, key, entries)
    return done


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


def _restore_entry(entry):
    kind, collection, full_name, path, original = entry
    id_block = _find(collection, full_name)
    if id_block is None:
        return False
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
