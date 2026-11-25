# SPDX-License-Identifier: GPL-3.0-or-later
"""What a tool gun shot hits: the target (object or bone), the spot on a surface, the thing that moves (a character's
rig for its meshes) and how that thing rests on a surface."""
from dataclasses import dataclass

import numpy as np
from mathutils import Vector

from . import object_shapes, size_state
from .picking import BONE, OBJECT, Picker, find_object, is_linked
from .runtime import RUNTIME

SPOT_SKIPS = 64              # surfaces a spot ray passes through (the moved thing's own layers)
CLEARANCE_POINTS = 1500      # the lowest vertices Remove clipping checks


class Refused(Exception):
    """A shot that can't be done: buzz, and the reason goes to the menu's note."""


@dataclass
class Shot:
    """One trigger pull: the hand and its pose then."""
    hand: str
    pose: object

    @property
    def ray(self):
        return self.pose.aim_location, self.pose.aim_direction, size_state.laser_length()


def pick(context, shot, bones=False):
    """The Target under the laser; Refused on empty space or while a hand holds it."""
    target = Picker(context, RUNTIME.cache).laser(bones, *shot.ray)
    if target is None:
        raise Refused("Nothing there")
    if target.key() in RUNTIME.grabbed:
        raise Refused("A hand holds it")
    return target


def refuse_linked(*owners):
    if any(is_linked(owner) for owner in owners):
        raise Refused("Linked: can't be changed here")


def pick_object(context, shot, change=True):
    ob = pick(context, shot).find_object(context.blend_data)
    if ob is None:
        raise Refused("Nothing there")
    if change:
        refuse_linked(ob)
    return ob


def pick_bone(context, shot):
    """(armature, pose bone) under the laser (Pose mode)."""
    target = pick(context, shot, bones=True)
    ob = target.find_object(context.blend_data)
    pose_bone = ob.pose.bones.get(target.bone_name) if ob is not None and target.kind == BONE else None
    if pose_bone is None:
        raise Refused("Nothing there")
    refuse_linked(ob)
    return ob, pose_bone


def find(context, name):
    """What the first shot picked, or None when it is gone."""
    ob = find_object(context.blend_data, name)
    if ob is None or ob.name not in context.view_layer.objects:
        return None
    if (OBJECT, name, "") in RUNTIME.grabbed:
        raise Refused("A hand holds it")
    refuse_linked(ob)
    return ob


def point(context, shot):
    """The world point the laser hits (a surface, a line or a bone)."""
    target = pick(context, shot)
    return shot.pose.aim_location + shot.pose.aim_direction * target.distance


def pick_mover(context, shot):
    """The thing to move: the shot object, or its rig."""
    mover = mover_of(pick_object(context, shot))
    refuse_linked(mover)
    if (OBJECT, mover.name_full, "") in RUNTIME.grabbed:
        raise Refused("A hand holds it")
    return mover


def rig_of(ob):
    """The armature an object is, is deformed by or hangs on, or None."""
    if ob.type == 'ARMATURE':
        return ob
    rig = next((modifier.object for modifier in ob.modifiers if modifier.type == 'ARMATURE' and modifier.object), None)
    parent = ob.parent
    while rig is None and parent is not None:
        rig, parent = (parent if parent.type == 'ARMATURE' else None), parent.parent
    return rig


def mover_of(ob):
    return rig_of(ob) or ob


def parts_of(context, mover):
    """`mover` and everything that comes along: its children, and for a rig the meshes it deforms."""
    parts = [mover, *mover.children_recursive]
    if mover.type == 'ARMATURE':
        parts += [ob for ob in context.view_layer.objects if ob not in parts and rig_of(ob) == mover]
    return parts


def _shapes(context, mover):
    return [ob for ob in parts_of(context, mover) if ob.type in object_shapes.SURFACE_TYPES and ob.visible_get()]


def spot(context, shot, mover=None):
    """The picking.SurfaceHit under the laser, passing through `mover`'s own parts."""
    skip = {ob.name_full for ob in parts_of(context, mover)} if mover else ()
    found = Picker(context, RUNTIME.cache).surface_hit(*shot.ray, skip=skip, skips=SPOT_SKIPS)
    if found is None:
        raise Refused("No surface there")
    return found


def rest_point(context, mover, normal):
    """The point of `mover` that goes on a spot: below its origin, at the lowest level of its boxes along `normal`."""
    depsgraph = context.evaluated_depsgraph_get()
    origin = mover.matrix_world.translation
    levels = [(ob.matrix_world @ Vector(corner) - origin).dot(normal)
              for ob in _shapes(context, mover) for corner in ob.evaluated_get(depsgraph).bound_box]
    return origin + normal * min(levels, default=0.0)


def _points(context, mover):
    clouds = []
    for ob in _shapes(context, mover):
        geometry = object_shapes.shape_geometry(ob)
        if geometry is not None and len(geometry[0]):
            world = np.array(ob.matrix_world)
            clouds.append(np.asarray(geometry[0]) @ world[:3, :3].T + world[:3, 3])
    return np.vstack(clouds) if clouds else np.array([tuple(mover.matrix_world.translation)])


def clearing_shift(context, mover, hit):
    """How far `mover` goes along the hit's normal to sit on that surface: exact under its lowest vertices, else (no
    surface below them, an instance) on the plane of the hit."""
    points, normal = _points(context, mover), np.array(hit.normal)
    levels = (points - np.array(hit.location)) @ normal
    if len(levels) > CLEARANCE_POINTS:
        lowest = np.argpartition(levels, CLEARANCE_POINTS)[:CLEARANCE_POINTS]
        height = float(np.ptp(levels))
        points, levels = points[lowest], levels[lowest]
    else:
        height = float(np.ptp(levels))
    flat_shift = -float(levels.min())
    if hit.instanced:
        return flat_shift
    depsgraph, surface = context.evaluated_depsgraph_get(), hit.owner
    inverse, reach = surface.matrix_world.inverted_safe(), max(height, 1e-3)
    down = inverse.to_3x3() @ -hit.normal
    distance = down.length * reach * 3.0
    shifts = []
    for point, level in zip(points.tolist(), levels.tolist()):
        start = Vector(point) + hit.normal * (reach - level)
        found, location, _normal, _face = surface.ray_cast(inverse @ start, down, distance=distance, depsgraph=depsgraph)
        if found:
            shifts.append((surface.matrix_world @ location - hit.location).dot(hit.normal) - level)
    return max(shifts, default=flat_shift)
