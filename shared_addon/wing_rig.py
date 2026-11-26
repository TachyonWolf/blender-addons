# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, parts: wings. One shared wing for every wing type: a wing arm (upper arm, forearm, hand) from a
pivot on the shoulder blade with an IK tip control and an elbow pole like the arms (IK/FK switch with snap, Stretch,
Pole Follow: limb_rig; IK by default), a fan of finger chains from the wrist, a Fold layer under it all and the wing
weights. Each wing type adds its own surface part (SURFACES): Membrane (wing_membrane: bat / dragon) now; Ray Fin,
Feathers and Arm Wings slot in the same way. Rest pose = the wing as modelled. Bone-only: constraints and simple
drivers, no shape keys, no Actions. Names: docs/BONE_NAMES.md (Wings).

    wing = default_fan(joints, probe)                    # the template figure's wing, on the back
    mesh, verts = wing_vertices(arm, meshes, wing)       # a 'Wings' vertex group, else grown from the default lead tip
    wing = fit_fan(verts, wing_pivot(wing), fan_plane(wing)) if mesh else wing
    write_wing_guides(part_guides, wing)                 # guides: shoulder, elbow, wrist, a tip per finger, root edge
    report = build_wings(rig, wing_guide_fan(part_guides), dict(parent='Chest', wing_type='MEMBRANE'))
    wing_weights(rig, mesh, report)

A wing is {'Arm': [shoulder, elbow, wrist], 'Lead': [wrist, tip], 'MidA': .., 'MidB': .., 'Root': [shoulder, root-edge
point]} (armature space, left side; as_wing also reads the older pivot fan, every spar from the pivot). Per side:
    WingBase.L              the wing's root at the shoulder pivot, under Chest: turn it to turn the whole wing. Holds
                            the sliders: fold (0 as modelled, 1 folded), spread (-1 .. 1), auto_fan (0 .. 1, 0.5: the
                            fingers close that share with the elbow's bend) and the surface's (Membrane: billow)
    WingUpperarm.L, WingForearm.L, WingHand.L     the wing arm: FK controls, deform, B-bones; IK on the forearm
    IK-WingHand.L           the tip control: IK target; IK_FK (1 = IK, the default), IK_Stretch, PoleFollow; turning
                            it turns the hand
    IK-Pole-WingElbow.L     the elbow pole (follows the wing), IK-PoleLine-WingElbow.L its line
    WingFingers.L           one control at the wrist over the whole fan: rotate Z spreads / closes it, X curls the
                            fingers, Y twists them; each finger's base takes its FINGER_FOLLOW share (the lead least)
    WingLead1.L ..          part_chains finger chains (thin rings, B-bones, optional TWK- tweaks), always shown: they
                            add on top of WingFingers. WingRoot1.L .. runs from WingBase down the wing's root edge
    MCH-WingFoldUpperarm.L, MCH-WingFoldForearm.L  the arm as `fold` poses it: the FK bones add its turn, the IK
                            control rides it, so Fold folds the wing in IK and in FK and keys add on top
    MCH-WingFingersFold.L   under the hand: lays the finger bundle back along the forearm as the fan closes
    MCH-WingLead.L ..       one per wrist finger: the fan's turns (Fold, Auto Fan, Spread, WingFingers)
    MCH-WingRoot.L          the Root chain's base: stretches to MCH-WingRootTarget.L, which follows WingBase and the
                            upper arm half and half, so the membrane by the body moves with the arm
Shown in IK: WingBase, IK-WingHand, IK-Pole-WingElbow (+ its line, not selectable), WingFingers, the finger chains. In
FK: the arm bones ("FK Left Wing", shown by IK_FK) instead of the IK control and pole. Everything MCH is in Mechanism.
The fan drivers read the elbow's bend (the angle between upper arm and forearm), so the fan follows the arm the same
way whether the IK, the FK bones or the Fold slider bends it.
"""
import math

import bpy
from mathutils import Matrix, Vector

try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, chain_weights as cw, limb_rig as lr, part_chains as pc, \
        rig_names as rn, wing_membrane
    from .face_rig_core import both, shape, switch, wire_object
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import chain_weights as cw
    import limb_rig as lr
    import part_chains as pc
    import rig_names as rn
    import wing_membrane
    from face_rig_core import both, shape, switch, wire_object

SURFACES = {'MEMBRANE': wing_membrane}           # wing type (full_rig_spec.WING_TYPES) -> its surface module
DEFAULT_TYPE = 'MEMBRANE'
ARM = 'Arm'                                      # the wing arm's key in a wing, and its guide chain (WingArm1.L, 2)
SPARS = ('Lead', 'MidA', 'MidB', 'Root')         # the fingers: leading edge first, root edge last
HAND_SPARS = SPARS[:-1]                          # ... from the wrist, folding and spreading with the elbow; the Root
                                                 # finger runs from the shoulder down the wing's root edge, so the
                                                 # membrane by the body stays by the body (a bat's)
SPAR_BONES = 3                                   # bones per finger chain
ARM_PARTS = ('WingUpperarm', 'WingForearm', 'WingHand')
LEGACY_BONES = ('MCH-WingFingers.L',)            # bones of older builds that no longer exist (2026-11-16)
# the sliders on WingBase every wing type has: (property, low, high, default, tooltip)
SLIDERS = (('fold', 0.0, 1.0, 0.0, 'Fold the wing: 0 as modelled, 1 folded (in IK and in FK)'),
           ('spread', -1.0, 1.0, 0.0, 'Spread the fingers: above 0 the fan opens wider, below 0 it closes'),
           ('auto_fan', 0.0, 1.0, 0.5, 'Auto Fan: how much the fingers close by themselves as the elbow bends'))
FINGER_FOLLOW = {'Lead': 0.3, 'MidA': 0.65, 'MidB': 1.0}   # each finger's share of WingFingers' turn: lead least
ROOT_FOLLOW = 0.5                                # the root edge's tip follows this share of the upper arm's turn
FINGER_RING = 0.12                               # finger chain ring radius / the finger bone's length (thin)
FAN_SHAPE = 0.45                                 # WingFingers' shape reaches this share along each finger
# default fan on the template figure: spar angle above the outward line (degrees), length as a share of the span
DEFAULT_SPARS = {'Lead': (40.0, 1.0), 'MidA': (10.0, 0.85), 'MidB': (-20.0, 0.7), 'Root': (-50.0, 0.45)}
SPAN = 0.55                                      # default lead spar length / figure height
SWEEP = 0.35                                     # the default fan points out and this much back (+Y) per unit out
PIVOT_OUT = 0.35                                 # pivot x as a share of the shoulder's
PIVOT_UP = 0.75                                  # pivot height: this far from the chest up to the shoulder
BACK = 0.06                                      # pivot behind the chest line / figure height (no mesh to find the back)
WRIST_SHARE = 0.5                                # the wrist sits this share of the way along the leading edge from the
                                                 # pivot to the lead tip, the elbow half way to it (equal arm halves fold
                                                 # the wrist back to the shoulder)
REST_BEND = math.radians(12)                     # a laid-out elbow is bent at least this much (toward the trailing edge),
MIN_BEND = math.radians(5)                       # ... a dragged guide at least this much, so the IK knows its way
DEAD_ZONE = 1e-3                                 # radians: the fan ignores elbow bends this small (IK solver noise at rest)
HAND_SHARE = 0.3                                 # hand length / forearm length
ARM_SEGMENTS = 3                                 # B-bone segments of the upper arm and forearm
FOLD_DOWN = math.radians(70)                     # Fold 1: the upper arm swings to point this far below the outward
                                                 # level line in the wing plane (toward the trailing edge)
FOLD_BEND = math.radians(150)                    # ... and the elbow closes to this bend
FOLD_GAP = math.radians(15)                      # the closed finger bundle lies this far off the forearm
FOLD_CLOSE = 0.9                                 # the fan closes this share of the way when fully folded
OPEN_SHARE = 0.6                                 # ... and opens up to this share wider as the arm straightens (x Auto Fan)
SPREAD_SHARE = 0.3                               # Spread 1 opens the fan this share wider, -1 closes it as much
POLE_SHARE = 0.5                                 # the pole sits this share of the arm's reach off the elbow
BASE_SHARE = 0.5                                 # WingBase length / upper arm length
BASE_SHAPE = 0.8                                 # WingBase ring radius / its length
CTRL_SHAPE = 0.05                                # IK control sphere / pole size, as a share of the span
POLE_SHAPE = 0.025
RING_SHAPE = 0.3                                 # arm FK ring radius / the bone's length
EDGE_BAND = 0.04                                 # fit: the leading edge = wing vertices this share of the reach off the top
WING_GROUPS = ('Wings', 'Wing', 'Wing.{side}')   # a vertex group with one of these names marks the wing vertices
MIN_WING_VERTS = 8
BEHIND = 0.03                                    # wing vertices sit no further in front of the pivot than this / span
REACH = 1.3                                      # ... and no further from it than this x the default span
OUTER = 0.3                                      # fit_fan reads the wing's angle range beyond this share of its reach
TIP_BAND = 0.03                                  # ... and the lead tip from the vertices this close to the furthest reach
ROOT_SHARE = 0.05                                # the pivot of a fitted fan: the centroid of this share of the wing
                                                 # vertices nearest the default pivot
ROOT_CUT = 0.12                                  # the wing's root sphere radius / span: inside, the body (or Chest) holds
BLEND = 0.15                                     # ... and beyond it the wing takes over over this share of the span
FALLOFF = 0.05                                   # weights: a bone pulls 1 / (distance + FALLOFF x span) ^ PULL_POWER
PULL_POWER = 3


# ---------------------------------------------------------------- names
def base_name(side):
    return rn.build('WingBase', side)


def arm_names(side):
    """[upper arm, forearm, hand] of the wing arm."""
    return [rn.build(part, side) for part in ARM_PARTS]


def ik_name(side):
    return rn.build('WingHand', side, role='IK')


def pole_name(side):
    return rn.build('Pole-WingElbow', side, role='IK')


def pole_line_name(side):
    return rn.build(f'{br.POLE_LINE}-WingElbow', side, role='IK')


def fold_names(side):
    """[upper arm, forearm] of the Fold slider's MCH arm."""
    return [rn.build('WingFold' + part[len('Wing'):], side, role='MCH') for part in ARM_PARTS[:2]]


def fingers_name(side):
    """The WingFingers control over the whole fan."""
    return rn.build('WingFingers', side)


def fingers_fold_name(side):
    """The MCH bone under the hand that lays the finger bundle back as the fan closes."""
    return rn.helper(fingers_name(side), 'Fold')


def turn_name(spar, side):
    """The MCH bone a finger hangs on: a wrist finger's turns about the wrist, the Root finger's stretch."""
    return rn.build(pc.stem_of('wing', spar), side, role='MCH')


def root_target_name(side):
    return rn.build('WingRootTarget', side, role='MCH')


def finger_chain(spar, side):
    return pc.chain_names('wing', SPAR_BONES, side, spar)


def finger_chains(side):
    """{finger: its chain} of one side."""
    return {spar: finger_chain(spar, side) for spar in SPARS}


def mechanism_bones(side):
    """The shared MCH bones of one side."""
    return (fold_names(side) + [fingers_fold_name(side), root_target_name(side)]
            + [turn_name(spar, side) for spar in SPARS])


def own_bones(side, surface=None):
    """Every bone build_wings makes on one side except the finger chains (part_chains), the surface's included."""
    surface = surface or SURFACES[DEFAULT_TYPE]
    return ([base_name(side)] + arm_names(side) + [ik_name(side), pole_name(side), pole_line_name(side),
                                                   fingers_name(side)]
            + mechanism_bones(side) + surface.own_bones(SPARS, SPAR_BONES, side))


def wing_table():
    """The table limb_rig.upgrade takes for the wing arms (left side; the right is flipped): snap data and Stretch."""
    return dict(parents=dict(Root=rn.ROOT), limbs=[dict(ctrl=ik_name('L'), ik=arm_names('L')[1], tip=arm_names('L')[2])])


# ---------------------------------------------------------------- fan geometry
class Plane:
    """The wing's plane at the pivot: e1 points into the wing, e2 up along it, normal = e1 x e2. angle() and radius()
    are a point's polar coordinates in it (angle 0 along e1, growing toward e2)."""

    def __init__(self, pivot, into, normal):
        self.pivot = Vector(pivot)
        self.normal = Vector(normal).normalized()
        self.e1 = (into - self.normal * into.dot(self.normal)).normalized()
        self.e2 = self.normal.cross(self.e1)
        if self.e2.z < 0:                # e2 points up: the lead spar has the largest angle
            self.normal, self.e2 = -self.normal, -self.e2

    def angle(self, co):
        rel = co - self.pivot
        return math.atan2(rel.dot(self.e2), rel.dot(self.e1))

    def radius(self, co):
        rel = co - self.pivot
        return math.hypot(rel.dot(self.e1), rel.dot(self.e2))

    def direction(self, angle):
        return self.e1 * math.cos(angle) + self.e2 * math.sin(angle)


def wing_pivot(wing):
    """The shoulder pivot of a wing (of an older pivot fan: the lead spar's root)."""
    return wing[ARM][0] if ARM in wing else wing[SPARS[0]][0]


def fan_plane(wing):
    """The Plane of a wing (or pivot fan): through the pivot and the lead and root finger tips."""
    pivot = wing_pivot(wing)
    lead, root = wing[SPARS[0]][-1] - pivot, wing[SPARS[-1]][-1] - pivot
    return Plane(pivot, lead + root, lead.cross(root))


def fan_span(wing):
    """The furthest finger tip's distance from the pivot."""
    pivot = wing_pivot(wing)
    return max((wing[spar][-1] - pivot).length for spar in SPARS)


def signed_angle(a, b, axis):
    """The turn about `axis` that takes direction a to direction b (radians, counter-clockwise positive)."""
    return math.atan2(a.cross(b).dot(axis), a.dot(b))


def along(points, share):
    """The point `share` of the way along a polyline."""
    lengths = [(b - a).length for a, b in zip(points, points[1:])]
    left = share * sum(lengths)
    for a, b, length in zip(points, points[1:], lengths):
        if left <= length:
            return a.lerp(b, left / length) if length > 0 else a.copy()
        left -= length
    return points[-1].copy()


def bent_elbow(shoulder, elbow, wrist, trailing, least=REST_BEND):
    """The elbow moved off the shoulder-wrist line toward `trailing` (a point on the trailing side, the root tip) until
    the arm bends at least `least` there: the IK then always folds the wing the same way."""
    axis = (wrist - shoulder).normalized()
    foot = shoulder + axis * (elbow - shoulder).dot(axis)
    away = trailing - shoulder
    away = (away - axis * away.dot(axis)).normalized()
    off = (elbow - foot).dot(away)
    inner, outer = max((foot - shoulder).length, 1e-6), max((wrist - foot).length, 1e-6)
    needed = math.tan(least) * inner * outer / (inner + outer)
    return elbow + away * (max(off, needed) - off)


def figure_height(joints):
    zs = [v.z for v in joints.values() if isinstance(v, Vector)]
    return max(zs) - min(zs)


def default_pivot(joints, probe=None):
    """Behind the chest, between the shoulder blades: on the back surface when a body `probe` finds it."""
    chest, shoulder = joints['chest'], joints['shoulder']
    inner = Vector((PIVOT_OUT * shoulder.x, chest.y, chest.z + PIVOT_UP * (shoulder.z - chest.z)))
    back = Vector((0, 1, 0))
    reach = probe.exit_distance(inner, back, 1.0) if probe is not None and probe.inside(inner) else None
    return inner + back * (reach if reach else BACK * figure_height(joints))


def default_fan(joints, probe=None):
    """The wing for a figure (body guide joints, left side): spread out and up from the back, swept back a little."""
    pivot = default_pivot(joints, probe)
    span = SPAN * figure_height(joints)
    plane = Plane(pivot, Vector((1, SWEEP, 0)), Vector((1, SWEEP, 0)).cross(Vector((0, 0, 1))))
    fan = {spar: [pivot, pivot + plane.direction(math.radians(degrees)) * span * share]
           for spar, (degrees, share) in DEFAULT_SPARS.items()}
    return wing_from_fan(fan)


def wing_from_fan(fan, cos=None):
    """A wing from a fan of spars that all start at the pivot (fit_fan, the default wing, an older build): the wrist
    along the lead spar (along the wing vertices' leading edge `cos` when given, then on their surface), the elbow half
    way to it (equal halves fold the wrist back to the shoulder), bent in the wing's plane; the fingers from the wrist
    to the spar tips."""
    pivot, tips = fan[SPARS[0]][0], {spar: fan[spar][-1] for spar in SPARS}
    plane = fan_plane(fan)
    edge = leading_edge(cos, plane, tips[SPARS[0]]) if cos else fan[SPARS[0]]
    wrist = along(edge, WRIST_SHARE)
    if cos:
        wrist = on_surface(cos, wrist, plane.normal, EDGE_BAND * plane.radius(tips[SPARS[0]]))
    elbow = bent_elbow(pivot, pivot.lerp(wrist, 0.5), wrist, pivot + plane.direction(plane.angle(tips[SPARS[-1]])))
    return as_wing({ARM: [pivot, elbow, wrist], **tips})


def as_wing(wing):
    """A wing (fresh Vectors, each finger from its root: finger_root) from a wing, {spar: tip or [.., tip]} plus the
    arm, or an older pivot fan."""
    if ARM not in wing:
        pivot = sum((Vector(pts[0]) for pts in wing.values()), Vector()) / len(wing)
        return wing_from_fan({spar: [pivot, Vector(wing[spar][-1])] for spar in SPARS})
    arm = [Vector(p) for p in wing[ARM][:3]]
    tip = lambda value: Vector(value[-1] if isinstance(value[0], (list, tuple, Vector)) else value)
    return {ARM: arm, **{spar: [finger_root(arm, spar), tip(wing[spar])] for spar in SPARS}}


def finger_root(arm, spar):
    """Where a finger starts: the wrist, the Root finger the shoulder."""
    return (arm[2] if spar in HAND_SPARS else arm[0]).copy()


# ---------------------------------------------------------------- finding the wing on the mesh
def side_coords(arm, mesh, side, group=None):
    """{vertex index: armature-space co} of one side's vertices (of `group`, if given), the right side's mirrored onto
    the left, so the left-side wing fits both."""
    verts = pc.part_vertices(arm, mesh, group)
    if side == 'R':
        return {i: pc.mirror_x(co) for i, co in verts.items() if co.x < 0}
    return {i: co for i, co in verts.items() if co.x > 0}


def grouped_wing(arm, meshes, side='L'):
    """(mesh, {index: co}) of one wing marked by a WING_GROUPS vertex group, or (None, {})."""
    for mesh in meshes:
        group = next((g.format(side=side) for g in WING_GROUPS if g.format(side=side) in mesh.vertex_groups), None)
        if group:
            verts = side_coords(arm, mesh, side, group)
            if len(verts) >= MIN_WING_VERTS:
                return mesh, verts
    return None, {}


def grown_wing(arm, meshes, wing, side='L'):
    """(mesh, {index: co}) of one wing (left-side coordinates) grown along the mesh from the vertex nearest the wing's
    lead tip. A wing on its own (its whole mesh island lies outward of the pivot, not in front of the back, within
    reach): that island. A wing joined to the body: grown through such vertices outside the root sphere (ROOT_CUT), so
    it stops at the root and never walks over the back; the root inside keeps the body's weights. (None, {}) when no
    mesh is near the wing."""
    plane, span = fan_plane(wing), fan_span(wing)
    tip = wing[SPARS[0]][-1]
    best = None
    for mesh in meshes:
        verts = side_coords(arm, mesh, side)
        if not verts:
            continue
        nearest = min(verts, key=lambda i: (verts[i] - tip).length)
        if best is None or (verts[nearest] - tip).length < best[2]:
            best = (mesh, verts, (verts[nearest] - tip).length, nearest)
    if best is None or best[2] > 0.5 * span:
        return None, {}
    mesh, verts, _, seed = best
    allowed = {i for i, co in verts.items()
               if (co - plane.pivot).dot(plane.e1) > -BEHIND * span and co.y > plane.pivot.y - BEHIND * span
               and (co - plane.pivot).length < REACH * span} | {seed}
    island = pc.grow(mesh, set(verts), [seed])
    if not island <= allowed:            # joined to the body: grow outside the root sphere only, so it stops there
        allowed = {i for i in allowed if (verts[i] - plane.pivot).length > ROOT_CUT * span} | {seed}
        island = pc.grow(mesh, allowed, [seed])
    return mesh, {i: verts[i] for i in island}


def wing_vertices(arm, meshes, wing, side='L'):
    """(mesh, {index: armature-space co, mirrored onto the left for 'R'}) of one wing: the WING_GROUPS vertex group
    when a mesh has one (the sure way for a wing joined to the body), else grown from the (left-side) wing
    (grown_wing). (None, {}) = no wing mesh."""
    mesh, verts = grouped_wing(arm, meshes, side)
    if mesh is None and wing is not None:
        mesh, verts = grown_wing(arm, meshes, wing, side)
    return (mesh, verts) if len(verts) >= MIN_WING_VERTS else (None, {})


def fit_fan(verts, near_pivot, guess_plane=None):
    """A wing fitted to wing vertices ({index: co}, left side): the pivot at the root (root_point), the lead tip where
    the wing reaches furthest, the other finger tips spread evenly from there down the wing's angle range in its plane,
    each where the wing reaches furthest at its angle; the arm along the leading edge to the wrist (wing_from_fan)."""
    cos = list(verts.values())
    pivot = root_point(cos, near_pivot)
    mean = sum(cos, Vector()) / len(cos)
    normal = flat_normal(cos) or (guess_plane.normal if guess_plane else Vector((0, -1, 0)))
    plane = Plane(pivot, mean - pivot, normal)
    polar = [(plane.angle(c), plane.radius(c), c) for c in cos]
    reach = max(r for _, r, _ in polar)
    angles = sorted(a for a, r, _ in polar if r > OUTER * reach)       # near the pivot the angle says nothing
    outermost = [c for _, r, c in polar if r >= (1 - TIP_BAND) * reach]
    lead_tip = sum(outermost, Vector()) / len(outermost)
    top, low = plane.angle(lead_tip), angles[int(0.03 * (len(angles) - 1))]
    window = 0.5 * (top - low) / (len(SPARS) - 1)
    fan = {SPARS[0]: [pivot, lead_tip]}
    for k, spar in enumerate(SPARS[1:], 1):
        angle = top - k * (top - low) / (len(SPARS) - 1)
        near = [(r, c) for a, r, c in polar if abs(a - angle) <= window]
        length = sorted(r for r, _ in near)[int(0.98 * (len(near) - 1))] if near else plane.radius(mean)
        fan[spar] = [pivot, spar_tip(plane, near, angle, length, length / SPAR_BONES)]
    return wing_from_fan(fan, cos)


def root_point(cos, near_pivot):
    """The wing's pivot: the centroid of its vertices nearest `near_pivot`; `near_pivot` itself when the wing stops
    short of it (a joined wing found without its root sphere: the root is in the body)."""
    nearest = sorted(cos, key=lambda c: (c - near_pivot).length)
    reach = (nearest[-1] - near_pivot).length
    if (nearest[0] - near_pivot).length > 0.5 * ROOT_CUT * reach:
        return near_pivot.copy()
    count = max(3, int(ROOT_SHARE * len(cos)))
    return sum(nearest[:count], Vector()) / count


def spar_tip(plane, near, angle, radius, step):
    """A finger tip: the centroid of the outermost wing vertices near its angle, or the point in the plane."""
    ring = [c for r, c in near if r >= radius - 0.5 * step]
    return sum(ring, Vector()) / len(ring) if ring else plane.pivot + plane.direction(angle) * radius


def leading_edge(cos, plane, tip, rings=12):
    """The wing's top outline from the pivot to the lead tip: per ring around the pivot, the centroid of the vertices
    within EDGE_BAND x the reach of the ring's top (largest angle), so the arm follows the wing's front frame."""
    reach = plane.radius(tip)
    step, band = reach / rings, EDGE_BAND * reach
    polar = [(plane.radius(c), plane.angle(c), c) for c in cos]
    points = [plane.pivot.copy()]
    for k in range(1, rings):
        radius = k * step
        ring = [(a, c) for r, a, c in polar if abs(r - radius) <= 0.5 * step]
        if ring:
            top = max(a for a, _ in ring)
            edge = [c for a, c in ring if a >= top - band / radius]
            points.append(sum(edge, Vector()) / len(edge))
    return points + [tip.copy()]


def on_surface(cos, point, normal, radius):
    """The point moved along `normal` onto the mean of the vertices within `radius` (the membrane's surface)."""
    near = [c for c in cos if (c - point).length <= radius]
    if not near:
        return point.copy()
    mean = sum(near, Vector()) / len(near)
    return point + normal * (mean - point).dot(normal)


def flat_normal(cos):
    """The thinnest direction of the points (the membrane's normal), or None when they are not flat."""
    mean = sum(cos, Vector()) / len(cos)
    rel = [c - mean for c in cos]
    length = pc.principal_axis(rel)
    width = pc.principal_axis([r - length * r.dot(length) for r in rel])
    normal = length.cross(width).normalized()
    spread = lambda axis: math.sqrt(sum(r.dot(axis) ** 2 for r in rel) / len(rel))
    return normal if spread(normal) <= 0.5 * spread(width) else None


# ---------------------------------------------------------------- guides
def write_wing_guides(guides, wing):
    """The wing guides in the part guide armature, both sides: the arm (shoulder -> elbow -> wrist: WingArm1.L,
    WingArm2.L) and one bone per finger from its root to its tip (WingLead1.L ..): the wrist fingers connected to the
    arm's wrist, so dragging it takes their roots along; the Root finger from the shoulder. Older per-joint finger
    guides (WingLead2.L ..) go."""
    wing = as_wing(wing)
    pc.write_guides(guides, 'wing', wing[ARM], ARM)
    for spar in SPARS:
        pc.write_guides(guides, 'wing', wing[spar], spar)
    with pc.sb.Kept(guides) as k:
        E = k.edit()
        for side in ('L', 'R'):
            pc.drop_bones(E, [n for spar in SPARS for n in pc.chain_names('wing', 8, side, spar)[1:]])
            upper, fore = (E[n] for n in pc.chain_names('wing', 2, side, ARM))
            for spar in SPARS:
                finger = E[pc.chain_names('wing', 1, side, spar)[0]]
                finger.parent, finger.use_connect = (fore, True) if spar in HAND_SPARS else (upper, False)
        k.done()


def wing_guide_fan(guides):
    """The wing read back from the wing guides (where the user dragged them), or None when there are none. Older
    guides (a chain per spar from the pivot) read as a pivot fan."""
    points = {spar: pc.guide_points(guides, 'wing', spar) for spar in SPARS}
    if any(pts is None for pts in points.values()):
        return None
    arm_points = pc.guide_points(guides, 'wing', ARM)
    if arm_points is None or len(arm_points) < 3:
        pivot = sum((pts[0] for pts in points.values()), Vector()) / len(points)
        return as_wing({spar: [pivot, pts[-1]] for spar, pts in points.items()})
    return as_wing({ARM: arm_points[:3], **points})


# ---------------------------------------------------------------- build
def folded_bend(upper, fore):
    """The elbow's bend at Fold 1: FOLD_BEND, less when the forearm is so much longer than the upper arm that the
    wrist would pass the shoulder (the IK pole flips there): the upper arm stays within 80 degrees of the wrist."""
    least_inner = math.acos(min(1.0, math.cos(math.radians(10)) * upper / fore))  # inner elbow angle keeping it so
    return min(FOLD_BEND, math.pi - least_inner)


class Layout:
    """Where one (left) wing's bones go, and the angles its fold drivers use. The hinge (the arm bones' local X) is the
    arm's bend axis: a turn about it closes the elbow, so every fold turn is a local X rotation."""

    def __init__(self, wing):
        shoulder, elbow, wrist = wing[ARM]
        self.tips = {spar: wing[spar][-1] for spar in SPARS}
        elbow = bent_elbow(shoulder, elbow, wrist, self.tips[SPARS[-1]], MIN_BEND)
        self.shoulder, self.elbow, self.wrist = shoulder, elbow, wrist
        upper, fore = elbow - shoulder, wrist - elbow
        self.hinge = upper.cross(fore).normalized()
        self.rest_bend = upper.angle(fore)
        lead = self.tips[SPARS[0]] - wrist
        self.hand_tip = wrist + lead.normalized() * HAND_SHARE * fore.length
        roots = {spar: finger_root([shoulder, elbow, wrist], spar) for spar in SPARS}
        self.fingers = {spar: [roots[spar].lerp(tip, k / SPAR_BONES) for k in range(SPAR_BONES + 1)]
                        for spar, tip in self.tips.items()}
        self.toward_lead = {spar: signed_angle(self.tips[spar] - wrist, lead, self.hinge) for spar in HAND_SPARS}
        self.flex = signed_angle(fore, lead, self.hinge) + math.pi - FOLD_GAP   # lays the lead finger back along the forearm
        self.fold_bend = folded_bend(upper.length, fore.length) - self.rest_bend
        level = Vector((1, 0, 0)) - self.hinge * self.hinge.x          # outward and level, in the arm's plane
        down = level.normalized() if level.length > 1e-6 else upper.normalized()
        down_side = -1 if signed_angle(fore, self.tips[SPARS[-1]] - wrist, self.hinge) < 0 else 1
        target = Matrix.Rotation(down_side * FOLD_DOWN, 3, self.hinge) @ down
        self.fold_upper = signed_angle(upper, target, self.hinge)       # the turn that swings the upper arm there
        reach = wrist - shoulder
        self.pole = elbow + reach.normalized().cross(self.hinge) * POLE_SHARE * reach.length
        self.span = max((tip - shoulder).length for tip in self.tips.values())
        fan = sum(((self.tips[spar] - wrist).normalized() for spar in HAND_SPARS), Vector())
        self.fan_tip = wrist + fan.normalized() * HAND_SHARE * fore.length            # WingFingers points into the fan

    def z(self, head, tail):
        """The roll rule of every wing bone: local X along the hinge."""
        return br.hinge_z(self.hinge, head, tail)

    def finger_up(self, spar):
        return self.z(self.fingers[spar][0], self.tips[spar])


def pair(A, name, head, tail, parent, z, deform=False, connect=False):
    """A left bone with its local Z toward `z` and its right mirror (face_rig_core.both)."""
    left, right = both(A, name, head, tail, parent, deform=deform, connect=connect)
    left.align_roll(z)
    right.roll = -left.roll
    return left


def make_bones(arm, lay, parent):
    """Edit mode: the wing arm, its fold arm, the IK control and pole, the finger fan's MCH bones, WingFingers and the
    root edge's MCH bones (both sides). Bones of older builds that no longer exist go."""
    upper, fore, hand = arm_names('L')
    fold_upper, fold_fore = fold_names('L')
    base_tail = lay.shoulder.lerp(lay.elbow, BASE_SHARE)
    bend = (lay.pole - lay.elbow).normalized()
    hand_length = (lay.hand_tip - lay.wrist).length
    root_tip = lay.tips[SPARS[-1]]
    bones = [  # name, head, tail, parent, deform, connect, local Z
        (base_name('L'), lay.shoulder, base_tail, parent, False, False, None),
        (upper, lay.shoulder, lay.elbow, base_name('L'), True, False, None),
        (fore, lay.elbow, lay.wrist, upper, True, True, None),
        (hand, lay.wrist, lay.hand_tip, fore, True, True, None),
        (fold_upper, lay.shoulder, lay.elbow, base_name('L'), False, False, None),
        (fold_fore, lay.elbow, lay.wrist, fold_upper, False, True, None),
        (ik_name('L'), lay.wrist, lay.hand_tip, fold_fore, False, False, None),
        (pole_name('L'), lay.pole, lay.pole + bend * CTRL_SHAPE * lay.span, None, False, False, None),
        (pole_line_name('L'), lay.elbow, lay.pole, upper, False, False, None),
        (fingers_fold_name('L'), lay.wrist, lay.hand_tip, hand, False, False, None),
        (fingers_name('L'), lay.wrist, lay.fan_tip, hand, False, False, lay.hinge),   # Z = the hinge: rotate Z spreads
        (turn_name(SPARS[-1], 'L'), lay.shoulder, root_tip, base_name('L'), False, False, None),
        (root_target_name('L'), root_tip, root_tip + (root_tip - lay.shoulder).normalized() * hand_length, None,
         False, False, None),
    ] + [(turn_name(spar, 'L'), lay.wrist, lay.wrist + (tip - lay.wrist).normalized() * hand_length,
          fingers_fold_name('L'), False, False, None) for spar, tip in lay.tips.items() if spar in HAND_SPARS]
    with pc.sb.Kept(arm) as k:
        E = k.edit()
        pc.drop_bones(E, [rn.with_side(name, side) for name in LEGACY_BONES for side in ('L', 'R')])
        for name, head, tail, up, deform, connect, z in bones:
            pair(arm.data, name, head, tail, up, z if z is not None else lay.z(head, tail), deform, connect)
        k.done()


def make_surface_bones(arm, lay, surface):
    """Edit mode, after the finger chains: the wing type's surface bones (both sides)."""
    with pc.sb.Kept(arm) as k:
        k.edit()
        for name, head, tail, up, deform, connect in surface.plan(lay, SPARS, finger_chains('L')):
            pair(arm.data, name, head, tail, up, lay.z(head, tail), deform, connect)
        k.done()


def strip_wings(arm, surface):
    """An earlier build's rigging comes off (Stretch, constraints, drivers, the sliders' old home), so a re-run builds
    the same way."""
    ctrl = arm.pose.bones.get(ik_name('L'))
    if ctrl is not None and 'Limb' in ctrl:
        limbs, _ = lr.limbs_of(arm, wing_table())
        for limb in limbs:
            lr.remove_features(arm, limb, ('stretch',))
    for side in ('L', 'R'):
        for key in ('fold', 'spread'):                       # on the IK control before 2026-11-16
            if arm.pose.bones.get(ik_name(side)) is not None:
                lr.drop_prop(arm.pose.bones[ik_name(side)], key)
    br.clear_rigging(arm, [n for side in ('L', 'R') for n in own_bones(side, surface)])


def sliders(surface):
    """(property, low, high, default, tooltip) of every slider on WingBase: the shared ones, then the surface's."""
    return list(SLIDERS) + surface.sliders()


def rig_side(arm, lay, side, surface):
    """Constraints and sliders of one wing. Returns (IK bone, IK constraint) for the pole angle fit."""
    P = arm.pose.bones
    upper, fore, hand = arm_names(side)
    ctrl, pole, base = ik_name(side), pole_name(side), base_name(side)
    switch(P[ctrl], 'IK_FK', 0.0, 1.0, 'IK (1) or FK (0): the wing tip control, or the wing bones themselves', 1.0,
           overshoot=1)
    for key, low, high, default, tip in sliders(surface):
        switch(P[base], key, low, high, tip, default, overshoot=1)
    for bone, fold in zip((upper, fore), fold_names(side)):
        br.con(arm, bone, 'Fold', 'COPY_ROTATION', fold, owner_space='LOCAL', target_space='LOCAL', mix_mode='BEFORE')
    con = br.ik(arm, fore, ctrl, 2, pole)
    P[fore].lock_ik_y = P[fore].lock_ik_z = True
    br.con(arm, hand, 'IK Turn', 'COPY_ROTATION', ctrl, owner_space='LOCAL', target_space='LOCAL', mix_mode='BEFORE')
    if rn.ROOT in arm.data.bones:
        br.rig_pole_follow(arm, pole, ctrl, {fold_names(side)[0]: 1.0})
    br.rig_pole_line(arm, pole_line_name(side), pole)
    rig_root_edge(arm, side)
    for name in fold_names(side) + [fingers_fold_name(side)] + [turn_name(spar, side) for spar in HAND_SPARS]:
        P[name].rotation_mode = 'XYZ'
    P[fingers_name(side)].rotation_mode = 'XYZ'
    surface.rig(arm, lay, SPARS, finger_chains(side), side, base)
    return fore, con


def rig_root_edge(arm, side):
    """The root edge's tip follows a point between WingBase and the upper arm (ROOT_FOLLOW of the arm's turn), so the
    membrane by the body moves with the arm: MCH-WingRoot (the Root finger's base) stretches to that point."""
    target, root = root_target_name(side), turn_name(SPARS[-1], side)
    con = br.con(arm, target, 'Follow', 'ARMATURE')
    con.targets.clear()
    for bone, weight in ((base_name(side), 1 - ROOT_FOLLOW), (arm_names(side)[0], ROOT_FOLLOW)):
        entry = con.targets.new()
        entry.target, entry.subtarget, entry.weight = arm, bone, weight
    br.con(arm, root, 'Stretch To', 'STRETCH_TO', target, volume='NO_VOLUME', rest_length=arm.data.bones[root].length)


def style_side(arm, lay, side, surface):
    """Control shapes and bone collections of one wing. The finger chains (part_chains: Wings) stay shown in IK and FK;
    the arm bones go into the FK collection later (limb_rig)."""
    P, B = arm.pose.bones, arm.data.bones
    shape(P[base_name(side)], 'WGT-Ring', BASE_SHAPE * B[base_name(side)].length)
    shape(P[ik_name(side)], 'SelectionSphere', CTRL_SHAPE * lay.span)
    shape(P[pole_name(side)], 'WGT-Ico', POLE_SHAPE * lay.span)
    shape(P[pole_line_name(side)], 'WGT-Line', B[pole_line_name(side)].length)
    fan_shape(arm, side)
    for name in (base_name(side), ik_name(side), pole_name(side), pole_line_name(side), fingers_name(side)):
        bc.place_bone(arm, name, 'Wings', False)
    for name in arm_names(side):
        shape(P[name], 'WGT-Ring', RING_SHAPE * B[name].length)
        bc.place_bone(arm, name, None, True)
    for name in mechanism_bones(side):
        bc.place_bone(arm, name, bc.driven_home(False), False)
    surface.style(arm, SPARS, SPAR_BONES, side)


def fan_shape(arm, side):
    """WingFingers' shape: a line out along each wrist finger (FAN_SHAPE of its length) and an arc through their ends,
    drawn in the control's own space, so it covers the fan."""
    name = rn.build('WGT-WingFingers', side)
    bone = arm.data.bones[fingers_name(side)]
    to_bone = bone.matrix_local.inverted()
    ends = []
    for spar in HAND_SPARS:
        chain = finger_chain(spar, side)
        root, tip = arm.data.bones[chain[0]], arm.data.bones[chain[-1]]
        ends.append(to_bone @ root.head_local.lerp(tip.tail_local, FAN_SHAPE))
    verts = [Vector()] + ends
    edges = [(0, k) for k in range(1, len(verts))] + [(k, k + 1) for k in range(1, len(verts) - 1)]
    old = bpy.data.objects.get(name)
    if old is not None:
        bpy.data.objects.remove(old)
    widget = wire_object(name, [tuple(v) for v in verts], edges)
    pb = arm.pose.bones[fingers_name(side)]
    pb.custom_shape, pb.use_custom_shape_bone_size = widget, False
    pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)


def finger_drivers(arm, lay, side):
    """The finger fan: it closes with Fold (fully) and with the elbow's bend (Auto Fan's share: 0 at rest .. 1 at
    FOLD_BEND), opens a little as the arm straightens (Auto Fan), Spread opens or closes it, and WingFingers turns each
    finger's base at its own share (FINGER_FOLLOW: the lead least): Z spreads, X curls, Y twists."""
    P = lr.bone_path
    upper, fore, _ = arm_names(side)
    base, control = P(base_name(side)), fingers_name(side)
    variables = {'bend': ('ROTATION_DIFF', upper, fore), 'fold': f'{base}["fold"]', 'auto': f'{base}["auto_fan"]',
                 'spread': f'{base}["spread"]'}
    bent = f'max(bend - {lay.rest_bend + DEAD_ZONE:.6f}, 0) * {1 / lay.fold_bend:.6f}'
    close = f'max(fold, auto * {bent})'
    opening = f'auto * min(bend - {lay.rest_bend - DEAD_ZONE:.6f}, 0) * {1 / max(lay.rest_bend, MIN_BEND):.6f}'
    lr.add_driver(arm, f'{P(fingers_fold_name(side))}.rotation_euler', 0, f'{-lay.flex:.6f} * {close}', variables)
    turns = {**variables, **{axis: ('TRANSFORMS', control, f'ROT_{axis.upper()}') for axis in 'xyz'}}
    flip = 1 if side == 'L' else -1      # WingFingers' Z is the hinge, the turn bones' X: they mirror the other way
    for spar in HAND_SPARS:
        share = FINGER_FOLLOW[spar]
        path = f'{P(turn_name(spar, side))}.rotation_euler'
        lr.add_driver(arm, path, 0, f'{lay.toward_lead[spar]:.6f} * ({FOLD_CLOSE} * {close} + {OPEN_SHARE} * {opening} '
                                    f'- {SPREAD_SHARE} * spread) + {flip * share} * z', turns)
        lr.add_driver(arm, path, 1, f'{share} * y', {'y': turns['y']})
        lr.add_driver(arm, path, 2, f'{-flip * share} * x', {'x': turns['x']})


def drive_side(arm, lay, side):
    """The drivers of one wing: IK/FK, pole follow, the Fold arm and the finger fan (finger_drivers)."""
    P = lr.bone_path
    fore, hand = arm_names(side)[1:]
    fold_upper, fold_fore = fold_names(side)
    ctrl = ik_name(side)
    ik = {'ik': f'{P(ctrl)}["IK_FK"]'}
    lr.add_driver(arm, f'{P(fore)}.constraints["IK"].influence', None, 'ik', ik)
    lr.add_driver(arm, f'{P(hand)}.constraints["IK Turn"].influence', None, 'ik', ik)
    for name in (ctrl, pole_name(side), pole_line_name(side)):          # IK controls show in IK only
        lr.add_driver(arm, f'{P(name)}.hide', None, 'ik < 0.5', ik)
    if rn.ROOT in arm.data.bones:
        br.pole_follow_drivers(arm, pole_name(side), ctrl, {fold_upper: 1.0})
    fold = {'fold': f'{P(base_name(side))}["fold"]'}
    lr.add_driver(arm, f'{P(fold_upper)}.rotation_euler', 0, f'fold * {lay.fold_upper:.6f}', fold)
    lr.add_driver(arm, f'{P(fold_fore)}.rotation_euler', 0, f'fold * {lay.fold_bend:.6f}', fold)
    finger_drivers(arm, lay, side)


def finish_fk(arm, side):
    """After limb_rig placed the arm's FK collection: the arm bones get their B-bones back (limb_rig keeps limb bones
    plain). The finger chains stay out of it: shown in IK and FK."""
    for name in arm_names(side)[:2]:
        bone = arm.data.bones[name]
        bone.bbone_segments, bone.bbone_easein, bone.bbone_easeout = ARM_SEGMENTS, 1.0, 1.0
        bc.thin_bbones([bone])


def surface_of(wing_type):
    """The surface module of a wing type (Membrane when the type has none yet)."""
    return SURFACES.get(wing_type or DEFAULT_TYPE, SURFACES[DEFAULT_TYPE])


def build_wings(arm, wing, opts=None):
    """Build (or rebuild) both wings from a wing (or an older pivot fan; armature space, left side). opts: parent
    (default 'Chest'), wing_type (default 'MEMBRANE': SURFACES), tweaks (TWK- controls on the fingers), stretch (the
    IK_Stretch slider; needs a Root bone). The rig must be in the view layer. Returns {'spars': {side: {'Arm': [upper
    arm, forearm, hand], finger: [bones], surface chain: [bones]}} (every deforming chain), 'bones': every bone made}."""
    o = {'parent': 'Chest', 'tweaks': False, 'stretch': True, 'wing_type': DEFAULT_TYPE, **(opts or {})}
    surface = surface_of(o['wing_type'])
    lay = Layout(as_wing(wing))
    parent = o['parent'] if o['parent'] in arm.data.bones else None
    mode = arm.mode
    strip_wings(arm, surface)
    make_bones(arm, lay, parent)
    report = dict(spars={'L': {}, 'R': {}}, bones=[])
    for spar in SPARS:
        finger = pc.build_chain(arm, 'wing', lay.fingers[spar], dict(
            word=spar, parent=turn_name(spar, 'L'), up=lay.finger_up(spar), tweaks=o['tweaks'],
            radius=FINGER_RING * (lay.tips[spar] - lay.fingers[spar][0]).length / SPAR_BONES))
        for side, chain in finger['chains'].items():
            report['spars'][side][spar] = chain
        report['bones'] += finger['bones']
    make_surface_bones(arm, lay, surface)
    ik_constraints = []
    for side in ('L', 'R'):
        report['spars'][side][ARM] = arm_names(side)
        report['spars'][side].update(surface.deform_chains(SPARS, SPAR_BONES, side))
        report['bones'] += own_bones(side, surface)
        ik_constraints.append(rig_side(arm, lay, side, surface))
        style_side(arm, lay, side, surface)
    with lr.rest_pose([arm]):
        for bone, con in ik_constraints:
            lr.fit_pole_angle(arm, arm.pose.bones[bone], con, br.QUARTER_TURNS)
    for side in ('L', 'R'):
        drive_side(arm, lay, side)
    lr.upgrade(arm, wing_table(), stretch=o['stretch'], parent_switch=False, hock=False)
    for side in ('L', 'R'):
        finish_fk(arm, side)
        stretch = rn.helper(ik_name(side), 'Stretch')               # limb_rig's Stretch helper
        report['bones'] += [stretch] if stretch in arm.data.bones else []
    lr.set_mode(arm, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    return report


def remove_leftovers(arm):
    """After the wing bones went (Wings off): their FK collections and its show driver go too."""
    if ik_name('L') in arm.data.bones:
        return
    for side in ('L', 'R'):
        coll = arm.data.collections_all.get(bc.fk_title(ik_name(side), False))
        if coll is not None:
            coll.driver_remove('is_visible')
            arm.data.collections.remove(coll)


# ---------------------------------------------------------------- weights
def segment_distance(co, head, tail):
    axis = tail - head
    t = max(0.0, min(1.0, (co - head).dot(axis) / max(axis.length_squared, 1e-12)))
    return (co - (head + axis * t)).length


def segment_share(segments, co, falloff):
    """{bone: weight} of a point on the wing, by distance to each deforming bone ([(bone, head, tail)]): every bone
    pulls 1 / (distance + falloff) ^ PULL_POWER, normalised. A function of the position only, so a frame mesh and the
    membrane in it get the same weights where they meet."""
    pulls = {name: (segment_distance(co, head, tail) + falloff) ** -PULL_POWER for name, head, tail in segments}
    total = sum(pulls.values())
    return {name: pull / total for name, pull in pulls.items()}


def segment_weights(arm, mesh, chains, found, along, falloff, blend, limit):
    """Weights by segment_share (a function of the position only, so a rim mesh and the panels in it get
    the same weights where they meet): `chains` = {side: {key: bones}} (the left side's rest bones measure both
    sides, the right side mirrored onto the left), `found` = {side: vertex indices}, along(co) = the share from the
    root for pc.write_part_weights' take-over from body weights, falloff = segment_share's (metres).
    Returns the deforming bones used."""
    bones = arm.data.bones
    to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
    left = chains['L']
    left_names = [n for key in left for n in left[key]]
    segments = [(n, bones[n].head_local, bones[n].tail_local) for n in left_names if bones[n].use_deform]
    names = [n for side_chains in chains.values() for chain in side_chains.values() for n in chain
             if bones[n].use_deform]
    groups = {n: mesh.vertex_groups.get(n) or mesh.vertex_groups.new(name=n) for n in names}
    bone_groups = {g.index: g.name for g in mesh.vertex_groups if g.name in bones}
    for side, side_chains in chains.items():
        named = dict(zip(left_names, [n for key in left for n in side_chains[key]]))
        for vi in found.get(side, ()):
            co = to_rig @ mesh.data.vertices[vi].co
            co = pc.mirror_x(co) if side == 'R' else co
            share = {named[n]: w for n, w in segment_share(segments, co, falloff).items()}
            pc.write_part_weights(mesh, vi, share, along(co), blend, bone_groups, groups, limit)
    return names


def hold_on_parent(arm, mesh):
    """A wing that is its own mesh: every body weight goes, the wing's parent (Chest) holds it all, so the root follows
    the parent alone (the wing weights take over within the blend)."""
    parent = arm.data.bones[base_name('L')].parent
    if parent is None:
        return
    bones = arm.data.bones
    for group in [g for g in mesh.vertex_groups if g.name in bones]:
        mesh.vertex_groups.remove(group)
    holder = mesh.vertex_groups.new(name=parent.name)
    holder.add(range(len(mesh.data.vertices)), 1.0, 'REPLACE')


def bone_wing(bones, chains):
    """The wing (left side) as built: from the bones of report['spars']['L']."""
    upper, fore, _ = chains[ARM]
    return as_wing({ARM: [bones[upper].head_local, bones[fore].head_local, bones[fore].tail_local],
                    **{spar: bones[chains[spar][-1]].tail_local for spar in SPARS}})


def wing_weights(arm, mesh, report, vertices=None, blend=BLEND, limit=4):
    """Weight the wing vertices of `mesh` to the deforming wing bones of build_wings' `report` (arm and fingers) by
    segment_share, both sides; over body weights the wing takes over from the root sphere out over `blend` x the span
    (part_chains.write_part_weights); a wing that is its own mesh takes over from the parent (hold_on_parent).
    `vertices` = {side: indices}, or None to find them (wing_vertices on this mesh, from the built left wing).
    Returns {side: vertices weighted}."""
    bones = arm.data.bones
    left = report['spars']['L']
    wing = bone_wing(bones, left)
    plane, span = fan_plane(wing), fan_span(wing)
    found = {side: list(vertices.get(side, ())) if vertices else list(wing_vertices(arm, [mesh], wing, side)[1])
             for side in report['spars']}
    if not any(found.values()):
        return {side: 0 for side in found}
    if sum(len(v) for v in found.values()) == len(mesh.data.vertices):
        hold_on_parent(arm, mesh)
    names = segment_weights(arm, mesh, report['spars'], found, lambda co: plane.radius(co) / span - ROOT_CUT,
                            FALLOFF * span, blend, limit)
    cw.ensure_mirror_groups(mesh, only=set(names))
    return {side: len(idx) for side, idx in found.items()}
