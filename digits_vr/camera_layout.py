# SPDX-License-Identifier: GPL-3.0-or-later
"""The Cam view panel's screen (DESIGN "Cam view panel"): a title, the scene camera's picture, a status line and the
Update button, side handles (Pin is added by panel.py). Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from .panel_layout import BUTTON, LABEL, NOTICE, TITLE, PanelSpec, Widget, side_handle

SPEC = PanelSpec(720, 560, scale_range=(0.2, 2.5))     # about 32 x 25 cm at scale 1; down to 0.2: docked on the belt
PICTURE = (40, 76, 640, 360)                         # (x, y, w, h) pixels: 16:9, the camera view is fitted into it


@dataclass(frozen=True)
class CameraModel:
    camera: str = ""            # the scene camera's name ("" = none)
    note: str = ""              # why there is no picture, or ""


def build(model):
    """All widgets, back to front."""
    x, y, w, h = PICTURE
    title = Widget("title", LABEL, x, 18, w - 110, 44, label="Cam view: " + (model.camera or "no camera"), size=30, style=TITLE)
    status = Widget("status", LABEL, x, y + h + 18, w - 220, 60, label=model.note or "Updates when the scene changes",
                    size=24, style=NOTICE if model.note else 'hint')
    update = Widget("camera_update", BUTTON, x + w - 200, y + h + 14, 200, 68, label="Update", action=("camera_update",),
                    enabled=bool(model.camera), size=28)
    return [title, status, update, side_handle('LEFT', SPEC.width, 100, 300), side_handle('RIGHT', SPEC.width, 100, 300)]
