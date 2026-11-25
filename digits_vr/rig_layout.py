# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's Selected tab: widgets of the rig panel (Digit's Assorted Tools' Character Rig box) from a RigView.
Pure Python (no bpy), tested headless. rig_tab.py reads the rig into a RigView with the shared rig_page functions;
this module only places widgets.

Top to bottom (under the desk's Rig / Modifiers switch): Show Bones group cards (A held = add / remove, like Shift),
the Part dropdown + Reset Part / Selected / All, the status line, then the page's items (scrolled with Up / Down).
The open Part dropdown is a list over the page (picker_overlay: sections, pages of part cards)."""
from dataclasses import dataclass

from .desk_layout import (BODY, CARD, DROPDOWN, LABEL, LIST_BOTTOM, SLIDER, TOGGLE, Widget, _card, _label, _pager,
                          _popup, _row, grid, hint, section)

# item kinds of a RigView (plain tuples, so equal views need no redraw):
#   ("hint", text) / ("heading", text)
#   ("ikfk", is_fk, live)
#   ("follows", (parent names), current index, enabled, changed)
#   ("row", row id, label, cells, changed, enabled); cells = ((side, kind, value, low, high), ...), kind one of
#       CELL_SLIDER / CELL_TOGGLE / CELL_NUMBER / CELL_TEXT (a vector: shown, not edited)
#   ("button", action name, label, enabled)
CELL_SLIDER, CELL_TOGGLE, CELL_NUMBER, CELL_TEXT = "slider", "toggle", "number", "text"
LEFT_X, FULL_WIDTH = 24, 976
CONTENT_WIDTH = 900                 # items; the Up / Down column sits at its right
BACK_WIDTH = 60                     # the ↺ of a changed row (its space is kept on every row)
SCROLL_STEP = 3                     # items per Up / Down press
PICKER_COLUMNS = 4
BOTTOM = 748                        # the screen's usable bottom (pixels)
ITEM_HEIGHTS = {"hint": 40, "heading": 40, "ikfk": 68, "follows": 68, "row": 80, "button": 68}   # with the 12 px gap


@dataclass(frozen=True)
class RigView:
    """What the Selected tab shows (plain values)."""
    message: str = ""           # set = no rig panel: this line only (nothing selected, Assorted Tools missing)
    title: str = ""
    groups: tuple = ()          # ((group name, showing), ...)
    page: str = ""              # the page showing ("" = none)
    page_label: str = ""        # with the changed dot
    reset_part: bool = False    # Reset Part shows (not on a rig with only Other)
    pose_mode: bool = False     # Reset Selected / Reset All need Pose Mode
    status: str = ""
    items: tuple = ()
    scroll: int = 0             # first item on show
    picker_open: bool = False
    picker: tuple = ()          # ((section, ((part name, changed), ...)), ...) while the picker is open
    picker_page: int = 0


def _cell_widget(identifier, cell, row_id, index, label, x, y, w, enabled):
    side, kind, value, low, high = cell
    text = f"{label}  {side}" if side else label
    action = ("rig_prop", row_id, index)
    if kind == CELL_TOGGLE:
        return Widget(identifier, TOGGLE, x, y, w, 60, label=text, action=action, active=bool(value), size=26,
                      enabled=enabled)
    if kind == CELL_TEXT:
        return _label(identifier, f"{text}: {value}", x, y + 10, w=w, size=26)
    integer = kind == CELL_NUMBER
    return Widget(identifier, SLIDER, x, y, w, 68, label=text, action=action, value=value, minimum=low, maximum=high,
                  size=26, unit="", step=1.0 if integer else max((high - low) / 100.0, 1e-4),
                  decimals=0 if integer else 2, enabled=enabled)


def _item_widgets(item, number, y):
    kind = item[0]
    prefix = f"rig_item_{number}"
    if kind == "hint":
        return [hint(prefix, item[1], LEFT_X, y, w=CONTENT_WIDTH)]
    if kind == "heading":
        return [section(prefix, item[1], LEFT_X, y, w=CONTENT_WIDTH)]
    if kind == "ikfk":
        _kind, is_fk, live = item
        return _row(prefix, (("IK", False), ("FK", True)), LEFT_X, y, CONTENT_WIDTH, 56, 16,
                    lambda index, choice, x, top, w, h: Widget(f"rig_snap_{choice[0]}", CARD, x, top, w, h,
                                                               label=choice[0], action=("rig_snap", choice[1]),
                                                               active=is_fk == choice[1], enabled=live, size=32))
    if kind == "follows":
        _kind, names, current, enabled, changed = item
        widgets = [Widget(prefix, LABEL, LEFT_X, y, 150, 56, label="Follows", size=26, style='title')]
        widgets += _row(prefix, names, LEFT_X + 158, y, CONTENT_WIDTH - 158 - BACK_WIDTH - 8, 56, 8,
                        lambda index, name, x, top, w, h: Widget(f"rig_parent_{index}", CARD, x, top, w, h,
                                                                 label=name, action=("rig_parent", index),
                                                                 active=current == index, enabled=enabled, size=26))
        if changed:
            widgets.append(_back_widget("rig_parent_back", ("rig_reset_follows",), y))
        return widgets
    if kind == "row":
        _kind, row_id, label, cells, changed, enabled = item
        cell_width = (CONTENT_WIDTH - BACK_WIDTH - 8 - 8 * (len(cells) - 1)) / len(cells)
        widgets = [_cell_widget(f"rig_row_{row_id}_{index}", cell, row_id, index, label if index == 0 else "",
                                LEFT_X + index * (cell_width + 8), y, cell_width, enabled)
                   for index, cell in enumerate(cells)]
        if changed:
            widgets.append(_back_widget(f"rig_row_{row_id}_back", ("rig_reset_row", row_id), y))
        return widgets
    if kind == "button":
        _kind, action, label, enabled = item
        return [Widget(f"rig_{action}", CARD, LEFT_X, y, 440, 56, label=label, action=(action,), enabled=enabled,
                       size=26)]
    return []


def _back_widget(identifier, action, y):
    return Widget(identifier, CARD, LEFT_X + CONTENT_WIDTH - BACK_WIDTH, y, BACK_WIDTH, 56, label="↺", action=action,
                  size=32)


def _page_items(view, top):
    """The items from `view.scroll` on, as many as fit, plus Up / Down."""
    widgets, y = [], top
    scroll = min(max(view.scroll, 0), max(len(view.items) - 1, 0))
    shown = scroll
    for number in range(scroll, len(view.items)):
        height = ITEM_HEIGHTS.get(view.items[number][0], 62)
        if y + height - 12 > BOTTOM:
            break
        widgets += _item_widgets(view.items[number], number, y)
        y += height
        shown = number + 1
    if scroll > 0 or shown < len(view.items):
        scroll_x, width = LEFT_X + CONTENT_WIDTH + 12, FULL_WIDTH - CONTENT_WIDTH - 12
        widgets += [Widget("rig_up", CARD, scroll_x, top, width, 94, label="Up", action=("rig_scroll", -SCROLL_STEP),
                           enabled=scroll > 0, size=24),
                    Widget("rig_down", CARD, scroll_x, top + 106, width, 94, label="Down",
                           action=("rig_scroll", SCROLL_STEP), enabled=shown < len(view.items), size=24)]
    return widgets


def picker_lines(picker):
    """The picker as lines: ("heading", section) and ("cards", ((name, changed), ...)) of up to PICKER_COLUMNS."""
    lines = []
    for section_name, names in picker:
        lines.append(("heading", section_name))
        for start in range(0, len(names), PICKER_COLUMNS):
            lines.append(("cards", names[start:start + PICKER_COLUMNS]))
    return lines


LINE_HEIGHTS = {"heading": 44, "cards": 68}     # with the gap below


def picker_pages(lines, height):
    """Lines split into pages that fit `height`; a heading never ends a page."""
    pages, current, used = [], [], 0
    for line in lines:
        need = LINE_HEIGHTS[line[0]] + (LINE_HEIGHTS["cards"] if line[0] == "heading" else 0)
        if current and used + need > height:
            pages.append(current)
            current, used = [], 0
        current.append(line)
        used += LINE_HEIGHTS[line[0]]
    if current:
        pages.append(current)
    return pages or [[]]


def picker_overlay(view, top):
    """The open Part dropdown: a list over the page under the Part button (sections of part cards, Prev / Next when
    they do not fit). A press outside it closes it."""
    part_y = _part_row_y(view, top)
    list_top = part_y + 64
    pager_height = 56 + 12
    room = LIST_BOTTOM - list_top - 26
    pages = picker_pages(picker_lines(view.picker), room)
    if len(pages) > 1:
        pages = picker_pages(picker_lines(view.picker), room - pager_height)
    number = min(max(view.picker_page, 0), len(pages) - 1)
    used = sum(LINE_HEIGHTS[kind] for kind, _content in pages[number]) - 12 + (pager_height if len(pages) > 1 else 0)
    widgets = _popup("rig_pick", LEFT_X, list_top, FULL_WIDTH, used + 26, ("rig_picker",), BODY, radius=12)
    x, width, y = LEFT_X + 13, FULL_WIDTH - 26, list_top + 13
    card_width = (width - 16 * (PICKER_COLUMNS - 1)) / PICKER_COLUMNS
    for line_number, (kind, content) in enumerate(pages[number]):
        if kind == "heading":
            widgets.append(section(f"rig_pick_heading_{line_number}", content, x, y + 4, width))
        else:
            for column, (name, changed) in enumerate(content):
                widgets.append(Widget(f"rig_pick_{name}", CARD, x + column * (card_width + 16), y, card_width, 56,
                                      label=f"{name} •" if changed else name, action=("rig_part", name),
                                      active=name == view.page, size=26))
        y += LINE_HEIGHTS[kind]
    if len(pages) > 1:
        widgets += _pager("rig_pick", x, y, width, number, len(pages), "rig_picker_page")
    return widgets


def _part_row_y(view, top):
    rows = (len(view.groups) + 2) // 3
    return top + (rows * 62 if rows else 0)


def selected_page(view, top):
    """All widgets of the Selected tab's Rig page for `view` (None = an empty view)."""
    view = view or RigView(message="Select a character's bone, armature or mesh to see its rig.")
    if view.message:
        return [hint("rig_message", view.message, LEFT_X, top, size=28, h=36)]
    widgets = grid("rig_group", view.groups, LEFT_X, top, FULL_WIDTH, 3, 50, lambda index, group, x, y, w, h: Widget(
        f"rig_group_{group[0]}", CARD, x, y, w, h, label=group[0], action=("rig_group", group[0]), active=group[1],
        size=26))
    y = _part_row_y(view, top)
    part_width = 330
    widgets.append(Widget("rig_part_button", DROPDOWN, LEFT_X, y, part_width, 56, label=f"Part: {view.page_label}",
                          caret="▼", action=("rig_picker",), active=view.picker_open, size=28, enabled=bool(view.page)))
    resets = ((("rig_reset_part", "Reset Part", 1.0),) if view.reset_part else ()) + (
        ("rig_reset_selected", "Reset Selected", 1.3), ("rig_reset_all", "Reset All", 1.0))
    free = FULL_WIDTH - part_width - 16 * len(resets)
    total = sum(weight for _identifier, _text, weight in resets)
    x = LEFT_X + part_width + 16
    for identifier, text, weight in resets:
        width = free * weight / total
        widgets.append(_card(identifier, x, y, width, 56, text, (identifier,), size=26,
                             enabled=view.pose_mode or identifier == "rig_reset_part"))
        x += width + 16
    y += 68
    widgets.append(hint("rig_status", view.status, LEFT_X, y))
    return widgets + _page_items(view, y + 40)
