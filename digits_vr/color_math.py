# SPDX-License-Identifier: GPL-3.0-or-later
"""The colour of the VR colour picker, without bpy: a Colour (hue, saturation, value, alpha; the way Blender's picker
shows it), its RGB and '#rrggbb' forms, and the channels the sliders edit in RGB and HSV mode. Colours are display
(sRGB) values; the material's linear colour comes from gpencil_math.linear_rgb. Tested headless."""
import colorsys
from dataclasses import dataclass, replace

RGB, HSV = 'RGB', 'HSV'
# mode -> ((channel, label), ...); alpha is in both
CHANNELS = {RGB: (('r', "R"), ('g', "G"), ('b', "B"), ('a', "A")), HSV: (('h', "H"), ('s', "S"), ('v', "V"), ('a', "A"))}
# channel -> (maximum, unit) of the slider (the minimum is 0): R G B 0..255, H in degrees, S V A in percent
RANGES = {'r': (255, ""), 'g': (255, ""), 'b': (255, ""), 'h': (360, "°"), 's': (100, "%"), 'v': (100, "%"), 'a': (100, "%")}


@dataclass(frozen=True)
class Colour:
    h: float = 0.0      # 0..1
    s: float = 0.0
    v: float = 0.0
    a: float = 1.0

    @property
    def rgb(self):
        return colorsys.hsv_to_rgb(self.h, self.s, self.v)

    @property
    def code(self):
        return "#%02x%02x%02x" % tuple(round(part * 255) for part in self.rgb)

    def get(self, channel):
        """The channel as its slider shows it (RANGES)."""
        if channel in 'rgb':
            return round(self.rgb['rgb'.index(channel)] * 255)
        return round(self._unit(channel) * RANGES[channel][0])

    def _unit(self, channel):
        return {'h': self.h, 's': self.s, 'v': self.v, 'a': self.a}[channel]

    def with_channel(self, channel, value):
        """This colour with one slider channel set (`value` in the slider's range). Hue and saturation are kept when a grey
        or black RGB edit has none."""
        fraction = min(1.0, max(0.0, value / RANGES[channel][0]))
        if channel in 'hsva':
            return replace(self, **{channel: fraction})
        rgb = list(self.rgb)
        rgb['rgb'.index(channel)] = fraction
        return self.with_rgb(rgb)

    def with_rgb(self, rgb):
        h, s, v = colorsys.rgb_to_hsv(*rgb)
        return replace(self, h=h if s > 1e-6 and v > 1e-6 else self.h, s=s if v > 1e-6 else self.s, v=v)


def from_code(code, alpha=1.0):
    """The Colour of a '#rrggbb' (or 'rrggbb' / '#rgb'; any case); None when `code` is not a colour."""
    text = code.strip().lstrip('#')
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6 or any(char not in "0123456789abcdefABCDEF" for char in text):
        return None
    return Colour(a=alpha).with_rgb([int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4)])
