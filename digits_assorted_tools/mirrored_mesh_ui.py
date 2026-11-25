# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Mirrored Mesh (Digit's Tools > Object): operator and card. Geometry: mirrored_mesh.py, planning and redo:
mirrored_mesh_add.py, options: mirrored_mesh_options.py.

Object Mode: a new object at the 3D cursor with the half and a Mirror modifier on the axes chosen on the card.
Edit Mode: the half goes into the active mesh at the cursor snapped onto the planes of its own Mirror modifiers.
The card holds the options (scene settings); the operator starts from them and writes its values back."""
import bpy
from bpy.props import PointerProperty

from . import mirrored_mesh as mm
from . import mirrored_mesh_add as add
from .mirror_pivot import AXIS_LETTERS
from .mirrored_mesh_options import MirroredMeshCard, OptionsMixin, copy_options, syncing
from .ui_cards import action_row, hints, status, wrapped  # generated copy


class DIGITOOLS_OT_add_mirrored_mesh(bpy.types.Operator, OptionsMixin):
    """Add a primitive as only the half that a Mirror modifier turns back into the whole"""
    bl_idname = add.OPERATOR_ID
    bl_label = "Add Mirrored Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
            return True
        if context.mode != 'EDIT_MESH':
            return False
        if not mm.mirror_claims(context.edit_object):
            cls.poll_message_set("Add a Mirror modifier first")
            return False
        return True

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "primitive")
        if context.mode == 'OBJECT':
            layout.prop(self, "axes", toggle=True)
        layout.prop(self, "orientation")
        for name in mm.SETTING_NAMES[self.primitive]:
            layout.prop(self, name)

    def execute(self, context):
        copy_options(context.scene.mirrored_mesh_card, self, only_unset=True)   # the card's values fill what was not given
        plan, why = add.plan_add(context, self)
        if plan is None:
            self.report({'ERROR'}, why)
            return {'CANCELLED'}
        add.add_half(context, plan, self.primitive)
        with syncing():   # the card follows what was added (and what the Adjust Last Operation panel changed)
            copy_options(self, context.scene.mirrored_mesh_card)
        return {'FINISHED'}


def draw_axes(layout, card, context):
    """Object Mode: the axis toggles; Edit Mode: the modifier's axes, read only."""
    if context.mode == 'EDIT_MESH':
        axes = mm.claimed_axes(mm.mirror_claims(context.edit_object))
        status(layout, "Mirror axes: " + (" ".join(AXIS_LETTERS[axis] for axis in axes) or "none"), icon='MOD_MIRROR')
        return
    row = layout.row(align=True)
    for axis, letter in enumerate(AXIS_LETTERS):
        row.prop(card, "axes", index=axis, text=letter, toggle=True)


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    card = context.scene.mirrored_mesh_card
    draw_axes(body, card, context)
    body.prop(card, "primitive", text="")
    plan, why = add.plan_add(context, card)
    if card.primitive in mm.SETTING_NAMES:
        for name in mm.SETTING_NAMES[card.primitive]:
            body.prop(card, name)
    body.prop(card, "orientation")
    if plan is None and why:
        alert = body.column()
        alert.alert = True
        wrapped(alert, why, icon='ERROR', context=context)
    row = action_row(body)
    row.enabled = plan is not None
    edit_mode = context.mode == 'EDIT_MESH'
    row.operator(DIGITOOLS_OT_add_mirrored_mesh.bl_idname, text="Add to Mesh" if edit_mode else "Add Mirrored Object",
                 icon='ADD')
    hints(body, ["Adds only the half that the Mirror modifier turns back into the whole",
                 "Changing an option right after an add redoes that add"], context)


classes = (MirroredMeshCard, DIGITOOLS_OT_add_mirrored_mesh)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mirrored_mesh_card = PointerProperty(type=MirroredMeshCard)


def unregister():
    del bpy.types.Scene.mirrored_mesh_card
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
