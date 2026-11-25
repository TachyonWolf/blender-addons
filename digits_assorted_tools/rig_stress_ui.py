# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig Stress Pose Test card (Digit's Tools > Character Rigs). Browsing is the main way to use it: a pose dropdown and
back / next arrows (they wrap around) put the rig in that stress pose of rig_stress.py live and measure it right
then (only on the click); its problem areas show under it, each with a Show button that selects the problem
vertices in Edit Mode (mesh_review.show_hit, like the Oops Debugger's Checks). Done puts the pose, mode and
selection back exactly as they were when browsing started. Scan All Poses (a folded section) runs every pose and
lists the ones with problems, each row jumping to its pose. Everything is kept in memory (per rig: the pose index,
the kept pose, the last scan), never saved in the .blend; nothing runs in the background or on a redraw."""
from dataclasses import dataclass

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from . import rig_stress as bs, position_snapshot
from .bone_chain import rig_for_chain  # generated copy
from .mesh_review import Hit, show_hit  # generated copy
from .save_pose import read_exact_pose
from .ui_cards import friendly_name, hints, section, shorten, status  # generated copy

POSE_ITEMS = [(pose.name, pose.name, f"Put the rig in {pose.name} and measure it") for pose in bs.POSES]
HOW_IT_WORKS = ["Pick a pose or press an arrow to start",
                "Show selects a problem in Edit Mode",
                "Done puts your pose back exactly"]


@dataclass
class Landed:
    """The pose being shown and what measuring it found."""
    index: int
    posed: bs.Posed
    problems: list


@dataclass
class Browsing:
    """One rig being browsed: what Done puts back, the meshes' rest shapes, their weight rows, the pose shown."""
    pose: dict
    position: dict
    probes: list
    weights: list
    landed: Landed = None


SESSIONS = {}   # rig name -> Browsing (from the first pose until Done)
INDEX = {}      # rig name -> index of the last pose looked at (kept after Done)
REPORTS = {}    # rig name -> rig_stress.Report of its last Scan All Poses


def target_rig(context):
    return rig_for_chain(context)


def start_browsing(context, rig):
    """Keep the user's exact pose and position, read the meshes' rest shapes once."""
    if rig.name not in SESSIONS:
        context.view_layer.update()
        probes = bs.rest_probes(rig, bs.deformed_meshes(context, rig))
        SESSIONS[rig.name] = Browsing(read_exact_pose(rig), position_snapshot.capture(context), probes, bs.weight_rows(probes))
    return SESSIONS[rig.name]


def land(context, rig, index):
    """Put the rig in pose `index` (wraps around) and measure it."""
    session = start_browsing(context, rig)
    if context.mode not in {'OBJECT', 'POSE'}:
        bpy.ops.object.mode_set(mode='OBJECT')       # back from a Show in Edit Mode
    index %= len(bs.POSES)
    pose = bs.POSES[index]
    posed = bs.apply_stress_pose(rig, pose)
    problems = bs.measure_pose(session.probes, pose.name) if posed.moved else []
    session.landed = Landed(index, posed, problems)
    INDEX[rig.name] = index


def finish(context, rig_name):
    """Done: put back the pose, mode and selection kept when browsing started."""
    session = SESSIONS.pop(rig_name, None)
    rig = bpy.data.objects.get(rig_name)
    if session is None or rig is None:
        return False
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bs.put_back_pose(rig, session.pose)
    position_snapshot.put_back(context, session.position)
    return True


def find_rows(session, pose, mesh, area):
    """The problem verts of a row of the pose shown ('' pose: a weight row), or None."""
    if pose:
        landed = session.landed
        if landed is None or bs.POSES[landed.index].name != pose:
            return None
        return next((p.verts for p in landed.problems if (p.mesh, p.area) == (mesh, area)), None)
    return next((verts for name, label, verts in session.weights if (name, label) == (mesh, area)), None)


def select_only(context, ob):
    for other in context.view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob


def rig_poll(cls, context):
    if target_rig(context) is None:
        cls.poll_message_set("Select a character rig, or a mesh it deforms")
        return False
    return True


class DIGITOOLS_OT_rig_stress_step(bpy.types.Operator):
    """Next or previous stress pose (wraps around): the rig shows it and it is measured. Done puts your pose back"""
    bl_idname = "digits_assorted_tools.rig_stress_step"
    bl_label = "Next Stress Pose"
    bl_options = {'REGISTER', 'UNDO'}

    direction: IntProperty(default=1, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return rig_poll(cls, context)

    @classmethod
    def description(cls, context, properties):
        return "Previous stress pose (wraps around)" if properties.direction < 0 else "Next stress pose (wraps around)"

    def execute(self, context):
        rig = target_rig(context)
        current = INDEX.get(rig.name)
        if current is None:                   # first press: the first pose (next) or the last one (previous)
            current = -1 if self.direction > 0 else 0
        land(context, rig, current + self.direction)
        return {'FINISHED'}


class DIGITOOLS_OT_rig_stress_go(bpy.types.Operator):
    """Put the rig in this stress pose and measure it. Done puts your pose back"""
    bl_idname = "digits_assorted_tools.rig_stress_go"
    bl_label = "Go to Stress Pose"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "pose"

    pose: EnumProperty(items=POSE_ITEMS, name="Pose")

    @classmethod
    def poll(cls, context):
        return rig_poll(cls, context)

    def execute(self, context):
        land(context, target_rig(context), next(i for i, p in enumerate(bs.POSES) if p.name == self.pose))
        return {'FINISHED'}


class DIGITOOLS_OT_rig_stress_done(bpy.types.Operator):
    """Put your pose, mode and selection back exactly as they were before browsing"""
    bl_idname = "digits_assorted_tools.rig_stress_done"
    bl_label = "Done"
    bl_options = {'REGISTER', 'UNDO'}

    rig: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        if not finish(context, self.rig):
            self.report({'WARNING'}, "Nothing to put back")
            return {'CANCELLED'}
        return {'FINISHED'}


class DIGITOOLS_OT_rig_stress_run(bpy.types.Operator):
    """Run every stress pose and list the ones with collapsed, flipped or over-stretched areas.
    The pose shown comes back after; the rig and weights are never changed"""
    bl_idname = "digits_assorted_tools.rig_stress_run"
    bl_label = "Scan All Poses"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not rig_poll(cls, context):
            return False
        if context.mode not in {'OBJECT', 'POSE'} and target_rig(context).name not in SESSIONS:
            cls.poll_message_set("Go to Object or Pose Mode first")
            return False
        return True

    def execute(self, context):
        rig = target_rig(context)
        if context.mode not in {'OBJECT', 'POSE'}:
            bpy.ops.object.mode_set(mode='OBJECT')
        wm = context.window_manager
        wm.progress_begin(0, len(bs.POSES))
        try:
            report = bs.run(context, rig, progress=lambda done, total: wm.progress_update(done))
        finally:
            wm.progress_end()
        REPORTS[rig.name] = report
        self.report({'INFO'}, f"{len({p.pose for p in report.problems})} poses with problems, {report.seconds:.1f} s")
        return {'FINISHED'}


class DIGITOOLS_OT_rig_stress_show(bpy.types.Operator):
    """Select this problem's vertices in Edit Mode on the pose shown (Done puts your pose back)"""
    bl_idname = "digits_assorted_tools.rig_stress_show"
    bl_label = "Show"
    bl_options = {'REGISTER', 'UNDO'}

    rig: StringProperty(options={'HIDDEN'})
    pose: StringProperty(options={'HIDDEN'})     # '' = a weight row
    mesh: StringProperty(options={'HIDDEN'})
    area: StringProperty(options={'HIDDEN'})     # body area, or the weight problem's label

    def execute(self, context):
        session, mesh = SESSIONS.get(self.rig), bpy.data.objects.get(self.mesh)
        verts = find_rows(session, self.pose, self.mesh, self.area) if session else None
        if mesh is None or verts is None or (len(verts) and verts.max() >= len(mesh.data.vertices)):
            self.report({'WARNING'}, "Nothing to show: pick the pose again")
            return {'CANCELLED'}
        if not mesh.visible_get():
            self.report({'WARNING'}, f"{mesh.name} is hidden")
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        select_only(context, mesh)
        show_hit(context, mesh, Hit(self.area, verts=verts))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def draw_grey(layout, text):
    grey = layout.column()
    grey.active = False
    grey.label(text=shorten(text))


def draw_show_rows(layout, rig_name, pose, rows):
    """Rows (title, mesh, area, detail): a label and a Show button, the detail grey under it."""
    for title, mesh, area, detail in rows:
        row = layout.row(align=True)
        row.label(text=shorten(title, 28), icon='MESH_DATA' if pose else 'GROUP_VERTEX')
        op = row.operator(DIGITOOLS_OT_rig_stress_show.bl_idname, text="Show", icon='EDITMODE_HLT')
        op.rig, op.pose, op.mesh, op.area = rig_name, pose, mesh, area
        draw_grey(layout, detail)


def draw_browser(layout, rig):
    """Back arrow, pose dropdown, next arrow."""
    index = INDEX.get(rig.name)
    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator(DIGITOOLS_OT_rig_stress_step.bl_idname, text="", icon='TRIA_LEFT').direction = -1
    label = f"{index + 1}/{len(bs.POSES)} {bs.POSES[index].name}" if index is not None else "Pick a Pose"
    row.operator_menu_enum(DIGITOOLS_OT_rig_stress_go.bl_idname, "pose", text=shorten(label, 24))
    row.operator(DIGITOOLS_OT_rig_stress_step.bl_idname, text="", icon='TRIA_RIGHT').direction = 1


def draw_landed(layout, rig, session):
    """Done, then what the pose shown has: its problem areas with Show, the meshes' weight rows."""
    row = layout.row(align=True)
    row.alert = True
    row.scale_y = 1.3
    row.operator(DIGITOOLS_OT_rig_stress_done.bl_idname, text="Done: Put My Pose Back", icon='LOOP_BACK').rig = rig.name
    landed = session.landed
    if landed is None:
        return
    if not landed.posed.moved:
        draw_grey(layout, "This rig has no bones for this pose")
        return
    if landed.posed.fk_limbs:
        draw_grey(layout, "No IK, posed in FK: " + ", ".join(landed.posed.fk_limbs))
    if landed.problems:
        status(layout, f"{len(landed.problems)} problem areas", icon='ERROR')
    else:
        status(layout, "No problems in this pose", icon='CHECKMARK')
    several_meshes = len({p.mesh for p in landed.problems}) > 1
    draw_show_rows(layout, rig.name, bs.POSES[landed.index].name,
                   [(f"{friendly_name(p.mesh)} · {p.area}" if several_meshes else p.area, p.mesh, p.area, p.detail())
                    for p in landed.problems])
    body = section(layout, "rigstress_weights", "Weights", default_closed=True, right=f"{len(session.weights)} found")
    if body:
        if not session.weights:
            draw_grey(body, "Weights look clean")
        draw_show_rows(body, rig.name, "", [(f"{friendly_name(mesh)} · {label}", mesh, label, f"{len(verts)} verts")
                                            for mesh, label, verts in session.weights])


def draw_scan(layout, rig):
    """Scan All Poses: the poses with problems, each a button that goes to it."""
    report = REPORTS.get(rig.name)
    body = section(layout, "rigstress_scan", "Scan All Poses", default_closed=True,
                   right=f"{len({p.pose for p in report.problems})} with problems" if report else None)
    if not body:
        return
    body.operator(DIGITOOLS_OT_rig_stress_run.bl_idname, text="Rescan" if report else "Scan All Poses", icon='FILE_REFRESH')
    if report is None:
        return
    col = body.column(align=True)
    for pose in bs.POSES:
        count = sum(1 for p in report.problems if p.pose == pose.name)
        if count:
            row = col.row(align=True)
            row.operator(DIGITOOLS_OT_rig_stress_go.bl_idname, text=pose.name, icon='POSE_HLT').pose = pose.name
            row.label(text=f"{count} areas")
    clean = [p for p in bs.POSES if p.name not in report.skipped and not any(q.pose == p.name for q in report.problems)]
    draw_grey(body, f"Clean: {len(clean)} poses, {report.seconds:.1f} s")
    if report.skipped:
        draw_grey(body, f"No bones for: {len(report.skipped)} poses")


def draw_card(layout, context):
    rig = target_rig(context)
    status(layout, friendly_name(rig.name) if rig else "Select a character rig", icon='ARMATURE_DATA')
    for rig_name in [name for name in SESSIONS if rig is None or name != rig.name]:   # another rig still posed
        row = layout.row(align=True)
        row.alert = True
        row.operator(DIGITOOLS_OT_rig_stress_done.bl_idname, text=shorten(f"Done: {rig_name}", 28), icon='LOOP_BACK').rig = rig_name
    if rig is None:
        return
    draw_browser(layout, rig)
    session = SESSIONS.get(rig.name)
    if session:
        draw_landed(layout, rig, session)
    else:
        hints(layout, HOW_IT_WORKS, context)
    draw_scan(layout, rig)


classes = (DIGITOOLS_OT_rig_stress_step, DIGITOOLS_OT_rig_stress_go, DIGITOOLS_OT_rig_stress_done,
           DIGITOOLS_OT_rig_stress_run, DIGITOOLS_OT_rig_stress_show)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    REPORTS.clear()
    SESSIONS.clear()
    INDEX.clear()
