# SPDX-License-Identifier: GPL-3.0-or-later
"""Pocketed models (DESIGN "Tool belt") [user, 2026-11-25]: a model released at a free slot SHRINKS (uniformly, however
huge) to fit the slot and stays where the slot is; gripped out it gets its real size back. The real transform and the slot
live on the object as one custom property (`digits_vr_pocket`), so undo / redo bring them back together with the shrunk
transform, a saved tiny file can still be put right, and nothing here can go out of step. A model is a whole parent tree: only the root's transform is stored and shrunk, its
children follow by parenting. `release_all` puts every pocketed object back at its real size and place (session end, belt off, add-on off, file load)."""
import bpy
from mathutils import Matrix, Vector

from . import belt_math
from .picking import is_linked
from .smart_select import top_parent
from .belt_state import BELT
from .runtime import RUNTIME

MARKER = "digits_vr_pocket"
MOVE_THRESHOLD = 0.002      # m (times your size): the belt must move this far before pocketed models are moved with it


def refusal(ob):
    """Why `ob` can't go on the belt, or "" when it can: linked, locked, or moved by a constraint, driver or animation."""
    if is_linked(ob):                      # a library override is local and editable (as in Smart select)
        return "linked"
    if any(ob.lock_location) or any(ob.lock_scale):
        return "locked"
    animation = ob.animation_data
    if ob.constraints or (animation is not None and (animation.action is not None or len(animation.drivers) > 0)):
        return "moved by a constraint, driver or animation"
    return ""


def eligible(context, grab):
    """What a finished Object-mode grab pockets: the WHOLE tree of each moved object, as one item [user, 2026-11-27]. The
    item is the top-most parent (Smart select's rule, `top_parent`, the setting or not); its children follow by parenting.
    [] when the grab moved bones or another mode is on. Each tree takes its own free slot."""
    if context.mode != 'OBJECT' or not grab.moved or any(getattr(moved, "bone_name", "") for moved in grab.moved):
        return []
    found = [bpy.data.objects.get(getattr(moved, "ob_name", "")) for moved in grab.moved]
    roots = {}
    for ob in found:
        if ob is not None:
            root = top_parent(ob, context.view_layer)
            roots[root.name_full] = root
    return [ob for ob in roots.values() if not any(other is not ob and ob in other.children_recursive for other in roots.values())]


def members(ob):
    return [ob, *ob.children_recursive]


def world_box(ob):
    """(centre, longest side) of the world bounding box of `ob` and its children."""
    points = []
    for member in members(ob):
        corners = member.bound_box if member.type not in {'EMPTY', 'ARMATURE'} else None
        points += [member.matrix_world @ Vector(corner) for corner in corners] if corners else [member.matrix_world.translation.copy()]
    low = Vector(map(min, zip(*points)))
    high = Vector(map(max, zip(*points)))
    return (low + high) / 2, max(high - low)


def _flat(matrix):
    return [value for row in matrix for value in row]


def _matrix(values):
    return Matrix([values[0:4], values[4:8], values[8:12], values[12:16]])


def put_in(ob, slot, home=None):
    """Shrink `ob` to fit `slot` and put it there; `home` = where it was picked up (world), the place it goes back to when VR
    ends. False when it can't (see refusal)."""
    if refusal(ob):
        return False
    bpy.context.view_layer.update()         # matrix_world is read: bring it up to date after a drag
    original, (center, extent) = ob.matrix_world.copy(), world_box(ob)
    anchor = BELT.slot_matrix(slot.index).translation
    shrunk = Matrix.Translation(anchor) @ Matrix.Scale(belt_math.fit_scale(extent, BELT.room()), 4) @ Matrix.Translation(-center) @ original
    if home is not None:
        shift = Vector(home) - original.translation
        original, center = Matrix.Translation(shift) @ original, center + shift
    ob[MARKER] = {"slot": slot.index, "matrix": _flat(original), "center": list(center)}
    ob.matrix_world = shrunk
    slot.pocket, slot.original, slot.center, slot.extent = ob.name_full, original, center, extent
    slot.placed, slot.anchor, slot.members = shrunk, anchor, frozenset(member.name_full for member in members(ob))
    return True


def take_out(ob, slot, position):
    """Real size back, with the middle of the model at `position` (the hand). Returns the new world matrix."""
    matrix = Matrix.Translation(Vector(position) - slot.center) @ slot.original
    if MARKER in ob:
        del ob[MARKER]
    ob.matrix_world = matrix
    slot.empty_pocket()
    return matrix


def restore(ob):
    """Back at its real size, where it was picked up."""
    data = ob[MARKER].to_dict()
    del ob[MARKER]
    ob.matrix_world = _matrix(list(data["matrix"]))


def release_all():
    """Every pocketed object (also leftovers of a crash or a saved tiny file) back at its real size and place."""
    for ob in bpy.data.objects:
        if MARKER in ob:
            restore(ob)
    for slot in BELT.slots:
        slot.empty_pocket()


def follow():
    """Each tick: pocketed models go with their slot, but only when the belt really moved."""
    threshold = MOVE_THRESHOLD * BELT.size_factor()
    for slot in BELT.slots:
        ob = bpy.data.objects.get(slot.pocket) if slot.pocket else None
        if ob is None:
            slot.pocket = ""
            continue
        target = BELT.slot_matrix(slot.index).translation
        if (target - slot.anchor).length > threshold:
            slot.placed = Matrix.Translation(target - slot.anchor) @ slot.placed
            slot.anchor = target
            ob.matrix_world = slot.placed
            RUNTIME.cache.mark_changed(slot.members)   # picks must see it where it is (the desk skips these updates)


def rescale():
    """Your size changed (user_scale.set_size, after BELT.rescale): the slots' room changed with you, so each pocketed model
    is shrunk again to fit it (about the slot point its matrix was made for; `follow` then moves it to the slot's new place).
    Never grown past its real size. Without this a model pocketed at 1:1 was 100x the slot at 0.01x and hid the belt."""
    for slot in BELT.slots:
        ob = bpy.data.objects.get(slot.pocket) if slot.pocket else None
        if ob is None or slot.placed is None or slot.original is None:
            continue
        shrink_now = slot.placed.median_scale / (slot.original.median_scale or 1.0)
        ratio = belt_math.fit_scale(slot.extent, BELT.room()) / (shrink_now or 1.0)
        if abs(ratio - 1.0) < 1e-9:
            continue
        anchor = Matrix.Translation(slot.anchor)
        slot.placed = anchor @ Matrix.Scale(ratio, 4) @ anchor.inverted() @ slot.placed
        ob.matrix_world = slot.placed
        RUNTIME.cache.mark_changed(slot.members)


def only_pockets(depsgraph):
    """True when a depsgraph update is just the belt moving pocketed models (the desk need not rebuild for it)."""
    if not BELT.running:
        return False
    names = set().union(*(slot.members for slot in BELT.slots))
    return bool(names) and all(isinstance(update.id, bpy.types.Object) and update.id.original.name_full in names
                               for update in depsgraph.updates)


def reconcile():
    """Undo, redo: the objects' own property says what is pocketed now; the slots follow it."""
    bpy.context.view_layer.update()
    found = {ob.name_full: ob[MARKER].to_dict() for ob in bpy.data.objects if MARKER in ob}
    for slot in BELT.slots:
        if slot.pocket and (slot.pocket not in found or found[slot.pocket]["slot"] != slot.index):
            slot.pocket, slot.members = "", frozenset()
    for name, data in found.items():
        ob, index = bpy.data.objects[name], data["slot"]
        slot = BELT.slots[index] if isinstance(index, int) and 0 <= index < len(BELT.slots) else None
        if slot is not None and slot.pocket == name:
            continue
        if slot is not None and slot.free():
            center, extent = world_box(ob)
            slot.pocket, slot.original, slot.center = name, _matrix(list(data["matrix"])), Vector(data["center"])
            slot.placed, slot.anchor = ob.matrix_world.copy(), center
            slot.extent = extent * slot.original.median_scale / (slot.placed.median_scale or 1.0)   # the real size
            slot.members = frozenset(member.name_full for member in members(ob))
        else:
            restore(ob)            # its slot is gone or taken: never leave it tiny
