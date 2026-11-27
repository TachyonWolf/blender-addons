# SPDX-License-Identifier: GPL-3.0-or-later
"""The size gesture of the drawing tools: while the Annotate tool is lit or Draw mode runs on a Grease Pencil object, B held + the
hand's height resizes the brush (size_gesture, as the sculpt brush and the select bubble do). Grease Pencil: the
setting `gp_radius`; Annotate: `annotate_thickness` (whole pixels). The ring at the tip shows the size (sculpt_draw's ring;
Annotate's ring is only a mark, annotate_math.RING_PER_PIXEL). The setting is written when B is let go; the desk's slider
follows. B is not Slow mode meanwhile (controls.py). No resize while a stroke runs."""
from . import annotate, annotate_math, gpencil, gpencil_math, settings, sculpt_draw
from .size_gesture import SizeGesture
from .size_state import SIZE


class View:
    """Written by update each tick, read by the overlay's draw."""
    active = False
    diameter = 0.0       # world m
    sizing = False
    annotating = False   # the Annotate tool is lit (else Draw mode)


STATE = SizeGesture()


def active():
    """A drawing tool is the trigger's tool now (B is its size gesture)."""
    return View.active


def _is_annotate():
    return View.annotating


def _wanted(context):
    return annotate.is_on(context) or context.mode == gpencil.DRAW_MODE and gpencil.active_object(context) is not None


def _setting_diameter():
    if _is_annotate():
        return annotate_math.ring_diameter(settings.get("annotate_thickness"), SIZE.factor)
    return gpencil_math.diameter_of_radius_cm(settings.get("gp_radius") * 100.0, SIZE.factor)


def _write(diameter):
    if _is_annotate():
        settings.put("annotate_thickness", annotate_math.thickness_of_diameter(diameter, SIZE.factor))
    else:
        settings.put("gp_radius", gpencil_math.radius_of_diameter(diameter, SIZE.factor))


def update(context, state):
    """Once per session tick. True while the size gesture runs."""
    View.active, View.annotating = _wanted(context), annotate.is_on(context)
    if not View.active:
        STATE.start, View.sizing = None, False
        return False
    was_sizing = View.sizing
    drawing = annotate.STATE.drawing or gpencil.STATE.drawing
    diameter = STATE.update(context, state, _setting_diameter, enabled=not drawing)
    View.sizing = diameter is not None
    if View.sizing:
        View.diameter = diameter
        return True
    if was_sizing:
        _write(View.diameter)           # B let go: kept like the desk slider's value
    View.diameter = _setting_diameter()
    return View.sizing


def visible():
    return View.active and bool(sculpt_draw.ring_hands(None, View.sizing))


def lines(aims, make_batch):
    """[(batch, colour, width, model matrix, in front)] for the overlay: the same ball as the sculpt brush."""
    if not visible():
        return []
    return sculpt_draw.ring_lines(aims, make_batch, sculpt_draw.ring_hands(None, View.sizing), View.diameter, sculpt_draw.NORMAL)


def teardown():
    STATE.start, View.active, View.sizing = None, False, False
