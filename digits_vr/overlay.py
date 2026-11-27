# SPDX-License-Identifier: GPL-3.0-or-later
"""Overlay drawing in the headset: our laser line and the pale blue hover glow (red-ish on linked data, which can't
be grabbed). Drawn by a SpaceView3D handler on region 'XR' (region 'WINDOW' draws nothing in VR), POST_VIEW, once
per eye. Selected items keep Blender's own orange outline.

Cheap per eye: sync() (once per session tick) builds the GPU batches in each item's own space and keeps them; the
first eye of a frame works out the model matrices, the second reuses them. The handler exists only while there is
something to draw or a drag runs; it also counts headset frames (RUNTIME.frame), which pace the drag."""
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector


from . import belt_draw, box_draw, draw_size, edit_cage, edit_loop_preview, gun_draw, hand_draw, hand_marker, help_draw, move, name_tag, object_shapes, panels, scale_meter, screenshot, sculpt_draw, select_bubble, settings, shape_math, size_state, snap_draw
from .action_map import HANDS
from .hands import aim_pose, touch_point
from .perf import TIMINGS
from .picking import BONE, armature_lines, bone_display_lines, find_object
from .runtime import RUNTIME

AIM_FORWARD = Vector((0.0, 0.0, -1.0))
LASER_COLOUR = (0.55, 0.8, 1.0, 0.8)
LASER_PAUSED = (0.6, 0.6, 0.62, 0.55)    # grey while Pause is on
HOVER_COLOUR = (0.45, 0.75, 1.0, 0.95)
LINKED_COLOUR = (1.0, 0.35, 0.3, 0.95)
LASER_WIDTH, BOX_WIDTH, BONE_WIDTH, ARMATURE_WIDTH = 3.0, 3.0, 8.0, 2.0
_shader = None
_laser_batch = None
_items = []          # [(batch, colour, width, object name, in front[, view dependent])] in the object's space (sync())
SLOW_BADGE = "Slow (B)"
SLOW_BADGE_RISE = 0.08   # m above the grip: clear of the hand, out of the way
HEAD_MOVE = 0.05     # m in your space: the outline is worked out again when the head moved this far (it depends on where you look from)
_head = [None]       # head position when the view-dependent items were built
_items_key = None    # what _items were built for: (target keys + linked flags, scene cache version)
_move_batch = [None, -1]   # [batch, move.PREVIEW.version it was built for]: the teleport arc + ring (world space)
_built = {}          # (target key, linked) -> item, for the current scene cache version


def _flat_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _batch(points):
    return batch_for_shader(_flat_shader(), 'LINES', {"pos": points})


def _target_item(target, head=None):
    """(batch, colour, width, object name) outlining a hover target in its object's space, or None."""
    ob = target.find_object(bpy.data)
    if ob is None:
        return None
    colour = LINKED_COLOUR if target.linked else HOVER_COLOUR
    if target.kind == BONE:
        pose_bone = ob.pose.bones.get(target.bone_name) if ob.pose else None
        if pose_bone is None:
            return None    # the glow is what Blender draws: the custom shape's wire, else head-tail
        return _batch(bone_display_lines(pose_bone)), colour, BONE_WIDTH, ob.name_full, True
    # no boxes: a surface: only its silhouette seen from the head, depth tested (object_shapes.outline_shape); an empty's,
    # light's or camera's lines likewise; the item says it is view dependent so sync() rebuilds it when you move
    if ob.type == 'ARMATURE':    # its visible bones' display shapes, thin, depth tested (never a box)
        return _batch(armature_lines(ob)), colour, ARMATURE_WIDTH, ob.name_full, False
    eye = ob.matrix_world.inverted_safe() @ (head if head is not None else ob.matrix_world.translation)
    shape = object_shapes.outline_shape(ob, eye)
    view = object_shapes.has_surface(ob) or bool(object_shapes.instance_parts(ob))
    return _batch(object_shapes.line_points(shape)), colour, BOX_WIDTH, ob.name_full, False, view


def needed():
    """Something to draw, or a drag running (its frame count paces the drag: controls.py)."""
    return settings.get("fine_control") or panels.any_open() or edit_cage.visible() or box_draw.visible() or belt_draw.visible() or snap_draw.visible() or hand_draw.visible() or hand_marker.visible() or gun_draw.visible() or move.visible() or sculpt_draw.visible() or select_bubble.visible() or draw_size.visible() or size_state.SIZE.gesturing or scale_meter.visible() or any(hand_state.laser_on or hand_state.laser_target or hand_state.touch_target or hand_state.grabbing
               for hand_state in RUNTIME.hands.values())


def sync():
    """Once per tick: rebuild the hover batches when the targets or the scene changed, add / remove the handler."""
    global _items_key
    if not (RUNTIME.active and needed()):
        remove()
        return
    edit_cage.update()
    edit_loop_preview.update()
    box_draw.update()
    belt_draw.update()
    snap_draw.update()
    gun_draw.update()
    hand_marker.update()
    targets = [target for hand_state in RUNTIME.hands.values()
               for target in (hand_state.laser_target, hand_state.touch_target) if target]
    if object_shapes._pending and object_shapes.advance():      # an outline got ready: draw it instead of the cross
        for target_key in [k for k, item in _built.items() if k != "version" and item and len(item) > 5 and item[5]]:
            del _built[target_key]
        _items_key = None
    key = (tuple((target.key(), target.linked) for target in targets), RUNTIME.cache.version)
    head = None
    if key != _items_key or any(len(item) > 5 and item[5] for item in _items):   # the head matters: read it
        state = bpy.context.window_manager.xr_session_state
        head = Vector(state.viewer_pose_location) if state else None
    if key == _items_key and _head[0] is not None and head is not None and (head - _head[0]).length > size_state.scaled(HEAD_MOVE):
        for target_key in [k for k, item in _built.items() if k != "version" and item and len(item) > 5 and item[5]]:
            del _built[target_key]     # an outline seen from the old spot: work it out again
        _items_key = None
    if key != _items_key:
        _items_key = key
        if _built.get("version") != RUNTIME.cache.version:   # poses or objects changed: old batches are stale
            _built.clear()
            _built["version"] = RUNTIME.cache.version
        _items.clear()
        _head[0] = head
        for target in targets:
            target_key = (target.key(), target.linked)
            if target_key not in _built:          # hover flips between two near bones: keep both batches
                _built[target_key] = _target_item(target, head)
            if _built[target_key] and _built[target_key] not in _items:   # laser and touch on one item: draw it once
                _items.append(_built[target_key])
    add()


_frame_lines = []    # [(batch, colour, width, model matrix, in front)] worked out on the first eye, reused by the second
_frame_tags = []     # [(batch, model matrix)] name tags, worked out on the first eye


def _aims(context, state):
    """Each hand's (aim location, aim rotation), read once per frame for the lasers and the name tags."""
    return [aim_pose(context, state, index) for index in range(len(HANDS))]


def _lines_this_frame(aims):
    global _laser_batch
    if _laser_batch is None:
        _laser_batch = _batch([(0, 0, 0), (0, 0, -1)])   # aim space: the aim pose points along -Z
    lines = []
    length = size_state.laser_length()
    for index, hand in enumerate(HANDS):
        hand_state = RUNTIME.hands[hand]
        panel_reach = panels.laser_reach(hand)
        if hand_state.laser_on or panel_reach is not None:
            reach = panel_reach or (hand_state.laser_target.distance if hand_state.laser_target else length)
            location, rotation = aims[index]
            model = Matrix.LocRotScale(location, rotation, (1, 1, reach))
            lines.append((_laser_batch, LASER_PAUSED if settings.get("paused") else LASER_COLOUR, LASER_WIDTH, model, False))
    if move.PREVIEW.points:
        if _move_batch[1] != move.PREVIEW.version:
            _move_batch[:] = [_batch(move.PREVIEW.points), move.PREVIEW.version]
        lines.append((_move_batch[0], move.PREVIEW.colour, LASER_WIDTH + 1, Matrix.Identity(4), False))
    lines += sculpt_draw.lines(aims, _batch)
    lines += select_bubble.lines(aims, _batch)
    lines += draw_size.lines(aims, _batch)
    for batch, colour, width, object_name, in_front, *_ in _items:
        ob = find_object(bpy.data, object_name)
        if ob is not None:   # in front: only a bone's glow (it runs inside Blender's bone shape); the rest is depth tested
            lines.append((batch, colour, width, ob.matrix_world.copy(), in_front))
    return lines


def _tags_this_frame(context, state, aims):
    """Name tags of what each hand points at / touches: the laser's hit spot or the touching hand, a bit above."""
    head = state.viewer_pose_location
    tags, named = [], set()
    if settings.get("fine_control"):     # the Slow badge: a small tag above each wrist while B's slow mode is on [user]
        for index in range(len(HANDS)):
            wrist = Vector(state.controller_grip_location_get(context, index))
            base, right, up, height = shape_math.tag_frame(wrist + Vector((0.0, 0.0, size_state.scaled(SLOW_BADGE_RISE))), head, size=size_state.SIZE.factor)
            tags.append((SLOW_BADGE, base, right, up, height))
    if not settings.get("name_tag"):
        return tags
    for index, hand in enumerate(HANDS):
        hand_state = RUNTIME.hands[hand]
        for target, laser in ((hand_state.laser_target, True), (hand_state.touch_target, False)):
            if target is None or target.key() in named:
                continue           # nothing there, or its name already shows (the laser's tag wins over the touch's)
            named.add(target.key())
            if laser:
                location, rotation = aims[index]
                point = location + (rotation @ AIM_FORWARD) * target.distance
            else:
                point = touch_point(context, state, index, hand_state.hover_source)
            base, right, up, height = shape_math.tag_frame(point, head, size=size_state.SIZE.factor)
            tags.append((target.bone_name if target.kind == BONE else target.object_name, base, right, up, height))
    return tags


def _draw_lines():
    """This eye's lines: one shader bind; the colour, line width and depth test set only when they change."""
    shader = _flat_shader()
    shader.bind()
    width = depth = shown = None
    for batch, colour, line_width, model, in_front in _frame_lines:
        wanted = 'NONE' if in_front else 'LESS_EQUAL'
        if wanted != depth:
            gpu.state.depth_test_set(wanted)
            depth = wanted
        if line_width != width:
            gpu.state.line_width_set(line_width)
            width = line_width
        if colour is not shown:          # both lasers share one colour
            shader.uniform_float("color", colour)
            shown = colour
        gpu.matrix.push()       # push / pop: cheaper than the push_pop() context; try keeps the stack balanced
        try:
            gpu.matrix.multiply_matrix(model)
            batch.draw(shader)
        finally:
            gpu.matrix.pop()


_xr = [None, None]   # [context, XR session state] read on the first eye, reused by the second


def draw():
    if not RUNTIME.active:
        return
    new_frame = TIMINGS.frame_mark()
    with TIMINGS.measure("draw"):
        if new_frame:
            RUNTIME.frame += 1
            context = bpy.context
            state = context.window_manager.xr_session_state
            _xr[:] = [context, state]
            if state is None:
                _frame_lines.clear()
                _frame_tags.clear()
            else:
                aims = _aims(context, state)
                _frame_lines[:] = _lines_this_frame(aims)
                tags = _tags_this_frame(context, state, aims)
                if scale_meter.visible():       # size readout + ruler (VR only; nothing runs while it is off)
                    ruler, ruler_tags = scale_meter.frame(state)
                    if ruler:
                        _frame_lines.append(ruler)
                    tags += ruler_tags
                tags += gun_draw.tags(state) + edit_loop_preview.tags(state)
                if settings.get("help_on"):              # Help: small tips beside panel widgets
                    tags = tags + help_draw.tips(state)
                _frame_tags[:] = name_tag.matrices(tags)
        panels.draw(new_frame)
        hand_draw.draw(new_frame, *_xr)
        gun_draw.draw()
        hand_marker.draw(new_frame, *_xr)
        edit_cage.draw()
        edit_loop_preview.draw()
        box_draw.draw()
        belt_draw.draw()
        snap_draw.draw()
        if not _frame_lines and not _frame_tags:
            return
        gpu.state.blend_set('ALPHA')
        if _frame_lines:
            _draw_lines()
            gpu.state.line_width_set(1.0)
        name_tag.draw(_frame_tags)
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')


def draw_and_capture():
    """The registered handler: draw, then (only when the Screenshot button asked) read this eye's picture back."""
    draw()
    if screenshot.WANTED:
        screenshot.capture()
    if screenshot.WRITING:
        screenshot.poll()


def add():
    if RUNTIME.draw_handle is None:
        RUNTIME.draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_and_capture, (), 'XR', 'POST_VIEW')


def remove():
    global _items_key
    screenshot.clear()              # a press not yet shot must not fire in the next session
    _items.clear()
    _built.clear()
    _items_key = None
    _head[0] = None
    _frame_tags.clear()
    hand_draw.clear()
    hand_marker.clear()
    name_tag.clear()           # the tag atlas: freed only at the session end
    scale_meter.clear()
    belt_draw.clear()
    _move_batch[:] = [None, -1]
    if RUNTIME.draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(RUNTIME.draw_handle, 'XR')
        RUNTIME.draw_handle = None
