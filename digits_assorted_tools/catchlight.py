# SPDX-License-Identifier: GPL-3.0-or-later
"""Catchlight (Digit's Tools > Setups): a tiny light that puts the sparkle in a character's eyes. Deploy: click
the eye (or face); the light goes on the viewer's side of it (placement maths in rig_placement), aimed at the
click, lighting only the reflection: specular only, linked to the eyes. Names, options and tooltips live in
catchlight_spec."""

import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty
from mathutils import Vector

from . import catchlight_spec as spec, rig_placement as placement, selected_ui
from .rig_common import select_only
from .ui_cards import action_row, hints, prop_group, section, status  # generated copy

LINK_PROP = "setups_catchlight_link"   # on the light object: what its light linking uses (shown on the card)
NOT_EYE_WORDS = ("lash", "lid", "brow", "socket")
EYE_REACH = 0.1                        # separate eye meshes within this distance of the click are linked (m)


# ---------------------------------------------------------------------------
# Finding things
# ---------------------------------------------------------------------------

def find_catchlight(context):
    ob = context.active_object
    return ob if ob is not None and ob.get(spec.TAG) is not None else None


def is_eye_name(name):
    lower = name.lower()
    return "eye" in lower and not any(word in lower for word in NOT_EYE_WORDS)


def eye_receivers(hit_object, hit, scene_objects):
    """The objects the catchlight should light: the separate eye meshes of the clicked character within
    EYE_REACH of the click (the clicked object itself if it is one); else just the clicked object."""
    eyes = []
    for ob in placement.subject_objects(hit_object, scene_objects):
        if ob.type != 'MESH' or not is_eye_name(ob.name):
            continue
        centre = placement.box_centre(placement.box_corners(ob.matrix_world, ob.bound_box))
        if ob == hit_object or (centre - hit).length <= EYE_REACH:
            eyes.append(ob)
    return eyes or [hit_object]


def viewer_eye(context, view):
    """Where the viewer's eye is: the scene camera when the 3D view looks through it, else the view's eye."""
    space = context.space_data
    camera = context.scene.camera
    if camera and space and space.type == 'VIEW_3D' and space.region_3d.view_perspective == 'CAMERA':
        return camera.matrix_world.translation.copy()
    return view.eye


# ---------------------------------------------------------------------------
# Building the light
# ---------------------------------------------------------------------------

def make_light(context):
    """A new specular-only area light object in the active collection."""
    light = bpy.data.lights.new(spec.NAME, 'AREA')
    ob = bpy.data.objects.new(spec.NAME, light)
    context.collection.objects.link(ob)
    ob[spec.TAG] = 1
    light.diffuse_factor, light.specular_factor = 0.0, 1.0      # EEVEE: sparkle only
    ob.visible_diffuse, ob.visible_glossy = False, True          # Cycles: glossy rays only
    light.use_shadow = False
    return ob


def apply_options(ob, size, strength, colour, shape):
    light = ob.data
    light.size, light.energy, light.color = size, strength, colour
    light.shape = 'DISK' if shape == 'ROUND' else 'SQUARE'


def link_to(ob, receivers):
    """Light linking: only `receivers` (objects) are lit by this light. Returns the text for the card."""
    coll = ob.light_linking.receiver_collection
    if coll is None:
        coll = bpy.data.collections.new(f"{ob.name} Receivers")
        ob.light_linking.receiver_collection = coll
    for old in list(coll.objects):
        coll.objects.unlink(old)
    for receiver in receivers:
        coll.objects.link(receiver)
    text = spec.LINK_EYES if any(is_eye_name(r.name) for r in receivers) else spec.LINK_OBJECT
    ob[LINK_PROP] = f"{text}: {', '.join(r.name for r in receivers)}"
    return ob[LINK_PROP]


def deploy(context, view, size=spec.DEFAULT_SIZE, strength=spec.DEFAULT_STRENGTH, colour=spec.DEFAULT_COLOUR,
           shape=spec.DEFAULT_SHAPE, distance=spec.DEFAULT_DISTANCE, clock=spec.DEFAULT_CLOCK, existing=None):
    """Make a catchlight for the eye (or face) the view ray points at: `distance` m from it on the viewer's side,
    offset towards `clock` o'clock, aimed at it. A click that hits nothing uses the fallback point ahead.
    `existing` (a catchlight): Redeploy, move it and re-link it, leaving size / strength / colour / shape.
    Returns the light object."""
    depsgraph = context.evaluated_depsgraph_get()      # cast before the light exists
    hit, hit_object = placement.cast_hit(context.scene, depsgraph, view.eye, view.forward)
    target = placement.target_point(view, hit)
    ob = existing if existing is not None else make_light(context)
    viewer = viewer_eye(context, view)
    ob.parent = None
    ob.location = placement.catchlight_location(viewer, target, distance, int(clock), spec.OFFSET_ANGLE)
    ob.rotation_euler = placement.aim_euler(ob.location, target)
    if existing is None:
        apply_options(ob, size, strength, colour, shape)
    if hit_object is not None:
        link_to(ob, eye_receivers(hit_object, hit, context.scene.objects))
    context.view_layer.update()
    select_only(context, ob)
    return ob


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class CATCHLIGHT_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a catchlight: click the character's eye (or face; Enter: the screen centre). A tiny light appears
    on your side of it, high up, aimed at the click, and only lights the reflection in the eye"""
    bl_idname = "catchlight.deploy"
    bl_label = "Deploy Catchlight"
    bl_options = {'REGISTER', 'UNDO'}
    root_tag = spec.TAG
    rig_label = spec.NAME

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        ob = deploy(context, view, wm.setups_catchlight_size, wm.setups_catchlight_strength,
                    tuple(wm.setups_catchlight_colour), wm.setups_catchlight_shape, wm.setups_catchlight_distance,
                    wm.setups_catchlight_clock, existing)
        self.report({'INFO'}, ob.get(LINK_PROP, "Nothing was clicked: the light is not linked to anything"))


class _CatchlightOperator:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_catchlight(context) is not None


class CATCHLIGHT_OT_select(_CatchlightOperator, bpy.types.Operator):
    """Select the catchlight"""
    bl_idname = "catchlight.select"
    bl_label = "Select Catchlight"

    def execute(self, context):
        select_only(context, find_catchlight(context))
        return {'FINISHED'}


class CATCHLIGHT_OT_remove(_CatchlightOperator, bpy.types.Operator):
    """Delete the catchlight"""
    bl_idname = "catchlight.remove"
    bl_label = "Remove Catchlight"

    def execute(self, context):
        ob = find_catchlight(context)
        light, coll = ob.data, ob.light_linking.receiver_collection
        bpy.data.objects.remove(ob)
        if light.users == 0:
            bpy.data.lights.remove(light)
        if coll is not None and coll.users == 0:
            bpy.data.collections.remove(coll)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def draw_section(layout, context):
    """The Catchlight deploy section (shown inside the Lighting Rig card): status, Deploy options and Remove; the
    light's own controls are in the Selected card."""
    placement.draw_scene_status(layout, context.scene, spec.TAG, "catchlight", 'LIGHT_AREA',
                                selected=find_catchlight(context) is not None)

    def options(sec):
        prop_group(sec, context.window_manager, [
            ("setups_catchlight_clock", "Clock Position"), ("setups_catchlight_distance", "Distance"),
            ("setups_catchlight_size", "Size"), ("setups_catchlight_strength", "Strength"),
            ("setups_catchlight_shape", "Shape"), ("setups_catchlight_colour", "Colour")])
        hints(sec, [spec.BOTH_EYES_NOTE])
    count = len(placement.rig_roots(context.scene.objects, spec.TAG))
    placement.draw_deploy(layout, "setups_catchlight_options", CATCHLIGHT_OT_deploy.bl_idname, count, options)
    if find_catchlight(context) is not None:
        action_row(layout, 1.0).operator(CATCHLIGHT_OT_remove.bl_idname, icon='TRASH')


def draw_selected(box, context):
    """The Selected card's part: size, strength and colour of the selected catchlight, Select (Remove is in the Lighting Rig card)."""
    light = find_catchlight(context)
    status(box, f"Sparkle light · {light.data.size * 1000:.0f} mm", icon='LIGHT_AREA')
    prop_group(box, light.data, [("size", "Size"), ("energy", "Strength"), ("color", "Colour")])
    hints(box, [light.get(LINK_PROP)])
    action_row(box, 1.0).operator(CATCHLIGHT_OT_select.bl_idname, icon='RESTRICT_SELECT_OFF')   # Remove is in the Lighting Rig card


selected_ui.add("Catchlight", lambda context: find_catchlight(context) is not None, lambda context: "Catchlight",
                draw_selected)

classes = (CATCHLIGHT_OT_deploy, CATCHLIGHT_OT_select, CATCHLIGHT_OT_remove)


def register():
    wm = bpy.types.WindowManager
    wm.setups_catchlight_size = FloatProperty(name="Size", default=spec.DEFAULT_SIZE, min=0.005, soft_max=1.0,
                                              subtype='DISTANCE', description=spec.SIZE_HELP)
    wm.setups_catchlight_strength = FloatProperty(name="Strength", default=spec.DEFAULT_STRENGTH, min=0.0,
                                                  soft_max=500.0, description=spec.STRENGTH_HELP)
    wm.setups_catchlight_shape = EnumProperty(name="Shape", items=[(i, n, t) for i, n, t in spec.SHAPE_ITEMS],
                                              default=spec.DEFAULT_SHAPE, description=spec.SHAPE_HELP)
    wm.setups_catchlight_colour = FloatVectorProperty(name="Colour", subtype='COLOR', size=3, min=0.0, max=1.0,
                                                      default=spec.DEFAULT_COLOUR, description=spec.COLOUR_HELP)
    wm.setups_catchlight_distance = FloatProperty(name="Distance", default=spec.DEFAULT_DISTANCE, min=0.05,
                                                  soft_max=3.0, subtype='DISTANCE', description=spec.DISTANCE_HELP)
    wm.setups_catchlight_clock = EnumProperty(name="Clock Position", items=list(spec.CLOCK_ITEMS),
                                              default=spec.DEFAULT_CLOCK, description=spec.CLOCK_HELP)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for name in ("size", "strength", "shape", "colour", "distance", "clock"):
        delattr(bpy.types.WindowManager, f"setups_catchlight_{name}")
