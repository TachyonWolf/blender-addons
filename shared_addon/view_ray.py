# SPDX-License-Identifier: GPL-3.0-or-later
"""Rays from the 3D view: what a viewport click points at. Shared by Digit's Assorted Tools (Setups' Deploy
pick, Look At) and Render Presets (Fog Marks), so there is one click picker.

- `region_under_mouse(areas, x, y)`: the 3D view region the screen position is over.
- `viewport_under_mouse(areas, x, y)`: the same, but None over the view's sidebar, tool shelf or header.
- `mouse_ray(region, region_data, coord)`: (origin, direction) through a region pixel.
- `cast_surface(scene, depsgraph, origin, direction, skip=None)`: (hit point, normal, original object) or None;
  `skip(object)` True = look through that object (e.g. decals), the ray goes on behind it.
- `cast_hit(scene, depsgraph, origin, direction, skip=None)`: (hit point, original object) or (None, None).
- `hit_under_mouse(context, event, skip=None)`: all of the above for a modal event.
- `bone_under_mouse(context, event, rigs, max_px)`: (rig, pose bone name) of the shown bone nearest the mouse.
- `begin_click` / `click_kind` / `end_click`: the small click-modal routine (cursor, status text, Esc /
  right-click cancel, viewport navigation passes through).
Nothing here runs in the background."""

from bpy_extras import view3d_utils
from mathutils import Vector

RAY_LENGTH = 1000.0
NAVIGATION_EVENTS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM'}
CANCEL_EVENTS = {'ESC', 'RIGHTMOUSE'}


SKIP_LIMIT = 32        # most objects a ray looks through before it gives up
SKIP_NUDGE = 1e-5      # how far past a skipped hit the ray starts again


def cast_surface(scene, depsgraph, origin, direction, skip=None):
    """(hit point, world normal, original object) of the first hit along the ray that `skip` doesn't reject, or
    None. Skipped objects are looked through: the ray starts again just past their hit."""
    start = origin.copy()
    direction = direction.normalized()
    remaining = RAY_LENGTH
    for _ in range(SKIP_LIMIT):
        hit, location, normal, _index, ob, _matrix = scene.ray_cast(depsgraph, start, direction, distance=remaining)
        if not hit:
            return None
        if skip is None or not skip(ob.original):
            return location.copy(), normal.normalized(), ob.original
        remaining -= (location - start).length + SKIP_NUDGE
        start = location + direction * SKIP_NUDGE
        if remaining <= 0:
            return None
    return None


def cast_hit(scene, depsgraph, origin, direction, skip=None):
    """(hit point, the original object hit) of a ray from origin along direction, or (None, None)."""
    found = cast_surface(scene, depsgraph, origin, direction, skip)
    return (found[0], found[2]) if found else (None, None)


def mouse_ray(region, region_data, coord):
    """(origin, direction) of the ray through the region pixel `coord`."""
    return (view3d_utils.region_2d_to_origin_3d(region, region_data, coord),
            view3d_utils.region_2d_to_vector_3d(region, region_data, coord))


def region_under_mouse(areas, x, y):
    """(window region, its RegionView3D) of the 3D view the screen position x, y is over (the smallest
    one when quad view stacks several), or None. Works for any 3D view, camera view included."""
    best = None
    for area in areas:
        if area.type != 'VIEW_3D':
            continue
        for region in area.regions:
            if (region.type == 'WINDOW' and region.data is not None
                    and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height
                    and (best is None or region.width * region.height < best.width * best.height)):
                best = region
    return (best, best.data) if best else None


def viewport_under_mouse(areas, x, y):
    """Like region_under_mouse, but None when the position is over another region of that 3D view (sidebar, tool
    shelf, header): with region overlap the WINDOW region runs under them, and a button click there is not a
    viewport click."""
    found = region_under_mouse(areas, x, y)
    if found is None:
        return None
    for area in areas:
        if area.type == 'VIEW_3D' and found[0] in list(area.regions):
            for region in area.regions:
                if (region.type != 'WINDOW' and region.width > 1 and region.height > 1
                        and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height):
                    return None
    return found


def hit_under_mouse(context, event, skip=None):
    """(hit point, original object, ray origin, ray direction) for the mouse position of `event`; point and
    object are None when the ray hits nothing (sky). None when the mouse is over no 3D view. Works while
    the click started in the sidebar: the region comes from the mouse position."""
    found = region_under_mouse(context.window.screen.areas, event.mouse_x, event.mouse_y)
    if found is None:
        return None
    region, region_data = found
    origin, direction = mouse_ray(region, region_data, (event.mouse_x - region.x, event.mouse_y - region.y))
    point, ob = cast_hit(context.scene, context.view_layer.depsgraph, origin, direction, skip)
    return point, ob, origin, direction


BONE_PICK_PIXELS = 20   # a bone counts as clicked when its head-tail line passes this close to the mouse


def segment_distance(point, start, end):
    """Distance in pixels from `point` to the 2D segment start-end."""
    line = end - start
    share = 0.0 if line.length_squared == 0 else max(0.0, min(1.0, (point - start).dot(line) / line.length_squared))
    return (start + line * share - point).length


def bone_under_mouse(context, event, rigs, max_px=BONE_PICK_PIXELS):
    """(rig, pose bone name) of the shown bone whose head-tail line, as drawn in the 3D view under the mouse, passes
    nearest the mouse (within max_px pixels), or None. Looks only at the pose bones of `rigs`; hidden bones and
    bones in hidden collections are skipped."""
    found = viewport_under_mouse(context.window.screen.areas, event.mouse_x, event.mouse_y)
    if found is None:
        return None
    region, region_data = found
    mouse = Vector((event.mouse_x - region.x, event.mouse_y - region.y))
    best, best_distance = None, max_px
    for rig in rigs:
        matrix = rig.matrix_world
        for pb in rig.pose.bones:
            collections = pb.bone.collections
            if pb.hide or (len(collections) and not any(c.is_visible_effectively for c in collections)):
                continue
            ends = [view3d_utils.location_3d_to_region_2d(region, region_data, matrix @ p) for p in (pb.head, pb.tail)]
            if None in ends:
                continue
            distance = segment_distance(mouse, *ends)
            if distance < best_distance:
                best, best_distance = (rig, pb.name), distance
    return best


def begin_click(context, operator, cursor, text):
    """Start a click modal for `operator`: modal cursor, status-bar help text, modal handler."""
    context.window.cursor_modal_set(cursor)
    context.workspace.status_text_set(text)
    context.window_manager.modal_handler_add(operator)
    return {'RUNNING_MODAL'}


def click_kind(event):
    """What an event means in a click modal: 'click' (left press), 'cancel' (Esc / right-click), 'pass'
    (viewport navigation, let it through) or 'wait' (ignore it)."""
    if event.type in CANCEL_EVENTS:
        return 'cancel'
    if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        return 'click'
    if event.type in NAVIGATION_EVENTS:
        return 'pass'
    return 'wait'


def end_click(context):
    """Undo what `begin_click` set (the handler ends with the operator's result)."""
    context.window.cursor_modal_restore()
    context.workspace.status_text_set(None)
