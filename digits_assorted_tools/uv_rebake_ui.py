# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Rebake card (Digit's Tools > Texture): move textures to another UV map on the selected meshes. Pick the source and
target UV maps, size and supersample; every image on the material is rebaked to its own new file, except tiling patterns
(off by default in the image list), which just read the new UV. All logic is in uv_rebake (generated copy of
Addons/shared_addon/uv_rebake.py)."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from . import uv_rebake as core  # generated copy
from .ui_cards import action_row, hints, poll_message, prop_group, section, status  # generated copy

SIZES = (('0', "Same as Image", "Keep each image's size"), ('1024', "1024", ""), ('2048', "2048", ""),
         ('4096', "4096", ""), ('8192', "8192", ""))
SUPERSAMPLES = (('1', "1x", "Bake at final size"), ('2', "2x", "Bake twice the size, then scale down"),
                ('4', "4x", "Bake four times the size, then scale down"))


class DIGITOOLS_PG_rebake_image(bpy.types.PropertyGroup):
    key: StringProperty()
    bake: BoolProperty(name="Bake", default=True, description="Rebake this image. Off: it just reads the new UV")


class DIGITOOLS_PG_rebake(bpy.types.PropertyGroup):
    source: StringProperty(name="Source", description="UV map the images are painted on")
    target: StringProperty(name="Target", description="UV map to carry them to")
    size: EnumProperty(name="Size", items=SIZES, default='0', description="Size of the new images")
    supersample: EnumProperty(name="Supersample", items=SUPERSAMPLES, default='2')
    margin: IntProperty(name="Margin", default=16, min=0, max=128, subtype='PIXEL',
                        description="Colour pushed past island edges, so dark background doesn't bleed along seams")
    sharp: BoolProperty(name="Sharp", default=True, description="Read images without blending: an island moved by whole "
                        "pixels copies exactly. Off: use each image node's interpolation")
    folder: StringProperty(name="Folder", subtype='DIR_PATH', default="//Rebaked",
                           options={'PATH_SUPPORTS_BLEND_RELATIVE'}, description="Where the new images go")
    copy_missing: BoolProperty(name="Copy to Missing Parts", description="Parts on the same image that lack the target "
                               "UV get a copy of the source UV, instead of stopping")
    apply: BoolProperty(name="Use New Images", default=True, description="Swap the new images into the materials and make "
                        "the target UV active for render")
    images: CollectionProperty(type=DIGITOOLS_PG_rebake_image)


def settings_of(context):
    return context.scene.digitools_rebake


def selected_meshes(context):
    return [ob for ob in context.selected_objects if ob.type == 'MESH']


def why_not(context):
    props = settings_of(context)
    if context.mode != 'OBJECT':
        return "Go to Object Mode"
    if not selected_meshes(context):
        return "Select a mesh"
    if not props.source or not props.target:
        return "Pick the source and target UV maps"
    if props.source == props.target:
        return "Source and target are the same UV map"
    return ""


def chosen_textures(context):
    """The selected meshes' textures, with the image list's toggles on them."""
    toggles = {item.key: item.bake for item in settings_of(context).images}
    textures = core.find_textures(selected_meshes(context))
    for texture in textures:
        texture.bake = toggles.get(texture.key, not texture.tiling)
    return textures


class DIGITOOLS_OT_rebake_find(bpy.types.Operator):
    """List the images on the selected meshes. Tiling patterns start switched off"""
    bl_idname = "digits_assorted_tools.rebake_find"
    bl_label = "Find Images"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return bool(selected_meshes(context))

    def execute(self, context):
        images = settings_of(context).images
        toggles = {item.key: item.bake for item in images}
        images.clear()
        for texture in core.find_textures(selected_meshes(context)):
            item = images.add()
            item.name, item.key = texture.name, texture.key
            item.bake = toggles.get(texture.key, not texture.tiling)
        return {'FINISHED'}


class DIGITOOLS_OT_rebake(bpy.types.Operator):
    """Rebake the chosen images from the source UV map to the target UV map and save them as new files. Parts sharing an
    image are baked together, selected or not"""
    bl_idname = "digits_assorted_tools.rebake"
    bl_label = "Rebake Images"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, why_not(context))

    def execute(self, context):
        props = settings_of(context)
        settings = core.Settings(size=int(props.size), supersample=int(props.supersample), margin=props.margin,
                                 sharp=props.sharp, folder=props.folder, copy_missing=props.copy_missing,
                                 apply=props.apply)
        try:
            results = core.rebake(context, chosen_textures(context), props.source, props.target, settings)
        except core.RebakeError as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, "Rebaked: " + ", ".join(image.name for _texture, image in results))
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout
    props = settings_of(context)
    meshes = selected_meshes(context)
    status(body, f"{len(meshes)} meshes selected" if meshes else "Select the meshes to rebake", icon='MESH_DATA')
    if context.active_object and context.active_object.type == 'MESH':
        layers = context.active_object.data
        body.prop_search(props, "source", layers, "uv_layers", icon='GROUP_UVS')
        body.prop_search(props, "target", layers, "uv_layers", icon='GROUP_UVS')
    row = body.row(align=True)
    row.prop(props, "size", text="")
    row.prop(props, "supersample", text="")
    body.prop(props, "folder")
    images = section(body, "digitools_uv_rebake_images", "Images", icon='IMAGE_DATA')
    if images:
        images.operator(DIGITOOLS_OT_rebake_find.bl_idname, icon='VIEWZOOM')
        for item in props.images:
            images.prop(item, "bake", text=item.name)
    options = section(body, "digitools_uv_rebake_options", "Options", icon='PREFERENCES', default_closed=True)
    if options:
        prop_group(options, props, ["margin", "sharp", "copy_missing", "apply"])
    action_row(body).operator(DIGITOOLS_OT_rebake.bl_idname, icon='RENDER_STILL')
    hints(body, [why_not(context)], context)


classes = (DIGITOOLS_PG_rebake_image, DIGITOOLS_PG_rebake, DIGITOOLS_OT_rebake_find, DIGITOOLS_OT_rebake)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.digitools_rebake = PointerProperty(type=DIGITOOLS_PG_rebake)


def unregister():
    del bpy.types.Scene.digitools_rebake
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
