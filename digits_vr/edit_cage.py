# SPDX-License-Identifier: GPL-3.0-or-later
"""The Edit mode cage in the headset (Blender draws NO vertices / edges in VR): edges as lines, vertices as points,
selected vertices bigger and orange, in the edited object's space (model matrix at draw). Batches are built in the
session tick (update(), called by overlay.sync) from edit_state's numpy arrays, and only when its version changed;
draw() runs once per eye inside overlay.draw. Cage A of the audit: the whole position buffer is rebuilt on a change
(6k vertices: cheap); a drag only changes the positions."""
import gpu
import numpy as np
from gpu.types import GPUBatch, GPUIndexBuf, GPUVertBuf, GPUVertFormat
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import edit_fill
from .edit_state import STATE
from .runtime import RUNTIME

EDGE_COLOUR = (0.05, 0.05, 0.08, 0.9)
POINT_COLOUR = (0.1, 0.1, 0.15, 1.0)
SELECTED_COLOUR = (1.0, 0.55, 0.1, 1.0)
HOVER_COLOUR = (0.45, 0.8, 1.0, 0.9)
EDGE_WIDTH, POINT_SIZE, SELECTED_SIZE, HOVER_SIZE = 2.0, 6.0, 11.0, 13.0
_built = {"version": -1, "coords_version": -1, "vbo": None, "indices": {}, "edges": None, "selected_edges": None, "points": None, "selected": None, "hover_key": None,
          "hover": [], "time": 0.0}
_shader = [None, None]      # [the UNIFORM_COLOR shader, the vertex format]


def visible():
    return STATE.ready


def _hovers():
    """What the hands point at: [(element, index)] (hover.py)."""
    found = {hover for hand_state in RUNTIME.hands.values() for hover in (hand_state.edit_hover,) if hover}
    return tuple(sorted(found))


def _index_buffer(kind, indices):
    """(kind, index buffer) over the shared vertices, or None (a numpy int32 array: (n,) for POINTS, (n, 2) LINES)."""
    return (kind, GPUIndexBuf(type=kind, seq=np.ascontiguousarray(indices, np.int32))) if len(indices) else None


def _fill(coords):
    """A new position buffer and the batches over it. A buffer that was drawn can't be filled again ("static buffer already
    in use"), so a drag makes a new one; the index buffers are kept."""
    vbo = GPUVertBuf(_format(), len(coords))
    vbo.attr_fill("pos", coords)
    _built.update(vbo=vbo, coords_version=STATE.coords_version,
                  **{name: GPUBatch(type=entry[0], buf=vbo, elem=entry[1]) if entry else None
                     for name, entry in _built["indices"].items()})


def update():
    """Tick time, never in the draw callback. ONE vertex buffer holds every vertex position and all the batches draw
    from it through index buffers: a selection / topology change (STATE.version) rebuilds the index buffers; a drag only
    changes the positions (STATE.coords_version), which is one new vertex buffer."""
    if not STATE.ready:
        if _built["vbo"] is not None:
            _built.update(version=-1, vbo=None, edges=None, selected_edges=None, points=None, selected=None, hover_key=None, hover=[])
            edit_fill.clear()
        return
    if _shader[0] is None:
        _shader[0] = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader, coords = _shader[0], STATE.coords
    if _built["version"] != STATE.version or _built["vbo"] is None:
        picked = STATE.edge_selected
        _built.update(version=STATE.version, indices={
            "edges": _index_buffer('LINES', STATE.edges[~picked]), "selected_edges": _index_buffer('LINES', STATE.edges[picked]),
            "points": _index_buffer('POINTS', STATE.pickable),
            "selected": _index_buffer('POINTS', np.flatnonzero(STATE.selected))})
        _fill(coords)
    elif _built["coords_version"] != STATE.coords_version:
        _fill(coords)               # a drag: the positions only
    hovers = _hovers()
    if (hovers, STATE.version) != _built["hover_key"]:
        _built["hover_key"] = (hovers, STATE.version)
        _built["hover"] = [batch for batch in (_hover_batch(shader, element, index) for element, index in hovers) if batch]
    edit_fill.update(hovers)


def _format():
    if _shader[1] is None:
        _shader[1] = GPUVertFormat()
        _shader[1].attr_add(id="pos", comp_type='F32', len=3, fetch_mode='FLOAT')
    return _shader[1]


def _hover_batch(shader, element, index):
    """(batch, kind) of the hovered vertex (a big point) or edge (a line); a face is edit_fill's."""
    coords = STATE.coords
    try:
        if element == 'VERT':
            return batch_for_shader(shader, 'POINTS', {"pos": coords[[index]]}), 'POINTS'
        if element != 'EDGE':
            return None
        return batch_for_shader(shader, 'LINES', {"pos": coords[STATE.all_edges[index]]}), 'LINES'
    except (IndexError, ValueError):
        return None


def draw():
    """This eye's cage. Depth tested; the lines and points sit on the surface, so the cage is pulled a hair toward the
    eye by drawing with LESS_EQUAL (the audit's note: no vertex-shader bias in the builtin shaders). The face fills
    (edit_fill) come first: they have their own pull toward the eye."""
    if _built["vbo"] is None or not STATE.ready:
        return
    shader = _shader[0]
    shader.bind()
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('ALPHA')
    gpu.matrix.push()
    try:
        gpu.matrix.multiply_matrix(Matrix(STATE.matrix.tolist()))
        edit_fill.draw()
        gpu.state.line_width_set(EDGE_WIDTH)
        shader.uniform_float("color", EDGE_COLOUR)
        if _built["edges"] is not None:
            _built["edges"].draw(shader)
        if _built["selected_edges"] is not None:
            gpu.state.line_width_set(EDGE_WIDTH + 1.0)
            shader.uniform_float("color", SELECTED_COLOUR)
            _built["selected_edges"].draw(shader)
        gpu.state.point_size_set(POINT_SIZE)
        shader.uniform_float("color", POINT_COLOUR)
        if _built["points"] is not None:
            _built["points"].draw(shader)
        if _built["selected"] is not None:
            gpu.state.point_size_set(SELECTED_SIZE)
            shader.uniform_float("color", SELECTED_COLOUR)
            _built["selected"].draw(shader)
        if _built["hover"]:
            gpu.state.depth_test_set('NONE')
            gpu.state.point_size_set(HOVER_SIZE)
            gpu.state.line_width_set(EDGE_WIDTH + 2.0)
            shader.uniform_float("color", HOVER_COLOUR)
            for batch, _kind in _built["hover"]:
                batch.draw(shader)
        edit_fill.draw_outline()
    finally:
        gpu.matrix.pop()
        gpu.state.depth_test_set('NONE')
        gpu.state.blend_set('NONE')
