"""After a capture: look at the written PNGs and flag maps that came out wrong or empty.

A value map is compared with what the AOV injection expects from the materials:
- every material gives the same constant (e.g. Specular 0.5 everywhere, Sheen 0): the map should be
  that value; a uniform map that matches is fine, one that doesn't is flagged
- materials use different constants (e.g. one metal part, the rest 0): flagged only when the map
  is all 0 although some material is non-zero (the non-zero part may be tiny or hidden)
- some material feeds the value from nodes (textures, ramps): any result can be right, but a map
  that is (nearly) all 0 gets a "check" note
Light maps (beauty, matte, albedo...) and masks are flagged when empty.
"""
import os

import bpy
import numpy as np

from . import maps

EMPTY = 1.5 / 255      # brightest 1% of the subject below this = (nearly) empty
MATCH = 0.02           # allowed difference from the expected constant (raw maps)
OPTIONAL_LIGHT = {"emission"}  # may be empty: the model just doesn't glow


def expectations(results):
    """{aov key: ('constant', value) | ('nodes', None)} from aov_inject.inject() results."""
    out = {}
    for key, (_input, kind) in maps.AOVS.items():
        if any(r["found"].get(key) == "socket" for r in results):
            out[key] = ("nodes", None)
            continue
        values = {_scalar(r["consts"][key], kind) for r in results if key in r["consts"]}
        out[key] = ("constant", values.pop() if len(values) == 1 else None) if values else ("constant", 0.0)
    return out


def _scalar(value, kind):
    if kind == "COLOR":
        return round(float(sum(value[:3]) / 3), 3)
    return round(float(value), 3)


def image_stats(path):
    """(mean, brightest-1% value, max, subject pixel count) of a PNG's red channel, inside its alpha."""
    image = bpy.data.images.load(path, check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        width, height = image.size
        pixels = np.empty(width * height * image.channels, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        channels = image.channels
        pixels = pixels.reshape(-1, channels)
    finally:
        bpy.data.images.remove(image)
    inside = pixels[:, 3] > 0.5 if channels == 4 and pixels[:, 3].min() < 0.5 else slice(None)
    values = pixels[inside, 0] if channels < 3 else pixels[inside, :3].max(axis=1)
    if values.size == 0:
        return 0.0, 0.0, 0.0, 0
    return float(values.mean()), float(np.percentile(values, 99)), float(values.max()), int(values.size)


def check(directory, wanted, results):
    """[(map, level, text)] with level 'bad' (broken / suspicious) or 'check' (look, may be fine)."""
    expected = expectations(results)
    nonzero = {key: any(_scalar(r["consts"][key], kind) > MATCH for r in results if key in r["consts"])
               for key, (_input, kind) in maps.AOVS.items()}
    flags = []
    for name in wanted:
        path = os.path.join(directory, name + ".png")
        if not os.path.exists(path):
            flags.append((name, "bad", "file missing"))
            continue
        mean, top, peak, count = image_stats(path)
        if count == 0:
            flags.append((name, "bad", "no subject pixels (empty alpha)"))
            continue
        empty = top < EMPTY
        if name in maps.AOVS:
            how, value = expected[name]
            kind = maps.AOVS[name][1]
            if how == "nodes":
                if empty:
                    flags.append((name, "check", "(nearly) all 0, while the materials feed it from nodes "
                                                 "(textures / ramps): can be right, e.g. very smooth or "
                                                 "non-metal materials; compare with the shader"))
            elif value is None:  # different constants: a small non-zero part (claws, trim) is enough
                if peak < EMPTY and nonzero[name]:
                    flags.append((name, "check", "all 0, while some material has a non-zero constant"))
            elif kind == "VALUE" and abs(mean - value) > MATCH and not (empty and value < MATCH):
                flags.append((name, "bad", f"mean {mean:.3f} does not match the materials' value {value:.3f}"))
        elif empty and name not in OPTIONAL_LIGHT:
            flags.append((name, "bad", "(nearly) empty"))
    return flags
