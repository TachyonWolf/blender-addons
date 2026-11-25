# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Digit World" asset library: the project's asset/ folder (Characters and Locations as collection assets,
catalogs in its blender_assets.cats.txt), registered in Preferences > File Paths > Asset Libraries (import method Link)
while the extension is enabled. Nothing is registered when the folder is not there (another computer)."""

import os

from . import asset_libraries  # generated copy

LIBRARY_NAME = "Digit World"
# Looked at (first that exists wins), relative to the home folder.
FOLDER_CANDIDATES = ()


def library_folder():
    home = os.path.expanduser("~")
    # Real path, not the ~/Projects symlink: paths inside linked .blends must resolve from one location only.
    return next((os.path.realpath(p) for p in (os.path.join(home, c) for c in FOLDER_CANDIDATES) if os.path.isdir(p)), "")


def add_library():
    """Register asset/ (Link mode) unless some library already points at it. Returns True when added."""
    folder = library_folder()
    return bool(folder) and asset_libraries.add_library(LIBRARY_NAME, folder, 'LINK')


def remove_library():
    """Remove the entry add_library made (matched by name and folder). Returns how many were removed."""
    folder = library_folder()
    return asset_libraries.remove_library(LIBRARY_NAME, folder) if folder else 0
