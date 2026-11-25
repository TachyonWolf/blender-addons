# SPDX-License-Identifier: GPL-3.0-or-later
"""The Selected panel of the Modifiers tab: one framed box per selected object that has Toony Modifiers (or whose helper
empty / curve / plate is selected), one plain arrow group per modifier on it with its main inputs, a closed More group
with the other value inputs, a Helpers row of select buttons and the recipe's tool buttons. The main inputs are the
recipe table's `controls` (recipes.py); the registry and card are the shared selected_ui.py."""
from . import selected_ui, toony_ui  # generated copy
from .recipes import modifier_helpers, selected_owners, toony_modifiers
from .ui_cards import friendly_name, status  # generated copy

SELECTED_ID = "modhelp_selected"
SUMMARY_CHARS = toony_ui.SUMMARY_CHARS


MODHELP_OT_select_helper = toony_ui.make_select_helper(__package__)


SELECT_HELPER = toony_ui.select_helper_id(__package__)


def draw_modifier(layout, context, owner, mod, index):
    toony_ui.draw_modifier(layout, context, owner, mod, index, SELECTED_ID, SELECT_HELPER)


def draw_owner(box, context, thing):
    """The box of one object: a status line, then its Toony modifiers."""
    owner, _picked = thing
    mods = toony_modifiers(owner)
    status(box, f"{mods[0].name} on {friendly_name(owner.name)}" if len(mods) == 1 else f"{len(mods)} Toony modifiers",
           icon='MESH_DATA' if owner.type == 'MESH' else 'OBJECT_DATA')
    for index, mod in enumerate(mods):
        draw_modifier(box, context, owner, mod, index)


def helper_label(owner, helper):
    """The helper's name as the modifier calls it ("Grab B"), else its object name in plain words."""
    return next((label for mod in toony_modifiers(owner) for label, ob in modifier_helpers(mod) if ob is helper),
                friendly_name(helper.name))


def entries(context):
    """[(key, box title, (owner, selected helpers))]: "Taffy Body" or, with a helper selected, "Taffy Body · Grab B"."""
    found = []
    for owner, picked in selected_owners(context).items():
        title = friendly_name(owner.name)
        if picked:
            title += " · " + helper_label(owner, picked[0])
        found.append((owner.name, title, (owner, picked)))
    return found


def empty_hint(context):
    """(grey hint, header summary) when no selected object has a Toony modifier."""
    ob = context.active_object
    if ob is not None and ob.type != 'ARMATURE':
        return f"{friendly_name(ob.name)} has no Toony modifiers yet. Add one below.", friendly_name(ob.name)[:SUMMARY_CHARS]
    return "Select a mesh with Toony modifiers to edit them here", "nothing"


selected_ui.add_each("Toony Modifiers", entries, draw_owner)


def draw_selected_body(layout, context):
    selected_ui.draw_body(layout, context, SELECTED_ID, empty_hint)


def header_summary(context):
    return selected_ui.header_summary(context, empty_hint)


classes = (MODHELP_OT_select_helper,)
