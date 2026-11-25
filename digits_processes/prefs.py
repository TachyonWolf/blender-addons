# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's Processes preferences: defaults a process uses unless changed for one run."""
from types import SimpleNamespace

import bpy
from bpy.props import EnumProperty, StringProperty

from .texture_screenshot import save_paths


class DigitProcessesPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    save_to: EnumProperty(name="Save Screenshots To", items=save_paths.SAVE_ITEMS, default=save_paths.BLEND,
                          description="Where Texture Data Screenshot images go when a run says Default")
    fallback_folder: StringProperty(
        name="Fallback Folder", subtype='DIR_PATH', default=save_paths.DEFAULT_FALLBACK,
        description="Used when the file is not saved yet and Next to this .blend is chosen (images go to "
                    "<folder>/<target>/). Empty = always ask to save first")

    def draw(self, context):
        self.layout.prop(self, "save_to")
        self.layout.prop(self, "fallback_folder")


DEFAULTS = SimpleNamespace(save_to=save_paths.BLEND, fallback_folder=save_paths.DEFAULT_FALLBACK)


def preferences(context):
    """The add-on's preferences; the defaults when it is registered without being enabled (headless tests)."""
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else DEFAULTS
