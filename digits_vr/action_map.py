# SPDX-License-Identifier: GPL-3.0-or-later
"""Our own XR action map (input map): built in `xr_session_start_pre`, the only time OpenXR accepts action sets
(A3). Oculus Touch first (the Steam Frame always arrives as Touch, A1), Valve Index second; a binding the runtime
refuses is logged and skipped, never fatal. Buttons are FLOAT actions with a threshold (there is no BOOLEAN, A6).
Our tools have no operators here: the session timer polls grip, trigger and both thumbsticks (tools.py says why;
move.py moves you in Python from the stick values: no native nav operators, so a hand's stick can be left alone while
it turns a grab On stick)."""
from dataclasses import dataclass, field

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
            '/input/thumbstick', '/input/thumbstick/click', '/output/haptic', '/input/menu/click'},
    INDEX: {'/input/grip/pose', '/input/aim/pose', '/input/squeeze/value', '/input/trigger/value',
            '/input/trigger/touch', '/input/a/click', '/input/b/click', '/input/thumbstick',
            '/input/thumbstick/click', '/output/haptic'},
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
    Action("stick", 'VECTOR2D', '/input/thumbstick'),              # On stick grip rotation (polled)
    Action("haptic", 'VIBRATION', '/output/haptic'),
    Action("stick_click", 'FLOAT', '/input/thumbstick/click', hands=(RIGHT,)),   # right stick click: the desk
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


def buzz(context, state, hand, duration=0.04, amplitude=0.6):
    try:
        state.haptic_action_apply(context, SET_NAME, "haptic", hand, duration=duration, frequency=0.0,
                                  amplitude=amplitude)
    except (RuntimeError, TypeError, ValueError):
        pass
