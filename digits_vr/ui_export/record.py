# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the add-on's real panel renderer (panel_draw.PanelRenderer) with recording stand-ins for Blender's GPU and text
modules, so the page draws exactly what the headset draws: every rounded shape as panel_draw tessellates it, every text
with its place, size and colour, every icon quad with its atlas corners and tint, in the renderer's own order.

Coordinates come out in panel pixels (top-left origin, y down); colours as panel_draw gives them (0..1 rgba)."""
import importlib
import sys
import types

import numpy as np

from addon_import import load

OPTICAL_PER_SIZE = 0.75             # blf sets the font's optical size (opsz axis) to the size in points: 0.75 x pixels.
                                    # Fitted to blf.dimensions in Blender 5.3 (mean error < 1 px over 81 samples).


class Face:
    """blf's default face (Blender's variable Inter) for text widths: one static instance per optical size, made on demand.
    Without a font file (the coverage check may run without one) every character is 0.55 em wide."""

    def __init__(self, path=None):
        self.path, self.instances, self.glyphs = path, {}, {}
        if path:
            from fontTools.ttLib import TTFont
            self.axes = {axis.axisTag: axis for axis in TTFont(path)["fvar"].axes}

    def optical(self, size):
        """The opsz value blf uses for a text size (within the font's range), rounded to 0.25."""
        axis = self.axes["opsz"]
        return round(min(axis.maxValue, max(axis.minValue, size * OPTICAL_PER_SIZE)) * 4) / 4

    def instance(self, optical):
        """(static font, {character: (advance, ink left, ink right) in em units}, units per em) at an optical size."""
        if optical not in self.instances:
            from fontTools.ttLib import TTFont
            from fontTools.varLib import instancer
            font = TTFont(self.path)
            location = {tag: axis.defaultValue for tag, axis in self.axes.items()}
            font = instancer.instantiateVariableFont(font, {**location, "opsz": optical})
            self.instances[optical] = (font, {}, font["head"].unitsPerEm)
        return self.instances[optical]

    def _glyphs(self, optical):
        """(font, glyph set at that optical size, {character: metrics})."""
        if optical not in self.glyphs:
            from fontTools.ttLib import TTFont
            font = TTFont(self.path)
            location = {tag: axis.defaultValue for tag, axis in self.axes.items()}
            self.glyphs[optical] = (font, font.getGlyphSet(location={**location, "opsz": optical}), {})
        return self.glyphs[optical]

    def _metrics(self, optical, character):
        """(advance, ink left, ink right) in font units, read from the variable font at the location (no instancing:
        instancing a whole font takes seconds, the few characters a layout uses take milliseconds)."""
        font, glyph_set, cache = self._glyphs(optical)
        if character not in cache:
            name = font.getBestCmap().get(ord(character))
            if name is None:                    # drawn by a fallback font: an average width
                cache[character] = (0.6 * font["head"].unitsPerEm, None, None)
            else:
                from fontTools.pens.boundsPen import BoundsPen
                pen = BoundsPen(glyph_set)
                glyph_set[name].draw(pen)
                bounds = pen.bounds
                cache[character] = (glyph_set[name].width, *((bounds[0], bounds[2]) if bounds else (None, None)))
        return cache[character]

    def width(self, text, size):
        """blf.dimensions' width: the ink box of the line (first ink to last ink), no kerning."""
        if not self.path:
            return 0.55 * size * len(text)
        optical = self.optical(size)
        units = self._glyphs(optical)[0]["head"].unitsPerEm
        pen, left, right = 0.0, None, None
        for character in text:
            advance, low, high = self._metrics(optical, character)
            if low is not None:
                left = pen + low if left is None else min(left, pen + low)
                right = pen + high if right is None else max(right, pen + high)
            pen += advance
        return 0.0 if left is None else (right - left) * size / units


FACE = Face()


class Recording:
    """What the stand-ins saw: `events` in draw order. `height` flips GL rows back to pixel rows (None = no flip)."""

    def __init__(self):
        self.events, self.height = [], None
        self.size, self.colour, self.place, self.line_width = 11, (1, 1, 1, 1), (0, 0), 1.0
        self.textures = {}               # texture name -> (height, width, 4) uint8, bottom row first

    def point(self, x, y):
        return (x, self.height - y) if self.height is not None else (x, y)

    def emit(self, event):
        self.events.append(event)


REC = Recording()


# ---- blf --------------------------------------------------------------------------------------------------------------

def _blf_module():
    blf = types.ModuleType("blf")
    blf.size = lambda _font, size: setattr(REC, "size", size)
    blf.color = lambda _font, *colour: setattr(REC, "colour", tuple(colour))
    blf.position = lambda _font, x, y, _z=0: setattr(REC, "place", (x, y))
    blf.dimensions = lambda _font, text: (FACE.width(text, REC.size), REC.size * 0.75)
    blf.draw = lambda _font, text: REC.emit(("text", text, *REC.point(*REC.place), REC.size, REC.colour))
    for name in ("enable", "disable", "shadow", "shadow_offset", "word_wrap", "clipping", "rotation", "aspect"):
        setattr(blf, name, lambda *_arguments: None)
    blf.ROTATION, blf.CLIPPING, blf.SHADOW, blf.WORD_WRAP = 1, 2, 4, 128
    return blf


# ---- gpu --------------------------------------------------------------------------------------------------------------

class Texture:
    def __init__(self, pixels):
        self.name = "texture_%d" % len(REC.textures)
        REC.textures[self.name] = pixels

    def filter_mode(self, _linear):
        pass


class Shader:
    def __init__(self, name):
        self.name, self.uniforms = name, {}

    def bind(self):
        pass

    def uniform_float(self, name, value):
        self.uniforms[name] = tuple(value) if hasattr(value, "__len__") else value

    def uniform_sampler(self, name, value):
        self.uniforms[name] = value


class ShapeRef:
    """panel_draw._shapes' output: the rounded rects of one layer, each tessellated by the real _shapes on its own."""

    def __init__(self, fans):
        self.fans = fans


class Batch:
    def __init__(self, _shader, kind, attributes):
        self.kind, self.attributes = kind, attributes

    def draw(self, shader):
        positions = self.attributes.get("pos")
        if isinstance(positions, ShapeRef):
            REC.emit(("shapes", positions.fans))
            return
        points = [REC.point(*point[:2]) for point in positions]
        texture = shader.uniforms.get("image")
        if "texCoord" in self.attributes:
            name = texture.name if isinstance(texture, Texture) else "body"
            REC.emit(("image", name, self.kind, points, [tuple(uv) for uv in self.attributes["texCoord"]],
                      shader.uniforms.get("color", (1.0, 1.0, 1.0, 1.0)) if shader.name == 'IMAGE_COLOR' else (1.0, 1.0, 1.0, 1.0)))
        elif "color" in self.attributes:
            REC.emit(("smooth", points, [tuple(colour) for colour in self.attributes["color"]]))
        elif self.kind == 'LINES':
            REC.emit(("lines", points, shader.uniforms.get("color"), REC.line_width))
        else:
            REC.emit(("tris", points, shader.uniforms.get("color")))


def _batch_module():
    module = types.ModuleType("gpu_extras.batch")
    module.batch_for_shader = Batch
    return module


# ---- images read through bpy ------------------------------------------------------------------------------------------

class _Image:
    """bpy.data.images.load(path): size and pixels (floats, bottom row first), read with PIL."""

    def __init__(self, path):
        from PIL import Image
        picture = Image.open(path).convert("RGBA").transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        self.size = picture.size
        values = np.asarray(picture, dtype=np.float32).reshape(-1) / 255.0
        self.pixels = types.SimpleNamespace(foreach_get=lambda target: target.__setitem__(slice(None), values))


def install():
    """Put the stand-ins in place and load the draw modules. Returns panel_draw."""
    sys.modules["blf"] = _blf_module()
    importlib.import_module("gpu_extras")
    sys.modules["gpu_extras.batch"] = _batch_module()
    gpu = importlib.import_module("gpu")
    gpu.state.line_width_set = lambda width: setattr(REC, "line_width", width)
    bpy = importlib.import_module("bpy")
    bpy.app.background = False
    bpy.data.images.load = _Image
    bpy.data.images.remove = lambda _image: None
    bpy.context.preferences.themes = []          # Blender's default theme tints (icon_draw._theme_tints)
    panel_draw, icon_draw, help_art, asset_draw = (load(name) for name in ("panel_draw", "icon_draw", "help_art", "asset_draw"))
    asset_draw.texture_from_pixels = Texture
    panel_draw._flat, panel_draw._image, panel_draw._smooth = Shader('UNIFORM_COLOR'), Shader('IMAGE'), Shader('SMOOTH_COLOR')
    icon_draw._state["shader"] = Shader('IMAGE_COLOR')
    icon_draw.load()
    help_art.load()
    for hand, pixels in help_art._pixels.items():
        help_art._textures[hand] = Texture(pixels)
    real_shapes = panel_draw._shapes

    tessellated = {}

    def shapes(rects, height):
        fans = []
        for rect in rects:
            key = (height, *rect[:5], rect[5].__qualname__ if callable(rect[5]) else rect[5])
            if key not in tessellated:
                positions, colours = real_shapes([rect], height)
                tessellated[key] = (key, [(x, height - y) for x, y in positions], [tuple(colour) for colour in colours])
            fans.append(tessellated[key])
        return ShapeRef(fans), None

    panel_draw._shapes = shapes
    return panel_draw


def use_font(path):
    """Text widths from blf's default face at `path` (Blender's Inter.woff2)."""
    global FACE
    FACE = Face(path)


class _State:
    """A PanelState stand-in for PanelRenderer.draw: open, nothing grabbed or pressed, `hover` = {hand: widget id}."""

    def __init__(self, hover=None):
        self.open, self.grabs, self.pressed = True, {}, {}
        self.hover = hover or {}

    def matrix(self):
        return None


def ring_key(panel_draw, widget):
    return (widget.x, widget.y, widget.w, widget.h, panel_draw.corner_radius(widget))


def capture(panel_draw, spec, body, widgets, rings):
    """One screen of a panel: body events (the texture, layer by layer), outside events (handles, Pin, as the headset
    draws them around the body) and outside events with each handle hovered. `rings` (ring_key -> (hover ring, press
    fill) triangles in pixels) gets the widgets' highlights it does not have yet."""
    renderer = panel_draw.PanelRenderer(spec, body)
    renderer.set_widgets(widgets)
    REC.events, REC.height = [], spec.height
    renderer._render()
    inside = REC.events
    renderer._local_points = lambda points, lift=0.0: [tuple(point[:2]) for point in points]
    REC.height = None

    def outside(hover=None):
        REC.events = []
        renderer.draw(_State(hover), True)
        return REC.events

    plain = outside()
    hovered = {widget.id: outside({"hand": widget.id}) for widget in renderer.handles}
    for widget in widgets:
        key = ring_key(panel_draw, widget)
        if key in rings:
            continue
        REC.events = []
        for pressed in (False, True):
            renderer._highlight(widget.id, pressed).draw(panel_draw._flat)
        rings[key] = [event[1] for event in REC.events]
    return inside, plain, hovered
