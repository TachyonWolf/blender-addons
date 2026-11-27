# SPDX-License-Identifier: GPL-3.0-or-later
"""What a hand picks WITH, and in which order: one list per grab mode of the three sources (laser, fingertip, palm), each
on or off [user, 2026-11-27]. Hover, name tag, trigger select and grip grab all take the first source of the list that
finds something (hands.HandPose.first_hit), so what glows is what the trigger selects and what the grip grabs.
Pure Python (no bpy), tested headless. An order is a tuple of (source, on) pairs, each source once."""

LASER, FINGER, PALM = 'LASER', 'FINGER', 'PALM'
SOURCES = (LASER, FINGER, PALM)
TOUCH_SOURCES = (FINGER, PALM)           # these pick at a point of the hand; the laser along a ray
NAMES = {LASER: "Laser", FINGER: "Fingertip", PALM: "Palm"}
SHORT_NAMES = {LASER: "Laser", FINGER: "Tip", PALM: "Palm"}      # on the desk button, which has little room
DETAILS = {LASER: "What the laser points at", FINGER: "What your fingertip touches", PALM: "What your palm touches"}

# grab mode -> its setting. Free: the palm, then the laser (the trigger still selects by laser). Laser, and Select
# and Grab (where the trigger selects and the grip moves the selection): the laser only; the palm still holds the grab.
FIELD_OF_MODE = {'FREE': "grab_order_free", 'LASER': "grab_order_laser", 'SELECT_GRAB': "grab_order_select"}
DEFAULTS = {
    'FREE': ((PALM, True), (LASER, True), (FINGER, False)),
    'LASER': ((LASER, True), (PALM, False), (FINGER, False)),
    'SELECT_GRAB': ((LASER, True), (PALM, False), (FINGER, False)),
}


def fields():
    """settings_store.FIELDS entries: setting -> (default as a list of [source, on], check)."""
    return {FIELD_OF_MODE[mode]: ([list(pair) for pair in order], is_valid) for mode, order in DEFAULTS.items()}


def is_valid(value):
    """A saved order: three [source, on] pairs holding every source once."""
    return (isinstance(value, (list, tuple)) and len(value) == len(SOURCES)
            and all(isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[1], bool) for pair in value)
            and sorted(pair[0] for pair in value if isinstance(pair[0], str)) == sorted(SOURCES))


def order_of(value, mode):
    """`value` (a saved order) as a tuple of pairs; the mode's default when it is not valid."""
    return tuple((pair[0], pair[1]) for pair in value) if is_valid(value) else DEFAULTS[mode]


def active(order):
    """The sources that are on, first priority first."""
    return tuple(source for source, on in order if on)


def pivot_source(order):
    """The touch source a grab is held by: the first one that is on, else the first in the list (so a laser-only mode holds
    its grab at the palm, as before the list existed)."""
    touching = [pair for pair in order if pair[0] in TOUCH_SOURCES]
    return next((source for source, on in touching if on), touching[0][0])


def moved(order, index, step):
    """`order` with the row at `index` moved by `step` places (-1 = up); unchanged at either end."""
    target = index + step
    if not 0 <= target < len(order) or not 0 <= index < len(order):
        return tuple(order)
    rows = list(order)
    rows[index], rows[target] = rows[target], rows[index]
    return tuple(rows)


def toggled(order, index):
    """`order` with the row at `index` switched on or off."""
    return tuple((source, not on if row == index else on) for row, (source, on) in enumerate(order))


def summary(order):
    """The words on a button: the sources that are on, in order ("Palm, Laser"; the fingertip is "Tip"), or "Nothing"."""
    return ", ".join(SHORT_NAMES[source] for source in active(order)) or "Nothing"


def migrated(grab_point):
    """Settings of the old `grab_point` (PALM / FINGER / BOTH_PALM / BOTH_FINGER) as {setting: order}. It chose which
    touch point grabs, for every mode: Free used it and so did a laser grab's hold. Free gets the old points on in the old order, then the laser on;
    the other two modes get the same touch order below the laser, switched off (they held the grab there)."""
    order = {'PALM': (PALM,), 'FINGER': (FINGER,), 'BOTH_PALM': (PALM, FINGER), 'BOTH_FINGER': (FINGER, PALM)}.get(grab_point)
    if order is None:
        return {}
    touching = [(source, True) for source in order] + [(source, False) for source in TOUCH_SOURCES if source not in order]
    laser_modes = ((LASER, True),) + tuple((source, False) for source, _on in touching)
    free = [pair for pair in touching if pair[1]] + [(LASER, True)] + [pair for pair in touching if not pair[1]]
    return {FIELD_OF_MODE['FREE']: [list(pair) for pair in free],
            FIELD_OF_MODE['LASER']: [list(pair) for pair in laser_modes],
            FIELD_OF_MODE['SELECT_GRAB']: [list(pair) for pair in laser_modes]}
