# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's Selected tab: widgets of the rig panel (Digit's Assorted Tools' Character Rig box) from a RigView.
Pure Python (no bpy), tested headless. rig_tab.py reads the rig into a RigView with the shared rig_page functions;
this module only places widgets.

Top to bottom: Show Bones group cards (A held = add / remove, like Shift), the Part button + Reset Part / Selected /
All, the status line, then either the page's items (scrolled with Up / Down) or, while the Part button is on, the
Part picker (sections, pages of part cards)."""
from dataclasses import dataclass

from .desk_layout import CARD, SLIDER, TOGGLE, Widget, _label, _row

# item kinds of a RigView (plain tuples, so equal views need no redraw):
#   ("hint", text) / ("heading", text)
#   ("ikfk", is_fk, live)
#   ("follows", (parent names), current index, enabled, changed)
#   ("row", row id, label, cells, changed, enabled); cells = ((side, kind, value, low, high), ...), kind one of
#       CELL_SLIDER / CELL_TOGGLE / CELL_NUMBER / CELL_TEXT (a vector: shown, not edited)
#   ("button", action name, label, enabled)
CELL_SLIDER, CELL_TOGGLE, CELL_NUMBER, CELL_TEXT = "slider", "toggle", "number", "text"
LEFT_X, FULL_WIDTH = 24, 976
CONTENT_WIDTH = 896                 # items; the Up / Down column sits at its right
BACK_WIDTH = 60                     # the ↺ of a changed row (its space is kept on every row)
SCROLL_STEP = 3                     # items per Up / Down press
PICKER_COLUMNS = 4
BOTTOM = 748                        # the screen's usable bottom (pixels)
ITEM_HEIGHTS = {"hint": 36, "heading": 40, "ikfk": 62, "follows": 62, "row": 70, "button": 62}


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
        return Widget(identifier, TOGGLE, x, y, w, 60, label=text, action=action, active=bool(value), size=28,
                      enabled=enabled)
    if kind == CELL_TEXT:
        return _label(identifier, f"{text}: {value}", x, y + 10, w=w, size=26)
    integer = kind == CELL_NUMBER
    return Widget(identifier, SLIDER, x, y, w, 66, label=text, action=action, value=value, minimum=low, maximum=high,
                  size=26, unit="", step=1.0 if integer else max((high - low) / 100.0, 1e-4),
                  decimals=0 if integer else 2, enabled=enabled)


def _item_widgets(item, number, y):
    kind = item[0]
    prefix = f"rig_item_{number}"
    if kind == "hint":
        return [_label(prefix, item[1], LEFT_X, y, w=CONTENT_WIDTH, size=24)]
    if kind == "heading":
        return [_label(prefix, item[1], LEFT_X, y + 4, w=CONTENT_WIDTH, size=28)]
    if kind == "ikfk":
        _kind, is_fk, live = item
        return _row(prefix, (("IK", False), ("FK", True)), LEFT_X, y, CONTENT_WIDTH, 56, 10,
                    lambda index, choice, x, top, w, h: Widget(f"rig_snap_{choice[0]}", CARD, x, top, w, h,
                                                               label=choice[0], action=("rig_snap", choice[1]),
                                                               active=is_fk == choice[1], enabled=live, size=32))
    if kind == "follows":
        _kind, names, current, enabled, changed = item
        widgets = [_label(prefix, "Follows", LEFT_X, y + 8, w=150, size=26)]
        widgets += _row(prefix, names, LEFT_X + 160, y, CONTENT_WIDTH - 160 - BACK_WIDTH - 8, 56, 8,
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
                       size=28)]
    return []


def _back_widget(identifier, action, y):
    return Widget(identifier, CARD, LEFT_X + CONTENT_WIDTH - BACK_WIDTH, y, BACK_WIDTH, 56, label="↺", action=action,
                  size=34)


def _page_items(view, top):
    """The items from `view.scroll` on, as many as fit, plus Up / Down."""
    widgets, y = [], top
    scroll = min(max(view.scroll, 0), max(len(view.items) - 1, 0))
    shown = scroll
    for number in range(scroll, len(view.items)):
        height = ITEM_HEIGHTS.get(view.items[number][0], 62)
        if y + height > BOTTOM:
            break
        widgets += _item_widgets(view.items[number], number, y)
        y += height
        shown = number + 1
    if scroll > 0 or shown < len(view.items):
        scroll_x, half = LEFT_X + CONTENT_WIDTH + 10, (BOTTOM - top - 10) / 2
        widgets += [Widget("rig_up", CARD, scroll_x, top, FULL_WIDTH - CONTENT_WIDTH - 10, half, label="Up",
                           action=("rig_scroll", -SCROLL_STEP), enabled=scroll > 0, size=26),
                    Widget("rig_down", CARD, scroll_x, top + half + 10, FULL_WIDTH - CONTENT_WIDTH - 10, half,
                           label="Down", action=("rig_scroll", SCROLL_STEP), enabled=shown < len(view.items),
                           size=26)]
    return widgets


def picker_lines(picker):
    """The picker as lines: ("heading", section) and ("cards", ((name, changed), ...)) of up to PICKER_COLUMNS."""
    lines = []
    for index, (section, names) in enumerate(picker):
        if index:                   # Full Body (the first section) needs no heading, like the desktop drop-down
            lines.append(("heading", section))
        for start in range(0, len(names), PICKER_COLUMNS):
            lines.append(("cards", names[start:start + PICKER_COLUMNS]))
    return lines


LINE_HEIGHTS = {"heading": 38, "cards": 54}


def picker_pages(lines, height):
    """Lines split into pages that fit `height`; a heading never ends a page."""
    pages, current, used = [], [], 0
    for index, line in enumerate(lines):
        need = LINE_HEIGHTS[line[0]] + (LINE_HEIGHTS["cards"] if line[0] == "heading" else 0)
        if current and used + need > height:
            pages.append(current)
            current, used = [], 0
        current.append(line)
        used += LINE_HEIGHTS[line[0]]
    if current:
        pages.append(current)
    return pages or [[]]


def _picker(view, top):
    pager_height = 50
    pages = picker_pages(picker_lines(view.picker), BOTTOM - top - pager_height - 8)
    number = min(max(view.picker_page, 0), len(pages) - 1)
    widgets, y = [], top
    card_width = (FULL_WIDTH - 8 * (PICKER_COLUMNS - 1)) / PICKER_COLUMNS
    for line_number, (kind, content) in enumerate(pages[number]):
        if kind == "heading":
            widgets.append(_label(f"rig_pick_heading_{line_number}", content, LEFT_X, y + 2, size=26))
        else:
            for column, (name, changed) in enumerate(content):
                widgets.append(Widget(f"rig_pick_{name}", CARD, LEFT_X + column * (card_width + 8), y, card_width,
                                      48, label=f"{name} •" if changed else name, action=("rig_part", name),
                                      active=name == view.page, size=24))
        y += LINE_HEIGHTS[kind]
    if len(pages) > 1:
        pager_y = BOTTOM - pager_height
        widgets += [Widget("rig_pick_prev", CARD, LEFT_X, pager_y, 180, pager_height, label="< Prev",
                           action=("rig_picker_page", -1), enabled=number > 0, size=26),
                    _label("rig_pick_count", f"Page {number + 1} of {len(pages)}", 420, pager_y + 6, w=200, size=24),
                    Widget("rig_pick_next", CARD, FULL_WIDTH + LEFT_X - 180, pager_y, 180, pager_height,
                           label="Next >", action=("rig_picker_page", 1), enabled=number < len(pages) - 1, size=26)]
    return widgets


def selected_page(view, top):
    """All widgets of the Selected tab for `view` (None = an empty view)."""
    view = view or RigView(message="Select a character's bone, armature or mesh to see its rig.")
    if view.message:
        return [_label("rig_message", view.message, LEFT_X, top, size=30)]
    widgets, y = [], top
    if view.groups:
        rows = [view.groups[start:start + 3] for start in range(0, len(view.groups), 3)]
        for row_number, groups in enumerate(rows):
            widgets += _row("rig_group", groups, LEFT_X, y, FULL_WIDTH, 42, 8,
                            lambda index, group, x, row_y, w, h: Widget(
                                f"rig_group_{group[0]}", CARD, x, row_y, w, h, label=group[0],
                                action=("rig_group", group[0]), active=group[1], size=26))
            y += 50
        y += 4
    part_width = 412 if view.reset_part else 596
    widgets.append(Widget("rig_part_button", CARD, LEFT_X, y, part_width, 52,
                          label=f"Part: {view.page_label}  {'▲' if view.picker_open else '▼'}",
                          action=("rig_picker",), active=view.picker_open, size=26, enabled=bool(view.page)))
    resets = ((("rig_reset_part", "Reset Part"),) if view.reset_part else ()) + (
        ("rig_reset_selected", "Reset Selected"), ("rig_reset_all", "Reset All"))
    widgets += _row("rig_reset", resets, LEFT_X + part_width + 8, y, FULL_WIDTH - part_width - 8, 52, 8,
                    lambda index, item, x, row_y, w, h: Widget(
                        item[0], CARD, x, row_y, w, h, label=item[1], action=(item[0],), size=24,
                        enabled=view.pose_mode or item[0] == "rig_reset_part"))
    y += 60
    if view.picker_open:
        return widgets + _picker(view, y)
    widgets.append(_label("rig_status", view.status, LEFT_X, y, size=24))
    return widgets + _page_items(view, y + 36)

