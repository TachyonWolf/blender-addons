# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU side of the Assets page: thumbnail textures (uploaded lazily, a few per render, only for the tiles on show; all
released when the page closes), the tiles drawn into the desk's offscreen, and the small preview that follows the hand
while an asset is pulled off the desk."""
import blf
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import asset_cache, asset_scan, desk_layout as layout, primitive_icons
from .primitive_shapes import PRIMITIVE_KIND
from .asset_state import ASSETS

UPLOADS_PER_RENDER = 4          # a texture upload is about 0.25 ms: a page fills over a few frames, not in one
DRAG_SIZE = 0.09                # metres: the preview in the hand
DRAG_FORWARD = 0.03             # metres beyond the fingertip (along its aim) where the preview floats and drops
_textures = {}                  # asset key -> GPUTexture, or None when the asset has no preview
_drag_batch = None
_drag_blank = None                # the square shown while the asset has no preview: [flat shader, batch]
_drag_matrix = None
_image = None
UNIT_UV = ((0, 0), (1, 0), (1, 1), (0, 1))     # texture corners of a quad drawn as a TRI_FAN


def _shader():
    global _image
    if _image is None:
        _image = gpu.shader.from_builtin('IMAGE')
    return _image


def free():
    """The page closed (or the session ended): drop every texture."""
    global _drag_batch, _drag_blank, _drag_matrix
    _textures.clear()
    _drag_batch = _drag_blank = _drag_matrix = None


def _upload(tile):
    """Make the texture of a tile from the cache (None when it has no preview)."""
    if tile["kind"] == PRIMITIVE_KIND:
        return texture_from_pixels(primitive_icons.pixels(tile["name"]))
    entry = ASSETS.index["files"].get(tile["file"]) if ASSETS.index else None
    pixels = asset_cache.load_preview(asset_scan.cache_folder(), entry, tile["position"]) if entry else None
    if pixels is None:
        return None
    return texture_from_pixels(pixels)


def texture_from_pixels(pixels):
    """A GPUTexture of a (height, width, 4) uint8 array (bottom row first). Also help_art.py's."""
    height, width = pixels.shape[:2]
    flat = np.ascontiguousarray(pixels, dtype=np.uint8).reshape(-1)
    try:
        return gpu.types.GPUTexture((width, height), format='RGBA8',
                                    data=gpu.types.Buffer('UBYTE', flat.size, flat))
    except (TypeError, ValueError, RuntimeError):      # older builds want float data
        floats = (flat.astype(np.float32) / 255.0)
        return gpu.types.GPUTexture((width, height), format='RGBA16F',
                                    data=gpu.types.Buffer('FLOAT', floats.size, floats))


def sync_textures():
    """Upload missing textures of the tiles on show (and the dragged one), release the rest. Returns how many tiles
    still wait (the screen renders again for them)."""
    wanted = {tile["key"]: tile for tile in ASSETS.tiles}
    if ASSETS.drag is not None:
        wanted[ASSETS.drag.tile["key"]] = ASSETS.drag.tile
    for key in [key for key in _textures if key not in wanted]:
        del _textures[key]
    budget, waiting = UPLOADS_PER_RENDER, 0
    for key, tile in wanted.items():
        if key in _textures:
            continue
        if budget <= 0:
            waiting += 1
            continue
        _textures[key] = _upload(tile)
        budget -= 1
    return waiting


def texture(key):
    return _textures.get(key)


def _fit(text, width):
    """`text` shortened with '..' so it fits `width` pixels at the current font size."""
    if blf.dimensions(0, text)[0] <= width:
        return text
    while len(text) > 1 and blf.dimensions(0, text + "..")[0] > width:
        text = text[:-1]
    return text + ".."


def tile_key(widget):
    """The asset key of a THUMB widget (ids are asset_<index>), or None when the page has no such tile."""
    index = int(widget.id.rsplit("_", 1)[1])
    return ASSETS.tiles[index]["key"] if index < len(ASSETS.tiles) else None


def thumb_rect(widget):
    """(x, y, w, h) of the thumbnail inside a tile (pixel space, top-left origin)."""
    size = layout.TILE_THUMB
    return widget.x + (widget.w - size) / 2, widget.y + max(8, widget.h - 175), size, size     # name below it


def textured_quad(shader, corners, texture_corners=UNIT_UV):
    """Batch of one textured quad (4 corners, bottom-left first, drawn as a TRI_FAN)."""
    return batch_for_shader(shader, 'TRI_FAN', {"pos": corners, "texCoord": texture_corners})


def image_quad(shader, x, y, w, h, height):
    """Batch of a textured rect: pixel space (top-left origin) in an offscreen `height` pixels high."""
    return textured_quad(shader, ((x, height - (y + h)), (x + w, height - (y + h)), (x + w, height - y), (x, height - y)))


def draw_tiles(widgets, shader, rgba, height):
    """Inside the desk offscreen (`height` pixels high; pixel projection, bottom-left origin): the thumbnails and tile names."""
    tiles = [widget for widget in widgets if widget.kind == layout.THUMB]
    if not tiles:
        return
    gpu.state.blend_set('ALPHA')
    shader.bind()
    for widget in tiles:
        loaded = _textures.get(tile_key(widget))
        if loaded is None:
            continue
        x, y, w, h = thumb_rect(widget)
        batch = image_quad(shader, x, y, w, h, height)
        shader.uniform_sampler("image", loaded)
        batch.draw(shader)
    gpu.state.blend_set('NONE')
    blf.size(0, tiles[0].size)
    blf.color(0, *rgba(layout.TEXT))
    for widget in tiles:
        text = _fit(widget.label, widget.w - 12)
        width, _height = blf.dimensions(0, text)
        blf.position(0, widget.x + (widget.w - width) / 2, height - (widget.y + widget.h - 16), 0)
        blf.draw(0, text)


def _drag_quad(shader):
    half = DRAG_SIZE / 2
    return textured_quad(shader, ((-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)))


def drag_location(state, context, hand):
    """World point where a held asset floats (and where a release drops it). A laser drag: where the laser points."""
    drag = ASSETS.drag
    if drag is not None and drag.laser and drag.point is not None:
        return drag.point
    from .hands import HandPose
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    return pose.aim_location + pose.aim_direction * DRAG_FORWARD


def draw_drag(new_frame):
    """The small preview that follows the hand (called by the desk panel's draw_extra once per eye; billboard towards the head)."""
    global _drag_batch, _drag_blank, _drag_matrix
    drag = ASSETS.drag
    if drag is None:
        return
    loaded = _textures.get(drag.texture_key)
    shader = _shader()
    if _drag_batch is None:
        _drag_batch = _drag_quad(shader)
    if new_frame or _drag_matrix is None:
        import bpy
        context = bpy.context
        state = context.window_manager.xr_session_state
        if state is None:
            return
        position = drag_location(state, context, drag.hand)
        toward_head = Vector(state.viewer_pose_location) - position
        rotation = toward_head.to_track_quat('Z', 'Y') if toward_head.length > 1e-4 else Matrix.Identity(3).to_quaternion()
        _drag_matrix = Matrix.LocRotScale(position, rotation, (1, 1, 1))
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    with gpu.matrix.push_pop():
        gpu.matrix.multiply_matrix(_drag_matrix)
        shader.bind()
        if loaded is not None:
            shader.uniform_sampler("image", loaded)
            _drag_batch.draw(shader)
        else:                                   # no preview: a plain pale blue square
            if _drag_blank is None:
                flat = gpu.shader.from_builtin('UNIFORM_COLOR')
                _drag_blank = (flat, batch_for_shader(flat, 'TRI_FAN', {"pos": ((-0.04, -0.04, 0), (0.04, -0.04, 0),
                                                                                (0.04, 0.04, 0), (-0.04, 0.04, 0))}))
            flat, blank = _drag_blank
            flat.bind()
            flat.uniform_float("color", layout.rgba(layout.ACCENT, 0.9))
            blank.draw(flat)
    gpu.state.blend_set('NONE')
