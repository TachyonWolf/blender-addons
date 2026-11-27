# SPDX-License-Identifier: GPL-3.0-or-later
"""The drag brushes (Grab, Elastic Grab, Snake Hook, Pose; sculpt_drag_math.py) on a live mesh: what they read from
Blender's brush and the mesh, and the positions they write each headset frame. sculpt_stroke.py runs them like the
native live strokes: plain meshes only, and sculpt_commit.py makes the whole stroke ONE native undo step."""
import numpy as np

from . import sculpt_drag_math as drag_math

CURVE_SAMPLES = 64
HIDE, MASK = ".hide_vert", ".sculpt_mask"


def _attribute(mesh, name, kind, field):
    attribute = mesh.attributes.get(name)
    if attribute is None or not len(attribute.data):
        return None
    values = np.zeros(len(mesh.vertices), kind)
    attribute.data.foreach_get(field, values)
    return values


def factor(mesh):
    """Per vertex: 1 - mask, 0 where hidden (Blender's brushes skip hidden vertices and scale by the mask)."""
    values = np.ones(len(mesh.vertices), np.float32)
    mask = _attribute(mesh, MASK, np.float32, "value")
    if mask is not None:
        values -= np.clip(mask, 0.0, 1.0)
    hidden = _attribute(mesh, HIDE, bool, "value")
    if hidden is not None:
        values[hidden] = 0.0
    return values


def brush_options(brush):
    """The brush settings sculpt_drag_math.unsupported() checks."""
    names = [name for name, *_rest in drag_math.SUPPORTED.values()] + [drag_math.POSE_ORIGIN[0]]
    return {name: getattr(brush, name, "") for name in names}


def falloff(brush):
    preset = brush.curve_distance_falloff_preset
    if preset != 'CUSTOM':
        return drag_math.falloff(preset)
    curve = brush.curve_distance_falloff
    curve.initialize()
    table = [curve.evaluate(curve.curves[0], step / (CURVE_SAMPLES - 1)) for step in range(CURVE_SAMPLES)]
    return drag_math.falloff(preset, table)


def settings(ob, brush, radius, strength):
    mesh = ob.data
    return drag_math.Settings(
        radius, strength, falloff(brush), (mesh.use_mirror_x, mesh.use_mirror_y, mesh.use_mirror_z),
        elastic_type=brush.elastic_deform_type, poisson=brush.elastic_deform_volume_preservation,
        pose_offset=brush.pose_offset, smooth_iterations=brush.pose_smooth_iterations)


def edges(mesh):
    values = np.empty(len(mesh.edges) * 2, np.int32)
    mesh.edges.foreach_get("vertices", values)
    return values.reshape(-1, 2)


def begin(ob, brush, tip, radius, strength, start):
    """The drag of `brush` touching the mesh at `tip` (object space), or None when the tip touches nothing.
    start: the flat positions at the stroke's start."""
    mesh = ob.data
    kind = brush.sculpt_brush_type
    return drag_math.make(kind, start, tip, settings(ob, brush, radius, strength), factor(mesh),
                          edges(mesh) if kind == drag_math.POSE else None)
