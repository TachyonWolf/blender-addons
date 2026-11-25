# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/asset_libraries.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Register / remove a folder as an asset library in Preferences > File Paths > Asset Libraries. Shared by the
extensions that serve their own library (Digit's Modifiers: "Digit's Modifiers"; Digit's Assorted Tools: the character library).
Only an entry with the given name AND folder is ever removed, so a library of the same name the user made elsewhere stays."""

import os

import bpy


def same_folder(a, b):
    return os.path.normcase(os.path.realpath(bpy.path.abspath(a))) == os.path.normcase(os.path.realpath(b))


def entries_for(name, folder):
    """The registered libraries called `name` that point at `folder`."""
    return [lib for lib in bpy.context.preferences.filepaths.asset_libraries
            if lib.name == name and same_folder(lib.path, folder)]


def add_library(name, folder, import_method='APPEND'):
    """Register `folder` as library `name` unless some library already points at it. Returns True when added."""
    libraries = bpy.context.preferences.filepaths.asset_libraries
    if not os.path.isdir(folder) or any(same_folder(lib.path, folder) for lib in libraries):
        return False
    library = libraries.new(name=name, directory=folder)
    library.import_method = import_method
    return True


def remove_library(name, folder):
    """Remove the entry add_library made (matched by name and folder). Returns how many were removed."""
    libraries = bpy.context.preferences.filepaths.asset_libraries
    mine = entries_for(name, folder)
    for lib in mine:
        libraries.remove(lib)
    return len(mine)
