# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/depth_fog_presets.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Depth Fog starting looks: density, colour, curve, height fade and glow. Applied to a Depth Fog group
node with apply_preset(node, name). Start / End are left alone (they follow the scene's size, or the
Fog Marks). "Default" is the group's own starting values."""
try:                                     # inside the add-on package
    from . import compositor_common as cc
except ImportError:                      # Scripts/<group folder> copy: compositor_common is one folder up
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
    import compositor_common as cc  # noqa: E402

PRESETS = {
    "Default": {"Density": 0.8, "Fog Colour": (0.62, 0.70, 0.80, 1.0), "Falloff": 1.0, "Height Fade": 0.0,
                "Glow": 0.0, "Glow Threshold": 1.0, "Glow Size": 0.03},
    "Light Haze": {"Density": 0.35, "Fog Colour": (0.70, 0.76, 0.85, 1.0), "Falloff": 1.4, "Height Fade": 0.0,
                   "Glow": 0.1, "Glow Threshold": 1.0, "Glow Size": 0.03},
    "Morning Mist": {"Density": 0.7, "Fog Colour": (0.85, 0.88, 0.92, 1.0), "Falloff": 0.8, "Height Fade": 0.6,
                     "Glow": 0.3, "Glow Threshold": 0.8, "Glow Size": 0.05},
    "Smoggy": {"Density": 0.85, "Fog Colour": (0.55, 0.50, 0.40, 1.0), "Falloff": 0.7, "Height Fade": 0.0,
               "Glow": 0.4, "Glow Threshold": 1.0, "Glow Size": 0.06},
    "Deep Dusk": {"Density": 0.75, "Fog Colour": (0.18, 0.16, 0.30, 1.0), "Falloff": 1.2, "Height Fade": 0.2,
                  "Glow": 0.8, "Glow Threshold": 0.6, "Glow Size": 0.08},
}


def preset_values(name):
    return dict(PRESETS[name])


def apply_preset(group_node, name):
    cc.apply_values(group_node, PRESETS[name])
