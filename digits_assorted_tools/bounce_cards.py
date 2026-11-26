# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounce Cards (Digit's Tools > Setups): Deploy button, sliders, drivers and card for the Bounce Cards asset.

The rig: BC_Rig (root, every slider is a custom property; Track To BC_Focus) > BC_Card (the panel,
a plane with a Curve shape key and a Principled material) and BC_Light (area light in front of it, used in Fake
mode). BC_Focus is a free empty. Names, sliders and presets live in bounce_cards_spec."""

import bpy
from bpy.props import BoolProperty, EnumProperty

from . import bounce_cards_spec as spec
from . import light_rig_spec
from . import rig_common, rig_placement as placement, selected_ui
from .rig_common import find_root, pointer, select_only
from .ui_cards import enum_label, prop_group, section, status, sub_heading  # generated copy


# ---------------------------------------------------------------------------
# Finding the rig
# ---------------------------------------------------------------------------

def part(rig, name):
    """Rig part: 'rig', 'card', 'light' or 'focus'."""
    return rig if name == "rig" else pointer(rig, "bc_" + name)


def find_rig(context):
    return find_root(context, spec.ROOT_TAG, spec.PART_TAG, lambda rig: [part(rig, p) for p in spec.PARTS])


def aim_constraint(rig):
    return rig.constraints[spec.AIM_CONSTRAINT]


# ---------------------------------------------------------------------------
# Sliders and drivers (also used by Scripts/bounce_cards/build_bounce_cards.py)
# ---------------------------------------------------------------------------

def define_props(rig):
    rig_common.define_props(rig, spec.PROPS, spec.stored)


def _owner(rig, target):
    return {"rig": rig, "card": part(rig, "card"), "light": part(rig, "light").data,
            "shape": part(rig, "card").data.shape_keys,
            "material": part(rig, "card").active_material.node_tree}[target]


def add_drivers(rig):
    for target, path, index, expression, variables in spec.driven_fields():
        rig_common.add_scripted_driver(_owner(rig, target), path, index, rig, variables, expression)
    rig.update_tag()


def apply_preset(rig, name):
    for prop, value in spec.PRESETS[name].items():
        rig[prop] = spec.stored(prop, value)
    rig.update_tag()


def aim_at(rig, target):
    """Make the card face `target` (any object): the rig's Track To target."""
    aim_constraint(rig).target = target
    rig.update_tag()


def light_rig_focus(scene):
    """The Focus of a Lighting Rig in the scene, or None."""
    for ob in scene.objects:
        if ob.get(light_rig_spec.ROOT_TAG) is not None:
            return pointer(ob, "tpl2_focus")
    return None


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _RigOperator:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_rig(context) is not None


class BOUNCECARD_OT_preset(_RigOperator, bpy.types.Operator):
    """Set the card's colour, strength, softness, curve and mode to a preset"""
    bl_idname = "bounce_cards.preset"
    bl_label = "Bounce Card Preset"

    preset: EnumProperty(items=spec.preset_items())

    def execute(self, context):
        apply_preset(find_rig(context), self.preset)
        return {'FINISHED'}


class BOUNCECARD_OT_aim_light_rig(_RigOperator, bpy.types.Operator):
    """Aim the card at the Focus of the Lighting Rig in this scene"""
    bl_idname = "bounce_cards.aim_light_rig"
    bl_label = "Aim at Light Rig Focus"

    def execute(self, context):
        focus = light_rig_focus(context.scene)
        if focus is None:
            self.report({'WARNING'}, "No Lighting Rig in this scene")
            return {'CANCELLED'}
        aim_at(find_rig(context), focus)
        return {'FINISHED'}


class BOUNCECARD_OT_aim_selected(_RigOperator, bpy.types.Operator):
    """Aim the card at the other selected object (select it, then the card part last)"""
    bl_idname = "bounce_cards.aim_selected"
    bl_label = "Aim at Selected"

    def execute(self, context):
        rig = find_rig(context)
        parts = {part(rig, p) for p in ("rig",) + spec.PARTS}
        others = [o for o in context.selected_objects if o not in parts]
        if not others:
            self.report({'WARNING'}, "Select the object to aim at too (Ctrl+click it first)")
            return {'CANCELLED'}
        aim_at(rig, others[0])
        return {'FINISHED'}


class BOUNCECARD_OT_select_part(_RigOperator, bpy.types.Operator):
    """Select this part of the bounce card"""
    bl_idname = "bounce_cards.select_part"
    bl_label = "Select Bounce Card Part"

    part: EnumProperty(items=[(p.upper(), p.title(), "") for p in ("rig",) + spec.PARTS])

    def execute(self, context):
        if not select_only(context, part(find_rig(context), self.part.lower())):
            self.report({'WARNING'}, "Rig part is missing or hidden")
            return {'CANCELLED'}
        return {'FINISHED'}


def deploy(context, view, path, preset="White Card", aim_light_rig=True):
    """Append the Bounce Card from `path` as real objects: BC_Focus on what the view centre points at
    (first ray hit, else a close point ahead; on the ground itself, lifted 1 m), the card to the
    viewer's right and a little closer, aimed at the Lighting Rig's Focus when there is one
    (and aim_light_rig), else at BC_Focus. Returns the rig."""
    target, depsgraph = placement.view_target(context, view)
    floor_z = placement.floor_below(context.scene, depsgraph, target)
    subject = placement.subject_point(target, floor_z, spec.FOCUS_HEIGHT)
    _, rig = rig_common.append_rig(context, path, spec.ASSET_NAME, spec.ROOT_TAG)
    focus = part(rig, "focus")
    focus.location = subject
    rig.location = placement.card_placement(view, subject, spec.DEPLOY_SIDE, spec.DEPLOY_TOWARD)
    light_focus = light_rig_focus(context.scene) if aim_light_rig else None
    aim_at(rig, light_focus or focus)
    apply_preset(rig, preset)
    context.view_layer.update()
    select_only(context, rig)
    return rig


class BOUNCECARD_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a Bounce Card as real, editable objects next to what you click (Enter: the screen centre), aimed
    at it (or at the Lighting Rig's Focus)"""
    bl_idname = "bounce_cards.deploy"
    bl_label = "Deploy Bounce Card"
    bl_options = {'REGISTER', 'UNDO'}
    library_name = spec.LIBRARY_FILE

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        deploy(context, view, path, wm.setups_bounce_preset, wm.setups_bounce_aim_light)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def draw_section(body, context):
    """The Bounce Cards deploy section (shown inside the Lighting Rig card): status and Deploy options; the card's
    own controls (preset, aim, parts) are in the Selected card."""
    placement.draw_scene_status(body, context.scene, spec.ROOT_TAG, "bounce card", 'LIGHT_AREA',
                                selected=find_rig(context) is not None)
    wm = context.window_manager
    placement.draw_deploy(body, "setups_bounce_cards_options", BOUNCECARD_OT_deploy.bl_idname, 0,
                          lambda sec: prop_group(sec, wm, [("setups_bounce_preset", "Start With"),
                                                           ("setups_bounce_aim_light", "Aim at Light Rig")]),
                          existing=len(placement.rig_roots(context.scene.objects, spec.ROOT_TAG)),
                          summary=enum_label(wm, "setups_bounce_preset"))


def draw_selected(body, context):
    """The Selected card's part: type, controls, aim and parts of the bounce card the selected object belongs to."""
    rig = find_rig(context)
    current = placement.matching_preset(rig, spec.PRESETS, spec.stored)
    status(body, f"Bounce card · {current or 'custom'}", icon='LIGHT_AREA')
    kinds = section(body, "setups_bounce_cards_kind", "Card Type", icon='PRESET', right=current or "custom")
    if kinds:
        grid = kinds.grid_flow(columns=2, align=True)
        for name in spec.PRESETS:
            grid.operator(BOUNCECARD_OT_preset.bl_idname, text=name, depress=name == current).preset = name
    ctl = section(body, "setups_bounce_cards_controls", "Card", icon='MESH_PLANE')
    if ctl:
        prop_group(ctl, rig, [(f'["{name}"]', name) for name in spec.PROP_NAMES])
    aim = section(body, "setups_bounce_cards_aim", "Aim", icon='PIVOT_CURSOR')
    if aim:
        row = aim.row(align=True)
        row.operator(BOUNCECARD_OT_aim_light_rig.bl_idname, icon='LIGHT_AREA')
        row.operator(BOUNCECARD_OT_aim_selected.bl_idname, icon='RESTRICT_SELECT_OFF')
    sub_heading(body, "Select Part")
    row = body.row(align=True)
    for name in ("rig",) + spec.PARTS:
        row.operator(BOUNCECARD_OT_select_part.bl_idname, text=name.title(),
                     depress=rig_common.is_active_part(context, spec.PART_TAG, name, spec.ROOT_TAG, "rig")).part = name.upper()


def selected_title(context):
    return rig_common.part_title("Bounce Card", context.active_object, spec.PART_TAG)


selected_ui.add("Bounce Card", lambda context: find_rig(context) is not None, selected_title, draw_selected)


classes = (
    BOUNCECARD_OT_preset,
    BOUNCECARD_OT_aim_light_rig,
    BOUNCECARD_OT_aim_selected,
    BOUNCECARD_OT_select_part,
    BOUNCECARD_OT_deploy,
)


def register():
    wm = bpy.types.WindowManager
    wm.setups_bounce_preset = EnumProperty(
        name="Start With", items=spec.preset_items(), default="White Card",
        description="The kind of card the new rig starts as (you can change it any time)")
    wm.setups_bounce_aim_light = BoolProperty(
        name="Aim at Light Rig", default=True,
        description="Aim the card at the Lighting Rig's Focus when the scene has one; "
                    "otherwise at the spot you were looking at")
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.setups_bounce_preset
    del bpy.types.WindowManager.setups_bounce_aim_light
