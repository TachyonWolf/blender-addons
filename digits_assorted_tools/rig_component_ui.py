# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Rig Component card (Digit's Tools > Character Rigs): ONE rig part on its own, as its own armature or into a
rig you pick, on the right bone by name (you can pick another bone).

The card: the Part (which component and its few settings), Where (Rig: empty = a new armature; Bone; Mesh: the guides
go on it and it gets the weights), then three steps like the Full Character Rig's: Add Guides, Build, Weights (done
ones get a rebuild button, red when a setting changed since the build), and Remove for this part only.
All logic is in rig_component (generated copy of Addons/shared_addon/rig_component.py); the card reads its record
(a custom property) and nothing else on redraw, so it costs nothing while you work.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty

from . import body_rig as br, rig_component as rc  # generated copies
from .full_rig_ui import ensure_object_mode, make_active
from .ui_cards import action_row, friendly_name, hints, progress, prop_group, section, status, step_row  # generated copy

STEP_ITEMS = tuple((s, t, tip) for s, t, tip in zip(rc.STEP_IDS, rc.STEP_TITLES, rc.STEP_TIPS))


def setting_property(setting):
    """The Blender property of one component setting (rig_component.SETTINGS)."""
    if setting.kind == 'bool':
        return BoolProperty(name=setting.label, description=setting.tip, default=setting.default)
    if setting.kind == 'int':
        return IntProperty(name=setting.label, description=setting.tip, default=setting.default,
                           min=setting.limits[0], max=setting.limits[1])
    return EnumProperty(name=setting.label, description=setting.tip, items=setting.choices, default=setting.default)


def is_rig(_self, ob):
    """A rig to add to: an armature that isn't a guide object."""
    return ob.type == 'ARMATURE' and not br.is_guides(ob) and not ob.get(rc.GUIDE_OF) and ob.get(br.TAG) is None \
        and not ob.get('face_rig_kind')


class DIGITOOLS_PG_rig_component(bpy.types.PropertyGroup):
    __annotations__ = dict(
        {s.id: setting_property(s) for s in rc.SETTINGS.values()},
        component=EnumProperty(name="Part", description="The rig part to add",
                               items=[(c.id, c.label, c.tip) for c in rc.COMPONENTS], default='tail'),
        rig=PointerProperty(name="Rig", type=bpy.types.Object, poll=is_rig,
                            description="The rig to add the part to. Empty: a new armature of its own"),
        parent_bone=bpy.props.StringProperty(name="Bone", description="The bone the part hangs on. Empty: the usual "
                                             "bone, found by its name (Pelvis, Chest or Head)"),
        mesh=PointerProperty(name="Mesh", type=bpy.types.Object, poll=lambda self, ob: ob.type == 'MESH',
                             description="The part's mesh: the guides go on it and it gets the weights. Empty: the "
                                         "guides start at the usual place"),
        guides=PointerProperty(name="Guides", type=bpy.types.Object, options={'HIDDEN'},
                               description="The guide bones of the part you are adding"))

    def settings(self):
        """{setting id: value} of the chosen component."""
        return {i: getattr(self, i) for i in rc.BY_ID[self.component].settings}

    def own_guides(self):
        """The guides when they belong to the chosen component (and rig), else None."""
        ob = self.guides
        if ob is None or ob.name not in bpy.data.objects or ob.get(rc.GUIDE_OF) != self.component:
            return None
        return ob if ob.get(rc.GUIDE_RIG, '') in ('', self.rig.name if self.rig else '') else None


def card_settings(context):
    return context.scene.digit_rig_component


def blocker(s, step):
    """Why a step can't run now ('' = it can)."""
    comp = rc.BY_ID[s.component]
    if comp.kind == 'face' and s.rig is None:
        return "The Face needs a rig with a Head bone: pick the Rig"
    if s.rig is not None and rc.clash(s.rig, s.component, comp):
        return rc.clash(s.rig, s.component, comp)
    built = rc.entry(s.rig, s.component) if s.rig is not None else None
    if step == 'build' and s.own_guides() is None and not built:
        return "Add Guides first"
    if step == 'weights':
        if not built:
            return "Build first"
        if s.mesh is None and not built.get('mesh'):
            return "Pick the Mesh to weigh"
    return ""


class DIGITOOLS_OT_rig_component_step(bpy.types.Operator):
    """Run this step for the chosen part (again, when the step is done)"""
    bl_idname = "digits_assorted_tools.rig_component_step"
    bl_label = "Add Rig Component Step"
    bl_options = {'REGISTER', 'UNDO'}

    step: EnumProperty(name="Step", items=STEP_ITEMS)
    redo: BoolProperty(name="Again", default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        tip = rc.STEP_TIPS[rc.STEP_IDS.index(properties.step)]
        return tip + (". Does this step again" if properties.redo else "")

    @classmethod
    def poll(cls, context):
        return getattr(context.scene, 'digit_rig_component', None) is not None

    def invoke(self, context, event):
        if self.redo and self.step == 'guides':          # the guides go back where they start
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        s = card_settings(context)
        why = blocker(s, self.step)
        if why:
            self.report({'ERROR'}, why)
            return {'CANCELLED'}
        ensure_object_mode(context)
        try:
            lines, active = self.run(s)
        except (ValueError, KeyError) as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        if active is not None:
            make_active(context, active)
        for line in lines:
            self.report({'INFO'}, line)
        return {'FINISHED'}

    def run(self, s):
        """(log lines, the object to make active)."""
        if self.step == 'guides':
            rc.remove_guides(s.own_guides())
            s.guides, lines = rc.add_guides(s.component, s.rig, s.mesh, s.settings())
            return lines, s.guides
        if self.step == 'build':
            s.rig, lines = rc.build(s.component, s.rig, s.own_guides(), s.settings(), s.parent_bone)
            return lines, s.rig
        mesh = s.mesh or bpy.data.objects.get(rc.entry(s.rig, s.component).get('mesh', ''))
        return rc.weigh(s.component, s.rig, mesh), s.rig


class DIGITOOLS_OT_rig_component_remove(bpy.types.Operator):
    """Take this part off the rig: only its bones, weights and guides go; the rest of the rig stays as it is"""
    bl_idname = "digits_assorted_tools.rig_component_remove"
    bl_label = "Remove Part"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = getattr(context.scene, 'digit_rig_component', None)
        return s is not None and ((s.rig is not None and rc.entry(s.rig, s.component) is not None)
                                  or s.own_guides() is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        s = card_settings(context)
        ensure_object_mode(context)
        if s.rig is not None and rc.entry(s.rig, s.component) is not None:
            s.rig, lines = rc.remove(s.component, s.rig)
        else:
            lines = ['guides removed']
        rc.remove_guides(s.own_guides())
        s.guides = None
        for line in lines:
            self.report({'INFO'}, line)
        return {'FINISHED'}


# ---------------------------------------------------------------- drawing
def draw_part(layout, s):
    comp = rc.BY_ID[s.component]
    box = section(layout, "digitools_rig_component_part", "Part", icon='BONE_DATA', right=comp.label)
    if box:
        box.prop(s, "component", text="")
        if comp.settings:
            prop_group(box, s, list(comp.settings))


def usual_bone(s):
    comp = rc.BY_ID[s.component]
    found = rc.parent_of(s.rig, s.component) if s.rig is not None else None
    return found or comp.parent


def draw_where(layout, s, context):
    right = friendly_name(s.rig.name) if s.rig is not None else "new rig"
    box = section(layout, "digitools_rig_component_where", "Where", icon='ARMATURE_DATA', right=right)
    if not box:
        return
    col = box.column(align=True)
    col.use_property_split, col.use_property_decorate = True, False
    col.prop(s, "rig")
    if s.rig is not None:
        col.prop_search(s, "parent_bone", s.rig.data, "bones")
    col.prop(s, "mesh")
    notes = []
    if s.rig is None:
        notes.append(f"Empty Rig: a new armature, {rc.BY_ID[s.component].label} Rig")
    elif not s.parent_bone:
        notes.append(f"Empty Bone: {usual_bone(s)}")
    if s.mesh is None:
        notes.append("Empty Mesh: the guides start at the usual place")
    hints(box, notes, context)


def draw_steps(layout, context, s):
    comp = rc.BY_ID[s.component]
    guides = s.own_guides()
    states = rc.step_states(s.component, guides, s.rig, s.settings())
    active = [st for st in states if st[1] != 'off']
    done = sum(1 for st in active if st[1] == 'done')
    box = section(layout, "digitools_rig_component_steps", "Steps", icon='TIME',
                  right="done" if done == len(active) else f"{done} of {len(active)}")
    if not box:
        return
    progress(box, done, len(active))
    idname = DIGITOOLS_OT_rig_component_step.bl_idname
    stale = False
    for number, (step, state, is_stale) in enumerate(states, 1):
        title = rc.STEP_TITLES[rc.STEP_IDS.index(step)]
        if state == 'off':
            row = box.row()
            row.active = False
            row.label(text=f"{number}  {title}")
            continue
        op = step_row(box, number, title, state, idname, idname if state == 'done' else None, is_stale,
                      rebuild_props=dict(step=step, redo=True), step=step)
        op.redo = state == 'done'
        stale = stale or is_stale
    notes = []
    if stale:
        notes.append("A setting changed since the build: rebuild to use it")
    nxt = next((st for st in states if st[1] == 'next'), None)
    if nxt:
        notes.append(rc.STEP_TIPS[rc.STEP_IDS.index(nxt[0])])
    if not comp.weights:
        notes.append("The Face takes its weights from the Head's weights on the mesh, when it is built")
    hints(box, notes, context)
    built = s.rig is not None and rc.entry(s.rig, s.component) is not None
    if built or guides is not None:
        action_row(box, scale=1.0).operator(DIGITOOLS_OT_rig_component_remove.bl_idname, icon='TRASH')


def draw_card(layout, context):
    s = getattr(context.scene, 'digit_rig_component', None)
    if s is None:
        return
    comp = rc.BY_ID[s.component]
    why = blocker(s, 'guides')
    built = s.rig is not None and rc.entry(s.rig, s.component) is not None
    if why:
        status(layout, why, icon='ERROR')
    elif built:
        status(layout, f"{comp.label} · on {friendly_name(s.rig.name)}", icon='CHECKMARK')
    else:
        status(layout, f"{comp.label} · not added yet", icon='BONE_DATA')
    draw_part(layout, s)
    draw_where(layout, s, context)
    draw_steps(layout, context, s)


classes = (DIGITOOLS_PG_rig_component, DIGITOOLS_OT_rig_component_step, DIGITOOLS_OT_rig_component_remove)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.digit_rig_component = PointerProperty(type=DIGITOOLS_PG_rig_component)


def unregister():
    del bpy.types.Scene.digit_rig_component
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
