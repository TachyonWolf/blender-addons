# SPDX-License-Identifier: GPL-3.0-or-later
"""The bridge to Digit's Assorted Tools: processes use its code (Texture Studio, Decals) from the installed,
enabled add-on instead of carrying copies. The one place that finds it.

    studio = assorted_tools.module("texture_studio.studio")   # raises Missing with a message for the user

An extension's package is `bl_ext.<repo>.digits_assorted_tools`; a legacy add-on is plain `digits_assorted_tools`.
Tests set PACKAGE_OVERRIDE to the source folder's package (on sys.path) to test the working copy.
"""
import importlib

import bpy

ADDON_ID = "digits_assorted_tools"
MISSING_TEXT = "Needs Digit's Assorted Tools: enable it in Preferences > Add-ons"
PACKAGE_OVERRIDE = None


class Missing(RuntimeError):
    """Digit's Assorted Tools is not enabled (or lacks a part a process needs)."""


def package_name(context=None):
    """The enabled add-on's package name, or None. Cheap (a scan of the enabled add-on names): fine in draw."""
    if PACKAGE_OVERRIDE:
        return PACKAGE_OVERRIDE
    preferences = (context or bpy.context).preferences
    return next((key for key in preferences.addons.keys()
                 if key == ADDON_ID or key.endswith("." + ADDON_ID)), None)


def is_enabled(context=None):
    return package_name(context) is not None


def module(name, context=None):
    """A submodule of Digit's Assorted Tools, e.g. "texture_studio.studio"."""
    package = package_name(context)
    if package is None:
        raise Missing(MISSING_TEXT)
    try:
        return importlib.import_module(f"{package}.{name}")
    except ImportError as error:
        raise Missing(f"Digit's Assorted Tools has no {name} (update it): {error}") from error


def optional_module(name, context=None):
    """Like module(), but None when the add-on or the module is missing (for optional steps)."""
    try:
        return module(name, context)
    except Missing:
        return None
