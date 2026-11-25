# SPDX-License-Identifier: GPL-3.0-or-later
"""The numbers on the desk's Performance tab. Recomputed at most twice a second (REFRESH_SECONDS), so the screen
(which redraws only when a value changes) and the Python cost stay small. The triangle count is cached: a recount
starts from the Recount button or when the last one is older than RECOUNT_SECONDS, and runs in slices of
SLICE_MS per refresh, so it never stalls a headset frame."""
import time

import bpy

from . import desk_layout as layout, modifier_policy, modifier_state, perf_state
from .perf import TIMINGS

REFRESH_SECONDS = 0.5
RECOUNT_SECONDS = 10.0
SLICE_MS = 2.0


class TriangleCount:
    """Evaluated triangles of the visible mesh objects, counted a slice at a time."""

    def __init__(self):
        self.total = -1             # -1 = never counted
        self.finished_at = None
        self._queue = None          # object names still to count
        self._running_total = 0

    def request(self):
        self.finished_at = None     # a recount starts at the next step

    def step(self, context, now):
        if self._queue is None:
            if self.finished_at is not None and now - self.finished_at < RECOUNT_SECONDS:
                return
            self._queue = [ob.name for ob in context.scene.objects if ob.type == 'MESH' and ob.visible_get()]
            self._running_total = 0
        depsgraph = context.evaluated_depsgraph_get()
        deadline = time.perf_counter() + SLICE_MS / 1000.0
        while self._queue and time.perf_counter() < deadline:
            ob = bpy.data.objects.get(self._queue.pop())
            if ob is not None:
                self._running_total += len(ob.evaluated_get(depsgraph).data.loop_triangles)
        if not self._queue:
            self.total, self.finished_at, self._queue = self._running_total, now, None


TRIANGLES = TriangleCount()
_cache = {"view": layout.PerfView(), "at": -1e9}


def reset():
    TRIANGLES.__init__()
    _cache.update(view=layout.PerfView(), at=-1e9)


def recount():
    TRIANGLES.request()
    _cache["at"] = -1e9


def _heavy_counts(scene):
    """(heavy modifiers VR turned off, heavy modifiers on in the viewport)"""
    off = len(modifier_state.viewport_modifiers.recorded(scene, modifier_state.RECORD_KEY))
    on = sum(1 for ob in scene.objects for mod in ob.modifiers
             if mod.type in modifier_policy.HEAVY_TYPES and mod.show_viewport)
    return off, on


def view(context):
    """The PerfView for the desk (cached for REFRESH_SECONDS)."""
    now = time.perf_counter()
    if now - _cache["at"] < REFRESH_SECONDS:
        return _cache["view"]
    _cache["at"] = now
    TRIANGLES.step(context, now)
    scene, eevee = context.scene, context.scene.eevee
    shading = context.window_manager.xr_session_settings.shading
    heavy_off, heavy_on = _heavy_counts(scene)
    frame = TIMINGS.summary().get("frame")
    _cache["view"] = layout.PerfView(
        fps=int(round(TIMINGS.fps(now))), python_p95=round(frame["p95"], 2) if frame else 0.0,
        triangles=TRIANGLES.total, counting=TRIANGLES._queue is not None, heavy_off=heavy_off, heavy_on=heavy_on,
        raytracing=eevee.use_raytracing, shadow_scale=round(eevee.shadow_resolution_scale, 2),
        taa_samples=eevee.taa_samples, compositor=shading.use_compositor, objects_hidden=perf_state.hidden_count(scene),
        draw_distance=round(context.window_manager.xr_session_settings.clip_end, 1))
    return _cache["view"]
