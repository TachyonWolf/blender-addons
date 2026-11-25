# SPDX-License-Identifier: GPL-3.0-or-later
"""Finger poke maths: when a fingertip pressing into a panel fires a press. Pure Python (no bpy), tested headless.

Depth is how far the tip is in front of the panel plane, in YOUR space metres (positive = in front, negative = behind).
A fingertip fires once when it reaches PRESS_DEPTH over a button; it fires again only after it came back out past
RELEASE_DEPTH (or never was in: a new tip starts disarmed). Sliding in over another key does not fire (release first)."""
from .hand_model import FINGERS, index_extended

PRESS_DEPTH = 0.010          # a tip this close to the screen (or past it) presses
RELEASE_DEPTH = 0.030        # back out to this far in front: ready to press again
BACK_LIMIT = 0.060           # a tip further behind than this did not come from the front: it never fires
POINTER, ALL, NONE = 'POINTER', 'ALL', 'NONE'
CHOICES = ((POINTER, "Pointer"), (ALL, "All"), (NONE, "None"))


def poking_fingers(choice, trigger):
    """The fingertips that can press, for the setting: Pointer = the index while its trigger is not pulled, All = every
    fingertip, None = none (the laser only)."""
    if choice == ALL:
        return FINGERS
    if choice == POINTER and index_extended(trigger):
        return ('index',)
    return ()


def poke_step(armed, widget_id, depth):
    """One tick of one fingertip over one panel: (fire, armed). `widget_id` = the button under the tip (None = none)."""
    if depth > RELEASE_DEPTH:
        return False, True
    if depth < -BACK_LIMIT:
        return False, False
    if widget_id is not None and armed and depth <= PRESS_DEPTH:
        return True, False
    return False, armed
