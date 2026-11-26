# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/render_polish_presets.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Render Polish starting looks: glow, bloom, fringe, vignette, brightness and sharpening. Applied to a
Render Polish group node with apply_preset(node, name). "Default" is the group's own starting values
(the old look); Soft and Punchy leave the line settings alone."""
try:                                     # inside the add-on package
    from . import compositor_common as cc
except ImportError:                      # Scripts/<group folder> copy: compositor_common is one folder up
    import os
    import sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
    import compositor_common as cc  # noqa: E402

PRESETS = {
    "Default": {"Glow Strength": 0.6, "Bloom Strength": 0.2, "Lens Fringe": 0.015, "Vignette Strength": 0.25,
                "Vignette Size": 0.9, "Vignette Softness": 0.2, "Brightness": 1.0, "Sharpen Amount": 0.5,
                "Lines Opacity": 1.0, "Glow Over Lines": False},
    "Soft": {"Glow Strength": 0.8, "Bloom Strength": 0.35, "Lens Fringe": 0.008, "Vignette Strength": 0.15,
             "Vignette Size": 1.0, "Vignette Softness": 0.5, "Brightness": 1.02, "Sharpen Amount": 0.2},
    "Punchy": {"Glow Strength": 0.5, "Bloom Strength": 0.15, "Lens Fringe": 0.02, "Vignette Strength": 0.35,
               "Vignette Size": 0.85, "Vignette Softness": 0.25, "Brightness": 1.05, "Sharpen Amount": 0.9},
}


def preset_values(name):
    return dict(PRESETS[name])


def apply_preset(group_node, name):
    cc.apply_values(group_node, PRESETS[name])
