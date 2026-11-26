# SPDX-License-Identifier: GPL-3.0-or-later
"""The select bubble: a sphere at the fingertip (hands.tool_point) that paints the selection while the trigger is held.
On in Edit mode when the active tool is Select, in Object / Pose mode when the "Select bubble" toggle is on. Everything
whose point is inside the sphere is added as the hand moves (A held: removed instead); what "inside" means per mode is
box_select (the same tests as the box). B held + hand up / down resizes it (size_gesture, as in Sculpt mode); the size is
the setting `select_bubble_diameter`, written when B is let go. One stroke = ONE undo step "VR Select Bubble", none when
nothing changed. The grip still grabs. Cost per tick: one sphere test on cached numpy points, only while the trigger is held
and the hand or size moved."""
import bpy

from . import box_math, box_select, edit_pick, router, sculpt_draw, settings
from .action_map import RIGHT, buzz, value
from .hands import tool_point
from .runtime import RUNTIME
from .size_gesture import SizeGesture

UNDO_NAME = "VR Select Bubble"


class View:
    """Written by update each tick, read by the overlay's draw."""
    active = False
    diameter = 0.15      # world m
    colour = sculpt_draw.NORMAL
    sizing = False
    hand = None          # the painting hand


class Stroke:
    """One running stroke."""

    def __init__(self, hand):
        self.hand, self.generation, self.mode = hand, RUNTIME.generation, bpy.context.mode
        self.cache = {}          # box_select: the object / bone points, worked out once
        self.changed = False
        self.last = None         # (centre, diameter, remove) of the last test: nothing moved, nothing to test


class State:
    stroke = None
    size = SizeGesture()


STATE = State()


def active():
    """The bubble is the trigger's tool now."""
    return View.active


def wanted(context):
    return router.bubble_on(router.mode_kind(context.mode), settings.get("edit_tool"), settings.get("select_bubble"))


def begin(context, state, hand):
    """Trigger pull with the bubble on."""
    if STATE.stroke is not None or router.mode_kind(context.mode) == router.EDIT and edit_pick.refused(context):
        buzz(context, state, hand)
        return
    STATE.stroke = Stroke(hand)
    View.hand = hand
    _paint(context, state)


def _paint(context, state):
    stroke = STATE.stroke
    centre = tuple(tool_point(context, state, stroke.hand))
    remove = value(context, state, "toggle", RIGHT) > 0.5
    now = (centre, View.diameter, remove)
    if now == stroke.last:
        return
    stroke.last = now
    View.colour = sculpt_draw.colour_of(remove, False)
    if box_select.apply(context, box_math.Sphere(centre, View.diameter / 2.0), remove, stroke.cache):
        stroke.changed = True


def update(context, state):
    """Once per session tick. True while a stroke or the size gesture runs."""
    View.active = wanted(context)
    stroke = STATE.stroke
    if stroke is not None:
        if stroke.generation != RUNTIME.generation or stroke.mode != context.mode:
            _forget()                   # an undo / redo or a mode change: nothing of ours to keep
        elif not View.active:
            end(context)
        else:
            _paint(context, state)
    if not View.active:
        STATE.size.start, View.sizing = None, False
        return False
    return _resize(context, state) or STATE.stroke is not None


def _resize(context, state):
    was_sizing = View.sizing
    if not was_sizing:
        View.diameter = settings.get("select_bubble_diameter")
        View.colour = sculpt_draw.colour_of(value(context, state, "toggle", RIGHT) > 0.5, False)
    diameter = STATE.size.update(context, state, lambda: View.diameter, enabled=STATE.stroke is None)
    View.sizing = diameter is not None
    if View.sizing:
        View.diameter = diameter
    elif was_sizing:
        settings.put("select_bubble_diameter", View.diameter)
    return View.sizing


def _forget():
    stroke, STATE.stroke = STATE.stroke, None
    View.hand = None
    return stroke


def end(context=None):
    """Trigger let go, pause, undo / mode button, session end: the stroke is ONE undo step (none when nothing changed)."""
    stroke = _forget()
    if stroke is not None and stroke.changed and stroke.generation == RUNTIME.generation:
        from .tools import push_undo
        push_undo(UNDO_NAME)


def visible():
    return View.active and bool(sculpt_draw.ring_hands(View.hand, View.sizing))


def lines(aims, make_batch):
    """[(batch, colour, width, model matrix, in front)] for the overlay: the same ball as the sculpt brush."""
    if not visible():
        return []
    return sculpt_draw.ring_lines(aims, make_batch, sculpt_draw.ring_hands(View.hand, View.sizing), View.diameter, View.colour)


def teardown(commit=True):
    """Session over (or file load: commit=False)."""
    if commit:
        end()
    _forget()
    STATE.size.start = None
    View.active = View.sizing = False
