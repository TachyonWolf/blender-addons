# SPDX-License-Identifier: GPL-3.0-or-later
"""Output options shared by the Combine Into One Model and Game Rig cards: a typed file name and a folder (both empty = automatic),
the path they resolve to, and the "Output" sub-card that draws them. Only this add-on uses it.

    path = output_path(name, folder, "Hero-Whole", ".blend", bpy.data.filepath)   # None = nowhere to put it
"""
import os

import bpy
from bpy.props import StringProperty

from .object_tools import free_path  # generated copy
from .ui_cards import section  # generated copy

NAME_HELP = "File name; the extension is optional. Empty: the automatic name shown in grey"
FOLDER_HELP = "Folder to save into (// is relative to this file); created if missing. Empty: next to this file"


def name_property():
    return StringProperty(name="Output Name", description=NAME_HELP)


def folder_property():
    return StringProperty(name="Output Folder", subtype='DIR_PATH', options={'PATH_SUPPORTS_BLEND_RELATIVE'},
                          description=FOLDER_HELP)


def clean_name(name, ext):
    """A typed name as a plain file stem: no folders, no `ext`, no dots or spaces at the ends. Empty when nothing is left."""
    stem = name.replace("\\", "/").split("/")[-1].strip()
    if ext and stem.lower().endswith(ext.lower()):
        stem = stem[:-len(ext)]
    return stem.strip(". ")


def resolve_folder(folder, filepath):
    """The typed folder as an absolute path, else the folder of `filepath`, else '' (nowhere known)."""
    folder = folder.strip()
    if folder.startswith("//") and not filepath:
        return ""                                   # relative to a file that does not exist yet
    if folder:
        return os.path.normpath(bpy.path.abspath(folder, start=os.path.dirname(filepath) if filepath else None))
    return os.path.dirname(filepath) if filepath else ""


def output_path(name, folder, auto_stem, ext, filepath, overwrite=False):
    """The file to write: typed name (or `auto_stem`) + ext in the typed folder (or next to `filepath`).
    Existing files are not overwritten (-2, -3 ...) unless `overwrite`. None when no folder is known."""
    base = resolve_folder(folder, filepath)
    if not base:
        return None
    stem = clean_name(name, ext) or auto_stem
    return os.path.join(base, stem + ext) if overwrite else free_path(base, stem, ext)


def make_folder(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def draw_output(layout, idname, owner, name_prop, folder_prop, auto_name, auto_folder="", with_folder=True, extra=None):
    """The "Output" sub-card: `extra(col)` draws more rows first (Game Rig's dropdown), then the name field with
    `auto_name` greyed in when empty, then the folder field (placeholder `auto_folder`)."""
    body = section(layout, idname, "Output", icon='FILE_FOLDER', default_closed=True)
    if not body:
        return
    col = body.column()
    if extra:
        extra(col)
    col.prop(owner, name_prop, placeholder=auto_name)
    if with_folder:
        col.prop(owner, folder_prop, placeholder=auto_folder)
