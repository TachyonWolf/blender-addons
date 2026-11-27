# SPDX-License-Identifier: GPL-3.0-or-later
"""The Find window (bpy side; matching in find_match.py, screen in find_layout.py): type a name with the VR keyboard and
see the matches live: objects, the bones of the active armature (Pose mode) and collections. A name card selects the
item (it becomes active and the only one selected); Go selects it and takes you there: you turn to face it and stand a
short way in front of it, at eye height, and the open panels move with you (like the Viewpoints Go).
Objects obey the workspace the way Select does: only workspace objects that can be picked are listed, and objects can be
chosen in Object mode only (Pose mode: bones; Edit mode: nothing). A collection selects its pickable objects."""
from dataclasses import dataclass

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import desk_qol_math as math_, held_item, keyboard, move, panel, router, selection, settings, size_state, workspace
from . import find_layout as layout
from .blender_icons import COLLECTION_ICON, object_icon
from .find_match import BONE, COLLECTION, HEADER, OBJECT, Item, counts, search
from .panel import Panel
from .panel_layout import scroll_window
from .panel_state import OPEN
from .picking import Target, find_object, pickable
from .picking import BONE as BONE_TARGET, OBJECT as OBJECT_TARGET
from .tools import push_undo

AWAY_PER_RADIUS = 2.5       # you stand this many radii of the item in front of it ...
MIN_AWAY = 1.2              # ... but never nearer than this many metres (at your size 1)
BONE_ICON = "OBJECT_DATA"


@dataclass
class FindState:
    query: str = ""
    scroll: int = 0


STATE = FindState()
_cache = {"key": None, "matches": []}


# -- what can be found ---------------------------------------------------------------------------------------------

def candidates(context):
    """Every item a search may list now (workspace and pick rules; bones only in Pose mode)."""
    scene, layer = context.scene, context.view_layer
    items = []
    if router.mode_kind(context.mode) != router.EDIT:
        items += [Item(OBJECT, ob.name_full, ob.name, object_icon(ob)) for ob in layer.objects
                  if pickable(ob, layer) and workspace.contains(scene, ob)]
    active = context.active_object
    if router.mode_kind(context.mode) == router.POSE and active is not None and active.type == 'ARMATURE':
        items += [Item(BONE, pose_bone.name, pose_bone.name, BONE_ICON, active.name_full) for pose_bone in active.pose.bones
                  if not pose_bone.hide and not pose_bone.bone.hide_select]
    items += [Item(COLLECTION, collection.name_full, collection.name, COLLECTION_ICON)
              for collection in scene.collection.children_recursive if not collection.hide_select]
    return items


def matches(context):
    """The search result for the current query, kept until the query, the workspace or the scene lists change."""
    active = context.active_object
    key = (STATE.query, workspace.key(context.scene), context.mode, active.name_full if active else "")
    if key != _cache["key"]:
        _cache.update(key=key, matches=search(STATE.query, candidates(context)) if STATE.query.strip() else [])
    return _cache["matches"]


def _is_selected(context, item):
    if item.kind == OBJECT:
        ob = find_object(context.blend_data, item.key)
        return bool(ob and ob.name in context.view_layer.objects and ob.select_get(view_layer=context.view_layer))
    if item.kind == BONE:
        ob = find_object(context.blend_data, item.owner)
        pose_bone = ob.pose.bones.get(item.key) if ob else None
        return bool(pose_bone and pose_bone.select)
    return False


def build_model(context):
    found = matches(context)
    STATE.scroll, last = scroll_window(len(found), layout.ROWS, STATE.scroll)
    shown = found[STATE.scroll:STATE.scroll + layout.ROWS]
    rows = tuple((item.kind, item.key, item.label, item.icon, item.owner,
                  item.kind != HEADER and _is_selected(context, item)) for item in shown)
    chosen = workspace.current(context.scene)
    return layout.FindModel(STATE.query, rows, STATE.scroll, last, counts(found),
                            router.mode_kind(context.mode) == router.OBJECT, chosen.name if chosen else "")


# -- selecting and going -------------------------------------------------------------------------------------------

def _objects_of(context, kind, key, owner):
    """The (objects) an item stands for, only those that may be acted on now."""
    scene, layer = context.scene, context.view_layer
    if kind == COLLECTION:
        collection = next((each for each in scene.collection.children_recursive if each.name_full == key), None)
        return [ob for ob in (collection.all_objects if collection else ())
                if ob.name in layer.objects and pickable(ob, layer) and workspace.contains(scene, ob)]
    ob = find_object(context.blend_data, owner if kind == BONE else key)
    return [ob] if ob is not None and ob.name in layer.objects and pickable(ob, layer) and workspace.contains(scene, ob) else []


def select(context, kind, key, owner=""):
    """Make the item the selection. True when it was possible."""
    mode = router.mode_kind(context.mode)
    objects = _objects_of(context, kind, key, owner)
    if not objects:
        return False
    if kind == BONE:
        return mode == router.POSE and selection.apply(context, Target(BONE_TARGET, objects[0].name_full, key), router.REPLACE)
    if mode != router.OBJECT:
        return False
    selection.apply(context, None, router.CLEAR)
    for ob in objects:
        ob.select_set(True)
    context.view_layer.objects.active = objects[0]
    return True


def world_points(context, kind, key, owner):
    """World points of the item (bounding box corners, or a bone's head and tail)."""
    if kind == BONE:
        ob = find_object(context.blend_data, owner)
        pose_bone = ob.pose.bones.get(key) if ob else None
        return [ob.matrix_world @ pose_bone.head, ob.matrix_world @ pose_bone.tail] if pose_bone else []
    points = []
    for ob in _objects_of(context, kind, key, owner):
        corners = [ob.matrix_world @ Vector(corner) for corner in ob.bound_box] if ob.type != 'EMPTY' else []
        points += corners or [ob.matrix_world.translation]
    return points


def go_navigation(navigation_location, navigation_rotation, head, head_forward, points, head_height, size):
    """New (navigation location, rotation) that put you in front of `points`: turned to face their middle, standing
    `AWAY_PER_RADIUS` radii (at least MIN_AWAY x your size) away on the side you are on, head at `head_height`. Pure maths."""
    centre = math_.centre_of(points)
    radius = max((Vector(point) - centre).length for point in points)
    head = Vector(head)
    flat = Vector((centre.x - head.x, centre.y - head.y, 0.0))
    if flat.length < 1e-4:                  # right on top of it: keep looking where you look
        flat = Vector((head_forward[0], head_forward[1], 0.0))
    if flat.length < 1e-4:
        flat = Vector((0.0, 1.0, 0.0))
    flat.normalize()
    away = max(MIN_AWAY * size, AWAY_PER_RADIUS * radius)
    location, rotation = math_.recenter(navigation_location, navigation_rotation, head, head_forward, centre, head_height)
    stand = centre - flat * away
    return location + Vector((stand.x - head.x, stand.y - head.y, 0.0)), rotation


def go(context, kind, key, owner=""):
    """Select the item and stand in front of it; the open panels move with you. True when it worked."""
    state = context.window_manager.xr_session_state
    points = world_points(context, kind, key, owner)
    if state is None or not points or not select(context, kind, key, owner):
        return False
    head = Vector(state.viewer_pose_location)
    forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
    before = Matrix.LocRotScale(Vector(state.navigation_location), state.navigation_rotation, (1.0, 1.0, 1.0))
    location, rotation = go_navigation(state.navigation_location, state.navigation_rotation, head, forward, points,
                                       settings.get("plane_height") + size_state.eye_height(), size_state.SIZE.factor)
    state.navigation_location, state.navigation_rotation = location, rotation
    after = Matrix.LocRotScale(Vector(location), rotation, (1.0, 1.0, 1.0))
    panel.move_all(after @ before.inverted())
    held_item.move_all(after @ before.inverted())
    move.size_changed(state)
    return True


# -- the window ----------------------------------------------------------------------------------------------------

def _set_query(text):
    STATE.query, STATE.scroll = text, 0


def ask():
    """Open the keyboard for the search text: the list follows every key; Cancel puts the old text back."""
    old = STATE.query
    return keyboard.ask("Find by name", old, _set_query, on_cancel=lambda: _set_query(old), near=PANEL,
                        on_change=_set_query)


def perform(context, widget, _pixel_x):
    if not widget.action or not widget.enabled:
        return False
    kind, *arguments = widget.action
    if kind == "find_ask":
        return ask()
    if kind == "find_clear":
        _set_query("")
        return True
    if kind == "find_scroll":
        STATE.scroll = max(0, STATE.scroll + arguments[0])
        return True
    if kind in ("find_select", "find_go"):
        done = (select if kind == "find_select" else go)(context, *arguments)
        if done:
            push_undo("VR Find")
        return done
    return False


class FindPanel(Panel):
    name = "find"
    spec = layout.SPEC
    open_side = 0.5             # first opens to the right of the desk, the viewpoints window is on the left
    open_drop = 0.05

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget, pixel_x)

    def toggle(self, context, state):
        """Opened by the desk button: the keyboard opens with it (typing is what you came to do)."""
        action = super().toggle(context, state)
        if action == OPEN:
            ask()
        return action


PANEL = FindPanel()
