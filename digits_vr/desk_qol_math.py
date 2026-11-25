# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure helpers of the desk QoL batch (no bpy; tested headless): the camera preview's refresh rule and framing, the
recenter pose, the failsafe list, and the short desk message."""
import math

from mathutils import Vector

try:
    from . import move_math
except ImportError:      # imported flat by the headless pure tests
    import move_math

PREVIEW_SIZE = (320, 180)            # the one offscreen, made once
PREVIEW_INTERVAL = 0.1               # s: at most 10 renders a second
PREVIEW_RECT = (684, -204, 320, 180)  # pixels in the desk texture: above the screen, right side (x, y, w, h)
NO_CAMERA = "No camera in the scene"
RECENTER_SECONDS, FAILSAFE_SECONDS = 2.0, 6.0
NOTICE_SECONDS = 4.0

# What the failsafe sets: VR-only settings through the existing settings (their listeners write the VR records).
# "paused" is set only when the Pause setting exists (another branch).
FAILSAFE_SETTINGS = {"hide_heavy_modifiers": True, "raytracing_off_in_vr": True,   # raytracing Off also hides glass
                     "compositor_off_in_vr": True, "always_laser": True, "paused": False}
FAILSAFE_NOTE = "Failsafe settings on"
RECENTER_NOTE = "Recentered"


SNAPSHOT_WIDTH = 1920
SNAPSHOT_FOLDER = "~/Pictures"


def snapshot_size(resolution_x, resolution_y, pixel_aspect_x=1.0, pixel_aspect_y=1.0, width=SNAPSHOT_WIDTH):
    """(width, height) of a snapshot: `width` wide, the render resolution's aspect."""
    aspect = (resolution_x * pixel_aspect_x) / max(1e-6, resolution_y * pixel_aspect_y)
    return width, max(1, round(width / aspect))


def snapshot_name(stem, stamp, taken=()):
    """File name '<blend name>-<date-time>.png' (untitled files: 'untitled'); a taken name gets -2, -3, ... (never overwrites)."""
    base = f"{stem or 'untitled'}-{stamp}"
    name, number = base + ".png", 1
    while name in taken:
        number += 1
        name = f"{base}-{number}.png"
    return name


def should_refresh(now, last, changed, interval=PREVIEW_INTERVAL):
    """Render the preview again only when something changed, and at most every `interval` seconds."""
    return changed and now - last >= interval


def fit_scales(camera_aspect, target_aspect=PREVIEW_SIZE[0] / PREVIEW_SIZE[1]):
    """(x, y) factors for the camera's projection so its WHOLE frame fits a buffer of `target_aspect` (more of the
    world shows beside / above it instead of cropping)."""
    if camera_aspect > target_aspect:
        return 1.0, target_aspect / camera_aspect
    return camera_aspect / target_aspect, 1.0


def facing_angle(head_forward, head, target):
    """The turn (radians, counter-clockwise from above) that makes the head look at `target` level; 0 when the
    target is straight above / below the head or you look straight up / down."""
    wanted = (target[0] - head[0], target[1] - head[1])
    ahead = (head_forward[0], head_forward[1])
    if math.hypot(*wanted) < 1e-4 or math.hypot(*ahead) < 1e-4:
        return 0.0
    angle = math.atan2(wanted[1], wanted[0]) - math.atan2(ahead[1], ahead[0])
    return (angle + math.pi) % (2 * math.pi) - math.pi


def recenter(navigation_location, navigation_rotation, head, head_forward, target, head_height):
    """New (navigation location, rotation): turned about the head to face `target`, then lifted so the head is at
    `head_height` (floor + eye height at your size). The head keeps its place on the floor; your size is untouched."""
    location, rotation = move_math.turn_about(Vector(navigation_location), navigation_rotation, Vector(head),
                                              facing_angle(head_forward, head, target))
    location.z += head_height - head[2]
    return location, rotation


def centre_of(points):
    """The middle of some world points; the world origin when there are none."""
    points = [Vector(point) for point in points]
    return sum(points, Vector()) / len(points) if points else Vector()


class Notice:
    """A short message the desk shows for a few seconds."""

    def __init__(self):
        self.text, self.until = "", 0.0

    def show(self, text, now, seconds=NOTICE_SECONDS):
        self.text, self.until = text, now + seconds

    def current(self, now):
        return self.text if now < self.until else ""


NOTICE = Notice()


def png_bytes(rgba, level=3):
    """PNG file bytes of an (h, w, 4) uint8 array given top row first (pure numpy + zlib)."""
    import struct
    import zlib
    import numpy as np
    height, width = rgba.shape[:2]
    raw = np.zeros((height, 1 + width * 4), np.uint8)       # each row starts with filter type 0
    raw[:, 1:] = rgba.reshape(height, width * 4)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), level)) + chunk(b"IEND", b""))
