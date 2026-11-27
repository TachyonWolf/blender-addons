# SPDX-License-Identifier: GPL-3.0-or-later
"""The personal PDA (bpy side, DESIGN "Personal PDA"): a small floating panel on the shared panel system, and a held item
named "pda" (held_item.py) that works without the belt. You make, rename and delete tabs; a tab has blank slots. Press a
blank slot, then a control on the desk: the slot becomes a LINK to that desk widget (its id). A linked slot shows the desk's
own widget (live label, state, value from desk_actions.build_model + desk_layout.build) and a press runs the desk's own
desk_actions.perform: one source of truth, no copies. A link the desk's current mode / page doesn't have shows dim and does
nothing. The layout is saved in the add-on's settings (`pda_tabs`, `pda_tab`), so it follows you across files. Closed = no
panel tick, no draw; the desk's press hook (`take_pick`) returns at once while nothing is being picked."""
import bpy
from mathutils import Vector

from . import desk_actions, desk_layout, keyboard, pda_layout as layout, pda_math as math_, settings
from .held_item import PanelHeldItem
from .panel import Panel
from .panel_layout import BACKDROP, DROPDOWN, HANDLE, LABEL, POPUP, SLOT, TAB, THUMB

NOT_LINKED = (HANDLE, LABEL, BACKDROP, POPUP, SLOT, TAB, DROPDOWN, THUMB)   # tabs and dropdowns only move around the desk
NAVIGATION = ("popup", "selected_sub", "tab")
GRAB_RADIUS = 0.22                  # m (scale 1) from the PDA's middle: a grip this close can take it
_names = {}                         # link -> the last label seen for it (what a dim slot shows)
_desk = {"model": None, "widgets": {}}


class Session:
    """What the PDA is doing right now (not saved)."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.edit, self.selected, self.picking, self.armed = False, -1, -1, False


SESSION = Session()


def linkable(widget):
    return bool(widget.action) and widget.kind not in NOT_LINKED and widget.action[0] not in NAVIGATION


def desk_widgets(context):
    """{id: Widget} of the desk's current screen (the linkable ones); rebuilt only when the desk's model changed."""
    model = desk_actions.build_model(context)
    if model is not _desk["model"]:
        _desk.update(model=model, widgets={widget.id: widget for widget in desk_layout.build(model) if linkable(widget)})
    return _desk["widgets"]


def tabs_and_current():
    tabs = math_.from_settings(settings.get("pda_tabs"))
    return tabs, min(settings.get("pda_tab"), max(0, len(tabs) - 1))


def _save(tabs, current):
    settings.put_many({"pda_tabs": math_.to_settings(tabs), "pda_tab": current})


def build_model(context):
    tabs, current = tabs_and_current()
    links = tabs[current][1] if tabs else ()
    found = desk_widgets(context) if any(links) else {}
    for link, widget in ((link, found.get(link)) for link in links):
        if widget is not None and widget.label:
            _names[link] = widget.label
    return layout.PdaModel(tabs, current, SESSION.edit, SESSION.selected, SESSION.picking, SESSION.armed,
                           tuple(found.get(link) if link else None for link in links),
                           tuple(_names.get(link, "") for link in links))


# -- what the buttons do ----------------------------------------------------------------------------------------------

def _press_slot(context, widget, pixel_x):
    index = layout.slot_index(widget.id)
    tabs, current = tabs_and_current()
    if not tabs or index < 0:
        return False
    link = tabs[current][1][index]
    if SESSION.picking == index:                     # the same slot again: stop waiting
        SESSION.picking = -1
    elif not link:
        SESSION.picking, SESSION.selected = index, -1
    elif SESSION.edit:
        SESSION.selected, SESSION.picking = index, -1
    else:
        return run_link(context, link, widget, pixel_x)
    return True


def run_link(context, link, widget, pixel_x):
    """Do what the desk's widget `link` does (a press, or a slider drag at the slot's pixel x). False when the desk's
    current page has no such control, or it is dim."""
    target = desk_widgets(context).get(link)
    if target is None or not target.enabled:
        return False
    done = desk_actions.perform(context, target, math_.mapped_pixel_x(widget, target, pixel_x))
    if done:
        desk_actions.forget_model()
    return done


def _step_tab(_context, widget, _pixel_x):
    tabs, current = tabs_and_current()
    SESSION.selected = SESSION.picking = -1
    _save(tabs, math_.step_tab(len(tabs), current, widget.action[1]))
    return True


def _new_tab(_context, _widget, _pixel_x):
    tabs = math_.add_tab(tabs_and_current()[0])
    SESSION.selected = SESSION.picking = -1
    _save(tabs, len(tabs) - 1)
    return True


def _rename(_context, _widget, _pixel_x):
    tabs, current = tabs_and_current()
    if not tabs:
        return False
    keyboard.ask("Name this tab", tabs[current][0], lambda text: _renamed(current, text), near=PANEL)
    return True


def _renamed(index, text):
    tabs, current = tabs_and_current()
    _save(math_.rename_tab(tabs, index, text), current)
    PANEL.refresh(bpy.context, force=True)


def _delete(_context, _widget, _pixel_x):
    tabs, current = tabs_and_current()
    if not tabs:
        return False
    if not SESSION.armed:                           # the first press only asks "Sure?"
        SESSION.armed = True
        return True
    SESSION.armed, SESSION.selected, SESSION.picking = False, -1, -1
    tabs = math_.delete_tab(tabs, current)
    _save(tabs, min(current, max(0, len(tabs) - 1)))
    return True


def _toggle_edit(_context, _widget, _pixel_x):
    SESSION.edit, SESSION.selected, SESSION.picking = not SESSION.edit, -1, -1
    return True


def _move(_context, widget, _pixel_x):
    tabs, current = tabs_and_current()
    if SESSION.selected < 0:
        return False
    tabs, SESSION.selected = math_.move_slot(tabs, current, SESSION.selected, widget.action[1])
    _save(tabs, current)
    return True


def _remove(_context, _widget, _pixel_x):
    tabs, current = tabs_and_current()
    if SESSION.selected < 0:
        return False
    _save(math_.clear_slot(tabs, current, SESSION.selected), current)
    SESSION.selected = -1
    return True


ACTIONS = {"pda_slot": _press_slot, "pda_tab_step": _step_tab, "pda_new_tab": _new_tab, "pda_rename": _rename,
           "pda_delete": _delete, "pda_edit": _toggle_edit, "pda_move": _move, "pda_remove": _remove}


def take_pick(context, widget):
    """The desk's press hook (desk.DeskPanel.take_trigger): while a PDA slot waits, a linkable desk control becomes its
    link and the press does nothing else. False (the press goes on as usual) when nothing waits, or it's a tab / list."""
    if SESSION.picking < 0 or not linkable(widget):
        return False
    tabs, current = tabs_and_current()
    _save(math_.set_slot(tabs, current, SESSION.picking, widget.id), current)
    SESSION.picking = -1
    PANEL.refresh(context, force=True)
    return True


class PdaPanel(Panel):
    name = "pda"
    spec = layout.SPEC
    open_side = -0.5            # first opens to the left of the desk
    open_drop = 0.1

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        if not widget.action or not widget.enabled:
            return False
        handler = ACTIONS.get(widget.action[0])
        if handler is None:
            return False
        if widget.action[0] != "pda_delete":
            SESSION.armed = False
        return handler(context, widget, pixel_x)

    def closed(self):
        SESSION.reset()
        _desk.update(model=None, widgets={})


PANEL = PdaPanel()


class PdaItem(PanelHeldItem):
    """The PDA as a held item: the belt moves, shows and hides it through this (it never imports the belt)."""
    name = "pda"
    panel = PANEL

    @property
    def shown(self):
        return PANEL.state.open

    @shown.setter
    def shown(self, value):
        if not value and PANEL.state.open:
            PANEL.close()

    def set_matrix(self, matrix):
        PANEL.state.set_matrix(matrix)
        PANEL.state.placed = True

    def grip_hit(self, position):
        state = PANEL.state
        return state.open and (state.location - Vector(position)).length <= GRAB_RADIUS * state.scale


ITEM = PdaItem()
