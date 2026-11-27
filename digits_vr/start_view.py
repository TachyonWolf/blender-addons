# SPDX-License-Identifier: GPL-3.0-or-later
"""Start VR with your head where the desktop 3D View is [user, 2026-11-27: "Put the head where the viewport is when
you hit Start VR"].

Two steps. At start (`prepare`, from `session.configure_session`): the view's eye position and heading become the
CUSTOM base pose (recorded with the Performance record, so the teardown puts the user's own base pose back). The
base pose is the floor of tracking space, so the head would sit one body height above the eye. On the first session
tick with a real headset pose (`settle`) the navigation is turned about the head and lifted so the head lands exactly
on the eye, facing the view's way (yaw only: the world is never rolled or pitched). Your size needs no special case:
the correction uses the head's real pose, which already carries it.

The view is the 3D View the Start button was pressed in (`remember`), else the largest one. A camera view is the
camera's place and an orthographic view sits at its eye distance: both are simply the inverse view matrix."""
import math

from mathutils import Matrix, Quaternion, Vector

from . import move, move_math, scene_record, settings

PENDING = {"eye": None, "yaw": 0.0, "region": None}       # the view to settle on; "region" = the one Start was pressed in
BASE_POSE = ("xr_session_settings.base_pose_type", "xr_session_settings.base_pose_location",
             "xr_session_settings.base_pose_angle")


def eye_and_yaw(view_matrix):
    """(eye position, heading angle) of a view matrix. Heading as the base pose angle wants it (0 = looking along +Y).
    Looking straight up or down: the view's up direction gives the heading."""
    world = Matrix(view_matrix).inverted()
    rotation = world.to_3x3()
    forward = rotation @ Vector((0.0, 0.0, -1.0))
    if math.hypot(forward.x, forward.y) < 1e-3:
        forward = rotation @ Vector((0.0, 1.0, 0.0)) * (1 if forward.z < 0 else -1)
    return world.translation.copy(), math.atan2(forward.y, forward.x) - math.pi / 2


def remember(context):
    """Start was pressed in this 3D View (called by the operator before the session starts)."""
    space = context.space_data
    PENDING["region"] = space.region_3d if space is not None and space.type == 'VIEW_3D' else None


def _region(context):
    if PENDING["region"] is not None:
        return PENDING["region"]
    best, best_size = None, 0
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            if area.type == 'VIEW_3D' and region and region.width * region.height > best_size:
                best, best_size = area.spaces.active.region_3d, region.width * region.height
    return best


def prepare(context):
    """Pin the base pose at the view's eye. Returns the record changes ([] when off or no 3D View is open)."""
    region, PENDING["region"] = _region(context), None
    PENDING["eye"] = None
    if settings.get("start_at") != 'VIEWPORT' or region is None:
        return []
    eye, yaw = eye_and_yaw(region.view_matrix)
    PENDING.update(eye=eye, yaw=yaw)
    window_manager = context.window_manager
    return [(window_manager, BASE_POSE[0], 'CUSTOM'), (window_manager, BASE_POSE[1], tuple(eye)),
            (window_manager, BASE_POSE[2], yaw)]


def correction(navigation_location, navigation_rotation, head, head_forward, eye, yaw):
    """New (navigation location, rotation): turned about the head to face `yaw`, then moved so the head is on `eye`."""
    head_yaw = math.atan2(head_forward[1], head_forward[0]) - math.pi / 2
    turn = (yaw - head_yaw + math.pi) % (2 * math.pi) - math.pi if math.hypot(head_forward[0], head_forward[1]) > 1e-4 else 0.0
    location, rotation = move_math.turn_about(Vector(navigation_location), Quaternion(navigation_rotation), Vector(head), turn)
    return location + (Vector(eye) - Vector(head)), rotation


def settle(state):
    """Session tick: once the headset has a pose, put the head on the view's eye. Returns True when it moved you."""
    eye = PENDING["eye"]
    head = Vector(state.viewer_pose_location)
    if eye is None or head.length < 1e-6:
        return False
    PENDING["eye"] = None
    forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
    state.navigation_location, state.navigation_rotation = correction(
        state.navigation_location, state.navigation_rotation, head, forward, eye, PENDING["yaw"])
    move.size_changed(state)
    return True


def clear():
    PENDING.update(eye=None, region=None)
