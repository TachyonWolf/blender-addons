# SPDX-License-Identifier: GPL-3.0-or-later
"""The VR tools: Select (trigger pull) and Grab (grip held). The session timer polls the buttons (controls.py)
and calls these; the router decides what each press does. Each finished action is ONE undo step (pushed with
ed.undo_push from a 3D View context), so desktop Ctrl+Z matches. A grab ends when its last grip lets go (commit), on
undo / redo (cancel, A18) or when the session ends (commit).

Grab extras (M2): Select and Grab (a grip anywhere moves the selection), grip rotation Puppet / On stick / Auto, a
second grip on the same item joins the grab (two-hand scale), fine control (B). A grab is a chain of segments: each
time its hands or its motion factor change, the delta so far is kept as `base` and a new segment starts from the
hands' poses now, so nothing jumps.

Why polling and not XR-invoked operators: all tool logic stays in one place (the tick, next to hover), the undo
step is pushed exactly once per finished action, and it avoids the XR modal quirks (an operator property set in
invoke stops Blender sending the held-button events to the modal; every frame re-invokes instead). Polling costs
two action_state_get calls per hand per tick (~0.01 ms) and up to one tick (33 ms) of press latency."""
import time

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import box_select as box_select_inside, edit_grab, edit_math, edit_pick, haptics_math, held_item, edit_state, pose_mirror, router, selection, settings, size_state, snap_state
from .action_map import LEFT, RIGHT, buzz, value, vector
from .context_helper import view3d_override
from .edit_tool_settings import LOOP_CUT
from .hands import HandPose
from .picking import BONE, OBJECT, Picker
from .runtime import RUNTIME
from .transform_math import (FINE_FACTOR, Channels, Locks, basis_from_parent_space, channels_from_basis, hand_matrix,
                             one_hand_delta, PUSH_MIN_DISTANCE, push_offset, trigger_net, two_hand_delta)


EMPTY = object()     # start_grab: the grip found nothing under the hand (two such grips scale you: user_scale.py)


def push_undo(name):
    """One undo step for a finished VR action."""
    override = view3d_override(bpy.context)
    if override:
        with bpy.context.temp_override(**override):
            bpy.ops.ed.undo_push(message=name)


def _pick(context, state, hand, behaviour_name):
    pose = HandPose(context, state, hand)
    if router.mode_kind(context.mode) == router.EDIT:
        return edit_pick.pick(context, pose, behaviour_name)
    picker = Picker(context, RUNTIME.cache)
    pose_mode = router.mode_kind(context.mode) == router.POSE
    if router.uses_laser(behaviour_name):
        return picker.laser(pose_mode, pose.aim_location, pose.aim_direction, size_state.laser_length())
    return picker.touch(pose_mode, pose.aim_location, size_state.touch_distance())     # the fingertip [user]


def select(context, state, hand, toggle=None):
    """Trigger pull: select what the laser points at (A held = toggle, like Shift); empty space clears. `toggle` is
    A's state when the press began (a gesture decided at the release passes it)."""
    behaviour_name = router.behaviour(router.SELECT, router.mode_kind(context.mode), settings.get("grab_mode"))
    if behaviour_name == router.REFUSE:
        buzz(context, state, hand)
        return
    if router.mode_kind(context.mode) == router.EDIT and edit_pick.refused(context):
        buzz(context, state, hand)       # Edit mode can't work on this mesh (the reason is on the desk)
        return
    hit = _pick(context, state, hand, behaviour_name)
    if hit and hit.linked and hit.kind == BONE:
        buzz(context, state, hand)       # bones of linked rigs can't be changed
        return
    outcome = router.select_outcome(hit, value(context, state, "toggle", RIGHT) > 0.5 if toggle is None else toggle)
    if outcome != router.NOTHING and selection.apply(context, hit, outcome):
        push_undo("VR Select")


class _Moved:
    """One item a grab moves, with its start state."""

    def __init__(self, ob, pose_bone=None):
        self.ob_name, self.bone_name = ob.name_full, pose_bone.name if pose_bone else ""
        owner = pose_bone or ob
        self.start_channels = Channels.of(owner)
        self.locks = Locks.of(owner, connected=bool(pose_bone and pose_bone.bone.use_connect and pose_bone.parent))
        self.start = (pose_bone.matrix if pose_bone else ob.matrix_world).copy()
        self.twin = pose_mirror.twin_of(ob, pose_bone) if pose_bone else None     # X-Axis Mirror: its opposite bone
        self.centre = (ob.matrix_world @ self.start).translation if pose_bone else self.start.translation.copy()

    def key(self):
        """Same as picking.Target.key() of this item."""
        return (BONE, self.ob_name, self.bone_name) if self.bone_name else (OBJECT, self.ob_name, "")

    def apply(self, data, delta, use_scale=False):
        ob = data.objects.get(self.ob_name)   # grabbed items are local (linked ones are refused)
        if ob is None:
            return
        if self.bone_name:
            pose_bone = ob.pose.bones.get(self.bone_name)
            if pose_bone is None:
                return
            world = ob.matrix_world
            target = world.inverted_safe() @ delta @ world @ self.start
            basis = ob.convert_space(pose_bone=pose_bone, matrix=target, from_space='POSE', to_space='LOCAL')
            channels_from_basis(basis, self.start_channels, self.locks, use_scale).write(pose_bone)
            if self.twin is not None and (BONE, self.ob_name, self.twin.name) not in RUNTIME.grabbed:   # a held twin is its own
                self.twin.apply(ob.pose, pose_bone)
            return
        parent_space = (ob.parent.matrix_world @ ob.matrix_parent_inverse) if ob.parent else Matrix.Identity(4)
        basis = basis_from_parent_space(delta @ self.start, parent_space)
        channels_from_basis(basis, self.start_channels, self.locks, use_scale).write(ob)


def moved_object(ob):
    """An object to move by world deltas (parents and locks handled), from its state now."""
    return _Moved(ob)


def motion_factor():
    return router.motion_factor(settings.get("fine_control"), FINE_FACTOR)


def hand_matrices(context, state, hands):
    """{hand: grip matrix} now."""
    poses = {hand: HandPose(context, state, hand) for hand in hands}
    return {hand: hand_matrix(pose.aim_location, pose.grip_rotation) for hand, pose in poses.items()}   # held at the fingertip [user, 2026-11-25]


class Grab:
    """One grab: what it moves, how it turns and which hands hold it (one, or two = scale). Lives in
    HandState.grab of each hand that holds it."""

    def __init__(self, behaviour_name, moved, hand, hand_now):
        self.behaviour, self.moved = behaviour_name, moved
        self.pivot_kind = router.pivot_kind()
        self.keys = {item.key() for item in moved}
        self.key = next(iter(self.keys))
        self.centre = sum((item.centre for item in moved), Vector()) / len(moved)   # world, at the start
        self.hands = [hand]
        self.base = Matrix.Identity(4)   # delta of the finished segments
        self.scaled = False              # two hands held it: scale is written from now on
        self.generation = RUNTIME.generation
        self.push = Vector()             # world offset of this segment's push / pull (folded into base at a rebase)
        self.pocketed = False            # released at a belt slot: the object is hidden, the undo step holds it (belt.py)
        self.snapper = None              # snap_state.ObjectSnap while snapping Object mode grabs (one hand, no scale)
        self.edits = any(isinstance(item, edit_grab.EditMoved) for item in moved)      # an Edit mode grab
        self.tool_item = next((item for item in moved if getattr(item, "message", "")), None)   # an active Edit tool's drag
        self.by_trigger = False          # the trigger started it (loop cut): its release ends it, not the grip's
        self.frames = 0
        self.last_frame, self.last_time = -1, 0.0   # paced by controls.due()
        self._begin_segment(hand_now)

    def _begin_segment(self, hand_now):
        self.starts = {hand: hand_now[hand].copy() for hand in self.hands}
        self.factor = motion_factor()

    def delta(self, hand_now):
        """World delta from the grab's start to the hands' poses now."""
        if len(self.hands) == 2:
            first, second = self.hands
            # distance grabs (Laser, Select and Grab) scale the item about its own centre; hand grabs between the hands
            pivot = self.base @ self.centre if self.behaviour in (router.GRAB_LASER, router.GRAB_SELECTION) else None
            segment = two_hand_delta((self.starts[first].translation, self.starts[second].translation),
                                     (hand_now[first].translation, hand_now[second].translation), self.factor, pivot)
        else:
            hand = self.hands[0]
            pivot = self.starts[hand].translation if self.pivot_kind == router.HAND else self.base @ self.centre
            segment = one_hand_delta(self.starts[hand], hand_now[hand], pivot, self.factor)   # the wrist always turns it [user]
        matrix = Matrix.Translation(self.push) @ segment @ self.base
        if self.snapper is not None and len(self.hands) == 1 and not self.scaled:
            return self.snapper.apply(matrix)       # snapping: ONE translation correction (off during two-hand scale)
        return matrix

    def rebase(self, hand_now, hands=None):
        """Keep the motion so far and start a new segment (new factor, or `hands` now hold it)."""
        self.base = self.delta(hand_now)
        self.push = Vector()
        if hands is not None:
            self.hands = list(hands)
            self.scaled = self.scaled or len(self.hands) == 2
        self._begin_segment(hand_now)


def _other_grab(hand):
    return next((hand_state.grab for other, hand_state in RUNTIME.hands.items()
                 if other != hand and hand_state.grab is not None), None)


def start_grab(context, state, hand):
    """Grip press: pick by the grab mode and start dragging, or join the other hand's grab (two-hand scale).
    Returns the Grab this hand now holds, EMPTY (nothing under the hand), or None (refused)."""
    behaviour_name = router.behaviour(router.GRAB, router.mode_kind(context.mode), settings.get("grab_mode"))
    if behaviour_name == router.REFUSE:
        buzz(context, state, hand)
        return None
    if router.mode_kind(context.mode) == router.EDIT and edit_pick.refused(context):
        buzz(context, state, hand)
        return None
    if router.mode_kind(context.mode) == router.EDIT:
        behaviour_name = router.edit_behaviour(router.GRAB, behaviour_name, settings.get("edit_tool"),
                                               bool(edit_state.STATE.selected.any()))
        if behaviour_name == router.EDIT_TOOL:
            return start_edit_tool(context, state, hand)
    hit = None
    if behaviour_name != router.GRAB_SELECTION:
        hit = _pick(context, state, hand, behaviour_name)
        if hit is None:
            return EMPTY                             # grip on nothing: one hand does nothing, two scale you
        if hit.linked:
            buzz(context, state, hand)               # linked data can't be changed
            return None
    other = _other_grab(hand)
    if other is not None and other.tool_item is not None:
        buzz(context, state, hand)                   # a tool drag has one hand: the other one's grip does nothing
        return None
    if other is not None and router.second_grip(behaviour_name, hit and hit.key() in other.keys) == router.JOIN:
        other.rebase(hand_matrices(context, state, other.hands + [hand]), other.hands + [hand])
        buzz(context, state, hand, duration=0.02, amplitude=0.3)
        return other
    if router.mode_kind(context.mode) == router.EDIT:
        moved = edit_grab.items(context, hit, HandPose(context, state, hand, with_grip_rotation=False).aim_location)
    elif hit is not None and hit.kind == BONE or hit is None and router.mode_kind(context.mode) == router.POSE:
        moved = [_Moved(ob, pose_bone) for ob, pose_bone in selection.grab_bones(context, hit)]
    else:
        moved = [_Moved(ob) for ob in selection.grab_objects(context, hit)]
    moved = [item for item in moved if item.key() not in RUNTIME.grabbed]   # each item has one grab (or tool gun hold)
    if not moved:
        return None
    hand_now = hand_matrices(context, state, [hand])
    centre = sum((item.centre for item in moved), Vector()) / len(moved)
    grab = Grab(behaviour_name, moved, hand, hand_now)
    if not any(item.bone_name for item in moved if hasattr(item, "bone_name")) and router.mode_kind(context.mode) == router.OBJECT:
        grab.snapper = snap_state.object_snap(context, [ob for ob in (bpy.data.objects.get(item.ob_name) for item in moved) if ob])
    RUNTIME.grabbed.update(grab.keys)
    buzz(context, state, hand, duration=0.02, amplitude=0.3, kind=haptics_math.GRAB)
    return grab


def start_edit_tool(context, state, hand):
    """Edit mode's active tool: make its geometry and let this hand drag it. Returns the Grab, EMPTY (the loop cut points
    at no edge) or None (refused: the reason is on the desk)."""
    from . import edit_tool_drag       # (it imports edit_actions, which imports this module)
    if edit_pick.refused(context) or edit_state.STATE.grabbing:
        buzz(context, state, hand)
        return None
    tool, pose = settings.get("edit_tool"), HandPose(context, state, hand)
    edge = None
    if tool == LOOP_CUT:
        aimed = edit_pick.pick_at(context, True, pose.aim_location, pose.aim_direction, pose.aim_location, kind=edit_math.EDGE)
        if aimed is None:
            return EMPTY
        edge = aimed.index
    item = edit_tool_drag.start(context, tool, pose.aim_location, edge)
    if item is None:
        buzz(context, state, hand)
        return None
    grab = Grab(router.EDIT_TOOL, [item], hand, hand_matrices(context, state, [hand]))
    RUNTIME.grabbed.update(grab.keys)
    buzz(context, state, hand, duration=0.02, amplitude=0.3, kind=haptics_math.GRAB)
    return grab


STICK_STEP_MAX = 0.1   # s: a longer gap between drags (a hitch) turns no more than this


def box_select(context, state, hand, gesture):
    """A + trigger dragged and released: add what is inside the box (per mode) to the selection. ONE undo step when
    something changed, none otherwise."""
    if router.mode_kind(context.mode) == router.EDIT and edit_pick.refused(context):
        buzz(context, state, hand)
        return
    if box_select_inside.apply(context, gesture):
        push_undo("VR Box Select")
        buzz(context, state, hand, duration=0.02, amplitude=0.3)


def _push_pull(grab, hand_now):
    """The triggers while holding: right pushes the item away along the hand-to-item line, left pulls it closer."""
    amounts = {hand: RUNTIME.hands[hand].trigger_amount for hand in (LEFT, RIGHT)
               if hand in RUNTIME.hands and held_item.held_in(hand) is None}      # that trigger is the held item's
    net = trigger_net(amounts.get(RIGHT, 0.0), amounts.get(LEFT, 0.0))
    if net == 0.0:
        return
    seconds = min(time.perf_counter() - grab.last_time, STICK_STEP_MAX)
    hand_position = hand_now[grab.hands[0]].translation
    centre_now = grab.delta(hand_now) @ grab.centre
    grab.push += push_offset(hand_position, centre_now, net, size_state.push_speed(), seconds, grab.factor,
                             size_state.scaled(PUSH_MIN_DISTANCE))


def drag(context, state, grab):
    """One frame of a grab. Returns False when the grab must be cancelled (an undo / redo ran meanwhile)."""
    if grab.generation != RUNTIME.generation:
        return False
    hand_now = hand_matrices(context, state, grab.hands)
    if motion_factor() != grab.factor:
        grab.rebase(hand_now)                        # fine control flipped mid-grab: no jump
    around_pivot = grab.tool_item is None and value(context, state, "toggle", RIGHT) > 0.5      # A held: turn about the item's own pivot
    pivot_now = router.pivot_kind(around_pivot)
    if pivot_now != grab.pivot_kind:
        grab.rebase(hand_now)                        # keep the motion so far, then switch the pivot: no jump
        grab.pivot_kind = pivot_now
    if len(grab.hands) == 1 and grab.frames and grab.tool_item is None:     # (a tool drag leaves the triggers alone)
        _push_pull(grab, hand_now)
    delta = grab.delta(hand_now)
    for item in grab.moved:
        item.apply(context.blend_data, delta, grab.scaled)
    if any(getattr(item, "dead", False) for item in grab.moved):
        return False                                 # an edit grab lost its mesh (desktop edit, key switch): cancel it
    grab.frames += 1
    return True


def release(context, state, grab, hand):
    """One hand lets go. Returns True while the other hand still holds the grab (it goes on, one-handed)."""
    if hand not in grab.hands:
        return False
    rest = [other for other in grab.hands if other != hand]
    if not rest:
        return False
    if grab.generation == RUNTIME.generation:
        grab.rebase(hand_matrices(context, state, grab.hands), rest)
    else:
        grab.hands = rest
    return True


def end_grab(grab, commit):
    """Finish a grab: one undo step when it moved something and is kept (commit)."""
    RUNTIME.grabbed.difference_update(grab.keys)
    snap_state.Guides.clear()
    edit_state.STATE.grabbing = False
    for item in grab.moved:
        if hasattr(item, "finish"):
            item.finish(bpy.data)
    if not grab.edits:
        RUNTIME.cache.all_dirty = True       # (an edit grab only changes the edited mesh: edit_state refreshes itself)
    changed = commit and (grab.frames or grab.tool_item is not None) and any(getattr(item, "changed", lambda: True)() for item in grab.moved)
    if grab.tool_item is not None:
        grab.tool_item.end(bpy.data, bool(changed))      # its exact cancel when nothing changed
        if changed:
            push_undo(grab.tool_item.message)
    elif changed or grab.pocketed:
        push_undo("VR Pocket" if grab.pocketed else "VR Scale" if grab.scaled else "VR Grab")
