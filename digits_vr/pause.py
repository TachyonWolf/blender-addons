# SPDX-License-Identifier: GPL-3.0-or-later
"""Pause VR tools (DESIGN "Pause VR tools"): a manual pause for when an overlay app (WayVR, the SteamVR dashboard, ...) is
on top and the sticks and triggers are not meant for Blender.

The setting `paused` (desk Pause toggle, sidebar, left stick click) is the one switch. While it is on, controls.update
ignores the scene tools (select, grab, box, draw, sculpt, edit, size gesture) and move.update ignores the sticks; panels
refuse every press except the Pause toggle; the desk dims and shows "Paused"; lasers draw grey. Both stick clicks (so the
desk and the 2 s / 6 s holds), the desk handles and the Pause toggle stay live. Off at every session start and in the
failsafe. Turning it on ends what runs: grabs (edit grabs too), strokes, a box, each as one undo step."""
from . import annotate, gpencil, sculpt_stroke, select_bubble, settings, sticks
from .action_map import HANDS, buzz
from .runtime import RUNTIME

def paused():
    return settings.get("paused")


def toggle(context, state):
    """The left stick click."""
    settings.put("paused", not settings.get("paused"))
    for hand in HANDS:
        buzz(context, state, hand, duration=0.04, amplitude=0.4)


def stop_tools(context):
    """Pause went on: end every running scene action cleanly (one undo step each)."""
    from . import controls              # controls imports this module's setting, not the other way round
    controls.end_all(commit=True)
    annotate.end(context)
    gpencil.end(context)
    sculpt_stroke.end(context)
    select_bubble.end(context)
    for hand_state in RUNTIME.hands.values():
        hand_state.gesture = None
        hand_state.empty_grip = False
    sculpt_stroke.STATE.grips.clear()


def _on_changed(value):
    if value and RUNTIME.active:
        import bpy
        stop_tools(bpy.context)


def reset():
    """Session start: never start paused (a saved or leftover value)."""
    if settings.get("paused"):
        settings.put("paused", False)


if toggle not in sticks.LEFT_CLICK_HANDLERS:
    sticks.LEFT_CLICK_HANDLERS.append(toggle)
if _on_changed not in settings.LISTENERS.setdefault("paused", []):
    settings.LISTENERS["paused"].append(_on_changed)
