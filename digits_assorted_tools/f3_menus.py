# SPDX-License-Identifier: GPL-3.0-or-later
"""F3 menu entries: Blender's F3 search only finds operators that sit in a menu, so every one-shot tool command of
Digit's Assorted Tools gets a line in a Blender menu. ONE table (`ENTRIES`) holds them all: (Blender menu class name,
draw function). `menu_entries.append_menus` / `remove_menus` register and remove a table of that shape. The commands use the card's current settings; the tool's own redo panel keeps the options adjustable."""

from .menu_entries import append_menus, remove_menus
from . import decal_ui
from . import (bbone_builder_ui, bones_in_front, bounce_cards, camera_rig, catchlight, composition_overlay, fast_viewport,
               helper_object_ui, light_rig, look_at, mirrored_mesh_ui, origin_tool, path_generators, photo_backdrop, pose_as_rest_ui, rig_stress_ui, shadow_catcher, span_ui,
               weight_tools_ui)

# Ids of operators defined in __init__.py (importing it from here would be circular)
COMBINE_OPERATOR = "digits_assorted_tools.combine_multi_part"


def entry_drawer(operator_id, text, icon='NONE', only_in_mode=None, properties=None):
    """A menu draw function with one operator line; `only_in_mode`: show it in that context mode only; `properties`:
    {operator property: value} set on the line."""
    def draw(self, context):
        if only_in_mode is None or context.mode == only_in_mode:
            operator = self.layout.operator(operator_id, text=text, icon=icon)
            for name, value in (properties or {}).items():
                setattr(operator, name, value)
    draw.__name__ = "draw_" + operator_id.replace(".", "_") + "".join(f"_{value}" for value in (properties or {}).values())
    return draw


def draw_lighting_rig_styles(self, context):
    self.layout.menu(light_rig.VIEW3D_MT_lighting_rig_add.bl_idname, icon='LIGHT_AREA')


def path_generator_entries():
    """Add > Curve > Spiral Curve / Knot Curve and Add > Mesh > Maze: one line per path generator, from its table."""
    return tuple((generator.add_menu, entry_drawer(path_generators.DIGITOOLS_OT_add_path_generator.bl_idname, generator.label,
                                                   generator.icon, only_in_mode='OBJECT', properties={"generator": generator.key}))
                 for generator in path_generators.spec.GENERATORS)


ENTRIES = (   # (Blender UI class name, our draw function)
    ("VIEW3D_MT_object_context_menu", decal_ui.draw_convert_entry),
    ("VIEW3D_MT_image_add", entry_drawer("decal.add_images", "Decal from Images…", 'IMAGE_PLANE', only_in_mode='OBJECT')),
    *path_generator_entries(),
    ("VIEW3D_MT_mesh_add", entry_drawer(mirrored_mesh_ui.DIGITOOLS_OT_add_mirrored_mesh.bl_idname, "Add Mirrored Mesh")),
    ("VIEW3D_MT_mesh_add", entry_drawer(photo_backdrop.PHOTOBACKDROP_OT_deploy.bl_idname, "Add Photo Backdrop",
                                        only_in_mode='OBJECT')),
    ("VIEW3D_MT_mesh_add", entry_drawer(shadow_catcher.SHADOWCATCHER_OT_deploy.bl_idname, "Add Shadow Catcher Floor",
                                        only_in_mode='OBJECT')),
    ("VIEW3D_MT_camera_add", entry_drawer(camera_rig.CAMERARIG_OT_deploy.bl_idname, "Add Camera Rig")),
    ("VIEW3D_MT_light_add", entry_drawer(light_rig.LIGHTRIG_OT_deploy.bl_idname, "Add Lighting Rig")),
    ("VIEW3D_MT_light_add", draw_lighting_rig_styles),
    ("VIEW3D_MT_light_add", entry_drawer(bounce_cards.BOUNCECARD_OT_deploy.bl_idname, "Add Bounce Cards", 'LIGHT_AREA')),
    ("VIEW3D_MT_light_add", entry_drawer(catchlight.CATCHLIGHT_OT_deploy.bl_idname, "Add Catchlight")),
    ("VIEW3D_MT_empty_add", entry_drawer(helper_object_ui.DIGITOOLS_OT_add_helper_object.bl_idname,
                                         "Add Modifier Helper", 'SHADING_WIRE')),
    ("VIEW3D_MT_object_convert", entry_drawer(helper_object_ui.DIGITOOLS_OT_make_helper_object.bl_idname,
                                              "Make Modifier Helper", 'SHADING_WIRE')),
    ("VIEW3D_MT_armature_add", entry_drawer(span_ui.DIGITOOLS_OT_span_add.bl_idname, "Add Bendy Span Bone",
                                            only_in_mode='EDIT_ARMATURE')),
    ("VIEW3D_MT_armature_add", entry_drawer(bbone_builder_ui.DIGITOOLS_OT_bbone_add_points.bl_idname,
                                            "Place B-Bone Chain Points", 'CURVE_BEZCURVE', only_in_mode='EDIT_ARMATURE')),
    ("VIEW3D_MT_pose_showhide", entry_drawer(bones_in_front.DIGITOOLS_OT_toggle_bones_in_front.bl_idname,
                                             "Toggle Bones In Front")),
    ("VIEW3D_MT_pose_constraints", entry_drawer(look_at.DIGITOOLS_OT_look_at.bl_idname, "Toggle Look At",
                                                only_in_mode='POSE')),
    ("VIEW3D_MT_pose", entry_drawer(rig_stress_ui.DIGITOOLS_OT_rig_stress_step.bl_idname, "Next Stress Pose",
                                    'TRIA_RIGHT', only_in_mode='POSE', properties={"direction": 1})),
    ("VIEW3D_MT_pose", entry_drawer(rig_stress_ui.DIGITOOLS_OT_rig_stress_step.bl_idname, "Previous Stress Pose",
                                    'TRIA_LEFT', only_in_mode='POSE', properties={"direction": -1})),
    ("VIEW3D_MT_pose_apply", entry_drawer(pose_as_rest_ui.DIGITOOLS_OT_pose_as_rest.bl_idname, "Apply Pose as Rest (with Meshes)",
                                          only_in_mode='POSE')),
    ("VIEW3D_MT_view", entry_drawer(fast_viewport.DIGITOOLS_OT_fast_viewport.bl_idname, "Toggle Fast Viewport")),
    ("VIEW3D_MT_view", entry_drawer(composition_overlay.DIGITOOLS_OT_toggle_composition_guides.bl_idname,
                                    "Toggle Composition Guides")),
    ("VIEW3D_MT_paint_weight", entry_drawer(weight_tools_ui.WEIGHTS_OT_remove_islands.bl_idname,
                                            "Remove Disconnected Weight Islands")),
    ("VIEW3D_MT_object", origin_tool.draw_origin_menu),
    ("VIEW3D_MT_edit_mesh", entry_drawer(origin_tool.DIGITOOLS_OT_set_origin.bl_idname, "Set Origin to Selection",
                                         'OBJECT_ORIGIN', only_in_mode='EDIT_MESH', properties={"target": 'SELECTION'})),
    ("VIEW3D_MT_object_apply", entry_drawer(COMBINE_OPERATOR, "Combine Into One Model")),
)


def register():
    append_menus(ENTRIES)


def unregister():
    remove_menus(ENTRIES)
