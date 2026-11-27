# SPDX-License-Identifier: GPL-3.0-or-later
"""Movement (milestone 4), run from the session tick (controls.update calls update()). All in Python through
`navigation_location` / `navigation_rotation` (one write per headset frame): the native nav operators cannot do plane
height, the teleport arc or a stick that is left alone while it turns a grab.

The floor plane engages on the first walk / teleport / height push (a turn alone does not) or when the mode / height changes (a session start does not
move you). Left stick: Walk on plane (level, where you look), Walk on geometry (same, but one ray cast down per frame finds the
ground under your head; your height slides to it at the slide speed, a step above the max step height blocks you), Teleport on plane (hold forward: arc + landing ring on region 'XR',
let go to jump), Free flight (where the head looks or the chosen hand points; level or dead ahead: move_heading / fly_pitch). Right stick: left / right turns (snap or smooth); up / down raises and
lowers the floor plane (plane modes) or flies up / down (Free flight). Idle = two stick reads every other tick; the timer runs every frame only
while a stick is pushed or the arc shows."""
import math
import time

from mathutils import Quaternion, Vector

from . import move_math, settings, size_state, stick_claim
from .action_map import LEFT, RIGHT, buzz, vector
from .hands import HandPose
from .runtime import RUNTIME

PLANE_MODES = ('WALK', 'TELEPORT')
MAX_DROP = 10.0               # m the ground cast reaches below your floor (Walk on geometry); deeper = no ground, you hold
CAST_LIFT = 0.05              # m in your space: the cast starts at least this far above the highest step, so a step edge is hit from above
SLIDE_DONE = 1e-4             # m: a height this near its target is there
IDLE_POLL_TICKS = 2          # idle sticks are polled every other session tick
PLANE_RATE = 0.5              # m/s the right stick raises / lowers the plane
MAX_STEP_SECONDS = 0.1        # a frame hitch never throws you far
FRAME_FALLBACK = 0.02         # without counted headset frames (no draw handler), move every 20 ms
VALID_COLOUR, INVALID_COLOUR = (0.45, 0.95, 0.55, 0.95), (1.0, 0.35, 0.3, 0.9)


class Preview:
    """The teleport arc + ring the overlay draws (world space line pairs). `version` changes with the points."""

    def __init__(self):
        self.points, self.colour, self.version = [], VALID_COLOUR, 0

    def show(self, points, colour):
        self.points, self.colour, self.version = points, colour, self.version + 1

    def clear(self):
        if self.points:
            self.points, self.version = [], self.version + 1


PREVIEW = Preview()
_state = {}


def _reset():
    _state.update(snap=0, aiming=False, moving=False, last_frame=-1, last_time=0.0, edited_height=False,
                  applied=None, offset=0.0, seen=None, floor=None, sliding=False, tp_floor=None, tp_target=None, landing=None, on_geometry=False)
    PREVIEW.clear()


_reset()


def start(_context):
    _reset()
    _state["seen"] = _plane_target()      # a session starts where Blender put you; the plane engages on the first push


def teardown():
    _reset()


def size_changed(state):
    """Your size changed (user_scale.py moved the navigation): the floor stays on the plane, so the distance from
    the plane to the navigation origin is measured again."""
    if _state["tp_floor"] is not None:
        _state["offset"] = state.navigation_location[2] - _state["tp_floor"]
    elif _state["applied"] is not None:
        _state["offset"] = state.navigation_location[2] - _state["applied"][1]
    elif _state["floor"] is not None:          # Walk on geometry: the floor is where it was, only the offset changes
        _state["offset"] = state.navigation_location[2] - _state["floor"]


def visible():
    """Something to draw (the arc), or movement running (its frame count paces the steps)."""
    return bool(PREVIEW.points) or _state["moving"]


def _stick(context, state, hand):
    if stick_claim.blocked(hand):          # this hand's laser is on a list: its stick scrolls it (stick_claim.py)
        return 0.0, 0.0
    return move_math.stick_with_dead_zone(*vector(context, state, "stick", hand))


def _plane_target():
    """(mode, height) the navigation should sit on right now, or None (flight: any height)."""
    mode = settings.get("move_mode")
    return (mode, settings.get("plane_height")) if mode in PLANE_MODES else None


def _snap_to_plane(state):
    """A plane mode (or the plane height) just changed: put the floor on the plane. Entering a plane mode measures
    the floor first (your eyes are eye_height above it right now)."""
    target = _plane_target()
    if target is not None and target != _state["applied"]:
        if _state["applied"] is None or _state["applied"][0] != target[0]:
            _state["offset"] = move_math.floor_offset(state.navigation_location[2], state.viewer_pose_location[2],
                                                      size_state.eye_height())
        state.navigation_location = move_math.plane_location(Vector(state.navigation_location), target[1],
                                                             _state["offset"])
    _state["applied"] = target


def update(context, state):
    """Once per session tick. Returns True while moving or aiming (the timer then runs every frame)."""
    if settings.get("paused"):           # pause.py: the sticks do not move you
        if _state["moving"]:
            _finish()
        return False
    if not _state["moving"] and RUNTIME.ticks % IDLE_POLL_TICKS != 1:
        return False      # idle: the sticks are read every other tick, on the ticks the stick clicks and D-pad skip
    left, right = _stick(context, state, LEFT), _stick(context, state, RIGHT)
    mode = settings.get("move_mode")
    if mode != 'GEO' and _state["floor"] is not None:
        _state.update(floor=None, sliding=False, applied=None)     # left Walk on geometry: a plane mode measures the floor again
    if mode != 'TELEPORT' and _state["tp_floor"] is not None:
        _state.update(tp_floor=None, tp_target=None, sliding=False)     # a teleport landing on geometry is forgotten
    if not (left[0] or left[1] or right[0] or right[1] or _state["aiming"] or _state["sliding"]):
        if _state["moving"]:
            _finish()
        target = _plane_target()
        if _state["applied"] is not None or target != _state["seen"]:   # engaged, or the desk changed mode / height
            _snap_to_plane(state)
        _state["seen"] = target
        return False
    now = time.perf_counter()
    first = not _state["moving"]
    if _state["applied"] is None and (left[0] or left[1] or right[1]):   # a turn alone does not lift you onto the plane
        _snap_to_plane(state)
    if mode == 'GEO' and _state["floor"] is None and (left[0] or left[1]):     # the first walk puts your floor under your eyes
        _state["offset"] = move_math.floor_offset(state.navigation_location[2], state.viewer_pose_location[2],
                                                  size_state.eye_height())
        _state.update(floor=state.navigation_location[2] - _state["offset"], applied=None)
    if first:
        _state.update(moving=True, last_time=now, last_frame=RUNTIME.frame)
    style = settings.get("turn_style")
    snap_direction = 0
    if style == 'SNAP':
        _state["snap"], snap_direction = move_math.snap_edge(_state["snap"], right[0])
    if not snap_direction and RUNTIME.frame == _state["last_frame"] and now - _state["last_time"] < FRAME_FALLBACK:
        return True                      # one step per headset frame
    seconds = 0.0 if first else min(now - _state["last_time"], MAX_STEP_SECONDS)
    _state.update(last_frame=RUNTIME.frame, last_time=now)
    _step(context, state, mode, left, right, style, snap_direction, seconds)
    return True


def _step(context, state, mode, left, right, style, snap_direction, seconds):
    location, rotation = Vector(state.navigation_location), Quaternion(state.navigation_rotation)
    head = Vector(state.viewer_pose_location)
    view_rotation = Quaternion(state.viewer_pose_rotation)
    start_location = location.copy()
    height = settings.get("plane_height")
    hand = (HandPose(context, state, LEFT if settings.get("heading_hand") == 'LEFT' else RIGHT, with_grip_rotation=False).aim_direction
            if mode != 'TELEPORT' and settings.get("move_heading") == 'HAND' else None)
    if mode in ('WALK', 'GEO'):
        location += move_math.walk_delta(view_rotation, left, size_state.scaled(settings.get("walk_speed")), seconds, hand)
    elif mode == 'FLY':
        location += move_math.fly_delta(view_rotation, left, right[1], size_state.scaled(settings.get("fly_speed")), seconds,
                                        hand, settings.get("fly_pitch") == 'FULL')
    else:
        location = _teleport(context, state, location, head, left, height)
    if mode == 'GEO' and _state["floor"] is not None:
        location = _geo_height(context, location, start_location, head, seconds)
    if mode in PLANE_MODES and _state["applied"] is not None:
        if right[1]:
            _state.update(tp_floor=None, tp_target=None, sliding=False)    # the right stick takes the floor back to the plane
            height = move_math.height_step(height, right[1], size_state.scaled(PLANE_RATE), seconds)
            settings.current()["plane_height"] = height     # live; written to the file when the stick rests
            _state["edited_height"] = True
        if _state["tp_floor"] is not None:      # landed on geometry: the floor slides to the surface (Walk on geometry rules)
            floor = move_math.slide_toward(_state["tp_floor"], _state["tp_target"],
                                           settings.get("geo_slide_speed") * _size_factor(), seconds)
            _state.update(tp_floor=floor, sliding=abs(floor - _state["tp_target"]) > SLIDE_DONE)
            location.z = floor + _state["offset"]
        else:
            location.z = height + _state["offset"]
        _state["applied"] = (mode, height)
    angle = (-snap_direction * math.radians(settings.get("snap_angle")) if style == 'SNAP'
             else move_math.smooth_angle(right[0], settings.get("turn_speed"), seconds))
    if angle:
        location, rotation = move_math.turn_about(location, rotation, head + (location - start_location), angle)
        state.navigation_rotation = rotation
    if location != start_location:
        state.navigation_location = location


def _size_factor():
    """Your size relative to normal (eye height and step height scale with it)."""
    return size_state.SIZE.factor


def _ground_under(context, point, floor, max_step):
    """z of the surface below `point` (one ray cast down), or None."""
    origin = Vector((point.x, point.y, max(point.z, floor + max_step + CAST_LIFT * _size_factor())))
    hit, location, _normal, _index, _object, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, -move_math.UP, distance=origin.z - floor + MAX_DROP * _size_factor())
    return location.z if hit else None


def _geo_height(context, location, start_location, head, seconds):
    """Walk on geometry: one cast down at the head's new spot sets the target floor height; the floor slides to it.
    A wall (a step above the max step height) puts you back where you were."""
    scale = _size_factor()
    floor = _state["floor"]
    max_step = settings.get("geo_step_height") * scale
    new_head = head + (location - start_location)
    target, blocked = move_math.ground_target(floor, _ground_under(context, new_head, floor, max_step), max_step)
    if blocked:
        location.x, location.y = start_location.x, start_location.y
    floor = move_math.slide_toward(floor, target, settings.get("geo_slide_speed") * scale, seconds)
    _state.update(floor=floor, sliding=abs(floor - target) > SLIDE_DONE, target=target)
    location.z = floor + _state["offset"]
    return location


def _aim(context, pose, height):
    """(arc points, landing or None, on geometry) of the arc now. Land on Geometry casts a ray along a few arc segments
    (only while aiming) and lands on the first floor-like hit; with no hit it is the plane arc."""
    scale = size_state.SIZE.factor
    if settings.get("teleport_land") == 'GEO':
        samples = move_math.arc_samples(pose.aim_location, pose.aim_direction, scale, height - MAX_DROP * scale)
        graph = context.evaluated_depsgraph_get()
        for start, end in zip(samples, samples[1:]):
            span = end - start
            if span.length < 1e-6:
                continue
            hit, location, normal, _index, _object, _matrix = context.scene.ray_cast(graph, start, span.normalized(),
                                                                                    distance=span.length)
            if hit:
                points = samples[:samples.index(start) + 1] + [location]
                reach = math.hypot(location.x - pose.aim_location.x, location.y - pose.aim_location.y)
                ok = normal.z >= move_math.MIN_LANDING_NORMAL and reach <= move_math.MAX_TELEPORT_RANGE * scale
                return points, (location if ok else None), True
    points, landing = move_math.arc_points(pose.aim_location, pose.aim_direction, height, scale)
    return points, landing, False


def _teleport(context, state, location, head, left, height):
    """Arc while the left stick is held forward; jump on letting go. Returns the (maybe new) navigation location."""
    if not _state["aiming"]:
        if left[1] < move_math.AIM_PRESS:
            return location
        _state["aiming"] = True
    if left[1] >= move_math.AIM_RELEASE:
        pose = HandPose(context, state, LEFT, with_grip_rotation=False)
        points, landing, on_geometry = _aim(context, pose, height)
        if landing is None:
            PREVIEW.show(move_math.strip_to_segments(points), INVALID_COLOUR)
        else:
            PREVIEW.show(move_math.strip_to_segments(points) + move_math.ring_points(landing, move_math.RING_RADIUS * size_state.SIZE.factor), VALID_COLOUR)
        _state.update(landing=landing, on_geometry=on_geometry)
        return location
    landing = _state["landing"]
    on_geometry = _state["on_geometry"]
    _state.update(aiming=False, landing=None)
    PREVIEW.clear()
    if landing is None:
        buzz(context, state, LEFT)
        return location
    buzz(context, state, LEFT, duration=0.02, amplitude=0.4)
    if on_geometry:       # your floor slides from where it is to the surface; a plane landing snaps to the plane as before
        current = _state["tp_floor"] if _state["tp_floor"] is not None else height
        _state.update(tp_floor=current, tp_target=landing.z, sliding=True)
    else:
        _state.update(tp_floor=None, tp_target=None, sliding=False)
    return move_math.teleport_location(location, head, landing)


def _finish():
    """The sticks came to rest: remember the plane height; the next push starts fresh."""
    if _state["edited_height"]:
        settings.put("plane_height", settings.get("plane_height"))
        _state["edited_height"] = False
    _state.update(moving=False, snap=0)
