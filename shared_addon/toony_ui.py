# SPDX-License-Identifier: GPL-3.0-or-later
"""Toony modifier controls for the Selected cards (shared: Addons/shared_addon/toony_ui.py is the ONE source, synced into
Digit's Modifiers and Digit's Assorted Tools; each draws it in its own Selected card).

`draw_modifier` draws one Geometry Nodes modifier as a plain arrow group (eye in the header, first main input as the
summary): the MAIN inputs, a closed "More" group with the other value inputs, a Helpers row of select buttons and the
recipe's tool buttons (Re-rest...). Main vs More comes from the node group's own interface: inputs outside its "More"
panel are main. The recipe table (Digit's Modifiers only) is optional extra knowledge: it sets `recipe_info`, a function
mod -> Info(controls, buttons, subject_socket) or None, which fixes the main inputs' order, adds the tool buttons and says
which Object input is the subject (not a helper). Without it a modifier counts as Toony when its group has a More panel.
Tweaking only: select helper, sliders, Re-rest; nothing here builds or removes.
"""
from collections import namedtuple

import bpy
from bpy.props import StringProperty

from .modifier_setup import MORE_PANEL, WIRING_TYPES, modifier_input, more_inputs  # generated copy
from .ui_cards import friendly_name, group, shorten, sub_heading  # generated copy

Info = namedtuple("Info", "controls buttons subject_socket")   # buttons = ((operator idname, label, icon), ...)
SUMMARY_CHARS = 24   # a header summary shares the row with the title and the eye
HELPER_BUTTON_CHARS = 16

recipe_info = lambda mod: None   # noqa: E731  (Digit's Modifiers replaces it with its recipe table lookup)
_panel_cache = {}                # node group name -> (interface item count, has a More panel)


def has_more_panel(tree):
    """True when the node group has a top level "More" interface panel (cached per group, invalidated by item count)."""
    count = len(tree.interface.items_tree)
    cached = _panel_cache.get(tree.name)
    if cached and cached[0] == count:
        return cached[1]
    found = any(i.item_type == 'PANEL' and i.name == MORE_PANEL for i in tree.interface.items_tree)
    _panel_cache[tree.name] = (count, found)
    return found


def info_of(mod):
    return recipe_info(mod) if mod.type == 'NODES' and mod.node_group else None


def is_toony(mod):
    return mod.type == 'NODES' and mod.node_group is not None and (info_of(mod) is not None or has_more_panel(mod.node_group))


def toony_modifiers(ob):
    """The Toony modifiers on `ob` in stack order (known to the recipe table, or with a More panel)."""
    return [mod for mod in ob.modifiers if is_toony(mod)]


def main_inputs(mod):
    """Socket names of the main inputs: the recipe's `controls`, else the value inputs outside the More panel."""
    info = info_of(mod)
    if info is not None:
        return info.controls
    return [i.name for i in mod.node_group.interface.items_tree
            if i.item_type == 'SOCKET' and i.in_out == 'INPUT' and i.socket_type not in WIRING_TYPES
            and not (i.parent and i.parent.name == MORE_PANEL)]


def is_field(mod, name):
    """True for a vertex group / attribute style input (shown only once a group is set)."""
    return next((item.structure_type == 'FIELD' for item in mod.node_group.interface.items_tree
                 if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name), False)


def mod_input(layout, mod, name, **kwargs):
    """Draw the Geometry Nodes modifier input called `name`: its value, or its vertex group when it is set to one. An
    unset vertex group input draws nothing (Blender has no call to draw a modifier's own panel inside another layout).
    Returns True when something was drawn."""
    item = modifier_input(mod, name)
    if item.type == 'ATTRIBUTE':
        layout.prop_search(item, "attribute_name", mod.id_data, "vertex_groups", text=name)
    elif is_field(mod, name):
        return False
    elif isinstance(item.value, bool):   # a checkbox is drawn full width: a split row pushes it right and cuts its label
        flag = layout.column(align=True)
        flag.use_property_split = False
        flag.prop(item, "value", text=name, **kwargs)
    else:
        layout.prop(item, "value", text=name, **kwargs)
    return True


def value_summary(mod, name):
    """"Progress 0.40": the input's name and value for a folded group's header ("" when it is no plain number / choice)."""
    item = modifier_input(mod, name)
    if item.type != 'VALUE':
        return ""
    value = item.value
    if isinstance(value, bool):
        text = "On" if value else "Off"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    elif isinstance(value, (int, str)):
        text = str(value)
    else:
        return ""
    return f"{name} {text}"[:SUMMARY_CHARS]


def modifier_helpers(mod):
    """[(label, object)] helper objects wired into a Toony modifier: its Object inputs that are set (not the mesh
    the recipe itself points at) and the empties of its Collection inputs (Fold Lines)."""
    info = info_of(mod)
    skip = info.subject_socket if info else None
    found = []
    for item in mod.node_group.interface.items_tree:
        if item.item_type != 'SOCKET' or item.in_out != 'INPUT' or item.name == skip:
            continue
        if item.socket_type == 'NodeSocketObject':
            ob = modifier_input(mod, item.name).value
            if ob is not None:
                found.append((item.name, ob))
        elif item.socket_type == 'NodeSocketCollection':
            collection = modifier_input(mod, item.name).value
            found += [(friendly_name(ob.name), ob) for ob in (collection.objects if collection else ()) if ob.type == 'EMPTY']
    return found


def select_helper_id(package):
    return f"{package.rsplit('.', 1)[-1]}.select_helper"


def make_select_helper(package):
    """The select-helper operator class of one extension (`package` = its folder name; own operator id per extension)."""
    idname = select_helper_id(package)

    class SelectHelper(bpy.types.Operator):
        """Select this helper object of the modifier"""
        bl_idname = idname
        bl_label = "Select Helper"
        bl_options = {'REGISTER', 'UNDO'}

        name: StringProperty(name="Object", options={'HIDDEN'})

        def execute(self, context):
            ob = bpy.data.objects.get(self.name)
            if ob is None or ob.name not in context.view_layer.objects:
                self.report({'WARNING'}, f"'{self.name}' is not in this view layer")
                return {'CANCELLED'}
            for other in context.selected_objects:
                other.select_set(False)
            ob.select_set(True)
            context.view_layer.objects.active = ob
            return {'FINISHED'}

    SelectHelper.__name__ = SelectHelper.__qualname__ = f"{package.rsplit('.', 1)[-1].upper()}_OT_select_helper"
    return SelectHelper


def draw_helpers(layout, context, owner, mod, select_operator):
    """The Helpers heading and a 2 column grid of select buttons, the selected one pressed."""
    helpers = modifier_helpers(mod)
    if not helpers:
        return
    sub_heading(layout, "Helpers")
    grid = layout.grid_flow(columns=2, align=True)
    for label, ob in helpers:
        text = shorten(label.removeprefix(friendly_name(owner.name) + " "), HELPER_BUTTON_CHARS)
        grid.operator(select_operator, text=text, depress=ob == context.active_object).name = ob.name


def draw_modifier(layout, context, owner, mod, index, idprefix, select_operator):
    """One Toony modifier of `owner`: a plain group (first one open) with its eye and a summary of its first main
    input. `idprefix` keeps the folded states apart per card; `select_operator` = this extension's select-helper id."""
    controls = main_inputs(mod)
    idname = f"{idprefix}_{owner.name}_{mod.name}"
    body = group(layout, idname, mod.name, default_closed=index > 0, right=value_summary(mod, controls[0]) if controls else "",
                 extra=lambda header: header.prop(mod, "show_viewport", text="", emboss=False))
    if body is None:
        return
    for name in controls:
        mod_input(body, mod, name)
    more = [item.name for item in more_inputs(mod.node_group, controls) if not is_field(mod, item.name)
            or modifier_input(mod, item.name).type == 'ATTRIBUTE']
    if more:
        extra = group(body, idname + "_more", MORE_PANEL, default_closed=True, right=f"{len(more)} inputs")
        if extra:
            for name in more:
                mod_input(extra, mod, name)
    draw_helpers(body, context, owner, mod, select_operator)
    info = info_of(mod)
    for operator, label, icon in info.buttons if info else ():
        body.operator(operator, text=label, icon=icon)
