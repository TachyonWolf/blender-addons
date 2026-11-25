# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared by every floating panel (desk, tool options, viewpoints, later the tool gun menu): the panel's size in
pixels (PanelSpec), the Widget type and kinds, the palette, hit-testing, sliders and the rounded-rect geometry.
Pure Python (no bpy), tested headless.

Pixel space: origin top-left, x right, y down, spec.width x spec.height. Handles sit just outside the body (x < 0 or
x > width). Panel-local metres (scale 1): x right, y up, z out of the screen, origin at the middle of the body."""
import functools
import math
from dataclasses import dataclass

RADIUS = 9                                  # rounded corners of buttons and cards
BEZEL = 5                                   # the pale blue frame around a screen
METERS_PER_PIXEL = 0.00045                  # every panel: 1000 px = 45 cm at scale 1

ACCENT = "#7fd0ff"                  # pale blue: panel accents
ACTIVE = "#ffb36b"                  # orange: the active mode, a held handle
NAVY_TOP, NAVY_BOTTOM = "#132333", "#0d1824"
FILL, FILL_DIM, FILL_PRESSED = "#1d3a52", "#15283a", "#2f6a94"
TEXT, TEXT_DIM, TEXT_ON_ACCENT = "#e6f4ff", "#5c7387", "#0d1824"
LEDGE, LEDGE_EDGE, BUTTON_FACE, BUTTON_SHADOW = "#1b2f43", "#3d6a8c", "#2f6a94", "#0a141e"
GRIP_GREY = "#c9d3de"
# the redesign (docs/redesign/*.dc.html): edges, toggles with a green pip, sections, hints, pop-ups
EDGE, TAB_EDGE = "#2c5373", "#5e7a92"
TOGGLE_ON_FILL, SWITCH_OFF, SWITCH_ON, KNOB_OFF = "#24506f", "#3a4a5a", "#0d1824", "#cfd8e3"
PIP = "#4ddf6a"                     # the green pip of a toggle that is on (user, 2026-11-25), with a glow
SECTION_TEXT, HINT_TEXT, DIVIDER, NOTE_TEXT = "#8fb1cb", "#9fbad0", "#223d55", "#8fb1cb"
POPUP_FILL, TRACK, KNOB = "#18304a", "#2d4459", "#e6f4ff"
WARN_TEXT, GOOD_TEXT, NOTICE_TEXT = "#ffd2a6", "#9fe0b0", "#ffd98a"
GROUND = "#10202d"                  # what a disabled widget fades into (the mock-ups: 38 % opacity)
DISABLED_MIX = 0.62
BACKDROP_COLOUR = (6 / 255, 12 / 255, 18 / 255, 0.45)

# widget kinds
BUTTON, MODE, TAB, CARD, TOGGLE, SLIDER, HANDLE, LABEL, THUMB = ('BUTTON', 'MODE', 'TAB', 'CARD', 'TOGGLE', 'SLIDER',
                                                                 'HANDLE', 'LABEL', 'THUMB')
DROPDOWN = 'DROPDOWN'       # a card with its value and a caret (▼ list below, ▸ pop-up); active = open
BACKDROP = 'BACKDROP'       # a pop-up's dark veil over the whole panel: a press on it closes the pop-up
POPUP = 'POPUP'             # a pop-up's frame: hit (so presses on it do nothing), drawn over the page
SLOT = 'SLOT'               # an empty dashed place for a later control (not hit)
# label styles (LABEL widgets: drawn only, never hit)
PLAIN, SECTION, HINT, WARN, GOOD, NOTICE, TITLE, DIVIDE, STAT = ('', 'section', 'hint', 'warn', 'good', 'notice',
                                                                 'title', 'divider', 'stat')
NOT_HIT = (LABEL, SLOT)
NO_HIGHLIGHT = (LABEL, SLOT, HANDLE, BACKDROP, POPUP)
LEFT_HANDLE, RIGHT_HANDLE = "handle_left", "handle_right"
HANDLE_WIDTH, HANDLE_GAP = 70, 16           # a side handle: its width, and its gap to the body


@dataclass(frozen=True)
class PanelSpec:
    """A panel's body in pixels, and how big it may get (scale relative to your size)."""
    width: int
    height: int
    scale_range: tuple = (0.5, 2.5)
    meters_per_pixel: float = METERS_PER_PIXEL

    def pixel_to_local(self, px, py):
        return (px - self.width / 2) * self.meters_per_pixel, (self.height / 2 - py) * self.meters_per_pixel

    def local_to_pixel(self, x, y):
        return x / self.meters_per_pixel + self.width / 2, self.height / 2 - y / self.meters_per_pixel

    def on_body(self, px, py):
        return 0 <= px <= self.width and 0 <= py <= self.height


@dataclass(frozen=True)
class Widget:
    id: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    label: str = ""
    action: tuple = ()          # what a press does, e.g. ("mode", "EDIT"); () = nothing
    enabled: bool = True
    active: bool = False        # selected tab / mode / card, toggle on
    value: float = 0.0          # slider position (real units)
    minimum: float = 0.0
    log: bool = False           # slider: positions are logarithmic (for ranges like 2 m to 1000 m)
    maximum: float = 1.0
    size: int = 38              # text size in pixels
    unit: str = "cm"            # slider: shown after the value
    step: float = 0.5           # slider: values snap to multiples of this
    decimals: int = 1           # slider: digits shown after the point
    color: str = ""             # swatch: the colour it shows (hex)
    style: str = ""             # LABEL: PLAIN / SECTION / HINT / WARN / GOOD / NOTICE / TITLE / DIVIDE / STAT;
                                # BUTTON: "flat" = a plain card-like face
    detail: str = ""            # a second, dimmer text: a card's sub line, a toggle's "(type)", a stat's caption
    caret: str = ""             # DROPDOWN: "▼" (a list below) or "▸" (a pop-up)
    text: str = ""              # SLIDER: shown instead of the value (e.g. "Blender's (120 m)")

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@functools.lru_cache(maxsize=256)
def hex_rgb(code):
    return tuple(int(code[index:index + 2], 16) / 255.0 for index in (1, 3, 5))


@functools.lru_cache(maxsize=512)
def rgba(code, alpha=1.0):
    """(r, g, b, a) of a '#rrggbb' code; cached (panels ask for the same few colours every eye)."""
    return (*hex_rgb(code), alpha)


def row(prefix, items, x, y, total_width, height, gap, make):
    """One horizontal row of equal widgets."""
    width = (total_width - gap * (len(items) - 1)) / len(items)
    return [make(index, item, x + index * (width + gap), y, width, height) for index, item in enumerate(items)]


def label(identifier, text, x, y, w=976, size=34):
    return Widget(identifier, LABEL, x, y, w, size + 8, label=text, size=size)


def section(identifier, text, x, y, w=976):
    """A small upper-case group title (drawn only)."""
    return Widget(identifier, LABEL, x, y, w, 28, label=text.upper(), size=24, style=SECTION)


def hint(identifier, text, x, y, w=976, h=28, style=HINT, size=24):
    """A dim help line (wrapped to `w` when long; give the height of two lines then)."""
    return Widget(identifier, LABEL, x, y, w, h, label=text, size=size, style=style)


def divider(identifier, x, y, w=976):
    return Widget(identifier, LABEL, x, y, w, 2, style=DIVIDE)


def popup(prefix, x, y, w, h, close_action, body, radius=14):
    """The two widgets that start a pop-up layer: the backdrop over the whole body (`body` = (width, height); a press
    on it = `close_action`) and the frame."""
    return [Widget(prefix + "_backdrop", BACKDROP, 0, 0, body[0], body[1], action=close_action),
            Widget(prefix + "_frame", POPUP, x, y, w, h, value=radius)]


def grid(prefix, items, x, y, total_width, columns, height, make, gap_x=16, gap_y=12):
    """Items in a grid of `columns` equal cells, row by row (like the mock-ups' g2 / g3 / g4)."""
    width = (total_width - gap_x * (columns - 1)) / columns
    return [make(index, item, x + (index % columns) * (width + gap_x), y + (index // columns) * (height + gap_y),
                 width, height) for index, item in enumerate(items)]


def side_handle(side, panel_width, y, h):
    """A grip bar just outside the body on the left or right side."""
    if side == 'LEFT':
        return Widget(LEFT_HANDLE, HANDLE, -HANDLE_WIDTH - HANDLE_GAP, y, HANDLE_WIDTH, h, action=("handle",))
    return Widget(RIGHT_HANDLE, HANDLE, panel_width + HANDLE_GAP, y, HANDLE_WIDTH, h, action=("handle",))


PIN_ID = "pin"
PIN_SIZE = (96, 44)                         # the Pin toggle in a panel's top right corner


def pin_widget(panel_width, pinned):
    """The Pin toggle every pinnable panel gets (panel.py adds it): lit when the panel is pinned to your body."""
    return Widget(PIN_ID, BUTTON, panel_width - PIN_SIZE[0] - 22, 12, PIN_SIZE[0], PIN_SIZE[1], label="Pin",
                  action=("pin",), active=pinned, size=26)


def frame_rects(width, height):
    """The plain panel body: a pale blue bezel round a navy screen. (x, y, w, h, radius, colour or f(y))."""
    top, bottom = rgba(NAVY_TOP), rgba(NAVY_BOTTOM)
    gradient = lambda y: mix(top, bottom, min(1.0, max(0.0, y / height)))      # noqa: E731
    return [(0, 0, width, height, 16, rgba(ACCENT, 0.85)),
            (BEZEL, BEZEL, width - 2 * BEZEL, height - 2 * BEZEL, 12, gradient)]


def mix(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def hit_test(widgets, px, py):
    """The topmost widget under a screen point, or None. Labels and slots are not hit. An open pop-up's backdrop
    covers the whole panel, so nothing under it is hit."""
    for widget in reversed(widgets):
        if widget.kind not in NOT_HIT and widget.contains(px, py):
            return widget
    return None


SCULPT_SIZE_RANGE_CM = (0.5, 200.0)      # the brush Size slider (desk Tools page and Tool options)


def slider_value(widget, px, padding=22):
    """Slider value for a pixel x (the track runs between the widget's padded edges)."""
    track_start, track_end = widget.x + padding, widget.x + widget.w - padding
    fraction = min(1.0, max(0.0, (px - track_start) / (track_end - track_start)))
    if widget.log:
        return float(f"{widget.minimum * (widget.maximum / widget.minimum) ** fraction:.2g}")   # 2 digits: 2.5, 31, 120
    value = widget.minimum + fraction * (widget.maximum - widget.minimum)
    return round(value / widget.step) * widget.step


def slider_fraction(widget):
    if widget.log:
        value = min(widget.maximum, max(widget.minimum, widget.value))
        return math.log(value / widget.minimum) / math.log(widget.maximum / widget.minimum)
    return (widget.value - widget.minimum) / (widget.maximum - widget.minimum)


def rounded_outline(x, y, w, h, radius, segments=4):
    """Corner points (pixel space, clockwise from the top-left) of a rounded rectangle, for fans and outlines."""
    radius = min(radius, w / 2, h / 2)
    points = []
    for corner_x, corner_y, start in ((x + radius, y + radius, 180), (x + w - radius, y + radius, 270),
                                      (x + w - radius, y + h - radius, 0), (x + radius, y + h - radius, 90)):
        for step in range(segments + 1):
            angle = math.radians(start + 90.0 * step / segments)
            points.append((corner_x + radius * math.cos(angle), corner_y + radius * math.sin(angle)))
    return points


def handle_parts(widget, panel_width):
    """Rects (x, y, w, h, radius) of a grip bar: the bar and two short arms joining the body edge."""
    on_left = widget.x < 0
    edge = 0 if on_left else panel_width
    arm_x = widget.x + widget.w - 2 if on_left else edge - 2
    arm_width = abs(edge - (widget.x + widget.w)) + 4 if on_left else widget.x - edge + 4
    arm_offset = min(36, widget.h / 4)
    return [(widget.x, widget.y, widget.w, widget.h, 22),
            (arm_x, widget.y + arm_offset, arm_width, 30, 6), (arm_x, widget.y + widget.h - arm_offset - 30, arm_width, 30, 6)]
