# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Posable (Selected card): a character dragged in from the "Digit World" asset library arrives linked (an Empty that
instances a library collection), so it cannot be posed. This box shows only for such a thing, or a linked object that is
not overridden yet, and one click makes it a library override (character_link.make_posable, the same code the inspector
files and Texture Studio > Add Character use): the Empty is replaced, the armature is selected and posable.

Cheap poll: reads a few properties of the one active object, nothing else. No handlers, no timers."""
import bpy

from . import character_link, selected_ui  # character_link: generated copy
from .ui_cards import hints  # generated copy


def locked_subject(context):
    """The active (else first selected) object when it is an override that is still a system override, else None."""
    ob = selected_ui.subject(context)
    return ob if character_link.is_locked_override(ob) else None


def subject(context):
    """The active (else first selected) object when it needs an override, else None."""
    ob = selected_ui.subject(context)
    return ob if character_link.needs_override(ob) else None


class CHARTOOLS_OT_make_posable(bpy.types.Operator):
    """Make the linked item (character, location, prop) a library override, so it can be posed, moved and edited (the instancing Empty is replaced)"""
    bl_idname = "chartools.make_posable"
    bl_label = "Make Adjustable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return subject(context) is not None

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            rig = character_link.make_posable(context, subject(context))
        except (ValueError, RuntimeError) as error:
            self.report({'ERROR'}, f"Make Adjustable: {error}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{rig.name} is now an override: adjustable")
        return {'FINISHED'}


class CHARTOOLS_OT_make_editable(bpy.types.Operator):
    """Make the selected library override editable, so modifiers can be added (it is locked as a system override now)"""
    bl_idname = "chartools.make_editable"
    bl_label = "Make Editable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return locked_subject(context) is not None

    def execute(self, context):
        objects = {*context.selected_objects, locked_subject(context)}
        changed = character_link.make_editable(objects)
        # an override whose parent is still locked can fall back to locked: lift the parents too
        for ob in list(objects):
            parent = ob.parent
            while parent is not None:
                changed += character_link.make_editable([parent])
                parent = parent.parent
        self.report({'INFO'}, f"{changed} override object(s) are now editable")
        return {'FINISHED'}


def title(context):
    return "Linked item"


def draw(box, context):
    hints(box, ["Linked from a library: it can't be posed or edited until it is an override."], context)
    box.operator(CHARTOOLS_OT_make_posable.bl_idname, icon='LIBRARY_DATA_OVERRIDE')


def locked_draw(box, context):
    hints(box, ["Library override, locked: modifiers can't be added until it is editable."], context)
    box.operator(CHARTOOLS_OT_make_editable.bl_idname, icon='LIBRARY_DATA_OVERRIDE')


selected_ui.add("Make Adjustable", lambda context: subject(context) is not None, title, draw)
selected_ui.add("Make Editable", lambda context: locked_subject(context) is not None, lambda context: "Locked override", locked_draw)

classes = (CHARTOOLS_OT_make_posable, CHARTOOLS_OT_make_editable)
