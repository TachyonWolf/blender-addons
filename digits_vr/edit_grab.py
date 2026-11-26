# SPDX-License-Identifier: GPL-3.0-or-later
"""Grabbing selected vertices in Edit mode. ONE EditMoved item for all of them (tools.Grab handles it like an
object): each frame it moves the vertices by the grab's world delta (numpy, one v.co write each) and calls
update_edit_mesh(destructive=False): no topology update, no undo push, no bmesh rebuild. The finished grab is ONE
undo step (tools.end_grab). The bmesh and its verts are held only for this grab and checked every frame; a dead one
(undo, mode switch, key switch, a desktop delete) cancels THIS grab only. cancel_all() puts the start coordinates
back (the desk's Undo / Redo call it first: an unpushed move would otherwise be lost together with the last
finished action)."""
import bmesh
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree

from . import edit_math, edit_select, edit_state, router, snap_state
from .edit_pick import EDIT_VERT
from .runtime import RUNTIME

DEAD = (ReferenceError, ValueError, RuntimeError)


class EditMoved:
    mirrors = True            # Mirror X: unselected twins follow
    message = ""              # an active tool's own undo step name (edit_tool_drag)

    def __init__(self, ob, bm, indices, selection_changed, driver_sign=1.0):
        self.ob_name, self.indices = ob.name_full, indices
        self.matrix = np.array(ob.matrix_world)
        self.bm, self.verts = bm, [bm.verts[i] for i in indices]
        self.base = np.array([vertex.co[:] for vertex in self.verts], np.float64)
        self.centre = Vector(edit_math.to_world(self.base, self.matrix).mean(axis=0))
        self.generation, self.key_index = RUNTIME.generation, edit_state.STATE.key
        self.dead = self.moved = False
        self.selection_changed = selection_changed
        self.tris_each_frame = len(bm.faces) <= edit_math.TRIS_EACH_FRAME_FACES
        self.snap = None                                # snap_state.EditSnap while snapping (set by items())
        self.plan, self.extra_verts, self.extra_base = None, [], np.zeros((0, 3))
        if self.mirrors and ob.data.use_mirror_x:                        # Mirror X: unselected twins follow (we never select them)
            self._plan_mirror(bm, driver_sign)

    def _plan_mirror(self, bm, driver_sign):
        visible = edit_state.STATE.visible
        tree = KDTree(int(visible.sum()))
        for index in np.flatnonzero(visible).tolist():
            tree.insert(bm.verts[index].co, index)
        tree.balance()
        twins = np.full(len(self.indices), -1)
        for row, point in enumerate(self.base.tolist()):
            _co, index, distance = tree.find((-point[0], point[1], point[2]))
            if index is not None and distance < edit_math.TWIN_TOLERANCE:
                twins[row] = index
        plan = edit_math.MirrorPlan(self.indices, self.base, twins, driver_sign)
        if plan.active:
            self.plan = plan
            self.extra_verts = [bm.verts[i] for i in plan.extra_indices.tolist()]
            self.extra_base = np.array([vertex.co[:] for vertex in self.extra_verts], np.float64).reshape(-1, 3)

    def key(self):
        return (EDIT_VERT, self.ob_name, "")

    def alive(self, data):
        ob = data.objects.get(self.ob_name)
        return (not self.dead and ob is not None and ob.mode == 'EDIT' and self.generation == RUNTIME.generation
                and self.bm.is_valid and self.verts[0].is_valid and self.verts[-1].is_valid
                and edit_state.STATE.key == self.key_index and not edit_state.STATE.stale)

    def apply(self, data, delta, use_scale=False):
        if not self.alive(data):
            self.dead = True
            return
        moved, extra = self.target(delta, use_scale)
        self._write(data, moved, extra)
        self.moved = self.moved or edit_math.moved_enough_points(self.base, moved)

    def target(self, delta, use_scale=False):
        """(points, twin points) the vertices go to for the grab's world `delta` (snapped: ONE correction for the whole
        set, before the Mirror X twins follow; no snapping while two hands scale)."""
        moved = edit_math.move_points(self.base, edit_math.local_delta(self.matrix, np.array(delta)))
        if self.snap is not None and not use_scale:
            moved = self.snap.correct(moved)
        if self.plan is None:
            return moved, self.extra_base
        return self.plan.apply(moved)

    def _write(self, data, points, extra):
        try:
            for vertex, point in zip(self.verts, points.tolist()):
                vertex.co = point
            for vertex, point in zip(self.extra_verts, extra.tolist()):
                vertex.co = point
            bmesh.update_edit_mesh(data.objects[self.ob_name].data, loop_triangles=self.tris_each_frame, destructive=False)
        except DEAD:
            self.dead = True
            return
        state = edit_state.STATE
        edit_state.moved_rows(self.indices, points)
        if len(self.extra_verts):
            edit_state.moved_rows(self.plan.extra_indices, extra)

    def finish(self, data):
        """The grab ended: one update with the triangles worked out (big meshes skip them per frame)."""
        if not self.tris_each_frame and self.alive(data):
            try:
                bmesh.update_edit_mesh(data.objects[self.ob_name].data, loop_triangles=True, destructive=False)
            except DEAD:
                self.dead = True

    def changed(self):
        return self.moved or self.selection_changed

    def restore(self, data):
        """Put the start coordinates back (if the data is still the one we hold)."""
        if self.alive(data) and self.moved:
            self._write(data, self.base, self.extra_base)
            self.moved = False


def select_aimed(context, hit, grip_target=router.AIMED, bm=None):
    """The ONE step every edit grip takes (Grab, Free grab and the active tools): the element under the laser / hand
    that is not selected becomes the selection alone (Aimed); a selected one, none, or the Selection setting leaves
    it. True when the selection changed (its undo step is the tool's own)."""
    if hit is None:
        return False
    bm = bm or edit_select.live_bmesh(context, hit.object_name)
    if bm is None or router.grab_targets(edit_select.selection_mask(bm, hit.element)[hit.index], grip_target) != router.ONLY_HIT:
        return False
    return edit_select.apply(context, hit, router.REPLACE, bm)


def items(context, hit, hand_world=None, grip_target=router.AIMED):
    """What a grip on `hit` moves: the whole selection when the hit is selected (or `grip_target` is Selection), else
    only it (selected alone). [] when nothing can move (refused, too many vertices, nothing selected)."""
    state = edit_state.STATE
    bm = edit_select.live_bmesh(context, hit.object_name if hit else state.object_name)
    if bm is None:
        return []
    changed = select_aimed(context, hit, grip_target, bm)
    mask = edit_select.selection_mask(bm)          # the selected VERTICES move, whatever the select mode
    edit_state.sync(context)       # the selection changed: the validity key moves on (the grab holds the new one)
    indices = np.flatnonzero(mask)
    if not len(indices) or len(indices) > edit_math.MAX_GRAB_VERTS:
        return []
    state.grabbing = True
    sign = -1.0 if hit is not None and _hit_x(bm, hit) < 0 else 1.0     # Mirror X: the grabbed side drives
    item = EditMoved(context.edit_object, bm, indices, changed, sign)
    if hand_world is not None:
        item.snap = snap_state.edit_snap(context.edit_object, item.matrix, item.base, indices, bm, np.array(hand_world))
    return [item]


def _hit_x(bm, hit):
    """Local x of the grabbed element (its first vertex)."""
    if hit.element == 'VERT':
        return bm.verts[hit.index].co.x
    element = bm.edges[hit.index] if hit.element == 'EDGE' else bm.faces[hit.index]
    return sum(vertex.co.x for vertex in element.verts) / len(element.verts)


def cancel_all(data):
    """Stop every running edit grab or tool drag and put the mesh back (before an Undo / Redo from the desk, mode switch)."""
    cancelled = False
    for hand_state in RUNTIME.hands.values():
        grab = hand_state.grab
        if grab is not None and grab.edits:
            for item in grab.moved:
                item.restore(data)
            RUNTIME.grabbed.difference_update(grab.keys)
            for other in RUNTIME.hands.values():
                if other.grab is grab:
                    other.grab = None
            cancelled = True
    edit_state.STATE.grabbing = False
    snap_state.Guides.clear()
    return cancelled
