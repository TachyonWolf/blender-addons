# SPDX-License-Identifier: GPL-3.0-or-later
"""Smart select: the one resolver every Object mode pick goes through (trigger select, touch, grip grab, laser grab).
While the setting `smart_select` is on, the first pick of an object acts on the top-most parent of its hierarchy; a
second pick of the same hierarchy within WINDOW seconds acts on the exact object hit. Pose bones, Edit mode elements
and linked data are never changed here. Time is passed in, so the logic is testable without a clock."""
import time
from dataclasses import dataclass, replace

from . import router, settings, size_state
from .picking import OBJECT, find_object, is_linked, pickable

WINDOW = 0.6              # s: after the last pick or release of a hierarchy, the next pick of it is exact
QUICK_GRAB_SECONDS = 0.5  # s: a smart first grab released within this ...
QUICK_GRAB_DISTANCE = 0.03  # m in your space: ... with the item moved less than this is a tap: undone, no undo step


def top_parent(ob, view_layer):
    """The top-most parent worth acting on: walk `parent` up, stopping below a parent that can't be picked (hidden,
    locked = hide_select, not in the view layer) or can't be changed (linked). `ob` itself when none qualifies. The
    workspace does NOT stop the walk: only workspace objects can be hit at all, and a rig's root often sits in another
    collection than its meshes [user, 2026-11-26: workspace Body, rig root in Digit]."""
    best = ob
    parent = ob.parent
    while parent is not None:
        if not (parent.name in view_layer.objects and pickable(parent, view_layer)) or is_linked(parent):
            break
        best = parent
        parent = parent.parent
    return best


@dataclass
class SmartState:
    root_name: str = ""      # the hierarchy (its top-most pickable object) last acted on
    stamp: float = -1e9      # when it was last picked or released


STATE = SmartState()


def reset():
    STATE.root_name, STATE.stamp = "", -1e9


def resolve(context, target, now=None, preview=False):
    """(target to act on, smart) for a pick `target` in Object mode with the setting on. `smart` is True when the root
    stands in for a deeper hit (the caller may then treat a quick tap as an accident). `preview` (the hover glow):
    the same answer, but the window is not started. Off, Pose / Edit and a lone object: unchanged."""
    if (not settings.get("smart_select") or router.mode_kind(context.mode) != router.OBJECT
            or target is None or target.kind != OBJECT or not target.object_name):
        return target, False
    now = time.perf_counter() if now is None else now
    ob = find_object(context.blend_data, target.object_name)
    if ob is None:
        return target, False
    root = top_parent(ob, context.view_layer)
    again = STATE.root_name == root.name_full and now - STATE.stamp <= WINDOW
    if not preview:
        STATE.root_name, STATE.stamp = root.name_full, now
    if root == ob or again:
        return target, False
    return replace(target, object_name=root.name_full, linked=is_linked(root)), True


def released(now=None):
    """A grab of the last hierarchy let go: the window runs from here."""
    STATE.stamp = time.perf_counter() if now is None else now


def is_tap(seconds, distance):
    """A smart first grab that was only a tap (so the rig is put back and no undo step is made)."""
    return seconds < QUICK_GRAB_SECONDS and distance < size_state.scaled(QUICK_GRAB_DISTANCE)
