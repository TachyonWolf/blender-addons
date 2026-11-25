# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws a floating panel in the headset (one PanelRenderer per panel). Called by panels.draw() once per eye, only
while the panel is open (closed = zero cost: no work, no offscreen).

The body is rendered with `blf` + flat rects into ONE GPUOffScreen per panel, only when something changed (dirty
flag), inside the draw callback (the only place an offscreen can be bound, A15). Each eye then draws one textured quad
(plain IMAGE shader: the eye output takes the colours as they are, spike B), the handle quads and the hover
highlights, all from the panel's single matrix. Colours are shown as-is (sRGB values)."""
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import asset_draw, help_art, help_layout, panel_layout as layout
from .panel_layout import rgba as _rgba

HOVER_COLOUR = _rgba(layout.ACCENT)          # a lit edge (R7)
PRESS_COLOUR = (1.0, 1.0, 1.0, 0.3)          # a pressed fill
HANDLE_HOVER = (0.85, 0.95, 1.0, 1.0)
LIFT = 0.0008                      # metres: highlights sit this far in front of the screen (no z-fight)
FONT = 0

_flat = _image = _smooth = None


def _shaders():
    global _flat, _image, _smooth
    if _flat is None:
        _flat = gpu.shader.from_builtin('UNIFORM_COLOR')
        _image = gpu.shader.from_builtin('IMAGE')
        _smooth = gpu.shader.from_builtin('SMOOTH_COLOR')
    return _flat, _image, _smooth


# ---------------------------------------------------------------------------
# The body texture (pixel space, top-left origin; GL wants bottom-left: y is flipped by the body height)
# ---------------------------------------------------------------------------

def _fan(points, colour, height):
    """Triangles of a convex outline (pixel space, top-left origin) as bottom-left GL pixel coordinates, each vertex
    coloured by `colour` (a tuple, or a function of the pixel y for gradients)."""
    count = len(points)
    centre_x, centre_y = sum(point[0] for point in points) / count, sum(point[1] for point in points) / count
    centre = (centre_x, height - centre_y)
    flipped = [(x, height - y) for x, y in points]
    positions = []
    for index in range(count):
        positions += (centre, flipped[index], flipped[(index + 1) % count])
    if callable(colour):
        centre_colour, point_colours = colour(centre_y), [colour(y) for _x, y in points]
        colours = []
        for index in range(count):
            colours += (centre_colour, point_colours[index], point_colours[(index + 1) % count])
    elif isinstance(colour[0], tuple):       # a radial fade (a glow): centre colour, rim colour
        centre_colour, rim_colour = colour
        colours = [centre_colour, rim_colour, rim_colour] * count
    else:
        colours = [colour] * (3 * count)
    return positions, colours


def _shapes(rects, height):
    """(positions, colours) for a TRIS batch of rounded (x, y, w, h, radius, colour) rects."""
    positions, colours = [], []
    for x, y, w, h, radius, colour in rects:
        segments = 8 if radius >= 20 else 4          # round knobs, pips and pills stay round
        more_positions, more_colours = _fan(layout.rounded_outline(x, y, w, h, radius, segments), colour, height)
        positions += more_positions
        colours += more_colours
    return positions, colours


def _tone(code, widget, alpha=1.0):
    """A palette colour, faded into the ground when the widget is disabled (the mock-ups' 38 % opacity)."""
    colour = _rgba(code, alpha)
    return colour if widget.enabled else layout.mix(colour, _rgba(layout.GROUND), layout.DISABLED_MIX)


TAB_FILL = layout.mix(_rgba(layout.NAVY_TOP), _rgba(layout.NAVY_BOTTOM), 0.18)


def corner_radius(widget):
    """Rounded corners: pills for tabs, the frame's own radius for pop-ups."""
    if widget.kind == layout.TAB:
        return widget.h / 2
    if widget.kind == layout.POPUP:
        return widget.value or 14
    return layout.RADIUS


def _switch(widget):
    """(x, y, w, h) of a toggle's switch at its right end (smaller on narrow toggles)."""
    small = widget.w < 260 or widget.h < 52
    width, height = (52, 30) if small else (64, 34)
    padding = 12 if small else 18
    return widget.x + widget.w - padding - width, widget.y + (widget.h - height) / 2, width, height


def _toggle_rects(widget):
    x, y, w, h, r = widget.x, widget.y, widget.w, widget.h, layout.RADIUS
    on = widget.active
    rects = [(x, y, w, h, r, _tone(layout.ACCENT if on else layout.EDGE, widget)),
             (x + 2, y + 2, w - 4, h - 4, r - 2, _tone(layout.TOGGLE_ON_FILL if on else layout.FILL, widget))]
    sx, sy, sw, sh = _switch(widget)
    knob = sh - 8
    rects.append((sx, sy, sw, sh, sh / 2, _tone(layout.SWITCH_ON if on else layout.SWITCH_OFF, widget)))
    knob_x = sx + sw - 4 - knob if on else sx + 4
    if on and widget.enabled:      # the green pip and its glow (a radial fade: centre colour, rim colour)
        glow = knob / 2 + 12
        centre_x, centre_y = knob_x + knob / 2, sy + sh / 2
        rects.append((centre_x - glow, centre_y - glow, 2 * glow, 2 * glow, glow,
                      (_rgba(layout.PIP, 0.75), _rgba(layout.PIP, 0.0))))
    rects.append((knob_x, sy + 4, knob, knob, knob / 2, _tone(layout.PIP if on else layout.KNOB_OFF, widget)))
    return rects


def _slider_track(widget):
    """(x, y, w) of a slider's track (10 px high, 10 px above the bottom edge, as the mock-ups lay it out)."""
    return widget.x + 22, widget.y + widget.h - 20, widget.w - 44


def _slider_rects(widget):
    x, y, w, h, r = widget.x, widget.y, widget.w, widget.h, layout.RADIUS
    track_x, track_y, track_w = _slider_track(widget)
    fraction = min(1.0, max(0.0, layout.slider_fraction(widget)))
    knob_x = track_x + fraction * track_w
    return [(x, y, w, h, r, _tone(layout.EDGE, widget)), (x + 2, y + 2, w - 4, h - 4, r - 2, _tone(layout.FILL_DIM, widget)),
            (track_x, track_y, track_w, 10, 5, _tone(layout.TRACK, widget)),
            (track_x, track_y, max(10, knob_x - track_x), 10, 5, _tone(layout.ACCENT, widget)),
            (knob_x - 13, track_y - 8, 26, 26, 13, _tone(layout.KNOB, widget))]


def _dashes(x, y, w, h, colour, dash=10, gap=6, thick=2):
    """A dashed rectangle outline as small rects."""
    rects = []
    for start in range(0, int(w), dash + gap):
        length = min(dash, w - start)
        rects += [(x + start, y, length, thick, 0, colour), (x + start, y + h - thick, length, thick, 0, colour)]
    for start in range(0, int(h), dash + gap):
        length = min(dash, h - start)
        rects += [(x, y + start, thick, length, 0, colour), (x + w - thick, y + start, thick, length, 0, colour)]
    return rects


def widget_rects(widget):
    """Rounded rects of one widget: (x, y, w, h, radius, colour), colour = rgba, f(y) or (centre, rim) for a glow."""
    x, y, w, h = widget.x, widget.y, widget.w, widget.h
    r = layout.RADIUS
    kind = widget.kind
    if kind == layout.THUMB:       # a tile: edge, face, and a dim square under the thumbnail
        thumb_x, thumb_y, thumb_w, thumb_h = asset_draw.thumb_rect(widget)
        return [(x, y, w, h, r, _rgba(layout.EDGE)), (x + 2, y + 2, w - 4, h - 4, r - 2, _rgba(layout.FILL_DIM)),
                (thumb_x, thumb_y, thumb_w, thumb_h, 8, _rgba(layout.FILL))]
    if kind == layout.BUTTON:      # raised: a dark shadow below, an edge, the face (pale blue when on)
        face = layout.ACCENT if widget.active else layout.BUTTON_FACE
        return [(x, y + 7, w, h, r, _tone(layout.BUTTON_SHADOW, widget)), (x, y, w, h, r, _tone(layout.LEDGE_EDGE, widget)),
                (x + 2, y + 2, w - 4, h - 4, r - 2, _tone(face, widget))]
    if kind == layout.CARD and widget.color:       # a colour swatch; the chosen one: a white edge in a blue ring
        if widget.active:
            return [(x - 3, y - 3, w + 6, h + 6, r + 3, _rgba(layout.ACCENT)), (x, y, w, h, r, _rgba(layout.TEXT)),
                    (x + 3, y + 3, w - 6, h - 6, r - 3, _rgba(widget.color))]
        return [(x, y, w, h, r, _rgba(widget.color))]
    if kind in (layout.MODE, layout.TAB, layout.CARD, layout.DROPDOWN):
        r = corner_radius(widget)
        if widget.active:
            colour = layout.ACTIVE if kind == layout.MODE else layout.ACCENT
            return [(x, y, w, h, r, _tone(colour, widget))]
        edge = layout.TAB_EDGE if kind == layout.TAB else layout.EDGE
        fill = TAB_FILL if kind == layout.TAB else _rgba(layout.FILL)
        if not widget.enabled:
            fill = layout.mix(fill, _rgba(layout.GROUND), layout.DISABLED_MIX)
        return [(x, y, w, h, r, _tone(edge, widget)), (x + 2, y + 2, w - 4, h - 4, r - 2, fill)]
    if kind == layout.TOGGLE:
        return _toggle_rects(widget)
    if kind == layout.SLIDER:
        return _slider_rects(widget)
    if kind == layout.BACKDROP:
        return [(x, y, w, h, 0, layout.BACKDROP_COLOUR)]
    if kind == layout.POPUP:
        r = corner_radius(widget)
        return [(x, y + 18, w, h, r, (0.0, 0.0, 0.0, 0.35)), (x, y, w, h, r, _rgba(layout.ACCENT)),
                (x + 3, y + 3, w - 6, h - 6, r - 3, _rgba(layout.POPUP_FILL))]
    if kind == layout.SLOT:
        return _dashes(x, y, w, h, _rgba(layout.LEDGE_EDGE))
    if kind == layout.LABEL and widget.style == layout.DIVIDE:
        return [(x, y, w, h, 0, _rgba(layout.DIVIDER))]
    if kind == layout.LABEL and widget.style == help_layout.BOX:
        return [(x, y, w, h, r, _rgba(layout.ACCENT)), (x + 2, y + 2, w - 4, h - 4, r - 2, _rgba(layout.FILL))]
    if kind == layout.LABEL and widget.style == layout.STAT:
        return [(x, y, w, h, r, _rgba(layout.DIVIDER)), (x + 2, y + 2, w - 4, h - 4, r - 2, _rgba(layout.FILL_DIM))]
    return []


LABEL_COLOURS = {layout.SECTION: layout.SECTION_TEXT, layout.HINT: layout.HINT_TEXT, layout.WARN: layout.WARN_TEXT,
                 layout.GOOD: layout.GOOD_TEXT, layout.NOTICE: layout.NOTICE_TEXT, layout.TITLE: layout.TEXT,
                 'note': layout.NOTE_TEXT, 'centre': layout.TEXT, 'pager': layout.TEXT, 'right': layout.TEXT}
CENTRED = ('note', layout.NOTICE, 'centre', 'pager')


def _wrap(text, width):
    """Words broken into lines no wider than `width` (blf's current size)."""
    lines, current = [], ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if current and blf.dimensions(FONT, trial)[0] > width:
            lines.append(current)
            current = word
        else:
            current = trial
    return lines + [current]


def _put(text, x, baseline, colour):
    blf.color(FONT, *colour)
    blf.position(FONT, x, baseline, 0)
    blf.draw(FONT, text)


def _baseline(height, centre_y, size):
    """GL baseline of text of `size` centred on pixel row `centre_y` (top-left origin)."""
    return height - centre_y - size * 0.36


def _draw_label(widget, height):
    style = widget.style
    if style in (layout.DIVIDE, help_layout.LINE, help_layout.ART):
        return
    if style == help_layout.BOX:   # a control: its name (drawn twice, 0.7 px apart: blf has no bold) and a small dim line
        blf.size(FONT, widget.size)
        title = _baseline(height, widget.y + widget.h * 0.32, widget.size)
        for shift in (0.0, 0.7):
            _put(widget.label, widget.x + 14 + shift, title, _rgba(layout.TEXT))
        blf.size(FONT, 19)
        _put(widget.detail, widget.x + 14, _baseline(height, widget.y + widget.h * 0.73, 19), _rgba(layout.HINT_TEXT))
        return
    if style == layout.STAT:       # a big value and its caption
        blf.size(FONT, 36)
        _put(widget.label, widget.x + 18, _baseline(height, widget.y + widget.h * 0.38, 36), _rgba(layout.ACCENT))
        blf.size(FONT, 24)
        _put(widget.detail, widget.x + 18, _baseline(height, widget.y + widget.h * 0.72, 24), _rgba(layout.HINT_TEXT))
        return
    colour = _rgba(LABEL_COLOURS.get(style, layout.ACCENT))
    blf.size(FONT, widget.size)
    line_height = widget.size * 1.2
    lines = _wrap(widget.label, widget.w) if widget.h >= 1.9 * widget.size else [widget.label]
    first = widget.y + widget.h / 2 - (len(lines) - 1) * line_height / 2
    for number, line in enumerate(lines):
        x = widget.x
        if style in CENTRED:
            x += (widget.w - blf.dimensions(FONT, line)[0]) / 2
        elif style == 'right':
            x += widget.w - blf.dimensions(FONT, line)[0]
        _put(line, x, _baseline(height, first + number * line_height, widget.size), colour)


def _draw_text(widget, height):
    kind = widget.kind
    if kind == layout.THUMB:       # drawn with the thumbnails (asset_draw.draw_tiles)
        return
    if kind == layout.LABEL:
        _draw_label(widget, height)
        return
    if not widget.label:
        return
    blf.size(FONT, widget.size)
    centre_y = widget.y + widget.h / 2
    if kind == layout.SLIDER:
        track_y = _slider_track(widget)[1]
        header = (widget.y + track_y) / 2 + 1
        baseline = _baseline(height, header, widget.size)
        _put(widget.label, widget.x + 22, baseline, _tone(layout.TEXT, widget))
        value_text = widget.text or f"{widget.value:.{widget.decimals}f} {widget.unit}".rstrip()
        text_width = blf.dimensions(FONT, value_text)[0]
        _put(value_text, widget.x + widget.w - 22 - text_width, baseline, _tone(layout.ACCENT, widget))
        return
    on_accent = widget.active and kind in (layout.MODE, layout.TAB, layout.CARD, layout.DROPDOWN, layout.BUTTON)
    colour = _tone(layout.TEXT_ON_ACCENT if on_accent else layout.TEXT, widget)
    if kind == layout.TOGGLE:
        small = _switch(widget)[0] - widget.x < 200 or widget.h < 52
        x = widget.x + (12 if small else 18)
        baseline = _baseline(height, centre_y, widget.size)
        _put(widget.label, x, baseline, colour)
        if widget.detail:
            label_width = blf.dimensions(FONT, widget.label + " ")[0]
            blf.size(FONT, 24)
            _put(widget.detail, x + label_width, _baseline(height, centre_y, 24), _tone(layout.HINT_TEXT, widget))
        return
    if kind == layout.DROPDOWN:
        baseline = _baseline(height, centre_y, widget.size)
        _put(widget.label, widget.x + 20, baseline, colour)
        if widget.caret:          # the arrows come from a fallback font: ▼ draws large, ▸ / ▾ small
            caret_size = round(widget.size * (0.7 if widget.caret == "▼" else 1.5))
            blf.size(FONT, caret_size)
            caret_width = blf.dimensions(FONT, widget.caret)[0]
            _put(widget.caret, widget.x + widget.w - 20 - caret_width, _baseline(height, centre_y, caret_size), colour)
        return
    if widget.detail:              # a card with a sub line (the Grab mode cards)
        text_width = blf.dimensions(FONT, widget.label)[0]
        _put(widget.label, widget.x + (widget.w - text_width) / 2, _baseline(height, centre_y - 13, widget.size), colour)
        blf.size(FONT, 22)
        detail_width = blf.dimensions(FONT, widget.detail)[0]
        _put(widget.detail, widget.x + (widget.w - detail_width) / 2, _baseline(height, centre_y + 20, 22), colour)
        return
    text_width = blf.dimensions(FONT, widget.label)[0]
    x = widget.x + 20 if widget.style == 'left' else widget.x + (widget.w - text_width) / 2
    _put(widget.label, x, _baseline(height, centre_y, widget.size), colour)


def _colour_draw(shader, batch, colour):
    """A flat batch with the UNIFORM_COLOR shader already bound."""
    shader.uniform_float("color", colour)
    batch.draw(shader)


def _draw_flat(batch, colour):
    _flat.bind()
    _flat.uniform_float("color", colour)
    batch.draw(_flat)


class PanelRenderer:
    """One panel's GPU side: its offscreen, quad, handle and highlight batches. `body` is a function returning the
    body's rounded rects (x, y, w, h, radius, colour or f(y)), drawn under the widgets."""

    def __init__(self, spec, body):
        self.spec, self.body = spec, body
        self.offscreen = None
        self.widgets, self.by_id, self.handles = [], {}, []
        self.dirty = True
        self.screen_batch = None
        self.handle_batches = {}               # handle id -> (edge, face)
        self.highlight_batches = {}            # widget id -> batch (cleared when the layout changes)
        self.frame_matrix = None
        self.shape_batches = {}                # layer -> (key, batch): rounded shapes, kept while the rects stay the same
        self.renders = 0                       # how many times the body was rendered (tests: it must stay low)

    def set_widgets(self, widgets):
        """New layout (the model changed): redraw the body on the next frame."""
        self.widgets = list(widgets)
        self.by_id = {widget.id: widget for widget in self.widgets}
        self.handles = [widget for widget in self.widgets if widget.kind == layout.HANDLE]
        self.highlight_batches.clear()
        self.dirty = True

    def free(self):
        """Drop the GPU objects (panel closed or session over); they are made again on the next open."""
        if self.offscreen is not None:
            self.offscreen.free()
        self.offscreen, self.screen_batch, self.frame_matrix = None, None, None
        self.shape_batches.clear()
        self.handle_batches.clear()
        self.highlight_batches.clear()

    def _layers(self):
        """The widgets split into layers: the page, then each open pop-up (it starts at its backdrop)."""
        layers, current = [], []
        for widget in self.widgets:
            if widget.kind == layout.BACKDROP and current:
                layers.append(current)
                current = []
            current.append(widget)
        return layers + [current]

    def _render(self):
        """Draw the whole body into the offscreen. Only inside a draw callback. Each layer draws its shapes, then its
        text, so a pop-up covers the page's text too."""
        flat, image, smooth = _shaders()
        width, height = self.spec.width, self.spec.height
        if self.offscreen is None:
            self.offscreen = gpu.types.GPUOffScreen(width, height)
        has_tiles = any(widget.kind == layout.THUMB for widget in self.widgets)
        waiting = asset_draw.sync_textures() if has_tiles else 0
        layers = self._layers()
        batches = []
        for number, widgets in enumerate(layers):
            rects = list(self.body()) if number == 0 else []
            for widget in widgets:
                rects.extend(widget_rects(widget))
            batches.append(self._shape_batch(number, rects, height, smooth))
        viewport, blend, depth = gpu.state.viewport_get(), gpu.state.blend_get(), gpu.state.depth_test_get()
        with self.offscreen.bind():
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))     # outside the rounded body: clear
            # push_pop() saves only the model-view matrix: the projection needs its own push, or the eye's projection
            # stays replaced by this flat one for the rest of that eye's frame (a white flash over the view on every
            # click, 2026-11-24)
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix(((2 / width, 0, 0, -1), (0, 2 / height, 0, -1),
                                                          (0, 0, -1, 0), (0, 0, 0, 1))))
                gpu.state.depth_test_set('NONE')
                for number, (widgets, batch) in enumerate(zip(layers, batches)):
                    gpu.state.blend_set('ALPHA')         # glows and the pop-up backdrop are see-through
                    batch.draw(smooth)
                    if number == 0 and has_tiles:
                        asset_draw.draw_tiles(widgets, image, _rgba)
                    help_art.draw(widgets, flat, image, height)
                    gpu.state.blend_set('ALPHA')
                    for widget in widgets:
                        if widget.kind != layout.HANDLE and (widget.label or widget.kind == layout.LABEL):
                            _draw_text(widget, height)
        gpu.state.viewport_set(*viewport)
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
        self.dirty = waiting > 0            # thumbnails still waiting for their upload: render again next frame
        self.renders += 1

    def _shape_batch(self, number, rects, height, smooth):
        """Layer `number`'s rounded shapes as one batch, made again only when a rect changed: a render for new text
        alone (the Speed tab's stats, a renamed spot) reuses it (building the triangles took ~2-5 ms in VR).
        A gradient (a function of y) is keyed by its name: frame_rects makes the same one for the same size."""
        key = (height, tuple(rect if not callable(rect[5]) else rect[:5] + (rect[5].__qualname__,) for rect in rects))
        kept = self.shape_batches.get(number)
        if kept is None or kept[0] != key:
            positions, colours = _shapes(rects, height)
            kept = (key, batch_for_shader(smooth, 'TRIS', {"pos": positions, "color": colours}))
            self.shape_batches[number] = kept
        return kept[1]

    # -----------------------------------------------------------------------
    # In the headset
    # -----------------------------------------------------------------------

    def _local_points(self, points, lift=0.0):
        return [(*self.spec.pixel_to_local(px, py), lift) for px, py in points]

    def _quad(self, shader, x, y, w, h):
        corners = self._local_points(((x, y + h), (x + w, y + h), (x + w, y), (x, y)))
        return batch_for_shader(shader, 'TRI_FAN', {"pos": corners, "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})

    def _rounded_batch(self, rects, lift):
        """One TRIS batch of rounded (x, y, w, h, radius) rects in panel-local metres."""
        triangles = []
        for x, y, w, h, radius in rects:
            points = layout.rounded_outline(x, y, w, h, radius)
            centre = (x + w / 2, y + h / 2)
            for index, point in enumerate(points):
                triangles += self._local_points((centre, point, points[(index + 1) % len(points)]), lift)
        return batch_for_shader(_flat, 'TRIS', {"pos": triangles})

    def _ring_batch(self, widget, thickness=3):
        """A lit edge round a widget (the hover look of the mock-ups), in panel-local metres."""
        x, y, w, h, radius = widget.x, widget.y, widget.w, widget.h, corner_radius(widget)
        outer = layout.rounded_outline(x, y, w, h, radius)
        inner = layout.rounded_outline(x + thickness, y + thickness, w - 2 * thickness, h - 2 * thickness,
                                       max(1, radius - thickness))
        triangles = []
        for index in range(len(outer)):
            following = (index + 1) % len(outer)
            triangles += self._local_points((outer[index], outer[following], inner[index]), LIFT)
            triangles += self._local_points((inner[index], outer[following], inner[following]), LIFT)
        return batch_for_shader(_flat, 'TRIS', {"pos": triangles})

    def _highlight(self, widget_id, pressed):
        """(hover ring or press fill) batch of a widget, made once per layout."""
        key = (widget_id, pressed)
        if key not in self.highlight_batches:
            widget = self.by_id.get(widget_id)
            if widget is None:
                batch = None
            elif pressed:
                batch = self._rounded_batch([(widget.x, widget.y, widget.w, widget.h, corner_radius(widget))], LIFT)
            else:
                batch = self._ring_batch(widget)
            self.highlight_batches[key] = batch
        return self.highlight_batches[key]

    def _all_handles(self):
        """(edge, face) batches of every handle together (kept until the layout or the GPU objects go)."""
        if "*" not in self.handle_batches:
            parts = [part for widget in self.handles for part in layout.handle_parts(widget, self.spec.width)]
            grown = [(x + 5, y + 5, w - 10, h - 10, max(2, radius - 4)) for x, y, w, h, radius in parts]
            self.handle_batches["*"] = (self._rounded_batch(parts, 0.0), self._rounded_batch(grown, LIFT / 2))
        return self.handle_batches["*"]

    def _handle_batches_for(self, widget):
        """(blue edge batch, grey face batch): a rounded bar with two short arms joining the body edge."""
        if widget.id not in self.handle_batches:
            parts = layout.handle_parts(widget, self.spec.width)
            edge = self._rounded_batch(parts, 0.0)
            grown = [(x + 5, y + 5, w - 10, h - 10, max(2, radius - 4)) for x, y, w, h, radius in parts]
            self.handle_batches[widget.id] = (edge, self._rounded_batch(grown, LIFT / 2))
        return self.handle_batches[widget.id]

    def draw(self, state, new_frame):
        """One eye's panel. `new_frame` = first eye of a headset frame (the matrix is worked out once per frame)."""
        if not state.open or not self.widgets:
            return
        flat, image, _smooth_shader = _shaders()
        if self.dirty or self.offscreen is None:
            self._render()
        if self.screen_batch is None:
            self.screen_batch = self._quad(image, 0, 0, self.spec.width, self.spec.height)
        if new_frame or self.frame_matrix is None:
            self.frame_matrix = state.matrix()
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.matrix.push()
        try:
            gpu.matrix.multiply_matrix(self.frame_matrix)
            image.bind()
            image.uniform_sampler("image", self.offscreen.texture_color)
            self.screen_batch.draw(image)
            flat.bind()                     # once: the handles and highlights only change the colour
            grabbed = {grab.handle_id for grab in state.grabs.values()} if state.grabs else ()
            hovered = set(state.hover.values()) if state.hover else ()
            if self.handles and not grabbed and not any(widget.id in hovered for widget in self.handles):
                edge, face = self._all_handles()        # the usual case: every handle in two draws
                _colour_draw(flat, edge, _rgba(layout.ACCENT))
                _colour_draw(flat, face, _rgba(layout.GRIP_GREY))
            else:
                for widget in self.handles:
                    edge, face = self._handle_batches_for(widget)
                    _colour_draw(flat, edge, _rgba(layout.ACTIVE) if widget.id in grabbed else _rgba(layout.ACCENT))
                    _colour_draw(flat, face, HANDLE_HOVER if widget.id in hovered else _rgba(layout.GRIP_GREY))
            for hand, widget_id in state.hover.items():
                widget = self.by_id.get(widget_id)
                if widget is None or widget.kind in layout.NO_HIGHLIGHT or not widget.enabled:
                    continue
                pressed = state.pressed.get(hand) == widget_id
                batch = self._highlight(widget_id, pressed)
                if batch:
                    _colour_draw(flat, batch, PRESS_COLOUR if pressed else HOVER_COLOUR)
        finally:
            gpu.matrix.pop()
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
