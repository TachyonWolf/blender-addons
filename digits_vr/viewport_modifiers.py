# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/viewport_modifiers.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Modifiers turned off IN THE VIEWPORT ONLY (show_viewport; renders are never touched), recorded in a scene custom
property so a later restore turns back on exactly those and leaves the ones the user had off alone.
Used by Fast Viewport (Digit's Assorted Tools) and the VR modifier state (Digit's VR), each with its own record key.

A record is JSON: [[object full name, modifier name, modifier persistent_uid], ...]. The object full name holds
the library too ("Body [Character.blend]"). Old two-item entries (no uid) are still read and matched by name."""

import bpy

from . import scene_record
from .scene_record import write_record  # also used as viewport_modifiers.write_record


def record_entry(ob, mod):
    return [ob.name_full, mod.name, mod.persistent_uid]


def recorded(scene, key):
    """[[object full name, modifier name, uid or None], ...] recorded under `key`."""
    return [list(entry[:2]) + [entry[2] if len(entry) > 2 else None] for entry in scene_record.recorded(scene, key)]


def find_modifier(entry, objects_by_name):
    """(object, modifier) of a record entry, or (object or None, None) when gone. The uid wins over the name, so a
    renamed modifier is still found."""
    ob = objects_by_name.get(entry[0])
    if ob is None:
        return None, None
    uid = entry[2]
    if uid is not None:
        for mod in ob.modifiers:
            if mod.persistent_uid == uid:
                return ob, mod
    return ob, ob.modifiers.get(entry[1])


def turn_off(scene, key, pairs):
    """Turn the given (object, modifier) pairs off in the viewport and add them to the record. Pairs already off or
    on objects that can't be edited (linked data) are skipped. Returns (turned off, skipped as not editable)."""
    entries = recorded(scene, key)
    done, skipped = 0, 0
    for ob, mod in pairs:
        if not mod.show_viewport:
            continue
        if not ob.is_editable:  # linked data, or a library override that doesn't allow it
            skipped += 1
            continue
        mod.show_viewport = False
        entries.append(record_entry(ob, mod))
        done += 1
    write_record(scene, key, entries)
    return done, skipped


def restore(scene, key, keep=None):
    """Turn back on the recorded modifiers and drop them from the record. `keep(ob, mod)` True leaves an entry
    recorded and off (e.g. still hidden in VR). Returns how many were turned back on."""
    by_name = {ob.name_full: ob for ob in bpy.data.objects}
    kept, restored = [], 0
    for entry in recorded(scene, key):
        ob, mod = find_modifier(entry, by_name)
        if mod is None or not ob.is_editable:
            continue  # gone or linked: nothing to restore
        if keep and keep(ob, mod):
            kept.append(entry)
            continue
        mod.show_viewport = True
        restored += 1
    write_record(scene, key, kept)
    return restored
