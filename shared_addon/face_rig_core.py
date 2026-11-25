"""Face Rig core: the generic Eye Rig and Anthro Mouth Rig ('maw' in the code) builder (from Digit's face rig, notes/wip/digit-face-rig.md
and notes/wip/face-rig-tool.md). The ONE source: sync_shared.py copies it into Digit's Assorted Tools and
Scripts/batch_tools (Digit's builder and the tests use that copy).

    build(arm, eye=cfg, maw=cfg)   cfg = config(kind, **settings) with cfg['guides'] = {guide name: Vector}
    rebuild(arm)                   remove + build from the stored configs, control pose offsets kept
    remove(arm)                    takes the built rig out (weights back to the bones it hung on)

Eye Rig, per eye: <Eye>Socket (move / squash the eye area) carries the eye and N lid pivots in the eye centre
(MCH-Lid*.L, driven) with tips on the lid edge (Pivots lids: DEF-LidTip*.L deform; Ring lids: MCH-LidTip*.L in
Mechanism, the lid ring deforms: LID_TIP_ROLE); UpperLid.L / LowerLid.L close (move) and tilt
(Y rotate), lids follow the look and the brow; lash sets (one control each over MCH follow + swing parents);
brows: Brow.L master + Inner / Mid / Outer over the Eyebrow1-4.L nodes (Brow Tweaks off: their MCH followers only) and
DEF-EyebrowSeg1-3.L B-bone segments.
Anthro Mouth Rig: jaw, UpperLip, LowerLip, MouthCorner.L (jaw follow), auto lip middles, Inner / Outer tweaks,
B-bone lip chains (the right side a true mirror). Weights from chain_weights along the lid ring / lip lines.
Face extras are on / off flags in the configs (FLAGS, all on by default); Rebuild with one off drops just that extra.
Bones follow docs/BONE_NAMES.md through rig_names (the right side mirrors the left, or is placed from its own guides with mirror off).
Coordinates are armature space; meshes must sit on the armature without an extra transform.
"""
import json
import math
import re
from collections import defaultdict, deque
from contextlib import contextmanager

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line
from mathutils.kdtree import KDTree

try:                                     # inside the add-on package
    from . import chain_weights as cw, bone_collections as bc, deform_metrics as dm, rig_names as rn, rig_rename as rr, \
        widget_meshes
except ImportError:                      # Scripts/batch_tools copy
    import widget_meshes
    import chain_weights as cw
    import deform_metrics as dm
    import bone_collections as bc
    import rig_names as rn
    import rig_rename as rr

MM = 0.001
UNLIMITED = 1e9                          # slider_limits(overshoot=None): no real limit on a typed value
OVERSHOOT = 3.0                          # sliders: a typed value may go this far past the slider's range
FOLLOW_ROOT = 'Follow Main Scale'
FWD = Vector((0, -1, 0))                 # out of the face
SIDES = rn.SIDES
UPPER_COLOR, LOWER_COLOR = bc.FACE_SPLIT[0][1], bc.FACE_SPLIT[1][1]   # pink / teal

# ---------------------------------------------------------------- config
COMMON = dict(
    head='Head',              # head bone (face bones hang on it)
    meshes=[],                # first = weight source (skin); the others get its head copied (identical heads) or transferred
    skin_parts=[],            # meshes on the skin that take the skin's new weights (face paint, blush, separate brows)
    replace=[],               # name prefixes (Left/Right stripped) of old face bones to remove; weights go to their parent
    weights=True,             # build skin weights (off: bones, drivers and shapes only)
    mirror=True,              # right side mirrors the left guides (off: Right… guides place the right side)
    size=1.0,                 # scale of falloffs, bone and shape sizes (1 = Digit)
    colors=(UPPER_COLOR, LOWER_COLOR),
)
EYE = dict(
    eye_bone=rn.left('Eye'),       # existing eye bone (made if missing)
    pivots=12,                # lid pivots per eye: 2 corners + half upper, half lower (even, 6..22)
    look_follow=(0.6, 0.35, 0.12),   # lids follow the eye look: upper, lower, corners
    brow_push=0.5,            # upper lid moves down by this share of the brow's drop
    brows=True,
    lashes=True, lash_mesh='',       # liners + lashes mesh (lashes found as small loose parts on the lid ring)
    lash_swing=-65.0,         # upper lash set swing when shut, degrees (None = fit to the shut lid)
    lash_aim=0.15, lash_start=0.5,
    liner_gap=0.9,            # shut lids stop this many liner diameters apart
    lid_upper=(11, 24, 8, 16), lid_lower=(3, 13, 6, 12), lid_corner=(3, 11, 5, 10),   # mm: skin full/zero, socket full/zero
    socket_falloff=(12, 30), socket_midline=(3, 15), eye_smooth=(14, 0.5, 30), lid_straight=True,
    lid_mode='PIVOTS',        # lid deformation: PIVOTS (the pivots deform) or RING (lid_bbone_ring: a B-bone ring deforms)
    ring_reach=30.0,          # ring: mm from the lid edge where the ring takes half of the lid weight (0 from twice that)
    sharp_corners=True,       # ring: no smooth handles across the eye corners
    smooth_blink=True,        # partial blinks keep the lid line one smooth arc (shape_blink_drivers); off: linear per pivot
    lid_twist=True,           # twisting a lid tweak (its own Y) turns that part of the lid round it (lid_twist)
    lid_push=(0.06, 0.12),    # lid pivots stretch forward by this share as the upper lid closes: all, the pair by the inner corner (lid_push)
    lid_tweaks=True,          # TWK-*Lid rings along each lid (lid_tweaks); off: no tweaks, so no lid twist either
    brow_tweaks=True,         # the Eyebrow1-4 nodes as tweak controls; off: none, the segments hang on their MCH followers (brow_nodes)
    look=True,                # Digit's look rig: HeadLookFocus, EyeFocus.L, the eyes track them (look_rig)
)
LID_MODES = ('PIVOTS', 'RING')
LEGACY = {'lid_band', 'smile_lift'}   # settings of older configs, ignored (smile_lift: now the Cheek controls' sliders)
MAW = dict(
    jaw='Jaw1',               # jaw bone (made from the Jaw guide if missing)
    lower_parent='',          # LowerLip parent (default: jaw)
    upper_parent='',          # UpperLip parent (default: head)
    corner_parent='',         # mouth corner rest parent (default: upper parent)
    corner_jaw_follow=0.4,
    corner_pull=(0.5, 0.35),  # upper / lower lip middles follow the mouth corner
    corner_lower_lift=1.0,    # the lower lip follows this share of a corner's lift (1: lip and corner read as one arc)
    smile_back=0.6,           # the Cheek control (smile_cheeks) slides back along the skin by this much of a mouth corner's lift
    smile_flare=0.14,         # the lip middles ride out over the teeth by this much of a corner's lift or pull back
    tongue=[],                # tongue meshes (empty: found by name and weights, then remembered here)
    corner_reach=0.25,        # corner_slide 1 moves a mouth corner this share of the lip length along the snout
    maw_squash=0.15,          # maw_stretch 1 draws the corners in this share of the lip length at a wide jaw
    maw_cheek=0.01,           # ... and bunches the cheeks this far (x cfg size)
    lip_center=(3, 14, 3, 7), lip_mid=(3, 16, 3, 7), lip_corner=(4, 14, 3, 7), lip_smooth=(8, 0.5, 24),
    smile_cheeks=True,        # Cheek controls + smile flare (smile_cheeks)
    zipper=True,              # `zip` on the mouth corners seals the lips (zip_lips)
    mouth_sliders=True,       # lip roll, corner slide / pin, maw stretch (lip_roll, corner_moves)
    tongue_rig=True,          # the tongue: Base, Mid and Tip controls (tongue_rig)
    snout=True,               # the snout part: Snout control, bends, Nose, NoseBridge (muzzle_features); off: a human mouth
    snarl=True,               # Snarl lifts + Nostrils with flare (muzzle_features, needs snout)
    puff=True,                # cheek Puff + PuffSwell (muzzle_features)
)
FLAGS = {'eye': ('brows', 'lashes', 'lid_tweaks', 'lid_twist', 'brow_tweaks', 'look'),     # on / off face extras, all on by default
         'maw': ('smile_cheeks', 'zipper', 'mouth_sliders', 'tongue_rig', 'snout', 'snarl', 'puff')}
FLAG_PROPS = {'zipper': ('zip',), 'tongue_rig': (), 'mouth_sliders': ('lip_roll_upper', 'lip_roll_lower', 'maw_stretch', 'corner_slide', 'corner_pin'),
              'snout': ('scrunch',), 'snarl': ('flare', 'snarl_scrunch'),
              'puff': ('puff',), 'smile_cheeks': ('cheek_follow', 'cheek_swing')}   # the sliders each flag adds
DEFAULTS = {'eye': EYE, 'maw': MAW}
TITLES = {'eye': 'Eye Rig', 'maw': 'Anthro Mouth Rig'}   # user-facing names (and the Library/FaceRigs.blend asset names); code and stored settings keep 'maw'
EYE_GUIDES = ['Eye', 'LidInner', 'LidUpper1', 'LidUpper2', 'LidUpper3', 'LidOuter', 'LidLower3', 'LidLower2',
              'LidLower1', 'Brow1', 'Brow2', 'Brow3', 'Brow4']
RING_GUIDES = EYE_GUIDES[1:9]            # lid ring order: inner, upper, outer, lower
BROW_GUIDES = EYE_GUIDES[9:]
MAW_GUIDES = ['LipUpper', 'LipUpperMid', 'MouthCorner', 'LipLowerMid', 'LipLower', 'Jaw']
CENTRE_GUIDES = {'LipUpper', 'LipLower', 'Jaw'}   # on the mirror plane: no Right copy
DIGIT_EYE_WIDTH = 0.0626                 # Digit's lid ring width (inner to outer corner): size 1
DIGIT_MOUTH_HALF = 0.0833                # ... and her mouth corner's x


def config(kind, **settings):
    """A full config dict for 'eye' or 'maw': defaults + settings (unknown keys are an error)."""
    cfg = dict(COMMON, **DEFAULTS[kind])
    settings = {k: v for k, v in settings.items() if k not in LEGACY}
    if settings.get('lid_mode') == 'HYBRID':          # merged into Ring (2026-11-03)
        settings['lid_mode'] = 'RING'
    bad = set(settings) - set(cfg) - {'guides'}
    if bad:
        raise KeyError(f'unknown {kind} settings: {sorted(bad)}')
    cfg.update(settings)
    cfg['kind'] = kind
    if kind == 'eye' and (cfg['pivots'] % 2 or not 6 <= cfg['pivots'] <= 22):
        raise ValueError('pivots must be even, 6..22')
    if kind == 'eye' and cfg['lid_mode'] not in LID_MODES:
        raise ValueError(f'lid_mode must be one of {LID_MODES}')
    return cfg


def to_json(cfg):
    out = {k: v for k, v in cfg.items() if k != 'guides'}
    out['guides'] = {k: list(v) for k, v in cfg.get('guides', {}).items()}
    return json.dumps(out)


def from_json(text):
    d = json.loads(text)
    if d.get('corner_lower_lift') == 0.35:             # the old default, not a choice: the lip now follows its corner
        del d['corner_lower_lift']
    d['guides'] = {k: Vector(v) for k, v in d.get('guides', {}).items()}
    kind = d.pop('kind')
    return config(kind, **d)


# ---------------------------------------------------------------- names and small helpers
def wants(cfg, flag):
    """An on / off face extra (FLAGS): on unless the config turns it off (older configs have them all on)."""
    return bool((cfg or {}).get(flag, True))


def drop_flag_props(arm, cfg):
    """The sliders (FLAG_PROPS) of the extras `cfg` turns off, off the face bones (kept ones such as the jaw or an own
    Nose hold some across a rebuild)."""
    gone = {p for flag, props in FLAG_PROPS.items() if not wants(cfg, flag) for p in props}
    head = arm.data.bones.get(cfg['head'])
    for b in head.children_recursive if gone and head else ():
        pb = arm.pose.bones[b.name]
        for p in gone & set(pb.keys()):
            del pb[p]


def stem(name):
    """The name without its side (the `replace` setting's prefixes are read on this)."""
    return rn.strip_side(name)


def part_of(name):
    return rn.parse(name).part


def is_lid_ring(name):
    return part_of(name) == 'LidRing'


def is_lash(name):
    return part_of(name) in LASH_PARTS or part_of(name) == 'Lash'


def mirror(v):
    return Vector((-v.x, v.y, v.z))


def resample(pts, fracs):
    """Points at the given arc-length fractions of a polyline."""
    if len(pts) < 2:                                   # a single point: every fraction is that point
        return [pts[0].copy() for _ in fracs] if pts else []
    seg = [(b - a).length for a, b in zip(pts, pts[1:])]
    total = sum(seg); out = []
    for f in fracs:
        d = f * total
        for a, b, l in zip(pts, pts[1:], seg):
            if d <= l or b is pts[-1]:
                out.append(a.lerp(b, min(1.0, d / l) if l > 0 else 0.0)); break
            d -= l
    return out


def at_x(pts, x):
    for p, q in zip(pts, pts[1:]):
        if min(p.x, q.x) <= x <= max(p.x, q.x) and abs(q.x - p.x) > 1e-9:
            return p.lerp(q, (x - p.x) / (q.x - p.x))
    return min(pts, key=lambda p: abs(p.x - x))


def angle_r(p, c):
    """Angle (up from the front) and radius of p round the X axis through c."""
    return math.atan2(p.z - c.z, -(p.y - c.y)), math.hypot(p.y - c.y, p.z - c.z)


def smooth_polyline(pts, closed, per=8):
    """Catmull-Rom curve through pts, `per` points per span (guide points -> a curve near the real edge loop)."""
    n = len(pts)
    if n < 3:
        return [p.copy() for p in pts]
    out = []
    spans = n if closed else n - 1
    for k in range(spans):
        p0 = pts[(k - 1) % n] if closed or k > 0 else pts[0]
        p1, p2 = pts[k], pts[(k + 1) % n]
        p3 = pts[(k + 2) % n] if closed or k + 2 < n else pts[-1]
        for j in range(per):
            t = j / per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    if not closed:
        out.append(pts[-1].copy())
    return out


def split_ring(ring):
    """Lid ring (closed, ordered) -> upper and lower lid lines, each from the inner (smaller |x|) to the outer corner."""
    xs = [abs(p.x) for p in ring]
    a, b = xs.index(min(xs)), xs.index(max(xs))
    p1 = [ring[(a + k) % len(ring)] for k in range((b - a) % len(ring) + 1)]
    p2 = [ring[(a - k) % len(ring)] for k in range((a - b) % len(ring) + 1)]
    return (p1, p2) if sum(p.z for p in p1) / len(p1) > sum(p.z for p in p2) / len(p2) else (p2, p1)


def blend2(t, names):
    """Weights for a point at t (0..1) on a 3-control line (start, middle, end): piecewise linear."""
    a, m, b = names
    return {a: 1 - 2 * t, m: 2 * t} if t <= 0.5 else {m: 2 - 2 * t, b: 2 * t - 1}


# A lid tip's role by lid mode: Pivots lids deform with the tips (DEF-LidTip*); with Ring lids the ring deforms and
# the tips are its mechanism (MCH-LidTip*, in Mechanism)
LID_TIP_ROLE = {'PIVOTS': 'DEF', 'RING': 'MCH'}


def lid_tip(lid, k, mode='PIVOTS'):
    """Lid tip `k` (from the inner corner) of the upper or lower lid, left side, named for the lid mode."""
    return rn.left(f'LidTip{lid}{k}', LID_TIP_ROLE[mode])


def lid_names(pivots, mode='PIVOTS'):
    """Lid bones (Left) in ring order: inner corner, upper 1..n, outer corner, lower n..1, named for the lid mode."""
    n = (pivots - 2) // 2
    return ([rn.left('LidTipInner', LID_TIP_ROLE[mode])] + [lid_tip('Upper', i, mode) for i in range(1, n + 1)]
            + [rn.left('LidTipOuter', LID_TIP_ROLE[mode])] + [lid_tip('Lower', i, mode) for i in range(n, 0, -1)])


def cfg_lid_names(cfg):
    """The eye config's lid bones (Left), lid_names order."""
    return lid_names(cfg['pivots'], cfg['lid_mode'])


def rig_lid_mode(arm):
    """The lid mode of a built rig: Ring when it has the lid ring, else its stored eye config's (a Ring build without
    weights has no ring yet), else Pivots."""
    if any(is_lid_ring(b.name) for b in arm.data.bones):
        return 'RING'
    return (stored(arm, 'eye') or {}).get('lid_mode', 'PIVOTS')


def name_lid_tips(arm, mode):
    """The rig's lid tips (both sides) renamed for the lid mode, DEF- or MCH- (rig_rename: weights, drivers and the
    build record follow). Returns how many were renamed."""
    want, B = LID_TIP_ROLE[mode], arm.data.bones
    table = {}
    for b in B:
        role, rest = rn.split_role(b.name)
        new = f'{want}-{rest}'
        if role in LID_TIP_ROLE.values() and role != want and rn.LID_TIP_NAME.fullmatch(rn.strip_side(rest)) and new not in B:
            table[b.name] = new
    if table:
        rr.rename(arm, table)
    return len(table)


TONGUE_BASE, TONGUE_MID, TONGUE_TIP = 'TongueBase', 'TongueMid', 'TongueTip'
TONGUE_MID_FOLLOW = rn.mch('TongueMid')      # follows Base and Tip half and half; TongueMid hangs on it
UP_NODES = ['UpperLip', rn.left('UpperLipInner'), rn.left('UpperLipMid'), rn.left('UpperLipOuter'), rn.left('MouthCorner')]
LO_NODES = ['LowerLip', rn.left('LowerLipInner'), rn.left('LowerLipMid'), rn.left('LowerLipOuter'), rn.left('MouthCorner')]
UP_SEGS = [rn.left(f'UpperLipSeg{k}', 'DEF') for k in range(1, 5)]
LO_SEGS = [rn.left(f'LowerLipSeg{k}', 'DEF') for k in range(1, 5)]
BROW_CTRL = [rn.left('BrowInner'), rn.left('BrowMid'), rn.left('BrowOuter')]
BROW_NODES = [rn.left(f'Eyebrow{k}') for k in (1, 2, 3, 4)]
BROW_SEGS = [rn.left(f'EyebrowSeg{k}', 'DEF') for k in (1, 2, 3)]
UPPER_LIP_ON_MID, LOWER_LIP_ON_MID = (0.65, 0.72), (0.5, 0.5)   # Inner, Outer share on the Mid: one control makes no step
LIP_TWEAKS = [rn.left('UpperLipInner'), rn.left('UpperLipOuter'), rn.left('LowerLipInner'), rn.left('LowerLipOuter')]


def brow_nodes(names, side='L'):
    """The bones the brow segments hang on (one side, inner to outer): the Eyebrow1-4 tweak nodes, or their MCH followers
    on a rig without them (Brow Tweaks off). `names`: the rig's bone names (any container of them)."""
    nodes = [rn.with_side(n, side) for n in BROW_NODES]
    return nodes if nodes[0] in names else [rn.mch(n) for n in nodes]


LASH_PARTS = {lid + 'Lashes' + job for lid in ('Upper', 'Lower') for job in ('', 'Swing', 'Tilt')}
NEW_DEFORM = ('Lid', 'UpperLashes', 'LowerLashes', 'UpperLipSeg', 'LowerLipSeg', 'EyeSocket', 'Cheek', 'SnarlLift', 'Puff',
              'Nostril', 'NoseBridge', 'MouthJawZip')           # parts (rig_names.parse)


def lip_tangent(segs):
    """The tangent bone at the lip centre of a segment chain: 'DEF-UpperLipSeg1.L' -> 'MCH-UpperLipTangent.L'."""
    b = rn.parse(segs[0])
    return rn.left(b.part.replace('Seg', 'Tangent'), 'MCH')


def mk(A, name, head, tail, parent=None, deform=False, roll=0.0, connect=False):
    eb = A.edit_bones.get(name) or A.edit_bones.new(name)
    eb.head, eb.tail, eb.roll = head, tail, roll
    eb.parent = A.edit_bones[parent] if parent else None
    eb.use_connect, eb.use_deform = connect, deform
    eb.use_inherit_rotation = True
    return eb


def both(A, name, head, tail, parent=None, right=None, **kw):
    """Left bone + Right bone (`name` is the left one); the Right bone mirrors the Left one, or is placed at
    mirror(right[0]) -> mirror(right[1]) (right side points given in the left frame, mirror off). Its parent is
    the mirror of the Left one's."""
    l = mk(A, name, head, tail, parent, **kw)
    rh, rt = right if right else (head, tail)
    r = mk(A, rn.with_side(name, 'R'), mirror(rh), mirror(rt), parent and rn.flip(parent), **kw)
    r.roll = -l.roll
    return l, r


def drive(pb, path, index, expr, variables):
    """Scripted driver; variables: {name: (bone, transform_type, space)} or {name: (bone, custom property)}."""
    pb.driver_remove(path, index)
    fc = pb.driver_add(path, index)
    d = fc.driver; d.type = 'SCRIPTED'
    for n, var in variables.items():
        v = d.variables.new(); v.name = n
        if len(var) == 2:
            v.type = 'SINGLE_PROP'
            v.targets[0].id = pb.id_data; v.targets[0].data_path = f'pose.bones["{var[0]}"]["{var[1]}"]'
            continue
        bone, ttype, space = var
        v.type = 'TRANSFORMS'
        t = v.targets[0]; t.id = pb.id_data; t.bone_target = bone
        t.transform_type = ttype; t.transform_space = space
        if ttype.startswith('ROT'):
            t.rotation_mode = 'AUTO'
    d.expression = expr
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    return fc


def follow(pb, targets):
    """Armature constraint: the (parentless) bone moves like skin weighted to `targets` {bone: weight}. It stays
    parentless on purpose: the constraint adds its targets' moves on top of a parent's, so a parent would move it twice."""
    c = pb.constraints.new('ARMATURE'); c.name = 'Follow'
    for bone, w in targets.items():
        if w > 1e-4:
            t = c.targets.new(); t.target = pb.id_data; t.subtarget = bone; t.weight = w
    return c


def stretch(pb, target):
    c = pb.constraints.new('STRETCH_TO'); c.target = pb.id_data; c.subtarget = target
    c.volume = 'NO_VOLUME'; c.keep_axis = 'SWING_Y'
    return c


def slider_limits(pb, name, lo, hi, default, description, overshoot=OVERSHOOT):
    """The slider goes lo..hi; a typed value may overshoot (overshoot=None: any typed value, but never below 0 when
    lo >= 0). Also on a linked character (library overridable)."""
    if overshoot is None:
        hard_min, hard_max = (0.0 if lo >= 0 else -UNLIMITED), UNLIMITED
    else:
        hard_min, hard_max = lo * overshoot, hi * overshoot
    pb.id_properties_ui(name).update(min=hard_min, max=hard_max, soft_min=lo, soft_max=hi, default=default,
                                     description=description)
    pb.property_overridable_library_set(f'["{name}"]', True)


def switch(pb, name, lo, hi, description, default=0.0, overshoot=OVERSHOOT):
    """A slider on a control, 0 by default: shown in Rig Switches (Selected card), put back by Reset Pose. Keeps its value
    when run again. overshoot=1: a true switch, no values past the slider."""
    if name not in pb:
        pb[name] = default
    slider_limits(pb, name, lo, hi, default, description, overshoot)


# ---------------------------------------------------------------- what every rig needs: root scale, linked use
def root_bone(arm):
    """The rig's one master bone, in any naming style, or None."""
    return rn.find(arm.data.bones.keys(), rn.ROOT)


def follow_root_scale(arm, root):
    """Bones with Inherit Scale None must still follow the root: a Copy Scale (pose space, offset) on each, because
    such a bone takes no scale from its parent, in a chain of them too."""
    free = sorted(b.name for b in arm.data.bones if b.inherit_scale == 'NONE' and b.name != root)
    for n in free:
        pb = arm.pose.bones[n]
        if FOLLOW_ROOT in pb.constraints:
            continue
        c = pb.constraints.new('COPY_SCALE')
        c.name, c.target, c.subtarget, c.use_offset = FOLLOW_ROOT, arm, root, True
        c.owner_space = c.target_space = 'POSE'
        pb.constraints.move(len(pb.constraints) - 1, 0)
    return free


def scale_limit_distances(arm, root):
    """A Limit Distance holds a world-space length, so it has to grow with the root's scale."""
    driven = {fc.data_path for fc in (arm.animation_data.drivers if arm.animation_data else [])}
    for pb in arm.pose.bones:
        for c in pb.constraints:
            if c.type == 'LIMIT_DISTANCE' and f'{c.path_from_id()}.distance' not in driven:
                base = c.distance
                dr = c.driver_add('distance').driver
                dr.type = 'SCRIPTED'
                v = dr.variables.new()
                v.name, v.type = 's', 'TRANSFORMS'
                t = v.targets[0]
                t.id, t.bone_target, t.transform_type, t.transform_space = arm, root, 'SCALE_AVG', 'LOCAL_SPACE'
                dr.expression = f'{base:.6f}*s'


def overridable_sliders(arm):
    """Every number on a pose bone can be changed on a linked character (`_` names and the Limb data stay out)."""
    for pb in arm.pose.bones:
        for k in pb.keys():
            if not k.startswith('_') and not isinstance(pb[k], str) and not pb.is_property_overridable_library(f'["{k}"]'):
                pb.property_overridable_library_set(f'["{k}"]', True)


def finish_rig(arm):
    """Run by the face and limb tools after they change a rig (safe to repeat): it scales with the root, works linked."""
    root = root_bone(arm)
    if root:
        follow_root_scale(arm, root)
        scale_limit_distances(arm, root)
    overridable_sliders(arm)
    if arm.mode != 'EDIT':
        bc.set_bbone_display(arm)


def smooth_handles(A, segs):
    """ABSOLUTE handles on the neighbouring B-bone segments (as Rigify does): Catmull-Rom tangents,
    no kink at the nodes. (AUTO ignores the custom bones unless the chain is connected.)"""
    E = A.edit_bones
    for k, s in enumerate(segs):
        eb = E[s]
        eb.bbone_handle_type_start = 'ABSOLUTE' if k > 0 else 'AUTO'
        eb.bbone_handle_type_end = 'ABSOLUTE' if k + 1 < len(segs) else 'AUTO'
        eb.bbone_custom_handle_start = E[segs[k - 1]] if k > 0 else None
        eb.bbone_custom_handle_end = E[segs[k + 1]] if k + 1 < len(segs) else None


# ---------------------------------------------------------------- widgets (control shapes)
def icosphere_widget(name):
    """Wire icosphere of radius 1: the 12 corners, joined to their nearest neighbours (5 each)."""
    phi = (1 + math.sqrt(5)) / 2
    corners = [p for a in (-1, 1) for b in (-phi, phi) for p in ((0, a, b), (a, b, 0), (b, 0, a))]
    verts = [tuple(Vector(p).normalized()) for p in corners]
    edge_length = 2 / math.sqrt(phi + 2)
    edges = [(i, j) for i in range(12) for j in range(i + 1, 12)
             if (Vector(verts[i]) - Vector(verts[j])).length < edge_length * 1.01]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = bpy.data.objects.new(name, me)
    ob.use_fake_user = True
    return ob


def wire_object(name, verts, edges):
    """A widget object of loose edges, kept with a fake user."""
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = bpy.data.objects.new(name, me)
    ob.use_fake_user = True
    return ob


DIR_WIDGETS = {'WGT-SphereDir': 'SelectionSphere', 'WGT-SphereEmptyDir': 'WGT-SphereEmpty', 'WGT-DiamondDir': 'WGT-Guide', 'WGT-CubeDir': 'WGT-Cube'}   # name: base shape
POINTER_LENGTH = 1.5                         # a pointer widget's line along +Y, in the base shape's radius


def pointer_widget(name, base):
    """Widget `name`: the `base` widget plus one line along +Y, POINTER_LENGTH long, with a small arrow tip."""
    mesh = ensure_widget(base).data
    verts = [tuple(v.co) for v in mesh.vertices]
    edges = [tuple(e.vertices) for e in mesh.edges]
    n, tip, wing = len(verts), POINTER_LENGTH, 0.25 * POINTER_LENGTH
    verts += [(0, 0, 0), (0, tip, 0), (-wing * 0.5, tip - wing, 0), (wing * 0.5, tip - wing, 0)]
    edges += [(n, n + 1), (n + 1, n + 2), (n + 1, n + 3)]
    return wire_object(name, verts, edges)


def ensure_widget(name):
    """Control shape object (WGT-Ring: circle in XZ, WGT-Arrow: arrow along the bone, WGT-Line: a line along the bone, WGT-Cone: wire cone along the bone, tip out, WGT-Cube: wire cube,
    SelectionSphere: three circles, WGT-SphereEmpty: three 24-segment circles (Blender's Sphere empty look), WGT-Ico: wire icosphere, WGT-Guide: small
    diamond, WGT-Square: unit square in XZ, WGT-Triangle: flat triangle in XY pointing along the bone, WGT-EyeSocket: circle in XZ with four diamond grab tabs, SelectionPaw and the other widget_meshes: made from
    data; WGT-Ngon / Star / Gear / Capsule / FourArrows: widget_meshes.parametric), the file's own if it has one."""
    ob = bpy.data.objects.get(name)
    if ob:
        return ob
    if name in widget_meshes.MESHES:
        data = widget_meshes.MESHES[name]
        me = bpy.data.meshes.new(name)
        me.from_pydata(data['verts'], [], data['faces'])
        ob = bpy.data.objects.new(name, me)
        ob.use_fake_user = True
        return ob
    if name in DIR_WIDGETS:
        return pointer_widget(name, DIR_WIDGETS[name])
    made = widget_meshes.parametric(name)       # WGT-Ngon6, WGT-Gear10-25-50Hole ...: the numbers are in the name
    if made:
        return wire_object(name, *made)
    if name == 'WGT-Arrow':                      # flat arrow along the bone (+Y) in its XY plane, 1 long
        return wire_object(name, [(0, 0, 0), (0, 1, 0), (-0.22, 0.72, 0), (0.22, 0.72, 0)], [(0, 1), (1, 2), (1, 3)])
    if name == 'WGT-Square':                     # unit square in XZ (faces forward): tongue controls, scaled to rectangles
        return wire_object(name, [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)], [(0, 1), (1, 2), (2, 3), (3, 0)])
    if name == 'WGT-Triangle':                   # flat triangle in XY pointing +Y, half-width 1: the jaw control
        return wire_object(name, [(-1, -0.6, 0), (1, -0.6, 0), (0, 1, 0)], [(0, 1), (1, 2), (2, 0)])
    if name == 'WGT-Ico':                        # wire icosphere, radius 1: main face controls
        return icosphere_widget(name)
    if name == 'WGT-Cone':                       # wire cone along the bone (+Y), 1 long, tip out: look targets
        ring = [(0.35 * math.cos(2 * math.pi * k / 16), 0, 0.35 * math.sin(2 * math.pi * k / 16)) for k in range(16)]
        tip = len(ring)
        return wire_object(name, ring + [(0, 1, 0)], [(k, (k + 1) % tip) for k in range(tip)] + [(k, tip) for k in range(0, tip, 4)])
    if name == 'WGT-Line':                       # one line along the bone (+Y), 1 long: pole lines
        return wire_object(name, [(0, 0, 0), (0, 1, 0)], [(0, 1)])
    if name == 'WGT-Cube':                       # wire cube outline, half-size 1: B-Bone Chain Builder web points
        corners = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        return wire_object(name, corners, [(i, j) for i in range(8) for j in range(i + 1, 8)
                                           if sum(a != b for a, b in zip(corners[i], corners[j])) == 1])
    rings = {'WGT-Ring': ['XZ'], 'SelectionSphere': ['XZ', 'XY', 'YZ'], 'WGT-SphereEmpty': ['XZ', 'XY', 'YZ'], 'WGT-Guide': ['XZ', 'YZ'], 'WGT-EyeSocket': ['XZ']}[name]
    segs = {'WGT-Guide': 4, 'WGT-SphereEmpty': 24}.get(name, 32)
    verts, edges = [], []
    if name == 'WGT-EyeSocket':                  # grab tabs: a small diamond outside the ring at each quarter
        for a in (0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
            c, d = Vector((math.cos(a), 0, math.sin(a))), Vector((-math.sin(a), 0, math.cos(a)))
            start = len(verts)
            verts += [tuple(c * 1.0), tuple(c * 1.09 + d * 0.07), tuple(c * 1.18), tuple(c * 1.09 - d * 0.07)]
            edges += [(start + k, start + (k + 1) % 4) for k in range(4)]
    for plane in rings:
        start = len(verts)
        for k in range(segs):
            a = 2 * math.pi * k / segs
            u, v = math.cos(a), math.sin(a)
            verts.append({'XZ': (u, 0, v), 'XY': (u, v, 0), 'YZ': (0, u, v)}[plane])
            edges.append((start + k, start + (k + 1) % segs))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, [])
    ob = bpy.data.objects.new(name, me)
    ob.use_fake_user = True
    return ob


def shape(pb, obj_name, size, translate=(0, 0, 0)):
    pb.custom_shape = ensure_widget(obj_name)
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_scale_xyz = (size, size, size)
    pb.custom_shape_translation = translate


SOCKET_COLOR = (1.0, 0.72, 0.05)    # eye socket controls: gold, apart from the lids' pink / teal and the face purple
SOCKET_WIRE = 1.5                   # custom shape line width
SOCKET_RING = 0.24                  # ring diameter as a share of the eye width: a small ring at the socket bone's base
QUICK_SELECT = [('Socket L', [rn.left('EyeSocket')]), ('Socket R', [rn.build('EyeSocket', 'R')]),
                ('Upper Lid L', [rn.left('UpperLid')]), ('Upper Lid R', [rn.build('UpperLid', 'R')]),
                ('Lower Lid L', [rn.left('LowerLid')]), ('Lower Lid R', [rn.build('LowerLid', 'R')]),
                ('Lashes', [rn.left('UpperLashes'), rn.build('UpperLashes', 'R'), rn.left('LowerLashes'), rn.build('LowerLashes', 'R')]),
                ('Tongue', [TONGUE_BASE, TONGUE_TIP, TONGUE_MID])]   # first = active


def face_shapes(arm, s):
    """Brow and lip control shapes: wire icospheres on the main controls, three-circle spheres on their tweaks.
    Sizes are radii x cfg size. Skips bones the rig lacks; works on a built rig in place."""
    P = arm.pose.bones
    for widget, size, names in FACE_SHAPES:
        for n in names:
            for nm in {n, rn.with_side(n, 'R')}:
                if nm in P:
                    shape(P[nm], widget, size * s)


def socket_controls(arm, cfg=None):
    """Eye socket controls (their scale gives toon oval eyes) easy to pick: a small WGT-EyeSocket ring at the
    socket bone's base (the eye centre), gold wire, in Face > Eyes. Every lid bone (spokes, MCH pivots, lid ring)
    stays clickable: the user hand-tunes them. Works on a built rig in place. Returns the bones set up."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    names = cfg_lid_names(cfg)
    B, P = arm.data.bones, arm.pose.bones
    done = []
    for side in SIDES:
        nm = rn.build('EyeSocket', side)
        if nm not in B or rn.with_side(names[0], side) not in B:
            continue
        b, pb = B[nm], P[nm]
        tips = [B[rn.with_side(n, side)].tail_local for n in names]
        width = abs(tips[(len(names) // 2)].x - tips[0].x)
        shape(pb, 'WGT-EyeSocket', SOCKET_RING * width, (0.0, 0.0, 0.0))
        if hasattr(pb, 'custom_shape_wire_width'):
            pb.custom_shape_wire_width = SOCKET_WIRE
        bc.place_bone(arm, nm, 'Eyes', b.use_deform)
        pb.color.palette = 'CUSTOM'
        pb.color.custom.normal = SOCKET_COLOR
        pb.color.custom.select = tuple(min(1.0, c * 0.5 + 0.5) for c in SOCKET_COLOR)
        pb.color.custom.active = (1.0, 1.0, 1.0)
        done.append(nm)
    return done



LID_TWEAK_EVERY = 2                 # a tweak control on every other lid spoke tip (upper / lower 1, 3, 5 ...)
FACE_SHAPES = [('WGT-Ico', 0.006, ['UpperLip', 'LowerLip', *BROW_CTRL]),
               ('WGT-Ico', 0.005, [rn.left('UpperLipMid'), rn.left('LowerLipMid')]),
               ('SelectionSphere', 0.0035, [rn.left(f'Eyebrow{k}') for k in (1, 2, 3, 4)]),
               ('SelectionSphere', 0.003, LIP_TWEAKS),
               ('WGT-Ico', 0.005, [rn.left('Snarl'), rn.left('Puff'), 'Nose']),
               ('SelectionSphere', 0.0035, [rn.left('Nostril'), 'NoseBridge'])]
LID_TWEAK_SIZE = 0.0035             # tweak ring size (x cfg size)
EYE_TIP_SIZE = 0.004               # eye control sphere size (x cfg size)


def lid_tweak_name(n):
    """'DEF-LidTipUpper3.L' -> 'TWK-UpperLid3.L' (upper / lower in the name: FACE_SPLIT colours it pink / teal)."""
    b = rn.parse(n)
    return rn.build(b.part.replace('LidTip', '') + 'Lid', b.side, b.number, 'TWK')


def lid_tweaks(arm, cfg=None):
    """Hand-tuning controls on the lid: a small ring at every LID_TWEAK_EVERY-th upper / lower spoke tip (on the
    lid edge), a child of the spoke's MCH pivot, so it rides blinks, tilt and look. The deform spoke (and with it
    the lid ring and the skin) Damped-Tracks its tweak: moving a tweak turns the spoke, keeping its length, so the
    lid edge stays on the eyeball. At rest nothing moves. Face Tweak collection, upper pink / lower teal.
    Works on a built rig in place (safe to run again). Returns the tweak bone names."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    n = (cfg['pivots'] - 2) // 2
    picks = [lid_tip(lid, k, cfg['lid_mode']) for lid in ('Upper', 'Lower') for k in range(1, n + 1, LID_TWEAK_EVERY)]
    A = arm.data
    if picks[0] not in A.bones:
        return []
    view = bpy.context.view_layer
    active, mode = view.objects.active, arm.mode
    view.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    E, s, made = A.edit_bones, cfg['size'], []
    for side in SIDES:
        for nm in picks:
            sp = E[rn.with_side(nm, side)]
            tw = mk(A, lid_tweak_name(rn.with_side(nm, side)), sp.tail, sp.tail + FWD * 0.004 * s, rn.mch(sp.name))
            made.append(tw.name)
    bpy.ops.object.mode_set(mode='POSE')
    P = arm.pose.bones
    for side in SIDES:
        for nm in picks:
            spoke, tw = rn.with_side(nm, side), lid_tweak_name(rn.with_side(nm, side))
            pb = P[spoke]
            c = pb.constraints.get('Lid Tweak') or pb.constraints.new('DAMPED_TRACK')
            c.name, c.target, c.subtarget, c.head_tail = 'Lid Tweak', arm, tw, 0.0
            t = P[tw]
            shape(t, 'WGT-Ring', LID_TWEAK_SIZE * s)
            t.lock_rotation = (True, True, True); t.lock_rotation_w = True; t.lock_scale = (True, True, True)
            bc.place_bone(arm, tw, 'Face Tweak', False)
    bc.apply_face_split_colors(arm, only=set(made))
    bpy.ops.object.mode_set(mode=mode if mode in ('POSE', 'OBJECT') else 'POSE')
    view.objects.active = active
    return made


LID_RING = 0.11                     # UpperLid / LowerLid ring radius as a share of the eye width (readable at the eye's scale)
EYE_RING_GAP = 0.004                # the eye rings sit this far (x cfg size) in front of the lid rim plane
PUPIL_RING, IRIS_RING = 0.004, 0.008   # Pupil / Iris ring radius (x cfg size)


def shape_offset(bone, point):
    """`point` (armature space) in the bone's own axes from its head: the custom_shape_translation that puts the
    shape's centre there (the shape is not scaled by the bone's length, see shape())."""
    return tuple(bone.matrix_local.to_3x3().inverted() @ (point - bone.head_local))


def eye_lid_geometry(arm, cfg):
    """{side: lid geometry} (left frame) from the skin's lid edge loop, else the guides; mirror on: the left one for both."""
    meshes = [bpy.data.objects[n] for n in cfg['meshes'] if n in bpy.data.objects]
    src = meshes[0] if meshes else None
    with rig_space(arm, meshes[:1]):
        left = eye_geometry(arm, src, cfg, 'L')
        return {'L': left, 'R': left if cfg['mirror'] else eye_geometry(arm, src, cfg, 'R')}


def fix_eye_controls(arm, cfg=None, geometry=None, log=print):
    """Eye controls on a built rig, in place (safe to run again; Build runs it last):
    - UpperLid / LowerLid (no deform) go to the lid rim: the middle of the lid edge loop's top / bottom, a little in
      front of it. Both ends move together, so the bone keeps its direction. Nothing deforms from them, so the skin
      does not change (rest stays at 0 mm).
    - Lid tweak rings are drawn at the rim point of their spoke (shape only: the spoke tracks the tweak bone, moving
      the bone would turn the spoke and the skin).
    - EyeSocket, Iris and Pupil rings are drawn round the pupil axis (the eye bone's line), facing out, nested in one
      plane just in front of the lid rim. Iris / Pupil get their ring when they have none.
    geometry: {side: eye_geometry()} when the caller has it. Returns the names of the bones it moved or reshaped."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    A, P, s = arm.data, arm.pose.bones, cfg['size']
    G = geometry or eye_lid_geometry(arm, cfg)
    names = cfg_lid_names(cfg)
    centres, rims = {}, {}
    for side in SIDES:
        eye = A.bones.get(rn.with_side(cfg['eye_bone'], side))
        if eye is None or rn.with_side(names[0], side) not in A.bones:
            continue
        F = frame(side)
        centres[side] = (eye.head_local.copy(), (eye.tail_local - eye.head_local).normalized())
        rims[side] = {n: F(p) for n, p in lid_points(G[side], names).items()}
    done = []
    mid = len(G['L']['up_nodes']) // 2
    with in_mode(arm, 'EDIT'):
        E = A.edit_bones
        for side in centres:
            F = frame(side)
            for lid, key in (('UpperLid', 'up_nodes'), ('LowerLid', 'lo_nodes')):
                bone = E.get(rn.build(lid, side))
                if bone is None:
                    continue
                delta = F(G[side][key][mid]) + FWD * 0.004 * s - bone.head
                bone.head += delta; bone.tail += delta
                done.append(bone.name)
    for side, (centre, axis) in centres.items():
        B = A.bones
        width = (rims[side][names[0]] - rims[side][names[len(names) // 2]]).length
        depth = sum((p - centre).dot(axis) for p in rims[side].values()) / len(rims[side]) + EYE_RING_GAP * s
        plane = centre + axis * depth
        rings = ((rn.build('EyeSocket', side), 'WGT-EyeSocket', SOCKET_RING * width, False),
                 (rn.build('Iris', side), 'WGT-Ring', IRIS_RING * s, True), (rn.build('Pupil', side), 'WGT-Ring', PUPIL_RING * s, True))
        for nm, widget, size, only_missing in rings:
            if nm in B and not (only_missing and P[nm].custom_shape is not None):
                shape(P[nm], widget, size, shape_offset(B[nm], plane))
                P[nm].custom_shape_rotation_euler = Vector((0, 1, 0)).rotation_difference(
                    B[nm].matrix_local.to_3x3().inverted() @ axis).to_euler()     # facing along the pupil axis
                done.append(nm)
        for lid in ('UpperLid', 'LowerLid'):
            nm = rn.build(lid, side)
            if nm in B:
                shape(P[nm], 'WGT-Ring', LID_RING * width)
        for spoke in rims[side]:
            tw = lid_tweak_name(rn.with_side(spoke, side))
            if tw in B and P[tw].custom_shape is not None:
                P[tw].custom_shape_translation = shape_offset(B[tw], rims[side][spoke])
                done.append(tw)
    log(f'M# eye controls: {len(done)} bones placed')
    return done


LID_TWIST_FALLOFF = (0.55, 0.28, 0.07)   # share of a tweak's twist on the pivots 1, 2, 3 steps along its lid (corners included)
LID_TWIST_LOWER = 0.7                    # lower lid gain: more and the lid edge sinks into the eyeball
LID_TWIST_SAT = 0.8                      # radians: a twist eases off past about this, x / (1 + |x| / LID_TWIST_SAT)
LID_TWIST_PROPS = ('lid_twist_x', 'lid_twist_z')     # driven properties on a pivot: its X / Z rotation from the twists
LID_PUSH_RAMP = 0.5                      # the lid push is full at this share of the upper lid's travel


def lid_chain(cfg, lid):
    """Tips of one lid, left side, inner corner -> outer corner, both corners included."""
    names = cfg_lid_names(cfg)
    n = (cfg['pivots'] - 2) // 2
    return [names[0]] + [lid_tip(lid, k, cfg['lid_mode']) for k in range(1, n + 1)] + [names[n + 1]]


def fit_rotation(frame, r, move):
    """(rx, rz): the pivot's X / Z rotation (radians, small) that moves its tip at r (from the pivot) closest to
    `move`: least squares on the two rotation directions."""
    a, b = frame.col[0].cross(r), frame.col[2].cross(r)
    aa, ab, bb = a.dot(a), a.dot(b), b.dot(b)
    det = aa * bb - ab * ab
    if det < 1e-18:
        return 0.0, 0.0
    am, bm = a.dot(move), b.dot(move)
    return (bb * am - ab * bm) / det, (aa * bm - ab * am) / det


def twist_shares(arm, cfg, side, lid, k):
    """{pivot: (rx, rz)} per radian of twist of the lid tweak on tip k: the neighbouring tips rotate round the
    tweak's own axis (out of the face), with LID_TWIST_FALLOFF by steps along the lid, fitted onto each pivot's
    two rotation channels from the rest pose. The tweak's own pivot stays: the lid turns round it."""
    B = arm.data.bones
    chain = [rn.with_side(t, side) for t in lid_chain(cfg, lid)]
    tweak = B[lid_tweak_name(chain[k])]
    axis, centre = tweak.matrix_local.to_3x3().col[1].normalized(), tweak.head_local
    gain = LID_TWIST_LOWER if lid == 'Lower' else 1.0
    shares = {}
    for step, share in enumerate(LID_TWIST_FALLOFF, 1):
        for i in (k - step, k + step):
            if 0 <= i < len(chain):
                pivot, tip = B[rn.mch(chain[i])], B[chain[i]].tail_local
                move = share * gain * axis.cross(tip - centre)
                shares[pivot.name] = fit_rotation(pivot.matrix_local.to_3x3(), tip - pivot.head_local, move)
    return shares


def clear_lid_twist(arm, pivot):
    """Take a pivot's twist terms out (its driven properties and the ' + twist' on its rotation drivers)."""
    pb = arm.pose.bones[pivot]
    for prop in LID_TWIST_PROPS:
        arm.driver_remove(f'pose.bones["{pivot}"]["{prop}"]')
        if prop in pb:
            del pb[prop]
    for i in (0, 2):
        fc = arm.animation_data.drivers.find(f'pose.bones["{pivot}"].rotation_euler', index=i) if arm.animation_data else None
        if fc and 'twist' in fc.driver.variables:
            fc.driver.variables.remove(fc.driver.variables['twist'])
            fc.driver.expression = fc.driver.expression.replace(' + twist', '')


def twist_driver(arm, pivot, axis, terms):
    """The pivot's driven twist property for rotation axis 0 (X) / 2 (Z) holds the terms (driver expressions hold
    at most 256 characters, as with lid_blink); its rotation driver adds it. terms: [(variable, tweak, coefficient)]."""
    prop = LID_TWIST_PROPS[axis // 2]
    arm.pose.bones[pivot][prop] = 0.0
    path = f'pose.bones["{pivot}"]["{prop}"]'
    d = arm.driver_add(path).driver
    d.type = 'SCRIPTED'
    for var, tweak, _ in terms:          # the property, not the transform: tweaks are children of the pivots
        v = d.variables.new(); v.name, v.type = var, 'SINGLE_PROP'
        v.targets[0].id = arm; v.targets[0].data_path = f'pose.bones["{tweak}"].rotation_euler[1]'
    d.expression = ' + '.join(f'{c:.5f}*{v}/(1+abs({v})/{LID_TWIST_SAT})' for v, _, c in terms)
    assert len(d.expression) < 256, d.expression
    main = arm.animation_data.drivers.find(f'pose.bones["{pivot}"].rotation_euler', index=axis).driver
    v = main.variables.new(); v.name, v.type = 'twist', 'SINGLE_PROP'
    v.targets[0].id = arm; v.targets[0].data_path = path
    main.expression += ' + twist'


def brow_tweak_controls(arm, cfg=None):
    """cfg brow_tweaks off on a rig with its own Eyebrow1-4 nodes (reused; a new build makes none): they still carry the
    brow segments (the brow controls move them) but are no controls of their own: no shape, in Mechanism. On: left as Build placed them (Face Tweak). Returns the nodes hidden."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    if wants(cfg, 'brow_tweaks'):
        return []
    hidden = [nm for n in BROW_NODES for nm in (n, rn.with_side(n, 'R')) if nm in arm.pose.bones]
    for nm in hidden:
        arm.pose.bones[nm].custom_shape = None
        bc.place_bone(arm, nm, 'Mechanism', False)
    return hidden


def lid_twist(arm, cfg=None, log=print):
    """Lid tweak twist: rotating a lid tweak on its own Y (R from the front, its only free rotation) turns that part
    of the lid round the tweak, the neighbours see-sawing with falloff (twist_shares); moving a tweak is unchanged.
    The tweaks get a SelectionSphere shape (a front ring shows no twist). cfg['lid_twist'] off takes it out again.
    Works on a built rig in place (safe to run again; the blink shaping keeps it). Returns the pivots written."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    n = (cfg['pivots'] - 2) // 2
    tweaked = range(1, n + 1, LID_TWEAK_EVERY)
    P = arm.pose.bones
    if lid_tweak_name(lid_tip('Upper', 1)) not in P:
        return []
    on = cfg.get('lid_twist', True)
    done = set()
    for side in SIDES:
        terms = defaultdict(list)             # pivot -> [(variable, tweak, rx, rz)]; the corners take both lids'
        for lid in ('Upper', 'Lower'):
            for t in lid_chain(cfg, lid):
                clear_lid_twist(arm, rn.mch(rn.with_side(t, side)))
            for k in tweaked:
                tweak = lid_tweak_name(rn.with_side(lid_tip(lid, k), side))
                tb = P[tweak]
                tb.rotation_mode = 'XYZ'
                if not on:                      # a posed twist stays when run again
                    tb.rotation_euler = (0, 0, 0)
                tb.lock_rotation = (True, not on, True)
                shape(tb, 'SelectionSphere' if on else 'WGT-Ring', LID_TWEAK_SIZE * cfg['size'])
                if on:
                    for pivot, (rx, rz) in twist_shares(arm, cfg, side, lid, k).items():
                        terms[pivot].append((f'{lid[0]}{k}', tweak, rx, rz))
        for pivot, ts in terms.items():
            twist_driver(arm, pivot, 0, [(v, t, x) for v, t, x, _ in ts])
            twist_driver(arm, pivot, 2, [(v, t, z) for v, t, _, z in ts])
            done.add(pivot)
    arm.update_tag()
    bpy.context.view_layer.update()
    log(f'FR# lid twist {"on" if on else "off"}: {len(done)} pivots')
    return sorted(done)


def lid_push(arm, cfg=None, log=print):
    """Lid push: as the upper lid closes, the lid pivots (both lids) stretch along their Y (forward, out of the
    face) by cfg['lid_push'] = (all, the pair by the inner corner), full by LID_PUSH_RAMP of the upper lid's
    travel, so the closing lid edge stays out of the eyeball and the shut lid keeps a dome. Nothing at rest or
    with the upper lid open; push 0 takes it out. Works on a built rig in place (safe to run again).
    Returns the pivots driven."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    every, inner = cfg.get('lid_push', EYE['lid_push'])
    n = (cfg['pivots'] - 2) // 2
    B, P = arm.data.bones, arm.pose.bones
    done = []
    for side in SIDES:
        upper = rn.with_side(rn.left('UpperLid'), side)
        if upper not in B:
            continue
        ramp = B[upper]['travel'] * LID_PUSH_RAMP
        for lid in ('Upper', 'Lower'):
            for k in range(1, n + 1):
                pb = P[rn.mch(rn.with_side(lid_tip(lid, k), side))]
                amount = inner if k == 1 else every
                pb.driver_remove('scale', 1)
                pb.scale[1] = 1.0
                if amount:
                    drive(pb, 'scale', 1, f'1 + ({amount:.3f})*min(max(-up/{ramp:.5f},0),1)',
                          {'up': (upper, 'LOC_Z', 'TRANSFORM_SPACE')})
                    done.append(pb.name)
    bpy.context.view_layer.update()
    log(f'FR# lid push: {len(done)} pivots')
    return done


def lid_extras(arm, cfg=None, log=print):
    """Lid twist + lid push, in place on a built Eye Rig (also the last eye step of Build). A rig built with old names
    moves to the standard ones first."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    standardise_face(arm, cfg['lid_mode'])
    return {'twist': lid_twist(arm, cfg, log), 'push': lid_push(arm, cfg, log)}

# ---------------------------------------------------------------- mesh helpers (also used by face_stress)
def face_bones(arm, head='Head'):
    """Deform bones that hang on the head: through parents, or through the constraint targets of a
    parentless bone (Armature-constraint followers)."""
    memo = {}

    def on_head(b):
        if b.name not in memo:
            memo[b.name] = False
            pb = arm.pose.bones[b.name]
            if b.parent:
                memo[b.name] = b.parent.name == head or on_head(b.parent)
            else:
                subs = [t.subtarget for c in pb.constraints for t in getattr(c, 'targets', [])]
                subs += [c.subtarget for c in pb.constraints if getattr(c, 'subtarget', '')]
                memo[b.name] = any(s == head or (s in arm.data.bones and on_head(arm.data.bones[s])) for s in subs)
        return memo[b.name]
    return {b.name for b in arm.data.bones if b.use_deform and b.name != head and on_head(b)}


def face_groups(obj, arm, head='Head'):
    fb = face_bones(arm, head)
    return {g.name for g in obj.vertex_groups if g.name in fb}


def free_groups(obj, arm, head='Head'):
    """Groups the face tools may rescale: face bones (both sides), the head, and dead groups (no bone, no
    modifier uses them: leftovers of an old rig that would hold lid vertices still). All else stays exact."""
    fg = face_groups(obj, arm, head)
    return fg | {head} | {rn.flip(g) for g in fg} | dead_groups(obj, arm)


def dead_groups(obj, arm):
    """Vertex groups of obj that no bone of arm deforms and nothing else reads (modifiers, shape keys)."""
    used = set()
    for m in obj.modifiers:
        for prop in m.bl_rna.properties:
            if prop.type == 'STRING':
                used.add(getattr(m, prop.identifier))
        if m.type == 'NODES':                 # Geometry Nodes attribute inputs
            used |= {v for v in m.values() if isinstance(v, str)}
    for kb in (obj.data.shape_keys.key_blocks if obj.data.shape_keys else []):
        used.add(kb.vertex_group)
    bones = {b.name for b in arm.data.bones}
    return {g.name for g in obj.vertex_groups if g.name not in bones and g.name not in used}


def snapshot(o):
    gi = {g.index: g.name for g in o.vertex_groups}
    return [{gi[g.group]: round(g.weight, 6) for g in v.groups} for v in o.data.vertices]


def copy_head(a, b, verts):
    """Copy all weights of a's `verts` to b's vertices at the same position. Returns the unmatched count."""
    kd = KDTree(len(b.data.vertices))
    for v in b.data.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    ga = {g.index: g.name for g in a.vertex_groups}
    gb = {g.name: g for g in b.vertex_groups}
    miss = 0
    for i in verts:
        _, j, d = kd.find(a.data.vertices[i].co)
        if d > 1e-6:
            miss += 1; continue
        for g in list(b.data.vertices[j].groups):
            b.vertex_groups[g.group].remove([j])
        for g in a.data.vertices[i].groups:
            n = ga[g.group]
            if n not in gb:
                gb[n] = b.vertex_groups.new(name=n)
            gb[n].add([j], g.weight, 'REPLACE')
    return miss


def eval_coords(obj, deps, mods_off=('SUBSURF',), matrix=None):
    """Evaluated vertex positions (world, or through `matrix`) with subdivision and GN off, plus edges / polys."""
    with dm.hidden_modifiers(obj, set(mods_off) | {'NODES'}):
        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        M = matrix if matrix is not None else obj.matrix_world
        co = [M @ v.co for v in me.vertices]
        topo = ([tuple(e.vertices) for e in me.edges], [tuple(p.vertices) for p in me.polygons])
        ev.to_mesh_clear()
    return co, topo


class LidParts:
    """Lid liners (tubes along the lid edge) and lashes on the liner mesh, found as loose parts near the
    rest lid ring (left side). measure() (face_stress) checks them in a pose. `matrix`: coordinates frame
    (default world); `size` scales the distance thresholds."""
    def __init__(self, obj, ring, matrix=None, size=1.0):
        self.obj = obj
        self.n0 = len(obj.data.vertices)
        rest, _ = eval_coords(obj, None, matrix=matrix)
        self.rest = rest[:self.n0]
        cz = sum(p.z for p in ring) / len(ring)
        cx = sum(p.x for p in ring) / len(ring)
        bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
        lab, _ = cw.components(bm, set())
        bm.free()
        comps = defaultdict(list)
        for i, c in lab.items():
            comps[c].append(i)
        self.liners, self.lashes, self.lash_verts, self.lash_side = {}, [], [], []
        for vs in comps.values():
            pts = [self.rest[i] for i in vs]
            if sum(p.x for p in pts) < 0:
                continue
            d = min(min((p - q).length for q in ring) for p in pts)
            if d > 0.006 * size:
                continue                                    # brows
            ext = max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3))
            if ext > 0.025 * size:
                side = 'upper' if sum(p.z for p in pts) / len(pts) > cz else 'lower'
                bins = defaultdict(list)                    # cross-sections: verts at the same angle round the eye
                for i in vs:
                    p = self.rest[i]
                    bins[round(math.degrees(math.atan2(p.z - cz, p.x - cx)) / 1.5)].append(i)
                self.liners[side] = [bins[k] for k in sorted(bins) if len(bins[k]) >= 4]
            else:
                root = min(vs, key=lambda i: min((self.rest[i] - q).length for q in ring))
                tip = max(vs, key=lambda i: (self.rest[i] - self.rest[root]).length)
                self.lashes.append((root, tip))
                self.lash_verts.append(vs)
        for o, _ in self.lashes:       # a lash belongs to the lid whose liner its root sits on
            near = {sd: min((self.rest[o] - self.rest[i]).length for b in bins for i in b) for sd, bins in self.liners.items()}
            self.lash_side.append(min(near, key=near.get) if near else 'upper')

    @staticmethod
    def thickness(co, bins):
        """Tube diameter per cross-section (the verts in a thin slice by angle round the eye)."""
        return [max((co[i] - co[j]).length for i in b for j in b) for b in bins]

    def diameter(self):
        d = [x for bins in self.liners.values() for x in self.thickness(self.rest, bins)]
        return sorted(d)[len(d) // 2] if d else 0.0


def arm_matrix(arm, obj):
    """obj's mesh coordinates -> armature space."""
    return arm.matrix_world.inverted() @ obj.matrix_world


class rig_space:
    """Context: meshes whose object transform differs from the armature's (an origin offset) get their vertices
    (and shape keys) moved into the armature's space for the build, then put back exactly, so every loop / weight
    helper can compare vertex coordinates with armature-space guides and bones. A mirrored mesh may only be
    offset along Y / Z or turned round X (moving its local X would move its mirror plane)."""
    def __init__(self, arm, objs):
        self.arm, self.objs, self.saved = arm, [o for o in objs if o is not None and o.type == 'MESH'], []

    def __enter__(self):
        for o in self.objs:
            M = arm_matrix(self.arm, o)
            if all(abs(M[i][j] - (i == j)) < 1e-6 for i in range(4) for j in range(4)):
                continue
            x_moved = any(abs(M[i][0] - (i == 0)) > 1e-6 for i in range(3)) or abs(M[0][3]) > 1e-6
            if has_mirror(o) and x_moved:      # a turn round X keeps the mirror plane
                raise ValueError(f'{o.name}: rotated or moved sideways against the armature with a Mirror modifier; '
                                 'apply its transform first')
            if o.data.users > 1:
                raise ValueError(f'{o.name}: its mesh is shared; make it single user (or apply its transform) first')
            me = o.data
            co = [0.0] * (3 * len(me.vertices)); me.vertices.foreach_get('co', co)
            keys = []
            for kb in (me.shape_keys.key_blocks if me.shape_keys else []):
                k = [0.0] * (3 * len(kb.data)); kb.data.foreach_get('co', k); keys.append(k)
            self.saved.append((o, o.matrix_world.copy(), co, keys))
            me.transform(M, shape_keys=True)
            o.matrix_world = self.arm.matrix_world.copy()
        return self

    def __exit__(self, *exc):
        for o, mw, co, keys in self.saved:
            o.data.vertices.foreach_set('co', co)
            for kb, k in zip(o.data.shape_keys.key_blocks if o.data.shape_keys else [], keys):
                kb.data.foreach_set('co', k)
            o.data.update()
            o.matrix_world = mw
        return False


def check_space(arm, obj):
    M = arm_matrix(arm, obj)
    ident = all(abs(M[i][j] - (i == j)) < 1e-4 for i in range(4) for j in range(4))
    if not ident:
        raise ValueError(f'{obj.name}: its transform differs from the armature\'s; apply it (or parent it without '
                         'an offset) before building weights')


def find_loop(obj, guide_pts, closed, tol, other=None):
    """Vertex indices of the mesh edge loop that runs along the guide points (smoothed), or []. Open lines
    (lips) run from the first guide (on the mirror plane) to the last (the corner): only the half on the
    guides' side counts, ordered first -> last, cut at the vertex nearest the last guide (the corner), and it
    must reach both ends' x within 2.5 tol; a loop round the whole mouth opening gives one lip (one_lip).
    The clean quad edge loop nearest the guide curve (edges within tol start a walk); if there is none (poles
    on the edge, or the clean loop misses a guide by more than 2.5 tol) the cheapest edge path that hugs the
    guide curve. A clean loop next to an edge with poles can still win over it, so guides for such an edge
    should sit right on it."""
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
    try:
        pts = smooth_polyline(guide_pts, closed)
        if closed:
            idx = cw.find_ring(bm, pts, closed=True, tol=tol)
        else:                             # open lines: every nearby loop, judged by the part that becomes the line
            lines = [l for l in (open_line(bm, i, guide_pts, pts, tol, other)
                                 for i in cw.find_ring(bm, pts, False, tol, every=True)) if l]
            off = lambda l: sum(cw.loop_distance(bm.verts[i].co, pts, False) for i in l) / len(l)
            idx = min(lines, key=off) if lines else []
        if idx and max(min((bm.verts[i].co - g).length for i in idx) for g in guide_pts) > 2.5 * tol:
            idx = []                         # a clean loop that misses a guide (a neighbouring ring) isn't the edge
        if not idx:                          # no clean loop (poles on the edge): the traced path
            idx = trace_loop(bm, guide_pts, pts, closed, tol)
        return idx
    finally:
        bm.free()


def open_line(bm, idx, guide_pts, curve, tol, other=None):
    """An open loop -> the lip line it gives: the half on the guides' side, one lip of a whole-opening loop
    (one_lip), ordered first guide -> last, cut at the vertex nearest the last guide (the corner); [] unless it
    reaches both ends' x within 2.5 tol."""
    idx = [i for k, i in enumerate(idx) if k == 0 or i != idx[k - 1]]     # an open walk can repeat its seam vertex
    sx = 1 if guide_pts[-1].x >= 0 else -1
    idx = [i for i in idx if bm.verts[i].co.x * sx >= -1e-4]
    idx = one_lip(bm, idx, guide_pts, curve, tol, other)
    if idx and (bm.verts[idx[0]].co - guide_pts[0]).length > (bm.verts[idx[-1]].co - guide_pts[0]).length:
        idx = idx[::-1]
    if idx:                               # the line ends at the corner guide (a loop running on into a fold stops)
        k = min(range(len(idx)), key=lambda j: (bm.verts[idx[j]].co - guide_pts[-1]).length)
        idx = idx[:k + 1]
    if not idx or abs(bm.verts[idx[0]].co.x - guide_pts[0].x) > 2.5 * tol \
            or abs(bm.verts[idx[-1]].co.x - guide_pts[-1].x) > 2.5 * tol:
        return []
    return idx


def one_lip(bm, idx, guide_pts, curve, tol, other=None):
    """An open loop that runs round the mouth corner and back (the whole mouth opening as one loop: upper lip
    out, lower lip back, both ends on the mirror plane) -> one lip: cut at the turning point (the vertex
    farthest from the two ends), each half trimmed at its vertex nearest the corner guide (a corner that
    folds back into the cheek stays out of the lips). The half kept hugs this lip's guide curve; with `other`
    (the other lip's guide points) the halves are shared out by which curve each is nearer to, so lips that
    overlap (an upper lip hanging in front of the lower one) still get one half each.
    Other loops come back unchanged."""
    if len(idx) < 4:
        return idx
    co = [bm.verts[i].co for i in idx]
    if abs(co[0].x - guide_pts[0].x) > 2.5 * tol or abs(co[-1].x - guide_pts[0].x) > 2.5 * tol:
        return idx
    mid = (co[0] + co[-1]) / 2
    t = max(range(len(co)), key=lambda j: (co[j] - mid).length)
    if t in (0, len(idx) - 1):
        return idx
    halves = []
    for h in (idx[:t + 1], idx[t:][::-1]):
        k = min(range(len(h)), key=lambda j: (bm.verts[h[j]].co - guide_pts[-1]).length)
        halves.append(h[:k + 1])
    off = lambda h, c: sum(cw.loop_distance(bm.verts[i].co, c, False) for i in h) / len(h)
    if other is None:
        return min(halves, key=lambda h: off(h, curve))
    curve_o = smooth_polyline(other, False)
    return min(halves, key=lambda h: off(h, curve) - off(h, curve_o))


def trace_loop(bm, guide_pts, curve, closed, tol):
    """Edge path through the vertices nearest the guides, each leg the cheapest path where an edge costs its
    length x (1 + (distance from the guide curve / tol)^2): it follows the mesh's edge flow along the curve."""
    import heapq
    kd = KDTree(len(bm.verts))
    for v in bm.verts:
        kd.insert(v.co, v.index)
    kd.balance()
    stops = [kd.find(p)[1] for p in guide_pts]
    off = {}

    def cost(e):
        k = e.index
        if k not in off:
            m = (e.verts[0].co + e.verts[1].co) / 2
            off[k] = cw.loop_distance(m, curve, closed)
        return e.calc_length() * (1 + (off[k] / tol) ** 2)
    path, used = [stops[0]], {stops[0]}
    legs = list(zip(stops, stops[1:] + ([stops[0]] if closed else [])))
    for a, b in legs:
        if a == b:
            continue
        dist, prev, heap = {a: 0.0}, {}, [(0.0, a)]
        while heap:
            d, i = heapq.heappop(heap)
            if i == b:
                break
            if d > dist.get(i, 1e9):
                continue
            for e in bm.verts[i].link_edges:
                j = e.other_vert(bm.verts[i]).index
                if j in used and j != b:
                    continue
                nd = d + cost(e)
                if nd < dist.get(j, 1e9):
                    dist[j] = nd; prev[j] = i; heapq.heappush(heap, (nd, j))
        if b not in prev:
            return []
        leg, i = [], b
        while i != a:
            leg.append(i); i = prev[i]
        for i in reversed(leg):
            path.append(i); used.add(i)
    if closed and path[-1] == path[0]:
        path.pop()
    return path if len(path) > 2 else []


def auto_size(guides):
    """Size factor (1 = Digit) from the eye guides' width, else the mouth corner."""
    if 'LidInner' in guides and 'LidOuter' in guides:
        return round(abs(guides['LidOuter'].x - guides['LidInner'].x) / DIGIT_EYE_WIDTH, 2)
    if 'MouthCorner' in guides:
        return round(abs(guides['MouthCorner'].x) / DIGIT_MOUTH_HALF, 2)
    return 1.0


def has_mirror(obj):
    return any(m.type == 'MIRROR' and m.use_axis[0] for m in obj.modifiers)


# ---------------------------------------------------------------- geometry
def frame(side):
    """Right side points are handled in the left frame (x mirrored)."""
    return (lambda v: v.copy()) if side == 'L' else mirror


def guide(cfg, name, side):
    """A guide point in the left frame for `side` (mirror on: the left guide)."""
    G = cfg['guides']
    if side == 'R' and not cfg['mirror'] and name not in CENTRE_GUIDES and rn.guide_name(name, 'R') in G:
        return mirror(G[rn.guide_name(name, 'R')])
    return G[name].copy()


def eye_geometry(arm, body, cfg, side, parts_obj=None):
    """Lid ring (from the skin's edge loop through the ring guides, or the smoothed guides themselves),
    lid nodes, brow points, eye centre; all in the left frame."""
    s = cfg['size']
    F = frame(side)
    g = {'side': side}
    ring_g = [guide(cfg, n, side) for n in RING_GUIDES]
    idx = []
    if body is not None:
        idx = find_loop(body, [F(p) for p in ring_g], True, 0.006 * s)
    M = arm_matrix(arm, body) if body is not None else None
    if idx:
        ring = [F(M @ body.data.vertices[i].co) for i in idx]
    else:
        ring = smooth_polyline(ring_g, True)
    g['eye_ring'] = idx
    eb = arm.data.bones.get(rn.with_side(cfg['eye_bone'], side))
    rim = shell_rim(arm, lid_shells(cfg), ring, F(eb.head_local) if eb else guide(cfg, 'Eye', side), F) if idx else None
    g['shell_rim'] = rim is not None
    if rim:                    # lid shells cover the skin's eye hole: their inner rim is the lid edge you see
        ring = rim
    upper, lower = split_ring(ring)
    g['lid_upper'], g['lid_lower'] = upper, lower
    n = (cfg['pivots'] - 2) // 2
    fr = [k / (n + 1) for k in range(1, n + 1)]
    g['up_nodes'], g['lo_nodes'] = resample(upper, fr), resample(lower, fr)
    g['inner'], g['outer'] = upper[0], upper[-1]
    g['eye_c'] = guide(cfg, 'Eye', side)
    if eb:
        g['eye_c'] = F(eb.head_local)
        g['eye_t'] = F(eb.tail_local)
    elif 'EyeAim' in cfg['guides']:
        g['eye_t'] = guide(cfg, 'EyeAim', side)
    else:
        g['eye_t'] = g['eye_c'] + FWD * 0.03 * s
    nodes = [arm.data.bones.get(nm) for nm in brow_nodes(arm.data.bones, side)]
    g['brow'] = [F(b.head_local) for b in nodes] if all(nodes) else [guide(cfg, nm, side) for nm in BROW_GUIDES]
    g['parts'] = None
    g['liner_gap'] = 0.0
    if parts_obj is not None:
        g['parts'] = LidParts(parts_obj, [M @ body.data.vertices[i].co for i in idx] if idx else ring,
                              matrix=arm_matrix(arm, parts_obj), size=s)
        g['liner_gap'] = cfg['liner_gap'] * g['parts'].diameter()
    return g


LID_SHELL = re.compile(r'lid', re.I)
SHELL_BIN = math.radians(6)            # half width of the angle bins the shell rim is read in


def lid_shells(cfg):
    """The skin parts that are separate eyelid meshes (lid shells), mirrored ones only (their base is one side)."""
    objs = (bpy.data.objects.get(n) for n in cfg.get('skin_parts', []))
    return [o for o in objs if o is not None and o.type == 'MESH' and LID_SHELL.search(o.name) and has_mirror(o)]


def shell_rim(arm, shells, ring, c, F, samples=72):
    """Lid shells that cover part of the skin's eye opening (thick lids sitting on the eyeball): their inner rim,
    the lid edge you see from the front, as a closed line round the eye centre c (left frame; `samples` angles,
    the shell point nearest c in the front view per angle, the skin's ring where no shell is; shells as evaluated,
    so with their Subdivision). None without shells, with shells round less than half the eye, or when the rim isn't well inside the skin's ring (shells that
    only lie on the skin)."""
    if not shells:
        return None
    deps = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in shells:
        M = arm_matrix(arm, o)
        ev = o.evaluated_get(deps)
        me = ev.to_mesh()
        pts += [F(M @ v.co) for v in me.vertices]
        ev.to_mesh_clear()
    pts = [p for p in pts if p.x > 0 and p.y < c.y]          # this eye's shells, in front of its centre
    pol = lambda p: math.atan2(p.z - c.z, p.x - c.x)
    rad = lambda p: math.hypot(p.x - c.x, p.z - c.z)
    rim, found = [], []
    for k in range(samples):
        a = -math.pi + 2 * math.pi * k / samples
        near = [p for p in pts if abs(wrap(pol(p) - a)) < SHELL_BIN]
        if near:
            found.append(min(near, key=rad))
        rim.append(found[-1] if near else ring_at_angle(ring, c, a))      # no shell there (a corner): the skin
    mid = lambda xs: sorted(xs)[len(xs) // 2]
    if len(found) < samples // 2 or mid([rad(p) for p in found]) > 0.85 * mid([rad(q) for q in ring]):
        return None
    return rim


def weight_lid_shells(arm, cfg, g, free):
    """Lid shells turn round the eye centre with their own lid, as one piece (cross-sections never squash): each
    shell is the upper or lower lid by where it sits; each vertex takes that lid's two lid bones on either side
    of its angle round the eye (front view), the corner bone past the corners. Right sides by the Mirror."""
    out = {}
    if not (g.get('shell_rim') and g.get('eye_ring')):
        return out
    c = g['eye_c']
    B = arm.data.bones
    names = cfg_lid_names(cfg)
    n = (cfg['pivots'] - 2) // 2
    lids = {'Upper': [names[0]] + names[1:n + 2], 'Lower': [names[0]] + names[n + 2:][::-1] + [names[n + 1]]}
    for o in lid_shells(cfg):
        M = arm_matrix(arm, o)
        co = [M @ v.co for v in o.data.vertices]
        lid = 'Upper' if sum(p.z for p in co) / len(co) > c.z else 'Lower'
        sg = 1 if lid == 'Upper' else -1           # angles that run inner corner -> outer corner, no wrap
        ang = lambda p: (math.atan2(sg * (p.z - c.z), p.x - c.x) + 0.5 * math.pi) % (2 * math.pi) - 0.5 * math.pi
        tips = [(ang(B[nm].tail_local), nm) for nm in lids[lid]][::-1]          # outer -> inner: angle rising
        groups = free | free_groups(o, arm, cfg['head'])
        for i, p in enumerate(co):
            a = ang(p)
            if a <= tips[0][0]:
                acc = {tips[0][1]: 1.0}
            elif a >= tips[-1][0]:
                acc = {tips[-1][1]: 1.0}
            else:
                k = next(k for k in range(len(tips) - 1) if tips[k][0] <= a <= tips[k + 1][0])
                t = (a - tips[k][0]) / (tips[k + 1][0] - tips[k][0])
                acc = {tips[k][1]: 1 - t, tips[k + 1][1]: t}
            cw._write_free(o, i, acc, groups, 4, 0.01)
        out[o.name] = (lid, len(co))
    return out


def lid_shell_weights(arm, cfg=None, log=print):
    """In place on a built rig: lid shell skin parts re-weighted to turn with their lids (weight_lid_shells)."""
    cfg = cfg or stored(arm, 'eye')
    src = bpy.data.objects.get(cfg['meshes'][0]) if cfg and cfg['meshes'] else None
    if src is None:
        return {}
    shells = lid_shells(cfg)
    with rig_space(arm, [src] + shells):
        reset = control_pose(arm, arm.pose.bones.keys())
        reset_pose(arm)
        try:
            g = eye_geometry(arm, src, cfg, 'L')
            free = free_groups(src, arm, cfg['head'])
            out = weight_lid_shells(arm, cfg, g, free)
        finally:
            restore_pose(arm, reset)
    for o in shells:
        cw.ensure_mirror_groups(o, only=new_deform(arm, cfg['head']))
    log('M# lid shells re-weighted', out)
    return out


def off_centre(line, near):
    """A lip line (centre -> corner) touches the centre plane at its start only. A low-poly mouth's loop can run along
    the mirror seam first, which put the Inner nodes on the centre plane: the lip tangent between them got no length and
    turned the lip B-bones at rest."""
    return line[:1] + [p for p in line[1:] if abs(p.x) > near]


def maw_geometry(arm, body, cfg, side):
    """Upper / lower lip lines (centre -> corner) from the skin's loops through the lip guides, nodes."""
    s = cfg['size']
    F = frame(side)
    M = arm_matrix(arm, body) if body is not None else None
    g = {'side': side}
    lips = {'lip_up': ['LipUpper', 'LipUpperMid', 'MouthCorner'], 'lip_lo': ['LipLower', 'LipLowerMid', 'MouthCorner']}
    for key, names in lips.items():
        pts = [guide(cfg, n, side) for n in names]
        other = [F(guide(cfg, n, side)) for n in lips['lip_lo' if key == 'lip_up' else 'lip_up']]
        idx = find_loop(body, [F(p) for p in pts], False, 0.006 * s, other) if body is not None else []
        if idx:
            line = [F(M @ body.data.vertices[i].co) for i in idx]          # centre -> corner
        else:
            line = smooth_polyline(pts, False)
        near = 0.1 * MM * s
        if len(off_centre(line, near)) < 2:               # the loop only runs along the mirror seam: no lip shape in it
            idx, line = [], smooth_polyline(pts, False)
        g[key] = idx
        g[key + '_line'] = off_centre(line, near)
    T = [0, 0.25, 0.5, 0.75, 1.0]
    g['lip_up_nodes'], g['lip_lo_nodes'] = resample(g['lip_up_line'], T), resample(g['lip_lo_line'], T)
    corner = (g['lip_up_nodes'][-1] + g['lip_lo_nodes'][-1]) / 2
    g['lip_up_nodes'][-1] = g['lip_lo_nodes'][-1] = corner
    for nodes in (g['lip_up_nodes'], g['lip_lo_nodes']):
        nodes[0].x = 0.0
    return g


def replaced_bones(arm, prefixes, keep=()):
    return [b.name for b in arm.data.bones if b.name not in keep
            and any(stem(b.name).startswith(o) for o in prefixes if o)]


def bone_tree(arm):
    """{bone: (parent or None, deforms)}: the rig's hierarchy, kept to look up heirs after the bones are gone."""
    return {b.name: (b.parent.name if b.parent else None, b.use_deform) for b in arm.data.bones}


def deform_heir(arm, gone, head='Head', tree=None):
    """Removed deform bone -> nearest deforming ancestor that stays (where its weight goes). tree: an earlier
    bone_tree() to read the hierarchy from (default: the rig as it is)."""
    tree = tree or bone_tree(arm)
    out = {}
    for n in gone:
        p, deform = tree[n]
        if not deform:
            continue
        while p and (p in gone or not tree[p][1]):
            p = tree[p][0]
        out[n] = p or head
    return out


def merge_groups(obj, heir):
    """Groups of removed bones -> their heir's group (adds up); both sides."""
    gi = {g.index: g.name for g in obj.vertex_groups}
    full = dict(heir); full.update({rn.flip(k): rn.flip(v) for k, v in heir.items()})
    for v in obj.data.vertices:
        acc = {}
        for gr in v.groups:
            n = gi[gr.group]
            if n in full and gr.weight > 0:
                acc[full[n]] = acc.get(full[n], 0) + gr.weight
        if not acc:
            continue
        for gr in list(v.groups):
            if gi[gr.group] in full:
                obj.vertex_groups[gr.group].remove([v.index])
        for n, w in acc.items():
            vg = obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n)
            cur = next((gr.weight for gr in v.groups if gr.group == vg.index), 0.0)
            vg.add([v.index], cur + w, 'REPLACE')


# ---------------------------------------------------------------- bones
def lid_points(g, names):
    """{lid bone: lid edge point} (left frame)."""
    n = len(g['up_nodes'])
    pts = {names[0]: g['inner'], names[n + 1]: g['outer']}
    for i in range(n):
        pts[names[1 + i]] = g['up_nodes'][i]                 # upper 1..n
        pts[names[-1 - i]] = g['lo_nodes'][i]                # lower n..1 closes the ring
    return pts


def build_eye_bones(arm, cfg, G):
    A = arm.data; E = A.edit_bones
    s, head = cfg['size'], cfg['head']
    gl, gr = G['L'], G['R']
    names = cfg_lid_names(cfg)
    eye = cfg['eye_bone']
    if eye not in E:                                     # no eye bone: make one per side
        both(A, eye, gl['eye_c'], gl['eye_t'], head, right=(gr['eye_c'], gr['eye_t']), deform=True)
    eye_roll = E[eye].roll
    c, et = gl['eye_c'], gl['eye_t']
    both(A, rn.left('EyeSocket'), c, c + FWD * 0.03 * s, head, right=(gr['eye_c'], gr['eye_c'] + FWD * 0.03 * s), deform=True)
    for sd in SIDES:
        E[rn.with_side(eye, sd)].parent = E[rn.build('EyeSocket', sd)]
    pl, pr = lid_points(gl, names), lid_points(gr, names)
    for n in names:
        piv = both(A, rn.mch(n), c, et, rn.left('EyeSocket'), right=(gr['eye_c'], gr['eye_t']), roll=eye_roll)
        for b in piv:
            if b.z_axis.z < 0.7:              # an eye bone rolled sideways (X up): the pivots get Z up, X across
                b.align_roll(Vector((0, 0, 1)))
        both(A, n, c, pl[n], rn.mch(n), right=(gr['eye_c'], pr[n]), deform=True)
    mid = len(gl['up_nodes']) // 2
    for n, key in ((rn.left('UpperLid'), 'up_nodes'), (rn.left('LowerLid'), 'lo_nodes')):
        h, hr = gl[key][mid] + FWD * 0.004 * s, gr[key][mid] + FWD * 0.004 * s
        both(A, n, h, h + FWD * 0.006 * s, rn.left('EyeSocket'), right=(hr, hr + FWD * 0.006 * s))
    if not cfg['brows']:
        return
    # brows: master + 3 controls; the node bones (tweaks) hang on MCH followers; segments are B-bone curves
    br, brr = gl['brow'], gr['brow']
    m, mr = resample(br, [0.5])[0], resample(brr, [0.5])[0]
    both(A, rn.left('Brow'), m + FWD * 0.004 * s, m + FWD * 0.016 * s, head, right=(mr + FWD * 0.004 * s, mr + FWD * 0.016 * s))
    for n, p, q in zip(BROW_CTRL, (br[0], m, br[3]), (brr[0], mr, brr[3])):
        both(A, n, p, p + FWD * 0.006 * s, rn.left('Brow'), right=(q, q + FWD * 0.006 * s))
    new_nodes = BROW_NODES[0] not in E and wants(cfg, 'brow_tweaks')    # a rig's own nodes are reused
    for k in (1, 2, 3, 4):
        p, q = br[k - 1], brr[k - 1]
        both(A, rn.left(f'Eyebrow{k}', 'MCH'), p, p + FWD * 0.004 * s, right=(q, q + FWD * 0.004 * s))
        if new_nodes:
            both(A, rn.left(f'Eyebrow{k}'), p, p + FWD * 0.002 * s, right=(q, q + FWD * 0.002 * s))
        for sd in SIDES:
            if rn.build('Eyebrow', sd, k) in E:
                E[rn.build('Eyebrow', sd, k)].parent = E[rn.build('Eyebrow', sd, k, 'MCH')]
    if BROW_SEGS[0] not in E:
        nodes = brow_nodes(E)
        for k in (1, 2, 3):
            both(A, rn.left(f'EyebrowSeg{k}', 'DEF'), br[k - 1], br[k], nodes[k - 1], right=(brr[k - 1], brr[k]), deform=True)
    for sd in SIDES:
        smooth_handles(A, [rn.with_side(n, sd) for n in BROW_SEGS])
        for k in (1, 2, 3):
            E[rn.with_side(BROW_SEGS[k - 1], sd)].bbone_segments = 6
            bc.thin_bbones([E[rn.with_side(BROW_SEGS[k - 1], sd)]])


def build_maw_bones(arm, cfg, G):
    A = arm.data; E = A.edit_bones
    s, head = cfg['size'], cfg['head']
    gl, gr = G['L'], G['R']
    jaw = cfg['jaw']
    if jaw not in E:
        J = cfg['guides']
        mk(A, jaw, J['Jaw'], J.get('JawTip', J['Jaw'] + FWD * 0.05 * s), head, deform=True)
    upper = cfg['upper_parent'] or head
    lower = cfg['lower_parent'] or jaw
    cpar = cfg['corner_parent'] or upper
    cn, cnr = gl['lip_up_nodes'][-1], gr['lip_up_nodes'][-1]
    f4, f6 = FWD * 0.004 * s, FWD * 0.006 * s
    both(A, rn.left('MouthCornerJaw', 'MCH'), cn, cn + f4, jaw, right=(cnr, cnr + f4))
    both(A, rn.left('MouthCorner', 'MCH'), cn, cn + f4, cpar, right=(cnr, cnr + f4))
    both(A, rn.left('MouthCorner'), cn, cn + f6, rn.left('MouthCorner', 'MCH'), right=(cnr, cnr + f6))
    both(A, rn.left('MouthCornerLow', 'MCH'), cn, cn + f4, rn.left('MouthCorner', 'MCH'), right=(cnr, cnr + f4))
    for n, p, par in (('UpperLip', gl['lip_up_nodes'][0], upper), ('LowerLip', gl['lip_lo_nodes'][0], lower)):
        mk(A, n, p, p + f6, par)
    for nodes, key in ((UP_NODES, 'lip_up_nodes'), (LO_NODES, 'lip_lo_nodes')):
        for n, p, q in zip(nodes[1:4], gl[key][1:4], gr[key][1:4]):
            both(A, rn.mch(n), p, p + f4, right=(q, q + f4))
            both(A, n, p, p + FWD * 0.005 * s, rn.mch(n), right=(q, q + FWD * 0.005 * s))
    for nodes, segs in ((UP_NODES, UP_SEGS), (LO_NODES, LO_SEGS)):
        # each side runs centre -> corner as a true mirror (Preserve Volume needs mirrored bone frames);
        # the centre stays smooth: the first segment's start handle is a tangent bone from the other side's
        # inner node to this side's (Catmull-Rom tangent through the centre)
        for k, sg in enumerate(segs):
            hl, tl = E[nodes[k]].head.copy(), E[nodes[k + 1]].head.copy()
            hr, tr = E[rn.with_side(nodes[k], 'R')].head.copy(), E[rn.with_side(nodes[k + 1], 'R')].head.copy()
            l, r = both(A, sg, hl, tl, nodes[k], right=(mirror(hr), mirror(tr)), deform=True)
            for eb in (l, r):
                eb.bbone_segments = 8
                bc.thin_bbones([eb])
            l.align_roll(Vector((0, 0, 1))); r.roll = -l.roll
        tan = lip_tangent(segs)
        inner_l, inner_r = E[nodes[1]].head.copy(), E[rn.with_side(nodes[1], 'R')].head.copy()
        both(A, tan, inner_r, inner_l, rn.with_side(nodes[1], 'R'), right=(mirror(inner_l), mirror(inner_r)))
        for side in SIDES:
            chain = [rn.with_side(sg, side) for sg in segs]
            smooth_handles(A, chain)
            E[chain[0]].bbone_handle_type_start = 'TANGENT'
            E[chain[0]].bbone_custom_handle_start = E[rn.with_side(tan, side)]


# ---------------------------------------------------------------- pose setup: constraints, drivers, shapes
def lid_tables(g, cfg, names):
    """Per lid bone: (lid, close angle, tilt factor, follow, radius). Angles in the eye bone's local X (+ = up)."""
    c = g['eye_c']
    pts = lid_points(g, names)
    n = len(g['up_nodes'])
    xm = g['up_nodes'][n // 2].x
    up_f, lo_f, corner_f = cfg['look_follow']
    out = {}
    for nm, p in pts.items():
        a, r = angle_r(p, c)
        if 'Upper' in nm:
            lid, other = 'Upper', g['lid_lower']
        elif 'Lower' in nm:
            lid, other = 'Lower', g['lid_upper']
        else:
            out[nm] = (None, 0.0, 0.0, corner_f, r); continue
        # shut = this lid's edge one liner-width short of the other lid's line: liners touch, never cross
        gap = g['liner_gap'] / r * (1 if lid == 'Upper' else -1)
        close = angle_r(at_x(other, p.x), c)[0] + gap - a
        k = rn.parse(nm).number; t = math.sin(math.pi * k / (n + 1))
        f = (up_f if lid == 'Upper' else lo_f) * (0.5 + 0.5 * t)
        out[nm] = (lid, close, (p.x - xm) / r, f, r)
    return out


def brow_weights_at(x, br):
    """Share of BrowInner / Mid / Outer at a lid point's x (for the brow push)."""
    t = max(0.0, min(1.0, (x - br[0].x) / (br[3].x - br[0].x)))
    return blend2(t, BROW_CTRL)


def lid_travel(g):
    n = len(g['up_nodes'])
    p = g['up_nodes'][n // 2]
    return (p - at_x(g['lid_lower'], p.x)).z


def look_axes(arm, eye, pivot):
    """For the pivot's local X and Z rotation: the eye bone's local rotation channel about the same axis, and its
    sign (the pivots follow the look; ROT_X / ROT_Z, +1 when the two bones share their roll)."""
    E, Pm = arm.data.bones[eye].matrix_local.to_3x3(), arm.data.bones[pivot].matrix_local.to_3x3()
    out = []
    for col in (0, 2):
        d, j = max((abs(E.col[k].dot(Pm.col[col])), k) for k in (0, 2))
        out.append(('ROT_' + 'XYZ'[j], 1.0 if E.col[j].dot(Pm.col[col]) > 0 else -1.0))
    return out


def setup_eye_pose(arm, cfg, G):
    P = arm.pose.bones
    s = cfg['size']
    names = cfg_lid_names(cfg)
    eye = cfg['eye_bone']
    n = len(G['L']['up_nodes'])
    probe = lid_tip('Upper', n // 2 + 1, cfg['lid_mode'])
    # sign check: +X rotation of a pivot must raise the lid point (angle up)
    test = P[rn.mch(probe)]
    test.rotation_mode = 'XYZ'; test.rotation_euler = (0.2, 0, 0)
    bpy.context.view_layer.update()
    gl = G['L']
    sign = 1.0 if angle_r(P[probe].tail, gl['eye_c'])[0] > angle_r(lid_points(gl, names)[probe], gl['eye_c'])[0] else -1.0
    test.rotation_euler = (0, 0, 0)
    travel = {}
    for side, sg in (('L', 1.0), ('R', -1.0)):
        g = G[side]
        D = travel[side] = lid_travel(g)
        tab = lid_tables(g, cfg, names)
        sn = lambda nm: rn.with_side(nm, side)
        eye_s = rn.with_side(eye, side)
        for nm, (lid, close, tilt, f, r) in tab.items():
            pb = P[sn(rn.mch(nm))]; pb.rotation_mode = 'XYZ'
            (cx, sx), (cz, sz) = look_axes(arm, eye_s, pb.name)
            v = {'ex': (eye_s, cx, 'LOCAL_SPACE'), 'ez': (eye_s, cz, 'LOCAL_SPACE')}
            terms = [f'{sx * f:.4f}*ex']
            if lid:
                # a, b: how far the upper / lower lid has travelled to the other lid (1 = shut). A brow
                # pulled down pushes the upper lid along (part of its drop, in lid travel). When a + b
                # pass 1 both scale back, so the lids meet but never cross.
                v['up'] = (sn(rn.left('UpperLid')), 'LOC_Z', 'TRANSFORM_SPACE'); v['lo'] = (sn(rn.left('LowerLid')), 'LOC_Z', 'TRANSFORM_SPACE')
                v['ty'] = (sn(rn.left(f'{lid}Lid')), 'ROT_Y', 'TRANSFORM_SPACE')
                ua = '(-up)'
                if cfg['brows']:
                    v['brow'] = (sn(rn.left('Brow')), 'LOC_Z', 'TRANSFORM_SPACE')
                    drop = 'brow'
                    for bn, w in brow_weights_at(lid_points(g, names)[nm].x, g['brow']).items():
                        if w > 1e-3:
                            key = part_of(bn)[4:].lower()    # inner / mid / outer
                            v[key] = (sn(bn), 'LOC_Z', 'TRANSFORM_SPACE'); drop += f'+{w:.3f}*{key}'
                    ua = f'(-up-{cfg["brow_push"]}*min({drop},0))'
                own = ua if lid == 'Upper' else 'lo'
                terms += [f'{sign * close / D:.5f}*{own}/max(1.0,({ua}+lo)/{D:.5f})', f'{sign * sg * tilt:.5f}*ty']
            drive(pb, 'rotation_euler', 0, shaped_tilt(' + '.join(terms)), v)
            if lid:
                pb['lid_linear'] = ' + '.join(terms)       # the linear driver: shape_blink_drivers starts from it
            drive(pb, 'rotation_euler', 2, f'{sz * f:.4f}*ez', {'ez': v['ez']})
        for lid, lo, hi in (('Upper', -1.25, 0.5), ('Lower', -0.5, 1.25)):
            pb = P[sn(rn.left(f'{lid}Lid'))]
            pb.rotation_mode = 'XYZ'
            pb.lock_location = (True, True, False); pb.lock_rotation = (True, False, True); pb.lock_scale = (True, True, True)
            pb.bone['travel'] = D
            c = pb.constraints.new('LIMIT_LOCATION'); c.owner_space = 'LOCAL'; c.use_transform_limit = True
            c.use_min_z = c.use_max_z = True
            c.min_z, c.max_z = lo * D, hi * D
            shape(pb, 'WGT-Ring', 0.0045 * s)
        shape(P[sn(rn.left('EyeSocket'))], 'WGT-Ring', 0.042 * s, (0, 0.044 * s, 0))
        if P[eye_s].custom_shape is None:        # the eye control (it turns the eye): a small sphere at its tip
            shape(P[eye_s], 'SelectionSphere', EYE_TIP_SIZE * s, (0, P[eye_s].bone.length, 0))
        if not cfg['brows']:
            continue
        shape(P[sn(rn.left('Brow'))], 'WGT-Ring', 0.011 * s)
        face_shapes(arm, s)
        br = g['brow']
        for k in (1, 2, 3, 4):
            t = sum((br[i] - br[i - 1]).length for i in range(1, k)) / sum((br[i] - br[i - 1]).length for i in range(1, 4))
            follow(P[sn(rn.left(f'Eyebrow{k}', 'MCH'))], {sn(b): w for b, w in blend2(t, BROW_CTRL).items()})
        nodes = brow_nodes(P, side)
        for k in (1, 2, 3):
            seg = P[sn(rn.left(f'EyebrowSeg{k}', 'DEF'))]
            if not any(con.type == 'STRETCH_TO' for con in seg.constraints):
                stretch(seg, nodes[k])
            for con in seg.constraints:
                if con.type == 'STRETCH_TO':
                    con.volume = 'NO_VOLUME'
    if cfg.get('smooth_blink', True):
        shape_blink_drivers(arm, cfg, log=lambda *a: None)
    bpy.context.view_layer.update()
    return travel, sign


# ---------------------------------------------------------------- blink shape: partial lids on one smooth arc
NUM = r'-?\d+(?:\.\d+)?'
BLINK_LINEAR = re.compile(rf'^(?P<f>{NUM})\*ex \+ (?P<k>{NUM})\*(?P<x>.+) \+ (?P<tilt>{NUM})\*ty$')
TILT_GAIN = 0.85     # lid tilt (lid control's Y rotation): share of the linear tilt kept for small rolls
TILT_SAT = 0.9       # radians: the tilt eases off past about this roll, and never passes TILT_GAIN * TILT_SAT
TILT_RAW = re.compile(rf'(?P<k>{NUM})\*ty$')


def tilt_term(k):
    """Driver text for a lid pivot's tilt: k * ty for small rolls, easing off for big ones (a saturating curve,
    simple-expression safe), so rolling a lid control never swings the lid off the eye."""
    return f'{float(k) * TILT_GAIN:.5f}*ty/(1+abs(ty)/{TILT_SAT})'


def shaped_tilt(linear):
    """A stored linear lid driver ('... + k*ty') with its tilt term eased (tilt_term)."""
    m = TILT_RAW.search(linear)
    return linear[:m.start()] + tilt_term(m['k']) if m else linear


def blink_controls(xs, z_open, z_shut, corners):
    """Middle control heights for each closing pivot tip's blink path: a quadratic Bezier open -> control -> shut
    in front-view height (z). Linear paths keep the open lid's steep shoulders near the corners while the middle
    already sags (a bump by the corner at half blink); with these controls the whole lid line lies on the
    corner-to-corner chord at the moment its middle passes it, so it stays one arc at every blink amount.
    xs, z_open, z_shut: the lid's pivot tips from the inner to the outer corner; corners: ((x, z) inner, outer).
    Each control stays between its open and shut height (no overshoot)."""
    (x0, z0), (x1, z1) = corners
    chord = lambda x: z0 + (z1 - z0) * (x - x0) / (x1 - x0)
    hu = [z - chord(x) for x, z in zip(xs, z_open)]
    hc = [z - chord(x) for x, z in zip(xs, z_shut)]
    m = len(xs) // 2
    t = hu[m] / (hu[m] - hc[m]) if abs(hu[m] - hc[m]) > 1e-9 else 0.5      # when the middle passes the chord
    t = min(0.75, max(0.25, t))
    out = []
    for x, a, b in zip(xs, hu, hc):
        c = -((1 - t) ** 2 * a + t * t * b) / (2 * t * (1 - t))        # on the chord at t
        out.append(chord(x) + min(max(a, b), max(min(a, b), c)))
    return out


BLINK_FADE = 4.0     # the blink shaping fades out while the other lid closes its first 1/BLINK_FADE (both lids
                     # moving = the linear paths, which meet exactly: shaped ones would overlap at the corners)


def shape_blink_drivers(arm, cfg=None, smooth=True, log=print):
    """Rewrite every closing lid pivot's rotation driver so its tip follows the blink path of blink_controls
    (smooth=False: back to the linear driver). Works on a built rig in place, from each pivot's linear driver
    (stored as 'lid_linear' on the pivot, else the driver itself): same look follow, tilt, brow push, travel
    and the same shut angle (hand-tuned shut poses stay), only the way there changes. The pivot's blink amount
    (the linear driver's, shut at = travel) goes to a driven property 'lid_blink' on the pivot (drivers hold
    at most 256 characters, too few to repeat it); blink <= 0 (wide eyes) stays linear, and so does a lid
    while the other lid closes too (BLINK_FADE). Simple expressions only. Returns the number of pivots written."""
    cfg = cfg or stored(arm, 'eye') or config('eye')
    names = cfg_lid_names(cfg)
    B, P = arm.data.bones, arm.pose.bones
    fcs = {fc.data_path: fc for fc in (arm.animation_data.drivers if arm.animation_data else []) if fc.array_index == 0}
    num = lambda v: f'{v:.7g}'
    n = (cfg['pivots'] - 2) // 2
    done = 0
    for side in SIDES:
        sn = lambda nm: rn.with_side(nm, side)
        if sn(rn.left('UpperLid')) not in B:
            continue
        D = B[sn(rn.left('UpperLid'))]['travel']
        tip = lambda nm: B[sn(nm)].tail_local
        corners = [(tip(c).x, tip(c).z) for c in (names[0], names[n + 1])]
        for lid in ('Upper', 'Lower'):
            rows = []
            for k in range(1, n + 1):                              # inner -> outer corner
                nm = lid_tip(lid, k, cfg['lid_mode'])
                pb = P[sn(rn.mch(nm))]
                fc = fcs[f'pose.bones["{pb.name}"].rotation_euler']
                lin = pb.get('lid_linear') or fc.driver.expression
                mt = BLINK_LINEAR.match(lin)
                assert mt, f'{pb.name}: not a lid driver of this rig: {lin}'
                c = B[pb.name].head_local
                a0, r = angle_r(tip(nm), c)
                sg = -1.0 if B[pb.name].matrix_local.col[0].x > 0 else 1.0     # rotation = sg * angle change
                rows.append(dict(pb=pb, fc=fc, lin=lin, mt=mt, c=c, a0=a0, r=r, sg=sg, close=sg * float(mt['k']) * D,
                                 q=tip(nm)))
            for w in rows:
                w['zs'] = w['c'].z + w['r'] * math.sin(w['a0'] + w['close'])
            ctrl = blink_controls([w['q'].x for w in rows], [w['q'].z for w in rows], [w['zs'] for w in rows], corners)
            for w, zx in zip(rows, ctrl):
                pb, fc, mt = w['pb'], w['fc'], w['mt']
                pb['lid_linear'] = w['lin']
                path = f'pose.bones["{pb.name}"]["lid_blink"]'
                twist = ' + twist' if 'twist' in fc.driver.variables else ''    # lid_twist's term stays
                if not smooth:
                    fc.driver.expression = shaped_tilt(w['lin']) + twist
                    if 'b' in fc.driver.variables:
                        fc.driver.variables.remove(fc.driver.variables['b'])
                    if 'lid_blink' in pb:
                        arm.driver_remove(path)
                        del pb['lid_blink']
                    done += 1
                    continue
                pb['lid_blink'] = 0.0
                arm.driver_remove(path)
                bd = arm.driver_add(path).driver
                bd.type = 'SCRIPTED'
                for v in fc.driver.variables:                   # the blink amount's inputs (up, lo, brow ...)
                    if v.name in mt['x'] and v.type == 'TRANSFORMS':
                        t0 = v.targets[0]; nv = bd.variables.new(); nv.name = v.name; nv.type = 'TRANSFORMS'
                        t = nv.targets[0]; t.id = arm; t.bone_target = t0.bone_target
                        t.transform_type, t.transform_space, t.rotation_mode = t0.transform_type, t0.transform_space, t0.rotation_mode
                bd.expression = mt['x']
                fd = fc.driver
                if 'b' not in fd.variables:
                    v = fd.variables.new(); v.name = 'b'; v.type = 'SINGLE_PROP'
                    v.targets[0].id_type = 'OBJECT'; v.targets[0].id = arm; v.targets[0].data_path = path
                r, a0, zs, q = w['r'], w['a0'], w['zs'], w['q']
                q0, q1, q2 = (q.z - w['c'].z) / r, 2 * (zx - q.z) / r / D, (q.z - 2 * zx + zs) / r / D ** 2
                curve = f"{num(w['sg'])}*(asin(clamp({num(q0)}+b*({num(q1)}+{num(q2)}*b),-1,1))-{num(a0)})"
                lin = f"{mt['k']}*b"
                other = f"lo*{num(BLINK_FADE / D)}" if lid == 'Upper' else f"up*{num(-BLINK_FADE / D)}"
                fd.expression = (f"{mt['f']}*ex + ({lin}+({curve}-{lin})*clamp(1-{other},0,1) if b > 0 else {lin})"
                                 f" + {tilt_term(mt['tilt'])}{twist}")
                assert len(fd.expression) < 256, fd.expression
                done += 1
    arm.update_tag()
    bpy.context.view_layer.update()
    log(f'FR# blink drivers {"shaped" if smooth else "linear"}: {done} pivots')
    return done


def setup_maw_pose(arm, cfg, G):
    P = arm.pose.bones
    s = cfg['size']
    pull_up, pull_lo = cfg['corner_pull']
    for side in SIDES:
        sn = lambda nm: rn.with_side(nm, side)
        c = P[sn(rn.left('MouthCorner', 'MCH'))].constraints.new('COPY_TRANSFORMS')
        c.target = arm; c.subtarget = sn(rn.left('MouthCornerJaw', 'MCH')); c.influence = cfg['corner_jaw_follow']
        shape(P[sn(rn.left('MouthCorner'))], 'WGT-Ring', 0.005 * s)
        for nodes in (UP_NODES, LO_NODES):
            ctr, mid, cor = nodes[0], sn(nodes[2]), sn(nodes[4])
            if nodes is LO_NODES:
                cor = sn(rn.left('MouthCornerLow', 'MCH'))            # the corner with its lift eased (corner_low)
            pull = pull_up if nodes is UP_NODES else pull_lo
            follow(P[rn.mch(mid)], {ctr: 1 - pull, cor: pull})
            inner, outer = UPPER_LIP_ON_MID if nodes is UP_NODES else LOWER_LIP_ON_MID
            follow(P[rn.mch(sn(nodes[1]))], {ctr: 1 - inner, mid: inner})
            follow(P[rn.mch(sn(nodes[3]))], {mid: outer, cor: 1 - outer})
        for segs, nodes in ((UP_SEGS, UP_NODES), (LO_SEGS, LO_NODES)):
            for k, seg in enumerate(segs):
                stretch(P[sn(seg)], sn(nodes[k + 1]))
            stretch(P[sn(lip_tangent(segs))], sn(nodes[1]))
    face_shapes(arm, s)
    corner_low(arm, cfg)
    bpy.context.view_layer.update()


def corner_low(arm, cfg=None):
    """MCH-<Side>MouthCornerLow: the mouth corner as the lower lip sees it. It copies the corner control's
    move, turn and scale, but only `corner_lower_lift` of its lift (moving down or sideways: in full), so a smile
    raises the corners without dragging the lower lip into the teeth. The lower lip's middle and outer points
    follow it instead of the corner (their Armature targets are switched); the last lower segment still ends on
    the corner. Works on a built rig in place (the bone is made if missing). Returns the bones set up."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    lift = cfg.get('corner_lower_lift', DEFAULTS['maw']['corner_lower_lift'])
    A, done = arm.data, []
    if rn.left('MouthCornerLow', 'MCH') not in A.bones and rn.left('MouthCorner') in A.bones:
        view = bpy.context.view_layer
        active, mode = view.objects.active, arm.mode
        view.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        E = A.edit_bones
        for side in SIDES:
            c = E[rn.build('MouthCorner', side)]
            mk(A, rn.build('MouthCornerLow', side, role='MCH'), c.head, c.head + (c.tail - c.head) * 0.66, rn.build('MouthCorner', side, role='MCH'), roll=c.roll)
        bpy.ops.object.mode_set(mode='POSE')
        for side in SIDES:
            bc.place_bone(arm, rn.build('MouthCornerLow', side, role='MCH'), 'Mechanism', False)
        bpy.ops.object.mode_set(mode=mode if mode in ('POSE', 'OBJECT') else 'POSE')
        view.objects.active = active
    P = arm.pose.bones
    for side in SIDES:
        low, ctl = P.get(rn.build('MouthCornerLow', side, role='MCH')), rn.build('MouthCorner', side)
        if not low:
            continue
        for k, axis in enumerate('XYZ'):
            v = {'c': (ctl, f'LOC_{axis}', 'TRANSFORM_SPACE')}
            eased = axis == 'Z' and lift < 1
            drive(low, 'location', k, f'min(c,0)+{lift:.4f}*max(c,0)' if eased else 'c', v)
        for typ in ('COPY_ROTATION', 'COPY_SCALE'):
            c = next((c for c in low.constraints if c.type == typ), None) or low.constraints.new(typ)
            c.target, c.subtarget = arm, ctl
            c.owner_space = c.target_space = 'LOCAL'
        for nm in (rn.left('LowerLipMid'), rn.left('LowerLipOuter')):
            pb = P.get(rn.mch(rn.with_side(nm, side)))
            fol = pb and pb.constraints.get('Follow')
            for t in (fol.targets if fol else []):
                if t.subtarget == ctl:
                    t.subtarget = low.name
        done.append(low.name)
    return done


SMILE_SPOT = (0.034, 0.026)     # the cheek control sits this far back and up from the mouth corner (x cfg size)
SMILE_PATH = Vector((0, 1, 0.6))    # the way the cheek slides, before it is laid on the skin: back and up
SMILE_BULGE = 0.12              # share of a corner's lift the cheek swells out of the skin
SMILE_SHAPE = 0.005             # control shape radius (x cfg size)
SMILE_REACH = 1.25              # skin falloff radius, as a share of the skin distance from the control to the corner
SMILE_CORE = 0.3                # share of that radius moving with the control in full
SMILE_FLOOR = 0.012             # the falloff fades in over this height above the corner (x cfg size): the mouth line stays shut


def skin_bmesh(meshes):
    """The skin (first mesh) as a bmesh with normals; empty without a skin (skin_hit then keeps its aim point)."""
    bm = bmesh.new()
    if meshes:
        bm.from_mesh(meshes[0].data)
        bm.verts.ensure_lookup_table()
        bm.normal_update()
    return bm


def deep_point(arm, cfg):
    """A point inside the head, level with the mouth."""
    return Vector((0, arm.data.bones[cfg['head']].head_local.y, arm.data.bones[rn.left('MouthCorner')].head_local.z))


def outer_skin(bm, arm, cfg):
    """Skin vertices facing away from deep_point: most of the mouth's inside is left out."""
    deep = deep_point(arm, cfg)
    return {v.index for v in bm.verts if v.normal.dot(v.co - deep) > 0}


def skin_hit(bm, deep, aim):
    """The outermost skin point (+ normal) on the way from `deep`, inside the head, through `aim`, seen from outside."""
    hit, normal, _, _ = BVHTree.FromBMesh(bm).ray_cast(deep + (aim - deep).normalized(), deep - aim)
    return (hit, normal) if hit else (aim, FWD)


def cheek_spot(bm, arm, cfg):
    """The outermost skin point (+ normal) up and back from the left mouth corner."""
    aim = arm.data.bones[rn.left('MouthCorner')].head_local + Vector((0, SMILE_SPOT[0], SMILE_SPOT[1])) * cfg['size']
    return skin_hit(bm, deep_point(arm, cfg), aim)


def nearest_vert(bm, verts, p, sx=1):
    """The one of `verts` on side sx (sign of x) nearest to p."""
    return min((bm.verts[i] for i in verts if bm.verts[i].co.x * sx >= 0), key=lambda v: (v.co - p).length_squared)


def smile_shares(arm, cfg, bm, outer, side):
    """{vertex: share} of <Side>Cheek on the skin: a soft falloff by distance along the outer skin from the control,
    reaching just past the mouth corner, on the skin above it."""
    B, s = arm.data.bones, cfg['size']
    sx = 1 if side == 'L' else -1
    ctl = rn.build('Cheek', side)
    inner = {v.index for v in bm.verts} - outer
    seed = nearest_vert(bm, outer, B[ctl].head_local, sx)
    dist, _ = cw.dijkstra(bm, [seed.index], blocked=inner, limit=0.2 * s)
    corner = nearest_vert(bm, dist, B[rn.build('MouthCorner', side)].head_local, sx)
    reach = SMILE_REACH * dist[corner.index]
    floor = B[rn.build('MouthCorner', side)].head_local.z
    return {i: (1 - cw.smoothstep(reach * SMILE_CORE, reach, d)) * cw.smoothstep(floor, floor + SMILE_FLOOR * s, bm.verts[i].co.z)
            for i, d in dist.items()}


def take_share(obj, arm, cfg, ctl, shares):
    """`ctl` takes each vertex's share ({vertex: share}) of its weights on the head and snout bones: lip, lid, jaw and
    old cheek bone weights stay, so totals stay as they were. Returns the vertices changed."""
    B, head = arm.data.bones, cfg['head']
    jaw = B[cfg['jaw']]
    keep = {jaw.name, *(c.name for c in jaw.children_recursive)}
    for side in SIDES:
        if rn.build('Cheek', side) in B:
            keep |= {c.name for c in B[rn.build('Cheek', side)].children_recursive}
    steal = free_groups(obj, arm, head) - new_deform(arm, head) - keep
    if part_of(ctl) == 'PuffSwell':
        steal |= {n for n in B.keys() if part_of(n) in PUFF_OVER}
    gi = {g.index: g.name for g in obj.vertex_groups}
    vg = obj.vertex_groups.get(ctl) or obj.vertex_groups.new(name=ctl)
    touched = set()
    for i, w in shares.items():
        part = [(g.group, g.weight) for g in obj.data.vertices[i].groups if gi.get(g.group) in steal]
        taken = w * sum(x for _, x in part)
        if taken < 0.01:
            continue
        for g, x in part:
            obj.vertex_groups[g].add([i], x * (1 - w), 'REPLACE')
        vg.add([i], taken, 'REPLACE')
        touched.add(i)
    return touched


def spread_weights(arm, cfg, meshes, parts, jobs):
    """Falloff weights on the skin (meshes[0]), then on the other bodies and the parts on the skin. jobs: [(bone, shares)]."""
    src = meshes[0]
    touched = set()
    for ctl, shares in jobs:
        touched |= take_share(src, arm, cfg, ctl, shares)
    gi = {g.index: g.name for g in src.vertex_groups}
    used = {gi[g.group] for i in touched for g in src.data.vertices[i].groups}
    for o in meshes[1:]:
        if copy_head(src, o, sorted(touched)):      # not the same head: weights from the skin's surface
            cw.transfer_from_surface(src, o, [v.index for v in o.data.vertices], used)
    report = weight_parts(src, arm, dict(cfg, skin_parts=[o.name for o in parts]), {}, used, touched, []) if parts else {}
    for o in meshes + parts:
        if has_mirror(o):
            cw.ensure_mirror_groups(o, only={bone for bone, _ in jobs})
    return len(touched), report


def skin_sides(src):
    """The sides whose weights are written: with a Mirror modifier the right side comes from the left."""
    return ['L'] if has_mirror(src) else SIDES


def smile_cheek_skin(arm, cfg, meshes, parts, bm, outer):
    """Weights of both smile cheeks."""
    return spread_weights(arm, cfg, meshes, parts, [(rn.build('Cheek', side), smile_shares(arm, cfg, bm, outer, side))
                                                    for side in skin_sides(meshes[0])])


def smile_flare(arm, cfg):
    """As a mouth corner lifts or pulls back, the lip middles and outer points ride outwards over the teeth, so a
    smile doesn't slide them in. Nothing moves until the corner does. (Not on the corner itself: its MCH parent
    can't read it.) Lip roll sliders (maw_features) and a snarl (muzzle_features), when the rig has them, add to the same channels: see
    lip_curl, lip_snarl. With smile_cheeks off only those are left (no driver when there are none).
    Works on a built rig in place."""
    flare = cfg.get('smile_flare', DEFAULTS['maw']['smile_flare'])
    smile = wants(cfg, 'smile_cheeks')
    deep, B, P = deep_point(arm, cfg), arm.data.bones, arm.pose.bones
    for side in SIDES:
        cor = rn.build('MouthCorner', side)
        for nm in ('LipMid', 'LipOuter'):
            for lip in ('Upper', 'Lower'):
                mch = rn.build(lip + nm, side, role='MCH')
                if mch not in B:
                    continue
                out = B[mch].head_local - deep
                out.z = 0
                local = B[mch].matrix_local.to_3x3().inverted() @ out.normalized()
                curl, snarl = lip_curl(arm, cfg, mch, lip), lip_snarl(arm, mch, side)
                corner = {'z': (cor, 'LOC_Z', 'TRANSFORM_SPACE'), 'y': (cor, 'LOC_Y', 'TRANSFORM_SPACE')} if smile else {}
                for k in range(3):
                    expr = (f'{flare * local[k]:.4f}*(max(z,0)+max(-y,0))' if smile else '') + curl.term(k) + snarl.term(k)
                    if expr:
                        drive(P[mch], 'location', k, expr.lstrip('+'), {**corner, **curl.variables, **snarl.variables})
                    else:
                        P[mch].driver_remove('location', k)


CHEEK_PARTS = ('Cheek', 'CheekMove', 'CheekPivot', 'CheekAnchor')    # the cheek rig's own bones
OLD_CHEEK = 'Smile' + 'Cheek'  # the cheek control's name until 2026-11-22 (standardise_face renames it)


def old_cheek_names(arm):
    """{SmileCheek bone: its new Cheek name} (rigs built before 2026-11-22)."""
    return {b.name: b.name.replace(OLD_CHEEK, 'Cheek') for b in arm.data.bones if OLD_CHEEK in b.name}


def old_cheeks(arm, head):
    """{existing cheek bone on the head: its <Side>Cheek}."""
    out = {}
    for b in arm.data.bones:
        if b.parent and b.parent.name == head and 'cheek' in b.name.lower() and not rn.parse(b.name).role \
                and rn.parse(b.name).part not in CHEEK_PARTS:
            side = rn.side_of(b.name)
            if side:
                out[b.name] = rn.build('Cheek', side)
    return out


CHEEK_TUNING = (('cheek_follow', 'Cheek Follow', 'COPY_LOCATION', 0.2, "How much the cheeks move with the mouth corners"),
                ('cheek_swing', 'Cheek Swing', 'COPY_ROTATION', 0.1, "How much the cheeks swing round with the mouth corners' turns"))


def pivot_bones(A, head):
    """(Edit Mode) MCH-CheekPivot on each mouth corner, axes and all (so a full copy is no move at rest), under the Head."""
    for side in SIDES:
        cor = A.edit_bones[rn.build('MouthCorner', side)]
        mk(A, rn.build('CheekPivot', side, role='MCH'), cor.head.copy(), cor.tail.copy(), head, roll=cor.roll)


def cheek_pivots(arm, cfg=None):
    """Upgrade a built rig in place: the smile cheeks hang from the Head through MCH-CheekPivot (cheek_follow /
    cheek_swing sliders on the Cheek controls) instead of a parentless Follow of corner and Head. Rest pose and weights unchanged; safe to run
    again. Returns the pivots made."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    head, A = cfg['head'], arm.data
    if old_cheek_names(arm):
        rr.rename(arm, old_cheek_names(arm))
    if rn.left('Cheek', 'MCH') not in A.bones:
        return []
    with in_mode(arm, 'EDIT'):
        pivot_bones(A, head)
        for side in SIDES:
            A.edit_bones[rn.build('Cheek', side, role='MCH')].parent = A.edit_bones[rn.build('CheekPivot', side, role='MCH')]
    P = arm.pose.bones
    for side in SIDES:
        mch = P[rn.build('Cheek', side, role='MCH')]
        for c in [c for c in mch.constraints if c.type == 'ARMATURE']:
            mch.constraints.remove(c)
        cheek_pivot(arm, head, side)
    made = [rn.build('CheekPivot', side, role='MCH') for side in SIDES]
    record_built(arm, made, head)
    return made


def cheek_pivot(arm, head, side):
    """MCH-CheekPivot (a Head child on the mouth corner) copies the corner's move and rotation by the
    cheek_follow / cheek_swing sliders on this side's Cheek control (Face > Cheeks in Rig Switches; made at their CHEEK_TUNING default,
    kept when run again; an older copy on the Head is taken over, then removed)."""
    P = arm.pose.bones
    pivot, cor = P[rn.build('CheekPivot', side, role='MCH')], rn.build('MouthCorner', side)
    ctl = P[rn.build('Cheek', side)]
    for c in list(pivot.constraints):
        pivot.constraints.remove(c)
    for key, name, kind, start, text in CHEEK_TUNING:
        if key not in ctl and key in P[head]:
            start = P[head][key]
        switch(ctl, key, 0, 1, text + " (a model setting: Reset leaves it)", default=start, overshoot=1)
        c = pivot.constraints.new(kind)
        c.name, c.target, c.subtarget = name, arm, cor
        c.owner_space = c.target_space = 'WORLD'
        drive(c, 'influence', -1, 'v', {'v': (ctl.name, key)})
    if side == SIDES[-1]:
        for key, *_ in CHEEK_TUNING:
            P[head].pop(key, None)
    bc.place_bone(arm, pivot.name, 'Mechanism', False)


def smile_cheeks(arm, cfg=None, log=print):
    """<Side>Cheek: a control on the cheek, up and back from the mouth corner, for a real smile: its MCH parent
    hangs from MCH-CheekPivot, a Head child at the corner that copies `cheek_follow` of the corner's move and
    `cheek_swing` of its rotation (sliders on the Cheek control, start 0.2 / 0.1, kept by Reset: they tune the
    model, they are not a pose), and slides back along the skin as the corner lifts
    (`smile_back`), so an existing corner pose carries the skin up and back into the cheek; the animator can also
    grab the control. Rest pose unchanged. cfg['meshes'] (first = the skin) place the control and get its weights; a
    bare rig gets the control up and back from the corner. Works on a built rig in place
    (safe to run again). Old cheek bones stay as they are, now children of the control, so what they weight rides
    the smile too. Returns the bones made."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    A, head, s = arm.data, cfg['head'], cfg['size']
    meshes = [bpy.data.objects[n] for n in cfg['meshes'] if n in bpy.data.objects]
    parts = [bpy.data.objects[n] for n in cfg['skin_parts'] if n in bpy.data.objects]
    if rn.left('MouthCorner') not in A.bones:
        return []
    back = cfg.get('smile_back', DEFAULTS['maw']['smile_back'])
    view = bpy.context.view_layer
    active, mode = view.objects.active, arm.mode
    with rig_space(arm, meshes + parts):
        for o in meshes + parts:
            if rn.left('Cheek') in A.bones:       # running again: start from the skin as it was
                merge_groups(o, {rn.left('Cheek'): head})
        bm = skin_bmesh(meshes)
        outer = outer_skin(bm, arm, cfg)
        p, n = cheek_spot(bm, arm, cfg)
        slide = (SMILE_PATH - n * n.dot(SMILE_PATH)).normalized() * back + n * SMILE_BULGE    # per unit of corner lift
        view.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        pivot_bones(A, head)
        both(A, rn.left('Cheek', 'MCH'), p, p + FWD * 0.004 * s, rn.left('CheekPivot', 'MCH'))
        both(A, rn.left('Cheek'), p, p + FWD * 0.006 * s, rn.left('Cheek', 'MCH'), deform=True)
        cheeks = old_cheeks(arm, head)
        for n, ctl in cheeks.items():
            A.edit_bones[n].parent = A.edit_bones[ctl]
        bpy.ops.object.mode_set(mode='POSE')
        P = arm.pose.bones
        for side in SIDES:
            ctl, mch, cor = rn.build('Cheek', side), rn.build('Cheek', side, role='MCH'), rn.build('MouthCorner', side)
            for c in list(P[mch].constraints):
                P[mch].constraints.remove(c)
            cheek_pivot(arm, head, side)
            axes = A.bones[mch].matrix_local.to_3x3().inverted()
            local = axes @ (slide if side == 'L' else mirror(slide))
            for k in range(3):
                drive(P[mch], 'location', k, f'{local[k]:.4f}*max(c,0)', {'c': (cor, 'LOC_Z', 'TRANSFORM_SPACE')})
            shape(P[ctl], 'WGT-Ico', SMILE_SHAPE * s)
            bc.place_bone(arm, ctl, 'Cheeks', True)
            bc.place_bone(arm, mch, 'Mechanism', False)
        smile_flare(arm, cfg)
        bpy.ops.object.mode_set(mode='OBJECT')
        if cfg['weights'] and meshes:
            log('M# smile cheeks: verts, parts', *smile_cheek_skin(arm, cfg, meshes, parts, bm, outer))
        bm.free()
    bpy.ops.object.mode_set(mode=mode if mode in ('POSE', 'OBJECT') else 'POSE')
    view.objects.active = active
    made = [n for side in SIDES for n in (rn.build('Cheek', side), rn.build('Cheek', side, role='MCH'),
                                           rn.build('CheekPivot', side, role='MCH'))]
    record_built(arm, made, head, {n: head for n in cheeks})
    return made


def record_built(arm, made, heir, reparented={}):
    """Bones an in-place step added, in the build record, so Remove takes them too (a rig the core didn't build has
    no record): their weights go to `heir`, `reparented` ({bone: old parent}) bones get their old parent back (the first
    one recorded, when run again)."""
    if 'face_rig_built' not in arm.data:
        return
    info = built_info(arm)
    info['made'] = sorted(set(info.get('made', [])) | set(made))
    info['heir'] = {**info.get('heir', {}), **{n: heir for n in made}}
    info['reparented'] = {**reparented, **info.get('reparented', {})}
    arm.data['face_rig_built'] = json.dumps(info)


@contextmanager
def in_mode(arm, mode):
    """The armature active in `mode` for a step in place, X-Axis Mirror off (it would overwrite the Right bones);
    afterwards the active object, mode and mirror are back."""
    view, A = bpy.context.view_layer, arm.data
    active, before, mirror_edit = view.objects.active, arm.mode, A.use_mirror_x
    view.objects.active = arm
    A.use_mirror_x = False
    bpy.ops.object.mode_set(mode=mode)
    try:
        yield
    finally:
        bpy.ops.object.mode_set(mode=before if before in ('POSE', 'OBJECT') else 'POSE')
        A.use_mirror_x = mirror_edit
        view.objects.active = active


def drop_dead_drivers(arm):
    """Drivers of pose bones that are gone."""
    if arm.animation_data:
        for fc in [fc for fc in arm.animation_data.drivers if fc.data_path.startswith('pose.bones["')
                   and fc.data_path.split('"')[1] not in arm.pose.bones]:
            arm.animation_data.drivers.remove(fc)


TONGUE_WORD = re.compile(r'to(u|n)n?gu?e', re.I)
def tongue_seg(k):
    return rn.build('TongueSeg', number=k, role='DEF')


def rig_meshes(arm):
    """Meshes this armature deforms."""
    return [o for o in bpy.data.objects if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]


def tongue_bones(arm, head):
    """The tongue bones under the head, old ones and an earlier tongue_rig's alike."""
    return [b.name for b in arm.data.bones if TONGUE_WORD.search(b.name) and is_face_bone(arm, b, head)]


def tongue_meshes(arm, cfg, old):
    """Tongue meshes: the config's, else meshes named so or mostly weighted to the old tongue bones."""
    found = [o for o in (bpy.data.objects.get(n) for n in cfg.get('tongue', [])) if o]
    if found:
        return found
    for o in rig_meshes(arm):
        groups = {g.index for g in o.vertex_groups if g.name in old}
        weighted = sum(1 for v in o.data.vertices if sum(g.weight for g in v.groups if g.group in groups) > 0.5)
        if TONGUE_WORD.search(o.name) or weighted > 0.5 * len(o.data.vertices):
            found.append(o)
    return found


def tongue_line(points, slices=12):
    """Centre line (root -> tip) of a tongue lying along Y, root at the back: the middle of each cross slice, on the
    mirror plane."""
    back, front = max(p.y for p in points), min(p.y for p in points)
    step = (front - back) / slices
    line = []
    for k in range(slices):
        zs = [p.z for p in points if back + (k + 1) * step <= p.y <= back + k * step]
        if zs:
            line.append(Vector((0, back + (k + 0.5) * step, (min(zs) + max(zs)) / 2)))
    line[0].y, line[-1].y = back, front
    return line


def tongue_thickness(points):
    """Largest top to bottom thickness along the tongue."""
    half_width = max(abs(p.x) for p in points)
    return max(p.z - min(q.z for q in points if abs(q.y - p.y) < half_width) for p in points)


TONGUE_SEGMENTS = 10            # B-bone segments on each of the two deform bones
TONGUE_SHAPES = ((TONGUE_BASE, 1.3), (TONGUE_MID, 1.0), (TONGUE_TIP, 0.7))   # x the tongue's half width / half thickness: nested from the front
JAW_LONG = 1.6                  # the jaw's triangle is this much longer than wide
JAW_LOW = 0.035                 # and sits this far under the jaw bone (at size 0.039; scales with the shape)


def square_widget():
    """WGT-Square: a unit square in the bone's XZ plane (faces forward)."""
    return ensure_widget('WGT-Square')


def jaw_shape(pb, size):
    """The jaw control as a flat triangle pointing forward (+Y), `size` wide, a little under the bone."""
    pb.custom_shape = ensure_widget('WGT-Triangle')
    pb.use_custom_shape_bone_size = False
    pb.custom_shape_scale_xyz = (size, size * JAW_LONG, size)
    pb.custom_shape_translation = (0, 0, -JAW_LOW * size / 0.039)


def tongue_shapes(arm, half_width, half_thick):
    """Rectangles on the controls as wide and thick as the tongue (x TONGUE_SHAPES), so they show how each control is
    turned. All transforms free (a re-made bone of the same name keeps the old pose bone's locks)."""
    for name, size in TONGUE_SHAPES:
        pb = arm.pose.bones[name]
        shape(pb, 'WGT-Square', 1)
        pb.custom_shape_scale_xyz = (size * half_width, 1, size * half_thick)
        pb.lock_location = pb.lock_rotation = pb.lock_scale = (False, False, False)
        pb.lock_rotation_w = False


def weight_tongue(arm, obj, nodes, tongue):
    """What the `tongue` groups don't leave to other bones (1 - other weights) goes along the two deform bones: a
    linear blend between the segment middles (the B-bones keep it smooth)."""
    M = arm_matrix(arm, obj)
    groups = [obj.vertex_groups.get(tongue_seg(k)) or obj.vertex_groups.new(name=tongue_seg(k)) for k in (1, 2)]
    names = {g.index: g.name for g in obj.vertex_groups}
    for v in obj.data.vertices:
        mine = [g.group for g in v.groups if names[g.group] in tongue]
        share = max(0.0, 1.0 - sum(g.weight for g in v.groups if names[g.group] not in tongue))
        for group in mine:
            obj.vertex_groups[group].remove([v.index])
        for k, w in cw.basis(cw.polyline_param(nodes, M @ v.co) - 0.5, 2, False, degree=1).items():
            if share * w > 0:
                groups[k].add([v.index], share * w, 'ADD')


def tongue_rig(arm, cfg=None, log=print):
    """The tongue from the tongue mesh(es): three controls, TongueBase (on the lower jaw, moves the whole tongue),
    TongueTip (child of Base) and TongueMid (halfway: MCH-TongueMid follows Base and Tip 50 / 50, Mid sits on it, free
    on top), and two deform B-bones, DEF-TongueSeg1 (Base -> Mid) and DEF-TongueSeg2 (Mid -> Tip), Stretch To the next
    control with Tangent handles (no kink at Mid). Scale X / Z on a control: wider / thicker there; Y: the ease.
    Rest pose unchanged. Works on a built rig in place (safe to run again) and from Build. A rig with no tongue mesh
    keeps what it has. Returns the bones made."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    A, head = arm.data, cfg['head']
    lower = cfg['lower_parent'] or cfg['jaw']
    if lower not in A.bones:
        return []
    old = tongue_bones(arm, head)
    meshes = tongue_meshes(arm, cfg, old)
    if not meshes:
        log('M# tongue: no tongue mesh, left as it was')
        return []
    points = [arm_matrix(arm, o) @ v.co for o in meshes for v in o.data.vertices]
    nodes = resample(tongue_line(points), [0, 0.5, 1])
    deform = {n for n in old if A.bones[n].use_deform}
    segs = [tongue_seg(1), tongue_seg(2)]
    for o in rig_meshes(arm):                   # other meshes on the old tongue bones go to the lower jaw
        if o not in meshes and used_groups(o) & deform:
            merge_groups(o, {n: lower for n in deform})
        for n in old:
            if o not in meshes and n in o.vertex_groups:
                o.vertex_groups.remove(o.vertex_groups[n])
    with in_mode(arm, 'EDIT'):
        E = A.edit_bones
        for n in old:
            E.remove(E[n])
        along, up = FWD * 0.01 * cfg['size'], Vector((0, 0, 1))
        for name, point, parent in ((TONGUE_BASE, nodes[0], lower), (TONGUE_TIP, nodes[2], TONGUE_BASE),
                                    (TONGUE_MID_FOLLOW, nodes[1], TONGUE_BASE), (TONGUE_MID, nodes[1], TONGUE_MID_FOLLOW)):
            mk(A, name, point, point + along, parent).align_roll(up)
        for k, (name, parent, end) in enumerate(((segs[0], TONGUE_BASE, TONGUE_MID), (segs[1], TONGUE_MID, TONGUE_TIP))):
            eb = mk(A, name, nodes[k], nodes[k + 1], parent, deform=True)
            eb.align_roll(up)
            eb.bbone_segments = TONGUE_SEGMENTS
            eb.bbone_handle_type_start = eb.bbone_handle_type_end = 'TANGENT'
            eb.bbone_custom_handle_start, eb.bbone_custom_handle_end = E[parent], E[end]
            eb.bbone_handle_use_scale_start = eb.bbone_handle_use_scale_end = (True, False, True)
            eb.bbone_handle_use_ease_start = eb.bbone_handle_use_ease_end = True
            bc.thin_bbones([eb])
    drop_dead_drivers(arm)
    with in_mode(arm, 'POSE'):
        P = arm.pose.bones
        for constraint in list(P[TONGUE_MID_FOLLOW].constraints):
            P[TONGUE_MID_FOLLOW].constraints.remove(constraint)
        follow = P[TONGUE_MID_FOLLOW].constraints.new('COPY_TRANSFORMS')    # half way from Base (its parent) to Tip
        follow.target, follow.subtarget, follow.influence = arm, TONGUE_TIP, 0.5
        follow.owner_space = follow.target_space = 'LOCAL'                  # half of Tip's own move (both sit on Base)
        for name, end in ((segs[0], TONGUE_MID), (segs[1], TONGUE_TIP)):
            for old_stretch in [c for c in P[name].constraints if c.type == 'STRETCH_TO']:
                P[name].constraints.remove(old_stretch)       # kept from an older tongue (aimed at bones now gone) or an earlier run
            stretch(P[name], end).rest_length = A.bones[name].length
        tongue_shapes(arm, max(abs(p.x) for p in points), tongue_thickness(points) / 2)
        for name, _ in TONGUE_SHAPES:
            bc.place_bone(arm, name, 'Mouth', False)
            P[name].color.palette = 'DEFAULT'
        bc.place_bone(arm, TONGUE_MID_FOLLOW, 'Mechanism', False)
        for name in segs:
            bc.place_bone(arm, name, None, True)
        bc.apply_face_split_colors(arm, cfg['colors'], only={TONGUE_BASE, TONGUE_MID, TONGUE_TIP})
    for o in meshes:
        weight_tongue(arm, o, nodes, set(old) | {lower, cfg['jaw']})
    made = [b.name for b in A.bones if TONGUE_WORD.search(b.name) and is_face_bone(arm, b, head)]
    for o in meshes:
        for n in set(old) - set(made):
            vg = o.vertex_groups.get(n)
            if vg:
                o.vertex_groups.remove(vg)
    record_built(arm, made, lower)
    cfg['tongue'] = [o.name for o in meshes]
    if 'face_rig_maw' in A:
        A['face_rig_maw'] = to_json(cfg)
    return made


ZIP_JAW = rn.build('MouthJawZip', role='DEF')
ZIP_OVERLAP = 1.0               # a zipped pair keeps its rest overbite and laps over by this share of it again: pulling the nodes together pushes the lower lip's skin through the upper
ZIP_SEAL_JAW = 0.5              # the seal line follows the jaw this share of the way: less keeps the upper lip (and the snout) from being dragged down
ZIP_STEP = 0.4                  # the zipper closes each lip point over this much of its slider
ZIP_JAW_REACH = 0.5             # chin skin this close to the lower lip (x mouth_size) follows the jaw less as the lips zip
ROLL_MAX = math.radians(55)     # lip roll at 1 ...
ROLL_ALONG = (1, 1, 0.85, 0.5, 0)   # ... at the lip nodes, centre -> corner
LIP_CURL = 0.007                # the lip line moves this far out at roll 1 (x cfg size)
CHEEK_BULGE = 0.25              # the cheeks bunch up (down would shear their falloff at the corner) and swell out by this much of that
JAW_WIDE = (math.radians(12), math.radians(40))   # maw_stretch comes in over this jaw opening


def jaw_opening(arm, jaw):
    """(transform type, sign) of the jaw's rotation channel that opens it: its axis along the armature's X."""
    axis = arm.data.bones[jaw].matrix_local.to_3x3().inverted() @ Vector((1, 0, 0))
    k = max(range(3), key=lambda i: abs(axis[i]))
    return 'ROT_' + 'XYZ'[k], 1 if axis[k] > 0 else -1


def insert_parent(A, child, name):
    """A new bone `name` between `child` and its parent, at the child's rest. Safe to run again."""
    c = A.edit_bones[child]
    if not (c.parent and c.parent.name == name):
        b = mk(A, name, c.head, c.tail, c.parent.name if c.parent else None, roll=c.roll)
        c.use_connect = False
        c.parent = b


def stay_on_head(arm, side):
    """The Limit Distance of cheek_anchor (finish_rig scales it with the root)."""
    B, move = arm.data.bones, rn.build('CheekMove', side, role='MCH')
    anchor = rn.build('CheekAnchor', side, role='MCH')
    pb = arm.pose.bones[move]
    c = pb.constraints.get('Stay On Head') or pb.constraints.new('LIMIT_DISTANCE')
    c.name, c.target, c.subtarget, c.limit_mode = 'Stay On Head', arm, anchor, 'LIMITDIST_INSIDE'
    c.owner_space = c.target_space = 'WORLD'
    c.distance = (B[move].head_local - B[anchor].head_local).length


def zip_bone(node):
    """'MCH-UpperLipMid.L' -> 'MCH-UpperLipMidZip.L'."""
    b = rn.parse(node)
    return rn.build(b.part + 'Zip', b.side, role=b.role)


def cheek_anchor(A, cfg, side):
    """MCH-CheekAnchor: a point on the mirror plane inside the head. The cheek mechanism may not leave a sphere round it
    (Stay On Head), so grins can't push the cheek patch off the skull."""
    E = A.edit_bones
    cheek = E[rn.build('Cheek', side)]
    s = cfg['size']
    at = Vector((0, cheek.head.y, cheek.head.z - 0.02 * s))
    return mk(A, rn.build('CheekAnchor', side, role='MCH'), at, at + Vector((0, 0, 0.02 * s)), cfg['head']).name


def build_maw_feature_bones(arm, cfg):
    """Returns the bones made: with mouth_sliders a movable layer under the corners and smile cheeks; with zipper a zip
    target for each lip node (a parentless copy of it, following the mouth line only), the seals and the jaw's zip bones;
    with either a movable layer under the lip centres."""
    A, made = arm.data, []
    E = A.edit_bones
    sliders, zipper = wants(cfg, 'mouth_sliders'), wants(cfg, 'zipper')
    for side in SIDES:
        if sliders:
            move = rn.build('MouthCornerMove', side, role='MCH')
            insert_parent(A, rn.build('MouthCorner', side), move)
            E[rn.build('MouthCornerLow', side, role='MCH')].parent = E[move]
            made.append(move)
            if rn.build('Cheek', side) in E:
                insert_parent(A, rn.build('Cheek', side), rn.build('CheekMove', side, role='MCH'))
                made += [rn.build('CheekMove', side, role='MCH'), cheek_anchor(A, cfg, side)]
        for nodes in (UP_NODES, LO_NODES) if zipper else ():
            for k in (1, 2, 3):
                node = E[rn.mch(rn.with_side(nodes[k], side))]
                made.append(zip_bone(node.name))
                mk(A, made[-1], node.head, node.tail, roll=node.roll)
                lap_zip_bone(E, made[-1], *(rn.mch(rn.with_side(lip[k], side)) for lip in (UP_NODES, LO_NODES)))
    for lip in ('UpperLip', 'LowerLip') if sliders or zipper else ():
        insert_parent(A, lip, rn.mch(f'{lip}Base'))
        made.append(rn.mch(f'{lip}Base'))
        if zipper:
            mk(A, rn.mch(f'{lip}Seal'), E[lip].head, E[lip].tail, roll=E[lip].roll)
            lap_zip_bone(E, rn.mch(f'{lip}Seal'), 'UpperLip', 'LowerLip')
            made.append(rn.mch(f'{lip}Seal'))
    if not zipper:
        return made
    jaw = E[cfg['jaw']]
    mk(A, ZIP_JAW, jaw.head, jaw.tail, cfg['head'], deform=True, roll=jaw.roll)
    mk(A, rn.mch('MouthHalf'), jaw.head, jaw.tail, cfg['upper_parent'] or cfg['head'], roll=jaw.roll)
    mk(A, rn.mch('MouthLow'), jaw.head, jaw.tail, cfg['lower_parent'] or cfg['jaw'], roll=jaw.roll)
    return made + [rn.mch('MouthHalf'), rn.mch('MouthLow'), ZIP_JAW]


def lap_zip_bone(E, name, upper, lower):
    """Moves a zip target (edit bone) away from the mid point of its upper and lower nodes (ZIP_OVERLAP), so the lips of
    a pair close over each other the way they do at rest, whatever the jaw does (the target follows the jaw half way
    round its hinge). In the rest, not the pose: the rig rests exactly at zero pose."""
    eb = E[name]
    shift = (eb.head - E[upper].head.lerp(E[lower].head, 0.5)) * ZIP_OVERLAP
    eb.head, eb.tail = eb.head + shift, eb.tail + shift


def clear_zip_offset(target):
    """Older builds lapped a zip target by its pose location (and before that a driver): back to zero."""
    target.driver_remove('location')
    target.location = (0.0, 0.0, 0.0)


def zip_lips(arm, cfg):
    """Each corner's `zip` seals the lips from that corner inwards: a lip node moves to its zip target, which follows
    the corner and MCH-MouthHalf, the jaw turned half way open round its hinge. Each pair's targets keep the lips
    lapped over each other (lap_zip_bone), so they seal as one clean line. Half way round the hinge, not the mid point of the two
    lips: that is nearer the hinge, inside the teeth."""
    P = arm.pose.bones
    half = P[rn.mch('MouthHalf')]
    c = half.constraints.get('Half') or half.constraints.new('COPY_TRANSFORMS')
    c.name, c.target, c.subtarget, c.influence = 'Half', arm, rn.mch('MouthLow'), ZIP_SEAL_JAW
    for lip in ('UpperLip', 'LowerLip'):
        seal = P[rn.mch(f'{lip}Seal')]
        for c in list(seal.constraints):
            seal.constraints.remove(c)
        follow(seal, {half.name: 1})
        clear_zip_offset(seal)
    start = lambda at: at * (1 - ZIP_STEP)
    close = lambda z, at: f'max(0,min(1,({z}-{start(at):.3f})/{ZIP_STEP}))'
    for side in SIDES:
        corner = rn.build('MouthCorner', side)
        switch(P[corner], 'zip', 0, 1, 'Seal the lips from this corner inwards')
        for nodes in (UP_NODES, LO_NODES):
            for k, at in ((3, 0.0), (2, 1 / 3), (1, 2 / 3)):       # outer node first
                mch = P[rn.mch(rn.with_side(nodes[k], side))]
                target = P[zip_bone(mch.name)]
                for c in list(target.constraints):
                    target.constraints.remove(c)
                to_corner = k / 4
                follow(target, {half.name: 1 - to_corner, corner: to_corner})
                clear_zip_offset(target)
                c = mch.constraints.get('Zip') or mch.constraints.new('COPY_TRANSFORMS')
                c.name, c.target, c.subtarget = 'Zip', arm, target.name
                drive(c, 'influence', -1, close('z', at), {'z': (corner, 'zip')})
    zip_jaw_bone(arm, cfg, close)
    for lip in ('UpperLip', 'LowerLip'):
        base = P[rn.mch(f'{lip}Base')]
        c = base.constraints.get('Zip') or base.constraints.new('COPY_TRANSFORMS')
        c.name, c.target, c.subtarget = 'Zip', arm, rn.mch(f'{lip}Seal')
        drive(c, 'influence', -1, close('(l+r)/2', 1.0),
              {'l': (rn.left('MouthCorner'), 'zip'), 'r': (rn.build('MouthCorner', 'R'), 'zip')})


def zip_jaw_bone(arm, cfg, close):
    """ZIP_JAW follows the jaw, and as the lips zip the seal's half open jaw instead: skin by the lower lip weighted to it
    stays up with the seal rather than sinking with the chin and leaving the lips apart."""
    P = arm.pose.bones
    pb = P[ZIP_JAW]
    for c in list(pb.constraints):
        pb.constraints.remove(c)
    for name, target in (('Jaw', cfg['jaw']), ('Zip', rn.mch('MouthHalf'))):
        c = pb.constraints.new('COPY_TRANSFORMS')
        c.name, c.target, c.subtarget = name, arm, target
    drive(pb.constraints['Zip'], 'influence', -1, close('(l+r)/2', 1.0),
          {'l': (rn.left('MouthCorner'), 'zip'), 'r': (rn.build('MouthCorner', 'R'), 'zip')})


def segment_distance(p, a, b):
    """Distance from p to the segment a-b."""
    _, t = intersect_point_line(p, a, b)
    return (p - (a + (b - a) * max(0.0, min(1.0, t)))).length


def zip_jaw_weights(arm, cfg):
    """Moves the jaw weight of skin near the lower lip onto ZIP_JAW, fading out down the chin. Nothing moves at zip 0."""
    B, jaw, reach = arm.data.bones, cfg['jaw'], ZIP_JAW_REACH * mouth_size(arm)
    line = [B[n].head_local for n in LO_NODES]
    line = [*line[::-1], *(mirror(p) for p in line)]
    for o in (rig_obj for rig_obj in rig_meshes(arm) if rig_obj.name in cfg['meshes']):
        src = o.vertex_groups.get(jaw)
        if not src or o.vertex_groups.get(ZIP_JAW):
            continue
        dest = o.vertex_groups.new(name=ZIP_JAW)
        for v, co in zip(o.data.vertices, rig_coords(arm, o)):
            w = next((g.weight for g in v.groups if g.group == src.index), 0)
            near = min(segment_distance(co, p, q) for p, q in zip(line, line[1:])) if w > 0 else reach
            share = 1 - cw.smoothstep(0, reach, near)
            if w > 0 and share > 0.01:
                src.add([v.index], w * (1 - share), 'REPLACE')
                dest.add([v.index], w * share, 'REPLACE')


class LipCurl:
    """The part of lip roll on one lip node's location channels (empty on a rig without the sliders)."""
    def __init__(self, local=None, jaw='', prop=''):
        self.local, self.variables = local, {'r': (jaw, prop)} if local else {}

    def term(self, k):
        return f'+{self.local[k]:.5f}*r' if self.local else ''


def lip_curl(arm, cfg, mch, lip):
    """A lip node's move for lip roll 1 (LIP_CURL along the lip): out and away from the mouth line."""
    jaw, prop = cfg['jaw'], 'lip_roll_' + lip.lower()
    if prop not in arm.pose.bones[jaw] or not wants(cfg, 'mouth_sliders'):
        return LipCurl()
    b = arm.data.bones[mch]
    along = next((a for n, a in zip(('Base', 'Inner', 'Mid', 'Outer'), ROLL_ALONG) if n in mch), 1)
    way = FWD * 0.6 + Vector((0, 0, 0.8 if lip == 'Upper' else -0.8))
    return LipCurl(b.matrix_local.to_3x3().inverted() @ way * LIP_CURL * cfg['size'] * along, jaw, prop)


def lip_roll(arm, cfg, jaw):
    """lip_roll_upper / lower on the jaw: the lip B-bones twist round the lip line and the lip's nodes move out with
    it (lip_curl), in full at the centre and none at the corner. 1 curls the lip out, -1 tucks it in."""
    P = arm.pose.bones
    switch(P[jaw], 'lip_roll_upper', -1, 1, 'Curl the upper lip out (1) or tuck it in (-1)')
    switch(P[jaw], 'lip_roll_lower', -1, 1, 'Curl the lower lip out (1) or tuck it in (-1)')
    smile_flare(arm, cfg)
    for lip in ('Upper', 'Lower'):
        for mch in [rn.mch(f'{lip}LipBase')] + [rn.build(f'{lip}LipInner', side, role='MCH') for side in SIDES]:
            curl = lip_curl(arm, cfg, mch, lip)
            for k in range(3):
                drive(P[mch], 'location', k, curl.term(k).lstrip('+'), curl.variables)
    for segs, prop, way in ((UP_SEGS, 'lip_roll_upper', 1), (LO_SEGS, 'lip_roll_lower', -1)):
        for side, mirrored in zip(SIDES, (1, -1)):
            for k, seg in enumerate(segs):
                pb = P[rn.with_side(seg, side)]
                for path, at in (('bbone_rollin', k), ('bbone_rollout', k + 1)):
                    drive(pb, path, -1, f'{way * mirrored * ROLL_MAX * ROLL_ALONG[at]:.4f}*v', {'v': (jaw, prop)})


def corner_moves(arm, cfg, jaw):
    """On the corners' and cheeks' move layer: `corner_slide` (a corner's slider) along the lip line, 1 = in (pucker),
    -1 = out (spread); `maw_stretch` (on the jaw) draws the corners in the same way and bunches the cheeks as the jaw
    opens past JAW_WIDE[0], in full at JAW_WIDE[1]. `corner_pin` drives the corner's jaw follow from corner_jaw_follow
    up to all the way; `zip` takes it to half way, on the seam."""
    P, B = arm.pose.bones, arm.data.bones
    reach = cfg.get('corner_reach', DEFAULTS['maw']['corner_reach'])
    squash = cfg.get('maw_squash', DEFAULTS['maw']['maw_squash'])
    cheek = cfg.get('maw_cheek', DEFAULTS['maw']['maw_cheek'])
    channel, sign = jaw_opening(arm, jaw)
    wide = f'q*max(0,min(1,({sign}*j-{JAW_WIDE[0]:.4f})/{JAW_WIDE[1] - JAW_WIDE[0]:.4f}))'
    wide_vars = {'q': (jaw, 'maw_stretch'), 'j': (jaw, channel, 'LOCAL_SPACE')}
    switch(P[jaw], 'maw_stretch', 0, 1, 'Draw the mouth in and bunch the cheeks when the jaw opens wide')
    deep = deep_point(arm, cfg)
    for side in SIDES:
        corner, move = rn.build('MouthCorner', side), rn.build('MouthCornerMove', side, role='MCH')
        switch(P[corner], 'corner_slide', -1, 1, 'Slide this corner along the snout: in (1, pucker) or out (-1, spread)')
        switch(P[corner], 'corner_pin', 0, 1, 'Pin this corner to the lower jaw', overshoot=1)
        here = B[corner].head_local
        mid = (B[rn.build('UpperLipMid', side, role='MCH')].head_local + B[rn.build('LowerLipMid', side, role='MCH')].head_local) / 2
        lip = 2 * (mid - here).length
        inward = (mid - here).normalized()
        local = B[move].matrix_local.to_3x3().inverted() @ inward * lip
        for k in range(3):
            drive(P[move], 'location', k, f'{local[k]:.5f}*({reach}*v+{squash}*{wide})',
                  {'v': (corner, 'corner_slide'), **wide_vars})
        cheek_move = rn.build('CheekMove', side, role='MCH')
        if cheek_move in B:
            at = B[cheek_move].head_local
            bunch = (Vector((0, 0, 1)) + (at - deep).normalized() * CHEEK_BULGE).normalized() * cheek * cfg['size']
            local = B[cheek_move].matrix_local.to_3x3().inverted() @ bunch
            for k in range(3):
                drive(P[cheek_move], 'location', k, f'{local[k]:.5f}*{wide}', wide_vars)
            stay_on_head(arm, side)


def corner_follow(arm, cfg):
    """The corners' jaw follow: corner_jaw_follow, up to all the way with `corner_pin` (mouth_sliders), half way (on the
    seam) with `zip` (zipper)."""
    P, base = arm.pose.bones, cfg['corner_jaw_follow']
    pin, zipper = wants(cfg, 'mouth_sliders'), wants(cfg, 'zipper')
    for side in SIDES:
        corner = rn.build('MouthCorner', side)
        follows = next(c for c in P[rn.build('MouthCorner', side, role='MCH')].constraints if c.type == 'COPY_TRANSFORMS')
        expr, variables = f'{base:.4f}', {}
        if pin:
            expr += f'+{1 - base:.4f}*p'
            variables['p'] = (corner, 'corner_pin')
        if zipper:
            expr += f'+{0.5 - base:.4f}*z' + ('*(1-p)' if pin else '')
            variables['z'] = (corner, 'zip')
        if variables:
            drive(follows, 'influence', -1, expr, variables)
        else:
            follows.driver_remove('influence')
            follows.influence = base


def maw_features(arm, cfg=None, log=print):
    """Zipper (cfg zipper) and the mouth sliders (cfg mouth_sliders: mouth squash on a wide jaw, lip roll, corner slide
    and corner pin), all off by default: sliders on the jaw (maw_stretch, lip_roll_upper / lower) and on each mouth
    corner (zip, corner_slide, corner_pin), shown in Rig Switches. Nothing moves until a slider does. Works on a built
    rig in place (safe to run again) and from Build. Returns the bones made."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    A, jaw = arm.data, cfg['jaw']
    if rn.left('MouthCorner') not in A.bones or jaw not in A.bones:
        return []
    corner_low(arm, cfg)
    with in_mode(arm, 'EDIT'):
        made = build_maw_feature_bones(arm, cfg)
    with in_mode(arm, 'POSE'):
        if wants(cfg, 'zipper'):
            zip_lips(arm, cfg)
        if wants(cfg, 'mouth_sliders'):
            lip_roll(arm, cfg, jaw)
            corner_moves(arm, cfg, jaw)
        corner_follow(arm, cfg)
        for n in made:
            bc.place_bone(arm, n, None if n == ZIP_JAW else 'Mechanism', n == ZIP_JAW)
    if wants(cfg, 'zipper'):
        zip_jaw_weights(arm, cfg)
    record_built(arm, made, cfg['head'])
    return made


# ---------------------------------------------------------------- upper muzzle: snout bend, snarl, nose, puff
# Lengths marked (x m) are shares of the mouth's half length along the lip (mouth_size): a flat face gets a small version.
SNOUT_NAME = re.compile(r'^(muzzle(_upper)?\d*|snout\d*|jaw_?upper|upper_?jaw|def-snoutseg\d+)$', re.I)   # the tool's own names too
NOSE_NAME = re.compile(r'^nose$', re.I)
SNOUT_SEGS = 3                  # the snout bends over this many bones: the rig's own, the last one split if there are fewer
SNOUT_SHARE = (0.25, 0.35, 0.4)     # share of the Snout control's move and turn at each bend, root -> tip
SNOUT_BLEND = 0.35              # weights of a split bone blend over this share of a piece either side of a joint
SNOUT_RING = 0.03               # Snout ring radius (x cfg size)
SNOUT = 'Snout'                 # the Snout control
SNARL_ALONG = 0.5               # the snarl sits this far from the lip middle to the outer lip point, over the canine
SNARL_UP = 0.18                 # ... and this far above the lip, round the snout (x m)
SNARL_REACH = 0.9               # skin falloff radius, as a share of the distance from the control to the nose's side
SNARL_LIP = {'LipMid': 0.7, 'LipOuter': 0.65}   # share of the lift on these lip nodes (the outer node also follows the middle)
SNARL_FADE = (0.1, 0.7)           # the snarl's skin lift fades out between these shares of the way from the control to the nose: the front of the snout stays put
SNARL_BULGE = 0.1               # at full lift the lifted skin is also pushed out this far (x m): the skin between the lift and the still skin would sink in
SNARL_MAX = 0.45                # the highest lift (x m)
SNARL_FULL = 0.25               # a lift of this much (x m) gives the whole of `snarl_scrunch`
SNARL_NOSTRIL = 0.15            # share of a lift that pulls the same side's nostril up
SOFT_CORE = 0.3                 # share of a falloff radius moving in full
SOFT_FLOOR = 0.04               # a side falloff fades in over this height above the lip line (x m): the mouth line stays shut
SOFT_CENTRE = 0.05              # ... and over this distance from the mirror plane (x m): one side moves alone
SCRUNCH_PULL = 0.05             # scrunch 1 pulls the nose this far back towards the eyes and up (x m)
SCRUNCH_BULGE = 0.035           # ... and bunches the bridge up this far (x m)
BRIDGE_BACK = 0.3               # the bridge control sits this far back from the nose (x m)
BRIDGE_REACH = 0.3              # its skin falloff radius (x m)
NOSE_REACH = 0.16               # skin falloff radius of a new Nose bone (x m)
NOSE_PART = 0.25                # a separate nose mesh lies within this of the nose (x m)
NOSTRIL_SIDE = 0.075            # a nostril sits this far from the mirror plane (x m)
NOSTRIL_REACH = 0.09            # its falloff radius (x m)
FLARE = 0.03                    # flare 1 moves the nostril this far out and a bit up (x m)
PUFF_ALONG = 0.6                # the puff sits this far from the outer lip point to the mouth corner
PUFF_UP = 0.2                   # ... and this far above the lip, round the snout (x m): low, towards the mouth corner
PUFF_REACH = 0.42               # the puff's skin bell radius (x m): the hard edge, nothing moves past it
PUFF_UPPER = 1.6                # distance above the spot counts this many times over: the bell ends sooner towards the eye
PUFF_SMOOTH = 8                 # passes of smoothing over the puff's bell
PUFF_FORE = 0.5                 # the swell's centre sits on the snout's axis at lip height, this far before the spot (x m): skin behind it goes out and back
PUFF_WIDE = 0.44                # puff 1 scales the skin out from that centre by this much across the snout (-1 sucks it in): each point goes its own way
PUFF_LONG = 0.2                 # ... and by this much along it
PUFF_GRAB = 0.25                # dragging the puff control out this far (x m) is a full puff
PUFF_TUCK = 0.24                # the swell fades in over this height above the lip line (x m): the lip stays put, the cheek curves back down to it
PUFF_OVER = ('Cheek', 'SnarlLift')         # the swell's weights go over these: skin they hold would stay behind as a dent
UP = Vector((0, 0, 1))


def mouth_size(arm):
    B = arm.data.bones
    return (B['UpperLip'].head_local - B[rn.left('MouthCorner')].head_local).length


def snout_bones(arm, cfg):
    """The rig's own snout bones, root -> tip: the upper lip's parent up to the head, or the snout-named bone furthest
    down under the head when the lips hang on the head."""
    B, head = arm.data.bones, cfg['head']
    ours = set(built_info(arm).get('made', []))     # an earlier run's bones are not the rig's own
    if rn.mch('SnoutBend1') in B:                   # a bent snout: its Snout is the control, not a snout bone
        ours.add(SNOUT)
    top = cfg['upper_parent'] if cfg['upper_parent'] not in ('', head) else \
        max((b for b in B[head].children_recursive if SNOUT_NAME.match(b.name) and b.name not in ours),
            key=lambda b: len(b.parent_recursive), default=B[head]).name
    chain, b = [], B.get(top)
    while b and b.name != head:
        if (SNOUT_NAME.match(b.name) and b.name not in ours) or b.name == top:
            chain.insert(0, b.name)
        b = b.parent
    return chain


def nose_bone(arm, head):
    return next((b.name for b in arm.data.bones[head].children_recursive if NOSE_NAME.match(b.name)), '')


def split_shares(t, pieces):
    """A point at t (0..1) along a bone cut into `pieces`: [share of each piece], blended at the joints."""
    steps = [cw.smoothstep(k - SNOUT_BLEND, k + SNOUT_BLEND, t * pieces) for k in range(1, pieces)]
    edges = [1.0, *steps, 0.0]
    return [a - b for a, b in zip(edges, edges[1:])]


class SnoutLine:
    """The last snout bone's line (`source`): it is cut into pieces (that bone + SnoutSeg1...), and is the axis the snarl
    turns round. A source named like the Snout control (the Full Character Rig's body Snout bone) becomes that control,
    so it is no piece and no bend: its bend would read the control above it (a dependency cycle). New SnoutSeg bones
    take its place, as on Digit (Snout on the Head beside the bends)."""
    def __init__(self, arm, chain):
        self.source = chain[-1]
        last = arm.data.bones[self.source]
        self.start, self.end = last.head_local.copy(), last.tail_local.copy()
        self.way = (self.end - self.start).normalized()
        own = [n for n in chain if n != SNOUT]
        free = (n for n in (rn.build('SnoutSeg', number=k, role='DEF') for k in range(1, 99)) if n not in arm.data.bones)
        self.new = [next(free) for _ in range(max(SNOUT_SEGS - len(own), 0))]     # a kept SnoutSeg1 / 2 is no new bone: Seg3 follows
        self.pieces = [n for n in (self.source,) if n != SNOUT] + self.new
        self.bones = [*own, *self.new]

    def at(self, p):
        """How far along the bone p lies, 0..1."""
        return max(0.0, min(1.0, (p - self.start).dot(self.way) / (self.end - self.start).length))

    def piece(self, p):
        """The piece p rides on."""
        return self.pieces[min(int(self.at(p) * len(self.pieces)), len(self.pieces) - 1)]

    def axis_point(self, p):
        return self.start + self.way * (p - self.start).dot(self.way)

    def snarl_axis(self, lip):
        """A point of the line the snarl turns round: the snout's axis brought down to the lip's height, so the lip starts
        straight up the muzzle's side (from the axis itself, below it, it only slid out sideways)."""
        c = self.axis_point(lip)
        c.z = lip.z
        return c

    def turned(self, p, along):
        """p moved `along` round the snarl's axis, up on the left side."""
        c = self.snarl_axis(p)
        return c + Matrix.Rotation(along / (p - c).length, 3, self.way) @ (p - c)


def split_snout_weights(arm, line):
    """Every mesh's weights on the last snout bone are shared out over its pieces by position (all of them when the
    bone becomes the Snout control, which deforms nothing)."""
    if not line.new:
        return
    for o in rig_meshes(arm):
        src = o.vertex_groups.get(line.source)
        if not src:
            continue
        M = arm_matrix(arm, o)
        groups = [o.vertex_groups.get(n) or o.vertex_groups.new(name=n) for n in line.pieces]
        for v in o.data.vertices:
            x = next((g.weight for g in v.groups if g.group == src.index), 0)
            if x > 0:
                for g, share in zip(groups, split_shares(line.at(M @ v.co), len(line.pieces))):
                    g.add([v.index], x * share, 'REPLACE')
        if line.source not in line.pieces:
            o.vertex_groups.remove(src)


def lip_height(arm, lip_line, co):
    """The height of the left upper lip line nearest to co (x taken as on the left)."""
    p = Vector((abs(co.x), co.y, co.z))
    return min(lip_line, key=lambda q: (q - p).length_squared).z


def lip_fade(arm, lip_line, co, rise):
    """0 at the upper lip line, up to 1 this `rise` above it."""
    floor = lip_height(arm, lip_line, co)
    return cw.smoothstep(floor, floor + rise, co.z)


def side_shares(arm, bm, outer, lip_line, p, reach, side, core=SOFT_CORE):
    """{vertex: share}: a soft falloff by distance along the outer skin from p, on one side and above the lip line."""
    m, sx = mouth_size(arm), 1 if side == 'L' else -1
    inner = {v.index for v in bm.verts} - outer
    dist, _ = cw.dijkstra(bm, [nearest_vert(bm, outer, p, sx).index], blocked=inner, limit=reach)
    out = {}
    for i, d in dist.items():
        co = bm.verts[i].co
        out[i] = (1 - cw.smoothstep(reach * core, reach, d)) * cw.smoothstep(0, SOFT_CENTRE * m, abs(co.x)) \
            * lip_fade(arm, lip_line, co, SOFT_FLOOR * m)
    return out


def bell_shares(bm, outer, p, reach, side):
    """{vertex: share}: a round cosine bell of the outer skin round p, on one side only."""
    sx = 1 if side == 'L' else -1
    out = {}
    for i in outer:
        co = bm.verts[i].co
        off = co - p
        d = Vector((off.x, off.y, off.z * (PUFF_UPPER if off.z > 0 else 1))).length
        if d < reach and co.x * sx > 0:
            out[i] = (1 + math.cos(math.pi * d / reach)) / 2
    return out


def fade_towards(bm, shares, start, goal, fade):
    """{vertex: share} faded out between the `fade` shares of the way from `start` to `goal`, measured along that line."""
    way = goal - start
    return {i: s * (1 - cw.smoothstep(fade[0], fade[1], (bm.verts[i].co - start).dot(way) / way.length_squared))
            for i, s in shares.items()}


def smooth_shares(bm, shares, passes):
    """{vertex: share} blurred over the mesh edges `passes` times: no lumps in a falloff."""
    for _ in range(passes):
        grown = {n.index for i in shares for n in (e.other_vert(bm.verts[i]) for e in bm.verts[i].link_edges)} | set(shares)
        shares = {i: sum(shares.get(n, 0) for n in [i, *(e.other_vert(bm.verts[i]).index for e in bm.verts[i].link_edges)])
                  / (1 + len(bm.verts[i].link_edges)) for i in grown}
    return shares


def ball_shares(coords, p, reach):
    """{vertex: share}: a soft ball round p."""
    return {i: 1 - cw.smoothstep(reach * SOFT_CORE, reach, (co - p).length) for i, co in enumerate(coords)
            if (co - p).length < reach}


def rig_coords(arm, o):
    M = arm_matrix(arm, o)
    return [M @ v.co for v in o.data.vertices]


def nose_tip(arm, cfg, bm, outer, line, nose):
    """The nose: its bone, else the skin's foremost point on the mirror plane above the upper lip."""
    if nose:
        return arm.data.bones[nose].head_local.copy()
    lip_z = arm.data.bones['UpperLip'].head_local.z
    points = [bm.verts[i].co for i in outer if abs(bm.verts[i].co.x) < 1e-4 and bm.verts[i].co.z > lip_z]
    return max(points, key=lambda p: (p - line.start).dot(line.way)).copy() if points else line.end.copy()


def muzzle_spots(arm, cfg, bm, line, tip):
    """Where the controls sit, left side: {spot: skin point}, and the puff's normal."""
    B, m = arm.data.bones, mouth_size(arm)
    mid, outer, corner = (B[n].head_local for n in (rn.left('UpperLipMid'), rn.left('UpperLipOuter'), rn.left('MouthCorner')))
    def on_skin(p):
        return skin_hit(bm, line.axis_point(p), p)
    canine = mid.lerp(outer, SNARL_ALONG)
    snarl, _ = on_skin(line.turned(canine, SNARL_UP * m))
    puff, _ = on_skin(line.turned(outer.lerp(corner, PUFF_ALONG), PUFF_UP * m))
    back = tip - line.way * BRIDGE_BACK * m
    bridge, up = skin_hit(bm, line.axis_point(back), line.axis_point(back) + UP * 0.01)
    nostril, _ = skin_hit(bm, tip - line.way * 0.01 + Vector((NOSTRIL_SIDE * m, 0, 0)), tip + Vector((NOSTRIL_SIDE * m, 0, 0)))
    swell = line.snarl_axis(puff) + line.way * PUFF_FORE * m
    return dict(snarl=snarl, snarl_axis=line.snarl_axis(canine), puff=puff, swell=swell, bridge=bridge, bridge_up=up, nostril=nostril)


def build_muzzle_bones(arm, cfg, line, tip, nose, spots):
    """Returns the bones made and the nose bone's name."""
    A, s, head = arm.data, cfg['size'], cfg['head']
    E = A.edit_bones
    made = list(line.new)
    base = E[line.source].parent.name if E[line.source].parent else head
    for n in line.new:
        k = line.pieces.index(n)
        a, b = line.start.lerp(line.end, k / len(line.pieces)), line.start.lerp(line.end, (k + 1) / len(line.pieces))
        mk(A, n, a, b, line.pieces[k - 1] if k else base, deform=True)
    riders = [e.name for e in E if e.parent and e.parent.name in {line.source, *line.pieces} and e.name not in line.bones
              and e.name not in (SNOUT, rn.mch('MouthHalf'))]
    riders += [n for n in (rn.mch('UpperLipBase'), rn.left('MouthCorner', 'MCH'), rn.build('MouthCorner', 'R', role='MCH')) if n in E and E[n].parent.name == head]
    for n in riders:
        E[n].parent = E[line.piece(E[n].head)]
    root = E[line.bones[0]].parent.name if E[line.bones[0]].parent else head
    mk(A, SNOUT, line.end, line.end + FWD * 0.01 * s, root if not root.startswith(rn.mch('SnoutBend')) else E[root].parent.name)
    for k, n in enumerate(line.bones, 1):               # a turn layer above each bone, all with the control's axes
        insert_parent(A, n, rn.mch(f'SnoutBend{k}'))
        e = E[rn.mch(f'SnoutBend{k}')]
        e.tail, e.roll = e.head + FWD * 0.01 * s, 0
        made.append(e.name)
    if not nose:
        nose = 'Nose'
        mk(A, nose, tip, tip + UP * 0.02 * s, line.pieces[-1], deform=True)
        made.append(nose)
    insert_parent(A, nose, rn.mch('NoseMove'))
    f4, f6 = FWD * 0.004 * s, FWD * 0.006 * s
    extras = []
    if wants(cfg, 'snarl'):
        extras += [(rn.left('Snarl'), spots['snarl'], line.piece(spots['snarl']), False), (rn.left('Nostril'), spots['nostril'], nose, True)]
    if wants(cfg, 'puff'):
        extras.append((rn.left('Puff'), spots['puff'], line.piece(spots['puff']), False))
    for name, p, parent, deform in extras:
        if name == rn.left('Puff'):
            c = spots['swell']
            both(A, rn.left('PuffSwell', 'DEF'), c, c + line.way * 0.02 * s, parent, deform=True)
            both(A, name, p, p + f6, parent)
            made += [name, rn.with_side(name, 'R'), rn.left('PuffSwell', 'DEF'), rn.build('PuffSwell', 'R', role='DEF')]
        elif name == rn.left('Snarl'):
            c = spots['snarl_axis']
            both(A, rn.left('SnarlLift', 'DEF'), c, c + line.way * 0.02 * s, parent, deform=True)
            both(A, name, p, p + f6, parent)
            made += [name, rn.with_side(name, 'R'), rn.left('SnarlLift', 'DEF'), rn.build('SnarlLift', 'R', role='DEF')]
        else:
            move = rn.build(part_of(name) + 'Move', rn.side_of(name), role='MCH')
            both(A, move, p, p + f4, parent)
            both(A, name, p, p + f6, move, deform=deform)
            made += [name, rn.with_side(name, 'R'), move, rn.with_side(move, 'R')]
    p = spots['bridge']
    mk(A, rn.mch('NoseBridgeMove'), p, p + f4, line.piece(p))
    mk(A, 'NoseBridge', p, p + f6, rn.mch('NoseBridgeMove'), deform=True)
    return made + ['Snout', rn.mch('NoseMove'), rn.mch('NoseBridgeMove'), 'NoseBridge'], nose


def drive_move(pb, way, expr, variables):
    """The bone's location follows `way` (armature space) x the expression."""
    local = pb.bone.matrix_local.to_3x3().inverted() @ way
    for k in range(3):
        drive(pb, 'location', k, f'{local[k]:.5f}*({expr})', variables)


def snout_bend(arm, line):
    """The Snout control's moves, turns and scale, shared out over the turn layers."""
    P = arm.pose.bones
    P['Snout'].rotation_mode = 'XYZ'
    shares = [1 / len(line.bones)] * len(line.bones) if len(line.bones) != len(SNOUT_SHARE) else SNOUT_SHARE
    for k, share in enumerate(shares, 1):
        layer = P[rn.mch(f'SnoutBend{k}')]
        layer.rotation_mode = 'XYZ'
        for i, axis in enumerate('XYZ'):
            drive(layer, 'rotation_euler', i, f'{share:.4f}*v', {'v': ('Snout', 'ROT_' + axis, 'TRANSFORM_SPACE')})
            drive(layer, 'location', i, f'{share:.4f}*v', {'v': ('Snout', 'LOC_' + axis, 'TRANSFORM_SPACE')})
            drive(layer, 'scale', i, f'pow(max(v,0.01),{share:.4f})', {'v': ('Snout', 'SCALE_' + axis, 'TRANSFORM_SPACE')})


def snarl_lift(cap, name='n'):
    return f'max(min({name},{cap:.4f}),0)'


class LipSnarl:
    """The part of a snarl on one upper lip node's location channels: the node turns round the snout's axis, up and a
    bit out, along the snout's surface (empty on a lip node or a rig without one)."""
    def __init__(self, ctl='', arc=None, away=None, rate=0, cap=0):
        self.arc, self.away, self.angle = arc, away, f'{rate:.4f}*{snarl_lift(cap)}'
        self.variables = {'n': (ctl, 'LOC_Z', 'TRANSFORM_SPACE')} if arc else {}

    def term(self, k):
        return f'+{self.arc[k]:.5f}*sin({self.angle})+{self.away[k]:.5f}*(1-cos({self.angle}))' if self.arc else ''


def lip_snarl(arm, mch, side):
    B = arm.data.bones
    lift = rn.build('SnarlLift', side, role='DEF')
    share = next((v for k, v in SNARL_LIP.items() if 'Upper' in mch and k in mch), 0)
    if lift not in B or not share:
        return LipSnarl()
    centre, way = B[lift].head_local, B[lift].matrix_local.to_3x3().col[1]
    ctl = rn.build('Snarl', side)
    radial = B[mch].head_local - centre
    radial -= way * radial.dot(way)
    local = B[mch].matrix_local.to_3x3().inverted()
    sx = 1 if side == 'L' else -1
    return LipSnarl(ctl, local @ (way.cross(radial) * sx), local @ -radial, share / (B[ctl].head_local - centre).length, SNARL_MAX * mouth_size(arm))


def setup_muzzle_pose(arm, cfg, line, nose, spots):
    P, B = arm.pose.bones, arm.data.bones
    s, m = cfg['size'], mouth_size(arm)
    snout_bend(arm, line)
    cap = SNARL_MAX * m
    snarl, puffs = wants(cfg, 'snarl'), wants(cfg, 'puff')
    both_lifts = {'l': (rn.left('Snarl'), 'LOC_Z', 'TRANSFORM_SPACE'), 'r': (rn.build('Snarl', 'R'), 'LOC_Z', 'TRANSFORM_SPACE')}
    for side, sx in zip(SIDES, (1, -1)):
        if snarl:
            snarl_pose(arm, spots, cap, side, sx)
        if puffs:
            puff_pose(arm, m, side, sx)
    switch(P[nose], 'scrunch', 0, 1, 'Scrunch the nose: pull it back and bunch the bridge')
    if snarl:
        switch(P[nose], 'snarl_scrunch', 0, 1, 'How much a snarl scrunches the nose', default=0.5)
        scrunch = f'max(0,min({OVERSHOOT:.0f},c+k*({snarl_lift(cap, "l")}+{snarl_lift(cap, "r")})/{2 * SNARL_FULL * m:.4f}))'
        variables = {'c': (nose, 'scrunch'), 'k': (nose, 'snarl_scrunch'), **both_lifts}
    else:
        scrunch, variables = f'max(0,min({OVERSHOOT:.0f},c))', {'c': (nose, 'scrunch')}
    drive_move(P[rn.mch('NoseMove')], (UP * 0.6 - line.way) * SCRUNCH_PULL * m, scrunch, variables)
    drive_move(P[rn.mch('NoseBridgeMove')], spots['bridge_up'] * SCRUNCH_BULGE * m + line.way * SCRUNCH_BULGE * m, scrunch, variables)
    shape(P['Snout'], 'WGT-Ring', SNOUT_RING * s, (0, (B[nose].head_local - line.end).dot(line.way) + 0.04 * s, 0))
    face_shapes(arm, s)
    for name, home, on in ((rn.left('Snarl'), 'Mouth', snarl), (rn.left('Nostril'), 'Mouth', snarl), (rn.left('Puff'), 'Cheeks', puffs)):
        for n in (name, rn.with_side(name, 'R')) if on else ():
            bc.place_bone(arm, n, home, B[n].use_deform)
    for n in ('Snout', nose, 'NoseBridge'):
        bc.place_bone(arm, n, 'Mouth', B[n].use_deform)
    lifts = [rn.left('SnarlLift', 'DEF'), rn.build('SnarlLift', 'R', role='DEF')] if snarl else []
    swells = [rn.left('PuffSwell', 'DEF'), rn.build('PuffSwell', 'R', role='DEF')] if puffs else []
    for n in line.new + lifts + swells:
        bc.place_bone(arm, n, None, True)
    smile_flare(arm, cfg)


def snarl_pose(arm, spots, cap, side, sx):
    """One side's snarl: the lift turns round the snout's axis and bulges out, the nostril flares and rides the lift."""
    P, B, m = arm.pose.bones, arm.data.bones, mouth_size(arm)
    lift, ctl = P[rn.build('SnarlLift', side, role='DEF')], P[rn.build('Snarl', side)]
    lift.rotation_mode = 'XYZ'
    rate = sx / (B[ctl.name].head_local - B[lift.name].head_local).length
    drive(lift, 'rotation_euler', 1, f'{rate:.4f}*{snarl_lift(cap)}', {'n': (ctl.name, 'LOC_Z', 'TRANSFORM_SPACE')})
    out = (spots['snarl'] - spots['snarl_axis']).normalized()
    drive_move(lift, (out if side == 'L' else mirror(out)) * SNARL_BULGE / SNARL_MAX, snarl_lift(cap), {'n': (ctl.name, 'LOC_Z', 'TRANSFORM_SPACE')})
    ctl.lock_location = (True, True, False)
    ctl.lock_rotation = ctl.lock_scale = (True, True, True)
    ctl.lock_rotation_w = True
    nostril = rn.build('Nostril', side)
    switch(P[nostril], 'flare', -1, 1, 'Flare this nostril (1) or pinch it (-1)')
    out = Vector((sx, 0, 0.4)) * FLARE * m
    pull = UP * SNARL_NOSTRIL
    move = P[rn.build('NostrilMove', side, role='MCH')]
    local_out, local_pull = (move.bone.matrix_local.to_3x3().inverted() @ v for v in (out, pull))
    for k in range(3):
        drive(move, 'location', k, f'{local_out[k]:.5f}*f+{local_pull[k]:.5f}*{snarl_lift(cap)}',
              {'f': (nostril, 'flare'), 'n': (ctl.name, 'LOC_Z', 'TRANSFORM_SPACE')})


def puff_pose(arm, m, side, sx):
    """One side's cheek puff: the slider, or dragging the control out / in, swells PuffSwell."""
    P = arm.pose.bones
    puff = rn.build('Puff', side)
    switch(P[puff], 'puff', -1, 1, 'Swell the side of the muzzle (1) or suck it in (-1)')
    P[puff].lock_location = (False, True, True)
    outward = 1 if P[puff].bone.matrix_local.col[0].to_3d().dot(Vector((sx, 0, 0))) > 0 else -1
    amount = f'max(-{OVERSHOOT:.0f},min({OVERSHOOT:.0f},p+{outward}*x/{PUFF_GRAB * m:.4f}))'         # the slider, or drag the control out / in
    for k, grow in enumerate((PUFF_WIDE, PUFF_LONG, PUFF_WIDE)):
        drive(P[rn.build('PuffSwell', side, role='DEF')], 'scale', k, f'1+{grow}*{amount}',
              {'p': (puff, 'puff'), 'x': (puff, 'LOC_X', 'TRANSFORM_SPACE')})


def muzzle_skin(arm, cfg, meshes, parts, line, nose, tip, spots, nose_is_new):
    """Falloff weights of the new deform bones on the skin, the bodies, parts on the skin and a separate nose mesh."""
    src, m, B = meshes[0], mouth_size(arm), arm.data.bones
    bm = skin_bmesh(meshes)
    outer = outer_skin(bm, arm, cfg)
    lip_line = resample([B[n].head_local.copy() for n in UP_NODES], [k / 24 for k in range(25)])
    skin_co = [v.co.copy() for v in src.data.vertices]
    nostril_reach = NOSTRIL_REACH * m
    jobs = []
    snarls, puffs = wants(cfg, 'snarl'), wants(cfg, 'puff')
    for side in skin_sides(src):
        flip = (lambda p: p) if side == 'L' else mirror
        if snarls:
            reach = SNARL_REACH * (spots['snarl'] - (tip + Vector((NOSTRIL_SIDE * m, 0, 0)))).length
            snarl = flip(spots['snarl'])
            shares = side_shares(arm, bm, outer, lip_line, snarl, reach, side)
            jobs.append((rn.build('SnarlLift', side, role='DEF'), fade_towards(bm, shares, snarl, tip, SNARL_FADE)))
        if puffs:
            puff = smooth_shares(bm, bell_shares(bm, outer, flip(spots['puff']), PUFF_REACH * m, side), PUFF_SMOOTH)
            jobs.append((rn.build('PuffSwell', side, role='DEF'), {i: w * lip_fade(arm, lip_line, bm.verts[i].co, PUFF_TUCK * m) for i, w in puff.items()}))
        if snarls:
            jobs.append((rn.build('Nostril', side), ball_shares(skin_co, flip(spots['nostril']), nostril_reach)))
    seed = nearest_vert(bm, outer, spots['bridge'])
    reach = BRIDGE_REACH * m
    dist, _ = cw.dijkstra(bm, [seed.index], blocked={v.index for v in bm.verts} - outer, limit=reach)
    jobs.append(('NoseBridge', {i: 1 - cw.smoothstep(reach * SOFT_CORE, reach, d) for i, d in dist.items()}))
    if nose_is_new:
        jobs.append((nose, ball_shares(skin_co, tip, NOSE_REACH * m)))
    report = spread_weights(arm, cfg, meshes, parts, jobs)
    bm.free()
    for o in rig_meshes(arm):           # a nose of its own, near the nose all over
        co = rig_coords(arm, o)
        if snarls and o not in meshes + parts and co and max((p - tip).length for p in co) < NOSE_PART * m:
            for side in skin_sides(o):
                flip = (lambda p: p) if side == 'L' else mirror
                take_share(o, arm, cfg, rn.build('Nostril', side), ball_shares(co, flip(spots['nostril']), nostril_reach))
            if has_mirror(o):
                cw.ensure_mirror_groups(o, only={rn.left('Nostril')})
    return report


def muzzle_features(arm, cfg=None, log=print):
    """The snout above the lip line, all bones, off by default: a Snout control (nod, side shift, scale for a puff) over
    the rig's snout bones, cut into SNOUT_SEGS bends; the Nose (the rig's own or a new one) with `scrunch`, NoseBridge;
    cfg snarl: <Side>Snarl lifts the outer upper lip round the snout's axis, along its surface, and scrunches the nose by
    `snarl_scrunch`, <Side>Nostril with `flare`; cfg puff: <Side>Puff with `puff`. cfg['meshes'] (first = the skin) place
    the controls on the skin and get their weights; without a skin (a bare rig) the controls sit on the snout's line. Works
    on a built rig in place (safe to run again) and from Build. A rig with no snout bone is skipped. Returns the bones made."""
    cfg = cfg or stored(arm, 'maw') or config('maw')
    A, head = arm.data, cfg['head']
    meshes = [bpy.data.objects[n] for n in cfg['meshes'] if n in bpy.data.objects]
    parts = [bpy.data.objects[n] for n in cfg['skin_parts'] if n in bpy.data.objects]
    chain = snout_bones(arm, cfg) if rn.left('MouthCorner') in A.bones else []
    if not chain:
        log('M# muzzle: no snout bone, skipped')
        return []
    line = SnoutLine(arm, chain)
    with rig_space(arm, meshes + parts):
        nose = nose_bone(arm, head)
        nose_is_new = not nose or nose in built_info(arm).get('made', [])
        gone = {n: chain[-1] for n in (rn.left('SnarlLift', 'DEF'), rn.left('Puff'), rn.left('PuffSwell', 'DEF'), rn.left('Nostril'))
                if n in A.bones}
        gone.update({n: chain[-1] for n in [*line.new, 'NoseBridge', *([nose] if nose and nose_is_new else [])] if n in A.bones})
        for o in rig_meshes(arm):
            merge_groups(o, gone)
        bm = skin_bmesh(meshes)
        outer = outer_skin(bm, arm, cfg)
        tip = nose_tip(arm, cfg, bm, outer, line, nose)
        spots = muzzle_spots(arm, cfg, bm, line, tip)
        bm.free()
        parents = {b.name: b.parent.name for b in A.bones if b.parent}
        split_snout_weights(arm, line)
        old_puff = [n for n in (rn.left('PuffMove', 'MCH'), rn.build('PuffMove', 'R', role='MCH')) if n in A.bones]   # the puff's bones before PuffSwell
        for n in old_puff:
            arm.pose.bones[n].driver_remove('location')
        with in_mode(arm, 'EDIT'):
            made, nose = build_muzzle_bones(arm, cfg, line, tip, nose, spots)
            for n in old_puff:
                A.edit_bones.remove(A.edit_bones[n])
        with in_mode(arm, 'POSE'):
            setup_muzzle_pose(arm, cfg, line, nose, spots)
            for n in made:
                if rn.split_role(n)[0] == 'MCH':
                    bc.place_bone(arm, n, 'Mechanism', False)
        if meshes:
            log('M# muzzle: verts, parts', *muzzle_skin(arm, cfg, meshes, parts, line, nose, tip, spots, nose_is_new))
    moved = {n: p for n, p in parents.items() if n in A.bones and n not in made and A.bones[n].parent and A.bones[n].parent.name != p}
    record_built(arm, made, chain[-1], moved)
    return made


# ---------------------------------------------------------------- weights
def mm(t, s):
    return [x * MM * s for x in t]


def split_socket(obj, cfg, g, brow, side):
    """Head weight round the eye -> <side>EyeSocket (all of it inside the lid ring, a falloff outside)."""
    s = cfg['size']
    f0, f1 = mm(cfg['socket_falloff'], s)
    m0, m1 = mm(cfg['socket_midline'], s)
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
    ring = set(g['eye_ring'])
    lab, sizes = cw.components(bm, ring)
    inner = min(range(len(sizes)), key=lambda c: sizes[c])
    dist, _ = cw.dijkstra(bm, list(ring), limit=f1)
    bm.free()
    gi = {gr.index: gr.name for gr in obj.vertex_groups}
    head = obj.vertex_groups[cfg['head']]
    name = rn.build('EyeSocket', side)
    sock = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    out = set()
    for i, d in dist.items():
        v = obj.data.vertices[i]
        w = {gi[x.group]: x.weight for x in v.groups}
        hw = w.get(cfg['head'], 0.0)
        if hw <= 0:
            continue
        f = 1.0 if lab.get(i, -1) == inner else 1.0 - cw.smoothstep(f0, f1, d)
        f *= max(0.0, 1.0 - 2.0 * sum(x for n, x in w.items() if n in brow))
        f *= cw.smoothstep(m0, m1, abs(v.co.x))   # bridge skin stays put
        if f <= 0.01:
            continue
        head.add([i], hw * (1 - f), 'REPLACE')
        sock.add([i], w.get(name, 0.0) + hw * f, 'REPLACE')
        out.add(i)
    return out


def weight_lids(obj, arm, cfg, g, FREE):
    """Lid skin weights along the lid ring (g['eye_ring']): the pivots' polar chain, the head weight round the eye
    to the socket, then smoothing."""
    side, s = g['side'], cfg['size']
    B = arm.data.bones
    brow = {n for n in FREE if 'Eyebrow' in n}
    names = [rn.with_side(n, side) for n in cfg_lid_names(cfg)]
    radii = {'Inner': cfg['lid_corner'], 'Outer': cfg['lid_corner'], 'Upper': cfg['lid_upper'], 'Lower': cfg['lid_lower']}
    nodes = [(n, B[n].tail_local.copy()) for n in names]
    rad = [mm(next(v for k, v in radii.items() if k in n), s) for n in names]
    ctr = sum((obj.data.vertices[i].co for i in g['eye_ring']), Vector()) / len(g['eye_ring'])
    spec = cw.ChainSpec(nodes, rad, True, 'polar', center=ctr); spec.prepare()
    smallest = lambda sizes: min(range(len(sizes)), key=lambda c: sizes[c])
    touched = cw.rebuild(obj, {'eye': g['eye_ring']}, lambda _: spec, set(names), smallest, FREE,
                         straight=cfg['lid_straight'])
    touched |= split_socket(obj, cfg, g, brow, side)
    it, fac, reach = cfg['eye_smooth']
    zone = cw.zone(obj, {'eye': g['eye_ring']}, reach * MM * s)
    gi = {gr.index: gr.name for gr in obj.vertex_groups}
    pin = {i for i in zone if sum(x.weight for x in obj.data.vertices[i].groups if gi[x.group] in brow) > 0.5}
    cw.smooth(obj, zone, FREE | {rn.build('EyeSocket', side)}, it, fac, pinned=pin | set(g['eye_ring']))
    return touched | set(zone)


def weight_lips(obj, arm, cfg, g, FREE):
    side, s = g['side'], cfg['size']
    sn = lambda n: rn.with_side(n, side)
    B = arm.data.bones
    rad = [mm(r, s) for r in (cfg['lip_center'], cfg['lip_mid'], cfg['lip_mid'], cfg['lip_mid'], cfg['lip_corner'])]
    up = cw.SegmentChainSpec([sn(n) for n in UP_SEGS], [B[sn(n)].head_local.copy() for n in UP_NODES], rad)
    lo = cw.SegmentChainSpec([sn(n) for n in LO_SEGS], [B[sn(n)].head_local.copy() for n in LO_NODES], rad)
    margins = {'up': g['lip_up'], 'lo': g['lip_lo']}
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
    lab, sizes = cw.components(bm, set(g['lip_up']) | set(g['lip_lo']))
    # the mouth's inside: the part holding the point just behind the lips' centre
    sx = 1 if side == 'L' else -1
    inside = (B['UpperLip'].head_local + B['LowerLip'].head_local) / 2 + Vector((0.004 * sx, 0.012, 0)) * s
    near = min((v for v in bm.verts if v.index in lab), key=lambda v: (v.co - inside).length)
    inner_c = lab[near.index]
    bm.free()
    touched = cw.rebuild(obj, margins, lambda lb: up if lb == 'up' else lo,
                         set(up.groups + lo.groups), lambda _: inner_c, FREE)
    it, fac, reach = cfg['lip_smooth']
    zone = cw.zone(obj, margins, reach * MM * s)
    corner, v = B[sn(rn.left('MouthCorner'))].head_local, obj.data.vertices
    nearc = lambda i: (v[i].co - corner).length < 8 * MM * s
    cw.smooth(obj, zone, FREE, it, fac, unblock=lambda a, b: nearc(a) and nearc(b), pinned=set(g['lip_up']) | set(g['lip_lo']))
    return touched | set(zone)


def weight_brows(obj, arm, cfg, g, FREE):
    """New brow segments (the character had no brow bones): skin near the brow line follows its segments
    (smoothstep falloff), taken from the head."""
    side, s = g['side'], cfg['size']
    B = arm.data.bones
    segs = [rn.with_side(n, side) for n in BROW_SEGS]
    pts = [B[n].head_local for n in brow_nodes(B, side)]
    r0, r1 = 3 * MM * s, 10 * MM * s
    head = cfg['head']
    gi = {x.index: x.name for x in obj.vertex_groups}
    groups = {n: obj.vertex_groups.get(n) or obj.vertex_groups.new(name=n) for n in segs}
    out = set()
    for v in obj.data.vertices:
        best = None
        for k in range(3):
            _, t = intersect_point_line(v.co, pts[k], pts[k + 1])
            t = max(0.0, min(1.0, t))
            d = (pts[k].lerp(pts[k + 1], t) - v.co).length
            if best is None or d < best[0]:
                best = (d, k)
        d, k = best
        if d >= r1:
            continue
        hw = next((x.weight for x in v.groups if gi[x.group] == head), 0.0)
        f = (1.0 - cw.smoothstep(r0, r1, d)) * hw
        if f <= 0.01:
            continue
        obj.vertex_groups[head].add([v.index], hw - f, 'REPLACE')
        groups[segs[k]].add([v.index], f, 'REPLACE')
        out.add(v.index)
    return out


def ring_at_angle(ring, ctr, a):
    """Point of a closed ring (XZ plane round ctr) at polar angle a."""
    ang = lambda p: math.atan2(p.z - ctr.z, p.x - ctr.x)
    for p, q in zip(ring, ring[1:] + ring[:1]):
        a0, a1 = ang(p), ang(q)
        span = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        off = (a - a0 + math.pi) % (2 * math.pi) - math.pi
        if span and 0 <= off / span <= 1:
            return p.lerp(q, off / span)
    return min(ring, key=lambda p: abs((ang(p) - a + math.pi) % (2 * math.pi) - math.pi))


def skin_part_verts(src, part, touched, reach):
    """Part vertices whose nearest skin face has a re-weighted vertex."""
    sco = [src.matrix_world @ v.co for v in src.data.vertices]
    polys = [tuple(p.vertices) for p in src.data.polygons]
    bvh = BVHTree.FromPolygons(sco, polys)
    out = []
    for v in part.data.vertices:
        _, _, pi, d = bvh.find_nearest(part.matrix_world @ v.co)
        if pi is not None and d < reach and any(k in touched for k in polys[pi]):
            out.append(v.index)
    return out


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def edge_normal(path, x, c):
    """Front-view (XZ) angle of a lid line's outward normal (away from the eye centre c) at x."""
    p = at_x(path, x)
    q = at_x(path, x + 0.002) - at_x(path, x - 0.002)
    n = (-q.z, q.x)
    if n[0] * (p.x - c.x) + n[1] * (p.z - c.z) < 0:
        n = (-n[0], -n[1])
    return math.atan2(n[1], n[0])


def lash_swing(roots, dirs, line, c, aim_w):
    """One swing (front-view rotation, radians) for a whole upper lash set, so on the shut lid the roots lie
    along the shut lid line and the lashes point out of it, evenly. Brute-force over whole degrees."""
    cx = sum(p.x for p in roots) / len(roots); cz = sum(p.z for p in roots) / len(roots)
    c2 = at_x(line, cx)
    target = edge_normal(line, cx, c)
    best = None
    for deg in range(-180, 180):
        f = math.radians(deg); cs, sn = math.cos(f), math.sin(f)
        off = []
        for p in roots:
            x, z = p.x - cx, p.z - cz
            x, z = c2.x + cs * x - sn * z, c2.z + sn * x + cs * z
            off.append(abs(z - at_x(line, x).z) * 1000)
        aim = [abs(math.degrees(wrap(math.atan2(d.z, d.x) + f - target))) for d in dirs]
        cost = sum(off) / len(off) + aim_w * sum(aim) / len(aim) + 0.05 * max(aim)
        if best is None or cost < best[0]:
            best = (cost, f)
    return best[1]


def rig_lashes(arm, body, eb, cfg):
    """Lashes as two rigid sets per eye, each one control: UpperLashes.L / LowerLashes.L (deform; grab,
    rotate or scale them to hand-fix a pose). Parents: MCH-<Lid>Lashes.L follows the lid edge at the set's
    roots (Armature constraint, the skin's weights there, that lid and the corners only),
    MCH-<Lid>LashesSwing.L cancels the lid's forward tilt (read from MCH-<Lid>LashesTilt.L, which hangs on the head) and, for the upper set, swings it once the eye is
    past `lash_start` shut. Re-runnable on any file with the rig (replaces earlier lash bones and weights).
    Left side lashes + a Mirror modifier on the lash mesh (the right set mirrors)."""
    s, head, eye = cfg['size'], cfg['head'], cfg['eye_bone']
    A, P, B = arm.data, arm.pose.bones, arm.data.bones
    names = cfg_lid_names(cfg)
    bm = bmesh.new(); bm.from_mesh(body.data); bm.verts.ensure_lookup_table()
    ring_i = cw.find_ring(bm, [B[n].tail_local for n in names], closed=True, tol=0.006 * s)
    bm.free()
    ring = [body.matrix_world @ body.data.vertices[i].co for i in ring_i]
    upper, lower = split_ring(ring)
    c = B[eye].head_local.copy()
    D = B[rn.left('UpperLid')]['travel']
    parts = LidParts(eb, ring, size=s)
    mode = arm.mode
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    E = A.edit_bones
    eye_roll = E[eye].roll
    for e in [e for e in E if is_lash(e.name)]:
        E.remove(e)
    sets = {}
    for (o, t), vs, sd in zip(parts.lashes, parts.lash_verts, parts.lash_side):
        sets.setdefault('Upper' if sd == 'upper' else 'Lower', []).append((parts.rest[o].copy(), parts.rest[t].copy(), vs))
    for lid, ls in sets.items():
        root = sum((r for r, _, _ in ls), Vector()) / len(ls)
        aim = sum(((t - r).normalized() for r, t, _ in ls), Vector()).normalized()
        both(A, rn.left(f'{lid}Lashes', 'MCH'), root, root + FWD * 0.004 * s, roll=eye_roll)
        both(A, rn.left(f'{lid}LashesSwing', 'MCH'), root, root + FWD * 0.004 * s, rn.left(f'{lid}Lashes', 'MCH'), roll=eye_roll)
        both(A, rn.left(f'{lid}LashesTilt', 'MCH'), root, root + FWD * 0.004 * s, head, roll=eye_roll)
        l, r = both(A, rn.left(f'{lid}Lashes'), root, root + aim * 0.012 * s, rn.left(f'{lid}LashesSwing', 'MCH'), deform=True)
        l.align_roll(Vector((0, -1, 0))); r.roll = -l.roll
    bpy.ops.object.mode_set(mode='POSE')
    if arm.animation_data:            # drivers of lash bones that are gone (older per-lash rigs)
        for fc in [fc for fc in arm.animation_data.drivers if fc.data_path.startswith('pose.bones["')
                   and fc.data_path.split('"')[1] not in arm.pose.bones]:
            arm.animation_data.drivers.remove(fc)
    for g_ in [g_ for g_ in eb.vertex_groups if is_lash(g_.name)]:
        eb.vertex_groups.remove(g_)
    free = free_groups(body, arm, head) | {n for n in (x.name for x in eb.vertex_groups) if part_of(n).startswith('Lid')}
    for lid, ls in sets.items():
        roots = [r for r, _, _ in ls]; root = sum(roots, Vector()) / len(roots)
        vs0 = ls[0][2][0]
        for x in list(eb.data.vertices[vs0].groups):          # (old lash groups would leave no room)
            eb.vertex_groups[x.group].remove([vs0])
        cw.transfer_from_loop(body, ring_i, eb, [vs0], free, anchor=root)      # the skin's weights at the set's roots
        gi = {x.index: x.name for x in eb.vertex_groups}
        other = 'LidTipLower' if lid == 'Upper' else 'LidTipUpper'
        w = {gi[x.group]: x.weight for x in eb.data.vertices[vs0].groups
             if x.weight > 0.01 and gi[x.group] in free and gi[x.group] in B and part_of(gi[x.group]) != other}
        tot = sum(w.values()); w = {n: x / tot for n, x in w.items()}
        flip = 0.0
        if lid == 'Upper':
            sw = cfg['lash_swing']
            flip = math.radians(sw) if sw is not None else lash_swing(roots, [t - r for r, t, _ in ls], lower, c, cfg['lash_aim'])
        for side, sg in (('L', 1.0), ('R', -1.0)):
            sn = lambda n: rn.with_side(n, side)
            mch, swing, ctrl = P[sn(rn.left(f'{lid}Lashes', 'MCH'))], P[sn(rn.left(f'{lid}LashesSwing', 'MCH'))], P[sn(rn.left(f'{lid}Lashes'))]
            tilt = P[sn(rn.left(f'{lid}LashesTilt', 'MCH'))]    # the lid's tilt against the head: a nod must not count
            for b_ in (mch, swing, ctrl, tilt):  # a re-run gets the old pose data back with the bone names
                for c_ in list(b_.constraints):
                    b_.constraints.remove(c_)
            follow(mch, {sn(n): x for n, x in w.items()})
            swing.rotation_mode = 'YXZ'
            c = tilt.constraints.new('COPY_ROTATION')
            c.name, c.target, c.subtarget, c.owner_space, c.target_space = 'Lid Tilt', arm, mch.name, 'WORLD', 'WORLD'
            drive(swing, 'rotation_euler', 0, '-rx', {'rx': (tilt.name, 'ROT_X', 'LOCAL_SPACE')})
            if flip:
                lids = {'up': (sn(rn.left('UpperLid')), 'LOC_Z', 'TRANSFORM_SPACE'), 'lo': (sn(rn.left('LowerLid')), 'LOC_Z', 'TRANSFORM_SPACE')}
                shut = f"(lo-up)/{D:.5f}"          # 0 open .. 1 shut; the swing starts past lash_start, eased in
                st = cfg['lash_start']
                drive(swing, 'rotation_euler', 1, f"{sg * flip:.4f}*pow(min(max(({shut}-{st})/{1 - st},0),1),2)", lids)
            shape(ctrl, 'WGT-Arrow', ctrl.bone.length)      # an arrow along the lashes: not mistaken for a ring control
            bc.place_bone(arm, ctrl.name, 'Eyes', True)
            for b_ in (mch, swing, tilt):
                bc.place_bone(arm, b_.name, 'Mechanism', False)
            ctrl.bone.color.palette = 'THEME06'
        verts = [i for _, _, vs in ls for i in vs]
        for i in verts:
            for x in list(eb.data.vertices[i].groups):
                eb.vertex_groups[x.group].remove([i])
        eb.vertex_groups.new(name=rn.left(f'{lid}Lashes')).add(verts, 1.0, 'REPLACE')
        print(f'M# {lid.lower()} lashes: {len(ls)} as one set, swing {math.degrees(flip):.0f} deg, follows', sorted(w))
    cw.ensure_mirror_groups(eb, only={rn.left(f'{lid}Lashes') for lid in sets})
    bc.apply_face_split_colors(arm, cfg['colors'], only={rn.build(f'{lid}Lashes', side) for lid in sets for side in SIDES})
    bpy.ops.object.mode_set(mode=mode)
    bpy.context.view_layer.update()
    return sets


def weight_parts(src, arm, cfg, gl, FREE, touched, old_names):
    """Lid liners + lashes take the lid edge's weights; skin parts take the skin's."""
    s = cfg['size']
    report = {}
    eb = bpy.data.objects.get(cfg.get('lash_mesh') or '') if cfg['kind'] == 'eye' else None
    oldset = set(old_names)
    lv = []
    if eb is not None and gl.get('parts') is not None:
        gi = {x.index: x.name for x in eb.vertex_groups}
        lv = [v.index for v in eb.data.vertices if any(gi[x.group] in oldset and x.weight > 0 for x in v.groups)]
        lash_set = {i for vs in gl['parts'].lash_verts for i in vs}
        if not lv:      # a first build on a character whose liners weren't on old lid bones: the liner parts
            lv = [i for bins in gl['parts'].liners.values() for b in bins for i in b]
        # liner tubes: every vertex takes the lid edge point at its angle round the eye, so a whole
        # cross-section moves as one piece
        ring = [src.matrix_world @ src.data.vertices[k].co for k in gl['eye_ring']]
        ctr = sum(ring, Vector()) / len(ring)
        pol = lambda p: math.atan2(p.z - ctr.z, p.x - ctr.x)
        for i in lv:
            if i in lash_set:
                continue
            p = eb.matrix_world @ eb.data.vertices[i].co
            cw.transfer_from_loop(src, gl['eye_ring'], eb, [i], FREE | oldset, anchor=ring_at_angle(ring, ctr, pol(p)))
        if cfg['lashes'] and gl['parts'].lashes:
            rig_lashes(arm, src, eb, cfg)
        rest = [i for i in skin_part_verts(src, eb, touched, 0.02 * s) if i not in set(lv)]
        cw.transfer_from_surface(src, eb, rest, {cfg['head'], rn.left('EyeSocket'), rn.build('EyeSocket', 'R')})
        report[eb.name] = (len(lv), len(rest))
    if cfg['kind'] == 'eye':
        report.update(weight_lid_shells(arm, cfg, gl, FREE | oldset))
    for n in cfg['skin_parts']:
        o = bpy.data.objects.get(n)
        if not o or o is eb or n in report:
            continue
        gi = {x.index: x.name for x in o.vertex_groups}
        vs = set(skin_part_verts(src, o, touched, 0.02 * s))
        vs |= {v.index for v in o.data.vertices if any(gi[x.group] in oldset and x.weight > 0 for x in v.groups)}
        cw.transfer_from_surface(src, o, sorted(vs), FREE | oldset)
        report[n] = len(vs)
    return report


def used_groups(obj):
    """Names of obj's vertex groups that hold any weight."""
    gi = {g.index: g.name for g in obj.vertex_groups}
    return {gi[x.group] for v in obj.data.vertices for x in v.groups if x.weight > 1e-4}


def drop_groups(names):
    left = {}
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        for n in names:
            vg = o.vertex_groups.get(n)
            if vg:
                used = sum(1 for v in o.data.vertices for x in v.groups if x.group == vg.index and x.weight > 1e-4)
                if used:
                    left[f'{o.name}:{n}'] = used
                o.vertex_groups.remove(vg)
    return left


def new_deform(arm, head='Head'):
    fb = face_bones(arm, head)
    return {n for n in fb if part_of(n).startswith(NEW_DEFORM)}


# ---------------------------------------------------------------- collections + colours
def homes(cfg_eye, cfg_maw):
    """Home collection of each Left/centre built bone name (Right ones follow)."""
    h = {}
    if cfg_eye:
        for n in (rn.left('UpperLid'), rn.left('LowerLid'), rn.left('EyeSocket')):
            h[n] = 'Eyes'
        for n in cfg_lid_names(cfg_eye):
            h[n] = 'Mechanism' if cfg_eye['lid_mode'] == 'RING' else None    # Pivots: the tips deform (Deform only)
            h[rn.mch(n)] = 'Mechanism'
        if cfg_eye['brows']:
            for n in [rn.left('Brow')] + BROW_CTRL:
                h[n] = 'Brows'
            for n in BROW_NODES:
                h[n] = 'Face Tweak'
                h[rn.mch(n)] = 'Mechanism'
            for n in BROW_SEGS:
                h[n] = None
    if cfg_maw:
        for n in ('UpperLip', 'LowerLip', rn.left('MouthCorner'), rn.left('UpperLipMid'), rn.left('LowerLipMid')):
            h[n] = 'Mouth'
        for n in LIP_TWEAKS:
            h[n] = 'Face Tweak'
        for n in (rn.left('UpperLipMid'), rn.left('LowerLipMid'), *LIP_TWEAKS, rn.left('MouthCorner'), rn.left('MouthCornerJaw'), rn.left('MouthCornerLow'),
                  rn.left('UpperLipTangent'), rn.left('LowerLipTangent')):
            h[rn.mch(n)] = 'Mechanism'
        for n in UP_SEGS + LO_SEGS:
            h[n] = None
    return h


def place_collections(arm, cfg_eye, cfg_maw, made):
    """Built bones into the shared layout (only them and reused brow nodes; the rest of the rig is left
    alone), then the upper / lower colours on them. `made`: bones this build created (an eye / jaw bone too)."""
    h = homes(cfg_eye, cfg_maw)
    cfg = cfg_eye or cfg_maw
    if cfg_eye:
        h[cfg_eye['eye_bone']] = 'Eyes'
    if cfg_maw:
        h[cfg_maw['jaw']] = 'Mouth'
    existing_ok = set(BROW_NODES + BROW_SEGS)          # reused bones that change role (nodes become tweaks)
    names = set()
    for n, home in h.items():
        for nm in {n, rn.with_side(n, 'R')}:
            b = arm.data.bones.get(nm)
            if b is None or (nm not in made and stem(nm) not in {stem(x) for x in existing_ok}):
                continue
            bc.place_bone(arm, nm, home, b.use_deform)
            names.add(nm)
    for nm in names:
        pb = arm.pose.bones[nm]
        if pb.color.palette == 'CUSTOM':
            pb.color.palette = 'DEFAULT'
    setup = {cfg_maw[k] for k in ('upper_parent', 'lower_parent', 'corner_parent')} if cfg_maw else set()
    setup -= {'', cfg['head'], (cfg_maw or {}).get('jaw')}
    for b in arm.data.bones:      # bones the rig already had: set-up ones go to Adjustment, extras to Face Non-Standard
        extra = re.search(bc.FACE_NON_STANDARD, rn.plain(b.name))
        if b.name not in names and (extra or b.name in setup or re.search(bc.FACE_ADJUSTMENT, rn.plain(b.name))) \
                and is_face_bone(arm, b, cfg['head']):
            bc.place_bone(arm, b.name, 'Face Non-Standard' if extra else 'Adjustment', b.use_deform)
    bc.apply_face_split_colors(arm, cfg['colors'], only=names)
    return names


def is_face_bone(arm, b, head):
    """b hangs (somewhere) under the head bone."""
    p = b.parent
    while p and p.name != head:
        p = p.parent
    return p is not None


# ---------------------------------------------------------------- build / remove / rebuild
def control_pose(arm, names):
    """Pose channels of the given bones (to restore after a rebuild)."""
    out = {}
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb and rn.split_role(n)[0] != 'MCH':
            out[n] = (tuple(pb.location), tuple(pb.rotation_quaternion), tuple(pb.rotation_euler), tuple(pb.scale))
    return out


def restore_pose(arm, saved):
    for n, (loc, q, e, sc) in saved.items():
        pb = arm.pose.bones.get(n)
        if pb:
            pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = loc, q, e, sc
    bpy.context.view_layer.update()


def reset_pose(arm):
    for pb in arm.pose.bones:
        pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.rotation_euler = (0, 0, 0)
        pb.scale = (1, 1, 1)
    bpy.context.view_layer.update()


def bone_homes(arm, names):
    """{bone: its collections}, to keep the user's sorting through a rebuild."""
    return {n: [c.name for c in arm.data.bones[n].collections] for n in names if n in arm.data.bones}


def restore_homes(arm, homes):
    collections = arm.data.collections_all
    for name, wanted in homes.items():
        bone = arm.data.bones.get(name)
        if bone is None or not all(c in collections for c in wanted):
            continue
        for c in list(bone.collections):
            c.unassign(bone)
        for c in wanted:
            collections[c].assign(bone)


def built_info(arm):
    return json.loads(arm.data.get('face_rig_built', '{}'))


BUILT_PARTS = re.compile(r'Lid.*|(Upper|Lower)(Lid|Lip.*|Lashes.*)|EyeSocket|Brow(Inner|Mid|Outer)?|Eyebrow(Seg)?|MouthCorner.*'
                         r'|Mouth(Half|Low|JawZip)|(Smile)?Cheek.*|Tongue.*|Snout(Bend|Seg)?|NoseMove'
                         r'|NoseBridge(Move)?|Nostril(Move)?|Snarl(Lift)?|Puff(Swell)?')


def is_built_name(name):
    """A name the face rig tools make, in any style."""
    return bool(BUILT_PARTS.fullmatch(part_of(name)))


def has_built(arm):
    """A built face rig on the rig, with or without its build record."""
    return bool(arm.data.get('face_rig_built')) or rn.find(arm.data.bones.keys(), rn.left('MouthCorner')) is not None \
        or rn.find(arm.data.bones.keys(), rn.left('UpperLid')) is not None


def standardise_face(arm, lid_mode=None):
    """A face rig built with old names (`LeftMouthCorner`) moves to the standard names first, so the one builder only
    knows those. Only the face rig's own bones: the rest of an old rig keeps its names. The lid tips get the role of
    `lid_mode` (default: the rig's, rig_lid_mode): an old Pivots rig's MCH- tips become DEF-. Returns how many were
    renamed."""
    names = set(built_info(arm).get('made', [])) | {b.name for b in arm.data.bones if is_built_name(b.name)}
    table = {n: rn.standard(n) for n in names if n in arm.data.bones and rn.standard(n) != n}
    table.update(old_cheek_names(arm))
    table = {old: new for old, new in table.items() if new not in arm.data.bones}
    if table:
        rr.rename(arm, table)
    return len(table) + name_lid_tips(arm, lid_mode or rig_lid_mode(arm))


def rig_bone_names(arm, cfg):
    """The config's bones as this rig calls them: a default `Eye.L` finds an old rig's `eye_l`."""
    for key in ('head', 'eye_bone', 'jaw', 'upper_parent', 'lower_parent', 'corner_parent'):
        if cfg.get(key):
            cfg[key] = rn.find(arm.data.bones.keys(), cfg[key]) or cfg[key]


def own_guides(arm, has_eye, has_maw):
    """Guide points read off a built rig's own bones: the lid tips on the lid edge, the lip nodes on the lip line."""
    B = arm.data.bones
    head_of = lambda name: B[name].head_local.copy()
    g = {}
    if has_eye:
        eye = guess_bones(arm)['eye_bone']
        g.update(Eye=head_of(eye), EyeAim=B[eye].tail_local.copy())
        g.update(ring_from_points([B[t].tail_local.copy() for t in lid_names(count_pivots(arm), rig_lid_mode(arm))], g['Eye']))
        g.update({f'Brow{k}': head_of(name) for k, name in enumerate(brow_nodes(B), start=1) if name in B})
    if has_maw:
        up, lo = [head_of(x) for x in UP_NODES], [head_of(x) for x in LO_NODES]
        jaw = B[B[rn.left('MouthCornerJaw', 'MCH')].parent.name]
        g.update(LipUpper=up[0], LipUpperMid=resample(up, [0.5])[0], MouthCorner=up[-1], LipLower=lo[0],
                 LipLowerMid=resample(lo, [0.5])[0], Jaw=jaw.head_local.copy(), JawTip=jaw.tail_local.copy())
    return g


def count_pivots(arm):
    """Lid pivots per eye of a built rig."""
    return 2 * sum(1 for b in arm.data.bones if rn.side_of(b.name) == 'L' and part_of(b.name) == 'LidTipUpper') + 2


def meshes_on_group(arm, groups):
    """Meshes on the rig that have weights on any of these vertex groups."""
    return [o for o in rig_meshes(arm) if used_groups(o) & set(groups)]


def recover_configs(arm):
    """(eye, maw) configs of a built rig that lost its stored ones, read off the rig itself: guides from its bones, jaw and
    parents from where the built bones hang, meshes from the weights. None for a rig that isn't built."""
    B = arm.data.bones
    parent_of = lambda *names: next(B[n].parent.name for n in names if n in B)    # the first of these bones the rig has
    has_eye, has_maw = rn.left('UpperLid') in B, rn.left('MouthCorner') in B
    guides = own_guides(arm, has_eye, has_maw)
    lash = meshes_on_group(arm, [rn.left('UpperLashes'), rn.left('LowerLashes')])
    meshes = guess_meshes(arm)
    skin_groups = [rn.with_side(n, sd) for n in BROW_SEGS + [rn.left('Cheek')] for sd in SIDES]
    parts = sorted(o.name for o in meshes_on_group(arm, skin_groups) if o.name not in meshes and o not in lash)
    common = dict(head=guess_bones(arm)['head'], meshes=meshes, skin_parts=parts, guides=guides,
                  size=auto_size(guides) if has_eye else 1.0)
    eye = maw = None
    if has_eye:
        eye = config('eye', **common, eye_bone=guess_bones(arm)['eye_bone'], pivots=count_pivots(arm),
                     brows=BROW_SEGS[0] in B or BROW_NODES[0] in B, lashes=bool(lash), lash_mesh=lash[0].name if lash else '',
                     lid_mode=rig_lid_mode(arm),
                     lid_tweaks=lid_tweak_name(lid_tip('Upper', 1)) in B, brow_tweaks=BROW_NODES[0] in B and arm.pose.bones[BROW_NODES[0]].custom_shape is not None)
    if has_maw:
        maw = config('maw', **common, jaw=parent_of(rn.left('MouthCornerJaw', 'MCH')),
                     lower_parent=parent_of(rn.mch('LowerLipBase'), 'LowerLip'), upper_parent=parent_of(rn.mch('MouthHalf'), rn.mch('UpperLipBase'), 'UpperLip'),
                     corner_parent=parent_of(rn.left('MouthCorner', 'MCH')),
                     smile_cheeks=rn.left('Cheek') in B, zipper=ZIP_JAW in B, mouth_sliders=rn.left('MouthCornerMove', 'MCH') in B,
                     tongue_rig=TONGUE_BASE in B, snarl=rn.left('Snarl') in B, puff=rn.left('Puff') in B)
    return eye, maw


def first_kept_parents(arm, made, head):
    """{bone that stays: the first parent that stays, else the head}, for the bones that hang on a built bone."""
    out = {}
    for b in arm.data.bones:
        if b.name not in made and b.parent and b.parent.name in made:
            p = b.parent
            while p and p.name in made:
                p = p.parent
            out[b.name] = p.name if p else head
    return out


def recover_record(arm):
    """A built face rig without its build record (Digit's master lost it): the record and configs, written from the rig."""
    eye, maw = recover_configs(arm)
    base = eye or maw
    keep = {eye['eye_bone'], rn.flip(eye['eye_bone'])} if eye else set()
    keep |= {rn.with_side(n, sd) for n in BROW_NODES + BROW_SEGS for sd in SIDES}   # a complete brow set is reused, as build does
    if maw:                      # its snout bones (DEF-SnoutSeg* too) are the rig's own: Rebuild cuts them again
        keep |= set(snout_bones(arm, maw))
    made = {b.name for b in arm.data.bones if is_built_name(b.name)} - keep
    A = arm.data
    A['face_rig_built'] = json.dumps(dict(made=sorted(made), reparented=first_kept_parents(arm, made, base['head']), heir={}))
    for cfg in (eye, maw):
        if cfg:
            A['face_rig_' + cfg['kind']] = to_json(cfg)


def build(arm, eye=None, maw=None, log=print):
    """Build the Eye Rig and / or the Anthro Mouth Rig on `arm` from their configs (config()). Returns a report dict.
    The armature should be in its rest pose for the face (the pose is reset; use rebuild() to keep it).
    Meshes offset from the armature are handled (rig_space)."""
    cfgs = [c for c in (eye, maw) if c]
    if not cfgs:
        raise ValueError('nothing to build')
    standardise_face(arm)
    for c in cfgs:
        rig_bone_names(arm, c)
    names = set(cfgs[0]['meshes']) | {n for c in cfgs for n in c.get('skin_parts', [])} | {(eye or {}).get('lash_mesh', '')}
    with rig_space(arm, [bpy.data.objects.get(n) for n in names if n]):
        return build_in_rig_space(arm, eye, maw, cfgs, log)


def build_in_rig_space(arm, eye, maw, cfgs, log):
    base = cfgs[0]
    head = base['head']
    if head not in arm.data.bones:
        raise ValueError(f'no head bone {head!r} in {arm.name}')
    meshes = [bpy.data.objects[n] for n in base['meshes'] if n in bpy.data.objects]
    src = meshes[0] if meshes else None
    weights = base['weights'] and src is not None
    if weights:
        for o in meshes:
            check_space(arm, o)
        if not has_mirror(src):
            log('M# note: the weight source has no Mirror modifier: both sides are weighted (less tested)')
    bpy.context.view_layer.objects.active = arm
    arm.hide_set(False); arm.hide_viewport = False
    start_mode = arm.mode
    if arm.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    reset_pose(arm)
    before_bones = {b.name for b in arm.data.bones}
    parents_before = {b.name: (b.parent.name if b.parent else '') for b in arm.data.bones}
    # geometry (left frame per side)
    G = {}
    if eye:
        lash = bpy.data.objects.get(eye['lash_mesh']) if eye['lash_mesh'] else None
        for side in SIDES:
            if side == 'R' and eye['mirror']:
                G.setdefault('eye', {})[side] = G['eye']['L']; continue
            G.setdefault('eye', {})[side] = eye_geometry(arm, src, eye, side, lash if side == 'L' and src else None)
        if src is not None and not G['eye']['L']['eye_ring']:
            log('M# eye: no edge loop along the lid guides; bones placed on the guides, no lid weights')
    if maw:
        for side in SIDES:
            if side == 'R' and maw['mirror']:
                G.setdefault('maw', {})[side] = G['maw']['L']; continue
            G.setdefault('maw', {})[side] = maw_geometry(arm, src, maw, side)
        if src is not None and not (G['maw']['L']['lip_up'] and G['maw']['L']['lip_lo']):
            log('M# maw: no edge loops along the lip guides; bones placed on the guides, no lip weights')
        elif src is not None and G['maw']['L']['lip_up'] == G['maw']['L']['lip_lo']:
            log('M# maw: WARNING the upper and lower lip guides found the same edge loop; put LipUpper / LipLower '
                '(and the Mid guides) right on each lip edge')
    keep = set()
    brow_set = {rn.with_side(n, sd) for n in BROW_NODES + BROW_SEGS for sd in SIDES}
    partial_brows = set()
    if eye:
        keep |= {eye['eye_bone'], rn.with_side(eye['eye_bone'], 'R')}
        have = brow_set & {b.name for b in arm.data.bones}
        if have == brow_set:
            keep |= brow_set                  # a complete old brow set is reused (nodes become tweaks)
        else:
            partial_brows = have              # a partial one (3 of 4 nodes) is replaced by a fresh set
    if maw:
        keep |= {maw['jaw'], maw['upper_parent'], maw['lower_parent'], maw['corner_parent']}
    keep.add(head)
    old = sorted(set(replaced_bones(arm, sum((c['replace'] for c in cfgs), []), keep)) | partial_brows)
    heir = deform_heir(arm, old, head)
    face_before = free_groups(src, arm, head) if weights else set()
    snap = {o.name: snapshot(o) for o in bpy.data.objects if o.type == 'MESH'} if weights else {}
    # bones
    A = arm.data
    mirror_edit, A.use_mirror_x = A.use_mirror_x, False    # X-Axis Mirror would overwrite the reversed Right chains
    bpy.ops.object.mode_set(mode='EDIT')
    E = A.edit_bones
    for n in old:
        E.remove(E[n])
    if eye:
        build_eye_bones(arm, eye, G['eye'])
    if maw:
        build_maw_bones(arm, maw, G['maw'])
    bpy.ops.object.mode_set(mode='POSE')
    A.use_mirror_x = mirror_edit
    made = sorted({b.name for b in arm.data.bones} - before_bones)
    report = {'removed': old, 'made': made}
    if eye:
        report['lid_travel'], report['lid_sign'] = setup_eye_pose(arm, eye, G['eye'])
        log(f"M# lid travel {report['lid_travel']} sign {report['lid_sign']}")
    if maw:
        setup_maw_pose(arm, maw, G['maw'])
    bpy.ops.object.mode_set(mode='OBJECT')
    if weights:
        report.update(build_weights(arm, eye, maw, G, meshes, old, heir, face_before, snap, made, log))
        if eye:
            ring = lid_post_step(arm, eye, log)
            made = sorted(set(made) | set(ring))
            report['made'] = made
    else:
        for o in meshes:                       # still move the removed bones' weights to their heirs
            merge_groups(o, {k: v for k, v in heir.items() if rn.side_of(k) != 'R'})
    report['placed'] = len(place_collections(arm, eye, maw, made))
    if maw:
        drop_flag_props(arm, maw)          # sliders of extras turned off, left on kept bones (the jaw) by an earlier build
        steps = [(smile_cheeks, wants(maw, 'smile_cheeks')), (maw_features, wants(maw, 'zipper') or wants(maw, 'mouth_sliders')),
                 (tongue_rig, wants(maw, 'tongue_rig')), (muzzle_features, wants(maw, 'snout'))]
        for step, on in steps:
            made = sorted(set(made) | set(step(arm, maw, log) if on else ()))
    if eye:
        socket_controls(arm, eye)
        made = sorted(set(made) | set(lid_tweaks(arm, eye) if wants(eye, 'lid_tweaks') else ()))
        lid_extras(arm, eye, log)
        brow_tweak_controls(arm, eye)
        made = sorted(set(made) | set(look_module().build(arm, eye, log) if wants(eye, 'look') else ()))
        fix_eye_controls(arm, eye, G['eye'], log)
    reparented = {n: p for n, p in parents_before.items() if n in A.bones and n not in made
                  and (A.bones[n].parent.name if A.bones[n].parent else '') != p}
    info = built_info(arm)
    info['made'] = sorted(set(info.get('made', [])) | set(made))
    info['reparented'] = dict(reparented, **info.get('reparented', {}))
    info['heir'] = {**info.get('heir', {}), **{n: (A.bones[n].parent.name if A.bones[n].parent and A.bones[n].parent.name not in made else head) for n in made}}
    A['face_rig_built'] = json.dumps(info)
    for c in cfgs:
        A['face_rig_' + c['kind']] = to_json(c)
    finish_rig(arm)
    bpy.context.view_layer.objects.active = arm
    if start_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='POSE' if start_mode == 'POSE' else 'OBJECT')
    return report


def build_weights(arm, eye, maw, G, meshes, old, heir, face_before, snap, made, log):
    base = eye or maw
    head = base['head']
    src = meshes[0]
    sides = ['L'] if has_mirror(src) else list(SIDES)
    for o in meshes:
        merge_groups(o, {k: v for k, v in heir.items() if rn.side_of(k) != 'R'})
    FREE = free_groups(src, arm, head) | {rn.flip(n) for n in new_deform(arm, head)} | new_deform(arm, head) | face_before
    touched = set()
    for side in sides:
        # a full (unmirrored) skin: the right side's loops are found on the right half
        if eye:
            g = G['eye'][side] if side == 'L' or not eye['mirror'] else eye_geometry(arm, src, eye, side)
            if g['eye_ring']:
                touched |= weight_lids(src, arm, eye, g, FREE)
            if eye['brows'] and rn.with_side(BROW_SEGS[0], side) in made:
                touched |= weight_brows(src, arm, eye, {'side': side}, FREE)
        if maw:
            g = G['maw'][side] if side == 'L' or not maw['mirror'] else maw_geometry(arm, src, maw, side)
            if g['lip_up'] and g['lip_lo']:
                touched |= weight_lips(src, arm, maw, g, FREE)
    if has_mirror(src):
        cw.symmetrize_center(src, touched, groups=FREE | free_groups(src, arm, head))
    headv = sorted({i for i, w in enumerate(snapshot(src)) if any(n in FREE for n in w)} | touched)
    out = {}
    for o in meshes[1:]:
        miss = copy_head(src, o, headv)
        if miss:                                # not the same head: weights from the skin's surface
            cw.transfer_from_surface(src, o, headv and [v.index for v in o.data.vertices], FREE | set(old))
        out[f'head copied to {o.name}'] = (len(headv), miss)
        log(f'M# head copied to {o.name}: {len(headv)} verts, unmatched {miss}')
    gl = G['eye']['L'] if eye else {}
    cfg_parts = dict(eye or maw)
    cfg_parts['skin_parts'] = sorted(set((eye or {}).get('skin_parts', [])) | set((maw or {}).get('skin_parts', [])))
    out['parts'] = weight_parts(src, arm, cfg_parts, gl, FREE, touched, old) if src else {}
    log('M# parts re-weighted', out['parts'])
    done = {o.name for o in meshes} | set(cfg_parts['skin_parts']) | {(eye or {}).get('lash_mesh', '')}
    for o in bpy.data.objects:     # stray old-bone weights on other meshes (a mane, a collar) follow the heir
        if o.type == 'MESH' and o.name not in done and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers) \
                and any(v.groups for v in o.data.vertices) and used_groups(o) & set(old):
            merge_groups(o, {k: v for k, v in heir.items() if rn.side_of(k) != 'R'})
            out.setdefault('old weights moved to heirs', []).append(o.name)
    out['old groups left'] = drop_groups(old)
    for o in bpy.data.objects:      # the Mirror modifier needs both sides' groups to mirror the weights
        if o.type == 'MESH' and has_mirror(o) and any(m.type == 'MIRROR' and m.use_mirror_vertex_groups for m in o.modifiers) \
                and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers):
            cw.ensure_mirror_groups(o, only=new_deform(arm, head) | {n for n in o.vertex_groups.keys() if part_of(n) == 'EyebrowSeg'})
    for o in meshes:
        free = FREE | free_groups(o, arm, head)          # incl. groups this build made (new brows)
        nonface = lambda w: {n: x for n, x in w.items() if n not in free and n not in old}
        a, b = snapshot(o), snap[o.name]
        out[f'{o.name} non-face changed'] = sum(nonface(x) != nonface(y) for x, y in zip(a, b))
    skip = {o.name for o in meshes} | set(cfg_parts['skin_parts']) | {(eye or {}).get('lash_mesh', '')}
    out['other meshes changed'] = [n for n, s_ in snap.items() if n not in skip and n in bpy.data.objects
                                   and snapshot(bpy.data.objects[n]) != s_]
    return out


def lid_post_step(arm, cfg, log=print):
    """Ring lids: lid_bbone_ring after the pivot lids are built and weighted. Returns the bones it made.
    Pivots: nothing to do."""
    if cfg['lid_mode'] == 'PIVOTS':
        return []
    return ring_module().build(arm, cfg=cfg, reach=cfg['ring_reach'], sharp_corners=cfg['sharp_corners'], log=log)


def look_module():
    """look_rig (the eyes' look target; generated copy next to this file)."""
    try:
        from . import look_rig as look
    except ImportError:
        import look_rig as look
    return look


def ring_module(cfg=None):
    """lid_bbone_ring (Ring lids; generated copy next to this file)."""
    try:
        from . import lid_bbone_ring as ring
    except ImportError:
        import lid_bbone_ring as ring
    return ring


def remove(arm, log=print):
    """Take the built face rig out: built bones and their drivers go, weights of built deform bones go to the
    bone they hung on, reused bones (eye, brow nodes) get their old parents back."""
    standardise_face(arm)
    if any(is_lid_ring(b.name) for b in arm.data.bones):     # ring lids: back to pivot lids first
        ring_module().remove(arm, stored(arm, 'eye'), log=log)
    info = built_info(arm)
    made = [n for n in info.get('made', []) if n in arm.data.bones]
    made += [b.name for b in arm.data.bones if is_lid_ring(b.name) and b.name not in made]   # ring lids
    if not made:
        return []
    look_module().remove(arm, made)        # kept bones (the eyes, the Head) stop aiming at bones that go
    heir = {}
    for n in made:
        b = arm.data.bones[n]
        if b.use_deform:
            p = b.parent
            while p and (p.name in made or not p.use_deform):
                p = p.parent
            fallback = info.get('heir', {}).get(n)
            if p is None and part_of(n).startswith('LowerLip'):
                cfg = json.loads(arm.data.get('face_rig_maw', '{}'))
                fallback = cfg.get('lower_parent') or cfg.get('jaw') or fallback
            heir[n] = p.name if p else (fallback if fallback not in made else None) or 'Head'
    merge_away(heir)
    bpy.context.view_layer.objects.active = arm
    mode = arm.mode
    bpy.ops.object.mode_set(mode='EDIT')
    E = arm.data.edit_bones
    for n, p in info.get('reparented', {}).items():
        if n in E and n not in made:
            E[n].parent = E[p] if p in E and p not in made else None
    for n in made:
        if n in E:
            E.remove(E[n])
    bpy.ops.object.mode_set(mode='OBJECT')
    drop_dead_drivers(arm)
    for k in ('face_rig_built', 'face_rig_eye', 'face_rig_maw'):
        if k in arm.data:
            del arm.data[k]
    if mode == 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    log(f'M# removed {len(made)} bones')
    return made


def merge_away(heir):
    """Every mesh: the weights of the gone bones in `heir` ({bone: heir}) onto their heirs, then their groups go."""
    for o in bpy.data.objects:
        if o.type == 'MESH' and any(g.name in heir for g in o.vertex_groups):
            merge_groups(o, {k: v for k, v in heir.items() if rn.side_of(k) != 'R' or not has_mirror(o)})
            for n in heir:
                vg = o.vertex_groups.get(n)
                if vg:
                    o.vertex_groups.remove(vg)


def stored(arm, kind):
    text = arm.data.get('face_rig_' + kind)
    return from_json(text) if text else None


def deform_bones(arm):
    return {b.name for b in arm.data.bones if b.use_deform}


def restore_weights(saved):
    """Every vertex back on the groups and weights of `saved` ({mesh name: snapshot()}), groups made as needed."""
    for name, weights in saved.items():
        o = bpy.data.objects[name]
        for g in o.vertex_groups:
            g.remove(range(len(o.data.vertices)))
        for i, w in enumerate(weights):
            for group, value in w.items():
                (o.vertex_groups.get(group) or o.vertex_groups.new(name=group)).add([i], value, 'REPLACE')


def rebuild(arm, eye=None, maw=None, log=print, keep_weights=True):
    """Remove + build again (from the given configs, else the stored ones), keeping the pose and the user's bone sorting.
    keep_weights: the skin weights come back exactly as they were, painted ones too, as long as the same bones deform,
    or fewer (an extra turned off): the weights of the bones that went then merge into their heirs; off, or when new
    bones deform: built fresh along the lid and lip loops."""
    standardise_face(arm)
    if 'face_rig_built' not in arm.data and has_built(arm):
        recover_record(arm)
    eye = eye or stored(arm, 'eye')
    maw = maw or stored(arm, 'maw')
    saved = control_pose(arm, arm.pose.bones.keys())    # build resets every bone: the pose on the body comes back too
    homes = bone_homes(arm, built_info(arm).get('made', []))
    weights = {o.name: snapshot(o) for o in rig_meshes(arm)} if keep_weights else None
    deform, tree = deform_bones(arm), bone_tree(arm)
    remove(arm, log)
    for c in (eye, maw):            # the old bones are gone already: nothing more to replace
        if c:
            c['replace'] = []
    report = build(arm, eye, maw, log)
    restore_pose(arm, saved)
    restore_homes(arm, homes)
    now = deform_bones(arm)
    if weights and now <= deform:      # a new lid mode deforms with other bones: its fresh weights stay
        restore_weights(weights)
        merge_away(deform_heir(arm, deform - now, (eye or maw)['head'], tree))
    return report


# ---------------------------------------------------------------- guides (the asset form) + auto placement
GUIDE_COLORS = {'upper': UPPER_COLOR, 'lower': LOWER_COLOR}


def guide_part(name):
    n = rn.guide_base(name)[0]
    if n.startswith(('LidUpper', 'LipUpper', 'Brow')) or n in ('LipUpper',):
        return 'upper'
    if n.startswith(('LidLower', 'LipLower', 'Jaw')):
        return 'lower'
    return None


DEFAULT_GUIDES = {   # Digit's guides (a head about 1.4 m up, facing -Y, left side +X)
    'eye': {'Eye': (0.0496, -0.0357, 1.3586), 'EyeAim': (0.0496, -0.0648, 1.3586), 'LidInner': (0.0199, -0.0846, 1.359),
            'LidUpper1': (0.028, -0.0851, 1.3803), 'LidUpper2': (0.0496, -0.083, 1.3871), 'LidUpper3': (0.071, -0.079, 1.38),
            'LidOuter': (0.0825, -0.0773, 1.3591), 'LidLower3': (0.0693, -0.0799, 1.3396), 'LidLower2': (0.0504, -0.0826, 1.337),
            'LidLower1': (0.0321, -0.0846, 1.3417), 'Brow1': (0.0078, -0.0763, 1.394), 'Brow2': (0.0323, -0.0763, 1.4068),
            'Brow3': (0.0669, -0.0712, 1.4059), 'Brow4': (0.0909, -0.0628, 1.3915)},
    'maw': {'LipUpper': (0.0, -0.1717, 1.2737), 'LipUpperMid': (0.0544, -0.1298, 1.2542), 'MouthCorner': (0.0833, -0.0532, 1.2575),
            'LipLower': (0.0, -0.1608, 1.2567), 'LipLowerMid': (0.0547, -0.1189, 1.2554),
            'Jaw': (0.0, -0.0353, 1.2577), 'JawTip': (0.0, -0.1067, 1.2577)},
}


def make_guides(kind, mirror_on=True, collection=None, name=None):
    """The guide armature ('Eye Rig Guides' / 'Anthro Mouth Rig Guides') with default positions, sphere shapes,
    upper/lower colours, bone collection 'Guides', in a collection 'Eye Rig' / 'Anthro Mouth Rig' (made if not given)
    holding the control shapes too. The asset builder and the add-on's fallback both use this."""
    title = TITLES[kind]
    coll = collection or bpy.data.collections.new(title)
    arm_data = bpy.data.armatures.new((name or title) + ' Guides')
    ob = bpy.data.objects.new((name or title) + ' Guides', arm_data)
    coll.objects.link(ob)
    ob['face_rig_kind'] = kind
    ob.show_in_front = True
    arm_data.display_type = 'STICK'
    pts = {k: Vector(v) for k, v in DEFAULT_GUIDES[kind].items()}
    names = [n for n in (EYE_GUIDES if kind == 'eye' else MAW_GUIDES)]
    if not mirror_on:
        names += [rn.guide_name(n, 'R') for n in names if n not in CENTRE_GUIDES and n != 'Eye'] + ([rn.guide_name('Eye', 'R')] if kind == 'eye' else [])
    for w in ('WGT-Guide', 'WGT-Ring', 'SelectionSphere', 'WGT-Ico'):
        ensure_widget(w)                               # control shapes stay unlinked: in no collection, so not in the viewport or outliner
    view = bpy.context.view_layer
    temp = ob.name not in view.objects                 # edit mode needs it in the view layer: link it for now
    if temp:
        bpy.context.scene.collection.children.link(coll)
    prev = view.objects.active
    if prev is not None and prev.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    view.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    gcol = arm_data.collections.new('Guides')
    for n in names:
        base, side = rn.guide_base(n)
        p = pts[base].copy()
        if side == 'R':
            p = mirror(p)
        eb = arm_data.edit_bones.new(n)
        eb.head = p
        if base == 'Eye':
            t = pts['EyeAim'].copy()
            eb.tail = mirror(t) if side == 'R' else t
        elif base == 'Jaw':
            eb.tail = pts['JawTip']
        else:
            eb.tail = p + FWD * 0.004
        gcol.assign(eb)
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in ob.pose.bones:
        part = guide_part(pb.name)
        big = rn.guide_base(pb.name)[0] in ('Eye', 'Jaw')
        shape(pb, 'SelectionSphere' if big else 'WGT-Guide', 0.006 if big else 0.0025)
        if part:
            col = GUIDE_COLORS[part]
            pb.color.palette = 'CUSTOM'
            pb.color.custom.normal = col
            pb.color.custom.select = tuple(min(1.0, c * 0.5 + 0.5) for c in col)
            pb.color.custom.active = (1.0, 1.0, 1.0)
        else:
            pb.color.palette = 'THEME06'
    if prev is not None:
        view.objects.active = prev
    if temp and collection is not None:
        bpy.context.scene.collection.children.unlink(coll)
    return ob


def guides_from_object(guide_ob, arm):
    """{guide name: point in arm space} from a guide armature (bone heads; EyeAim / JawTip = tails)."""
    M = arm.matrix_world.inverted() @ guide_ob.matrix_world
    out = {}
    for b in guide_ob.data.bones:
        out[b.name] = M @ b.head_local
        if rn.guide_base(b.name)[0] == 'Eye':
            out[b.name + 'Aim'] = M @ b.tail_local
        elif b.name == 'Jaw':
            out['JawTip'] = M @ b.tail_local
    return out


def set_guides(guide_ob, arm, points):
    """Move the guide bones to `points` (arm space) and the guide object onto the armature."""
    guide_ob.matrix_world = arm.matrix_world.copy()
    view = bpy.context.view_layer
    prev = view.objects.active
    view.objects.active = guide_ob
    bpy.ops.object.mode_set(mode='EDIT')
    E = guide_ob.data.edit_bones
    for eb in E:
        p = points.get(eb.name)
        base, side = rn.guide_base(eb.name)
        if p is None and side == 'R' and base in points:
            p = mirror(points[base])
        if p is None:
            continue
        d = eb.tail - eb.head
        eb.head = p
        if eb.name in ('Eye', 'Jaw'):
            tip = points.get('EyeAim' if eb.name == 'Eye' else 'JawTip')
            eb.tail = tip if tip is not None else p + d
        elif eb.name == rn.guide_name('Eye', 'R') and 'EyeAim' in points:
            eb.tail = mirror(points['EyeAim'])
        else:
            eb.tail = p + d
    bpy.ops.object.mode_set(mode='OBJECT')
    view.objects.active = prev


FACE_WORDS = {
    'eye': re.compile(r'^(?!.*(iris|pupil|puipl|lid|brow|lash|socket|look|focus|target|track|cheek|b\d)).*eye', re.I),
    'jaw': re.compile(r'jaw|(muzzle|snout|mouth).?lower|lower.?(muzzle|snout)', re.I),
    'upper_jaw': re.compile(r'^(muzzle|snout)\d?$|(jaw|muzzle|snout).?upper|upper.?(jaw|muzzle|snout)', re.I),
    'head': re.compile(r'^head$', re.I),
    'lid_up': re.compile(r'(upper.?(eye|lid)|(eye|lid).?upper)', re.I),
    'lid_lo': re.compile(r'(lower.?(eye|lid)|(eye|lid).?lower)', re.I),
    'lip_up': re.compile(r'(upper.?lip|lip.?upper)', re.I),
    'lip_lo': re.compile(r'(lower.?lip|lip.?lower)', re.I),
    'brow': re.compile(r'brow(?!.*b\d)', re.I),
    'lid_ring': re.compile(r'eye_?\d+([._][LlRr])?$', re.I),        # numbered lid ring bones (LeftEye1-8)
    'lip_any': re.compile(r'lip|mouth', re.I),
}


def is_left(name):
    return rn.side_of(name) == 'L'


def is_right(name):
    return rn.side_of(name) == 'R'


def guess_bones(arm):
    """Head, left eye, jaw and upper jaw / snout bone names from the rig (by name), or ''."""
    B = arm.data.bones
    head = next((b.name for b in B if FACE_WORDS['head'].match(b.name)), '')
    eyes = [b.name for b in B if FACE_WORDS['eye'].search(b.name) and is_left(b.name) and b.use_deform]
    eyes = eyes or [b.name for b in B if FACE_WORDS['eye'].search(b.name) and is_left(b.name)]
    eye = min(eyes, key=len) if eyes else ''
    uppers = [b.name for b in B if FACE_WORDS['upper_jaw'].search(b.name) and not is_right(b.name) and not is_left(b.name)]
    jaws = [b.name for b in B if FACE_WORDS['jaw'].search(b.name) and b.name not in uppers]
    lowered = [j for j in jaws if re.search(r'lower|1$', j, re.I)] or jaws
    jaw = min(lowered, key=lambda n: (B[n].parent is not None and B[n].parent.name in jaws, len(n))) if lowered else ''
    upper = min(uppers, key=len) if uppers else ''
    return {'head': head, 'eye_bone': eye, 'jaw': jaw, 'upper_jaw': upper}


def nearest_surface(obj, arm, p):
    """Nearest point of obj's rest surface to p (arm space)."""
    M = arm_matrix(arm, obj)
    bvh = BVHTree.FromPolygons([M @ v.co for v in obj.data.vertices], [tuple(q.vertices) for q in obj.data.polygons])
    hit = bvh.find_nearest(p)
    return hit[0] if hit[0] is not None else p


EYEBALL_NAME = re.compile(r'eye(?!.*(brow|lash|lid))', re.I)


def eyeball_centre(arm, meshes):
    """(centre, radius) of the left eyeball: the eye-named mesh's loose part on +X nearest the eye height."""
    for o in meshes:
        if not EYEBALL_NAME.search(o.name) or o.type != 'MESH':
            continue
        if not (o.parent == arm or any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)):
            continue                          # widget meshes (Bone_Control_Eyelook) aren't eyeballs
        M = arm_matrix(arm, o)
        bm = bmesh.new(); bm.from_mesh(o.data); bm.verts.ensure_lookup_table()
        lab, sizes = cw.components(bm, set())
        bm.free()
        parts = defaultdict(list)
        for i, c in lab.items():
            parts[c].append(M @ o.data.vertices[i].co)
        best = None
        for pts in parts.values():
            c = sum(pts, Vector()) / len(pts)
            if c.x <= 0:
                continue
            r = max((p - c).length for p in pts)
            if best is None or r > best[1]:
                best = (c, r)
        if best:
            return best
    return None


def eye_opening(arm, skin, head):
    """(eyeball centre, radius, rim points) of the left eye opening when the skin has no eyeball: the biggest hole
    (boundary edge loop) on +X near the head bone, the eyeball centre set back from the hole's middle towards the
    head's axis by its radius. None when there is no such hole (or no head bone)."""
    if head is None:
        return None
    M = arm_matrix(arm, skin)
    a, b = head.head_local, head.tail_local
    reach = 1.5 * max(head.length, 1e-6)
    bm = bmesh.new()
    bm.from_mesh(skin.data)
    rim = {v.index for e in bm.edges if e.is_boundary for v in e.verts}
    lab, best = {}, None
    bm.verts.ensure_lookup_table()
    for start in rim:
        if start in lab:
            continue
        loop, todo = [start], [start]
        lab[start] = True
        while todo:
            v = bm.verts[todo.pop()]
            for e in v.link_edges:
                w = e.other_vert(v).index
                if e.is_boundary and w not in lab:
                    lab[w] = True
                    loop.append(w)
                    todo.append(w)
        pts = [M @ skin.data.vertices[i].co for i in loop]
        mid = sum(pts, Vector()) / len(pts)
        r = sum((p - mid).length for p in pts) / len(pts)
        on_axis = intersect_point_line(mid, a, b)[0]
        if len(pts) < 5 or mid.x < 0.1 * r or r > 0.5 * reach or (mid - on_axis).length > reach:
            continue
        if best is None or r > best[1]:
            inward = Vector((0, on_axis.y, on_axis.z)) - mid
            best = (mid + inward.normalized() * r, r, pts)
    bm.free()
    return best


def ring_from_points(pts, c):
    """8 ring guide points (inner, upper 1-3, outer, lower 3-1) from points round an eye centre (front view)."""
    ang = lambda p: math.atan2(p.z - c.z, p.x - c.x)
    srt = sorted(pts, key=ang)
    out = {}
    for name, deg in zip(RING_GUIDES, (180, 135, 90, 45, 0, -45, -90, -135)):
        a = math.radians(deg)
        out[name] = ring_at_angle(srt, c, a if a <= math.pi else a - 2 * math.pi)
    return out


# Faces without a mesh (a bare rig): guides on the rig's own head, so they scale with it. Lengths are the base bone's.
FIGURE_EYE = dict(centre=(0.145, -0.34, 0.54), radius=0.055, opening=(0.065, 0.035))   # from the Head's head
FIGURE_MOUTHS = {   # base bone (guess_bones key), its end the lips start from, lip middle from there, corner (x, back)
    'human': ('head', 'head', (0.0, -0.5, 0.3), (0.11, 0.09)),           # a flat mouth on the face front
    'snout': ('upper_jaw', 'tail', (0.0, 0.12, -0.2), (0.25, 0.82)),     # lips under the snout, the corners far back
}
FIGURE_LIP_MID = (0.6, 0.25)      # a lip's middle guide: share of the corner's x and of its way back
FIGURE_LIP_GAP = 0.012            # the lower lip guides sit this far below the upper ones


def figure_eye(arm, head):
    """(eye centre, aim, radius, {ring guide: point}) on the Head bone of a rig without a skin mesh."""
    bone = arm.data.bones[head]
    length = bone.length
    centre = bone.head_local + Vector(FIGURE_EYE['centre']) * length
    radius = FIGURE_EYE['radius'] * length
    half_w, half_h = (k * length for k in FIGURE_EYE['opening'])
    ring = {}
    for name, deg in zip(RING_GUIDES, (180, 135, 90, 45, 0, -45, -90, -135)):
        x, z = half_w * math.cos(math.radians(deg)), half_h * math.sin(math.radians(deg))
        front = math.sqrt(max(radius ** 2 - x ** 2 - z ** 2, 0.0)) + 0.1 * radius
        ring[name] = centre + Vector((x, -front, z))
    return centre, centre + FWD * radius, radius, ring


def figure_mouth(arm, bones):
    """Lip and mouth corner guides of a rig without a skin mesh: under the snout bone when it has one, else a flat
    human mouth on the Head's front."""
    shape = 'snout' if arm.data.bones.get(bones.get('upper_jaw') or '') else 'human'
    key, end, lip, corner = FIGURE_MOUTHS[shape]
    bone = arm.data.bones[bones[key]]
    length = bone.length
    start = bone.tail_local if end == 'tail' else bone.head_local
    upper = Vector((0.0, start.y, start.z)) + Vector(lip) * length
    corner = Vector((corner[0] * length, upper.y + corner[1] * length, upper.z))
    mid = Vector((FIGURE_LIP_MID[0] * corner.x, upper.y + FIGURE_LIP_MID[1] * (corner.y - upper.y), upper.z))
    gap = Vector((0, 0, FIGURE_LIP_GAP * length))
    return {'LipUpper': upper, 'LipLower': upper - gap, 'LipUpperMid': mid, 'LipLowerMid': mid - gap, 'MouthCorner': corner}


def auto_guides(arm, kind, meshes, bones=None):
    """Best-guess guide points (arm space) for a character: from its old face bones (lid / lip / brow
    controls found by name) when it has them, else from the eye bone / eyeball mesh and the skin, else (no skin: a
    bare rig) from the rig's head (figure_eye, figure_mouth)."""
    B = arm.data.bones
    bones = bones or guess_bones(arm)
    skin = next((bpy.data.objects[n] for n in meshes if n in bpy.data.objects), None)
    pts = {}
    left = [b for b in B if is_left(b.name)]
    figure = skin is None and bones.get('head') in B
    if kind == 'eye':
        eb = B.get(bones.get('eye_bone') or '')
        # a bare rig skips the eyeball search: it would find another character's eyes in the scene
        ball = None if figure else eyeball_centre(arm, [o for o in bpy.data.objects if o.type == 'MESH'])
        hole = eye_opening(arm, skin, B.get(bones.get('head') or '')) if not (eb or ball) and skin is not None else None
        ring, r = None, 0.015
        if eb:
            c, aim = eb.head_local.copy(), eb.tail_local.copy()
        elif ball:
            c = ball[0]; aim = c + FWD * ball[1]
        elif hole:
            c = hole[0]; aim = c + FWD * hole[1]
        elif figure:
            c, aim, r, ring = figure_eye(arm, bones['head'])
        else:
            c, aim = Vector(DEFAULT_GUIDES['eye']['Eye']), Vector(DEFAULT_GUIDES['eye']['EyeAim'])
        r = ball[1] if ball else hole[1] if hole else r
        pts['Eye'], pts['EyeAim'] = c, aim
        named = [b.head_local.copy() for b in left if (FACE_WORDS['lid_up'].search(b.name) or FACE_WORDS['lid_lo'].search(b.name))
                 and not b.use_deform and (b.head_local - c).length < 4 * r]
        numbered = [b.head_local.copy() for b in left if FACE_WORDS['lid_ring'].search(b.name)      # LeftEye1-8
                    and b.name != bones.get('eye_bone') and (b.head_local - c).length < 4 * r]
        around = lambda ps: len({round(math.degrees(math.atan2(p.z - c.z, p.x - c.x)) / 45) % 8 for p in ps})
        lid = max((named, numbered), key=around)          # the set that goes round the eye (not one lid only)
        if around(lid) < 5:
            lid = []
        if len(lid) < 4 and hole:                    # the eye opening's rim is the lid edge
            lid = hole[2]
        if len(lid) < 4 and skin is not None:        # skin points just in front of the eyeball, frontmost per angle
            M = arm_matrix(arm, skin)
            near = [M @ v.co for v in skin.data.vertices]
            near = [p for p in near if p.x > 0 and (p - c).length < 1.25 * r and p.y < c.y]
            bins = {}
            for p in near:
                k = round(math.degrees(math.atan2(p.z - c.z, p.x - c.x)) / 15)
                if k not in bins or p.y < bins[k].y:
                    bins[k] = p
            lid = list(bins.values())
        if len(lid) < 4 and ring:
            pts.update(ring)
        elif len(lid) >= 4:
            pts.update(ring_from_points(lid, c))
        else:
            for n, p in DEFAULT_GUIDES['eye'].items():
                pts.setdefault(n, c + (Vector(p) - Vector(DEFAULT_GUIDES['eye']['Eye'])) * (r / 0.015))
        brow = sorted([b for b in left if part_of(b.name) == 'Eyebrow'],
                      key=lambda b: abs(b.head_local.x))
        if len(brow) >= 2:
            bp = [b.head_local.copy() for b in brow]
            for n, p in zip(BROW_GUIDES, resample(bp, [0, 1 / 3, 2 / 3, 1]) if len(bp) != 4 else bp):
                pts[n] = p
        else:
            top = max(pts[n].z for n in RING_GUIDES)
            w = pts['LidOuter'].x - pts['LidInner'].x
            for k, n in enumerate(BROW_GUIDES):
                x = pts['LidInner'].x - 0.1 * w + k * 1.2 * w / 3
                p = Vector((x, pts['LidUpper2'].y, top + 0.35 * w - 0.08 * w * abs(k - 1.5)))
                pts[n] = nearest_surface(skin, arm, p) if skin else p
    else:
        jaw = B.get(bones.get('jaw') or '')
        def lip_points(word):     # the old lip line's bones, and its control nodes (not its deforming segments)
            bs = [b for b in B if FACE_WORDS[word].search(b.name) and not is_right(b.name)]
            nodes = [b for b in bs if not b.use_deform]
            pts = lambda bones: sorted([b.head_local.copy() for b in bones], key=lambda p: p.x)
            return pts(bs), pts(nodes if len(nodes) >= 2 else bs)
        (all_u, ups), (all_l, los) = lip_points('lip_up'), lip_points('lip_lo')
        if len(ups) >= 2 and len(los) >= 2:
            cu = min(all_u, key=lambda p: (round(abs(p.x), 3), p not in ups))   # centre: the bone on the mirror plane
            cl = min(all_l, key=lambda p: (round(abs(p.x), 3), p not in los))   # (a node when there are several)
            corner = max(all_u + all_l, key=lambda p: p.x)
            ups = [p for p in ups if p.x < corner.x - 1e-6]
            los = [p for p in los if p.x < corner.x - 1e-6]
            line_u = ups + [corner]; line_l = los + [corner]
            pts['LipUpper'], pts['LipLower'] = Vector((0, cu.y, cu.z)), Vector((0, cl.y, cl.z))
            pts['LipUpperMid'], pts['LipLowerMid'] = resample(line_u, [0.5])[0], resample(line_l, [0.5])[0]
            pts['MouthCorner'] = corner
        elif figure:
            pts.update(figure_mouth(arm, bones))
        else:
            zj = jaw.head_local.z if jaw else Vector(DEFAULT_GUIDES['maw']['LipUpper']).z
            p = Vector((0, -10, zj))
            if skin is not None:
                M = arm_matrix(arm, skin)
                bvh = BVHTree.FromPolygons([M @ v.co for v in skin.data.vertices], [tuple(q.vertices) for q in skin.data.polygons])
                hit = bvh.ray_cast(Vector((1e-3, -10, zj)), Vector((0, 1, 0)))   # just off the mirror seam
                if hit[0] is not None:
                    p = hit[0]; p.x = 0.0
            if p.y < -5:
                p = Vector(DEFAULT_GUIDES['maw']['LipUpper'])
            eye_x = 0.03
            if B.get(bones.get('eye_bone') or ''):
                eye_x = abs(B[bones['eye_bone']].head_local.x)
            corner = Vector((0.75 * eye_x, p.y + 0.4 * eye_x, p.z))
            pts['LipUpper'], pts['LipLower'] = p + Vector((0, 0, 0.0025)), p - Vector((0, 0, 0.0025))
            pts['MouthCorner'] = nearest_surface(skin, arm, corner) if skin else corner
            for n, a, b in (('LipUpperMid', 'LipUpper', 'MouthCorner'), ('LipLowerMid', 'LipLower', 'MouthCorner')):
                m = (pts[a] + pts[b]) / 2
                pts[n] = nearest_surface(skin, arm, m) if skin else m
        if skin is not None:              # the lip edges read off the mesh's mouth opening (old bones sit between lips)
            eb = B.get(bones.get('eye_bone') or '')
            reach = max(0.5 * abs(pts['MouthCorner'].x), 0.6 * abs(eb.head_local.x) if eb else 0.0)
            found = mouth_guides(skin, arm, (pts['LipUpper'] + pts['LipLower']) / 2, reach,
                                 pts['MouthCorner'] if len(ups) >= 2 and len(los) >= 2 else None)
            pts.update(found)
        if jaw:
            pts['Jaw'], pts['JawTip'] = jaw.head_local.copy(), jaw.tail_local.copy()
        else:
            m = pts['LipLower']
            pts['Jaw'], pts['JawTip'] = m + Vector((0, 0.08, 0.02)), m + Vector((0, 0.005, -0.02))
    return pts


def lip_walk(bm, v):
    """The quad edge loop from a mirror-plane vertex v off the plane, to where it ends: back on the plane (a
    mouth opening that is one loop) or at a pole (a mouth corner)."""
    e = next((x for x in v.link_edges if abs(x.other_vert(v).co.x) > 1e-4), None)
    if e is None:
        return [v]
    loop, w = [v], e.other_vert(v)
    for _ in range(400):
        loop.append(w)
        if abs(w.co.x) < 1e-4 or len(w.link_edges) != 4:
            break
        f = set(e.link_faces)
        nx = [x for x in w.link_edges if x != e and not (set(x.link_faces) & f)]
        if len(nx) != 1:
            break
        e = nx[0]; w = e.other_vert(w)
    return loop


def mouth_rims(bm, M, near, reach):
    """(upper rim, lower rim) vertices of the mouth on the mirror plane: along the face's centre profile the
    upper lip's lowest point and the lower lip's highest point, where the profile turns into the mouth (the
    profile runs back from both, into the mouth; of such pairs the closest together and to `near`). Lips that overlap (an upper lip hanging in front) are fine.
    M: mesh -> armature space; near: a guess of the mouth centre (armature space). None if not found."""
    P = lambda v: M @ v.co
    plane = {v for v in bm.verts if abs(v.co.x) < 1e-4}
    nb = {v: [e.other_vert(v) for e in v.link_edges if e.other_vert(v) in plane] for v in plane}
    def extreme(v, sign):                   # a local z min (sign 1) / max (-1) of the profile, plateaus too
        dz = [sign * (P(w).z - P(v).z) for w in nb[v]]
        return len(dz) == 2 and min(dz) > -2e-4 and max(dz) > 2e-4 and (P(v) - near).length < reach

    def goes_in(v, steps=12):               # how far back (+Y) the profile runs from v the inner way, and its path
        best, prev, cur, seen = 0.0, None, v, set()
        nxt = max(nb[v], key=lambda w: P(w).y)
        for _ in range(steps):
            prev, cur = cur, nxt
            seen.add(cur)
            best = max(best, P(cur).y - P(v).y)
            ahead = [w for w in nb[cur] if w != prev]
            if not ahead:
                break
            nxt = ahead[0]
        return best, seen
    inward = {}
    lows = [v for v in plane if extreme(v, 1)]
    highs = [v for v in plane if extreme(v, -1)]
    best = None
    for u in lows:
        for l in highs:
            gap = (P(u) - P(l)).length
            score = gap + ((P(u) + P(l)) / 2 - near).length      # close together, near the guess
            if best is not None and score >= best[0]:
                continue
            for v in (u, l):
                if v not in inward:
                    inward[v] = goes_in(v)
            (du, su), (dl, sl) = inward[u], inward[l]
            if min(du, dl) > max(gap, 0.2 * reach) and l not in su and u not in sl:   # not both on one lip's inside
                best = (score, u, l)
    return best[1:] if best else None


def mouth_guides(skin, arm, near, reach, corner=None):
    """Lip guides from the skin's mouth opening (mouth_rims), {} if there is none near `near`: LipUpper /
    LipLower on the rims, the corner where the rims' edge loops end (or `corner`, e.g. from old lip bones,
    snapped to the loops), the Mid guides half way along each lip."""
    M = arm_matrix(arm, skin)
    bm = bmesh.new(); bm.from_mesh(skin.data); bm.verts.ensure_lookup_table()
    try:
        rims = mouth_rims(bm, M, near, reach)
        if not rims:
            return {}
        lines = [[M @ v.co for v in lip_walk(bm, r)] for r in rims]
        out = {'LipUpper': lines[0][0].copy(), 'LipLower': lines[1][0].copy()}
        out['LipUpper'].x = out['LipLower'].x = 0.0
        if corner is not None and any(min((p - corner).length for p in line) > 0.25 * abs(corner.x) for line in lines):
            return out                        # the rims' loops wander off (poles): only the centres from the mesh
        if corner is None:
            u, l = lines
            if abs(u[-1].x) < 1e-4 and len(u) > 2:      # one loop round the opening: its turning point
                mid = (u[0] + u[-1]) / 2
                corner = max(u, key=lambda p: (p - mid).length)
            else:
                corner = (u[-1] + l[-1]) / 2
        for key, line in zip(('LipUpperMid', 'LipLowerMid'), lines):
            k = min(range(len(line)), key=lambda j: (line[j] - corner).length)
            out[key] = resample(line[:k + 1], [0.5])[0] if k > 0 else (line[0] + corner) / 2
        ends = [min(line, key=lambda p: (p - corner).length) for line in lines]
        out['MouthCorner'] = (ends[0] + ends[1]) / 2
        return out
    finally:
        bm.free()


def detect_replace(arm, cfg, body=None):
    """Prefixes (Left/Right stripped) of old face bones sitting on the lid ring / lip lines (and their children):
    the bones the new rig replaces."""
    s = cfg['size']
    G = cfg['guides']
    lines = []
    if cfg['kind'] == 'eye':
        lines.append((smooth_polyline([G[n] for n in RING_GUIDES], True), True))
    else:
        lines.append((smooth_polyline([G[n] for n in ('LipUpper', 'LipUpperMid', 'MouthCorner')], False), False))
        lines.append((smooth_polyline([G[n] for n in ('LipLower', 'LipLowerMid', 'MouthCorner')], False), False))
    keep = {cfg['head'], cfg.get('eye_bone', ''), cfg.get('jaw', ''), cfg.get('upper_parent', ''), cfg.get('lower_parent', '')}
    built = set(built_info(arm).get('made', []))
    hit = set()
    for b in arm.data.bones:
        if b.name in keep or b.name in built or not is_left(b.name) and abs(b.head_local.x) > 1e-4:
            continue
        if re.search(r'brow|cheek|teeth|tongue|tounge|nose', b.name, re.I):
            continue
        d = min(cw.loop_distance(b.head_local, pts, closed) for pts, closed in lines)
        words = ('lid_up', 'lid_lo', 'lid_ring') if cfg['kind'] == 'eye' else ('lip_up', 'lip_lo', 'lip_any')
        named = any(FACE_WORDS[w].search(b.name) for w in words) and d < 0.03 * s
        if d < 0.004 * s or named:
            hit.add(b.name)
    for b in arm.data.bones:                   # their children (segment bones) too
        if b.parent and b.parent.name in hit and b.name not in keep:
            hit.add(b.name)
    return sorted({re.sub(r'(\.\d+)$', '', stem(n)) for n in hit})


def guess_meshes(arm):
    """(skin, [meshes with the same head]) among the meshes the armature deforms: of the big meshes round the
    head bone, the one with the most vertices in front of the eyeball (not a shell that is mostly that: lid /
    brow meshes; else the biggest); the others share its head vertices (two copies of a body)."""
    head = arm.data.bones.get(guess_bones(arm)['head'] or 'Head')
    if head is None:
        return []
    h = head.head_local
    cands = []
    for o in bpy.data.objects:
        if o.type != 'MESH' or not any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers) \
                or EYEBALL_NAME.search(o.name):
            continue
        M = arm_matrix(arm, o)
        near = [M @ v.co for v in o.data.vertices if (M @ v.co - h).length < 0.25]
        if len(near) > 50:
            cands.append((len(near), o, near))
    if not cands:
        return []
    ball = eyeball_centre(arm, [o for o in bpy.data.objects if o.type == 'MESH'])
    if ball:          # the skin wraps the eyeball (hair / manes are big round the head too)
        c, r = ball
        socket = lambda pts: sum(1 for p in pts if (p - c).length < 1.6 * r and p.y < c.y)     # in front of the eye
        shell = lambda c_: socket(c_[2]) > 0.5 * c_[0]          # a lid / lash / brow shell, not the skin
        cands = [c_ for c_ in cands if not shell(c_)] or cands
        cands.sort(key=lambda c_: (-socket(c_[2]), -c_[0]))
    else:
        cands.sort(key=lambda c: -c[0])
    _, skin, pts = cands[0]
    out = [skin.name]
    for _, o, _ in cands[1:]:
        kd = KDTree(len(o.data.vertices))
        M = arm_matrix(arm, o)
        for v in o.data.vertices:
            kd.insert(M @ v.co, v.index)
        kd.balance()
        same = sum(1 for p in pts[::7] if kd.find(p)[2] < 1e-5)
        if same >= 0.95 * len(pts[::7]):
            out.append(o.name)
    return out


def auto_config(arm, kind, meshes=None, **settings):
    """A config for a character from best guesses: bones by name, meshes (+ eyelid shell meshes as skin parts),
    guide points, size, the old face bones to replace. `settings` override any of it."""
    bones = guess_bones(arm)
    meshes = list(meshes) if meshes is not None else guess_meshes(arm)
    guides = auto_guides(arm, kind, meshes, bones)
    eye_guides = guides if kind == 'eye' else auto_guides(arm, 'eye', meshes, bones)
    lids = [o.name for o in bpy.data.objects if o.type == 'MESH' and re.search(r'lid', o.name, re.I)
            and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers) and o.name not in meshes]
    base = dict(head=bones['head'] or 'Head', meshes=meshes, size=auto_size(eye_guides),
                skin_parts=lids)                # separate eyelid shells follow the lids (take the skin's new weights)
    if kind == 'eye':
        base['eye_bone'] = bones['eye_bone'] or rn.left('Eye')
        lash = next((o.name for o in bpy.data.objects if o.type == 'MESH' and re.search(r'lash|liner', o.name, re.I)), '')
        base['lash_mesh'] = lash
    else:
        base['jaw'] = bones['jaw'] or 'Jaw1'
        base['upper_parent'] = bones['upper_jaw']       # the snout / upper jaw carries the upper lip (default head)
    base.update({k: v for k, v in settings.items() if k != 'replace'})
    cfg = config(kind, guides=settings.get('guides', guides), **{k: v for k, v in base.items() if k != 'guides'})
    cfg['replace'] = settings['replace'] if 'replace' in settings else detect_replace(arm, cfg)
    return cfg
