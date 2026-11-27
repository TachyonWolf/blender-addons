# SPDX-License-Identifier: GPL-3.0-or-later
"""Asset library list (Preferences > File Paths > Asset Libraries) and the background scan.

The scan runs in its OWN `blender -b` process (asset_worker.py), at low priority, so the VR session never loads a .blend file or
stalls a frame: libraries.load() in the session would block for tens of milliseconds per file. The worker writes the
cache (asset_cache.py) in the extension's user folder; this module only starts it, polls it (a cheap `poll()` every
POLL_TICKS session ticks) and tells the page when new results are there."""
import os
import subprocess
import time
from dataclasses import dataclass

import bpy

from . import asset_cache, settings
from .asset_state import APPEND, APPEND_REUSE, LINK

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "asset_worker.py")
POLL_TICKS = 15                 # session ticks between two checks of the worker (~2 per second)
FRESH_SECONDS = 300.0           # a session start skips the scan when the last one is younger than this
METHODS = {'LINK': LINK, 'APPEND': APPEND, 'APPEND_REUSE': APPEND_REUSE, 'FOLLOW_PREFS': LINK}  # Blender's default: Link


@dataclass(frozen=True)
class Library:
    name: str
    path: str
    method: str     # LINK, APPEND or APPEND_REUSE


def libraries(context=None):
    """The asset libraries of the user's Preferences (folders that exist), in their order."""
    preferences = (context or bpy.context).preferences
    return [Library(item.name, os.path.normpath(bpy.path.abspath(item.path)), METHODS.get(item.import_method, LINK))
            for item in preferences.filepaths.asset_libraries if item.path and os.path.isdir(bpy.path.abspath(item.path))]


def cache_folder():
    """Where the scan cache lives: the add-on's user folder (settings.user_folder)."""
    return os.path.join(settings.user_folder(), "asset_cache")


def worker_command(binary, folder, paths):
    """The worker's command line. POSIX runs it under `nice` (lowest priority); Windows has no `nice`: see worker_options."""
    command = [binary, "-b", "--factory-startup", "-noaudio", "--python", WORKER, "--", folder, *paths]
    return command if os.name == "nt" else ["nice", "-n", "19", *command]


def worker_options():
    """Popen keywords: no stdio; on Windows also idle priority and no console window (the worker is a console program)."""
    options = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        options["creationflags"] = subprocess.IDLE_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW
    return options


_scan = {"process": None, "finished": 0, "error": ""}      # finished: counts completed scans (the page reloads on a change)


def scanning():
    return _scan["process"] is not None


def finished_count():
    return _scan["finished"]


def last_error():
    return _scan["error"]


def start(force=False, folder=None):
    """Start the background scan (not when one runs, or, unless `force`, when the cache is fresh). True if started."""
    if scanning():
        return False
    folder = folder or cache_folder()
    if not force and time.time() - asset_cache.load_index(folder).get("scanned_at", 0.0) < FRESH_SECONDS:
        return False
    paths = [library.path for library in libraries()]
    if not paths or not bpy.app.binary_path:
        return False
    os.makedirs(folder, exist_ok=True)
    _scan["process"] = subprocess.Popen(worker_command(bpy.app.binary_path, folder, paths), **worker_options())
    _scan["error"] = ""
    return True


def poll(ticks=0):
    """Check the worker (every POLL_TICKS ticks); True when it just finished."""
    process = _scan["process"]
    if process is None or (ticks and ticks % POLL_TICKS):
        return False
    code = process.poll()
    if code is None:
        return False
    _scan["process"] = None
    _scan["error"] = "" if code == 0 else f"scan failed (exit code {code})"
    _scan["finished"] += 1
    return True


def stop():
    """Session over: end a running scan (partial results stay in the cache; the next scan carries on)."""
    process, _scan["process"] = _scan["process"], None
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()


class DIGITSVR_OT_scan_assets(bpy.types.Operator):
    """Scan the asset libraries for the Assets tab in VR (runs in a background Blender; the tab fills when it is done)"""
    bl_idname = "digits_vr.scan_assets"
    bl_label = "Scan Asset Libraries"

    def execute(self, context):
        started = start(force=True)
        self.report({'INFO'}, "Scanning asset libraries in the background" if started else
                    "A scan is already running" if scanning() else "No asset libraries to scan")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(DIGITSVR_OT_scan_assets)


def unregister():
    stop()
    bpy.utils.unregister_class(DIGITSVR_OT_scan_assets)
