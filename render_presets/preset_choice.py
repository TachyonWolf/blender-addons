# SPDX-License-Identifier: GPL-3.0-or-later
"""Which preset the dropdown has chosen, and the preset dict it stands for. The choice is stored as a
string id ("builtin:Final" / "saved:Cafe Night"); the dropdown enum (Built-in / Saved headings) is only
a picker over it. A built-in's preset comes from its Setup plus the live values of the applied chain's
nodes, so re-Apply and Save as My Preset keep tweaks made on the sliders."""

import os

from . import builtin_presets as bp, compositor_chain, look_nodes, preset_store, setup_props

BUILTIN, SAVED = "builtin", "saved"
DEFAULT_CHOICE = f"{BUILTIN}:Final"
DEFAULT_PRESETS_DIR = "~/Blender/RenderPresets"
OLD_DEFAULT_PRESETS_DIR = "~/Blender/OldRenderPresets"  # inside the add-on; moved out
_items = []   # the dropdown's items; kept here because Blender needs the strings to stay alive


def choice_id(kind, name):
    return f"{kind}:{name}"


def parse_choice(choice):
    """("builtin" | "saved", name)."""
    kind, _, name = choice.partition(":")
    return kind, name


def migrated_presets_dir(value):
    """The old default folder (written with or without ~) becomes the new default; any other value stays."""
    if os.path.expanduser(value) == os.path.expanduser(OLD_DEFAULT_PRESETS_DIR):
        return DEFAULT_PRESETS_DIR
    return value


def migrate_preferences(context):
    """Update the stored folder preference once, at register. Does nothing when run as a plain folder."""
    addon = context.preferences.addons.get(__package__)
    if addon:
        addon.preferences.presets_dir = migrated_presets_dir(addon.preferences.presets_dir)


def user_dir(context):
    addon = context.preferences.addons.get(__package__)  # None when run as a plain folder (tests)
    return os.path.expanduser(migrated_presets_dir(addon.preferences.presets_dir) if addon else DEFAULT_PRESETS_DIR)


def saved_presets(context):
    return preset_store.list_presets(user_dir(context))


def saved_label(name):
    """A saved preset named like a built-in shows as "Name (saved)"."""
    return f"{name} (saved)" if name in bp.BUILTINS else name


def picker_items(owner, context):
    """Built-in heading, the built-ins, Saved heading, the saved presets (numbered, see string_picker)."""
    entries = [("", "Built-in", "")]
    entries += [(choice_id(BUILTIN, name), name, "Built-in preset (tune it in Setup)") for name in bp.preset_names()]
    saved = saved_presets(context) if context else {}
    if saved:
        entries.append(("", "Saved", ""))
        entries += [(choice_id(SAVED, name), saved_label(name), "Your saved preset") for name in saved]
    _items.clear()
    number = 0
    for identifier, label, description in entries:
        if identifier:
            _items.append((identifier, label, description, 'NONE', number))
            number += 1
        else:
            _items.append((identifier, label, description, 'NONE', setup_props.HEADING_NUMBER + len(_items)))
    return _items


def chosen(context):
    """(kind, name) of the dropdown's choice."""
    return parse_choice(context.scene.render_presets_ui.chosen)


def builtin_setup(context):
    """The chosen built-in's setup, or None for a saved preset."""
    kind, name = chosen(context)
    if kind != BUILTIN or name not in bp.BUILTINS:
        return None
    return setup_props.setup_for(context.scene.render_presets_ui, name)


def builtin_preset(scene, setup):
    """The preset dict of a built-in's setup, with the live look values of the chain it would build."""
    preset = bp.options_to_preset(setup.builtin_name, setup_props.setup_options(setup),
                                  starts=setup_props.setup_starts(setup))
    look = look_nodes.read_look(scene, preset.get("compositor_chain", []))
    if look:
        preset[compositor_chain.LOOK_KEY] = look
    return preset


def selected_preset(context):
    """The chosen preset's dict, or None (nothing chosen, or a saved file that is gone)."""
    setup = builtin_setup(context)
    if setup is not None:
        return builtin_preset(context.scene, setup)
    kind, name = chosen(context)
    return saved_presets(context).get(name) if kind == SAVED else None
