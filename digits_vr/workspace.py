# SPDX-License-Identifier: GPL-3.0-or-later
"""Workspace and locks: which objects a pick may act on. Select, grab, box select, the select bubble and the tool gun act
only on objects in the workspace collection (and its child collections); everything else (the stage, set pieces) is not
hovered, not hit (a ray passes through it) and not selected. Locked objects and objects in locked collections (Blender's
`hide_select`, the same as on the desktop) are left out too. Saved in the .blend as a Scene custom property pointing at the
collection (it follows a rename; a deleted collection means Everything, today's behaviour and the default).
The allowed set is read only when the pick list is rebuilt (`SceneCache.pickable_objects`); `key` (workspace, object and
collection counts, REVISION) tells when it must be read again. No filter at all (None) while there is no workspace and no
locked collection. The Outliner tab that sets all this is outliner.py."""
import bpy

PROP = "digits_vr_workspace"
REVISION = [0]              # bumped by every change the Outliner makes (a lock, a collection switched off, a workspace)
_members = {"key": None, "names": None}


def changed():
    REVISION[0] += 1


def current(scene):
    """The workspace collection, or None (Everything)."""
    collection = scene.get(PROP)
    return collection if isinstance(collection, bpy.types.Collection) else None


def set_current(scene, collection):
    """Make `collection` the workspace (None: Everything)."""
    if collection is None:
        scene.pop(PROP, None)
    else:
        scene[PROP] = collection
    changed()


def key(scene):
    """What the allowed set depends on: changes when the choice or the object / collection lists or a lock change."""
    collection = current(scene)
    return scene.name_full, collection.name_full if collection else "", len(bpy.data.objects), len(bpy.data.collections), REVISION[0]


def _allowed(collection, names):
    """Add the pickable objects of an unlocked collection tree to `names`."""
    if collection.hide_select:
        return
    names.update(ob.name_full for ob in collection.objects if not ob.hide_select)
    for child in collection.children:
        _allowed(child, names)


def member_names(scene, refresh=False):
    """name_full of every object a pick may act on (None = no filter), kept until `key` changes."""
    now = key(scene)
    if refresh or _members["key"] != now:
        chosen = current(scene)
        if chosen is None and not any(collection.hide_select for collection in bpy.data.collections):
            names = None
        else:
            names = set()
            _allowed(chosen or scene.collection, names)
            names = frozenset(names)
        _members.update(key=now, names=names)
    return _members["names"]


def contains(scene, ob):
    names = member_names(scene)
    return names is None or ob.name_full in names


def reaches(scene, ob):
    """In the workspace, or a parent of something in it (a rig root in another collection than its meshes): Smart select
    grabs such a root, so grabs may move it."""
    names = member_names(scene)
    return names is None or ob.name_full in names or any(child.name_full in names for child in ob.children_recursive)
