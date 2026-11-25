# SPDX-License-Identifier: GPL-3.0-or-later
"""Action router: one table says what each controller input does, by edit mode and grab mode. Pure Python (no
bpy), so it is tested headless. Tools never read buttons; they ask the router.

Inputs: SELECT (trigger pull), GRAB (grip press). Modes: OBJECT, POSE, OTHER (any other Blender mode: refused).
Grab modes: FREE (grip grabs what the hand touches), LASER (grip grabs what the laser points at), SELECT_GRAB (the
trigger only selects; a grip anywhere moves the selection by the hand's motion)."""

OBJECT, POSE, OTHER = 'OBJECT', 'POSE', 'OTHER'
GP_DRAW = 'PAINT_GREASE_PENCIL'   # Blender's Grease Pencil Draw mode (the same string as `context.mode`)
FREE, LASER, SELECT_GRAB = 'FREE', 'LASER', 'SELECT_GRAB'
GRAB_MODES = (FREE, LASER, SELECT_GRAB)
SELECT, GRAB, DRAW = 'SELECT', 'GRAB', 'DRAW'   # DRAW = the trigger while Annotate is on

# Behaviours
SELECT_LASER = 'SELECT_LASER'   # pick along the laser, then select (see select_outcome)
GRAB_TOUCH = 'GRAB_TOUCH'       # pick the nearest item within the touch distance, then drag
GRAB_LASER = 'GRAB_LASER'       # pick along the laser, then drag
GRAB_SELECTION = 'GRAB_SELECTION'   # no pick: drag the current selection, wherever the hand is
ANNOTATE_STROKE = 'ANNOTATE_STROKE'   # draw a stroke from the controller tip while the trigger is held
GP_STROKE = 'GP_STROKE'         # the same, into a Grease Pencil object (Draw mode)
REFUSE = 'REFUSE'               # not available here: haptic buzz, nothing changes

# (input, mode, grab mode) -> behaviour; None as grab mode = every grab mode
TABLE = {
    (SELECT, OBJECT, None): SELECT_LASER,
    (SELECT, POSE, None): SELECT_LASER,
    (DRAW, OBJECT, None): ANNOTATE_STROKE,
    (DRAW, GP_DRAW, None): GP_STROKE,
    (GRAB, OBJECT, FREE): GRAB_TOUCH,
    (GRAB, OBJECT, LASER): GRAB_LASER,
    (GRAB, POSE, FREE): GRAB_TOUCH,
    (GRAB, POSE, LASER): GRAB_LASER,
    (GRAB, OBJECT, SELECT_GRAB): GRAB_SELECTION,
    (GRAB, POSE, SELECT_GRAB): GRAB_SELECTION,
}


def mode_kind(blender_mode):
    """Our mode for Blender's `context.mode` ('OBJECT', 'POSE', 'EDIT_MESH', ...)."""
    return blender_mode if blender_mode in (OBJECT, POSE, GP_DRAW) else OTHER


def behaviour(action, mode, grab_mode):
    """What `action` does in `mode` with `grab_mode` (REFUSE when the table has no row)."""
    return TABLE.get((action, mode, grab_mode)) or TABLE.get((action, mode, None)) or REFUSE


def trigger_input(annotating, mode):
    """What a trigger pull is: DRAW while Annotate is on in Object mode, and always in Grease Pencil Draw mode; else
    SELECT (so Pose mode still selects)."""
    return DRAW if annotating and mode == OBJECT or mode == GP_DRAW else SELECT


def uses_laser(behaviour_name):
    return behaviour_name in (SELECT_LASER, GRAB_LASER)


# Select outcomes
REPLACE, TOGGLE, CLEAR, NOTHING = 'REPLACE', 'TOGGLE', 'CLEAR', 'NOTHING'


def select_outcome(hit, toggle_held):
    """Trigger pull: on an item, select only it (or toggle it while A is held, like Shift). On empty space, clear the
    selection (with A held: nothing, like Shift-click on nothing)."""
    if hit:
        return TOGGLE if toggle_held else REPLACE
    return NOTHING if toggle_held else CLEAR


# What a grip moves
WHOLE_SELECTION, ONLY_HIT = 'WHOLE_SELECTION', 'ONLY_HIT'


def grab_targets(hit_selected):
    """Grip on a selected item moves the whole selection; on an unselected item, it selects and moves only that."""
    return WHOLE_SELECTION if hit_selected else ONLY_HIT


def hover_pickers(grab_mode, trigger_touched, grip_amount, grip_aim_threshold=0.05, always_laser=False):
    """Which hover checks run for one hand this tick: (laser, touch). The laser shows while a finger rests on the
    trigger; in Laser grab mode also while the grip is half squeezed (aiming a grab). Free mode always previews
    what the hand touches. With Always Show Lasers on, the laser shows all the time."""
    laser = always_laser or trigger_touched or (grab_mode == LASER and grip_amount > grip_aim_threshold)
    touch = grab_mode == FREE
    return laser, touch


def button_edge(was_down, amount, press=0.6, release=0.4):
    """Polled analog button with hysteresis: (down now, pressed this poll, released this poll)."""
    down = amount >= press if not was_down else amount > release
    return down, down and not was_down, was_down and not down


# Grip rotation options
PUPPET, STICK, AUTO = 'PUPPET', 'STICK', 'AUTO'
ROTATION_MODES = (PUPPET, STICK, AUTO)
HAND, ITEM = 'HAND', 'ITEM'


def rotation_style(rotation_mode, reach, swap_distance):
    """PUPPET (the wrist turns it in place) or STICK (held rigidly as if on a stick: the wrist turns it AND swings
    it around the hand) for a grab that starts `reach` away from the hand. Auto: puppet when closer than the swap
    distance. Both always follow the wrist [user, 2026-11-24]."""
    if rotation_mode == AUTO:
        return PUPPET if reach < swap_distance else STICK
    return rotation_mode


def swap_distance(linked, touch_distance, own_distance):
    """Auto's swap distance: the touch distance while linked (the default), else its own setting."""
    return touch_distance if linked else own_distance


def pivot_kind(behaviour_name, style, around_pivot=False):
    """What a grab turns about. Natural by default: the hand, as if held or on a stick in your hand (the wrist turns
    it AND swings it around the hand). While A is held: the item's own pivot (turns in place) [user, 2026-11-25]."""
    return ITEM if around_pivot else HAND


# A grip while the other hand already holds something
JOIN, SEPARATE = 'JOIN', 'SEPARATE'


def second_grip(behaviour_name, hit_in_other_grab):
    """JOIN = both hands hold one grab (two-hand scale); SEPARATE = a grab of its own. Select and Grab always joins
    (both grips hold the selection); otherwise only a grip on an item the other hand moves joins."""
    return JOIN if behaviour_name == GRAB_SELECTION or hit_in_other_grab else SEPARATE


def motion_factor(fine_control, fine_factor):
    """How much of the hand's motion a grab applies: fine control (B) slows it."""
    return fine_factor if fine_control else 1.0
