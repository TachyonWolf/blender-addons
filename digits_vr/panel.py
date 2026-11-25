# SPDX-License-Identifier: GPL-3.0-or-later
"""The floating-panel controller every panel is built on (the desk, tool options, viewpoints, later the tool gun
menu). One Panel = one place in space (PanelState), one screen (widgets from a frozen model), one renderer
(PanelRenderer), remembered in the settings JSON under `<name>_open / _scale / _location / _rotation / _pinned`.

A new panel subclasses Panel and sets `name` and `spec`, then fills in the content:
- build_model(context): a frozen, comparable snapshot of what it shows (equal models = no redraw);
- build_widgets(model): its widgets in pixels, handles included (panel_layout.side_handle);
- perform(context, widget, pixel_x): what a press (or a slider drag at pixel_x) does; True when it changed something;
then adds itself to panels.PANELS and its four settings to settings_store (panel_fields). Optional hooks below.
panels.py runs every open panel from the session tick and the draw callback; a closed panel costs nothing."""
from mathutils import Quaternion, Vector

from . import panel_layout as layout, pin_math, settings
from .action_map import LEFT, RIGHT, buzz
from .body_frame import BODY
from .hands import HandPose
from .panel_draw import PanelRenderer
from .panel_state import (CALL, CLOSE, OPEN_DISTANCE, OPEN_DROP, TOUCH_REACH, HandleGrab, PanelState, near_handle,
                          one_hand_matrix, place_in_front, screen_hit, stick_action, two_hand_matrix)
from .runtime import RUNTIME
from .size_state import SIZE
from .transform_math import hand_matrix


def _paused_blocks(widget):
    """Pause (pause.py): a panel refuses every press except the Pause toggle."""
    return settings.get("paused") and widget.id != "pause"

MODEL_CHECK_TICKS = 6          # the screen model is compared about 5 times a second
REGISTRY = {}                  # name -> Panel (filled as panels are made; desk buttons find panels here)


class Panel:
    name = ""
    spec = None
    open_distance, open_drop = OPEN_DISTANCE, OPEN_DROP
    open_side = 0.0            # metres to the right (negative: left) when it opens in front of you
    pinnable = True            # gets the Pin toggle (the gun's menu belongs to the gun: no)

    def __init__(self, state=None):
        self.state = state if state is not None else PanelState(scale_range=self.spec.scale_range)
        self.widgets = []
        self.model = None
        self.renderer = PanelRenderer(self.spec, self.body_rects)
        self.ticks, self.last_frame, self.last_pin_frame, self.two_hand = 0, -1, -1, None
        self.check_phase = len(REGISTRY) * 2 + 1      # panels compare their models on different ticks (no pile-up)
        REGISTRY[self.name] = self

    # -- content (override) ----------------------------------------------------

    def build_model(self, context):
        return None

    def build_widgets(self, model):
        return []

    def perform(self, context, widget, pixel_x):
        return False

    def body_rects(self):
        return layout.frame_rects(self.spec.width, self.spec.height)

    # -- optional hooks --------------------------------------------------------

    def take_trigger(self, context, state, hand, widget):
        """A trigger press on `widget` (not a handle) before the usual press. True = taken."""
        return False

    def take_grip(self, context, state, hand, matrix):
        """A grip before the handle check. True = taken."""
        return False

    def trigger_released(self, context):
        """A trigger that pressed a widget of this panel let go."""

    def update(self, context, state):
        """Every tick while open, after the handles moved it."""

    def draw_extra(self, new_frame):
        """Once per eye after the panel is drawn."""

    def closed(self):
        """The panel closed or the session ended: drop page state."""

    def load(self):
        """Session start: read this panel's own extra settings."""

    def remembered(self):
        """Extra settings written with the panel's place."""
        return {}

    # -- open, close, remember -------------------------------------------------

    def key(self, field_name):
        return f"{self.name}_{field_name}"

    def is_open(self):
        return self.state.open

    def laser_reach(self, hand):
        return self.state.reach.get(hand) if self.state.open else None

    def start(self, context):
        """Session start: load the remembered place (and open it if it was open)."""
        panel = self.state
        panel.size = SIZE.factor
        panel.scale = settings.get(self.key("scale")) * panel.size
        saved_location, saved_rotation = settings.get(self.key("location")), settings.get(self.key("rotation"))
        panel.placed = bool(saved_location and saved_rotation)
        panel.pinned = self.pinnable and settings.get(self.key("pinned"))
        panel.pin_offset = panel.pin_last = None
        if panel.pinned and panel.placed:           # pinned: the saved place is relative to your body frame
            panel.pin_offset = pin_math.PinOffset(Vector(saved_location), Quaternion(saved_rotation), settings.get(self.key("scale")))
        elif panel.placed:
            panel.location, panel.rotation = Vector(saved_location), Quaternion(saved_rotation)
        self.ticks, self.last_frame, self.last_pin_frame, self.two_hand = 0, -1, -1, None
        self.load()
        if settings.get(self.key("open")):
            self.open(context, None, remember=False)

    def teardown(self):
        """Session over: drop everything live (the remembered open / closed state stays as the user left it)."""
        self.state.open = False
        self.state.clear_live()
        self.closed()
        self.renderer.free()
        self.widgets.clear()
        self.model = None

    def remember(self):
        panel = self.state
        location, rotation = list(panel.location), list(panel.rotation)
        if panel.pinned and panel.pin_offset is not None:       # pinned: the place is relative to your body frame
            location, rotation = list(panel.pin_offset.location), list(panel.pin_offset.rotation)
        settings.put_many({self.key("open"): panel.open, self.key("scale"): panel.scale / panel.size,
                           self.key("location"): location if panel.placed else [],
                           self.key("rotation"): rotation if panel.placed else [], **self.remembered()})

    def set_pinned(self, state, pinned):
        """Pin it to your body frame where it is now (or let it stay in the world). True when that changed."""
        panel = self.state
        if not self.pinnable or panel.pinned == pinned:
            return False
        panel.pinned = pinned
        panel.pin_offset = panel.pin_last = None
        if pinned:
            BODY.update(state)
            panel.follow_body(BODY.matrix)
        settings.put(self.key("pinned"), pinned)
        self.remember()
        return True

    def refresh(self, context, force=False):
        """Rebuild the screen when what it shows changed."""
        model = self.build_model(context)
        if force or model != self.model:
            self.model = model
            self.widgets[:] = self.build_widgets(model)
            if self.pinnable:
                self.widgets.append(layout.pin_widget(self.spec.width, self.state.pinned))
            self.renderer.set_widgets(self.widgets)

    def bring_to_you(self, state):
        panel = self.state
        forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
        panel.location, panel.rotation = place_in_front(Vector(state.viewer_pose_location), forward,
                                                        distance=self.open_distance * panel.size,
                                                        drop=self.open_drop * panel.size, side=self.open_side * panel.size)
        panel.placed = True

    def open(self, context, state, remember=True):
        """Open it: where it was, or in front of you when `state` is given (a call) or it has no place yet."""
        if state is not None or not self.state.placed:
            self.bring_to_you(state or context.window_manager.xr_session_state)
        self.state.open = True
        self.refresh(context, force=True)
        if remember:
            self.remember()

    def close(self):
        self.state.open = False
        self.state.clear_live()
        self.closed()
        self.renderer.free()
        self.remember()

    def toggle(self, context, state):
        """Closed -> open in front of you; open and far -> call it to you; open and near -> close it."""
        head = Vector(state.viewer_pose_location)
        action = stick_action(self.state.open, self.state.distance_to(head) / self.state.size)
        if action == CLOSE:
            self.close()
        elif action == CALL:
            self.bring_to_you(state)
            self.remember()
        else:
            self.open(context, state)
        return action

    # -- the laser and the trigger ---------------------------------------------

    def ray_hit(self, pose, matrix):
        """(widget or None, pixel x, distance) when a laser meets the panel (body or handle), else None."""
        if self.state.docked:
            return None
        hit = screen_hit(matrix, pose.aim_location, pose.aim_direction, self.spec)
        if hit is None:
            return None
        pixel_x, pixel_y, distance = hit
        widget = layout.hit_test(self.widgets, pixel_x, pixel_y)
        if widget is None and not self.spec.on_body(pixel_x, pixel_y):
            return None
        return widget, pixel_x, distance

    def set_hover(self, context, hand, hit):
        """This hand's laser result for the tick (None = not on this panel). A held slider follows the laser."""
        panel = self.state
        if hit is None:
            panel.hover.pop(hand, None)
            panel.reach.pop(hand, None)
            return
        widget, pixel_x, distance = hit
        panel.reach[hand] = distance
        if widget is None:
            panel.hover.pop(hand, None)
        else:
            panel.hover[hand] = widget.id
        held = panel.pressed.get(hand)
        if held and RUNTIME.hands[hand].trigger_down:
            slider = self.renderer.by_id.get(held)
            if slider is not None and slider.kind == layout.SLIDER and not _paused_blocks(slider) and self.perform(context, slider, pixel_x):
                self.refresh(context)

    def press(self, context, state, hand, hit):
        """A trigger pull with the laser on this panel: the panel takes it (the scene never sees it)."""
        widget, pixel_x, distance = hit
        self.state.reach[hand] = distance
        if widget is not None and widget.kind != layout.HANDLE:
            if self.take_trigger(context, state, hand, widget):
                return True
            if widget.id == layout.PIN_ID:
                done = not _paused_blocks(widget) and self.set_pinned(state, not self.state.pinned)
            else:
                done = False if _paused_blocks(widget) else self.perform(context, widget, pixel_x)
            if done or widget.enabled:
                buzz(context, state, hand, duration=0.015, amplitude=0.5)       # haptic tick
            else:
                buzz(context, state, hand)                                       # disabled: a longer buzz
            self.state.pressed[hand] = widget.id
            self.refresh(context, force=done)
        return True

    def release_triggers(self, context):
        for hand in [hand for hand in self.state.pressed if not RUNTIME.hands[hand].trigger_down]:
            del self.state.pressed[hand]
            self.trigger_released(context)

    # -- the handles -----------------------------------------------------------

    def grip(self, context, state, hand, pose):
        """A grip press. True when it took hold of a handle (by touch, or by the laser on it)."""
        panel = self.state
        if not panel.open or panel.docked or hand in panel.grabs:
            return False
        matrix = panel.matrix()
        if self.take_grip(context, state, hand, matrix):
            return True
        handle_id = near_handle(matrix, pose.grip_location, self.widgets, TOUCH_REACH * panel.size, self.spec)
        hovered = self.renderer.by_id.get(panel.hover.get(hand))
        if handle_id is None and hovered is not None and hovered.kind == layout.HANDLE:
            handle_id = hovered.id
        if handle_id is None or any(grab.handle_id == handle_id for grab in panel.grabs.values()):
            return False
        panel.grabs[hand] = HandleGrab(handle_id, hand_matrix(pose.grip_location, pose.grip_rotation), matrix)
        self._restart_grabs(context, state)
        buzz(context, state, hand, duration=0.02, amplitude=0.3)
        return True

    def _grip_points(self, context, state):
        return {hand: HandPose(context, state, hand, with_grip_rotation=False).grip_location.copy()
                for hand in self.state.grabs}

    def _restart_grabs(self, context, state):
        """Hands changed: every held handle measures from the panel and hands as they are now."""
        matrix = self.state.matrix()
        for hand, grab in self.state.grabs.items():
            pose = HandPose(context, state, hand)
            grab.hand_start, grab.desk_start = hand_matrix(pose.grip_location, pose.grip_rotation), matrix
        self.two_hand = (matrix, self._grip_points(context, state)) if len(self.state.grabs) == 2 else None

    def _drag(self, context, state):
        """Move / scale once per headset frame while handles are held; saves when the last one lets go."""
        panel = self.state
        released = [hand for hand in panel.grabs if not RUNTIME.hands[hand].grip_down]
        if released:
            for hand in released:
                del panel.grabs[hand]
            if panel.grabs:
                self._restart_grabs(context, state)
            else:
                self.two_hand = None
                self.remember()
                return
        if not panel.grabs or RUNTIME.frame == self.last_frame:
            return
        self.last_frame = RUNTIME.frame
        if len(panel.grabs) == 2:
            start_matrix, start_points = self.two_hand
            now_points = self._grip_points(context, state)
            panel.set_matrix(two_hand_matrix(start_matrix, (start_points[LEFT], start_points[RIGHT]),
                                             (now_points[LEFT], now_points[RIGHT]), panel.size, self.spec.scale_range))
        else:
            (hand, grab), = panel.grabs.items()
            pose = HandPose(context, state, hand)
            panel.set_matrix(one_hand_matrix(grab, hand_matrix(pose.grip_location, pose.grip_rotation)))

    def _follow_body(self, state):
        """Pinned: once per headset frame the panel goes to its place in your body frame. A docked panel (on the belt) or a
        held one is not moved."""
        panel = self.state
        if panel.docked or panel.grabs or RUNTIME.frame == self.last_pin_frame:
            return
        self.last_pin_frame = RUNTIME.frame
        panel.follow_body(BODY.update(state))

    def tick(self, context, state):
        """Once per session tick while open, after the lasers (panels.tick). True while a handle is held, or while it is
        pinned (the timer then runs every frame, so it keeps up as you move)."""
        self.ticks += 1
        self._drag(context, state)
        if self.state.pinned:
            self._follow_body(state)
        self.update(context, state)
        if (RUNTIME.ticks + self.check_phase) % MODEL_CHECK_TICKS == 0:
            self.refresh(context)
        return bool(self.state.grabs) or (self.state.pinned and not self.state.docked)

    def draw(self, new_frame):
        self.renderer.draw(self.state, new_frame)
        self.draw_extra(new_frame)


def rescale_all(pivot, old_size, new_size):
    """Your size changed about `pivot`: every panel keeps its size and place relative to you."""
    for each in REGISTRY.values():
        each.state.rescale(pivot, old_size, new_size)


def move_all(world_delta):
    """The view jumped (a viewpoint Go): every placed panel moves by `world_delta` (no scale), so each stays where it
    was relative to you."""
    for each in REGISTRY.values():
        if each.state.placed:
            each.state.move_by(world_delta)
