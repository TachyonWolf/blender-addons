# SPDX-License-Identifier: GPL-3.0-or-later
"""Move a mesh object's origin to a world point while the mesh stays where it is. No UI in here.

The mesh data is shifted the other way (shape keys included), so every vertex keeps its world place. A mesh shared by
linked duplicates is shifted ONCE and every user's object moves with it, so each keeps its look. Children keep their
world place. A Mirror modifier without a mirror object works around the origin, so the origin only moves along the
axes it does NOT mirror (unless told otherwise); the other modifiers that react to the origin are reported as
warnings. Rigged meshes work as they are: an Armature modifier deforms in world space, so it does not care."""
from collections import Counter
from dataclasses import dataclass, field

from mathutils import Matrix

from .mirror_pivot import mirror_planes_of
from .scene_checks import users_by_data

AXIS_LETTERS = "XYZ"
# Modifiers whose result depends on where the object origin is (Mirror is handled apart; Array only with an offset object)
ORIGIN_MODIFIER_TYPES = {'SIMPLE_DEFORM': "Simple Deform", 'WAVE': "Wave", 'CURVE': "Curve", 'LATTICE': "Lattice",
                         'WARP': "Warp", 'SCREW': "Screw", 'CAST': "Cast", 'DISPLACE': "Displace", 'HOOK': "Hook",
                         'NODES': "Geometry Nodes"}


@dataclass
class MoveResult:
    moved: int = 0          # objects whose origin was set
    followers: int = 0      # linked duplicates that moved along with a shared mesh
    skipped: Counter = field(default_factory=Counter)   # reason > count
    kept_axes: set = field(default_factory=set)         # axis letters kept because a Mirror works around them
    warnings: set = field(default_factory=set)


def skip_reason(ob):
    """Why the origin of this object can't move, or "" when it can."""
    if ob.type != 'MESH':
        return "not a mesh"
    if not (ob.is_editable and ob.data.is_editable):
        return "linked from a library"
    return ""


def mirror_axes(ob):
    """Local axis indices an origin-based Mirror modifier (no mirror object) of this object works around."""
    return {axis for mod in ob.modifiers if mod.type == 'MIRROR' and mod.mirror_object is None
            for axis in mirror_planes_of(ob, mod).axes}


def origin_warnings(ob):
    """Sentences about modifiers of `ob` that react to the origin (Mirror is not here: the move works around it)."""
    found = []
    for mod in ob.modifiers:
        label = ORIGIN_MODIFIER_TYPES.get(mod.type)
        if label is None and mod.type == 'ARRAY' and mod.use_object_offset and mod.offset_object:
            label = "Array with an offset object"
        if label:
            found.append(f'"{ob.name}": {label} "{mod.name}" reacts to the origin, check its shape')
    if ob.animation_data and (ob.animation_data.action or ob.animation_data.drivers):
        found.append(f'"{ob.name}" is animated: its location may jump back when the frame changes')
    return found


def users_of(ob, users):
    return users.get(ob.data, [ob])


def shifted_delta(ob, world_point, users, keep_mirror_axes, result):
    """The move of the origin in local space, with the Mirror axes zeroed when asked."""
    delta = ob.matrix_world.inverted() @ world_point
    if keep_mirror_axes:
        for axis in set().union(*(mirror_axes(user) for user in users_of(ob, users))):
            if abs(delta[axis]) > 1e-9:
                result.kept_axes.add(AXIS_LETTERS[axis])
            delta[axis] = 0.0
    return delta


def keep_children_in_place(parent, old_parent_world):
    """After the parent's matrix changed: give each object child a new parent inverse so it stays where it was
    (its own location values stay the same). Vertex children follow the mesh, which did not move in the world."""
    new_inverse = parent.matrix_world.inverted() @ old_parent_world
    for child in parent.children:
        if child.parent_type == 'OBJECT':
            child.matrix_parent_inverse = new_inverse @ child.matrix_parent_inverse


def shift_origin(ob, delta, users):
    """Shift the origin of `ob` (and every linked duplicate) by `delta`, local space; the mesh stays in the world."""
    sharers = users_of(ob, users)
    old_worlds = {user: user.matrix_world.copy() for user in sharers}
    ob.data.transform(Matrix.Translation(-delta), shape_keys=True)
    ob.data.update()
    for user in sharers:
        user.matrix_world = old_worlds[user] @ Matrix.Translation(delta)
        keep_children_in_place(user, old_worlds[user])


def move_origins(moves, keep_mirror_axes=True):
    """Set the origin of each (object, world point) in `moves`; the points were all worked out before anything moved.
    Returns a MoveResult."""
    result = MoveResult()
    users = users_by_data()
    done_data = set()
    for ob, world_point in moves:
        reason = skip_reason(ob)
        if reason:
            result.skipped[reason] += 1
            continue
        if ob.data in done_data:   # a linked duplicate of an object already moved: it went along
            continue
        for user in users_of(ob, users):
            result.warnings.update(origin_warnings(user))
        shift_origin(ob, shifted_delta(ob, world_point, users, keep_mirror_axes, result), users)
        done_data.add(ob.data)
        result.moved += 1
        result.followers += len(users_of(ob, users)) - 1
    return result
