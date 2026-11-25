# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewpoints window's screen (DESIGN "QoL batch": a window like the desk, opened from the Move tab): Save current
spot, then the saved spots with Go and Delete, a page at a time. Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from .panel_layout import BUTTON, CARD, PanelSpec, label, side_handle, Widget

SPEC = PanelSpec(760, 640)          # about 34 x 29 cm at scale 1; two handles: move, and both = scale
ROWS = 5                            # spots per page
ROW_TOP, ROW_STEP, ROW_HEIGHT = 176, 76, 64


@dataclass(frozen=True)
class ViewpointsModel:
    """What the window shows (plain values: equal models need no redraw)."""
    names: tuple = ()           # the spots on this page
    first: int = 0              # index of the first one shown
    page: int = 0
    pages: int = 1
    total: int = 0


def pages(total):
    return max(1, (total + ROWS - 1) // ROWS)


def page_slice(page, total):
    """(first index, page) clamped to the pages there are."""
    page = min(max(0, page), pages(total) - 1)
    return page * ROWS, page


def build(model):
    """All widgets, back to front."""
    widgets = [label("title", "Viewpoints", 24, 18, w=400, size=34),
               Widget("spot_save", BUTTON, 24, 76, 712, 72, label="Save current spot", size=36, action=("spot_save",))]
    if not model.names:
        widgets.append(label("empty", "No saved spots yet", 24, ROW_TOP + 10, w=712, size=30))
    for offset, name in enumerate(model.names):
        index, y = model.first + offset, ROW_TOP + offset * ROW_STEP
        widgets += [Widget("spot_name_%d" % index, CARD, 24, y, 400, ROW_HEIGHT, label=name, size=32,
                           action=("spot_rename", index)),
                    Widget("spot_go_%d" % index, CARD, 440, y, 140, ROW_HEIGHT, label="Go", size=32, action=("spot_go", index)),
                    Widget("spot_delete_%d" % index, CARD, 596, y, 140, ROW_HEIGHT, label="Delete", size=28,
                           action=("spot_delete", index))]
    if model.pages > 1:
        pager_y = ROW_TOP + ROWS * ROW_STEP + 8
        widgets += [Widget("spot_prev", CARD, 24, pager_y, 160, 52, label="Prev", size=28, action=("spot_page", -1),
                           enabled=model.page > 0),
                    label("spot_page", "Page %d of %d" % (model.page + 1, model.pages), 280, pager_y + 6, w=220, size=28),
                    Widget("spot_next", CARD, 576, pager_y, 160, 52, label="Next", size=28, action=("spot_page", 1),
                           enabled=model.page < model.pages - 1)]
    widgets += [side_handle('LEFT', SPEC.width, 170, 300), side_handle('RIGHT', SPEC.width, 170, 300)]
    return widgets
