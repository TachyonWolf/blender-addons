# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain maths of the Placement tools (no bpy; tested in tests/test_placement.py): which Blender snap the drop uses,
where a single click puts the item when Live Follow is off, and the dial angle that turns the Front Axis towards
the mouse before Blender's Rotate takes over. Also the surface frame decals sit on (`surface_frame`) and the maths of
the decal handles (`drag_scale`, `drag_angle`, `snap_angle`, `precise`)."""

from math import atan2

from mathutils import Matrix, Vector

AXES = {"X": Vector((1, 0, 0)), "Y": Vector((0, 1, 0)), "Z": Vector((0, 0, 1))}
TINY = 1e-6


def axis_vector(name):
    """'X', '-Y', ... as a unit vector."""
    return -AXES[name[1:]] if name.startswith("-") else AXES[name].copy()


def snap_elements(place_mode, set_depth):
    """Blender snap for Live Follow: Place On = Face; Middle of Depth = Volume (centred inside the object under the
    mouse); Set Depth = Face, then the item is pushed Depth further once."""
    return {'VOLUME'} if place_mode == 'MIDDLE' and not set_depth else {'FACE'}


def click_point(first, second, direction, place_mode, set_depth, depth):
    """Live Follow off: where the click puts the item, from the first and second ray hit (None = no hit), or None.
    Place On = first hit; Set Depth = Depth past the first hit; Middle of Depth = halfway to the second hit."""
    if first is None:
        return None
    if place_mode == 'SURFACE':
        return first
    if set_depth:
        return first + direction.normalized() * depth
    return (first + second) / 2 if second is not None else None


def ray_plane_point(origin, direction, centre, normal):
    """Where the ray meets the plane through `centre` with `normal`, or None (parallel, or behind the eye)."""
    facing = direction.dot(normal)
    if abs(facing) < TINY:
        return None
    distance = (centre - origin).dot(normal) / facing
    return origin + direction * distance if distance > 0 else None


def spin_angle(front, toward, axis):
    """Signed angle (radians, right-handed around the unit `axis`, as Blender's Rotate counts it) that turns
    `front` so its part flat on the dial points along the flat part of `toward`; None when either lies along
    the axis."""
    front_flat = front - axis * front.dot(axis)
    toward_flat = toward - axis * toward.dot(axis)
    if front_flat.length < TINY or toward_flat.length < TINY:
        return None
    front_flat.normalize()
    toward_flat.normalize()
    return atan2(axis.dot(front_flat.cross(toward_flat)), front_flat.dot(toward_flat))


def default_up(normal):
    """An "up" for a surface with `normal`: world Z laid flat on the surface, or world Y where the surface faces
    straight up or down."""
    for candidate in (AXES["Z"], AXES["Y"]):
        flat = candidate - normal * candidate.dot(normal)
        if flat.length > 0.1:
            return flat.normalized()
    return AXES["X"].copy()


def surface_frame(point, normal, up, angle=0.0):
    """4x4 world matrix of a frame on a surface: origin `point`, local Z along `normal`, local Y along `up` laid
    flat on the surface (or `default_up` when `up` is too close to the normal), then turned by `angle` (radians)
    around the normal. Scale 1."""
    z_axis = normal.normalized()
    y_axis = up - z_axis * up.dot(z_axis)
    y_axis = y_axis.normalized() if y_axis.length > TINY * 100 else default_up(z_axis)
    x_axis = y_axis.cross(z_axis)
    turned = Matrix.Rotation(angle, 3, z_axis)
    x_axis, y_axis = turned @ x_axis, turned @ y_axis
    frame = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    frame.translation = point
    return frame


PRECISE = 0.1   # Shift while dragging a handle: changes go this much slower (Blender's precise convention)


def precise(start, value, is_precise):
    """`value` as dragged from `start`; with Shift held only PRECISE of the change is applied."""
    return start + (value - start) * PRECISE if is_precise else value


def drag_scale(centre, start_point, point):
    """How much a corner drag scales: distance of `point` from `centre` over that of `start_point` (None when the
    drag started on the centre)."""
    start_distance = (start_point - centre).length
    if start_distance < TINY:
        return None
    return (point - centre).length / start_distance


def drag_angle(centre, start_point, point, normal):
    """Signed angle (radians, right-handed around `normal`) a rotate drag turned from `start_point` to `point`
    around `centre`, or None."""
    return spin_angle(start_point - centre, point - centre, normal.normalized())


def snap_angle(angle, step):
    """`angle` rounded to whole `step`s (Ctrl while rotating)."""
    return round(angle / step) * step if step > 0 else angle
