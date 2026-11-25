# SPDX-License-Identifier: GPL-3.0-or-later
"""Composition Guides (Digit's Tools > Scene): the composition guide lines with a thin black outline, so they stay
readable on any picture, drawn in the 3D view by ONE draw handler (POST_PIXEL).
- Looking through the camera: on the camera's frame, for the guides switched on in the camera itself (the Camera Rig's
  Composition buttons), on top of Blender's own thin lines.
- Anywhere else: on a "planning frame" centred in the view, with the render's aspect ratio (resolution x pixel
  aspect), for the guides chosen in this tool (so you can plan a shot without looking through the camera).
The guide list and its teaching tooltips are camera_rig_spec.GUIDES (one table). Settings live on the Scene.

No background work: the handler exists only while "Show Guides" is on (the scene flag; `sync` adds / removes it,
the toggle calls it, unregister removes it). Handlers are not saved in a .blend, so after a file load the flag may be
on with no handler: the Composition Guides card and the Camera Rig's Composition section call `sync` when drawn,
which re-adds it. The draw callback only reads a few scene settings and draws; it scans nothing."""
from functools import lru_cache
from math import cos, pi, sin, sqrt

import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader

from . import camera_rig_spec as spec
from .rig_placement import dim_outside, ratio_text
from .ui_cards import action_row, hints, prop_group, section, status  # generated copy

PHI = (1 + sqrt(5)) / 2
GOLDEN = 1 / PHI   # 0.618; the other golden line sits at 1 - GOLDEN = 0.382
PLANNING_MARGIN = 0.08   # share of the view left empty on each side of the planning frame
OUTLINE_COLOUR = (0.0, 0.0, 0.0, 0.85)
OUTLINE_EXTRA = 2.0      # the black line is this many pixels wider than the coloured one
BORDER_WIDTH = 1.5
PREFIX = "comp_guides_"
SETTINGS = ("show", "color", "width", "outline", "border", "darken", "spiral_corner", "spiral_rects")
SPIRAL_STEPS = 9         # quarter arcs in the spiral
SPIRAL_ARC_POINTS = 16   # line pieces per arc

# ---------------------------------------------------------------------------
# Maths (plain numbers: a frame is (left, bottom, right, top) in pixels, y up)
# ---------------------------------------------------------------------------

def short_name(prop):
    return prop.removeprefix("show_composition_")


def scene_prop(prop):
    """The Scene property (planning choice) for a camera guide property."""
    return PREFIX + short_name(prop)


def _triangle(w, h, harmony):
    """Segments of a triangle guide in a w x h frame (origin bottom-left, diagonal bottom-left to top-right): the
    diagonal plus a line from each other corner at a right angle to it. Golden Triangle stops at the diagonal;
    Harmony Triangle carries on to the frame's edge."""
    dx, dy = w, h
    out = [((0, 0), (w, h))]
    for cx, cy in ((0, h), (w, 0)):
        t = (cx * dx + cy * dy) / (dx * dx + dy * dy)
        foot = (t * dx, t * dy)
        if harmony:
            vx, vy = foot[0] - cx, foot[1] - cy
            reach = min((w - cx) / vx if vx > 0 else cx / -vx if vx < 0 else float("inf"),
                        (h - cy) / vy if vy > 0 else cy / -vy if vy < 0 else float("inf"))
            out.append(((cx, cy), (cx + vx * reach, cy + vy * reach)))
        else:
            out.append(((cx, cy), foot))
    return out


def _spiral_canonical(w, h, steps):
    """(polyline, split segments) of the golden spiral in a w x h frame, entering at the bottom-left corner.
    Each step cuts the rectangle at 1/PHI of its first side, draws a quarter ellipse in the cut piece (centred on the
    cut line, so the curve crosses it at a right angle) and carries on in the rest, turned 90 degrees. For a frame
    that is not exactly golden the pieces are rectangles, so the curve still fits the frame."""
    entry = (0.0, 0.0)
    d1, d2 = ((1.0, 0.0), (0.0, 1.0)) if w >= h else ((0.0, 1.0), (1.0, 0.0))
    length, side = (w, h) if w >= h else (h, w)
    line, splits = [], []
    for _ in range(steps):
        cut = length * GOLDEN
        centre = (entry[0] + cut * d1[0], entry[1] + cut * d1[1])
        for i in range(0 if not line else 1, SPIRAL_ARC_POINTS + 1):   # an arc starts where the last one ended
            t = (pi / 2) * i / SPIRAL_ARC_POINTS
            along, across = -cut * cos(t), side * sin(t)
            line.append((centre[0] + along * d1[0] + across * d2[0], centre[1] + along * d1[1] + across * d2[1]))
        end = line[-1]
        splits.append((centre, end))
        entry, d1, d2 = end, (-d2[0], -d2[1]), d1
        length, side = side, length - cut
    return line, splits


@lru_cache(maxsize=16)
def spiral_geometry(frame, corner="TOP_LEFT", rectangles=False, steps=SPIRAL_STEPS):
    """Line segments of the golden spiral (plus its rectangle lines when `rectangles`) inside `frame`, with the tight
    end in `corner`. Cached by frame, so the draw callback only builds it when the frame changes."""
    x0, y0, x1, y1 = frame
    w, h = x1 - x0, y1 - y0
    line, splits = _spiral_canonical(w, h, steps)
    end = line[-1]
    flip_x = (end[0] > w / 2) != corner.endswith("RIGHT")
    flip_y = (end[1] > h / 2) != corner.startswith("TOP")

    def place(p):
        return (x0 + (w - p[0] if flip_x else p[0]), y0 + (h - p[1] if flip_y else p[1]))
    segments = [(place(a), place(b)) for a, b in zip(line, line[1:])]
    if rectangles:
        segments += [(place(a), place(b)) for a, b in splits]
    return tuple(segments)


def spiral_eye(frame, corner):
    """The point the spiral winds in on (where the subject's eye goes), for `corner`."""
    return spiral_geometry(tuple(frame), corner, False, 40)[-1][1]


def guide_segments(prop, frame, corner="TOP_LEFT", rectangles=False):
    """[((x, y), (x, y)), ...] the lines of the guide named by camera property `prop`, inside `frame`.
    `corner` and `rectangles` are the Golden Spiral's settings."""
    x0, y0, x1, y1 = frame
    w, h = x1 - x0, y1 - y0

    def across(fractions):   # lines at these fractions of the width / height
        return [((x0 + f * w, y0), (x0 + f * w, y1)) for f in fractions] + \
               [((x0, y0 + f * h), (x1, y0 + f * h)) for f in fractions]

    name = short_name(prop)
    if prop == spec.SPIRAL_PROP:
        return list(spiral_geometry(tuple(frame), corner, rectangles))
    if name == "thirds":
        return across((1 / 3, 2 / 3))
    if name == "center":
        return across((0.5,))
    if name == "golden":
        return across((1 - GOLDEN, GOLDEN))
    if name == "center_diagonal":
        return [((x0, y0), (x1, y1)), ((x0, y1), (x1, y0))]
    if name in ("golden_tria_a", "golden_tria_b", "harmony_tri_a", "harmony_tri_b"):
        flip = name.endswith("_b")
        return [tuple((x1 - px if flip else x0 + px, y0 + py) for px, py in seg)
                for seg in _triangle(w, h, name.startswith("harmony"))]
    raise ValueError(f"not a composition guide: {prop}")


def fit_frame(region_w, region_h, aspect, margin=PLANNING_MARGIN):
    """The largest frame of this width / height `aspect`, centred in the region with `margin` (share of the
    region) free on every side, as (left, bottom, right, top)."""
    room_w, room_h = region_w * (1 - 2 * margin), region_h * (1 - 2 * margin)
    w = min(room_w, room_h * aspect)
    h = w / aspect
    x0, y0 = (region_w - w) / 2, (region_h - h) / 2
    return (x0, y0, x0 + w, y0 + h)


def render_aspect(scene):
    r = scene.render
    return (r.resolution_x * r.pixel_aspect_x) / (r.resolution_y * r.pixel_aspect_y)


def flat_points(segments):
    return [point for segment in segments for point in segment]


# ---------------------------------------------------------------------------
# What to draw (reads settings only)
# ---------------------------------------------------------------------------

def camera_frame(region, rv3d, camera, scene):
    """The camera's frame in region pixels (left, bottom, right, top), or None when it can't be placed."""
    points = [view3d_utils.location_3d_to_region_2d(region, rv3d, camera.matrix_world @ corner)
              for corner in camera.data.view_frame(scene=scene)]
    if any(p is None for p in points):
        return None
    xs, ys = [p.x for p in points], [p.y for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def view_camera(scene, space, rv3d):
    """The camera object this 3D view looks through, or None when it is not in camera view."""
    if rv3d.view_perspective != 'CAMERA':
        return None
    camera = space.camera if space.use_local_camera else scene.camera
    return camera if camera is not None and camera.type == 'CAMERA' else None


def planned_lines(scene, region, rv3d, space):
    """(guide segments, the frame, planning?) for this 3D view, or None when nothing is drawn."""
    camera = view_camera(scene, space, rv3d)
    if camera is not None:
        frame = camera_frame(region, rv3d, camera, scene)
        props = [g[0] for g in spec.GUIDES if getattr(camera.data, g[0])]
        return (frame, props, False) if frame else None
    props = [g[0] for g in spec.GUIDES if getattr(scene, scene_prop(g[0]))]
    return fit_frame(region.width, region.height, render_aspect(scene)), props, True


def _draw_lines(shader, segments, scene):
    batch = batch_for_shader(shader, 'LINES', {"pos": flat_points(segments)})
    width = scene.comp_guides_width
    if scene.comp_guides_outline:
        shader.uniform_float("color", OUTLINE_COLOUR)
        gpu.state.line_width_set(width + OUTLINE_EXTRA)
        batch.draw(shader)
    shader.uniform_float("color", tuple(scene.comp_guides_color))
    gpu.state.line_width_set(width)
    batch.draw(shader)


def _draw():
    context = bpy.context
    scene, region, rv3d = context.scene, context.region, context.region_data
    if not scene.comp_guides_show or rv3d is None or region is None or context.space_data.type != 'VIEW_3D':
        return
    plan = planned_lines(scene, region, rv3d, context.space_data)
    if plan is None:
        return
    frame, props, planning = plan
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    x0, y0, x1, y1 = frame
    if planning:
        if scene.comp_guides_darken > 0:
            dim_outside(shader, (region.width, region.height), ((x0, y0), (x1, y1)), (0, 0, 0, scene.comp_guides_darken))
        if scene.comp_guides_border:
            _draw_lines(shader, [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))], scene)
    segments = [seg for prop in props for seg in guide_segments(
        prop, frame, scene.comp_guides_spiral_corner, scene.comp_guides_spiral_rects)]
    if segments:
        _draw_lines(shader, segments, scene)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


# ---------------------------------------------------------------------------
# The draw handler: on only while a scene has Show Guides on
# ---------------------------------------------------------------------------

_handle = None


def has_handler():
    return _handle is not None


def wanted():
    return any(scene.comp_guides_show for scene in bpy.data.scenes)


def sync():
    """Add the draw handler when some scene wants it and it is missing, remove it when nobody does."""
    global _handle
    if wanted() and _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_PIXEL')
    elif not wanted() and _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None


def _remove():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None


def _changed(self, context):
    sync()
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def draw_line_settings(layout, scene):
    """Outline / Line Width / Line Colour: shared by this card and the Camera Rig's Composition section."""
    prop_group(layout, scene, [("comp_guides_outline", "Outline"), ("comp_guides_width", "Line Width"),
                               ("comp_guides_color", "Line Colour")])


def draw_spiral_settings(layout, scene):
    """Spiral Corner / Show Rectangles: shared by this card and the Camera Rig's Composition section."""
    prop_group(layout, scene, [("comp_guides_spiral_corner", "Spiral Corner"), ("comp_guides_spiral_rects", "Show Rectangles")])


def draw_card(layout, context):
    scene = context.scene
    sync()   # a loaded file keeps the flag but not the handler
    chosen = [g for g in spec.GUIDES if getattr(scene, scene_prop(g[0]))]
    status(layout, f"{'On' if scene.comp_guides_show else 'Off'} · {len(chosen)} planning guides",
           icon='MOD_LATTICE')
    action_row(layout).prop(scene, "comp_guides_show", text="Show Guides", toggle=True,
                            icon='HIDE_OFF' if scene.comp_guides_show else 'HIDE_ON')
    guides = section(layout, "digitools_compguides_guides", "Guides", icon='MOD_LATTICE',
                     right=f"{len(chosen)} of {len(spec.GUIDES)} on")
    if guides:
        grid = guides.grid_flow(columns=2, align=True)
        for prop, label, _tip in spec.GUIDES:
            grid.prop(scene, scene_prop(prop), text=label, toggle=True)
        if getattr(scene, scene_prop(spec.SPIRAL_PROP)):
            draw_spiral_settings(guides, scene)
    lines = section(layout, "digitools_compguides_lines", "Lines", icon='LINE_DATA')
    if lines:
        draw_line_settings(lines, scene)
    frame = section(layout, "digitools_compguides_frame", "Planning Frame", icon='FULLSCREEN_ENTER')
    if frame:
        prop_group(frame, scene, [("comp_guides_border", "Frame Border"), ("comp_guides_darken", "Darken Outside")])
        r = scene.render
        hints(frame, [f"Match Render Size: the frame uses the render's shape, "
                      f"{ratio_text(r.resolution_x, r.resolution_y)}"], context)
    hints(layout, ["Looking through the camera, the guides switched on in the camera are used instead "
                   "(Camera Rig > Composition)"], context)


class DIGITOOLS_OT_toggle_composition_guides(bpy.types.Operator):
    """Show or hide the composition guides (the same Show Guides switch as the Composition Guides card)"""
    bl_idname = "digits_assorted_tools.toggle_composition_guides"
    bl_label = "Toggle Composition Guides"

    def execute(self, context):
        context.scene.comp_guides_show = not context.scene.comp_guides_show
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register():
    bpy.utils.register_class(DIGITOOLS_OT_toggle_composition_guides)
    Scene = bpy.types.Scene
    Scene.comp_guides_show = BoolProperty(
        name="Show Guides", default=False, update=_changed,
        description="Draw the composition guides in the 3D view with a thin black outline: on the camera's frame "
                    "when looking through the camera, otherwise on a planning frame the shape of the render")
    Scene.comp_guides_color = FloatVectorProperty(
        name="Line Colour", subtype='COLOR', size=4, min=0.0, max=1.0, default=(1.0, 1.0, 1.0, 0.9), update=_changed,
        description="Colour of the guide lines. Lower the alpha to make them see-through")
    Scene.comp_guides_width = FloatProperty(
        name="Line Width", default=1.5, min=1.0, max=6.0, update=_changed, description="Thickness of the guide lines in pixels")
    Scene.comp_guides_outline = BoolProperty(
        name="Outline", default=True, update=_changed,
        description="A thin black line under every guide line, so it stays visible on light and dark pictures")
    Scene.comp_guides_border = BoolProperty(
        name="Frame Border", default=True, update=_changed, description="Outline the planning frame (outside camera view)")
    Scene.comp_guides_darken = FloatProperty(
        name="Darken Outside", default=0.35, min=0.0, max=1.0, subtype='FACTOR', update=_changed,
        description="Darken the view outside the planning frame, like looking through a camera. 0 is off")
    Scene.comp_guides_spiral_corner = EnumProperty(
        name="Spiral Corner", items=spec.enum_items(spec.SPIRAL_CORNERS), default="TOP_LEFT", update=_changed,
        description="Where the Golden Spiral's tight end sits. That is where the subject goes: the spiral leads the "
                    "eye inward to it. Used for the camera view and the planning frame")
    Scene.comp_guides_spiral_rects = BoolProperty(
        name="Show Rectangles", default=False, update=_changed, description=spec.SPIRAL_RECTS_TIP)
    # no built-in camera flag for the spiral: ours lives on the camera data (saved with it), toggled per camera
    setattr(bpy.types.Camera, spec.SPIRAL_PROP, BoolProperty(
        name="Golden Spiral", default=False, update=_changed, description=spec.SPIRAL_TIP))
    for prop, label, tip in spec.GUIDES:
        setattr(Scene, scene_prop(prop), BoolProperty(
            name=label, default=prop == "show_composition_thirds", update=_changed,
            description=tip + " (Planning frame, outside camera view.)"))


def unregister():
    bpy.utils.unregister_class(DIGITOOLS_OT_toggle_composition_guides)
    _remove()
    delattr(bpy.types.Camera, spec.SPIRAL_PROP)
    Scene = bpy.types.Scene
    for name in SETTINGS:
        delattr(Scene, PREFIX + name)
    for prop, _label, _tip in spec.GUIDES:
        delattr(Scene, scene_prop(prop))
