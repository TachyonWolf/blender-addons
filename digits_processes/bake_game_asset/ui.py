# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake to Game Asset: its options (`Object.digit_bake_game_asset` on the character's rig, next to Game Rig's own
`digit_game_rig` options, which this card shows too), operators and card. Draw reads a few properties and the cheap
add-on lookups only; triangles are counted on Rescan and after a run, never in draw."""
import os

import bpy
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty

from .. import assorted_tools
from ..ui_cards import action_row, hints, poll_message, prop_group, section, status  # generated copy
from . import process

NOT_COUNTED = -1


class BakeGameAssetOptions(bpy.types.PropertyGroup):
    low_poly: BoolProperty(name="Reduce Triangles", default=False,
                           description="Cut the game copy down to about the Target Triangles (Decimate Collapse; "
                                       "UVs and weights are kept)")
    target_triangles: IntProperty(name="Target Triangles", default=process.DEFAULT_TARGET_TRIANGLES, min=100,
                                  soft_max=200000, description="About how many triangles the whole game copy keeps")
    warn_above: IntProperty(name="Warn Above", default=process.DEFAULT_WARN_ABOVE, min=100, soft_max=500000,
                            description="The card warns when the triangle count is over this. A PC hero is about "
                                        "50-100k; phones and VR want 10-30k")
    triangles: IntProperty(default=NOT_COUNTED, options={'HIDDEN'}, description="Last triangle count (-1: not counted)")
    triangles_of: StringProperty(options={'HIDDEN'}, description="What the last count was of: game copy or source")
    report: StringProperty(name="Report", description="What the last Make Game Asset did")


def options_of(main):
    return main.digit_bake_game_asset


def main_rig(context):
    """The character's root rig, or None (also when Digit's Assorted Tools is off)."""
    game_ui = assorted_tools.optional_module("game_rig_ui", context)
    return game_ui.main_rig(context) if game_ui else None


class DIGITPROCESSES_OT_count_triangles(bpy.types.Operator):
    """Count the triangles of the game copy (or, before one exists, of the meshes it will be made from)"""
    bl_idname = "digit_processes.count_triangles"
    bl_label = "Rescan"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return main_rig(context) is not None

    def execute(self, context):
        main = main_rig(context)
        options = options_of(main)
        options.triangles, options.triangles_of = process.count_triangles(context, main)
        return {'FINISHED'}


class DIGITPROCESSES_OT_bake_game_asset(bpy.types.Operator):
    """Make a game-ready copy: simple rig, optional low-poly, procedural materials baked to textures, then export.
    The original rig, meshes and materials are not changed"""
    bl_idname = "digit_processes.bake_game_asset"
    bl_label = "Make Game Asset"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT' or not assorted_tools.is_enabled(context):
            return False
        main = main_rig(context)
        return poll_message(cls, process.problem(context, main) if main else "Select the character (or its rig)")

    def execute(self, context):
        main = main_rig(context)
        options = options_of(main)
        try:
            result, game_report = process.run(context, main, options.low_poly, options.target_triangles)
        except (ValueError, RuntimeError) as error:   # assorted_tools.Missing is a RuntimeError
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        options.triangles, options.triangles_of = result.triangles_after, "game copy"
        options.report = result.line(process.tools(context).game_rig.info_line(game_report))
        self.report({'WARNING' if result.export_error or result.problems else 'INFO'}, options.report)
        return {'FINISHED'}


def count_line(main, options):
    if options.triangles == NOT_COUNTED:
        return f"{main.name}: triangles not counted yet"
    return f"{main.name}: {options.triangles:,} triangles ({options.triangles_of})"


def draw_card(layout, context):
    body = layout   # the process dropdown is the title
    if not assorted_tools.is_enabled(context):
        status(body, "Needs Digit's Assorted Tools", icon='ERROR')
        hints(body, ["Enable it in Preferences > Add-ons: this process chains its Game Rig and Procedural Baker."], context)
        return
    main = main_rig(context)
    if main is None:
        status(body, "Select the character (or its rig)")
        return
    kit = process.tools(context)
    options, game_options = options_of(main), main.digit_game_rig
    row = body.row(align=True)
    row.label(text=count_line(main, options), icon='MESH_DATA')
    row.operator(DIGITPROCESSES_OT_count_triangles.bl_idname, text="", icon='FILE_REFRESH')
    over = options.triangles != NOT_COUNTED and options.triangles > options.warn_above
    if over:
        status(body, f"Over {options.warn_above:,} triangles" + ("" if options.low_poly else ": try Reduce Triangles"),
               icon='ERROR')
    action_row(body, 1.6).operator(DIGITPROCESSES_OT_bake_game_asset.bl_idname, icon='EXPORT')
    why = process.problem(context, main)
    hints(body, [why, options.report], context)
    rig = section(body, "digit_processes_game_asset_rig", "Rig", icon='ARMATURE_DATA')
    if rig:
        prop_group(rig, game_options, ["engine", None, "fingers", "face", "parts"])
    low = section(body, "digit_processes_game_asset_low", "Low-Poly", icon='MOD_DECIM',
                  right=f"{options.target_triangles:,}" if options.low_poly else "off")
    if low:
        prop_group(low, options, ["low_poly"])
        column = low.column()
        column.active = options.low_poly
        prop_group(column, options, ["target_triangles"])
        prop_group(low, options, ["warn_above"])
    kit.baker.draw_map_options(body, context.scene.procedural_baker)
    hints(body, ["Bakes only procedural materials, one set per mesh and material; image textures stay as they are"],
          context)
    auto = kit.game_ui.output_path(main, auto=True)
    kit.output_file.draw_output(body, "digit_processes_game_asset_output", game_options, "output_name", "output_folder",
                                os.path.basename(auto) if auto else main.name,
                                kit.output_file.resolve_folder("", bpy.data.filepath),
                                with_folder=game_options.output != kit.game_ui.THIS_FILE,
                                extra=lambda col: col.prop(game_options, "output"))


CLASSES = (BakeGameAssetOptions, DIGITPROCESSES_OT_count_triangles, DIGITPROCESSES_OT_bake_game_asset)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_bake_game_asset = PointerProperty(type=BakeGameAssetOptions)


def unregister():
    del bpy.types.Object.digit_bake_game_asset
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
