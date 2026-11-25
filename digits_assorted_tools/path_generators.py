# SPDX-License-Identifier: GPL-3.0-or-later
"""Path Generators (Digit's Tools > Object, and the 3D View Add > Curve / Mesh menus): adds a Spiral Curve, Knot Curve
or Maze object at the 3D cursor, carrying its Geometry Nodes generator modifier (the table is path_generators_spec.py,
the node groups are in this extension's assets/ folder). The card's Add buttons are the same operator; for a selected
generator object it shows the modifier's main inputs (shared toony_ui.draw_modifier)."""
import re

import bpy
from bpy.props import EnumProperty

from . import path_generators_spec as spec, toony_ui
from .character_rig import SELECT_HELPER
from .modifier_setup import append_group, empty_curve_data, library_file  # generated copy
from .rig_common import select_only
from .ui_cards import action_row, friendly_name, hints, status, sub_heading  # generated copy

CARD_ID = "digitools_path_generators"
COPY_SUFFIX = re.compile(r"\.\d+$")   # "Maze.001" after appending a second copy
STACK_HINTS = {'CURVE': "Stretch To Curve, Traveling Bulge or Stretchy Limb can follow it; Apply makes a normal curve",
               'MESH': "Points and edges only: stack Screw (angle 0: raises the walls) or Geometry Nodes after it. Skin "
                       "needs it applied first"}


def generator_modifier(ob):
    """The path generator modifier on `ob` (first one), else None."""
    for mod in getattr(ob, "modifiers", ()):
        if mod.type == 'NODES' and mod.node_group and COPY_SUFFIX.sub("", mod.node_group.name) in spec.BY_GROUP:
            return mod
    return None


def new_data(generator):
    """Empty object data for the generator's object type (the modifier makes all of the geometry)."""
    return empty_curve_data(generator.label) if generator.object_type == 'CURVE' else bpy.data.meshes.new(generator.label)


def add_generator(context, key):
    """A new object of the generator `key` at the 3D cursor in the active collection, its modifier on it, selected and
    active. Returns the object, or None when the node group's asset file is missing."""
    generator = spec.BY_KEY[key]
    group = append_group(generator.group, library_file(generator.asset_file))
    if group is None:
        return None
    ob = bpy.data.objects.new(generator.label, new_data(generator))
    context.collection.objects.link(ob)
    ob.location = context.scene.cursor.location
    ob.modifiers.new(generator.group, 'NODES').node_group = group
    select_only(context, ob)
    return ob


class DIGITOOLS_OT_add_path_generator(bpy.types.Operator):
    """Add a path generator object at the 3D cursor: a Geometry Nodes modifier makes its curve or mesh, so its inputs
    stay editable (Apply it for normal geometry)"""
    bl_idname = "digits_assorted_tools.add_path_generator"
    bl_label = "Add Path Generator"
    bl_options = {'REGISTER', 'UNDO'}

    generator: EnumProperty(name="Generator", items=spec.enum_items(), description="Which path to add")

    @classmethod
    def description(cls, context, properties):
        return spec.BY_KEY[properties.generator].description

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        if add_generator(context, self.generator) is None:
            self.report({'ERROR'}, f"{spec.BY_KEY[self.generator].asset_file} not found: reinstall Digit's Assorted Tools")
            return {'CANCELLED'}
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    status(body, "Adds a path at the 3D cursor", icon='CURVE_DATA')
    column = action_row(body).column(align=True)
    for generator in spec.GENERATORS:
        column.operator(DIGITOOLS_OT_add_path_generator.bl_idname, text=generator.label,
                        icon=generator.icon).generator = generator.key
    ob = context.active_object
    mod = generator_modifier(ob)
    if mod is not None:
        sub_heading(body, friendly_name(ob.name), icon='OBJECT_DATA')
        toony_ui.draw_modifier(body, context, ob, mod, 0, CARD_ID, SELECT_HELPER)
    hints(body, [STACK_HINTS[ob.type] if mod is not None else "Select a path to edit its main settings here",
                 "" if context.mode == 'OBJECT' else "Switch to Object Mode"], context)


classes = (DIGITOOLS_OT_add_path_generator,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
