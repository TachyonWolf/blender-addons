# SPDX-License-Identifier: GPL-3.0-or-later
"""Append and remove a table of Blender menu entries: (Blender UI class name, draw function). The one helper behind
mirror_pivot.py's MENUS and f3_menus.py's ENTRIES."""
import bpy


def append_menus(entries):
    for menu_name, draw in entries:
        getattr(bpy.types, menu_name).append(draw)


def remove_menus(entries):
    for menu_name, draw in entries:
        getattr(bpy.types, menu_name).remove(draw)
