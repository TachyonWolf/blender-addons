# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/limb_rig.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rigify-style limb upgrades on our own character rigs, keeping each rig's controls (no generated rig):
IK stretch sliders, hand / foot parent switching, the data the IK/FK snap and parent buttons of the Rig
Switches card (Selected, rig_switches_ui) read, and the digitigrade hock rebuild.

A "table" says which bones are which (see guess_table for the format and for guessing it from a rig); the
Limbs card (limbs_ui) and Scripts/charfix/limb_upgrade.py (which keeps the table of the six known rigs) both
run upgrade(rig, table, ...). Safe to re-run. Defaults leave every pose as it was. This file is the ONE
source; sync_shared.py copies it into each add-on / script folder.
"""
import json
import math
import re
from contextlib import contextmanager

import bpy
from mathutils import Vector

try:                                     # inside the add-on package
    from . import bone_collections as BC, rig_names as rn
    from .face_rig_core import OVERSHOOT, finish_rig, guess_bones, slider_limits
    from .object_tools import set_mode  # also used as lr.set_mode
except ImportError:                      # Scripts/batch_tools copy
    import bone_collections as BC
    import rig_names as rn
    from face_rig_core import OVERSHOOT, finish_rig, guess_bones, slider_limits
    from object_tools import set_mode

MECH = 'Mechanism'
HELPER_UP = Vector((0, 0, 0.02))  # the small helper bones point up, this long
HOCK_BEND = (math.radians(5), math.radians(172))  # hock bend range, flat to folded
KEEP_OFF_HIP = 1.15  # ik2 target stays this much outside the virtual leg's folded length
PARENT_NAMES = ('Root', 'Pelvis', 'Chest', 'Head')  # what a control can follow, in IK_Parent order
HOCK_PARTS = dict(leg_ik2_1='LegIK2Seg1', leg_ik2_2='LegIK2Seg2', leg_ik3_1='LegIK3Seg1', leg_ik3_2='LegIK3Seg2',
                  leg_ik2_target='LegIK2Target', hip='Hip')    # the rebuilt hock's helpers (Mechanism)
TWIST_SHARE = 0.33       # share of the hand's roll the twist share bone (Forearm1) takes
TWIST_SEGMENTS = 4       # B-bones on the twist forearm only: on the upper arm or the legs they crumple tight folds
TWIST_NAME = 'Twist Share'       # the swing-twist Transformation constraint on the bone above the twist forearm
OLD_TWIST = 'Copy Rotation'      # older rigs: a Copy Rotation of the hand on the twist forearm itself


# ---------- small shared helpers ----------
def bone_path(bone):
    return f'pose.bones["{bone}"]'


def add_prop(pb, name, value, lo, hi, desc):
    pb[name] = value
    slider_limits(pb, name, lo, hi, value, desc, overshoot=1)


def add_driver(rig, path, index, expr, variables):
    """Scripted driver on rig, replacing one already there. variables maps name -> data path
    of a rig property, a (bone, bone) pair for the distance between two bones, or ('ROTATION_DIFF', bone, bone) for
    the angle between them (an elbow's bend, also under IK), or ('TRANSFORMS', bone, 'ROT_Z') for a bone's own local
    channel (rotations read as swing and twist about Y, so X / Z swing and Y twist stay apart)."""
    rig.driver_remove(path, -1 if index is None else index)
    fc = rig.driver_add(path, index) if index is not None else rig.driver_add(path)
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    drv = fc.driver
    drv.type = 'SCRIPTED'
    for name, dp in variables.items():
        v = drv.variables.new()
        v.name = name
        if isinstance(dp, tuple) and dp[0] == 'TRANSFORMS':
            v.type = 'TRANSFORMS'
            target = v.targets[0]
            target.id, target.bone_target, target.transform_type = rig, dp[1], dp[2]
            target.transform_space, target.rotation_mode = 'LOCAL_SPACE', 'SWING_TWIST_Y'
        elif isinstance(dp, tuple):
            v.type, bones = (dp[0], dp[1:]) if len(dp) == 3 else ('LOC_DIFF', dp)
            for target, bone in zip(v.targets, bones):
                target.id, target.bone_target = rig, bone
        else:
            v.type = 'SINGLE_PROP'
            v.targets[0].id_type = 'OBJECT'
            v.targets[0].id = rig
            v.targets[0].data_path = dp
    drv.expression = expr


def ik_chain(pb, con):
    """The pose bones an IK constraint moves, tip first."""
    out, x = [], pb
    n = con.chain_count or 999
    while x and len(out) < n:
        out.append(x)
        x = x.parent
    return out


def tip_iks(rig):
    """[(pose bone, IK constraint)] of the rig's tip IKs: an IK whose target is a control bone of the same armature
    (a part armature's tail / ponytail IK; rig_parts shows them, part_chains.add_tip_switch makes them switchable)."""
    bones = rig.pose.bones
    return [(pb, con) for pb in bones for con in pb.constraints
            if con.type == 'IK' and con.target == rig and con.subtarget in bones and con.subtarget != pb.name]


def chain_err(rig, pb, con):
    """Summed angle (rad) between rest and evaluated pose of an IK chain; handles 2pi wrap."""
    bpy.context.view_layer.update()
    err = 0.0
    for x in ik_chain(pb, con):
        a = rig.data.bones[x.name].matrix_local.to_quaternion().rotation_difference(x.matrix.to_quaternion()).angle
        err += min(a, 2 * math.pi - a)
    return err


@contextmanager
def rest_pose(rigs):
    """Temporarily clear pose transforms (and force POSE position) on rigs."""
    saved = []
    for r in rigs:
        saved.append((r, r.data.pose_position, [(pb, pb.location.copy(), pb.rotation_quaternion.copy(),
                                                  pb.rotation_euler.copy(), pb.rotation_axis_angle[:], pb.scale.copy())
                                                 for pb in r.pose.bones]))
        r.data.pose_position = 'POSE'
        for pb in r.pose.bones:
            pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0); pb.rotation_axis_angle = (0, 0, 1, 0); pb.scale = (1, 1, 1)
    try:
        yield
    finally:
        for r, pp, bones in saved:
            r.data.pose_position = pp
            for pb, l, q, e, aa, s in bones:
                pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.rotation_axis_angle, pb.scale = l, q, e, aa, s


# ---------- guessing the table ----------
TIP_WORD = re.compile(r'(hand|foot|paw|hoof)$')


def is_leg(names):
    return any(BC.LEG_WORD.search(rn.plain(n)) for n in names)


def find_tip(bone):
    """(tip, heel): the hand / foot bone below the IK bone, and the bone between them (a digitigrade
    leg's lower shin) or None."""
    for kid in bone.children:
        if TIP_WORD.search(rn.plain(kid.name)):
            return kid, None
    for kid in bone.children:
        for grandkid in kid.children:
            if TIP_WORD.search(rn.plain(grandkid.name)):
                return grandkid, kid
    return None, None


def same_side(a, b):
    return rn.side_of(a) == rn.side_of(b)


def find_control(bones, tip, con):
    """The IK control: the bone called like the tip + IK on the tip's side, else what the IK targets."""
    tip_word = rn.plain(tip.name)
    wanted = {tip_word + word for word in ('ik', 'ctrl', 'control')} | {'ik' + tip_word}
    named = [b.name for b in bones if not rn.is_helper(b.name) and rn.plain(b.name) in wanted and same_side(b.name, tip.name)]
    if named:
        return min(named, key=len)
    return con.subtarget if con.subtarget and not rn.is_helper(con.subtarget) else ''


def find_hock(bones, tip):
    """(hock control, hock target helper) on the tip's side, '' when missing."""
    hocks = [b.name for b in bones if 'hock' in rn.plain(b.name) and same_side(b.name, tip.name)]
    control = [n for n in hocks if not rn.is_helper(n) and 'ik' in rn.plain(n) and 'target' not in rn.plain(n)]
    target = [n for n in hocks if rn.is_helper(n) and 'target' in rn.plain(n)]
    return (min(control, key=len) if control else ''), (min(target, key=len) if target else '')


def guess_limb(rig, pb, con):
    """A table entry for the IK on pb (a limb with a pole and a hand / foot below it), or None."""
    bones = rig.data.bones
    tip, heel = find_tip(bones[pb.name])
    if tip is None:
        return None
    ctrl = find_control(bones, tip, con)
    if not ctrl:
        return None
    entry = dict(ctrl=ctrl, ik=pb.name, tip=tip.name)
    target = rn.find(bones.keys(), rn.helper(ctrl, 'Target'))
    if target:
        entry['target'] = target
    if heel:
        entry['heel'] = heel.name
        hock, hock_target = find_hock(bones, tip)
        if hock and hock_target:
            entry.update(hock=hock, hock_target=hock_target)
    if find_twist_share(rig, pb.name, (tip.name, ctrl)):
        entry['twist'] = pb.name
    return entry


def find_twist_share(rig, forearm, sources):
    """(bone, constraint) sharing the hand's roll for the twist forearm, or None: a Twist Share on the bone above it
    (the Full Rig, Digit), else an old Copy Rotation on the forearm itself. `sources`: the bones it may read."""
    pose = rig.pose.bones
    parent = rig.data.bones[forearm].parent
    share = pose[parent.name].constraints.get(TWIST_NAME) if parent else None
    if share and share.type == 'TRANSFORM' and share.subtarget in sources:
        return pose[parent.name], share
    old = pose[forearm].constraints.get(OLD_TWIST)
    if old and old.type == 'COPY_ROTATION' and old.subtarget in sources:
        return pose[forearm], old
    return None


def above(rig, chain_root):
    """The bones above a limb's chain, nearest first, that are not helpers or sided."""
    return [b.name for b in rig.data.bones[chain_root].parent_recursive
            if not rn.is_helper(b.name) and not rn.has_side(b.name)]


def first_named(rig, pattern):
    """First plain, unsided bone whose plain name matches pattern, or ''."""
    return next((b.name for b in rig.data.bones if re.fullmatch(pattern, rn.plain(b.name))
                 and not rn.is_helper(b.name) and not rn.has_side(b.name)), '')


def guess_parents(rig, found):
    """Root, Pelvis, Chest, Head: from what the legs and arms hang from, else by name. `found` holds the
    entries with their `leg` flag and `up` (bones above the chain)."""
    legs = [e for e in found if e['leg']]
    arms = [e for e in found if not e['leg']]
    root = found[0]['up'][-1] if found else rn.find(rig.data.bones.keys(), rn.ROOT) or ''
    pelvis = next((n for n in legs[0]['up'] if n != root), '') if legs else ''
    chest = next((n for n in arms[0]['up'] if n != root and 'shoulder' not in rn.plain(n)), '') if arms else ''
    return dict(Root=root,
                Pelvis=pelvis or first_named(rig, r'(torso)?(pelvis|hips?)'),
                Chest=chest or first_named(rig, r'(torso)?chest\d?|torso\d'),
                Head=guess_bones(rig)['head'])


def guess_table(rig):
    """The table for a rig, from bone names and chain structure. Format (the same as RIGS in
    Scripts/charfix/limb_upgrade.py, written for the left side, the right side is flipped):
      parents:  Root / Pelvis / Chest / Head -> bone name ('' = not found)
      hock_mch: True when the hock is rebuilt with helper bones (None: no digitigrade leg with a hock)
      limbs:    entries with ctrl = IK control, ik = bone with the IK constraint, tip = hand / foot bone,
                and where there are any: target (end of the foot roll chain), heel (bone between ik and tip),
                hock (hock control), hock_target, twist (the forearm whose B-bones carry the hand's roll; its
                twist share is a Twist Share on the bone above, or on older rigs a Copy Rotation on itself)."""
    found = []
    for pb in (rig.pose.bones if rig.pose else []):
        if rn.is_helper(pb.name) or rn.side_of(pb.name) == 'R':
            continue
        con = next((c for c in pb.constraints if c.type == 'IK' and c.pole_subtarget), None)
        entry = guess_limb(rig, pb, con) if con else None
        if entry:
            chain = [x.name for x in reversed(ik_chain(pb, con))]
            found.append(dict(entry, leg=is_leg(chain + [entry['tip']]), up=above(rig, chain[0])))
    parents = guess_parents(rig, found)
    limbs = [{k: v for k, v in e.items() if k not in ('leg', 'up')} for e in sorted(found, key=lambda e: e['leg'])]
    return dict(parents=parents, hock_mch=True if any(e.get('hock') for e in found) else None, limbs=limbs)


def existing_or_new(rig, name):
    """The rig's bone called `name` in any style, else `name` (the standard name, for a bone still to be made)."""
    return rn.find(rig.pose.bones.keys(), name) or name


def resolve_limb(rig, entry, flip, hock_mch):
    """One side's limb: names from the table plus what the IK constraint knows. None if bones are missing."""
    name = rn.flip if flip else str
    limb = {k: name(v) for k, v in entry.items() if v}
    if not all(k in limb for k in ('ctrl', 'ik', 'tip')) or not all(v in rig.pose.bones for v in limb.values()):
        return None
    pb = rig.pose.bones[limb['ik']]
    con = next((c for c in pb.constraints if c.type == 'IK'), None)
    if con is None or not con.pole_subtarget or 'IK_FK' not in rig.pose.bones[limb['ctrl']]:
        return None
    limb.setdefault('target', limb['ctrl'])
    limb.update(con=con.name, pole=con.pole_subtarget, chain=[x.name for x in reversed(ik_chain(pb, con))])
    limb['fk'] = limb['chain'] + [b for b in (limb.get('heel'), limb['tip']) if b]
    limb['ik_target'] = con.subtarget
    limb['parent_bone'] = existing_or_new(rig, rn.helper(limb['ctrl'], 'Parent'))
    limb['stretch_bone'] = existing_or_new(rig, rn.helper(limb['ctrl'], 'Stretch'))
    if hock_mch and limb.get('hock') and limb.get('hock_target') and limb.get('heel'):
        side = rn.side_of(limb['ctrl'])
        limb['hock_bones'] = {key: existing_or_new(rig, rn.build(part, side, role='MCH')) for key, part in HOCK_PARTS.items()}
    return limb


# ---------- edit mode ----------
def new_bone(rig, name, head, tail, parent, connect=False, hinge=None):
    """A Mechanism helper bone; hinge = the direction its local X must point (its IK bend axis)."""
    b = rig.data.edit_bones.new(name)
    b.head, b.tail, b.parent, b.use_connect, b.use_deform = head, tail, parent, connect, False
    if hinge:
        b.align_roll(hinge.cross(tail - head))
    return b


def add_hock_bones(rig, limb):
    """Virtual leg as in Rigify's rear_paw: ik2 is a two-bone leg (thigh extended by the heel's
    length along it), ik3 is the real shin + heel hanging off ik2's thigh. The hock control rides ik3.
    The thigh runs from the top of the chain to the shin, however many bones are between."""
    eb = rig.data.edit_bones
    names = limb['hock_bones']
    thigh, shin = eb[limb['chain'][0]], eb[limb['chain'][-1]]
    heel, foot = eb[limb['heel']], eb[limb['target']].head.copy()
    hinge = (shin.head - thigh.head).cross(foot - thigh.head).normalized()
    along_thigh = (shin.head - thigh.head).normalized()
    bend = shin.head + along_thigh * heel.vector.dot(along_thigh)
    ik2_1 = new_bone(rig, names['leg_ik2_1'], thigh.head, bend, thigh.parent, hinge=hinge)
    new_bone(rig, names['leg_ik2_2'], bend, foot, ik2_1, connect=True, hinge=hinge)
    ik3_1 = new_bone(rig, names['leg_ik3_1'], shin.head, shin.tail, ik2_1, hinge=hinge)
    ik3_2 = new_bone(rig, names['leg_ik3_2'], heel.head, foot, ik3_1, connect=True, hinge=hinge)
    new_bone(rig, names['leg_ik2_target'], foot, foot + HELPER_UP, eb[limb['target']])
    new_bone(rig, names['hip'], thigh.head, thigh.head + HELPER_UP, thigh.parent)
    eb[limb['hock']].parent = ik3_2


def add_feature_bones(rig, limb, stretch=True, parent_switch=True):
    eb = rig.data.edit_bones
    if stretch and limb['stretch_bone'] not in eb:
        top = eb[limb['chain'][0]]
        new_bone(rig, limb['stretch_bone'], top.head, eb[limb['ik_target']].head, top.parent)
    if parent_switch and limb['parent_bone'] not in eb:
        ctrl = eb[limb['ctrl']]
        new_bone(rig, limb['parent_bone'], ctrl.head, ctrl.tail, None).roll = ctrl.roll
        ctrl.parent = eb[limb['parent_bone']]


def edit_limbs(rig, limbs, add_bones):
    """Runs add_bones(rig, limb) per limb in edit mode and puts the new bones in Mechanism."""
    mirror, rig.data.use_mirror_x = rig.data.use_mirror_x, False  # edits must not touch the other side
    set_mode(rig, 'EDIT')
    before = set(rig.data.edit_bones.keys())
    for limb in limbs:
        add_bones(rig, limb)
    added = set(rig.data.edit_bones.keys()) - before
    set_mode(rig, 'POSE')
    rig.data.use_mirror_x = mirror
    for name in added:
        BC.place_bone(rig, name, MECH, False)
    return len(added)


# ---------- pose mode ----------
def get_constraint(pb, name, kind):
    return pb.constraints.get(name) or _new_constraint(pb, name, kind)


def _new_constraint(pb, name, kind):
    c = pb.constraints.new(kind)
    c.name = name
    return c


def set_limit(rig, pb, name, target, distance, mode):
    c = get_constraint(pb, name, 'LIMIT_DISTANCE')
    c.target, c.subtarget, c.distance, c.limit_mode = rig, target, distance, mode
    c.use_transform_limit = False  # on: pops the bone on G once the foot has moved
    return c


def set_hinge_ik(rig, pb, target, pole=None):
    c = get_constraint(pb, 'IK', 'IK')
    c.target, c.subtarget, c.chain_count, c.use_stretch, c.iterations = rig, target, 2, False, 500
    if pole:
        c.pole_target, c.pole_subtarget = rig, pole
    return c


def full_reach(rig, limb):
    """The limb's length when straight; a bone with every IK axis locked stays rigid with the one above."""
    pose, bones = rig.pose.bones, rig.data.bones
    joints = [b for b in limb['chain'] if not (pose[b].lock_ik_x and pose[b].lock_ik_y and pose[b].lock_ik_z)]
    points = [bones[b].head_local for b in joints] + [bones[limb['chain'][-1]].tail_local]
    return sum((b - a).length for a, b in zip(points, points[1:]))


def rest_bend(rig, upper, lower):
    """Signed bend at a joint, around the lower bone's local X, at rest."""
    y1, m = rig.data.bones[upper].matrix_local.col[1].to_3d(), rig.data.bones[lower].matrix_local
    y2, x2 = m.col[1].to_3d(), m.col[0].to_3d()
    return math.atan2(y1.cross(y2).dot(x2), y1.dot(y2))


def fit_pole_angle(rig, pb, con, angles=(math.pi / 2, -math.pi / 2)):
    """The pole angle that leaves the chain at rest: our helper bones' X is the hinge, so a quarter turn (a chain whose
    X axis is its hinge needs one of the four quarter turns: pass them as `angles`)."""
    errors = {}
    for angle in angles:
        con.pole_angle = angle
        errors[angle] = chain_err(rig, pb, con)
    con.pole_angle = min(errors, key=errors.get)


def rig_hock(rig, limb):
    """Constraints of a rebuilt hock. Limits sit on MCH bones, never on the control."""
    pose, bones = rig.pose.bones, rig.data.bones
    names = limb['hock_bones']
    ik2_1, ik2_2, ik3_1, ik3_2 = (names[k] for k in ('leg_ik2_1', 'leg_ik2_2', 'leg_ik3_1', 'leg_ik3_2'))
    for name in (ik2_2, ik3_1, ik3_2):
        pose[name].lock_ik_y = pose[name].lock_ik_z = True
    sign = 1 if rest_bend(rig, ik3_1, ik3_2) > 0 else -1
    low, high = sorted(sign * a - rest_bend(rig, ik3_1, ik3_2) for a in HOCK_BEND)
    pose[ik3_2].use_ik_limit_x = True
    pose[ik3_2].ik_min_x, pose[ik3_2].ik_max_x = low, high
    ik2 = set_hinge_ik(rig, pose[ik2_2], names['leg_ik2_target'], limb['pole'])
    set_hinge_ik(rig, pose[ik3_2], limb['target'])
    with rest_pose([rig]):
        fit_pole_angle(rig, pose[ik2_2], ik2)
    hock = pose[limb['hock']]
    hock.lock_rotation = (True, True, True)
    old = hock.constraints.get('Stay On Ball')
    if old:
        hock.constraints.remove(old)
    target, hip = pose[limb['hock_target']], names['hip']
    heel_length = (bones[limb['hock']].head_local - bones[limb['target']].head_local).length
    set_limit(rig, target, 'Stay On Ball', limb['target'], heel_length, 'LIMITDIST_ONSURFACE')
    set_limit(rig, target, 'Stay In Reach', hip, full_reach(rig, limb), 'LIMITDIST_INSIDE')
    fold = (bones[ik2_1].length - bones[ik2_2].length) * KEEP_OFF_HIP
    set_limit(rig, pose[names['leg_ik2_target']], 'Keep Off Hip', hip, abs(fold), 'LIMITDIST_OUTSIDE')


def open_hinge_for_stretch(rig, upper, lower, sliders):
    """A chain bone's IK limit may stop it short of straight, which a stretched limb needs."""
    pb = rig.pose.bones[lower]
    if not pb.use_ik_limit_x:
        return
    straight = -rest_bend(rig, upper, lower)
    for attr, limit, past in (('ik_min_x', pb.ik_min_x, straight < pb.ik_min_x), ('ik_max_x', pb.ik_max_x, straight > pb.ik_max_x)):
        if past:
            add_driver(rig, f'{bone_path(lower)}.{attr}', None, f'{straight:.5f} if s > 0 else {limit:.5f}', sliders)


def rig_stretch(rig, limb, master):
    """IK_Stretch slider: starts at 1 (the feature is on), 0 = as before. Not the IK's own stretch: any
    ik_stretch above 0 shrinks a limb in reach and evens out badly, and a driver on it that reads bone positions is a dependency
    cycle (all IK shares one init step). Instead the chain really gets longer before the IK solves:
    a Stretch To helper measures limb length against the target, the chain's top bone copies that
    Y scale and the bones below take it with Aligned inherit. In reach the ratio is 1, so nothing
    changes. The bone after the chain keeps its size."""
    pose, bones = rig.pose.bones, rig.data.bones
    ctrl = pose[limb['ctrl']]
    if 'IK_Stretch' not in ctrl:
        add_prop(ctrl, 'IK_Stretch', 1.0, 0.0, 1.0, '1 = the limb stretches to reach the control, 0 = it stops at full length')
    sliders = {'s': f'{bone_path(limb["ctrl"])}["IK_Stretch"]', 'ik': f'{bone_path(limb["ctrl"])}["IK_FK"]'}
    helper = pose[limb['stretch_bone']]
    measure = get_constraint(helper, 'Stretch To Target', 'STRETCH_TO')
    measure.target, measure.subtarget, measure.volume = rig, limb['ik_target'], 'NO_VOLUME'
    measure.rest_length = full_reach(rig, limb)
    at_least_one = get_constraint(helper, 'Only Longer', 'LIMIT_SCALE')
    at_least_one.use_min_y, at_least_one.min_y, at_least_one.owner_space = True, 1.0, 'LOCAL'
    top = pose[limb['chain'][0]]
    scale = get_constraint(top, 'Stretch', 'COPY_SCALE')
    scale.target, scale.subtarget, scale.use_x, scale.use_z = rig, limb['stretch_bone'], False, False
    scale.target_space = scale.owner_space = 'LOCAL'
    for bone in limb['chain'][1:]:
        bones[bone].inherit_scale = 'ALIGNED'
    for upper, lower in zip(limb['chain'], limb['chain'][1:]):
        open_hinge_for_stretch(rig, upper, lower, sliders)
    reach_limit = pose[limb['ik_target']].constraints.get('Stay In Reach')
    if reach_limit:  # the limit holds the target at s times the way out, the chain just follows it
        add_driver(rig, f'{bone_path(limb["ik_target"])}.constraints["Stay In Reach"].influence', None, '1 - s', sliders)
    add_driver(rig, f'{bone_path(top.name)}.constraints["{scale.name}"].influence', None,
                 'ik if s > 0 else 0' if reach_limit else 's * ik', sliders)
    end = limb.get('heel') or limb['tip']
    keep = get_constraint(pose[end], 'Stretch Keep Size', 'COPY_SCALE')
    keep.target, keep.subtarget, keep.target_space, keep.owner_space = rig, master, 'POSE', 'POSE'
    add_driver(rig, f'{bone_path(end)}.constraints["{keep.name}"].influence', None, '1 if s > 0 and ik > 0 else 0', sliders)


def twist_share(rig, bone, ctrl, share=TWIST_SHARE):
    """The Twist Share constraint: `bone` (Forearm1) turns about its Y by `share` (TWIST_SHARE) of the hand control's twist
    (swing-twist, so a bent wrist doesn't halve it), before its own rotation. Its influence needs drive_twist_share."""
    pb = rig.pose.bones[bone]
    c = get_constraint(pb, TWIST_NAME, 'TRANSFORM')
    c.target, c.subtarget = rig, ctrl
    c.owner_space = c.target_space = 'LOCAL'
    c.map_from, c.from_rotation_mode = 'ROTATION', 'SWING_TWIST_Y'
    c.from_min_y_rot, c.from_max_y_rot = -math.pi, math.pi
    c.map_to, c.map_to_x_from, c.map_to_y_from, c.map_to_z_from = 'ROTATION', 'X', 'Y', 'Z'
    c.to_min_x_rot = c.to_max_x_rot = c.to_min_z_rot = c.to_max_z_rot = 0.0
    c.to_min_y_rot, c.to_max_y_rot = -math.pi * share, math.pi * share
    c.mix_mode_rot = 'BEFORE'
    return c


def drive_twist_share(rig, bone, ctrl):
    """The share is on in IK only (influence = IK_FK): in FK the B-bones carry the roll."""
    add_driver(rig, f'{bone_path(bone)}.constraints["{TWIST_NAME}"].influence', None, 'ik',
               {'ik': f'{bone_path(ctrl)}["IK_FK"]'})


def fix_twist(rig, limb):
    """A share reading a bone below itself (the hand) is a dependency cycle, and a pose that lags one update: read
    the hand control instead, only while in IK. A Twist Share already reads it and is left alone."""
    found = find_twist_share(rig, limb['twist'], (limb['tip'], limb['ctrl']))
    if found is None or found[1].subtarget == limb['ctrl']:
        return
    owner, twist = found
    twist.subtarget = limb['ctrl']
    if twist.type == 'TRANSFORM':
        drive_twist_share(rig, owner.name, limb['ctrl'])
    else:
        add_driver(rig, f'{bone_path(owner.name)}.constraints["{twist.name}"].influence', None, f'ik*{TWIST_SHARE}',
                   {'ik': f'{bone_path(limb["ctrl"])}["IK_FK"]'})


def plain_bbones(rig, limb):
    """B-bones only on the twist forearm: elsewhere on a limb they crumple tight folds (roll is not the cause, easing
    makes it worse). Run once, on a limb's first upgrade: a later run leaves hand settings alone."""
    for name in limb['fk']:
        bone = rig.data.bones[name]
        bone.bbone_segments = TWIST_SEGMENTS if name == limb.get('twist') else 1
        bone.bbone_easein = bone.bbone_easeout = 0.0
        BC.thin_bbones([bone])


def foot_roll_overshoot(ctrl):
    """The foot roll slider stays, a typed value may go past it."""
    if 'FootRoll' in ctrl:
        ui = ctrl.id_properties_ui('FootRoll').as_dict()
        lo, hi = ui.get('soft_min', ui['min']), ui.get('soft_max', ui['max'])
        slider_limits(ctrl, 'FootRoll', lo, hi, ui.get('default', 0.0), ui.get('description', ''), OVERSHOOT)


def rig_parent_switch(rig, limb, parents, key='IK_Parent'):
    """`key` (IK_Parent) on the control picks which bone its parent helper follows (index into parents). Also the
    look rig's LookFollow. A run with fewer parents than before (a parent bone gone) drops the extra targets' drivers
    and narrows the slider, so no driver points at a missing target."""
    ctrl = rig.pose.bones[limb['ctrl']]
    last = len(parents) - 1
    if key not in ctrl:
        add_prop(ctrl, key, 0, 0, last, 'What this control follows: ' + ', '.join(parents))
    else:
        ctrl[key] = min(ctrl[key], last)
        slider_limits(ctrl, key, 0, last, 0, 'What this control follows: ' + ', '.join(parents), overshoot=1)
    helper = rig.pose.bones[limb['parent_bone']]
    c = get_constraint(helper, 'Parent Switch', 'ARMATURE')
    remove_drivers(rig, f'{bone_path(limb["parent_bone"])}.constraints["{c.name}"].targets[')
    while len(c.targets):
        c.targets.remove(c.targets[0])
    for i, bone in enumerate(parents.values()):
        t = c.targets.new()
        t.target, t.subtarget = rig, bone
        path = f'{bone_path(limb["parent_bone"])}.constraints["{c.name}"].targets[{i}].weight'
        add_driver(rig, path, None, f'1 if p == {i} else 0', {'p': f'{bone_path(limb["ctrl"])}["{key}"]'})


def store_limb_data(rig, limb, parents):
    """What the Rig Switches buttons need, on the control as a JSON string. A part chain (part_chains: tail, ears) adds
    `part` ('Tail', 'Ear', 'Head': the rig panel's page word instead of Arm / Leg) and has no pole: chain = its IK bones,
    fk = all its bones, target = the control."""
    ctrl = rig.pose.bones[limb['ctrl']]
    data = dict(chain=limb['chain'], fk=limb['fk'], tip=limb['tip'], target=limb['target'], pole=limb['pole'],
                hock=limb.get('hock'), hock_target=limb.get('hock_target'), parents=list(parents))
    for key in ('part', 'turns'):      # turns: the bone the control turns (neck IK: Head), for the FK -> IK snap
        if limb.get(key):
            data[key] = limb[key]
    text = json.dumps(data)
    ctrl['Limb'] = text
    ctrl.id_properties_ui('Limb').update(default=text, description='Bones of this limb, for the Rig Switches buttons')


def limbs_of(rig, table):
    """The rig's limbs, both sides, and what the table asks for but the rig lacks."""
    limbs, skipped = [], []
    for entry in table['limbs']:
        for flip in (False, True):
            limb = resolve_limb(rig, entry, flip, table.get('hock_mch'))
            if limb and any(l['ctrl'] == limb['ctrl'] for l in limbs):
                continue  # an unsided limb is its own flip
            if limb:
                limbs.append(limb)
            else:
                skipped.append(f'{rn.flip(entry["ctrl"]) if flip else entry["ctrl"]}: bones missing, or no IK with a pole, or no IK_FK property')
    return limbs, skipped


def rebuild_hocks(rig, table):
    """Legs with a hock_mch pattern that aren't rebuilt yet. Returns a report line."""
    limbs, _ = limbs_of(rig, table)
    hocks = [l for l in limbs if l.get('hock_bones')]
    rebuilt = [l for l in hocks if l['hock_bones']['leg_ik2_1'] not in rig.data.bones]
    if rebuilt:
        edit_limbs(rig, rebuilt, add_hock_bones)
        for limb in rebuilt:
            rig_hock(rig, limb)
        return f'rebuilt {len(rebuilt)} legs'
    if hocks:
        return 'already rebuilt'
    return 'kept the old hock' if any(l.get('hock') for l in limbs) else 'no hocks'


def add_features(rig, table, stretch=True, parent_switch=True):
    """Stretch, parent switch and snap data on every limb. Returns a report dict."""
    limbs, skipped = limbs_of(rig, table)
    parents = {k: v for k, v in table['parents'].items() if v in rig.data.bones} if parent_switch else {}
    if parent_switch:
        skipped += [f'parent {k}: no bone "{v}"' for k, v in table['parents'].items() if k not in parents]
    if stretch and table['parents'].get('Root') not in rig.data.bones:
        skipped.append('stretch: no Root bone, so the tip could not keep its size')
        stretch = False
    added = edit_limbs(rig, limbs, lambda r, limb: add_feature_bones(r, limb, stretch, parent_switch))
    done = []
    for limb in limbs:
        did = []
        ctrl = rig.pose.bones[limb['ctrl']]
        if 'Limb' not in ctrl:
            plain_bbones(rig, limb)
        foot_roll_overshoot(ctrl)
        if stretch:
            rig_stretch(rig, limb, table['parents']['Root'])
            did.append('stretch')
        if limb.get('twist'):
            fix_twist(rig, limb)
            did.append('twist fix')
        if parent_switch and parents:
            rig_parent_switch(rig, limb, parents)
            did.append('parent switch')
        store_limb_data(rig, limb, parents)
        did.append('snap data')
        if limb.get('hock_bones') and limb['hock_bones']['leg_ik2_1'] in rig.data.bones:
            did.append('hock')
        done.append(f'{limb["ctrl"]}: ' + ', '.join(did))
    drivers = rig.animation_data.drivers if rig.animation_data else []
    return dict(limbs=[l['ctrl'] for l in limbs], done=done, added=added, skipped=skipped,
                bad_drivers=[fc.data_path for fc in drivers if not fc.driver.is_valid])


def upgrade(rig, table, stretch=True, parent_switch=True, hock=True):
    """The chosen steps, leaving the rig in the mode it was in (it must be in the view layer)."""
    mode = rig.mode
    report = dict(rig=rig.name, hock=rebuild_hocks(rig, table) if hock else 'hock rebuild off')
    report.update(add_features(rig, table, stretch, parent_switch))
    BC.place_fk(rig)
    finish_rig(rig)
    set_mode(rig, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    return report


# ---------- taking features off again (Regenerate with a toggle off) ----------
FEATURES = ('stretch', 'parent_switch', 'hock')


def drivers_on(rig, prefix):
    drivers = rig.animation_data.drivers if rig.animation_data else []
    return [fc for fc in drivers if fc.data_path.startswith(prefix)]


def remove_drivers(rig, prefix):
    for fc in drivers_on(rig, prefix):
        rig.animation_data.drivers.remove(fc)


def remove_constraint(rig, bone, name):
    pb = rig.pose.bones.get(bone)
    c = pb and pb.constraints.get(name)
    if c:
        remove_drivers(rig, f'{bone_path(bone)}.constraints["{name}"]')
        pb.constraints.remove(c)


def drop_prop(pb, name):
    if name in pb:
        del pb[name]


def else_value(fc):
    """The `else` value of an open_hinge_for_stretch driver ('a if s > 0 else b' -> b)."""
    return float(fc.driver.expression.rsplit('else', 1)[1])


def remove_stretch(rig, limb):
    pose = rig.pose.bones
    remove_constraint(rig, limb['chain'][0], 'Stretch')
    remove_constraint(rig, limb.get('heel') or limb['tip'], 'Stretch Keep Size')
    for bone in limb['chain'][1:]:
        for attr in ('ik_min_x', 'ik_max_x'):
            for fc in drivers_on(rig, f'{bone_path(bone)}.{attr}'):
                value = else_value(fc)
                rig.animation_data.drivers.remove(fc)
                setattr(pose[bone], attr, value)
    reach = pose[limb['ik_target']].constraints.get('Stay In Reach')
    if reach:
        remove_drivers(rig, f'{bone_path(limb["ik_target"])}.constraints["Stay In Reach"].influence')
        reach.influence = 1.0
    drop_prop(pose[limb['ctrl']], 'IK_Stretch')
    return [limb['stretch_bone']]


def remove_parent_switch(rig, limb):
    """The control goes back under what IK_Parent 0 followed (the Root), so its default pose stays."""
    helper = rig.pose.bones.get(limb['parent_bone'])
    switch = helper and helper.constraints.get('Parent Switch')
    drop_prop(rig.pose.bones[limb['ctrl']], 'IK_Parent')
    return [limb['parent_bone']], (switch.targets[0].subtarget if switch and len(switch.targets) else '')


def remove_hock(rig, limb):
    """Back to the plain hock: the control rides the foot target again, the target helper loses its limits."""
    for name in ('Stay On Ball', 'Stay In Reach'):
        remove_constraint(rig, limb['hock_target'], name)
    rig.pose.bones[limb['hock']].lock_rotation = (False, False, False)
    return list(limb.get('hock_bones', {}).values())


def remove_features(rig, limb, which=FEATURES):
    """Take features off one limb (a limb from limbs_of): 'stretch', 'parent_switch' and / or 'hock' (the rebuilt hock's
    helpers). Removes only their helper bones, constraints, drivers and properties, so a rig upgraded with a feature and
    then stripped of it is the rig upgraded without it. Returns the removed bone names."""
    which = set(which) - ({'hock'} if not limb.get('hock_bones') else set())
    gone, old_parent = [], None
    if 'stretch' in which:
        gone += remove_stretch(rig, limb)
    if 'parent_switch' in which:
        bones, old_parent = remove_parent_switch(rig, limb)
        gone += bones
    if 'hock' in which:
        gone += remove_hock(rig, limb)
    gone = [n for n in gone if n in rig.data.bones]
    for name in gone:
        remove_drivers(rig, bone_path(name))
    mode = rig.mode
    mirror, rig.data.use_mirror_x = rig.data.use_mirror_x, False
    set_mode(rig, 'EDIT')
    eb = rig.data.edit_bones
    if old_parent and old_parent in eb and limb['parent_bone'] in eb:
        eb[limb['ctrl']].parent = eb[old_parent]
    if 'hock' in which:
        eb[limb['hock']].parent = eb[limb['target']]
    for name in gone:
        eb.remove(eb[name])
    set_mode(rig, 'POSE')
    rig.data.use_mirror_x = mirror
    ctrl = rig.pose.bones[limb['ctrl']]
    if 'Limb' in ctrl:
        parents = [] if 'parent_switch' in which else json.loads(ctrl['Limb'])['parents']
        store_limb_data(rig, limb, parents)
    set_mode(rig, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    return gone


def report_lines(report):
    """The report as short text lines: one per limb done, then what was skipped."""
    lines = list(report['done'])
    lines.append('Hock: ' + report['hock'])
    lines += ['Skipped ' + s for s in report['skipped']]
    lines += ['Driver not valid: ' + p for p in report['bad_drivers']]
    return lines
