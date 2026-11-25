# SPDX-License-Identifier: GPL-3.0-or-later
"""The PDA's screen (DESIGN "Personal PDA"): a tab row, a grid of slots, an Edit mode with its buttons. A linked slot shows
the DESK's own widget (same label, state and values, resolved by the caller from the desk's current screen) in the slot's
place; a link the desk's current page doesn't have shows dim. Pure Python (no bpy), tested headless."""
from dataclasses import dataclass, replace

from . import pda_math as math_
from .panel_layout import (BUTTON, CARD, HANDLE, HINT, LABEL, SLIDER, TAB, TITLE, TOGGLE, PanelSpec, Widget, divider, grid, hint,
                           side_handle)

SPEC = PanelSpec(520, 820)
LEFT, WIDTH = 24, 472
SLOT_COLUMNS, SLOT_HEIGHT, SLOT_TOP = 2, 84, 236
TEXT_LIMIT = 26                  # a linked widget's text is no bigger than this (slots are small)
PICK_HINT = "Now press a control on the desk (tabs and lists only move around it)."
EMPTY_HINT = "Press an empty slot, then a control on the desk."
EDIT_HINT = "Press a slot to pick it, then move or remove it."
NO_TABS_HINT = "No tabs yet. Press + to make one."
SLOT_ID = "pda_slot_"


@dataclass(frozen=True)
class PdaModel:
    """What the PDA shows (plain values: equal models need no redraw)."""
    tabs: tuple = ()                # ((name, links), ...)
    current: int = 0
    edit: bool = False
    selected: int = -1              # the picked slot in Edit mode (-1 none)
    picking: int = -1               # the slot waiting for a desk control (-1 none)
    armed: bool = False             # Delete tab pressed once
    linked: tuple = ()              # per slot of the current tab: the desk's own Widget, or None (not on the desk's page)
    names: tuple = ()               # per slot: the last text seen for its link (a dim slot's label)


def pretty(link):
    return link.replace("_", " ").strip().capitalize()


def _card(identifier, x, y, w, h, text, action, size=26, **more):
    return Widget(identifier, CARD, x, y, w, h, label=text, action=action, size=size, **more)


def _slot(model, index, link, x, y, w, h):
    """One slot's widget: blank, picking, linked (the desk's widget, moved here) or dim."""
    identifier, action = SLOT_ID + str(index), ("pda_slot", index)
    desk = model.linked[index] if index < len(model.linked) else None
    name = (model.names[index] if index < len(model.names) else "") or pretty(link)
    if model.picking == index:
        return _card(identifier, x, y, w, h, "Pick on desk...", action, size=24, active=True)
    if not link:
        return _card(identifier, x, y, w, h, "+" if not model.edit else "Empty", action, size=34 if not model.edit else 24)
    if model.edit or desk is None:
        return _card(identifier, x, y, w, h, (desk.label if desk and desk.label else name), action, size=24,
                     active=model.edit and model.selected == index, enabled=model.edit)
    return replace(desk, id=identifier, x=x, y=y, w=w, h=h, action=action, size=min(desk.size, TEXT_LIMIT),
                   kind=desk.kind if desk.kind in (BUTTON, CARD, TOGGLE, SLIDER) else CARD)


def _tab_row(model):
    count = len(model.tabs)
    name = model.tabs[model.current][0] if count else "No tabs"
    return [_card("pda_prev", LEFT, 82, 64, 64, "<", ("pda_tab_step", -1), size=34, enabled=count > 1),
            Widget("pda_tab_name", TAB, LEFT + 76, 82, 232, 64, label=name, size=30, active=bool(count)),
            _card("pda_next", LEFT + 320, 82, 64, 64, ">", ("pda_tab_step", 1), size=34, enabled=count > 1),
            _card("pda_new", LEFT + 396, 82, 76, 64, "+", ("pda_new_tab",), size=38, enabled=count < math_.MAX_TABS)]


def _edit_row(model):
    has_tab = bool(model.tabs)
    return [_card("pda_rename", LEFT, 160, 224, 56, "Rename tab", ("pda_rename",), enabled=has_tab),
            _card("pda_delete", LEFT + 248, 160, 224, 56, "Sure? Delete" if model.armed else "Delete tab", ("pda_delete",),
                  enabled=has_tab, active=model.armed)]


def _bottom(model):
    top = SLOT_TOP + math_.SLOTS_PER_TAB // SLOT_COLUMNS * (SLOT_HEIGHT + 12) + 4
    if not model.tabs:
        return [hint("pda_hint", NO_TABS_HINT, LEFT, top + 14, WIDTH, 56)]
    if model.picking >= 0:
        return [hint("pda_hint", PICK_HINT, LEFT, top + 14, WIDTH, 56)]
    if model.edit:
        picked = model.selected >= 0
        return [_card("pda_earlier", LEFT, top, 144, 64, "Earlier", ("pda_move", -1), enabled=picked and model.selected > 0),
                _card("pda_later", LEFT + 164, top, 144, 64, "Later", ("pda_move", 1),
                      enabled=picked and model.selected < math_.SLOTS_PER_TAB - 1),
                _card("pda_remove", LEFT + 328, top, 144, 64, "Remove", ("pda_remove",), enabled=picked),
                hint("pda_hint", EDIT_HINT, LEFT, top + 76, WIDTH, 28)]
    return [hint("pda_hint", EMPTY_HINT, LEFT, top + 14, WIDTH, 56)]


def build(model):
    """All widgets, back to front: title, Edit, tab row, (Edit row), slots, the bottom row, the handle."""
    widgets = [Widget("pda_title", LABEL, LEFT, 22, 200, 44, label="PDA", size=34, style=TITLE),
               Widget("pda_edit", TOGGLE, LEFT + 252, 18, 220, 52, label="Edit", action=("pda_edit",), active=model.edit, size=28)]
    widgets += _tab_row(model)
    if model.edit:
        widgets += _edit_row(model)
    else:
        widgets.append(divider("pda_line", LEFT, 188, WIDTH))
    if model.tabs:
        links = model.tabs[model.current][1]
        widgets += grid("pda_slots", links, LEFT, SLOT_TOP, WIDTH, SLOT_COLUMNS, SLOT_HEIGHT,
                        lambda index, link, x, y, w, h: _slot(model, index, link, x, y, w, h))
    widgets += _bottom(model)
    widgets += [side_handle('LEFT', SPEC.width, 60, 340), side_handle('RIGHT', SPEC.width, 60, 340)]
    return widgets


def slot_index(widget_id):
    """The slot number of a PDA slot widget id, or -1."""
    return int(widget_id[len(SLOT_ID):]) if widget_id.startswith(SLOT_ID) else -1
