# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode's instant tools (EDIT_PLAN section 9): delete, merge, fill. Each is ONE function a button (or the PDA) calls
with the context: it works on the SELECTION like the desktop tools, refuses with a reason on the desk note line when the
selection doesn't fit or a drag runs, and pushes ONE undo step, or none when nothing changed. (The tools a grip drives:
edit_tools / edit_tool_drag.) Hidden parts are respected (they can't be selected). Mirror X: not applied by these ops.

They use bmesh.ops on the live edit bmesh (no 3D View needed, so they also run headless). Every topology change drops our
caches (indices change)."""
import time

import bmesh
import bpy
from mathutils import Vector

from . import desk_qol_math, edit_math, edit_pick, edit_select, edit_state, tools
from .context_helper import run_in_view3d
from .edit_tools import select_only, selected
from .runtime import RUNTIME

BUSY = "Let go of the running drag first"


def notice(reason):
    desk_qol_math.NOTICE.show(reason, time.perf_counter())


def busy():
    """True (with the reason on the desk) while an Edit grab or tool drag runs."""
    if edit_state.STATE.grabbing:
        notice(BUSY)
    return edit_state.STATE.grabbing


def mirror_note(ob, text):
    """`text` plus a hint when a mesh mirror is on: none of the tools mirrors (Blender's ops don't, only moves do)."""
    on = ob is not None and ob.type == 'MESH' and (ob.data.use_mirror_x or ob.data.use_mirror_y or ob.data.use_mirror_z)
    return f"{text} (Mirror X is on: not applied by this tool)" if on and text else text


def _run(context, tool):
    """Run `tool(bm)` -> (reason, message). Returns True when the mesh changed."""
    if edit_pick.refused(context) or busy():
        return False
    bm = edit_select.live_bmesh(context, edit_state.STATE.object_name)
    if bm is None:
        return False
    ob = context.edit_object
    reason, message = tool(bm)
    if reason:
        notice(mirror_note(ob, reason))
        return False
    bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=True)     # topology changed
    edit_state.STATE.stale = True                     # indices changed: drop every cache at the next tick
    edit_state.STATE.faces = None
    tools.push_undo(message)
    label = message.replace("VR ", "")
    if mirror_note(ob, label) != label:
        notice(mirror_note(ob, label))                # e.g. "Merge (Mirror X is on: not applied by this tool)"
    return True


def _delete(bm):
    kind = edit_state.STATE.kind
    verts, edges, faces = selected(bm)
    geom, context = ((verts, 'VERTS') if kind == edit_math.VERT else (edges, 'EDGES') if kind == edit_math.EDGE
                     else (faces, 'FACES'))
    if not geom:
        return "Nothing selected", ""
    bmesh.ops.delete(bm, geom=geom, context=context)
    return "", "VR Delete"


def _merge(bm):
    verts = selected(bm)[0]
    if len(verts) < 2:
        return "Select two or more vertices", ""
    centre = sum((vertex.co for vertex in verts), Vector()) / len(verts)
    bmesh.ops.pointmerge(bm, verts=verts, merge_co=centre)
    select_only(bm, [vertex for vertex in verts if vertex.is_valid][:1])
    return "", "VR Merge"


def _fill(bm):
    """Blender's own F (Make Edge / Face) [user, 2026-11-25: "the standard thing Blender does"]: a whole selected rim
    becomes one ngon; one or two points at a hole's edge add one triangle at that corner, so pressing again fills the gap
    step by step; two loose points get an edge."""
    verts, edges, _faces = selected(bm)
    if not verts:
        return "Select points or edges", ""
    data = bpy.context.edit_object.data
    before = (len(bm.faces), len(bm.edges))
    try:
        if not run_in_view3d(bpy.context, lambda: bpy.ops.mesh.edge_face_add()):
            bpy.ops.mesh.edge_face_add()             # no 3D View (headless): Edit mode is enough for this operator
    except RuntimeError:
        return "Nothing to fill", ""
    after_bm = bmesh.from_edit_mesh(data)
    if (len(after_bm.faces), len(after_bm.edges)) == before:
        return "Nothing to fill", ""
    return "", "VR Fill"


def delete(context):
    return _run(context, _delete)


def merge(context):
    return _run(context, _merge)


def fill(context):
    return _run(context, _fill)


TOOLS = {"delete": delete, "merge": merge, "fill": fill}


# ---- desktop undo while a drag runs ----------------------------------------------------------------------------------

REDO_AFTER = [False]      # a desktop Ctrl+Z hit while an Edit grab / tool was unfinished: put the undone step back (tick)


def undo_happened():
    """Called by the undo_post handler. An unpushed grab or tool is not an undo step, so Blender's undo took back the last
    FINISHED action too: ask for a Redo right after (the tick), so only the unfinished work is lost."""
    if any(hand_state.grab is not None and hand_state.grab.edits for hand_state in RUNTIME.hands.values()):
        REDO_AFTER[0] = True


def tick(context):
    """Session tick: after the desktop undo mid-grab / mid-tool, the Redo that keeps the last finished action."""
    if REDO_AFTER[0] and not any(hand_state.grab is not None for hand_state in RUNTIME.hands.values()):
        REDO_AFTER[0] = False
        from . import desk_actions
        desk_actions.history(context, True)
