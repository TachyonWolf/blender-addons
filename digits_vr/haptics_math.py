# SPDX-License-Identifier: GPL-3.0-or-later
"""Which buzz plays, and the target-change check. Pure Python (no bpy), tested headless.

ONE decision for every buzz (action_map.buzz calls `choose`): the Haptics pop-up's settings (View tab) pick the pulse.
Kinds: LEGACY = today's buzzes (refused, limits, ticks); GRAB = the grab buzz; POINT = the new pulse when what a
laser or hand points at changes. While the master is off, LEGACY and GRAB play exactly as before and POINT is silent
[user, 2026-11-25]."""

LEGACY, GRAB, POINT = 'legacy', 'grab', 'point'
POINT_PULSE = (0.03, 0.6)      # (seconds, amplitude) at strength 1: a tick you can feel (0.012 s at 0.3 was too weak)
GRAB_PULSE = (0.08, 1.0)       # longer and stronger: clearly not the point tick
STRENGTH_RANGE = (0.1, 1.0)


def choose(kind, duration, amplitude, get):
    """(duration, amplitude) to play, or None for silence. `get(name)` reads a setting."""
    if not get("haptics"):
        return None if kind == POINT else (duration, amplitude)
    strength = get("haptics_strength")
    if kind == POINT:
        base, enabled = POINT_PULSE, get("haptics_point")
    elif kind == GRAB:
        base, enabled = GRAB_PULSE, get("haptics_grab")
    else:
        base, enabled = (duration, amplitude), get("haptics_other")
    if not enabled:
        return None
    return base[0], min(1.0, base[1] * strength)


def target_changed(previous_key, key):
    """True when a hand now points at something new: a different target, not when it points at nothing."""
    return key is not None and key != previous_key
