# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig Stress Pose Test (the logic; rig_stress_ui.py is the card): puts a character rig in extreme body poses one by one,
measures every visible mesh it deforms with deform_metrics (generated copy of the shared metrics that
Scripts/batch_tools/face_stress.py uses too) and lists the problem areas per pose: over-stretched and squashed edges,
collapsed and flipped faces, spikes. Plus the weight hygiene of each mesh.

Poses are data (POSES): end states in the character's frame (armature space, left side: +X left, -Y front, +Z up),
so a pose looks the same whatever the rest pose (T or A) or bone roll; the right side gets the mirror image.
Limbs are posed through their IK controls (Reach): the hand / foot IK control goes to a share of the limb's rest
length along a direction from the limb's root, the pole goes off the limb line toward a direction; the limb's IK_FK
switch goes to IK (IK Stretch stays as it is). The rig's limbs come from the Limb data limb_rig stores on each IK
control. A limb with no IK falls back to FK turns (the Reach's `fallback`). Chains with no IK (spine, neck, head,
tail, fingers) use their FK controls (Turn): an Aim points bones along a direction, a Bend turns them from where their
parent leaves them toward a direction, a Twist turns them about their own length. Bones are found by their standard
names (docs/BONE_NAMES.md, through rig_names, so old names work too); only the ones an animator poses are moved:
IK controls and poles, spine, neck, head, tail, fingers, never shoulders, tweak, MCH or DEF bones. A chain ("Spine#")
shares a spread angle over the bones the rig has; bones a rig lacks are skipped. Arms the pose doesn't move are in FK
(they follow the body), legs it doesn't move stay in IK (feet planted). Each depth of bones is placed from its
parents' evaluated pose, so constraints that stay on are followed. The rig is never changed: the user's pose,
switches included, is read before and put back exactly (save_pose.read_exact_pose), modifiers hidden for measuring
come back on, weights are only read."""
import json
import math
import re
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, replace

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from . import chain_weights, deform_metrics as dm, rig_names as rn, weight_cleanup  # generated copies
from .pose_ops import reset_transforms
from .save_pose import apply_exact_pose, read_exact_pose

LEFT_RIGHT = ('L', 'R')
CENTRE = ('',)
LEFT_ONLY, RIGHT_ONLY = ('L',), ('R',)
UP, DOWN, FRONT, BACK, OUT = (0, 0, 1), (0, 0, -1), (0, -1, 0), (0, 1, 0), (1, 0, 0)   # armature space, left side
SWITCHES = {'SpineIK': 0, 'HeadAim': 0}   # custom properties set for every pose: spine and head in FK
IK_SWITCH = 'IK_FK'                  # on a limb's IK control: 1 = IK, 0 = FK
LIMB_PARTS = {'Hand': 'arm', 'Foot': 'leg'}   # the IK control's part -> which limb it is
CONTROL_CONSTRAINTS = {'IK', 'COPY_ROTATION', 'COPY_TRANSFORMS', 'TRACK_TO', 'DAMPED_TRACK', 'LOCKED_TRACK'}
POLE_DISTANCE = 0.6                  # the pole sits this share of the limb's length off the limb line
MIRROR_MATCH = 1e-4                  # metres: a Mirror modifier's copy of a vertex sits this close to its mirror image
MAX_CHAIN = 40                       # a numbered chain is looked for up to this number


@dataclass(frozen=True)
class Turn:
    """One move of a pose. kind 'aim': point `bones` along `direction`; 'bend': turn them `degrees` from where their
    parent leaves them toward `direction` (one turn axis for the whole chain, so a long chain curls); 'twist': turn them
    `degrees` about their own length. A bone pattern: "Name" one bone, "Name#" a numbered chain (or the unnumbered
    bone when the chain is one bone), "A|B" the first alternative the rig has. `spread`: the angle is shared out over
    all the bones found, else each bone gets it. Directions are for the left side (centre bones use them as they are)."""
    kind: str
    bones: tuple
    direction: tuple = (0, 0, 0)
    degrees: float = 0.0
    sides: tuple = LEFT_RIGHT
    spread: bool = False


def aim(bones, direction, sides=LEFT_RIGHT):
    return Turn('aim', bones, direction, sides=sides)


def bend(bones, toward, degrees, sides=LEFT_RIGHT, spread=False):
    return Turn('bend', bones, toward, degrees, sides, spread)


def twist(bones, degrees, sides=LEFT_RIGHT, spread=False):
    return Turn('twist', bones, degrees=degrees, sides=sides, spread=spread)


@dataclass(frozen=True)
class Reach:
    """An IK limb end state: the limb's IK control at `fraction` of the limb's rest length from its root along
    `direction` (None: where it rests), the pole off the limb line toward `pole`. `control`: an optional bend / twist
    Turn of the control itself (wrist, ankle). `carry`: the control turns with the limb (a hand stays in line with the
    arm); off, it keeps its rest orientation (feet flat on the floor). `fallback`: FK Turns for a rig with no IK on
    this limb."""
    limb: str                     # 'arm' / 'leg'
    direction: tuple = None
    fraction: float = 0.95
    pole: tuple = (0, 1, 0)
    control: Turn = None
    carry: bool = True
    sides: tuple = LEFT_RIGHT
    fallback: tuple = ()


@dataclass(frozen=True)
class Pose:
    name: str
    turns: tuple = ()             # FK Turns (chains with no IK)
    reaches: tuple = ()           # IK limbs


ARM = ("Upperarm#",)
ELBOW = ("Forearm1|Forearm",)
THIGH = ("Thigh#",)
KNEE = ("Shin1|Shin",)
FINGERS = ("Thumb#", "Index#", "Middle#", "Ring#", "Pinky#", "Fingers")
SPINE = ("Spine#", "Chest")
NECK_HEAD = ("Neck#", "Head")
BACK_BONE = SPINE + NECK_HEAD    # spine poses carry the neck and head (and their look target) along
POSES = (
    Pose("Arms Up", reaches=(Reach('arm', (0.25, 0, 1), pole=BACK, fallback=(aim(ARM, (0.25, 0, 1)),)),)),
    Pose("Arms Down", reaches=(Reach('arm', (0.15, 0.05, -1), pole=BACK, fallback=(aim(ARM, (0.15, 0.05, -1)),)),)),
    Pose("Arms Across", reaches=(Reach('arm', (-0.7, -1, 0), 0.9, pole=DOWN, fallback=(aim(ARM, (-0.6, -1, 0)),)),)),
    Pose("Arms Back", reaches=(Reach('arm', (0.5, 1, -0.5), 0.9, pole=DOWN, fallback=(aim(ARM, (0.5, 1, -0.4)),)),)),
    Pose("Elbows Folded", reaches=(Reach('arm', (0.5, -1, 0), 0.3, pole=(1, 0.5, 0), fallback=(bend(ELBOW, FRONT, 150),)),)),
    Pose("Arm Twist", reaches=(Reach('arm', None, pole=UP, control=twist((), 90),
                                     fallback=(twist(ARM, 80), twist(("Forearm#",), 90, spread=True), twist(("Hand",), 60))),)),
    Pose("Wrists Bent", reaches=(Reach('arm', None, control=bend((), UP, 80), fallback=(bend(("Hand",), UP, 80),)),)),
    Pose("Fists", turns=(bend(FINGERS, DOWN, 85),)),
    Pose("Leg Kick", reaches=(Reach('leg', (0, -1, 0.35), pole=UP, fallback=(aim(THIGH, (0, -1, 0.35)),)),)),
    Pose("Knees Folded", reaches=(Reach('leg', (0, 0.8, -0.6), 0.4, pole=FRONT, fallback=(bend(KNEE, BACK, 140),)),)),
    Pose("Squat", reaches=(Reach('leg', (0.2, 0.1, -1), 0.5, pole=(0.4, -1, 0), carry=False,
                                 fallback=(aim(THIGH, (0.35, -1, -0.2)), bend(KNEE, BACK, 140))),)),
    Pose("Crouch", reaches=(Reach('leg', DOWN, 0.45, pole=FRONT, carry=False, fallback=(aim(THIGH, (0, -1, -0.6)), bend(KNEE, BACK, 110))),)),
    Pose("Side Splits", reaches=(Reach('leg', (1, 0, -0.1), pole=FRONT, fallback=(aim(THIGH, (1, 0, -0.05)),)),)),
    Pose("Front Splits", reaches=(Reach('leg', (0, -1, -0.1), pole=UP, sides=LEFT_ONLY, fallback=(aim(THIGH, (0, -1, -0.1), LEFT_ONLY),)),
                                  Reach('leg', (0, 1, -0.1), pole=DOWN, sides=RIGHT_ONLY, fallback=(aim(THIGH, (0, 1, -0.1), RIGHT_ONLY),)))),
    Pose("Leg Twist", reaches=(Reach('leg', None, pole=OUT, control=twist((), 40), fallback=(twist(THIGH, 60, spread=True), twist(("Foot",), 40))),)),
    Pose("Feet Pointed", reaches=(Reach('leg', None, control=bend((), DOWN, 50), fallback=(aim(("Foot",), (0, -0.35, -1)),)),)),
    Pose("Bend Forward", turns=(bend(BACK_BONE, FRONT, 100, CENTRE, spread=True),)),
    Pose("Bend Back", turns=(bend(BACK_BONE, BACK, 60, CENTRE, spread=True),)),
    Pose("Bend Sideways", turns=(bend(BACK_BONE, OUT, 60, CENTRE, spread=True),)),
    Pose("Spine Twist", turns=(twist(BACK_BONE, 90, CENTRE, spread=True),)),
    Pose("Head Turned", turns=(twist(NECK_HEAD, 90, CENTRE, spread=True),)),
    Pose("Head Back", turns=(bend(NECK_HEAD, BACK, 80, CENTRE, spread=True),)),
    Pose("Head Down", turns=(bend(NECK_HEAD, FRONT, 80, CENTRE, spread=True),)),
    Pose("Tail Curled", turns=(bend(("Tail#",), UP, 200, CENTRE, spread=True),)),
)

# body area of a bone, by its part name (first match wins); the side goes in front ("Left Arm")
AREAS = ((r'Toe|Heel', 'Foot'), (r'Shoulder|Upperarm|Forearm|Elbow', 'Arm'),
         (r'Hand|Thumb|Index|Middle|Ring|Pinky|Finger|Palm', 'Hand'), (r'Hip|Thigh|Shin|Knee|Hock', 'Leg'),
         (r'Foot', 'Foot'), (r'Root|Pelvis|Spine|Chest|Torso|Butt|Breast|Belly', 'Torso'), (r'Neck', 'Neck'),
         (r'Tail', 'Tail'), (r'Wing', 'Wing'), (r'Ear', 'Ear'), (r'Hair', 'Hair'), (r'', 'Head'))
UNWEIGHTED = "Unweighted"
MIRROR_TWINS = "No Mirror Twin Group"


# ---------------------------------------------------------------------------
# Finding bones and posing
# ---------------------------------------------------------------------------

class BoneFinder:
    """Pose bones of a rig by standard name, whatever style the rig uses (rig_names.standard, read once per rig)."""

    def __init__(self, rig):
        self.bones = rig.pose.bones
        self.by_standard = {}
        for name in self.bones.keys():
            self.by_standard.setdefault(rn.standard(name).lower(), name)

    def get(self, name):
        if name in self.bones:
            return self.bones[name]
        found = self.by_standard.get(rn.standard(name).lower())
        return self.bones[found] if found else None

    def part(self, part, side, number=None):
        """The plain control of a part (also the deform bone on our rigs), else its FK- control."""
        for role in ('', 'FK'):
            bone = self.get(rn.build(part, side, number, role))
            if bone is not None:
                return bone
        return None

    def chain(self, part, side):
        """A numbered chain Part1, Part2, ... (or the one unnumbered Part)."""
        bones = []
        for number in range(1, MAX_CHAIN):
            bone = self.part(part, side, number)
            if bone is None:
                break
            bones.append(bone)
        single = None if bones else self.part(part, side)
        return bones or ([single] if single else [])

    def pattern(self, pattern, side):
        """The bones one Turn pattern names on one side (see Turn)."""
        for choice in pattern.split('|'):
            found = self.chain(choice[:-1], side) if choice.endswith('#') else [b for b in [self.part(choice, side)] if b]
            if found:
                return found
        return []


def for_side(direction, side):
    """A left-side direction for this side: the right side gets the mirror image (x negated)."""
    return Vector((-direction[0], direction[1], direction[2]) if side == 'R' else direction).normalized()


def depth(pose_bone):
    count, parent = 0, pose_bone.parent
    while parent:
        count, parent = count + 1, parent.parent
    return count


@dataclass
class Move:
    """One turn on one bone: which Turn, the side, its angle (spread shares it out), the chain it belongs to."""
    turn: Turn
    side: str
    degrees: float
    chain: tuple          # (turn index, side): a bend's chain shares one turn axis


def plan_moves(finder, turns, driven=frozenset()):
    """{pose bone: [Move]} of FK Turns on this rig (bones it lacks are skipped), in turn order. `driven`: names of
    bones their controls pose; they still count when a spread angle is shared out, but get no FK bend."""
    moves = {}
    for index, turn in enumerate(turns):
        for side in turn.sides:
            bones = [b for pattern in turn.bones for b in finder.pattern(pattern, side)]
            degrees = turn.degrees / len(bones) if turn.spread and bones else turn.degrees
            for bone in bones:
                if turn.kind != 'bend' or bone.name not in driven:
                    moves.setdefault(bone, []).append(Move(turn, side, degrees, (index, side)))
    return moves


def turned_about_head(matrix, rotation):
    """An armature-space bone matrix turned by a 3x3 rotation about the bone's head."""
    head = Matrix.Translation(matrix.translation)
    return head @ rotation.to_4x4() @ head.inverted() @ matrix


def moved_matrix(matrix, move, chain_axes):
    """The bone's armature-space matrix after one Move."""
    length_axis = matrix.col[1].xyz.normalized()
    turn = move.turn
    if turn.kind == 'aim':
        rotation = length_axis.rotation_difference(for_side(turn.direction, move.side)).to_matrix()
    elif turn.kind == 'bend':
        axis = chain_axes.setdefault(move.chain, length_axis.cross(for_side(turn.direction, move.side)))
        if axis.length < 1e-6:
            return matrix                  # already pointing that way: no bend axis
        rotation = Matrix.Rotation(math.radians(move.degrees), 3, axis.normalized())
    else:
        degrees = -move.degrees if move.side == 'R' else move.degrees
        rotation = Matrix.Rotation(math.radians(degrees), 3, length_axis)
    return turned_about_head(matrix, rotation)


def place_bones(rig, moves):
    """Set every moved bone, parents first: each depth is placed from its parents' evaluated pose, so the end state
    holds whatever the rest pose and the constraints still on."""
    chain_axes = {}
    for level in sorted({depth(b) for b in moves}):
        for pose_bone, bone_moves in moves.items():
            if depth(pose_bone) != level:
                continue
            matrix = pose_bone.matrix.copy()
            for move in bone_moves:
                matrix = moved_matrix(matrix, move, chain_axes)
            pose_bone.matrix = matrix
        bpy.context.view_layer.update()


@dataclass
class IkLimb:
    """A limb with IK, read from the Limb data on its IK control (limb_rig): the control, its pole, the limb's root
    bone and its rest length (root to the tip's head along the bones)."""
    control: object
    pole: object
    root: object
    length: float


def ik_limbs(rig, finder):
    """{('arm' / 'leg', side): IkLimb} of the rig's IK limbs (names in the Limb data read in any style)."""
    limbs = {}
    for pose_bone in rig.pose.bones:
        if 'Limb' not in pose_bone.keys() or IK_SWITCH not in pose_bone.keys():
            continue
        parsed = rn.parse(pose_bone.name)
        try:
            data = json.loads(pose_bone['Limb'])
        except (TypeError, ValueError):
            continue
        fk = [finder.get(name) for name in data.get('fk', [])]
        if parsed.part not in LIMB_PARTS or len(fk) < 2 or None in fk:
            continue
        pole = finder.get(data['pole']) if data.get('pole') else None
        limbs[(LIMB_PARTS[parsed.part], parsed.side)] = IkLimb(pose_bone, pole, fk[0], sum(b.bone.length for b in fk[:-1]))
    return limbs


def set_typed(pose_bone, key, value):
    """Set a custom property keeping its own type (an int switch stays an int)."""
    if isinstance(pose_bone[key], (int, float)):
        pose_bone[key] = type(pose_bone[key])(value)


def set_switches(rig, limbs, posed_limbs):
    """SWITCHES on every bone; each IK limb to IK when the pose moves it or it is a leg (feet planted), else FK."""
    for pose_bone in rig.pose.bones:
        for key, value in SWITCHES.items():
            if key in pose_bone.keys():
                set_typed(pose_bone, key, value)
    for key, limb in limbs.items():
        set_typed(limb.control, IK_SWITCH, 1 if key in posed_limbs or key[0] == 'leg' else 0)


def place_limb(limb, reach, side):
    """Put the IK control (and pole) where the Reach says, from the limb root's evaluated position."""
    root = limb.root.head.copy()
    matrix = limb.control.matrix.copy()
    if reach.direction is not None:
        direction = for_side(reach.direction, side)
        if reach.carry:      # turn the control as the limb turns, from its rest line to the new one
            matrix = (matrix.translation - root).normalized().rotation_difference(direction).to_matrix().to_4x4() @ matrix
        matrix.translation = root + direction * limb.length * reach.fraction
    if reach.control is not None:
        matrix = moved_matrix(matrix, Move(reach.control, side, reach.control.degrees, ('control', side)), {})
    limb.control.matrix = matrix
    target = matrix.translation
    line = (target - root).normalized()
    pole_direction = for_side(reach.pole, side)
    off_line = pole_direction - line * pole_direction.dot(line)
    if limb.pole is not None and off_line.length > 1e-3:
        pole_matrix = limb.pole.matrix.copy()
        pole_matrix.translation = (root + target) / 2 + off_line.normalized() * limb.length * POLE_DISTANCE
        limb.pole.matrix = pole_matrix


def chain_controls(rig, bones):
    """The animator controls that drive a chain through its constraints (IK-Chest, IK-Head, a head's look target):
    bone targets outside the chain, not MCH / DEF, and not a child of another control found (it moves along)."""
    names = {b.name for b in bones}
    controls = []
    for bone in bones:
        for constraint in bone.constraints:
            target = rig.pose.bones.get(getattr(constraint, 'subtarget', '') or '')
            if (constraint.type in CONTROL_CONSTRAINTS and not constraint.mute and constraint.influence > 0
                    and getattr(constraint, 'target', None) == rig and target is not None and target.name not in names
                    and rn.parse(target.name).role not in ('MCH', 'DEF') and target not in controls):
                controls.append(target)
    return [c for c in controls if not any(parent in controls for parent in c.parent_recursive)]


def turn_controls(controls, turn, first_bone):
    """Turn a chain's controls as one piece about the chain root, the way the Turn turns the chain."""
    pivot = first_bone.head.copy()
    length_axis = first_bone.matrix.col[1].xyz.normalized()
    if turn.kind == 'bend':
        axis = length_axis.cross(for_side(turn.direction, ''))
        if axis.length < 1e-6:
            return
        rotation = Matrix.Rotation(math.radians(turn.degrees), 3, axis.normalized())
    else:
        rotation = Matrix.Rotation(math.radians(turn.degrees), 3, length_axis)
    turn_about = Matrix.Translation(pivot) @ rotation.to_4x4() @ Matrix.Translation(-pivot)
    for control in controls:
        control.matrix = turn_about @ control.matrix


def driven_bones(rig, bones):
    """Names of the chain bones a control constraint poses: the constrained bone, and an IK's whole chain."""
    driven = set()
    for bone in bones:
        for constraint in bone.constraints:
            if constraint.type not in CONTROL_CONSTRAINTS or constraint.mute or getattr(constraint, 'target', None) != rig:
                continue
            driven.add(bone.name)
            if constraint.type == 'IK':
                parents = bone.parent_recursive
                driven |= {p.name for p in (parents if constraint.chain_count == 0 else parents[:constraint.chain_count - 1])}
    return driven


def split_controlled(rig, finder, turns):
    """(FK turns, [(controls, centre turn, first bone)], driven bone names): a centre chain driven by controls is
    posed through them; its other bones still get the FK turn (and twists turn every bone: a target on the chain's
    axis can't twist it)."""
    controlled, driven = [], set()
    for turn in turns:
        bones = [b for pattern in turn.bones for b in finder.pattern(pattern, '')] if turn.sides == CENTRE else []
        controls = chain_controls(rig, bones) if bones else []
        if controls:
            controlled.append((controls, turn, bones[0]))
            driven |= driven_bones(rig, bones)
    return turns, controlled, driven


@dataclass
class Posed:
    """What apply_stress_pose did: how many bones / limbs it moved, and the limbs that fell back to FK."""
    moved: int
    fk_limbs: list


def refresh(rig):
    """Re-evaluate after posing: custom property changes (switches) only reach the rig's drivers when it is tagged."""
    rig.update_tag()
    bpy.context.view_layer.update()


def put_back_pose(rig, pose):
    """Put a read_exact_pose snapshot back, drivers re-evaluated."""
    apply_exact_pose(rig, pose)
    refresh(rig)


def apply_stress_pose(rig, pose):
    """Rest pose, switches set, then the pose's IK limbs and FK turns. Returns Posed (moved 0: the rig lacks them all)."""
    for pose_bone in rig.pose.bones:
        reset_transforms(pose_bone)
    finder = BoneFinder(rig)
    limbs = ik_limbs(rig, finder)
    placed, turns, fk_limbs = [], list(pose.turns), []
    for reach in pose.reaches:
        for side in reach.sides:
            limb = limbs.get((reach.limb, side))
            if limb is not None:
                placed.append((limb, reach, side))
            else:
                fk_limbs.append(f"{rn.SIDE_WORDS.get(side, '')} {reach.limb}".strip())
                turns += [replace(turn, sides=(side,)) for turn in reach.fallback if side in turn.sides]
    set_switches(rig, limbs, {(reach.limb, side) for _limb, reach, side in placed})
    refresh(rig)
    turns, controlled, driven = split_controlled(rig, finder, turns)
    moves = plan_moves(finder, turns, driven)
    place_bones(rig, moves)
    for controls, turn, first_bone in controlled:
        turn_controls(controls, turn, first_bone)
    for limb, reach, side in placed:
        place_limb(limb, reach, side)
    refresh(rig)
    return Posed(len(moves) + len(placed) + sum(len(c) for c, _t, _b in controlled), sorted(set(fk_limbs)))


def pose_by_name(name):
    return next((p for p in POSES if p.name == name), None)


# ---------------------------------------------------------------------------
# Meshes and areas
# ---------------------------------------------------------------------------

def deformed_meshes(context, rig):
    """Visible meshes an enabled Armature modifier of this rig deforms."""
    return [ob for ob in context.view_layer.objects if ob.type == 'MESH' and ob.visible_get()
            and any(m.type == 'ARMATURE' and m.object == rig and m.show_viewport for m in ob.modifiers)]


def area_of_bone(name):
    """'Left Arm', 'Torso', 'Tail'... for a deform bone name."""
    parsed = rn.parse(name)
    area = next(word for pattern, word in AREAS if re.search(pattern, parsed.part))
    return f"{rn.SIDE_WORDS[parsed.side]} {area}" if parsed.side in rn.SIDE_WORDS else area


def dominant_bones(weights, count):
    """Per original vertex: the deform group weighing it most ('' when none)."""
    return [max(weights[i], key=weights[i].get) if i in weights else '' for i in range(count)]


def evaluated_arrays(obj):
    """(positions (V, 3) object space, Topology) of the evaluated mesh."""
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = evaluated.to_mesh()
    try:
        return dm.mesh_positions(me), dm.Topology.from_mesh(me)
    finally:
        evaluated.to_mesh_clear()


def original_map(obj, rest):
    """(original vertex per evaluated vertex or -1, whether it is a mirror copy). Same count: one to one. Else
    (Mirror, Solidify...) the original vertex at the same place, or at its mirror image (x negated)."""
    count = len(obj.data.vertices)
    if len(rest) == count:
        return np.arange(count), np.zeros(count, dtype=bool)
    tree = KDTree(count)
    for vertex in obj.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    original, mirrored = np.full(len(rest), -1, dtype=np.intp), np.zeros(len(rest), dtype=bool)
    for j, point in enumerate(rest.tolist()):
        for flip in (False, True):
            _co, index, distance = tree.find((-point[0], point[1], point[2]) if flip else point)
            if index is not None and distance < MIRROR_MATCH:
                original[j], mirrored[j] = index, flip
                break
    return original, mirrored


@dataclass
class Problem:
    """One pose's problems on one area of one mesh: counts per kind, the worst stretch / squash, the original vertices."""
    pose: str
    mesh: str
    area: str
    counts: dict
    verts: np.ndarray
    worst: dict = field(default_factory=dict)

    @property
    def total(self):
        return sum(self.counts.values())

    def detail(self):
        parts = []
        for kind, count in self.counts.items():
            worst = self.worst.get(kind)
            parts.append(f"{count} {kind.lower()}" + (f" x{worst:.1f}" if worst is not None else ""))
        return ", ".join(parts)


class MeshProbe:
    """One deformed mesh: its rest shape, read once, and what a pose does to it (`measure`)."""

    def __init__(self, obj):
        self.obj = obj
        self.rest, self.topo = evaluated_arrays(obj)
        self.rest_lengths = dm.edge_lengths(self.rest, self.topo.edges)
        self.rest_areas, self.rest_normals = dm.face_areas_normals(self.rest, self.topo)
        self.neighbour_pairs = dm.neighbour_faces(self.topo, len(self.rest))
        self.original, mirrored = original_map(obj, self.rest)
        self.weights = dm.vertex_weights(obj, weight_cleanup.deform_group_names(obj))
        bones = dominant_bones(self.weights, len(obj.data.vertices))
        areas = [None if i < 0 else area_of_bone(rn.flip(bones[i]) if flip else bones[i]) if bones[i] else UNWEIGHTED
                 for i, flip in zip(self.original, mirrored)]     # None: made by a modifier, can't be shown
        self.area_names = sorted({a for a in areas if a is not None})
        self.area = np.array([-1 if a is None else self.area_names.index(a) for a in areas], dtype=np.intp)

    def problem_masks(self, co):
        """{kind: (element type 'edge' / 'face' / 'vert', bool per element, value per element or None)} for the
        current pose (value: how many times longer / shorter than at rest)."""
        ratios = dm.stretch_ratios(co, self.rest_lengths, self.topo.edges)
        areas, normals = dm.face_areas_normals(co, self.topo)
        spikes = dm.spike_scores(co, self.rest, self.topo.edges)
        return {"Stretched": ('edge', ratios > dm.STRETCH_BAD, ratios),
                "Squashed": ('edge', ratios < dm.SQUASH_BAD, 1 / np.maximum(ratios, 1e-9)),
                "Collapsed": ('face', dm.collapsed_faces(areas, self.rest_areas), None),
                "Flipped": ('face', dm.flipped_faces(normals, self.rest_normals, self.topo, len(self.rest), self.neighbour_pairs), None),
                "Spikes": ('vert', np.nan_to_num(spikes) > dm.SPIKE_BAD, None)}

    def element_area(self, element):
        """Area index per edge / face / vertex: the area of its first vertex."""
        anchor = {'edge': self.topo.edges[:, 0] if len(self.topo.edges) else np.zeros(0, dtype=np.intp),
                  'face': self.topo.first_vert, 'vert': np.arange(len(self.rest))}[element]
        return self.area[anchor]

    def element_verts(self, element, mask):
        """The (evaluated) vertices of the masked elements: both edge ends, every corner of a face."""
        if element == 'edge':
            return self.topo.edges[mask].reshape(-1)
        if element == 'face':
            return self.topo.loop_vert[mask[self.topo.loop_face]]
        return np.flatnonzero(mask)

    def measure(self, pose_name):
        """Problems of the current pose, one per area that has any."""
        co, _topo = evaluated_arrays(self.obj)
        if len(co) != len(self.rest):
            return []      # a modifier changed the topology in this pose: nothing to compare
        masks = self.problem_masks(co)
        areas = {element: self.element_area(element) for element in ('edge', 'face', 'vert')}
        problems = []
        for area_index, area in enumerate(self.area_names):
            counts, worst, verts = {}, {}, []
            for kind, (element, mask, values) in masks.items():
                here = mask & (areas[element] == area_index)
                if not here.any():
                    continue
                counts[kind] = int(here.sum())
                if values is not None:
                    worst[kind] = float(values[here].max())
                verts.append(self.element_verts(element, here))
            if counts:
                originals = self.original[np.unique(np.concatenate(verts))]
                problems.append(Problem(pose_name, self.obj.name, area, counts, np.unique(originals[originals >= 0]), worst))
        return problems

    def verts_without_mirror_twin(self):
        """Vertices weighted to a sided deform group whose other-side group is missing while a Mirror modifier mirrors
        the groups: the mirrored half then follows this side's bone (chain_weights.ensure_mirror_groups adds them)."""
        if not chain_weights.mirrors_groups(self.obj):
            return []
        lonely = {rn.flip(name) for name in chain_weights.missing_mirror_groups(self.obj)}
        return sorted(i for i, groups in self.weights.items() if lonely & set(groups))

    def weight_problems(self):
        """[(label, original vertex indices)] of the mesh's weight hygiene (only the ones found)."""
        report = dm.weight_report(self.obj, self.weights)
        found = [(f"Over {dm.MAX_INFLUENCES} Bones", report.too_many),
                 ("Not Summing to 1", report.unnormalized),
                 ("Tiny Weights", sorted({i for i, _group in report.tiny})),
                 ("Uneven Centre", report.centre_uneven),
                 ("Weight Jumps", sorted({v for a, b, _group, _jump in report.jumps for v in (a, b)})),
                 (MIRROR_TWINS, self.verts_without_mirror_twin())]
        return [(label, np.array(verts, dtype=np.intp)) for label, verts in found if len(verts)]


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

@dataclass
class Report:
    rig: str
    meshes: list
    problems: list            # [Problem]
    weights: list             # [(mesh name, label, verts)]
    skipped: list             # pose names the rig has no bones for
    seconds: float


@contextmanager
def measuring(meshes):
    """The meshes' modifiers that only smooth or decorate off while inside (measured on the cage), then back on."""
    with ExitStack() as stack:
        for ob in meshes:
            stack.enter_context(dm.hidden_modifiers(ob))
        bpy.context.view_layer.update()
        yield


@contextmanager
def kept_pose(rig):
    """The rig's exact pose read on entering and put back on leaving (also on errors)."""
    pose = read_exact_pose(rig)
    try:
        yield
    finally:
        put_back_pose(rig, pose)


def rest_probes(rig, meshes):
    """A MeshProbe per mesh, read in the rest pose; the rig's pose comes back after."""
    with kept_pose(rig), measuring(meshes):
        for pose_bone in rig.pose.bones:
            reset_transforms(pose_bone)
        refresh(rig)
        return [MeshProbe(ob) for ob in meshes]


def measure_pose(probes, pose_name):
    """Problems of the rig's current pose on every probe's mesh."""
    with measuring([probe.obj for probe in probes]):
        return [problem for probe in probes for problem in probe.measure(pose_name)]


def weight_rows(probes):
    """[(mesh name, label, verts)] of every probe's weight hygiene."""
    return [(probe.obj.name, label, verts) for probe in probes for label, verts in probe.weight_problems()]


def run(context, rig, progress=None):
    """Every pose on every deformed mesh; the rig comes back exactly as it was. `progress(done, total)` is optional."""
    started = time.perf_counter()
    context.view_layer.update()      # visibility of objects added since the last update
    meshes = deformed_meshes(context, rig)
    problems, skipped = [], []
    probes = rest_probes(rig, meshes)
    with kept_pose(rig), measuring(meshes):
        for done, pose in enumerate(POSES):
            if progress:
                progress(done, len(POSES))
            if not apply_stress_pose(rig, pose).moved:
                skipped.append(pose.name)
                continue
            for probe in probes:
                problems += probe.measure(pose.name)
    weights = weight_rows(probes)
    return Report(rig.name, [ob.name for ob in meshes], problems, weights, skipped, time.perf_counter() - started)
