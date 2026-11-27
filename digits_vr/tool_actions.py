# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool rows, bpy side (tool_rows.py is the definition): what they show now, for the desk's Tools page and the Tool
options panel alike, and the actions that are not the desk's older ones. Mirror: Pose mode = the armature's own X-Axis
Mirror (`Pose.use_mirror_x`, Blender keeps it in the .blend like the desktop checkbox)."""
import time

from . import annotate, color_math, color_picker, edit_page, edit_tool_settings, gpencil, hands, hide, router, sculpt_page, settings
from .panel_layout import slider_value
from .runtime import RUNTIME
from .tool_rows import AXES, BRUSH_MENU, EditView, SculptView
from .tools import push_undo

POSE_NOTE = "Pose mirror works on X (Blender's own option)"
LATER_NOTE = "Mirror in this mode: coming later"
REBUILD_AFTER = 5.0         # s: the kept fields are read again at least this often
CHOICES = {"box_shape", "snap_mode", "grip_target"} | {name for entries in edit_tool_settings.SETTINGS.values() for name, *_rest in entries}
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
            color_picker.PICKER.revision, pose.use_mirror_x if pose is not None else None,
            sculpt_page.key(context) if context.mode == router.SCULPT else None,
            edit_page.key(context) if context.mode == router.EDIT else None)


def popup_opened(context, name):
    """A pop-up of the rows opened (both panels call this): the colour pop-up starts on its colour."""
    if name == 'gp_color':
        color_picker.PICKER.open(color_picker.NEW, color_picker.PICKER.colour)
    elif name == 'gp_color_edit':
        code, alpha = gpencil.material_color(context)
        color_picker.PICKER.open(color_picker.EDIT, color_math.from_code(code, alpha))
    elif name == BRUSH_MENU:
        sculpt_page.Menu.scroll = 0


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
        annotate_color=settings.get("annotate_color"),
        annotate_thickness=int(round(settings.get("annotate_thickness"))), annotate_strokes=annotate.stroke_count(context.scene),
        hidden_shown=hidden[0], hidden_page=hidden[1], hidden_pages=hidden[2], hidden_total=hidden[3], can_hide=hidden[4],
        gp_materials=gp[0], gp_material=gp[1], gp_layer=gp[2], gp_layer_index=gp[3], gp_layer_count=gp[4], gp_strokes=gp[5],
        gp_layers=gp[6], gp_radius_cm=round(settings.get("gp_radius") * 100, 1), box_shape=settings.get("box_shape"),
        object_tool=settings.get("object_tool"), bubble_start=settings.get("select_bubble_start"), picker=color_picker.view(),
        snap_mode=settings.get("snap_mode"), mirror=mirror, grab_mode=settings.get("grab_mode"), grab_order=hands.current_order(),
        grip_target=settings.get("grip_target"), touch_distance_cm=round(settings.get("touch_distance") * 100, 1),
        push_speed=round(settings.get("push_speed"), 2), fine_control=settings.get("fine_control"), mirror_note=POSE_NOTE if pose is not None else LATER_NOTE)


def perform(context, widget, pixel_x):
    """A tool row's press. None = not one of these actions."""
    kind, *arguments = widget.action
    if kind in color_picker.KEEP_OPEN:
        return color_picker.perform(widget, pixel_x, slider_value)
    if kind == "color_apply":
        return _apply_color(context)
    if kind in CHOICES:                                  # remembered settings: the same ones the tools use
        settings.put(kind, arguments[0])
        return True
    if kind in ("edit_tool", "object_tool"):             # pressing the lit tool again goes back to Grab
        lit = settings.get(kind) == arguments[0]
        settings.put(kind, edit_tool_settings.GRAB if lit else arguments[0])
        return True
    if kind == "edit_instant":
        return edit_page.run_tool(context, arguments[0])
    if kind == "edit_select":
        return edit_page.set_select(context, arguments[0])
    if kind == "mirror":
        return _toggle_mirror(context, arguments[0])
    return sculpt_page.perform(context, widget, pixel_x)


def _apply_color(context):
    colour = color_picker.PICKER.colour
    if color_picker.PICKER.purpose == color_picker.EDIT:
        return gpencil.set_material_color(context, colour.code, colour.a)
    return gpencil.add_material(context, colour.code, colour.a) >= 0


def _toggle_mirror(context, axis):
    pose = _pose(context)
    if pose is None or axis != 'X':
        return False
    pose.use_mirror_x = not pose.use_mirror_x
    push_undo("VR X-Axis Mirror " + ("on" if pose.use_mirror_x else "off"))
    return True
