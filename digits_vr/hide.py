# SPDX-License-Identifier: GPL-3.0-or-later
"""Hide / Unhide in Object mode (desk Tools tab): Hide = Hide Selected (H), Unhide = Unhide All (Alt+H), Unhide from list =
one object from a paged list of the hidden ones. Normal Blender hiding (`hide_set`, saved with the file), one undo step
each. Objects the add-on hid itself for VR (glass / transparent, Performance tab) are left out of the list and
of Unhide: they come back when VR ends."""
from dataclasses import dataclass

import bpy

from .tools import push_undo

LIST_ROWS = 5       # rows of the desk's Hidden objects pop-up per page


@dataclass
class State:
    page: int = 0


STATE = State()


def vr_hidden_objects():
    """Full names of the objects this add-on hid for VR (the Performance tab's glass / transparent objects): not
    listed and not unhidden here, they come back when VR ends."""
    from . import perf_state
    return perf_state.hidden_names(bpy.context.scene)


def hidden_names(context):
    """Names of the user-hidden objects in the view layer, sorted."""
    skip = vr_hidden_objects()
    return sorted(ob.name for ob in context.view_layer.objects if ob.hide_get() and ob.name not in skip)


def can_hide(context):
    return any(ob.visible_get() for ob in context.selected_objects)


def page_of(names, page, per_page=LIST_ROWS):
    """(names on show, page clamped into range, page count)."""
    pages = max(1, -(-len(names) // per_page))
    page = min(max(page, 0), pages - 1)
    return tuple(names[page * per_page:(page + 1) * per_page]), page, pages


def view(context):
    """(names on show, page, pages, total hidden, can hide) for the desk model."""
    names = hidden_names(context)
    shown, STATE.page, pages = page_of(names, STATE.page)
    return shown, STATE.page, pages, len(names), can_hide(context)


def hide_objects(objects, push=True):
    """Hide these objects (H). One undo step (`push` False: the caller pushes it)."""
    for ob in objects:
        ob.hide_set(True)
    if objects and push:
        push_undo("VR Hide")
    return bool(objects)


def hide_selected(context):
    return hide_objects([ob for ob in context.selected_objects if ob.visible_get()])


def unhide_all(context):
    """Show every user-hidden object and select them (Alt+H). One undo step."""
    names = hidden_names(context)
    for name in names:
        ob = context.view_layer.objects.get(name)
        if ob is not None:
            ob.hide_set(False)
            ob.select_set(True)
    if names:
        push_undo("VR Unhide")
    return bool(names)


def unhide_one(context, name):
    """Show one object from the list and make it the only selection. One undo step."""
    ob = context.view_layer.objects.get(name)
    if ob is None or not ob.hide_get() or name in vr_hidden_objects():
        return False
    for other in context.selected_objects:
        other.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    push_undo("VR Unhide Object")
    return True


def turn_page(step):
    STATE.page = max(0, STATE.page + step)
    return True
