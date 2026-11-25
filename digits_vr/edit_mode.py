# SPDX-License-Identifier: GPL-3.0-or-later
"""Entering and leaving Edit mode from the desk. Like the desktop, each switch is its own undo step: a script's
mode_set pushes none, and without the push one Ctrl+Z after an edit would leave Edit mode (audit A3)."""
import time

import bpy

from . import desk_qol_math, edit_grab, edit_math, edit_state, router, tools
from .context_helper import run_in_view3d

ENTER, LEAVE = "VR Enter Edit Mode", "VR Leave Edit Mode"


def switch(context, mode):
    """`mode` is OBJECT / POSE / ... when leaving Edit mode, or EDIT_MESH when entering it. False when nothing happened."""
    entering = mode == router.EDIT
    if entering:
        reason = _refusal_for_enter(context.active_object)
        if reason:
            desk_qol_math.NOTICE.show(reason, time.perf_counter())
            return False
    else:
        edit_grab.cancel_all(context.blend_data)       # a grab or tool drag still running: the mesh goes back before the switch
    blender_mode = 'EDIT' if entering else mode
    done = run_in_view3d(context, lambda: bpy.ops.object.mode_set(mode=blender_mode))
    if done:
        tools.push_undo(ENTER if entering else LEAVE)
    return done


def _refusal_for_enter(ob):
    """Cheap refusals before the switch (the rest shows when Edit mode is on: edit_state.reason)."""
    if ob is None or ob.type != 'MESH':
        return "Not a mesh"
    key = ob.active_shape_key
    facts = {"linked": bool(ob.library) or bool(ob.data.library), "objects_in_mode": 0,
             "key_locked": bool(ob.data.shape_keys and key is not None and key.lock_shape),
             "faces": len(ob.data.polygons), "scale_zero": False}
    return edit_math.refusal(facts)
