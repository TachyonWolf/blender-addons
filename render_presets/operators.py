# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Presets operators: Apply / Revert / Save Current / Delete for any preset, Reset to Defaults
and Save as My Preset for a built-in's Setup, and Sample World for Depth Fog's colour."""

import bpy
from bpy.props import StringProperty

from . import compositor_chain, look_nodes, preset_choice, preset_store, setup_props


def report_skipped(op, skipped):
    if skipped:
        op.report({'WARNING'}, f"{len(skipped)} setting(s) not available here: {', '.join(skipped[:3])}...")


class RENDERPRESETS_OT_apply(bpy.types.Operator):
    bl_idname = "render_presets.apply"
    bl_label = "Apply Preset"
    bl_description = "Apply the chosen preset to this scene (Revert undoes it)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        preset = preset_choice.selected_preset(context)
        if preset is None:
            self.report({'ERROR'}, "No preset chosen")
            return {'CANCELLED'}
        replaced = compositor_chain.replace_node_count(context.scene, preset)
        report_skipped(self, preset_store.apply_preset(context.scene, preset))
        note = context.scene.get(compositor_chain.NOTE_KEY)
        if note:
            self.report({'WARNING'}, note)
        elif replaced:
            self.report({'INFO'}, "Compositor replaced; Revert restores the old one")
        return {'FINISHED'}

    def invoke(self, context, event):
        preset = preset_choice.selected_preset(context)
        count = compositor_chain.replace_node_count(context.scene, preset) if preset else 0
        if not count:
            return self.execute(context)
        return context.window_manager.invoke_confirm(
            self, event, title="Replace compositor?", confirm_text="Replace",
            message=f"This replaces the scene's current compositor ({count} nodes). Revert brings it back.")


class RENDERPRESETS_OT_revert(bpy.types.Operator):
    bl_idname = "render_presets.revert"
    bl_label = "Revert"
    bl_description = "Put back the settings the applied preset(s) replaced"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return preset_store.can_revert(context.scene)

    def execute(self, context):
        report_skipped(self, preset_store.revert_preset(context.scene))
        return {'FINISHED'}


class RENDERPRESETS_OT_save(bpy.types.Operator):
    bl_idname = "render_presets.save"
    bl_label = "Save Current as Preset"
    bl_description = "Save the ticked groups of the scene's current settings as a preset file"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ui = context.scene.render_presets_ui
        name = ui.save_name.strip()
        if not name or not ui.capture:
            self.report({'ERROR'}, "Give the preset a name and tick at least one group")
            return {'CANCELLED'}
        preset = preset_store.capture_preset(context.scene, name, ui.capture)
        preset_store.save_preset(preset_choice.user_dir(context), preset)
        ui.chosen = preset_choice.choice_id(preset_choice.SAVED, name)
        self.report({'INFO'}, f"Saved preset {name}")
        return {'FINISHED'}


class RENDERPRESETS_OT_delete(bpy.types.Operator):
    bl_idname = "render_presets.delete"
    bl_label = "Delete Preset"
    bl_description = "Delete the chosen saved preset's file (built-ins can't be deleted)"

    @classmethod
    def poll(cls, context):
        return preset_choice.chosen(context)[0] == preset_choice.SAVED

    def execute(self, context):
        name = preset_choice.chosen(context)[1]
        if not preset_store.delete_preset(preset_choice.user_dir(context), name):
            self.report({'WARNING'}, f"No preset file for {name}")
            return {'CANCELLED'}
        context.scene.render_presets_ui.chosen = preset_choice.DEFAULT_CHOICE
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class BuiltinSetupOperator:
    """Poll for the Setup buttons: a built-in is chosen."""

    @classmethod
    def poll(cls, context):
        return preset_choice.builtin_setup(context) is not None


class RENDERPRESETS_OT_reset_setup(BuiltinSetupOperator, bpy.types.Operator):
    bl_idname = "render_presets.reset_setup"
    bl_label = "Reset to Defaults"
    bl_description = "Put this built-in's setup back to its defaults (in this scene)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        setup_props.reset_setup(preset_choice.builtin_setup(context))
        return {'FINISHED'}


class RENDERPRESETS_OT_save_setup(BuiltinSetupOperator, bpy.types.Operator):
    bl_idname = "render_presets.save_setup"
    bl_label = "Save as My Preset"
    bl_description = "Save this setup, with the live Look slider values, as one of your presets"

    name: StringProperty(name="Name")

    def invoke(self, context, event):
        self.name = f"My {preset_choice.builtin_setup(context).builtin_name}"
        return context.window_manager.invoke_props_dialog(self, confirm_text="Save")

    def execute(self, context):
        name = self.name.strip()
        if not name:
            self.report({'ERROR'}, "Give the preset a name")
            return {'CANCELLED'}
        preset = preset_choice.builtin_preset(context.scene, preset_choice.builtin_setup(context))
        preset["name"] = name
        preset_store.save_preset(preset_choice.user_dir(context), preset)
        context.scene.render_presets_ui.chosen = preset_choice.choice_id(preset_choice.SAVED, name)
        self.report({'INFO'}, f"Saved preset {name}")
        return {'FINISHED'}


class RENDERPRESETS_OT_sample_world(bpy.types.Operator):
    bl_idname = "render_presets.sample_world"
    bl_label = "Sample World"
    bl_description = "Set the Fog Colour from the world's colour (or the average of its environment image)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return look_nodes.chain_node(context.scene, look_nodes.FOG_GROUP) is not None

    def execute(self, context):
        colour, problem = look_nodes.world_colour(context.scene)
        if colour is None:
            self.report({'WARNING'}, problem)
            return {'CANCELLED'}
        node = look_nodes.chain_node(context.scene, look_nodes.FOG_GROUP)
        if not look_nodes.write_values(node, {look_nodes.FOG_COLOUR: colour}):
            self.report({'WARNING'}, "Fog Colour could not be written (no matching input)")
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (RENDERPRESETS_OT_apply, RENDERPRESETS_OT_revert, RENDERPRESETS_OT_save, RENDERPRESETS_OT_delete,
           RENDERPRESETS_OT_reset_setup, RENDERPRESETS_OT_save_setup, RENDERPRESETS_OT_sample_world)
