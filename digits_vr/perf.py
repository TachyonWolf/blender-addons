# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-frame cost tracking (Q1 budget: idle < 0.5 ms, dragging < 2 ms, Python only). Pure Python.
Each callback runs inside `with TIMINGS.measure("name"):`; tests read p95 from TIMINGS.summary()."""
import time
from collections import deque

SAMPLES = 600


FRAME_PARTS = ('tick', 'draw', 'depsgraph')   # the callbacks Blender calls; everything else runs inside them
FPS_WINDOW = 60
SLOW_KEPT = 6       # slowest frames kept (with their parts) for the test logs
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
        samples = self.samples.get(name)
        if samples is None:
            samples = self.samples[name] = deque(maxlen=self.size)
        samples.append(milliseconds)
        if name in FRAME_PARTS:      # top-level callbacks only: nested measures (pick, drag) are inside "tick"
            self._frame_ms += milliseconds
            self._parts.append((name, milliseconds))

    def add_native(self, name, milliseconds):
        """Time Blender itself spent inside our callbacks (a sculpt stroke): reported on its own, not in "frame"."""
        self.add(name, milliseconds)
        self._frame_ms -= milliseconds

    def frame_mark(self, now=None):
        """Call at the start of each draw callback: closes the previous frame's total on a new frame. Returns True
        for the first eye of a new frame. Runs twice per headset frame: kept to a few plain operations."""
        now = time.perf_counter() if now is None else now
        last = self._last_draw
        self._last_draw = now
        if last is not None and now - last <= FRAME_GAP:
            return False
        if last is not None:
            self.add("frame", self._frame_ms)
            slow = self.slow_frames
            if len(slow) < SLOW_KEPT or self._frame_ms > slow[-1][0]:     # keep the slowest few, sorted
                slow.append((round(self._frame_ms, 3), [(name, round(ms, 3)) for name, ms in self._parts]))
                slow.sort(reverse=True)
                del slow[SLOW_KEPT:]
            self._frame_ms = 0.0
        self._parts = []
        self.frame_times.append(now)
        return True

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
