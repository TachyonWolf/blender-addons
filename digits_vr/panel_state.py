# SPDX-License-Identifier: GPL-3.0-or-later
"""Every floating panel's position, size and open / closed state, plus the pure math for placing one, pointing a
laser at it and moving / scaling it with its handles. mathutils only (no bpy), so it is tested headless.

A panel is drawn from ONE transform (location, rotation, scale): a scale change is one matrix. Its scale is a WORLD
scale; its size relative to you (scale / size) is what the spec's scale_range clamps."""
import math
from dataclasses import dataclass, field

from mathutils import Matrix, Quaternion, Vector

from . import pin_math, scale_math
from .panel_layout import HANDLE
from .transform_math import hand_delta

NEAR_DISTANCE = 1.0            # within this of the headset = near (a toggle closes it), else it is called to you
OPEN_DISTANCE = 0.5            # opens this far in front of you
OPEN_DROP = 0.2                # and this far below eye level
TILT_DEGREES = 30.0            # leaning back towards you, like a desk top
TOUCH_REACH = 0.07             # a hand this close to a handle (metres) can grab it
OPEN, CALL, CLOSE = 'OPEN', 'CALL', 'CLOSE'


@dataclass
class HandleGrab:
    """One hand holding a handle: where the hand and the panel were when it took hold."""
    handle_id: str
    hand_start: Matrix
    desk_start: Matrix
    start_value: float = 0.0            # a resize handle: the panel's body height (pixels) when it took hold


@dataclass
class ListDrag:
    """A trigger pressed on a scrolling list: it is a click on `widget` until the laser moves past the threshold, then a scroll."""
    bar_id: str
    start_py: float
    start_value: float
    widget: object = None       # the row pressed (None: the gap between rows)
    pixel_x: float = 0.0
    scrolled: bool = False


@dataclass
class PanelState:
    open: bool = False
    location: Vector = field(default_factory=lambda: Vector((0.0, 0.0, 1.0)))
    rotation: Quaternion = field(default_factory=Quaternion)
    scale: float = 1.0                                  # WORLD scale
    size: float = 1.0                                   # your size (size_state): the panel keeps its size relative to you
    scale_range: tuple = (0.5, 2.5)
    docked: bool = False                                # sitting on the tool belt (belt.py): no laser, poke or handle input
    placed: bool = False                                # a position exists (remembered or set by opening)
    hover: dict = field(default_factory=dict)           # hand -> widget id under that hand's laser
    reach: dict = field(default_factory=dict)           # hand -> laser distance to the panel (hits only)
    grabs: dict = field(default_factory=dict)           # hand -> HandleGrab
    pressed: dict = field(default_factory=dict)         # hand -> widget id held with the trigger
    laser_pixel: dict = field(default_factory=dict)     # hand -> (pixel x, pixel y) where its laser meets the panel
    drags: dict = field(default_factory=dict)           # hand -> ListDrag: a trigger down on a scrolling list
    pinned: bool = False                                # keeps its place relative to your body frame (follow_body)
    pin_offset: object = None                           # pin_math.PinOffset, None = take it from where the panel is
    pin_last: object = None                             # the matrix the pin gave it last (to see someone else move it)

    def matrix(self):
        return Matrix.LocRotScale(self.location, self.rotation, (self.scale,) * 3)

    def set_matrix(self, matrix):
        location, rotation, scale = matrix.decompose()
        self.location, self.rotation = location, rotation
        self.scale = scale.x if self.docked else clamp_scale(scale.x / self.size, self.scale_range) * self.size   # on the belt: any size

    def rescale(self, pivot, old_size, new_size):
        """Your size changed about the world point `pivot`: the panel scales with it, so it looks the same to you."""
        self.location = scale_math.scale_about(self.location, Vector(pivot), old_size, new_size)
        self.scale *= new_size / old_size
        self.size = new_size

    def move_by(self, world_delta):
        """Move rigidly by a world transform without scale (the view jumped): same place relative to you."""
        location, rotation, _scale = (world_delta @ self.matrix()).decompose()
        self.location, self.rotation = location, rotation.normalized()

    def follow_body(self, frame):
        """Pinned: sit at the remembered place in the body frame `frame`. A panel someone else moved since (a grab, a
        call to you, a belt carry) is kept where it is and the pin takes its new place."""
        now = self.matrix()
        if self.pin_offset is None or (self.pin_last is not None and pin_math.moved(now, self.pin_last, self.size)):
            self.pin_offset = pin_math.capture(frame, now, self.size)
        else:
            self.set_matrix(pin_math.apply(frame, self.pin_offset, self.size))
            now = self.matrix()
        self.pin_last = now

    def distance_to(self, point):
        return (self.location - Vector(point)).length

    def clear_live(self):
        """Forget hovers, holds and grabs (the session ended or the panel closed)."""
        self.hover.clear()
        self.reach.clear()
        self.grabs.clear()
        self.pressed.clear()
        self.drags.clear()
        self.laser_pixel.clear()


def clamp_scale(scale, scale_range=(0.5, 2.5)):
    """A panel's size relative to you, kept within `scale_range`."""
    return min(scale_range[1], max(scale_range[0], scale))


def stick_action(is_open, distance_to_head):
    """A toggle (stick click, a desk button): closed -> open it; open and far -> call it to you; open and near ->
    close it. `distance_to_head` is relative to your size."""
    if not is_open:
        return OPEN
    return CLOSE if distance_to_head <= NEAR_DISTANCE else CALL


def place_in_front(head_location, head_forward, distance=OPEN_DISTANCE, drop=OPEN_DROP, tilt=TILT_DEGREES, side=0.0):
    """(location, rotation) for a panel `distance` in front of the head, `drop` below it and `side` to the right
    (negative: left), its screen turned to face you and leaning back by `tilt` degrees. Only the horizontal part of where you
    look counts (looking up never tips it)."""
    flat = Vector((head_forward[0], head_forward[1], 0.0))
    flat = flat.normalized() if flat.length > 1e-4 else Vector((0.0, 1.0, 0.0))
    right = flat.cross(Vector((0.0, 0.0, 1.0)))
    location = Vector(head_location) + flat * distance + right * side - Vector((0.0, 0.0, drop))
    facing = (flat * distance + right * side).normalized()          # off to the side it still turns to face you
    angle = math.radians(tilt)
    normal = -facing * math.cos(angle) + Vector((0.0, 0.0, math.sin(angle)))     # out of the screen, towards you
    x_axis = Vector((0.0, 0.0, 1.0)).cross(normal).normalized()
    y_axis = normal.cross(x_axis)
    return location, Matrix((x_axis, y_axis, normal)).transposed().to_quaternion()


def screen_hit(matrix, origin, direction, spec):
    """Where a ray meets the panel plane: (pixel x, pixel y, distance) or None (parallel, or behind the origin).
    The distance is along `direction` in world units (the panel's scale does not change it)."""
    inverse = matrix.inverted_safe()
    local_origin = inverse @ Vector(origin)
    local_direction = inverse.to_3x3() @ Vector(direction)
    if abs(local_direction.z) < 1e-9:
        return None
    distance = -local_origin.z / local_direction.z
    if distance <= 0.0:
        return None
    point = local_origin + local_direction * distance
    px, py = spec.local_to_pixel(point.x, point.y)
    return px, py, distance


def near_handle(matrix, point, widgets, reach, spec):
    """The handle widget id whose box a hand at `point` touches (within `reach` metres), or None."""
    inverse = matrix.inverted_safe()
    local = inverse @ Vector(point)
    scale = matrix.median_scale or 1.0
    if abs(local.z) > reach / scale:
        return None
    margin_pixels = reach / (spec.meters_per_pixel * scale)
    px, py = spec.local_to_pixel(local.x, local.y)
    for widget in widgets:
        if widget.kind == HANDLE and (widget.x - margin_pixels <= px <= widget.x + widget.w + margin_pixels
                                      and widget.y - margin_pixels <= py <= widget.y + widget.h + margin_pixels):
            return widget.id
    return None


def one_hand_matrix(grab, hand_now):
    """The panel follows one hand rigidly (location and rotation; its scale stays)."""
    moved = hand_delta(grab.hand_start, hand_now) @ grab.desk_start
    location, rotation, _scale = moved.decompose()
    return Matrix.LocRotScale(location, rotation, (grab.desk_start.median_scale,) * 3)


def two_hand_matrix(start_matrix, start_points, now_points, size=1.0, scale_range=(0.5, 2.5)):
    """Both handles held: the panel scales with the distance between the hands (clamped), turns with the line between
    them, and its middle follows the middle point. Points are (first hand, second hand) in world space. `size` is your
    size: the limits are on the panel's size relative to you."""
    start_vector = Vector(start_points[1]) - Vector(start_points[0])
    now_vector = Vector(now_points[1]) - Vector(now_points[0])
    if start_vector.length < 1e-4 or now_vector.length < 1e-4:
        return start_matrix
    location, rotation, scale = start_matrix.decompose()
    new_scale = clamp_scale(scale.x / size * now_vector.length / start_vector.length, scale_range) * size
    ratio = new_scale / scale.x
    turn = start_vector.rotation_difference(now_vector)
    start_middle = (Vector(start_points[0]) + Vector(start_points[1])) / 2
    now_middle = (Vector(now_points[0]) + Vector(now_points[1])) / 2
    new_location = now_middle + turn @ ((location - start_middle) * ratio)
    return Matrix.LocRotScale(new_location, turn @ rotation, (new_scale,) * 3)
