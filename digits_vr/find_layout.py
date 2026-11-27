# SPDX-License-Identifier: GPL-3.0-or-later
"""The Find window's screen (find.py): a search box (a press opens the keyboard), the matches as a scrolling list
(group headers, then one row per item: a name card = Select, a Go card = Select and go there), one scroll bar.
Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from .find_match import HEADER
from .panel_layout import LABEL, PanelSpec, Widget, hint, label, side_handle
from .panel_widgets import card, scrollbar

SPEC = PanelSpec(760, 700)
ROWS = 7                            # list rows on show (headers count as rows)
ROW_TOP, ROW_STEP, ROW_HEIGHT = 168, 64, 56
GO_WIDTH, GAP, BAR_GAP = 130, 10, 12
LEFT, RIGHT = 24, 736               # the content's left and right edge
CURSOR = "|"
HINT_TOP = ROW_TOP + ROWS * ROW_STEP + 4


@dataclass(frozen=True)
class FindModel:
    """What the window shows (plain values: equal models need no redraw)."""
    query: str = ""
    rows: tuple = ()            # the rows on show: (kind, key, label, icon, owner, selected)
    scroll: int = 0
    last: int = 0               # the last scroll position
    total: int = 0              # items found (no headers)
    acting: bool = True         # False: objects can't be selected now (not Object mode)
    workspace: str = ""         # the workspace collection's name, "" = Everything


def build(model):
    """All widgets, back to front."""
    shown = model.query + CURSOR if len(model.query) < 40 else model.query[-40:] + CURSOR
    widgets = [label("title", "Find", LEFT, 18, w=300, size=34),
               card("find_box", LEFT, 76, 560, 72, "Name: " + shown, ("find_ask",), size=32, style='left'),
               card("find_clear", 596, 76, 140, 72, "Clear", ("find_clear",), size=28, enabled=bool(model.query))]
    width = RIGHT - LEFT - 24 - BAR_GAP
    for index, (kind, key, text, icon, owner, selected) in enumerate(model.rows):
        y = ROW_TOP + index * ROW_STEP
        if kind == HEADER:
            widgets.append(Widget(f"find_head_{index}", LABEL, LEFT, y + 14, width, 30, label=text.upper(), size=24,
                                  style='section'))
            continue
        enabled = model.acting or kind != 'O'
        widgets.append(card(f"find_row_{index}", LEFT, y, width - GO_WIDTH - GAP, ROW_HEIGHT, text,
                            ("find_select", kind, key, owner), size=26, style='left', icon=icon, active=selected,
                            enabled=enabled))
        widgets.append(card(f"find_go_{index}", LEFT + width - GO_WIDTH, y, GO_WIDTH, ROW_HEIGHT, "Go",
                            ("find_go", kind, key, owner), size=28, enabled=enabled))
    if not model.query:
        widgets.append(label("find_empty", "Press the box and type a name", LEFT, ROW_TOP + 10, w=width, size=28))
    elif not model.total:
        widgets.append(label("find_empty", "Nothing found", LEFT, ROW_TOP + 10, w=width, size=28))
    widgets += scrollbar("find_scroll", RIGHT - 24, ROW_TOP, ROWS * ROW_STEP - 8, model.scroll, model.last, "find_scroll",
                         visible=ROWS, area=(LEFT, ROW_TOP, width, ROWS * ROW_STEP - 8))
    note = ("Select or Go: only objects in " + (model.workspace or "the scene")) if model.acting \
        else "Go to Object mode to select objects"
    widgets.append(hint("find_note", note, LEFT, HINT_TOP, w=712, size=22))
    widgets += [side_handle('LEFT', SPEC.width, 170, 300), side_handle('RIGHT', SPEC.width, 170, 300)]
    return widgets
