# SPDX-License-Identifier: GPL-3.0-or-later
"""Reparent by dragging in the Outliner tab: trigger on an OBJECT's name and drag it (like Blender's Outliner drop).
Dropped on another object's row: parented to it, keeping its place in the world. Dropped on a collection's row: the
parent is cleared (keeping its place) and the object MOVES into that collection (out of its others). Dropped on empty space
of the desk: the parent is cleared, the object stays in its collections. Dropped on any other control or off the desk:
nothing. Released over its own row: a tap, nothing. Locked (`hide_select`) and linked objects are refused; so is a drop that
would make a parent its own child. One undo step per drop. The target row glows while dragging (model fields
`outliner_drag` / `outliner_drop`).
One claim mechanism: the layout sets `Widget.claims_drag` on an object's name (the shared list drag never scrolls from it);
a trigger-drag anywhere else on the page scrolls."""
import time
from dataclasses import dataclass

import bpy

from . import workspace
from .action_map import buzz
from .desk_qol_math import NOTICE
from .desk_state import DESK
from .outliner_layout import COLLECTION, OBJECT, ROW_PREFIX
from . import router, selection
from .picking import OBJECT as PICKED_OBJECT, Target, is_linked
from .runtime import RUNTIME
from .tools import push_undo


@dataclass
class Drag:
    hand: str
    source: str                 # name_full of the dragged object
    widget_id: str              # its own row's widget id (a release there is a tap)
    target: str = ""            # fold key of the row under the laser ("" = none)


STATE = [None]                  # the drag in progress (a list: no `global`)


def drag():
    return STATE[0]


def _row_of(widget_id, rows):
    if not (widget_id or "").startswith(ROW_PREFIX):
        return None
    index = int(widget_id[len(ROW_PREFIX):])
    return rows[index] if index < len(rows) else None


def press(context, state, hand, widget_id, rows):
    """A trigger on a row's name. True when it took the press (an object's name: a drag begins)."""
    row = _row_of(widget_id, rows)
    if row is None or row.kind != OBJECT or STATE[0] is not None:       # (the layout marks these names `claims_drag`)
        return False
    if row.locked:
        _say("Locked: unlock it first")
        buzz(context, state, hand)
        return True
    STATE[0] = Drag(hand, row.name_full, widget_id)
    buzz(context, state, hand, duration=0.02, amplitude=0.4)
    return True


def select_object(context, state, hand, name_full):
    """A tap on an object's row: it becomes the only selection and the active object, like a click in Blender's Outliner
    (the same `selection.apply` as a trigger select; no Smart select: you picked exactly this row). True when it did."""
    ob = bpy.data.objects.get(name_full)
    if router.mode_kind(context.mode) != router.OBJECT:
        reason = "Go to Object mode to select here"
    elif ob is None or ob.name not in context.view_layer.objects:
        reason = "That object is not in the view layer"
    elif ob.hide_select:
        reason = "Locked: unlock it first"
    else:
        reason = ""
    if reason:
        _say(reason)
        buzz(context, state, hand)
        return False
    if selection.apply(context, Target(PICKED_OBJECT, ob.name_full, linked=is_linked(ob)), router.REPLACE):
        push_undo("VR Select")
    return True


def _say(text):
    NOTICE.show(text, time.perf_counter())


def reason_refused(source, target):
    """Why `source` can't go under object `target` (None = it can)."""
    if source.hide_select or is_linked(source):
        return "Locked or linked: can't be moved"
    if target is not None and (target.hide_select or is_linked(target)):
        return "That parent is locked or linked"
    parent = target
    while parent is not None:
        if parent == source:
            return "An object can't be its own parent's child"
        parent = parent.parent
    return None


def set_parent(source, target):
    """Parent `source` to object `target` keeping its place in the world (Blender's Object parenting)."""
    world = source.matrix_world.copy()
    source.parent = target
    source.parent_type, source.parent_bone = 'OBJECT', ""
    source.matrix_parent_inverse = target.matrix_world.inverted()
    source.matrix_world = world


def clear_parent(source):
    world = source.matrix_world.copy()
    source.parent = None
    source.matrix_world = world


def move_to(source, collection):
    """Out of every collection it is in, into `collection`."""
    if collection not in source.users_collection:
        collection.objects.link(source)
    for other in list(source.users_collection):
        if other != collection:
            other.objects.unlink(source)


def drop(context, source_name, target_kind, target_name):
    """Do one drop. target_kind OBJECT / COLLECTION / "" (empty space). True when something changed."""
    source = bpy.data.objects.get(source_name)
    if source is None:
        return False
    context.view_layer.update()                       # world matrices current: a drop never moves anything
    target = bpy.data.objects.get(target_name) if target_kind == OBJECT else None
    reason = reason_refused(source, target)
    if target_kind == COLLECTION:
        collection = next((item for item in context.scene.collection.children_recursive if item.name_full == target_name), None)
        if reason is None and collection is not None and not collection.hide_select:
            clear_parent(source)
            move_to(source, collection)
            text = f"{source.name} moved to {collection.name}"
        else:
            reason = reason or "That collection is locked"
    elif target_kind == OBJECT and target is not None and reason is None:
        set_parent(source, target)
        text = f"{source.name} parented to {target.name}"
    elif target_kind == "" and reason is None:
        if source.parent is None:
            _say(f"{source.name} has no parent")
            return False
        clear_parent(source)
        text = f"{source.name} has no parent now"
    if reason is not None or "text" not in locals():
        _say(reason or "Nothing changed")
        return False
    _say(text)
    workspace.changed()
    RUNTIME.cache.all_dirty = True
    RUNTIME.cache.objects = None
    RUNTIME.cache.version += 1
    push_undo("VR Reparent")
    return True


def update(context, state, rows):
    """Each tick (from the desk): follow the laser while the trigger is held, drop at the release. True when the screen
    must be drawn again (the glow moved, or the drag ended)."""
    current = STATE[0]
    if current is None:
        return False
    hover = DESK.hover.get(current.hand)
    row = _row_of(hover, rows)
    target = row.fold_key() if row is not None and hover != current.widget_id else ""
    if RUNTIME.hands[current.hand].trigger_down:
        changed = target != current.target
        current.target = target
        return changed
    STATE[0] = None
    on_desk = current.hand in DESK.reach
    if hover == current.widget_id:
        select_object(context, state, current.hand, current.source)        # a tap on its own row: select it
        return True
    if row is not None:
        done = drop(context, current.source, row.kind, row.name_full)
    elif hover is None and on_desk:
        done = drop(context, current.source, "", "")
    else:
        _say("Dropped off the list: nothing changed")
        done = False
    if done:
        buzz(context, state, current.hand, duration=0.03, amplitude=0.5)
    return True


def cancel():
    STATE[0] = None
