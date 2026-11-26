# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the list's operators: select a decal, move it up / down a layer, remove it, hide / show it, and swap
a map in one of its slots. Work is done by decal_mesh / decal_material."""

import os

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import decal_maps, decal_material, decal_mesh
from .decal_state_ops import DecalOperator
from .object_tools import remove_object, select_only  # generated copy


class DECAL_OT_select(DecalOperator, bpy.types.Operator):
    """Make this decal the active, selected object"""
    bl_idname = "decal.select"
    bl_label = "Select Decal"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        if decal.name not in context.view_layer.objects:
            self.report({'WARNING'}, f"{decal.name} is not in this view layer")
            return {'CANCELLED'}
        select_only(context, [decal] if decal.visible_get() else [], decal)
        return {'FINISHED'}


class DECAL_OT_move_layer(DecalOperator, bpy.types.Operator):
    """Move the decal one layer up (drawn over its neighbour) or down"""
    bl_idname = "decal.move_layer"
    bl_label = "Move Layer"
    direction: IntProperty(name="Direction", default=1, min=-1, max=1, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return "Layer up: drawn over the decal above" if properties.direction > 0 else "Layer down"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        if decal.digit_decal.target is None or not decal_mesh.move_layer(decal, self.direction):
            self.report({'WARNING'}, f"{decal.name} cannot move further that way (no target, or already at the end)")
            return {'CANCELLED'}
        return {'FINISHED'}


class DECAL_OT_remove(DecalOperator, bpy.types.Operator):
    """Delete the decal (its mesh and material go too when nothing else uses them; the images stay)"""
    bl_idname = "decal.remove"
    bl_label = "Remove Decal"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        materials = [slot.material for slot in decal.material_slots if slot.material]
        remove_object(decal)
        for material in materials:
            if material.users == 0:
                bpy.data.materials.remove(material)
        return {'FINISHED'}


class DECAL_OT_toggle_hidden(DecalOperator, bpy.types.Operator):
    """Hide or show the decal in the viewport"""
    bl_idname = "decal.toggle_hidden"
    bl_label = "Hide / Show Decal"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        if decal.name not in context.view_layer.objects:
            self.report({'WARNING'}, f"{decal.name} is not in this view layer")
            return {'CANCELLED'}
        decal.hide_set(not decal.hide_get())
        return {'FINISHED'}


ROLE_ITEMS = [(role, label, f"The {label} map") for role, label in decal_maps.ROLES]
ROLE_ITEMS += [(decal_maps.back_role(role), f"Back {label}", f"The {label} map seen from behind")
               for role, label in decal_maps.ROLES]


class DECAL_OT_browse_map(DecalOperator, ImportHelper, bpy.types.Operator):
    """Pick an image for this map slot"""
    bl_idname = "decal.browse_map"
    bl_label = "Use Image"
    role: EnumProperty(name="Map", items=ROLE_ITEMS, options={'HIDDEN', 'SKIP_SAVE'})
    filter_glob: StringProperty(default="*" + ";*".join(decal_maps.IMAGE_EXTENSIONS), options={'HIDDEN'})

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        if decal.active_material is None or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, f"{decal.name} has no material, or the image file is missing")
            return {'CANCELLED'}
        image = decal_material.load_image(self.filepath, self.role)
        decal_material.set_map(decal.active_material, self.role, image)
        return {'FINISHED'}


class DECAL_OT_clear_map(DecalOperator, bpy.types.Operator):
    """Empty this map slot"""
    bl_idname = "decal.clear_map"
    bl_label = "Clear Map"
    role: EnumProperty(name="Map", items=ROLE_ITEMS, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        decal = self.decal(context)
        if decal is None:
            return {'CANCELLED'}
        if decal.active_material is None or self.role == "COLOR":
            self.report({'WARNING'}, f"{decal.name} has no material, or the Colour map cannot be emptied")
            return {'CANCELLED'}
        decal_material.set_map(decal.active_material, self.role, None)
        return {'FINISHED'}


CLASSES = (DECAL_OT_select, DECAL_OT_move_layer, DECAL_OT_remove, DECAL_OT_toggle_hidden, DECAL_OT_browse_map,
           DECAL_OT_clear_map)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
