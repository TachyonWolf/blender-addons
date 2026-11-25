# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's controller: runs inside the session tick (controls.update calls tick()). It handles
- the right stick click (open / call / close) and the D-pad (left X = undo, left Y = redo);
- the laser against the screen (hover), trigger presses on buttons (the desk wins over the scene), sliders;
- the two handles: grip near a handle (or laser on it) and move; both handles scale and move it.
Closed desk = the stick check, nothing else. Open desk = two laser rays per tick and a model check at 5 Hz."""
from mathutils import Quaternion, Vector

from . import asset_page, desk_actions, desk_draw, desk_layout as layout, rig_tab, router, settings, size_state
from .action_map import HANDS, LEFT, RIGHT, buzz, value
from .desk_state import CALL, CLOSE, DESK, OPEN, OPEN_DISTANCE, OPEN_DROP, TOUCH_REACH, HandleGrab, near_handle, one_hand_matrix, place_in_front, \
    screen_hit, stick_action, two_hand_matrix
from .hands import HandPose
from .runtime import RUNTIME
from .transform_math import hand_matrix

BUTTON_POLL_TICKS = 2          # stick click and D-pad are polled every other tick (~15 Hz)
MODEL_CHECK_TICKS = 6          # the screen model (mode, settings, modifiers) is compared about 5 times a second
_widgets = []
_model = None
_state = {"stick_down": False, "undo_down": False, "redo_down": False, "last_frame": -1, "ticks": 0, "two_hand": None}


def is_open():
    return DESK.open


def laser_reach(hand):
    """Distance from a hand's laser to the desk when it points at the desk (the desk wins over the scene), else None."""
    return DESK.reach.get(hand) if DESK.open else None


def start(context):
    """Session start: load the remembered desk (and open it if it was open)."""
    DESK.tab = settings.get("desk_tab")
    DESK.size = size_state.SIZE.factor
    DESK.scale = settings.get("desk_scale") * DESK.size
    saved_location, saved_rotation = settings.get("desk_location"), settings.get("desk_rotation")
    DESK.placed = bool(saved_location and saved_rotation)
    if DESK.placed:
        DESK.location, DESK.rotation = Vector(saved_location), Quaternion(saved_rotation)
    _state.update(stick_down=False, undo_down=False, redo_down=False, last_frame=-1, ticks=0, two_hand=None)
    if settings.get("desk_open"):
        _open(context, None, remember=False)


def teardown():
    """Session over: drop everything live (the remembered open / closed state stays as the user left it)."""
    global _model
    DESK.open = False
    DESK.clear_live()
    asset_page.close()
    rig_tab.forget()
    desk_draw.free()
    _widgets.clear()
    _model = None


def size_changed(pivot, old_size, new_size):
    """Your size changed about `pivot`: the desk keeps its size and place relative to you."""
    DESK.rescale(pivot, old_size, new_size)


def _remember():
    settings.put_many({"desk_open": DESK.open, "desk_tab": DESK.tab, "desk_scale": DESK.scale / DESK.size,
                       "desk_location": list(DESK.location) if DESK.placed else [],
                       "desk_rotation": list(DESK.rotation) if DESK.placed else []})


def _refresh(context, force=False):
    """Rebuild the screen when what it shows changed."""
    global _model
    model = desk_actions.build_model(context)
    if force or model != _model:
        _model = model
        _widgets[:] = layout.build(model)
        desk_draw.set_widgets(_widgets)


def _bring_to_you(state, context):
    head = Vector(state.viewer_pose_location)
    forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
    DESK.location, DESK.rotation = place_in_front(head, forward, distance=OPEN_DISTANCE * DESK.size,
                                                  drop=OPEN_DROP * DESK.size)
    DESK.placed = True


def _open(context, state, remember=True):
    if state is not None or not DESK.placed:
        state = state or context.window_manager.xr_session_state
        _bring_to_you(state, context)
    DESK.open = True
    _refresh(context, force=True)
    if remember:
        _remember()


def _close():
    DESK.open = False
    DESK.clear_live()
    asset_page.close()
    desk_draw.free()
    _remember()


def _stick_click(context, state):
    amount = value(context, state, "stick_click", RIGHT)
    _state["stick_down"], pressed, _released = router.button_edge(_state["stick_down"], amount)
    if not pressed:
        return
    head = Vector(state.viewer_pose_location)
    action = stick_action(DESK.open, DESK.distance_to(head) / DESK.size)
    if action == CLOSE:
        _close()
    elif action == CALL:
        _bring_to_you(state, context)
        _remember()
    else:
        _open(context, state)
    buzz(context, state, RIGHT, duration=0.02, amplitude=0.4)


def _history_buttons(context, state):
    for name, redo in (("undo", False), ("redo", True)):
        _state[name + "_down"], pressed, _released = router.button_edge(_state[name + "_down"],
                                                                         value(context, state, name + "_button", LEFT))
        if pressed and not desk_actions.history(context, redo):
            buzz(context, state, LEFT)


def _ray_hit(context, state, hand, matrix):
    """(widget or None, pixel x, distance) when a hand's laser meets the desk (screen or handle), else None."""
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    hit = screen_hit(matrix, pose.aim_location, pose.aim_direction)
    if hit is None:
        return None
    pixel_x, pixel_y, distance = hit
    widget = layout.hit_test(_widgets, pixel_x, pixel_y)
    if widget is None and not layout.on_screen(pixel_x, pixel_y):
        return None
    return widget, pixel_x, distance


def _hover(context, state, matrix):
    for hand in HANDS:
        hand_state = RUNTIME.hands[hand]
        hit = _ray_hit(context, state, hand, matrix) if (hand_state.trigger_touched or hand_state.trigger_down or settings.get("always_laser")) else None
        if hit is None:
            DESK.hover.pop(hand, None)
            DESK.reach.pop(hand, None)
            continue
        widget, pixel_x, distance = hit
        DESK.reach[hand] = distance
        if widget is None:
            DESK.hover.pop(hand, None)
        else:
            DESK.hover[hand] = widget.id
        held = DESK.pressed.get(hand)
        if held and hand_state.trigger_down:        # a slider follows the laser while the trigger is held
            slider = next((item for item in _widgets if item.id == held and item.kind == layout.SLIDER), None)
            if slider and desk_actions.perform(context, slider, pixel_x):
                _refresh(context)


def trigger_pressed(context, state, hand):
    """Trigger pull. True when the laser is on the desk: the desk takes the press (the scene never sees it)."""
    if not DESK.open:
        return False
    hit = _ray_hit(context, state, hand, DESK.matrix())
    if hit is None:
        return False
    widget, pixel_x, distance = hit
    DESK.reach[hand] = distance
    if widget is not None and widget.kind == layout.THUMB and DESK.tab == 'assets' \
            and asset_page.trigger_pressed(context, state, hand, widget.id):
        return True                  # a laser drag of the thumbnail began: it drops where the laser points
    if widget is not None and widget.kind != layout.HANDLE:
        done = desk_actions.perform(context, widget, pixel_x)
        if done or widget.enabled:
            buzz(context, state, hand, duration=0.015, amplitude=0.5)       # haptic tick
        else:
            buzz(context, state, hand)                                       # disabled: a longer buzz
        DESK.pressed[hand] = widget.id
        _refresh(context, force=done)
    return True


def grip_pressed(context, state, hand):
    """Grip press. True when it took hold of a desk handle (by touch, or by the laser on it)."""
    if not DESK.open or hand in DESK.grabs:
        return False
    pose = HandPose(context, state, hand)
    matrix = DESK.matrix()
    if DESK.tab == 'assets' and asset_page.grip_pressed(context, state, hand, matrix, DESK.hover.get(hand)):
        return True                  # a thumbnail now follows the hand (checked first: tiles sit near the handles)
    handle_id = near_handle(matrix, pose.grip_location, _widgets, TOUCH_REACH * DESK.size)
    if handle_id is None and DESK.hover.get(hand) in (layout.LEFT_HANDLE, layout.RIGHT_HANDLE):
        handle_id = DESK.hover[hand]
    if handle_id is None or any(grab.handle_id == handle_id for grab in DESK.grabs.values()):
        return False
    DESK.grabs[hand] = HandleGrab(handle_id, hand_matrix(pose.grip_location, pose.grip_rotation), matrix)
    _restart_grabs(context, state)
    buzz(context, state, hand, duration=0.02, amplitude=0.3)
    return True


def _grip_points(context, state):
    return {hand: HandPose(context, state, hand, with_grip_rotation=False).grip_location.copy() for hand in DESK.grabs}


def _restart_grabs(context, state):
    """Hands changed: every held handle measures from the desk and hands as they are now."""
    matrix = DESK.matrix()
    for hand, grab in DESK.grabs.items():
        pose = HandPose(context, state, hand)
        grab.hand_start, grab.desk_start = hand_matrix(pose.grip_location, pose.grip_rotation), matrix
    _state["two_hand"] = (matrix, _grip_points(context, state)) if len(DESK.grabs) == 2 else None


def _drag(context, state):
    """Move / scale the desk once per headset frame while handles are held; saves when the last one lets go."""
    released = [hand for hand in DESK.grabs if not RUNTIME.hands[hand].grip_down]
    if released:
        for hand in released:
            del DESK.grabs[hand]
        if DESK.grabs:
            _restart_grabs(context, state)
        else:
            _state["two_hand"] = None
            _remember()
            return
    if not DESK.grabs or RUNTIME.frame == _state["last_frame"]:
        return
    _state["last_frame"] = RUNTIME.frame
    if len(DESK.grabs) == 2:
        start_matrix, start_points = _state["two_hand"]
        now_points = _grip_points(context, state)
        DESK.set_matrix(two_hand_matrix(start_matrix, (start_points[LEFT], start_points[RIGHT]),
                                        (now_points[LEFT], now_points[RIGHT]), DESK.size))
    else:
        (hand, grab), = DESK.grabs.items()
        pose = HandPose(context, state, hand)
        DESK.set_matrix(one_hand_matrix(grab, hand_matrix(pose.grip_location, pose.grip_rotation)))


def tick(context, state):
    """Once per session tick. Returns True while a handle is held (the timer then runs every frame)."""
    _state["ticks"] += 1
    if _state["ticks"] % BUTTON_POLL_TICKS == 0:     # three action reads: every other tick keeps idle cost down
        _stick_click(context, state)
        _history_buttons(context, state)
    if not DESK.open:
        return False
    for hand in [hand for hand in DESK.pressed if not RUNTIME.hands[hand].trigger_down]:
        del DESK.pressed[hand]
        rig_tab.released(context)       # a rig slider drag: one undo step at the release
    _hover(context, state, DESK.matrix())
    _drag(context, state)
    asset_page.update_drag(context, state, DESK.matrix())
    if _state["ticks"] % MODEL_CHECK_TICKS == 0:
        _refresh(context)
    return bool(DESK.grabs)


def register():
    desk_actions.register()


def unregister():
    desk_actions.unregister()
