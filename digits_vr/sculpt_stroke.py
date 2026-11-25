# SPDX-License-Identifier: GPL-3.0-or-later
"""Sculpt mode: the trigger held = a stroke of Blender's own active brush at the fixed point in front of the hand
(hands.tool_point). A held = Smooth, grip
held = Invert, B held + hand up / down = brush size.

LIVE (plain meshes): each headset frame one native call WITHOUT an undo step; at release sculpt_commit makes the whole
change one native Sculpt step. Smooth and Invert may change during it. RELEASE (shape keys, Multires, Dyntopo): the path
shows, ONE native call at release: Smooth / Invert are taken at the press and stay (one stroke = one undo step). BLOCKED: a buzz and the reason on the desk. sculpt_math.kind_for decides.

Blender keeps a pending undo step after a call without undo. touch_nothing() after each call keeps it empty. Every way a
stroke can end uses it up, so it never reaches the user's next action: a commit; or (nothing to keep) an empty step that
is undone at once; or an undo from the desktop, which then takes back that empty step instead of the user's history.
An undo during a stroke cancels the stroke."""
import time

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Vector

from . import desk_qol_math, sculpt_brush, sculpt_commit, sculpt_draw, sculpt_math as math_, sculpt_mesh
from .action_map import RIGHT, buzz, value
from .context_helper import view3d_override_showing
from .hands import tool_point
from .perf import TIMINGS
from .router import SCULPT
from .runtime import RUNTIME
from .size_gesture import SizeGesture
from .size_state import SIZE
from .stroke_recorder import StrokeRecorder

FALLBACK_DIAMETER = 0.1     # m
CUT_NOTE = "Sculpt: stroke cancelled, the mode or mesh changed"
CUT = "VR Sculpt Stroke (cancelled)"


class Stroke:
    """One running stroke."""

    def __init__(self, context, ob, kind, view, diameter, brush):
        self.object_name, self.kind, self.view, self.diameter = ob.name_full, kind, view, diameter
        self.brush_name, self.brush_type = brush.name_full, brush.sculpt_brush_type
        self.gap = math_.spacing(brush.spacing, diameter)
        self.inverse = ob.matrix_world.inverted_safe()
        self.box = sculpt_mesh.evaluated_box(ob)
        self.reach = diameter / sculpt_brush.object_scale(ob)
        self.layer = sculpt_commit.Layer(self.brush_type in math_.MASK_BRUSHES)
        self.start = self.layer.read(ob.data) if kind == math_.LIVE else None
        self.last = self.start          # the array as our last call left it
        self.last_point = None          # world: the last dab
        self.called = False             # Blender holds a pending undo step
        self.surface = sculpt_mesh.drawn_points(context, ob) if kind == math_.LIVE else None     # until the first contact
        self.last_operator = _last_operator(context)
        self.samples = []               # RELEASE: [(world point, pressure)]
        self.began = time.perf_counter()
        self.latched = None             # RELEASE: (invert, smooth) at the press
        self.dropped = False            # an undo took the start away: nothing to keep

    def object(self):
        return bpy.data.objects.get(self.object_name)

    def valid(self, context):
        """Still the mesh and mode the stroke began with."""
        ob = self.object()
        return (ob is not None and context.mode == SCULPT and context.active_object == ob
                and (self.start is None or len(ob.data.vertices) * self.layer.width == len(self.start)))


def _last_operator(context):
    """Something that changes when an operator with its own undo step ran (a desktop action)."""
    operators = context.window_manager.operators
    return (len(operators), operators[-1].as_pointer()) if len(operators) else None


class State:
    recorder = StrokeRecorder(point_of=tool_point)
    stroke = None
    grips = set()           # hands whose grip inverts
    size = SizeGesture()    # B held: the brush size


STATE = State()


def running():
    return STATE.stroke is not None


def tell(text, context=None, state=None, hand=None):
    if text:
        desk_qol_math.NOTICE.show(text, time.perf_counter())
    if hand is not None:
        buzz(context, state, hand)


def grip(hand, held):
    (STATE.grips.add if held else STATE.grips.discard)(hand)


def _modifiers(context, state):
    """(invert, smooth) now. Smooth wins, as on the desktop."""
    stroke = STATE.stroke
    if stroke is not None and stroke.latched is not None:
        return stroke.latched
    masking = stroke is not None and stroke.layer.is_mask        # Smooth with the Mask brush: not proven
    smooth = value(context, state, "toggle", RIGHT) > 0.5 and not masking
    return bool(STATE.grips) and not smooth, smooth


def begin(context, state, hand):
    """Trigger pull in Sculpt mode."""
    if STATE.stroke is not None:
        buzz(context, state, hand)              # one stroke at a time
        return
    ob, brush = context.active_object, sculpt_brush.active()
    kind, reason = math_.kind_for(sculpt_mesh.facts(context, ob, brush))
    tell(reason)
    if kind == math_.BLOCKED:
        buzz(context, state, hand)
        return
    view = sculpt_mesh.DesktopView(context, ob)
    if not view.usable:
        tell("Sculpt: show the object in a desktop 3D View", context, state, hand)
        return
    stroke = Stroke(context, ob, kind, view, sculpt_brush.diameter(ob, view.override), brush)
    if kind == math_.RELEASE:
        stroke.latched = _modifiers(context, state)
    STATE.stroke = stroke
    STATE.recorder.min_distance = stroke.gap / SIZE.factor     # the recorder scales it by your size again
    STATE.recorder.begin(hand)
    sculpt_draw.View.stroke_hand, sculpt_draw.View.path = hand, []
    if undo_pre not in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.append(undo_pre)
    _sample(context, state, first=True)


def _sample(context, state, first=False):
    stroke = STATE.stroke
    point = STATE.recorder.sample(context, state, once_per_frame=not first)
    if point is None:
        return
    points = math_.dabs(stroke.last_point, point, stroke.gap, stroke.diameter / 2)
    if not points:
        return
    direction = Vector(points[-1]) - Vector(stroke.last_point) if stroke.last_point is not None else Vector()
    stroke.last_point = STATE.recorder.last_point = points[-1]
    pressure = math_.pressure(RUNTIME.hands[STATE.recorder.hand].trigger_amount)
    modes = _modifiers(context, state)
    if stroke.kind == math_.RELEASE:
        stroke.samples += [(spot, pressure) for spot in points]
        sculpt_draw.View.path += points
        return
    _call(context, stroke, points, pressure, modes, direction)


def _elements(stroke, points, pressures, direction):
    """The stroke list for world `points`. A direction brush gets one extra first element (Blender skips its first
    dab: no motion yet)."""
    if stroke.brush_type in math_.DIRECTION_BRUSHES:
        points, pressures = [points[0]] + list(points), [pressures[0]] + list(pressures)
        pixels = math_.steps_along(stroke.view.pixel, stroke.view.on_screen(direction), len(points))
    else:
        pixels = [stroke.view.pixel] * len(points)
    return [sculpt_brush.element(tuple(stroke.inverse @ Vector(point)), pixel, index * 0.01, pressure, index == 0)
            for index, (point, pixel, pressure) in enumerate(zip(points, pixels, pressures))]


def _native(stroke, elements, push, modes):
    began = time.perf_counter()
    try:
        with sculpt_brush.world_size(stroke.object(), stroke.diameter):
            sculpt_brush.stroke(elements, push=push, invert=modes[0], smooth=modes[1])
            if not push:
                sculpt_brush.touch_nothing(stroke.view.pixel)
    finally:
        TIMINGS.add_native("sculpt", (time.perf_counter() - began) * 1000.0)


def _call(context, stroke, points, pressure, modes, direction):
    """One live call (no undo step)."""
    ob = stroke.object()
    if not any(math_.near_box(stroke.inverse @ Vector(point), *stroke.box, stroke.reach) for point in points):
        return                                  # in the air
    if not stroke.called:
        local = np.array([stroke.inverse @ Vector(point) for point in points], np.float32)
        if not math_.touches(stroke.surface, local, stroke.reach / 2):
            return                              # not at the surface yet: no call, so no undo step to clear either
        stroke.surface = None
    now = stroke.layer.read(ob.data)
    if not sculpt_commit.same(now, stroke.last):
        stroke.start = now                      # someone else changed the mesh: keep what they did out of our step
        tell("Sculpt: the mesh was changed on the desktop during this stroke")
    stroke.view.refresh(context, ob)
    if not stroke.view.usable:
        return
    with context.temp_override(**stroke.view.override):
        stroke.called = True
        _native(stroke, _elements(stroke, points, [pressure] * len(points), direction), False, modes)
    stroke.last = stroke.layer.read(ob.data)


def update(context, state):
    """Once per session tick. True while a stroke or the size gesture runs."""
    active = context.mode == SCULPT
    view = sculpt_draw.View
    view.active = active
    if not active and STATE.stroke is None:
        STATE.grips.clear()
        STATE.size.start = None
        view.sizing = False
        return False
    if STATE.stroke is not None:
        if STATE.stroke.dropped or STATE.recorder.stale:
            _cancelled()
        elif not STATE.stroke.valid(context):
            _cut(context, CUT_NOTE)
        elif _brush_changed(STATE.stroke):
            end(context)                        # kept as one step; the new brush starts with the next press
        else:
            _sample(context, state)
    if active:
        resizing = _size_gesture(context, state)
        _show(context, state)
        return STATE.stroke is not None or resizing
    return False


def _brush_changed(stroke):
    brush = sculpt_brush.active()
    return brush is None or brush.name_full != stroke.brush_name


def _show(context, state):
    view = sculpt_draw.View
    if STATE.stroke is not None:
        view.diameter = STATE.stroke.diameter
    elif sculpt_draw.visible():
        view.diameter = _diameter_now(context)
    if sculpt_draw.visible():
        view.colour = sculpt_draw.colour_of(*_modifiers(context, state))


def _diameter_now(context):
    """World size of the next stroke (a fallback while no desktop 3D View shows the object)."""
    if sculpt_brush.Size.diameter is not None:
        return sculpt_brush.Size.diameter
    ob = context.active_object
    found = view3d_override_showing(context, ob) if ob is not None else None
    return sculpt_brush.diameter(ob, found) if found and sculpt_brush.active() is not None else FALLBACK_DIAMETER


def _size_gesture(context, state):
    """B held: the hand's height since the press sets the size (up = bigger, 10 cm doubles it)."""
    diameter = STATE.size.update(context, state, lambda: _diameter_now(context), enabled=STATE.stroke is None)
    sculpt_draw.View.sizing = diameter is not None
    if diameter is not None:
        sculpt_brush.Size.diameter = diameter
    return diameter is not None


def _forget():
    stroke, STATE.stroke = STATE.stroke, None
    STATE.recorder.stop()
    sculpt_draw.View.stroke_hand, sculpt_draw.View.path = None, []
    if undo_pre in bpy.app.handlers.undo_pre:
        bpy.app.handlers.undo_pre.remove(undo_pre)
    return stroke


def end(context=None):
    """Trigger let go, undo button (which then undoes it), mode button, session end: keep the stroke as one undo step."""
    if STATE.stroke is None:
        return
    context = context or bpy.context
    stroke = STATE.stroke
    if stroke.dropped or STATE.recorder.stale:
        _cancelled()
        return
    if not stroke.valid(context):
        _cut(context, CUT_NOTE)
        return
    _forget()
    ob = stroke.object()
    with context.temp_override(**stroke.view.override):
        if stroke.kind == math_.RELEASE:
            _release_call(stroke)
        elif stroke.called:
            _commit(ob, stroke)


def _commit(ob, stroke):
    live = stroke.layer.read(ob.data)
    if sculpt_commit.same(live, stroke.start):
        _clear_pending(stroke)                  # nothing changed
        return
    began = time.perf_counter()
    try:
        sculpt_commit.commit(ob, stroke.layer, stroke.start, live,
                             build_bvh=lambda: sculpt_brush.touch_nothing(stroke.view.pixel))
    except sculpt_commit.CommitError as error:
        _clear_pending(stroke)
        print(f"digits_vr: sculpt stroke not kept: {error}")
        tell("Sculpt: the stroke could not be kept. The mesh is as it was before it")
    TIMINGS.add_native("sculpt_commit", (time.perf_counter() - began) * 1000.0)


def _clear_pending(stroke):
    """Use up Blender's pending step and leave no undo step: push it empty, then undo that (in the window's own event
    loop: an undo can't run here). The caller has the 3D View override."""
    sculpt_brush.touch_nothing(stroke.view.pixel, push=True)
    bpy.ops.digits_vr.history('INVOKE_DEFAULT', redo=False)


def _release_call(stroke):
    if not stroke.samples:
        return
    points, pressures = zip(*stroke.samples)
    direction = Vector(points[-1]) - Vector(points[0])
    _native(stroke, _elements(stroke, points, pressures, direction), True, stroke.latched)


def _cut(context, reason):
    """The mode, object or mesh changed under the stroke. Same vertices: the mesh goes back to the stroke's start, as
    nothing recorded the change. Blender's pending step: the desktop operator that did it has used it up; without one
    (a script) a push does."""
    from .tools import push_undo
    stroke = _forget()
    ob = stroke.object()
    if stroke.called and ob is not None:
        sculpt_commit.restore(ob, stroke.layer, stroke.start)
        if _last_operator(context) == stroke.last_operator:
            push_undo(CUT)
        if context.mode != SCULPT:
            push_undo(CUT)          # the used-up step is an empty Sculpt one: without a full step here, undoing the
                                    # next action would land on it and not bring objects back
    tell(reason)


@persistent
def undo_pre(*_args):
    """Before an undo someone else started (desktop Ctrl+Z; our own button ends the stroke first): cancel the stroke.
    The start state goes back, and Blender's pending step is pushed (empty): the undo then takes back that one, so the
    user's earlier history stays."""
    stroke = STATE.stroke
    if stroke is None or stroke.dropped:
        return
    stroke.dropped = True
    ob = stroke.object()
    if ob is None or ob.mode != SCULPT:
        return
    try:
        with bpy.context.temp_override(**stroke.view.override):
            if stroke.called:
                sculpt_commit.restore(ob, stroke.layer, stroke.start)
            else:
                sculpt_brush.touch_nothing(stroke.view.pixel)
            bpy.ops.ed.undo_push(message=CUT)
    except (RuntimeError, TypeError, ReferenceError) as error:
        print(f"digits_vr: sculpt stroke before an undo: {error}")


def _cancelled():
    """The undo (or redo) ran: the stroke is gone and nothing is pending."""
    _forget()
    tell("Sculpt: stroke cancelled")


def teardown(commit=True):
    """Session over (or file load: commit=False)."""
    if STATE.stroke is not None:
        if commit:
            try:
                end()
            except (RuntimeError, ReferenceError, AttributeError, TypeError) as error:
                print(f"digits_vr: sculpt stroke at the session end: {error}")
        _forget()
    STATE.grips.clear()
    STATE.size.start = None
    sculpt_brush.Size.diameter = None
    sculpt_draw.clear()
