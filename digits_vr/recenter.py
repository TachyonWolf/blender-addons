# SPDX-License-Identifier: GPL-3.0-or-later
"""Both stick clicks held: 2 s = recenter, 6 s = failsafe settings (bpy side; `sticks.py` calls these).

Recenter turns you (about your head) to face the selection, or the middle of the scene, and stands you at eye height
on the floor plane. Your size stays. Failsafe (a safe state when something ruined the frame rate): Solid shading,
heavy modifiers off, Hide glass on, compositor off, Your size 1:1, the desk reset in front of you,
lasers on, Pause off. VR-only: it only uses the existing settings (their listeners write the VR records) and Your
size, so the user's own file settings are never touched beyond what VR already records."""
import time

from mathutils import Quaternion, Vector

from . import desk, desk_qol_math as math_, move, settings, size_state, user_scale



def scene_points(context):
    """World points the recenter faces: selected objects (or the selected bones in Pose mode), else the middle of
    every visible object (bounding box centres)."""
    selected = list(context.selected_objects)
    if selected:
        if context.mode == 'POSE' and context.active_object and context.active_object.type == 'ARMATURE':
            ob = context.active_object
            bones = [ob.matrix_world @ bone.head for bone in ob.pose.bones if bone.select]
            if bones:
                return bones
        return [ob.matrix_world.translation for ob in selected]
    points = []
    for ob in context.view_layer.objects:
        if ob.visible_get() and ob.type not in {'CAMERA', 'LIGHT'}:
            points.append(ob.matrix_world @ (sum((Vector(corner) for corner in ob.bound_box), Vector()) / 8)
                          if ob.type != 'EMPTY' else ob.matrix_world.translation)
    return points


def recenter(context, state):
    """Face the selection (or the scene), standing at eye height. Returns True."""
    head = Vector(state.viewer_pose_location)
    forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
    target = math_.centre_of(scene_points(context))
    head_height = settings.get("plane_height") + size_state.eye_height()
    location, rotation = math_.recenter(state.navigation_location, Quaternion(state.navigation_rotation), head, forward,
                                        target, head_height)
    state.navigation_rotation = rotation
    state.navigation_location = location
    move.size_changed(state)           # the floor offset follows the new height
    math_.NOTICE.show(math_.RECENTER_NOTE, time.perf_counter())
    return True


def failsafe(context, state):
    """Safe settings for a ruined frame rate (see the module text). Returns True."""
    values = {name: value for name, value in math_.FAILSAFE_SETTINGS.items() if name in settings.current()}
    settings.put_many(values)
    from . import perf_state
    perf_state.reapply(context.scene)
    context.window_manager.xr_session_settings.shading.type = 'SOLID'
    user_scale.set_size(context, state, 1.0)
    desk.reset(context, state)
    math_.NOTICE.show(math_.FAILSAFE_NOTE, time.perf_counter())
    return True
