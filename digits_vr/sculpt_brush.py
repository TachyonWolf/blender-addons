# SPDX-License-Identifier: GPL-3.0-or-later
"""The brush of a VR stroke: Blender's own active Sculpt brush, its size in world metres (the desktop brush's size
until the size gesture sets one for this VR session), and the native stroke call. Blender sizes a brush in pixels of
the desktop view or in the object's space; for each call the size is set in the object's space and put back right
after it, so no brush setting changes."""
from contextlib import contextmanager

import bpy
from mathutils import Vector

from . import sculpt_math as math_

FAR = 1e4            # object-space distance beyond the mesh of the stroke that touches nothing


class Size:
    diameter = None  # m in the world; None = the desktop brush's size


def active():
    return bpy.context.tool_settings.sculpt.brush if bpy.context.tool_settings.sculpt else None


def _size_owner(brush):
    """Where Blender reads this brush's size: shared by all brushes, or the brush's own."""
    return bpy.context.tool_settings.sculpt.unified_paint_settings if brush.use_unified_size else brush


def strength_owner(brush):
    """Where Blender reads this brush's strength: shared by all brushes, or the brush's own."""
    return bpy.context.tool_settings.sculpt.unified_paint_settings if brush.use_unified_strength else brush


def _used_brushes():
    """The active brush, and the Smooth brushes (A held switches to one for the call)."""
    return [active()] + [brush for brush in bpy.data.brushes if brush.sculpt_brush_type == 'SMOOTH' and brush != active()]


def object_scale(ob):
    return math_.mean_scale(ob.matrix_world.to_3x3())


def diameter(ob, override):
    """World diameter the next stroke has."""
    if Size.diameter is not None:
        return Size.diameter
    owner = _size_owner(active())
    if owner.use_locked_size == 'SCENE':
        return owner.unprojected_size * object_scale(ob)
    from bpy_extras.view3d_utils import region_2d_to_location_3d
    region, view = override["region"], override["area"].spaces.active.region_3d
    centre = ob.matrix_world.translation
    middle = Vector((region.width / 2, region.height / 2))
    first, second = (region_2d_to_location_3d(region, view, middle + Vector((x, 0)), centre) for x in (0.0, owner.size))
    return min(max((second - first).length, math_.SIZE_RANGE[0]), math_.SIZE_RANGE[1])


@contextmanager
def world_size(ob, world_diameter):
    """The brush measured in the scene at this size while inside (Blender reads it at the stroke's start)."""
    owners = []
    for brush in _used_brushes():
        owner = _size_owner(brush)
        if owner not in owners:
            owners.append(owner)
    kept = [(owner, owner.use_locked_size, owner.unprojected_size) for owner in owners]
    try:
        for owner in owners:
            owner.use_locked_size = 'SCENE'
            owner.unprojected_size = world_diameter / object_scale(ob)
        yield
    finally:
        for owner, lock, size in kept:
            owner.use_locked_size, owner.unprojected_size = lock, size


def element(local_point, pixel, time_, pressure, start):
    return {"name": "", "is_start": start, "location": local_point, "mouse": pixel, "mouse_event": pixel,
            "pressure": pressure, "size": 1.0, "time": time_, "x_tilt": 0.0, "y_tilt": 0.0}


def stroke(elements, push=False, invert=False, smooth=False):
    """Blender's own brush stroke (the caller has the 3D View override). push=False: no undo step (one is left pending
    inside Blender: see clear_pending)."""
    return bpy.ops.sculpt.brush_stroke('EXEC_DEFAULT', push, stroke=elements, mode='INVERT' if invert else 'NORMAL',
                                       brush_toggle='SMOOTH' if smooth else 'None')


def touch_nothing(pixel, push=False):
    """A stroke far from the mesh. After a live call it makes Blender's pending undo step an EMPTY one, so a foreign
    undo push can't record half a stroke (guard A); with push=True that empty step is pushed, so nothing is pending."""
    stroke([element((FAR, FAR, FAR), pixel, 0.0, 1.0, True)], push=push)
