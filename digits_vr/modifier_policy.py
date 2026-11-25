# SPDX-License-Identifier: GPL-3.0-or-later
"""Which modifiers show in VR: the bookkeeping, pure Python (no bpy), tested headless.

Heavy modifiers are off in VR by default; each modifier can be switched on (or a light one off) on its own. The
choices are stored in a local Scene custom property (JSON), keyed by object name + library path + modifier
persistent_uid, because new custom properties on library overrides are not saved (spike C, Q5)."""
import json

# Approved split (DESIGN.md "Modifiers in VR"): OFF in VR by default
HEAVY_TYPES = frozenset({'SUBSURF', 'MULTIRES', 'REMESH', 'NODES', 'BOOLEAN', 'BEVEL', 'DECIMATE', 'SCREW', 'SKIN',
                         'WELD', 'VOLUME_TO_MESH', 'OCEAN'})
KEY_SEPARATOR = "|"


def choice_key(object_name, library_path, uid):
    """Key of one modifier's VR choice. library_path is '' for local data (overrides are local)."""
    return KEY_SEPARATOR.join((object_name, library_path or "", str(uid)))


def default_shown(modifier_type):
    return modifier_type not in HEAVY_TYPES


def shown_in_vr(modifier_type, choice):
    """True when the modifier shows in VR: the user's choice (True / False) wins, else the type default."""
    return default_shown(modifier_type) if choice is None else bool(choice)


def read_choices(text):
    """{key: bool} from the stored JSON (bad data is logged and dropped)."""
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        print("digits_vr: unreadable VR modifier choices, ignored")
        return {}
    return {str(key): bool(value) for key, value in data.items()} if isinstance(data, dict) else {}


def write_choices(choices):
    return json.dumps(dict(sorted(choices.items())))


def set_choice(choices, key, modifier_type, shown):
    """Store a choice; a choice equal to the type default is dropped, so the store holds only exceptions."""
    updated = dict(choices)
    if shown == default_shown(modifier_type):
        updated.pop(key, None)
    else:
        updated[key] = bool(shown)
    return updated


def to_hide(modifiers, choices):
    """Keys of the modifiers to turn off for VR. `modifiers` = [(key, type, show_viewport)]; only modifiers on in
    the viewport are touched (the user's own off ones stay off and are never recorded)."""
    return [key for key, modifier_type, show_viewport in modifiers
            if show_viewport and not shown_in_vr(modifier_type, choices.get(key))]
