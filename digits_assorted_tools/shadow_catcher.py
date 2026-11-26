# SPDX-License-Identifier: GPL-3.0-or-later
"""Shadow Catcher Floor (Digit's Tools > Setups): Deploy button and card for a large plane that is invisible
in the render but catches the shadows of everything above it (Cycles), so a render composites over a photo.
Deploy makes the plane (no asset) just under the lowest point of the clicked object, same rule as the Photo Backdrop."""

import bpy
from bpy.props import BoolProperty, FloatProperty

from . import rig_placement as placement, selected_ui
from .object_tools import remove_object  # generated copy
from .rig_common import select_only
from .ui_cards import action_row, hints, prop_group, status  # generated copy

NAME = "Shadow Catcher Floor"
TAG = "setups_shadow_catcher"   # custom property on the plane, so the card finds it whatever it is renamed to
DEFAULT_SIZE = 20.0
SIZE_HELP = ("Width and length of the floor (m). It only needs to cover the area where shadows fall and reflect: "
             "a floor that is too small cuts the shadows off at its edge")
FILM_HELP = ("Render the background transparent (Film > Transparent) so the shadows can be composited over a photo. "
             "Without it the world colour fills the picture and the catcher has nothing to show through")
ENGINE_HINT = "Shadow catchers only work in Cycles: switch the render engine (Render properties)"


def is_catcher(ob):
    return ob is not None and ob.get(TAG) is not None


def find_catcher(context):
    ob = context.active_object
    return ob if is_catcher(ob) else None


def make_plane(context, size):
    """A square plane `size` m wide in the active collection, facing up."""
    half = size / 2
    mesh = bpy.data.meshes.new(NAME)
    mesh.from_pydata([(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, half, 0)], [], [(0, 1, 2, 3)])
    mesh.update()
    ob = bpy.data.objects.new(NAME, mesh)
    context.collection.objects.link(ob)
    return ob


def deploy(context, view, size=DEFAULT_SIZE, film_transparent=True):
    """Make a Shadow Catcher plane `size` m wide a hair under the lowest point of the clicked object (its
    whole character if it belongs to a rig), centred under it; empty click: under the fallback point.
    Sets the scene's transparent film when asked. Returns the plane."""
    ground = placement.ground_under_click(context, view)
    ob = make_plane(context, size)
    ob[TAG] = 1
    ob.is_shadow_catcher = True
    ob.location = placement.floor_location(ground)
    if film_transparent:
        context.scene.render.film_transparent = True
    context.view_layer.update()
    select_only(context, ob)
    return ob


class SHADOWCATCHER_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a Shadow Catcher floor just under what you click (Enter: the screen centre)"""
    bl_idname = "shadow_catcher.deploy"
    bl_label = "Deploy Shadow Catcher Floor"
    bl_options = {'REGISTER', 'UNDO'}

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        deploy(context, view, wm.setups_catcher_size, wm.setups_catcher_film)


class SHADOWCATCHER_OT_select(bpy.types.Operator):
    """Select the shadow catcher floor"""
    bl_idname = "shadow_catcher.select"
    bl_label = "Select Shadow Catcher"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_catcher(context) is not None

    def execute(self, context):
        select_only(context, find_catcher(context))
        return {'FINISHED'}


class SHADOWCATCHER_OT_remove(bpy.types.Operator):
    """Delete the shadow catcher floor"""
    bl_idname = "shadow_catcher.remove"
    bl_label = "Remove Shadow Catcher"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_catcher(context) is not None

    def execute(self, context):
        ob = find_catcher(context)
        remove_object(ob)
        return {'FINISHED'}


def engine_hints(scene):
    return [] if scene.render.engine == 'CYCLES' else [ENGINE_HINT]


def draw_card(layout, context):
    """The Shadow Catcher tool: Deploy only; the floor's own controls are in the Selected card."""
    body = layout   # the tool dropdown is the title
    placement.draw_scene_status(body, context.scene, TAG, "floor", 'SHADING_RENDERED',
                                selected=find_catcher(context) is not None)
    hints(body, engine_hints(context.scene), context)
    wm = context.window_manager
    placement.draw_deploy(body, "setups_shadow_catcher_options", SHADOWCATCHER_OT_deploy.bl_idname, 0,
                          lambda sec: prop_group(sec, wm, [("setups_catcher_size", "Size"),
                                                           ("setups_catcher_film", "Transparent Film")]),
                          existing=len(placement.rig_roots(context.scene.objects, TAG)))
    if find_catcher(context) is not None:
        action_row(body, 1.0).operator(SHADOWCATCHER_OT_remove.bl_idname, icon='TRASH')


def draw_selected(box, context):
    """The Selected card's part: size, film and Select of the shadow catcher floor."""
    catcher = find_catcher(context)
    status(box, f"Floor {catcher.dimensions.x:g} x {catcher.dimensions.y:g} m", icon='SHADING_RENDERED')
    hints(box, engine_hints(context.scene), context)
    col = prop_group(box, catcher, [])
    col.prop(catcher, "dimensions", index=0, text="Width")
    col.prop(catcher, "dimensions", index=1, text="Length")
    prop_group(box, context.scene.render, [("film_transparent", "Transparent Film")])
    action_row(box, 1.0).operator(SHADOWCATCHER_OT_select.bl_idname, icon='RESTRICT_SELECT_OFF')   # Remove is in the tool card


selected_ui.add("Shadow Catcher", lambda context: find_catcher(context) is not None, lambda context: "Shadow Catcher",
                draw_selected)

classes = (SHADOWCATCHER_OT_deploy, SHADOWCATCHER_OT_select, SHADOWCATCHER_OT_remove)


def register():
    wm = bpy.types.WindowManager
    wm.setups_catcher_size = FloatProperty(name="Size", default=DEFAULT_SIZE, min=0.1, soft_max=100.0,
                                           subtype='DISTANCE', description=SIZE_HELP)
    wm.setups_catcher_film = BoolProperty(name="Transparent Film", default=True, description=FILM_HELP)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.setups_catcher_size
    del bpy.types.WindowManager.setups_catcher_film
