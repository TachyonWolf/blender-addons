# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's VR: pose characters and move objects from inside VR (Blender's OpenXR session).
Sidebar tab VR. Milestone 1: select, hover, grab objects and pose bones (Free / Laser), heavy modifiers off in VR
with file safety. Docs: docs/ (README, TECH, DESIGN, STATUS)."""
from . import asset_scan, desk, display_state, modifier_state, perf_state, session, settings, ui, user_scale

MODULES = (settings, ui, modifier_state, display_state, perf_state, asset_scan, desk, user_scale, session)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
