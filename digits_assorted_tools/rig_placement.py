# SPDX-License-Identifier: GPL-3.0-or-later
"""Where the Setups cards put a rig when you press Deploy: the 3D view's eye and look direction plus
what the view centre points at (a ray hit, or a point at a close distance) become the rig's transform.
The maths is plain functions of vectors (testable without a 3D view); `view_from_context`, `cast`
and `floor_below` are the thin bpy parts. `PickOperator` is the one click-in-the-viewport modal (the
Deploy buttons, Focus Pull and Frame Subject use it); `PickDeployOperator` adds the library lookup."""

from collections import namedtuple
from math import atan2, cos, radians, sin, sqrt

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .modifier_setup import library_file  # generated copy
from .ui_cards import action_row, hints, section, status  # generated copy
from .view_ray import RAY_LENGTH, cast_hit, mouse_ray, region_under_mouse, viewport_under_mouse  # noqa: F401  (generated copy; re-exported)

FALLBACK_MIN, FALLBACK_MAX = 1.5, 5.0   # no ray hit: the target is the view's orbit distance, clamped to this (m)
FLOOR_PROBE = 0.05                      # floor rays start this far above the point, so a point ON the floor finds it
CAMERA_HEIGHT = (0.1, 6.0)              # a floor this far below the eye is used as the dolly's ground (m)
DEFAULT_CAMERA_HEIGHT = 1.6             # otherwise the rig keeps its own camera height
ON_FLOOR = 0.05                         # a hit this close to the floor counts as "the ground"
UP = Vector((0, 0, 1))

# eye position, unit look direction, orbit distance, and (tan(half fov) across, up) of a perspective
# view (None: orthographic or unknown, so Match View leaves the eye alone)
View = namedtuple("View", "eye forward distance half_tans", defaults=(None,))


# ---------------------------------------------------------------------------
# Plain maths
# ---------------------------------------------------------------------------

def view_from_matrix(view_inverse, distance):
    """The View of a viewport whose inverted view matrix is `view_inverse` (the eye's world matrix)."""
    forward = (view_inverse.to_3x3() @ Vector((0, 0, -1))).normalized()
    return View(view_inverse.translation.copy(), forward, distance)


def fallback_distance(distance):
    return min(max(distance, FALLBACK_MIN), FALLBACK_MAX)


def target_point(view, hit):
    """The view centre's target: the ray hit, else a point straight ahead at a close distance."""
    return hit if hit is not None else view.eye + view.forward * fallback_distance(view.distance)


def yaw_facing(direction):
    """Z rotation that turns an object's +Y (the dolly's facing) to `direction`'s horizontal part."""
    return atan2(-direction.x, direction.y) if direction.xy.length > 1e-6 else 0.0


def yaw_toward(origin, point):
    """Z rotation that turns an object's -Y side (where Swing 0 sits) to `point`."""
    to = point - origin
    return atan2(to.x, -to.y) if to.xy.length > 1e-6 else 0.0


def view_from_ray(view, origin, direction):
    """The view with its eye and look direction replaced by a mouse ray (a click in the viewport)."""
    return view._replace(eye=Vector(origin), forward=Vector(direction).normalized())


def fit_axis(sensor_width, sensor_height, sensor_fit, aspect):
    """(axis, sensor size in mm along it): the way the sensor spans the frame. HORIZONTAL: across (0) by
    the sensor width, VERTICAL: up (1) by the sensor height, AUTO: the sensor width across for a
    landscape or square frame, up for a portrait one. `aspect` = width / height."""
    if sensor_fit == 'HORIZONTAL':
        return 0, sensor_width
    if sensor_fit == 'VERTICAL':
        return 1, sensor_height
    return (0 if aspect >= 1 else 1), sensor_width


def camera_fit_tan(lens, sensor_width, aspect):
    """(axis, tan(half fov)) of a camera on the axis its sensor spans, like Blender's Auto sensor fit."""
    axis, size = fit_axis(sensor_width, sensor_width, 'AUTO', aspect)
    return axis, size / 2 / lens


def matched_eye(view, target, lens, sensor_width, aspect):
    """Where a camera with this lens sits to show the subject as large as the viewport does: backed up
    from the target along the line of sight when its field of view is narrower than the viewport's
    (longer lens), moved closer when wider. The eye as-is when the view's field of view is unknown."""
    if view.half_tans is None:
        return view.eye
    axis, cam_tan = camera_fit_tan(lens, sensor_width, aspect)
    return target - (target - view.eye) * (view.half_tans[axis] / cam_tan)


def frame_half_tans(lens, sensor_width, sensor_height, sensor_fit, aspect):
    """(tan(half fov) across, up) of the rendered frame, honouring the camera's sensor fit
    (AUTO / HORIZONTAL / VERTICAL) and the render aspect (width / height)."""
    axis, size = fit_axis(sensor_width, sensor_height, sensor_fit, aspect)
    tan = size / 2 / lens
    return (tan, tan / aspect) if axis == 0 else (tan * aspect, tan)


def box_around(centre, mouse, aspect, min_half_width=1.0):
    """((left, bottom), (right, top)) of the frame drawn around `centre` (screen pixels) with one
    corner on the mouse: always the render aspect (width / height), as wide as the mouse is far
    out across or up, and at least `min_half_width` wide on each side."""
    half_width = max(abs(mouse[0] - centre[0]), abs(mouse[1] - centre[1]) * aspect, min_half_width)
    half_height = half_width / aspect
    return ((centre[0] - half_width, centre[1] - half_height), (centre[0] + half_width, centre[1] + half_height))


def aspect_from_box(box, limits=(0.125, 8.0)):
    """Width / height of a drawn box ((left, bottom), (right, top)), kept within `limits` so a box
    squeezed to a line still gives a sane ratio."""
    width, height = box[1][0] - box[0][0], box[1][1] - box[0][1]
    return min(max(width / height, limits[0]), limits[1]) if height > 1e-9 else limits[1]


def free_box_around(centre, mouse, min_half=1.0):
    """The frame drawn around `centre` with one corner on the mouse, in any aspect (Shift while drawing)."""
    half_width, half_height = max(abs(mouse[0] - centre[0]), min_half), max(abs(mouse[1] - centre[1]), min_half)
    return ((centre[0] - half_width, centre[1] - half_height), (centre[0] + half_width, centre[1] + half_height))


# (name, width / height): the ratios Snap Ratio picks from, with the portrait inverses
COMMON_RATIOS = tuple((f"{a}:{b}", a / b) for a, b in
                      ((1, 1), (5, 4), (4, 3), (3, 2), (16, 10), (16, 9), (2, 1), (2.39, 1),
                       (4, 5), (3, 4), (2, 3), (9, 16)))


def snap_ratio(ratio, tolerance=0.03):
    """(name, value) of the common ratio within `tolerance` (relative) of `ratio`, the nearest one, or None."""
    name, value = min(COMMON_RATIOS, key=lambda r: abs(r[1] / ratio - 1))
    return (name, value) if abs(value / ratio - 1) <= tolerance else None


def _round_to(value, step):
    return max(step, int(round(value / step)) * step)


def resolution_for_aspect(pixels, ratio, snap=True, presets=(), preset_tolerance=0.15):
    """(width, height, ratio name or None) of about `pixels` total at width / height = `ratio`:
    w = sqrt(P * r), h = sqrt(P / r). Snap off: free ratio, even numbers. Snap on: the ratio goes to the
    nearest common one (`snap_ratio`) and the size to a multiple of 8, or to a preset (width, height) of the
    same ratio whose pixel count is within `preset_tolerance` of `pixels`."""
    name = None
    if snap:
        found = snap_ratio(ratio)
        if found:
            name, ratio = found
    width, height = sqrt(pixels * ratio), sqrt(pixels / ratio)
    if not snap:
        return _round_to(width, 2), _round_to(height, 2), None
    close = [p for p in presets if abs(p[0] / p[1] / ratio - 1) < 0.01 and abs(p[0] * p[1] / pixels - 1) <= preset_tolerance]
    if name and close:
        best = min(close, key=lambda p: abs(p[0] * p[1] - pixels))
        return best[0], best[1], name
    return _round_to(width, 8), _round_to(height, 8), name


def ratio_text(width, height, name=None):
    """"1920 × 1080 · 16:9" (a snapped ratio's name) or "1600 × 1350 · 1.19:1" (free)."""
    return f"{width} × {height} · {name or f'{width / height:.2f}:1'}"


def box_corners_2d(box):
    return [(box[i][0], box[j][1]) for i, j in ((0, 0), (1, 0), (1, 1), (0, 1))]


def ray_tans(rays, forward, right, up):
    """(tan across, tan up) of the smallest camera frame, looking along `forward`, that holds every ray
    (directions from the eye)."""
    tans = [(abs(ray.dot(right)) / ray.dot(forward), abs(ray.dot(up)) / ray.dot(forward)) for ray in rays]
    return max(t[0] for t in tans), max(t[1] for t in tans)


def lens_for_tans(tans, sensor_width, sensor_height, sensor_fit, aspect, lens_range=(8.0, 1200.0)):
    """The focal length (mm) whose frame, at the render aspect, just holds a field of view of
    (tan across, tan up); clamped to lens_range."""
    axis, size = fit_axis(sensor_width, sensor_height, sensor_fit, aspect)
    tan = max(tans[0], tans[1] * aspect) if axis == 0 else max(tans[1], tans[0] / aspect)
    lens = size / 2 / tan if tan > 1e-9 else lens_range[1]
    return min(max(lens, lens_range[0]), lens_range[1])


def box_distance(eye_distance, box_tans, frame_tans):
    """How far from the target a camera with this frame (tan across, tan up of its half field of view) must
    stand so the box seen from `eye_distance` away (its own tan across / up) exactly fills the frame:
    a bigger box or a longer lens (narrower frame) means further."""
    return max(eye_distance * max(box_tans[0] / frame_tans[0], box_tans[1] / frame_tans[1]), 0.01)


def eye_for_box(eye, target, box_tans, frame_tans):
    """The eye moved along the line from the target through it, to where `box_distance` says."""
    back = Vector(eye) - target
    if back.length < 1e-9:
        return Vector(eye)
    return target + back.normalized() * box_distance(back.length, box_tans, frame_tans)


def camera_axes(back, up_hint):
    """(right, up) of a camera whose backward axis (the way away from what it sees) is `back`, with
    its up as close to `up_hint` (e.g. its current up) as possible."""
    up = up_hint - back * up_hint.dot(back)
    if up.length < 1e-6:
        up = UP - back * UP.dot(back) if abs(back.z) < 0.999 else Vector((0, 1, 0))
    up.normalize()
    return up.cross(back), up


def frame_distance(points, centre, back, right, up, half_tans, margin):
    """How far from `centre`, along `back` (unit, from the centre toward the camera), a camera looking
    at the centre must sit so every point fits the frame: the farthest any point needs, each across
    and up. `margin` = the empty border, as a fraction of the frame (0.1: the subject spans 90%)."""
    usable = [t * (1 - margin) for t in half_tans]
    distance = 0.01
    for point in points:
        rel = point - centre
        along = rel.dot(back)
        distance = max(distance, along + abs(rel.dot(right)) / usable[0], along + abs(rel.dot(up)) / usable[1])
    return distance


def box_corners(matrix_world, bound_box):
    """The 8 world-space corners of an object's bounding box."""
    return [matrix_world @ Vector(corner) for corner in bound_box]


def box_centre(points):
    """Middle of the axis-aligned box around the points."""
    lows = Vector(map(min, zip(*points)))
    highs = Vector(map(max, zip(*points)))
    return (lows + highs) / 2


def local_point(parent_matrix, parent_inverse, world_point):
    """Local location that puts a child (parent matrix + parent inverse) at world_point."""
    return (parent_matrix @ parent_inverse).inverted_safe() @ world_point


def camera_placement(view, floor_z):
    """(dolly location, dolly Z rotation, camera local offset) putting the camera exactly at the eye:
    the dolly stands on the floor under the eye (when it is 0.1-6 m down), else the camera keeps the
    rig's own 1.6 m height."""
    height = view.eye.z - floor_z if floor_z is not None else None
    if height is None or not CAMERA_HEIGHT[0] <= height <= CAMERA_HEIGHT[1]:
        height = DEFAULT_CAMERA_HEIGHT
    return Vector((view.eye.x, view.eye.y, view.eye.z - height)), yaw_facing(view.forward), Vector((0, 0, height))


def subject_point(target, floor_z, lift):
    """Where a light or card aims: the target, but when it is the ground itself, `lift` above it (the
    subject stands there)."""
    if floor_z is not None and target.z - floor_z < ON_FLOOR:
        return target + Vector((0, 0, lift))
    return target


def light_placement(focus_point, floor_z, focus_height, eye):
    """(rig root location, Z rotation) for a Lighting Rig whose Focus sits on focus_point: the root
    on the floor under it (else `focus_height` below it), turned so Swing 0 faces the eye."""
    root = Vector((focus_point.x, focus_point.y,
                   floor_z if floor_z is not None else focus_point.z - focus_height))
    return root, yaw_toward(root, eye)


def clock_direction(view_forward, clock):
    """Unit vector, perpendicular to `view_forward`, pointing at `clock` o'clock as the viewer sees it
    (12 = up, 3 = right, 9 = left; the angle from up is (clock - 12) * 30 degrees)."""
    forward = Vector(view_forward).normalized()
    right = forward.cross(UP)
    right = right.normalized() if right.length > 1e-6 else Vector((1, 0, 0))
    up = right.cross(forward)
    angle = radians((clock - 12) * 30.0)
    return up * cos(angle) + right * sin(angle)


def catchlight_location(viewer, target, distance, clock, offset_angle=35.0):
    """Where a catchlight goes: `distance` m from `target` (the character's eye) on the viewer's side, turned
    `offset_angle` degrees away from the viewer's line towards `clock` o'clock, so the reflection lands near
    that clock position. The result is always between the viewer and the target."""
    to_viewer = Vector(viewer) - Vector(target)
    to_viewer = to_viewer.normalized() if to_viewer.length > 1e-6 else Vector((0, -1, 0))
    side = clock_direction(-to_viewer, clock)
    angle = radians(offset_angle)
    return Vector(target) + (to_viewer * cos(angle) + side * sin(angle)) * distance


def aim_euler(origin, point):
    """Euler rotation turning an object's -Z axis (a light's beam) from `origin` towards `point`."""
    return (Vector(point) - Vector(origin)).to_track_quat('-Z', 'Y').to_euler()


def card_placement(view, subject, side, toward_viewer):
    """Card location: `side` m to the viewer's right of the subject and `toward_viewer` m closer, at its height."""
    flat = Vector((view.forward.x, view.forward.y, 0))
    if flat.length < 1e-6:
        return subject.copy()
    flat.normalize()
    right = flat.cross(UP)
    return subject + right * side - flat * toward_viewer


# ---------------------------------------------------------------------------
# bpy parts
# ---------------------------------------------------------------------------

def render_aspect(scene):
    """Width / height of the scene's render frame, pixel aspect included."""
    render = scene.render
    return (render.resolution_x * render.pixel_aspect_x) / (render.resolution_y * render.pixel_aspect_y)


def view_from_rv3d(rv3d):
    """The View of a 3D view region's data; its field of view comes from the projection (window) matrix."""
    view = view_from_matrix(rv3d.view_matrix.inverted(), rv3d.view_distance)
    if not rv3d.is_perspective:
        return view
    window = rv3d.window_matrix
    return view._replace(half_tans=(1 / window[0][0], 1 / window[1][1]))


def view_from_context(context):
    """The View of the 3D view the button was pressed in (else the first 3D view of the screen), or
    one looking along +Y from 4 m behind the 3D cursor when there is none (scripts, background mode)."""
    space = context.space_data if context.space_data and context.space_data.type == 'VIEW_3D' else None
    if space is None and context.screen:
        space = next((s for a in context.screen.areas if a.type == 'VIEW_3D' for s in a.spaces
                      if s.type == 'VIEW_3D'), None)
    if space is not None and space.region_3d is not None:
        return view_from_rv3d(space.region_3d)
    cursor = context.scene.cursor.location
    return View(cursor + Vector((0, -4, DEFAULT_CAMERA_HEIGHT)), Vector((0, 1, 0)), 4.0)


def cast(scene, depsgraph, origin, direction):
    """Where a ray from origin along direction first hits the scene's geometry, or None."""
    return cast_hit(scene, depsgraph, origin, direction)[0]


def floor_below(scene, depsgraph, point):
    """Z of the first surface straight below point (just above it counts), or None."""
    hit = cast(scene, depsgraph, point + Vector((0, 0, FLOOR_PROBE)), Vector((0, 0, -1)))
    return hit.z if hit is not None else None


def view_target(context, view):
    """(target point, scene depsgraph): the first thing in the view centre, else the close point ahead.
    Cast before the rig is appended, so it can't block its own ray."""
    depsgraph = context.evaluated_depsgraph_get()
    return target_point(view, cast(context.scene, depsgraph, view.eye, view.forward)), depsgraph


# ---------------------------------------------------------------------------
# Under the subject: the floor of whatever was clicked (Photo Backdrop, Shadow Catcher Floor)
# ---------------------------------------------------------------------------

GROUND_GAP = 0.002   # a floor goes this far below the subject's lowest point, so they never z-fight (m)

# Where a floor goes: its centre (x, y of the subject's bounds middle, z = the subject's lowest point),
# the eye it is seen from and the subject's height (a light rig is fitted to it; 0 / None: no real subject)
Ground = namedtuple("Ground", "centre eye height", defaults=(None,))


def ground_from_bounds(low, high, eye):
    """The Ground under a subject whose world-space bounding box runs from `low` to `high`."""
    return Ground(Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z)), Vector(eye), high.z - low.z)


def floor_location(ground):
    """Where a floor object's origin goes: under the subject's centre, a hair below its lowest point."""
    return ground.centre - Vector((0, 0, GROUND_GAP))


def wall_yaw(ground):
    """Z rotation that turns an object's +Y (the backdrop's wall side) away from the viewer."""
    return yaw_facing(ground.centre - ground.eye)


def armature_of(ob):
    """The armature that deforms or parents `ob` (Armature modifier first, then the parent chain), or None."""
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object is not None:
            return mod.object
    parent = ob.parent
    while parent is not None:
        if parent.type == 'ARMATURE':
            return parent
        parent = parent.parent
    return ob if ob.type == 'ARMATURE' else None


def subject_objects(ob, scene_objects):
    """The objects whose geometry makes up the clicked object: itself, or every mesh of its character
    (all meshes parented to or deformed by its armature) when it belongs to a rig."""
    rig = armature_of(ob)
    if rig is None:
        return [ob]
    meshes = [o for o in scene_objects if o.type == 'MESH' and armature_of(o) == rig]
    return meshes or [ob]


def world_bounds(objects, depsgraph):
    """(low, high) corners of the world-space box around the evaluated geometry (modifiers, shape keys
    and armature poses included) of `objects`, or None when they have no vertices."""
    import numpy as np
    low, high = None, None
    for ob in objects:
        evaluated = ob.evaluated_get(depsgraph)
        try:
            mesh = evaluated.to_mesh()
        except RuntimeError:   # empties, cameras, lights: no geometry
            continue
        try:
            count = len(mesh.vertices)
            if count == 0:
                continue
            coords = np.empty(count * 3, dtype=np.float32)
            mesh.vertices.foreach_get("co", coords)
            coords = coords.reshape(count, 3)
            matrix = np.array(evaluated.matrix_world)
            world = coords @ matrix[:3, :3].T + matrix[:3, 3]
        finally:
            evaluated.to_mesh_clear()
        lo, hi = world.min(axis=0), world.max(axis=0)
        low = lo if low is None else np.minimum(low, lo)
        high = hi if high is None else np.maximum(high, hi)
    return None if low is None else (Vector(low.tolist()), Vector(high.tolist()))


def ground_under_click(context, view):
    """The Ground for a click: under the geometry of the object hit by the view's ray (its whole
    character when it belongs to a rig); with no hit (or no geometry), under the fallback point ahead,
    on the first surface below it (else at its own height)."""
    depsgraph = context.evaluated_depsgraph_get()
    scene = context.scene
    point, ob = cast_hit(scene, depsgraph, view.eye, view.forward)
    if ob is not None:
        bounds = world_bounds(subject_objects(ob, scene.objects), depsgraph)
        if bounds is not None:
            return ground_from_bounds(*bounds, view.eye)
    target = target_point(view, point)
    floor_z = floor_below(scene, depsgraph, target)
    return ground_from_bounds(Vector((target.x, target.y, target.z if floor_z is None else floor_z)),
                              Vector((target.x, target.y, target.z)), view.eye)


# ---------------------------------------------------------------------------
# Redeploy: one rig of a kind in the scene can be moved instead of copied
# ---------------------------------------------------------------------------

REDEPLOY_TIP = "Move this rig to a new spot with the same click, keeping all its settings"


def rig_roots(objects, root_tag):
    """The rig roots (objects carrying the tag property) among `objects`."""
    return [ob for ob in objects if ob.get(root_tag) is not None]


def show_redeploy(count):
    """Redeploy is offered when the scene has exactly one rig of the kind (with 0 there is nothing to move,
    with 2+ it is unclear which)."""
    return count == 1


def needs_confirm(count, redeploy, confirmed):
    """Deploy asks first ("deploy a second one?") when one rig exists and the user hasn't answered yet."""
    return show_redeploy(count) and not redeploy and not confirmed


class SETUPS_OT_dismiss(bpy.types.Operator):
    """Close the question without doing anything"""
    bl_idname = "setups.dismiss"
    bl_label = "Dismiss"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        return {'CANCELLED'}


# ---------------------------------------------------------------------------
# Click to place: the modal every Deploy button shares
# ---------------------------------------------------------------------------

PICK_HELP = "Click the target  ·  Enter: screen centre  ·  Esc / Right-click: cancel"


def pick_action(event_type, event_value):
    """What a key event means while picking: 'click', 'centre', 'cancel' or None (pass it through,
    so the viewport can still be navigated)."""
    if event_value != 'PRESS':
        return None
    return {'LEFTMOUSE': 'click', 'RET': 'centre', 'NUMPAD_ENTER': 'centre',
            'ESC': 'cancel', 'RIGHTMOUSE': 'cancel'}.get(event_type)


def clicked_outside_viewport(areas, x, y):
    """True when a click at screen x, y is not on a 3D viewport itself: on its sidebar, tool shelf or header
    (they overlap the viewport), or on another editor. Such a click ends a pick and goes on to that button."""
    return viewport_under_mouse(areas, x, y) is None


def fill_rect(shader, rect):
    """Fill ((left, bottom), (right, top)) with the shader's current colour (POST_PIXEL drawing)."""
    (x0, y0), (x1, y1) = rect
    if x1 > x0 and y1 > y0:
        batch_for_shader(shader, 'TRI_FAN', {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]}).draw(shader)


def dim_outside(shader, region_size, box, colour):
    """Darken the whole region except `box` (((left, bottom), (right, top)))."""
    (x0, y0), (x1, y1) = box
    width, height = region_size
    shader.uniform_float("color", colour)
    for rect in (((0, 0), (width, y0)), ((0, y1), (width, height)), ((0, y0), (x0, y1)), ((x1, y0), (width, y1))):
        fill_rect(shader, rect)


class PickOverlay:
    """What a pick draws in the 3D view (POST_PIXEL): a frame with the outside darkened (`box` =
    ((left, bottom), (right, top)) in the region's pixels) and a text label beside the mouse. Set the
    fields and redraw; `stop` removes the draw handler (PickOperator calls it on every exit)."""
    DIM, LINE, TEXT_SIZE = (0.0, 0.0, 0.0, 0.45), (1.0, 1.0, 1.0, 0.95), 16

    def __init__(self):
        self.region_pointer = None
        self.box = None
        self.mouse = None
        self.text = ""
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')

    def update(self, region, mouse, text="", box=None):
        self.region_pointer = region.as_pointer() if region is not None else None
        self.mouse, self.text, self.box = mouse, text, box

    def stop(self):
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

    def _draw(self):
        region = bpy.context.region
        if region is None or region.as_pointer() != self.region_pointer:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        if self.box is not None:
            dim_outside(shader, (region.width, region.height), self.box, self.DIM)
            shader.uniform_float("color", self.LINE)
            gpu.state.line_width_set(2.0)
            batch_for_shader(shader, 'LINE_LOOP', {"pos": box_corners_2d(self.box)}).draw(shader)
            gpu.state.line_width_set(1.0)
        if self.text and self.mouse is not None:
            blf.size(0, self.TEXT_SIZE)
            x, y = self.mouse[0] + 18, self.mouse[1] + 18
            blf.color(0, 0.0, 0.0, 0.0, 0.8)
            blf.position(0, x + 1, y - 1, 0)
            blf.draw(0, self.text)
            blf.color(0, 1.0, 1.0, 1.0, 1.0)
            blf.position(0, x, y, 0)
            blf.draw(0, self.text)
        gpu.state.blend_set('NONE')


class PickOperator:
    """Mixin for an operator that needs a click in a 3D view: invoke asks for the click and calls
    `picked(context, view)` with the View under the mouse ray (Enter: the view centre of the 3D view
    under the mouse; Esc / right-click: cancel); execute (scripts, no view) calls it with the first 3D
    view's centre. `prepare()` runs first and can refuse (False). `picked` returns the operator result."""
    pick_help = PICK_HELP
    refine_help = PICK_HELP
    READOUT_MOVE = 3   # pixels the mouse must move before `readout` runs again (it may ray cast)
    _picking = False
    _refining = False
    _shift = False
    _ctrl = False
    _overlay = None

    def prepare(self):
        return True

    def refine_start(self, context, view, region, rv3d):
        """Optional second step after the first click: return True to keep the modal running (set
        `refine_help`, draw what you need), then `refine_move` follows the mouse and a click ends it with
        `picked(context, view)`. `region` / `rv3d` are the 3D view clicked in (None for Enter outside any)."""
        return False

    def refine_move(self, context, mouse):
        """The mouse moved during the second step: `mouse` = (x, y) in the clicked region's pixels;
        `self._shift` / `self._ctrl` say whether Shift / Ctrl is held; set `self._overlay.update(...)` to draw
        (frame, label)."""

    def refine_cancel(self, context):
        """Esc / right-click (or a click off the viewport) during the second step: undo what it changed."""

    def readout(self, context, view):
        """Text shown beside the cursor while hovering in the first step, for the View under the
        mouse (None: nothing). Runs only after the mouse moved a few pixels."""
        return None

    def picked(self, context, view):
        raise NotImplementedError

    def execute(self, context):
        if not self.prepare():
            return {'CANCELLED'}
        return self.picked(context, view_from_context(context))

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return self.execute(context)
        if not self.prepare():
            return {'CANCELLED'}
        self._area, self._window, self._workspace = context.area, context.window, context.workspace
        self._picking, self._refining, self._last_readout = True, False, None
        self._overlay = PickOverlay()
        self._window.cursor_modal_set('CROSSHAIR')
        self._set_help(self.pick_help)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _set_help(self, text):
        self._area.header_text_set(text)
        self._workspace.status_text_set(text)

    def cancel(self, context):
        if self._picking:
            self._end_pick()

    def _end_pick(self):
        self._picking = False
        if self._overlay is not None:
            self._overlay.stop()
            self._overlay = None
        self._window.cursor_modal_restore()
        self._area.header_text_set(None)
        self._workspace.status_text_set(None)

    def _picked_view(self, context, event, clicked):
        """The View to place from: a click gives the mouse ray (eye at the viewport eye), Enter the
        view centre of the 3D view under the mouse (else the one the button was in)."""
        found = region_under_mouse(context.window.screen.areas, event.mouse_x, event.mouse_y)
        self._region, self._rv3d = found if found else (None, None)
        if found is None:
            return None if clicked else view_from_context(context)
        region, rv3d = found
        view = view_from_rv3d(rv3d)
        if not clicked:
            return view
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        return view_from_ray(view, *mouse_ray(region, rv3d, coord))

    def _refine_at(self, context, event):
        self._shift, self._ctrl = event.shift, event.ctrl
        self.refine_move(context, (event.mouse_x - self._region.x, event.mouse_y - self._region.y))
        self._area.tag_redraw()

    def _hover(self, context, event):
        """First step, mouse moved: show `readout` for the ray under the mouse (throttled)."""
        here = (event.mouse_x, event.mouse_y)
        if self._last_readout and abs(here[0] - self._last_readout[0]) + abs(here[1] - self._last_readout[1]) <= self.READOUT_MOVE:
            return
        self._last_readout = here
        view = self._picked_view(context, event, True)
        text = self.readout(context, view) if view is not None else None
        mouse = (event.mouse_x - self._region.x, event.mouse_y - self._region.y) if view is not None else None
        self._overlay.update(self._region, mouse, text or "")
        self._set_help(f"{self.pick_help}  ·  {text}" if text else self.pick_help)
        self._area.tag_redraw()

    def modal(self, context, event):
        action = pick_action(event.type, event.value)
        if event.type == 'MOUSEMOVE':
            self._window.cursor_modal_set('CROSSHAIR')   # other areas reset it as the mouse crosses them
            if self._refining:
                self._refine_at(context, event)
            else:
                self._hover(context, event)
        if self._refining and event.type in ('LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL', 'RIGHT_CTRL'):
            self._refine_at(context, event)   # pressing / releasing Shift / Ctrl redraws without a mouse move
        if action is None:
            return {'PASS_THROUGH'}
        if action == 'cancel':
            self._end_pick()
            if self._refining:
                self.refine_cancel(context)
            return {'CANCELLED'}
        if action == 'click' and clicked_outside_viewport(context.window.screen.areas, event.mouse_x, event.mouse_y):
            # a click on the sidebar (e.g. the next button, Stick) is not a pick: stop picking, let the button
            # have it (before, the viewport under the sidebar took it and the button seemed to do nothing)
            self._end_pick()
            if self._refining:
                self.refine_cancel(context)
            return {'CANCELLED', 'PASS_THROUGH'}
        if self._refining:
            self._end_pick()
            return self.picked(context, self._view)
        view = self._picked_view(context, event, action == 'click')
        if view is None:      # a click outside every 3D view (sidebar, header): let the UI have it
            return {'PASS_THROUGH'}
        if self.refine_start(context, view, self._region, self._rv3d):
            self._refining, self._view = True, view
            self._set_help(self.refine_help)
            self._refine_at(context, event)
            return {'RUNNING_MODAL'}
        self._end_pick()
        return self.picked(context, view)


class PickDeployOperator(PickOperator):
    """PickOperator for a Deploy button: the click places the rig. Subclasses set `library_name` (empty: no asset needed,
    `path` is "") and implement `place(context, view, path, existing)`.

    Redeploy (opt in with `root_tag` = the rig root's tag property and `rig_label`): with exactly one such
    rig in the scene the card offers Redeploy, the same click flow with `redeploy=True`, which calls
    `place` with that rig as `existing` (move it, touch nothing else) instead of appending a new one.
    Deploy with one rig present first asks "Deploy a second one?" (Yes / No / Redeploy Existing)."""
    library_name = ""
    root_tag = ""
    rig_label = ""
    redeploy: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})   # move the existing rig
    confirmed: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})  # "Deploy a second one?" answered Yes

    def place(self, context, view, path, existing=None):
        raise NotImplementedError

    @classmethod
    def description(cls, context, properties):
        if properties.redeploy:
            return REDEPLOY_TIP
        return (cls.__doc__ or "").strip()

    def existing_rigs(self, context):
        return rig_roots(context.scene.objects, self.root_tag) if self.root_tag else []

    def prepare(self):
        self._path = "" if self.redeploy else library_file(self.library_name) if self.library_name else ""
        if self._path is None:
            self.report({'ERROR'}, f"{self.library_name} not found in your asset libraries")
        return self._path is not None

    def invoke(self, context, event):
        if needs_confirm(len(self.existing_rigs(context)), self.redeploy, self.confirmed):
            return self._ask_second(context)
        return super().invoke(context, event)

    def _ask_second(self, context):
        idname = self.bl_idname

        def draw(menu, _context):
            layout = menu.layout
            layout.operator(idname, text="Yes", icon='ADD').confirmed = True
            layout.operator(SETUPS_OT_dismiss.bl_idname, text="No", icon='X')
            layout.operator(idname, text="Redeploy Existing", icon='FILE_REFRESH').redeploy = True

        context.window_manager.popup_menu(draw, title=f"A {self.rig_label} already exists. Deploy a second one?",
                                          icon='QUESTION')
        return {'INTERFACE'}

    def picked(self, context, view):
        existing = None
        if self.redeploy:
            rigs = self.existing_rigs(context)
            if not show_redeploy(len(rigs)):
                self.report({'ERROR'}, f"Redeploy needs exactly one {self.rig_label} in the scene")
                return {'CANCELLED'}
            existing = rigs[0]
        self.place(context, view, self._path, existing)
        return {'FINISHED'}


def draw_deploy_buttons(layout, operator_idname, count):
    """The card's main button row: Redeploy above Deploy when `count` says it applies."""
    if show_redeploy(count):
        action_row(layout).operator(operator_idname, text="Redeploy", icon='FILE_REFRESH').redeploy = True
    action_row(layout).operator(operator_idname, icon='ADD')


def matching_preset(rig, presets, stored):
    """Name of the preset whose values the rig's custom properties hold now, or None (`stored(prop, value)`
    turns a preset value into the stored one)."""
    def same(a, b):
        if isinstance(b, (list, tuple)):
            return all(abs(x - y) < 1e-3 for x, y in zip(a, b))
        return abs(a - b) < 1e-3
    for name, values in presets.items():
        if all(prop in rig and same(rig[prop], stored(prop, value)) for prop, value in values.items()):
            return name
    return None


def draw_scene_status(layout, scene, root_tag, noun, icon, selected=False):
    """The status line of a Deploy card: how many rigs of the kind the scene holds, then a grey hint where their
    controls are (the Selected card; `selected` = one of them is selected now)."""
    count = len(rig_roots(scene.objects, root_tag))
    if count:
        status(layout, f"{count} {noun}{'' if count == 1 else 's'} in the scene", icon=icon)
        hints(layout, ["Its controls are in Selected above" if selected else f"Select a {noun} to change its controls"])
    else:
        status(layout, f"No {noun} yet", icon='INFO')


def draw_deploy(layout, idname, operator_idname, count, draw_options, existing=None, summary=None):
    """The Deploy section of a setup card: its options first (`draw_options(section_layout)`), then the main buttons
    at the end, so you set up, then press. Open while no rig exists; once one does it folds, shows `summary`
    (the chosen options) at the right and keeps an icon-only + button that deploys with the current options.
    `existing` = how many rigs exist (default `count`)."""
    existing = count if existing is None else existing
    sec = section(layout, idname, "Deploy", icon='ADD', default_closed=bool(existing), right=summary,
                  button=(operator_idname, 'ADD') if existing else None)
    if sec:
        draw_options(sec)
        sec.separator()
        draw_deploy_buttons(sec, operator_idname, count)


classes = (SETUPS_OT_dismiss,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
