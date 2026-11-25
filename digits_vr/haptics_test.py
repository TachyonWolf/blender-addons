# SPDX-License-Identifier: GPL-3.0-or-later
"""The Haptics pop-up's Test buttons [user, 2026-11-25]: a full-strength buzz per hand, the point tick and the grab pulse,
through the same call as every real pulse. They ignore the Haptics toggles."""
import time

from . import action_map, desk_layout, desk_qol_math, haptics_math
from .hands import session_state

PULSES = {"right": (1.0, 1.0), "left": (1.0, 1.0), "point": haptics_math.POINT_PULSE, "grab": haptics_math.GRAB_PULSE}


def run(context, route):
    """Play one test. False outside a VR session."""
    state = session_state(context)
    if state is None:
        return False
    hands = {"right": (action_map.RIGHT,), "left": (action_map.LEFT,)}.get(route, action_map.HANDS)
    sent = all([action_map.play_pulse(context, state, hand, *PULSES[route]) for hand in hands])
    label = dict(desk_layout.HAPTIC_TESTS)[route]
    desk_qol_math.NOTICE.show(f"Haptics test '{label}': " + ("sent" if sent else "refused by Blender"), time.perf_counter(), seconds=6.0)
    return True
