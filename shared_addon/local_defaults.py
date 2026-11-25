# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-computer defaults: an optional JSON file outside the add-ons replaces their built-in default folders, so the code
holds generic ones. No file (the normal case) = the built-in defaults. Read once, when the add-on loads. No bpy.

File: ~/.config/digits_blender_addons/defaults.json, an object {key: value}. DIGITS_ADDONS_DEFAULTS names another file.
Keys: render_folder, texture_studio_output, texture_studio_file, hdri_folders (list), asset_library_name,
asset_library_folders (list), presets_folder, project_folder (holds Library/ and Scripts/), vr_snapshot_folder."""
import json
import os

FILE = os.path.expanduser(os.environ.get("DIGITS_ADDONS_DEFAULTS") or "~/.config/digits_blender_addons/defaults.json")


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


VALUES = _load()


def get(key, default):
    """The local value of `key`, or `default` when it is missing or another type (a list for a tuple is fine)."""
    value = VALUES.get(key)
    if isinstance(default, tuple):
        return tuple(value) if isinstance(value, list) and all(isinstance(v, str) for v in value) else default
    return value if isinstance(value, type(default)) else default
