# SPDX-License-Identifier: GPL-3.0-or-later
"""Bendy Limbs: rubber-hose arms and legs for the Full Character Rig body (option bendy_limbs, body_rig calls in).

Each limb segment (upper arm, forearm, thigh, shin) gets one tweak control in its middle (`TWK-Upperarm.L`, in Limb
Tweak) and two deforming B-bones that replace the segment's own deform: `DEF-Upperarm1.L` from the segment start to the
tweak (Stretch To it) and `DEF-Upperarm2.L` from the tweak (Copy Location) to the next joint (Stretch To it). The tweak
is both halves' B-bone handle there, so moving it bows the segment in one smooth arc; its scale X/Z thickens the
middle, its scale Y makes the bend rounder or pointier. Across the elbow / knee the two halves are each other's
handle, eased by the limb's `RubberHose` slider (on the IK control): 0 = a crisp joint as without the option, 1 = the
whole limb bends as one curve.

The IK/FK chain bones keep their pose and only stop deforming, so IK, FK, the IK/FK snap and Stretchy Limbs see the
same rig as without the option. The forearm's second half hangs on Forearm2 and has the Hand as its end handle (4 segments, as the plain twist forearm), so the hand's roll twists it exactly as without the option (measured: 0 twist without the handle).
Bendy Limbs is a choice per limb (`MODES`: Off / Legs / Arms / Both). The hock of
a digitigrade leg stays one rigid bone. At the zero pose (tweaks unmoved, slider 0) every deform bone sits at rest.
The ONE source: sync_shared.py copies it next to body_rig.
"""
try:                                     # inside the add-on package
    from . import face_rig_core as fr, limb_rig as lr, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import face_rig_core as fr
    import limb_rig as lr
    import rig_names as rn

OPTION = 'bendy_limbs'                   # body_rig setting: one of MODES
MODES = ('OFF', 'LEGS', 'ARMS', 'BOTH')  # which limbs are bendy (the option's choices live in full_rig_spec)
LIMB_PARTS = {'arm': ('Upperarm', 'Forearm'), 'leg': ('Thigh', 'Shin')}
MODE_LIMBS = {'OFF': (), 'LEGS': ('leg',), 'ARMS': ('arm',), 'BOTH': ('arm', 'leg')}
SLIDER = 'RubberHose'                    # on the hand / foot IK control
SEGMENTS = 6                             # B-bone segments per deform half: a smooth arc
WRIST_SEGMENTS = lr.TWIST_SEGMENTS       # the forearm's wrist half: as many as the plain twist forearm (measured: same twist)
TWEAK_LENGTH = 0.25                      # tweak bone length, a share of its segment
TWEAK_SIZE = 0.025                       # tweak shape, a share of the body height
JOINT_HANDLE = 'ABSOLUTE'                # elbow / knee halves: each other's handle (TANGENT folds an S there)
JOINT_CUT = 0.5                          # slider 1: the joint point sits this share of the way to the tweaks' middle
JOINT_EASE = 1.0                         # B-bone ease at the elbow / knee with the slider at 1
SCALE_XZ = (True, False, True)           # the tweak's X/Z scale thickens the B-bones (Y goes to ease)


def mode_of(value):
    """The mode of a stored or given setting: older records kept True / False (True = both limbs)."""
    if isinstance(value, str):
        return value.upper() if value.upper() in MODES else 'OFF'
    return 'BOTH' if value else 'OFF'


def parts_of(mode):
    """The segment names (Upperarm, Forearm, Thigh, Shin) that are bendy in `mode`."""
    return tuple(part for limb in MODE_LIMBS[mode_of(mode)] for part in LIMB_PARTS[limb])


def segments(names, side, mode='BOTH'):
    """[(segment, first chain bone, last chain bone, what its second deform half stretches to, upper)] of one side's
    arm and leg: an upper segment's half ends on the lower segment's first half (the joint point), a lower one on the
    hand / foot / hock. Only the segments of the limbs bendy in `mode`."""
    n = lambda part, number=None, role='': rn.build(part, side, number, role)
    shin_end = n('Hock') if n('Hock') in names else n('Foot')
    every = [('Upperarm', n('Upperarm'), n('Upperarm'), n('Forearm', 1, 'DEF'), True),
             ('Forearm', n('Forearm', 1), n('Forearm', 2), n('Hand'), False),
             ('Thigh', n('Thigh'), n('Thigh'), n('Shin', 1, 'DEF'), True),
             ('Shin', n('Shin'), n('Shin'), shin_end, False)]
    return [seg for seg in every if seg[0] in parts_of(mode)]


def part_names(segment, side):
    """(tweak, first deform half, second deform half) of a segment."""
    return (rn.build(segment, side, role='TWK'), rn.build(segment, side, 1, 'DEF'), rn.build(segment, side, 2, 'DEF'))


def chain_bones(names, side, mode='BOTH'):
    return {bone for _, first, last, _, _ in segments(names, side, mode) for bone in (first, last)}


# ---------------------------------------------------------------- the bone list (body_rig.Body)
def add_specs(body, spec_bone):
    """Tweak + two deform halves per left segment of the bendy limbs; their chain bones stop deforming."""
    by_name = {s.name: s for s in body.specs}
    mode = body.t[OPTION]
    chain = chain_bones(by_name, 'L', mode)
    body.specs = [s._replace(deform=False) if s.name in chain else s for s in body.specs]
    for segment, first, last, _, _ in segments(by_name, 'L', mode):
        start, end, z = by_name[first].head, by_name[last].tail, by_name[first].z
        mid = by_name[first].tail if first != last else (start + end) / 2
        tweak, half1, half2 = part_names(segment, 'L')
        direction = (end - start).normalized() * (end - start).length * TWEAK_LENGTH
        body.specs += [spec_bone(tweak, mid, mid + direction, first, z=z),
                       spec_bone(half1, start, mid, first, deform=True, z=z, segments=SEGMENTS),
                       spec_bone(half2, mid, end, last, deform=True, z=z,
                                 segments=WRIST_SEGMENTS if segment == 'Forearm' else SEGMENTS)]


# ---------------------------------------------------------------- edit mode
def set_handle(eb, end, handle, ease, kind='TANGENT'):
    """One end of a B-bone: handle of this `kind` (or none), with this edit-mode ease."""
    setattr(eb, f'bbone_handle_type_{end}', kind if handle else 'AUTO')
    setattr(eb, f'bbone_custom_handle_{end}', handle)
    setattr(eb, f'bbone_ease{"in" if end == "start" else "out"}', ease)


def link_handles(rig, mode):
    """B-bone handles of every deform half: the tweak in the segment's middle, the other segment's half at the joint
    (ease 0 here: the RubberHose slider adds it in pose mode), the Hand at the forearm's wrist end, nothing at the shoulder / hip and the ankle."""
    E = rig.data.edit_bones
    for side in rn.SIDES:
        segs = segments(E.keys(), side, mode)
        for index, (segment, *_bones, upper) in enumerate(segs):
            partner = segs[index ^ 1][0]                 # upper arm <-> forearm, thigh <-> shin (a limb is always whole)
            tweak, half1, half2 = (E[n] for n in part_names(segment, side))
            other1, other2 = (E[n] for n in part_names(partner, side)[1:])
            set_handle(half1, 'start', None if upper else other2, 0.0, JOINT_HANDLE)
            set_handle(half2, 'end', other1 if upper else None, 0.0, JOINT_HANDLE)
            if segment == 'Forearm':                     # the hand's roll twists the forearm; a Stretch To alone loses it
                set_handle(half2, 'end', E[rn.build('Hand', side)], 0.0)
            set_handle(half1, 'end', tweak, 1.0)
            set_handle(half2, 'start', tweak, 1.0)
            half1.bbone_handle_use_scale_end = half2.bbone_handle_use_scale_start = SCALE_XZ
            half1.bbone_handle_use_ease_end = half2.bbone_handle_use_ease_start = True
            for eb in (tweak, half1, half2):
                eb.inherit_scale = 'FULL'


# ---------------------------------------------------------------- pose mode
def add_constraint(rig, pb, kind, name, target):
    c = pb.constraints.new(kind)
    c.name, c.target, c.subtarget = name, rig, target
    return c


def stretch_to(rig, pb, target):
    c = add_constraint(rig, pb, 'STRETCH_TO', 'Stretch To', target)
    c.volume, c.rest_length = 'NO_VOLUME', pb.bone.length


def drive(rig, path, expr, ctrl):
    lr.add_driver(rig, path, None, expr, {'r': f'{lr.bone_path(ctrl)}["{SLIDER}"]'})


def rig_joint(rig, ctrl, upper, lower):
    """The elbow / knee point of the deform halves slides from the joint (RubberHose 0) toward the middle of the two
    tweaks (1: JOINT_CUT of the way, where a curve tangent to both limb parts passes), so the limb rounds the joint in
    one curve instead of folding at it; the halves ease in there."""
    pose = rig.pose.bones
    upper_tweak, _, upper_half = part_names(upper, rn.side_of(ctrl))
    lower_tweak, lower_half, _ = part_names(lower, rn.side_of(ctrl))
    # two Copy Locations in a row put it at (1 - b)(1 - a) joint + (1 - b) a upper + b lower: CUT of the way to the
    # tweaks' middle at r = 1, with b = r CUT / 2 and a = b / (1 - b)
    cut = f'r * {JOINT_CUT / 2}'
    for name, tweak, expr in (('Rubber Upper', upper_tweak, f'{cut} / (1 - {cut})'), ('Rubber Lower', lower_tweak, cut)):
        add_constraint(rig, pose[lower_half], 'COPY_LOCATION', name, tweak)
        drive(rig, f'{lr.bone_path(lower_half)}.constraints["{name}"].influence', expr, ctrl)
    for half, ease in ((upper_half, 'bbone_easeout'), (lower_half, 'bbone_easein')):
        drive(rig, f'{lr.bone_path(half)}.{ease}', f'r * {JOINT_EASE}', ctrl)


def rig_segment(rig, segment, side, end_bone, H):
    """First half Stretch To the tweak; second half from the tweak (Copy Location) to `end_bone` (Stretch To)."""
    pose = rig.pose.bones
    tweak, half1, half2 = part_names(segment, side)
    stretch_to(rig, pose[half1], tweak)
    add_constraint(rig, pose[half2], 'COPY_LOCATION', 'Copy Location', tweak)
    stretch_to(rig, pose[half2], end_bone)
    fr.shape(pose[tweak], 'SelectionSphere', TWEAK_SIZE * H)


def rig_halves(rig, H, mode):
    """Constraints, the tweak shapes and the RubberHose slider (+ its drivers) on both sides, for the bendy limbs."""
    pose = rig.pose.bones
    for side in rn.SIDES:
        segs = segments(pose.keys(), side, mode)
        by_part = {seg[0]: seg for seg in segs}
        limbs = [(by_part[parts[0]], by_part[parts[1]], ctrl) for limb, ctrl in (('arm', 'Hand'), ('leg', 'Foot'))
                 for parts in (LIMB_PARTS[limb],) if limb in MODE_LIMBS[mode_of(mode)]]
        for (upper, *_u), (lower, *_l), part in limbs:
            ctrl = rn.build(part, side, role='IK')
            fr.switch(pose[ctrl], SLIDER, 0.0, 1.0, 'Rubber hose: 0 = a crisp elbow / knee, 1 = the limb rounds it in one '
                      'smooth curve. The TWK tweaks bow each part.', overshoot=1)
            rig_joint(rig, ctrl, upper, lower)            # first: the joint point moves before the halves stretch
        for segment, *_chain, end_bone, _upper in segs:
            rig_segment(rig, segment, side, end_bone, H)
    mechanism = rig.data.collections_all.get(lr.MECH)
    for name in (n for side in rn.SIDES for n in chain_bones(pose.keys(), side, mode)):
        if mechanism:                                   # IK-driven and no longer deforming, but still the FK bones
            mechanism.unassign(rig.data.bones[name])


def drop_sliders(rig, mode):
    """No RubberHose slider left on the IK control of a limb that is not bendy in `mode`."""
    for side in rn.SIDES:
        for part in [p for p, limb in (('Hand', 'arm'), ('Foot', 'leg')) if limb not in MODE_LIMBS[mode_of(mode)]]:
            pb = rig.pose.bones.get(rn.build(part, side, role='IK'))
            if pb:
                lr.drop_prop(pb, SLIDER)
