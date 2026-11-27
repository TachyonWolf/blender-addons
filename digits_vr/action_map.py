# SPDX-License-Identifier: GPL-3.0-or-later
"""Our own XR action map (input map): built in `xr_session_start_pre`, the only time OpenXR accepts action sets
(A3). Oculus Touch first (the Steam Frame always arrives as Touch, A1), Valve Index second; a binding the runtime
refuses is logged and skipped, never fatal. Buttons are FLOAT actions with a threshold (there is no BOOLEAN, A6).
Our tools have no operators here: the session timer polls grip, trigger and both thumbsticks (tools.py says why;
move.py moves you in Python from the stick values: no native nav operators)."""
import time
from dataclasses import dataclass, field

from . import haptics_math, settings

SET_NAME = "digits_vr"
LEFT, RIGHT = '/user/hand/left', '/user/hand/right'
HANDS = (LEFT, RIGHT)   # pose action user paths: index 0 = left, 1 = right in controller_*_get
TOUCH = '/interaction_profiles/oculus/touch_controller'
INDEX = '/interaction_profiles/valve/index_controller'
PROFILES = (TOUCH, INDEX)

# Components each profile really has (OpenXR spec). A binding to a component a profile lacks makes Blender 5.3
# segfault on the NEXT call after the refused binding (seen on the real headset, 2026-11-24), so never ask for one.
PROFILE_COMPONENTS = {
    TOUCH: {'/input/grip/pose', '/input/aim/pose', '/input/squeeze/value', '/input/trigger/value',
            '/input/trigger/touch', '/input/a/click', '/input/b/click', '/input/x/click', '/input/y/click',
            '/input/thumbstick', '/input/thumbstick/click', '/output/haptic', '/input/menu/click',
            '/input/thumbstick/touch', '/input/a/touch', '/input/b/touch', '/input/x/touch', '/input/y/touch',
            '/input/thumbrest/touch'},
    INDEX: {'/input/grip/pose', '/input/aim/pose', '/input/squeeze/value', '/input/trigger/value',
            '/input/trigger/touch', '/input/a/click', '/input/b/click', '/input/thumbstick',
            '/input/thumbstick/click', '/output/haptic', '/input/thumbstick/touch', '/input/a/touch', '/input/b/touch',
            '/input/trackpad/touch'},
}


@dataclass
class Action:
    name: str
    kind: str                      # FLOAT, VECTOR2D, POSE, VIBRATION
    component: str                 # same path on Touch and Index
    hands: tuple = HANDS
    op: str = ""
    op_mode: str = 'PRESS'
    threshold: float = 0.5
    pose: str = ""                 # 'grip' / 'aim' for POSE actions
    region: str = 'ANY'            # stick direction: POSITIVE / NEGATIVE
    op_properties: dict = field(default_factory=dict)
    profile_components: dict = field(default_factory=dict)   # profile -> component, where it differs

    def component_for(self, profile):
        return self.profile_components.get(profile, self.component)


ACTIONS = (
    Action("grip_pose", 'POSE', '/input/grip/pose', pose='grip'),
    Action("aim_pose", 'POSE', '/input/aim/pose', pose='aim'),
    Action("grab", 'FLOAT', '/input/squeeze/value'),       # grip and trigger are polled (see tools.py for why)
    Action("select", 'FLOAT', '/input/trigger/value'),
    Action("trigger_touch", 'FLOAT', '/input/trigger/touch'),
    Action("toggle", 'FLOAT', '/input/a/click', hands=(RIGHT,)),   # A = Shift while selecting
    Action("fine", 'FLOAT', '/input/b/click', hands=(RIGHT,)),     # B toggles fine control
    Action("stick", 'VECTOR2D', '/input/thumbstick'),              # movement (move.py) and the thumb's pose (hand_state.py), polled
    # Thumb touches (capacitive; the drawn thumb rests while any is touched, hand_state.py). A path a profile lacks is
    # skipped there (thumb rest: Touch only; trackpad: Index only), and an unbound action reads 0 = today's behaviour.
    Action("touch_stick", 'FLOAT', '/input/thumbstick/touch'),
    Action("touch_a", 'FLOAT', '/input/a/touch', hands=(RIGHT,)),
    Action("touch_b", 'FLOAT', '/input/b/touch', hands=(RIGHT,)),
    Action("touch_x", 'FLOAT', '/input/x/touch', hands=(LEFT,), profile_components={INDEX: '/input/a/touch'}),
    Action("touch_y", 'FLOAT', '/input/y/touch', hands=(LEFT,), profile_components={INDEX: '/input/b/touch'}),
    Action("touch_rest", 'FLOAT', '/input/thumbrest/touch'),
    Action("touch_trackpad", 'FLOAT', '/input/trackpad/touch'),
    Action("haptic", 'VIBRATION', '/output/haptic'),
    Action("stick_click", 'FLOAT', '/input/thumbstick/click', hands=(LEFT, RIGHT)),   # stick clicks (sticks.py): right = desk, left = Pause, both held = recenter / failsafe
    # D-pad = left X / Y on Touch (gate test). Index has no X / Y: its left A / B instead.
    Action("undo_button", 'FLOAT', '/input/x/click', hands=(LEFT,), profile_components={INDEX: '/input/a/click'}),
    Action("redo_button", 'FLOAT', '/input/y/click', hands=(LEFT,), profile_components={INDEX: '/input/b/click'}),
)


def _add_item(amap, action):
    item = amap.actionmap_items.new(action.name, replace_existing=True)
    item.type = action.kind
    if action.kind == 'POSE':
        item.pose_is_controller_grip = action.pose == 'grip'
        item.pose_is_controller_aim = action.pose == 'aim'
    for hand in action.hands:
        item.user_paths.new(hand)
    if action.op:
        item.op = action.op
        item.op_mode = action.op_mode
        for key, value in action.op_properties.items():
            try:
                setattr(item.op_properties, key, value)
            except (AttributeError, TypeError, ValueError) as error:
                print(f"digits_vr: action {action.name}: can't set {key}: {error}")
    for profile in PROFILES:
        component = action.component_for(profile)
        if component not in PROFILE_COMPONENTS[profile]:
            continue   # never bind a component the profile lacks (crashes Blender, see PROFILE_COMPONENTS)
        binding = item.bindings.new(profile.rsplit('/', 1)[-1], replace_existing=True)
        binding.profile = profile
        binding.threshold = action.threshold
        if action.region != 'ANY':
            binding.axis0_region = action.region
        for _hand in action.hands:
            binding.component_paths.new(component)
    return item


def _build_set(context, state, name, actions, problems):
    amap = state.actionmaps.new(state, name, replace_existing=True)
    for action in actions:
        _add_item(amap, action)
    if not state.action_set_create(context, amap):
        problems.append(f"action set {name} not created")
        return
    for item in amap.actionmap_items:
        if not state.action_create(context, amap, item):
            problems.append(f"action {item.name}")
            continue
        for binding in item.bindings:
            if not state.action_binding_create(context, amap, item, binding):
                problems.append(f"binding {item.name}/{binding.name}")   # e.g. a profile the runtime lacks: fine
    if not state.controller_pose_actions_set(context, name, "grip_pose", "aim_pose"):
        problems.append("controller poses")


def build(context, state):
    """Create our action set, actions and bindings on the runtime and make it active. Returns a list of problems
    (empty = all bound). Call only from xr_session_start_pre."""
    problems = []
    _build_set(context, state, SET_NAME, ACTIONS, problems)
    if not state.active_action_set_set(context, SET_NAME):
        problems.append("active set")
    return list(dict.fromkeys(problems))


def assert_active(context, state):
    """Make our set the active one again (viewport_vr_preview activates its own on start, A4)."""
    return bool(state.active_action_set_set(context, SET_NAME))


def value(context, state, action_name, hand):
    """Current float value of an action for one hand (0.0 when unknown)."""
    try:
        return state.action_state_get(context, SET_NAME, action_name, hand)[0]
    except (RuntimeError, TypeError, ValueError):
        return 0.0


def vector(context, state, action_name, hand):
    """Current (x, y) of a VECTOR2D action for one hand ((0, 0) when unknown)."""
    try:
        return tuple(state.action_state_get(context, SET_NAME, action_name, hand))
    except (RuntimeError, TypeError, ValueError):
        return 0.0, 0.0


_haptic_problems = []
_haptic_ends = {}             # hand -> when its pulse must be over
# Blender 5.3 documents the duration in seconds but passes it on as nanoseconds (headset, 2026-11-25: 1.5 "seconds" is never
# felt, 2e8 is). haptics_tick stops each pulse at its real end, so a Blender that fixes this can't buzz for years.
HAPTIC_UNITS_PER_SECOND = 1e9


def play_pulse(context, state, hand, seconds, amplitude, frequency=0.0):
    """One vibration. False when Blender refused it."""
    _haptic_ends[hand] = time.perf_counter() + seconds
    return bool(state.haptic_action_apply(context, SET_NAME, "haptic", hand, duration=seconds * HAPTIC_UNITS_PER_SECOND,
                                          frequency=frequency, amplitude=amplitude))


def haptics_tick(context, state):
    """Session tick: stop the pulses that are over."""
    now = time.perf_counter()
    for hand in [hand for hand, end in _haptic_ends.items() if now > end]:
        del _haptic_ends[hand]
        stop_pulse(context, state, hand)


def stop_pulse(context, state, hand):
    try:
        state.haptic_action_stop(context, SET_NAME, "haptic", hand)
    except (RuntimeError, TypeError, ValueError):
        pass


def buzz(context, state, hand, duration=0.04, amplitude=0.6, kind=haptics_math.LEGACY):
    """THE one place a buzz is played: haptics_math.choose checks the Haptics settings first (None = silence)."""
    pulse = haptics_math.choose(kind, duration, amplitude, settings.get)
    if pulse is None:
        return
    try:
        played, problem = play_pulse(context, state, hand, *pulse), "Blender refused it"
    except (RuntimeError, TypeError, ValueError) as error:
        played, problem = False, error
    if not played and str(problem) not in _haptic_problems:
        _haptic_problems.append(str(problem))
        print(f"digits_vr: haptic pulse failed: {problem}")       # once per cause
