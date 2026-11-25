# SPDX-License-Identifier: GPL-3.0-or-later
"""The Subdivision ticker (bpy side): reads the row's state for the active object and steps the level on a press.

Writes the viewport `levels` only. render_levels of an existing modifier is never touched (render safety rule); a modifier
this adds is a real edit of the file, so its render_levels = the level first chosen. A level above 0 makes the modifier
show in VR through the existing Show in VR choice (modifier_state), so VR's own record still restores the original flags.

Undo: one press = one undo step. In Edit mode `ed.undo_push` records only the mesh, so a modifier change would not undo:
there the change is wrapped in an Object mode round trip (the push then lands in the global undo stack; the mesh edits are
kept). A Redo of that step lands in Object mode (the step was pushed there): `_after_redo` then puts the user back in the
mode they pressed in."""
import bpy
from bpy.app.handlers import persistent

from . import modifier_state, subdiv_math as math_
from .context_helper import run_in_view3d


def target(ob):
    """The last Subdivision Surface modifier of `ob`, or None."""
    return next((mod for mod in reversed(ob.modifiers) if mod.type == 'SUBSURF'), None)


def reason(ob):
    override = ob.override_library
    return math_.unavailable_reason(ob.type, ob.library is not None, ob.data is not None and ob.data.library is not None,
                                    bool(override and override.is_system_override))


def key(ob):
    """What the row depends on, for the desk's change key (cheap)."""
    mod = target(ob)
    return (ob.name_full, mod.levels if mod else None, mod.show_viewport if mod else None,
            mod.show_in_editmode if mod else None, reason(ob))


def view(ob):
    mod = target(ob)
    base_faces = len(ob.data.polygons) if ob.type == 'MESH' else 0
    return math_.view(mod.levels if mod else 0, reason(ob), base_faces,
                      mod.show_viewport if mod else True, mod.show_in_editmode if mod else True)


def _apply(context, ob, direction):
    mod = target(ob)
    level = mod.levels if mod else 0
    new = math_.next_level(level, direction)
    if new is None:
        return False
    if mod is None:
        mod = ob.modifiers.new("Subdivision", 'SUBSURF')
        mod.render_levels = new          # a real new modifier: its render level is what was chosen first
    mod.levels = new
    if new > 0:
        modifier_state.set_shown(context.scene, ob, mod, True)
    return True


def _run(context, call):
    """`call()` in the 3D View override; without a 3D View (headless) directly. An operator that can't run is skipped."""
    try:
        if not run_in_view3d(context, call):
            call()
    except RuntimeError as error:
        print(f"digits_vr: subdivision: {error}")


_edit_press = {}     # the last ticker press made in Edit mode: object name, level, mode (see _after_redo)


@persistent
def _after_redo(*_args):
    """Redo of an Edit mode press arrives in Object mode: go back into the mode it was pressed in (when the redone
    state is that press: same object, same level)."""
    if not _edit_press:
        return
    context = bpy.context
    ob = bpy.data.objects.get(_edit_press["name"])
    mod = target(ob) if ob is not None else None
    if (ob is None or mod is None or mod.levels != _edit_press["level"] or ob.mode != 'OBJECT'
            or context.view_layer.objects.active != ob):
        return
    _run(context, lambda: bpy.ops.object.mode_set(mode=_edit_press["mode"]))


def register():
    if _after_redo not in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.append(_after_redo)


def unregister():
    if _after_redo in bpy.app.handlers.redo_post:
        bpy.app.handlers.redo_post.remove(_after_redo)
    _edit_press.clear()


def step(context, direction):
    """A press of - (-1) or + (+1) on the active object. Returns True when something changed."""
    ob = context.active_object
    if ob is None or reason(ob):
        return False
    if ob.mode == 'OBJECT':
        changed = _apply(context, ob, direction)
        if changed:
            _run(context, lambda: bpy.ops.ed.undo_push(message="Subdivision level"))
        return changed
    name, mode = ob.name, ob.mode
    _run(context, lambda: bpy.ops.object.mode_set(mode='OBJECT'))
    ob = bpy.data.objects[name]
    changed = _apply(context, ob, direction)
    _run(context, lambda: bpy.ops.ed.undo_push(message="Subdivision level"))
    _run(context, lambda: bpy.ops.object.mode_set(mode=mode))
    mod = target(bpy.data.objects[name])
    _edit_press.update(name=name, level=mod.levels if mod else None, mode=mode)
    return changed
