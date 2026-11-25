# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's position, size and open / closed state, plus the pure math for placing it, pointing a laser at it and
moving / scaling it with the handles. mathutils only (no bpy), so it is tested headless.

The desk is drawn from ONE transform (location, rotation, scale): a scale change is one matrix."""
import math
from dataclasses import dataclass, field

from mathutils import Matrix, Quaternion, Vector

from . import desk_layout
from .transform_math import hand_delta

SCALE_RANGE = (0.5, 2.5)
NEAR_DISTANCE = 1.0            # stick click: within this of the headset = near (close it), else call it
OPEN_DISTANCE = 0.5            # opens this far in front of you
OPEN_DROP = 0.2                # and this far below eye level
TILT_DEGREES = 30.0            # leaning back towards you, like a desk top
TOUCH_REACH = 0.07             # a hand this close to a handle (metres) can grab it
OPEN, CALL, CLOSE = 'OPEN', 'CALL', 'CLOSE'


@dataclass
class HandleGrab:
    """One hand holding a handle: where the hand and the desk were when it took hold."""
    handle_id: str
    hand_start: Matrix
    desk_start: Matrix


@dataclass
class DeskState:
    open: bool = False
    location: Vector = field(default_factory=lambda: Vector((0.0, 0.0, 1.0)))
    rotation: Quaternion = field(default_factory=Quaternion)
    scale: float = 1.0                                  # WORLD scale: its size relative to you (scale / size) is what clamps
    size: float = 1.0                                   # your size (size_state): the desk keeps its size relative to you
    tab: str = 'grab'
    display_more: bool = False                          # Display tab: showing the second page
    placed: bool = False                                # a position exists (remembered or set by opening)
    hover: dict = field(default_factory=dict)           # hand -> widget id under that hand's laser
    reach: dict = field(default_factory=dict)           # hand -> laser distance to the desk (hits only)
    grabs: dict = field(default_factory=dict)           # hand -> HandleGrab
    pressed: dict = field(default_factory=dict)         # hand -> widget id held with the trigger

    def matrix(self):
        return Matrix.LocRotScale(self.location, self.rotation, (self.scale,) * 3)

    def set_matrix(self, matrix):
        location, rotation, scale = matrix.decompose()
        self.location, self.rotation = location, rotation
        self.scale = clamp_scale(scale.x / self.size) * self.size

    def rescale(self, pivot, old_size, new_size):
        """Your size changed about the world point `pivot`: the desk scales with it, so it looks the same to you."""
        ratio = new_size / old_size
        self.location = Vector(pivot) + (self.location - Vector(pivot)) * ratio
        self.scale *= ratio
        self.size = new_size

    def distance_to(self, point):
        return (self.location - Vector(point)).length

    def clear_live(self):
        """Forget hovers, holds and grabs (the session ended or the desk closed)."""
        self.hover.clear()
        self.reach.clear()
        self.grabs.clear()
        self.pressed.clear()


DESK = DeskState()


def clamp_scale(scale):
    """The desk's size relative to you, kept within SCALE_RANGE."""
    return min(SCALE_RANGE[1], max(SCALE_RANGE[0], scale))


def stick_action(is_open, distance_to_head):
    """Right stick click: closed -> open it; open and far -> call it to you; open and near -> close it."""
    if not is_open:
        return OPEN
    return CLOSE if distance_to_head <= NEAR_DISTANCE else CALL


def place_in_front(head_location, head_forward, distance=OPEN_DISTANCE, drop=OPEN_DROP, tilt=TILT_DEGREES):
    """(location, rotation) for a desk `distance` in front of the head and `drop` below it, its screen facing you and
    leaning back by `tilt` degrees. Only the horizontal part of where you look counts (looking up never tips it)."""
    flat = Vector((head_forward[0], head_forward[1], 0.0))
    flat = flat.normalized() if flat.length > 1e-4 else Vector((0.0, 1.0, 0.0))
    location = Vector(head_location) + flat * distance - Vector((0.0, 0.0, drop))
    angle = math.radians(tilt)
    normal = -flat * math.cos(angle) + Vector((0.0, 0.0, math.sin(angle)))     # out of the screen, towards you
    x_axis = Vector((0.0, 0.0, 1.0)).cross(normal).normalized()
    y_axis = normal.cross(x_axis)
    return location, Matrix((x_axis, y_axis, normal)).transposed().to_quaternion()


def screen_hit(matrix, origin, direction):
    """Where a ray meets the desk plane: (pixel x, pixel y, distance) or None (parallel, or behind the origin).
    The distance is along `direction` in world units (the desk's scale does not change it)."""
    inverse = matrix.inverted_safe()
    local_origin = inverse @ Vector(origin)
    local_direction = inverse.to_3x3() @ Vector(direction)
    if abs(local_direction.z) < 1e-9:
        return None
    distance = -local_origin.z / local_direction.z
    if distance <= 0.0:
        return None
    point = local_origin + local_direction * distance
    px, py = desk_layout.local_to_pixel(point.x, point.y)
    return px, py, distance


def near_handle(matrix, point, widgets, reach=TOUCH_REACH):
    """The handle widget id whose box a hand at `point` touches (within `reach` metres), or None."""
    inverse = matrix.inverted_safe()
    local = inverse @ Vector(point)
    scale = matrix.median_scale or 1.0
    margin_pixels = reach / (desk_layout.METERS_PER_PIXEL * scale)
    px, py = desk_layout.local_to_pixel(local.x, local.y)
    if abs(local.z) > reach / scale:
        return None
    for widget in widgets:
        if widget.kind == desk_layout.HANDLE and (widget.x - margin_pixels <= px <= widget.x + widget.w + margin_pixels
                                                  and widget.y - margin_pixels <= py <= widget.y + widget.h + margin_pixels):
            return widget.id
    return None


def one_hand_matrix(grab, hand_now):
    """The desk follows one hand rigidly (location and rotation; its scale stays)."""
    moved = hand_delta(grab.hand_start, hand_now) @ grab.desk_start
    location, rotation, _scale = moved.decompose()
    return Matrix.LocRotScale(location, rotation, (grab.desk_start.median_scale,) * 3)


def two_hand_matrix(start_matrix, start_points, now_points, size=1.0):
    """Both handles held: the desk scales with the distance between the hands (clamped), turns with the line between
    them, and its middle follows the middle point. Points are (first hand, second hand) in world space. `size` is your
    size: the limits are on the desk's size relative to you."""
    start_vector = Vector(start_points[1]) - Vector(start_points[0])
    now_vector = Vector(now_points[1]) - Vector(now_points[0])
    if start_vector.length < 1e-4 or now_vector.length < 1e-4:
        return start_matrix
    location, rotation, scale = start_matrix.decompose()
    new_scale = clamp_scale(scale.x / size * now_vector.length / start_vector.length) * size
    ratio = new_scale / scale.x
    turn = start_vector.rotation_difference(now_vector)
    start_middle = (Vector(start_points[0]) + Vector(start_points[1])) / 2
    now_middle = (Vector(now_points[0]) + Vector(now_points[1])) / 2
    new_location = now_middle + turn @ ((location - start_middle) * ratio)
    return Matrix.LocRotScale(new_location, turn @ rotation, (new_scale,) * 3)
