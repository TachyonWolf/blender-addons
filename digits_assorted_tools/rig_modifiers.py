# SPDX-License-Identifier: GPL-3.0-or-later
"""Viewport Modifiers: a Selected card box under the Character Rig box. One toggle for the Subdivision modifiers of every
mesh of the character (`character_rig.rig_meshes`), a quick viewport Levels choice (0 / 1 / 2), and one toggle per other
modifier type found on those meshes. Viewport only (`show_viewport`; renders are never touched). Armature modifiers are
left out: turning them off breaks posing. Nothing runs in the background: the draw loops over the meshes' modifiers
(about 25 meshes, cheap)."""
import bpy

from . import character_rig, selected_ui
from .ui_cards import friendly_name, sub_heading

LEVEL_CHOICES = (0, 1, 2)
MAIN_KIND = 'SUBSURF'
LEFT_OUT = {'ARMATURE'}   # posing needs them
NAMES = {item.identifier: item.name for item in bpy.types.Modifier.bl_rna.properties['type'].enum_items}
STATE_ICONS = {'on': 'CHECKBOX_HLT', 'off': 'CHECKBOX_DEHLT', 'mixed': 'REMOVE'}


def rig_modifiers(rig):
    """[(mesh, modifier)] of the rig's meshes shown in the viewport (meshes in disabled or excluded collections,
    or hidden, are left out), Armature modifiers left out."""
    return [(ob, mod) for ob in character_rig.rig_meshes(rig) if ob.visible_get()
            for mod in ob.modifiers if mod.type not in LEFT_OUT]


def state_of(on, total):
    return 'off' if not on else 'on' if on == total else 'mixed'


def kind_states(rig):
    """{modifier type: (state, on count, total)}, Subdivision first, then A-Z by label."""
    counts = {}
    for _ob, mod in rig_modifiers(rig):
        on, total = counts.get(mod.type, (0, 0))
        counts[mod.type] = (on + bool(mod.show_viewport), total + 1)
    order = sorted(counts, key=lambda kind: (kind != MAIN_KIND, label_of(kind)))
    return {kind: (state_of(*counts[kind]), *counts[kind]) for kind in order}


def label_of(kind):
    return NAMES.get(kind, kind.replace("_", " ").title())


def levels_of(rig):
    """The viewport Levels shared by every Subdivision modifier, or None when they differ (or there are none)."""
    found = {mod.levels for _ob, mod in rig_modifiers(rig) if mod.type == MAIN_KIND}
    return found.pop() if len(found) == 1 else None


def turn(rig, kind, show):
    """Set show_viewport of every `kind` modifier of the rig's meshes (not the linked ones). Returns how many changed."""
    changed = 0
    for ob, mod in rig_modifiers(rig):
        if mod.type == kind and ob.is_editable and mod.show_viewport != show:
            mod.show_viewport = show
            changed += 1
    return changed


def set_levels(rig, levels):
    """Viewport Levels of every Subdivision modifier of the rig's meshes. Returns how many changed."""
    changed = 0
    for ob, mod in rig_modifiers(rig):
        if mod.type == MAIN_KIND and ob.is_editable and mod.levels != levels:
            mod.levels = levels
            changed += 1
    return changed


TOOLTIP_NAMES = 15   # mesh names listed in a toggle's tooltip before "+ N more"


def meshes_list(rig, kind):
    """Tooltip text: the meshes that have this kind of modifier, '(off)' after those where it is off."""
    names = {}
    for ob, mod in rig_modifiers(rig):
        if mod.type == kind:
            names[ob.name] = names.get(ob.name, False) or mod.show_viewport
    shown = [name if on else f"{name} (off)" for name, on in sorted(names.items())]
    extra = len(shown) - TOOLTIP_NAMES
    return ", ".join(shown[:TOOLTIP_NAMES]) + (f" + {extra} more" if extra > 0 else "")


class CHARTOOLS_OT_rig_modifiers(bpy.types.Operator):
    """Turn one kind of modifier off or on in the viewport for every mesh of the character (renders are not touched).
    Helps a slow viewport and slow snapping"""
    bl_idname = "chartools.rig_modifiers"
    bl_label = "Viewport Modifiers"
    bl_options = {'REGISTER', 'UNDO'}

    rig: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    kind: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    levels: bpy.props.IntProperty(default=-1, options={'HIDDEN', 'SKIP_SAVE'})   # >= 0: set Subdivision viewport Levels

    @classmethod
    def description(cls, context, properties):
        if properties.levels >= 0:
            return f"Set the viewport Levels of every Subdivision modifier of the character to {properties.levels}. Viewport only; lower is faster"
        rig = bpy.data.objects.get(properties.rig)
        where = meshes_list(rig, properties.kind) if rig else ""
        return (f"Turn {label_of(properties.kind)} off or on in the viewport for every mesh of the character. "
                "Viewport only (renders are not touched); off helps a slow viewport and slow snapping. Mixed turns all on"
                + (f"\n\nMeshes: {where}" if where else ""))

    def execute(self, context):
        rig = bpy.data.objects.get(self.rig)
        if rig is None:
            return {'CANCELLED'}
        if self.levels >= 0:
            self.report({'INFO'}, f"Subdivision viewport Levels {self.levels}: {set_levels(rig, self.levels)} changed")
            return {'FINISHED'}
        state, _on, _total = kind_states(rig).get(self.kind, ('off', 0, 0))
        show = state != 'on'   # all on: turn off; off or mixed: turn on
        self.report({'INFO'}, f"{label_of(self.kind)} {'on' if show else 'off'} in the viewport: {turn(rig, self.kind, show)} changed")
        return {'FINISHED'}


classes = (CHARTOOLS_OT_rig_modifiers,)


def poll(context):
    return character_rig.subject_rig(context) is not None


def title(context):
    rig = character_rig.subject_rig(context)
    states = kind_states(rig)
    main = states.get(MAIN_KIND)
    summary = f"Subdivision {main[0]}" if main else "no Subdivision"
    return f"{friendly_name(rig.name)} · Viewport Modifiers", summary


def draw_kind(layout, rig, kind, state, on, total, big=False):
    row = layout.row(align=True)
    row.scale_y = 1.4 if big else 1.0
    op = row.operator(CHARTOOLS_OT_rig_modifiers.bl_idname, text=f"{label_of(kind)} · {on} of {total} on",
                      icon=STATE_ICONS[state], depress=state == 'on')
    op.rig, op.kind = rig.name, kind


def draw(box, context):
    rig = character_rig.subject_rig(context)
    states = kind_states(rig)
    if not states:
        box.label(text="No modifiers on the character's meshes", icon='INFO')
        return
    main = states.get(MAIN_KIND)
    if main:
        draw_kind(box, rig, MAIN_KIND, *main, big=True)
        row = box.row(align=True)
        row.label(text="Levels")
        current = levels_of(rig)
        for level in LEVEL_CHOICES:
            op = row.operator(CHARTOOLS_OT_rig_modifiers.bl_idname, text=str(level), depress=current == level)
            op.rig, op.levels = rig.name, level
    others = [(kind, value) for kind, value in states.items() if kind != MAIN_KIND]
    if others:
        sub_heading(box, "Other modifiers", icon='MODIFIER')
        col = box.column(align=True)
        for kind, value in others:
            draw_kind(col, rig, kind, *value)


selected_ui.add("Character Rig Viewport Modifiers", poll, title, draw)
