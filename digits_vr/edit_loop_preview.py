# SPDX-License-Identifier: GPL-3.0-or-later
"""The loop cut's preview: while Loop cut is the active tool, the loop the laser's edge would give, as lines, and the
number of cuts on a tag. update() runs in the session tick and rebuilds only when the hovered edge, the mesh or the
number of cuts changed (bmesh reads + numpy); draw() runs per eye inside overlay.draw."""
import bmesh
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import edit_math, edit_tool_math, edit_tool_settings as options, edit_tools, settings, shape_math
from .edit_ring import Ring
from .edit_state import STATE
from .runtime import RUNTIME

COLOUR = (1.0, 0.85, 0.2, 1.0)        # Blender's own preview is yellow
WIDTH = 3.0
_built = {"key": None, "lines": None, "batch": None, "tag": None, "shader": None}


def cutting():
    """Loop cut is the active tool and the mesh can be edited."""
    return STATE.ready and settings.get("edit_tool") == options.LOOP_CUT


def _aimed():
    """The edges the lasers point at."""
    return tuple(sorted({hand_state.edit_hover[1] for hand_state in RUNTIME.hands.values()
                         if hand_state.edit_hover and hand_state.edit_hover[0] == edit_math.EDGE}))


def lines(bm, edge, cuts):
    """((n, 3) local line pairs, the middle of the aimed edge) of the cut through `edge`, or None."""
    if edge >= len(bm.edges):
        return None
    bm.edges.ensure_lookup_table()
    ring = Ring(bm.edges[edge])
    if ring.refusal(cuts, edit_tools.MAX_VERTS):
        return None
    heads, tails = ring.points()
    return edit_tool_math.preview_lines(heads, tails, np.array(ring.pairs), cuts), (heads[0] + tails[0]) / 2


def _clear():
    if _built["key"] is not None:
        _built.update(key=None, lines=None, batch=None, tag=None)


def refresh(context):
    """Work out the lines when the preview changed. True when the GPU batch must be made again."""
    edges = _aimed() if cutting() and not STATE.grabbing else ()
    if not edges:
        _clear()
        return False
    cuts = int(settings.get("edit_loop_cuts"))
    key = (edges, cuts, STATE.version, STATE.geometry_version)
    if key == _built["key"]:
        return False
    found = []
    ob = context.edit_object
    if ob is not None and ob.name_full == STATE.object_name:
        bm = bmesh.from_edit_mesh(ob.data)
        found = [item for item in (lines(bm, edge, cuts) for edge in edges) if item is not None]
    text = "1 cut" if cuts == 1 else f"{cuts} cuts"
    world = tuple(edit_math.to_world(found[0][1][None, :], STATE.matrix)[0].tolist()) if found else None
    _built.update(key=key, batch=None, lines=np.concatenate([item[0] for item in found]) if found else None,
                  tag=(text, world) if found else None)
    return bool(found)


def update():
    """Tick time, never in the draw callback."""
    if refresh(bpy.context):
        if _built["shader"] is None:
            _built["shader"] = gpu.shader.from_builtin('UNIFORM_COLOR')
        _built["batch"] = batch_for_shader(_built["shader"], 'LINES', {"pos": _built["lines"].astype(np.float32)})


def tags(state):
    """The name-tag entry of this frame: the number of cuts, at the aimed edge."""
    if _built["tag"] is None:
        return []
    text, world = _built["tag"]
    base, right, up, height = shape_math.tag_frame(world, state.viewer_pose_location)
    return [(text, base, right, up, height)]


def draw():
    batch = _built["batch"]
    if batch is None or not STATE.ready:
        return
    shader = _built["shader"]
    shader.bind()
    shader.uniform_float("color", COLOUR)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(WIDTH)
    gpu.matrix.push()
    try:
        gpu.matrix.multiply_matrix(Matrix(STATE.matrix.tolist()))
        batch.draw(shader)
    finally:
        gpu.matrix.pop()
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
