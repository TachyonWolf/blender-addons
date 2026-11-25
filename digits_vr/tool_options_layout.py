# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool options panel's screen (DESIGN "Tool options panel"): a small panel with one handle that shows the current
mode's tools and settings (tool_rows.py, the same rows as the desk's Tools page). Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from . import tool_rows
from .panel_layout import LABEL, TITLE, TOGGLE, PanelSpec, Widget, side_handle

SPEC = PanelSpec(640, 1290, scale_range=(0.2, 2.5))          # about 29 x 56 cm at scale 1: the tallest mode fits (test_edit_tools)
BODY = (SPEC.width, SPEC.height)
LEFT, TOP, WIDTH = 29, 76, 582
MODE_LABELS = {'OBJECT': "Object", 'EDIT_MESH': "Edit", 'POSE': "Pose", 'SCULPT': "Sculpt", 'PAINT_GREASE_PENCIL': "Draw"}


@dataclass(frozen=True)
class ToolOptionsModel(tool_rows.ToolsModel):
    attached: bool = False      # snaps back to the tool belt when you get far away


def build(model):
    """All widgets, back to front: title, the mode's rows, Attached, the handle, an open pop-up."""
    rows = tool_rows.narrow(model, LEFT, TOP, WIDTH)
    title = Widget("title", LABEL, LEFT, 22, WIDTH, 44, label="Tool options: " + MODE_LABELS.get(model.mode, "Other"), size=32,
                   style=TITLE)
    attached = Widget("attached", TOGGLE, LEFT, SPEC.height - 85, WIDTH, 60, label="Attached to the belt", size=26,
                      action=("attached",), active=model.attached)
    return [title, *rows, attached, side_handle('LEFT', SPEC.width, 60, 420), side_handle('RIGHT', SPEC.width, 60, 420),
            *tool_rows.overlay(model, rows, BODY, SPEC.height - 20)]
