"""Render preset files and the apply / revert / save logic. Pure Python plus scene data, no UI, so the
add-on, the headless script and the tests all share it.

A preset file is JSON: {"name": ..., "groups": [...optional render_settings groups...],
"settings": {"scene.cycles.samples": 64, ...}}. Explicit settings win over groups. Optional
"compositor_chain" (+ "compositor_presets") builds a compositor node-group chain (compositor_chain.py); optional
"look": {group: {input name: value}} holds the chain's live tweaks (Save as My Preset writes it) and is
applied after the starting looks. Files without it load as before. Presets stay plain data so other tools
(a Scene Kit, mood lighting) can add keys later; unknown keys are kept as they are.
"""
import json
import os
import re

from . import compositor_chain, fog_marks, render_settings as rs

REVERT_KEY = "render_presets_revert"    # scene custom property: JSON {path: value before the first apply}
APPLIED_KEY = "render_presets_applied"  # scene custom property: name of the last applied preset


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def file_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("_").lower() + ".json"


def list_presets(directory):
    """{name: preset dict} of the JSON files in a folder; an unreadable file is reported and skipped."""
    presets = {}
    if not os.path.isdir(directory):
        return presets
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, entry)) as f:
                preset = json.load(f)
            presets[preset["name"]] = preset
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"ERROR: render presets: skipped preset file {os.path.join(directory, entry)}: {error!r}")
    return presets


def save_preset(directory, preset):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, file_name(preset["name"])), "w") as f:
        json.dump(preset, f, indent=2)
        f.write("\n")


def delete_preset(directory, name):
    path = os.path.join(directory, file_name(name))
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ---------------------------------------------------------------------------
# Resolving, diffing, applying, reverting
# ---------------------------------------------------------------------------

def resolved_settings(scene, preset):
    """The preset's full {path: value} for this scene: its groups first, then its own settings."""
    settings = rs.group_settings(scene, preset.get("groups", []))
    settings.update(preset.get("settings", {}))
    return settings


def preset_diff(scene, preset):
    return rs.diff_settings(scene, resolved_settings(scene, preset))


def apply_preset(scene, preset):
    """Apply a preset, keeping the values it replaces so revert_preset can undo it. Applying a second
    preset keeps the first snapshot, so one revert goes back to the scene as it was. Returns skipped paths."""
    settings = resolved_settings(scene, preset)
    saved = json.loads(scene.get(REVERT_KEY, "{}"))
    before = rs.read_settings(scene, [p for p in settings if p not in saved])
    saved.update(before)
    scene[REVERT_KEY] = json.dumps(saved)
    scene[APPLIED_KEY] = preset["name"]
    note = compositor_chain.apply_chain(scene, preset)
    if note:
        scene[compositor_chain.NOTE_KEY] = note
    fog_marks.rebuild_drivers(scene)   # a rebuilt compositor tree has lost the Fog Marks' drivers
    return rs.apply_settings(scene, settings)


def can_revert(scene):
    return REVERT_KEY in scene


def revert_preset(scene):
    """Put back the values stored by apply_preset; returns skipped paths."""
    saved = json.loads(scene.get(REVERT_KEY, "{}"))
    skipped = rs.apply_settings(scene, saved)
    compositor_chain.revert_chain(scene)
    fog_marks.rebuild_drivers(scene)
    for key in (REVERT_KEY, APPLIED_KEY):
        if key in scene:
            del scene[key]
    return skipped


def capture_preset(scene, name, group_names):
    """A new preset holding the scene's current values of the ticked capture groups."""
    paths = [p for group in group_names for p in rs.CAPTURE_GROUPS[group]]
    return {"name": name, "settings": rs.read_settings(scene, paths)}
