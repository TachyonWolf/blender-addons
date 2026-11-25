# SPDX-License-Identifier: GPL-3.0-or-later
"""The Screenshot button (View and File tabs): what you see in the headset, saved as a PNG for debugging and sharing.

A press (`request`) only sets a flag. The overlay's draw handler (overlay.draw_and_capture, region 'XR', POST_VIEW) calls
`capture` AFTER our own drawing, once, on the first eye it draws: it reads back the bound framebuffer (scene, desk,
panels, hands, lasers, hover glow; Blender draws nothing after a POST_VIEW callback except what composes the eyes onto the
headset surface). The PNG is encoded and written by a worker thread (zlib lets go of the GIL; written as <name>.part and renamed, so a quit never leaves a broken PNG), so the headset frame only
pays for the readback. "Saved <name>" shows only when the thread is done (`poll`). No Image data-block is made. The file name, folder and desk notice are Snapshot's
(camera_preview.output_file / saved_notice). Zero cost while nothing is asked: one bool test per eye."""
import os
import threading
import time

import numpy as np

from . import camera_preview, desk_qol_math as math_
from .desk_qol_math import png_bytes

WANTED = False
WRITING = []     # [(path, name, started)] of files a worker thread is still writing
_DONE = {}       # path -> True / False, set by the worker thread (a dict item set is atomic; no bpy there)
LAST = {"ms": 0.0, "size": (0, 0), "path": "", "error": ""}    # tests / debugging: the last capture


def request():
    """The button: take a screenshot at the next headset frame. Needs a running draw handler (the desk being open)."""
    global WANTED
    WANTED = True
    return True


def _write(path, rgba):
    """Worker thread: write to a temp name, then rename over the reserved (empty) file; delete the temp on failure."""
    temp = path + ".part"
    try:
        data = png_bytes(rgba)
        with open(temp, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
        _DONE[path] = True
    except Exception as error:      # a full disk etc.
        LAST["error"] = str(error)
        print(f"digits_vr: screenshot write failed: {error}")
        for leftover in (temp, path):
            try:
                os.remove(leftover)
            except OSError:
                pass
        _DONE[path] = False


def poll():
    """Cheap, on the main thread (overlay.draw_and_capture, only while a write runs): show the result of finished writes."""
    for entry in WRITING[:]:
        path, name, _started = entry
        if path in _DONE:
            WRITING.remove(entry)
            if _DONE.pop(path):
                camera_preview.saved_notice(name, time.perf_counter())
            else:
                math_.NOTICE.show("Screenshot failed", time.perf_counter())


def capture():
    """Called at the end of the XR draw handler while WANTED: read this eye's framebuffer, hand it to a writer thread."""
    global WANTED
    import gpu
    WANTED = False
    started = time.perf_counter()
    path = ""
    try:
        x, y, width, height = gpu.state.viewport_get()
        pixels = np.asarray(gpu.state.active_framebuffer_get().read_color(x, y, width, height, 4, 0, 'UBYTE'))
        rgba = pixels.reshape(height, width, 4)[::-1].copy()    # bottom-up -> top-down
        rgba[:, :, 3] = 255
        path, name = camera_preview.output_file("-vr")
        open(path, "xb").close()                                 # reserve the name (a second press can't take it)
    except Exception as error:      # a GPU problem: a message, not an error in the draw handler
        print(f"digits_vr: screenshot failed: {error}")
        math_.NOTICE.show("Screenshot failed", started)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
        return
    WRITING.append((path, name, started))
    threading.Thread(target=_write, args=(path, rgba), daemon=True).start()
    LAST.update(size=(width, height), path=path, error="", ms=(time.perf_counter() - started) * 1000.0)
