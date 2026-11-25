# SPDX-License-Identifier: GPL-3.0-or-later
"""Action router: one table says what each controller input does, by edit mode and grab mode. Pure Python (no
bpy), so it is tested headless. Tools never read buttons; they ask the router.

Inputs: SELECT (trigger pull), GRAB (grip press). Modes: OBJECT, POSE, OTHER (any other Blender mode: refused).
Grab modes: FREE (grip grabs what the hand touches), LASER (grip grabs what the laser points at), SELECT_GRAB (the
trigger only selects; a grip anywhere moves the selection by the hand's motion)."""

try:
    from . import edit_tool_settings
except ImportError:        # the headless pure tests import the modules top-level
    import edit_tool_settings

OBJECT, POSE, OTHER = 'OBJECT', 'POSE', 'OTHER'
EDIT = 'EDIT_MESH'     # Blender's mesh Edit mode (the same string as `context.mode`)
GP_DRAW = 'PAINT_GREASE_PENCIL'   # Blender's Grease Pencil Draw mode (the same string as `context.mode`)
SCULPT = 'SCULPT'                 # Blender's Sculpt mode
FREE, LASER, SELECT_GRAB = 'FREE', 'LASER', 'SELECT_GRAB'
GRAB_MODES = (FREE, LASER, SELECT_GRAB)
SELECT, GRAB, DRAW, BUBBLE = 'SELECT', 'GRAB', 'DRAW', 'BUBBLE'   # DRAW = the trigger while Annotate is on; BUBBLE = while the select bubble is on

# Behaviours
SELECT_LASER = 'SELECT_LASER'   # pick along the laser, then select (see select_outcome)
GRAB_TOUCH = 'GRAB_TOUCH'       # pick the nearest item within the touch distance, then drag
GRAB_LASER = 'GRAB_LASER'       # pick along the laser, then drag
GRAB_SELECTION = 'GRAB_SELECTION'   # no pick: drag the current selection, wherever the hand is
ANNOTATE_STROKE = 'ANNOTATE_STROKE'   # draw a stroke from the controller tip while the trigger is held
GP_STROKE = 'GP_STROKE'         # the same, into a Grease Pencil object (Draw mode)
SCULPT_STROKE = 'SCULPT_STROKE'   # sculpt at the controller tip while the trigger is held
SCULPT_INVERT = 'SCULPT_INVERT'   # the grip held = the stroke inverts (like Ctrl)
EDIT_TOOL = 'EDIT_TOOL'         # Edit mode's active tool runs, and holding drags it
SELECT_BUBBLE = 'SELECT_BUBBLE'   # paint the selection with the bubble at the fingertip while the trigger is held
REFUSE = 'REFUSE'               # not available here: haptic buzz, nothing changes

# (input, mode, grab mode) -> behaviour; None as grab mode = every grab mode
TABLE = {
    (SELECT, OBJECT, None): SELECT_LASER,
    (SELECT, POSE, None): SELECT_LASER,
    (SELECT, EDIT, None): SELECT_LASER,
    (GRAB, EDIT, FREE): GRAB_TOUCH,
    (GRAB, EDIT, LASER): GRAB_LASER,
    (GRAB, EDIT, SELECT_GRAB): GRAB_SELECTION,
    (BUBBLE, OBJECT, None): SELECT_BUBBLE,
    (BUBBLE, POSE, None): SELECT_BUBBLE,
    (BUBBLE, EDIT, None): SELECT_BUBBLE,
    (DRAW, OBJECT, None): ANNOTATE_STROKE,
    (DRAW, GP_DRAW, None): GP_STROKE,
    (DRAW, SCULPT, None): SCULPT_STROKE,
    (GRAB, SCULPT, None): SCULPT_INVERT,
    (GRAB, OBJECT, FREE): GRAB_TOUCH,
    (GRAB, OBJECT, LASER): GRAB_LASER,
    (GRAB, POSE, FREE): GRAB_TOUCH,
    (GRAB, POSE, LASER): GRAB_LASER,
    (GRAB, OBJECT, SELECT_GRAB): GRAB_SELECTION,
    (GRAB, POSE, SELECT_GRAB): GRAB_SELECTION,
}
TRIGGER_DRAWS = (GP_DRAW, SCULPT)                # modes where the trigger always draws: nothing is picked or hovered


KNOWN_MODES = (
    OBJECT,
    POSE,
    GP_DRAW,
    EDIT,
    SCULPT,
)


def mode_kind(blender_mode):
    """Our mode for Blender's `context.mode` ('OBJECT', 'POSE', 'EDIT_MESH', ...)."""
    return blender_mode if blender_mode in KNOWN_MODES else OTHER


def behaviour(action, mode, grab_mode):
    """What `action` does in `mode` with `grab_mode` (REFUSE when the table has no row)."""
    return TABLE.get((action, mode, grab_mode)) or TABLE.get((action, mode, None)) or REFUSE


def edit_behaviour(action, behaviour_name, tool, anything_selected):
    """Edit mode: what its active tool makes of `behaviour_name`. Grab (no tool): a grip anywhere moves the selection;
    with nothing selected the table's pick. Loop cut also answers the trigger; the other tools the grip."""
    if behaviour_name == REFUSE:
        return REFUSE
    if action == SELECT:
        return EDIT_TOOL if tool == edit_tool_settings.LOOP_CUT else behaviour_name
    if tool not in (edit_tool_settings.GRAB, edit_tool_settings.SELECT):     # Select: the grip still grabs the selection
        return EDIT_TOOL
    return GRAB_SELECTION if anything_selected else behaviour_name


def bubble_on(mode, edit_tool, bubble_setting):
    """The select bubble is the trigger's tool: Edit mode's active tool Select, or the toggle in Object / Pose mode."""
    return edit_tool == edit_tool_settings.SELECT if mode == EDIT else bubble_setting and mode in (OBJECT, POSE)


def trigger_input(annotating, mode, bubble=False):
    """What a trigger pull is: BUBBLE while the select bubble is on (see bubble_on), DRAW while Annotate is on in
    Object mode, and always in the TRIGGER_DRAWS modes; else SELECT (so Pose mode still selects)."""
    if bubble:
        return BUBBLE
    return DRAW if annotating and mode == OBJECT or mode in TRIGGER_DRAWS else SELECT


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


# Grip rotation: natural (the wrist turns what you hold AND swings it around the hand); A held turns it about its own pivot
HAND, ITEM = 'HAND', 'ITEM'


def pivot_kind(around_pivot=False):
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


# Stick clicks. A stick click alone is a click (the right one opens the desk, the left one is planned as Pause); BOTH
# held together are a chord: 2 s = recenter, 6 s = failsafe. A chord never also clicks (the two-stick hold wins).
LEFT_CLICK, RIGHT_CLICK, RECENTER, FAILSAFE = 'LEFT_CLICK', 'RIGHT_CLICK', 'RECENTER', 'FAILSAFE'
CLICK_WAIT = 0.2          # s a lone click waits (the other stick may join) before it counts; a release counts it at once


class StickChord:
    """Turns the two stick-click amounts into events. update(left, right, now) returns a list of LEFT_CLICK /
    RIGHT_CLICK (a stick that went down alone, at its release or after CLICK_WAIT), RECENTER (both held 2 s) and
    FAILSAFE (both held 6 s). Pure, polled."""

    def __init__(self, recenter_seconds=2.0, failsafe_seconds=6.0):
        self.times = (recenter_seconds, failsafe_seconds)
        self.down = {LEFT_CLICK: False, RIGHT_CLICK: False}
        self.since = {}            # stick -> press time while its click may still count
        self.both_since = None
        self.stage = 0

    def update(self, left_amount, right_amount, now):
        events = []
        edges = {}
        for stick, amount in ((LEFT_CLICK, left_amount), (RIGHT_CLICK, right_amount)):
            self.down[stick], pressed, released = button_edge(self.down[stick], amount)
            edges[stick] = released
            if pressed:
                self.since[stick] = now
        both = all(self.down.values())
        if both:
            self.since.clear()                  # both are down: neither is a lone click any more
            if self.both_since is None:
                self.both_since = now
            held = now - self.both_since
            for stage, seconds, event in ((1, self.times[0], RECENTER), (2, self.times[1], FAILSAFE)):
                if self.stage < stage and held >= seconds:
                    self.stage = stage
                    events.append(event)
            return events
        self.both_since, self.stage = None, 0
        other = {LEFT_CLICK: RIGHT_CLICK, RIGHT_CLICK: LEFT_CLICK}
        for stick in (LEFT_CLICK, RIGHT_CLICK):
            started = self.since.get(stick)
            if started is None:
                continue
            if edges[stick] or (self.down[stick] and now - started >= CLICK_WAIT and not self.down[other[stick]]):
                del self.since[stick]
                events.append(stick)
            elif not self.down[stick]:
                del self.since[stick]
        return events

# ---- Help: what each controller button does right now (one source: the table above) --------------------------------
# Help (DESIGN "Help button") asks `help_labels`; it never keeps a table of its own, so it cannot drift from the real
# behaviour. A button that does nothing now is left out (no label, no line).
BEHAVIOUR_NAMES = {
    SELECT_LASER: ("Select", "pull on an item"), GRAB_TOUCH: ("Grab", "what your hand touches"),
    GRAB_LASER: ("Grab", "what the laser hits"), GRAB_SELECTION: ("Grab selection", "your hand moves it"),
    ANNOTATE_STROKE: ("Draw", "hold to draw a note"), GP_STROKE: ("Draw", "hold to draw"),
    SCULPT_STROKE: ("Stroke", "pull harder = stronger"), SCULPT_INVERT: ("Invert", "hold: like Ctrl"),
    SELECT_BUBBLE: ("Select bubble", "hold: paint selection")}
HAND_L, HAND_R = 'LEFT', 'RIGHT'
BUTTONS = ('trig', 'stick', 'click', 'b1', 'b2', 'grip')     # per hand; b1 / b2 = X / Y (left), A / B (right) on Touch
HIDDEN_GESTURES = ("Both stick clicks 2 s: recenter. 6 s: safe settings.", "Two grips on nothing: scale yourself.")


def help_labels(mode, grab_mode, annotating=False, move_mode='WALK', paused=False, grabbing=False, boxing_hand=None,
                fine_on=False, box_volume=True, gun=None, edit_tool=edit_tool_settings.GRAB, bubble=False):
    """{hand: {button: (title, second line)}} for what the controllers do now. `boxing_hand`: the hand dragging a box
    (`box_volume`: a 3D box, else a laser box).
    `gun`: (hand that holds the tool gun, its tool's name) or None.
    Paused: only the stick clicks (desk, Pause) are alive."""
    labels = {HAND_L: {}, HAND_R: {}}
    labels[HAND_L]['click'] = ("Pause", "stick press")
    labels[HAND_R]['click'] = ("Desk", "open / bring / close")
    if paused:
        return labels
    trigger = BEHAVIOUR_NAMES.get(behaviour(trigger_input(annotating, mode, bubble), mode, grab_mode))
    grip = BEHAVIOUR_NAMES.get(behaviour(GRAB, mode, grab_mode))
    stick_left = {'TELEPORT': ("Teleport", "hold forward, let go"), 'FLY': ("Fly", "where you look")}.get(move_mode, ("Walk", "move"))
    for hand in (HAND_L, HAND_R):
        entries = labels[hand]
        if trigger:
            entries['trig'] = ("Push" if hand == HAND_R else "Pull", "while holding") if grabbing else trigger
        if grip:
            entries['grip'] = grip
        entries['stick'] = stick_left if hand == HAND_L else ("Turn", "turn the view")
    if mode == EDIT and not bubble:
        labels[HAND_R]['trig'] = ("Select element", "A: tap toggles, drag = box") if not grabbing else labels[HAND_R]['trig']
        if edit_tool not in (edit_tool_settings.GRAB, edit_tool_settings.SELECT):
            label = (edit_tool_settings.TOOL_LABELS[edit_tool], "hold to drag")
            for hand in (HAND_L, HAND_R):
                labels[hand]['grip'] = label
                if edit_behaviour(SELECT, SELECT_LASER, edit_tool, True) == EDIT_TOOL:
                    labels[hand]['trig'] = label
    if gun is not None:
        labels[gun[0]]['trig'], labels[gun[0]]['grip'] = ("Shoot", gun[1]), ("Hold the gun", "let go: it floats")
    if boxing_hand is not None:
        labels[boxing_hand]['trig'] = ("Box grows", "let go = select")
        if box_volume:
            labels[HAND_R]['grip'], labels[HAND_L]['grip'] = ("Push corner", "3D box: farther"), ("Pull corner", "3D box: nearer")
        else:
            for hand in (HAND_L, HAND_R):
                labels[hand].pop('grip', None)
    labels[HAND_L]['b1'] = ("Undo", "one step")
    labels[HAND_L]['b2'] = ("Redo", "one step")
    if mode == SCULPT:
        labels[HAND_R]['b1'] = ("Smooth", "hold: like Shift")
    elif bubble:
        labels[HAND_R]['b1'] = ("Remove", "hold: bubble deselects")
    elif mode != GP_DRAW:
        labels[HAND_R]['b1'] = ("Add to selection", "hold A first") if mode != EDIT else ("Toggle / box", "hold A first")
    labels[HAND_R]['b2'] = ("Bubble size", "hold, hand up / down") if bubble else ("Slow mode", "on" if fine_on else "off")
    return labels

