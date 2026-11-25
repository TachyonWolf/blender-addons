# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop's Constraint Setups: one registry entry per setup (SETUPS), grouped for the dropdown (GROUPS).
A Setup knows what it needs selected (`check`), what it adds (`run`), how Try It poses it (`demo`) and which
constraint names it makes (`made`, for the "On this bone now" list). Setups the Full Character Rig has call its code
(body_rig, limb_rig); the small new ones are here. A new setup = one Setup(...) line in SETUPS (+ its options on
bone_workshop_props if it needs new ones). Nothing runs in the background: every function runs from a button."""
import math
from dataclasses import dataclass
from typing import Callable

import bpy
from mathutils import Matrix, Vector

from . import body_rig as br, bone_collections as bc, face_rig_core as fr, limb_rig as lr, rig_names as rn, \
    scene_checks as sc  # generated copies
from . import bone_workshop as bw, bone_workshop_spec as spec

GROUPS = ("Limbs", "Hands & Feet", "Chains", "Helpers")
MECH = "Mechanism"
ARM_BEND, LEG_BEND = Vector((0, 1, 0)), Vector((0, -1, 0))    # elbows point back, knees forward (the rig faces -Y)
END_SHARE = 0.3          # At End: the IK bone is this share of the last chain bone long


@dataclass
class Setup:
    id: str
    group: str
    label: str
    desc: str          # what it does, in plain words
    needs: str         # what to select
    adds: str          # what it adds
    options: tuple     # bone_workshop_props setting names it draws
    check: Callable    # check(sel, s) -> why it can't run now, or ""
    run: Callable      # run(sel, s) -> report lines
    demo: Callable     # demo(sel, s) -> [(bone, kind, value)]: kind 'move' (rig-space offset), 'turn' ((axis, angle)), 'prop'
    made: tuple = ()   # constraint names it makes
    edits: bool = True  # adds bones (Edit Mode): not on library overrides


class Selection:
    """The active rig's selected bones (root first, by depth) and the active bone."""

    def __init__(self, rig, names, active):
        self.rig, self.active = rig, active
        bones = rig.data.bones
        self.names = sorted(names, key=lambda n: (len(bones[n].parent_recursive), n))

    @classmethod
    def of(cls, context):
        rig = context.active_object
        names = [pb.name for pb in context.selected_pose_bones or [] if pb.id_data == rig]
        active = context.active_pose_bone.name if context.active_pose_bone else ""
        if active and active not in names:
            names.append(active)
        return cls(rig, names, active)

    def others(self):
        return [n for n in self.names if n != self.active]

    def mirrored(self):
        """The same selection on the other side, or None (a middle bone, or a missing mirror bone)."""
        flipped = [rn.flip(n) for n in self.names]
        if flipped == self.names or not all(n in self.rig.data.bones for n in flipped):
            return None
        return Selection(self.rig, flipped, rn.flip(self.active))


# ---------------------------------------------------------------- helpers
def is_chain(rig, names):
    """Each bone is the child of the one before it."""
    bones = rig.data.bones
    return all(bones[b].parent and bones[b].parent.name == a for a, b in zip(names, names[1:]))


def has_kind(pb, kind):
    return any(c.type == kind for c in pb.constraints)


def tip_of(rig, name):
    """The bone that carries on where `name` ends (a hand below a forearm): its child starting at its tail."""
    bone = rig.data.bones[name]
    near = [c for c in bone.children if (c.head_local - bone.tail_local).length < 1e-4]
    return (next((c for c in near if c.use_connect), None) or (near[0] if near else None) or
            (bone.children[0] if len(bone.children) == 1 else None))


def root_of(rig):
    return rn.find(rig.data.bones.keys(), rn.ROOT)


def edit(rig, work):
    """work(edit_bones) in Edit Mode (X-mirror off), back to Pose Mode. Returns what work returned."""
    mirror, rig.data.use_mirror_x = rig.data.use_mirror_x, False
    lr.set_mode(rig, 'EDIT')
    try:
        return work(rig.data.edit_bones)
    finally:
        lr.set_mode(rig, 'POSE')
        rig.data.use_mirror_x = mirror


def copy_bone(E, name, source, parent=None, head=None, tail=None, deform=False):
    """A new edit bone shaped like `source` (or head / tail given), with its roll."""
    eb = E.new(name)
    src = E[source]
    eb.head = head if head is not None else src.head.copy()
    eb.tail = tail if tail is not None else src.tail.copy()
    eb.roll, eb.parent, eb.use_deform = src.roll, E.get(parent) if parent else None, deform
    return eb


def look(rig, names, preset):
    """The style preset's look on new control bones, sorted into their collections by name."""
    widget, scale, colour = bw.preset_look(preset)
    bones = [rig.pose.bones[n] for n in names]
    bw.set_shape(bones, widget)
    for pb in bones:
        pb.custom_shape_scale_xyz = (scale,) * 3
        bw.set_colour(pb, colour)
    bw.auto_sort(bones)


def to_mechanism(rig, names):
    for name in names:
        bc.move_to(rig, name, MECH, False)


def drive_by(rig, bone, constraint, ctrl, prop):
    """The constraint's influence follows a slider on the control."""
    lr.add_driver(rig, f'{lr.bone_path(bone)}.constraints["{constraint}"].influence', None, 'v',
                  {'v': f'{lr.bone_path(ctrl)}["{prop}"]'})


def chain_length(rig, names):
    return sum(rig.data.bones[n].length for n in names)


def need_chain(sel, lo, hi, what):
    if not lo <= len(sel.names) <= hi:
        return f"Select {what}"
    if not is_chain(sel.rig, sel.names):
        return "The bones must hang one under the other (a chain)"
    return ""


def need_pair(sel, what):
    if len(sel.names) != 2 or not sel.active:
        return f"Select {what}"
    return ""


# ---------------------------------------------------------------- IK Limb
def ik_names(sel, s):
    """(chain, the bone after it, IK control, pole) for an IK Limb on the selection."""
    rig, chain = sel.rig, sel.names
    tip = tip_of(rig, chain[-1])
    tip = tip.name if tip else None
    if s.ik_new == 'EXISTING':
        ctrl = s.ik_bone
    else:      # Inline: IK-Hand.L along the hand; At End (or no bone after the chain): IK-Forearm.L at its tip
        ctrl = spec.with_role(tip if tip and s.ik_place == 'INLINE' else chain[-1], 'IK')
    pole = rn.build(f"Pole-{rn.parse(chain[1]).part}", rn.side_of(chain[1]), role='IK')
    return chain, tip, ctrl, pole


def check_ik(sel, s):
    why = need_chain(sel, 2, 3, "the limb's 2 or 3 bones, the upper one too (an arm: upper arm and forearm)")
    if why:
        return why
    chain, tip, ctrl, pole = ik_names(sel, s)
    P = sel.rig.pose.bones
    if has_kind(P[chain[-1]], 'IK'):
        return f"{chain[-1]} has an IK already"
    if s.ik_new == 'EXISTING':
        if ctrl not in P:
            return "Pick the IK bone to use (IK Bone: Use Existing)"
        if ctrl in chain:
            return "The IK bone can't be one of the chain's bones"
    elif ctrl in P:
        return f"{ctrl} exists already: pick Use Existing"
    if pole in P:
        return f"{pole} exists already"
    return ""


def fit_pole(rig, pb, con, coarse=36, fine=24):
    """The pole angle that leaves the chain at rest (Limb Rig's fit, over every angle: hand-made bones have any roll)."""
    lr.fit_pole_angle(rig, pb, con, angles=[-math.pi + 2 * math.pi * k / coarse for k in range(coarse)])
    best, step = con.pole_angle, 2 * math.pi / coarse
    lr.fit_pole_angle(rig, pb, con, angles=[best + step * (k / fine - 0.5) for k in range(fine + 1)])


def run_ik(sel, s):
    rig = sel.rig
    chain, tip, ctrl, pole = ik_names(sel, s)
    inline = s.ik_place == 'INLINE' and tip is not None
    leg = lr.is_leg(chain + [tip or ""])
    H = br.rig_height(rig)
    root = root_of(rig)

    def bones(E):
        top, mid, end = E[chain[0]].head, E[chain[1]].head, E[chain[-1]].tail
        hinge, _bend = br.bend_of(top, mid, end, LEG_BEND if leg else ARM_BEND)
        at, bend = br.pole_point(mid, top, end, hinge)
        eb = E.new(pole)
        eb.head, eb.tail, eb.parent, eb.use_deform = at, at + bend * 0.04 * H, E.get(root) if root else None, False
        if s.ik_new == 'NEW':
            if inline:
                copy_bone(E, ctrl, tip, root)
            else:
                last = E[chain[-1]]
                copy_bone(E, ctrl, chain[-1], root, end, end + last.vector.normalized() * last.length * END_SHARE)
    edit(rig, bones)
    P = rig.pose.bones
    c = br.ik(rig, chain[-1], ctrl, len(chain), pole)
    fit_pole(rig, P[chain[-1]], c)
    if inline:
        br.con(rig, tip, 'Copy Rotation', 'COPY_ROTATION', ctrl)
    fr.switch(P[ctrl], 'IK_FK', 0.0, 1.0, 'IK (1) or FK (0): the IK control, or the limb bones themselves', 1.0, overshoot=1)
    drive_by(rig, chain[-1], 'IK', ctrl, 'IK_FK')
    if inline:
        drive_by(rig, tip, 'Copy Rotation', ctrl, 'IK_FK')
    if s.ik_new == 'NEW':
        look(rig, [ctrl], 'ik')
    look(rig, [pole], 'pole')
    entry = dict(ctrl=ctrl, ik=chain[-1], tip=tip or chain[-1])
    table = dict(parents=lr.guess_parents(rig, [dict(entry, leg=leg, up=lr.above(rig, chain[0]))]), hock_mch=None,
                 limbs=[entry])
    report = lr.upgrade(rig, table, stretch=s.stretchy and bool(root), parent_switch=s.limb_parent_switch, hock=False)
    lines = [f"IK on {chain[-1]} to {ctrl}, pole {pole}" + (f", {tip} turns with it" if inline else "")]
    lines += report['skipped']
    if s.pole_line:
        lines += br.add_features(rig, ['pole_lines'])['done']
    return lines


def demo_ik(sel, s):
    chain, _tip, ctrl, _pole = ik_names(sel, s)
    rig = sel.rig
    top = rig.pose.bones[chain[0]].head
    at = rig.pose.bones[ctrl].head
    return [(ctrl, 'move', (top - at) * 0.35)]


# ---------------------------------------------------------------- Twist Share
def check_twist(sel, s):
    return need_pair(sel, "the hand (or its control), then the forearm last") or \
        ("Click the forearm last: it takes the share" if sel.active not in sel.names else "")


def run_twist(sel, s):
    rig, owner, source = sel.rig, sel.active, sel.others()[0]
    lr.twist_share(rig, owner, source, s.twist_share)
    if 'IK_FK' in rig.pose.bones[source]:
        lr.drive_twist_share(rig, owner, source)
    bone = rig.data.bones[owner]
    if bone.bbone_segments == 1:
        bone.bbone_segments = lr.TWIST_SEGMENTS
    return [f"{owner} takes {round(s.twist_share * 100)}% of {source}'s roll ({bone.bbone_segments} B-Bone segments)"]


def demo_twist(sel, s):
    return [(sel.others()[0], 'turn', ('Y', math.radians(80)))]


# ---------------------------------------------------------------- Spine IK
def spine_ctrl(sel):
    return spec.with_role(sel.names[-1], 'IK')


def check_spine(sel, s):
    why = need_chain(sel, 2, 8, "the spine bones, from the bottom one to the chest")
    if why:
        return why
    if has_kind(sel.rig.pose.bones[sel.names[-1]], 'IK'):
        return f"{sel.names[-1]} has an IK already"
    return f"{spine_ctrl(sel)} exists already" if spine_ctrl(sel) in sel.rig.pose.bones else ""


def run_spine(sel, s):
    rig, top, ctrl = sel.rig, sel.names[-1], spine_ctrl(sel)
    edit(rig, lambda E: copy_bone(E, ctrl, top, root_of(rig)))
    br.rig_spine_ik(rig, top, ctrl, len(sel.names) - 1)
    br.drive_spine_ik(rig, top, ctrl)
    look(rig, [ctrl], 'ik')
    bw.set_shape([rig.pose.bones[ctrl]], 'WGT-Ring')
    br.shape_spine_ik(rig.pose.bones[ctrl])
    return [f"Spine IK: {top} follows {ctrl}, {len(sel.names) - 1} bones bend"]


def demo_spine(sel, s):
    return [(spine_ctrl(sel), 'move', Vector((0, -0.4, -0.1)) * chain_length(sel.rig, sel.names))]


# ---------------------------------------------------------------- Finger Curl
def finger_chains(sel):
    """Chains of the selected finger bones (base first), without the palm."""
    picked = set(sel.others())
    bones = sel.rig.data.bones
    bases = [n for n in sel.names if n in picked and not (bones[n].parent and bones[n].parent.name in picked)]
    chains = []
    for base in bases:
        chain, bone = [base], bones[base]
        while True:
            nxt = [c for c in bone.children if c.name in picked]
            if len(nxt) != 1:
                break
            bone = nxt[0]
            chain.append(bone.name)
        chains.append(chain)
    return chains


def is_thumb(name):
    return 'thumb' in rn.plain(name)


def check_fist(sel, s):
    if len(sel.names) < 2 or not sel.active:
        return "Select the finger bones, then click the Palm control last"
    if not finger_chains(sel):
        return "Select at least one finger"
    return ""


def run_fist(sel, s):
    rig, palm = sel.rig, sel.active
    chains = finger_chains(sel)
    turns = {}
    for chain in chains:
        if is_thumb(chain[0]):
            if s.thumb == 'CURLS':
                turns[chain[0]] = {'X': br.THUMB_AIM[0], 'Z': br.THUMB_AIM[1]}
                if len(chain) > 1:
                    turns[chain[1]] = {'X': br.THUMB_CURL}
            br.curl_follow(rig, chain[1:])
        else:
            turns[chain[0]] = {'X': s.curl_angle, 'Z': -br.UNFAN * br.fan_angle(rig, chain[0], palm)}
            br.curl_follow(rig, chain)
    br.fist_on(rig, palm, turns)
    lines = [f"Fist on {len(turns)} finger bones: turn {palm} on X"]
    fingers = sorted((c[0] for c in chains if not is_thumb(c[0])),
                     key=lambda n: (rig.data.bones[palm].matrix_local.inverted() @ rig.data.bones[n].head_local).x)
    if s.fan and len(fingers) > 1:
        shares = [(n, 1 - 2 * i / (len(fingers) - 1)) for i, n in enumerate(fingers)]
        shares = [(n, v) for n, v in shares if abs(v) > 1e-6]
        br.spread_on(rig, palm, shares)
        for name, share in shares:
            rig.pose.bones[name].constraints['Hand Spread'].influence = abs(share)
        lines.append(f"Fan: turn {palm} on Z")
    return lines


def demo_fist(sel, s):
    return [(sel.active, 'turn', ('X', -br.FIST_TURN))]


# ---------------------------------------------------------------- Foot Roll
def foot_parts(sel):
    """(foot, toes, IK control, the IK's owner) for the selected IK foot control, or Nones. The foot is the bone after
    the IK chain (Limb data's tip), the toes the bone after the foot."""
    rig, ctrl = sel.rig, sel.active
    owner = next((pb for pb in rig.pose.bones for c in pb.constraints if c.type == 'IK' and c.subtarget == ctrl), None)
    if owner is None:
        return None, None, None, None
    foot = tip_of(rig, owner.name)
    toes = tip_of(rig, foot.name) if foot else None
    return (foot.name if foot else None), (toes.name if toes else None), ctrl, owner.name


def check_foot(sel, s):
    if len(sel.names) != 1:
        return "Select the IK foot control of a leg (make one with IK Limb)"
    foot, toes, ctrl, _shin = foot_parts(sel)
    if ctrl is None:
        return f"{sel.active} is not an IK control: no IK reaches for it"
    if foot is None or toes is None:
        return "The leg needs a foot bone and a toe bone after its IK chain"
    return "This foot has a foot roll already" if rn.helper(ctrl, 'RollHeel') in sel.rig.pose.bones else ""


def run_foot(sel, s):
    rig = sel.rig
    foot, toes, ctrl, shin = foot_parts(sel)
    H = br.rig_height(rig)
    target = rn.helper(ctrl, 'Target')

    def bones(E):
        ankle, ball, tip = E[foot].head.copy(), E[toes].head.copy(), E[toes].tail.copy()
        fwd = br.flat(ball - ankle).normalized()
        floor = min(tip.z, ankle.z)
        heel = br.flat(ankle) - fwd * 0.25 * (ball - ankle).length + Vector((0, 0, floor))
        side = br.UP.cross(fwd).normalized()
        specs = br.foot_roll_specs(ctrl, None, (heel, br.flat(tip) + Vector((0, 0, floor)), ball, ankle), ctrl,
                                   lambda p: (p, p + br.UP * 0.03 * H), lambda a, b: br.hinge_z(side, a, b))
        for spec_ in specs:
            br.make_spec_bone(rig.data, spec_)
        return [spec_.name for spec_ in specs]
    added = edit(rig, bones)
    P = rig.pose.bones
    ik = next(c for c in P[shin].constraints if c.type == 'IK')
    ik.subtarget = target
    copy = next((c for c in P[foot].constraints if c.type == 'COPY_ROTATION' and c.subtarget == ctrl), None)
    if copy:
        copy.subtarget = target
    else:
        br.con(rig, foot, 'Copy Rotation', 'COPY_ROTATION', target, owner_space='POSE', target_space='POSE')
    br.rig_foot_roll(rig, ctrl, None, s.roll_break)
    br.drive_foot_roll(rig, ctrl)
    to_mechanism(rig, added)
    lines = [f"Foot roll on {ctrl}: FootRoll and RollBreak sliders ({len(added)} pivot bones)"]
    if s.foot_bank:
        done = br.add_features(rig, ['foot_bank'])
        lines += done['done'] or [f"Foot bank needs the leg's Limb data: run IK Limb (or Upgrade Limbs) first"]
    return lines


def demo_foot(sel, s):
    return [(foot_parts(sel)[2], 'prop', ('FootRoll', 1.0))]


# ---------------------------------------------------------------- Chain Curl, Stretch To, Aim, Parent Switch, Deform Follows
def check_curl(sel, s):
    return need_chain(sel, 2, 32, "a chain of bones, from its root")


def run_curl(sel, s):
    rig, root = sel.rig, sel.names[0]
    use = tuple(s.curl_axes)
    for i, name in enumerate(sel.names[1:]):
        br.con(rig, name, 'Chain Curl', 'COPY_ROTATION', root, use_x=use[0], use_y=use[1], use_z=use[2], mix_mode='ADD',
               owner_space='LOCAL', target_space='LOCAL', influence=max(0.0, s.curl_follow - s.fade * i))
    return [f"{len(sel.names) - 1} bones curl with {root}"]


def demo_curl(sel, s):
    return [(sel.names[0], 'turn', ('X', math.radians(25)))]


def check_target(sel, s):
    return need_pair(sel, "the target bone, then click the bone that should follow it last")


def run_stretch(sel, s):
    rig, owner, target = sel.rig, sel.active, sel.others()[0]
    c = br.con(rig, owner, 'Stretch To', 'STRETCH_TO', target, volume=s.volume)
    c.rest_length = rig.data.bones[owner].length
    return [f"{owner} stretches to {target}"]


def demo_target_move(sel, s):
    rig, owner, target = sel.rig, sel.active, sel.others()[0]
    pb = rig.pose.bones[owner]
    return [(target, 'move', (pb.tail - pb.head) * 0.5)]


def run_aim(sel, s):
    rig, owner, target = sel.rig, sel.active, sel.others()[0]
    br.con(rig, owner, 'Aim', 'DAMPED_TRACK', target, track_axis='TRACK_Y')
    if s.aim_slider:
        fr.switch(rig.pose.bones[target], 'Aim', 0.0, 1.0, f'How much the bones aim at {target}', 1.0, overshoot=1)
        drive_by(rig, owner, 'Aim', target, 'Aim')
    return [f"{owner} aims at {target}" + (" (slider Aim on it)" if s.aim_slider else "")]


def demo_aim(sel, s):
    rig, owner = sel.rig, sel.active
    pb = rig.pose.bones[owner]
    return [(sel.others()[0], 'move', Vector((pb.length, 0, 0)))]


def parent_choices(rig, ctrl):
    """{label: bone} of PARENT_NAMES the rig has, minus the control itself and the bones below it."""
    below = {b.name for b in rig.data.bones[ctrl].children_recursive} | {ctrl}
    found = {label: rn.find(rig.data.bones.keys(), label) for label in lr.PARENT_NAMES}
    return {label: bone for label, bone in found.items() if bone and bone not in below}


def check_parent(sel, s):
    if len(sel.names) != 1:
        return "Select one control"
    if rn.is_helper(sel.active):
        return "Pick a control (not a DEF- or MCH- bone)"
    return "" if len(parent_choices(sel.rig, sel.active)) > 1 else \
        "The rig needs at least two of Root, Pelvis, Chest and Head to switch between"


def run_parent(sel, s):
    rig, ctrl = sel.rig, sel.active
    limb = dict(ctrl=ctrl, parent_bone=lr.existing_or_new(rig, rn.helper(ctrl, 'Parent')))
    lr.edit_limbs(rig, [limb], lambda r, l: lr.add_feature_bones(r, l, stretch=False, parent_switch=True))
    parents = parent_choices(rig, ctrl)
    lr.rig_parent_switch(rig, limb, parents)
    return [f"{ctrl} can follow {', '.join(parents)} (IK_Parent slider)"]


def demo_parent(sel, s):
    return [(sel.active, 'prop', ('IK_Parent', 1))]


def def_name(name):
    return spec.with_role(name, 'DEF')


def check_follow(sel, s):
    if not sel.names:
        return "Select the controls"
    if any(rn.split_role(n)[0] == 'DEF' for n in sel.names):
        return "Select controls, not DEF- bones"
    return "" if any(def_name(n) not in sel.rig.data.bones for n in sel.names) else "Every one has its DEF- bone already"


def run_follow(sel, s):
    rig = sel.rig
    todo = [n for n in sel.names if def_name(n) not in rig.data.bones]

    def bones(E):
        for name in todo:
            parent = E[name].parent
            copy_bone(E, def_name(name), name, def_name(parent.name) if parent and def_name(parent.name) in E else None,
                      deform=True)
    edit(rig, bones)
    renamed = 0
    meshes = sc.rig_meshes(rig, bpy.context.scene.objects)
    for name in todo:
        br.con(rig, def_name(name), 'Copy Transforms', 'COPY_TRANSFORMS', name)
        bw.set_deform(rig.pose.bones[name], False)
        rig.data.bones[name].use_deform = False
        bc.move_to(rig, def_name(name), None, True)
        for mesh in meshes:
            group = mesh.vertex_groups.get(name)
            if group and def_name(name) not in mesh.vertex_groups:
                group.name = def_name(name)
                renamed += 1
    return [f"{len(todo)} DEF- bones follow their controls", f"{renamed} vertex groups moved to the DEF- bones"]


def demo_follow(sel, s):
    return [(sel.names[0], 'turn', ('X', math.radians(30)))]


SETUPS = (
    Setup('ik', "Limbs", "IK Limb",
          "IK with a pole and an IK/FK switch on the control: move the control and the limb bends to reach it.",
          "Select the limb's 2 or 3 bones, upper one first (upper arm and forearm).",
          "an IK and pole, an IK_FK slider and snap data (Limb Rig), parent switch and stretch if on",
          ('ik_new', 'ik_place', 'limb_parent_switch', 'stretchy', 'pole_line'), check_ik, run_ik, demo_ik,
          made=('IK', 'Copy Rotation', 'IK_Stretch', 'Parent Switch')),
    Setup('twist', "Limbs", "Twist Share",
          "The forearm takes a share of the hand's roll, so the wrist doesn't twist like a candy wrapper.",
          "Select the hand (or its IK control), then click the forearm last.",
          "a Twist Share constraint, and 4 B-Bone segments on the forearm",
          ('twist_share',), check_twist, run_twist, demo_twist, made=(lr.TWIST_NAME,), edits=False),
    Setup('spine', "Limbs", "Spine IK", "Move the chest control and the spine bends to follow.",
          "Select the spine bones, from the bottom one to the chest.",
          "a new IK- chest control, IK on the top bone and a SpineIK slider",
          (), check_spine, run_spine, demo_spine, made=('IK', 'Copy Rotation')),
    Setup('fist', "Hands & Feet", "Finger Curl",
          "Turn the Palm control on X and every finger curls into a fist. On Z the fingers fan out. Same as the Full "
          "Rig's Fist Control.",
          "Select the finger bones, then click the Palm control last.",
          "a Fist constraint on each finger base; later segments follow the base",
          ('curl_angle', 'thumb', 'fan'), check_fist, run_fist, demo_fist,
          made=(br.FIST, 'Hand Spread', 'Copy Rotation'), edits=False),
    Setup('foot', "Hands & Feet", "Foot Roll",
          "FootRoll, RollBreak (and Foot Bank) sliders on the IK foot control: the ball lifts first, then the toe tip.",
          "Select the IK foot control of a leg (IK Limb makes one).",
          "MCH pivot bones (heel, tip, ball) and sliders on the foot control",
          ('roll_break', 'foot_bank'), check_foot, run_foot, demo_foot, made=('Copy Rotation',)),
    Setup('curl', "Chains", "Chain Curl",
          "Turn the first bone and the rest of the chain curls with it. For tails, ears and hair.",
          "Select a chain of bones, from its root.", "a Chain Curl (Copy Rotation, local, add) down the chain",
          ('curl_follow', 'fade', 'curl_axes'), check_curl, run_curl, demo_curl, made=('Chain Curl',), edits=False),
    Setup('stretch', "Chains", "Stretch To",
          "The bone stretches to reach a target and keeps its volume. Good for squash and stretch.",
          "Select the target bone, then click the bone that stretches last.", "a Stretch To constraint",
          ('volume',), check_target, run_stretch, demo_target_move, made=('Stretch To',), edits=False),
    Setup('aim', "Helpers", "Aim at Target",
          "The bone always points at a target. For eyes, head aim and look-at.",
          "Select the target bone, then click the bone that aims last.", "a Damped Track (Y axis) and an Aim slider",
          ('aim_slider',), check_target, run_aim, demo_aim, made=('Aim',), edits=False),
    Setup('parent', "Helpers", "Parent Switch",
          "A control can follow Root, Pelvis, Chest or Head, picked with a slider.",
          "Select one control.", "an MCH parent bone with an Armature constraint, and an IK_Parent slider",
          (), check_parent, run_parent, demo_parent, made=('Parent Switch',)),
    Setup('follow', "Helpers", "Deform Follows",
          "Makes a DEF- copy that follows each control and takes over its weights (game-rig style split).",
          "Select the controls.", "a DEF- bone with Copy Transforms in Body Deform; the weights move to it",
          (), check_follow, run_follow, demo_follow, made=('Copy Transforms',)),
)
BY_ID = {setup.id: setup for setup in SETUPS}


def why_not(setup, sel, s):
    """Why `setup` can't run on the selection now ("" = ready)."""
    reason = bw.why_not(sel.rig, 'edit' if setup.edits else 'data')
    return reason or setup.check(sel, s)


def add(setup, sel, s, mirror=True):
    """Run the setup (and on the other side when mirror is on and the mirror bones are there). Returns report lines."""
    lines = setup.run(sel, s)
    other = sel.mirrored() if mirror else None
    if other is not None and not setup.check(other, s):
        lines += [f"Other side: {line}" for line in setup.run(other, s)]
    elif other is None and mirror and any(rn.has_side(n) for n in sel.names):
        lines.append("Other side: no mirror bones, done on this side only")
    return lines


def made_by(constraint_name):
    """The setup label that makes a constraint of this name, or "by hand"."""
    return next((setup.label for setup in SETUPS if constraint_name in setup.made), "by hand")


# ---------------------------------------------------------------- Try It
def apply_demo(rig, items, amount):
    """Pose the demo at `amount` (0..1) on top of the current pose."""
    for bone, kind, value in items:
        pb = rig.pose.bones.get(bone)
        if pb is None:
            continue
        if kind == 'move':
            pb.matrix = Matrix.Translation(Vector(value) * amount) @ pb.matrix
        elif kind == 'turn':
            axis, angle = value
            pb.matrix_basis = pb.matrix_basis @ Matrix.Rotation(angle * amount, 4, axis)
        elif kind == 'prop' and value[0] in pb:
            pb[value[0]] = type(pb[value[0]])(value[1] * amount) if isinstance(pb[value[0]], (int, float)) else value[1]
        bpy.context.view_layer.update()
