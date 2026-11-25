# SPDX-License-Identifier: GPL-3.0-or-later
"""Your size (user scale): preset sizes, scaling the viewer about a point, the two-hand gesture's size. mathutils
only (no bpy), tested headless.

Size 2 = you are twice as big (the world looks half as big). The viewer shows world point = navigation_location +
navigation_rotation @ (size * point in the tracking space): changing the size about a world `pivot` keeps the pivot
where it is."""
import math

PRESETS = (0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)   # [user, 2026-11-25]
MIN_SIZE, MAX_SIZE = PRESETS[0], PRESETS[-1]
PRESET_TOLERANCE = 0.005          # relative: a size this close to a preset counts as it
MIN_HAND_GAP = 0.02               # m (physical): hands closer than this give no gesture scale


def clamp_size(size):
    return min(MAX_SIZE, max(MIN_SIZE, size))


def active_preset(size):
    """The preset `size` is on, or None (between presets, e.g. after the two-hand gesture)."""
    return next((preset for preset in PRESETS if abs(size / preset - 1.0) <= PRESET_TOLERANCE), None)


def preset_label(preset):
    """'1:1' for 1, else '0.1x', '20x'."""
    return "1:1" if preset == 1.0 else f"{preset:g}x"


def scale_about(location, pivot, old_size, new_size):
    """New navigation location after the size goes from `old_size` to `new_size`, the world point `pivot`
    staying where it is."""
    return pivot - (pivot - location) * (new_size / old_size)


def gesture_size(start_size, start_gap, gap):
    """Size from the two-hand gesture. `start_gap` and `gap` are the hands' distances in your own (physical) space:
    pulling apart makes you smaller, bringing together makes you bigger. Clamped to the preset range."""
    if gap < MIN_HAND_GAP or start_gap < MIN_HAND_GAP:
        return clamp_size(start_size)
    return clamp_size(start_size * start_gap / gap)


def log_fraction(size):
    """0..1 position of `size` on the log scale between the smallest and largest size (for a readout)."""
    return math.log(size / MIN_SIZE) / math.log(MAX_SIZE / MIN_SIZE)
