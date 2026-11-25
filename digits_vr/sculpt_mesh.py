# SPDX-License-Identifier: GPL-3.0-or-later
"""What a VR stroke must know about the mesh it works on: the facts sculpt_math.kind_for judges, and the desktop pixel
Blender's stroke starts from (its ray must hit the mesh; the 3D location then places the brush)."""
import bpy
import numpy as np

from . import modifier_state, sculpt_math as math_
from .context_helper import view3d_override_showing

SAMPLED_FACES = 96


def facts(context, ob, brush):
    mesh = ob.data if ob is not None and ob.type == 'MESH' else None
    if mesh is None:
        return {"mesh": False}
    keys = mesh.shape_keys is not None
    active_key = ob.active_shape_key if keys else None
    multires = [mod for mod in ob.modifiers if mod.type == 'MULTIRES']
    plane = brush is not None and brush.sculpt_brush_type == 'PLANE'
    return {"mesh": True, "editable": bool(mesh.is_editable and ob.is_editable),
            "others": any(other.mode == 'SCULPT' and other != ob for other in context.view_layer.objects),
            "locked_key": bool(active_key and (active_key.lock_shape or active_key.mute)), "keys": keys,
            "brush_type": brush.sculpt_brush_type if brush is not None else "",
            "stroke_method": brush.stroke_method if brush is not None else "",
            "stabilized": plane and (brush.stabilize_normal > 0 or brush.stabilize_plane > 0),
            "multires_off": any(modifier_state.is_off_for_vr(context.scene, ob, mod) for mod in multires),
            "multires": any(mod.show_viewport for mod in multires), "dyntopo": ob.use_dynamic_topology_sculpting,
            "vertices": len(mesh.vertices)}


def hit_pixel(context, ob, override):
    """The centre of a face as it is drawn (a ray through it always meets the mesh), or None when none is in view."""
    evaluated = ob.evaluated_get(context.evaluated_depsgraph_get())
    mesh = evaluated.data
    count = len(mesh.polygons)
    if not count:
        return None
    step = max(count // SAMPLED_FACES, 1)
    faces = [mesh.polygons[index] for index in range(step // 2, count, step)]
    faces = [face for face in faces if not face.hide]
    if not faces:
        return None
    matrix = ob.matrix_world
    turn = matrix.to_3x3().inverted_safe().transposed()
    points = [matrix @ face.center for face in faces]
    normals = [(turn @ face.normal).normalized() for face in faces]
    region, view = override["region"], override["area"].spaces.active.region_3d
    return math_.pick_pixel(points, normals, view.perspective_matrix, -view.view_matrix.inverted_safe().col[2].xyz,
                            region.width, region.height)


class DesktopView:
    """The 3D View a stroke goes through and its hit pixel; looked up again when that view moves."""

    def __init__(self, context, ob):
        self.override = view3d_override_showing(context, ob)
        self.key = self.pixel = None
        if self.override:
            self.refresh(context, ob)

    def refresh(self, context, ob):
        region, view = self.override["region"], self.override["area"].spaces.active.region_3d
        key = (region.width, region.height, tuple(tuple(row) for row in view.perspective_matrix))
        if key != self.key:
            self.key, self.pixel = key, hit_pixel(context, ob, self.override)

    @property
    def usable(self):
        return self.override is not None and self.pixel is not None

    def on_screen(self, world_direction):
        """A world direction on the desktop screen, in pixels (length does not matter)."""
        turned = self.override["area"].spaces.active.region_3d.view_matrix.to_3x3() @ world_direction
        return turned.x, turned.y


def drawn_points(context, ob):
    """The vertices as drawn (deformed), in object space, flat."""
    mesh = ob.evaluated_get(context.evaluated_depsgraph_get()).data
    values = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.attributes["position"].data.foreach_get("vector", values)
    return values


def evaluated_box(ob):
    """(low, high) of the object's drawn bounds, in its own space."""
    corners = np.array([corner[:] for corner in ob.bound_box])
    return tuple(corners.min(axis=0)), tuple(corners.max(axis=0))
