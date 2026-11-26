# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/lens_effects_presets.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Lens Effects presets: which lens effects are on and how strong. Applied to a Lens Effects group
node with apply_preset(node, name). Film effects have their own presets in film_look_presets.py."""
try:                                     # inside the add-on package
    from . import compositor_common as cc
except ImportError:                      # Scripts/<group folder> copy: compositor_common is one folder up
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
    import compositor_common as cc  # noqa: E402

EFFECTS = ("Lens Dirt", "Flare", "Lens Scratches")

# preset -> {effect: amount}; an effect that is missing is off. Other sliders keep their values.
PRESETS = {
    "Clean": {"Flare": 0.15},
    "Cinematic": {"Flare": 0.3, "Lens Dirt": 0.12, "Lens Scratches": 0.15},
    "Old Lens": {"Lens Dirt": 0.3, "Lens Scratches": 0.4, "Flare": 0.2},
    "Off": {},
}


def preset_values(name):
    return cc.preset_values(EFFECTS, PRESETS, name)


def apply_preset(group_node, name):
    cc.apply_preset(group_node, EFFECTS, PRESETS, name)
