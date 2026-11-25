# SPDX-License-Identifier: GPL-3.0-or-later
"""The Display tab (bpy side): what the VR view hides (bones, cameras, lights, ...). These are VR-only settings of
`wm.xr_session_settings`, so the scene is not touched. The choice (`display_hidden`, keys of display_types.py) is
saved in the settings JSON. Every item is written as a change of the Performance record (perf_state.WM_KEY,
shared with the compositor and draw distance), so teardown / file save put Blender's own values back.
Picking skips the hidden types (picking.SceneCache)."""
import bpy

from . import display_types, settings
from .runtime import RUNTIME


def changes(window_manager):
    """(ID, path, value) changes for scene_record.set_values: every item set from the saved choice."""
    hidden = settings.get("display_hidden")
    return [(window_manager, "xr_session_settings." + item.attr, item.key not in hidden) for item in display_types.ITEMS]


def hidden_types():
    return frozenset(settings.get("display_hidden"))


def hides(object_type):
    return display_types.hides_type(settings.get("display_hidden"), object_type)


def toggle(key):
    settings.put("display_hidden", display_types.toggled(settings.get("display_hidden"), key))


def show_all():
    settings.put("display_hidden", [])


def _on_changed(_value):
    """The choice changed: write it to the view now (a session runs) and make picking forget hidden objects."""
    if not RUNTIME.active:
        return
    from . import scene_record
    from .perf_state import WM_KEY
    scene_record.set_values(bpy.context.window_manager, WM_KEY, changes(bpy.context.window_manager), "window_managers")
    RUNTIME.cache.all_dirty = True
    RUNTIME.cache.objects = None
    RUNTIME.cache.version += 1


def register():
    settings.LISTENERS.setdefault("display_hidden", []).append(_on_changed)


def unregister():
    if _on_changed in settings.LISTENERS.get("display_hidden", ()):
        settings.LISTENERS["display_hidden"].remove(_on_changed)
