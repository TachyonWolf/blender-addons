# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools and their settings of each mode (Object, Edit, Pose, Sculpt, Draw): the ONE definition the desk's Tools page
(wide: two columns) and the Tool options panel (narrow: one column) lay out. Pure Python (no bpy), tested headless.

A mode is a list of Groups (a title and its Rows, in column 0 or 1 of the wide layout); a Row is widgets without a place,
in `columns` equal cells. tool_actions.py fills the ToolsModel and runs the rows' actions (with desk_actions)."""
from dataclasses import dataclass, replace

from . import color_picker, edit_tool_settings as edit_options, grab_order, router
from .annotate_math import PALETTE, THICKNESS_RANGE
from .gpencil_math import RADIUS_RANGE_CM, SWATCH_COLUMNS
from .panel_layout import (CARD, DROPDOWN, HINT, SCROLL_WIDTH, SCULPT_SIZE_RANGE_CM, SLIDER, TOGGLE, WARN, Widget, grid, hint, label,
                           popup, section)
from .panel_widgets import LIST_ROW, LIST_STEP, card, dropdown, dropdown_list, pager, popup_head, scrollbar, slider, toggle

AXES = ('X', 'Y', 'Z')
BOX_SHAPES = (('VOLUME', "3D box"), ('LASER', "Laser box"))
SNAP_MODES = (('OFF', "Off"), ('GRID', "Grid"), ('ALIGN', "Align"))
EDIT_SELECT = (('VERT', "Vert"), ('EDGE', "Edge"), ('FACE', "Face"))
BOX_HINTS = {'VOLUME': "3D box: drag from where you point. Right grip: deeper, left grip: nearer.",
             'LASER': "Laser box: drag from where you point; selects through."}
SNAP_HINTS = {'OFF': "Snap off: things move freely.", 'GRID': "Grid: moves jump to the grid.",
              'ALIGN': "Align: moves turn to match the surface."}
GRAB_MODES = (('FREE', "Free"), ('LASER', "Laser"), ('SELECT_GRAB', "Grab selected"))   #
GRAB_HINTS = {'FREE': "Grip grabs what your hand touches.", 'LASER': "Grip grabs what the laser hits.",
              'SELECT_GRAB': "Laser selects, grip moves the selection."}
TOUCH_RANGE_CM = (0.5, 50.0)
PUSH_SPEED_RANGE = (0.1, 10.0)   # m/s
GRAB_ORDER_ID = "grab_order"     # the Order button, and the pop-up it opens
ORDER_WIDTH = 400                # the order menu's width
ORDER_TITLES = {'FREE': "Free", 'LASER': "Laser", 'SELECT_GRAB': "Grab selected"}
HIDE_ROWS = 5                       # rows of the Hidden objects pop-up
BRUSH_MENU = 'sculpt_brushes'       # the Sculpt brush menu pop-up
LIST_POPUPS = (BRUSH_MENU,)         # pop-ups of the rows that a pick closes (both panels)
KEEP_OPEN = (*color_picker.KEEP_OPEN, "sculpt_menu_scroll")     # presses that leave a pop-up open
MENU_CARD, MENU_TITLE, MENU_GAP, MENU_HEAD = 68, 30, 8, 93
CARD_ROW, SLIDER_ROW, TITLE_ROW = 60, 68, 28
COMPACT_ROW = 52                  # the cards of the options that share a column with the tool's own settings
ROW_GAP, GROUP_GAP, CELL_GAP = 10, 16, 12


@dataclass(frozen=True)
class SculptView:
    """Sculpt mode's tools (sculpt_page.py): brush menu, size, strength, mirror, one notice line."""
    brush: str = ""                 # the active brush's name
    brushes: tuple = ()             # the menu: ((group, ((brush name, why it can't be used or ""), ...)), ...)
    menu_scroll: int = 0            # the menu's first line shown
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
    picker: color_picker.PickerView = color_picker.PickerView()   # the colour pop-up's colour and mode
    hidden_shown: tuple = ()    # names of the hidden objects on this list page (Unhide from list)
    hidden_page: int = 0
    hidden_pages: int = 1
    hidden_total: int = 0
    can_hide: bool = False      # a visible object is selected
    box_shape: str = 'VOLUME'
    object_tool: str = edit_options.GRAB   # Object / Pose mode's active tool (Grab = the trigger picks along the laser; Select = the bubble)
    bubble_start: str = 'ADD'   # Select tool: a stroke adds to the selection, or clears it first (New)
    snap_mode: str = 'OFF'
    mirror: tuple = ()          # ((axis, on, works), ...) for X, Y, Z
    mirror_note: str = ""       # a line under the toggles (why an axis is off)
    grab_mode: str = 'FREE'     # the Grab tool's settings
    grab_order: tuple = grab_order.DEFAULTS['FREE']     # what the active grab mode picks with: ((source, on), ...) in order
    grip_target: str = 'AIMED'
    touch_distance_cm: float = 6.0
    push_speed: float = 1.5     # m/s
    fine_control: bool = False


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
    return Group((_title("box_title", "Box select shape"), _choice("box_", BOX_SHAPES, "box_shape", model.box_shape, 2, height=COMPACT_ROW),
                  _hint("box_hint", BOX_HINTS.get(model.box_shape, ""), 56)), column)


def _object_tool_group(model, column=0):
    """Object / Pose mode's tools (Grab, Select, Annotate) and, under the cards, the lit tool's own settings
   ."""
    tools = tuple(tool for tool in edit_options.OBJECT_TOOLS if model.mode == 'OBJECT' or tool[0] != edit_options.ANNOTATE)   # the trigger draws in Object mode only
    lit = model.object_tool if model.object_tool in dict(tools) else edit_options.GRAB
    rows = [_choice("object_", tools, "object_tool", lit, len(tools), size=26)]
    if lit == edit_options.SELECT:
        rows += [_title("object_start_title", "Select: start"), *(_setting_row(entry, model.bubble_start) for entry in edit_options.SETTINGS[edit_options.SELECT])]
    elif lit == edit_options.ANNOTATE:
        rows += _annotate_rows(model)
    else:
        rows += [*_grab_rows(model), *_mirror_rows(model)]       # Mirror is the Grab tool's option here [user, 2026-11-27]
    return Group(tuple(rows), column)


def _grab_rows(model, enabled=True):
    """The Grab tool's settings (Object, Pose and Edit mode: one system): which mode, what the grip acts on, what it picks
    with (the Order button has a full row), reach and speed, slow mode [user, 2026-11-27]. `enabled` False dims the grip cards."""
    return [_title("grab_title", "Grab mode"), _choice("grab_", GRAB_MODES, "grab_mode", model.grab_mode, 3, size=22, height=COMPACT_ROW),
            _row(48, 2, *_grip_cards(model.grip_target, enabled)),
            _row(CARD_ROW, 1, dropdown(GRAB_ORDER_ID, 0, 0, 0, 0, "Order: " + grab_order.summary(model.grab_order), ("popup", GRAB_ORDER_ID),
                                       model.popup == GRAB_ORDER_ID, size=24)),     # ONE button: the active mode's order [user, 2026-11-27]
            _row(SLIDER_ROW - 8, 2, slider("touch_distance", 0, 0, 0, 0, "Touch distance", model.touch_distance_cm, TOUCH_RANGE_CM, size=22),
                 slider("push_speed", 0, 0, 0, 0, "Push speed", model.push_speed, PUSH_SPEED_RANGE, unit="m/s", step=0.1, factor=1.0, size=22)),
            _row(COMPACT_ROW, 1, toggle("fine_control", 0, 0, 0, 0, "Fine control (B)", "fine_control", model.fine_control, size=24))]


def _snap_group(model, column=0):
    return Group((_title("snap_title", "Snap"), _choice("snap_", SNAP_MODES, "snap_mode", model.snap_mode, 3, height=COMPACT_ROW),
                  _hint("snap_hint", SNAP_HINTS.get(model.snap_mode, ""))), column)


def _mirror_rows(model):
    states = {axis: (on, works) for axis, on, works in model.mirror}
    rows = [_title("mirror_title", "Mirror"),
            _row(COMPACT_ROW, 3, *(card("mirror_" + axis, 0, 0, 0, 0, axis, ("mirror", axis), size=36,
                                        active=states.get(axis, (False, False))[0],
                                        enabled=states.get(axis, (False, False))[1]) for axis in AXES))]
    return [*rows, _hint("note", model.mirror_note)] if model.mirror_note else rows


def _mirror_group(model, column=0):
    return Group(tuple(_mirror_rows(model)), column)


def _annotate_rows(model):
    has_strokes = model.annotate_strokes > 0
    return [
        _row(52, 6, *(Widget("annotate_color_" + name, CARD, 0, 0, 0, 0, action=("annotate_color", name), color=code,
                             active=model.annotate_color == name) for name, _label, code in PALETTE)),
        _row(SLIDER_ROW, 1, slider("annotate_thickness", 0, 0, 0, 0, "Thickness", model.annotate_thickness, THICKNESS_RANGE,
                                   unit="px", step=1.0, factor=1.0, decimals=0)),
        _row(CARD_ROW, 2, *(card(name, 0, 0, 0, 0, text, (name,), size=24, enabled=has_strokes) for name, text in (
            ("annotate_erase", "Erase last stroke"), ("annotate_clear", "Clear all")))),
        _row(CARD_ROW, 1, card("gp_new", 0, 0, 0, 0, "New Grease Pencil", ("gp_new",), size=28))]


def _hide_group(model):
    return Group((
        _title("hide_title", "Hide"),
        _row(CARD_ROW, 2, card("hide_selected", 0, 0, 0, 0, "Hide selected", ("hide_selected",), size=26, enabled=model.can_hide),
             card("unhide_all", 0, 0, 0, 0, "Unhide all", ("unhide_all",), size=26, enabled=model.hidden_total > 0)),
        _row(CARD_ROW, 1, dropdown("hidden_list", 0, 0, 0, 0, "Hidden objects (%d)" % model.hidden_total, ("popup", "hidden"),
                                   model.popup == 'hidden', caret="▸", size=26, enabled=model.hidden_total > 0))), 1)


def _pose_group(_model, column=0):
    return Group((_title("tools_title", "Pose tools (selected bones)"),
                  _row(84, 2, *(card(name, 0, 0, 0, 0, text, (name,), size=28) for name, text in (
                      ("pose_clear", "Clear transforms"), ("pose_mirror", "Mirror pose"))))), column)


def _draw_groups(model):
    has_layers = model.gp_layer_count > 0
    rows = [_title("gp_title", "Grease Pencil material")]
    if model.gp_materials:
        columns = min(SWATCH_COLUMNS, max(4, len(model.gp_materials)))
        rows.append(_row(CARD_ROW, columns, *(Widget("gp_material_%d" % index, CARD, 0, 0, 0, 0,
                                                     action=("popup", "gp_color_edit") if model.gp_material == index else ("gp_material", index),
                                                     color=item[1], active=model.gp_material == index)
                                              for index, item in enumerate(model.gp_materials))))
    rows.append(_row(CARD_ROW, 1, card("gp_color_add", 0, 0, 0, 0, "Add colour", ("popup", "gp_color"), size=26, icon="ADD",
                                       active=model.popup == 'gp_color')))
    rows.append(_row(SLIDER_ROW, 1, slider("gp_radius", 0, 0, 0, 0, "Thickness (radius)", model.gp_radius_cm, RADIUS_RANGE_CM,
                                           step=0.1)))
    layer = Group((_title("gp_layer_title", "Layer"),
                   _row(CARD_ROW, 1, Widget("gp_layer_name", DROPDOWN, 0, 0, 0, 0, label="Layer: " + (model.gp_layer or "-"),
                                            action=("popup", "layer"), active=model.popup == 'layer', caret="▼", size=28,
                                            enabled=has_layers)),
                   _row(CARD_ROW, 1, card("gp_layer_add", 0, 0, 0, 0, "Add layer", ("gp_layer_add",), size=26, icon="ADD")),
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


def _grip_cards(chosen, enabled):
    """What the grip acts on (Aimed / Selection): one setting, shown by the Grab tool and by every Edit tool."""
    return tuple(card("grip_" + value, 0, 0, 0, 0, "Grip: " + label, ("grip_target", value), size=24, detail=tip,
                      active=chosen == value, enabled=enabled) for value, label, tip in router.GRIP_TARGETS)


def _edit_groups(model):
    view = model.edit
    values = dict(view.values)
    tool = [_choice("edit_", edit_options.TOOLS, "edit_tool", view.tool, 3, view.usable, height=COMPACT_ROW)]
    note = [_hint("edit_note", view.note or edit_options.HINTS[view.tool], 56, WARN if view.warn else HINT)]
    entries = edit_options.SETTINGS[view.tool]
    groups = [Group((_choice("edit_select_", EDIT_SELECT, "edit_select", view.select, 3, view.usable, height=COMPACT_ROW),)), Group(tuple(tool))]
    if view.tool != edit_options.GRAB or view.note:      # the Grab tool's own rows say what it does: its hint shows only as a warning
        groups.append(Group(tuple(note), 1))
    if entries:
        groups.append(Group((_title("edit_settings_title", edit_options.TOOL_LABELS[view.tool] + " settings"),
                             *(_setting_row(entry, values.get(entry[0], entry[3])) for entry in entries))))
    elif view.tool == edit_options.GRAB:
        groups += [Group(tuple(_grab_rows(model, view.usable))), _snap_group(model, 1)]      # the whole Grab block, then Grab's Snap [user, 2026-11-27]
    if view.tool != edit_options.GRAB:
        groups.append(Group((_row(48, 2, *_grip_cards(model.grip_target, view.usable)),), 1))
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
                   _row(72, 1, dropdown("sculpt_brush_menu", 0, 0, 0, 0, "Brush: " + (view.brush or "-"), ("popup", BRUSH_MENU),
                                        model.popup == BRUSH_MENU, caret="▸", size=28, enabled=bool(view.brushes))))),
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
        return [_object_tool_group(model), _box_group(model, 1), _snap_group(model, 1), _hide_group(model)]
    if model.mode == 'EDIT_MESH':
        return _edit_groups(model)
    if model.mode == 'POSE':
        return [_object_tool_group(model), _pose_group(model, 1), _box_group(model, 1)]
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
    if model.mode == 'SCULPT' and model.popup == BRUSH_MENU:
        return _brush_overlay(model.sculpt, body, bottom)
    if model.popup == GRAB_ORDER_ID:
        return _order_overlay(model, widgets, body, bottom)
    opener = next((widget for widget in widgets if widget.id == "gp_layer_name"), None)
    if model.popup == 'layer' and opener is not None:
        top = opener.y + opener.h + 8
        rows = [("gp_layer_%d" % index, name, ("gp_layer_set", index), index == model.gp_layer_index)
                for index, name in enumerate(model.gp_layers)][:int(bottom - top - 26) // LIST_STEP]
        return dropdown_list("gp_layer_list", opener.x, top, opener.w, rows, ("popup", ""), body)
    if model.popup in color_picker.POPUPS:
        width = min(body[0] - 40, 720)
        return color_picker.widgets(model.picker, (body[0] - width) / 2, 20, width, body)
    return []


def _brush_lines(view, columns):
    """The brush menu's lines, top to bottom: (height, group title) and (height, ((name, note), ...) up to `columns`)."""
    lines = []
    for group, entries in view.brushes:
        lines.append((MENU_TITLE, group))
        lines += [(MENU_CARD, entries[start:start + columns]) for start in range(0, len(entries), columns)]
    return lines


def _slug(text):
    return "".join(letter if letter.isalnum() else "_" for letter in text)


def _brush_overlay(view, body, bottom, max_width=940):
    """The brush menu: Blender's brushes as cards in groups (4 a line on the desk, 3 on the Tool options panel); one that
    can't sculpt here is dim with its reason. Lines that don't fit between the head and `bottom` scroll."""
    w = min(body[0] - 40, max_width)
    x, y = (body[0] - w) / 2, 20
    columns = 4 if w >= 800 else 3
    lines = _brush_lines(view, columns)
    top, room = y + MENU_HEAD, bottom - y - MENU_HEAD - 27
    steps = [height + MENU_GAP for height, _item in lines]
    last = next((first for first in range(len(lines)) if sum(steps[first:]) - MENU_GAP <= room), max(len(lines) - 1, 0))
    first = min(max(view.menu_scroll, 0), last)
    shown = 0
    while first + shown < len(lines) and sum(steps[first:first + shown + 1]) - MENU_GAP <= room:
        shown += 1
    used = sum(steps[first:first + shown]) - MENU_GAP
    inner = w - 54 - (SCROLL_WIDTH + 12 if last else 0)
    widgets = popup("sculpt_brush_popup", x, y, w, MENU_HEAD + used + 27, ("popup", ""), body)
    widgets += popup_head("sculpt_brush_popup", x, y, w, "Sculpt brush")
    line_y = top
    for height, item in lines[first:first + shown]:
        if isinstance(item, str):
            widgets.append(section("sculpt_group_" + _slug(item), item, x + 27, line_y, inner))
        else:
            widgets += grid("", item, x + 27, line_y, inner, columns, height, lambda _index, entry, cell_x, cell_y, cell_w, cell_h:
                            card("sculpt_brush_" + _slug(entry[0]), cell_x, cell_y, cell_w, cell_h, entry[0],
                                 ("sculpt_brush", entry[0]), size=22, active=entry[0] == view.brush, enabled=not entry[1],
                                 detail=entry[1]), gap_x=CELL_GAP)
        line_y += height + MENU_GAP
    return widgets + scrollbar("sculpt_brush_scroll", x + w - 27 - SCROLL_WIDTH, top, used, first, last, "sculpt_menu_scroll",
                               visible=shown, area=(x + 27, top, inner, used))


def _hidden_overlay(model, body):
    w = 576
    x, y = (body[0] - w) / 2, 180
    widgets = popup("hidden_popup", x, y, w, 522, ("popup", ""), body)
    widgets += popup_head("hidden_popup", x, y, w, "Hidden objects (%d)" % model.hidden_total)
    for index, name in enumerate(model.hidden_shown[:HIDE_ROWS]):
        widgets.append(card("hide_row_%d" % index, x + 27, y + 93 + index * 70, w - 54 - SCROLL_WIDTH - 12, 56, name,
                            ("unhide_one", name), size=28, style='left'))
    widgets += scrollbar("hide_scroll", x + w - 27 - SCROLL_WIDTH, y + 93, HIDE_ROWS * 70 - 14, model.hidden_page,
                         model.hidden_pages - 1, "hide_page", area=(x + 27, y + 93, w - 54 - SCROLL_WIDTH - 12, HIDE_ROWS * 70 - 14))
    return widgets + pager("hide", x + 27, y + 443, w - 54, model.hidden_page, model.hidden_pages, "hide_page")


def _order_overlay(model, widgets, body, bottom):
    """The small menu of the active grab mode's order, under its button: a row per source (on / off, its name, up, down). The
    first source that finds something under the hand is the one that picks: it glows, the trigger selects it, the grip grabs it."""
    opener = next((widget for widget in widgets if widget.id == GRAB_ORDER_ID), None)
    if opener is None:
        return []
    rows = len(model.grab_order)
    height = 26 + 44 + rows * LIST_STEP - 8
    width = ORDER_WIDTH
    x, y = min(opener.x, body[0] - width - 20), min(opener.y + opener.h + 8, bottom - height)     # left edges aligned
    result = popup("order_menu", x, y, width, height, ("popup", ""), body, radius=12)
    result.append(label("order_title", ORDER_TITLES[model.grab_mode] + ": first match wins", x + 13, y + 10, width - 26, size=22))
    button = 60
    for index, (source, on) in enumerate(model.grab_order):
        row_y = y + 13 + 44 + index * LIST_STEP
        result += [Widget("order_on_" + source, TOGGLE, x + 13, row_y, width - 26 - 2 * (button + 8), LIST_ROW,
                          label=grab_order.NAMES[source], action=("grab_order", "toggle", index), active=on, size=26),
                   card("order_up_" + source, x + width - 13 - 2 * button - 8, row_y, button, LIST_ROW, "",
                        ("grab_order", "move", index, -1), icon="TRIA_UP", enabled=index > 0),
                   card("order_down_" + source, x + width - 13 - button, row_y, button, LIST_ROW, "",
                        ("grab_order", "move", index, 1), icon="TRIA_DOWN", enabled=index < rows - 1)]
    return result
