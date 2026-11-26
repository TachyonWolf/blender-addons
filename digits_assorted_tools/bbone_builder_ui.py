# SPDX-License-Identifier: GPL-3.0-or-later
"""B-Bone Chain Builder card (Digit's Tools > Character Rigs): place points (a guide armature "<Name> Points"), give
each a control level 4 / 3 / 2 / 1, then Build a chain or loop of B-bones through them into a rig; Edit Points, Rebuild,
Reset Pose, Remove, Mirror to Other Side, Weights. Add Web Between (2 points picked): a light blue web point
joined to both, its links drawn as thin light blue lines. Place Points is a stay-on click modal (view_ray): click adds a point (near the curve: inserts), click a point
picks it, drag moves it, 4 / 3 / 2 / 1 set its level, X removes it, Esc / Enter / the button ends it. Clicks outside
the viewport window pass through, so the card's buttons work while it runs. Into empty: Build makes a new armature. All rig logic is in bbone_builder (generated copy of
Addons/shared_addon/bbone_builder.py). Nothing runs in the background: the card reads the guide's few bones only
while it is open."""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras import view3d_utils
from mathutils import Vector

from . import bbone_builder as bb, view_ray  # generated copies
from .ui_cards import action_row, choice_row, hints, poll_message, prop_group, section, status, wrapped  # generated copy

START_ITEMS = [('WING', "Wing Loop (example)", "A closed loop round a wing outline: 3 level 3, 2 level 2, 5 level 1"),
               ('TAIL', "Tail Chain (example)", "An open chain: base, middle and tip level 3, points between"),
               ('EMPTY', "Empty", "No points: place them with Place Points")]
SHAPE_ITEMS = [('CHAIN', "Chain", "An open run of B-bones from the first point to the last"),
               ('LOOP', "Loop", "A closed loop: the last point joins back to the first")]
CURVE_ITEMS = [('CONTROLS', "Controls", "Each B-bone's ends follow the controls there: turn a control to steer the curve "
                "(point two neighbours' Y axes along the line between them for a straight B-bone); scale its Y for a "
                "fuller curve. Auto Turn (a slider on the first main control, in the Rig panel) keeps each control "
                "turned along the curve as the points move; your own turn adds on top"),
               ('NEIGHBOURS', "Neighbours", "Each B-bone's ends follow its neighbouring B-bones: one smooth curve that "
                "only moving the controls changes (like Digit's eye lids)")]
LEVEL_ICONS = ('COLLECTION_COLOR_04', 'COLLECTION_COLOR_02', 'COLLECTION_COLOR_01', 'COLLECTION_COLOR_06')   # levels 1 2 3 4: green-teal, orange, red, purple
LEGEND = ((4, "Level 4: main, in charge. Moves only when you move it."),
          (3, "Level 3: follows the nearest level 4 on each side, blended by distance. You can still move it."),
          (2, "Level 2: follows the nearest level 3 or 4 on each side."),
          (1, "Level 1: follows the nearest level 2, 3 or 4 on each side. Like the in-between lid points on Digit's eyes."))
LEVEL_KEYS = {name: n for n, word in ((1, 'ONE'), (2, 'TWO'), (3, 'THREE'), (4, 'FOUR')) for name in (word, f'NUMPAD_{n}')
              if n <= bb.LEVEL_COUNT}
REMOVE_KEYS = {'X', 'DEL'}
DONE_KEYS = {'RET', 'NUMPAD_ENTER'}
ADD_HELP = "Click: add  ·  click a point: pick  ·  drag: move  ·  4 3 2 1: level  ·  X: remove  ·  Esc: done"
WEB_HELP = ("Web point (light blue): joins 2 points, shown by light blue lines. Follows them by distance; "
            "you can still move it.")
MODE = {'on': False, 'stop': False}      # Place Points running / asked to end (the button again)


def is_rig(_self, ob):
    return ob.type == 'ARMATURE' and not bb.is_guide(ob)


def is_mesh(_self, ob):
    return ob.type == 'MESH'


class DIGITOOLS_PG_bbone(bpy.types.PropertyGroup):
    """A guide armature's build settings (on the guide object)."""
    shape: EnumProperty(name="Shape", items=SHAPE_ITEMS, default='CHAIN')
    chain_name: StringProperty(name="Name", default="Chain",
                               description="Bone names: <Name>1 controls, DEF-<Name>1 B-bones, MCH-<Name>Follow1")
    target: PointerProperty(name="Into", type=bpy.types.Object, poll=is_rig, description="The rig to build into")
    parent_bone: StringProperty(name="Parent", description="The bone the level 4 controls hang under (e.g. Chest)")
    curve_from: EnumProperty(name="Curve From", items=CURVE_ITEMS, default=bb.CURVES[0],
                             description="What steers the B-bones' curve at each point. Rebuild applies it")
    segments: IntProperty(name="B-Bone Segments", default=bb.SEGMENTS, min=1, max=16,
                          description="Bendy bone segments of each B-bone")
    mesh: PointerProperty(name="Mesh", type=bpy.types.Object, poll=is_mesh,
                          description="Weights: the whole mesh goes on the chain's B-bones (nearest ones)")
    smooth: BoolProperty(name="Smooth", default=True,
                         description="Smooth: no creases or rips where parts touch (weights are smoothed through space)")
    reach: FloatProperty(name="Reach", default=3.0, min=0.5, max=10.0, subtype='PERCENTAGE',
                         description="How far the smoothing reaches, in percent of the chain's length")
    with_selected: BoolProperty(name="And Selected Meshes", default=False,
                                description="Also weight the selected meshes, together with this one (a rim and panels in separate objects)")
    keep_twin: BoolProperty(name="Keep Mirror Twin", default=True,
                            description="Rebuild also rebuilds the other side's chain (.L / .R) from the mirrored points, so both sides match")
    built: StringProperty(name="Built", description="The chain name of the last build (empty: not built)")


# ---------------------------------------------------------------- state
def current_guide(context):
    """The guide of the card: the active object when it is one, else the last one used (if still in the scene, or in no collection: it is relinked on use)."""
    ob = context.active_object
    if bb.is_guide(ob):
        return ob
    last = context.scene.digit_bbone_guide
    return last if bb.is_guide(last) and (last.name in context.scene.objects or not last.users_collection) else None


def editing(context, guide):
    return guide is not None and context.active_object == guide and guide.mode == 'EDIT'


def active_point(context, guide):
    return guide.data.edit_bones.active if editing(context, guide) else None


def build_problem(context):
    guide = current_guide(context)
    if guide is None:
        return "Make points first (Start New B-Bone Chain)"
    s = guide.digit_bbone
    need = 3 if s.shape == 'LOOP' else 2
    if len(bb.guide_bones(guide)) < need:
        return f"Build: a {s.shape.lower()} needs {need} points"
    if not s.chain_name.strip():
        return "Build: give the chain a name"
    return ""


def built_rig(context):
    """(guide, rig, chain name) of a built chain, or (guide, None, '')."""
    guide = current_guide(context)
    if guide is None:
        return None, None, ''
    s = guide.digit_bbone
    return (guide, s.target, s.built) if s.built and s.target is not None else (guide, None, '')


def to_object_mode(context):
    if context.active_object is not None and context.active_object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def focus(context, ob, mode):
    """Make `ob` the shown, selected, active object in `mode`."""
    to_object_mode(context)
    ob.hide_set(False)
    for other in context.selected_objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if mode != 'OBJECT':
        bpy.ops.object.mode_set(mode=mode)


def sync(context, guide):
    """Edit Mode on the guide: web links back on their points (they don't follow Blender's own moves). Every card
    tool runs it first; Place Points on every event it sees."""
    if editing(context, guide) and bb.sync_webs(guide):
        redraw(context)


def redraw(context):
    for area in context.screen.areas if context.screen else ():
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def unique_chain_name(base):
    """`base`, or base2, base3 ... when another guide already uses it."""
    taken = {ob.digit_bbone.chain_name for ob in bpy.data.objects if bb.is_guide(ob)}
    name, k = base, 2
    while name in taken:
        name, k = f"{base}{k}", k + 1
    return name


# ---------------------------------------------------------------- operators
class DIGITOOLS_OT_bbone_new(bpy.types.Operator):
    """Start a new B-bone chain: a new set of points (a guide armature) at the 3D cursor, from the Start From
    shape, aimed at the active rig (none: Build makes a new armature)"""
    bl_idname = "digits_assorted_tools.bbone_new"
    bl_label = "Start New B-Bone Chain"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        start = context.scene.digit_bbone_start
        loop, base, _points = bb.EXAMPLES[start]
        rig = context.active_object if context.active_object and is_rig(None, context.active_object) else None
        bone = rig.data.bones.active.name if rig and rig.data.bones.active else ''
        to_object_mode(context)
        name = unique_chain_name(base)
        guide = bb.new_guide(context.collection or context.scene.collection, name, start,
                             context.scene.cursor.location.copy())
        s = guide.digit_bbone
        s.shape, s.chain_name, s.target, s.parent_bone = ('LOOP' if loop else 'CHAIN'), name, rig, bone
        context.scene.digit_bbone_guide = guide
        focus(context, guide, 'EDIT')
        self.report({'INFO'}, f"{guide.name}: {len(bb.guide_bones(guide))} points")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_add_points(bpy.types.Operator):
    """Place points in the viewport until you end it (Esc, Enter, or this button again): click adds a point (on a
    surface at the hit, else at the 3D cursor's depth; near the curve inserts one), click a point picks it, drag
    moves it, 0 / 1 / 2 set its level, X removes it. Clicks on panels and buttons pass through"""
    bl_idname = "digits_assorted_tools.bbone_add_points"
    bl_label = "Place Points"
    bl_options = {'REGISTER', 'UNDO'}

    guide_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    drag = None      # the name of the point being dragged

    @classmethod
    def poll(cls, context):
        return poll_message(cls, "" if current_guide(context) else "Make points first (Start New B-Bone Chain)")

    def invoke(self, context, event):
        if MODE['on']:      # the button again: end the running mode
            MODE['stop'] = True
            return {'FINISHED'}
        MODE['on'] = True
        guide = current_guide(context)
        self.guide_name = guide.name
        focus(context, guide, 'EDIT')
        return view_ray.begin_click(context, self, 'CROSSHAIR', ADD_HELP)

    def finish(self, context):
        MODE['on'] = MODE['stop'] = False
        view_ray.end_click(context)
        redraw(context)
        return {'FINISHED'}

    def modal(self, context, event):
        guide = bpy.data.objects.get(self.guide_name)
        if guide is None or guide.mode != 'EDIT' or MODE['stop']:
            return self.finish(context)
        if event.value == 'PRESS' and event.type in DONE_KEYS:
            return self.finish(context)
        if bb.sync_webs(guide):      # links catch up after a move (e.g. G) ended
            redraw(context)
        found = view_ray.viewport_under_mouse(context.window.screen.areas, event.mouse_x, event.mouse_y)
        if self.drag is not None:
            return self.dragging(context, guide, event, found)
        if found is None:      # over the sidebar, header or another editor: the UI keeps the event
            return {'PASS_THROUGH'}
        if event.value == 'PRESS' and event.type in LEVEL_KEYS:
            bb.set_level(guide, bb.selected_points(guide), LEVEL_KEYS[event.type])
            redraw(context)
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and event.type in REMOVE_KEYS:
            selected = bb.selected_points(guide)
            bb.remove_points(guide, selected[:1])
            redraw(context)
            return {'RUNNING_MODAL'}
        kind = view_ray.click_kind(event)
        if kind == 'cancel':
            return self.finish(context)
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind == 'wait':
            context.window.cursor_modal_set('CROSSHAIR')   # other areas reset it as the mouse crosses them
            return {'RUNNING_MODAL'}
        self.click(context, guide, event, *found)
        redraw(context)
        return {'RUNNING_MODAL'}

    def dragging(self, context, guide, event, found):
        """A picked point follows the mouse (at its own depth) until the button is released."""
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.drag = None
        elif event.type == 'MOUSEMOVE' and found is not None:
            region, view = found
            bone = guide.data.edit_bones.get(self.drag)
            if bone is not None:
                world = guide.matrix_world @ bone.head
                co = view3d_utils.region_2d_to_location_3d(region, view, (event.mouse_x - region.x,
                                                                           event.mouse_y - region.y), world)
                move = guide.matrix_world.inverted() @ co - bone.head
                bone.head += move
                bone.tail += move
                bb.place_links(guide)
            redraw(context)
        return {'RUNNING_MODAL'}

    def click(self, context, guide, event, region, view):
        """Pick the point under the mouse (and start dragging it), else insert one on the curve, else add one at the
        end."""
        mouse = (event.mouse_x - region.x, event.mouse_y - region.y)
        order = bb.guide_bones(guide)
        pickable = order + bb.web_bones(guide)
        screen = [view3d_utils.location_3d_to_region_2d(region, view, guide.matrix_world @ b.head) for b in pickable]
        picked = bb.nearest_point(screen, mouse)
        if picked >= 0:
            bb.select_only(guide, pickable[picked])
            self.drag = pickable[picked].name
            return
        seg = bb.insert_after(screen[:len(order)], mouse, guide.digit_bbone.shape == 'LOOP')
        hit = view_ray.hit_under_mouse(context, event)
        co = hit[0] if hit and hit[0] is not None else \
            view3d_utils.region_2d_to_location_3d(region, view, mouse, context.scene.cursor.location)
        up = view.view_rotation @ Vector((0, 1, 0))
        if seg >= 0:
            bb.add_point(guide, co, new_level(context, 1), order[seg].name, up)
        else:
            bb.add_point(guide, co, new_level(context, 2 if order else bb.LEVEL_COUNT), None, up)


def new_level(context, default):
    """The level of a newly placed point: the user's pick in the card, else `default`."""
    scene = context.scene
    return int(scene.digit_bbone_new_level) if scene.get('digit_bbone_level_picked') else default


def level_picked(self, _context):
    self['digit_bbone_level_picked'] = True


def point_problem(context):
    guide = current_guide(context)
    if not editing(context, guide):
        return "Points: Edit Points (or Place Points) first"
    if not bb.selected_points(guide):
        return "Points: select a point"
    return ""


def subdivide_problem(context):
    guide = current_guide(context)
    if not editing(context, guide):
        return "Points: Edit Points (or Place Points) first"
    if not bb.adjacent_pairs(guide, guide.digit_bbone.shape == 'LOOP'):
        return "Select two points next to each other"
    return ""


def web_problem(context):
    guide = current_guide(context)
    if not editing(context, guide):
        return "Points: Edit Points (or Place Points) first"
    if len(bb.selected_points(guide)) != 2:
        return "Web: select exactly 2 points (Shift-click the second)"
    return ""


class DIGITOOLS_OT_bbone_add_web(bpy.types.Operator):
    """Add one web point midway between the 2 selected points (any two: outline or web points), joined to both. It
    follows them by distance once built; its level is one below the lower of the two"""
    bl_idname = "digits_assorted_tools.bbone_add_web"
    bl_label = "Add Web Between"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, web_problem(context))

    def execute(self, context):
        guide = current_guide(context)
        sync(context, guide)
        with bb.usable(guide):
            ends = sorted(bb.selected_points(guide), key=lambda b: b != guide.data.edit_bones.active)
            web = bb.add_web(guide, ends[0].name, ends[1].name)
        self.report({'INFO'}, f"{web.name} joins {ends[0].name} and {ends[1].name}")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_level(bpy.types.Operator):
    """Set the control level of the selected points (4 main; each lower level follows the nearest higher points)"""
    bl_idname = "digits_assorted_tools.bbone_level"
    bl_label = "Set Level"
    bl_options = {'REGISTER', 'UNDO'}

    level: IntProperty(name="Level", min=1, max=bb.LEVEL_COUNT)

    @classmethod
    def poll(cls, context):
        return poll_message(cls, point_problem(context))

    def execute(self, context):
        guide = current_guide(context)
        sync(context, guide)
        bb.set_level(guide, bb.selected_points(guide), self.level)
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_subdivide(bpy.types.Operator):
    """Add a point between each pair of neighbouring selected points, in the middle of the curve"""
    bl_idname = "digits_assorted_tools.bbone_subdivide"
    bl_label = "Subdivide"
    bl_options = {'REGISTER', 'UNDO'}

    child: BoolProperty(name="Child Level", default=False,
                        description="The new points are one level below their neighbours (min 1), else the lower "
                                    "level number of the two")

    @classmethod
    def poll(cls, context):
        return poll_message(cls, subdivide_problem(context))

    def execute(self, context):
        guide = current_guide(context)
        sync(context, guide)
        with bb.usable(guide):
            new = bb.subdivide(guide, guide.digit_bbone.shape == 'LOOP', self.child)
        self.report({'INFO'}, f"Added {len(new)} point{'' if len(new) == 1 else 's'}")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_remove_point(bpy.types.Operator):
    """Remove the selected point (the chain closes over the gap). Web points joined to it go too; a web point takes
    its two links along"""
    bl_idname = "digits_assorted_tools.bbone_remove_point"
    bl_label = "Remove Point"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, point_problem(context))

    def execute(self, context):
        guide = current_guide(context)
        sync(context, guide)
        active = guide.data.edit_bones.active
        chosen = active if active in bb.selected_points(guide) else bb.selected_points(guide)[0]
        bb.remove_points(guide, [chosen])
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_build(bpy.types.Operator):
    """Build the chain into the rig: a control per point (shape and colour by level), a B-bone per segment, the
    followers' follow set-up. Rebuild replaces the last build"""
    bl_idname = "digits_assorted_tools.bbone_build"
    bl_label = "Build"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, build_problem(context))

    def execute(self, context):
        guide = current_guide(context)
        work = bb.usable(guide)
        with work:
            return self.run(context, guide, work)

    def run(self, context, guide, work):
        s = guide.digit_bbone
        sync(context, guide)
        to_object_mode(context)
        if s.target is None:      # Into empty: a new armature named after the chain
            s.target = bb.new_rig(guide.users_collection[0] if guide.users_collection else context.scene.collection,
                                  s.chain_name.strip())
        if s.built and s.built != s.chain_name.strip():      # renamed since the last build: the old one goes
            bb.remove(s.target, s.built)
        try:
            report = bb.build(guide, s.target, s.chain_name.strip(), s.parent_bone, s.shape == 'LOOP', s.segments,
                              s.curve_from)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        s.built = s.chain_name.strip()
        context.scene.digit_bbone_guide = guide
        bb.drop_hold(guide)                 # Edit Points' hold ends: the guide goes back to the user's states, hidden
        work.hide = True
        note = ""
        if s.keep_twin and bb.twin_built(s.target, s.built):
            try:
                twin = bb.rebuild_twin(guide, s.target, s.built, s.parent_bone, s.shape == 'LOOP', s.segments,
                                       s.curve_from)
            except bb.TwinError as exc:
                twin, note = None, ""
                self.report({'WARNING'}, f"Built {s.built}, but {exc}")
            except ValueError as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            if twin:
                adopt_mirror(s, twin)
                note = f"; also rebuilt {twin['name']}"
        focus(context, s.target, 'POSE')
        self.report({'INFO'}, f"Built {len(report['deform'])} B-bones and {len(report['controls'])} controls{note}")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_edit(bpy.types.Operator):
    """Show the points again and edit them (Edit Mode on the guide); Build again when done"""
    bl_idname = "digits_assorted_tools.bbone_edit"
    bl_label = "Edit Points"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        guide = current_guide(context)
        return poll_message(cls, "" if guide and not editing(context, guide) else "Edit: already editing the points")

    def execute(self, context):
        guide = current_guide(context)
        bb.make_usable(guide, hold=True)        # stays usable until Build is pressed again
        focus(context, guide, 'EDIT')
        sync(context, guide)
        return {'FINISHED'}


def built_problem(context):
    return "" if built_rig(context)[1] is not None else "Not built yet"


def mirror_problem(context):
    why = built_problem(context)
    if why or bb.sided(built_rig(context)[2]):
        return why
    return "Mirror: name the chain with .L or .R at the end"


SETTINGS = ('shape', 'target', 'segments', 'curve_from', 'mesh', 'smooth', 'reach', 'with_selected', 'keep_twin')   # carried to the mirrored guide


def adopt_mirror(s, report):
    """The mirrored guide (report from mirror_chain) takes the settings `s` of the guide it came from."""
    other = report['guide'].digit_bbone
    for key in SETTINGS:
        setattr(other, key, getattr(s, key))
    other.chain_name = other.built = report['name']
    other.parent_bone = report['parent']
    report['guide'].hide_set(True)


class DIGITOOLS_OT_bbone_mirror(bpy.types.Operator):
    """Mirror the points to the other side (a guide "<Name>.R Points" for a .L chain, and back) and build it into the
    same rig, under the other side's parent, with mirrored rolls. Replaces the other side's points and build"""
    bl_idname = "digits_assorted_tools.bbone_mirror"
    bl_label = "Mirror to Other Side"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, mirror_problem(context))

    def execute(self, context):
        guide, rig, name = built_rig(context)
        with bb.usable(guide):
            return self.run(context, guide, rig, name)

    def run(self, context, guide, rig, name):
        s = guide.digit_bbone
        to_object_mode(context)
        try:
            report = bb.mirror_chain(guide, rig, name, s.parent_bone, s.shape == 'LOOP', s.segments,
                                     s.curve_from)
        except ValueError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        adopt_mirror(s, report)
        focus(context, rig, 'POSE')
        self.report({'INFO'}, f"Mirrored to {report['name']}: {len(report['deform'])} B-bones")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_show(bpy.types.Operator):
    """Show or hide the chain's B-bones (turns Deform on when it is hidden, without showing its other bones)"""
    bl_idname = "digits_assorted_tools.bbone_show"
    bl_label = "Show B-Bones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, built_problem(context))

    def execute(self, context):
        _guide, rig, name = built_rig(context)
        shown = bb.bbone_collection(rig, name)
        if shown.is_visible_effectively:
            shown.is_visible = False
        else:
            bb.show_bbones(rig, name)
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_reset_pose(bpy.types.Operator):
    """Put the built chain's controls back to rest"""
    bl_idname = "digits_assorted_tools.bbone_reset_pose"
    bl_label = "Reset Pose"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, built_problem(context))

    def execute(self, context):
        _guide, rig, name = built_rig(context)
        bb.reset_pose(rig, name)
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_remove(bpy.types.Operator):
    """Take the built chain out of the rig: its bones, its B-bones' vertex groups and its empty collection. The points
    stay"""
    bl_idname = "digits_assorted_tools.bbone_remove"
    bl_label = "Remove Build"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return poll_message(cls, built_problem(context))

    def execute(self, context):
        guide, rig, name = built_rig(context)
        to_object_mode(context)
        count = bb.remove(rig, name)
        guide.digit_bbone.built = ''
        self.report({'INFO'}, f"Removed {count} bones")
        return {'FINISHED'}


class DIGITOOLS_OT_bbone_weights(bpy.types.Operator):
    """Weight the whole mesh to the built chain's B-bones (each vertex on its nearest ones) and add an Armature
    modifier for the rig"""
    bl_idname = "digits_assorted_tools.bbone_weights"
    bl_label = "Weights"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = built_problem(context)
        guide = current_guide(context)
        if not why and guide.digit_bbone.mesh is None:
            why = "Weights: pick a mesh"
        return poll_message(cls, why)

    def execute(self, context):
        guide, rig, name = built_rig(context)
        to_object_mode(context)
        s = guide.digit_bbone
        extra = [o for o in context.selected_objects if o.type == 'MESH'] if s.smooth and s.with_selected else []
        count = bb.weigh(rig, s.mesh, name, smooth=s.smooth, reach=s.reach / 100, extra=extra)
        self.report({'INFO'}, f"Weighted {count} vertices")
        return {'FINISHED'}


# ---------------------------------------------------------------- card
def level_row(layout, current, enabled):
    row = layout.row(align=True)
    row.enabled = enabled
    for level in bb.LEVELS:
        row.operator(DIGITOOLS_OT_bbone_level.bl_idname, text=f"Level {level}", icon=LEVEL_ICONS[level - 1],
                     depress=current == level).level = level


def draw_add(body, context, guide):
    sec = section(body, "digitools_bbone_add", "Add Points", icon='ADD')
    if not sec:
        return
    sec.operator(DIGITOOLS_OT_bbone_add_points.bl_idname, icon='ADD', depress=MODE['on'])
    prop_group(sec, context.scene, [("digit_bbone_new_level", "New point level")])
    wrapped(sec, "Click to add · click a point to pick it · drag to move · 4 3 2 1 level · X remove · Esc done",
            context=context)


def draw_points(body, context, guide):
    sec = section(body, "digitools_bbone_point", "Selected Point", icon='RESTRICT_SELECT_OFF')
    if not sec:
        return
    point = active_point(context, guide)
    if point is None:
        sec.label(text="Pick a point")
    else:
        sec.prop(point, "name", text="Web Point" if bb.is_web(point) else "Point")
        ends = bb.web_ends(guide).get(point.name) if bb.is_web(point) else None
        if ends:
            sec.label(text=f"Joins {ends[0].name} and {ends[1].name}", icon='LINKED')
    level_row(sec, bb.level_of(point) if point is not None else None, point is not None)
    row = sec.row(align=True)
    row.enabled = point is not None
    row.operator(DIGITOOLS_OT_bbone_remove_point.bl_idname, icon='X')
    if editing(context, guide):
        sec.operator(DIGITOOLS_OT_bbone_add_web.bl_idname, icon='MOD_WIREFRAME')
    if editing(context, guide) and bb.adjacent_pairs(guide, guide.digit_bbone.shape == 'LOOP'):
        for text, child in (("Subdivide · Same Level", False), ("Subdivide · Child Level", True)):
            sec.operator(DIGITOOLS_OT_bbone_subdivide.bl_idname, text=text, icon='MOD_SUBSURF').child = child


def draw_bones(body, context, guide):
    s = guide.digit_bbone
    sec = section(body, "digitools_bbone_bones", "Bones", icon='BONE_DATA', right=f"{s.segments} segments")
    if not sec:
        return
    col = prop_group(sec, s, [("chain_name", "Name"), ("target", "Into")])
    if s.target is None:
        sec.label(text="Into: empty = a new armature")
    if s.target is not None:
        col.prop_search(s, "parent_bone", s.target.data, "bones", text="Parent")
    prop_group(sec, s, ["segments"])
    choice_row(sec, s, "curve_from", label="Curve From")
    count, webs = len(bb.guide_bones(guide)), len(bb.web_ends(guide))
    segments = (count if s.shape == 'LOOP' else max(count - 1, 0)) if count > 1 else 0
    sec.label(text=f"To build: {segments + 2 * webs} B-bones · {count + webs} controls")
    action_row(sec).operator(DIGITOOLS_OT_bbone_build.bl_idname, text="Rebuild" if s.built else "Build",
                             icon='FILE_REFRESH' if s.built else 'BONE_DATA')
    if bb.sided(s.chain_name.strip()):
        prop_group(sec, s, ["keep_twin"])
    shown = s.target.data.collections_all.get(bb.bbone_collection_name(s.built)) if s.built and s.target else None
    if shown is not None:
        on = shown.is_visible_effectively
        sec.operator(DIGITOOLS_OT_bbone_show.bl_idname, text="Show B-Bones", depress=on, icon='HIDE_OFF' if on else 'HIDE_ON')
    row = sec.row(align=True)
    row.operator(DIGITOOLS_OT_bbone_edit.bl_idname, icon='EDITMODE_HLT')
    row.operator(DIGITOOLS_OT_bbone_reset_pose.bl_idname, icon='LOOP_BACK')
    sec.operator(DIGITOOLS_OT_bbone_mirror.bl_idname, icon='MOD_MIRROR')
    sec.operator(DIGITOOLS_OT_bbone_remove.bl_idname, icon='TRASH')
    hints(sec, [build_problem(context)], context)


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    scene = context.scene
    guide = current_guide(context)
    if guide is None:
        status(body, "Make points to start", icon='BONE_DATA')
    else:
        levels = [p.level for p in bb.guide_points(guide)]
        webs = len(bb.web_ends(guide))
        status(body, f"{len(levels)} points" + "".join(f" · L{n} {levels.count(n)}" for n in bb.LEVELS)
               + (f" · {webs} web" if webs else ""), icon='BONE_DATA')
    shape = section(body, "digitools_bbone_shape", "Shape", icon='CURVE_BEZCIRCLE')
    if shape:
        if guide is not None:
            choice_row(shape, guide.digit_bbone, "shape")
        prop_group(shape, scene, [("digit_bbone_start", "Start From")])
        shape.operator(DIGITOOLS_OT_bbone_new.bl_idname, icon='ADD')
    if guide is None:
        return
    draw_add(body, context, guide)
    draw_points(body, context, guide)
    draw_bones(body, context, guide)
    s = guide.digit_bbone
    weights = section(body, "digitools_bbone_weights", "Weights", icon='GROUP_VERTEX', default_closed=True)
    if weights:
        prop_group(weights, s, ["mesh", "smooth"] + (["reach", "with_selected"] if s.smooth else []))
        hints(weights, ["Smooth: no creases or rips where parts touch"], context)
        weights.operator(DIGITOOLS_OT_bbone_weights.bl_idname, icon='MOD_VERTEX_WEIGHT')
    legend = section(body, "digitools_bbone_levels", "Control Levels", icon='INFO')
    if legend:
        for level, text in LEGEND:
            wrapped(legend, text, icon=LEVEL_ICONS[level - 1], context=context)
        wrapped(legend, WEB_HELP, icon='MOD_WIREFRAME', context=context)


classes = (DIGITOOLS_PG_bbone, DIGITOOLS_OT_bbone_new, DIGITOOLS_OT_bbone_add_points, DIGITOOLS_OT_bbone_add_web,
           DIGITOOLS_OT_bbone_level,
           DIGITOOLS_OT_bbone_subdivide, DIGITOOLS_OT_bbone_remove_point, DIGITOOLS_OT_bbone_build, DIGITOOLS_OT_bbone_edit,
           DIGITOOLS_OT_bbone_reset_pose, DIGITOOLS_OT_bbone_show, DIGITOOLS_OT_bbone_mirror, DIGITOOLS_OT_bbone_remove,
           DIGITOOLS_OT_bbone_weights)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_bbone = PointerProperty(type=DIGITOOLS_PG_bbone)
    bpy.types.Scene.digit_bbone_new_level = EnumProperty(
        name="New point level", update=level_picked, default='2',
        items=[('4', "Level 4", "New points are main, in charge"), ('3', "Level 3", "New points follow level 4"),
               ('2', "Level 2", "New points follow level 3 or 4"), ('1', "Level 1", "New points follow level 2, 3 or 4")],
        description="The level of the points you place. Until you pick one: 2, and 1 when inserted on the curve")
    bpy.types.Scene.digit_bbone_start = EnumProperty(name="Start From", items=START_ITEMS, default='EMPTY',
                                                     description="The shape Start New B-Bone Chain starts from")
    bpy.types.Scene.digit_bbone_guide = PointerProperty(type=bpy.types.Object, name="Points",
                                                        description="The points the B-Bone Chain Builder last used")


def unregister():
    del bpy.types.Scene.digit_bbone_guide
    del bpy.types.Scene.digit_bbone_new_level
    del bpy.types.Scene.digit_bbone_start
    del bpy.types.Object.digit_bbone
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
