# SPDX-License-Identifier: GPL-3.0-or-later
"""Annotate (M6): draw in 3D in Object mode. While the Annotate tool is lit, the trigger draws a stroke from the controller tip:
a point per headset frame, spaced by a minimum distance (annotate_math). The strokes are normal Blender annotations
(`Scene.annotation`, one layer per colour + thickness, named "VR <colour> <n>"), so they show on the desktop and
save with the file. One undo step per stroke. Erase last and Clear all touch only our "VR ..." layers, never the
user's own notes. Controls (controls.py) calls begin / update / end; the desk calls the rest."""
from dataclasses import dataclass, field

import bpy

from . import annotate_math as math_, edit_tool_settings, router, settings
from .stroke_recorder import StrokeRecorder
from .tools import push_undo

NOTES_NAME = "VR Notes"


@dataclass
class State:
    stroke: object = None
    recorder: StrokeRecorder = field(default_factory=StrokeRecorder)    # the shared hand sampling
    where: tuple = ()               # (layer name, frame number) of the running stroke
    drawn: list = field(default_factory=list)   # (layer name, frame number) per finished stroke, oldest first

    @property
    def drawing(self):
        return self.stroke is not None


STATE = State()


def _vr_layers(scene):
    annotation = scene.annotation
    return [layer for layer in annotation.layers if math_.is_ours(layer.info)] if annotation else []


def stroke_count(scene):
    return sum(len(frame.strokes) for layer in _vr_layers(scene) for frame in layer.frames)


def _layer_for(scene, color_id, thickness):
    """The layer for a colour + thickness (made when missing, with the annotation datablock itself)."""
    if scene.annotation is None:
        scene.annotation = bpy.data.annotations.new(NOTES_NAME)
    name = math_.layer_name(color_id, thickness)
    layer = next((item for item in scene.annotation.layers if item.info == name), None)
    if layer is None:
        layer = scene.annotation.layers.new(name)
        layer.color = _rgb(color_id)
        layer.thickness = thickness
    return layer


def _rgb(color_id):
    code = math_.color_code(color_id)
    return tuple(int(code[index:index + 2], 16) / 255.0 for index in (1, 3, 5))


def _frame_for(layer, frame_number):
    return next((frame for frame in layer.frames if frame.frame_number == frame_number), None) \
        or layer.frames.new(frame_number)


def begin(context, state, hand):
    """Trigger pull while Annotate is on: start a stroke at the controller tip."""
    if STATE.drawing:
        return
    scene = context.scene
    layer = _layer_for(scene, settings.get("annotate_color"), int(round(settings.get("annotate_thickness"))))
    frame = _frame_for(layer, scene.frame_current)
    STATE.stroke = frame.strokes.new()
    STATE.stroke.display_mode = '3DSPACE'
    STATE.recorder.begin(hand)
    STATE.where = (layer.info, frame.frame_number)
    _add_point(context, state, first=True)


def _add_point(context, state, first=False):
    point = STATE.recorder.sample(context, state, once_per_frame=not first)
    if point is None:
        return
    points = STATE.stroke.points
    points.add(1)
    points[len(points) - 1].co = point


def update(context, state):
    """Once per session tick: one more point per headset frame. True while a stroke runs (the timer then runs every
    frame)."""
    if not STATE.drawing:
        return False
    if STATE.recorder.stale:        # undo / redo ran: the stroke object is stale
        _forget()
        return False
    _add_point(context, state)
    return True


def _forget():
    STATE.stroke = None
    STATE.recorder.stop()


def end(context):
    """Trigger let go: a stroke of two or more points is one undo step; a tap leaves nothing."""
    if not STATE.drawing:
        return
    layer_name, frame_number = STATE.where
    stroke, stale = STATE.stroke, STATE.recorder.stale
    _forget()
    if stale:
        return
    if len(stroke.points) < 2:
        annotation = context.scene.annotation
        layer = next((item for item in annotation.layers if item.info == layer_name), None) if annotation else None
        frame = next((item for item in layer.frames if item.frame_number == frame_number), None) if layer else None
        if frame is not None:
            frame.strokes.remove(stroke)
        return
    STATE.drawn.append((layer_name, frame_number))
    push_undo("VR Annotate")


def session_start():
    """A session never starts with Annotate lit (the trigger would draw at once): a saved Annotate tool starts on Grab."""
    if settings.get("object_tool") == edit_tool_settings.ANNOTATE:
        settings.put("object_tool", edit_tool_settings.GRAB)


def is_on(context):
    """The Annotate tool is lit (Tools > Object > Annotate): the trigger draws."""
    return router.annotate_on(router.mode_kind(context.mode), settings.get("object_tool"))


def erase_last(context):
    """Remove the stroke drawn last (that still exists). One undo step."""
    annotation = context.scene.annotation
    while STATE.drawn and annotation:
        layer_name, frame_number = STATE.drawn.pop()
        layer = next((item for item in annotation.layers if item.info == layer_name), None)
        frame = next((item for item in layer.frames if item.frame_number == frame_number), None) if layer else None
        if frame is not None and len(frame.strokes):
            frame.strokes.remove(frame.strokes[len(frame.strokes) - 1])
            push_undo("VR Erase Stroke")
            return True
    return False


def clear_all(context):
    """Remove every stroke on our layers. One undo step."""
    cleared = False
    for layer in _vr_layers(context.scene):
        for frame in list(layer.frames):
            layer.frames.remove(frame)
            cleared = True
    STATE.drawn.clear()
    if cleared:
        push_undo("VR Clear Annotations")
    return cleared


def teardown(commit=True):
    """Session over: finish a running stroke (kept as an undo step when `commit`)."""
    if STATE.drawing and commit:
        end(bpy.context)
    _forget()
    STATE.drawn.clear()
