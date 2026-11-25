# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, wings: the Membrane surface (a bat or dragon wing). wing_rig builds the parts every wing type
shares (guides, wing arm, Fold layer, IK/FK, finger chains, weights); this module adds the skin between the fingers.
Bone-only: Armature, Copy Location and Stretch To constraints and one slider (Billow on WingBase).

Per gap between two neighbouring fingers (Lead | MidA, MidA | MidB, MidB | Root; named by the front finger):
    DEF-WingWebLead1.L ..   an in-between chain, joint for joint half way between the two fingers: each bone turns
                            like both neighbours' bones at 0.5 / 0.5 (Armature constraint), sits exactly half way
                            between their heads (Copy Location) and reaches for the next joint (Stretch To), so the
                            membrane bends smoothly between the fingers; its last bone reaches for the trailing edge
    MCH-WingEdgeLead.L      the trailing edge's middle, half way between the two finger tips
    MCH-WingBillowLead.L    ... under it, moved by Billow: in toward the wrist and out of the wing (sag, above 0) or
                            out toward the straight line (tight, below 0)
    DEF-WingEdgeLead1.L, 2  the trailing edge: front tip -> middle -> back tip, both halves Stretch To, one smooth
                            B-bone curve
A surface module gives wing_rig: plan (edit bones), rig (constraints and drivers per side), style, sliders, own_bones
and deform_chains. Ray Fin, Feathers and Arm Wings slot in as further surface modules (wing_rig.SURFACES).
"""
try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, limb_rig as lr, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import limb_rig as lr
    import rig_names as rn

BILLOW = 'billow'                        # the slider on WingBase
BILLOW_SHARE = 0.25                      # Billow 1 moves an edge middle this share of its gap's width
BILLOW_IN, BILLOW_OUT = 0.8, 0.6         # ... this much toward the wrist and this much out of the wing's plane
MID_SHARE = 0.2                          # MCH-WingEdge length / its gap's width
SEGMENTS = 3                             # B-bone segments of the in-between and edge bones


# ---------------------------------------------------------------- names
def gaps(spars):
    """[(front finger, back finger)] of neighbouring fingers, leading edge first."""
    return list(zip(spars, spars[1:]))


def web_chain(front, side, count):
    return [rn.build(f'WingWeb{front}', side, number, 'DEF') for number in range(1, count + 1)]


def edge_mid(front, side):
    return rn.build(f'WingEdge{front}', side, role='MCH')


def billow_name(front, side):
    return rn.build(f'WingBillow{front}', side, role='MCH')


def edge_bones(front, side):
    return [rn.build(f'WingEdge{front}', side, number, 'DEF') for number in (1, 2)]


def deform_chains(spars, count, side):
    """{key: deforming bones} the wing weights use, on top of the arm and fingers."""
    out = {}
    for front, _ in gaps(spars):
        out[f'Web{front}'] = web_chain(front, side, count)
        out[f'Edge{front}'] = edge_bones(front, side)
    return out


def own_bones(spars, count, side):
    return [n for chain in deform_chains(spars, count, side).values() for n in chain] + \
        [n for front, _ in gaps(spars) for n in (edge_mid(front, side), billow_name(front, side))]


def sliders():
    """(property, low, high, default, tooltip) of the sliders this surface puts on WingBase."""
    return [(BILLOW, -1.0, 1.0, 0.0, 'Billow: above 0 the trailing edge sags (the membrane fills like a sail), below 0 '
                                      'it pulls tight')]


# ---------------------------------------------------------------- build
def plan(lay, spars, chains):
    """Edit bones of the left side as (name, head, tail, parent, deform, connect); `chains` = {finger: its bones}. The
    in-between joints sit half way between the fingers' joints; the edge middle half way between the tips."""
    out = []
    for front, back in gaps(spars):
        front_points, back_points = lay.fingers[front], lay.fingers[back]
        web = [a.lerp(b, 0.5) for a, b in zip(front_points, back_points)]
        names = web_chain(front, 'L', len(web) - 1)
        out += [(name, web[k], web[k + 1], None, True, False) for k, name in enumerate(names)]
        middle = web[-1]
        mid_tail = middle + (web[-1] - web[-2]).normalized() * MID_SHARE * (back_points[-1] - front_points[-1]).length
        first, second = edge_bones(front, 'L')
        out += [(edge_mid(front, 'L'), middle, mid_tail, None, False, False),
                (billow_name(front, 'L'), middle, mid_tail, edge_mid(front, 'L'), False, False),
                (first, front_points[-1], middle, chains[front][-1], True, False),
                (second, middle, back_points[-1], billow_name(front, 'L'), True, False)]
    return out


def follow(arm, bone, targets):
    """Armature constraint: the (parentless) bone moves like skin weighted to `targets` {bone: weight}."""
    con = br.con(arm, bone, 'Follow', 'ARMATURE')
    con.targets.clear()
    for target_bone, weight in targets.items():
        target = con.targets.new()
        target.target, target.subtarget, target.weight = arm, target_bone, weight


def half_way(arm, bone, front, back, head_tail=0.0):
    """The bone's head goes exactly half way between two bones' heads (or tails, head_tail 1)."""
    for name, target, influence in (('Front', front, 1.0), ('Back', back, 0.5)):
        br.con(arm, bone, f'Copy Location {name}', 'COPY_LOCATION', target, head_tail=head_tail, influence=influence)


def stretch_to(arm, bone, target, head_tail=0.0):
    br.con(arm, bone, 'Stretch To', 'STRETCH_TO', target, head_tail=head_tail, volume='NO_VOLUME',
           rest_length=arm.data.bones[bone].length)


def smooth_join(arm, first, second):
    """Two bones meeting end to head bend as one B-bone curve there."""
    bones = arm.data.bones
    bones[first].bbone_segments = bones[second].bbone_segments = SEGMENTS
    bc.thin_bbones([bones[first], bones[second]])
    bones[first].bbone_handle_type_end, bones[first].bbone_custom_handle_end = 'ABSOLUTE', bones[second]
    bones[second].bbone_handle_type_start, bones[second].bbone_custom_handle_start = 'ABSOLUTE', bones[first]


def billow_move(lay, arm, front):
    """The left edge middle's move at Billow 1 (armature space): toward the in-between chain's start and out of the
    wing's plane."""
    bone = arm.data.bones[edge_mid(front, 'L')]
    width = bone.length / MID_SHARE
    inward = (arm.data.bones[web_chain(front, 'L', 1)[0]].head_local - bone.head_local).normalized()
    return (inward * BILLOW_IN + lay.hinge * BILLOW_OUT) * BILLOW_SHARE * width


def rig(arm, lay, spars, chains, side, sliders_bone):
    """Constraints and drivers of one side's membrane; `chains` = {finger: bones} of that side, `sliders_bone` = the
    bone holding Billow (WingBase)."""
    for front, back in gaps(spars):
        web = web_chain(front, side, len(chains[front]))
        mid, billow = edge_mid(front, side), billow_name(front, side)
        for k, name in enumerate(web):
            follow(arm, name, {chains[front][k]: 0.5, chains[back][k]: 0.5})
            half_way(arm, name, chains[front][k], chains[back][k])
            stretch_to(arm, name, web[k + 1] if k + 1 < len(web) else billow)
        for first, second in zip(web, web[1:]):
            smooth_join(arm, first, second)
        follow(arm, mid, {chains[front][-1]: 0.5, chains[back][-1]: 0.5})
        half_way(arm, mid, chains[front][-1], chains[back][-1], head_tail=1.0)
        first, second = edge_bones(front, side)
        stretch_to(arm, first, billow)
        stretch_to(arm, second, chains[back][-1], head_tail=1.0)
        smooth_join(arm, first, second)
        move = billow_move(lay, arm, front)
        if side == 'R':
            move.x = -move.x
        offset = arm.data.bones[billow].matrix_local.to_3x3().inverted() @ move       # in the bone's rest axes
        variables = {BILLOW: f'{lr.bone_path(sliders_bone)}["{BILLOW}"]'}
        for axis, amount in enumerate(offset):
            lr.add_driver(arm, f'{lr.bone_path(billow)}.location', axis, f'{BILLOW} * {amount:.6f}', variables)


def style(arm, spars, count, side):
    """Bone collections: the in-between and edge bones deform only, the edge middles are Mechanism."""
    for name in [n for chain in deform_chains(spars, count, side).values() for n in chain]:
        bc.place_bone(arm, name, None, True)
    for front, _ in gaps(spars):
        for name in (edge_mid(front, side), billow_name(front, side)):
            bc.place_bone(arm, name, bc.driven_home(False), False)
