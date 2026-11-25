# SPDX-License-Identifier: GPL-3.0-or-later
"""The Sculpt tool rows (tool_rows.py), bpy side: a short brush list (only the brush types a VR stroke can use: sculpt_math.PROVEN),
the brush size in cm (the VR session's own size, as the size gesture sets it), strength, X / Y / Z mirror (the mesh's own
symmetry), and one notice line: why a stroke cannot run, or that it shows only when you let go. """
import bpy

from . import sculpt_brush, sculpt_math as math_, sculpt_mesh
from .context_helper import run_in_view3d, view3d_override_showing
from .tool_rows import SculptView
from .panel_layout import slider_value
from .tools import push_undo

BRUSH_LABELS = {'DRAW': "Draw", 'CLAY': "Clay", 'INFLATE': "Inflate", 'SMOOTH': "Smooth", 'MASK': "Mask"}
BRUSHES = tuple((kind, label) for kind, label in BRUSH_LABELS.items() if kind in math_.PROVEN)
NO_VIEW = "Show the object in a 3D View on the desktop to sculpt"
SIZE_FALLBACK = 0.05            # m, shown when the brush has no VR size yet and no view tells it


def _strength_owner(brush):
    return bpy.context.tool_settings.sculpt.unified_paint_settings if brush.use_unified_strength else brush


def key(context):
    """What the page shows, for the desk's change key (cheap reads)."""
    ob, brush = context.active_object, sculpt_brush.active()
    if ob is None or ob.type != 'MESH' or brush is None:
        return (None,)
    mesh = ob.data
    return (ob.name_full, brush.name, sculpt_brush.Size.diameter, round(_strength_owner(brush).strength, 3),
            mesh.use_mirror_x, mesh.use_mirror_y, mesh.use_mirror_z, ob.use_dynamic_topology_sculpting,
            mesh.shape_keys is not None)


def view(context):
    ob, brush = context.active_object, sculpt_brush.active()
    if ob is None or ob.type != 'MESH' or brush is None:
        return SculptView(note="Select a mesh to sculpt")
    kind, reason = math_.kind_for(sculpt_mesh.facts(context, ob, brush))
    note, frame = reason, False
    if view3d_override_showing(context, ob) is None:
        note, frame = NO_VIEW, True
    size = sculpt_brush.Size.diameter
    if size is None:
        override = view3d_override_showing(context, ob)
        try:
            size = sculpt_brush.diameter(ob, override) if override else SIZE_FALLBACK
        except (RuntimeError, ReferenceError, AttributeError, TypeError, ZeroDivisionError):
            size = SIZE_FALLBACK
    mesh = ob.data
    return SculptView(brush=brush.sculpt_brush_type, brushes=BRUSHES, size_cm=round(size * 100, 1),
                      strength=round(_strength_owner(brush).strength, 2),
                      mirror=(mesh.use_mirror_x, mesh.use_mirror_y, mesh.use_mirror_z), note=note,
                      warn=kind == math_.BLOCKED or frame, frame=frame)


def pick_brush(context, brush_type):
    sculpt = context.tool_settings.sculpt
    brush = next((item for item in bpy.data.brushes
                  if item.use_paint_sculpt and item.sculpt_brush_type == brush_type), None)
    if sculpt is None or brush is None:
        return False
    sculpt.brush = brush
    return True


def set_size(value_cm):
    sculpt_brush.Size.diameter = max(math_.SIZE_RANGE[0], min(math_.SIZE_RANGE[1], value_cm / 100.0))
    return True


def set_strength(context, value):
    brush = sculpt_brush.active()
    if brush is None:
        return False
    _strength_owner(brush).strength = max(0.0, min(1.0, value))
    return True


def toggle_mirror(context, axis):
    ob = context.active_object
    if ob is None or ob.type != 'MESH':
        return False
    name = "use_mirror_" + axis.lower()
    setattr(ob.data, name, not getattr(ob.data, name))
    push_undo("VR Sculpt mirror " + axis)
    return True


def perform(context, widget, pixel_x):
    """A sculpt widget of the desk's Tools page or the Tool options panel. None = not a sculpt widget."""
    kind, arguments = widget.action[0], widget.action[1:]
    if kind == "sculpt_brush":
        return pick_brush(context, arguments[0])
    if kind == "sculpt_slider":
        value = slider_value(widget, pixel_x)
        return set_size(value) if arguments[0] == "size" else set_strength(context, value)
    if kind == "sculpt_mirror":
        return toggle_mirror(context, arguments[0])
    if kind == "sculpt_frame":
        return frame_object(context)
    return None


def frame_object(context):
    ob = context.active_object
    if ob is None:
        return False
    return run_in_view3d(context, lambda: bpy.ops.view3d.view_selected())
