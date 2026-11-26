# SPDX-License-Identifier: GPL-3.0-or-later
"""The Screenshot button (View and File tabs): what one eye sees in the headset, saved as a PNG for debugging and sharing.

A press (`request`) only sets a flag. The overlay's draw handler (overlay.draw_and_capture, region 'XR', POST_VIEW) calls
`capture` AFTER our own drawing, once, on the first eye it draws. Blender runs that callback with its OVERLAY layer bound
(draw_context.cc: `overlay_fb`), not the scene's colour: that layer holds Blender's XR overlays (floor grid, extras) and
everything we draw (desk, panels, hands, gun, lasers, glow), premultiplied, transparent elsewhere; the headset gets the
two laid together later, where Python cannot reach. Reading only that layer gave pictures with no scene, and see-through
things (belt slots, panel backs) solid (2026-11-26). So `capture` reads the layer's centre square (eye_crop) plus the
eye's view and projection; the next session tick (`tick`) draws the scene from exactly those matrices off-screen
(camera_preview.render_pixels, with the headset's shading and no desktop overlays: never inside the XR draw), lays the
layer over it (desk_qol_math.over) and a worker thread writes the PNG (zlib lets go of the GIL; written as <name>.part
and renamed, so a quit never leaves a broken PNG). "Saved <name>" shows only when the thread is done (`poll`). No Image
data-block is made. The file name, folder and desk notice are Snapshot's (camera_preview.output_file / saved_notice).
Zero cost while nothing is asked: one bool test per eye, one None test per tick."""
import os
import threading
import time

import numpy as np

from . import camera_preview, desk_qol_math as math_
from .context_helper import view3d_override
from .desk_qol_math import png_bytes

WANTED = False
WRITING = []     # [(path, name, started)] of files a worker thread is still writing
PENDING = []     # [Eye] read in the headset's draw, waiting for the session tick to add the scene
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


class Eye:
    """One eye's overlay layer (bottom row first, premultiplied) with the matrices it was drawn with (cropped)."""
    __slots__ = ("overlay", "view", "projection", "started")

    def __init__(self, overlay, view, projection, started):
        self.overlay, self.view, self.projection, self.started = overlay, view, projection, started


def _failed(started, error, path=""):
    print(f"digits_vr: screenshot failed: {error}")
    math_.NOTICE.show("Screenshot failed", started)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _read_eye():
    """In the XR draw: (overlay pixels of the crop, view matrix, eye projection, (x, y, size), (width, height))."""
    import gpu
    x, y, width, height = gpu.state.viewport_get()
    projection = gpu.matrix.get_projection_matrix().copy()
    crop = math_.eye_crop(projection, width, height)
    crop_x, crop_y, size = crop
    pixels = gpu.state.active_framebuffer_get().read_color(x + crop_x, y + crop_y, size, size, 4, 0, 'UBYTE')
    return np.asarray(pixels).reshape(size, size, 4), gpu.matrix.get_model_view_matrix().copy(), projection, crop, (width, height)


def capture():
    """Called at the end of the XR draw handler while WANTED: keep this eye's overlay layer and matrices for `tick`."""
    global WANTED
    WANTED = False
    started = time.perf_counter()
    try:
        overlay, view, projection, crop, (width, height) = _read_eye()
    except Exception as error:      # a GPU problem: a message, not an error in the draw handler
        _failed(started, error)
        return
    PENDING[:] = [Eye(overlay, view, math_.crop_projection(projection, crop, width, height), started)]
    LAST.update(size=(crop[2], crop[2]), ms=(time.perf_counter() - started) * 1000.0)


def tick(context):
    """Session tick, between headset frames: draw the scene for a captured eye, lay its overlay over it and hand the
    picture to a writer thread. Without a 3D View (or when the scene draw fails) the overlay alone is saved."""
    if not PENDING:
        return
    eye = PENDING.pop()
    size = eye.overlay.shape[0]
    scene = None
    override = view3d_override(context)
    try:
        if override is not None:
            scene = camera_preview.render_pixels(context, override, eye.view, eye.projection, size, size,
                                                 look=context.window_manager.xr_session_settings.shading)
    except Exception as error:      # no GPU / context problem: the overlay alone is still worth keeping
        print(f"digits_vr: screenshot without the scene: {error}")
    note = "" if scene is not None else "no scene"
    rgba = math_.over(eye.overlay, np.zeros_like(eye.overlay) if scene is None else scene)[::-1].copy()   # bottom-up -> top-down
    path = ""
    try:
        path, name = camera_preview.output_file("-vr")
        open(path, "xb").close()                                 # reserve the name (a second press can't take it)
    except Exception as error:
        _failed(eye.started, error, path)
        return
    WRITING.append((path, name, eye.started))
    threading.Thread(target=_write, args=(path, rgba), daemon=True).start()
    LAST.update(path=path, error=note)


def clear():
    """Session over: a press not yet shot, or an eye not yet finished, must not fire in the next session."""
    global WANTED
    WANTED = False
    PENDING.clear()
