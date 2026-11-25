# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, parts: Ray Fin, a manta / stingray pectoral fin: a stiff rim with panels that ripples instead
of folding. Spokes run from the body edge out to the rim, a rim chain runs along the edge, and a travelling wave
runs through the spokes. Bone-only: constraints and simple drivers (`frame` is in Blender's simple subset), no shape
keys, no Actions, no Python-only expressions. Names: docs/BONE_NAMES.md (Wings).

    outline = fit_fin(verts) or default_fin(joints, probe)    # [front root, front rim .., tip, .. back rim, back root]
    write_fin_guides(part_guides, outline)                    # guides: one chain along the outline (FinOutline1.L ..)
    report = build_fin(rig, fin_guide_outline(part_guides), dict(parent='Chest', spokes=5))
    fin_weights(rig, mesh, report)

An outline is a list of points (armature space, left side) around the fin: the front root on the body, the leading
edge, the rim tip (the point that reaches furthest out), the trailing edge, the back root on the body. Per side:
    FinBase.L           the root line (front root -> back root), under Chest: turn it to flap the whole fin; holds
                        Wave Height, Wave Speed, Wavelength, Wave Direction and Fold
    FinTip.L            at the rim tip: move it up / down to bend the whole fin, turn it about its length to twist
                        (pitch) the fin; adds on top of the wave and rides along with Fold
    FinSpokeA1.L ..     the spokes (A at the front), SPOKE_BONES B-bones each from the root line to the rim: thin FK
                        rings for one-off tweaks; the wave, Fold and FinTip add on top through a 'Fin Wave'
                        Transformation constraint, so posing and keying the spokes stays free
    FinRim1.L ..        the rim chain (deform only, B-bones): front root -> each spoke tip -> back root, stretched
                        from tip to tip, so the edge stays one smooth stiff line between the spokes
    MCH-FinFold1.L ..   a copy of the spoke nearest the tip that only folds: FinTip rides on its end (Mechanism)
The wave on spoke i (0 at the front), bone j:
    turn = share_j * reach_i / gain_i * (height * sin(+-phase - 2 pi i / (spokes - 1) / wavelength - 2 pi WAVE_LAG j)
           + FinTip's up / down + FinTip's twist x chord offset_i) - Fold x FOLD_CURL / bones
with phase = frame x Wave Speed x 2 pi / 24, share_j = (j + 1) / bones (0 at the root, 1 at the rim) and gain_i the
spoke's lever (a unit of turn moves its tip gain_i metres), so Wave Height and FinTip are in metres at the rim.
No IK / FK switch: a fin has no limb to aim; FinTip already works like a tip control (drag it, the fin follows).
"""
import math

from mathutils import Vector

try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, chain_weights as cw, limb_rig as lr, part_chains as pc, \
        rig_names as rn, wing_rig as wr
    from .face_rig_core import shape, switch
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import chain_weights as cw
    import limb_rig as lr
    import part_chains as pc
    import rig_names as rn
    import wing_rig as wr
    from face_rig_core import shape, switch

KIND = 'fin'
OUTLINE = 'Outline'                      # the guide chain's word
SPOKES = 5                               # default spoke count
SPOKE_BONES = 3                          # default bones per spoke
MAX_SPOKES = 12
SPOKE_SEGMENTS = 3                       # B-bone segments of a spoke bone
RIM_SEGMENTS = 3                         # ... of a rim bone
RIM_POINTS = 3                           # fit_fin / default_fin: outline points on each edge between root and tip
WAVE_REACH = 0.2                         # Wave Height 1: the rim swings this share of the fin's reach up and down
WAVE_LAG = 0.1                           # the wave lags this share of the chord per bone out along a spoke (the crest
                                         # sweeps back toward the rim)
FPS = 24.0                               # Wave Speed 1 = one wave per FPS frames (a second at 24 fps)
FOLD_CURL = math.radians(120)            # Fold 1 curls every spoke this far down / in, shared by its bones
MIN_REACH = 0.15                         # the shortest spoke still follows the wave and FinTip this much
BASE_SHAPE = 0.3                         # FinBase ring radius / its length
TIP_SHAPE = 0.05                         # FinTip sphere / the fin's reach
TIP_LENGTH = 0.1                         # FinTip bone length / the fin's reach
SPOKE_RING = 0.15                        # spoke ring radius / the spoke bone's length (thin)
ROOT_BAND = 0.05                         # fit: the root = vertices this share of the reach from the innermost one
TIP_BAND = 0.03                          # ... the tip = the centroid of the vertices this close to the furthest out
EDGE_WINDOW = 0.06                       # ... a rim point: the outermost vertex within this share of the edge
BLEND = 0.15                             # weights over body weights: the fin takes over over this share of the reach
FALLOFF = 0.15                           # weights: wing_rig.segment_share falloff / the fin's reach (soft: the panels
                                         # between two spokes follow both, so the surface stays smooth)
WEIGHT_LIMIT = 8                         # weights: at most this many bones per vertex (4 cuts the soft blend and
                                         # tears the rim from the panels; game exports limit it themselves)
DEFAULT_ROOT = 0.12                      # default_fin: root half length / figure height
DEFAULT_OUT, DEFAULT_BACK, DEFAULT_DROP = 0.4, 0.08, 0.05   # ... the tip: out, back and down / figure height
DEFAULT_BULGE = 0.06                     # ... the edges bow out this much / figure height


# ---------------------------------------------------------------- names
def base_name(side):
    return rn.build('FinBase', side)


def tip_name(side):
    return rn.build('FinTip', side)


def spoke_word(index):
    """'SpokeA' for the front spoke, 'SpokeB' ..: letters, so the bone number stays the bone's place on the spoke."""
    return 'Spoke' + chr(ord('A') + index)


def spoke_chain(index, side, bones=SPOKE_BONES):
    return pc.chain_names(KIND, bones, side, spoke_word(index))


def rim_names(side, spokes=SPOKES):
    """FinRim1.L .. FinRim<spokes + 1>.L: front root -> spoke tips -> back root."""
    return [rn.build('FinRim', side, k + 1) for k in range(spokes + 1)]


def fold_names(side, bones=SPOKE_BONES):
    return [rn.build('FinFold', side, j + 1, role='MCH') for j in range(bones)]


def own_bones(side, spokes=SPOKES, bones=SPOKE_BONES):
    """Every bone build_fin makes on one side."""
    return ([base_name(side), tip_name(side)] + fold_names(side, bones) + rim_names(side, spokes)
            + [n for i in range(spokes) for n in spoke_chain(i, side, bones)])


def stale_bones(side, spokes, bones):
    """Bones of an earlier build with more spokes or bones per spoke than this one."""
    longest = 8
    return ([n for i in range(MAX_SPOKES) for k, n in enumerate(spoke_chain(i, side, longest))
             if i >= spokes or k >= bones]
            + rim_names(side, MAX_SPOKES)[spokes + 1:] + fold_names(side, longest)[bones:])


# ---------------------------------------------------------------- fin geometry
def facing(normal):
    """The fin's up side: +Z for a lying fin (a manta's), else away from the body (+Y, behind) for one on the back."""
    normal = Vector(normal).normalized()
    if abs(normal.z) >= 0.7:
        return normal if normal.z > 0 else -normal
    return normal if normal.y >= 0 else -normal


def outline_normal(outline):
    """The outline's plane normal (Newell's sum over the closed outline)."""
    total = Vector()
    for a, b in zip(outline, outline[1:] + outline[:1]):
        total += a.cross(b)
    return total.normalized() if total.length > 1e-9 else Vector((0, 1, 0))


class Layout:
    """Where one (left) fin's bones go and the numbers its drivers use."""

    def __init__(self, outline, spokes=SPOKES, bones=SPOKE_BONES):
        self.outline = [Vector(p) for p in outline]
        if len(self.outline) < 3:
            raise ValueError("a fin outline needs at least a front root, a tip and a back root")
        self.spoke_count, self.bones = max(1, min(spokes, MAX_SPOKES)), max(1, bones)
        self.front, self.back = self.outline[0], self.outline[-1]
        self.up = facing(outline_normal(self.outline))
        root = self.back - self.front
        out = self.up.cross(root).normalized()
        self.out = out if (sum(self.outline, Vector()) / len(self.outline) - self.front).dot(out) > 0 else -out
        tip_index = max(range(len(self.outline)), key=lambda k: (self.outline[k] - self.front).dot(self.out))
        tip_index = min(max(tip_index, 1), len(self.outline) - 2)
        self.tip = self.outline[tip_index]
        self.reach = max((self.tip - self.front).dot(self.out), 1e-6)
        front_edge, back_edge = self.outline[:tip_index + 1], self.outline[tip_index:]
        self.spokes, self.shares, self.gains = [], [], []
        for i in range(self.spoke_count):
            place = (i + 1) / (self.spoke_count + 1)
            end = wr.along(front_edge, 2 * place) if place <= 0.5 else wr.along(back_edge, 2 * place - 1)
            start = self.front.lerp(self.back, place)
            self.spokes.append([start.lerp(end, j / self.bones) for j in range(self.bones + 1)])
            self.shares.append(min(1.0, max(MIN_REACH, (end - self.front).dot(self.out) / self.reach)))
            self.gains.append(lever(self.bone_shares(), (end - start).length / self.bones))
        self.tip_spoke = min(range(self.spoke_count), key=lambda i: (self.spokes[i][-1] - self.tip).length)

    def bone_shares(self):
        """How much of a spoke's turn each bone takes: 0 at the root growing to 1 at the rim."""
        return [(j + 1) / self.bones for j in range(self.bones)]


def lever(shares, bone_length):
    """How far a spoke's tip moves per unit of turn when its bones turn by `shares` (small turns add up along it)."""
    total, turned = 0.0, 0.0
    for share in shares:
        turned += share
        total += turned * bone_length
    return max(total, 1e-6)


def default_fin(joints, probe=None):
    """A fin for a figure (body guide joints, left side): on the back, reaching out and a little back and down."""
    height = wr.figure_height(joints)
    centre = wr.default_pivot(joints, probe)
    front = centre + Vector((0, 0, DEFAULT_ROOT * height))
    back = centre - Vector((0, 0, DEFAULT_ROOT * height))
    tip = centre + Vector((DEFAULT_OUT, DEFAULT_BACK, -DEFAULT_DROP)) * height
    bulge = DEFAULT_BULGE * height

    def edge(start, end, side_sign):
        along_edge = end - start
        away = Vector((0, 0, side_sign)) - along_edge.normalized() * along_edge.normalized().z * side_sign
        return [start.lerp(end, t) + away.normalized() * bulge * math.sin(math.pi * t)
                for t in ((k + 1) / (RIM_POINTS + 1) for k in range(RIM_POINTS))]
    return [front] + edge(front, tip, 1) + [tip] + edge(tip, back, -1) + [back]


def plane_axes(cos):
    """(up, out, chord) of a flat fin or wing (left side points): its up side (facing), out = away from the body
    (+X in its plane) and chord = across it, toward the front (+Z on a fin or wing on the back)."""
    up = facing(wr.flat_normal(cos) or Vector((0, 1, 0)))
    out = Vector((1, 0, 0)) - up * up.x
    out = out.normalized() if out.length > 1e-6 else Vector((1, 0, 0))
    chord = up.cross(out)
    return up, out, chord if (chord.z if abs(chord.z) >= abs(chord.y) else -chord.y) > 0 else -chord


def fit_fin(verts):
    """An outline fitted to fin vertices ({index: co}, left side, armature space): the root = the innermost band of
    vertices (its front and back ends), the tip = where the fin reaches furthest out, and RIM_POINTS points on each
    edge (the outermost vertex across the edge near each). None for too few vertices."""
    cos = list(verts.values())
    if len(cos) < wr.MIN_WING_VERTS:
        return None
    up, out, chord = plane_axes(cos)
    inner = min(co.dot(out) for co in cos)
    reach = max(co.dot(out) for co in cos) - inner
    root = [co for co in cos if co.dot(out) <= inner + ROOT_BAND * reach]
    front, back = max(root, key=lambda co: co.dot(chord)), min(root, key=lambda co: co.dot(chord))
    outermost = [co for co in cos if co.dot(out) >= inner + (1 - TIP_BAND) * reach]
    tip = sum(outermost, Vector()) / len(outermost)
    return [front.copy()] + rim_points(cos, front, tip, chord) + [tip] + rim_points(cos, tip, back, -chord) + \
        [back.copy()]


def rim_points(cos, start, end, side):
    """RIM_POINTS points on the edge from `start` to `end`: per point the vertex reaching furthest toward `side`
    among those across the edge near it."""
    axis = end - start
    length_sq = max(axis.length_squared, 1e-12)
    away = side - axis * side.dot(axis) / length_sq
    points = []
    for k in range(RIM_POINTS):
        place = (k + 1) / (RIM_POINTS + 1)
        near = [co for co in cos if abs((co - start).dot(axis) / length_sq - place) <= EDGE_WINDOW]
        points.append(max(near, key=lambda co: co.dot(away)).copy() if near else start.lerp(end, place))
    return points


def outline_fan(outline):
    """The outline as a wing_rig fan (every spar from the root's middle to the tip, the Root spar to the back root),
    so wing_rig.wing_vertices can find the fin's vertices (a 'Wings' group, or grown from the tip)."""
    outline = [Vector(p) for p in outline]
    pivot = (outline[0] + outline[-1]) / 2
    tip = max(outline, key=lambda p: (p - pivot).length)
    return {spar: [pivot.copy(), (outline[-1] if spar == wr.SPARS[-1] else tip).copy()] for spar in wr.SPARS}


def built_fan(arm, spars):
    """outline_fan of a built left fin (build_fin's report['spars']['L']): the root line and the spoke tips."""
    bones = arm.data.bones
    base = bones[base_name('L')]
    tips = [bones[chain[-1]].tail_local for key, chain in spars.items() if key != 'Rim']
    return outline_fan([base.head_local] + tips + [base.tail_local])


# ---------------------------------------------------------------- guides
def write_fin_guides(guides, outline):
    """The fin guide in the part guide armature, both sides: one connected chain along the outline (FinOutline1.L ..,
    front root first), so dragging a joint moves that outline point. Extra bones of a longer earlier outline go."""
    outline = [Vector(p) for p in outline]
    pc.write_guides(guides, KIND, outline, OUTLINE)
    with pc.sb.Kept(guides) as kept:
        edit_bones = kept.edit()
        for side in ('L', 'R'):
            pc.drop_bones(edit_bones, pc.chain_names(KIND, 32, side, OUTLINE)[len(outline) - 1:])
        kept.done()


def fin_guide_outline(guides):
    """The outline read back from the fin guide (where the user dragged it), or None when there is none."""
    return pc.guide_points(guides, KIND, OUTLINE)


# ---------------------------------------------------------------- build
def make_root_bones(arm, lay, parent):
    """Edit mode: FinBase, the MCH fold copy of the tip spoke and FinTip on its end (both sides)."""
    tip_points = lay.spokes[lay.tip_spoke]
    tip_end = tip_points[-1]
    tip_tail = tip_end + (tip_end - tip_points[-2]).normalized() * TIP_LENGTH * lay.reach
    folds = fold_names('L', lay.bones)
    bones = [(base_name('L'), lay.front, lay.back, parent, False)]
    bones += [(name, tip_points[j], tip_points[j + 1], folds[j - 1] if j else base_name('L'), j > 0)
              for j, name in enumerate(folds)]
    bones.append((tip_name('L'), tip_end, tip_tail, folds[-1], False))
    with pc.sb.Kept(arm) as kept:
        edit_bones = kept.edit()
        pc.drop_bones(edit_bones, [n for side in ('L', 'R') for n in stale_bones(side, lay.spoke_count, lay.bones)])
        for name, head, tail, up_bone, connect in bones:
            wr.pair(arm.data, name, head, tail, up_bone, lay.up, connect=connect)
        kept.done()


def make_rim(arm, lay):
    """Edit mode: the rim chain, front root -> every spoke tip -> back root, B-bones tangent to each other."""
    ends = [lay.front] + [points[-1] for points in lay.spokes] + [lay.back]
    parents = [base_name('L')] + [spoke_chain(i, 'L', lay.bones)[-1] for i in range(lay.spoke_count)]
    names = rim_names('L', lay.spoke_count)
    with pc.sb.Kept(arm) as kept:
        edit_bones = kept.edit()
        for k, name in enumerate(names):
            wr.pair(arm.data, name, ends[k], ends[k + 1], parents[k], lay.up, deform=True, connect=k > 0)
        for side in ('L', 'R'):
            pc.set_handles(edit_bones, rim_names(side, lay.spoke_count), None, RIM_SEGMENTS)
        kept.done()


def rim_targets(lay, side):
    """(bone, head_tail) each rim bone stretches to: the next spoke's tip, the last one FinBase's tail (back root)."""
    return [(spoke_chain(i, side, lay.bones)[-1], 1.0) for i in range(lay.spoke_count)] + [(base_name(side), 1.0)]


def rig_side(arm, lay, side):
    """Sliders, locks and constraints of one fin (drivers: drive_side)."""
    P = arm.pose.bones
    base, tip = P[base_name(side)], P[tip_name(side)]
    switch(base, 'WaveHeight', 0.0, 1.0, 'Wave Height: how far the wave lifts the rim (1 = a fifth of the fin)')
    switch(base, 'WaveSpeed', 0.0, 2.0, 'Wave Speed: waves per second at 24 fps; it plays by itself, 0 holds it',
           1.0)
    switch(base, 'Wavelength', 0.25, 2.0, 'Wavelength: 1 = one wave across the fin from front to back; smaller '
           'makes more ripples', 1.0, overshoot=1)
    switch(base, 'WaveDirection', 0.0, 1.0, 'Wave Direction: 0 runs front to back (swimming), 1 back to front',
           overshoot=1)
    switch(base, 'fold', 0.0, 1.0, 'Fold the fin: 0 as modelled, 1 curled down / in', overshoot=1)
    tip.rotation_mode = 'XYZ'
    tip.lock_location = (True, True, False)          # up / down only
    tip.lock_rotation = (True, False, True)          # twist about its length only
    for name in fold_names(side, lay.bones):
        P[name].rotation_mode = 'XYZ'
    for name, (target, head_tail) in zip(rim_names(side, lay.spoke_count), rim_targets(lay, side)):
        con = br.con(arm, name, 'Rim', 'STRETCH_TO', target, head_tail=head_tail, volume='NO_VOLUME',
                     keep_axis='SWING_Y')
        con.rest_length = arm.data.bones[name].length
    for i in range(lay.spoke_count):
        for name in spoke_chain(i, side, lay.bones):
            con = br.con(arm, name, 'Fin Wave', 'TRANSFORM', base_name(side), owner_space='LOCAL',
                         target_space='LOCAL', map_to='ROTATION', mix_mode_rot='AFTER')
            con.from_min_x, con.from_max_x = -1.0, 1.0      # input ignored: to_min = to_max, both driven


def style_side(arm, lay, side):
    """Control shapes and bone collections of one fin (the spokes: part_chains already placed them, as thin rings)."""
    P, B = arm.pose.bones, arm.data.bones
    shape(P[base_name(side)], 'WGT-Ring', BASE_SHAPE * B[base_name(side)].length)
    shape(P[tip_name(side)], 'SelectionSphere', TIP_SHAPE * lay.reach)
    for name in (base_name(side), tip_name(side)):
        bc.place_bone(arm, name, 'Wings', False)
    for name in rim_names(side, lay.spoke_count):
        bc.place_bone(arm, name, bc.driven_home(True), True)
    for name in fold_names(side, lay.bones):
        bc.place_bone(arm, name, bc.driven_home(False), False)


def wave_expression(lay, index, bone, twist_lever):
    """The turn of spoke `index`'s bone `bone` (see the module notes); a simple expression."""
    scale = lay.bone_shares()[bone] * lay.shares[index] / lay.gains[index]
    chord_lag = 2 * math.pi * index / max(lay.spoke_count - 1, 1)     # over the wavelength
    out_lag = 2 * math.pi * WAVE_LAG * bone                            # fixed, so short waves don't cancel on a spoke
    fold = -FOLD_CURL / lay.bones
    return (f'{scale:.6g}*({WAVE_REACH * lay.reach:.6g}*height*sin((1-2*direction)*frame*speed*'
            f'{2 * math.pi / FPS:.6g}-{chord_lag:.6g}/wavelength-{out_lag:.6g})+lift{-twist_lever:+.6g}*twist)'
            f'+{fold:.6g}*fold')


def drive_side(arm, lay, side):
    """The drivers of one fin: the wave, FinTip and Fold on every spoke bone, Fold on the MCH fold copy."""
    P, B = lr.bone_path, arm.data.bones
    base, tip = base_name(side), tip_name(side)
    sliders = {'height': 'WaveHeight', 'speed': 'WaveSpeed', 'wavelength': 'Wavelength',
               'direction': 'WaveDirection', 'fold': 'fold'}
    variables = {key: f'{P(base)}["{prop}"]' for key, prop in sliders.items()}
    variables.update(lift=f'{P(tip)}.location[2]', twist=f'{P(tip)}.rotation_euler[1]')
    tip_x, tip_head = B[tip].matrix_local.col[0].xyz, B[tip].head_local
    for i in range(lay.spoke_count):
        chain = spoke_chain(i, side, lay.bones)
        twist_lever = (B[chain[-1]].tail_local - tip_head).dot(tip_x)   # a turn about FinTip's Y lifts this spoke
        for j, name in enumerate(chain):
            expr = wave_expression(lay, i, j, twist_lever)
            for end in ('min', 'max'):
                lr.add_driver(arm, f'{P(name)}.constraints["Fin Wave"].to_{end}_x_rot', None, expr, variables)
    for name in fold_names(side, lay.bones):
        lr.add_driver(arm, f'{P(name)}.rotation_euler', 0, f'{-FOLD_CURL / lay.bones:.6g}*fold',
                      {'fold': variables['fold']})


def build_fin(arm, outline, opts=None):
    """Build (or rebuild) both fins from an outline (armature space, left side). opts: parent (default 'Chest'),
    spokes (SPOKES), spoke_bones (SPOKE_BONES). The rig must be in the view layer. Returns {'spars': {side: {word:
    spoke chain, 'Rim': rim chain}}, 'bones': every bone made} (the same shape as wing_rig.build_wings' report)."""
    options = {'parent': 'Chest', 'spokes': SPOKES, 'spoke_bones': SPOKE_BONES, **(opts or {})}
    lay = Layout(outline, options['spokes'], options['spoke_bones'])
    parent = options['parent'] if options['parent'] in arm.data.bones else None
    mode = arm.mode
    br.clear_rigging(arm, [n for side in ('L', 'R') for n in own_bones(side, MAX_SPOKES, 8)])
    make_root_bones(arm, lay, parent)
    report = dict(spars={'L': {}, 'R': {}}, bones=[])
    for i, points in enumerate(lay.spokes):
        length = (points[1] - points[0]).length
        built = pc.build_chain(arm, KIND, points, dict(word=spoke_word(i), parent=base_name('L'), up=lay.up,
                                                       radius=SPOKE_RING * length, bbone_segments=SPOKE_SEGMENTS))
        for side, chain in built['chains'].items():
            report['spars'][side][spoke_word(i)] = chain
    make_rim(arm, lay)
    for side in ('L', 'R'):
        report['spars'][side]['Rim'] = rim_names(side, lay.spoke_count)
        report['bones'] += own_bones(side, lay.spoke_count, lay.bones)
        rig_side(arm, lay, side)
        style_side(arm, lay, side)
        drive_side(arm, lay, side)
    lr.set_mode(arm, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    return report


# ---------------------------------------------------------------- weights
def fin_weights(arm, mesh, report, vertices=None, blend=BLEND, limit=None):
    """Weight the fin vertices of `mesh` to the spokes and rim of build_fin's `report`, both sides. `vertices` =
    {side: indices}, or None for the whole mesh split at x = 0 (a fin mesh of its own). Over body weights the fin
    takes over from the root line out over `blend` x the reach. Returns {side: vertices weighted}."""
    bones = arm.data.bones
    if vertices is None:
        to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
        vertices = {side: [v.index for v in mesh.data.vertices if ((to_rig @ v.co).x > 0) == (side == 'L')]
                    for side in report['spars']}
    base = bones[base_name('L')]
    root, root_axis = base.head_local, (base.tail_local - base.head_local).normalized()
    reach = max((bones[chain[-1]].tail_local - root).length for chain in report['spars']['L'].values())

    def along(co):
        rel = co - root
        return (rel - root_axis * rel.dot(root_axis)).length / reach

    names = wr.segment_weights(arm, mesh, report["spars"], vertices, along, FALLOFF * reach, blend, limit or WEIGHT_LIMIT)
    cw.ensure_mirror_groups(mesh, only=set(names))
    return {side: len(indices) for side, indices in vertices.items()}
