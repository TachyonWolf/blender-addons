# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's File tab: Save only (plain Ctrl+S: `wm.save_mainfile`). Our save_pre / save_post handlers already put the
VR-only settings back around a save, so the file keeps the user's own settings. An untitled file is not saved from VR
(the file dialog is not usable there): a message says so. Shows the file name and "Saved" until the file changes."""
import os
from contextlib import nullcontext

import bpy

from .context_helper import run_in_view3d

UNTITLED = "Save it once on the desktop first"
FAILED = "Could not save (see the desktop)"


class State:
    saved = False         # we saved it, and nothing changed since
    message = ""          # the last refusal / failure


STATE = State()


def is_dirty():
    return bpy.data.is_dirty


def view():
    """(file name, status line, message) for the File page."""
    name = os.path.basename(bpy.data.filepath)
    if not name:
        return "", "Not saved yet", STATE.message
    if is_dirty():
        return name, "Unsaved changes", STATE.message
    return name, "Saved" if STATE.saved else "No changes", STATE.message


def save(context):
    """The Save button. Returns True when the file was written."""
    STATE.saved, STATE.message = False, ""
    if not bpy.data.filepath:
        STATE.message = UNTITLED
        return False
    try:
        done = run_in_view3d(context, lambda: bpy.ops.wm.save_mainfile())
        if not done:        # no 3D View open: the window alone is enough for a save
            windows = context.window_manager.windows
            with context.temp_override(window=windows[0]) if windows else nullcontext():
                bpy.ops.wm.save_mainfile()
    except RuntimeError as error:
        print(f"digits_vr: save failed: {error}")
        STATE.message = FAILED
        return False
    STATE.saved = True
    return True
