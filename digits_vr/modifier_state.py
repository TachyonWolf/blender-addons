# SPDX-License-Identifier: GPL-3.0-or-later
"""Modifier VR state + file safety. While VR runs, heavy modifiers are off in the viewport (show_viewport; renders
untouched) unless switched on per modifier. The turned-off ones are recorded on the scene by the shared
viewport_modifiers.py (same logic as Fast Viewport), so restore turns back on exactly those.

File safety (Q2, A16, A17), all through @persistent handlers:
- save_pre restores the flags and drops the record, save_post turns them off again: a saved file never has them off.
- After a load (session.py's load_post) any record left in a file is restored (crash, autosave, quit.blend: those
  run no save handlers).
- After undo / redo (session.py's handlers): during VR re-apply (an undo can bring back flags from before VR);
  after VR restore any record the undo brought back."""
import bpy
from bpy.app.handlers import persistent

from . import glass_faces, modifier_policy as policy, settings, viewport_modifiers  # viewport_modifiers: generated copy
from .runtime import RUNTIME

RECORD_KEY = "digits_vr_modifiers_off"        # Scene: viewport_modifiers record (what VR turned off)
CHOICES_KEY = "digits_vr_modifier_choices"    # Scene: JSON {choice key: shown in VR}, only the non-default ones


def user_modifiers(ob):
    """The object's modifiers, without the ones VR adds itself (glass faces hidden): those are never listed, chosen
    or turned off."""
    return [mod for mod in ob.modifiers if not glass_faces.is_ours(mod)]


def modifier_key(ob, mod):
    return policy.choice_key(ob.name, ob.library.filepath if ob.library else "", mod.persistent_uid)


def choices(scene):
    return policy.read_choices(scene.get(CHOICES_KEY, ""))


def is_shown(scene, ob, mod, scene_choices=None):
    scene_choices = choices(scene) if scene_choices is None else scene_choices
    return policy.shown_in_vr(mod.type, scene_choices.get(modifier_key(ob, mod)))


def is_off_for_vr(scene, ob, mod):
    """True while VR has this modifier off (it is in the record)."""
    uid = mod.persistent_uid
    return any(entry[0] == ob.name_full and entry[2] == uid for entry in viewport_modifiers.recorded(scene, RECORD_KEY))


def hide_for_vr(scene):
    """Turn off what should not show in VR. Returns (turned off, skipped as linked)."""
    if not settings.get("hide_heavy_modifiers"):
        return 0, 0
    scene_choices = choices(scene)
    pairs = [(ob, mod) for ob in scene.objects for mod in user_modifiers(ob)
             if mod.show_viewport and not is_shown(scene, ob, mod, scene_choices)]
    return viewport_modifiers.turn_off(scene, RECORD_KEY, pairs)


def restore(scene):
    return viewport_modifiers.restore(scene, RECORD_KEY)


def restore_everywhere():
    """Restore every scene's record (teardown and repair). Returns how many came back on."""
    return sum(restore(scene) for scene in bpy.data.scenes if RECORD_KEY in scene)


def reapply(scene):
    """Bring the flags in line with the current choices: restore what should now show, turn off what should not."""
    if not settings.get("hide_heavy_modifiers"):
        restore(scene)
        return
    scene_choices = choices(scene)
    viewport_modifiers.restore(scene, RECORD_KEY, keep=lambda ob, mod: not is_shown(scene, ob, mod, scene_choices))
    hide_for_vr(scene)


def set_shown(scene, ob, mod, shown):
    """Store one modifier's Show in VR choice (and apply it now when VR runs)."""
    updated = policy.set_choice(choices(scene), modifier_key(ob, mod), mod.type, shown)
    if updated:
        scene[CHOICES_KEY] = policy.write_choices(updated)
    elif CHOICES_KEY in scene:
        del scene[CHOICES_KEY]
    if RUNTIME.active:
        reapply(scene)


def _on_hide_heavy_changed(_value):
    if RUNTIME.active:
        reapply(bpy.context.scene)


# ---------------------------------------------------------------------------
# File safety handlers
# ---------------------------------------------------------------------------

@persistent
def on_save_pre(*_args):
    if RUNTIME.active:
        restore_everywhere()


@persistent
def on_save_post(*_args):
    if RUNTIME.active:
        hide_for_vr(bpy.context.scene)


def after_undo():
    """Called by session.py's undo_post / redo_post."""
    if RUNTIME.active:
        reapply(bpy.context.scene)
    else:
        restore_everywhere()


HANDLERS = (("save_pre", on_save_pre), ("save_post", on_save_post))


def register():
    for name, function in HANDLERS:
        getattr(bpy.app.handlers, name).append(function)
    settings.LISTENERS.setdefault("hide_heavy_modifiers", []).append(_on_hide_heavy_changed)


def unregister():
    settings.LISTENERS.get("hide_heavy_modifiers", []).remove(_on_hide_heavy_changed)
    for name, function in HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if function in handlers:
            handlers.remove(function)
