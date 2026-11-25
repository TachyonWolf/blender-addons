# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a screenshot's images go (no bpy): Next to this .blend, a picked folder, or packed into the .blend.

resolve() gets plain paths (the caller turns // paths absolute) and returns a SavePlan, or raises NeedsSave when
the file is unsaved, "Next to this .blend" was chosen and no fallback folder is set.
"""
import os
import re
from dataclasses import dataclass

BLEND, FOLDER, PACK, DEFAULT = "BLEND", "FOLDER", "PACK", "DEFAULT"
SAVE_ITEMS = [
    (BLEND, "Next to this .blend", "Textures/Decals/<target>/ beside the .blend, with relative paths"),
    (FOLDER, "Pick a Folder", "<folder>/<target>/"),
    (PACK, "Pack into .blend", "No files: the images are packed into the .blend"),
]
DEFAULT_ITEM = (DEFAULT, "Default", "The choice in the add-on's Preferences")
SUBFOLDER = os.path.join("Textures", "Decals")
DEFAULT_FALLBACK = os.path.join("~", "Pictures", "Decals")


class NeedsSave(ValueError):
    """Unsaved file, "Next to this .blend" chosen and no fallback folder."""


@dataclass
class SavePlan:
    folder: str = ""         # absolute folder the maps are written to ("" = a temporary folder, for packing)
    relative: bool = False   # store image paths relative to the .blend
    pack: bool = False
    note: str = ""           # said to the user after the run (e.g. the fallback was used)


def safe_name(name):
    """A folder name from an object / collection name."""
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "Target"


def effective_mode(mode, preferred):
    return preferred if mode == DEFAULT else mode


def resolve(mode, blend_path, target_name, picked_folder="", fallback_folder=DEFAULT_FALLBACK):
    """The SavePlan for `mode` (BLEND / FOLDER / PACK). blend_path "" = unsaved file."""
    name = safe_name(target_name)
    if mode == PACK:
        return SavePlan(pack=True)
    if mode == FOLDER:
        if not picked_folder:
            raise ValueError("pick a folder to save to")
        return SavePlan(os.path.join(os.path.abspath(os.path.expanduser(picked_folder)), name), relative=bool(blend_path))
    if blend_path:
        return SavePlan(os.path.join(os.path.dirname(os.path.abspath(blend_path)), SUBFOLDER, name), relative=True)
    if not fallback_folder:
        raise NeedsSave("This file is not saved: save it first, or set a fallback folder in the add-on's Preferences")
    folder = os.path.join(os.path.abspath(os.path.expanduser(fallback_folder)), name)
    return SavePlan(folder, note=f"File not saved: images went to the fallback folder {folder}")
