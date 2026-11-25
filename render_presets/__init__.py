# SPDX-License-Identifier: GPL-3.0-or-later
"""Render Presets: apply named bundles of render settings (sidebar tab Render Presets).

Built-in presets live in code (builtin_presets.py) and each has a Setup (setup_props.py / setup_ui.py)
with live Look sliders (look_ui.py); saved presets are JSON files (preset_store.py) in a folder that
can be synced. One dropdown lists both (preset_choice.py). The apply / revert / diff logic
is in preset_store.py and render_settings.py, which the headless apply_preset.py uses too."""

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from . import (builtin_presets as bp, compositor_chain, fog_marks, look_ui, operators, preset_choice, preset_store,
               render_settings, setup_props, setup_ui)
from .operators import RENDERPRESETS_OT_apply, RENDERPRESETS_OT_delete, RENDERPRESETS_OT_revert, RENDERPRESETS_OT_save
from .ui_cards import (action_row, choice_row, diff_row, hints, prop_group, section, setting_label, setting_value, status,  # generated copy
                       sub_heading)

MAX_DIFF_LINES = 8
CHAIN_LABELS = {option.chain_group: option.label for option in bp.options_in_group(bp.LOOK)}
CAPTURE_ITEMS = [(group, group.title(), "") for group in render_settings.CAPTURE_GROUPS]


# ---------------------------------------------------------------------------
# Properties and preferences
# ---------------------------------------------------------------------------

RenderPresetsUI = type("RenderPresetsUI", (bpy.types.PropertyGroup,), {"__annotations__": {
    "chosen": StringProperty(name="Chosen Preset", default=preset_choice.DEFAULT_CHOICE,
                             description="builtin:<name> or saved:<name>"),
    "picker": setup_props.string_picker("Preset", preset_choice.picker_items, "chosen",
                                        description="Built-in presets, then your saved presets"),
    "save_name": StringProperty(name="Name", default="My Preset"),
    "capture": EnumProperty(name="Capture", items=CAPTURE_ITEMS, options={'ENUM_FLAG'},
                            default={"samples", "resolution", "colour"}),
    "show_diff": BoolProperty(name="Show changes", default=True),
    **setup_props.setup_pointers(),
}})


class RenderPresetsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    presets_dir: StringProperty(name="Presets folder", subtype='DIR_PATH', default=preset_choice.DEFAULT_PRESETS_DIR,
                                description="Folder of your saved preset JSON files (put it in a synced folder)")

    def draw(self, context):
        self.layout.prop(self, "presets_dir")


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class RENDERPRESETS_PT_panel(bpy.types.Panel):
    bl_label = "Render Presets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Render Presets"

    def draw(self, context):
        draw_card(self.layout, context)


def draw_card(layout, context):
    scene = context.scene
    ui = scene.render_presets_ui
    body = layout   # the panel title is "Render Presets"
    applied = scene.get(preset_store.APPLIED_KEY)
    status(body, f"Applied · {applied}" if applied else "Pick a preset and press Apply",
           icon='CHECKMARK' if applied else 'INFO')
    body.prop(ui, "picker", text="")
    setup = preset_choice.builtin_setup(context)
    if setup is not None:
        hints(body, ["Built-in · tune it in Setup below"], context)
    row = action_row(body)
    row.operator(RENDERPRESETS_OT_apply.bl_idname, icon='CHECKMARK')
    row.operator(RENDERPRESETS_OT_revert.bl_idname, icon='LOOP_BACK')
    if setup is None:
        row.operator(RENDERPRESETS_OT_delete.bl_idname, text="", icon='TRASH')
    note = scene.get(compositor_chain.NOTE_KEY)
    hints(body, [note] if note else [], context)
    preset = preset_choice.selected_preset(context)
    if preset is not None:
        draw_diff(body, scene, preset, context)
    if setup is not None:
        setup_ui.draw_setup(body, context, setup)
    elif preset is not None:
        look_ui.draw_saved_look(body, context)
    save = section(body, "render_presets_save", "Save Current as Preset", icon='FILE_TICK', default_closed=True)
    if save:
        prop_group(save, ui, [("save_name", "Name")])
        sub_heading(save, "Include")
        choice_row(save, ui, "capture", vertical=True)
        save.operator(RENDERPRESETS_OT_save.bl_idname, icon='FILE_TICK')


def chain_text(labels):
    return ", ".join(CHAIN_LABELS.get(label, label) for label in labels) or "None"


def compositor_change(scene, preset):
    """(now, after) texts for the Changes section's Compositor row, or None when Apply leaves it alone."""
    wanted = preset.get("compositor_chain")
    if not wanted:
        return None
    tree = compositor_chain.current_tree(scene)
    present = compositor_chain.chain_groups_in(tree)
    if present:
        now = chain_text(present)
    else:
        now = "None" if compositor_chain.is_trivial(tree) else f"{len(tree.nodes)} nodes"
    after = chain_text(wanted)
    return None if now == after else (now, after)


def draw_diff(layout, scene, preset, context):
    changes = preset_store.preset_diff(scene, preset)
    compositor = compositor_change(scene, preset)
    sec = section(layout, "render_presets_changes", "Changes", icon='DOCUMENTS',
                  right=f"{len(changes)} setting{'' if len(changes) == 1 else 's'}")
    if not sec:
        return
    col = sec.column(align=True)
    if compositor:
        diff_row(col, "Compositor", *compositor)
    if not changes and not compositor:
        col.label(text="Nothing would change")
    for path, old, new in changes[:MAX_DIFF_LINES]:
        owner, attr = render_settings._owner_and_attr(scene, path)
        diff_row(col, setting_label(owner, attr), setting_value(owner, attr, old), setting_value(owner, attr, new))
    if len(changes) > MAX_DIFF_LINES:
        hints(col, [f"and {len(changes) - MAX_DIFF_LINES} more"], context)


CLASSES = (*setup_props.SETUP_CLASSES.values(), RenderPresetsUI, RenderPresetsPreferences, *operators.CLASSES,
           RENDERPRESETS_PT_panel)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.render_presets_ui = PointerProperty(type=RenderPresetsUI)
    fog_marks.register()


def unregister():
    fog_marks.unregister()
    del bpy.types.Scene.render_presets_ui
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
