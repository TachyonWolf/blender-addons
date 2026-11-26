# SPDX-License-Identifier: GPL-3.0-or-later
"""The viewpoints window (bpy side): save where you stand (navigation location + rotation + your size) and jump back.
Opened from the desk's Move tab. The spots are user data: kept per .blend file in a scene custom property
(viewpoint_store), saved with the file, never in the VR-only records. Go moves the open panels with you."""
import bpy
from mathutils import Matrix, Quaternion, Vector

from . import held_item, keyboard, move, panel, user_scale, viewpoint_layout as layout, viewpoint_store as store
from .panel import Panel
from .size_state import SIZE
from .tools import push_undo

SCENE_KEY = "digits_vr_viewpoints"
_view = {"page": 0}


def spots(scene):
    return store.parse(scene.get(SCENE_KEY, ""))


def _store(scene, new_spots, undo_name):
    scene[SCENE_KEY] = store.dump(new_spots)
    push_undo(undo_name)


_names = {"text": None, "names": ()}     # the spot names of the last stored text (parsed once, not each model check)


def _spot_names(scene):
    text = scene.get(SCENE_KEY, "")
    if text != _names["text"]:
        _names.update(text=text, names=tuple(spot["name"] for spot in store.parse(text)))
    return _names["names"]


def build_model(context):
    names = _spot_names(context.scene)
    first, _view["page"] = layout.page_slice(_view["page"], len(names))
    return layout.ViewpointsModel(names[first:first + layout.ROWS], first, _view["page"], layout.pages(len(names)),
                                  len(names))


def save_current(context):
    state = context.window_manager.xr_session_state
    if state is None:
        return False
    scene = context.scene
    _store(scene, store.add(spots(scene), state.navigation_location, state.navigation_rotation, SIZE.factor),
           "VR Save spot")
    _view["page"] = layout.pages(len(spots(scene))) - 1        # show the new one
    return True


def _navigation(location, rotation):
    return Matrix.LocRotScale(Vector(location), Quaternion(rotation), (1.0, 1.0, 1.0))


def go(context, index):
    """Jump to spot `index`: your size first (about your head), then the navigation. Open panels keep their place
    relative to you."""
    state = context.window_manager.xr_session_state
    saved = spots(context.scene)
    if state is None or not 0 <= index < len(saved):
        return False
    spot = saved[index]
    user_scale.set_size(context, state, spot["size"])
    before = _navigation(state.navigation_location, state.navigation_rotation)
    after = _navigation(spot["location"], spot["rotation"])
    state.navigation_location, state.navigation_rotation = after.translation, after.to_quaternion()
    panel.move_all(after @ before.inverted())
    held_item.move_all(after @ before.inverted())
    move.start(context)          # the floor plane / geometry state is measured again from the new spot
    return True


def delete(context, index):
    scene = context.scene
    saved = spots(scene)
    if not 0 <= index < len(saved):
        return False
    _store(scene, store.delete(saved, index), "VR Delete spot")
    return True


def rename(context, index, name):
    scene = context.scene
    saved = spots(scene)
    renamed = store.rename(saved, index, name)
    if renamed is saved:
        return False
    _store(scene, renamed, "VR Rename spot")
    return True


def ask_name(index):
    """Open the keyboard for spot `index`'s name (Enter renames it, Cancel keeps it)."""
    saved = spots(bpy.context.scene)
    if not 0 <= index < len(saved):
        return False
    return keyboard.ask("Name this spot", saved[index]["name"], lambda text: rename(bpy.context, index, text), near=PANEL)


def perform(context, widget, _pixel_x):
    if not widget.action or not widget.enabled:
        return False
    kind, *arguments = widget.action
    if kind == "spot_save":
        return save_current(context)
    if kind == "spot_go":
        return go(context, arguments[0])
    if kind == "spot_rename":
        return ask_name(arguments[0])
    if kind == "spot_delete":
        return delete(context, arguments[0])
    if kind == "spot_page":
        _view["page"] += arguments[0]
        return True
    return False


class ViewpointsPanel(Panel):
    name = "viewpoints"
    spec = layout.SPEC
    open_side = -0.5            # first opens to the left of the desk (clear of its handle)
    open_drop = 0.05

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget, pixel_x)

    def closed(self):
        _view["page"] = 0


PANEL = ViewpointsPanel()
