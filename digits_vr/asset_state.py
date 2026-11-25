# SPDX-License-Identifier: GPL-3.0-or-later
"""The Assets page's live state (data only; no bpy, no gpu) and the pure rules for pulling an asset off the desk.
Dropped by asset_page.close() (tab left, desk closed) and by the central teardown."""
from dataclasses import dataclass, field

from mathutils import Vector

from . import desk_layout as layout
from .desk_state import screen_hit

OFF_DESK_MARGIN = 0.12      # metres beyond the desk body (or in front of its screen) where a release drops the asset
TOUCH_REACH = 0.05          # a hand this close to a tile (metres) can pull it
MESSAGE_SECONDS = 6.0       # how long a drop result stays in the pager row

# bpy.data collection name -> how a drop treats it
PLACE_OBJECT, PLACE_INSTANCE, APPLY_MATERIAL, SET_WORLD, ADD_MODIFIER, REFUSE = (
    'PLACE_OBJECT', 'PLACE_INSTANCE', 'APPLY_MATERIAL', 'SET_WORLD', 'ADD_MODIFIER', 'REFUSE')
LINK, APPEND, APPEND_REUSE = 'LINK', 'APPEND', 'APPEND_REUSE'


@dataclass
class AssetDrag:
    """An asset pulled off its tile and held by a hand."""
    hand: str
    tile: dict              # the asset dict (asset_cache.library_assets)
    library: object         # asset_scan.Library
    texture_key: str
    laser: bool = False     # True: a trigger + laser drag (drops where the laser points); False: a grip pull-off
    point: object = None    # laser drag: world point the preview floats at and the release drops on


@dataclass
class AssetsState:
    index: object = None            # asset_cache index (loaded lazily), None = not loaded
    library: int = 0                # open library (index in the preferences list)
    catalog: object = None          # chosen catalog id (None = all)
    page: int = 0
    chip_page: int = 0
    message: str = ""
    message_time: float = 0.0
    seen_scans: int = 0             # scans whose results the index already holds
    revision: int = 0               # bumped by every change the screen shows (the model rebuilds only then)
    view: object = None             # the last AssetsView and the key it was made for
    view_key: object = None
    tiles: list = field(default_factory=list)       # asset dicts of the page on show, in tile order
    drag: object = None             # AssetDrag while a hand holds an asset
    catalogs: dict = field(default_factory=dict)    # library path -> (mtime, {uuid: path})

    def changed(self):
        self.revision += 1

    def reset(self):
        """Back to a closed page (library and catalog choices stay; they are cheap and handy to keep)."""
        self.tiles.clear()
        self.drag = None
        self.view = self.view_key = None
        self.message = ""


ASSETS = AssetsState()


def placement(kind):
    """How a drop treats an asset of this bpy.data collection (see asset_import)."""
    return {"objects": PLACE_OBJECT, "collections": PLACE_INSTANCE, "materials": APPLY_MATERIAL, "worlds": SET_WORLD,
            "node_groups": ADD_MODIFIER}.get(kind, REFUSE)


def is_off_desk(desk_matrix, point, margin=OFF_DESK_MARGIN):
    """True when a world point is clear of the desk: outside its body by more than `margin` (metres), or farther than
    that in front of or behind the screen. Releasing an asset there drops it."""
    local = desk_matrix.inverted_safe() @ Vector(point)
    scale = desk_matrix.median_scale or 1.0
    half_width = layout.DESK_WIDTH * layout.METERS_PER_PIXEL / 2
    half_height = layout.DESK_HEIGHT * layout.METERS_PER_PIXEL / 2
    limit = margin / scale
    return abs(local.z) > limit or abs(local.x) > half_width + limit or abs(local.y) > half_height + limit


def touched_tile(desk_matrix, point, tiles, top, reach=TOUCH_REACH):
    """Index of the tile a hand at world `point` touches (inside its box, within `reach` of the screen), or None."""
    local = desk_matrix.inverted_safe() @ Vector(point)
    scale = desk_matrix.median_scale or 1.0
    if abs(local.z) > reach / scale:
        return None
    pixel_x, pixel_y = layout.local_to_pixel(local.x, local.y)
    for index in range(len(tiles)):
        x, y, w, h = layout.asset_tile_rect(index, top)
        if x <= pixel_x <= x + w and y <= pixel_y <= y + h:
            return index
    return None


# What a laser drag points at
ON_SURFACE, ON_FLOOR, IN_AIR = 'ON_SURFACE', 'ON_FLOOR', 'IN_AIR'


def laser_drop_point(origin, direction, length, scene_hit, floor_z):
    """(world point, ON_SURFACE / ON_FLOOR / IN_AIR) where a laser drag drops. `scene_hit` = the scene ray hit point
    (or None). A surface hit wins (like Blender's asset drop onto a surface); else the floor plane z = floor_z where the
    laser crosses it within `length`; else the laser's end."""
    if scene_hit is not None:
        return Vector(scene_hit), ON_SURFACE
    origin, direction = Vector(origin), Vector(direction).normalized()
    if abs(direction.z) > 1e-6:
        distance = (floor_z - origin.z) / direction.z
        if 0.0 < distance <= length:
            return origin + direction * distance, ON_FLOOR
    return origin + direction * length, IN_AIR


def laser_on_desk(desk_matrix, origin, direction):
    """True when the laser points at the desk screen: a laser drag released there is cancelled."""
    hit = screen_hit(desk_matrix, origin, direction)
    return hit is not None and layout.on_screen(hit[0], hit[1])
