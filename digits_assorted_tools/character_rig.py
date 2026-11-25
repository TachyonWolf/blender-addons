"""Character Rig: the Selected card box of a character (Digit...): the rig panel (Show Bones, part pages with the
switches, IK | FK that snap, resets; shared rig_switches_ui.py) and the Toony modifiers on its meshes (shared toony_ui.py), for a selected
rig, part armature (Wings, Ears) or mesh of it. Tweaking only; building (Limbs, Face Rig...) stays in the tool cards.
Move Alone (move_alone.py) shows for an active control that other bones follow, on any armature (also one without
switches: then the box holds only that row).

Cheap poll: the rig comes from the active object by parent / modifier lookups; its switch bones and its meshes are
cached (rig_switches_ui.switch_names, `rig_meshes` here), so a redraw never scans all bones or the scene again."""
import bpy

from . import look_at, move_alone, rig_switches_ui as switches, selected_ui, toony_ui  # rig_switches_ui, toony_ui: generated copies
from .rig_parts import shown_armatures  # generated copy
from .ui_cards import friendly_name, sub_heading

SELECTED_ID = "chartools_character_rig"
SELECT_HELPER = toony_ui.select_helper_id(__package__)


def posable_parts(rig):
    """The rig's part armatures (any depth) you can pose now: in the view layer (collection not excluded:
    rig_parts.shown_armatures) and visible (not hidden, collection not hidden)."""
    return [ob for ob in shown_armatures(rig)[1:] if ob.visible_get()]


class CHARTOOLS_OT_select_rig(bpy.types.Operator):
    """Select the character's armature and its part armatures that are on (tails, ears, hair), all in Pose Mode, the
    main armature active (unhidden if it was hidden in the viewport)"""
    bl_idname = "chartools.select_rig"
    bl_label = "Select Rig"
    bl_options = {'REGISTER', 'UNDO'}

    rig: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig)
        if rig is None or rig.name not in context.view_layer.objects:
            self.report({'WARNING'}, f"Rig {self.rig!r} is not in this view layer")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        rig.hide_viewport = False
        rig.hide_set(False)
        for ob in context.selected_objects:
            ob.select_set(False)
        parts = posable_parts(rig)
        for ob in [rig] + parts:
            ob.select_set(True)
        context.view_layer.objects.active = rig
        if not rig.visible_get():
            self.report({'WARNING'}, f"{rig.name} selected, but its collection is hidden")
            return {'FINISHED'}
        if rig.mode != 'OBJECT':     # still in Pose Mode from before: mode_set would keep its parts out
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='POSE')
        self.report({'INFO'}, f"{rig.name} and {len(parts)} part{'' if len(parts) == 1 else 's'} in Pose Mode")
        return {'FINISHED'}


classes = (toony_ui.make_select_helper(__package__), CHARTOOLS_OT_select_rig)

_meshes = {}      # rig name -> (object count, [mesh names])
mesh_scans = 0    # how many scene scans happened (tests: a redraw must not add to it)


def is_under(ob, rig):
    """True when `ob` is the rig or hangs under it at any depth (part armatures)."""
    while ob is not None:
        if ob == rig:
            return True
        ob = ob.parent
    return False


def belongs_to_rig(ob, rig):
    """True when the mesh is deformed by the rig or one of its part armatures, or parented under it."""
    return any(m.type == 'ARMATURE' and m.object and is_under(m.object, rig) for m in ob.modifiers) or is_under(ob.parent, rig)


def rig_meshes(rig):
    """The meshes deformed by or parented to the rig (cached per rig; scanned again when the object count changes)."""
    global mesh_scans
    count = len(bpy.data.objects)
    cached = _meshes.get(rig.name)
    if cached and cached[0] == count:
        names = cached[1]
    else:
        mesh_scans += 1
        names = [ob.name for ob in bpy.data.objects if ob.type == 'MESH' and belongs_to_rig(ob, rig)]
        _meshes[rig.name] = (count, names)
    return [bpy.data.objects[name] for name in names if name in bpy.data.objects]


def toony_meshes(rig):
    """[(mesh, [Toony modifiers])] for the rig's meshes that have any."""
    found = [(ob, toony_ui.toony_modifiers(ob)) for ob in rig_meshes(rig)]
    return [(ob, mods) for ob, mods in found if mods]


def subject_rig(context):
    return switches.character_rig(selected_ui.subject(context))


def poll(context):
    return subject_rig(context) is not None or move_alone.active_control(context) is not None


def title(context):
    rig = subject_rig(context)
    if rig is None:
        return f"{friendly_name(context.active_object.name)} · Rig"
    return f"{friendly_name(rig.name)} · Rig", switches.rig_summary(rig)


def draw_select_rig(row, rig):
    """Select Rig, small at the right of the panel's top heading."""
    right = row.row()
    right.alignment = 'RIGHT'
    right.operator(CHARTOOLS_OT_select_rig.bl_idname, icon='RESTRICT_SELECT_OFF').rig = rig.name


def draw(box, context):
    rig = subject_rig(context)
    if rig is None:
        move_alone.draw_toggle(box, context)
        return
    switches.draw_rig_panel(box, rig, SELECTED_ID, context, extra=lambda row: draw_select_rig(row, rig))
    move_alone.draw_toggle(box, context)
    if look_at.eye_bone_names(rig) and context.active_object == rig:
        sub_heading(box, "Look At", icon='HIDE_OFF')
        look_at.draw_toggle(box, rig)
        look_at.draw_eye_cross(box, context, rig)
    for ob, mods in toony_meshes(rig):
        sub_heading(box, friendly_name(ob.name), icon='MESH_DATA')
        for index, mod in enumerate(mods):
            toony_ui.draw_modifier(box, context, ob, mod, index, SELECTED_ID, SELECT_HELPER)


selected_ui.add("Character Rig", poll, title, draw)
