# SPDX-License-Identifier: GPL-3.0-or-later
"""Finger poke (bpy side): a fingertip pushed into a button of any open panel (desk, tool options, viewpoints,
keyboard) presses it, like the laser + trigger. The setting `finger_poke` says which tips can press (Pointer: the
index while its trigger is not pulled; All; None). Each fingertip keeps its own armed state (poke_math.poke_step), so
nothing fires twice. Runs from panels.tick, so with every panel closed it costs nothing."""
from mathutils import Vector

from . import hand_state, panel_layout as layout, poke_math, settings
from .action_map import HANDS
from .hand_model import fingertips
from .hands import drawn_hand_pose
from .perf import TIMINGS
from .runtime import RUNTIME
from .size_state import SIZE
from .transform_math import hand_matrix

REACH = 0.25     # m (your space): further than any fingertip is from the grip (about 0.16)
_tip_cache = {}  # hand -> (key, hand-space fingertips)
_armed = {}      # (panel name, hand, finger) -> bool


def reset():
    _armed.clear()


def _tips_world(context, state, hand, names):
    matrix = hand_matrix(*drawn_hand_pose(context, state, HANDS.index(hand)))
    side = 1.0 if hand == HANDS[1] else -1.0
    curls = hand_state.CURLS[hand]
    key = (side, names, tuple(curls.values()))
    if _tip_cache.get(hand, (None,))[0] != key:       # the curls rarely change: keep the hand-space tips
        _tip_cache[hand] = (key, fingertips(side, curls, names))
    tips = _tip_cache[hand][1]
    return {name: matrix @ (Vector(point) * SIZE.factor) for name, point in tips.items()}


def update(context, state, open_panels):
    choice = settings.get("finger_poke")
    if choice == poke_math.NONE or not open_panels:
        return
    with TIMINGS.measure("poke"):
        inverses = None
        for hand in HANDS:
            names = poke_math.poking_fingers(choice, RUNTIME.hands[hand].trigger_amount)
            if not names:
                continue
            if inverses is None:
                inverses = [(panel, panel.state.matrix().inverted_safe(), panel.state.scale) for panel in open_panels if not panel.state.docked]
            grip = Vector(state.controller_grip_location_get(context, HANDS.index(hand)))
            near = []
            for panel, inverse, scale in inverses:
                # cheap test first: a fingertip is within REACH of the grip, so a grip well in front of (or behind) the
                # panel leaves every tip out of range (poke_math.poke_step gives the same answer without the tips)
                grip_depth = (inverse @ grip).z * scale / SIZE.factor
                if grip_depth > REACH:
                    armed = True
                elif grip_depth < -REACH:
                    armed = False
                else:
                    near.append((panel, inverse, scale))
                    continue
                for name in names:
                    _armed[(panel.name, hand, name)] = armed
            if not near:
                continue
            for name, tip in _tips_world(context, state, hand, names).items():
                for panel, inverse, scale in near:
                    _tip_on_panel(context, state, panel, inverse, scale, hand, name, tip)


def _tip_on_panel(context, state, panel, inverse, scale, hand, name, tip):
    local = inverse @ tip
    depth = local.z * scale / SIZE.factor
    pixel_x, pixel_y = panel.spec.local_to_pixel(local.x, local.y)
    widget = layout.hit_test(panel.widgets, pixel_x, pixel_y) if panel.spec.on_body(pixel_x, pixel_y) else None
    if widget is not None and widget.kind in (layout.HANDLE, layout.LABEL, layout.THUMB):
        widget = None
    key = (panel.name, hand, name)
    fire, _armed[key] = poke_math.poke_step(_armed.get(key, False), widget.id if widget else None, depth)
    if widget is not None and -poke_math.BACK_LIMIT <= depth <= poke_math.PRESS_DEPTH:
        panel.state.pressed[hand] = widget.id           # shown pressed while the tip is in
    if fire:
        panel.press(context, state, hand, (widget, pixel_x, 0.0, pixel_y))
