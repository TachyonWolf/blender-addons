# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's Outliner tab (bpy side): the rows of the scene's collections and their objects, and what its buttons do.
Set as workspace (workspace.py), On / Off = the collection's view-layer checkbox (`LayerCollection.exclude`, the
checkbox of Blender's Outliner), Lock = `hide_select` of the object or collection. One undo step each. Only the rows of
the open collections are built, and only those on show are read."""
from dataclasses import dataclass, field

import bpy

from . import workspace
from .outliner_layout import COLLECTION, EVERYTHING_LABEL, OBJECT, OutlinerRow, rows_shown, window_of
from . import outliner_drag
from .row_icons import icon_for
from .tools import push_undo


@dataclass
class OutlinerState:
    opened: set = field(default_factory=set)    # fold keys ("C:name") of the collections shown open (all start shut)
    scroll: int = 0                             # first row on show


STATE = OutlinerState()


def _layer_collections(layer_collection, found):
    found[layer_collection.collection.name_full] = layer_collection
    for child in layer_collection.children:
        _layer_collections(child, found)
    return found


def _walk(collection, depth, rows):
    """(depth, collection or object) of the visible rows below `collection`."""
    for child in collection.children:
        rows.append((depth, child))
        if COLLECTION + ":" + child.name_full in STATE.opened:
            rows.extend((depth + 1, ob) for ob in child.objects)     # its own objects first, right under its name
            _walk(child, depth + 1, rows)
    return rows


def _row(depth, item, layers, view_layer):
    if isinstance(item, bpy.types.Collection):
        key = COLLECTION + ":" + item.name_full
        return OutlinerRow(COLLECTION, item.name_full, item.name, depth, bool(item.children or item.objects),
                           key in STATE.opened, not layers[item.name_full].exclude, item.hide_select, "collection")
    return OutlinerRow(OBJECT, item.name_full, item.name, depth, locked=item.hide_select, icon=icon_for(item.type),
                       selected=item.name in view_layer.objects and item.select_get(view_layer=view_layer))


def view(context, extra):
    """(label of the workspace, name_full of it or "", rows on show, scroll, last scroll) for the desk model."""
    chosen = workspace.current(context.scene)
    entries = _walk(context.scene.collection, 0, [])
    shown, STATE.scroll, last = window_of(entries, STATE.scroll, rows_shown(extra))
    layers = _layer_collections(context.view_layer.layer_collection, {})
    return (chosen.name if chosen else EVERYTHING_LABEL, chosen.name_full if chosen else "",
            tuple(_row(depth, item, layers, context.view_layer) for depth, item in shown), STATE.scroll, last)


def current_name(scene):
    chosen = workspace.current(scene)
    return chosen.name_full if chosen else ""


def key(scene):
    """What the Outliner tab's rows depend on besides the press state (for the desk model's reuse key)."""
    return workspace.key(scene), STATE.scroll, len(STATE.opened), outliner_drag.drag() is not None


def label(scene):
    chosen = workspace.current(scene)
    return chosen.name if chosen else EVERYTHING_LABEL


def _find(context, kind, name_full):
    if kind == OBJECT:
        return bpy.data.objects.get(name_full) or next((ob for ob in bpy.data.objects if ob.name_full == name_full), None)
    return next((collection for collection in context.scene.collection.children_recursive
                 if collection.name_full == name_full), None)


def _set_workspace(context, name_full):
    collection = _find(context, COLLECTION, name_full) if name_full else None
    if name_full and collection is None:
        return False
    workspace.set_current(context.scene, collection)
    push_undo("VR Workspace")
    return True


def _enable(context, name_full):
    layer = _layer_collections(context.view_layer.layer_collection, {}).get(name_full)
    if layer is None:
        return False
    layer.exclude = not layer.exclude
    workspace.changed()
    push_undo("VR Collection On / Off")
    return True


def _lock(context, kind, name_full):
    item = _find(context, kind, name_full)
    if item is None:
        return False
    item.hide_select = not item.hide_select
    workspace.changed()
    push_undo("VR Lock")
    return True


def perform(context, action):
    """A desk button of the Outliner tab. True when something changed."""
    kind, *arguments = action
    if kind == "workspace_set":
        return _set_workspace(context, arguments[0])
    if kind == "workspace_enable":
        return _enable(context, arguments[0])
    if kind == "workspace_lock":
        return _lock(context, *arguments)
    if kind == "workspace_fold":
        STATE.opened ^= {arguments[0]}
    elif kind == "workspace_scroll":
        STATE.scroll = max(0, STATE.scroll + arguments[0])
    else:
        return False
    return True
