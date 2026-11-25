# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-frame cost tracking (Q1 budget: idle < 0.5 ms, dragging < 2 ms, Python only). Pure Python.
Each callback runs inside `with TIMINGS.measure("name"):`; tests read p95 from TIMINGS.summary()."""
import time
from collections import deque

SAMPLES = 600


FRAME_PARTS = ('tick', 'draw', 'depsgraph')   # the callbacks Blender calls; everything else runs inside them
FPS_WINDOW = 60
FRAME_GAP = 0.003   # s: two draw calls further apart than this belong to different headset frames


class Timings:
    """Named timing samples, plus "frame": all measured Python time between two headset frames (the Q1 number).
    The overlay's draw callback marks frames (it runs once per eye, back to back)."""

    def __init__(self, size=SAMPLES):
        self.size = size
        self.samples = {}
        self._frame_ms = 0.0
        self._last_draw = None
        self._parts, self.slow_frames = [], []
        self.frame_times = deque(maxlen=FPS_WINDOW)     # start time of each headset frame

    def measure(self, name):
        """with TIMINGS.measure("tick"): ... (a plain class, cheaper than a generator context manager)"""
        return _Measure(self, name)

    def add(self, name, milliseconds):
        self.samples.setdefault(name, deque(maxlen=self.size)).append(milliseconds)
        if name in FRAME_PARTS:      # top-level callbacks only: nested measures (pick, drag) are inside "tick"
            self._frame_ms += milliseconds
            self._parts.append((name, round(milliseconds, 3)))

    def frame_mark(self, now=None):
        """Call at the start of each draw callback: closes the previous frame's total on a new frame. Returns True
        for the first eye of a new frame."""
        now = time.perf_counter() if now is None else now
        new_frame = self._last_draw is None or now - self._last_draw > FRAME_GAP
        if new_frame and self._last_draw is not None:
            self.samples.setdefault("frame", deque(maxlen=self.size)).append(self._frame_ms)
            self.slow_frames.append((round(self._frame_ms, 3), self._parts))
            self.slow_frames = sorted(self.slow_frames, reverse=True)[:6]
            self._frame_ms = 0.0
        if new_frame:
            self._parts = []
            self.frame_times.append(now)
        self._last_draw = now
        return new_frame

    def fps(self, now=None):
        """Headset frames per second over the last FPS_WINDOW frames (draw callbacks, first eye of each); 0 when no
        frame came in the last second."""
        now = time.perf_counter() if now is None else now
        if len(self.frame_times) < 3 or now - self.frame_times[-1] > 1.0:
            return 0.0
        return (len(self.frame_times) - 1) / (self.frame_times[-1] - self.frame_times[0])

    def clear(self):
        self.frame_times.clear()
        self.samples.clear()
        self._frame_ms = 0.0
        self._last_draw = None
        self._parts, self.slow_frames = [], []

    def summary(self):
        """{name: {"count", "p50", "p95", "max"}} in milliseconds."""
        return {name: percentiles(values) for name, values in self.samples.items() if values}


def percentiles(values):
    ordered = sorted(values)
    def at(fraction):
        return ordered[min(len(ordered) - 1, int(fraction * (len(ordered) - 1) + 0.5))]
    return {"count": len(ordered), "p50": at(0.5), "p95": at(0.95), "max": ordered[-1]}


class _Measure:
    __slots__ = ("timings", "name", "start")

    def __init__(self, timings, name):
        self.timings, self.name = timings, name

    def __enter__(self):
        self.start = time.perf_counter()

    def __exit__(self, *_exc):
        self.timings.add(self.name, (time.perf_counter() - self.start) * 1000.0)
        return False


TIMINGS = Timings()
