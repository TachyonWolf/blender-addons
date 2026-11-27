# SPDX-License-Identifier: GPL-3.0-or-later
"""Grease Pencil drawing (Draw mode on a Grease Pencil object). The trigger draws a stroke from the controller tip
(the shared stroke recorder, like Annotate) into the object's active layer at the current frame, through the
Grease Pencil v3 data API: `drawing.add_strokes`, then points by position / radius. Points are in the object's local
space. One undo step per stroke. The desk's Tools page (materials, radius, layers, Erase last, Clear layer) calls the
rest. Controls (controls.py) calls begin / update / end."""
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

from . import gpencil_math as math_, settings
from .size_state import scaled
from .stroke_recorder import StrokeRecorder
from .tools import push_undo

DRAW_MODE = 'PAINT_GREASE_PENCIL'


@dataclass
class State:
    recorder: StrokeRecorder = field(default_factory=lambda: StrokeRecorder(math_.MIN_POINT_DISTANCE))
    object_name: str = ""
    layer_name: str = ""
    frame_number: int = 0
    stroke_index: int = -1          # the running stroke in its drawing (-1 = none)
    to_local: object = None         # the object's inverse world matrix, taken at the stroke's start
    radius: float = 0.01
    count: int = 0                  # points written so far

    @property
    def drawing(self):
        return self.stroke_index >= 0


STATE = State()


def active_object(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'GREASEPENCIL' else None


def active_layer(context):
    ob = active_object(context)
    return ob.data.layers.active if ob is not None else None


def _held_drawing(layer, frame_number=None):
    """The drawing of the layer's frame at `frame_number` (default: shown at the current frame), None when none."""
    frame = layer.current_frame() if frame_number is None else next(
        (item for item in layer.frames if item.frame_number == frame_number), None)
    return frame.drawing if frame is not None else None


def stroke_count(context):
    """Strokes the active layer shows at this frame (Erase last / Clear layer need one)."""
    layer = active_layer(context)
    drawing = _held_drawing(layer) if layer is not None else None
    return len(drawing.strokes) if drawing is not None else 0


def _frame_for(layer, frame_number):
    return next((item for item in layer.frames if item.frame_number == frame_number), None) \
        or layer.frames.new(frame_number)


def _drawing_of(context, state):
    ob = bpy.data.objects.get(state.object_name)
    layer = ob.data.layers.get(state.layer_name) if ob is not None else None
    return _held_drawing(layer, state.frame_number) if layer is not None else None


def _write(drawing, state, point, first):
    stroke = drawing.strokes[state.stroke_index]
    if not first:
        stroke.add_points(1)
    spot = drawing.strokes[state.stroke_index].points[state.count]
    spot.position = state.to_local @ Vector(point)
    spot.radius = state.radius
    state.count += 1


def begin(context, state, hand):
    """Trigger pull in Draw mode: start a stroke at the controller tip. Nothing when the layer is locked or hidden."""
    if STATE.drawing:
        return
    ob = active_object(context)
    if ob is None:
        return
    layer = ob.data.layers.active or ob.data.layers.new(math_.LAYER_NAME)
    if layer.lock or layer.hide:
        return
    frame = _frame_for(layer, context.scene.frame_current)
    drawing = frame.drawing
    drawing.add_strokes([1])
    STATE.object_name, STATE.layer_name, STATE.frame_number = ob.name, layer.name, frame.frame_number
    STATE.stroke_index, STATE.count = len(drawing.strokes) - 1, 0
    STATE.to_local = ob.matrix_world.inverted()
    STATE.radius = scaled(settings.get("gp_radius"))
    drawing.strokes[STATE.stroke_index].material_index = max(0, ob.active_material_index)
    STATE.recorder.begin(hand)
    point = STATE.recorder.sample(context, state, once_per_frame=False)
    _write(drawing, STATE, point, first=True)


def update(context, state):
    """Once per session tick: one more point per headset frame. True while a stroke runs (the timer then runs every
    frame)."""
    if not STATE.drawing:
        return False
    drawing = _drawing_of(context, STATE)
    if STATE.recorder.stale or drawing is None or STATE.stroke_index >= len(drawing.strokes):
        _forget()                   # undo / redo ran: the stroke is gone or stale
        return False
    point = STATE.recorder.sample(context, state)
    if point is not None:
        _write(drawing, STATE, point, first=False)
        drawing.tag_positions_changed()
    return True


def _forget():
    STATE.stroke_index, STATE.to_local = -1, None
    STATE.recorder.stop()


def end(context):
    """Trigger let go: a stroke of two or more points is one undo step; a tap leaves nothing."""
    if not STATE.drawing:
        return
    drawing, stale, points = _drawing_of(context, STATE), STATE.recorder.stale, STATE.count
    index = STATE.stroke_index
    _forget()
    if stale or drawing is None or index >= len(drawing.strokes):
        return
    drawing.tag_positions_changed()
    if points < 2:
        drawing.remove_strokes(indices=[index])
        return
    push_undo("VR Grease Pencil Stroke")


def erase_last(context):
    """Remove the newest stroke of the active layer at this frame. One undo step."""
    layer = active_layer(context)
    drawing = _held_drawing(layer) if layer is not None else None
    if drawing is None or not len(drawing.strokes):
        return False
    drawing.remove_strokes(indices=[len(drawing.strokes) - 1])
    push_undo("VR Erase Stroke")
    return True


def clear_layer(context):
    """Remove every stroke of the active layer at this frame. One undo step."""
    layer = active_layer(context)
    drawing = _held_drawing(layer) if layer is not None else None
    if drawing is None or not len(drawing.strokes):
        return False
    drawing.remove_strokes(indices=list(range(len(drawing.strokes))))
    push_undo("VR Clear Layer")
    return True


def set_material(context, index):
    ob = active_object(context)
    if ob is None or not 0 <= index < len(ob.material_slots):
        return False
    ob.active_material_index = index
    return True


def step_layer(context, step):
    """Make the next / previous layer the active one (held at both ends)."""
    ob = active_object(context)
    if ob is None or not len(ob.data.layers):
        return False
    layers = list(ob.data.layers)
    current = layers.index(ob.data.layers.active) if ob.data.layers.active in layers else 0
    target = math_.step_index(current, len(layers), step)
    if target == current and ob.data.layers.active is not None:
        return False
    ob.data.layers.active = layers[target]
    return True


def set_layer(context, index):
    """Make layer `index` the active one (the desk's Layer dropdown)."""
    ob = active_object(context)
    if ob is None or not 0 <= index < len(ob.data.layers):
        return False
    layer = list(ob.data.layers)[index]
    if ob.data.layers.active == layer:
        return False
    ob.data.layers.active = layer
    return True


def add_layer(context):
    """A new layer after the active one, named by Blender ("Layer", "Layer.001", ...), made the active one. One undo
    step. Returns the layer (None without a Grease Pencil object)."""
    ob = active_object(context)
    if ob is None:
        return None
    layer = ob.data.layers.new(math_.LAYER_NAME)
    ob.data.layers.active = layer
    push_undo("VR Add Layer")
    return layer


def rename_layer(context, name):
    """Give the active layer the typed name (Blender keeps it unique). One undo step."""
    layer = active_layer(context)
    name = name.strip()
    if layer is None or not name or name == layer.name:
        return False
    layer.name = name
    push_undo("VR Rename Layer")
    return True


def material_color(context):
    """('#rrggbb', alpha) of the active material's stroke colour (the picker's start when editing it)."""
    ob = active_object(context)
    mat = ob.active_material if ob is not None else None
    style = mat.grease_pencil if mat is not None else None
    return (math_.srgb_hex(style.color), style.color[3]) if style is not None else ("#000000", 1.0)


def set_material_color(context, code, alpha=1.0):
    """The active material's stroke colour. One undo step."""
    ob = active_object(context)
    mat = ob.active_material if ob is not None else None
    if mat is None or mat.grease_pencil is None:
        return False
    mat.grease_pencil.color = (*math_.linear_rgb(code), alpha)
    push_undo("VR Edit Colour")
    return True


def add_material(context, code, alpha=1.0):
    """A new stroke material of colour `code` ('#rrggbb', named by Blender: "Material", "Material.001", ...), added to
    the object's slots and made the active one. One undo step. Returns its slot index (-1 without an object)."""
    ob = active_object(context)
    if ob is None:
        return -1
    mat = bpy.data.materials.new(math_.MATERIAL_NAME)
    bpy.data.materials.create_gpencil_data(mat)
    mat.grease_pencil.color = (*math_.linear_rgb(code), alpha)
    ob.data.materials.append(mat)
    ob.active_material_index = len(ob.material_slots) - 1
    push_undo("VR Add Colour")
    return ob.active_material_index


def view(context):
    """What the Tools page shows: (materials [(name, hex)], active material, layer name, layer index, layer count,
    strokes, layer names)."""
    ob = active_object(context)
    if ob is None:
        return (), 0, "", 0, 0, 0, ()
    materials = []
    for slot in ob.material_slots[:math_.MAX_SWATCHES]:
        mat = slot.material
        style = mat.grease_pencil if mat is not None else None
        materials.append((mat.name if mat else "", math_.srgb_hex(style.color) if style else "#808080"))
    layers = list(ob.data.layers)
    active = ob.data.layers.active
    return (tuple(materials), ob.active_material_index, active.name if active else "",
            layers.index(active) if active in layers else 0, len(layers), stroke_count(context),
            tuple(layer.name for layer in layers))


def _palette_material(name, rgb):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        bpy.data.materials.create_gpencil_data(mat)
        mat.grease_pencil.color = (*rgb, 1.0)
    return mat


def new_object(context, location):
    """A new empty Grease Pencil object at `location` (world): one layer, the palette's colours as materials (and
    black). Selected and active. One undo step."""
    from . import annotate_math
    data = bpy.data.grease_pencils.new(math_.OBJECT_NAME)
    ob = bpy.data.objects.new(math_.OBJECT_NAME, data)
    data.layers.new(math_.LAYER_NAME)
    data.materials.append(_palette_material("VR Black", (0.0, 0.0, 0.0)))
    for identifier, label, code in annotate_math.PALETTE:
        data.materials.append(_palette_material("VR " + label, math_.linear_rgb(code)))
    context.view_layer.active_layer_collection.collection.objects.link(ob)
    ob.location = location
    for other in context.view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    push_undo("VR New Grease Pencil")
    return ob


def teardown(commit=True):
    """Session over: finish a running stroke (kept as an undo step when `commit`)."""
    if STATE.drawing and commit:
        end(bpy.context)
    _forget()
