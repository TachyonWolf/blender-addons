# SPDX-License-Identifier: GPL-3.0-or-later
"""The Assets page's controller (bpy side): the page view for the desk model, its button actions, and pulling an
asset off the desk with a grip (laser on a tile, or the hand touching it) or dragging it with trigger + laser (it drops
where the laser points: scene surface, floor plane, laser end). A release away from the desk drops the
asset there (asset_import, one undo step); a release on the desk puts it back. State: asset_state.ASSETS."""
import os
import time

from . import asset_cache, asset_draw, asset_import, asset_scan, asset_state, desk_layout as layout, settings
from .action_map import buzz
from .primitive_shapes import PRIMITIVE_KIND, catalog as primitive_catalog
from .asset_state import ASSETS, AssetDrag, MESSAGE_SECONDS, OFF_DESK_MARGIN, TOUCH_REACH, is_off_desk, laser_drop_point, laser_on_desk, touched_tile
from .size_state import laser_length, scaled
from .hands import HandPose
from .runtime import RUNTIME

HINT = "Pull a thumbnail off with the grip, or hold the trigger and aim the laser where it goes"


PRIMITIVES = asset_scan.Library("Primitives", "", asset_state.APPEND)     # the last entry of the library list


def say(text):
    ASSETS.message, ASSETS.message_time = text, time.monotonic()
    ASSETS.changed()


def all_libraries(context):
    """The Preferences libraries, then the built-in Primitives list."""
    return [*asset_scan.libraries(context), PRIMITIVES]


def _ensure_index():
    if ASSETS.index is None:
        ASSETS.index = asset_cache.load_index(asset_scan.cache_folder())


def _catalogs(library):
    """{uuid: path} of a library, re-read when its catalog file changed."""
    try:
        stamp = os.stat(os.path.join(library.path, asset_cache.CATALOG_FILE)).st_mtime
    except OSError:
        stamp = 0.0
    cached = ASSETS.catalogs.get(library.path)
    if cached is None or cached[0] != stamp:
        cached = ASSETS.catalogs[library.path] = (stamp, asset_cache.read_catalogs(library.path))
    return cached[1]


def _chips(chips, chip_page):
    """(the Catalog pop-up's page of chips, page, pages): All + catalogs, ASSET_CHIP_SLOTS per page."""
    every = [(None, "All"), *chips]
    per_page = layout.ASSET_CHIP_SLOTS
    pages = max(1, -(-len(every) // per_page))
    page = min(max(chip_page, 0), pages - 1)
    return tuple(every[page * per_page:(page + 1) * per_page]), page, pages


def _message(assets_count, scan_started_empty):
    if ASSETS.message:
        return ASSETS.message
    if asset_scan.scanning():
        return "Scanning libraries in the background..."
    if asset_scan.last_error():
        return asset_scan.last_error()
    if scan_started_empty:
        return "Not scanned yet: use Scan Asset Libraries in the sidebar"
    return "" if assets_count else "No assets here"


def build_view(context):
    """The AssetsView for the desk model (rebuilt only when something it shows changed)."""
    if ASSETS.message and time.monotonic() - ASSETS.message_time > MESSAGE_SECONDS:
        ASSETS.message = ""
        ASSETS.changed()
    libraries = all_libraries(context)
    key = (ASSETS.revision, tuple(libraries), asset_scan.finished_count(), asset_scan.scanning())
    if ASSETS.view is not None and ASSETS.view_key == key:
        return ASSETS.view
    _ensure_index()
    if asset_scan.finished_count() != getattr(ASSETS, "seen_scans", 0):
        ASSETS.seen_scans = asset_scan.finished_count()
        ASSETS.index = asset_cache.load_index(asset_scan.cache_folder())
    ASSETS.library = min(ASSETS.library, max(0, len(libraries) - 1))
    shown, chips, tiles, page, pages, total = [], (), (), 0, 1, 0
    chip_page, chip_pages, catalog_label = 0, 1, "All"
    if libraries:
        library = libraries[ASSETS.library]
        is_primitives = library is PRIMITIVES
        everything = primitive_catalog() if is_primitives else asset_cache.library_assets(ASSETS.index, library.path)
        chips_all = [] if is_primitives else asset_cache.catalog_chips(everything, _catalogs(library))
        if ASSETS.catalog is not None and ASSETS.catalog not in {chip[0] for chip in chips_all}:
            ASSETS.catalog = None
        shown = asset_cache.filter_catalog(everything, ASSETS.catalog)
        page_items, ASSETS.page, pages = asset_cache.page_of(shown, ASSETS.page, layout.ASSETS_PER_PAGE)
        ASSETS.tiles[:] = page_items
        chips, chip_page, chip_pages = _chips(chips_all, ASSETS.chip_page)
        ASSETS.chip_page = chip_page
        catalog_label = dict(chips_all).get(ASSETS.catalog, "All") if ASSETS.catalog is not None else "All"
        tiles = tuple((tile["key"], tile["name"], asset_cache.KIND_LABELS.get(tile["kind"], tile["kind"]))
                      for tile in page_items)
        page, total = ASSETS.page, len(shown)
    ASSETS.view = layout.AssetsView(
        libraries=tuple(item.name for item in libraries), library=ASSETS.library, chips=chips, chip_page=chip_page,
        chip_pages=chip_pages, catalog=ASSETS.catalog, catalog_label=catalog_label,
        tiles=tiles, page=page, pages=pages, total=total, primitives=bool(libraries) and libraries[ASSETS.library] is PRIMITIVES,
        message=_message(total, not ASSETS.index["scanned_at"] and not ASSETS.index["files"]))
    ASSETS.view_key = key
    return ASSETS.view


def perform(context, action):
    """A desk button of this page. True when something changed."""
    kind, *arguments = action
    if kind == "asset_library":
        ASSETS.library, ASSETS.catalog, ASSETS.page, ASSETS.chip_page = arguments[0], None, 0, 0
    elif kind == "asset_catalog":
        ASSETS.catalog, ASSETS.page = arguments[0], 0
    elif kind == "asset_chips":
        ASSETS.chip_page += arguments[0] if arguments else 1
    elif kind == "asset_page":
        ASSETS.page += arguments[0]
    elif kind == "asset":
        say(HINT)
        return True
    else:
        return False
    ASSETS.message = ""
    ASSETS.changed()
    return True


def close():
    """The page was left or the desk closed: drop the textures and any drag."""
    ASSETS.reset()
    asset_draw.free()


# ---------------------------------------------------------------------------
# Pulling an asset off the desk
# ---------------------------------------------------------------------------

def _tile_under(context, state, hand, desk_matrix, hover_id):
    """Index of the tile a hand takes: the one its laser is on, else the one its hand touches."""
    if hover_id and hover_id.startswith("asset_") and hover_id[6:].isdigit():
        return int(hover_id[6:])
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    return touched_tile(desk_matrix, pose.aim_location, ASSETS.tiles, layout.PAGE_TOP, scaled(TOUCH_REACH))


def grip_pressed(context, state, hand, desk_matrix, hover_id):
    """Grip press on the Assets page: True when it took a thumbnail (it now follows the hand)."""
    if ASSETS.drag is not None or not ASSETS.tiles:
        return False
    return _take(context, state, hand, _tile_under(context, state, hand, desk_matrix, hover_id), laser=False)


def _take(context, state, hand, index, laser):
    """Start a drag of tile `index` (None / out of range: nothing). A primitive outside Object mode is refused with a
    buzz and a note. True when the press was used."""
    libraries = all_libraries(context)
    if index is None or index >= len(ASSETS.tiles) or ASSETS.library >= len(libraries):
        return False
    tile = ASSETS.tiles[index]
    reason = asset_import.precheck(context, tile) if tile["kind"] == PRIMITIVE_KIND else ""
    if reason:
        say(reason)
        buzz(context, state, hand, duration=0.08, amplitude=0.8)
        return True
    ASSETS.drag = AssetDrag(hand, tile, libraries[ASSETS.library], tile["key"], laser=laser)
    ASSETS.changed()
    asset_draw.sync_textures()
    buzz(context, state, hand, duration=0.02, amplitude=0.4)
    return True


def trigger_pressed(context, state, hand, hover_id):
    """Trigger pull with the laser on a thumbnail: start a laser drag (the preview follows the laser, the release
    drops it where it points). True when it took a thumbnail. The desk already won over the scene."""
    if ASSETS.drag is not None or not ASSETS.tiles or not (hover_id or "").startswith("asset_"):
        return False
    return _take(context, state, hand, int(hover_id[6:]), laser=True)


def laser_point(context, state, hand):
    """(world point, kind) a laser drag points at: the scene surface, else the floor plane, else the laser's end."""
    pose = HandPose(context, state, hand, with_grip_rotation=False)
    length = laser_length()
    hit = context.scene.ray_cast(context.evaluated_depsgraph_get(), pose.aim_location, pose.aim_direction,
                                 distance=length)
    return laser_drop_point(pose.aim_location, pose.aim_direction, length, hit[1] if hit[0] else None,
                            settings.get("plane_height"))


def update_drag(context, state, desk_matrix):
    """Each tick: a laser drag follows the laser and ends on the trigger's release; a grip pull-off ends on the grip's
    release. The release drops the asset (away from the desk) or puts it back (laser on the desk / hand on it)."""
    drag = ASSETS.drag
    if drag is None:
        return
    hand_state = RUNTIME.hands[drag.hand]
    if drag.laser:
        if hand_state.trigger_down:
            drag.point, _kind = laser_point(context, state, drag.hand)
            return
        pose = HandPose(context, state, drag.hand, with_grip_rotation=False)
        location = None if laser_on_desk(desk_matrix, pose.aim_location, pose.aim_direction) else drag.point
    elif hand_state.grip_down:
        return
    else:
        location = asset_draw.drag_location(state, context, drag.hand)
        location = location if is_off_desk(desk_matrix, location, scaled(OFF_DESK_MARGIN)) else None
    ASSETS.drag = None
    ASSETS.changed()
    if location is None:
        say("Back on the desk: nothing added")
        return
    drop(context, drag, location)
    buzz(context, state, drag.hand, duration=0.03, amplitude=0.5)


def drop(context, drag, location):
    """Import the held asset at `location` as ONE undo step; the page says what happened."""
    from .tools import push_undo       # tools imports the grab code: only needed at a drop
    try:
        done, text = asset_import.place(context, drag.tile, drag.library, location)
    except (RuntimeError, ReferenceError, TypeError, ValueError, OSError) as error:
        done, text = False, f"Could not add {drag.tile['name']}: {error}"
    if done:
        push_undo(f"VR Add {drag.tile['name']}")
        RUNTIME.cache.all_dirty = True
        RUNTIME.cache.objects = None
        RUNTIME.cache.version += 1
    say(text)
    return done
