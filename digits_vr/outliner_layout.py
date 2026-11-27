# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's Outliner tab (outliner.py): the scene's collections with their objects as laser-pressable rows, an
Everything choice and a reset button, a lock on every row, an on / off switch on every collection, one scroll bar. Also the
workspace chip on the ledge. The list scrolls row by row like every list (the scroll bar and the shared drag / stick). Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from .blender_icons import checkbox_icon, disclosure_icon, lock_icon
from .panel_layout import LABEL, SCROLL_WIDTH, Widget, scroll_window
from .panel_widgets import card, scrollbar

EVERYTHING_LABEL = "Everything"
COLLECTION, OBJECT = 'C', 'O'
ROW_PREFIX = "workspace_row_"
ROW_STEP, ROW_HEIGHT, FOLD_WIDTH, INDENT, MAX_DEPTH = 64, 56, 56, 28, 6
BASE_ROWS = 6          # rows on show at the desk's normal height; each 64 px of extra height adds one
LABEL_LIMIT = 26       # characters of a name on the chip
ICON_BUTTON_WIDTH, GAP = 72, 8     # the lock and the On / Off checkbox: icon only, a square-ish target (row is 56 high)


@dataclass(frozen=True)
class OutlinerRow:
    kind: str                 # COLLECTION or OBJECT
    name_full: str
    label: str
    depth: int = 0
    foldable: bool = False    # a collection with children or objects
    opened: bool = False
    enabled: bool = True      # a collection: not excluded from the view layer (Blender's checkbox)
    locked: bool = False      # hide_select, the desktop's "disable in selection"
    icon: str = ""            # Blender's Outliner icon (blender_icons)
    selected: bool = False    # an object selected in the world (the row mirrors it)

    def fold_key(self):
        return self.kind + ":" + self.name_full


def rows_shown(extra=0):
    return BASE_ROWS + extra // ROW_STEP


def short(text, limit=LABEL_LIMIT):
    return text if len(text) <= limit else text[:limit - 1] + "…"


def window_of(rows, scroll, shown):
    """(rows on show, scroll clamped into range, last scroll)."""
    scroll, last = scroll_window(len(rows), shown, scroll)
    return rows[scroll:scroll + shown], scroll, last


def chip_text(label):
    return "Workspace: " + short(label)


def page_widgets(model, top):
    """The Outliner tab: Everything and Reset on top, the rows below with their scroll bar and pager."""
    widgets = [card("workspace_everything", 24, top, 300, 60, EVERYTHING_LABEL, ("workspace_set", ""), size=28,
                    active=not model.workspace_current, style='left'),
               card("workspace_reset", 340, top, 330, 60, "Reset workspace to All", ("workspace_set", ""), size=24,
                    enabled=bool(model.workspace_current)),
               card("workspace_find", 686, top, 110, 60, "Find", ("panel", "find"), size=28),      # the Find window (find.py)
               Widget("workspace_hint", LABEL, 810, top, 190, 60, label="Press a collection to work there", size=20, style='note')]
    list_top, width = top + 76, 976 - SCROLL_WIDTH - 12
    lock_x = 24 + width - ICON_BUTTON_WIDTH
    for index, row in enumerate(model.workspace_rows):
        y = list_top + index * ROW_STEP
        if row.foldable:
            widgets.append(card(f"workspace_fold_{index}", 24, y, FOLD_WIDTH, ROW_HEIGHT, "",
                                ("workspace_fold", row.fold_key()), icon=disclosure_icon(row.opened)))
        right = lock_x - GAP
        if row.kind == COLLECTION:
            right -= ICON_BUTTON_WIDTH + GAP
            widgets.append(card(f"workspace_switch_{index}", right + GAP, y, ICON_BUTTON_WIDTH, ROW_HEIGHT, "",
                                ("workspace_enable", row.name_full), active=row.enabled, icon=checkbox_icon(row.enabled)))
        indent = FOLD_WIDTH + GAP + min(row.depth, MAX_DEPTH) * INDENT
        action = ("workspace_set", row.name_full) if row.kind == COLLECTION else ()
        widgets.append(card(f"{ROW_PREFIX}{index}", 24 + indent, y, right - 24 - indent, ROW_HEIGHT, row.label, action,
                            size=26, style='left', enabled=row.name_full != model.outliner_drag, claims_drag=row.kind == OBJECT,
                            icon=row.icon, active=row.fold_key() == model.outliner_drop or row.selected
                            or (row.kind == COLLECTION and row.name_full == model.workspace_current)))
        widgets.append(card(f"workspace_lock_{index}", lock_x, y, ICON_BUTTON_WIDTH, ROW_HEIGHT, "",
                            ("workspace_lock", row.kind, row.name_full), active=not row.locked, icon=lock_icon(row.locked)))   # lit = selectable
    rows = rows_shown(model.extra)
    return widgets + scrollbar("workspace_scroll", 972, list_top, rows * ROW_STEP - 8, model.workspace_scroll, model.workspace_last,
                               "workspace_scroll", visible=rows, area=(24, list_top, width, rows * ROW_STEP - 8))
