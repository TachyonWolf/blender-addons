# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's Assorted Tools: the Selected card at the top of the panel (selected_ui.py): the live controls of a selected
Camera Rig, Lighting Rig, Bounce Card, Photo Backdrop, Shadow Catcher Floor or Catchlight. Below it the tool
card, whose header is the tool dropdown. Convert: Make Modifier Helper (selected objects become modifier helpers).
Object: Add Mirrored Mesh (a primitive as only the half a Mirror modifier completes; mirrored_mesh*.py), Add Modifier Helper (a styled primitive at the 3D cursor; helper_object_ui.py). Export: Combine Into One Model (Combine
Multi Part Model: a rigged character's parts and nested rigs into one rig + one mesh, saved as a new file; output name
and folder in output_file.py) and Game Rig (game_rig_ui.py, also exports FBX / glTF / Blend). Character Rigs: Combine
Bones (combine_bones_ui.py), Bone Workshop (bone_workshop*.py: shape, size, colour, collections, settings and name of
the selected bones and their mirror bones; Rig Check in rig_check.py), Full Character Rig (full_rig_ui.py; its Existing Rig section holds Rebuild Face, Upgrade Limbs
and Sort Bone Collections for rigs made before it: face_rig_ui.py / limbs_ui.py keep their operators), Rename Bones (rename_ui.py, logic in rig_rename.py) and
Bendy Span Bone (span_ui.py, logic in span_bones.py), B-Bone Chain Builder (bbone_builder_ui.py, logic in bbone_builder.py). Weights: Combined Weight From Bones (bone_chain_ui.py, shared with
Digit's Modifiers: a vertex group from a bone chain's summed weights, minus Excluded Bones).
Check also has Pre-Render Check (pre_render_check.py); Scene: Composition Guides (composition_overlay.py) and Fast Viewport (fast_viewport.py); Character Rigs also has
Save Pose (save_pose.py) and Rig Stress Pose Test (rig_stress_ui.py, logic in rig_stress.py). Folded in from former add-ons: Reset Pose / IK-FK snap / parent switch operators (pose_ops.py, the
Pose > Transform menu entry; the rig panel's part, bone group, reset and copy operators in rig_panel_ops.py), Bones In Front While Posing (Scene;
bones_in_front.py, the one timer, on only while its preference is on) and Procedural Baker (Export; procedural_baker.py).
Remove Disconnected Islands and Merge Vertex Groups (weight_tools_ui.py, logic in weight_cleanup.py).
Setups: Camera Rig, Lighting Rig, Photo Backdrop, Shadow Catcher Floor, HDRI World; the Lighting Rig card also holds the
folded Catchlight (catchlight.py) and Bounce Cards (bounce_cards.py) Deploy sections and Catchlight's Remove (they are no longer
dropdown tools).
Texture: UV Rebake (uv_rebake_ui.py, logic in uv_rebake.py).
Scene > Texture Studio (texture_studio/: the starter card; its own sidebar panel shows only in a studio scene; File > New > Texture Studio).
The sidebar panel shows one tool at a time, picked in a dropdown (the TOOLS registry below).

Self-contained on purpose: the extension is installed as a copy, so it can't import the
charfix scripts that live next to it in the source folder.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from .ui_cards import action_row, header_right, hints, prop_group, section, status, toggles  # generated copy
from . import bbone_builder_ui, bone_chain_ui, bone_workshop_ui, bounce_cards, camera_rig, catchlight, character_rig, bones_in_front, make_posable, composition_overlay, rig_placement, combine_bones_ui, digit_world_library, face_rig_ui, fast_viewport, full_rig_ui, game_rig_ui, hdri_world, helper_object_ui, light_rig, limbs_ui, look_at, move_alone, f3_menus, mirror_pivot, mirror_pivot_tools, mirrored_mesh_ui, placement_tool, origin_tool, output_file as of, path_generators, photo_backdrop, pose_as_rest_ui, pose_ops, pose_shape_keys, rig_panel_ops, pre_render_check, procedural_baker, rename_ui, rig_component_ui, rig_modifiers, rig_stress_ui, save_pose, select_non_manifold_smart, selected_ui, shadow_catcher, span_ui, weight_tools_ui
from .scene_checks import belongs_to, find_rig, rig_of_object  # noqa: F401  (generated copy; also used by other modules)
from .combine_model import make_whole, save_as_whole, split_parts, whole_path  # noqa: F401  (tests call split_parts and whole_path)
from . import drivers_ui, oops_ui, uv_rebake_ui
from . import decal_recipe, decal_state_ops, decal_layer_ops, decal_import_ops, decal_drop, decal_gizmo, decal_ui
from .texture_studio import panel as texture_studio_ui
from . import rig_switches_ui  # generated copy: the rig card's search field
from . import prefs, tool_menu
from .tool_menu import BEGINNER, EXPERT
from .tool_picker import enum_items, tool_id  # generated copy of shared_addon/tool_picker.py
from .prefs import DigitToolsPreferences



# ---------------------------------------------------------------------------
# Operator and panel
# ---------------------------------------------------------------------------

REMOVE_HIDDEN_HELP = "On: hidden parts of the character are left out of the merge and deleted. Off: everything is merged, hidden parts included"
DROP_NORMALS_HELP = "On: the combined mesh has no custom split normals (Geometry Nodes modifiers work badly on meshes with them). Off: normals are kept"


def keep_names_of(scene):
    return [n.strip() for n in scene.whole_keep_collections.split(",") if n.strip()]


class CHARTOOLS_OT_combine(bpy.types.Operator):
    """Combine the character's parts and nested rigs into one rig + one mesh, save as a new file"""
    bl_idname = "digits_assorted_tools.combine_multi_part"
    bl_label = "Combine Multi Part Model"
    bl_options = {'REGISTER'}

    drop_normals: BoolProperty(
        name="Clear custom normals", default=False,
        description=DROP_NORMALS_HELP)

    @classmethod
    def poll(cls, context):
        return find_rig(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rig = find_rig(context)
        whole, report = make_whole(context, rig, keep_names_of(context.scene), context.scene.whole_remove_hidden, self.drop_normals)
        if whole is None:
            self.report({'WARNING'}, report.summary())
            return {'CANCELLED'}
        scene = context.scene
        path = save_as_whole(scene.whole_output_name, scene.whole_output_folder, rig.name)
        text = report.summary()
        text += f". Saved as {os.path.basename(path)}" if path else ". File not saved yet: done in place"
        self.report({'WARNING'} if report.warnings else {'INFO'}, text)
        return {'FINISHED'}


class CHARTOOLS_PT_selected(bpy.types.Panel):
    """The Selected panel: its own top-level sidebar panel (collapse, drag to reorder), first in the tab."""
    bl_label = "Selected"
    bl_idname = "CHARTOOLS_PT_selected"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Digit's Tools"
    bl_order = 0

    def draw_header_preset(self, context):
        header_right(self.layout, selected_ui.header_summary(context))

    def draw(self, context):
        selected_ui.draw_body(self.layout, context)


class CHARTOOLS_PT_panel(bpy.types.Panel):
    """The Tools panel: the tool dropdown on top, the chosen tool's card under it."""
    bl_label = "Tools"
    bl_idname = "CHARTOOLS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Digit's Tools"
    bl_order = 1

    def draw(self, context):
        chosen = context.window_manager.digit_tool
        tool_menu.draw_legend(self.layout)
        tool_menu.draw_dropdown(self.layout, chosen)
        draw_tool(self.layout, context, chosen)

    @staticmethod
    def draw_combine(layout, context):
        scene = context.scene
        rig = find_rig(context)
        body = layout   # the tool dropdown is the title
        if rig is None:
            status(body, "Select the character (or its rig)")
            return
        parts, spares = split_parts(context, rig, keep_names_of(scene), scene.whole_remove_hidden)
        status(body, f"{len(parts)} to merge · {len(spares)} to delete", icon='ARMATURE_DATA')
        op = action_row(body).operator(CHARTOOLS_OT_combine.bl_idname, icon='MESH_DATA')
        op.drop_normals = scene.whole_drop_normals
        path = whole_path(bpy.data.filepath, scene.whole_output_name, scene.whole_output_folder, rig.name)
        hints(body, [f"Saves as {os.path.basename(path)}" if path else "File not saved yet: done in place"], context)
        opts = section(body, "chartools_combine_options", "Options", icon='PREFERENCES')
        if opts:
            toggles(opts, scene, [("whole_remove_hidden", "Remove Hidden Parts"),
                                  ("whole_drop_normals", "Clear Custom Normals")], columns=1)
            prop_group(opts, scene, [("whole_keep_collections", "Keep Collections")])
        auto = whole_path(bpy.data.filepath, "", scene.whole_output_folder, rig.name)
        of.draw_output(body, "chartools_combine_output", scene, "whole_output_name", "whole_output_folder",
                       os.path.basename(auto) if auto else "", of.resolve_folder("", bpy.data.filepath))


CHAIN_TOOL = bone_chain_ui.BoneChainTool(__package__)   # the combined weight group tool (shared with Digit's Modifiers)

# The tools the panel's dropdown offers: one row each, (category, label, draw function(layout, context), icon,
# skill badge (BEGINNER, EXPERT or None)). Adding a tool = adding its row here. The dropdown lists categories as
# headings, tools A-Z under each.
TOOL_ROWS = (
    ("Export", "Combine Into One Model", CHARTOOLS_PT_panel.draw_combine, 'PACKAGE', None),
    ("Check", "Oops Debugger", oops_ui.draw_card, 'ERROR', BEGINNER),
    ("Check", "Pre-Render Check", pre_render_check.draw_card, 'CHECKMARK', None),
    ("Convert", "Make Modifier Helper", helper_object_ui.draw_card, 'EMPTY_ARROWS', EXPERT),
    ("Object", "Add Mirrored Mesh", mirrored_mesh_ui.draw_card, 'MOD_MIRROR', BEGINNER),
    ("Object", "Add Modifier Helper", helper_object_ui.draw_add_card, 'EMPTY_AXIS', None),
    ("Object", "Decals", decal_ui.draw_card, 'IMAGE_PLANE', None),
    ("Object", "Origin Tool", origin_tool.draw_card, 'OBJECT_ORIGIN', BEGINNER),
    ("Object", "Path Generators", path_generators.draw_card, 'CURVE_DATA', BEGINNER),
    ("Character Rigs", "Add Rig Component", rig_component_ui.draw_card, 'BONE_DATA', None),
    ("Character Rigs", "Bone Workshop", bone_workshop_ui.draw_card, 'BONE_DATA', BEGINNER),
    ("Character Rigs", "Combine Bones", combine_bones_ui.draw_card, 'GROUP_BONE', EXPERT),
    ("Character Rigs", "Drivers", drivers_ui.draw_card, 'DRIVER', EXPERT),
    ("Character Rigs", "Full Character Rig", full_rig_ui.draw_card, 'ARMATURE_DATA', None),
    ("Character Rigs", "Look At", look_at.draw_card, 'HIDE_OFF', None),
    ("Character Rigs", "Rename Bones", rename_ui.draw_card, 'SORTALPHA', EXPERT),
    ("Character Rigs", "Apply Pose as Rest", pose_as_rest_ui.draw_card, 'MOD_ARMATURE', EXPERT),
    ("Character Rigs", "Rig Stress Pose Test", rig_stress_ui.draw_card, 'MOD_SIMPLEDEFORM', None),
    ("Character Rigs", "Poses to Shape Keys", pose_shape_keys.draw_card, 'SHAPEKEY_DATA', EXPERT),
    ("Character Rigs", "Save Pose", save_pose.draw_card, 'POSE_HLT', None),
    ("Character Rigs", "Bendy Span Bone", span_ui.draw_card, 'BONE_DATA', None),
    ("Character Rigs", "B-Bone Chain Builder", bbone_builder_ui.draw_card, 'CURVE_BEZCURVE', None),
    ("Export", "Game Rig", game_rig_ui.draw_card, 'EXPORT', EXPERT),
    ("Export", "Procedural Baker", procedural_baker.draw_card, 'NODE_TEXTURE', EXPERT),
    ("Scene", "Bones In Front", bones_in_front.draw_card, 'XRAY', None),
    ("Scene", "Composition Guides", composition_overlay.draw_card, 'MESH_GRID', None),
    ("Scene", "Fast Viewport", fast_viewport.draw_card, 'TIME', None),
    ("Setups", "Camera Rig", camera_rig.draw_card, 'CAMERA_DATA', BEGINNER),
    ("Setups", "HDRI World", hdri_world.draw_card, 'WORLD', BEGINNER),
    ("Setups", "Photo Backdrop", photo_backdrop.draw_card, 'IMAGE_BACKGROUND', BEGINNER),
    ("Setups", "Shadow Catcher Floor", shadow_catcher.draw_card, 'CON_FLOOR', None),
    ("Setups", "Lighting Rig", light_rig.draw_card, 'LIGHT', BEGINNER),
    ("Weights", bone_chain_ui.DISPLAY_NAME, CHAIN_TOOL.draw_body, 'GROUP_VERTEX', None),
    ("Weights", weight_tools_ui.MERGE_NAME, weight_tools_ui.draw_merge_card, 'AUTOMERGE_ON', None),
    ("Weights", weight_tools_ui.ISLAND_NAME, weight_tools_ui.draw_island_card, 'UNLINKED', None),
    ("Scene", "Texture Studio", texture_studio_ui.draw_card, 'IMAGE_DATA', None),
    ("Texture", "UV Rebake", uv_rebake_ui.draw_card, 'UV', EXPERT),
    )
TOOLS = tuple((category, label, draw) for category, label, draw, _icon, _badge in TOOL_ROWS)   # what the tests and the menus read
TOOL_LOOKS = {label: (icon, badge) for _category, label, _draw, icon, badge in TOOL_ROWS}      # icon and badge by label


def sorted_tools():
    return sorted(TOOLS, key=lambda tool: (tool[0], tool[1]))


def tool_items():
    return enum_items([(category, label) for category, label, _ in sorted_tools()])


TOOL_ITEMS = tool_items()  # kept at module level: Blender reads the list lazily


def draw_tool(layout, context, chosen):
    """Draw the card of the chosen tool."""
    for _, label, draw in TOOLS:
        if tool_id(label) == chosen:
            draw(layout, context)


classes = (DigitToolsPreferences, CHARTOOLS_OT_combine, CHARTOOLS_PT_selected, CHARTOOLS_PT_panel, *tool_menu.classes, *character_rig.classes, *make_posable.classes, *rig_modifiers.classes)


# Modules with their own register() and unregister(), registered in this order and unregistered in reverse.
MODULES = (
    CHAIN_TOOL, weight_tools_ui, oops_ui, drivers_ui, fast_viewport, origin_tool, composition_overlay, save_pose,
    look_at, move_alone, rig_stress_ui, pose_shape_keys, pose_as_rest_ui, face_rig_ui, limbs_ui, full_rig_ui,
    rig_component_ui, rename_ui, span_ui, bbone_builder_ui, game_rig_ui, combine_bones_ui, bone_workshop_ui,
    helper_object_ui, mirrored_mesh_ui, path_generators, rig_placement, camera_rig, light_rig, hdri_world,
    bounce_cards, photo_backdrop, shadow_catcher, catchlight, pose_ops, rig_panel_ops, bones_in_front,
    procedural_baker, select_non_manifold_smart, mirror_pivot, mirror_pivot_tools, placement_tool, f3_menus,
    uv_rebake_ui, texture_studio_ui, decal_recipe, decal_state_ops, decal_layer_ops, decal_import_ops, decal_drop,
    decal_gizmo,
)


def register():
    prefs.register()   # before the preferences class, which points at its settings
    rig_switches_ui.register()   # early: others use its properties
    bpy.types.WindowManager.digit_tool = EnumProperty(
        name="Tool", items=TOOL_ITEMS, default=tool_id(sorted_tools()[0][1]),
        description="Which tool the panel shows")
    bpy.types.Scene.whole_keep_collections = StringProperty(
        name="Keep Collections",
        description="Comma separated collection names whose objects are never merged or deleted (WIP)")
    bpy.types.Scene.whole_remove_hidden = BoolProperty(
        name="Remove hidden child items", default=False,
        description=REMOVE_HIDDEN_HELP)
    bpy.types.Scene.whole_output_name = of.name_property()
    bpy.types.Scene.whole_output_folder = of.folder_property()
    bpy.types.Scene.whole_drop_normals = BoolProperty(
        name="Clear custom normals", default=False, description=DROP_NORMALS_HELP)
    for cls in classes:
        bpy.utils.register_class(cls)
    for module in MODULES:
        module.register()
    digit_world_library.add_library()


def unregister():
    digit_world_library.remove_library()
    for module in reversed(MODULES):
        module.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.whole_keep_collections
    del bpy.types.Scene.whole_remove_hidden
    del bpy.types.Scene.whole_drop_normals
    del bpy.types.Scene.whole_output_name
    del bpy.types.Scene.whole_output_folder
    del bpy.types.WindowManager.digit_tool
    rig_switches_ui.unregister()
    prefs.unregister()
