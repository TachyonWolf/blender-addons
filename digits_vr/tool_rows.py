# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools and their settings of each mode (Object, Edit, Pose, Sculpt, Draw): the ONE definition the desk's Tools page
(wide: two columns) and the Tool options panel (narrow: one column) lay out. Pure Python (no bpy), tested headless.

A mode is a list of Groups (a title and its Rows, in column 0 or 1 of the wide layout); a Row is widgets without a place,
in `columns` equal cells. tool_actions.py fills the ToolsModel and runs the rows' actions (with desk_actions)."""
from dataclasses import dataclass, replace

from . import edit_tool_settings as edit_options
from .annotate_math import PALETTE, THICKNESS_RANGE
from .gpencil_math import RADIUS_RANGE_CM
from .panel_layout import CARD, DROPDOWN, HINT, SCULPT_SIZE_RANGE_CM, SLIDER, TOGGLE, WARN, Widget, grid, hint, popup, section
from .panel_widgets import LIST_STEP, card, dropdown, dropdown_list, pager, popup_head, slider, toggle

AXES = ('X', 'Y', 'Z')
BOX_SHAPES = (('VOLUME', "3D box"), ('LASER', "Laser box"))
SNAP_MODES = (('OFF', "Off"), ('GRID', "Grid"), ('ALIGN', "Align"))
EDIT_SELECT = (('VERT', "Vert"), ('EDGE', "Edge"), ('FACE', "Face"))
BOX_HINTS = {'VOLUME': "3D box: drag from where you point. Right grip: deeper, left grip: nearer.",
             'LASER': "Laser box: drag from where you point; selects through."}
SNAP_HINTS = {'OFF': "Snap off: things move freely.", 'GRID': "Grid: moves jump to the grid.",
              'ALIGN': "Align: moves turn to match the surface you point at."}
HIDE_ROWS = 5                       # rows of the Hidden objects pop-up
CARD_ROW, SLIDER_ROW, TITLE_ROW = 60, 68, 28
ROW_GAP, GROUP_GAP, CELL_GAP = 10, 16, 12


@dataclass(frozen=True)
class SculptView:
    """Sculpt mode's tools (sculpt_page.py): brush list, size, strength, mirror, one notice line."""
    brush: str = ""                 # the active brush type ('DRAW', ...)
    brushes: tuple = ()             # ((type, label), ...)
    size_cm: float = 5.0
    strength: float = 0.5
    mirror: tuple = (False, False, False)
    note: str = ""                  # why a stroke can't run / when it shows ("" = nothing to say)
    warn: bool = False              # the note is a warning (it blocks the stroke)
    frame: bool = False             # offer the Frame object button (no desktop 3D View shows the object)


@dataclass(frozen=True)
class EditView:
    """Edit mode's tools (edit_page.py)."""
    select: str = 'VERT'            # the select mode: 'VERT' / 'EDGE' / 'FACE' (edit_math.select_kind)
    hidden: bool = False            # something is hidden: Reveal works
    note: str = ""                  # why a tool can't run ("" = nothing to say)
    warn: bool = False
    usable: bool = False            # the mesh can be edited in VR (else every button dims)
    tool: str = edit_options.GRAB   # the active tool
    values: tuple = ()              # ((setting name, value), ...) of the active tool


@dataclass(frozen=True)
class ToolsModel:
    """What the tool rows show (plain values: equal models need no redraw)."""
    mode: str = 'OBJECT'
    popup: str = ""             # the open pop-up or dropdown list
    sculpt: SculptView = SculptView()
    edit: EditView = EditView()
    annotate_on: bool = False
    annotate_color: str = 'red'
    annotate_thickness: int = 3
    annotate_strokes: int = 0   # strokes our annotation layers hold (Erase last / Clear all need one)
    gp_materials: tuple = ()    # Draw mode: ((name, hex colour), ...) of the Grease Pencil object's materials
    gp_material: int = 0        # the active material's index
    gp_layer: str = ""          # the active layer's name
    gp_layer_index: int = 0
    gp_layer_count: int = 0
    gp_layers: tuple = ()       # every layer's name (the Layer dropdown)
    gp_strokes: int = 0         # strokes of the active layer at this frame
    gp_radius_cm: float = 1.0
    hidden_shown: tuple = ()    # names of the hidden objects on this list page (Unhide from list)
    hidden_page: int = 0
    hidden_pages: int = 1
    hidden_total: int = 0
    can_hide: bool = False      # a visible object is selected
    box_shape: str = 'VOLUME'
    select_bubble: bool = False   # Object / Pose mode: the trigger paints the selection with the bubble
    snap_mode: str = 'OFF'
    mirror: tuple = ()          # ((axis, on, works), ...) for X, Y, Z
    mirror_note: str = ""       # a line under the toggles (why an axis is off)


@dataclass(frozen=True)
class Row:
    widgets: tuple
    height: float
    columns: int = 1


@dataclass(frozen=True)
class Group:
    rows: tuple
    column: int = 0             # which column of the wide layout


def _row(height, columns, *widgets):
    return Row(tuple(widgets), height, columns)


def _title(identifier, text):
    return _row(TITLE_ROW, 1, section(identifier, text, 0, 0))


def _hint(identifier, text, height=28, style=HINT):
    return _row(height, 1, hint(identifier, text, 0, 0, style=style))


def _choice(prefix, items, name, chosen, columns, enabled=True, height=CARD_ROW, size=28):
    """Cards to pick one value: the action is (name, value)."""
    return _row(height, columns, *(card(prefix + value, 0, 0, 0, 0, label, (name, value), size=size,
                                        active=chosen == value, enabled=enabled) for value, label in items))


# ---- groups -----------------------------------------------------------------------------------------------------------

def _box_group(model, column=0):
    return Group((_title("box_title", "Box select shape"), _choice("box_", BOX_SHAPES, "box_shape", model.box_shape, 2),
                  _hint("box_hint", BOX_HINTS.get(model.box_shape, ""), 56)), column)


def _bubble_group(model, column=0):
    return Group((_row(CARD_ROW, 1, toggle("select_bubble", 0, 0, 0, 0, "Select bubble (trigger)", "select_bubble",
                                           model.select_bubble)),), column)


def _snap_group(model, column=0):
    return Group((_title("snap_title", "Snap"), _choice("snap_", SNAP_MODES, "snap_mode", model.snap_mode, 3),
                  _hint("snap_hint", SNAP_HINTS.get(model.snap_mode, ""))), column)


def _mirror_group(model, column=0):
    states = {axis: (on, works) for axis, on, works in model.mirror}
    rows = [_title("mirror_title", "Mirror"),
            _row(CARD_ROW, 3, *(card("mirror_" + axis, 0, 0, 0, 0, axis, ("mirror", axis), size=36,
                                     active=states.get(axis, (False, False))[0],
                                     enabled=states.get(axis, (False, False))[1]) for axis in AXES))]
    return Group((*rows, _hint("note", model.mirror_note)) if model.mirror_note else tuple(rows), column)


def _annotate_group(model):
    has_strokes = model.annotate_strokes > 0
    return Group((
        _title("tools_title", "Annotate"),
        _row(CARD_ROW, 1, Widget("annotate_on", TOGGLE, 0, 0, 0, 0, label="Draw with the trigger", action=("annotate_toggle",),
                                 active=model.annotate_on, size=28)),
        _row(52, 6, *(Widget("annotate_color_" + name, CARD, 0, 0, 0, 0, action=("annotate_color", name), color=code,
                             active=model.annotate_color == name) for name, _label, code in PALETTE)),
        _row(SLIDER_ROW, 1, slider("annotate_thickness", 0, 0, 0, 0, "Thickness", model.annotate_thickness, THICKNESS_RANGE,
                                   unit="px", step=1.0, factor=1.0, decimals=0)),
        _row(CARD_ROW, 2, *(card(name, 0, 0, 0, 0, text, (name,), size=24, enabled=has_strokes) for name, text in (
            ("annotate_erase", "Erase last stroke"), ("annotate_clear", "Clear all")))),
        _row(CARD_ROW, 1, card("gp_new", 0, 0, 0, 0, "New Grease Pencil", ("gp_new",), size=28))), 1)


def _hide_group(model):
    return Group((
        _title("hide_title", "Hide"),
        _row(CARD_ROW, 2, card("hide_selected", 0, 0, 0, 0, "Hide selected", ("hide_selected",), size=26, enabled=model.can_hide),
             card("unhide_all", 0, 0, 0, 0, "Unhide all", ("unhide_all",), size=26, enabled=model.hidden_total > 0)),
        _row(CARD_ROW, 1, dropdown("hidden_list", 0, 0, 0, 0, "Hidden objects (%d)" % model.hidden_total, ("popup", "hidden"),
                                   model.popup == 'hidden', caret="▸", size=26, enabled=model.hidden_total > 0))), 1)


def _pose_group(_model):
    return Group((_title("tools_title", "Pose tools (selected bones)"),
                  _row(84, 2, *(card(name, 0, 0, 0, 0, text, (name,), size=28) for name, text in (
                      ("pose_clear", "Clear transforms"), ("pose_mirror", "Mirror pose"))))))


def _draw_groups(model):
    has_layers = model.gp_layer_count > 0
    rows = [_title("gp_title", "Grease Pencil material")]
    if model.gp_materials:
        columns = max(4, len(model.gp_materials))
        rows.append(_row(CARD_ROW, columns, *(Widget("gp_material_%d" % index, CARD, 0, 0, 0, 0, action=("gp_material", index),
                                                     color=item[1], active=model.gp_material == index)
                                              for index, item in enumerate(model.gp_materials))))
    rows.append(_row(SLIDER_ROW, 1, slider("gp_radius", 0, 0, 0, 0, "Thickness (radius)", model.gp_radius_cm, RADIUS_RANGE_CM,
                                           step=0.1)))
    layer = Group((_title("gp_layer_title", "Layer"),
                   _row(CARD_ROW, 1, Widget("gp_layer_name", DROPDOWN, 0, 0, 0, 0, label="Layer: " + (model.gp_layer or "-"),
                                            action=("popup", "layer"), active=model.popup == 'layer', caret="▼", size=28,
                                            enabled=has_layers)),
                   _row(CARD_ROW, 2, *(card(name, 0, 0, 0, 0, text, (name,), size=24,
                                            enabled=model.gp_strokes > 0 and has_layers) for name, text in (
                       ("gp_erase", "Erase last stroke"), ("gp_clear", "Clear this frame"))))), 1)
    return [Group(tuple(rows)), layer]


def _setting_row(entry, value):
    """One setting of an Edit tool (edit_tool_settings.SETTINGS)."""
    name, kind, label, _default, detail = entry
    if kind == edit_options.SLIDER:
        low, high, step, decimals = detail
        return _row(SLIDER_ROW, 1, slider(name, 0, 0, 0, 0, label, value, (low, high), unit="", step=step, factor=1.0,
                                          decimals=decimals))
    if kind == edit_options.CHOICE:
        return _choice(name + "_", detail, name, value, len(detail))
    return _row(CARD_ROW, 1, toggle(name, 0, 0, 0, 0, label, name, value))


def _edit_groups(model):
    view = model.edit
    values = dict(view.values)
    tool = [_title("edit_tools_title", "Active tool"),
            _choice("edit_", edit_options.TOOLS, "edit_tool", view.tool, 3, view.usable)]
    note = [_hint("edit_note", view.note or edit_options.HINTS[view.tool], 56, WARN if view.warn else HINT)]
    entries = edit_options.SETTINGS[view.tool]
    groups = [Group((_title("edit_select_title", "Select mode"),
                     _choice("edit_select_", EDIT_SELECT, "edit_select", view.select, 3, view.usable))), Group(tuple(tool)), Group(tuple(note), 1)]
    if entries:
        groups.append(Group((_title("edit_settings_title", edit_options.TOOL_LABELS[view.tool] + " settings"),
                             *(_setting_row(entry, values.get(entry[0], entry[3])) for entry in entries))))
    elif view.tool == edit_options.GRAB:
        groups.append(_snap_group(model))          # Grab's setting
    instant = _row(CARD_ROW, 4, *(card("edit_" + name, 0, 0, 0, 0, text, ("edit_instant", name), size=24, enabled=view.usable
                                       and (name != "reveal" or view.hidden)) for name, text in edit_options.INSTANT))
    return groups + [Group((_title("edit_instant_title", "Do once"), instant), 1), _box_group(model, 1), _mirror_group(model, 1)]


def _sculpt_groups(model):
    view = model.sculpt
    low, high = SCULPT_SIZE_RANGE_CM
    note = [_hint("sculpt_note", view.note or "Trigger = stroke. A held = smooth. Grip held = invert.", 56,
                  WARN if view.warn else HINT)]
    if view.frame:
        note.append(_row(CARD_ROW, 1, card("sculpt_frame", 0, 0, 0, 0, "Frame object", ("sculpt_frame",), size=26)))
    return [Group((_title("sculpt_title", "Brush"),
                   _choice("sculpt_brush_", view.brushes, "sculpt_brush", view.brush, 3, height=72))),
            Group((_row(76, 1, Widget("sculpt_size", SLIDER, 0, 0, 0, 0, label="Size", action=("sculpt_slider", "size"),
                                      value=view.size_cm, minimum=low, maximum=high, unit="cm", step=0.5, log=True, size=28)),
                   _row(76, 1, Widget("sculpt_strength", SLIDER, 0, 0, 0, 0, label="Strength", value=view.strength,
                                      action=("sculpt_slider", "strength"), minimum=0.0, maximum=1.0, unit="", step=0.05,
                                      decimals=2, size=28)))),
            Group((_title("sculpt_mirror_title", "Mirror"),
                   _row(72, 3, *(card("sculpt_mirror_" + axis, 0, 0, 0, 0, axis, ("sculpt_mirror", axis), size=36,
                                      active=view.mirror[index]) for index, axis in enumerate(AXES)))), 1),
            Group(tuple(note), 1)]


def groups(model):
    """The Groups of the model's mode, top to bottom."""
    if model.mode == 'OBJECT':
        return [_box_group(model), _snap_group(model), _mirror_group(model), _bubble_group(model), _annotate_group(model),
                _hide_group(model)]
    if model.mode == 'EDIT_MESH':
        return _edit_groups(model)
    if model.mode == 'POSE':
        return [_pose_group(model), _mirror_group(model), _box_group(model, 1), _bubble_group(model, 1)]
    if model.mode == 'SCULPT':
        return _sculpt_groups(model)
    if model.mode == 'PAINT_GREASE_PENCIL':
        return _draw_groups(model)
    return [Group((_hint("tools_none", "No tools in this mode.", 40),))]


# ---- laying out -------------------------------------------------------------------------------------------------------

def _stack(chosen, x, y, width):
    """One column of Groups: widgets with their places."""
    widgets = []
    for group in chosen:
        for row in group.rows:
            widgets += grid("", row.widgets, x, y, width, row.columns, row.height, lambda _index, item, cell_x, cell_y, w, h:
                            replace(item, x=cell_x, y=cell_y, w=w, h=h), gap_x=CELL_GAP, gap_y=ROW_GAP)
            lines = (len(row.widgets) + row.columns - 1) // row.columns
            y += lines * (row.height + ROW_GAP)
        y += GROUP_GAP - ROW_GAP
    return widgets


def narrow(model, x, y, width):
    return _stack(groups(model), x, y, width)


def wide(model, x, y, width, gap=32):
    column_width = (width - gap) / 2
    return [widget for column in (0, 1) for widget in _stack([group for group in groups(model) if group.column == column],
                                                             x + column * (column_width + gap), y, column_width)]


def overlay(model, widgets, body, bottom):
    """The open pop-up of the rows (`widgets` = the laid-out page) on a panel `body` (width, height); [] when none is open."""
    if model.mode == 'OBJECT' and model.popup == 'hidden':
        return _hidden_overlay(model, body)
    opener = next((widget for widget in widgets if widget.id == "gp_layer_name"), None)
    if model.popup == 'layer' and opener is not None:
        top = opener.y + opener.h + 8
        rows = [("gp_layer_%d" % index, name, ("gp_layer_set", index), index == model.gp_layer_index)
                for index, name in enumerate(model.gp_layers)][:int(bottom - top - 26) // LIST_STEP]
        return dropdown_list("gp_layer_list", opener.x, top, opener.w, rows, ("popup", ""), body)
    return []


def _hidden_overlay(model, body):
    w = 576
    x, y = (body[0] - w) / 2, 180
    widgets = popup("hidden_popup", x, y, w, 522, ("popup", ""), body)
    widgets += popup_head("hidden_popup", x, y, w, "Hidden objects (%d)" % model.hidden_total)
    for index, name in enumerate(model.hidden_shown[:HIDE_ROWS]):
        widgets.append(card("hide_row_%d" % index, x + 27, y + 93 + index * 70, w - 54, 56, name, ("unhide_one", name), size=28,
                            style='left'))
    return widgets + pager("hide", x + 27, y + 443, w - 54, model.hidden_page, model.hidden_pages, "hide_page")
