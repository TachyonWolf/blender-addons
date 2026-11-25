# SPDX-License-Identifier: GPL-3.0-or-later
"""Where you were before a Select button moved you: mode, active and selected objects, and in Pose Mode the active
rig's selected and active bones. The Oops Debugger's (and Pre-Render Check's) Select buttons call `keep_first`; the
Back button calls `restore`. One snapshot at a time, the FIRST one is kept until you go back or forget it, so Back
returns to what you were working on before the fixing began. `extra` carries what the caller wants back too (the
Oops "Looking for" kind). Stored as JSON on the window manager: not saved in the .blend. Nothing runs in the
background."""

import json

import bpy
from bpy.props import StringProperty

PROPERTY = "digits_position_snapshot"


def capture(context, extra=None):
    """The current position as a plain dict (JSON-able)."""
    active = context.view_layer.objects.active
    snapshot = {"mode": active.mode if active else 'OBJECT',
                "active": active.name if active else "",
                "selected": [ob.name for ob in context.view_layer.objects if ob.select_get()],
                "pose": None,
                "extra": dict(extra or {})}
    if active is not None and active.type == 'ARMATURE' and active.mode == 'POSE':
        bones = active.data.bones
        snapshot["pose"] = {"selected": [pb.name for pb in active.pose.bones if pb.select],
                            "active": bones.active.name if bones.active else ""}
    return snapshot


def current(context):
    """The kept snapshot, or None."""
    text = getattr(context.window_manager, PROPERTY, "")
    return json.loads(text) if text else None


def keep_first(context, snapshot):
    """Keep `snapshot` unless one is already kept."""
    if not getattr(context.window_manager, PROPERTY, ""):
        setattr(context.window_manager, PROPERTY, json.dumps(snapshot))


def clear(context):
    setattr(context.window_manager, PROPERTY, "")


def label(context):
    """Text for the Back button, or None when nothing is kept."""
    snapshot = current(context)
    if snapshot is None:
        return None
    place = snapshot["extra"].get("place") or snapshot["active"]   # the caller may name the place (a view), else the active object
    return f"Back to {place}" if place else "Back"


def restore_selection(context, snapshot):
    """Select the remembered objects that still exist and make the remembered active one active."""
    objects = context.view_layer.objects
    for ob in objects:
        ob.select_set(False)
    for name in snapshot["selected"]:
        if name in objects:
            objects[name].select_set(True)
    objects.active = objects.get(snapshot["active"])


def restore_pose_bones(rig, pose):
    """The remembered bones that still exist are selected, the remembered active bone is active."""
    for pose_bone in rig.pose.bones:
        pose_bone.select = pose_bone.name in pose["selected"]
    rig.data.bones.active = rig.data.bones.get(pose["active"])


def restore(context):
    """Put everything that still exists back, forget the snapshot, return its `extra` (None: nothing was kept)."""
    snapshot = current(context)
    if snapshot is None:
        return None
    put_back(context, snapshot)
    clear(context)
    return snapshot["extra"]


def put_back(context, snapshot):
    """Put a `capture` snapshot back (mode, selection, pose bone selection) for what still exists."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    restore_selection(context, snapshot)
    active = context.view_layer.objects.active
    if snapshot["pose"] and active is not None and active.type == 'ARMATURE':
        restore_pose_bones(active, snapshot["pose"])
    if active is not None and snapshot["mode"] != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode=snapshot["mode"])
        except (RuntimeError, TypeError):   # that mode no longer fits the active object
            pass


def register():
    setattr(bpy.types.WindowManager, PROPERTY, StringProperty(options={'SKIP_SAVE'}))


def unregister():
    delattr(bpy.types.WindowManager, PROPERTY)
