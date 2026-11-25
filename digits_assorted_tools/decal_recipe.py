# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the recipe stored on every decal object (`Object.digit_decal`), the one place a decal's own settings
live. The flat grid, its frame and its modifier stack are rebuilt from it (decal_mesh.py). Values that already
live in Blender data are NOT copied here: Lift is the Lift Displace modifier's strength, the Look values are the
Digit Decal node's inputs, the maps are the material's image nodes.

States: Unattached (no target) > Placing > Stuck. Changing Size, Rotation, Flip, Mirror X or Wrap on a Stuck
decal unsticks it first (it turns Placing); nothing is baked or bound per change."""

from math import radians

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty

from . import decal_maps

UNATTACHED = 'UNATTACHED'
PLACING = 'PLACING'
STUCK = 'STUCK'
STATES = ((UNATTACHED, "Unattached", "In the world, on no surface yet: ready to be attached"),
          (PLACING, "Placing", "Slides on the surface: re-projected every update, any pose"),
          (STUCK, "Stuck", "Follows the rig, shape keys and deforming modifiers (Surface Deform)"))
SHADING_ITEMS = (('LIT', "Lit", "Lit by the scene like paint (normal, roughness, glow maps work)"),
                 ('UNLIT', "Unlit (baked)", "Shows the colour as it is, not lit again: for photos or bakes that "
                                            "already hold their lighting"))
OVER_EDGES = (('SQUASH', "Squash", "Projects straight down: flat parts are exact, where the surface turns away the "
                                    "decal squashes into a band"),
              ('BEND', "Bend", "Wraps over edges like a sticker, keeping its size along the surface"),
              ('FADE', "Fade", "Projects straight down and fades out where the surface turns past the Edge Angle"),
              ('BEND_FADE', "Bend, then Fade", "Bends over edges gentler than the Edge Angle, fades out past it"))
BENDS = {'BEND', 'BEND_FADE'}
FADES = {'FADE', 'BEND_FADE'}


def _changed_shape(recipe, context):
    from . import decal_mesh   # decal_mesh uses the recipe; imported here to avoid a cycle
    decal_mesh.recipe_changed(recipe.id_data, rebuild_grid=True)


def _changed_size(recipe, context):
    from . import decal_mesh
    decal_mesh.recipe_changed(recipe.id_data, rebuild_grid=True, size_typed=True)


def _changed_frame(recipe, context):
    from . import decal_mesh
    decal_mesh.recipe_changed(recipe.id_data, rebuild_grid=False)


def _is_mesh(_recipe, ob):
    return ob.type == 'MESH' and not ob.digit_decal.is_decal


def _get_lift(recipe):
    from . import decal_mesh
    return decal_mesh.lift_of(recipe.id_data)


def _set_lift(recipe, value):
    from . import decal_mesh
    decal_mesh.set_lift(recipe.id_data, value)


def _get_detail(recipe):
    from . import decal_mesh
    return decal_mesh.detail_of(recipe.id_data)


def _set_detail(recipe, value):
    from . import decal_mesh
    decal_mesh.set_detail(recipe.id_data, value)


def _get_shading(recipe):
    from . import decal_material
    return 0 if decal_material.shading_of(recipe.id_data.active_material) == 'LIT' else 1


def _set_shading(recipe, value):
    from . import decal_material
    decal_material.set_shading(recipe.id_data.active_material, SHADING_ITEMS[value][0])


def _redraw_viewports(settings, context):
    """The handles' poll runs on a viewport redraw: ask for one when Gizmos On changes."""
    for area in getattr(context.screen, "areas", ()):
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _changed_layer_step(settings, context):
    from . import decal_mesh
    for ob in context.scene.objects:
        if decal_mesh.is_decal(ob):
            decal_mesh.update_layer_lift(ob)


class DecalRecipe(bpy.types.PropertyGroup):
    is_decal: BoolProperty(name="Is Decal", options={'HIDDEN'})
    target: PointerProperty(name="Target", type=bpy.types.Object, poll=_is_mesh,
                            description="The mesh this decal sits on")
    state: EnumProperty(name="State", items=STATES, default=UNATTACHED)
    # Base frame in the Target's local space (world space while Unattached): where it was aimed, the surface normal there, and "up"
    point: FloatVectorProperty(name="Point", size=3, subtype='TRANSLATION', options={'HIDDEN'})
    normal: FloatVectorProperty(name="Normal", size=3, default=(0, 0, 1), subtype='DIRECTION', options={'HIDDEN'})
    up: FloatVectorProperty(name="Up", size=3, default=(0, 1, 0), subtype='DIRECTION', options={'HIDDEN'})
    size: FloatProperty(name="Size", default=0.1, min=0.001, soft_max=1.0, subtype='DISTANCE', unit='LENGTH',
                        update=_changed_size, description="Length of the decal's long side (its real size: a "
                                                          "scale from S is folded in at the next rebuild)")
    rotation: FloatProperty(name="Rotation", default=0.0, subtype='ANGLE', unit='ROTATION', update=_changed_frame,
                            description="Turn around the surface normal")
    crop: FloatVectorProperty(name="Crop", size=4, default=(0, 0, 1, 1), options={'HIDDEN'},
                              description="Visible part of the image as UVs (u0, v0, u1, v1)")
    crop_pixels: bpy.props.IntVectorProperty(name="Crop Pixels", size=2, default=(1, 1), options={'HIDDEN'})
    flip: BoolProperty(name="Flip", update=_changed_shape, description="Mirror the image left to right")
    mirror_x: BoolProperty(name="Mirror X", update=_changed_shape,
                           description="A mirrored copy on the other side of the target (across its X axis)")
    over_edges: EnumProperty(name="Over Edges", items=OVER_EDGES, default='BEND_FADE', update=_changed_shape,
                             description="What the decal does where the surface turns away from it")
    edge_angle: FloatProperty(name="Edge Angle", default=radians(60), min=0.0, max=radians(180), subtype='ANGLE',
                              update=_changed_shape,
                              description="Fade: where the surface turns more than this away from the decal's aim, "
                                          "it fades out")
    layer: IntProperty(name="Layer", min=0, options={'HIDDEN'}, description="Stack order on the target, 0 = bottom")
    target_edge: FloatProperty(name="Target Edge", default=0.01, options={'HIDDEN'},
                               description="Target's average edge length when made: sets the grid density")
    bound_vertex_count: IntProperty(name="Bound Vertex Count", options={'HIDDEN'})
    # Not stored here: views of their one home (the Lift modifier's input, the Detail modifier's levels, the
    # Digit Decal node's Unlit input)
    lift: FloatProperty(name="Lift", min=0.0, soft_max=0.005, step=0.01, precision=2, subtype='DISTANCE', unit='LENGTH',
                        get=_get_lift, set=_set_lift, options={'SKIP_SAVE'},
                        description="How far the decal floats above the surface, in world units whatever its scale "
                                    "(against z-fighting and clipping)")
    detail: IntProperty(name="Detail", min=0, max=decal_maps.MAX_DETAIL, get=_get_detail, set=_set_detail,
                        options={'SKIP_SAVE'},
                        description="Subdivision levels on the light base grid: more hugs tight curves better "
                                    "(renders use one more)")
    shading: EnumProperty(name="Shading", items=SHADING_ITEMS, get=_get_shading, set=_set_shading, options={'SKIP_SAVE'},
                          description="Lit like paint, or Unlit for images that already hold their lighting")

    @property
    def aspect(self):
        return self.crop_pixels[0] / max(1, self.crop_pixels[1])


class DecalSettings(bpy.types.PropertyGroup):
    """The Decals card's own settings (`Scene.digit_decals`)."""
    target: PointerProperty(name="Target", type=bpy.types.Object, poll=_is_mesh,
                            description="The mesh whose decals the card lists, and where new decals go")
    show_gizmos: BoolProperty(name="Gizmos On", update=_redraw_viewports,
                              description="Handles on the active decal: drag inside to slide it over the surface, a "
                                          "corner to size it, the orange dot to rotate it")
    aim_after_place: BoolProperty(name="Aim After Place", default=True,
                                  description="After the click that places a decal (Attach, Re-aim), turn it to face "
                                              "the mouse around the surface normal, then click (Esc keeps the angle)")
    default_lift: FloatProperty(name="Default Lift", default=decal_maps.DEFAULT_LIFT, min=0.0, soft_max=0.005, step=0.01,
                                precision=2, subtype='DISTANCE', unit='LENGTH',
                                description="Lift of new decals (world units)")
    layer_step: FloatProperty(name="Layer Step", default=decal_maps.LAYER_STEP, min=0.0, soft_max=0.001, step=0.001, precision=2,
                              subtype='DISTANCE', unit='LENGTH', update=_changed_layer_step,
                              description="Extra lift per decal layer (bigger decals step further)")


CLASSES = (DecalRecipe, DecalSettings)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_decal = PointerProperty(type=DecalRecipe)
    bpy.types.Scene.digit_decals = PointerProperty(type=DecalSettings)


def unregister():
    del bpy.types.Scene.digit_decals
    del bpy.types.Object.digit_decal
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
