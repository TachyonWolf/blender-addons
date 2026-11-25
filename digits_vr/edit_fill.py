# SPDX-License-Identifier: GPL-3.0-or-later
"""The translucent face fills of the Edit mode cage: the selected faces (orange) and the hovered face (blue, with its outline),
built from the REAL triangulation (edit_state.face_triangles: a concave ngon is several triangles, not a fan). The vertex
shader moves every corner a little toward the eye (a share of its distance, so it holds at any range): the fill never
z-fights with the surface or the cage lines, and is still depth tested (a face behind a hill stays hidden). With a
modifier on, the shown surface is not the cage: the pull is bigger so the fill still shows. Batches are
built in update() (the session tick) and only when the selection, topology, positions or hover changed; draw() binds them."""
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import edit_math, edit_state

SELECTED_COLOUR = (1.0, 0.55, 0.1, 0.38)
HOVER_COLOUR = (0.3, 0.75, 1.0, 0.55)
HOVER_OUTLINE_COLOUR = (0.75, 0.95, 1.0, 1.0)
OUTLINE_WIDTH = 4.0
PULL = 0.008                # of the distance to the eye
PULL_MODIFIED = 0.04        # a modifier changes the shown surface: pull harder
_VERTEX = """
void main() {
    vec3 toEye = eyeLocal - pos;
    gl_Position = modelViewProjection * vec4(pos + toEye * pull, 1.0);
}
"""
_FRAGMENT = """
void main() { fragColor = color; }
"""
_built = {"selected_key": None, "selected": None, "hover_key": None, "hover": None, "outline": None, "pull": PULL}
_shader = [None]


def _make_shader():
    """The eye-pulled shader, or the plain one when this GPU backend refuses it (the fill then relies on depth alone)."""
    try:
        info = gpu.types.GPUShaderCreateInfo()
        info.vertex_in(0, 'VEC3', "pos")
        info.fragment_out(0, 'VEC4', "fragColor")
        info.push_constant('MAT4', "modelViewProjection")
        info.push_constant('VEC3', "eyeLocal")
        info.push_constant('FLOAT', "pull")
        info.push_constant('VEC4', "color")
        info.vertex_source(_VERTEX)
        info.fragment_source(_FRAGMENT)
        return gpu.shader.create_from_info(info), True
    except (RuntimeError, AttributeError, TypeError, ValueError):
        return gpu.shader.from_builtin('UNIFORM_COLOR'), False


def _shader_pair():
    if _shader[0] is None:
        _shader[0] = _make_shader()
    return _shader[0]


def clear():
    _built.update(selected_key=None, selected=None, hover_key=None, hover=None, outline=None)


def _pull():
    ob = bpy.context.edit_object
    modified = ob is not None and any(modifier.show_viewport and modifier.show_in_editmode for modifier in ob.modifiers)
    return PULL_MODIFIED if modified else PULL


def update(hovers):
    """Tick time. `hovers` = ((element, index), ...) from edit_cage; only a hovered FACE gets a fill."""
    state = edit_state.STATE
    context = bpy.context
    shader = _shader_pair()[0]
    selected_key = (state.version, state.coords_version)
    if selected_key != _built["selected_key"]:
        _built["pull"] = _pull()
        faces = np.flatnonzero(state.face_selected) if len(state.face_selected) <= edit_math.HOVER_MAX_FACES else ()   # big mesh: no fill
        _built.update(selected_key=selected_key, selected=_triangle_batch(shader, context, faces))
    faces = tuple(index for element, index in hovers if element == 'FACE')
    hover_key = (faces, state.version, state.coords_version)
    if hover_key != _built["hover_key"]:
        _built.update(hover_key=hover_key, hover=_triangle_batch(shader, context, faces),
                      outline=_outline_batch(context, faces))


def _triangle_batch(shader, context, faces):
    if not len(faces):
        return None
    points = edit_state.face_triangles(context, faces)
    return batch_for_shader(shader, 'TRIS', {"pos": points}) if len(points) else None


def _outline_batch(context, faces):
    if not len(faces):
        return None
    points = np.concatenate([edit_state.face_outline(context, face) for face in faces])
    return batch_for_shader(gpu.shader.from_builtin('UNIFORM_COLOR'), 'LINES', {"pos": points})


def draw():
    """This eye, inside edit_cage.draw (the object's matrix is already on the model stack)."""
    if _built["selected"] is None and _built["hover"] is None:
        return
    shader, pulled = _shader_pair()
    shader.bind()
    model_view = Matrix(gpu.matrix.get_model_view_matrix())
    if pulled:
        shader.uniform_float("modelViewProjection", Matrix(gpu.matrix.get_projection_matrix()) @ model_view)
        shader.uniform_float("eyeLocal", model_view.inverted_safe().translation)
        shader.uniform_float("pull", _built["pull"])
    gpu.state.depth_mask_set(False)
    try:
        for batch, colour in ((_built["selected"], SELECTED_COLOUR), (_built["hover"], HOVER_COLOUR)):
            if batch is not None:
                shader.uniform_float("color", colour)
                batch.draw(shader)
    finally:
        gpu.state.depth_mask_set(True)


def draw_outline():
    """The hovered face's outline (called with the hover marks, depth off like them)."""
    if _built["outline"] is not None:
        line_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        line_shader.bind()
        line_shader.uniform_float("color", HOVER_OUTLINE_COLOUR)
        gpu.state.line_width_set(OUTLINE_WIDTH)
        _built["outline"].draw(line_shader)
