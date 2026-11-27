# SPDX-License-Identifier: GPL-3.0-or-later
"""The asset scan cache: what the Assets tab shows. Pure Python + numpy (no bpy, no relative imports), so the scan
worker (a background `blender -b`) loads this file by path and the headless tests import it.

Layout in the cache folder:
  assets_index.json   {"version", "scanned_at", "files": {blend path: {"mtime", "size", "npz", "assets": [...]}}}
  previews/<id>.npz   one array per asset with a preview ("p<position>": uint8 RGBA, rows bottom-up like Blender)
An asset entry: {"name", "kind" (the bpy.data collection name: objects, collections, materials, ...), "catalog"
(UUID or ""), "preview": [w, h] or null}. A file is stale when its mtime or size differ from the entry."""
import hashlib
import json
import os

import numpy as np

VERSION = 1
INDEX_NAME = "assets_index.json"
PREVIEW_FOLDER = "previews"
PREVIEW_SIZE = 128                  # previews are stored at this size (the desk tile shows them at about 128 px)
CATALOG_FILE = "blender_assets.cats.txt"
NO_CATALOG = ""
SKIP_FOLDERS = ("Previews", "RefImages")   # preview image folders hold no asset files

# bpy.data collection name -> what the Assets tab calls it
KIND_LABELS = {"objects": "Object", "collections": "Collection", "materials": "Material", "worlds": "World",
               "node_groups": "Node group", "actions": "Action", "meshes": "Mesh", "images": "Image",
               "brushes": "Brush", "textures": "Texture", "lights": "Light", "cameras": "Camera",
               "armatures": "Armature", "curves": "Curve", "grease_pencils": "Grease Pencil",
               "linestyles": "Line style", "palettes": "Palette", "workspaces": "Workspace"}


def parse_catalogs(text):
    """{uuid: path} from the text of blender_assets.cats.txt (lines `uuid:path/to/catalog:Simple Name`)."""
    catalogs = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("VERSION"):
            continue
        parts = line.split(":", 2)
        if len(parts) >= 2 and parts[0] and parts[1]:
            catalogs[parts[0]] = parts[1]
    return catalogs


def read_catalogs(library_path):
    """{uuid: path} of a library folder ({} when it has no catalog file)."""
    try:
        with open(os.path.join(library_path, CATALOG_FILE), encoding="utf-8") as handle:
            return parse_catalogs(handle.read())
    except OSError:
        return {}


def index_path(folder):
    return os.path.join(folder, INDEX_NAME)


def empty_index():
    return {"version": VERSION, "scanned_at": 0.0, "files": {}}


def load_index(folder):
    """The index of a cache folder, or an empty one when there is none (or it is unreadable / from another version)."""
    try:
        with open(index_path(folder), encoding="utf-8") as handle:
            index = json.load(handle)
        if isinstance(index, dict) and index.get("version") == VERSION and isinstance(index.get("files"), dict):
            return index
    except (OSError, ValueError):
        pass
    return empty_index()


def save_index(folder, index):
    """Write atomically (temp file + rename): the game never reads half an index while the worker writes."""
    os.makedirs(folder, exist_ok=True)
    path = index_path(folder)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(index, handle)
    os.replace(temp, path)


def find_blend_files(root):
    """Every .blend file under `root` (no .blend1 backups, no hidden or preview folders), sorted."""
    found = []
    for folder, subfolders, names in os.walk(root):
        subfolders[:] = sorted(name for name in subfolders if not name.startswith(".") and name not in SKIP_FOLDERS)
        found.extend(os.path.join(folder, name) for name in names if name.lower().endswith(".blend"))
    return sorted(found)


def file_stamp(path):
    """(mtime, size) of a file, or None when it is gone."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_mtime, stat.st_size


def is_stale(entry, stamp):
    return entry is None or stamp is None or (entry.get("mtime"), entry.get("size")) != tuple(stamp)


def npz_name(blend_path):
    return hashlib.sha1(blend_path.encode("utf-8")).hexdigest()[:16] + ".npz"


def shrink(pixels, size=PREVIEW_SIZE):
    """(h, w, 4) uint8 -> at most size x size by block averaging (whole-number factors) or left as is."""
    height, width = pixels.shape[:2]
    factor = max(height, width) // size
    if factor < 2 or height % factor or width % factor:
        return pixels
    blocks = pixels.reshape(height // factor, factor, width // factor, factor, 4).astype(np.float32)
    return blocks.mean(axis=(1, 3)).round().astype(np.uint8)


def float_to_bytes(pixels, width, height):
    """Flat float RGBA 0..1 (bottom-up rows, as Blender gives them) -> (h, w, 4) uint8, shrunk."""
    array = np.asarray(pixels, dtype=np.float32).reshape(height, width, 4)
    return shrink((np.clip(array, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))


def write_previews(folder, blend_path, arrays):
    """Save {position: uint8 array} of one file; returns the npz name (None when there are no previews)."""
    if not arrays:
        return None
    os.makedirs(os.path.join(folder, PREVIEW_FOLDER), exist_ok=True)
    name = npz_name(blend_path)
    target = os.path.join(folder, PREVIEW_FOLDER, name)
    temp = target + ".tmp.npz"
    np.savez(temp, **{f"p{position}": array for position, array in arrays.items()})
    os.replace(temp, target)
    return name


def load_preview(folder, entry, position):
    """The uint8 (h, w, 4) preview of asset number `position` of a file entry, or None."""
    if not entry.get("npz"):
        return None
    try:
        with np.load(os.path.join(folder, PREVIEW_FOLDER, entry["npz"])) as archive:
            key = f"p{position}"
            return np.array(archive[key]) if key in archive.files else None
    except (OSError, ValueError):
        return None


def prune(folder, index):
    """Remove preview files nothing in the index points to."""
    keep = {entry["npz"] for entry in index["files"].values() if entry.get("npz")}
    target = os.path.join(folder, PREVIEW_FOLDER)
    if os.path.isdir(target):
        for name in os.listdir(target):
            if name not in keep:
                try:
                    os.remove(os.path.join(target, name))
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Reading the index for the Assets tab
# ---------------------------------------------------------------------------

def under(root, path):
    """True when `path` lies inside the folder `root`."""
    root = os.path.join(os.path.normpath(root), "")
    return os.path.normpath(path).startswith(root)


def library_assets(index, root):
    """Every asset of a library folder as dicts with its file and position added, sorted by name:
    {"file", "position", "name", "kind", "catalog", "preview", "key"}."""
    found = []
    for path, entry in index["files"].items():
        if under(root, path):
            for position, asset in enumerate(entry["assets"]):
                found.append({**asset, "file": path, "position": position,
                              "key": f"{path}|{asset['kind']}|{asset['name']}"})
    return sorted(found, key=lambda asset: (asset["name"].lower(), asset["file"]))


def catalog_chips(assets, catalogs):
    """[(catalog id, label)] of the catalogs that hold assets here: label = catalog path, 'Unsorted' for none; sorted
    by label."""
    used = {asset["catalog"] for asset in assets}
    chips = [(identifier, catalogs.get(identifier, "Unknown")) for identifier in used if identifier != NO_CATALOG]
    chips.sort(key=lambda chip: chip[1].lower())
    if NO_CATALOG in used:
        chips.append((NO_CATALOG, "Unsorted"))
    return chips


def filter_catalog(assets, catalog):
    """Assets in one catalog; None = all."""
    return assets if catalog is None else [asset for asset in assets if asset["catalog"] == catalog]


def page_of(items, page, per_page):
    """(items on the page, page number clamped into range, page count)."""
    pages = max(1, -(-len(items) // per_page))
    page = min(max(page, 0), pages - 1)
    return items[page * per_page:(page + 1) * per_page], page, pages
