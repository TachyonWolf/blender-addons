# SPDX-License-Identifier: GPL-3.0-or-later
"""The scene camera's live picture on the Cam view panel (camera_panel.py) (bpy side). Renders only while that panel
is open.

TWO small GPUOffScreens (PREVIEW_SIZE; one shows while the other renders), made on the first renders and freed with the
panel (never per frame, never per item). It renders with `GPUOffScreen.draw_view3d` and the camera's own matrices, at most
10 times a second and only when something changed: a depsgraph update (also those made by VR grabs, rendered once the
grab ends), another camera, the camera moved or its lens changed, another VR shading, or the Update button
(`request_update`). An idle scene costs nothing.

Where it renders: NOT in the headset's draw callback. The XR view is itself an off-screen draw, and `draw_view3d`
there fails with "Nested off-screen drawing not supported" (ox, 2026-11-25). So the session tick (`update`) asks for a
render and tags the desktop 3D View for a redraw; a POST_PIXEL handler on its WINDOW region renders the preview there,
between headset frames. The headset only draws the finished texture, on the panel, with depth like the panel itself.
Viewport, blend, depth and both matrices are saved and put back around it (README gotchas); a failure turns the preview
off with a message until Update is pressed. The shading is the open 3D View's own (changing the user's viewport shading
from a draw callback was judged not worth the risk)."""
import time

import bpy
import gpu
from mathutils import Matrix

from . import asset_draw, desk_qol_math as math_, local_defaults
from .context_helper import view3d_override
from .perf import TIMINGS
from .runtime import RUNTIME

WAIT_LIMIT = 1.0      # s: a render asked for but not done by then is asked again (the desktop window did not draw)


SHOW_DELAY = 0.03     # s: a finished picture is shown this much later, so the headset never samples a half-drawn one


class State:
    offscreen = None            # the picture the headset shows
    back = None                 # the next one is drawn here, then the two swap (double buffer: no flicker)
    ready_at = None             # when the picture in `back` may be shown
    last = 0.0
    key = None
    dirty = True
    failed = ""                 # why the preview is off ("" = fine; Update tries again)
    picture = None              # the image quad on the panel (built in the tick, never in the draw callback)
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
    STATE.offscreen = STATE.back = STATE.ready_at = STATE.picture = STATE.key = STATE.wanted = None
    STATE.dirty = True
    STATE.failed = ""


def request_update():
    """The Update button: render again on the next tick, even if nothing seems changed; a failed preview tries again."""
    STATE.dirty, STATE.last, STATE.failed = True, 0.0, ""


def _camera_key(context, camera):
    """What the picture depends on besides the scene: which camera, where it is, its lens, the VR shading."""
    return (camera.name_full, tuple(map(tuple, camera.matrix_world)), getattr(camera.data, "lens", 0.0),
            context.window_manager.xr_session_settings.shading.type)


def note(context):
    """The short message the Cam view panel shows ("" = nothing to say)."""
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


def update(context, spec, rect):
    """Once per session tick while the Cam view panel is open: build the picture quad once (pixels `rect` of the panel
    `spec`), and ask the desktop view to render when due (no-op while nothing changed; a VR grab first ends)."""
    now = time.perf_counter()
    if STATE.picture is None:
        STATE.picture = _quad(_image_shader(), spec, rect)
    if STATE.ready_at is not None and now >= STATE.ready_at:
        STATE.offscreen, STATE.back, STATE.ready_at = STATE.back, STATE.offscreen, None
    if now - STATE.last < math_.PREVIEW_INTERVAL or STATE.failed or RUNTIME.grabbed:
        return                      # rendered (or asked) less than an interval ago, off, or a grab moves things each frame
    if STATE.wanted is not None:
        if now - STATE.wanted[1] > WAIT_LIMIT:
            STATE.wanted = None     # the desktop window did not redraw (minimised?): ask again later
            STATE.last = now
        return
    camera = context.scene.camera
    if camera is None:
        return
    key = _camera_key(context, camera)
    if not math_.should_refresh(now, STATE.last, STATE.dirty or key != STATE.key or (STATE.offscreen is None and STATE.ready_at is None)):
        return
    override = view3d_override(context)
    if override is None:
        STATE.failed = "Open a 3D View"
        return
    STATE.wanted, STATE.last = (key, now), now
    _ask_redraw(override)


PICTURE_LIFT = 0.0005     # m (times the panel's scale): the picture sits this far in front of the panel, so it writes depth
                          # without fighting the panel's own surface


def _quad(shader, spec, rect):
    x, y, w, h = rect
    corners = [(*spec.pixel_to_local(px, py), PICTURE_LIFT) for px, py in ((x, y + h), (x + w, y + h), (x + w, y), (x, y))]
    return asset_draw.textured_quad(shader, corners)


_shaders = []


def _image_shader():
    if not _shaders:
        _shaders.append(gpu.shader.from_builtin('IMAGE'))
    return _shaders[0]


def draw(matrix):
    """After the Cam view panel is drawn (its draw_extra), in its matrix: the picture, once it exists. Depth tested AND
    written, like every panel, so what is in front of it hides it and what is behind it stays hidden."""
    if STATE.offscreen is None or STATE.picture is None:
        return
    shader = _image_shader()
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.depth_mask_set(True)
    with gpu.matrix.push_pop():
        gpu.matrix.multiply_matrix(matrix)
        shader.bind()
        shader.uniform_sampler("image", STATE.offscreen.texture_color)
        STATE.picture.draw(shader)
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


def render_pixels(context, override, view_matrix, projection, width, height, look=None):
    """(height, width, 4) uint8, bottom row first: the scene drawn from these matrices through the desktop 3D View of
    `override`, in one temporary offscreen (freed at once). Call it between headset frames (a button, the session tick),
    never inside the XR draw (README gotchas). `look`: a View3DShading (the headset's) used instead of the view's own,
    with the view's overlays off, both put back after; None = the 3D View as it is."""
    import numpy as np
    space = override["area"].spaces.active
    offscreen = gpu.types.GPUOffScreen(width, height)
    viewport, blend = gpu.state.viewport_get(), gpu.state.blend_get()
    depth, mask = gpu.state.depth_test_get(), gpu.state.depth_mask_get()
    put_back = _borrow_look(space, look) if look is not None else None
    try:
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            offscreen.draw_view3d(context.scene, context.view_layer, space, override["region"], view_matrix, projection,
                                  do_color_management=True)
        with offscreen.bind():
            pixels = np.asarray(gpu.state.active_framebuffer_get().read_color(0, 0, width, height, 4, 0, 'UBYTE'))
    finally:
        if put_back is not None:
            put_back()
        gpu.state.viewport_set(*viewport)
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
        gpu.state.depth_mask_set(mask)
        offscreen.free()
    return pixels.reshape(height, width, 4)


def _copyable(value):
    return tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


def _borrow_look(space, look):
    """Give the 3D View `space` the shading `look` and no overlays (draw_view3d draws with the view's own); returns the
    call that puts them back. `type` and `light` go first: other values only exist for some types."""
    names = [prop.identifier for prop in look.bl_rna.properties
             if not prop.is_readonly and prop.type not in {'POINTER', 'COLLECTION'} and prop.identifier != "rna_type"]
    names.sort(key=lambda name: (name != "type", name != "light"))
    shading = space.shading
    saved = [(name, _copyable(getattr(shading, name))) for name in names]
    show_overlays = space.overlay.show_overlays

    def set_all(values):
        for name, value in values:
            try:
                setattr(shading, name, value)
            except (AttributeError, TypeError, ValueError):     # a value the other type does not offer
                pass
    set_all([(name, _copyable(getattr(look, name))) for name in names])
    space.overlay.show_overlays = False

    def put_back():
        set_all(saved)
        space.overlay.show_overlays = show_overlays
    return put_back


def snapshot(context):
    """The Snapshot buttons (View and File tabs): the scene camera's view as a PNG in the snapshot folder, named after the
    .blend + date-time, never overwriting. One temporary offscreen (freed at once); a button press, not per frame.
    Shows "Saved <name>" on the desk. Returns True when the file was written."""
    now = time.perf_counter()
    camera = context.scene.camera
    override = view3d_override(context)
    if camera is None or override is None:
        math_.NOTICE.show(math_.NO_CAMERA if camera is None else "Open a 3D View", now)
        return False
    render = context.scene.render
    width, height = math_.snapshot_size(render.resolution_x, render.resolution_y, render.pixel_aspect_x, render.pixel_aspect_y)
    path, name = output_file()
    image = None
    try:
        pixels = render_pixels(context, override, *_matrices(context, camera, fit=False), width, height)
        image = bpy.data.images.new("digits_vr_snapshot", width, height, alpha=True)
        image.pixels.foreach_set((pixels.reshape(-1).astype("float32") / 255.0))
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()
    except Exception as error:      # no GPU / context problem: a message, not an error in the session timer
        print(f"digits_vr: snapshot failed: {error}")
        math_.NOTICE.show("Snapshot failed", now)
        return False
    finally:
        if image is not None:
            bpy.data.images.remove(image)
    saved_notice(name, now)
    return True
