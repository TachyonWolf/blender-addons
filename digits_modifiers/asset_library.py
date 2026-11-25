# SPDX-License-Identifier: GPL-3.0-or-later
"""The extension's own asset library: its bundled `assets/` folder, registered in Preferences >
File Paths > Asset Libraries as "Digit's Modifiers" while the extension is enabled. Only an entry with
this name AND this folder is ever touched, so a library of the same name the user made elsewhere stays."""

import os

from . import asset_libraries

LIBRARY_NAME = "Digit's Modifiers"
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def add_library():
    """Register the assets folder (Append mode) unless some library already points at it. Returns True when added."""
    return asset_libraries.add_library(LIBRARY_NAME, ASSETS_DIR, 'APPEND')


def remove_library():
    """Remove the entry add_library made (matched by name and folder). Returns how many were removed."""
    return asset_libraries.remove_library(LIBRARY_NAME, ASSETS_DIR)
