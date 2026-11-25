# SPDX-License-Identifier: GPL-3.0-or-later
"""A live view of the scene camera above the desk's screen (bpy side). Draws only while the desk is open and the
setting `camera_preview` is on.

TWO small GPUOffScreens (PREVIEW_SIZE; one shows while the other renders), made on the first renders and freed with the desk (never per frame, never per
item). It renders with `GPUOffScreen.draw_view3d` and the camera's own matrices, at most 10 times a second and only
when something changed (a depsgraph update, another camera, another VR shading): an idle scene costs nothing.

Where it renders: NOT in the headset's draw callback. The XR view is itself an off-screen draw, and `draw_view3d`
there fails with "Nested off-screen drawing not supported" (ox, 2026-11-25). So the session tick (`update`) asks for a
render and tags the desktop 3D View for a redraw; a POST_PIXEL handler on its WINDOW region renders the preview there,
between headset frames (a desktop redraw at most 10 times a second, only while the scene changes). The headset
only draws the finished texture. Viewport, blend, depth and both matrices are saved and put back around it (README
gotchas); a failure turns the preview off with a message instead of repeating. The shading is the open 3D View's
own (changing the user's viewport shading from a draw callback was judged not worth the risk)."""
import time

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import desk_layout as layout, desk_qol_math as math_, local_defaults, settings
from .context_helper import view3d_override
from .perf import TIMINGS

WAIT_LIMIT = 1.0      # s: a render asked for but not done by then is asked again (the desktop window did not draw)


SHOW_DELAY = 0.03     # s: a finished picture is shown this much later, so the headset never samples a half-drawn one


class State:
    offscreen = None            # the picture the headset shows
    back = None                 # the next one is drawn here, then the two swap (double buffer: no flicker)
    ready_at = None             # when the picture in `back` may be shown
    batches = None              # (frame batch, image batch)
    last = 0.0
    key = None
    dirty = True
    failed = ""                 # why the preview is off ("" = fine)
    renders = 0                 # tests: it must stay low while nothing changes
    wanted = None               # (camera key, time asked) while a render waits for the desktop redraw
    handlers = []               # (region type, handle) of the desktop draw handlers that render it


STATE = State()


def mark_dirty():
    """The scene changed (session.on_depsgraph_update): render again when due."""
    STATE.dirty = True


def free():
    """Desk closed or session over: drop the GPU objects (made again on the next render) and the desktop handlers."""
    for region_type, handle in STATE.handlers:
        bpy.types.SpaceView3D.draw_handler_remove(handle, region_type)
    STATE.handlers = []
    for offscreen in (STATE.offscreen, STATE.back):
        if offscreen is not None:
            offscreen.free()
    STATE.offscreen = STATE.back = STATE.ready_at = STATE.batches = STATE.key = STATE.wanted = None
    STATE.dirty = True
    STATE.failed = ""


def note(context):
    """The short message the desk shows for the preview ("" = nothing to say)."""
    if not settings.get("camera_preview"):
        return ""
    if context.scene.camera is None:
        return math_.NO_CAMERA
    return STATE.failed


def _matrices(context, camera, fit=True):
    scene = context.scene
    render = scene.render
    width, height = render.resolution_x, render.resolution_y
    projection = camera.calc_matrix_camera(context.evaluated_depsgraph_get(), x=width, y=height,
                                           scale_x=render.pixel_aspect_x, scale_y=render.pixel_aspect_y)
    aspect = width * render.pixel_aspect_x / max(1e-6, height * render.pixel_aspect_y)
    scale_x, scale_y = math_.fit_scales(aspect) if fit else (1.0, 1.0)
    return camera.matrix_world.normalized().inverted_safe(), Matrix.Diagonal((scale_x, scale_y, 1.0, 1.0)) @ projection


def _render(context, camera, space, region):
    if STATE.back is None:
        STATE.back = gpu.types.GPUOffScreen(*math_.PREVIEW_SIZE)
    view_matrix, projection = _matrices(context, camera)
    viewport, blend = gpu.state.viewport_get(), gpu.state.blend_get()
    depth, mask = gpu.state.depth_test_get(), gpu.state.depth_mask_get()
    try:
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            STATE.back.draw_view3d(context.scene, context.view_layer, space, region, view_matrix, projection,
                                        do_color_management=True)
    finally:
        gpu.state.viewport_set(*viewport)
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
        gpu.state.depth_mask_set(mask)
    STATE.renders += 1
    STATE.ready_at = time.perf_counter() + SHOW_DELAY


def _ask_redraw(override):
    """Tag the desktop 3D View for a redraw; its POST_PIXEL handler renders the preview. (A HEADER-region handler
    crashed the NVIDIA driver in a worker thread, ox 2026-11-25: the view's own WINDOW region works.)"""
    override["region"].tag_redraw()
    if not STATE.handlers:
        STATE.handlers = [('WINDOW', bpy.types.SpaceView3D.draw_handler_add(_desktop_draw, (), 'WINDOW', 'POST_PIXEL'))]


def _desktop_draw():
    """POST_PIXEL of a desktop 3D View region, between headset frames: render the preview if one is wanted."""
    if STATE.wanted is None or STATE.failed or STATE.ready_at is not None:
        return
    context = bpy.context
    area, camera = context.area, context.scene.camera
    region = next((region for region in area.regions if region.type == 'WINDOW'), None) if area else None
    if camera is None or region is None:
        return
    key, _asked = STATE.wanted
    STATE.wanted = None
    with TIMINGS.measure("preview"):
        try:
            _render(context, camera, area.spaces.active, region)
        except Exception as error:      # a GPU / context problem: off with a message, not an error every frame
            STATE.failed = "Camera view unavailable"
            print(f"digits_vr: camera preview off: {error}")
            return
    STATE.key, STATE.dirty = key, False


def update(context):
    """Once per session tick while the desk is open: ask for a render (desktop redraw) when one is due."""
    now = time.perf_counter()
    if STATE.ready_at is not None and now >= STATE.ready_at:
        STATE.offscreen, STATE.back, STATE.ready_at = STATE.back, STATE.offscreen, None
    if now - STATE.last < math_.PREVIEW_INTERVAL or STATE.failed or not settings.get("camera_preview"):
        return                      # rendered (or asked) less than an interval ago, or off: no Blender reads at all
    if STATE.wanted is not None:
        if now - STATE.wanted[1] > WAIT_LIMIT:
            STATE.wanted = None     # the desktop window did not redraw (minimised?): ask again later
            STATE.last = now
        return
    camera = context.scene.camera
    if camera is None:
        return
    key = (camera.name_full, context.window_manager.xr_session_settings.shading.type)
    if not math_.should_refresh(now, STATE.last, STATE.dirty or key != STATE.key or (STATE.offscreen is None and STATE.ready_at is None)):
        return
    override = view3d_override(context)
    if override is None:
        STATE.failed = "Open a 3D View"
        return
    STATE.wanted, STATE.last = (key, now), now
    _ask_redraw(override)


def _quad(shader, x, y, w, h, with_uv=False):
    corners = [(*layout.SPEC.pixel_to_local(px, py), 0.0) for px, py in ((x, y + h), (x + w, y + h), (x + w, y), (x, y))]
    data = {"pos": corners}
    if with_uv:
        data["texCoord"] = ((0, 0), (1, 0), (1, 1), (0, 1))
    return batch_for_shader(shader, 'TRI_FAN', data)


_shaders = []


def draw(matrix):
    """After the desk is drawn (desk.draw_extra): the frame, then the picture (once it exists), in the desk's matrix."""
    if STATE.offscreen is None or not settings.get("camera_preview"):
        return
    if not _shaders:
        _shaders[:] = [gpu.shader.from_builtin('UNIFORM_COLOR'), gpu.shader.from_builtin('IMAGE')]
    flat_shader, image_shader = _shaders
    if STATE.batches is None:
        x, y, w, h = math_.PREVIEW_RECT
        STATE.batches = (_quad(flat_shader, x - 6, y - 6, w + 12, h + 12), _quad(image_shader, x, y, w, h, with_uv=True))
    frame, picture = STATE.batches
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    depth_mask = gpu.state.depth_mask_get()
    gpu.state.depth_mask_set(False)      # frame and picture share one plane: writing depth made them z-fight (flicker)
    with gpu.matrix.push_pop():
        gpu.matrix.multiply_matrix(matrix)
        flat_shader.bind()
        flat_shader.uniform_float("color", (*layout.hex_rgb(layout.ACCENT), 0.85))
        frame.draw(flat_shader)
        image_shader.bind()
        image_shader.uniform_sampler("image", STATE.offscreen.texture_color)
        picture.draw(image_shader)
    gpu.state.depth_mask_set(depth_mask)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def output_file(kind=""):
    """(full path, name) of a new picture in the snapshot folder (made if missing): '<blend name><kind>-<date-time>.png',
    never an existing name. Shared by Snapshot and Screenshot."""
    import datetime
    import os
    folder = os.path.expanduser(local_defaults.get("vr_snapshot_folder", math_.SNAPSHOT_FOLDER))
    os.makedirs(folder, exist_ok=True)
    stem = (os.path.splitext(os.path.basename(bpy.data.filepath))[0] or "untitled") + kind
    name = math_.snapshot_name(stem, datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), set(os.listdir(folder)))
    return os.path.join(folder, name), name


def saved_notice(name, now):
    """The desk's 'Saved <name>' message."""
    math_.NOTICE.show("Saved " + name, now, seconds=8.0)


def snapshot(context):
    """The Snapshot buttons (View and File tabs): the scene camera's view as a PNG in the snapshot folder, named after the
    .blend + date-time, never overwriting. One temporary offscreen (freed at once); a button press, not per frame.
    Shows "Saved <name>" on the desk. Returns True when the file was written."""
    import numpy as np
    now = time.perf_counter()
    camera = context.scene.camera
    override = view3d_override(context)
    if camera is None or override is None:
        math_.NOTICE.show(math_.NO_CAMERA if camera is None else "Open a 3D View", now)
        return False
    render = context.scene.render
    width, height = math_.snapshot_size(render.resolution_x, render.resolution_y, render.pixel_aspect_x, render.pixel_aspect_y)
    path, name = output_file()
    offscreen, image = None, None
    try:
        offscreen = gpu.types.GPUOffScreen(width, height)
        view_matrix, projection = _matrices(context, camera, fit=False)
        viewport, blend = gpu.state.viewport_get(), gpu.state.blend_get()
        depth, mask = gpu.state.depth_test_get(), gpu.state.depth_mask_get()
        try:
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                offscreen.draw_view3d(context.scene, context.view_layer, override["area"].spaces.active, override["region"],
                                      view_matrix, projection, do_color_management=True)
            with offscreen.bind():
                pixels = np.asarray(gpu.state.active_framebuffer_get().read_color(0, 0, width, height, 4, 0, 'UBYTE'))
        finally:
            gpu.state.viewport_set(*viewport)
            gpu.state.blend_set(blend)
            gpu.state.depth_test_set(depth)
            gpu.state.depth_mask_set(mask)
        image = bpy.data.images.new("digits_vr_snapshot", width, height, alpha=True)
        image.pixels.foreach_set((pixels.reshape(-1).astype(np.float32) / 255.0))
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()
    except Exception as error:      # no GPU / context problem: a message, not an error in the session timer
        print(f"digits_vr: snapshot failed: {error}")
        math_.NOTICE.show("Snapshot failed", now)
        return False
    finally:
        if offscreen is not None:
            offscreen.free()
        if image is not None:
            bpy.data.images.remove(image)
    saved_notice(name, now)
    return True
