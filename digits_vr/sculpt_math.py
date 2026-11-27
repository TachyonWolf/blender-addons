# SPDX-License-Identifier: GPL-3.0-or-later
"""Sculpt mode without bpy: which meshes and brushes a VR stroke may touch (and how), where the dabs go, trigger
pressure, the size gesture, and the pixel Blender's stroke needs. Tested headless."""
import math

import numpy as np

from .sculpt_drag_math import DRAG_BRUSHES

# How a stroke runs. LIVE: a native call each headset frame, one undo step at release (sculpt_commit.py). RELEASE: only
# the path shows; one native call per run of samples at release. BLOCKED: nothing, with a reason.
LIVE, RELEASE, BLOCKED = 'LIVE', 'RELEASE', 'BLOCKED'

# Candidates: brushes the one-call-per-frame probe found usable (docs/spikes/SPIKE-SCULPT.md "Brushes"). PROVEN: those
# that passed their own ox check with live strokes and undo. Only PROVEN ones work; move a type there when it passes.
DIRECTION_BRUSHES = frozenset({'PLANE', 'PINCH', 'CLAY_STRIPS'})       # read the mouse's motion: see steps_along
CANDIDATES = frozenset({'DRAW', 'DRAW_SHARP', 'CLAY', 'INFLATE', 'BLOB', 'CREASE', 'SMOOTH', 'MASK'}) | DIRECTION_BRUSHES
MASK_BRUSHES = frozenset({'MASK'})
# PROVEN: Draw, Smooth, Mask, Clay, Inflate [coordinator, 2026-11-25]; the other candidates passed one ox run each
# (STATUS "Brushes allowed") and joined with the brush menu
PROVEN = CANDIDATES
STROKE_METHODS = frozenset({'SPACE', 'DOTS', 'AIRBRUSH'})      # the others need the mouse or one unbroken stroke
MAX_DABS = 12                  # per frame: a faster hand spreads them wider
JUMP_RADII = 6.0               # a tip that jumps this many radii (and JUMP_METERS) in a frame is not joined by dabs
JUMP_METERS = 0.3
MIN_SPACING = 0.05             # of the diameter
PULL, FULL = 0.4, 1.0          # trigger amounts (router.button_edge lets go at 0.4): lightest, full pressure
LIGHTEST = 0.2
SIZE_RANGE = (0.001, 5.0)      # m, diameter (the B gesture: in your space; the brush slider: world)
SIZE_DOUBLES = 0.10            # m of hand motion (in your space) that doubles the size


# The brush menu: groups of (Essentials brush name, brush type). The name picks the brush. Elastic Snake Hook is left
# out: its Kelvinlet mode is not built (kind_for refuses it by its setting).
NOT_YET = "Not in VR yet"
MENU = (("Draw", (("Draw", 'DRAW'), ("Draw Sharp", 'DRAW_SHARP'), ("Clay", 'CLAY'), ("Clay Strips", 'CLAY_STRIPS'),
                  ("Inflate/Deflate", 'INFLATE'), ("Blob", 'BLOB'), ("Crease Polish", 'CREASE'), ("Crease Sharp", 'CREASE'),
                  ("Layer", 'LAYER'))),
        ("Flatten", (("Flatten/Contrast", 'PLANE'), ("Fill/Deepen", 'PLANE'), ("Scrape/Fill", 'PLANE'),
                     ("Pinch/Magnify", 'PINCH'))),
        ("Shape / Drag", (("Grab", 'GRAB'), ("Elastic Grab", 'ELASTIC_DEFORM'), ("Snake Hook", 'SNAKE_HOOK'), ("Pose", 'POSE'),
                          ("Thumb", 'THUMB'), ("Nudge", 'NUDGE'), ("Boundary", 'BOUNDARY'))),
        ("Smooth and Mask", (("Smooth", 'SMOOTH'), ("Mask", 'MASK'))))
PLAIN_FACTS = (("keys", "shape keys"), ("multires", "Multires"), ("dyntopo", "Dyntopo"))


def _title(brush_type):
    return brush_type.replace('_', ' ').title() or 'none'


def menu_note(entry, facts):
    """The short line on a brush's card in the menu: why it can't sculpt this mesh ("" = it can, or the reason is the
    mesh's own and the notice line says it). entry: a MENU item; facts: the mesh's (kind_for)."""
    brush_type = entry[1]
    if brush_type not in PROVEN | DRAG_BRUSHES:
        return NOT_YET
    if brush_type in DRAG_BRUSHES:
        return next(("Not with " + name for fact, name in PLAIN_FACTS if facts.get(fact)), "")
    return ""


def _drag_kind(facts):
    """Our own drag brushes (sculpt_drag_math.py) write the base mesh's positions: plain meshes only, always live."""
    name = _title(facts["brush_type"])
    if facts.get("drag_setting"):
        return BLOCKED, f"Sculpt: this {name} brush's {facts['drag_setting']} does not work in VR"
    if not facts["vertices"]:
        return BLOCKED, "Sculpt: this mesh has no vertices"
    for fact, label in PLAIN_FACTS:
        if facts[fact]:
            return BLOCKED, f"Sculpt: {name} does not work with {label} in VR"
    return LIVE, ""


def kind_for(facts):
    """(LIVE / RELEASE / BLOCKED, reason) for `facts` = {"mesh", "editable", "others", "locked_key", "brush_type",
    "stroke_method", "stabilized", "multires_off", "multires", "dyntopo", "keys", "vertices", "drag_setting"}. Any doubt:
    not LIVE."""
    if not facts["mesh"]:
        return BLOCKED, "Sculpt: the active object is not a mesh"
    if not facts["editable"]:
        return BLOCKED, "Sculpt: this mesh is linked, it can't be changed here"
    if facts["others"]:
        return BLOCKED, "Sculpt: another object is in Sculpt mode too. Leave it first"
    if facts["locked_key"]:
        return BLOCKED, "Sculpt: the active shape key is locked or muted"
    if facts["multires_off"]:
        return BLOCKED, "Sculpt: Multires is off in VR. Show it (Selected tab, Modifiers)"
    if facts["brush_type"] in DRAG_BRUSHES:
        return _drag_kind(facts)
    if facts["brush_type"] in CANDIDATES - PROVEN:
        return BLOCKED, f"Sculpt: the brush type {_title(facts['brush_type'])} is not tested in VR yet"
    if facts["brush_type"] not in PROVEN:
        return BLOCKED, f"Sculpt: the brush type {_title(facts['brush_type'])} does not work in VR"
    if facts["stroke_method"] not in STROKE_METHODS:
        return BLOCKED, f"Sculpt: a brush with stroke method {facts['stroke_method'].replace('_', ' ').title()} does not work in VR"
    if facts["stabilized"]:
        return BLOCKED, "Sculpt: a plane brush with Stabilize on does not work in VR"
    if not facts["vertices"]:
        return BLOCKED, "Sculpt: this mesh has no vertices"
    for fact, name in PLAIN_FACTS:
        if facts[fact]:
            return RELEASE, f"Sculpt: no live preview with {name}. The stroke is made when you let go"
    return LIVE, ""


def spacing(percent, diameter):
    """World distance between dabs."""
    return max(percent / 100.0, MIN_SPACING) * diameter


def dabs(last, now, gap, radius, per_frame=MAX_DABS):
    """World points from `last` (not included) to at most `now`, `gap` apart; [now] after a jump (teleport, turn)."""
    if last is None:
        return [tuple(now)]
    distance = math.dist(last, now)
    if distance > max(JUMP_RADII * radius, JUMP_METERS):
        return [tuple(now)]
    count = int(distance / gap + 1e-6)
    if count < 1:
        return []
    step = gap / distance if count <= per_frame else 1.0 / per_frame
    return [tuple(a + (b - a) * step * (index + 1) for a, b in zip(last, now)) for index in range(min(count, per_frame))]


def pressure(amount):
    share = min(max((amount - PULL) / (FULL - PULL), 0.0), 1.0)
    return LIGHTEST + (1.0 - LIGHTEST) * share


def sized(start_diameter, lift, size=1.0):
    """The size gesture: the hand moved `lift` metres up (in your space) since B went down. The world diameter is kept
    within SIZE_RANGE in YOUR space (`size` = your size): at 100x an unscaled 5 m cap was a 5 cm bubble to you."""
    return min(max(start_diameter * 2.0 ** (lift / SIZE_DOUBLES), SIZE_RANGE[0] * size), SIZE_RANGE[1] * size)


def mean_scale(matrix_rows):
    """The scale Blender divides a brush radius by: the mean of the three axis lengths of a 3x3 (rows)."""
    return max(float(np.linalg.norm(np.asarray(matrix_rows, float), axis=0).mean()), 1e-9)


def pick_pixel(points, normals, perspective, view_direction, width, height, margin=8.0):
    """The pixel of the best face centre to start a stroke ray at: inside the region and the clip range, facing the
    view, nearest the region's centre; None when none. points / normals: (n, 3) world, perspective: 4x4 rows,
    view_direction: from the viewer into the scene."""
    points = np.asarray(points, float)
    clip = np.c_[points, np.ones(len(points))] @ np.asarray(perspective, float).T
    in_front = clip[:, 3] > 1e-6
    w = np.where(in_front, clip[:, 3], 1.0)[:, None]
    ndc = clip[:, :3] / w
    pixel = (ndc[:, :2] * 0.5 + 0.5) * (width, height)
    inside = (in_front & (np.abs(ndc[:, 2]) < 1.0) & (pixel[:, 0] > margin) & (pixel[:, 0] < width - margin)
              & (pixel[:, 1] > margin) & (pixel[:, 1] < height - margin))
    if not inside.any():
        return None
    facing = np.abs(np.asarray(normals, float) @ np.asarray(view_direction, float)) > 0.1
    chosen = inside & facing if (inside & facing).any() else inside
    distance = ((pixel - (width / 2, height / 2)) ** 2).sum(axis=1)
    distance[~chosen] = np.inf
    return tuple(float(value) for value in pixel[distance.argmin()])


def near_box(point, low, high, reach):
    return all(a - reach <= value <= b + reach for value, a, b in zip(point, low, high))


def touches(surface, points, reach):
    """Any of `points` (n, 3) within `reach` of a vertex in `surface` (flat float array)."""
    flat = surface.reshape(-1, 3)
    for point in points:
        offset = flat - point
        if float(np.einsum('ij,ij->i', offset, offset).min()) <= reach * reach:
            return True
    return False


def steps_along(pixel, direction, count, step=3.0):
    """`count` pixels from the hit pixel along the hand's motion on the desktop screen. Direction brushes read the
    mouse's motion, and the first pixel of a stroke must hit the mesh: the rest only give the direction."""
    length = math.hypot(*direction)
    unit = (direction[0] / length, direction[1] / length) if length > 1e-9 else (1.0, 0.0)
    return [(pixel[0] + unit[0] * step * index, pixel[1] + unit[1] * step * index) for index in range(count)]
