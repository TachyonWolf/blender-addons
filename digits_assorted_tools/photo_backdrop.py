# SPDX-License-Identifier: GPL-3.0-or-later
"""Photo Backdrop (Digit's Tools > Setups): Deploy button and card for the Photo Backdrop asset (a seamless
cyclorama: floor curving into the wall). Deploy appends it as real objects with its floor just under the
geometry of what you click and the wall behind it as seen from the viewer, plus a Lighting Rig of the chosen
style fitted to that subject (light_rig.deploy_on_ground; Lighting "None": no light). The colour is the Base
Color of the backdrop's own material. Backdrops made before the Lighting option carry their own wall light,
parented to the sheet; they keep working."""

import bpy
from bpy.props import EnumProperty, FloatVectorProperty

from . import light_rig, light_rig_spec, rig_common, rig_placement as placement, selected_ui
from .modifier_setup import library_file  # generated copy
from .rig_common import select_only
from .ui_cards import enum_label, hints, prop_group, sub_heading  # generated copy

ASSET_NAME = "Photo Backdrop"
LIBRARY_FILE = "PhotoBackdrop.blend"
TAG = "setups_photo_backdrop"   # custom property on the backdrop sheet (the asset has no tag of its own)
DEFAULT_COLOUR = (0.92, 0.92, 0.92)
COLOUR_HELP = ("Backdrop colour. White and light grey backdrops bounce soft light back onto the subject and "
               "are easy to key (to cut out or composite); coloured ones set a mood but also tint the subject "
               "with bounced light")
LIGHT_ITEMS = [(light_rig_spec.NO_STYLE, "None", "No lighting rig: just the backdrop")] + light_rig_spec.style_items()


def sheet_of(ob):
    """The backdrop sheet that `ob` is (or the wall light of, on backdrops made before the Lighting option), or None."""
    if ob is None:
        return None
    if ob.get(TAG) is not None:
        return ob
    return ob.parent if ob.parent is not None and ob.parent.get(TAG) is not None else None


def find_backdrop(context):
    return sheet_of(context.active_object)


def base_colour_input(sheet):
    """The Base Color socket of the sheet's Principled material, or None."""
    mat = sheet.active_material
    if mat is None or mat.node_tree is None:
        return None
    node = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    return node.inputs["Base Color"] if node else None


def set_colour(sheet, colour):
    """Paint the backdrop (material Base Color, and the viewport colour so Solid mode matches)."""
    socket = base_colour_input(sheet)
    socket.default_value = (*colour[:3], 1.0)
    sheet.active_material.diffuse_color = (*colour[:3], 1.0)


def deploy(context, view, path, colour=DEFAULT_COLOUR, light_style=light_rig_spec.NO_STYLE, light_path=None):
    """Append the Photo Backdrop from `path` as real objects: the floor a hair under the lowest point of
    the clicked object (its whole character if it belongs to a rig), centred under it, the wall behind it
    as seen from the viewer; empty click: under the fallback point. With a `light_style` (and its library
    file `light_path`) a Lighting Rig of that style is fitted to the same subject, facing the viewer.
    Returns the backdrop sheet."""
    ground = placement.ground_under_click(context, view)   # measured before the backdrop exists
    coll = rig_common.append_collection(context, path, ASSET_NAME)
    sheet = next(o for o in coll.all_objects if o.type == 'MESH')
    for light in (o for o in coll.all_objects if o.type == 'LIGHT'):   # an older asset's own wall light
        light.parent = sheet   # still at the origin together, so no parent inverse needed
    sheet[TAG] = 1
    if sheet.active_material.users > 1:
        sheet.active_material = sheet.active_material.copy()
    set_colour(sheet, colour)
    sheet.location = placement.floor_location(ground)
    sheet.rotation_euler.z = placement.wall_yaw(ground)
    if light_style != light_rig_spec.NO_STYLE and light_path:
        light_rig.deploy_on_ground(context, light_path, ground, light_style)
    context.view_layer.update()
    select_only(context, sheet)
    return sheet


class PHOTOBACKDROP_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a Photo Backdrop as real, editable objects: its floor goes just under what you click (Enter: the
    screen centre), the wall behind it as seen from your view"""
    bl_idname = "photo_backdrop.deploy"
    bl_label = "Deploy Photo Backdrop"
    bl_options = {'REGISTER', 'UNDO'}
    library_name = LIBRARY_FILE

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        style, light_path = wm.setups_backdrop_light, None
        if style != light_rig_spec.NO_STYLE:
            light_path = library_file(light_rig.library_of(style))
            if light_path is None:
                self.report({'WARNING'}, f"{light_rig.library_of(style)} not found in your asset libraries: backdrop only")
        deploy(context, view, path, wm.setups_backdrop_colour, style, light_path)


class PHOTOBACKDROP_OT_select(bpy.types.Operator):
    """Select the backdrop"""
    bl_idname = "photo_backdrop.select"
    bl_label = "Select Backdrop"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_backdrop(context) is not None

    def execute(self, context):
        select_only(context, find_backdrop(context))
        return {'FINISHED'}


def draw_card(layout, context):
    """The Photo Backdrop tool: Deploy only; the backdrop's own controls are in the Selected card."""
    body = layout   # the tool dropdown is the title
    placement.draw_scene_status(body, context.scene, TAG, "backdrop", 'IMAGE_BACKGROUND',
                                selected=find_backdrop(context) is not None)
    wm = context.window_manager
    placement.draw_deploy(body, "setups_photo_backdrop_options", PHOTOBACKDROP_OT_deploy.bl_idname, 0,
                          lambda sec: draw_options(sec, wm),
                          existing=len(placement.rig_roots(context.scene.objects, TAG)),
                          summary=enum_label(wm, "setups_backdrop_light"))
    if not placement.rig_roots(context.scene.objects, TAG):
        hints(body, ["Click the character or object the backdrop goes under"], context)


def draw_options(layout, wm):
    """Deploy options: the colour, then the nested Lighting Rig (its Style; None = backdrop only)."""
    prop_group(layout, wm, [("setups_backdrop_colour", "Colour")])
    sub_heading(layout, light_rig.LABEL, icon='LIGHT_AREA')
    prop_group(layout, wm, [("setups_backdrop_light", "Style")])


def draw_selected(box, context):
    """The Selected card's part: the colour of the backdrop the selected object is (or lights)."""
    sheet = find_backdrop(context)
    socket = base_colour_input(sheet)
    if socket is not None:
        prop_group(box, socket, [("default_value", "Colour")])   # the material itself: always live
    box.operator(PHOTOBACKDROP_OT_select.bl_idname, text="Select Backdrop", icon='RESTRICT_SELECT_OFF')


selected_ui.add("Photo Backdrop", lambda context: find_backdrop(context) is not None, lambda context: "Photo Backdrop",
                draw_selected)


classes = (PHOTOBACKDROP_OT_deploy, PHOTOBACKDROP_OT_select)


def register():
    bpy.types.WindowManager.setups_backdrop_colour = FloatVectorProperty(
        name="Colour", subtype='COLOR', size=3, min=0.0, max=1.0, default=DEFAULT_COLOUR, description=COLOUR_HELP)
    bpy.types.WindowManager.setups_backdrop_light = EnumProperty(
        name="Lighting Rig", items=LIGHT_ITEMS, default=light_rig_spec.BACKDROP_STYLE,
        description="The Lighting Rig deployed with the backdrop, fitted to the subject and facing you (None: no light)")
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.setups_backdrop_colour
    del bpy.types.WindowManager.setups_backdrop_light
