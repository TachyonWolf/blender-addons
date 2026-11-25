# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-scene Setup storage for the built-in presets, made from builtin_presets.OPTIONS when the add-on
loads: one PropertyGroup class per built-in whose class defaults are that built-in's defaults (so Reset
to Defaults is property_unset), held by fixed PointerProperties on the add-on's scene settings
(setup_draft, setup_final, ...).

Where a built-in's default is None (Keep), a checkbox option becomes Keep / On / Off and any other
option gets a Keep toggle next to its value. Look options also store their starting look (Start With)."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import builtin_presets as bp, look_nodes

KEEP, ON, OFF = "KEEP", "ON", "OFF"
KEEP_ON_OFF = [(KEEP, "Keep", "Leave the scene's own value"), (ON, "On", ""), (OFF, "Off", "")]
TRI_STATE_VALUES = {KEEP: None, ON: True, OFF: False}
CHOICE_LABELS = {"OFF": "No Limit"}
HEADING_NUMBER = 1000   # enum numbers of "" heading items (real items count from 0)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def setup_attr(builtin_name):
    """The PointerProperty name of a built-in's setup: "Ref Sheet" -> "setup_ref_sheet"."""
    return "setup_" + builtin_name.lower().replace(" ", "_")


def keep_attr(option):
    return f"keep_{option.id}"


def start_attr(option):
    """The stored starting look name of a Look option."""
    return f"{option.id}_start"


def start_picker_attr(option):
    """The Start With dropdown (an enum that only reads and writes start_attr)."""
    return f"{option.id}_start_picker"


def choice_label(choice):
    return CHOICE_LABELS.get(choice, choice)


# ---------------------------------------------------------------------------
# A string kept behind an enum dropdown (dynamic items can't have a string default or survive a
# reload as an index, so the choice lives in a StringProperty and the enum is only a picker)
# ---------------------------------------------------------------------------

def string_picker(name, items_function, string_attr, on_pick=None, description=""):
    """An EnumProperty showing `items_function`'s items whose value is the StringProperty
    `string_attr`. Items are 5-tuples numbered from 0; "" items are headings. `on_pick(owner, id)`
    runs after a pick."""
    def get(owner):
        """The number of the stored choice; the first real item when it is gone (a deleted file)."""
        current = getattr(owner, string_attr)
        real = [item for item in items_function(owner, bpy.context) if item[0]]
        return next((item[4] for item in real if item[0] == current), real[0][4] if real else 0)

    def set_value(owner, number):
        for item in items_function(owner, bpy.context):
            if item[0] and item[4] == number:
                setattr(owner, string_attr, item[0])
                if on_pick:
                    on_pick(owner, item[0])
                return

    return EnumProperty(name=name, description=description, items=items_function, get=get, set=set_value)


# ---------------------------------------------------------------------------
# Option properties
# ---------------------------------------------------------------------------

def fallback_value(option):
    """A starting value for an option a built-in keeps: the first built-in that sets it, else the range start."""
    for spec in bp.BUILTINS.values():
        if spec["defaults"].get(option.id) is not None:
            return spec["defaults"][option.id]
    if option.type == "choice":
        return option.choices[0]
    return False if option.type == "bool" else option.minimum


def option_property(option, default):
    """The Blender property for one option with this built-in default (None = Keep)."""
    if option.type == "bool" and default is None:
        return EnumProperty(name=option.label, items=KEEP_ON_OFF, default=KEEP)
    value = fallback_value(option) if default is None else default
    if option.type == "bool":
        return BoolProperty(name=option.label, default=value)
    if option.type == "choice":
        items = [(choice, choice_label(choice), "") for choice in option.choices]
        return EnumProperty(name=option.label, items=items, default=value)
    if option.type == "int":
        return IntProperty(name=option.label, default=value, min=int(option.minimum), max=int(option.maximum))
    return FloatProperty(name=option.label, default=value, min=option.minimum, max=option.maximum, precision=3, step=0.1)


_start_items = {}   # group -> enum items; kept here because Blender needs the strings to stay alive


def start_items_for(option):
    def items(owner, context):
        names = look_nodes.starting_looks(option.chain_group) or [bp.default_look(option)]
        _start_items[option.chain_group] = [(name, name, f"Start {option.label} from the {name} look", 'NONE', i)
                                            for i, name in enumerate(names)]
        return _start_items[option.chain_group]
    return items


def start_picked(option):
    """Picking a starting look writes it onto the applied chain's node straight away."""
    def on_pick(setup, look_name):
        look_nodes.write_starting_look(setup.id_data, option.chain_group, look_name)
    return on_pick


def setup_annotations(builtin_name):
    defaults = bp.default_options(builtin_name)
    annotations = {}
    for option in bp.OPTIONS:
        default = defaults[option.id]
        annotations[option.id] = option_property(option, default)
        if default is None and option.type != "bool":
            annotations[keep_attr(option)] = BoolProperty(
                name="Keep", default=True, description="Leave the scene's own value (untick to set it)")
        if option.group == bp.LOOK:
            annotations[start_attr(option)] = StringProperty(name="Start With", default=bp.default_look(option))
            annotations[start_picker_attr(option)] = string_picker(
                "Start With", start_items_for(option), start_attr(option), start_picked(option),
                description="The look this effect starts from; picking one sets the live sliders")
    return annotations


def make_setup_class(builtin_name):
    defaults = bp.default_options(builtin_name)
    return type(f"RenderPresetsSetup_{setup_attr(builtin_name)[6:]}", (bpy.types.PropertyGroup,), {
        "__annotations__": setup_annotations(builtin_name),
        "builtin_name": builtin_name,
        "keep_ids": frozenset(option_id for option_id, value in defaults.items() if value is None),
    })


SETUP_CLASSES = {name: make_setup_class(name) for name in bp.BUILTINS}


def setup_pointers():
    """{PointerProperty name: PointerProperty} for the add-on's scene settings."""
    return {setup_attr(name): bpy.props.PointerProperty(type=cls) for name, cls in SETUP_CLASSES.items()}


# ---------------------------------------------------------------------------
# Reading and resetting a setup
# ---------------------------------------------------------------------------

def setup_for(ui, builtin_name):
    return getattr(ui, setup_attr(builtin_name))


def option_value(setup, option):
    """The option's value, None for Keep."""
    value = getattr(setup, option.id)
    if isinstance(value, float):
        value = round(value, 6)   # a FloatProperty is single precision: 0.02 reads 0.0199999...
    if option.id not in setup.keep_ids:
        return value
    if option.type == "bool":
        return TRI_STATE_VALUES[value]
    return None if getattr(setup, keep_attr(option)) else value


def setup_options(setup):
    """{option id: value or None} for options_to_preset."""
    return {option.id: option_value(setup, option) for option in bp.OPTIONS}


def setup_starts(setup):
    """{look option id: starting look name}."""
    return {option.id: getattr(setup, start_attr(option)) for option in bp.options_in_group(bp.LOOK)}


def reset_setup(setup):
    """Back to the built-in's defaults; the live chain nodes get the default starting looks again."""
    pickers = {start_picker_attr(option) for option in bp.options_in_group(bp.LOOK)}
    for name in type(setup).__annotations__:
        if name not in pickers:
            setup.property_unset(name)
    for option in bp.options_in_group(bp.LOOK):
        look_nodes.write_starting_look(setup.id_data, option.chain_group, getattr(setup, start_attr(option)))
