# SPDX-License-Identifier: GPL-3.0-or-later
"""The running drag of an active Edit tool: ONE grab item (tools.Grab handles it like a grabbed selection). It holds a
snapshot of the mesh from before the tool, so a cancel is exact and a setting changed mid-drag runs the tool again at the
same amount. Release = ONE undo step (tools.end_grab), or the exact cancel when nothing changed."""
import bmesh
import bpy
import numpy as np

from . import edit_math, edit_select, edit_state, edit_tool_math, edit_tool_settings as options
from . import edit_tools, settings, size_state
from .edit_actions import mirror_note, notice
from . import edit_grab
from .edit_grab import DEAD, EditMoved
from .edit_snapshot import MeshSnapshot


FAILED = (edit_tools.Refused, RuntimeError, ValueError)      # a refusal, or a bmesh op that gave up on this mesh


class ToolMoved(EditMoved):
    mirrors = False

    def __init__(self, ob, bm, tool, hand_world, edge=None, hit=None):
        self.tool, self.edge, self.hit = tool, edge, hit
        self.grip_target = settings.get("grip_target")
        self.message = "VR " + options.TOOL_LABELS[tool]
        self.hand_start = np.array(hand_world, float)
        self.delta = np.eye(4)
        self.snapshot = MeshSnapshot(ob, bm)
        try:
            self._run(ob, bm)
        except FAILED:
            self.snapshot.restore(ob, bm)
            self.close()
            raise

    def _run(self, ob, bm):
        self.values = options.values(self.tool, settings.get)
        edit_grab.select_aimed(bpy.context, self.hit, self.grip_target, bm)    # after the snapshot: a cancel brings the old selection back
        effect = edit_tools.run(self.tool, bm, self.values, self.edge)
        bm.verts.index_update()
        indices = np.array([vertex.index for vertex in effect.verts])
        verts = effect.verts
        for vertex, point in zip(verts, effect.origin.tolist()):
            vertex.co = point                          # (the probe amount goes; the hand adds its own)
        bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=True)
        refresh_caches()
        bm.verts.ensure_lookup_table()
        super().__init__(ob, bm, indices, False)
        self.effect, self.plan, self.extra_verts, self.extra_base = effect, None, [], np.zeros((0, 3))
        self.scale = float(abs(np.linalg.det(self.matrix[:3, :3])) ** (1 / 3)) or 1.0
        dead = size_state.scaled(edit_tool_math.START_TRAVEL) / self.scale
        self.travel = edit_tool_math.HandTravel(dead, effect.axis)
        self.amount = 0.0
        self.final = self.base

    def apply(self, data, delta, use_scale=False):
        self.delta = np.array(delta)
        if self.alive(data) and options.values(self.tool, settings.get) != self.values:
            self._run_again(data)
        if not self.dead:
            super().apply(data, delta, use_scale)

    def _run_again(self, data):
        """A setting changed during the drag: the mesh back, the tool again; the hand keeps its travel (and axis)."""
        ob, axis = data.objects[self.ob_name], self.travel.axis
        bm, before = self.bm, self.values
        try:
            if not self.snapshot.restore(ob, bm):
                self.dead = True
                return
            try:
                self._run(ob, bm)
            except FAILED as reason:          # e.g. too many points: keep the last setting that worked
                notice(str(reason))
                for name, value in before.items():
                    settings.put(name, value)
                self.snapshot.restore(ob, bm)
                self._run(ob, bm)
        except (*DEAD, *FAILED):
            self.dead = True
            return
        if self.effect.axis is None:
            self.travel.axis = axis

    def target(self, delta, use_scale=False):
        effect = self.effect
        if effect.dirs is None:
            self.final = edit_math.move_points(self.base, edit_math.local_delta(self.matrix, self.delta))
            return self.final, self.extra_base
        start = self.hand_start
        world = self.delta[:3, :3] @ start + self.delta[:3, 3] - start
        local = np.linalg.inv(self.matrix[:3, :3]) @ world
        self.amount = float(np.clip(self.travel.amount(local) * effect.gain, effect.low, effect.high))
        self.final = effect.origin + effect.dirs * self.amount
        return self.final, self.extra_base

    def changed(self):
        if self.effect.keeps_zero:
            return True
        dead = self.travel.dead if self.effect.dirs is None else edit_math.MIN_MOVE
        return float(np.abs(self.final - self.base).max()) > dead

    def finish(self, data):
        """The grab ended: normals and triangles of the final shape."""
        if not self.alive(data):
            return
        try:
            self.bm.normal_update()
            bmesh.update_edit_mesh(data.objects[self.ob_name].data, loop_triangles=True, destructive=False)
        except DEAD:
            self.dead = True

    def restore(self, data):
        """The exact cancel (when the mesh is still the one we hold), and the snapshot goes."""
        if self.alive(data):
            self.snapshot.restore(data.objects[self.ob_name], self.bm)
            refresh_caches()
        self.close()

    def end(self, data, kept):
        """The drag is over: keep the result, or cancel it exactly."""
        if kept:
            self.close()
        else:
            self.restore(data)

    def close(self):
        self.snapshot.close()


def refresh_caches():
    """The topology changed: indices too, so every Edit cache is rebuilt now (not at the next tick)."""
    edit_state.STATE.stale = True
    edit_state.STATE.faces = None
    edit_state.sync(bpy.context)


def start(context, tool, hand_world, edge=None, hit=None):
    """Run `tool` (on `hit` alone when it is not selected: edit_grab.select_aimed) and return its ToolMoved, or None
    (refused: the reason is on the desk)."""
    state = edit_state.STATE
    bm = edit_select.live_bmesh(context, state.object_name)
    if bm is None:
        return None
    ob = context.edit_object
    state.grabbing = True
    try:
        item = ToolMoved(ob, bm, tool, hand_world, edge, hit)
    except FAILED as reason:
        state.grabbing = False
        refresh_caches()
        notice(str(reason))
        return None
    note = mirror_note(ob, options.TOOL_LABELS[tool])
    if note != options.TOOL_LABELS[tool]:
        notice(note)
    return item
