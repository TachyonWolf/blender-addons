# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig Check (Bone Workshop): things a rig's bones may still need. Each one is a scene_checks.Check in the area
Rig Setup, kept in this module's own list (CHECKS here, not the Oops Debugger's registry) and drawn with the
Oops Debugger's rows. The scan runs only on its button and is kept in this module's own cache until the next
scan or a fix; nothing runs in the background."""
import bpy

from . import bone_collections as bc, oops_ui, rig_names as rn, scene_checks as sc  # generated copies
from . import bone_workshop as bw, bone_workshop_spec as spec

AREA = sc.RIG_SETUP
CHECKS = sc.OWN_CHECKS   # this tool's checks (not in the Oops registry)
CACHE = sc.ScanCache()
WIDGET_PREFIXES = ('WGT-', 'Selection')


def own(check):
    CHECKS.append(check)
    return check


def shown(bone):
    return not bone.collections or any(c.is_visible for c in bone.collections)


# ---------------------------------------------------------------- the checks
def no_shape(scope):
    return [(rig, pb.name) for rig in scope.rigs for pb in rig.pose.bones
            if pb.custom_shape is None and not rn.is_helper(pb.name) and not pb.hide and shown(pb.bone)]


def find_no_shape(scope):
    items = no_shape(scope)
    return sc.found(items, [n for _r, n in items], rows=sc.bone_rows(
        (rig, n, f"Suggested: {spec.PRESET_BY_ID[spec.suggest(n) or 'fk'].label}", "") for rig, n in items),
        bones=[(r.name, n) for r, n in items])


def clear_no_shape(scope):
    """Each bone gets the look of the preset its name suggests (shape, size, colour; collections stay)."""
    items = no_shape(scope)
    for rig, name in items:
        look = bw.preset_look(spec.suggest(name) or 'fk')
        pb = rig.pose.bones[name]
        bw.set_shape([pb], look[0])
        pb.custom_shape_scale_xyz = (look[1],) * 3
        bw.set_colour(pb, look[2])
    return len(items)


def off_standard(scope):
    return [(rig, n, new) for rig in scope.rigs for n, new in bw.standard_table(rig, rig.data.bones.keys()).items()]


def find_off_standard(scope):
    items = off_standard(scope)
    return sc.found(items, [n for _r, n, _new in items], rows=sc.bone_rows((rig, n, f"→ {new}", "") for rig, n, new in items),
                    bones=[(r.name, n) for r, n, _new in items])


def clear_off_standard(scope):
    done = 0
    for rig in scope.rigs:
        count, clashes = bw.rename(rig, bw.standard_table(rig, rig.data.bones.keys()))
        done += count
        scope.notes += clashes
    return done


def def_in_controls(scope):
    return [(rig, b.name) for rig in scope.rigs for b in rig.data.bones
            if rn.split_role(b.name)[0] == 'DEF' and any(not bc.is_rigging(c) for c in b.collections)]


def find_def_in_controls(scope):
    items = def_in_controls(scope)
    return sc.found(items, [n for _r, n in items], rows=sc.bone_rows((rig, n, "in a control collection", "") for rig, n in items),
                    bones=[(r.name, n) for r, n in items])


def clear_def_in_controls(scope):
    items = def_in_controls(scope)
    for rig, name in items:
        bc.move_to(rig, name, None, True)
    return len(items)


def side_differences(rig, pb):
    """What differs between a left bone and its right bone, in words ([] when they match)."""
    other = bw.mirror_of(pb)
    if other is None:
        return ["no right bone"]
    out = []
    if bw.widget_name(pb) != bw.widget_name(other):
        out.append("shape")
    if bw.shown_colour(pb)[0] != bw.shown_colour(other)[0]:
        out.append("colour")
    home, other_home = bw.home_of(pb), bw.home_of(other)
    if home and other_home != rn.flip(home):
        out.append("collection")
    return out


def lr_mismatch(scope):
    return [(rig, pb.name, side_differences(rig, pb)) for rig in scope.rigs for pb in rig.pose.bones
            if rn.side_of(pb.name) == 'L' and side_differences(rig, pb)]


def find_lr_mismatch(scope):
    items = lr_mismatch(scope)
    return sc.found(items, [n for _r, n, _d in items], rows=sc.bone_rows((rig, n, ", ".join(d), "") for rig, n, d in items),
                    bones=[(r.name, n) for r, n, _d in items])


def clear_lr_mismatch(scope):
    """The left bone's look, settings and collection onto the right one (the tools write the left side first)."""
    done = 0
    for rig, name, _d in lr_mismatch(scope):
        pb, other = rig.pose.bones[name], bw.mirror_of(rig.pose.bones[name])
        if other is None:
            scope.notes.append(f"{name}: no right bone to mirror to")
            continue
        bw.copy_look(pb, other)
        bw.copy_settings(pb, other)
        done += 1
    return done


def unused_widgets(_scope=None):
    """Widget objects (WGT-*, Selection*) of this file that no bone of any armature uses and no collection holds."""
    used = {pb.custom_shape.name for ob in bpy.data.objects if ob.type == 'ARMATURE' and ob.pose
            for pb in ob.pose.bones if pb.custom_shape}
    return [ob.name for ob in bpy.data.objects if ob.name.startswith(WIDGET_PREFIXES) and ob.library is None
            and ob.name not in used and not ob.users_collection]


def find_unused_widgets(scope):
    names = unused_widgets(scope)
    return sc.found(names, names, rows=[(n, "used by no bone", "", "") for n in names])


def clear_unused_widgets(scope):
    names = unused_widgets(scope)
    for name in names:
        ob = bpy.data.objects[name]
        mesh = ob.data
        bpy.data.objects.remove(ob)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return len(names)


own(sc.Check("rig_no_shape", AREA, "Controls With No Shape",
             "Gives each bone the shape, size and colour its name suggests (the Style Presets).",
             find_no_shape, clear_no_shape, "Add Shapes", risk=2,
             why="Without a shape a control is drawn as a plain bone: hard to see and click among the others.",
             keep="Fine for bones you never pose, or when you like plain bones."))
own(sc.Check("rig_off_standard", AREA, "Names Off the Standard",
             "Renames the bones to their standard names (docs/BONE_NAMES.md). Animation, constraints and vertex groups "
             "follow; names another bone already has are skipped.",
             find_off_standard, clear_off_standard, "Rename", risk=3, confirm=True,
             why="The tools find bones by their standard names. Off-standard names can make Upgrade Limbs, Rig Check "
                 "and mirroring miss them.",
             keep="Keep them when a game engine or another tool needs these exact names."))
own(sc.Check("rig_def_in_controls", AREA, "DEF Bones in Controls",
             "Moves the DEF- bones into Body or Face Deform only.",
             find_def_in_controls, clear_def_in_controls, "Move", risk=2,
             why="DEF- bones bend the mesh and are posed by the controls. In a control collection they get clicked "
                 "by mistake.",
             keep="Fine on a simple rig where you pose the deform bones yourself."))
own(sc.Check("rig_lr_mismatch", AREA, "Left / Right Differ",
             "Copies each left bone's shape, size, colour and settings onto its right bone.",
             find_lr_mismatch, clear_lr_mismatch, "Mirror", risk=2,
             why="A right bone that looks or acts unlike its left bone is often a missed step.",
             keep="Keep it when the sides differ on purpose (a scar, an eye patch, one-sided props)."))
own(sc.Check("rig_unused_widgets", AREA, "Unused Shape Meshes",
             "Removes shape objects (WGT-*, Selection*) no bone in the file uses.",
             find_unused_widgets, clear_unused_widgets, "Remove", risk=1,
             why="Left-over shapes make the file bigger and the lists longer.",
             keep="Keep them when you want to use them later."))


def by_id(check_id):
    return next(c for c in CHECKS if c.id == check_id)


# ---------------------------------------------------------------- scan and buttons
def results(context):
    """The last scan's findings for the active object's rig, or None before the first scan."""
    key = sc.active_of(context).name if sc.active_of(context) else ""
    return CACHE.value if CACHE.key == key else None


def scan(context):
    """Run every check now (a button), keep the findings in this module's cache."""
    scope = sc.scope_of(context)
    found = [(c, f) for c in CHECKS for f in [sc.run_check(c, scope)] if f is not None]
    CACHE.clear()
    CACHE.get(sc.active_of(context).name if sc.active_of(context) else "", lambda: found)
    return found


class DIGITOOLS_OT_bw_rig_check(bpy.types.Operator):
    """Check the rig's bones now: shapes, names, collections, left and right sides, unused shape meshes"""
    bl_idname = "digits_assorted_tools.bw_rig_check"
    bl_label = "Check Rig"

    @classmethod
    def poll(cls, context):
        return sc.active_of(context) is not None

    def execute(self, context):
        found = scan(context)
        self.report({'INFO'}, f"Rig Check: {len(found)} things to look at" if found else "Rig Check: all good")
        return {'FINISHED'}


class DIGITOOLS_OT_bw_rig_fix(oops_ui._CheckOperator, bpy.types.Operator):
    """Fix what this check found"""
    bl_idname = "digits_assorted_tools.bw_rig_fix"
    bl_label = "Fix"

    def invoke(self, context, event):
        check = by_id(self.check_id)
        if not (check.confirm or sc.needs_warning(check.risk)):
            return self.execute(context)
        finding = check.find(sc.scope_of(context))
        return context.window_manager.invoke_confirm(
            self, event, title=f"{check.button}?", confirm_text=check.button, icon='WARNING',
            message=oops_ui.clear_confirm_message(check, check.actions[0], finding.count if finding else 0))

    def execute(self, context):
        check = by_id(self.check_id)
        scope = sc.scope_of(context)
        count = check.actions[0].clear(scope)
        for note in scope.notes:
            self.report({'WARNING'}, note)
        scan(context)
        self.report({'INFO'}, f"{check.label}: fixed {count}")
        return {'FINISHED'}


classes = (DIGITOOLS_OT_bw_rig_check, DIGITOOLS_OT_bw_rig_fix)
