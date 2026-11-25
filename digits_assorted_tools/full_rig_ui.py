# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig card: one rig for a character mesh, lean by default, every extra a toggle.

The card is a Plan (the few choices that shape the rig, and the Build row: a toggle per part on the base model, each
part's settings under it while it is on), the six numbered Steps (Add Guides ... Weights: the next one is the big
button, done ones get a rebuild button, red when an option changed since the build) and the Body / Face options,
folded with "n of m on". A rig made before this tool (no full-rig record) gets an Existing Rig section
instead: Rebuild Face, Upgrade Limbs and Sort Bone Collections, the per-rig actions of the former Face Rig and Limbs
tools. The rig controls themselves live in the Selected card.

The options, labels and tooltips are all in full_rig_spec (generated copy of Addons/shared_addon/full_rig_spec.py);
the settings (`Object.digit_full_rig`) are generated from that table, so a new option is one line there. They sit on
the character's first mesh until the body is built, then on the rig. With nothing selected the card offers New Rig
Without Mesh: a bare character (guides at the 3D cursor, the settings on the guides) that skips Fit and Weights until
Use This Mesh gives it a mesh. What each step does is in full_rig.run_step; the
card only finds the character, draws the state full_rig.step_states reads from the marks (no scans on redraw) and
runs the operators.
"""

import json
from collections import namedtuple
from itertools import count

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Matrix

from . import bone_collections as bc, body_rig as br, face_rig_core as core, full_rig as F, full_rig_spec as spec  # generated copies
from .face_rig_ui import character
from .rig_parts import rig_armatures  # generated copy
from .ui_cards import (action_row, choice_row, count_on, friendly_name, hints, progress, prop_group, section, status,  # generated copy
                       step_row, sub_heading)

# The Build row: one plain toggle per part on the base model (the body itself is always built). `toggle`: the card
# setting the button flips (Face = face_rig, Ears = ears over the Ears type, the rest the spec's own options); `row`:
# 0 = the head, 1 = the body; `settings`: the options drawn under the row while the part is on (its mesh picker, from
# PART_MESH_PICKERS, under them); `note`: what the part needs, in plain words. The Face's settings are the Face Options.
BuildPart = namedtuple('BuildPart', 'toggle row settings note')
HAIR_NOTE = "Hair: its guide starts behind the head. Drag Base, Mid and Tip onto the hair before Generate Face & Parts"
BUILD_PARTS = (BuildPart('face_rig', 0, (), ''), BuildPart('ears', 0, ('ear_type', 'ear_tweaks'), ''),
               BuildPart('hair', 0, ('hair_tweaks',), HAIR_NOTE), BuildPart('tail', 1, ('tail_tweaks',), ''),
               BuildPart('breasts', 1, ('breast_bones',), ''), BuildPart('butt', 1, (), ''))
WINGS_NOTE = "Wings: add them with the Add Rig Component tool"     # wings are too character-specific for the Full Rig
BUILD_TOGGLES = tuple(p.toggle for p in BUILD_PARTS)
BUILD_ROWS = tuple(tuple(p.toggle for p in BUILD_PARTS if p.row == row) for row in (0, 1))
PART_OPTION_IDS = {i for p in BUILD_PARTS for i in (p.toggle,) + p.settings if i in spec.BY_ID}  # drawn by the Build row
STEP_ITEMS = tuple((s, t, tip) for s, t, tip in zip(F.STEP_IDS, F.STEP_TITLES, F.STEP_TIPS))
GUIDE_NOTE = "The guides are placed: Remove the rig and start again to change these"
PLAN_CHOICES = (('preset', "Preset"), ('face', "Face"), ('leg_type', "Legs"), ('fingers', "Fingers"), ('toes', "Toes"))
# (part kind, setting, label, the Build toggle it belongs under): which mesh a part is on, for a part on a mesh of its own
PART_MESH_PICKERS = (('tail', 'tail_mesh', "Tail Mesh", 'tail'), ('ear', 'ear_mesh', "Ear Mesh", 'ears'),
                     ('hair', 'hair_mesh', "Hair Mesh", 'hair'))
# the option boxes; a box with nothing left once the Build row drew its parts' settings (Parts, today) is not drawn
OPTION_BOXES = (('Body', "Body Options", 'ARMATURE_DATA'), ('Face', "Face Options", 'HIDE_OFF'), ('Parts', "Parts Options", 'BONE_DATA'))
BARE_NAME = "Character"                  # a bare character's name: "Character", "Character 2" ...
BARE_START_NOTE = "No mesh? New Rig Without Mesh places the guides at the 3D cursor, to try the rig tools"
NO_MESH_NOTE = "No mesh: Fit and Weights are skipped. To add one, select it together with the guides or rig"
LATE_MESH_NOTE = "The rig is built: the bones stay where they are. Move the mesh onto the rig, then Weights"


def apply_preset(settings, context=None):
    for id, value in spec.preset(settings.preset).items():
        setattr(settings, id, value)


def apply_face(settings, context=None):
    """A Face choice sets its face defaults (lid pivots, tongue ...) and its Ears type (the one Ears switches on)."""
    for id, value in spec.face_options(settings.face).items():
        setattr(settings, id, value)
    if settings.ears:
        settings.ear_type = spec.face_ears(settings.face)
    else:
        settings.ear_type_last = spec.face_ears(settings.face)


def remember_ear_type(settings, context=None):
    """The last Ears type chosen, for the Ears toggle to switch back on."""
    if settings.ear_type != 'NONE':
        settings.ear_type_last = settings.ear_type


def ears_on(settings):
    return settings.ear_type != 'NONE'


def set_ears(settings, on):
    """Ears off = Ears type None; on = the last type chosen (else the Face's: Short for Snout, Human for Human)."""
    if on != ears_on(settings):
        settings.ear_type = (settings.ear_type_last or spec.face_ears(settings.face)) if on else 'NONE'


UPDATES = {'face': apply_face, 'ear_type': remember_ear_type}


def option_property(o):
    """The Blender property of one option of the spec table."""
    update = UPDATES.get(o.id)
    if o.kind == 'bool':
        return BoolProperty(name=o.label, description=o.tooltip, default=o.default['LEAN'], update=update)
    if o.kind == 'int':
        return IntProperty(name=o.label, description=o.tooltip, default=o.default['LEAN'], min=o.limits[0],
                           max=o.limits[1], update=update)
    return EnumProperty(name=o.label, description=o.tooltip, items=o.choices, default=o.default['LEAN'], update=update)


def part_mesh_property(label):
    """A part's mesh picker: empty = the body (the mesh nearest the part)."""
    return PointerProperty(name=label, type=bpy.types.Object, poll=lambda self, ob: ob.type == 'MESH',
                           description="The mesh this part is on, when it is a separate object. Empty: the body")


class DIGITOOLS_PG_full_rig(bpy.types.PropertyGroup):
    __annotations__ = dict(
        {o.id: option_property(o) for o in spec.OPTIONS},
        **{prop: part_mesh_property(label) for _kind, prop, label, _option in PART_MESH_PICKERS},
        preset=EnumProperty(name="Preset", description="Lean builds only what posing needs; Everything switches every extra on. "
                            "Changing it sets all the options below",
                            items=[(p, spec.PRESET_LABELS[p], "") for p in spec.PRESETS], default='LEAN',
                            update=lambda self, context: apply_preset(self, context)),
        face_rig=BoolProperty(name="Face", default=True,
                              description="Build the face rig: brows, lids, mouth, tongue. Off skips Check Face Guides "
                                          "and the face rig"),
        ears=BoolProperty(name="Ears", get=ears_on, set=set_ears,
                          description="Rig the ears. Off: the ears move with the head. On: the Ears type you chose last"),
        ear_type_last=StringProperty(name="Last Ears Type", options={'HIDDEN'},
                                     description="The Ears type the Ears toggle switches back on ('' = the Face's)"))

    def values(self):
        """{option id: value} as set on the card (what full_rig_spec.config_for takes)."""
        return {o.id: getattr(self, o.id) for o in spec.OPTIONS}

    def part_meshes(self):
        """{part kind: mesh name} of the part mesh pickers ('' = the body), what full_rig.run_step takes."""
        return {kind: getattr(self, prop).name if getattr(self, prop) else '' for kind, prop, _label, _option in PART_MESH_PICKERS}


def settings_of(ob):
    """The card settings of an object, {name: value} in the order put_settings sets them back: the preset first (it
    sets every option, which are then put back one by one), the options in table order (the Face before the face
    options it sets), then the rest."""
    a = ob.digit_full_rig
    rest = [prop for _kind, prop, _label, _toggle in PART_MESH_PICKERS] + ['face_rig', 'ear_type_last']
    return {name: getattr(a, name) for name in ['preset'] + [o.id for o in spec.OPTIONS] + rest}


def put_settings(ob, saved):
    for name, value in saved.items():
        setattr(ob.digit_full_rig, name, value)


def copy_settings(src, dst):
    """The card settings of one object onto another (the rig takes them over from the mesh, and gives them back)."""
    put_settings(dst, settings_of(src))


# ---------------------------------------------------------------- finding the character
Found = namedtuple('Found', 'name meshes guides rig legacy owner')


def rig_of(ob):
    """(full-rig armature, other armature) of an object: a rig made by this tool, else a rig made before it."""
    if ob.type == 'ARMATURE':
        candidates = [ob]
    elif ob.type == 'MESH':
        candidates = [bpy.data.objects.get(ob.get(F.RIG_OF, ''))] + [m.object for m in ob.modifiers if m.type == 'ARMATURE' and m.object] \
            + [ob.parent]
    else:
        return None, None
    arms = [c for c in candidates if c is not None and c.type == 'ARMATURE' and not br.is_guides(c)
            and c.get(br.TAG) != F.PART_TAG]
    mine = next((a for a in arms if F.RECORD in a.data), None)
    return mine, (arms[0] if arms and mine is None else None)


def guides_named(name):
    ob = bpy.data.objects.get(name or '')
    return ob if br.is_guides(ob) else None


def find(context):
    """The character the card works on, from the active object (rig, mesh, guides): Found(name, meshes, guides, rig,
    legacy rig, settings owner) or None. A plain mesh selected together with a bare character (no mesh: the guides or
    the rig) finds that character, for Use This Mesh. Cheap: custom properties and names only."""
    ob = context.active_object
    found = found_from(ob, context) if ob is not None else None
    if found is not None and found.owner == ob and found.guides is None and ob.type == 'MESH':   # a mesh, nothing started
        bare = (found_from(o, context) for o in context.selected_objects if o.type == 'ARMATURE')
        return next((f for f in bare if f is not None and is_bare(f)), found)
    return found


def is_bare(found):
    """A character of this tool without a mesh."""
    return found.legacy is None and not found.meshes


def found_from(ob, context):
    rig, legacy = rig_of(ob)
    if rig is not None:
        rec = F.read_record(rig)
        return Found(rig.name.removesuffix(' Rig'), F.meshes_of(rec), guides_named(rec.get('guides')), rig, None, rig)
    if legacy is not None:
        return Found(legacy.name, [], None, None, legacy, legacy)
    part = ob.get(br.TAG) == F.PART_TAG
    guides = ob if br.is_guides(ob) else guides_named(ob.get(F.GUIDES_OF))
    if guides is not None:
        names = json.loads(guides.get('full_rig_meshes', '[]'))
        meshes = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
        if not meshes:                   # a bare character: the guides hold the settings
            return Found(guides.name.removesuffix(' Guides'), [], guides, None, None, guides)
    elif ob.type == 'MESH' and not part:
        meshes = [ob] + [o for o in context.selected_objects if o.type == 'MESH' and o != ob]
    else:
        return None
    return Found(meshes[0].name, meshes, guides, None, None, meshes[0])


def spare_meshes(context, found):
    """The selected meshes a bare character can take (Use This Mesh): not rigged, not another character's, not a part
    or a control shape."""
    if found is None or not is_bare(found):
        return []
    return [o for o in context.selected_objects if o.type == 'MESH' and not F.is_widget(o) and o.get(br.TAG) != F.PART_TAG
            and rig_of(o) == (None, None) and guides_named(o.get(F.GUIDES_OF)) is None]


def unique_name(stem):
    """`stem`, else `stem 2`, `stem 3` ...: a name no rig, guides or part guides object has yet."""
    def taken(name):
        return any(f'{name}{end}' in bpy.data.objects for end in ('', ' Guides', ' Part Guides'))
    return next(name for name in (stem if i == 1 else f'{stem} {i}' for i in count(1)) if not taken(name))


# ---------------------------------------------------------------- operators
def ensure_object_mode(context):
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def make_active(context, ob):
    for o in context.selected_objects:
        o.select_set(False)
    ob.hide_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob


class DIGITOOLS_OT_full_rig_step(bpy.types.Operator):
    """Run this step of the Full Character Rig (again, when the step is done)"""
    bl_idname = "digits_assorted_tools.full_rig_step"
    bl_label = "Full Character Rig Step"
    bl_options = {'REGISTER', 'UNDO'}

    step: EnumProperty(name="Step", items=STEP_ITEMS)
    redo: BoolProperty(name="Again", default=False, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return F.STEP_TIPS[F.STEP_IDS.index(properties.step)] + (". Does this step again" if properties.redo else "")

    @classmethod
    def poll(cls, context):
        found = find(context)
        if found is None or found.legacy is not None:
            cls.poll_message_set("Select the character mesh (or its rig)")
            return False
        return True

    def invoke(self, context, event):
        if self.redo and self.step in F.GUIDE_STEPS:        # these put the guides back where they start
            return context.window_manager.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context):
        found = find(context)
        ensure_object_mode(context)
        s = found.owner.digit_full_rig
        saved = settings_of(found.owner) if found.owner == found.guides else None   # bare: Add Guides again replaces them
        try:
            guides, rig, lines = F.run_step(self.step, found.meshes, s.values(), found.guides, found.rig, s.face_rig,
                                            part_meshes=s.part_meshes())
        except (ValueError, KeyError) as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        if saved is not None and self.step == 'guides':
            put_settings(guides, saved)
        if rig is not None and found.rig is None:
            copy_settings(guides if saved is not None else found.owner, rig)    # the rig has the settings from now on
        make_active(context, guides if self.step == 'guides' else rig or guides)
        for line in lines:
            self.report({'INFO'}, line)
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_new_bare(bpy.types.Operator):
    """Place the guides of a new rig at the 3D cursor, with no character mesh: to try the rig tools. Drag the guides,
    then Generate Body. Fit and Weights are skipped until you give it a mesh"""
    bl_idname = "digits_assorted_tools.full_rig_new_bare"
    bl_label = "New Rig Without Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if find(context) is not None:
            cls.poll_message_set("A character is selected: use its steps")
            return False
        return True

    def execute(self, context):
        ensure_object_mode(context)
        guides = F.add_guides([], spec.preset('LEAN'), unique_name(BARE_NAME),
                              matrix=Matrix.Translation(context.scene.cursor.location))
        make_active(context, guides)     # its settings start as the card's defaults (the Lean preset)
        self.report({'INFO'}, f"{guides.name} placed at the 3D cursor: drag them, then Generate Body")
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_use_mesh(bpy.types.Operator):
    """Give this rig the selected mesh: it becomes the character's mesh, as if the rig had started from it. Before
    Generate Body, the guides move to the mesh and Fit Guides fits them to it; after it, Weights skins it (move the
    mesh onto the rig first)"""
    bl_idname = "digits_assorted_tools.full_rig_use_mesh"
    bl_label = "Use This Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not spare_meshes(context, find(context)):
            cls.poll_message_set("Select a mesh together with a rig made without one")
            return False
        return True

    def execute(self, context):
        found = find(context)
        meshes = spare_meshes(context, found)
        ensure_object_mode(context)
        F.set_meshes(found.guides, found.rig, meshes)
        if found.rig is None:            # Fit reads the mesh from the guides' place, as if they had started on it
            F.place_guides(found.guides, Matrix.Translation(meshes[0].matrix_world.translation))
            copy_settings(found.guides, meshes[0])          # the settings sit on the first mesh until the body is built
        make_active(context, found.rig or found.guides)
        self.report({'INFO'}, f"{', '.join(o.name for o in meshes)}: now the mesh of {friendly_name(found.name)}")
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_accept(bpy.types.Operator):
    """Make the new rig final: it replaces the rough skeleton it was built from and takes its name"""
    bl_idname = "digits_assorted_tools.full_rig_accept"
    bl_label = "Accept"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        found = find(context)
        return found is not None and found.rig is not None and not F.read_record(found.rig).get('accepted')

    def execute(self, context):
        found = find(context)
        ensure_object_mode(context)
        for line in F.accept(found.rig):
            self.report({'INFO'}, line)
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_remove(bpy.types.Operator):
    """Remove the rig and put the meshes back as they were (modifiers, vertex groups, parenting); the guides go too"""
    bl_idname = "digits_assorted_tools.full_rig_remove"
    bl_label = "Remove"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        found = find(context)
        return found is not None and (found.rig is not None or found.guides is not None)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        found = find(context)
        ensure_object_mode(context)
        meshes = found.meshes
        if found.rig is not None:
            if meshes:
                copy_settings(found.rig, meshes[0])         # the settings go back to the mesh
            lines = F.remove(found.rig)
        else:
            F.remove_guides(found.guides)
            lines = ['guides removed']
        if meshes:
            make_active(context, meshes[0])
        for line in lines:
            self.report({'INFO'}, line)
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_keep_extras(bpy.types.Operator):
    """Put the selected bones on this rig's Keep These Extras list (bones the tool does not make, such as your own
    lashes or jaw bones), or take them off it. Listed extras survive Regenerate; unlisted ones are reported"""
    bl_idname = "digits_assorted_tools.full_rig_keep_extras"
    bl_label = "Keep Selected Bones"
    bl_options = {'REGISTER', 'UNDO'}

    keep: BoolProperty(name="Keep", default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        arm = character(context)
        return arm is not None and context.mode == 'POSE'

    def execute(self, context):
        arm = character(context)
        picked = {b.name for b in context.selected_pose_bones or []}
        mine = F.tool_bones(arm)
        current = set(F.extras_list(arm))
        names = current | (picked - mine) if self.keep else current - picked
        F.set_extras(arm, names)
        self.report({'INFO'}, f"Keep list: {len(names)} extras")
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_sort_collections(bpy.types.Operator):
    """Sort this rig's bones into the shared Bone Collections layout (Body, Face, Deform...), the same names on every
    character. Safe to run again"""
    bl_idname = "digits_assorted_tools.full_rig_sort_collections"
    bl_label = "Sort Bone Collections"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character(context) is not None

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context)
        plan = bc.plan_rig(arm)
        bc.build(arm, plan, bc.extra_adjustment(arm, plan))
        self.report({'INFO'}, f"Sorted {len(plan)} bones into {len(arm.data.collections_all)} collections")
        return {'FINISHED'}


class DIGITOOLS_OT_full_rig_fix_bbone_display(bpy.types.Operator):
    """Draw every bone's B-Bone width to fit its length (Blender's default 0.1 m is fat on a character) and clear
    per-bone B-Bone display on the rig and its part armatures, so Edit Mode stays clear on small rigs. Safe to run again"""
    bl_idname = "digits_assorted_tools.fix_bbone_display"
    bl_label = "Fix Bone Display"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character(context) is not None

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context)
        changed = bc.set_bbone_display(arm)
        cleared = sum(bc.clear_bbone_overrides(ob) for ob in rig_armatures(arm))
        self.report({'INFO'}, f"Bone display fixed: size on {changed} of {len(arm.data.bones)} bones, "
                              f"{cleared} per-bone B-Bone displays cleared")
        return {'FINISHED'}


# ---------------------------------------------------------------- drawing
def stale_groups(states, marks, values):
    """Option groups with an option that differs from the build of a stale step."""
    return {spec.BY_ID[i].group for step, _state, stale in states if stale
            for i, v in (marks.get(step) or {}).items() if values[i] != v}


def step_marks(found):
    """The marks the stale steps compare with (the rig's, else the guides')."""
    if found.rig is not None:
        return F.steps_of(F.read_record(found.rig))
    return F.guide_marks(found.guides)


def face_label(settings):
    """"Snout face" / "Human face" for the card's summary lines."""
    return f"{spec.FACES[settings.face]['label']} face"


def draw_plan(layout, context, s, found):
    built = found.rig is not None
    box = section(layout, "digitools_full_rig_plan", "Plan", icon='PRESET', default_closed=built,
                  right=f"{spec.PRESET_LABELS[s.preset]} · {face_label(s)}")
    if not box:
        return
    for name, label in PLAN_CHOICES:
        col = box.column(align=True)
        col.active = not (built and name in F.GUIDE_IDS)
        choice_row(col, s, name, label=label)
    if built:
        hints(box, [GUIDE_NOTE])
    box.separator()
    draw_build(box, s, context)


def draw_build(layout, s, context=None):
    """Build: a plain on / off toggle per part (the body is always built), on two rows: the head (Face | Ears | Hair),
    then the body (Tail | Breasts | Butt). The settings of the parts that are on follow under the rows. Wings: the Add
    Rig Component tool (a hint says so)."""
    buttons = sub_heading(layout, "Build").column(align=True)
    for names in BUILD_ROWS:
        row = buttons.row(align=True)
        for name in names:
            row.prop(s, name, toggle=True)
    items = part_items(s)
    if items:
        layout.separator()
        prop_group(layout, s, items)
    hints(layout, [p.note for p in BUILD_PARTS if getattr(s, p.toggle)] + [WINGS_NOTE], context)


def part_items(s):
    """The settings the Build row draws: each part that is on, its settings then its mesh picker, a gap between parts."""
    pickers = {toggle: (prop, label) for _kind, prop, label, toggle in PART_MESH_PICKERS}
    items = []
    for part in BUILD_PARTS:
        own = list(part.settings) + ([pickers[part.toggle]] if part.toggle in pickers else [])
        if getattr(s, part.toggle) and own:
            items += ([None] if items else []) + own
    return items


def draw_steps(layout, context, found, states, values):
    """The Steps section; returns the option groups whose steps are stale."""
    active = [st for st in states if st[1] != 'off']
    done = sum(1 for st in active if st[1] == 'done')
    nxt = next((st for st in states if st[1] == 'next'), None)
    box = section(layout, "digitools_full_rig_steps", "Steps", icon='TIME',
                  right="done" if nxt is None else f"Next: {F.STEP_TITLES[F.STEP_IDS.index(nxt[0])]}")
    if not box:
        return set()
    progress(box, done, len(active), f"{done} of {len(active)}" + (" · done" if done == len(active) else ""))
    stale = []
    for number, (step, state, is_stale) in enumerate(states, 1):
        title = F.STEP_TITLES[F.STEP_IDS.index(step)]
        if state == 'off':
            row = box.row()
            row.active = False
            row.label(text=f"{number}  {title}")
            continue
        rebuildable = state == 'done' and not (found.rig is not None and step in F.GUIDE_STEPS)
        idname = DIGITOOLS_OT_full_rig_step.bl_idname
        op = step_row(box, number, title, state, idname, idname if rebuildable else None, is_stale,
                      rebuild_props=dict(step=step, redo=True), step=step)
        op.redo = state == 'done'
        if is_stale:
            stale.append(step)
    groups = stale_groups(states, step_marks(found), values)
    if stale:
        box.separator()
        status(box, " and ".join(g for g in spec.GROUPS if g in groups) + " options changed since the build", icon='ERROR')
        for step in stale:
            row = action_row(box)
            row.alert = True
            op = row.operator(DIGITOOLS_OT_full_rig_step.bl_idname,
                              text=f"Rebuild {F.STEP_SHORT[F.STEP_IDS.index(step)]}", icon='FILE_REFRESH')
            op.step, op.redo = step, True
    elif nxt:
        hints(box, [F.STEP_TIPS[F.STEP_IDS.index(nxt[0])]], context)
    if found.rig is not None or found.guides is not None:
        row = box.row(align=True)
        if found.rig is not None and not F.read_record(found.rig).get('accepted'):
            row.operator(DIGITOOLS_OT_full_rig_accept.bl_idname, icon='CHECKMARK')
        row.operator(DIGITOOLS_OT_full_rig_remove.bl_idname, icon='TRASH')
    return groups


def option_summary(group, s, changed):
    text = count_on(s, [i for i in option_items(group) if spec.BY_ID[i].kind == 'bool'])
    if group == 'Body' and not changed:
        text = f"Spine {s.spine_bones} · {text}"
    return text + (" · changed" if changed else "")


def draw_options(layout, s, groups):
    for group, title, icon in OPTION_BOXES:
        items = option_items(group)
        if not items:
            continue
        box = section(layout, f"digitools_full_rig_{group.lower()}", title, icon=icon, default_closed=True,
                      right=option_summary(group, s, group in groups))
        if box:
            box.active = group != 'Face' or s.face_rig
            prop_group(box, s, items)


def option_items(group):
    """The options a group's box draws: the leftovers, not the Plan's guide options nor the Build row's parts and
    their settings."""
    return [o.id for o in spec.options(group) if o.id not in F.GUIDE_IDS and o.id not in PART_OPTION_IDS]


def draw_existing(layout, context, arm):
    """A rig made before this tool: its per-rig actions (the former Face Rig and Limbs tools)."""
    status(layout, f"{friendly_name(arm.name)} · built before this tool", icon='ARMATURE_DATA')
    box = section(layout, "digitools_full_rig_existing", "Existing Rig", icon='ARMATURE_DATA')
    if box:
        face_built = core.has_built(arm)
        col = box.column(align=True)
        row = action_row(col)
        row.enabled = face_built
        row.operator("digits_assorted_tools.face_rig_build", text="Rebuild Face", icon='FILE_REFRESH').rebuild = True
        row = action_row(col)
        row.enabled = face_built
        row.operator("digits_assorted_tools.face_rig_fix_eyes", icon='HIDE_OFF')
        action_row(col).operator("digits_assorted_tools.limbs_upgrade", text="Upgrade Limbs", icon='CON_KINEMATIC')
        action_row(col).operator("digits_assorted_tools.body_features_add", text="Add Body Features", icon='POSE_HLT')
        action_row(col).operator(DIGITOOLS_OT_full_rig_sort_collections.bl_idname, icon='GROUP_BONE')
        action_row(col).operator(DIGITOOLS_OT_full_rig_fix_bbone_display.bl_idname, icon='BONE_DATA')
        hints(box, ["" if face_built else "Rebuild Face needs a face rig built with the old Face Rig tool",
                    "Rebuild Face keeps your pose and bone sorting", "Fix Eye Controls centres the eye rings and puts the lid controls on the lid edge, no rebuild", "Upgrade Limbs adds IK stretch and parent switching",
                    "Add Body Features adds pole lines, pole follow, foot bank and head / neck follow"], context)
        prop_group(box, arm.digit_face_rig, ["keep_weights"])
    limbs = section(layout, "digitools_full_rig_limb_options", "Limb Options", icon='PREFERENCES', default_closed=True)
    if limbs:
        prop_group(limbs, arm.digit_limbs, ["stretch", "parent_switch", "hock"] + list(br.FEATURES))
    hints(layout, ["To build a new Full Character Rig, select a mesh without a rig"], context)


def draw_no_mesh(layout, context, found):
    """A bare character: Use This Mesh while a spare mesh is selected, else how to add one."""
    spare = spare_meshes(context, found)
    if not spare:
        hints(layout, [NO_MESH_NOTE], context)
        return
    text = "Use This Mesh" if len(spare) == 1 else f"Use These {len(spare)} Meshes"
    action_row(layout).operator(DIGITOOLS_OT_full_rig_use_mesh.bl_idname, text=text, icon='MESH_DATA')
    if found.rig is not None:
        hints(layout, [LATE_MESH_NOTE], context)


def draw_extras(layout, context, arm):
    """Keep These Extras: the bones on the rig that the tool did not make. Listed ones survive Regenerate; the others
    stay too but are reported."""
    box = section(layout, "digitools_full_rig_extras", "Keep These Extras", icon='BONE_DATA', default_closed=True)
    if not box:
        return
    report = F.extras_report(arm)
    status(box, f"{len(report['kept'])} kept · {len(report['unlisted'])} not on the list", icon='INFO')
    col = box.column(align=True)
    row = action_row(col)
    row.operator(DIGITOOLS_OT_full_rig_keep_extras.bl_idname, text="Keep Selected", icon='ADD').keep = True
    row.operator(DIGITOOLS_OT_full_rig_keep_extras.bl_idname, text="Unlist Selected", icon='REMOVE').keep = False
    hints(box, F.extras_lines(report) or ["No bones outside the tool's own"], context)


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    found = find(context)
    if found is None:
        status(body, "Select the character (or its rig)")
        action_row(body).operator(DIGITOOLS_OT_full_rig_new_bare.bl_idname, icon='ARMATURE_DATA')
        hints(body, [BARE_START_NOTE], context)
        return
    if found.legacy is not None:
        draw_existing(body, context, found.legacy)
        return
    s = found.owner.digit_full_rig
    name = friendly_name(found.name)
    bare = is_bare(found)
    if found.rig is not None:
        status(body, f"{name} · rigged · " + ("no mesh" if bare else f"{spec.PRESET_LABELS[s.preset]} · {face_label(s)}"),
               icon='CHECKMARK')
    else:
        status(body, f"{name} · " + ("no mesh, no rig yet" if bare else "no rig yet"), icon='ARMATURE_DATA')
    if bare:
        draw_no_mesh(body, context, found)
    draw_plan(body, context, s, found)
    values = s.values()
    groups = draw_steps(body, context, found, F.step_states(found.guides, found.rig, values, s.face_rig), values)
    draw_options(body, s, groups)
    if found.rig is not None:
        draw_extras(body, context, found.rig)


classes = (DIGITOOLS_PG_full_rig, DIGITOOLS_OT_full_rig_step, DIGITOOLS_OT_full_rig_new_bare, DIGITOOLS_OT_full_rig_use_mesh,
           DIGITOOLS_OT_full_rig_accept, DIGITOOLS_OT_full_rig_remove, DIGITOOLS_OT_full_rig_sort_collections,
           DIGITOOLS_OT_full_rig_fix_bbone_display, DIGITOOLS_OT_full_rig_keep_extras)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_full_rig = PointerProperty(type=DIGITOOLS_PG_full_rig)


def unregister():
    del bpy.types.Object.digit_full_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
