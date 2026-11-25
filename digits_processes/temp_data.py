# SPDX-License-Identifier: GPL-3.0-or-later
"""Temporary data for a process: everything made inside `with temporary_data():` (scenes, objects, rigs,
worlds, node groups, libraries, render results...) is removed again when the block ends, also after an error.

It compares ID session ids before and after, so it catches whatever the chained tools add without knowing them.
Keep anything that must survive (output images, a decal) OUT of the block: make it after the block ends.
"""
from contextlib import contextmanager

import bpy

NOT_DATA = {"window_managers", "workspaces", "screens"}   # UI, never made or removed by a process
_collection_names = None


def collection_names():
    """The bpy.data attributes that hold IDs (objects, scenes, images...), found once."""
    global _collection_names
    if _collection_names is None:
        _collection_names = [name for name in dir(bpy.data) if name not in NOT_DATA and not name.startswith("_")
                             and isinstance(getattr(bpy.data, name, None), bpy.types.bpy_prop_collection)]
    return _collection_names


def all_ids():
    for name in collection_names():
        for datablock in getattr(bpy.data, name):
            if isinstance(datablock, bpy.types.ID):
                yield datablock


def snapshot():
    """The session ids of every ID in the file now."""
    return {datablock.session_uid for datablock in all_ids()}


def remove_new(before):
    """Remove every ID that is not in `before`. Returns the removed names ("collection: name")."""
    new = [datablock for datablock in all_ids() if datablock.session_uid not in before]
    names = [f"{type(datablock).__name__}: {datablock.name}" for datablock in new]
    if new:
        bpy.data.batch_remove(new)
    return names


@contextmanager
def temporary_data(removed=None):
    """Remove everything made inside the block when it ends. `removed`, a list, gets the removed names."""
    before = snapshot()
    try:
        yield
    finally:
        names = remove_new(before)
        if removed is not None:
            removed.extend(names)
