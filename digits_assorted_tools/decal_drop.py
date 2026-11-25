# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: dropping image files on the 3D viewport. Two FileHandlers sit next to Blender's own image handlers, so
Blender's "drop as" menu lists "Decal on Object" (made right where you dropped), "Decal, open Import…" (the dialog,
aimed there) and Blender's own Reference / Image choices. The operators live in decal_import_ops.py."""

import bpy

from .decal_import_ops import DECAL_OT_drop_dialog, DECAL_OT_drop_place
from .decal_maps import IMAGE_EXTENSIONS_TEXT


def in_viewport(context):
    return context.area is not None and context.area.type == 'VIEW_3D'


class DECAL_FH_place(bpy.types.FileHandler):
    bl_idname = "DECAL_FH_place"
    bl_label = DECAL_OT_drop_place.bl_label
    bl_import_operator = DECAL_OT_drop_place.bl_idname
    bl_file_extensions = IMAGE_EXTENSIONS_TEXT

    @classmethod
    def poll_drop(cls, context):
        return in_viewport(context)


class DECAL_FH_dialog(bpy.types.FileHandler):
    bl_idname = "DECAL_FH_dialog"
    bl_label = DECAL_OT_drop_dialog.bl_label
    bl_import_operator = DECAL_OT_drop_dialog.bl_idname
    bl_file_extensions = IMAGE_EXTENSIONS_TEXT

    @classmethod
    def poll_drop(cls, context):
        return in_viewport(context)


CLASSES = (DECAL_FH_place, DECAL_FH_dialog)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
