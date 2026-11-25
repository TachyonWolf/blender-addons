# SPDX-License-Identifier: GPL-3.0-or-later
"""Asset scan worker. Runs in its own background Blender, never in the VR session:
    blender -b --factory-startup --python asset_worker.py -- <cache folder> <library folder> [<library folder> ...]
It walks each library folder, and for every .blend file that is new or changed (mtime or size) it links the file's
assets (read-only, nothing is saved), reads preview pixels and catalog ids, and writes them into the cache (see
asset_cache.py). Unchanged files are skipped, vanished ones dropped. Prints `DIGITSVR_SCAN done <scanned> <total>`."""
import importlib.util
import os
import sys
import time

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("digits_vr_asset_cache", os.path.join(HERE, "asset_cache.py"))
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


def scan_file(folder, path):
    """The index entry of one .blend file (assets with preview pixels written to the cache)."""
    assets, arrays = [], {}
    try:
        with bpy.data.libraries.load(path, link=True, assets_only=True) as (source, target):
            for attribute in cache.KIND_LABELS:
                names = list(getattr(source, attribute, None) or [])
                if names:
                    setattr(target, attribute, names)
    except Exception as error:      # unreadable or newer-version file: no assets from it
        print(f"DIGITSVR_SCAN skip {path}: {error}")
        return {"assets": []}
    for attribute in cache.KIND_LABELS:
        for datablock in getattr(target, attribute, None) or []:
            if datablock is None or datablock.asset_data is None:
                continue
            preview, size = datablock.preview, None
            if preview is not None and preview.image_size[0] and preview.image_size[1]:
                width, height = preview.image_size
                flat = cache.np.empty(width * height * 4, dtype=cache.np.float32)
                preview.image_pixels_float.foreach_get(flat)
                arrays[len(assets)] = cache.float_to_bytes(flat, width, height)
                size = list(arrays[len(assets)].shape[1::-1])
            assets.append({"name": datablock.name, "kind": attribute,
                           "catalog": datablock.asset_data.catalog_id if datablock.asset_data.catalog_id != "00000000-0000-0000-0000-000000000000" else "",
                           "preview": size})
    while bpy.data.libraries:       # removing one can remove the libraries it pulled in
        bpy.data.libraries.remove(bpy.data.libraries[0])
    return {"assets": assets, "npz": cache.write_previews(folder, path, arrays)}


def main(folder, libraries):
    index = cache.load_index(folder)
    found = {}
    for root in libraries:
        for path in cache.find_blend_files(root):
            found[path] = cache.file_stamp(path)
    scanned = 0
    for path, stamp in found.items():
        if cache.is_stale(index["files"].get(path), stamp):
            entry = scan_file(folder, path)
            if stamp is not None:
                entry.update(mtime=stamp[0], size=stamp[1])
                index["files"][path] = entry
                scanned += 1
                if scanned % 10 == 0:                      # partial results show up while the scan runs
                    cache.save_index(folder, index)
    for path in [path for path in index["files"] if path not in found]:
        del index["files"][path]
    index["scanned_at"] = time.time()
    cache.save_index(folder, index)
    cache.prune(folder, index)
    print(f"DIGITSVR_SCAN done {scanned} {len(index['files'])}")


if "--" in sys.argv:
    arguments = sys.argv[sys.argv.index("--") + 1:]
    if len(arguments) >= 2:
        main(arguments[0], arguments[1:])
