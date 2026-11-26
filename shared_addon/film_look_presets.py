"""Film Look presets: which film effects are on and how strong. Applied to a Film Look group node
(the node in the compositor that uses the asset) with apply_preset(node, name). Lens effects
(dirt, flare, lens scratches) have their own presets in lens_effects_presets.py."""
try:                                     # inside the add-on package
    from . import compositor_common as cc
except ImportError:                      # Scripts/<group folder> copy: compositor_common is one folder up
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
    import compositor_common as cc  # noqa: E402

EFFECTS = ("Halation", "Grain", "Scratches", "Weave")

# preset -> {effect: amount}; an effect that is missing is off. Other sliders keep their values.
PRESETS = {
    "Subtle": {"Halation": 0.25, "Grain": 0.12},
    "Cinematic": {"Halation": 0.35, "Grain": 0.22},
    "Vintage": {"Halation": 0.6, "Grain": 0.3, "Scratches": 0.45, "Weave": 0.3},
    "Off": {},
}


def preset_values(name):
    return cc.preset_values(EFFECTS, PRESETS, name)


def apply_preset(group_node, name):
    cc.apply_preset(group_node, EFFECTS, PRESETS, name)
