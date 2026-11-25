# SPDX-License-Identifier: GPL-3.0-or-later
"""Fast Viewport card (Digit's Tools > Scene): one toggle that turns the heavy modifiers (Subdivision, Multires,
Geometry Nodes, Line Art) of a whole character off IN THE VIEWPORT ONLY (show_viewport; renders are never touched).
The modifiers it turned off are recorded on the scene, so turning back on restores exactly those and leaves the ones
you had off alone (the Oops Debugger and Pre-Render Check read that record, so they don't call these a mistake).
The count of heavy modifiers is cached (selection change or Rescan); nothing runs in the background."""
import bpy
from bpy.props import BoolProperty

from . import oops_ui, scene_checks as sc, viewport_modifiers  # sc, viewport_modifiers: generated copies
from .bone_chain import rig_for_chain  # generated copy
from .ui_cards import action_row, hints, prop_group, section  # generated copy

RECORD_KEY = sc.FAST_VIEWPORT_KEY  # scene custom property, format in viewport_modifiers.py
# (modifier type, label, scene option): one line per kind of heavy modifier
KINDS = (('SUBSURF', "Subdivision", "fast_viewport_subsurf"),
         ('MULTIRES', "Multires", "fast_viewport_multires"),
         ('NODES', "Geometry Nodes", "fast_viewport_nodes"),
         ('LINEART', "Line Art", "fast_viewport_lineart"))


# ---------------------------------------------------------------------------
# Finding the character and its heavy modifiers
# ---------------------------------------------------------------------------

def main_rig(context):
    """The top armature of the active object's rig (part armatures hang under it), or None."""
    rig = rig_for_chain(context)
    while rig and rig.parent and rig.parent.type == 'ARMATURE':
        rig = rig.parent
    return rig


def character_objects(context, rig):
    """The rig, everything parented under it (part armatures and their meshes) and every object an armature of the
    character deforms."""
    armatures = [rig] + [ob for ob in rig.children_recursive if ob.type == 'ARMATURE']
    found = {ob.name_full: ob for ob in [rig] + rig.children_recursive}
    for ob in context.scene.objects:
        if any(m.type == 'ARMATURE' and m.object in armatures for m in ob.modifiers):
            found[ob.name_full] = ob
    return list(found.values())


def heavy_modifiers(objects, types):
    """[(object, modifier)] of the given modifier types that are on in the viewport."""
    return [(ob, mod) for ob in objects for mod in ob.modifiers if mod.type in types and mod.show_viewport]


def chosen_types(scene):
    return {kind for kind, _label, option in KINDS if getattr(scene, option)}


# ---------------------------------------------------------------------------
# Turning off and back on
# ---------------------------------------------------------------------------

def recorded(scene):
    """[[object full name, modifier name, uid], ...] this tool turned off."""
    return viewport_modifiers.recorded(scene, RECORD_KEY)


def turn_off(scene, objects, types):
    """Turn the heavy viewport modifiers off and record them. Returns (turned off, skipped as not editable)."""
    return viewport_modifiers.turn_off(scene, RECORD_KEY, heavy_modifiers(objects, types))


def turn_on(scene):
    """Turn back on the modifiers turned off by turn_off. Returns how many were restored."""
    return viewport_modifiers.restore(scene, RECORD_KEY)


# ---------------------------------------------------------------------------
# Operator and card
# ---------------------------------------------------------------------------

class DIGITOOLS_OT_fast_viewport(bpy.types.Operator):
    """Turn the character's heavy modifiers off in the viewport (renders are not touched), or back on"""
    bl_idname = "digits_assorted_tools.fast_viewport"
    bl_label = "Fast Viewport"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if recorded(context.scene) or main_rig(context):
            return True
        cls.poll_message_set("Select a character's armature or mesh")
        return False

    def execute(self, context):
        scene = context.scene
        sc.CACHE.clear()
        if recorded(scene):
            self.report({'INFO'}, f"Viewport modifiers back on: {turn_on(scene)}")
            return {'FINISHED'}
        off, skipped = turn_off(scene, character_objects(context, main_rig(context)), chosen_types(scene))
        self.report({'INFO'}, f"Viewport modifiers turned off: {off}" + (f" ({skipped} linked, skipped)" if skipped else ""))
        return {'FINISHED'}


def heavy_count(context, rig):
    """How many heavy modifiers are on, cached until the selection or the chosen kinds change, or Rescan."""
    types = chosen_types(context.scene)
    key = ("fast_viewport", tuple(sorted(types))) + sc.context_key(context)
    return sc.CACHE.get(key, lambda: len(heavy_modifiers(character_objects(context, rig), types)))


def draw_card(layout, context):
    scene = context.scene
    off = len(recorded(scene))
    rig = main_rig(context)
    head = layout.row(align=True)
    if off:
        head.label(text=f"Fast: {off} modifiers off", icon='CHECKMARK')
    elif rig:
        head.label(text=f"Normal: {heavy_count(context, rig)} heavy modifiers on", icon='MOD_TIME')
    else:
        head.label(text="Select a character")
    head.operator(oops_ui.OOPS_OT_rescan.bl_idname, text="", icon='FILE_REFRESH')
    action_row(layout).operator(DIGITOOLS_OT_fast_viewport.bl_idname, text="Turn Back On" if off else "Turn Heavy Ones Off",
                                icon='LOOP_BACK' if off else 'MOD_TIME')
    hints(layout, ["Only the viewport changes: renders keep every modifier"], context)
    body = section(layout, "fastviewport_kinds", "Kinds", default_closed=True,
                   right=f"{len(chosen_types(scene))} of {len(KINDS)} on")
    if body:
        prop_group(body, scene, [(option, label) for _kind, label, option in KINDS]).enabled = not off


classes = (DIGITOOLS_OT_fast_viewport,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for _kind, label, option in KINDS:
        setattr(bpy.types.Scene, option, BoolProperty(
            name=label, default=True, description=f"Fast Viewport turns {label} modifiers off in the viewport"))


def unregister():
    for _kind, _label, option in KINDS:
        delattr(bpy.types.Scene, option)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
