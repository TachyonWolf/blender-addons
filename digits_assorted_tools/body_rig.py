# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/body_rig.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, body: guides for torso, limbs, hands, feet, spine and head, fitting them to the mesh, and building the
body armature (build_body: names from rig_names, base IK/FK limbs that limb_rig.upgrade then completes from limb_table).

Guides are one armature `<Name> Guides`, tagged `full_rig_guides = 'body'` (+ the options it was made with, JSON in
`full_rig_guide_options`). Each guide bone runs from one joint to the next (a metarig), with its standard name
(rig_names.build: `Pelvis`, `Spine1`, `Upperarm.L`, `Index1.L`, `Heel.L`). Only the LEFT side and the centre are made:
the right side is mirrored on Generate (full_points), so the guides can never go out of symmetry. Face guides stay
face_rig_core's own objects; tail / ear guides are root markers only (part_chains lays their chains).

Three sources fill the same joint dict ({joint key: Vector}, guide armature space, +X = left, -Y = front, +Z = up):
template_landmarks (the default figure: plantigrade or digitigrade legs, a human or snout head), fit_joints (ray casts
into the character mesh) and rig_joints (an existing rig, through game_rig's Skeleton). derive() then lays hands and feet out the same way for all three, and
bone_specs turns joints into guide bones. The fitting maths works on a Probe (ray casts) and needs no bpy.
"""
import json
import math
import re
from collections import namedtuple

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

try:                                     # inside the add-on package
    from . import bendy_limbs as bl, bone_collections as BC, face_rig_core as fr, full_rig_spec as spec, game_rig as gr, \
        limb_rig as lr, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import bendy_limbs as bl
    import bone_collections as BC
    import face_rig_core as fr
    import full_rig_spec as spec
    import game_rig as gr
    import limb_rig as lr
    import rig_names as rn

TAG, OPTIONS_PROP = 'full_rig_guides', 'full_rig_guide_options'
FOOT_WIDTH_PROP = 'full_rig_foot_width'  # on the guides: the foot's width Fit measured on the mesh
DEFAULT_HEIGHT = 1.7                     # metres: guides made without a mesh
X, Y, UP, FRONT = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((0, -1, 0))
FINGERS = {4: ('Thumb', 'Index', 'Middle', 'Ring'), 5: ('Thumb', 'Index', 'Middle', 'Ring', 'Pinky')}
TOES = {3: ('BigToe', 'SecondToe', 'LittleToe'),
        4: ('BigToe', 'SecondToe', 'MiddleToe', 'LittleToe'),
        5: ('BigToe', 'SecondToe', 'MiddleToe', 'FourthToe', 'LittleToe')}
FINGER_LENGTH = {'Index': 0.95, 'Middle': 1.0, 'Ring': 0.94, 'Pinky': 0.78}       # of the middle finger
TOE_LENGTH = {'BigToe': 1.0, 'SecondToe': 0.95, 'MiddleToe': 0.88, 'FourthToe': 0.8, 'LittleToe': 0.7}
FINGER_JOINTS, THUMB_JOINTS, TOE_JOINTS = (0.0, 0.48, 0.78), (0.0, 0.38, 0.7), (0.0, 0.55)   # along each digit
PALM = 0.52                              # wrist to knuckles, of wrist to finger tip
FOOT_WIDTH = 0.4                         # foot width, of heel to toe tip, when nothing measured it
TOE_SPREAD = 0.85                        # separate toes' bases span this share of the foot's width
CENTRE_JOINTS = ('pelvis', 'waist', 'chest', 'neck', 'skull', 'top', 'jaw', 'chin', 'snout', 'nose', 'tail', 'tail_tip')


# ---------------------------------------------------------------- options
GUIDE_DEFAULTS = dict(face='HUMAN', leg_type='PLANTIGRADE', fingers=5, toes=5, spine_bones=2, neck_bones=2, tail=False,
                      ears=False)       # neck_bones: a build option (the one Neck guide is split), kept with the guide ones


def resolve(opts=None):
    """Full guide options from a body_rig config (full_rig_spec.config_for(...)['body_rig']) or a partial dict: the
    Face choice's defaults first (snout / tail / ears), then what `opts` sets. The snout always follows the Face."""
    opts = {k: v for k, v in (opts or {}).items() if v is not None}
    if 'template' in opts:                      # older guides and records: the Template meant the Face
        opts.setdefault('face', spec.LEGACY_TEMPLATES.get(opts.pop('template'), 'SNOUT'))
    face = opts.get('face') or GUIDE_DEFAULTS['face']
    out = dict(GUIDE_DEFAULTS, **spec.face_guides(face))
    out.update(opts)
    out['snout'] = out['face'] == 'SNOUT'
    for key in ('fingers', 'toes', 'spine_bones', 'neck_bones'):
        out[key] = int(out[key])
    if out['fingers'] not in (1, 4, 5) or out['toes'] not in spec.TOE_COUNT_VALUES or not 1 <= out['spine_bones'] <= 3 \
            or not 1 <= out['neck_bones'] <= 3 or out['leg_type'] not in ('PLANTIGRADE', 'DIGITIGRADE'):
        raise ValueError(f'bad guide options {out}')
    return out


def guide_options(guides):
    return resolve(json.loads(guides.get(OPTIONS_PROP, '{}')))


def is_guides(ob):
    return ob is not None and ob.type == 'ARMATURE' and ob.get(TAG) == 'body'


def find_guides(name=None):
    """Body guide objects (of one character name)."""
    return [o for o in bpy.data.objects if is_guides(o) and (name is None or o.name == f'{name} Guides')]


# ---------------------------------------------------------------- the guide bones: (name, head joint, tail joint, parent)
def finger_names(count):
    return FINGERS.get(count, ())


def toe_names(count):
    return TOES.get(count, ())


def bone_specs(opts):
    """Every guide bone for the options, parents first: (name, head joint, tail joint, parent). Left side + centre;
    joint keys are plain words ('elbow'), digit joints '<Digit><n>' and '<Digit>Tip'."""
    b = lambda part, number=None: rn.build(part, 'L', number)
    spine = [rn.build('Spine', number=i) for i in range(1, opts['spine_bones'] + 1)]
    joints = ['waist'] + [f'spine{i}' for i in range(1, len(spine))] + ['chest']
    out, parent = [('Pelvis', 'pelvis', 'waist', None)], 'Pelvis'
    for name, a, z in zip(spine, joints, joints[1:]):
        out.append((name, a, z, parent))
        parent = name
    out += [('Chest', 'chest', 'neck', parent), ('Neck', 'neck', 'skull', 'Chest'), ('Head', 'skull', 'top', 'Neck'),
            ('Jaw', 'jaw', 'chin', 'Head')]
    if opts['snout']:
        out.append(('Snout', 'snout', 'nose', 'Head'))
    if opts['ears']:
        out.append((b('Ear'), 'ear', 'ear_tip', 'Head'))
    if opts['tail']:
        out.append(('Tail', 'tail', 'tail_tip', 'Pelvis'))
    out += [(b('Shoulder'), 'clavicle', 'shoulder', 'Chest'), (b('Upperarm'), 'shoulder', 'elbow', b('Shoulder')),
            (b('Forearm'), 'elbow', 'wrist', b('Upperarm')), (b('Hand'), 'wrist', 'knuckles', b('Forearm'))]
    out += digit_specs(finger_names(opts['fingers']), b('Hand'), 'Fingers', 'knuckles', 'fingertips')
    digi = opts['leg_type'] == 'DIGITIGRADE'
    out += [(b('Thigh'), 'hip', 'knee', 'Pelvis'), (b('Shin'), 'knee', 'hock' if digi else 'ankle', b('Thigh'))]
    if digi:
        out.append((b('Hock'), 'hock', 'ankle', b('Shin')))
    out.append((b('Foot'), 'ankle', 'ball', b('Hock') if digi else b('Shin')))
    out += digit_specs(toe_names(opts['toes']), b('Foot'), 'Toes', 'ball', 'toetip')
    out.append((b('Heel'), 'heel', 'heel_tip', b('Foot')))
    return out


def digit_joints(digit, toes=False):
    return THUMB_JOINTS if digit == 'Thumb' else TOE_JOINTS if toes else FINGER_JOINTS


def digit_specs(digits, parent, mitten, base, tip):
    """Finger / toe bones: one mitten bone (`Fingers.L`, `Toes.L`) without digits, else `<Digit>1..n.L` each."""
    if not digits:
        return [(rn.build(mitten, 'L'), base, tip, parent)]
    out = []
    for d in digits:
        keys = [f'{d}{i}' for i in range(1, len(digit_joints(d, mitten == 'Toes')) + 1)] + [f'{d}Tip']
        up = parent
        for i, (a, z) in enumerate(zip(keys, keys[1:]), 1):
            out.append((rn.build(d, 'L', i), a, z, up))
            up = out[-1][0]
    return out


# ---------------------------------------------------------------- template: a default figure, height 1, feet at z 0
# T-pose, left side. Hands and feet as landmarks: derive() lays out the fingers and toes.
TEMPLATE = {
    'pelvis': (0, 0.0, 0.52), 'waist': (0, 0.0, 0.58), 'chest': (0, 0.0, 0.70), 'neck': (0, 0.0, 0.825),
    'skull': (0, 0.0, 0.87), 'top': (0, 0.0, 1.0), 'jaw': (0, -0.02, 0.9), 'chin': (0, -0.07, 0.885),
    'clavicle': (0.02, -0.015, 0.81), 'shoulder': (0.11, 0.0, 0.81), 'elbow': (0.29, 0.01, 0.81),
    'wrist': (0.44, 0.0, 0.81), 'handtip': (0.55, 0.0, 0.81), 'palm_width': 0.05,
    'hip': (0.055, 0.0, 0.51), 'knee': (0.06, -0.01, 0.285), 'ankle': (0.065, 0.015, 0.045),
    'heel': (0.065, 0.035, 0.012), 'toetip': (0.07, -0.105, 0.012), 'foot_width': 0.055,
}
DIGITIGRADE_LEGS = {
    'pelvis': (0, 0.0, 0.5), 'waist': (0, 0.0, 0.56), 'hip': (0.06, 0.0, 0.5), 'knee': (0.06, -0.04, 0.32),
    'hock': (0.06, 0.04, 0.16), 'ankle': (0.06, -0.01, 0.03), 'heel': (0.06, 0.01, 0.012), 'toetip': (0.06, -0.12, 0.012),
}
SNOUT_HEAD = {'snout': (0, -0.07, 0.92), 'nose': (0, -0.15, 0.91), 'chin': (0, -0.12, 0.885)}
PART_JOINTS = {'ear': (0.05, 0.0, 0.98), 'ear_tip': (0.08, 0.01, 1.08), 'tail': (0, 0.06, 0.5), 'tail_tip': (0, 0.4, 0.4)}


def template_landmarks(opts, height=DEFAULT_HEIGHT, base=Vector()):
    """The default figure's landmarks scaled to `height`, feet at `base`: digitigrade legs and a snout head when the
    options ask for them; every part joint is there either way (the fitting reads them off when it needs them)."""
    t = {**SNOUT_HEAD, **DIGITIGRADE_LEGS, **PART_JOINTS, **TEMPLATE}
    if opts['leg_type'] == 'DIGITIGRADE':
        t.update(DIGITIGRADE_LEGS)
    if opts['snout']:
        t.update(SNOUT_HEAD)
    return {k: (Vector(v) * height + base if isinstance(v, tuple) else v * height) for k, v in t.items()}


# ---------------------------------------------------------------- hands and feet from a few landmarks
def lerp(a, b, t):
    return a + (b - a) * t


def perpendicular(d):
    """Two unit axes square to direction d."""
    a = d.cross(UP) if abs(d.dot(UP)) < 0.9 else d.cross(FRONT)
    a.normalize()
    return a, d.cross(a).normalized()


def hand_frame(wrist, tip):
    """(along, front, back of hand) unit axes of a left hand; front is the thumb side."""
    along = (tip - wrist).normalized()
    front = along.cross(UP)
    front = front.normalized() if front.length > 1e-4 else FRONT.copy()
    return along, front, front.cross(along).normalized()


def derive(j, opts, probe=None):
    """The joints the guide bones need (spine joints, knuckles, fingers, ball, toes, heel tip) filled in from the
    landmarks; joints already in `j` (read from a rig) stay. With a probe each digit is fitted into the mesh."""
    j = dict(j)
    n = opts['spine_bones']
    for i in range(1, n):
        j.setdefault(f'spine{i}', lerp(j['waist'], j['chest'], i / n))
    wrist = j['wrist']
    tip = j.pop('handtip', None) or j['fingertips']
    along, front, back = hand_frame(wrist, tip)
    hand_len = (tip - wrist).length
    width = j.pop('palm_width', None) or 0.45 * hand_len
    j.setdefault('knuckles', wrist + along * PALM * hand_len)
    j.setdefault('fingertips', tip - along * 0.03 * hand_len)
    lay_digits(j, finger_names(opts['fingers']), j['knuckles'], (along, front, back), width,
               (tip - j['knuckles']).length, probe, thumb_base=wrist + along * 0.12 * hand_len)
    heel, toetip = j['heel'], j['toetip']
    fwd = Vector((toetip.x - heel.x, toetip.y - heel.y, 0)).normalized()
    side = fwd.cross(UP).normalized()            # left foot: towards the body's middle (the big toe side)
    foot_len = (toetip - heel).length
    j.setdefault('ball', Vector((*lerp(heel, toetip, 0.7).xy, lerp(heel.z, j['ankle'].z, 0.3))))
    j.setdefault('heel_tip', heel + fwd * 0.12 * foot_len)
    width = j.pop('foot_width', None) or FOOT_WIDTH * foot_len
    lay_digits(j, toe_names(opts['toes']), j['ball'], (fwd, side, UP), width, (toetip - j['ball']).length, probe,
               toes=True)
    return j


def lay_digits(j, digits, base, frame, width, length, probe, thumb_base=None, toes=False):
    """Finger / toe joints spread evenly across the hand / foot at `base`. frame = (along, front, back); front points
    to the thumb / big toe side."""
    along, front, back = frame
    rows = [d for d in digits if d != 'Thumb']
    spread = width * (TOE_SPREAD if toes else 0.75)
    room = spread / max(len(rows), 1)
    found = separate_digits(probe, base, frame, width, length, len(rows)) if probe is not None and rows else None
    for i, d in enumerate(rows):
        f = 0.5 - i / (len(rows) - 1) if len(rows) > 1 else 0.0
        size = (TOE_LENGTH if toes else FINGER_LENGTH)[d]
        start, dir = base + front * f * spread - along * (1 - size) * 0.3 * length, along
        if found:                                 # each digit aims at its own finger / toe on the mesh
            start = base + front * found[i][0]
            dir = (found[i][1] - start).normalized()
            room = found[i][2]
        put_digit(j, d, start, dir, size * length, digit_joints(d, toes), probe, room)
    if 'Thumb' in digits:
        start = thumb_base + front * 0.3 * width - back * 0.15 * width
        dir, size = (along * 0.55 + front * 0.8 - back * 0.25).normalized(), 0.8 * length
        tip = thumb_tip(probe, thumb_base, frame, length) if probe is not None else None
        if tip is not None:                       # aim at the mesh's thumb: the hand's point furthest to the front
            start = thumb_base + front * 0.2 * width
            dir, size = (tip - start).normalized(), 0.95 * (tip - start).length
        put_digit(j, 'Thumb', start, dir, size, THUMB_JOINTS, probe, 0.3 * width, fixed=tip is not None)


def separate_digits(probe, base, frame, width, length, count):
    """[(offset of the digit across the knuckle line, a point in the digit's middle, its half width)], front first,
    when a line across the digits a little past the knuckles crosses exactly `count` separate fingers / toes on the
    mesh; else None (merged digits, a mitten: the even layout stays)."""
    along, front, back = frame
    for t in (0.3, 0.2, 0.4, 0.5):
        for lift in (0.0, 0.05, -0.05):
            mid = base + along * t * length + back * lift * width
            spans = probe.intervals(mid + front * width, -front, 2 * width)
            spans = [(a, b) for a, b in spans if b - a > 0.03 * width]
            if len(spans) == count:
                out = []
                for a, b in spans:
                    c = mid + front * (width - (a + b) / 2)
                    out.append(((c - base).dot(front), probe.centre(c, (back,), width), 0.5 * (b - a) + 0.15 * width))
                return out
    return None


def thumb_tip(probe, wrist_side, frame, length):
    """The thumb's tip on the mesh: of the hand's vertices (from the wrist to the fingers' middle), the one sticking
    out furthest on the thumb side; None when nothing sticks out."""
    along, front, back = frame
    best, most = None, 0.0
    for v in probe.verts:
        r = v - wrist_side
        score = r.dot(front) + 0.5 * r.dot(along)        # the thumb points out and a little forward
        if -0.1 * length < r.dot(along) < 1.2 * length and abs(r.dot(back)) < 0.6 * length \
                and r.dot(front) > 0.25 * length and score > most:
            best, most = v, score
    return None if best is None else best - (best - wrist_side).normalized() * 0.01 * length


def put_digit(j, d, start, dir, length, fractions, probe, room, fixed=False):
    """Joints of one digit. With a probe the base is centred in the digit, the tip is the digit's furthest vertex
    along it (unless `fixed`) and the joints are centred, each only where the walls are found (merged or thin fingers
    keep the layout)."""
    axes = perpendicular(dir)
    tip = start + dir * length
    if probe is not None:
        start = probe.centre(start, axes, room)
        end = None if fixed else probe.reach(start, dir, 0.6 * room, 2 * length)
        if end is not None and (end - start).dot(dir) > 0.4 * length:
            tip = end - dir * 0.04 * (end - start).length       # the digit's own furthest point, just inside
        tip = probe.centre(probe.into(tip, 0.3 * room), axes, room)
    for i, t in enumerate(fractions, 1):
        p = lerp(start, tip, t)
        j.setdefault(f'{d}{i}', probe.centre(probe.into(p, 0.3 * room), axes, room) if probe is not None and i > 1 else p)
    j.setdefault(f'{d}Tip', tip)


# ---------------------------------------------------------------- the mesh probe (ray casts in guide space)
class Probe:
    """Ray casts into the character's meshes, in the guide armature's space."""

    def __init__(self, verts, polys):
        self.verts = verts
        self.tree = BVHTree.FromPolygons(verts, polys)

    @classmethod
    def from_objects(cls, meshes, space=None):
        """The evaluated meshes in `space` (the guide object), or world space."""
        dg = bpy.context.evaluated_depsgraph_get()
        inv = space.matrix_world.inverted() if space else None
        verts, polys = [], []
        for ob in meshes:
            ev = ob.evaluated_get(dg)
            me = ev.to_mesh()
            m = inv @ ob.matrix_world if inv else ob.matrix_world
            base = len(verts)
            verts += [m @ v.co for v in me.vertices]
            polys += [tuple(base + i for i in p.vertices) for p in me.polygons]
            ev.to_mesh_clear()
        return cls(verts, polys)

    def exit_distance(self, p, d, dist):
        """Distance from p along d to where the ray leaves the mesh (walls it enters on the way are crossed)."""
        travelled, o = 0.0, p.copy()
        for _ in range(8):
            hit, normal, _, t = self.tree.ray_cast(o, d, dist - travelled)
            if hit is None:
                return None
            travelled += t
            if normal.dot(d) > 0:
                return travelled
            o = hit + d * 1e-5
            travelled += 1e-5
        return None

    def reach(self, start, d, radius, most):
        """The mesh's furthest vertex from `start` along d, of those within `radius` of that line (one finger, one
        toe); None when none."""
        best, far = None, 0.0
        for v in self.verts:
            r = v - start
            a = r.dot(d)
            if far < a < most and (r - d * a).length < radius:
                best, far = v, a
        return best

    def into(self, p, depth):
        """p when inside, else its nearest surface point pushed `depth` in (tolerant: thin or curled parts)."""
        if self.inside(p):
            return p
        q, normal, _, _ = self.tree.find_nearest(p)
        return p if q is None else q - normal * depth

    def intervals(self, o, d, dist):
        """(enter, leave) distances along the ray o + d * t, t up to dist, of each stretch inside the mesh."""
        out, travelled, start = [], 0.0, None
        for _ in range(64):
            hit, normal, _, t = self.tree.ray_cast(o, d, dist - travelled)
            if hit is None:
                break
            travelled += t
            if normal.dot(d) < 0:
                start = travelled if start is None else start
            elif start is not None:
                out.append((start, travelled))
                start = None
            o = hit + d * 1e-5
            travelled += 1e-5
        return out

    def hit(self, o, d, dist):
        return self.tree.ray_cast(o, d, dist)[0]

    def inside(self, p):
        """p is inside the mesh: most of six axis rays leave it before anything else."""
        votes = 0
        for d in (X, -X, Y, -Y, UP, -UP):
            hit, normal, _, _ = self.tree.ray_cast(p, d, 100.0)
            votes += hit is not None and normal.dot(d) > 0
        return votes >= 4

    def span(self, p, u, reach):
        """(distance to the wall along +u, along -u) from p, or None when either is past `reach`."""
        a, b = self.exit_distance(p, u, reach), self.exit_distance(p, -u, reach)
        return None if a is None or b is None else (a, b)

    def centre(self, p, axes, reach, passes=2):
        """p moved to the middle of the mesh cross-section along each axis. Tolerant: along an axis whose two walls
        aren't both found within `reach` (thin or open geometry, merged fingers) p stays where it was."""
        p = p.copy()
        for _ in range(passes):
            for u in axes:
                s = self.span(p, u, reach)
                if s:
                    p += u * (s[0] - s[1]) / 2
        return p

    def width(self, p, u, reach):
        s = self.span(p, u, reach)
        return None if s is None else s[0] + s[1]

    def bounds(self):
        vs = self.verts
        return Vector([min(v[i] for v in vs) for i in range(3)]), Vector([max(v[i] for v in vs) for i in range(3)])


def centroid(vs):
    return sum(vs, Vector()) / len(vs) if vs else None


# ---------------------------------------------------------------- fit: landmarks from the mesh
def fit_joints(probe, opts):
    """Landmarks of the character in the probe's mesh (T- or mild A-pose, facing -Y, centred on x 0): the template
    scaled to the bounding box, then each landmark read off the mesh (vertex slices + ray casts) and centred in the
    cross-section. Left side + centre (x 0)."""
    lo, hi = probe.bounds()
    H, floor = hi.z - lo.z, lo.z
    t = template_landmarks(opts, H, Vector((0, 0, floor)))
    z = lambda f: floor + f * H
    left = [v for v in probe.verts if v.x > 0.01 * H]
    L = {}
    legs(probe, opts, L, t, left, H, floor, z)
    arms(probe, L, t, left, H)
    torso_head(probe, opts, L, H, hi)
    out = {k: L.get(k, t.get(k)) for k in set(t) | set(L)}
    for k in CENTRE_JOINTS:
        out[k] = Vector((0, out[k].y, out[k].z))
    return out


def legs(probe, opts, L, t, left, H, floor, z):
    """Hip, knee (+ hock), ankle, ball, heel and toe tip of the left leg."""
    leg = centroid([v for v in left if z(0.25) < v.z < z(0.32)]) or t['knee']
    hit = probe.hit(Vector((0, leg.y, floor - 0.01 * H)), UP, H)
    L['crotch'] = crotch = hit.z if hit is not None and hit.z < z(0.65) else z(0.47)
    line = []
    for i in range(3, int(100 * (crotch - floor) / H)):          # the leg's centre line, a slice every 1% of H
        zz = z(i / 100)
        c = centroid([v for v in left if abs(v.z - zz) < 0.006 * H and abs(v.x - leg.x) < 0.1 * H])
        if c is not None:
            c = Vector((c.x, c.y, zz))
            line.append(probe.centre(c, (X, Y), 0.15 * H) if probe.inside(c) else c)
    upper = centroid([v for v in left if crotch - 0.08 * H < v.z < crotch - 0.03 * H and v.x < leg.x + 0.12 * H])
    hip_x = (upper or leg).x
    hip = probe.centre(Vector((hip_x, leg.y, crotch + 0.05 * H)), (Y,), 0.2 * H)
    L['hip'] = Vector((hip_x, hip.y, hip.z))
    digi = opts['leg_type'] == 'DIGITIGRADE'
    feet = [v for v in left if v.z < z(0.05) and abs(v.x - leg.x) < 0.12 * H]
    if feet:
        toe, heel = min(feet, key=lambda v: v.y), max(feet, key=lambda v: v.y)
        x, foot_len = sum(v.x for v in feet) / len(feet), heel.y - toe.y
        L['foot_width'] = max(v.x for v in feet) - min(v.x for v in feet)
        L['heel'] = probe.centre(Vector((x, heel.y - 0.06 * foot_len, z(0.012))), (X,), 0.1 * H)
        L['toetip'] = probe.centre(Vector((x, toe.y + 0.04 * foot_len, z(0.012))), (X,), 0.1 * H)
        ankle_at, ball_at, ankle_z = (0.18, 0.62, z(0.03)) if digi else (0.24, 0.72, z(0.045))
        L['ankle'] = probe.centre(Vector((x, heel.y - ankle_at * foot_len, ankle_z)), (X, UP) if digi else (X, Y),
                                  0.08 * H)
        L['ball'] = probe.centre(Vector((x, heel.y - ball_at * foot_len, z(0.02))), (X, UP), 0.06 * H)
    ankle = L.get('ankle', t['ankle'])
    if digi and line:
        low = [p for p in line if z(0.08) < p.z < z(0.3)] or line
        L['hock'] = max(low, key=lambda p: p.y).copy()            # the leg's rearmost point low down
        high = [p for p in line if L['hock'].z + 0.05 * H < p.z < L['hip'].z - 0.06 * H] or line
        L['knee'] = min(high, key=lambda p: p.y).copy()           # and its frontmost above that
    else:
        k = lerp(L['hip'], ankle, 0.5)
        near = min(line, key=lambda p: abs(p.z - k.z)) if line else k
        L['knee'] = Vector((near.x, near.y, k.z))
    L['knee'].y -= 0.08 * (probe.width(L['knee'], Y, 0.2 * H) or 0.08 * H)   # a hint of bend: knee forward


def arms(probe, L, t, left, H):
    """Shoulder, elbow, wrist, hand tip, knuckles and palm width of the left arm."""
    arm = [v for v in left if v.z > L['crotch'] + 0.1 * H]
    tip = max(arm, key=lambda v: v.x) if arm else t['handtip']
    slab = lambda f: centroid([v for v in arm if abs(v.x - f * tip.x) < 0.02 * H and v.z > L['crotch'] + 0.15 * H])
    a1, a2 = slab(0.55), slab(0.8)
    if a1 and a2:
        a1, a2 = probe.centre(a1, (Y, UP), 0.1 * H), probe.centre(a2, (Y, UP), 0.1 * H)
        axis = (a2 - a1).normalized()
    else:
        a1, axis = t['elbow'], (t['wrist'] - t['elbow']).normalized()
    on_arm = lambda x: a1 + axis * ((x - a1.x) / axis.x if abs(axis.x) > 1e-3 else 0)
    L['arm_y'] = a1.y
    chest = probe.centre(Vector((0, a1.y, on_arm(0.2 * tip.x).z - 0.09 * H)), (Y,), 0.3 * H)
    side = probe.exit_distance(chest, X, 0.5 * H)                 # the chest's side, below the armpit
    torso_w = side if side and side < 0.5 * tip.x else t['shoulder'].x
    L['shoulder'] = on_arm(0.95 * torso_w)
    L['shoulder'].y = probe.centre(on_arm(1.3 * torso_w), (Y,), 0.1 * H).y    # front-to-back: the upper arm's middle
    L['handtip'] = tip - axis * 0.01 * H
    L['wrist'] = find_wrist(probe, tip, axis, H)
    L['elbow'] = probe.centre(lerp(L['shoulder'], L['wrist'], 0.56), (Y, UP), 0.1 * H)
    L['elbow'].y += 0.08 * (probe.width(L['elbow'], Y, 0.1 * H) or 0.05 * H)   # a hint of bend: elbow back
    along, front, back = hand_frame(L['wrist'], L['handtip'])
    L['knuckles'] = probe.centre(lerp(L['wrist'], L['handtip'], PALM), (front, back), 0.06 * H)
    L['palm_width'] = probe.width(L['knuckles'], front, 0.08 * H) or t['palm_width']


def find_wrist(probe, tip, axis, H):
    """The wrist: walking back from the finger tips, the hand narrows (across the palm) to the wrist and then stops
    narrowing; the first point where it stops. Falls back to a human hand length."""
    across = perpendicular(axis)
    points = []
    for i in range(30):
        p = probe.centre(tip - axis * (0.05 + 0.005 * i) * H, across, 0.08 * H)
        points.append((probe.width(p, across[0], 0.1 * H), p))
    widest = None
    for (w, p), (w2, _) in zip(points, points[1:]):
        if w is None or w2 is None:
            continue
        widest = max(widest or w, w)
        if w < 0.85 * widest and w2 > 0.98 * w:
            return p
    return tip - axis * 0.11 * H


def torso_head(probe, opts, L, H, hi):
    """Pelvis, waist, chest, neck, head, jaw, snout, clavicle, ears and tail on the middle line."""
    def mid(zz, y, reach=0.3 * H):
        return probe.centre(Vector((0, y, zz)), (Y,), reach)
    L['pelvis'] = mid(L['hip'].z, L['hip'].y)
    L['waist'] = mid(L['hip'].z + 0.06 * H, L['hip'].y)
    L['neck'] = mid(L['shoulder'].z + 0.025 * H, L['arm_y'])
    L['chest'] = mid(lerp(L['waist'], L['neck'], 0.56).z, L['arm_y'])
    L['clavicle'] = Vector((0.15 * L['shoulder'].x, L['shoulder'].y - 0.015 * H, L['shoulder'].z - 0.005 * H))
    widths = []
    for i in range(1, 12):                                       # the neck's thinnest point: where the head starts
        p = mid(L['neck'].z + i * 0.01 * H, L['neck'].y, 0.15 * H)
        w = probe.width(p, X, 0.2 * H)
        if w:
            widths.append((w, p))
    neck_top = min(widths, key=lambda wp: wp[0])[1].z if widths else L['neck'].z + 0.04 * H
    L['skull'] = mid(max(neck_top + 0.015 * H, L['neck'].z + 0.03 * H), L['neck'].y, 0.15 * H)
    up = probe.exit_distance(L['skull'], UP, 0.5 * H)
    top_z = L['skull'].z + up if up else hi.z
    L['top'] = Vector((0, L['skull'].y, top_z - 0.01 * H))
    hh = top_z - L['skull'].z
    head_c = mid(L['skull'].z + 0.4 * hh, L['skull'].y, 0.3 * H)
    head = [v for v in probe.verts if v.z > L['skull'].z and abs(v.x) < 0.5 * hh]
    L['jaw'] = Vector((0, head_c.y - 0.05 * hh, L['skull'].z + (0.22 if opts['snout'] else 0.08) * hh))
    if opts['snout'] and head:
        nose = min(head, key=lambda v: v.y)
        L['nose'] = tip_inside(probe, Vector((0, nose.y + 0.04 * hh, nose.z)), FRONT, 0.1 * hh)
        L['snout'] = Vector((0, lerp(head_c, L['nose'], 0.45).y, L['nose'].z + 0.08 * hh))
        chin_z = L['nose'].z - 0.12 * hh
    elif opts['snout']:                         # no head vertices to measure: the chin sits where the jaw does
        chin_z = L['jaw'].z
    if opts['snout']:
        front = probe.hit(Vector((0, head_c.y - H, chin_z)), Y, H)
        L['chin'] = Vector((0, front.y + 0.06 * hh if front is not None else head_c.y - 0.4 * hh, chin_z))
    else:                                       # the chin: the face's frontmost point below the mouth
        low = [v for v in probe.verts if abs(v.x) < 0.15 * hh and L['skull'].z - 0.5 * hh < v.z < L['skull'].z - 0.1 * hh]
        chin = min(low, key=lambda v: v.y) if low else Vector((0, head_c.y - 0.4 * hh, L['skull'].z - 0.3 * hh))
        L['chin'] = Vector((0, chin.y + 0.1 * hh, chin.z + 0.03 * hh))
    if opts['ears']:
        ears = [v for v in probe.verts if 0.08 * hh < v.x < 2 * hh and v.z > L['skull'].z + 0.6 * hh]
        ear_tip = max(ears, key=lambda v: v.z) if ears else None
        if ear_tip is not None and ear_tip.z > top_z - 0.02 * H:
            L['ear_tip'] = tip_inside(probe, ear_tip, (ear_tip - head_c).normalized(), 0.25 * (ear_tip - head_c).length)
            L['ear'] = walk_to_body(probe, L['ear_tip'], head_c, H)
    if opts['tail']:
        back = [v for v in probe.verts if abs(v.x) < 0.1 * H and hi.z - 0.9 * H < v.z < L['chest'].z]
        tail_tip = max(back, key=lambda v: v.y) if back else None
        if tail_tip is not None and tail_tip.y > L['pelvis'].y + 0.15 * H:
            L['tail_tip'] = tip_inside(probe, Vector((0, tail_tip.y, tail_tip.z)), Y, 0.04 * H)
            L['tail'] = tail_root(probe, L, H)


def tail_root(probe, L, H):
    """Where the tail leaves the body: of rays going back from the middle line around the hips, the one that runs
    furthest runs into the tail; its root sits on the back surface the other rays find."""
    runs = []
    for i in range(-8, 16):
        o = Vector((0, L['pelvis'].y, L['pelvis'].z + i * 0.01 * H))
        if probe.inside(o):
            d = probe.exit_distance(o, Y, H)
            if d:
                runs.append((d, o))
    if len(runs) < 3:
        return lerp(L['tail_tip'], L['pelvis'], 0.8)
    d, o = max(runs, key=lambda r: r[0])
    back = sorted(r[0] for r in runs)[len(runs) // 2]
    return Vector((0, o.y + 0.8 * back, o.z))


def tip_inside(probe, p, out, most):
    """A part's tip point: stepped back from the very tip (along -`out`, at most `most`) until inside, centred
    across the part."""
    for k in range(11):
        q = p - out * k * most / 10
        if probe.inside(q):
            return probe.centre(q, perpendicular(out), 4 * most)
    return probe.tree.find_nearest(p)[0] or p     # an open shell (a cupped ear): on its surface


def walk_to_body(probe, tip, target, H, steps=40):
    """Root of a part (an ear): walking from its tip towards `target`, the first place past a quarter of the way
    where the cross-section suddenly widens (a part tapers smoothly; meeting the head is a jump). An open part
    (a cupped ear, not inside anywhere) roots where the walk first gets inside."""
    d = target - tip
    axes = perpendicular(d.normalized())
    if not probe.inside(tip):                   # an open shell: the root is where the walk gets inside the head
        for i in range(steps):
            if probe.inside(tip + d * (i / steps)):
                return probe.centre(tip + d * (i / steps), axes, 0.1 * H)
    widths = []
    for i in range(steps):
        found = [w for w in (probe.width(tip + d * (i / steps), a, 0.25 * H) for a in axes) if w]
        widths.append(min(found) if found else None)
        if i > steps // 4 and widths[i - 2] and (widths[i] is None or widths[i] > 1.5 * widths[i - 2]):
            return probe.centre(tip + d * ((i - 2) / steps), axes, 0.1 * H)
    return lerp(tip, target, 0.5)


# ---------------------------------------------------------------- joints from an existing rig
def rig_joints(rig, opts):
    """Landmarks read from a rig's REST bones (any names, through game_rig's Skeleton: torso path, limbs, fingers,
    toes), in the rig's space. What the rig lacks comes from the template scaled to the rig's height."""
    skel = gr.Skeleton(rig)
    path = gr.torso_path(skel)
    skel.torso = path
    head = lambda k: skel.head(k).copy()
    tail = lambda k: skel.matrix(k) @ Vector((0, skel.length(k), 0))
    necks = [k for k in path[1:-1] if 'neck' in gr.plain(k)]
    spines = [k for k in path[1:-1] if k not in necks]
    j = {'pelvis': head(path[0]), 'skull': head(path[-1]), 'top': tail(path[-1])}
    j['waist'] = head(spines[0]) if spines else tail(path[0])
    j['neck'] = head(necks[0]) if necks else tail(spines[-1]) if spines else lerp(j['waist'], j['skull'], 0.7)
    j['chest'] = head(spines[-1]) if len(spines) > 1 else lerp(j['waist'], j['neck'], 0.56)
    deform = skel.deform_keys(skel.main)
    found, fingers = {}, {}
    for pattern, leg in ((gr.HAND, False), (gr.FOOT, True)):
        for key in (k for k in deform if re.search(pattern, gr.plain(k)) and skel.side(k) == 'L'):
            found.update({part: k for k, part, _, _ in gr.limb_entries(skel, key, leg, path)})
            if leg:
                found.update({'toes': k for k, *_ in gr.toes_entries(skel, key)})
            else:
                for k, finger, _, seg in gr.finger_entries(skel, key):
                    fingers.setdefault(finger.title(), {})[seg] = k
    for part, joint in (('clavicle', 'clavicle'), ('upperarm', 'shoulder'), ('lowerarm', 'elbow'), ('hand', 'wrist'),
                        ('thigh', 'hip'), ('calf', 'knee'), ('foot', 'ankle'), ('toes', 'ball')):
        if part in found:
            j[joint] = head(found[part])
    if 'hand' in found:
        j['handtip'] = tail(found['hand'])
    if 'hock' in found and opts['leg_type'] == 'DIGITIGRADE':
        j['hock'] = head(found['hock'])
    if 'foot' in found:
        end = tail(found['toes']) if 'toes' in found else tail(found['foot'])
        floor = min(j['ankle'].z, end.z)
        j['toetip'] = Vector((end.x, end.y, floor))
        heel = [k for k in skel.bones if k[0] == skel.main and 'heel' in gr.plain(k) and skel.side(k) == 'L']
        back = j['ankle'] - end
        j['heel'] = head(heel[0]) if heel else Vector((*(j['ankle'] + back * 0.25).xy, floor))
    for name, segs in fingers.items():
        if name in finger_names(opts['fingers']):
            fractions = digit_joints(name)
            if len(segs) == len(fractions):
                j.update({f'{name}{s}': head(k) for s, k in segs.items()})
            else:
                a, b = head(segs[min(segs)]), tail(segs[max(segs)])
                j.update({f'{name}{i}': lerp(a, b, f) for i, f in enumerate(fractions, 1)})
            j[f'{name}Tip'] = tail(segs[max(segs)])
    jaw = next((k for k in deform if re.search(gr.JAW, gr.plain(k))), None)
    if jaw:
        j['jaw'], j['chin'] = head(jaw), tail(jaw)
    for word, wanted in (('tail', opts['tail']), ('ear', opts['ears'])):
        roots = [k for k in skel.bones if re.search(word, gr.plain(k)) and skel.side(k) in ('', 'L')
                 and not (skel.bones[k].parent and re.search(word, rn.plain(skel.bones[k].parent)))]
        if wanted and roots:
            j[word], j[word + '_tip'] = head(roots[0]), tail(roots[0])
    low = min(j.get('toetip', j['pelvis']).z, j['pelvis'].z)
    for k, v in template_landmarks(opts, max(j['top'].z - low, 1e-3), Vector((0, 0, low))).items():
        j.setdefault(k, v)
    return j


def toe_count(names):
    """How many separate toes a rig's bone names show (a toe is a bone like 'bigtoe1'); 1 when it has none."""
    toes = len({m.group(1) for m in (re.match(r'([a-z]*toe)\d', n) for n in names) if m})
    return toes if toes in spec.TOE_COUNT_VALUES else 1


def rig_options(rig):
    """Guide options a rig suggests: digitigrade when it has a hock, its finger and spine counts, tail / ears / snout."""
    skel = gr.Skeleton(rig)
    names = [gr.plain(k) for k in skel.bones if k[0] == skel.main]
    has = lambda pattern: any(re.search(pattern, n) for n in names)
    fingers = [f for f, words in gr.FINGER_WORDS.items() if has(words)]
    path = gr.torso_path(skel)[1:-1]
    spines = [k for k in path if 'neck' not in gr.plain(k)]
    hock = has('hock')
    return resolve({'face': 'SNOUT' if has('snout|muzzle|nose') else 'HUMAN', 'leg_type': 'DIGITIGRADE' if hock else 'PLANTIGRADE',
                    'fingers': 5 if len(fingers) >= 5 else 4 if len(fingers) >= 3 else 1,
                    'toes': toe_count(names),
                    'spine_bones': min(3, max(1, len(spines) - 1)),
                    'neck_bones': min(3, max(1, len(path) - len(spines))),
                    'tail': has('tail'), 'ears': has(r'^ear')})


# ---------------------------------------------------------------- the guide armature
def make_guides(name, opts=None, collection=None, joints=None):
    """The body guide armature `<name> Guides` at the template's (or `joints`') positions, tagged so tools find it.
    `opts`: body_rig options (see resolve()). Returns the object."""
    opts = resolve(opts)
    data = bpy.data.armatures.new(f'{name} Guides')
    ob = bpy.data.objects.new(f'{name} Guides', data)
    (collection or bpy.context.scene.collection).objects.link(ob)
    ob[TAG] = 'body'
    ob[OPTIONS_PROP] = json.dumps(opts)
    ob.show_in_front = True
    data.collections.new('Guides')
    set_joints(ob, joints or derive(template_landmarks(opts), opts), opts)
    return ob


def set_joints(guides, joints, opts=None):
    """(Re)make the guide bones from a joint dict, X-Axis Mirror off while editing."""
    opts = opts or guide_options(guides)
    view, A = bpy.context.view_layer, guides.data
    active, mirror_edit = view.objects.active, A.use_mirror_x
    if active is not None and active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    view.objects.active = guides
    A.use_mirror_x = False
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        E = A.edit_bones
        for eb in list(E):
            E.remove(eb)
        coll = A.collections.get('Guides') or A.collections.new('Guides')
        for bone, a, b, parent in bone_specs(opts):
            eb = E.new(bone)
            eb.head, eb.tail = joints[a], joints[b]
            if (eb.tail - eb.head).length < 1e-4:
                eb.tail = eb.head + UP * 0.01
            eb.roll, eb.use_deform = 0.0, False
            eb.parent = E[parent] if parent else None
            eb.use_connect = bool(parent) and (E[parent].tail - eb.head).length < 1e-5
            coll.assign(eb)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        A.use_mirror_x = mirror_edit
        view.objects.active = active
    return guides


def guide_joints(guides):
    """{joint key: Vector} read back from the guide bones (where the user dragged them), guide space."""
    B, out = guides.data.bones, {}
    for bone, a, b, _ in bone_specs(guide_options(guides)):
        if bone in B:
            out.setdefault(a, B[bone].head_local.copy())
            out[b] = B[bone].tail_local.copy()
    return out


def full_points(guides):
    """{bone name: (head, tail)} for BOTH sides: the guides plus the mirror of the left ones as .R (what Generate
    builds from)."""
    flip = lambda v: Vector((-v.x, v.y, v.z))
    out = {}
    for b in guides.data.bones:
        out[b.name] = (b.head_local.copy(), b.tail_local.copy())
        if rn.side_of(b.name) == 'L':
            out[rn.flip(b.name)] = (flip(b.head_local), flip(b.tail_local))
    return out


def fit_guides(guides, meshes):
    """Fit the guides to the character meshes: the template scaled to their bounds, every joint read off and centred
    in the mesh, fingers and toes spread across the palm and foot. Keeps the options the guides were made with."""
    opts = guide_options(guides)
    probe = Probe.from_objects(meshes, guides)
    joints = fit_joints(probe, opts)
    if joints.get('foot_width'):
        guides[FOOT_WIDTH_PROP] = joints['foot_width']        # the foot bank pivots sit on the foot's edges
    set_joints(guides, derive(joints, opts, probe), opts)
    return guides


def guides_from_rig(rig, opts=None, name=None):
    """Body guides from an existing rig's rest joints (a rough skeleton); options guessed from the rig
    unless given. The guide object sits where the rig does."""
    opts = resolve(opts) if opts else rig_options(rig)
    ob = make_guides(name or rig.name, opts, rig.users_collection[0] if rig.users_collection else None,
                     derive(rig_joints(rig, opts), opts))
    ob.matrix_world = rig.matrix_world.copy()
    return ob


# ---------------------------------------------------------------- building the body rig from the guides
# One roll rule: every bone's Z axis points along a direction squared to the bone (front, up, or for a limb hinge x bone,
# which makes local X the joint's bend axis). The right side is the exact mirror of the left (roll negated), X-Axis Mirror
# off while editing. IK/FK limbs are the base limb_rig expects (IK with a pole, IK_FK on the control, the deform bones
# are the FK bones); limb_rig.upgrade then adds the snap data, the rebuilt hock and the Stretchy Limbs / Parent Switch
# features from limb_table, so nothing is guessed.
RECORD = 'full_rig_body'                 # JSON on the armature data: the bones and options of the last build_body
BACK = Vector((0, 1, 0))
SPINE_IK, HEAD_AIM, KNEE_FOLLOW = 'SpineIK', 'HeadAim', 'KneeFollow'          # KneeFollow: old builds, dropped
POLE_FOLLOW, HEAD_FOLLOW, NECK_FOLLOW = 'PoleFollow', 'HeadFollow', 'NeckFollow'
HEAD_AIM_CONSTRAINT, LOOK_FOCUS = 'Head Aim', 'HeadLookFocus'      # Head Aim (also look_rig's)
HEAD_AIM_BONE = rn.build('HeadAim', role='MCH')    # carries Head Aim + Look Roll; the Head hangs on it, so every head turn adds on the aim
LOOK_ROLL, POINT_AWAY = 'Look Roll', 'Point Away'
FOOT_BANK, HEEL_SWIVEL = 'FootBank', 'HeelSwivel'
TOGGLES = {'spine_ik': False, 'neck_ik': False, 'head_aim': False, 'lock_movement': False, 'hand_spread': False, 'hand_fist': False,
           'fist_thumb': 'CURLS', 'stretch': False, 'parent_switch': False,
           bl.OPTION: 'OFF'}
HEAD_SOCKET, NECK_SOCKET = rn.build('HeadSocket', role='MCH'), rn.build('NeckSocket', role='MCH')   # Head / Neck Follow
IK_HEAD = rn.build('Head', role='IK')    # Neck IK: move = the neck bends, turn = the head turns (Copy Rotation)
HEAD_IK_PARENT = rn.helper(IK_HEAD, 'Parent')                      # MCH-HeadIKParent: limb_rig's parent switch
HEAD_IK_PARENTS = ('Root', 'Pelvis', 'Chest')                      # what IK-Head can follow, in IK_Parent order
HEAD_IK_DEFAULT = 'Chest'                # the head control goes with the body
IK_ROTATION = 'IK Rotation'              # Head copies IK-Head's turn while in IK (after Head Aim, added to it)
HEAD_IK_RING = (0.56, 0.5, 0.0)          # IK-Head's ring: radius, up, back, of the Head's length (a vertical ring around the head's middle)
NECK_IK_TEXT = 'IK (1) or FK (0): the IK-Head control (move = neck, turn = head), or the neck and head bones themselves'
SPREAD = 'Palm'                          # Palm.L: the hand control: its Z turn fans the fingers, its X turn makes a fist
FIST = 'Fist'                            # the Transformation constraint (first on the stack) that curls a finger with Palm X
FIST_TURN, OPEN_TURN = math.radians(90), math.radians(20)     # Palm X down for a full fist / up: fingers bend back this far
FINGER_CURL = math.radians(-66)          # each finger segment at a full fist (more: the tips sink into the palm)
UNFAN = 1.0                              # at a full fist each finger turns this share of its rest fan angle back to parallel
THUMB_AIM = (math.radians(-75), 0.0)     # Thumb1 at a full fist (thumb Curls): X drops it palm-side, Z swings it
THUMB_CURL = math.radians(-60)           # Thumb2's X at a full fist (Thumb3 copies it)
POLE_LINE = 'PoleLine'                   # IK-PoleLine-Elbow.L: a line from the joint to its pole, shown in IK
BANK_EDGES = (('BankOut', 1), ('BankIn', -1))       # MCH-FootBankOut.L / In: pivots on the foot's outer / inner edge
BANK_RANGE = SWIVEL_RANGE = 1.0          # radians: the FootBank and HeelSwivel sliders
BANK_TURN = -1                           # sign of the left bank pivots' Y turn that lifts the other edge
KNEE_FOOT_SHARE = 0.5                    # a knee pole following the body: this much the foot control, the rest the Pelvis
HINGE_ROTATION = 'YZX'                   # Euler order of hinge controls: the bend (X) last, so it stays on one curve
FOOT_ROLL_RANGE, ROLL_BREAK = 1.5, math.radians(35)     # radians: the FootRoll slider, and where the ball hands over to the tip
POLE_DISTANCE = 0.5                      # poles sit this share of a limb's length off the bending joint
LOOK_DISTANCE = 0.35                     # head aim target: this share of the height in front of the head
STRAIGHT = 0.02                          # a joint bent less than this share of its limb counts as straight
SPINE_SEGMENTS = 3                       # B-bone segments on the spine bones: a smooth back
QUARTER_TURNS = (0.0, math.pi / 2, math.pi, -math.pi / 2)
PAW_SIZE = 0.08                          # IK hand / foot paw shape: about 1.17 wide, so this x 1.17 of the height across
SHAPES = [  # (name pattern on rn.plain, widget, size as a share of the height; None = the bone's length), first match
    # wins; MCH bones get none
    (r'^root$', 'WGT-Ring', 0.18), (r'^ikchest$', 'WGT-Ring', 0.13), (r'^ik(hand|foot)$', 'SelectionPaw', PAW_SIZE),
    (r'^ikhock$', 'SelectionSphere', 0.025), (r'^ikpoleline', 'WGT-Line', None), (r'^ikpole', 'WGT-Ico', 0.015),
    (r'^palm$', 'WGT-Ring', 0.02), (r'^headlookfocus$', 'WGT-Cone', 0.06),
    (r'^pelvis$', 'WGT-Ring', 0.12), (r'^(spine\d|chest)$', 'WGT-Ring', 0.1), (r'^neck', 'WGT-Ring', 0.045),
    (r'^head$', 'WGT-Ring', 0.07), (r'^thigh$', 'WGT-Ring', 0.05), (r'^(shin|hock)$', 'WGT-Ring', 0.04),
    (r'^jaw$', 'WGT-Triangle', 0.025), (r'^(snout|heel)$', 'WGT-Ring', 0.025), (r'^(fingers|toes|thumb|index|middle|ring|pinky|bigtoe|secondtoe|'
                                                 r'middletoe|fourthtoe|littletoe)\d*$', 'WGT-Ring', 0.008),
    (r'', 'WGT-Ring', 0.035),
]

Spec = namedtuple('Spec', 'name head tail parent deform connect z segments')


def spec_bone(name, head, tail, parent=None, deform=False, connect=False, z=FRONT, segments=1):
    """One bone to build: z = where its Z axis points (the roll rule), segments = B-bone segments."""
    return Spec(name, head.copy(), tail.copy(), parent, deform, connect, z.copy(), segments)


def hinge_z(hinge, head, tail):
    """The Z direction that makes the bone's local X its hinge."""
    return hinge.cross(tail - head)


def rule_z(y, z):
    """The Z axis the roll rule gives a bone pointing along the unit vector y: z squared to it (up or front when z runs
    along it)."""
    if (z - y * z.dot(y)).length < 0.1 * z.length:
        z = UP if abs(y.dot(UP)) < 0.9 else FRONT
    return (z - y * z.dot(y)).normalized()


def roll_rule(eb, z):
    """The one roll rule: the bone's Z axis points along z squared to the bone (up or front when z runs along it)."""
    eb.align_roll(rule_z(eb.vector.normalized(), z))


def bend_of(top, mid, end, fallback):
    """(hinge, bend direction) of a limb: the way its middle joint points off the top-to-end line, or `fallback`
    (elbows back, knees forward) when the guides are straight or bent the wrong way."""
    line = (end - top).normalized()
    off = (mid - top) - line * (mid - top).dot(line)
    if off.length < STRAIGHT * (end - top).length or off.normalized().dot(fallback) < 0.3:
        off = fallback - line * fallback.dot(line)
    bend = off.normalized()
    return bend.cross(line).normalized(), bend


def flat(v):
    return Vector((v.x, v.y, 0))


def pole_point(mid, top, end, hinge):
    """(where a limb's pole goes, the bend direction): off the bending joint `mid`, on the bend plane (so the IK rests
    where the bones do), POLE_DISTANCE of the limb's length away. Used by the build and Bone Workshop's IK Limb."""
    line = (end - top).normalized()
    bend = line.cross(hinge)               # on the bend plane, the way bend_of's hinge says the joint points
    return mid + bend * POLE_DISTANCE * (end - top).length, bend


# The feature bones, one spec function each: Body (from the guides) and add_features (from an existing rig's own bones)
# both lay them out here, so a feature added later is the bone a fresh build makes.
def foot_roll_specs(ctrl, toes, points, parent, stub, z_of):
    """The foot roll pivots under an IK foot control: MCH-FootRollHeel > RollTip > RollBall > MCH-FootIKTarget (the
    Foot's twin, the IK's target), plus the toes' MCH-ToesRollCounter on RollTip. points = (heel and tip on the
    floor, ball, ankle); stub(p) = (head, tail) of a small helper bone at p; z_of(head, tail) = its Z axis."""
    heel, tip, ball, ankle = points
    specs, up = [], parent
    for job, at in (('RollHeel', heel), ('RollTip', tip), ('RollBall', ball)):
        specs.append(spec_bone(rn.helper(ctrl, job), *stub(at), up, z=z_of(*stub(at))))
        up = rn.helper(ctrl, job)
    specs.append(spec_bone(rn.helper(ctrl, 'Target'), ankle, ball, up, z=z_of(ankle, ball)))
    if toes:
        specs.append(spec_bone(rn.helper(toes, 'RollCounter'), *stub(ball), rn.helper(ctrl, 'RollTip'), z=z_of(*stub(ball))))
    return specs


def socket_specs(root_vector, root_z, neck, head):
    """MCH-NeckSocket and MCH-HeadSocket (Head / Neck Follow): stubs pointing like the Root (`root_vector`, Z axis along
    `root_z`), at the neck's and the head's base. neck / head = (base, parent, connected to it)."""
    return [spec_bone(name, at, at + root_vector, parent, connect=joined, z=root_z)
            for name, (at, parent, joined) in ((NECK_SOCKET, neck), (HEAD_SOCKET, head))]


def neck_names(opts):
    return [rn.build('Neck', number=i) for i in range(1, opts['neck_bones'] + 1)]


def head_ik_specs(at, head_vector, parent):
    """IK-Head at the neck's end (`at`), turned like the Head (its vector, the same roll rule), so the Head's Copy
    Rotation of it changes nothing at rest; under `parent` (MCH-HeadIKParent, made here with no parent: the parent
    switch's Armature constraint moves it), or None when IK-Head keeps a parent of its own."""
    specs = [spec_bone(HEAD_IK_PARENT, at, at + head_vector)] if parent == HEAD_IK_PARENT else []
    return specs + [spec_bone(IK_HEAD, at, at + head_vector, parent)]


def pole_line_name(pole):
    """IK-Pole-Knee.L -> IK-PoleLine-Knee.L."""
    p = rn.parse(pole)
    part = p.part.replace('Pole', POLE_LINE, 1) if p.part.startswith('Pole') else f'{POLE_LINE}-{p.part}'
    return rn.build(part, p.side, p.number, 'IK')


def pole_line_spec(pole, joint, pole_at, parent):
    """IK-PoleLine-<joint>: from the bending joint to the pole, on the bone above the joint."""
    return spec_bone(pole_line_name(pole), joint, pole_at, parent, z=UP)


def foot_half_width(across, measured, heel_to_tip):
    """Half the foot's width: measured on the mesh by Fit (kept on the guides), else the spread of separate toes (their
    bases' places across the foot), else a share of the foot's length (`heel_to_tip`: a Vector)."""
    if measured:
        return measured / 2
    if len(across) > 1:
        return (max(across) - min(across)) / TOE_SPREAD / 2
    return FOOT_WIDTH * heel_to_tip.length / 2


def bank_specs(ctrl, heel, fwd, out, half, H):
    """MCH-FootIKBankOut / In: the foot rocks on its outer / inner edge (`out`: towards the outer edge), along `fwd`,
    chained under the foot control; the foot roll's heel pivot hangs on the last one."""
    specs, up = [], ctrl
    for job, edge in BANK_EDGES:
        at = heel + out * edge * half
        specs.append(spec_bone(rn.helper(ctrl, job), at, at + fwd * 0.03 * H, up, z=UP))
        up = specs[-1].name
    return specs


def body_options(config):
    """The build toggles from a full_rig_spec.config_for(...) dict (or a flat dict of the same keys); missing = off."""
    flat_cfg = flat_config(config)
    toggles = {k: type(v)(flat_cfg.get(k, v)) for k, v in TOGGLES.items() if k != bl.OPTION}
    return dict(toggles, **{bl.OPTION: bl.mode_of(flat_cfg.get(bl.OPTION, 'OFF'))})


def flat_config(config):
    config = config or {}
    return dict(config.get('body_rig', {}), **config.get('limb_rig', {})) if 'body_rig' in config or 'limb_rig' in config else config


def build_options(guides, config):
    """The guides' options plus the build's neck count (one Neck guide, split into Neck1..N; the guides' when unset)."""
    opts = guide_options(guides)
    return resolve(dict(opts, neck_bones=flat_config(config).get('neck_bones', opts['neck_bones'])))


class Body:
    """The bone list of one build: left side and centre, parents first (the right side is their mirror)."""

    def __init__(self, points, opts, toggles, foot_width=None):
        self.P, self.opts, self.t, self.foot_width = dict(points), opts, toggles, foot_width
        pts = [v for ht in points.values() for v in ht]
        self.floor = min(v.z for v in pts)
        self.H = max(v.z for v in pts) - self.floor
        self.specs = []
        self.torso()
        self.arm()
        self.leg()
        if bl.parts_of(toggles[bl.OPTION]):
            bl.add_specs(self, spec_bone)

    def add(self, *args, **kw):
        self.specs.append(spec_bone(*args, **kw))

    def joined(self, child, parent):
        return (self.P[child][0] - self.P[parent][1]).length < 1e-5

    def stub(self, p, length=0.03):
        return p, p + UP * length * self.H

    def torso(self):
        P, H = self.P, self.H
        pelvis = P['Pelvis'][0]
        self.add(rn.ROOT, *self.stub(Vector((0, pelvis.y, self.floor)), 0.1))
        self.add('Pelvis', *P['Pelvis'], rn.ROOT, deform=True)
        up = 'Pelvis'
        for name in [rn.build('Spine', number=i) for i in range(1, self.opts['spine_bones'] + 1)] + ['Chest']:
            self.add(name, *P[name], up, deform=True, connect=self.joined(name, up),
                     segments=1 if name == 'Chest' else SPINE_SEGMENTS)
            up = name
        a, b = P['Neck']
        necks = neck_names(self.opts)
        neck_socket, head_socket = socket_specs(self.stub(Vector(), 0.1)[1], FRONT,     # the Root's direction and roll
                                                (a, 'Chest', self.joined('Neck', 'Chest')),
                                                (P['Head'][0], necks[-1], self.joined('Head', 'Neck')))
        self.specs.append(neck_socket)
        for i, name in enumerate(necks):
            self.add(name, lerp(a, b, i / len(necks)), lerp(a, b, (i + 1) / len(necks)), necks[i - 1] if i else NECK_SOCKET,
                     deform=True, connect=bool(i))
        self.specs.append(head_socket)
        if self.t['head_aim']:
            self.add(HEAD_AIM_BONE, P['Head'][0], lerp(*P['Head'], 0.5), HEAD_SOCKET)
        self.add('Head', *P['Head'], HEAD_AIM_BONE if self.t['head_aim'] else HEAD_SOCKET, deform=True)
        if self.t['neck_ik']:
            self.specs += head_ik_specs(b, P['Head'][1] - P['Head'][0], HEAD_IK_PARENT)
        self.add('Jaw', *P['Jaw'], 'Head', deform=True, z=UP)
        if 'Snout' in P:
            self.add('Snout', *P['Snout'], 'Head', z=UP)         # face_rig_core's snout_bones hangs the snout on it
        if self.t['spine_ik']:
            self.add(rn.build('Chest', role='IK'), *P['Chest'], rn.ROOT)
        if self.t['head_aim']:
            a, b = P['Head']
            y = (b - a).normalized()
            z = (FRONT - y * FRONT.dot(y)).normalized()     # the Head's Z axis (roll_rule with FRONT): Damped Track aims it
            focus = a + z * LOOK_DISTANCE * H
            self.add(LOOK_FOCUS, focus, focus + z * 0.04 * H, rn.ROOT, z=UP)

    def arm(self):
        P, L = self.P, rn.left
        shoulder, elbow = P[L('Upperarm')]
        wrist = P[L('Forearm')][1]
        hinge, _ = bend_of(shoulder, elbow, wrist, BACK)
        elbow = self.on_plane(L('Upperarm'), L('Forearm'), shoulder, hinge)
        twist = lerp(elbow, wrist, 0.5)
        self.add(L('Shoulder'), *P[L('Shoulder')], 'Chest', deform=True)
        self.add(L('Upperarm'), shoulder, elbow, L('Shoulder'), True, self.joined(L('Upperarm'), L('Shoulder')),
                 hinge_z(hinge, shoulder, elbow))
        self.add(rn.build('Forearm', 'L', 1), elbow, twist, L('Upperarm'), True, True, hinge_z(hinge, elbow, twist))
        self.add(rn.build('Forearm', 'L', 2), twist, wrist, rn.build('Forearm', 'L', 1), True, True,
                 hinge_z(hinge, twist, wrist), segments=lr.TWIST_SEGMENTS)
        self.add(L('Hand'), *P[L('Hand')], rn.build('Forearm', 'L', 2), deform=True, connect=True, z=UP)
        hand_z = rule_z((P[L('Hand')][1] - P[L('Hand')][0]).normalized(), UP)
        for name, _, _, parent in digit_specs(finger_names(self.opts['fingers']), L('Hand'), 'Fingers', '', ''):
            z = hand_z if rn.parse(name).part == 'Thumb' else UP       # thumb rule: its Z = the hand's Z (curls palm-side)
            self.add(name, *P[name], parent, deform=True, connect=self.joined(name, parent), z=z)
        if has_palm(self.t, self.opts):
            wrist_at, knuckles = P[L('Hand')]
            self.add(L(SPREAD), knuckles, knuckles + (knuckles - wrist_at) * 0.4, L('Hand'), z=UP)
        self.add(L('Hand', 'IK'), *P[L('Hand')], rn.ROOT, z=UP)
        self.pole('Elbow', elbow, shoulder, wrist, hinge)

    def on_plane(self, upper, lower, top, hinge):
        """The middle joint of a limb moved onto its bend plane (the plane through `top` square to `hinge`), in the
        points too: guides fitted to a mesh can sit a little off it, and then the IK can't rest where the bones do."""
        mid = self.P[upper][1]
        mid = mid - hinge * (mid - top).dot(hinge)
        self.P[upper] = (self.P[upper][0], mid)
        self.P[lower] = (mid, self.P[lower][1])
        return mid

    def pole(self, joint, mid, top, end, hinge):
        """IK-Pole-<joint>: off the bending joint, on the bend plane (so the IK rests where the bones do), no parent
        (rig_pole_follow hangs it on the body), and its pole line from the joint."""
        L = rn.left
        at, bend = pole_point(mid, top, end, hinge)
        pole = L(f'Pole-{joint}', 'IK')
        self.add(pole, at, at + bend * 0.04 * self.H, None, z=UP)
        self.specs.append(pole_line_spec(pole, mid, at, L('Upperarm') if joint == 'Elbow' else L('Thigh')))

    def leg(self):
        P, H, L = self.P, self.H, rn.left
        digi = self.opts['leg_type'] == 'DIGITIGRADE'
        hip, knee = P[L('Thigh')]
        ankle = P[L('Foot')][0]
        hinge, _ = bend_of(hip, knee, ankle, FRONT)        # one bend plane for the whole leg, the hock on it too
        knee = self.on_plane(L('Thigh'), L('Shin'), hip, hinge)
        if digi:
            self.on_plane(L('Shin'), L('Hock'), hip, hinge)
        low = P[L('Shin')][1]                              # the hock (digitigrade) or the ankle
        self.add(L('Hip'), Vector((0, hip.y, hip.z)), hip, 'Pelvis')
        self.add(L('Thigh'), hip, knee, L('Hip'), True, True, hinge_z(hinge, hip, knee))
        self.add(L('Shin'), knee, low, L('Thigh'), True, True, hinge_z(hinge, knee, low))
        above = L('Shin')
        if digi:
            self.add(L('Hock'), *P[L('Hock')], L('Shin'), True, True, hinge_z(hinge, *P[L('Hock')]))
            above = L('Hock')
        ankle, ball = P[L('Foot')]
        heel, heel_tip = P[L('Heel')]
        toes = digit_specs(toe_names(self.opts['toes']), L('Foot'), 'Toes', '', '')
        fwd = flat(ball - heel).normalized()
        tip = max((P[name][1] for name, *_ in toes), key=lambda v: v.dot(fwd))
        side = UP.cross(fwd).normalized()                 # the foot's hinge: foot roll and toe curl turn around it
        on_side = lambda a, b: hinge_z(side, a, b)
        self.add(L('Foot'), ankle, ball, above, True, True, on_side(ankle, ball))
        self.add(L('Heel'), heel, heel_tip, L('Foot'), True, False, on_side(heel, heel_tip))
        toes_roll = rn.helper(L('Toes'), 'Roll')         # MCH-ToesRoll.L: the toes' parent, the roll keeps them flat
        self.add(toes_roll, *self.stub(ball), L('Foot'), z=on_side(*self.stub(ball)))
        for name, _, _, parent in toes:
            base = parent == L('Foot')
            self.add(name, *P[name], toes_roll if base else parent, deform=True, connect=not base and self.joined(name, parent),
                     z=on_side(*P[name]))
        ctrl = L('Foot', 'IK')
        self.add(ctrl, ankle, ankle + fwd * (ball - ankle).length, rn.ROOT, z=UP)
        ground = min(heel.z, tip.z)
        floor = lambda p: Vector((p.x, p.y, ground))
        across = [P[name][0].dot(side) for name, _, _, parent in toes if parent == L('Foot')]
        self.specs += bank_specs(ctrl, floor(heel), fwd, side, foot_half_width(across, self.foot_width, tip - heel), H)
        self.specs += foot_roll_specs(ctrl, L('Toes'), (floor(heel), floor(tip), ball, ankle), self.specs[-1].name,
                                      self.stub, on_side)
        self.pole('Knee', knee, hip, low, hinge)
        if digi:
            hock = P[L('Hock')][0]
            self.add(L('Hock', 'IK'), *self.stub(hock, 0.04), rn.helper(ctrl, 'Target'))
            self.add(L('HockTarget', 'MCH'), *self.stub(hock, 0.025), L('Hock', 'IK'))

    def names(self):
        out = []
        for s in self.specs:
            out += [s.name, rn.flip(s.name)] if rn.side_of(s.name) == 'L' else [s.name]
        return out


def limb_table(opts):
    """The table limb_rig.upgrade takes for the body build_body makes (left side; the right is flipped). `opts`: body_rig
    options (resolve(...)), only leg_type matters."""
    opts = resolve(opts)
    L = rn.left
    leg = dict(ctrl=L('Foot', 'IK'), ik=L('Shin'), tip=L('Foot'), target=rn.helper(L('Foot', 'IK'), 'Target'))
    digi = opts['leg_type'] == 'DIGITIGRADE'
    if digi:
        leg.update(heel=L('Hock'), hock=L('Hock', 'IK'), hock_target=L('HockTarget', 'MCH'))
    arm = dict(ctrl=L('Hand', 'IK'), ik=rn.build('Forearm', 'L', 2), tip=L('Hand'), twist=rn.build('Forearm', 'L', 2))
    return dict(parents=dict(Root=rn.ROOT, Pelvis='Pelvis', Chest='Chest', Head='Head'),
                hock_mch=True if digi else None, limbs=[arm, leg])


# ---------------------------------------------------------------- edit mode
SCALE_ISOLATED = {('Shoulder', None), ('Neck', 1), ('Head', None), ('Hand', None), ('Thigh', None), ('Foot', None)}


def make_bones(rig, body, stale):
    """Create or update every bone (right side mirrored), remove the stale ones of an earlier build."""
    A = rig.data
    E = A.edit_bones
    for name in stale:
        if name in E:
            E.remove(E[name])
    for s in body.specs:
        make_spec_bone(A, s, mirror=True)


def inherit_scale_for(name):
    """Scale isolation: the bones in SCALE_ISOLATED take no scale from their parent (the build's Follow Main Scale
    constraint, face_rig_core.follow_root_scale, still passes the Root's scale on), so scaling Pelvis or Chest
    leaves them alone."""
    b = rn.parse(name)
    if not b.role and (b.part, b.number) in SCALE_ISOLATED:
        return 'NONE'
    return 'ALIGNED' if b.part in ('Forearm', 'Shin', 'Hock') else 'FULL'


def make_spec_bone(A, s, mirror=False):
    """One spec as an edit bone (made or updated), plus its right twin when `mirror` and it is a left bone."""
    eb = fr.mk(A, s.name, s.head, s.tail, s.parent, s.deform, connect=s.connect)
    roll_rule(eb, s.z)
    pair = [eb]
    if mirror and rn.side_of(s.name) == 'L':
        pair = list(fr.both(A, s.name, s.head, s.tail, s.parent, roll=eb.roll, deform=s.deform, connect=s.connect))
    for b in pair:
        b.bbone_segments, b.bbone_easein, b.bbone_easeout = s.segments, 1.0, 1.0
        BC.thin_bbones([b])
        b.inherit_scale = inherit_scale_for(b.name)
        b.use_local_location = True
    return pair


# ---------------------------------------------------------------- pose mode
def clear_rigging(rig, names):
    """Constraints and drivers of our bones go, so a re-run builds them the same way again."""
    for name in names:
        if name in rig.pose.bones:
            lr.remove_drivers(rig, lr.bone_path(name))
            pb = rig.pose.bones[name]
            for c in list(pb.constraints):
                pb.constraints.remove(c)


def con(rig, bone, name, kind, target='', **settings):
    c = lr.get_constraint(rig.pose.bones[bone], name, kind)
    if target:
        c.target, c.subtarget = rig, target
    for k, v in settings.items():
        setattr(c, k, v)
    return c


def ik(rig, bone, target, chain, pole=None, **settings):
    c = con(rig, bone, 'IK', 'IK', target, chain_count=chain, use_stretch=False, iterations=500, **settings)
    if pole:
        c.pole_target, c.pole_subtarget = rig, pole
    return c


def side_names(side):
    return lambda part, role='', number=None: rn.build(part, side, number, role)


def rig_arm(rig, n):
    """IK (chain upper arm + both forearms) on Forearm2, elbow hinge on Forearm1, Forearm1 takes a twist share of the
    hand roll (limb_rig.twist_share); Forearm2's B-bones carry the rest down to the wrist."""
    pose = rig.pose.bones
    ctrl, f1, f2 = n('Hand', 'IK'), n('Forearm', number=1), n('Forearm', number=2)
    c = ik(rig, f2, ctrl, 3, n('Pole-Elbow', 'IK'))
    pose[f1].lock_ik_z = True       # Y stays free: a locked IK Y zeroes the Twist Share
    pose[f2].lock_ik_x = pose[f2].lock_ik_y = pose[f2].lock_ik_z = True
    lr.twist_share(rig, f1, ctrl)
    con(rig, n('Hand'), 'Copy Rotation', 'COPY_ROTATION', ctrl)
    fr.switch(pose[ctrl], 'IK_FK', 0.0, 1.0, 'IK (1) or FK (0): the hand control, or the arm bones themselves', 1.0, overshoot=1)
    return [(f2, c)]


def rig_leg(rig, n, digi, toggles):
    """IK on the Shin (to the foot target, or to the hock target on a digitigrade leg), foot roll, the toes' counter roll."""
    pose = rig.pose.bones
    ctrl, target, shin = n('Foot', 'IK'), rn.helper(n('Foot', 'IK'), 'Target'), n('Shin')
    c = ik(rig, shin, n('HockTarget', 'MCH') if digi else target, 2, n('Pole-Knee', 'IK'))
    pose[shin].lock_ik_y = pose[shin].lock_ik_z = True
    if digi:
        con(rig, n('Hock'), 'Hock Aim', 'DAMPED_TRACK', target)
    con(rig, n('Foot'), 'Copy Rotation', 'COPY_ROTATION', target, owner_space='POSE', target_space='POSE')
    pb = pose[ctrl]
    fr.switch(pb, 'IK_FK', 0.0, 1.0, 'IK (1) or FK (0): the foot control, or the leg bones themselves', 1.0, overshoot=1)
    rig_foot_roll(rig, ctrl, n('Toes'))
    rig_foot_bank(rig, ctrl)
    return [(shin, c)]


def rig_foot_roll(rig, ctrl, toes=None, roll_break=ROLL_BREAK):
    """FootRoll and RollBreak on the foot control; the roll pivots (foot_roll_specs) only turn by their drivers
    (drive_foot_roll). With `toes`, the toes' roll bone (MCH-ToesRoll) counter-turns so the toes stay flat."""
    pose = rig.pose.bones
    if toes and rn.helper(toes, 'Roll') in pose:
        con(rig, rn.helper(toes, 'Roll'), 'FootRollToes', 'COPY_ROTATION', rn.helper(toes, 'RollCounter'),
            mix_mode='BEFORE', owner_space='LOCAL', target_space='LOCAL_OWNER_ORIENT')
    for job in ('RollHeel', 'RollTip', 'RollBall'):
        roll_helper(pose[rn.helper(ctrl, job)])
    if toes and rn.helper(toes, 'RollCounter') in pose:
        roll_helper(pose[rn.helper(toes, 'RollCounter')])
    pb = pose[ctrl]
    fr.switch(pb, 'FootRoll', -FOOT_ROLL_RANGE, FOOT_ROLL_RANGE, 'Roll the foot: below 0 on the heel, above 0 onto the ball, '
              'then the toe tip')
    fr.switch(pb, 'RollBreak', 0.0, FOOT_ROLL_RANGE, 'How far the foot rolls on the ball before it rolls on the toe tip',
              roll_break)


def drive_foot_roll(rig, ctrl, toes=None):
    """The roll pivots turn by FootRoll: the heel below 0, the ball up to RollBreak, then the toe tip."""
    P = lr.bone_path
    roll = {'roll': f'{P(ctrl)}["FootRoll"]', 'brk': f'{P(ctrl)}["RollBreak"]'}
    pivots = [(rn.helper(ctrl, 'RollHeel'), 'min(roll, 0)'), (rn.helper(ctrl, 'RollTip'), 'max(roll - brk, 0)'),
              (rn.helper(ctrl, 'RollBall'), 'min(max(roll, 0), brk)')]
    if toes and rn.helper(toes, 'RollCounter') in rig.pose.bones:
        pivots.append((rn.helper(toes, 'RollCounter'), '-min(max(roll, 0), brk)'))
    for bone, expr in pivots:
        lr.add_driver(rig, f'{P(bone)}.rotation_euler', 0, expr, roll)


def rig_foot_bank(rig, ctrl):
    """FootBank and HeelSwivel on the foot control; the bank pivots only turn by their drivers (drive_foot_bank)."""
    pb = rig.pose.bones[ctrl]
    fr.switch(pb, FOOT_BANK, -BANK_RANGE, BANK_RANGE, 'Rock the foot onto its edge: above 0 the outer edge, below 0 '
              'the inner edge')
    fr.switch(pb, HEEL_SWIVEL, -SWIVEL_RANGE, SWIVEL_RANGE, 'Turn the foot on its heel: above 0 the toes swing out, '
              'below 0 in')
    for job, _ in BANK_EDGES:
        roll_helper(rig.pose.bones[rn.helper(ctrl, job)])


def drive_foot_bank(rig, ctrl):
    """FootBank turns the outer or inner pivot on its Y, HeelSwivel turns the heel pivot on its Y."""
    P = lr.bone_path
    mirror = 1 if rn.side_of(ctrl) != 'R' else -1         # a Y turn of a mirrored bone mirrors with the sign flipped
    bank = {'bank': f'{P(ctrl)}["{FOOT_BANK}"]'}
    for (job, _), expr in zip(BANK_EDGES, ('max(bank, 0)', 'min(bank, 0)')):
        lr.add_driver(rig, f'{P(rn.helper(ctrl, job))}.rotation_euler', 1, f'{BANK_TURN * mirror} * {expr}', bank)
    lr.add_driver(rig, f'{P(rn.helper(ctrl, "RollHeel"))}.rotation_euler', 1, f'{mirror} * swivel',
                  {'swivel': f'{P(ctrl)}["{HEEL_SWIVEL}"]'})


def poles(n):
    """(pole, IK control, {body bone the pole follows: share}, pole line) of one side's arm and leg."""
    return [(pole, ctrl, pole_follow_body(ctrl, leg), pole_line_name(pole))
            for pole, ctrl, leg in ((n('Pole-Elbow', 'IK'), n('Hand', 'IK'), False), (n('Pole-Knee', 'IK'), n('Foot', 'IK'), True))]


def pole_follow_body(ctrl, leg, pelvis='Pelvis', chest='Chest'):
    """{body bone: share} a pole follows: a knee the Pelvis and its foot control, an elbow the Chest."""
    return {pelvis: 1 - KNEE_FOOT_SHARE, ctrl: KNEE_FOOT_SHARE} if leg else {chest: 1.0}


def rig_pole_follow(rig, pole, ctrl, body):
    """The pole rides the body (Rigify's pole_parent): an Armature constraint blends the Root with `body` ({bone:
    share}), set by PoleFollow on the IK control (1 = with the body, 0 = with the Root only, as old builds were). Knee
    poles follow the Pelvis and the foot, elbow poles the Chest, so moving the torso without the Root keeps the knees and
    elbows pointing where they did. At rest every target is unposed, so the pole stays put."""
    follow = con(rig, pole, 'Pole Follow', 'ARMATURE')
    while len(follow.targets):
        follow.targets.remove(follow.targets[0])
    for bone, weight in ((rn.ROOT, 0.0), *body.items()):          # the weights PoleFollow 1 gives (pole_follow_drivers)
        target = follow.targets.new()
        target.target, target.subtarget, target.weight = rig, bone, weight
    pb = rig.pose.bones[ctrl]
    if KNEE_FOLLOW in pb:                          # an older follow (old builds, hand-made rigs): its value carries over
        if POLE_FOLLOW not in pb:
            pb[POLE_FOLLOW] = float(pb[KNEE_FOLLOW])
        lr.drop_prop(pb, KNEE_FOLLOW)
    lr.remove_constraint(rig, pole, 'Knee Follow')
    fr.switch(pb, POLE_FOLLOW, 0.0, 1.0, 'The pole follows the body (1) or stays with the Root (0)', 1.0, overshoot=1)


def pole_follow_drivers(rig, pole, ctrl, body):
    """Target weights of rig_pole_follow's constraint: the Root takes 1 - PoleFollow, the body bones their share of it."""
    P, follow = lr.bone_path, {'follow': f'{lr.bone_path(ctrl)}["{POLE_FOLLOW}"]'}
    for i, expr in enumerate(['1 - follow'] + [f'follow * {share:.4f}' for share in body.values()]):
        lr.add_driver(rig, f'{P(pole)}.constraints["Pole Follow"].targets[{i}].weight', None, expr, follow)


def digit_chains(opts):
    """Left finger and toe chains with more than one bone, base first."""
    chains = {}
    for digits, mitten in ((finger_names(opts['fingers']), 'Fingers'), (toe_names(opts['toes']), 'Toes')):
        for name, _, _, _ in digit_specs(digits, rn.left('Hand'), mitten, '', ''):
            chains.setdefault(rn.parse(name).part, []).append(name)
    return [c for c in chains.values() if len(c) > 1]


def rig_digits(rig, opts, side):
    """Segments 2 and 3 of a finger or toe copy the base's curl (its X turn): curl a finger with one bone. The thumb
    (the user's thumb rule): Thumb1 only aims it and nothing copies it, Thumb2 is the curl and Thumb3 copies Thumb2."""
    for chain in digit_chains(opts):
        if rn.parse(chain[0]).part == 'Thumb':
            chain = chain[1:]
        curl_follow(rig, [rn.with_side(name, side) for name in chain])


def curl_follow(rig, chain):
    """The later segments of a finger chain copy its first bone's curl (X turn)."""
    for name in chain[1:]:
        con(rig, name, 'Copy Rotation', 'COPY_ROTATION', chain[0], use_y=False, use_z=False,
            owner_space='LOCAL', target_space='LOCAL')


def spread_shares(opts):
    """(left finger base, share) the hand spread fans: the first finger after the thumb turns fully one way, the last
    fully the other way, the ones between in even steps."""
    bases = [rn.build(f, 'L', 1) for f in finger_names(opts['fingers']) if f != 'Thumb']
    if len(bases) < 2:
        return []
    return [(name, 1 - 2 * i / (len(bases) - 1)) for i, name in enumerate(bases)
            if abs(1 - 2 * i / (len(bases) - 1)) > 1e-6]


def has_palm(toggles, opts):
    """Palm.L is built for Hand Spread or Fist Control on a hand with fingers."""
    return (toggles['hand_spread'] or toggles['hand_fist']) and opts['fingers'] > 1


def fan_angle(rig, name, hand=None):
    """A left finger base's rest turn away from the hand's direction (`hand`, else Hand.L), about the hand's Z (its spread)."""
    y, hand = rig.data.bones[name].matrix_local.col[1], rig.data.bones[hand or rn.left('Hand')].matrix_local
    local = hand.inverted().to_3x3() @ y.xyz
    return math.atan2(-local.x, local.y)


def fist_map(rig, opts, thumb_curls=True):
    """{left finger bone: {axis: its local turn at a full fist}}: the finger bases curl and turn back parallel (else
    curled fingers cross under the palm); with thumb_curls Thumb1 aims the thumb across and Thumb2 curls it."""
    out = {name: {'X': FINGER_CURL, 'Z': -UNFAN * fan_angle(rig, name)}
           for name in (rn.build(f, 'L', 1) for f in finger_names(opts['fingers']) if f != 'Thumb')}
    if thumb_curls and 'Thumb' in finger_names(opts['fingers']):
        out[rn.build('Thumb', 'L', 1)] = {'X': THUMB_AIM[0], 'Z': THUMB_AIM[1]}
        out[rn.build('Thumb', 'L', 2)] = {'X': THUMB_CURL}
    return out


def rig_hand_fist(rig, opts, side, thumb_curls=True):
    """Turning Palm.L down on its X curls the fingers into a fist (up: they bend back OPEN_TURN / FIST_TURN of it): a
    Transformation constraint "Fist", first on each finger base's stack, maps Palm's local X turn onto the base's own
    turns (fist_map), mixed before its own pose, so a finger's own curl adds on top. Segments 2 and 3 copy the base's
    curl, so the whole finger closes."""
    fist_on(rig, rn.build(SPREAD, side), {rn.with_side(left, side): turns
                                          for left, turns in fist_map(rig, opts, thumb_curls).items()}, side == 'R')


def fist_on(rig, palm, finger_turns, mirrored=False):
    """The Fist constraint on each finger base: {bone: {axis: its local turn at a full fist}} (fist_map, or Bone
    Workshop's Finger Curl from the bones you pick); mirrored = turns written for the left side on right bones (Z flips)."""
    for name, turns in finger_turns.items():
        pb = rig.pose.bones[name]
        c = con(rig, pb.name, FIST, 'TRANSFORM', palm, owner_space='LOCAL', target_space='LOCAL', map_from='ROTATION',
                map_to='ROTATION', mix_mode_rot='BEFORE', from_rotation_mode=HINGE_ROTATION, from_min_x_rot=-FIST_TURN,
                from_max_x_rot=OPEN_TURN, use_motion_extrapolate=False)
        for axis in 'xyz':
            turn = turns.get(axis.upper(), 0.0) * (-1 if mirrored and axis == 'z' else 1)   # mirrored: Z flips, X not
            setattr(c, f'map_to_{axis}_from', 'X')
            setattr(c, f'to_min_{axis}_rot', turn)
            setattr(c, f'to_max_{axis}_rot', -turn * OPEN_TURN / FIST_TURN)
        pb.constraints.move(pb.constraints.find(FIST), 0)


def rig_hand_spread(rig, opts, side):
    """Turning Palm.L on its Z fans the fingers (Rigify's palm): each finger base takes its share of that turn before its
    own pose, so curls and single-finger poses stay. The influence is set by spread_influence (after the collections:
    a constraint at full influence would count as driving the finger)."""
    spread_on(rig, rn.build(SPREAD, side), [(rn.with_side(name, side), share) for name, share in spread_shares(opts)])


def spread_on(rig, palm, shares):
    """Hand Spread on each finger base [(bone, share)]: the base takes its share of the palm's Z turn (influence 0 here,
    spread_influence sets it after the collections)."""
    for name, share in shares:
        con(rig, name, 'Hand Spread', 'COPY_ROTATION', palm, use_x=False,
            use_y=False, invert_z=share < 0, mix_mode='BEFORE', owner_space='LOCAL', target_space='LOCAL', influence=0.0)


def spread_influence(rig, opts):
    for side in rn.SIDES:
        for name, share in spread_shares(opts):
            rig.pose.bones[rn.with_side(name, side)].constraints['Hand Spread'].influence = abs(share)


def rig_pole_line(rig, line, pole):
    """The pole line stretches from its joint to the pole; it can't be clicked or posed."""
    con(rig, line, 'Stretch To', 'STRETCH_TO', pole, volume='NO_VOLUME', rest_length=rig.data.bones[line].length)
    pb = rig.pose.bones[line]
    pb.lock_location = pb.lock_rotation = pb.lock_scale = (True, True, True)
    rig.data.bones[line].hide_select = True


def drive_pole_line(rig, line, ctrl):
    """The pole line shows only in IK."""
    lr.add_driver(rig, f'{lr.bone_path(line)}.hide', None, 'ik < 0.5', {'ik': f'{lr.bone_path(ctrl)}["IK_FK"]'})


def drive_head_follow(rig):
    for socket, key in ((NECK_SOCKET, NECK_FOLLOW), (HEAD_SOCKET, HEAD_FOLLOW)):
        lr.add_driver(rig, f'{lr.bone_path(socket)}.constraints["Follow"].influence', None, '1 - follow',
                      {'follow': f'{lr.bone_path("Head")}["{key}"]'})


def rig_head_follow(rig):
    """Neck and head sockets copy the Root's turn by 1 - NeckFollow / HeadFollow (Rigify's neck_follow / head_follow): at
    1 the neck and head turn with the torso, at 0 they keep their turn while the torso bends. The sockets point like the
    Root, so they rest unchanged."""
    for socket, key in ((NECK_SOCKET, NECK_FOLLOW), (HEAD_SOCKET, HEAD_FOLLOW)):
        con(rig, socket, 'Follow', 'COPY_ROTATION', rn.ROOT, owner_space='POSE', target_space='POSE')
        fr.switch(rig.pose.bones['Head'], key, 0.0, 1.0, f'The {key[:-6].lower()} turns with the torso (1) or keeps its '
                  'own turn while the torso bends (0)', 1.0, overshoot=1)


def rotate_only_controls(opts):
    """Left and centre controls that only turn (Lock Movement): spine to head, the FK limb bones, the heel, the fingers,
    toes and hand spread. Root, Pelvis, Shoulder, Thigh, the IK controls and poles keep their movement."""
    L, digi = rn.left, opts['leg_type'] == 'DIGITIGRADE'
    torso = [rn.build('Spine', number=i) for i in range(1, opts['spine_bones'] + 1)] + ['Chest'] + neck_names(opts) + ['Head']
    limbs = [L('Upperarm'), rn.build('Forearm', 'L', 1), rn.build('Forearm', 'L', 2), L('Hand'), L('Shin'),
             L('Foot'), L('Heel')] + ([L('Hock')] if digi else [])
    return torso + limbs + digit_names(opts) + [L(SPREAD)]


def hinge_controls(opts):
    """Left controls that bend on one axis (X): elbows, knees, the hock, the heel, fingers, toes and the hand spread."""
    L = rn.left
    return ([rn.build('Forearm', 'L', 1), rn.build('Forearm', 'L', 2), L('Shin'), L('Hock'), L('Heel'), L(SPREAD)]
            + digit_names(opts))


def digit_names(opts):
    return [name for digits, parent, mitten in ((finger_names(opts['fingers']), rn.left('Hand'), 'Fingers'),
                                                (toe_names(opts['toes']), rn.left('Foot'), 'Toes'))
            for name, *_ in digit_specs(digits, parent, mitten, '', '')]


def both_sides(names):
    return [n for name in names for n in ([name, rn.flip(name)] if rn.side_of(name) == 'L' else [name])]


def set_controls(rig, opts, toggles):
    """Lock Movement on the rotate-only controls (off: their movement unlocked again) and the hinge Euler order."""
    pose = rig.pose.bones
    for name in both_sides(rotate_only_controls(opts)):
        if name in pose:
            pose[name].lock_location = (toggles['lock_movement'],) * 3
    for name in both_sides(hinge_controls(opts)):
        if name in pose:
            pose[name].rotation_mode = HINGE_ROTATION


def roll_helper(pb):
    pb.rotation_mode = 'XYZ'
    pb.lock_location = pb.lock_rotation = pb.lock_scale = (True, True, True)


def rig_spine_ik(rig, top, ctrl, count):
    """Spine IK: `top` (the Chest) reaches for the control `ctrl` and the `count` bones below it bend to bring it there;
    it also turns with the control. SpineIK on the control: 1 = IK, 0 = posed bone by bone (drive_spine_ik)."""
    ik(rig, top, ctrl, count, use_tail=False)          # the spine bones bend to bring the chest there
    con(rig, top, 'Copy Rotation', 'COPY_ROTATION', ctrl, owner_space='POSE', target_space='POSE')
    fr.switch(rig.pose.bones[ctrl], SPINE_IK, 0.0, 1.0, 'The spine bends to follow this chest control (1), or is posed '
              'bone by bone (0)', 1.0, overshoot=1)


def drive_spine_ik(rig, top, ctrl):
    s = {'s': f'{lr.bone_path(ctrl)}["{SPINE_IK}"]'}
    for name in ('IK', 'Copy Rotation'):
        lr.add_driver(rig, f'{lr.bone_path(top)}.constraints["{name}"].influence', None, 's', s)


def rig_torso(rig, toggles, opts):
    pose, spine_bones = rig.pose.bones, opts['spine_bones']
    if toggles['spine_ik']:
        rig_spine_ik(rig, 'Chest', rn.build('Chest', role='IK'), spine_bones)
    if toggles['neck_ik']:
        necks = neck_names(opts)
        ik(rig, necks[-1], IK_HEAD, len(necks))
        rig_neck_ik(rig, necks, head_ik_parents(rig))
    if toggles['head_aim']:
        rig_head_aim(rig)


def head_aim_bone(A, head='Head'):
    """Edit mode: MCH-HeadAim, as long as the head's first half with its head and roll, under the head's parent; the
    head hangs on it (not connected). Returns the bone, or the old one when it is there."""
    E = A.edit_bones
    if HEAD_AIM_BONE in E:
        return E[HEAD_AIM_BONE]
    bone = E[head]
    aim = fr.mk(A, HEAD_AIM_BONE, bone.head, bone.head + (bone.tail - bone.head) * 0.5,
                bone.parent.name if bone.parent else None, False, roll=bone.roll)
    aim.inherit_scale = inherit_scale_for(HEAD_AIM_BONE)
    bone.use_connect, bone.parent = False, aim
    return aim


def aim_point_away(rig):
    """Point Away tracks the head's base: the aim bone's parent (the head socket sits there; a neck bone ends there,
    so its tail). Not the Head (a dependency cycle)."""
    B = rig.data.bones
    parent = B[HEAD_AIM_BONE].parent
    if parent is None:
        return
    turn = rig.pose.bones[LOOK_FOCUS].constraints[POINT_AWAY]
    turn.target, turn.subtarget = rig, parent.name
    base = B[HEAD_AIM_BONE].head_local
    turn.head_tail = 1.0 if (parent.tail_local - base).length < (parent.head_local - base).length else 0.0


def rig_head_aim(rig, head='Head', track_axis='TRACK_Z'):
    """Head Aim: on MCH-HeadAim (the head's parent; head_aim_bone makes it) a Damped Track turns its front (`track_axis`)
    to HeadLookFocus, then Look Roll adds the target's Y twist, both by the HeadAim slider on HeadLookFocus. HeadLookFocus
    points its -Y away from the head's socket (Point Away), so its twist is the roll. On by default (user, 2026-11-20).
    Also used by look_rig on other rigs. The influence drivers come later (drive_head_aim). A Head Aim an older build put
    on the Head moves to the new bone."""
    P = rig.pose.bones
    old = P[head].constraints.get(HEAD_AIM_CONSTRAINT)
    if old:
        lr.remove_drivers(rig, f'{lr.bone_path(head)}.constraints["{HEAD_AIM_CONSTRAINT}"]')
        P[head].constraints.remove(old)
    con(rig, HEAD_AIM_BONE, HEAD_AIM_CONSTRAINT, 'DAMPED_TRACK', LOOK_FOCUS, track_axis=track_axis)
    con(rig, HEAD_AIM_BONE, LOOK_ROLL, 'TRANSFORM', LOOK_FOCUS, map_from='ROTATION', map_to='ROTATION',
        from_rotation_mode='SWING_TWIST_Y', from_min_y_rot=-math.pi, from_max_y_rot=math.pi, map_to_z_from='Y',
        to_min_z_rot=-math.pi, to_max_z_rot=math.pi, mix_mode_rot='AFTER', target_space='LOCAL', owner_space='LOCAL')
    focus = P[LOOK_FOCUS]
    focus.rotation_mode = 'YZX'
    focus.lock_rotation = (True, False, True)           # only the Y twist is used: it rolls the head
    con(rig, LOOK_FOCUS, POINT_AWAY, 'DAMPED_TRACK', track_axis='TRACK_NEGATIVE_Y')
    aim_point_away(rig)
    fr.switch(focus, HEAD_AIM, 0.0, 1.0, 'The head looks at this target (1), or is posed by hand (0)', 1.0, overshoot=1)
    if IK_ROTATION in P[head].constraints:                    # IK-Head's turn adds on top of the aim
        set_ik_rotation(rig)


def head_ik_parents(rig):
    return {name: name for name in HEAD_IK_PARENTS if name in rig.data.bones}


def head_ik_limb(chain):
    """limb_rig's limb dict for the neck IK: a part chain (no pole) on the Head page; `turns` = the Head, so the FK -> IK
    snap gives IK-Head the head's turn."""
    return dict(ctrl=IK_HEAD, parent_bone=HEAD_IK_PARENT, chain=list(chain), fk=list(chain) + ['Head'], tip=chain[-1],
                target=IK_HEAD, pole=None, part='Head', turns='Head')


def neck_ik_of(rig, bone):
    """The IK on `bone` aimed at IK-Head, or None."""
    return next((c for c in rig.pose.bones[bone].constraints if c.type == 'IK' and c.subtarget == IK_HEAD), None)


def set_ik_rotation(rig):
    """Head's IK Rotation: IK-Head's own local turn added AFTER the look constraints (Head Aim aims first, so the turn
    adds on top of the aim and rotating IK-Head turns and nods the head, aim on or off)."""
    head = rig.pose.bones['Head']
    turn = lr.get_constraint(head, IK_ROTATION, 'COPY_ROTATION')
    turn.target, turn.subtarget = rig, IK_HEAD
    turn.mix_mode, turn.target_space, turn.owner_space = 'AFTER', 'LOCAL', 'LOCAL'
    last = len(head.constraints) - 1
    if head.constraints.find(IK_ROTATION) != last:
        head.constraints.move(head.constraints.find(IK_ROTATION), last)


def rig_neck_ik(rig, chain, parents, default=HEAD_IK_DEFAULT):
    """Neck IK on the neck `chain` (root first; its last bone has an IK aimed at IK-Head): Head adds
    IK-Head's turn (after any look constraint), IK_FK on IK-Head (1 = IK), the parent switch when IK-Head hangs on
    MCH-HeadIKParent (`parents`; a new switch starts on `default`), and the snap data. Drivers: drive_neck_ik."""
    pose = rig.pose.bones
    set_ik_rotation(rig)
    ctrl = pose[IK_HEAD]
    fr.switch(ctrl, 'IK_FK', 0.0, 1.0, NECK_IK_TEXT, 1.0, overshoot=1)
    limb = head_ik_limb(chain)
    switch = HEAD_IK_PARENT in rig.data.bones and parents
    if switch:
        new = 'IK_Parent' not in ctrl
        lr.rig_parent_switch(rig, limb, parents)
        if new:
            index = list(parents).index(default) if default in parents else 0
            ctrl['IK_Parent'] = index
            ctrl.id_properties_ui('IK_Parent').update(default=index)
    lr.store_limb_data(rig, limb, parents if switch else {})


def drive_neck_ik(rig):
    ik_var = {'ik': f'{lr.bone_path(IK_HEAD)}["IK_FK"]'}
    chain = json.loads(rig.pose.bones[IK_HEAD]['Limb'])['chain']
    lr.add_driver(rig, f'{lr.bone_path(chain[-1])}.constraints["{neck_ik_of(rig, chain[-1]).name}"].influence', None, 'ik',
                  ik_var)
    lr.add_driver(rig, f'{lr.bone_path("Head")}.constraints["{IK_ROTATION}"].influence', None, 'ik', ik_var)


def shape_head_ik(rig):
    """IK-Head's control: a vertical WGT-Ring around the head's middle (half the Head's length up), sized by the Head's length."""
    length = rig.data.bones['Head'].length
    radius, up, back = (k * length for k in HEAD_IK_RING)
    pb = rig.pose.bones[IK_HEAD]
    fr.shape(pb, 'WGT-Ring', radius, (0, up, back))
    pb.custom_shape_rotation_euler = (math.pi / 2, 0, 0)


def drive_head_aim(rig, head='Head'):
    for name in (HEAD_AIM_CONSTRAINT, LOOK_ROLL):
        lr.add_driver(rig, f'{lr.bone_path(HEAD_AIM_BONE)}.constraints["{name}"].influence', None, 'a',
                      {'a': f'{lr.bone_path(LOOK_FOCUS)}["{HEAD_AIM}"]'})


def drive_body(rig, opts, toggles):
    """Every driver, added after the bone collections are placed (a driven influence may be 0 then)."""
    P = lr.bone_path
    for side in rn.SIDES:
        n = side_names(side)
        for ctrl, bones in ((n('Hand', 'IK'), [(n('Forearm', number=2), 'IK', 'ik'), (n('Forearm', number=1), lr.TWIST_NAME, 'ik'),
                                                (n('Hand'), 'Copy Rotation', 'ik')]),
                            (n('Foot', 'IK'), [(n('Shin'), 'IK', 'ik'), (n('Foot'), 'Copy Rotation', 'ik'),
                                               (rn.helper(n('Toes'), 'Roll'), 'FootRollToes', 'ik')]
                             + ([(n('Hock'), 'Hock Aim', 'ik')] if opts['leg_type'] == 'DIGITIGRADE' else []))):
            for bone, name, expr in bones:
                lr.add_driver(rig, f'{P(bone)}.constraints["{name}"].influence', None, expr, {'ik': f'{P(ctrl)}["IK_FK"]'})
        ctrl = n('Foot', 'IK')
        drive_foot_roll(rig, ctrl, n('Toes'))
        drive_foot_bank(rig, ctrl)
        for pole, limb_ctrl, body, line in poles(n):
            pole_follow_drivers(rig, pole, limb_ctrl, body)
            drive_pole_line(rig, line, limb_ctrl)
    drive_head_follow(rig)
    if toggles['spine_ik']:
        drive_spine_ik(rig, 'Chest', rn.build('Chest', role='IK'))
    if toggles['neck_ik']:
        drive_neck_ik(rig)
    if toggles['head_aim']:
        drive_head_aim(rig)


def shape_spine_ik(pb):
    """The chest control's ring sits at its tip (shoulder height), where the user grabs the chest; it still turns
    around the bone's head."""
    pb.custom_shape_translation = (0, pb.bone.length, 0)


def shape_rule(name, length, H):
    """(widget, size) SHAPES gives the control `name` (`length` long) on a rig `H` tall, or None for an MCH bone."""
    if rn.is_helper(name):
        return None
    widget, size = next((w, s) for pattern, w, s in SHAPES if re.search(pattern, rn.plain(name)))
    return widget, length if size is None else size * H


def shape_controls(rig, names, H):
    for name in names:
        if name == IK_HEAD:
            shape_head_ik(rig)
            continue
        rule = shape_rule(name, rig.data.bones[name].length, H)
        if rule and rule[0] == 'WGT-Triangle':
            fr.jaw_shape(rig.pose.bones[name], rule[1])
        elif rule:
            fr.shape(rig.pose.bones[name], *rule)
        if name == rn.build('Chest', role='IK'):
            shape_spine_ik(rig.pose.bones[name])


def place_collections(rig, names):
    plan = BC.plan_rig(rig)
    for name in names:
        BC.place_bone(rig, name, *plan[name])


def read_record(rig):
    return json.loads(rig.data.get(RECORD, '{}'))


def strip_limb_features(rig, record):
    """An earlier build's limb_rig extras come off first (they are rebuilt from the table), so a re-run is the same build."""
    if not record:
        return
    limbs, _ = lr.limbs_of(rig, limb_table(record['opts']))
    for limb in limbs:
        lr.remove_features(rig, limb)


def keep_isolated_stretch(rig):
    """Stretchy Limbs' Stretch on a scale-isolated Thigh replaces its local Y scale, which would drop Follow Main Scale's
    Y: let it multiply instead (the same as replacing while the Thigh's own scale is 1)."""
    for name in both_sides([rn.left('Thigh')]):
        stretch = rig.pose.bones[name].constraints.get('Stretch') if name in rig.pose.bones else None
        if stretch and rig.data.bones[name].inherit_scale == 'NONE':
            stretch.use_offset = True


def build_body(rig, guides, config=None):
    """Build (or rebuild) the body bones on the armature `rig` from the body guides: torso, IK/FK arms and legs with poles,
    foot roll, the digitigrade hock, fingers and toes by count, plus the toggles in `config` (full_rig_spec.config_for
    output: spine_ik, neck_ik, head_aim, lock_movement, hand_spread, hand_fist, fist_thumb, stretch, parent_switch; bendy_limbs is OFF / LEGS / ARMS / BOTH; missing = off;
    neck_bones, else the guides'). Leg type, finger, toe and spine counts come from the guides. Safe to re-run: bones are updated in place, a feature switched off loses only its bones.
    The rig must be in the view layer. Returns a report dict."""
    opts, toggles = build_options(guides, config), body_options(config)
    to_rig = rig.matrix_world.inverted() @ guides.matrix_world
    points = {k: (to_rig @ a, to_rig @ b) for k, (a, b) in full_points(guides).items() if rn.side_of(k) != 'R'}
    record = read_record(rig)
    foot_width = guides.get(FOOT_WIDTH_PROP) or record.get('foot_width')
    body = Body(points, opts, toggles, foot_width and foot_width * to_rig.to_scale().x)
    names = body.names()
    stale = [n for n in record.get('bones', []) if n not in names]
    view = bpy.context.view_layer
    active, mode = view.objects.active, rig.mode
    lr.set_mode(rig, 'POSE')
    strip_limb_features(rig, record)
    clear_rigging(rig, set(names) | set(stale))
    mirror, rig.data.use_mirror_x = rig.data.use_mirror_x, False
    lr.set_mode(rig, 'EDIT')
    try:
        for name in stale:
            lr.remove_drivers(rig, lr.bone_path(name))
        make_bones(rig, body, stale)
        if bl.parts_of(toggles[bl.OPTION]):
            bl.link_handles(rig, toggles[bl.OPTION])
    finally:
        lr.set_mode(rig, 'POSE')
        rig.data.use_mirror_x = mirror
    ik_constraints = []
    for side in rn.SIDES:
        n = side_names(side)
        ik_constraints += rig_arm(rig, n) + rig_leg(rig, n, opts['leg_type'] == 'DIGITIGRADE', toggles)
        rig_digits(rig, opts, side)
        for pole, ctrl, follow, line in poles(n):
            rig_pole_follow(rig, pole, ctrl, follow)
            rig_pole_line(rig, line, pole)
        if toggles['hand_fist'] and has_palm(toggles, opts):
            rig_hand_fist(rig, opts, side, toggles['fist_thumb'] == 'CURLS')
        if toggles['hand_spread'] and has_palm(toggles, opts):
            rig_hand_spread(rig, opts, side)
    rig_torso(rig, toggles, opts)
    rig_head_follow(rig)
    set_controls(rig, opts, toggles)
    with lr.rest_pose([rig]):
        for bone, c in ik_constraints:
            lr.fit_pole_angle(rig, rig.pose.bones[bone], c, QUARTER_TURNS)
    shape_controls(rig, names, body.H)
    place_collections(rig, names)
    if toggles['hand_spread'] and has_palm(toggles, opts):
        spread_influence(rig, opts)
    drive_body(rig, opts, toggles)
    if bl.parts_of(toggles[bl.OPTION]):
        bl.rig_halves(rig, body.H, toggles[bl.OPTION])
    bl.drop_sliders(rig, toggles[bl.OPTION])
    report = lr.upgrade(rig, limb_table(opts), stretch=toggles['stretch'], parent_switch=toggles['parent_switch'])
    keep_isolated_stretch(rig)
    rig.data[RECORD] = json.dumps(dict(bones=names, opts=opts, toggles=toggles, foot_width=foot_width))
    lr.set_mode(rig, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    view.objects.active = active
    return dict(report, bones=len(rig.data.bones), removed=stale)


# ---------------------------------------------------------------- the features on an existing rig
# A rig built before a feature, or a hand-made rig on the bone-name standard with limb_rig's snap data (the `Limb` data
# on its IK controls), gets the bones a fresh build makes: the same spec functions lay them out, from the rig's own bones
# instead of the guides. Each side on its own (no mirroring: an existing rig may be a little off), right bones' Z axes
# point the same way as the left ones', as a mirrored build makes them.
FEATURES = ('pole_lines', 'pole_follow', 'foot_bank', 'head_follow', 'neck_ik')
FEATURE_LABELS = dict(pole_lines='pole line', pole_follow='pole follow', foot_bank='foot bank / heel swivel',
                      head_follow='head / neck follow', neck_ik='neck IK', head_aim='head aim')
NECKS = ('Neck1', 'Neck')                # the neck's first bone: a build's, else a one-bone neck


def body_names(opts, toggles=None):
    """Every bone name a build with these options makes (laid out on the template; no guides needed)."""
    opts = resolve(opts)
    joints = derive(template_landmarks(opts), opts)
    points = {name: (joints[a], joints[b]) for name, a, b, _ in bone_specs(opts)}
    return Body(points, opts, dict(TOGGLES, **(toggles or {}))).names()


def rig_limbs(rig):
    """[(IK control, Limb data, is a leg)]: the rig's arms and legs with a pole (no part chains, no wing arms)."""
    out = []
    for pb in rig.pose.bones:
        if 'Limb' not in pb or 'IK_FK' not in pb or BC.is_wing_limb(pb.name):
            continue
        limb = json.loads(pb['Limb'])
        names = limb.get('chain', []) + [limb.get('pole'), limb.get('tip')]
        if not limb.get('part') and len(limb.get('chain', [])) > 1 and all(n in rig.data.bones for n in names):
            out.append((pb.name, limb, lr.is_leg(names)))
    return out


def rig_height(rig):
    """Floor to the top of the Head (a build's height: the guides' top joint), else to the highest bone."""
    zs = [v.z for b in rig.data.bones for v in (b.head_local, b.tail_local)]
    top = rig.data.bones['Head'].tail_local.z if 'Head' in rig.data.bones else max(zs, default=DEFAULT_HEIGHT)
    return top - min(zs) if zs else DEFAULT_HEIGHT


def pole_joint(E, pose, chain, pole):
    """The chain bone whose head is the bending joint: of the bones the IK may bend (not a twist bone with X and Z
    locked), the one bent most off its parent at rest (a split thigh's Thigh2 hardly is, the Shin is); a straight chain:
    the one nearest the pole's foot on the chain's top-to-end line (the pole sits square off its joint)."""
    top, end = E[chain[0]].head, E[chain[-1]].tail
    line = (end - top).normalized()
    foot = top + line * (E[pole].head - top).dot(line)
    free = [n for n in chain[1:] if not (pose[n].lock_ik_x and pose[n].lock_ik_z)] or chain[1:]
    bend = {n: E[n].vector.angle(E[n].parent.vector, 0.0) for n in free}
    most = max(bend.values())
    return min((n for n in free if bend[n] > most - STRAIGHT), key=lambda n: (E[n].head - foot).length)


def ik_chains_across(rig, child):
    """IK constraints whose chain runs from `child` into its parent: a bone put between them would join the chain."""
    parent = rig.data.bones[child].parent
    return [f'{pb.name} {c.name}' for pb in rig.pose.bones for c in pb.constraints if c.type == 'IK'
            and parent and {child, parent.name} <= {x.name for x in lr.ik_chain(pb, c)}]


class Feature:
    """One feature on one limb (or the head): its bones in edit mode, constraints and switches, then drivers."""

    def __init__(self, kind, owner, edit, rig_it, drive):
        self.kind, self.owner, self.edit, self.rig_it, self.drive = kind, owner, edit, rig_it, drive

    def line(self):
        return f'{self.owner}: {FEATURE_LABELS[self.kind]}'


def limb_features(rig, ctrl, limb, leg, which):
    """(features to add, skipped lines) for one limb."""
    B, P = rig.data.bones, rig.pose.bones
    pole, chain, side = limb['pole'], limb['chain'], rn.side_of(ctrl)
    out, skipped = [], []
    line = pole_line_name(pole)
    if 'pole_lines' in which and not (line in B and 'Stretch To' in P[line].constraints):
        def edit_line(A, pole=pole, chain=chain):
            E = A.edit_bones
            joint = pole_joint(E, rig.pose.bones, chain, pole)
            make_spec_bone(A, pole_line_spec(pole, E[joint].head, E[pole].head, E[joint].parent.name))
        out.append(Feature('pole_lines', ctrl, edit_line, lambda: rig_pole_line(rig, line, pole),
                           lambda: drive_pole_line(rig, line, ctrl)))
    body = pole_follow_body(ctrl, leg)
    if 'pole_follow' in which and not ('Pole Follow' in P[pole].constraints and POLE_FOLLOW in P[ctrl]):
        lacking = [n for n in list(body) + [rn.ROOT] if n not in B]
        if lacking:
            skipped.append(f'{ctrl}: pole follow needs {", ".join(lacking)}')
        else:
            def edit_follow(A, pole=pole):
                A.edit_bones[pole].use_connect, A.edit_bones[pole].parent = False, None    # the Armature constraint parents it
            out.append(Feature('pole_follow', ctrl, edit_follow, lambda: rig_pole_follow(rig, pole, ctrl, body),
                               lambda: pole_follow_drivers(rig, pole, ctrl, body)))
    if leg and 'foot_bank' in which and not (rn.helper(ctrl, 'BankIn') in B and FOOT_BANK in P[ctrl]):
        pivots = [rn.helper(ctrl, job) for job in ('RollHeel', 'RollBall', 'RollTip')]
        if not all(n in B for n in pivots):
            skipped.append(f'{ctrl}: foot bank needs the foot roll pivots {", ".join(pivots)}')
        else:
            def edit_bank(A, ctrl=ctrl, side=side, pivots=pivots):
                E = A.edit_bones
                heel, ball, tip = (E[n].head for n in pivots)
                fwd = flat(ball - heel).normalized()
                out_dir = UP.cross(fwd).normalized() * (-1 if side == 'R' else 1)
                roll = E.get(rn.with_side(rn.helper(rn.left('Toes'), 'Roll'), side)) if side else None
                across = [b.head.dot(out_dir) for b in (roll.children if roll else []) if b.use_deform]
                specs = bank_specs(ctrl, heel.copy(), fwd, out_dir, foot_half_width(across, None, tip - heel), rig_height(rig))
                for s in specs:
                    make_spec_bone(A, s)
                E[pivots[0]].use_connect, E[pivots[0]].parent = False, E[specs[-1].name]
            out.append(Feature('foot_bank', ctrl, edit_bank, lambda: rig_foot_bank(rig, ctrl),
                               lambda: drive_foot_bank(rig, ctrl)))
    return out, skipped


def head_features(rig, which):
    B = rig.data.bones
    if 'head_follow' not in which or (NECK_SOCKET in B and HEAD_SOCKET in B and HEAD_FOLLOW in rig.pose.bones['Head']):
        return [], []
    neck = next((n for n in NECKS if n in B), None)
    if not (neck and 'Head' in B and rn.ROOT in B and B[neck].parent and B['Head'].parent):
        return [], [f'head / neck follow needs {rn.ROOT}, a neck ({" or ".join(NECKS)}) and Head with parents']
    across = ik_chains_across(rig, neck) + ik_chains_across(rig, 'Head')
    if across:
        return [], [f'head / neck follow: left out, a socket would join the IK chain of {", ".join(across)}']

    def edit_sockets(A):
        E = A.edit_bones
        root, kids = E[rn.ROOT], (E[neck], E[HEAD_AIM_BONE if HEAD_AIM_BONE in E else 'Head'])   # the head socket goes under the aim bone's parent
        specs = socket_specs(root.tail - root.head, root.z_axis,
                             *((k.head, k.parent.name, (k.head - k.parent.tail).length < 1e-5) for k in kids))
        for kid, s in zip(kids, specs):
            make_spec_bone(A, s)
            kid.use_connect, kid.parent = False, E[s.name]
    def rig_it():
        rig_head_follow(rig)
        if POINT_AWAY in rig.pose.bones[LOOK_FOCUS].constraints if LOOK_FOCUS in rig.pose.bones else False:
            aim_point_away(rig)                  # the new socket is the head's base now
    return [Feature('head_follow', 'Head', edit_sockets, rig_it, lambda: drive_head_follow(rig))], []


def aim_features(rig, which):
    """A Head Aim an older build left on the Head moves to MCH-HeadAim (made here) with Look Roll, Point Away on
    HeadLookFocus and the HeadLookBase's Copy Rotation of the Head gone. Nothing moves at rest."""
    P = rig.pose.bones
    if not ({'neck_ik', 'head_follow'} & set(which)) or 'Head' not in P or LOOK_FOCUS not in P:
        return [], []
    old = P['Head'].constraints.get(HEAD_AIM_CONSTRAINT)
    if not old or HEAD_AIM_BONE in rig.data.bones:
        return [], []
    axis = old.track_axis

    def rig_it():
        rig_head_aim(rig, 'Head', axis)
        base = P.get('HeadLookBase')
        for c in [c for c in (base.constraints if base else []) if c.type == 'COPY_ROTATION' and c.subtarget == 'Head']:
            base.constraints.remove(c)
    return [Feature('head_aim', 'Head', head_aim_bone, rig_it, lambda: drive_head_aim(rig))], []


def neck_chain(rig):
    """The neck bones from the chest up (root first): the Head's parents named Neck..., MCH sockets skipped."""
    chain, bone = [], rig.data.bones['Head'].parent
    while bone and (rn.is_helper(bone.name) or rn.plain(bone.name).startswith('neck')):
        if not rn.is_helper(bone.name):
            chain.insert(0, bone.name)
        bone = bone.parent
    return chain


def neck_features(rig, which):
    """Neck IK as a build makes it. A rig with its own IK-Head (an IK on the last neck bone aimed at it) keeps it: it
    gets the parent switch (starting on what it hangs on now; none when that isn't Root, Pelvis or Chest), IK_FK at 1,
    the Head's IK Rotation after its look constraints and the snap data, so it poses as before."""
    B, P = rig.data.bones, rig.pose.bones
    if 'neck_ik' not in which:
        return [], []
    if 'Head' not in B or rn.ROOT not in B:
        return [], [f'neck IK needs {rn.ROOT} and Head']
    chain = neck_chain(rig)
    if not chain:
        return [], ['neck IK needs neck bones (Neck1, Neck2 ...) above the Head']
    if IK_HEAD in P and 'IK_FK' in P[IK_HEAD] and 'Limb' in P[IK_HEAD] and IK_ROTATION in P['Head'].constraints:
        return [], []
    own = next((c for c in P[chain[-1]].constraints if c.type == 'IK'), None)
    if own and own.subtarget != IK_HEAD:
        return [], [f'neck IK: left out, {chain[-1]} has its own IK to {own.subtarget or "nothing"} (a hand-made head '
                    f'set-up; rename that control to {IK_HEAD} to adopt it)']
    if IK_HEAD in B and not own:
        return [], [f'neck IK: left out, {IK_HEAD} is there but no IK on {chain[-1]} aims at it']
    if own:
        chain = [b.name for b in reversed(lr.ik_chain(P[chain[-1]], own))]
        turn = B['Head'].matrix_local.to_quaternion().rotation_difference(B[IK_HEAD].matrix_local.to_quaternion()).angle
        if turn > 1e-4:
            return [], [f'neck IK: left out, {IK_HEAD} rests turned {math.degrees(turn):.1f} degrees off the Head '
                        '(the Head would turn copying it)']
    old_parent = B[IK_HEAD].parent.name if own and B[IK_HEAD].parent else None
    switch = not own or old_parent is None or old_parent in HEAD_IK_PARENTS
    notes = [] if switch else [f'neck IK: {IK_HEAD} keeps its parent {old_parent} (no parent switch: it follows only '
                               f'{", ".join(HEAD_IK_PARENTS)})']
    parents = head_ik_parents(rig)

    def edit_head_ik(A):
        E = A.edit_bones
        if own:
            if switch:
                make_spec_bone(A, spec_bone(HEAD_IK_PARENT, E[IK_HEAD].head, E[IK_HEAD].tail))[0].roll = E[IK_HEAD].roll
                E[IK_HEAD].use_connect, E[IK_HEAD].parent = False, E[HEAD_IK_PARENT]
            return
        head, end = E['Head'], E[chain[-1]].tail.copy()
        for s in head_ik_specs(end, head.tail - head.head, HEAD_IK_PARENT):
            make_spec_bone(A, s)[0].roll = head.roll

    def rig_it():
        if not own:
            ik(rig, chain[-1], IK_HEAD, len(chain))
        rig_neck_ik(rig, chain, parents, (old_parent or rn.ROOT) if own else HEAD_IK_DEFAULT)
    return [Feature('neck_ik', 'Head', edit_head_ik, rig_it, lambda: drive_neck_ik(rig))], notes


def plan_features(rig, which=FEATURES):
    """(features still to add, skipped lines): nothing for what the rig has already."""
    features, skipped = [], []
    for ctrl, limb, leg in rig_limbs(rig):
        found, why = limb_features(rig, ctrl, limb, leg, which)
        features += found
        skipped += why
    for plan in (head_features, neck_features, aim_features):
        found, why = plan(rig, which)
        features += found
        skipped += why
    return features, skipped


def add_features(rig, which=FEATURES):
    """Pole lines, Pole Follow, Foot Bank + Heel Swivel, Head / Neck Follow and Neck IK (`which`: any of FEATURES) on an
    existing rig, as build_body makes them. Nothing moves at rest; with PoleFollow 0, FootBank / HeelSwivel 0, Head /
    NeckFollow 1 and a new IK-Head's IK_FK 0 the rig poses as before (an adopted IK-Head poses as before at IK_FK 1). What the rig has already is left alone: a re-run does nothing. An older Knee Follow is
    replaced by Pole Follow (its value kept). The rig must be in the view layer; it is left in the mode it was in.
    Returns {'done': [lines], 'added': [bone names], 'skipped': [lines]}."""
    features, skipped = plan_features(rig, which)
    if not features:
        return dict(done=[], added=[], skipped=skipped)
    view = bpy.context.view_layer
    active, mode = view.objects.active, rig.mode
    view.objects.active = rig
    lr.set_mode(rig, 'EDIT')
    mirror, rig.data.use_mirror_x = rig.data.use_mirror_x, False
    before = set(rig.data.edit_bones.keys())
    try:
        for f in features:
            f.edit(rig.data)
        added = sorted(set(rig.data.edit_bones.keys()) - before)
    finally:
        rig.data.use_mirror_x = mirror
        lr.set_mode(rig, 'POSE')
    for f in features:
        f.rig_it()
    shape_controls(rig, added, rig_height(rig))
    place_collections(rig, added)
    for f in features:
        f.drive()
    lr.set_mode(rig, mode if mode in ('OBJECT', 'POSE') else 'OBJECT')
    view.objects.active = active
    return dict(done=[f.line() for f in features], added=added, skipped=skipped)
