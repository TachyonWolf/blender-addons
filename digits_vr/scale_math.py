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


def rescale_matrix(matrix, pivot, old_size, new_size):
    """A world matrix after your size went from `old_size` to `new_size` about `pivot`: same place and size relative to
    you (the rule every panel and every cached belt matrix follows)."""
    from mathutils import Matrix
    location, rotation, scale = matrix.decompose()
    return Matrix.LocRotScale(scale_about(location, pivot, old_size, new_size), rotation, scale * (new_size / old_size))


def navigation_after(navigation, rotation, base_location, pivot, old_size, new_size):
    """New navigation location when the size changes and `pivot` stays where it is. The size grows out of the BASE POSE
    (world = navigation + rotation @ (base + size * tracked point)), not out of the navigation location: with the base
    at the scene camera, scaling about the navigation shifted you by the camera's position (user, 2026-11-25)."""
    origin = navigation + rotation @ base_location
    return navigation + scale_about(origin, pivot, old_size, new_size) - origin


def gesture_size(start_size, start_gap, gap, invert=False):
    """Size from the two-hand gesture. `start_gap` and `gap` are the hands' distances in your own (physical) space:
    pulling apart makes you smaller, bringing together makes you bigger (`invert` swaps that). Clamped to the preset range."""
    if gap < MIN_HAND_GAP or start_gap < MIN_HAND_GAP:
        return clamp_size(start_size)
    return clamp_size(start_size * (gap / start_gap if invert else start_gap / gap))


# ---------------------------------------------------------------------------
# The scale meter: a readout of your size and a ruler of real lengths [user, 2026-11-25]
# ---------------------------------------------------------------------------

RULER_SPAN = 0.3          # m (physical): about how long the ruler looks to you
RULER_TICKS = 4           # steps along the ruler
_NICE = (1.0, 2.0, 5.0, 10.0)


def size_label(size):
    """'1:1', '0.54x', '20x' (two figures: the readout changes smoothly without a new label every frame)."""
    return "1:1" if abs(size / 1.0 - 1.0) <= PRESET_TOLERANCE else f"{size:.2g}x"


def length_label(metres):
    """A real length with a fitting unit: '5 mm', '20 cm', '2 m', '1 km'."""
    for limit, unit, factor in ((0.01, "mm", 1000.0), (1.0, "cm", 100.0), (1000.0, "m", 1.0)):
        if metres < limit:
            return f"{metres * factor:g} {unit}"
    return f"{metres / 1000.0:g} km"


def ruler_step(size, span=RULER_SPAN, ticks=RULER_TICKS):
    """The real length (m, world) of one ruler step: a round number (1, 2 or 5 x 10^n) that makes the ruler look about
    `span` long to you at this size. The ruler is drawn `ticks * step` long in world units."""
    wanted = span * size / ticks
    exponent = math.floor(math.log10(wanted))
    fraction = wanted / 10 ** exponent
    nice = min(_NICE, key=lambda option: abs(math.log(option / fraction)))
    return nice * 10 ** exponent
