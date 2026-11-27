# SPDX-License-Identifier: GPL-3.0-or-later
"""Every VR temp change put back at once: the Clean up VR changes button, file load (a crash or autosave left some)
and renders [user, 2026-11-27].
- put_back_all(): every record (Performance: settings, hidden objects, glass faces, see-through slots and fake users;
  heavy modifiers; the VR base scale) and the leftovers WITHOUT a record found by their tags (glass faces modifier,
  see-through copies, pocketed belt models); then the file's flag (perf_state.FLAG_KEY) is cleared.
- Clean up VR changes (sidebar, under Start VR): refuses while VR runs (Stop VR puts everything back anyway; the
  desk's File tab only exists in VR, so its "Restore my settings" stays a placeholder). One undo step.
- Renders: the VR changes are put back on the MAIN thread before a render builds its scene, when the flag is set (one
  property read when it is not), so a render never uses the VR stand-ins. While VR runs the copies are kept and the
  next session tick applies everything again after render_complete / render_cancel (those only set RUNTIME fields).
  - F12 / Ctrl+F12 (INVOKE) run the render handlers on the render JOB's thread (Blender source: render_startjob ->
    RE_RenderFrame -> render_init / render_pre), where writing data could crash Blender. So while VR runs, F12 and
    Ctrl+F12 are mapped to DIGITSVR_OT_render (add-on keymap, added at VR start, removed at teardown): it puts back on
    the main thread, then starts Blender's render. A render started another way (the Render menu) on another thread
    with the flag set only warns: no writes.
  - Command-line renders (-b -f / -a) and EXEC renders run the handlers on the main thread: they put back there.
  - A viewport render (OpenGL) fires no render handlers: it shows what the viewport shows."""
import threading

import bpy
from bpy.app.handlers import persistent

from . import belt_pocket, modifier_state, perf_state, user_scale
from .belt_state import BELT
from .hands import session_state
from .runtime import RUNTIME


def put_back_all(context):
    """Put back every VR temp change in this file. Returns how many came back."""
    restored = modifier_state.restore_everywhere() + perf_state.restore_everywhere() + user_scale.restore(context)
    if not BELT.running:
        belt_pocket.release_all()
    perf_state.clear_mark()
    return restored


def after_load():
    """session.py's load_post (before it resumes a running session): leftovers of a crash or autosave go."""
    restored = put_back_all(bpy.context)
    if restored:
        print(f"digits_vr: {restored} VR temp changes left in the file were put back")


def reapply():
    """Every VR change again, as the save_post handlers do (each checks that VR runs)."""
    modifier_state.on_save_post()
    perf_state.on_save_post()
    user_scale.on_save_post()


def tick():
    """Session tick: after a render, apply the VR changes again (on the main thread)."""
    if RUNTIME.reapply_after_render and not RUNTIME.rendering:
        RUNTIME.reapply_after_render = False
        reapply()


def put_back_for_render():
    """Main thread only: put the VR changes back before a render (copies kept while VR runs)."""
    if RUNTIME.rendering or not perf_state.changes_marked():
        return
    if RUNTIME.active:
        RUNTIME.rendering = True
        modifier_state.restore_everywhere()
        perf_state.restore_records()        # slots back, copies kept: the headset may still draw them
        user_scale.restore(bpy.context)
        perf_state.clear_mark()
    else:
        put_back_all(bpy.context)


@persistent
def on_render_start(*_args):
    if threading.current_thread() is threading.main_thread():
        put_back_for_render()
    elif not RUNTIME.rendering and perf_state.changes_marked():
        print("digits_vr: a render started on the render thread with VR changes in the file; they can't be put back "
              "from there. Stop VR (or use F12) before rendering from a menu")


@persistent
def on_render_end(*_args):
    if RUNTIME.rendering:
        RUNTIME.rendering = False
        RUNTIME.reapply_after_render = RUNTIME.active


class DIGITSVR_OT_clean_up(bpy.types.Operator):
    """Put back everything Digit's VR changed in this file for the time being (settings, hidden objects, modifiers, \
glass faces, see-through materials), also leftovers of a crash. Stop VR first"""
    bl_idname = "digits_vr.clean_up"
    bl_label = "Clean up VR changes"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if session_state(context) is not None:
            cls.poll_message_set("Stop VR first: stopping VR puts everything back")
            return False
        return True

    def execute(self, context):
        restored = put_back_all(context)
        self.report({'INFO'}, f"Put back {restored} VR changes" if restored else "No VR changes left to put back")
        return {'FINISHED'}


class DIGITSVR_OT_render(bpy.types.Operator):
    """Render (F12 while VR runs): the VR changes are put back first, on the main thread, then Blender's render starts"""
    bl_idname = "digits_vr.render"
    bl_label = "Render without VR changes"
    bl_options = {'INTERNAL'}

    animation: bpy.props.BoolProperty()

    def execute(self, context):
        put_back_for_render()
        result = bpy.ops.render.render('INVOKE_DEFAULT', animation=self.animation, use_viewport=True)
        if 'CANCELLED' in result:
            on_render_end()         # no render started: the VR changes come back on the next tick
        return result


_keymap_items = []


def map_render_keys():
    """While VR runs: F12 / Ctrl+F12 go through DIGITSVR_OT_render (add-on keymap, wins over the default)."""
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None or _keymap_items:
        return
    keymap = keyconfig.keymaps.new(name="Screen", space_type='EMPTY')
    for ctrl in (False, True):
        item = keymap.keymap_items.new(DIGITSVR_OT_render.bl_idname, 'F12', 'PRESS', ctrl=ctrl)
        item.properties.animation = ctrl
        _keymap_items.append((keymap, item))


def unmap_render_keys():
    for keymap, item in _keymap_items:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _keymap_items.clear()


CLASSES = (DIGITSVR_OT_clean_up, DIGITSVR_OT_render)
HANDLERS = (("render_init", on_render_start), ("render_pre", on_render_start),
            ("render_complete", on_render_end), ("render_cancel", on_render_end))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for name, function in HANDLERS:
        getattr(bpy.app.handlers, name).append(function)


def unregister():
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function in handlers:
            handlers.remove(function)
    unmap_render_keys()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
