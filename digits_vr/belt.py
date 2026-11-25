# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool belt (DESIGN "Tool belt"): a belt at hip height that turns with the body, with a few slots. Drop a held item
(tool gun, PDA, tool options panel) at a slot and it docks; grip it out again. Release a grabbed model at a free slot and
it is pocketed (it shrinks to fit the slot, belt_pocket.py); grip it out and it is full size again, placed where you let go. An Attached
item snaps back to the belt when you get farther from it than the snap-back distance. The belt only talks to the held
item interface (held_item.py). Off = `BELT.running` is False and nothing here runs per tick.
A saved file may hold a pocketed model small: belt_pocket keeps its real transform on the object, so load puts it back.
Hooks (small, in other modules): controls.update (update, grip_pressed, grip_released, grab_released), tools.end_grab,
session start / teardown / load / undo, overlay (belt_draw)."""
import bpy
from mathutils import Matrix, Vector

from . import belt_items, belt_math, belt_pocket, settings  # noqa: F401 (belt_items makes the tool options panel a held item)
from .action_map import HANDS, buzz
from .belt_state import BELT, Carry
from .body_frame import BODY
from .hands import HandPose
from .held_item import REGISTRY, held_in
from .runtime import RUNTIME
from .size_state import SIZE
from .tools import push_undo
from .transform_math import hand_matrix

MOVED_ELSEWHERE = 0.02      # m (times your size): a docked item this far from where the belt put it was moved by someone else


def _optional(item, name, default=None):
    """An optional hook an item may offer (the contract in held_item.py stays small)."""
    return getattr(item, name, default)


# -- start, stop -------------------------------------------------------------

def start(context):
    """Session start (and the setting turned on in a session)."""
    BELT.reset()
    belt_pocket.release_all()           # leftovers of a crash never stay hidden
    BELT.running = bool(settings.get("belt_on"))
    if BELT.running:
        _dock_homes(context)


def stop():
    """Session end, setting turned off, file load, add-on off: everything goes back where it belongs. Idempotent."""
    for hand in list(BELT.carries):
        _end_carry(hand, None)
    for slot in BELT.slots:
        if slot.item is not None:
            _undock(slot, keep_place=False)
    belt_pocket.release_all()
    BELT.reset()


teardown = stop


def _option_changed(value):
    if not RUNTIME.active:
        return
    if value:
        start(bpy.context)
    else:
        stop()


# -- docking -----------------------------------------------------------------

def _dock_homes(context):
    """Items whose home is the belt (`home_on_belt`) start in a free slot."""
    for item in list(REGISTRY.values()):
        free = BELT.free_indices()
        if item.home_on_belt and free:
            _dock(context, None, item, free[0])


def _dock(context, state, item, index, hand=None):
    slot = BELT.slots[index]
    slot.item, slot.floating, slot.last_set = item, item.matrix().copy(), None
    hook = _optional(item, "entered_belt")
    if hook:
        hook()
    BELT.watched.pop(item.name, None)
    if hand is not None and state is not None:
        buzz(context, state, hand, duration=0.03, amplitude=0.5)


def _undock(slot, keep_place):
    """The item leaves its slot. keep_place: it stays where it is now (its full size back), else it returns to where it
    was before it docked."""
    item, floating = slot.item, slot.floating
    slot.item = slot.floating = slot.last_set = None
    if floating is not None:
        if keep_place:
            location, rotation, _scale = item.matrix().decompose()
            item.set_matrix(Matrix.LocRotScale(location, rotation, floating.to_scale()))
        else:
            item.set_matrix(floating)
    hook = _optional(item, "left_belt")
    if hook:
        hook()


def _dock_scale(item):
    return _optional(item, "dock_scale", 1.0) * BELT.size_factor()


def _docked_items():
    """Each tick: docked items sit in their slots; one that was closed or taken by someone else leaves."""
    for slot in BELT.slots:
        item = slot.item
        if item is None:
            continue
        if not item.shown:
            _undock(slot, keep_place=False)
        elif item.held_by is not None or _moved_elsewhere(slot, item):
            _undock(slot, keep_place=True)
        else:
            item.set_matrix(BELT.slot_matrix(slot.index, _dock_scale(item)))
            slot.last_set = item.matrix().copy()


def _moved_elsewhere(slot, item):
    return slot.last_set is not None and (item.matrix().translation - slot.last_set.translation).length > MOVED_ELSEWHERE * SIZE.factor


def _loose_items(context, state, poses, head):
    """Each tick, the items that are not docked or carried: one let go near a slot docks; an Attached one that is far
    from you snaps back."""
    taken = {slot.item.name for slot in BELT.slots if slot.item} | {carry.item.name for carry in BELT.carries.values() if carry.item}
    limit = settings.get("belt_snap_back") * SIZE.factor
    for name, item in list(REGISTRY.items()):
        if name in taken:
            continue
        hand = item.held_by
        if hand is not None:
            BELT.watched[name] = (hand, poses[hand].aim_location.copy())      # the fingertip decides the slot [user]
            continue
        seen = BELT.watched.pop(name, None)
        free = BELT.free_indices()
        if item.home_on_belt and item.stowed and free:
            _dock(context, None, item, free[0])
            continue
        index = BELT.nearest(seen[1], free) if seen else None
        if index is not None:
            _dock(context, state, item, index, seen[0])
        elif free and item.attached and item.shown and belt_math.snap_back_due(item.matrix().translation, head, limit):
            _dock(context, state, item, free[0])


# -- carrying things off the belt --------------------------------------------

def _hand_over(slot, pose, hand):
    """An item that follows the hand by itself (the tool gun) leaves its slot: no carry."""
    item = slot.item
    _location, rotation, scale = (slot.floating or item.matrix()).decompose()
    slot.item = slot.floating = slot.last_set = None
    item.held_by = hand
    item.set_matrix(Matrix.LocRotScale(pose.grip_location, rotation, scale))
    item.on_grab(hand)
    hook = _optional(item, "left_belt")
    if hook:
        hook()


def _take_item(slot, pose, hand):
    item = slot.item
    _location, rotation, scale = (slot.floating or item.matrix()).decompose()
    item.set_matrix(Matrix.LocRotScale(pose.grip_location, rotation, scale))
    hold = hand_matrix(pose.grip_location, pose.grip_rotation)
    carry = Carry(hand, belt_math.carry_offset(hold, item.matrix()), item=item, generation=RUNTIME.generation)
    slot.item = slot.floating = slot.last_set = None
    item.on_grab(hand)
    hook = _optional(item, "left_belt")
    if hook:
        hook()
    return carry


def _take_model(slot, pose, hand):
    ob = bpy.data.objects.get(slot.pocket)
    if ob is None:
        slot.pocket = ""
        return None
    matrix = belt_pocket.take_out(ob, slot, pose.grip_location)       # real size back, middle of it at the hand
    ob.select_set(True)
    hold = hand_matrix(pose.grip_location, pose.grip_rotation)
    RUNTIME.cache.all_dirty = True
    return Carry(hand, belt_math.carry_offset(hold, matrix), object_name=ob.name_full, generation=RUNTIME.generation)


def grip_pressed(context, state, hand):
    """A grip press (controls, before the panels): True when it took something off the belt."""
    if not BELT.running or hand in BELT.carries or settings.get("paused"):
        return False
    pose = HandPose(context, state, hand)
    occupied = BELT.occupied_indices()
    point = pose.aim_location if settings.get("belt_take_fingertip") else pose.grip_location     # an option [user, 2026-11-25]
    index = BELT.nearest(point, occupied)
    if index is None:
        index = next((slot.index for slot in BELT.slots if slot.item is not None and slot.item.grip_hit(point)), None)
    if index is None:
        return False
    slot = BELT.slots[index]
    if slot.item is not None and slot.item.follows_hand:
        _hand_over(slot, pose, hand)
        buzz(context, state, hand, duration=0.03, amplitude=0.5)
        return True
    carry = _take_item(slot, pose, hand) if slot.item is not None else _take_model(slot, pose, hand)
    if carry is None:
        return False
    BELT.carries[hand] = carry
    buzz(context, state, hand, duration=0.03, amplitude=0.5)
    return True


def _end_carry(hand, index, context=None):
    """The hand let go (or the belt stops). `index`: the free slot it was let go at, or None. A model is placed where it
    is (one undo step), or pocketed again at a free slot."""
    carry = BELT.carries.pop(hand)
    if carry.item is not None:
        carry.item.on_release(hand)
        if index is not None and BELT.slots[index].free():
            _dock(context, None, carry.item, index)
        return
    ob = bpy.data.objects.get(carry.object_name)
    if ob is None or carry.generation != RUNTIME.generation:
        return
    pocketed = index is not None and BELT.slots[index].free() and belt_pocket.put_in(ob, BELT.slots[index])
    if context is not None:
        push_undo("VR Pocket" if pocketed else "VR Place")
    RUNTIME.cache.all_dirty = True


def grip_released(context, state, hand):
    """A grip let go (controls): what this hand carried off the belt is dropped: docked at a free slot, else left where
    it is."""
    if hand not in BELT.carries:
        return
    index = BELT.nearest(HandPose(context, state, hand, with_grip_rotation=False).aim_location, BELT.free_indices())
    _end_carry(hand, index, context)
    if index is not None:
        buzz(context, state, hand, duration=0.03, amplitude=0.5)


def grab_released(context, state, grab, hand):
    """A grabbed object (or a selection of them) is let go (controls, before the grab ends): at a free slot in Object mode
    each is pocketed, shrunk to fit, one slot each, nearest slot first. The grab's own undo step holds the shrinking too
    (tools.end_grab): one step. All or nothing: a linked, locked or driven object, or too few free slots, is a long buzz."""
    if not BELT.running:
        return
    objects = belt_pocket.eligible(context, grab)
    free = BELT.free_indices()
    if not objects or not free:
        return
    first = BELT.nearest(HandPose(context, state, hand, with_grip_rotation=False).aim_location, free)     # the fingertip [user]
    if first is None:
        return
    if len(objects) > len(free) or any(belt_pocket.refusal(ob) for ob in objects):
        buzz(context, state, hand)
        return
    homes = {item.ob_name: item.start.translation.copy() for item in grab.moved}
    for ob, index in zip(objects, [first] + [index for index in free if index != first]):
        belt_pocket.put_in(ob, BELT.slots[index], homes.get(ob.name_full))
    grab.pocketed = True
    buzz(context, state, hand, duration=0.03, amplitude=0.5)


# -- the tick ----------------------------------------------------------------

def _turn_with_body(state):
    """The belt hangs on the shared body frame (body_frame.py). Returns the head position."""
    BODY.update(state)
    return Vector(state.viewer_pose_location)


def _move_carries(poses):
    for hand, carry in list(BELT.carries.items()):
        if carry.generation != RUNTIME.generation:
            _end_carry(hand, None)
            continue
        pose = poses[hand]
        target = hand_matrix(pose.grip_location, pose.grip_rotation) @ carry.offset
        if carry.item is not None:
            carry.item.set_matrix(target)
            continue
        ob = bpy.data.objects.get(carry.object_name)
        if ob is None:
            BELT.carries.pop(hand)
        else:
            ob.matrix_world = target


def lock_at_fingertip(context, state, hand):
    """B pressed: with this hand's fingertip at a slot holding an item, lock / unlock that item to the belt (Attached:
    it snaps back when you move away; the slot shows yellow) [user, 2026-11-25]. True when B was used for this."""
    if not BELT.running:
        return False
    index = BELT.nearest(HandPose(context, state, hand, with_grip_rotation=False).aim_location, BELT.occupied_indices())
    item = BELT.slots[index].item if index is not None else None
    if item is None:
        return False
    item.attached = not item.attached
    buzz(context, state, hand, duration=0.03 if item.attached else 0.08, amplitude=0.5)
    return True


def _holds_droppable(context, hand):
    """Does this hand hold something a free slot would take (an object grab in Object mode, a carried model or item, a
    held item)?"""
    grab = RUNTIME.hands[hand].grab
    if grab is not None:
        return context.mode == 'OBJECT' and not any(getattr(moved, "bone_name", "") for moved in grab.moved)
    return hand in BELT.carries or held_in(hand) is not None


def _ready_slots(context, poses):
    """The free slots a fingertip is close enough to drop into right now (drawn blue) [user, 2026-11-25]."""
    free = BELT.free_indices()
    found = (BELT.nearest(pose.aim_location, free) for hand, pose in poses.items() if free and _holds_droppable(context, hand))
    return frozenset(index for index in found if index is not None)


def update(context, state):
    """Once per session tick while the belt runs (controls.update). Returns True while something is carried (the timer
    then runs every frame)."""
    if BELT.reconcile_due:
        BELT.reconcile_due = False
        belt_pocket.reconcile()
    head = _turn_with_body(state)
    poses = {hand: HandPose(context, state, hand, with_grip_rotation=bool(BELT.carries)) for hand in HANDS}
    _move_carries(poses)
    _docked_items()
    belt_pocket.follow()
    _loose_items(context, state, poses, head)
    BELT.ready = _ready_slots(context, poses)
    near = BELT.size_factor() * belt_math.NEAR_BELT
    BELT.visible = bool(BELT.carries or BELT.watched or BELT.occupied_indices()
                        or any(hand_state.grab is not None for hand_state in RUNTIME.hands.values())
                        or any((pose.grip_location - BELT.frame.translation).length < near for pose in poses.values()))
    return bool(BELT.carries)


# -- file safety, undo -------------------------------------------------------

def after_load():
    """load_post: a model left shrunk in the pocket (a crash, or a file saved with it pocketed) is put back at its real size
    and place."""
    BELT.reset()
    belt_pocket.release_all()


def after_undo():
    """undo_post / redo_post: carries stop; the markers decide what is pocketed."""
    if BELT.running:
        for hand in list(BELT.carries):
            _end_carry(hand, None)
        BELT.reconcile_due = True        # on the next tick: inside undo_post, view_layer.update() crashed Blender (2026-11-25)
    else:
        belt_pocket.release_all()


def register():
    settings.LISTENERS.setdefault("belt_on", []).append(_option_changed)


def unregister():
    stop()
    if _option_changed in settings.LISTENERS.get("belt_on", []):
        settings.LISTENERS["belt_on"].remove(_option_changed)
