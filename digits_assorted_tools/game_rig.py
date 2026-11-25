# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/game_rig.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Game Rig: a SIMPLE game-ready copy of a character, the source rig and meshes untouched.

Make Game Rig builds collection "<rig> Game" with one new armature "<rig>_Game" (single root, every bone a deform
bone, no constraints / drivers / shapes / B-bones, one bone collection) and a copy of every visible mesh the rig or
its part rigs (tails, ears, hair, wings) deform: Mirror applied, one Armature modifier on the new rig, Subdivision
kept but off, at most 4 weights per vertex. The pose is never read: bones come from their REST matrices.

Which bones stay is decided by structure (the follow tree: parents, or the Armature / Child Of constraint target of
a parentless bone, then deform flags and bend angles), with names only as hints. Every dropped deform bone's weight
goes to the nearest kept bone it follows (the build record's `heir` when the walk finds none). The names of the kept
bones come from rig_names (one table per engine; Generic keeps the source names). Logic only, the card is
game_rig_ui.py in Digit's Assorted Tools. This file is the ONE source; sync_shared.py copies it into the add-on.

Optional for callers with more needs (Scripts/vrchat): `jaw=False` sends the jaw and everything on it to the head,
`forearm_split=True` keeps every forearm bone, `extras` keeps named bones the plan would drop (a second pair of arms,
wing bones, a helper), `meshes` picks the meshes, `apply_stack=True` bakes every modifier except Armature and
Subdivision into the copies, not just Mirror.

B-Bone Chain Builder chains (bbone_builder; any chain or loop, e.g. Digit's wings) become TWO game bones a chain,
<Name>1 root -> mid and <Name>2 mid -> tip, under the chain's parent bone (ChainLine): root = the point nearest the
parent bone, tip = the top-level point farthest from it, mid = the middle of the chain (a loop: its outline's centre;
a web point near there wins). The chain's B-bone weights split between the two by where each vertex lies along
root -> mid -> tip, blended wide across the mid joint (CHAIN_BLEND). The chain's base (its points nearest the body)
is held by the body: chain vertices near it take the weights of the nearest body vertices, fading out over CHAIN_HOLD
(soften_chains), so the base follows the spine; then the chain vertices' weights are smoothed in space, body vertices
untouched. A chain with a bone in `extras` stays the caller's business.
`follow=True` (for baking an animation): every game bone copies its source bone, a chain's bones run from its root
control over a helper MCH-<Name>Mid (Armature constraint on the chain's controls) to its tip control. Without it the
game rig has no constraints.
"""
import math
import re
from collections import namedtuple
from itertools import groupby

import bpy
from mathutils import Matrix, Vector

try:                                     # inside the add-on package
    from . import bbone_builder as BB, bone_collections as BC, rig_names
    from .face_rig_core import built_info
except ImportError:                      # Scripts/batch_tools copy
    import bbone_builder as BB
    import bone_collections as BC
    import rig_names
    from face_rig_core import built_info

PART_CHAIN = 4                 # bones kept of one part chain (a tail, one ear)
PART_BONES = 5                 # bones kept of a whole part rig
JOINT_EPS = 1e-4               # metres: a bone ending where another starts (stand_in)
LIMB_BEND = math.radians(25)   # a limb joint bent more than this in rest is a joint of the game limb
MAX_INFLUENCES = 4
SIDE_EPS = 1e-3
TAG = "game_rig_source"        # custom property on what a run made: the source rig's name
HAND, FOOT = r"^(hand|wrist|paw)$", r"^(foot|ankle)$"
FOLLOW_CONSTRAINTS = ('CHILD_OF', 'COPY_TRANSFORMS', 'COPY_LOCATION')
FINGER_WORDS = {'thumb': 'thumb', 'index': 'index|pointer', 'middle': 'middle', 'ring': 'ring',
                'pinky': 'pinky|pinkie|little|small'}   # some rigs' pinky is finger_small
JAW = r"^jaw\d*$|lowerjaw|^muzzlelower$|mandible"
EYE = r"^eye1?$|^eyeball$"    # the eyeball: Eye, or the first bone of an Eye1 / Eye2 chain
FACE_WORDS = r"eye|lid|lash|brow|lip|jaw|tongue|tounge|teeth|tooth|muzzle|snout|nose|nostril|cheek|snarl|puff|mouth|beak"
PART_KINDS = {'Tail': 'tail', 'Ears': 'ear', 'Hair': 'hair', 'Wings': 'wing'}
# A bone to keep besides the plan: source rig + bone, its final name, and the (rig, bone) source key of its parent when
# the follow tree's answer isn't wanted. A rig named in an Extra is not thinned as a part: only its Extras stay.
Extra = namedtuple('Extra', 'rig bone name parent', defaults=(None,))
CHAIN_BLEND = 0.8              # a game chain's two bones blend over this share of the shorter one, centred on the mid joint
CHAIN_BASE = 0.05              # chain points no farther from the body than its root + this share of the span: its base
CHAIN_HOLD = 0.13              # chain vertices this near the base (share of the root -> tip span) fade to the body's weights
CHAIN_BODY_NEAR = 6            # ... the mean (by 1 / distance) of this many nearest body vertices within that reach
CHAIN_SMOOTH = (4, 0.03)       # then spatial smoothing over the chain vertices: passes, reach (share of the span)
CHAIN_WEB_SNAP = 0.25          # a web point this near the chain's middle (share of root -> tip) is the mid point


# ---------------------------------------------------------------- rest positions (never the current pose)
def root_rig(ob):
    """The main rig a part rig hangs on (an armature parented to an armature), or ob itself."""
    while ob.parent and ob.parent.type == 'ARMATURE':
        ob = ob.parent
    return ob


def family(main):
    return [o for o in bpy.data.objects if o.type == 'ARMATURE' and root_rig(o) == main]


def rest_world(ob):
    """ob's world matrix as if every rig were in its rest pose (a part parented to a bone follows that bone's rest)."""
    if ob.parent is None:
        return ob.matrix_basis.copy()
    base = rest_world(ob.parent)
    bone = ob.parent.data.bones.get(ob.parent_bone) if ob.parent_type == 'BONE' and ob.parent.type == 'ARMATURE' else None
    if bone:
        base = base @ bone.matrix_local @ Matrix.Translation((0, bone.length, 0))
    return base @ ob.matrix_parent_inverse @ ob.matrix_basis


# ---------------------------------------------------------------- the source skeleton: who follows whom
class Info:
    """What the plan needs of one source bone (plain values: Blender objects can go stale during a run)."""

    def __init__(self, bone):
        self.parent = bone.parent.name if bone.parent else None
        self.deform, self.length, self.matrix = bone.use_deform, bone.length, bone.matrix_local.copy()
        self.chain = bone.get(BB.CHAIN_KEY)      # the B-Bone Chain Builder chain it belongs to, or None


def constraint_targets(con):
    """(object, bone name, weight) a constraint ties its bone to."""
    if con.type == 'ARMATURE':
        return [(t.target.name, t.subtarget, t.weight * con.influence) for t in con.targets if t.target]
    if con.type in FOLLOW_CONSTRAINTS and getattr(con, 'target', None):
        return [(con.target.name, con.subtarget, con.influence)]
    return []


class Skeleton:
    """Bones of the main rig and its part rigs, keyed (rig name, bone name), in the main rig's space."""

    def __init__(self, main):
        self.main = main.name
        rigs = family(main)
        self.bones = {(r.name, b.name): Info(b) for r in rigs for b in r.data.bones}
        self.heirs = built_info(main).get('heir', {})
        inverse = rest_world(main).inverted()
        self.to_main = {r.name: inverse @ rest_world(r) for r in rigs}
        self.world = rest_world(main)
        self.regions = {r.name: PART_KINDS.get(BC.rig_region(r)) for r in rigs}
        self.hung = {r.name: (r.parent.name, r.parent_bone) if r.parent_type == 'BONE' else None for r in rigs}
        self.ties = {(r.name, pb.name): self.strongest_target(r, pb) for r in rigs for pb in r.pose.bones
                     if pb.parent is None}
        self.aimed = {}        # key -> bones with a constraint aimed at it (IK target, Copy, Track...)
        for r in rigs:
            for pb in r.pose.bones:
                for con in pb.constraints:
                    target, sub = getattr(con, 'target', None), getattr(con, 'subtarget', '')
                    if target is not None and sub and con.enabled:
                        self.aimed.setdefault((target.name, sub), []).append((r.name, pb.name))
        self.virtual = {}      # key -> (matrix, length, parent key): bones made up by the plan (root, toes)
        self.merged = {}       # key -> key whose bone takes its weight (every toe -> the one toes bone)
        self.torso = []        # pelvis ... head, where parts without a bone parent attach
        self.names = {}        # key -> final name of a virtual bone no engine names (a chain's Wing1.L)
        self.lines = []        # ChainLine per B-Bone Chain Builder chain that becomes two game bones
        self._follow, self._kids, self._under = {}, None, None

    def strongest_target(self, rig, pb):
        """The bone a parentless bone is tied to: its strongest Armature target, or a Child Of / Copy target."""
        best, strongest = None, 0
        for con in pb.constraints:
            if con.enabled and con.influence > 0:
                for target, sub, weight in constraint_targets(con):
                    if weight > strongest and (target, sub) != (rig.name, pb.name):
                        best, strongest = (target, sub), weight
        return best

    def deform_keys(self, rig_name, chains=False):
        """Deform bones of a rig; B-Bone Chain Builder bones only with `chains` (the plan treats them as ChainLines)."""
        return [k for k, b in self.bones.items() if k[0] == rig_name and b.deform and (chains or not b.chain)]

    def matrix(self, key):
        return self.virtual[key][0] if key in self.virtual else self.to_main[key[0]] @ self.bones[key].matrix

    def length(self, key):
        return self.virtual[key][1] if key in self.virtual else self.bones[key].length

    def head(self, key):
        return self.matrix(key).translation

    def direction(self, key):
        return self.matrix(key).col[1].xyz

    def side(self, key):
        x = self.head(key).x
        return 'L' if x > SIDE_EPS else 'R' if x < -SIDE_EPS else ''

    def attach(self, rig_name):
        """The main-rig bone a part rig hangs on: its parent bone, else the torso bone nearest to its first bone."""
        hung = self.hung[rig_name]
        if hung in self.bones:
            return hung if self.bones[hung].deform else self.follow(hung)
        first = next(iter(k for k in self.bones if k[0] == rig_name), None)
        if first is None or not self.torso:
            return None
        return min(self.torso, key=lambda k: (self.head(k) - self.head(first)).length)

    def follow(self, key):
        """The deform bone this bone moves with (cached)."""
        if key not in self._follow:
            self._follow[key] = self._walk(key)
        return self._follow[key]

    def _walk(self, key):
        """Nearest deform ancestor, non-deform parents skipped; a parentless bone goes by its constraint target, a
        part rig's root bone by the bone the part hangs on. None = it follows nothing (the root). Under a non-deform
        parent, that parent's deform child ending where this bone starts stands in for it (Bendy Limbs: the Shin
        follows DEF-Thigh2, DEF-Thigh2 follows DEF-Thigh1, both under the non-deform Thigh)."""
        seen = {key}
        while True:
            parent = self.bones[key].parent
            if parent:
                up = (key[0], parent)
                key = up if self.bones[up].deform else self.stand_in(up, key) or up
            else:
                rig_name = key[0]
                key = self.ties.get(key)
                if key is None and rig_name != self.main:
                    key = self.attach(rig_name)
                if key is None:
                    return None
            if key in seen:
                return None
            seen.add(key)
            if self.bones[key].deform:
                return key

    def stand_in(self, parent, child):
        """The deform child of non-deform `parent` whose tail is `child`'s head (a Bendy Limbs half), or None."""
        if self._under is None:
            self._under = {}
            for key, bone in self.bones.items():
                if bone.parent:
                    self._under.setdefault((key[0], bone.parent), []).append(key)
        start = self.head(child)
        return next((k for k in self._under.get(parent, ()) if k != child and self.bones[k].deform
                     and (self.head(k) + self.direction(k) * self.length(k) - start).length < JOINT_EPS), None)

    def children(self):
        """follow-children of every deform bone, in bone order."""
        if self._kids is None:
            self._kids = {}
            for key, bone in self.bones.items():
                up = self.follow(key) if bone.deform else None
                if up:
                    self._kids.setdefault(up, []).append(key)
        return self._kids

    def descendants(self, key):
        found, todo = [], list(self.children().get(key, []))
        while todo:
            found.append(todo.pop(0))
            todo += self.children().get(found[-1], [])
        return found

    def ancestor(self, key, kept):
        """Nearest kept bone above `key` (virtual bones know their parent), or None."""
        up = self.virtual[key][2] if key in self.virtual else self.follow(key)
        seen = set()
        while up is not None and up not in kept and up not in seen:
            seen.add(up)
            up = self.follow(up)
        return up

    def target(self, key, kept, root):
        """The kept bone that takes the weight of deform bone `key`: itself, else the nearest kept bone it follows,
        else the kept bone it drives (a weighted IK control), else the root."""
        start, seen = key, set()
        while key is not None and key not in seen:
            seen.add(key)
            if key in self.merged:
                return self.merged[key]
            if key in kept:
                return key
            key = self.follow(key)
        return self.driven(start, kept) or root

    def driven(self, key, kept):
        """The kept bone a control moves: the first bone (breadth first down the control's parent tree) with a
        constraint aimed at it, or the kept bone that bone follows. None if it moves no kept bone."""
        under = {}
        for k, bone in self.bones.items():
            if bone.parent:
                under.setdefault((k[0], bone.parent), []).append(k)
        todo, seen = [key], {key}
        while todo:
            current = todo.pop(0)
            for owner in self.aimed.get(current, ()):
                up, chain = owner, set()
                while up is not None and up not in kept and up not in chain:
                    chain.add(up)
                    up = self.follow(up)
                if up is not None and up in kept:
                    return up
            for child in under.get(current, ()):
                if child not in seen:
                    seen.add(child)
                    todo.append(child)
        return None


# ---------------------------------------------------------------- which bones stay (entries: key, part, side, number)
def plain(key):
    return rig_names.plain(key[1])


def torso_path(skel):
    """Deform bones from the pelvis (the top of the deform tree) down to the head."""
    deform = skel.deform_keys(skel.main)
    heads = [k for k in deform if re.search(r"^head$", plain(k))]
    path = [heads[0] if heads else max(deform, key=lambda k: skel.head(k).z)]
    while skel.follow(path[-1]) and skel.follow(path[-1]) not in path:
        path.append(skel.follow(path[-1]))
    return path[::-1]


def thin(keys):
    """Of each run of bones with the same name stem (Neck1, Neck2; torso_1..3): the first, and the last when 3 or more."""
    out = []
    for _, run in groupby(keys, key=lambda k: rig_names.bare_stem(k[1])):
        run = list(run)
        out += run[:1] if len(run) < 3 else [run[0], run[-1]]
    return out


def torso_entries(skel, path):
    entries = [(path[0], 'pelvis', '', 1)]
    counts = {'spine': 0, 'neck': 0}
    for key in thin(path[1:-1]):
        part = 'neck' if 'neck' in plain(key) else 'spine'
        counts[part] += 1
        entries.append((key, part, '', counts[part]))
    if len(path) > 1:
        entries.append((path[-1], 'head', '', 1))
    return entries


def root_entry(skel, pelvis):
    """The one root: the source's own top bone above the pelvis, or a new one on the floor under it."""
    key = pelvis
    while skel.bones[key].parent:
        key = (key[0], skel.bones[key].parent)
    if key != pelvis:
        return (key, 'root', '', 1)
    floor = skel.head(pelvis)
    matrix = Matrix.Translation((floor.x, floor.y, 0)) @ Matrix.Rotation(math.pi / 2, 4, 'X')
    key = (skel.main, "Root")
    skel.virtual[key] = (matrix, max(floor.z * 0.2, 0.05), None)
    return (key, 'root', '', 1)


def limb_joints(skel, rest):
    """The bones of a limb worth keeping: the first, the ones where it bends in rest, else the middle one."""
    if len(rest) <= 2:
        return rest
    dirs = [skel.direction(k) for k in rest]
    bent = [k for k, a, b in zip(rest[1:], dirs, dirs[1:]) if a.angle(b, 0) > LIMB_BEND]
    if bent:
        return rest[:1] + bent
    starts, total = [], 0.0
    for key in rest:
        starts.append(total)
        total += skel.length(key)
    middle = min(range(1, len(rest)), key=lambda i: abs(starts[i] - total / 2))
    return [rest[0], rest[middle]]


def limb_entries(skel, tip, leg, torso, forearm_split=False):
    """Shoulder (arms), upper, lower (+ hock on legs) and the hand / foot, from the torso down to `tip`.
    forearm_split: every bone between elbow and hand stays (a straight arm otherwise keeps one forearm bone)."""
    chain = [tip]
    while skel.follow(chain[-1]) and skel.follow(chain[-1]) not in torso + chain:
        chain.append(skel.follow(chain[-1]))
    chain = [k for k in reversed(chain) if not re.search(r"heel|heal", plain(k))]
    if leg and len(chain) > 2 and re.search(r"^hips?$", plain(chain[0])):
        chain = chain[1:]                     # a hip bone is the pelvis' business
    lead = chain[:1] if len(chain) > 2 and re.search(r"shoulder|clav|collar", plain(chain[0])) else []
    side = skel.side(tip)
    parts = ('thigh', 'calf', 'hock') if leg else ('upperarm', 'lowerarm')
    between = chain[len(lead):-1]
    if forearm_split and not leg and len(between) == 3:
        parts, joints = ('upperarm', 'lowerarm', 'lowerarm2'), between
    else:
        joints = limb_joints(skel, between)[:len(parts)]
    return ([(k, 'clavicle', side, 1) for k in lead] + [(k, p, side, 1) for k, p in zip(joints, parts)]
            + [(tip, 'foot' if leg else 'hand', side, 1)])


def finger_entries(skel, hand):
    """Every segment of every finger below a hand (up to 3 each), numbered from the hand."""
    side, found, segment = skel.side(hand), [], {}
    for key in skel.descendants(hand):
        finger = next((f for f, words in FINGER_WORDS.items() if re.search(words, plain(key))), None)
        if finger:
            segment[key] = segment.get(skel.follow(key), 0) + 1
            if segment[key] <= 3:
                found.append((key, finger, side, segment[key]))
    return found


def toes_entries(skel, foot):
    """One toes bone: the only toe, or (several toes) a new bone at their average with every toe's weight."""
    toes = [k for k in skel.children().get(foot, []) if not re.search(r"heel|heal", plain(k))]
    side = skel.side(foot)
    if len(toes) < 2:
        return [(k, 'toes', side, 1) for k in toes]
    key = (foot[0], foot[1] + ".Toes")
    matrix = skel.matrix(toes[0]).copy()
    matrix.translation = sum((skel.head(k) for k in toes), Vector()) / len(toes)
    skel.virtual[key] = (matrix, sum(skel.length(k) for k in toes) / len(toes), foot)
    for toe in toes:
        for member in [toe] + skel.descendants(toe):
            skel.merged[member] = key
    return [(key, 'toes', side, 1)]


def face_entries(skel, head, face, jaw=True):
    """Jaw (unless jaw=False) and eyes; with `face` also the brow bones (up to 3 a side) and the lip corner of each
    side."""
    deform = [k for k in skel.deform_keys(skel.main) if re.search(FACE_WORDS, plain(k))]
    entries = []
    for part, pattern in ((('jaw', JAW),) if jaw else ()) + (('eye', EYE),):
        top = [k for k in deform if re.search(pattern, plain(k)) and not (
            skel.follow(k) and re.search(pattern, plain(skel.follow(k))))]
        entries += [(k, part, skel.side(k) if part == 'eye' else '', 1) for k in top[:2 if part == 'eye' else 1]]
    if face:
        for side in 'LR':
            brows = sorted((k for k in deform if 'brow' in plain(k) and skel.side(k) == side),
                           key=lambda k: abs(skel.head(k).x))
            entries += [(k, 'brow', side, i + 1) for i, k in enumerate(sample(brows, 3))]
            lips = [k for k in deform if 'lip' in plain(k) and skel.side(k) == side]
            if lips:
                entries.append((max(lips, key=lambda k: abs(skel.head(k).x)), 'lipcorner', side, 1))
    return entries


def sample(chain, count):
    """`count` bones of a chain, evenly spread, first and last included."""
    if count >= len(chain):
        return chain
    if count == 1:
        return chain[:1]
    return [chain[round(i * (len(chain) - 1) / (count - 1))] for i in range(count)]


def part_entries(skel, rig_name, counts):
    """The chains of one part rig, each cut to PART_CHAIN bones, the whole part to PART_BONES (shared out evenly)."""
    part = skel.regions[rig_name]
    keys = skel.deform_keys(rig_name)
    kids = {k: [] for k in keys}
    roots = []
    for key in keys:
        up = skel.follow(key)
        (kids[up] if up in kids else roots).append(key)

    def size(key):
        return 1 + sum(size(k) for k in kids[key])

    def chain_from(start):
        chain = [start]
        while len(kids[chain[-1]]) == 1:
            chain.append(kids[chain[-1]][0])
        return chain, kids[chain[-1]]

    def allot(starts, budget, out):
        turns = {}

        def turn(key):                    # equal bones: left and right take turns when the budget runs out
            turns[skel.side(key)] = turns.get(skel.side(key), 0) + 1
            return turns[skel.side(key)]
        starts = sorted(starts, key=lambda k: (-size(k), turn(k)))[:budget]
        for start in starts:
            share = budget // len(starts)
            chain, branches = chain_from(start)
            picked = sample(chain, min(PART_CHAIN, share))
            out += picked
            allot(branches, share - len(picked), out)

    picked = []
    allot(roots, PART_BONES, picked)
    entries = []
    for key in picked:
        side = skel.side(key) if part in ('ear', 'wing') else ''
        counts[part, side] = counts.get((part, side), 0) + 1
        entries.append((key, part, side, counts[part, side]))
    return entries


def used_rigs(meshes, skel):
    names = {r.name for m in meshes for r in armature_targets(m) if r.name in skel.to_main}
    return [n for n in skel.to_main if n in names and n != skel.main]


def make_plan(skel, part_rigs, fingers=True, face=False, jaw=True, forearm_split=False, extras=()):
    """Every kept bone as (key, part, side, number), root first, a parent always before its children; `extras` (part
    None: their name comes from the Extra) last, and their rigs are not cut down as parts. B-Bone Chain Builder chains
    become two bones each (skel.lines)."""
    path = torso_path(skel)
    skel.torso = path
    entries = [root_entry(skel, path[0])] + torso_entries(skel, path)
    main_deform = skel.deform_keys(skel.main)
    for pattern, leg in ((HAND, False), (FOOT, True)):
        for tip in (k for k in main_deform if re.search(pattern, plain(k))):
            entries += limb_entries(skel, tip, leg, path, forearm_split)
            entries += toes_entries(skel, tip) if leg else (finger_entries(skel, tip) if fingers else [])
    entries += face_entries(skel, path[-1], face, jaw)
    counts = {}
    extra_rigs = {e.rig for e in extras}
    for rig_name in part_rigs:
        if rig_name not in extra_rigs:
            entries += part_entries(skel, rig_name, counts)
    skel.lines = chain_lines(skel, [skel.main] + list(part_rigs), extras)
    entries += chain_entries(skel, skel.lines, counts)
    entries += [((e.rig, e.bone), None, '', 1) for e in extras]
    seen = set()
    return [e for e in entries if not (e[0] in seen or seen.add(e[0]))]


def bone_names(plan, skel, engine, extras=()):
    """{key: final bone name}: the Extra's name, or the engine's name for its logical part (rig_names), else the source
    name; unique."""
    names, used = {}, set()
    fixed = {(e.rig, e.bone): e.name for e in extras}
    for key, part, side, index in plan:
        name = fixed.get(key) or (rig_names.game_name(engine, part, side, index) if part else None)
        name = name or skel.names.get(key) or key[1]
        while name in used:
            name += "_2"
        used.add(name)
        names[key] = name
    return names


# ---------------------------------------------------------------- B-Bone Chain Builder chains: two game bones each
def numbered(skel, rig_name, name_of):
    """Keys (rig, name_of(0)), (rig, name_of(1)) ... as long as the rig has them."""
    keys = []
    while (rig_name, name_of(len(keys))) in skel.bones:
        keys.append((rig_name, name_of(len(keys))))
    return keys


def segment_point(co, start, end):
    """(share 0..1 along start -> end, distance) of the point on the segment nearest to `co`."""
    along = end - start
    share = min(max((co - start).dot(along) / along.length_squared, 0.0), 1.0) if along.length_squared > 1e-12 else 0.0
    return share, (start + along * share - co).length


def aim_matrix(head, tail, up):
    """A bone matrix at `head` pointing at `tail`, its Z leaning to `up`."""
    y = (tail - head).normalized()
    x = y.cross(up)
    x = (x if x.length > 1e-6 else y.orthogonal()).normalized()
    matrix = Matrix((x, y, x.cross(y))).transposed().to_4x4()
    matrix.translation = head
    return matrix


def smooth_step(value):
    value = min(max(value, 0.0), 1.0)
    return value * value * (3 - 2 * value)


class ChainLine:
    """One built B-Bone Chain Builder chain as two game bones root -> mid -> tip (main-rig space). `controls` and
    `webs` are the chain's control keys; `mid_weights` {control key: weight} puts the mid point among them, so a
    helper following those controls stays at the chain's middle; `keys` are the two virtual game bone keys."""

    def __init__(self, skel, rig_name, name):
        self.rig, self.name = rig_name, name
        self.side = BB.chain_names(name)[1] or skel.side((rig_name, BB.control_name(name, 0)))
        self.controls = numbered(skel, rig_name, lambda k: BB.control_name(name, k))
        self.webs = numbered(skel, rig_name, lambda j: BB.web_control_name(name, j))
        self.loop = (rig_name, BB.deform_name(name, len(self.controls) - 1)) in skel.bones
        tops = [key for k, key in enumerate(self.controls) if (rig_name, BB.follow_name(name, k)) not in skel.bones]
        parent = skel.bones[tops[0]].parent if tops else None
        self.parent = (rig_name, parent) if parent else None
        cos = [skel.head(key) for key in self.controls]
        root = min(range(len(cos)), key=lambda i: self.body_distance(skel, cos[i]))
        self.root_bone = self.controls[root]
        self.tip_bone = max(tops or self.controls, key=lambda key: (skel.head(key) - cos[root]).length)
        self.mid_weights = self.middle(skel, cos, root, self.controls.index(self.tip_bone))
        self.root, self.tip = cos[root], skel.head(self.tip_bone)
        self.mid = sum((skel.head(key) * w for key, w in self.mid_weights.items()), Vector())
        self.up = BB.side_up(cos, self.side)
        self.keys = ((rig_name, name + "#1"), (rig_name, name + "#2"))
        self.span = max((self.tip - self.root).length, 1e-6)
        self.base = self.base_segments(skel, cos)

    def base_segments(self, skel, cos):
        """[(start, end)]: where the chain meets the body, the chain's segments between points no farther from the body
        than its root + CHAIN_BASE of the span (a lone point: a segment of no length)."""
        far = [self.body_distance(skel, co) for co in cos]
        near = [i for i, d in enumerate(far) if d <= min(far) + CHAIN_BASE * self.span]
        count = len(cos)
        pairs = [(i, (i + 1) % count) for i in near if (i + 1) % count in near and (self.loop or i + 1 < count)]
        joined = {i for pair in pairs for i in pair}
        return [(cos[a], cos[b]) for a, b in pairs] + [(cos[i], cos[i]) for i in near if i not in joined]

    def hold(self, co):
        """How much of a point's weight the body holds: 1 on the chain's base, fading (smoothstep) to 0 at CHAIN_HOLD."""
        gap = min(segment_point(co, start, end)[1] for start, end in self.base)
        return 1.0 - smooth_step(gap / (CHAIN_HOLD * self.span))

    def body_distance(self, skel, co):
        """How far a point is from the parent bone (no parent: from the centre line X = 0)."""
        if self.parent is None:
            return abs(co.x)
        head = skel.head(self.parent)
        return segment_point(co, head, head + skel.direction(self.parent) * skel.length(self.parent))[1]

    def middle(self, skel, cos, root, tip):
        """{control key: weight} of the mid point: a loop's outline centre (each point weighted by half its two edges),
        an open chain's point halfway along from root to tip; a web point near there instead."""
        count = len(cos)
        if self.loop:
            edges = [(cos[(i + 1) % count] - cos[i]).length for i in range(count)]
            total = sum(edges) or 1.0
            weights = {self.controls[i]: (edges[i - 1] + edges[i]) / (2 * total) for i in range(count)}
        else:
            step = 1 if tip >= root else -1
            path = list(range(root, tip + step, step))
            lengths = [(cos[b] - cos[a]).length for a, b in zip(path, path[1:])]
            half, walked, weights = sum(lengths) / 2, 0.0, {self.controls[root]: 1.0}
            for a, b, length in zip(path, path[1:], lengths):
                if walked + length >= half and length > 0:
                    share = (half - walked) / length
                    weights = {self.controls[a]: 1.0 - share, self.controls[b]: share}
                    break
                walked += length
        mid = sum((skel.head(key) * w for key, w in weights.items()), Vector())
        reach = CHAIN_WEB_SNAP * (cos[tip] - cos[root]).length
        near = min(self.webs, key=lambda key: (skel.head(key) - mid).length, default=None)
        if near is not None and (skel.head(near) - mid).length < reach:
            return {near: 1.0}
        return weights

    def bones(self):
        """[(key, rest matrix, length, parent key)] of the two game bones."""
        return [(self.keys[0], aim_matrix(self.root, self.mid, self.up), (self.mid - self.root).length, self.parent),
                (self.keys[1], aim_matrix(self.mid, self.tip, self.up), (self.tip - self.mid).length, self.keys[0])]

    def share(self, co):
        """((first key, weight share), (second key, weight share)) of a point by where it lies along root -> mid -> tip:
        all on the nearer bone, blended (smoothstep) over CHAIN_BLEND of the shorter bone's length centred on the mid joint."""
        first, near_first = segment_point(co, self.root, self.mid)
        second, near_second = segment_point(co, self.mid, self.tip)
        lengths = (self.mid - self.root).length, (self.tip - self.mid).length
        past = (first - 1.0) * lengths[0] if near_first <= near_second else second * lengths[1]   # metres past the mid
        on_second = smooth_step(past / max(CHAIN_BLEND * min(lengths), 1e-6) + 0.5)
        return (self.keys[0], 1.0 - on_second), (self.keys[1], on_second)


def chain_lines(skel, rigs, extras=()):
    """A ChainLine per built B-Bone Chain Builder chain (2+ controls) in `rigs` (names), except chains with a bone in
    `extras`."""
    claimed = {(e.rig, e.bone) for e in extras}
    chains = {}
    for key, bone in skel.bones.items():
        if bone.chain and key[0] in rigs:
            chains.setdefault((key[0], bone.chain), set()).add(key)
    lines = []
    for (rig_name, name), keys in sorted(chains.items()):
        if keys & claimed or (rig_name, BB.control_name(name, 1)) not in skel.bones:
            continue
        lines.append(ChainLine(skel, rig_name, name))
    return lines


def chain_entries(skel, lines, counts):
    """Plan entries of the chains' game bones (part = the chain's part when the engines name it, e.g. wing); the
    chain's deform bones send their weight to the nearer game bone in the bone map (the meshes split it, ChainLine)."""
    entries = []
    for line in lines:
        part, side = rig_names.pascal(BB.chain_names(line.name)[0]).lower(), line.side
        part = part if part in rig_names.PARTS else None
        for number, (key, matrix, length, parent) in enumerate(line.bones(), 1):
            skel.virtual[key] = (matrix, max(length, 1e-3), parent)
            skel.names[key] = BB.chain_bone(line.name, '', number)
            counts[part, side] = counts.get((part, side), 0) + 1
            entries.append((key, part, side, counts[part, side]))
        for key, bone in skel.bones.items():
            if key[0] == line.rig and bone.chain == line.name and bone.deform:
                centre = skel.head(key) + skel.direction(key) * bone.length / 2
                skel.merged[key] = max(line.share(centre), key=lambda item: item[1])[0]
    return entries


# ---------------------------------------------------------------- meshes and weights
def armature_targets(ob):
    return [m.object for m in ob.modifiers if m.type == 'ARMATURE' and m.object]


def source_meshes(context, main):
    """(meshes to copy, others): the visible meshes the main rig or one of its part rigs deforms."""
    rigs = set(family(main))
    meshes, others = [], []
    for ob in context.view_layer.objects:
        if ob.type == 'MESH' and ob.visible_get() and not ob.get(TAG):
            (meshes if rigs & set(armature_targets(ob)) else others).append(ob)
    return meshes, others


def merge_weights(ob, bone_of, to_rig=None):
    """Weights of vertex groups -> the bones in `bone_of` (group name -> bone name, or a function of the vertex's
    place in rig space (`to_rig`: object -> rig matrix) giving [(bone name, share)]; other groups are dropped), at most
    MAX_INFLUENCES strongest per vertex, normalised, empty groups gone."""
    bone_by_index = {g.index: bone_of.get(g.name) for g in ob.vertex_groups}
    to_rig = to_rig or Matrix.Identity(4)
    rows = []
    for vertex in ob.data.vertices:
        weights = {}
        for g in vertex.groups:
            target = bone_by_index.get(g.group)
            if not target or g.weight <= 0:
                continue
            for bone, share in (target(to_rig @ vertex.co) if callable(target) else ((target, 1.0),)):
                weights[bone] = weights.get(bone, 0.0) + g.weight * share
        top = [item for item in sorted(weights.items(), key=lambda item: -item[1])[:MAX_INFLUENCES] if item[1] > 0]
        total = sum(w for _, w in top)
        rows.append([(b, w / total) for b, w in top])
    ob.vertex_groups.clear()
    groups = {}
    for index, row in enumerate(rows):
        for bone, weight in row:
            if bone not in groups:
                groups[bone] = ob.vertex_groups.new(name=bone)
            groups[bone].add([index], weight, 'REPLACE')


def group_targets(skel, ob, plan, names):
    """{vertex group name: game bone name} for a source mesh: deform bones of the rigs it uses go to the kept bone
    that takes their weight; a ChainLine's B-bones to a split between its two game bones by the vertex's place."""
    kept = {e[0] for e in plan}
    root = plan[0][0]
    line_of = {(line.rig, line.name): line for line in skel.lines if line.keys[0] in kept}
    out = {}
    for rig in armature_targets(ob):
        for group in ob.vertex_groups:
            key = (rig.name, group.name)
            if key in skel.bones and skel.bones[key].deform and group.name not in out:
                line = line_of.get((key[0], skel.bones[key].chain))
                out[group.name] = chain_split(line, names) if line else names[skel.target(key, kept, root)]
    return out


def chain_split(line, names):
    """The weight split of a ChainLine by place, in game bone names."""
    return lambda co: [(names[key], share) for key, share in line.share(co)]


def soften_chains(objects, lines, names, rig, to_rig):
    """The game meshes' chain vertices (weighted to a ChainLine's game bones): near the chain's base they fade to the
    spine's weights at that spot (ChainLine.hold): the nearest body vertices' weights on the chain bone's ancestors in
    the game `rig` (Chest, Spine, Hips), renormalised, so hair or a shoulder near the base doesn't pull it. Then their
    weights are smoothed in space among themselves (CHAIN_SMOOTH), top MAX_INFLUENCES, normalised. Other vertices keep
    theirs. `to_rig`: object -> main-rig space matrix. Returns how many vertices changed."""
    try:
        from . import rig_weights as rw
    except ImportError:
        import rig_weights as rw
    line_of = {names[key]: line for line in lines for key in line.keys}
    chain, body = [], []                   # (object, vertex index, rig-space point, {bone: weight})
    for ob in objects:
        bone_of, matrix = {g.index: g.name for g in ob.vertex_groups}, to_rig(ob)
        for vertex in ob.data.vertices:
            row = {bone_of[g.group]: g.weight for g in vertex.groups if g.weight > 0}
            if row:
                (chain if line_of.keys() & row.keys() else body).append((ob, vertex.index, matrix @ vertex.co, row))
    if not chain:
        return 0
    spines = {line.name: spine_holds(body, rig.data.bones[names[line.keys[0]]]) for line in lines}
    rows = []
    for _, _, co, row in chain:
        line = line_of[max((b for b in row if b in line_of), key=row.get)]
        held, (tree, holds) = line.hold(co), spines[line.name]
        near = tree.find_n(co, CHAIN_BODY_NEAR) if held > 0 and holds else []
        near = [(1.0 / max(d, 1e-6), holds[k]) for _, k, d in near if d <= CHAIN_HOLD * line.span]
        if near:
            total = sum(w for w, _ in near)
            row = {b: w * (1.0 - held) for b, w in row.items()}
            for w, hold in near:
                for b, x in hold.items():
                    row[b] = row.get(b, 0.0) + held * x * w / total
        rows.append(row)
    bones = sorted({b for row in rows for b in row})
    passes, reach = CHAIN_SMOOTH
    smoothed = rw.spatial_smooth([item[2] for item in chain], [[row.get(b, 0.0) for b in bones] for row in rows],
                                 reach * min(line.span for line in lines), passes=passes, limit=MAX_INFLUENCES)
    group_of = {ob.name: {g.index: g for g in ob.vertex_groups} for ob in objects}
    for (ob, index, _, _), row in zip(chain, smoothed):
        for group in [group_of[ob.name][g.group] for g in ob.data.vertices[index].groups]:
            group.remove([index])
        kept = [(bone, weight) for bone, weight in zip(bones, row) if weight > rw.FLOOR]
        total = sum(weight for _, weight in kept)
        for bone, weight in kept:
            group = ob.vertex_groups.get(bone) or ob.vertex_groups.new(name=bone)
            group.add([index], weight / total, 'REPLACE')
    return len(chain)


def spine_holds(body, bone):
    """(KD-tree, [{bone: weight}]) of the body vertices weighted to `bone`'s ancestors (game bone names), each row cut
    to those ancestors and renormalised: what holds a chain whose first bone is `bone`."""
    from mathutils.kdtree import KDTree
    spine, up = set(), bone.parent
    while up:
        spine.add(up.name)
        up = up.parent
    points, holds = [], []
    for _, _, co, row in body:
        hold = {b: w for b, w in row.items() if b in spine}
        total = sum(hold.values())
        if total > 1e-4:
            points.append(co)
            holds.append({b: w / total for b, w in hold.items()})
    tree = KDTree(len(points))
    for k, co in enumerate(points):
        tree.insert(co, k)
    tree.balance()
    return tree, holds


def apply_mirror(context, ob, apply_stack=False):
    """Replace ob's mesh by the Mirror-applied rest mesh (the other modifiers are gone first; apply_stack: every
    modifier stays and is applied except Armature and Subdivision). Returns the Subdivision settings of the source
    (levels, render levels) or None."""
    subsurf = next((m for m in ob.modifiers if m.type == 'SUBSURF'), None)
    levels = (subsurf.levels, subsurf.render_levels) if subsurf else None
    for mod in list(ob.modifiers):
        if mod.type in ('ARMATURE', 'SUBSURF') or (mod.type != 'MIRROR' and not apply_stack):
            ob.modifiers.remove(mod)
        elif mod.type == 'MIRROR':
            mod.show_viewport = True
    if ob.modifiers:
        depsgraph = context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph), depsgraph=depsgraph)
        ob.modifiers.clear()
        ob.data = mesh
    return levels


def copy_mesh(context, src_name, collection_name, rig_name, plan, names, skel, apply_stack=False):
    """One game mesh from `src`: a free copy in rest position, Mirror applied, weights on the game bones, Armature
    modifier on `rig`, Subdivision (as the source's, off) after it. The source is not touched."""
    src, rig, collection = bpy.data.objects[src_name], bpy.data.objects[rig_name], bpy.data.collections[collection_name]
    targets = group_targets(skel, src, plan, names)
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = src.name + " Game"
    collection.objects.link(ob)
    for con in list(ob.constraints):
        ob.constraints.remove(con)
    ob.animation_data_clear()
    ob.parent, ob.matrix_world = None, rest_world(src)
    levels = apply_mirror(context, ob, apply_stack)
    merge_weights(ob, targets, skel.world.inverted() @ ob.matrix_world)
    ob.parent = rig
    ob.matrix_parent_inverse = rig.matrix_world.inverted()
    ob.modifiers.new("Armature", 'ARMATURE').object = rig
    if levels:
        sub = ob.modifiers.new("Subdivision", 'SUBSURF')
        sub.levels, sub.render_levels = levels
        sub.show_viewport = sub.show_render = False
    ob[TAG] = skel.main
    return ob


# ---------------------------------------------------------------- the new armature and the whole run
def build_armature(context, collection, skel, plan, names, base=None, parents=None):
    """The game armature: every kept bone at its rest matrix, parented to its nearest kept ancestor (else the root), or
    as `parents` {key: parent key} says. Named "<base>_Game" (base: the source rig's name unless given)."""
    name = (base or skel.main) + "_Game"
    data = BC.new_armature(name)
    rig = bpy.data.objects.new(name, data)
    collection.objects.link(rig)
    rig.matrix_world = skel.world
    rig[TAG] = skel.main
    context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    deform = data.collections.new("Deform")
    kept, root = {e[0] for e in plan}, plan[0][0]
    edit = {}
    for key, *_ in plan:
        bone = edit[key] = data.edit_bones.new(names[key])
        matrix, length = skel.matrix(key), max(skel.length(key), 1e-3)
        bone.head, bone.tail = matrix.translation, matrix.translation + Vector((0, 1, 0))
        bone.length = length
        bone.matrix = matrix
        bone.use_deform = True
        deform.assign(bone)
    for key, bone in edit.items():
        if key != root:
            bone.parent = edit[(parents or {}).get(key) or skel.ancestor(key, kept) or root]
    bpy.ops.object.mode_set(mode='OBJECT')
    return rig


def clavicle_parents(skel, plan, fixed):
    """{clavicle key: the neck's parent}: Unity's Humanoid (and Unreal) want both shoulders and the neck on the same
    bone; a source with an upper chest often hangs the shoulders one bone lower (for example: shoulders on Chest, neck on
    UpperChest). Only a clavicle whose own parent is a torso bone below the neck's parent moves."""
    kept = {e[0] for e in plan}
    neck = next((e[0] for e in plan if e[1] in ('neck', 'head')), None)
    top = neck and (fixed.get(neck) or skel.ancestor(neck, kept))
    if top is None or top not in skel.torso:
        return {}
    below = skel.torso[:skel.torso.index(top)]
    return {e[0]: top for e in plan
            if e[1] == 'clavicle' and e[0] not in fixed and (skel.ancestor(e[0], kept) in below)}


def follow_source(context, rig_name, skel, plan, names):
    """For baking an animation: every game bone made from a source bone copies it (world space); a ChainLine's first
    bone starts at the root control and stretches to MCH-<Name>Mid (a non-deform helper in the game rig, an Armature
    constraint on the chain's controls by `mid_weights`, so it stays at the chain's middle), its second runs from
    there to the tip control. Virtual bones (a new root, merged toes) just ride on their parent."""
    rig = bpy.data.objects[rig_name]
    lines = [line for line in skel.lines if line.keys[0] in names]
    helpers = {line.name: BB.chain_bone(line.name, 'Mid', None, 'MCH') for line in lines}
    if lines:
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        mechanism = rig.data.collections.new("Mechanism")
        for line in lines:
            bone = rig.data.edit_bones.new(helpers[line.name])
            bone.head = line.mid
            bone.tail = line.mid + (line.tip - line.root).normalized() * max((line.tip - line.root).length * 0.1, 1e-3)
            bone.use_deform = False
            mechanism.assign(bone)
        bpy.ops.object.mode_set(mode='OBJECT')
    rig = bpy.data.objects[rig_name]
    poses = rig.pose.bones
    for key, *_ in plan:
        if key in skel.bones:
            copy = poses[names[key]].constraints.new('COPY_TRANSFORMS')
            copy.target, copy.subtarget = bpy.data.objects[key[0]], key[1]
    for line in lines:
        source = bpy.data.objects[line.rig]
        follow = poses[helpers[line.name]].constraints.new('ARMATURE')
        for key, weight in line.mid_weights.items():
            target = follow.targets.new()
            target.target, target.subtarget, target.weight = source, key[1], weight
        first, second = (poses[names[key]] for key in line.keys)
        aim(first, (source, line.root_bone[1]), (rig, helpers[line.name]))
        aim(second, (rig, helpers[line.name]), (source, line.tip_bone[1]))


def aim(pb, start, end):
    """The bone's head sits on bone `start`'s head and its tail stretches to bone `end`'s ((object, bone name) each)."""
    place = pb.constraints.new('COPY_LOCATION')
    place.target, place.subtarget = start
    reach = pb.constraints.new('STRETCH_TO')
    reach.target, reach.subtarget = end
    reach.volume, reach.rest_length = 'NO_VOLUME', pb.bone.length


def game_collections(main):
    """The game rig collections this tool made from `main`."""
    return [coll for coll in bpy.data.collections if coll.get(TAG) == main.name]


def remove_previous(main):
    """A game rig this tool made earlier from `main` goes (objects, their data, the collection)."""
    for coll in game_collections(main):
        for ob in list(coll.all_objects):
            data, library = ob.data, bpy.data.meshes if ob.type == 'MESH' else bpy.data.armatures
            bpy.data.objects.remove(ob)
            if data and not data.users:
                library.remove(data)
        bpy.data.collections.remove(coll)


def dropped_report(skel, plan, part_rigs):
    """{kind: count} of the deform bones (of the rigs the meshes use) that are not in the game rig."""
    kept = {e[0] for e in plan}
    counts = {}
    for key in (k for r in [skel.main] + part_rigs for k in skel.deform_keys(r, chains=True)):
        if key in kept:
            continue
        name = plain(key)
        kind = ('chains' if skel.bones[key].chain else 'parts' if key[0] != skel.main
                else 'fingers' if re.search(BC.FINGER_WORDS, name)
                else 'face' if re.search(FACE_WORDS, name) else 'body')
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def bone_map(skel, plan, names, part_rigs):
    """{(rig, bone): final bone name} for every kept bone and every dropped deform bone (the bone that took its weight)."""
    kept, root = {e[0] for e in plan}, plan[0][0]
    found = {key: names[skel.target(key, kept, root)]
             for rig in [skel.main] + part_rigs for key in skel.deform_keys(rig, chains=True)}
    found.update(names)
    return found


def make_game_rig(context, main, fingers=True, face=False, parts=True, engine=rig_names.DEFAULT_ENGINE, name=None,
                  jaw=True, forearm_split=False, extras=(), meshes=None, apply_stack=False, follow=False):
    """Build the game rig for `main`; a given `name` replaces the rig's name in "<name> Game" (collection) and
    "<name>_Game" (rig). See the module docstring for jaw, forearm_split, extras, meshes (source objects),
    apply_stack and follow. Returns a report dict: rig, meshes, bones, dropped {kind: count}, others, names, bone_map,
    kept, chains {chain name: its two game bone names}.
    Objects are looked up by name between steps: switching modes can invalidate Blender object references."""
    view = context.view_layer
    active = view.objects.active.name if view.objects.active else None
    selected = [o.name for o in context.selected_objects]
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    remove_previous(main)
    view.update()
    skel = Skeleton(main)
    found, others = source_meshes(context, main)
    meshes = found if meshes is None else meshes
    part_rigs = used_rigs(meshes, skel)
    plan = make_plan(skel, part_rigs if parts else [], fingers, face, jaw, forearm_split, extras)
    names = bone_names(plan, skel, engine, extras)
    parents = {(e.rig, e.bone): e.parent for e in extras if e.parent}
    parents.update(clavicle_parents(skel, plan, parents))
    mesh_names = [m.name for m in meshes]
    collection = bpy.data.collections.new((name or skel.main) + " Game")
    collection[TAG] = skel.main
    context.scene.collection.children.link(collection)
    rig_name = build_armature(context, collection, skel, plan, names, name, parents).name
    if follow:
        follow_source(context, rig_name, skel, plan, names)
    context.view_layer.update()
    copies = [copy_mesh(context, n, collection.name, rig_name, plan, names, skel, apply_stack).name for n in mesh_names]
    lines = [line for line in skel.lines if line.keys[0] in names]
    if lines:
        view.update()
        soften_chains([bpy.data.objects[n] for n in copies], lines, names, bpy.data.objects[rig_name],
                      lambda ob: skel.world.inverted() @ ob.matrix_world)
    for ob in context.selected_objects:
        ob.select_set(False)
    for name in selected:
        bpy.data.objects[name].select_set(True)
    view.objects.active = bpy.data.objects[active] if active else None
    return dict(rig=bpy.data.objects[rig_name], meshes=copies, bones=len(plan), others=len(others),
                dropped=dropped_report(skel, plan, part_rigs), names=[names[e[0]] for e in plan],
                bone_map=bone_map(skel, plan, names, part_rigs), kept=names,
                chains={line.name: [names[key] for key in line.keys] for line in skel.lines})


def info_line(report):
    dropped = report['dropped']
    text = f"{report['rig'].name}: {report['bones']} bones, {len(report['meshes'])} meshes"
    if dropped:
        text += f"; dropped {sum(dropped.values())} deform bones (" + ", ".join(f"{n} {k}" for k, n in dropped.items()) + ")"
    return text
