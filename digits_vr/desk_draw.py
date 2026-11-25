# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the desk in the headset. Called by overlay.draw() once per eye, only while the desk is open (closed = zero
cost: no handler work, no offscreen).

The screen is rendered with `blf` + flat rects into ONE GPUOffScreen, only when something changed (dirty flag), inside
the draw callback (the only place an offscreen can be bound, A15). Each eye then draws one textured quad (plain IMAGE
shader: the eye output takes the colours as they are, spike B), two handle quads and the hover highlights, all from
the desk's single matrix. Colours are shown as-is (sRGB values)."""
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import asset_draw, desk_layout as layout
from .desk_state import DESK

HOVER_COLOUR = (1.0, 1.0, 1.0, 0.2)
PRESS_COLOUR = (1.0, 1.0, 1.0, 0.4)
HANDLE_HOVER = (0.85, 0.95, 1.0, 1.0)
LIFT = 0.0008                      # metres: highlights sit this far in front of the screen (no z-fight)
FONT = 0

_offscreen = None
_widgets = []
_by_id = {}
_dirty = True
_flat = _image = _smooth = None
_screen_batch = None
_handle_batches = {}               # handle id -> batch
_highlight_batches = {}            # widget id -> batch (cleared when the layout changes)
_frame_matrix = None
renders = 0                        # how many times the screen was rendered (tests: it must stay low)


def set_widgets(widgets):
    """New layout (the model changed): redraw the screen on the next frame."""
    global _widgets, _dirty
    _widgets = list(widgets)
    _by_id.clear()
    _by_id.update({widget.id: widget for widget in _widgets})
    _highlight_batches.clear()
    _dirty = True


def mark_dirty():
    global _dirty
    _dirty = True


def free():
    """Drop the GPU objects (desk closed or session over); they are made again on the next open."""
    global _offscreen, _screen_batch, _frame_matrix
    if _offscreen is not None:
        _offscreen.free()
    _offscreen, _screen_batch, _frame_matrix = None, None, None
    _handle_batches.clear()
    _highlight_batches.clear()
    asset_draw.free()


def _shaders():
    global _flat, _image, _smooth
    if _flat is None:
        _flat = gpu.shader.from_builtin('UNIFORM_COLOR')
        _image = gpu.shader.from_builtin('IMAGE')
        _smooth = gpu.shader.from_builtin('SMOOTH_COLOR')
    return _flat, _image, _smooth


def _rgba(code, alpha=1.0):
    return (*layout.hex_rgb(code), alpha)


# ---------------------------------------------------------------------------
# The screen texture
# ---------------------------------------------------------------------------

def _fan(points, colour):
    """Triangles of a convex outline (pixel space, top-left origin) as bottom-left GL pixel coordinates, each vertex
    coloured by `colour` (a tuple, or a function of the pixel y for gradients)."""
    centre = (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))
    positions, colours = [], []
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        for vertex in (centre, point, following):
            positions.append((vertex[0], layout.DESK_HEIGHT - vertex[1]))
            colours.append(colour(vertex[1]) if callable(colour) else colour)
    return positions, colours


def _shapes(rects):
    """(positions, colours) for a TRIS batch of rounded (x, y, w, h, radius, colour) rects."""
    positions, colours = [], []
    for x, y, w, h, radius, colour in rects:
        more_positions, more_colours = _fan(layout.rounded_outline(x, y, w, h, radius), colour)
        positions += more_positions
        colours += more_colours
    return positions, colours


def _mix(first, second, amount):
    return tuple(a + (b - a) * amount for a, b in zip(first, second))


def _body_rects():
    """The desk: the bezel, the screen with its navy gradient, the desk top (ledge) below it."""
    top, bottom = _rgba(layout.NAVY_TOP), _rgba(layout.NAVY_BOTTOM)
    screen = layout.SCREEN_HEIGHT
    gradient = lambda y: _mix(top, bottom, min(1.0, max(0.0, y / screen)))      # noqa: E731
    ledge_top = screen + 6
    return [(0, 0, layout.DESK_WIDTH, screen, 16, _rgba(layout.ACCENT, 0.85)),          # the thin pale blue bezel
            (layout.BEZEL, layout.BEZEL, layout.DESK_WIDTH - 2 * layout.BEZEL, screen - 2 * layout.BEZEL, 12, gradient),
            (0, ledge_top, layout.DESK_WIDTH, layout.DESK_HEIGHT - ledge_top, 22, _rgba(layout.LEDGE_EDGE)),
            (3, ledge_top + 3, layout.DESK_WIDTH - 6, layout.DESK_HEIGHT - ledge_top - 6, 20, _rgba(layout.LEDGE))]


def _widget_rects(widget):
    """Rounded rects of one widget: border, fill, knobs."""
    accent, fill, dim = _rgba(layout.ACCENT), _rgba(layout.FILL), _rgba(layout.FILL_DIM)
    x, y, w, h = widget.x, widget.y, widget.w, widget.h
    r = layout.RADIUS
    if widget.kind == layout.THUMB:       # a tile: border, face, and a dim square under the thumbnail
        thumb_x, thumb_y, thumb_w, thumb_h = asset_draw.thumb_rect(widget)
        return [(x, y, w, h, r, accent), (x + 2, y + 2, w - 4, h - 4, r - 2, fill),
                (thumb_x, thumb_y, thumb_w, thumb_h, 6, dim)]
    if widget.kind == layout.BUTTON:      # raised: a dark shadow below, the face, a light top edge
        return [(x, y + 6, w, h, r, _rgba(layout.BUTTON_SHADOW)), (x, y, w, h, r, accent),
                (x + 3, y + 3, w - 6, h - 9, r - 2, _rgba(layout.BUTTON_FACE))]
    if widget.kind == layout.CARD and widget.color:       # a colour swatch: the colour in a frame (accent when chosen)
        frame = accent if widget.active else dim
        return [(x, y, w, h, r, frame), (x + 5, y + 5, w - 10, h - 10, r - 2, _rgba(widget.color))]
    if widget.kind in (layout.MODE, layout.TAB, layout.CARD):
        if not widget.enabled:
            return [(x, y, w, h, r, _rgba(layout.TEXT_DIM, 0.6)), (x + 2, y + 2, w - 4, h - 4, r - 2, dim)]
        if widget.active:
            colour = _rgba(layout.ACTIVE) if widget.kind == layout.MODE else accent
            return [(x, y, w, h, r, colour)]
        return [(x, y, w, h, r, accent), (x + 2, y + 2, w - 4, h - 4, r - 2, fill)]
    if widget.kind == layout.TOGGLE:
        rects = [(x, y, w, h, r, fill if widget.enabled else dim)]
        box = (x + w - 58, y + (h - 34) / 2, 34, 34)
        rects += [(*box, 6, accent if widget.enabled else _rgba(layout.TEXT_DIM, 0.6)),
                  (box[0] + 3, box[1] + 3, 28, 28, 4, accent if widget.active else dim)]
        return rects
    if widget.kind == layout.SLIDER:
        track_x, track_w = x + 24, w - 48
        track_y = y + h - 26
        knob_x = track_x + layout.slider_fraction(widget) * track_w
        track_colour = accent if widget.enabled else _rgba(layout.TEXT_DIM)
        return [(x, y, w, h, r, dim), (track_x, track_y, track_w, 8, 4, fill),
                (track_x, track_y, knob_x - track_x, 8, 4, track_colour),
                (knob_x - 9, track_y - 12, 18, 32, 5, _rgba(layout.TEXT if widget.enabled else layout.TEXT_DIM))]
    return []


def _draw_text(widget):
    enabled = widget.enabled
    if widget.kind == layout.THUMB:       # drawn with the thumbnails (asset_draw.draw_tiles)
        return
    blf.size(FONT, widget.size)
    centre_y = layout.DESK_HEIGHT - widget.y - widget.h / 2
    baseline = centre_y - widget.size * 0.32
    if widget.kind in (layout.BUTTON, layout.MODE, layout.TAB, layout.CARD):
        if not enabled:
            colour = _rgba(layout.TEXT_DIM)
        elif widget.kind == layout.BUTTON:
            colour = _rgba(layout.TEXT)
        elif widget.active:
            colour = _rgba(layout.TEXT_ON_ACCENT)
        else:
            colour = _rgba(layout.ACCENT if widget.kind == layout.TAB else layout.TEXT)
        text_width, _height = blf.dimensions(FONT, widget.label)
        position = (widget.x + (widget.w - text_width) / 2, baseline - (3 if widget.kind == layout.BUTTON else 0))
    elif widget.kind == layout.SLIDER:
        blf.color(FONT, *_rgba(layout.TEXT if enabled else layout.TEXT_DIM))
        line = layout.DESK_HEIGHT - widget.y - widget.size - 4
        blf.position(FONT, widget.x + 24, line, 0)
        blf.draw(FONT, widget.label)
        value_text = f"{widget.value:.{widget.decimals}f} {widget.unit}".rstrip()
        text_width, _height = blf.dimensions(FONT, value_text)
        blf.position(FONT, widget.x + widget.w - 24 - text_width, line, 0)
        blf.draw(FONT, value_text)
        return
    else:
        if widget.kind == layout.LABEL:
            colour = _rgba(layout.ACCENT)
        else:
            colour = _rgba(layout.TEXT if enabled else layout.TEXT_DIM)
        position = (widget.x + (18 if widget.kind == layout.TOGGLE else 0), baseline)
    blf.color(FONT, *colour)
    blf.position(FONT, *position, 0)
    blf.draw(FONT, widget.label)


def _render():
    """Draw the whole desk into the offscreen. Only inside a draw callback."""
    global _offscreen, _dirty, renders
    flat, _image_shader, smooth = _shaders()
    width, height = layout.DESK_WIDTH, layout.DESK_HEIGHT
    if _offscreen is None:
        _offscreen = gpu.types.GPUOffScreen(width, height)
    waiting = asset_draw.sync_textures() if _widgets and any(w.kind == layout.THUMB for w in _widgets) else 0
    rects = _body_rects()
    for widget in _widgets:
        rects.extend(_widget_rects(widget))
    positions, colours = _shapes(rects)
    batch = batch_for_shader(smooth, 'TRIS', {"pos": positions, "color": colours})
    with _offscreen.bind():
        gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))     # outside the rounded body: clear
        # push_pop() saves only the model-view matrix: the projection needs its own push, or the eye's projection
        # stays replaced by this flat one for the rest of that eye's frame (a white flash over the view on every
        # click, 2026-11-24)
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_matrix(Matrix.Identity(4))
            gpu.matrix.load_projection_matrix(Matrix(((2 / width, 0, 0, -1), (0, 2 / height, 0, -1),
                                                      (0, 0, -1, 0), (0, 0, 0, 1))))
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
            batch.draw(smooth)
            asset_draw.draw_tiles(_widgets, _image_shader, _rgba)
            for widget in _widgets:
                if widget.label and widget.kind != layout.HANDLE:
                    _draw_text(widget)
    _dirty = waiting > 0            # thumbnails still waiting for their upload: render again next frame
    renders += 1


# ---------------------------------------------------------------------------
# In the headset
# ---------------------------------------------------------------------------

def _local_points(points, lift=0.0):
    return [(*layout.pixel_to_local(px, py), lift) for px, py in points]


def _quad(shader, x, y, w, h, lift=0.0, with_uv=False):
    corners = _local_points(((x, y + h), (x + w, y + h), (x + w, y), (x, y)), lift)
    data = {"pos": corners}
    if with_uv:
        data["texCoord"] = ((0, 0), (1, 0), (1, 1), (0, 1))
    return batch_for_shader(shader, 'TRI_FAN', data)


def _rounded_batch(shader, rects, lift):
    """One TRIS batch of rounded (x, y, w, h, radius) rects in desk-local metres."""
    triangles = []
    for x, y, w, h, radius in rects:
        points = layout.rounded_outline(x, y, w, h, radius)
        centre = (x + w / 2, y + h / 2)
        for index, point in enumerate(points):
            triangles += _local_points((centre, point, points[(index + 1) % len(points)]), lift)
    return batch_for_shader(shader, 'TRIS', {"pos": triangles})


def _highlight(widget_id):
    if widget_id not in _highlight_batches:
        widget = _by_id.get(widget_id)
        _highlight_batches[widget_id] = _rounded_batch(
            _flat, [(widget.x, widget.y, widget.w, widget.h, layout.RADIUS)], LIFT) if widget else None
    return _highlight_batches[widget_id]


def _handle_batches_for(widget):
    """(blue edge batch, grey face batch): a rounded bar with two short arms joining the desk edge."""
    if widget.id not in _handle_batches:
        parts = layout.handle_parts(widget)
        edge = _rounded_batch(_flat, parts, 0.0)
        grown = [(x + 5, y + 5, w - 10, h - 10, max(2, radius - 4)) for x, y, w, h, radius in parts]
        _handle_batches[widget.id] = (edge, _rounded_batch(_flat, grown, LIFT / 2))
    return _handle_batches[widget.id]


def _draw_flat(batch, colour):
    _flat.bind()
    _flat.uniform_float("color", colour)
    batch.draw(_flat)


def draw(new_frame):
    """One eye's desk. `new_frame` = first eye of a headset frame (the desk matrix is worked out once per frame)."""
    global _frame_matrix, _screen_batch
    if not DESK.open or not _widgets:
        return
    flat, image, _smooth_shader = _shaders()
    if _dirty or _offscreen is None:
        _render()
    if _screen_batch is None:
        _screen_batch = _quad(image, 0, 0, layout.DESK_WIDTH, layout.DESK_HEIGHT, with_uv=True)
    if new_frame or _frame_matrix is None:
        _frame_matrix = DESK.matrix()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    with gpu.matrix.push_pop():
        gpu.matrix.multiply_matrix(_frame_matrix)
        image.bind()
        image.uniform_sampler("image", _offscreen.texture_color)
        _screen_batch.draw(image)
        grabbed = {grab.handle_id for grab in DESK.grabs.values()}
        for widget in _widgets:
            if widget.kind == layout.HANDLE:
                edge, face = _handle_batches_for(widget)
                hovered = widget.id in DESK.hover.values()
                _draw_flat(edge, _rgba(layout.ACTIVE) if widget.id in grabbed else _rgba(layout.ACCENT))
                _draw_flat(face, HANDLE_HOVER if hovered else _rgba(layout.GRIP_GREY))
        for hand, widget_id in DESK.hover.items():
            widget = _by_id.get(widget_id)
            if widget is None or widget.kind == layout.HANDLE or widget.kind == layout.LABEL:
                continue
            batch = _highlight(widget_id)
            if batch:
                _draw_flat(batch, PRESS_COLOUR if DESK.pressed.get(hand) == widget_id else HOVER_COLOUR)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')
    asset_draw.draw_drag(new_frame)
