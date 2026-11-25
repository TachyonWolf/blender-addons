# SPDX-License-Identifier: GPL-3.0-or-later
"""Look rig: Digit's eye-look set-up, built on any face by the Eye Rig (face_rig_core, the `look` extra, on by default).
The ONE source; sync_shared.py copies it into Digit's Assorted Tools and Scripts/batch_tools.

Bones (Digit's names, docs/BONE_NAMES.md):
    MCH-HeadLookFocusParent   parentless helper: an Armature constraint picks what the look follows (LookFollow)
      HeadLookFocus           the look target, in front of the face on the Head's forward axis (Look collection)
        HeadLookBase          at eye height in the target's plane; child of HeadLookFocus, so it rolls with the head (a ring round both eyes)
          MCH-EyeFocus.L      driven: slides towards the middle as the target comes closer (Focus)
            EyeFocus.L        one eye's own target, straight ahead of the eye at rest
    Eye.L                     Damped Track "Look" to EyeFocus.L (the eye lids already follow the eye's turn)
      LookLine.L              a line from the eye to its target, like the IK pole lines (not clickable)
      Pupil.L > Iris.L        made when missing (deform, no weights: paint the eyeball's pupil on Pupil.L)
A body rig's own HeadLookFocus (Full Character Rig, Head Aim on) is reused, not moved.

Sliders on HeadLookFocus (the Rig panel shows them):
    LookFollow  0 Root / 1 Torso / 2 Neck: what the target rides with (Neck, not Head: the head aims at it)
    Focus       1 = both eyes on the target, 0 = parallel, above 1 = crossed, below 0 = wall-eyed. The eyes are
                parallel at rest, so the focus only shows while the target is nearer than its rest spot.
    HeadAim     how far the head turns to the target (body_rig's Head Aim; added here when the rig has none)
    PupilSize   scales Pupil.L / Pupil.R (the irises keep their size)
    IrisSize    scales Iris.L / Iris.R (children of the pupils: driven IrisSize / PupilSize, so each slider moves only its part)
At zero pose with the defaults every bone is exactly at rest. Nothing here runs in the background."""
import math

try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, face_rig_core as fr, limb_rig as lr, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import face_rig_core as fr
    import limb_rig as lr
    import rig_names as rn

from mathutils import Vector

FOCUS, BASE = 'HeadLookFocus', 'HeadLookBase'
FOLLOW_HELPER = rn.helper(FOCUS, 'Parent')          # MCH-HeadLookFocusParent
EYE_FOCUS, LINE = rn.left('EyeFocus'), rn.left('LookLine')
PUPIL, IRIS = rn.left('Pupil'), rn.left('Iris')
EYE_TRACK = 'Look'                                   # the Damped Track on each eye bone
LOOK_FOLLOW, FOCUS_PROP, PUPIL_SIZE, IRIS_SIZE = 'LookFollow', 'Focus', 'PupilSize', 'IrisSize'
FOLLOW_CHOICES = ('Root', 'Torso', 'Neck')
REACH = 2.5              # a new HeadLookFocus sits this many Head bone lengths in front of the head (Digit's: 2.55)
FOCUS_LENGTH = 0.06      # bone lengths (x cfg size)
SMALL = 0.03
PUPIL_LENGTH = 0.004
FOCUS_RANGE = (-3.0, 3.0)
PUPIL_RANGE = (0.05, 4.0)     # dot-small .. about as wide as the eye; a typed value may go further
IRIS_RANGE = (0.05, 4.0)
LOOK_HOME, MECH_HOME, EYE_HOME = 'Look', 'Mechanism', 'Eyes'
BODY_HOME = 'Torso'                                   # HeadLookFocus is in Look AND here (Show Bones Body / Face)


def sides(arm, eye_bone):
    """The eye bones (left, right) of the rig, or None when it lacks one."""
    names = (eye_bone, rn.with_side(eye_bone, 'R'))
    return names if all(n in arm.data.bones for n in names) else None


def has_look_rig(arm):
    """The rig has a look target the Look At tool can move."""
    return FOCUS in arm.data.bones


def head_forward(matrix):
    """(Damped Track axis name, the axis as a vector) of the Head bone axis closest to out of the face; `matrix`: the
    Head's rest rotation in armature space."""
    _, index, sign = max((sign * matrix.col[index].dot(fr.FWD), index, sign) for index in (0, 2) for sign in (1, -1))
    return ('TRACK_' + ('' if sign > 0 else 'NEGATIVE_') + 'XZ'[index // 2]), matrix.col[index] * sign


def eye_target_point(eye, base, forward):
    """Where an eye's target sits: on the eye bone's own line (so the eye rests unturned), in the base's plane."""
    along = eye.vector.normalized()
    facing = along.dot(forward)
    depth = (base - eye.head).dot(forward)
    return eye.head + along * (depth / facing if facing > 0.3 else depth)


def follow_targets(arm, head):
    """{choice: bone} of what HeadLookFocus can ride with, the ones the rig has (Neck = the Head's parent)."""
    names = arm.data.bones.keys()
    parent = arm.data.bones[head].parent
    if parent and parent.name == br.HEAD_AIM_BONE:         # the aim bone follows the target: ride what it hangs on
        parent = parent.parent
    found = {'Root': fr.root_bone(arm), 'Torso': rn.find(names, 'Chest'), 'Neck': parent.name if parent else None}
    return {choice: found[choice] for choice in FOLLOW_CHOICES if found[choice]}


# ---------------------------------------------------------------- bones (Edit Mode)
def make_bones(arm, cfg, eyes):
    """Every look bone; returns the names it made."""
    E, s, head = arm.data.edit_bones, cfg['size'], cfg['head']
    before = set(E.keys())
    head_bone = E[head]
    _, forward = head_forward(head_bone.matrix.to_3x3())
    if FOCUS not in E:
        focus = head_bone.head + forward * REACH * head_bone.length
        fr.mk(arm.data, FOCUS, focus, focus + forward * FOCUS_LENGTH * s).align_roll(Vector((0, 0, 1)))
    focus = E[FOCUS]
    br.head_aim_bone(arm.data, head)              # the head's aim mechanism (the face's own Head Aim hangs on it)
    helper = fr.mk(arm.data, FOLLOW_HELPER, focus.head, focus.tail, roll=focus.roll)
    focus.parent = helper
    left, right = (E[n] for n in eyes)
    middle = (left.head + right.head) / 2
    base = middle + forward * (focus.head - middle).dot(forward)
    fr.mk(arm.data, BASE, base, base + head_bone.vector.normalized() * SMALL * s, FOCUS, roll=head_bone.roll)
    points = {}
    for side, eye in zip(rn.SIDES, (left, right)):
        point = eye_target_point(eye, base, forward)
        tip = point + eye.vector.normalized() * SMALL * s
        points[side] = (point, tip) if side == 'L' else (fr.mirror(point), fr.mirror(tip))
    eye_roll = left.roll
    fr.both(arm.data, rn.mch(EYE_FOCUS), *points['L'], BASE, right=points['R'], roll=eye_roll)
    fr.both(arm.data, EYE_FOCUS, *points['L'], rn.mch(EYE_FOCUS), right=points['R'], roll=eye_roll)
    fr.both(arm.data, LINE, left.tail, points['L'][0], eyes[0], right=(fr.mirror(right.tail), points['R'][0]))
    if PUPIL not in E:
        tips = {'L': left.tail, 'R': fr.mirror(right.tail)}
        along = {'L': left.vector.normalized(), 'R': fr.mirror(right.vector.normalized())}
        pupil = {side: (tips[side], tips[side] + along[side] * PUPIL_LENGTH * s) for side in rn.SIDES}
        iris = {side: (pupil[side][1], pupil[side][1] + along[side] * PUPIL_LENGTH * s) for side in rn.SIDES}
        fr.both(arm.data, PUPIL, *pupil['L'], eyes[0], right=pupil['R'], deform=True, roll=eye_roll)
        fr.both(arm.data, IRIS, *iris['L'], PUPIL, right=iris['R'], deform=True, roll=eye_roll)
        for side in rn.SIDES:
            E[rn.with_side(IRIS, side)].inherit_scale = 'NONE'     # Pupil Size leaves the iris alone
    return sorted(set(E.keys()) - before)


# ---------------------------------------------------------------- pose
def drive_focus(arm, eyes, root, head):
    """MCH-EyeFocus.L slides towards HeadLookBase by Focus: 0 = the eyes parallel (rest), 1 = both eyes meet on the
    target, whatever its distance (Look At sets 1), above 1 crossed, below 0 wall-eyed."""
    P = arm.pose.bones
    for side, eye in zip(rn.SIDES, eyes):
        mch = rn.with_side(rn.mch(EYE_FOCUS), side)
        inward = arm.data.bones[mch].matrix_local.to_3x3().inverted() @ \
            (arm.data.bones[BASE].head_local - arm.data.bones[mch].head_local)
        for index in range(3):
            if abs(inward[index]) < 1e-6:
                continue
            fr.drive(P[mch], 'location', index, f'{inward[index]:.6f}*f', {'f': (FOCUS, FOCUS_PROP)})


def rig_pose(arm, cfg, eyes, made):
    P, head = arm.pose.bones, cfg['head']
    focus = P[FOCUS]
    for side, eye in zip(rn.SIDES, eyes):
        track = lr.get_constraint(P[eye], EYE_TRACK, 'DAMPED_TRACK')
        track.target, track.subtarget, track.track_axis = arm, rn.with_side(EYE_FOCUS, side), 'TRACK_Y'
        br.rig_pole_line(arm, rn.with_side(LINE, side), rn.with_side(EYE_FOCUS, side))
    lr.remove_constraint(arm, BASE, 'Copy Rotation')       # the base follows the target by parenting (so it rolls with the head)
    targets = follow_targets(arm, head)
    if targets:
        lr.rig_parent_switch(arm, {'ctrl': FOCUS, 'parent_bone': FOLLOW_HELPER}, targets, key=LOOK_FOLLOW)
    fr.switch(focus, FOCUS_PROP, *FOCUS_RANGE, 'Where the eyes meet: 0 = parallel (rest), 1 = both eyes on the '
              'target at any distance (Look At sets 1), above 1 = cross-eyed, below 0 = wall-eyed. Type any value',
              default=0.0, overshoot=None)
    rig_eye_sizes(arm)
    if br.HEAD_AIM_CONSTRAINT not in P[br.HEAD_AIM_BONE].constraints:
        axis = P[head].constraints.get(br.HEAD_AIM_CONSTRAINT)
        br.rig_head_aim(arm, head, axis.track_axis if axis else head_forward(arm.data.bones[head].matrix_local.to_3x3())[0])
        br.drive_head_aim(arm, head)
    drive_focus(arm, eyes, fr.root_bone(arm), head)
    shape_controls(arm, cfg, eyes, made)


def rig_eye_sizes(arm):
    """Pupil Size and Iris Size sliders on HeadLookFocus driving the Pupil / Iris bones (those that exist). Safe to run
    again, also on a finished rig."""
    P, focus = arm.pose.bones, arm.pose.bones[FOCUS]
    fr.switch(focus, PUPIL_SIZE, *PUPIL_RANGE, 'Size of both pupils (1 = as modelled). Type any value', default=1.0, overshoot=None)
    fr.switch(focus, IRIS_SIZE, *IRIS_RANGE, 'Size of both irises (1 = as modelled). Type any value', default=1.0, overshoot=None)
    for side in rn.SIDES:
        pupil, iris = rn.with_side(PUPIL, side), rn.with_side(IRIS, side)
        for index in range(3):
            if pupil in P:
                fr.drive(P[pupil], 'scale', index, 'p', {'p': (FOCUS, PUPIL_SIZE)})
            if iris in P and arm.data.bones[iris].inherit_scale == 'NONE':     # new rigs: the iris ignores the pupil's scale
                fr.drive(P[iris], 'scale', index, 'i', {'i': (FOCUS, IRIS_SIZE)})
            elif iris in P:    # older rigs: the iris takes the pupil's scale, so undo it
                fr.drive(P[iris], 'scale', index, 'i / max(p, 0.001)', {'i': (FOCUS, IRIS_SIZE), 'p': (FOCUS, PUPIL_SIZE)})


def shape_controls(arm, cfg, eyes, made):
    """Shapes, locks and collections: rings for the targets, lines for the look lines, MCH bones in Mechanism."""
    P, B, s = arm.pose.bones, arm.data.bones, cfg['size']
    spread = (B[eyes[0]].head_local - B[eyes[1]].head_local).length
    if FOCUS in made:
        fr.shape(P[FOCUS], 'WGT-Ring', 0.5 * spread)
    fr.shape(P[BASE], 'WGT-Ring', 1.0)
    P[BASE].custom_shape_scale_xyz = (spread, 1.0, 0.45 * spread)          # a flat ring round both eyes, facing out
    P[BASE].custom_shape_rotation_euler = (math.pi / 2, 0.0, 0.0)
    P[BASE].lock_rotation = (True, True, True)
    homes = {FOCUS: LOOK_HOME, BASE: LOOK_HOME, FOLLOW_HELPER: MECH_HOME}
    if br.HEAD_AIM_BONE in made:
        homes[br.HEAD_AIM_BONE] = MECH_HOME
    for side in rn.SIDES:
        side_name = lambda name: rn.with_side(name, side)
        fr.shape(P[side_name(EYE_FOCUS)], 'WGT-Ring', 0.18 * spread)
        fr.shape(P[side_name(LINE)], 'WGT-Line', B[side_name(LINE)].length)
        homes.update({side_name(EYE_FOCUS): LOOK_HOME, side_name(LINE): LOOK_HOME, side_name(rn.mch(EYE_FOCUS)): MECH_HOME})
        for name, size in ((PUPIL, fr.PUPIL_RING), (IRIS, fr.IRIS_RING)):
            if side_name(name) in made:
                fr.shape(P[side_name(name)], 'WGT-Ring', size * s)
                homes[side_name(name)] = EYE_HOME
    for name, home in homes.items():
        if name in made or name == FOCUS:
            bc.place_bone(arm, name, home, B[name].use_deform)
    if FOCUS in B:                                   # the look target shows with the Body controls too, not only Face
        bc.ensure_home(arm, BODY_HOME).assign(B[FOCUS])


def build(arm, cfg, log=print):
    """Add the look rig to a built Eye Rig (in place, safe to re-run). Returns the bones it made."""
    eyes = sides(arm, cfg['eye_bone'])
    if eyes is None or cfg['head'] not in arm.data.bones:
        log('M# look rig: no eye bones, skipped')
        return []
    with fr.in_mode(arm, 'EDIT'):
        made = make_bones(arm, cfg, eyes)
    with fr.in_mode(arm, 'POSE'):
        rig_pose(arm, cfg, eyes, made)
    log(f'M# look rig: {len(made)} bones')
    return made


# ---------------------------------------------------------------- removing
def remove(arm, gone):
    """Before the bones in `gone` are deleted: what kept bones aim at or read from them goes too (the eyes' Look,
    a Head Aim the face added, a kept Pupil's size drivers), so the rig is as before."""
    gone = set(gone)
    kept_focus = arm.pose.bones.get(FOCUS) if FOLLOW_HELPER in gone and FOCUS not in gone else None
    for key in (LOOK_FOLLOW, FOCUS_PROP, PUPIL_SIZE, IRIS_SIZE):       # a body's own HeadLookFocus loses the face's sliders
        if kept_focus is not None and key in kept_focus:
            del kept_focus[key]
    for pb in arm.pose.bones:
        if pb.name in gone:
            continue
        for constraint in [c for c in pb.constraints if getattr(c, 'subtarget', '') in gone]:
            lr.remove_constraint(arm, pb.name, constraint.name)
    drivers = arm.animation_data.drivers if arm.animation_data else []
    for fc in [fc for fc in drivers if reads_any(fc, gone)]:
        drivers.remove(fc)


def reads_any(fc, bones):
    """The driver reads a property or transform of one of `bones`."""
    for variable in fc.driver.variables:
        for target in variable.targets:
            if target.bone_target in bones or any(f'pose.bones["{bone}"]' in target.data_path for bone in bones):
                return True
    return False
