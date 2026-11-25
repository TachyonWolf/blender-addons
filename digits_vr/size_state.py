# SPDX-License-Identifier: GPL-3.0-or-later
"""Your size right now (1.0 = 1:1) and the settings that scale with it. Kept apart from user_scale.py (which moves
the viewer and imports the desk and movement), so any module can ask for a scaled distance without a cycle.
Distances in the settings (touch distance, laser length, eye height) are meant in YOUR space: at size 10 they are
10x as long in the world."""
from . import settings


class SizeState:
    factor = 1.0          # you relative to the scene's units; the session starts at 1.0
    gesturing = False     # the two-hand gesture runs (the overlay's frame count paces it)
    original = 1.0        # xr_session_settings.base_scale before we touched it (put back when VR ends)


SIZE = SizeState()


def scaled(value):
    return value * SIZE.factor


def touch_distance():
    return scaled(settings.get("touch_distance"))


def swap_distance():
    return scaled(settings.get("swap_distance"))


def laser_length():
    return scaled(settings.get("laser_length"))


def push_speed():
    return scaled(settings.get("push_speed"))


def eye_height():
    return scaled(settings.get("eye_height"))
