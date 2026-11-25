# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool rows, bpy side (tool_rows.py is the definition): what they show now, for the desk's Tools page and the Tool
options panel alike, and the actions that are not the desk's older ones. Mirror: Pose mode = the armature's own X-Axis
Mirror (`Pose.use_mirror_x`, Blender keeps it in the .blend like the desktop checkbox)."""
import time

from . import annotate, edit_page, edit_tool_settings, gpencil, hide, router, sculpt_page, settings
from .runtime import RUNTIME
from .tool_rows import AXES, EditView, SculptView
from .tools import push_undo

POSE_NOTE = "Pose mirror works on X (Blender's own option)"
LATER_NOTE = "Mirror in this mode: coming later"
REBUILD_AFTER = 5.0         # s: the kept fields are read again at least this often
CHOICES = {"box_shape", "snap_mode"} | {name for entries in edit_tool_settings.SETTINGS.values() for name, *_rest in entries}
_kept = {"key": None, "fields": None, "time": 0.0}


def _pose(context):
    """The pose whose mirror the toggles show, or None outside Pose mode."""
    ob = context.active_object
    if router.mode_kind(context.mode) == router.POSE and ob is not None and ob.type == 'ARMATURE':
        return ob.pose
    return None


def key(context):
    """Changes when something the rows show may have changed (cheap reads)."""
    ob = context.active_object
    pose = _pose(context)
    return (settings.revision, RUNTIME.scene_updates, RUNTIME.generation, context.mode, ob.name_full if ob else None,
            annotate.STATE.on, pose.use_mirror_x if pose is not None else None,
            sculpt_page.key(context) if context.mode == router.SCULPT else None,
            edit_page.key(context) if context.mode == router.EDIT else None)


def forget():
    _kept["key"] = None


def fields(context):
    """The ToolsModel fields (tool_rows.py) of now, except `popup`. During a session kept until key() changes: two panels
    ask, and some reads walk the scene or the mesh."""
    if not RUNTIME.active:
        return _fields(context)
    now_key, now = key(context), time.perf_counter()
    if now_key != _kept["key"] or now - _kept["time"] > REBUILD_AFTER:
        _kept.update(key=now_key, fields=_fields(context), time=now)
    return _kept["fields"]


def _fields(context):
    mode = router.mode_kind(context.mode)
    hidden = hide.view(context) if mode == router.OBJECT else ((), 0, 1, 0, False)
    gp = gpencil.view(context) if mode == router.GP_DRAW else ((), 0, "", 0, 0, 0, ())
    pose = _pose(context)
    mirror = ((('X', pose.use_mirror_x, True), ('Y', False, False), ('Z', False, False)) if pose is not None
              else tuple((axis, False, False) for axis in AXES))
    return dict(
        mode=mode, sculpt=sculpt_page.view(context) if mode == router.SCULPT else SculptView(),
        edit=edit_page.view(context) if mode == router.EDIT else EditView(),
        annotate_on=annotate.STATE.on, annotate_color=settings.get("annotate_color"),
        annotate_thickness=int(round(settings.get("annotate_thickness"))), annotate_strokes=annotate.stroke_count(context.scene),
        hidden_shown=hidden[0], hidden_page=hidden[1], hidden_pages=hidden[2], hidden_total=hidden[3], can_hide=hidden[4],
        gp_materials=gp[0], gp_material=gp[1], gp_layer=gp[2], gp_layer_index=gp[3], gp_layer_count=gp[4], gp_strokes=gp[5],
        gp_layers=gp[6], gp_radius_cm=round(settings.get("gp_radius") * 100, 1), box_shape=settings.get("box_shape"),
        select_bubble=settings.get("select_bubble"),
        snap_mode=settings.get("snap_mode"), mirror=mirror, mirror_note=POSE_NOTE if pose is not None else LATER_NOTE)


def perform(context, widget, pixel_x):
    """A tool row's press. None = not one of these actions."""
    kind, *arguments = widget.action
    if kind in CHOICES:                                  # remembered settings: the same ones the tools use
        settings.put(kind, arguments[0])
        return True
    if kind == "edit_tool":                              # pressing the lit tool again goes back to Grab
        lit = settings.get("edit_tool") == arguments[0]
        settings.put("edit_tool", edit_tool_settings.GRAB if lit else arguments[0])
        return True
    if kind == "edit_instant":
        return edit_page.run_tool(context, arguments[0])
    if kind == "edit_select":
        return edit_page.set_select(context, arguments[0])
    if kind == "mirror":
        return _toggle_mirror(context, arguments[0])
    return sculpt_page.perform(context, widget, pixel_x)


def _toggle_mirror(context, axis):
    pose = _pose(context)
    if pose is None or axis != 'X':
        return False
    pose.use_mirror_x = not pose.use_mirror_x
    push_undo("VR X-Axis Mirror " + ("on" if pose.use_mirror_x else "off"))
    return True
