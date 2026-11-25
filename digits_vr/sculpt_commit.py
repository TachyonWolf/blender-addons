# SPDX-License-Identifier: GPL-3.0-or-later
"""One native undo step for a live VR stroke, without replaying it (spike V5, docs/spikes/SPIKE-SCULPT.md): put the
start state back, then a temporary Geometry Nodes tool writes the live state from a temporary attribute. Blender
stores that as ONE Sculpt step with the exact before and after. Tool and attribute are removed in `finally`: nothing
VR-only stays in the file. The tool only moves vertices where the attribute exists.

When anything fails, the mesh goes back to the stroke's START state (history stays consistent) and CommitError is
raised. Callers run inside a 3D View override."""
import bpy
import numpy as np

ATTRIBUTE, GROUP = "digitsvr_live_stroke", "Digit's VR sculpt stroke"
OPERATOR = "digits_vr_tool.sculpt_stroke"          # registered by Blender only while a commit runs
MASK = ".sculpt_mask"


class CommitError(Exception):
    """The stroke could not be kept; the mesh is back at the stroke's start."""


class Layer:
    """The array a stroke changes: positions, or the sculpt mask."""

    def __init__(self, is_mask=False):
        self.is_mask, self.width = is_mask, 1 if is_mask else 3
        self.name, self.field = (MASK, "value") if is_mask else ("position", "vector")
        self.kind = 'FLOAT' if is_mask else 'FLOAT_VECTOR'

    def read(self, mesh):
        values = np.zeros(len(mesh.vertices) * self.width, np.float32)
        attribute = mesh.attributes.get(self.name)
        if attribute is not None and len(attribute.data):      # no mask layer yet = nothing is masked
            attribute.data.foreach_get(self.field, values)
        return values

    def write(self, mesh, values):
        attribute = mesh.attributes.get(self.name)
        if attribute is None or len(values) != len(mesh.vertices) * self.width:
            raise CommitError("the mesh changed during the stroke")
        attribute.data.foreach_set(self.field, values)


def same(first, second):
    """Bit-equal float arrays (comparing as integers: NaN-safe; a memoryview compare is 10x slower)."""
    return len(first) == len(second) and np.array_equal(first.view(np.int32), second.view(np.int32))


def _make_tool(layer):
    group = bpy.data.node_groups.new(GROUP, 'GeometryNodeTree')
    group.node_tool_idname = OPERATOR
    group.is_tool = group.is_mode_sculpt = group.is_type_mesh = True
    for way in ('INPUT', 'OUTPUT'):
        group.interface.new_socket("Geometry", in_out=way, socket_type='NodeSocketGeometry')
    nodes, links = group.nodes, group.links
    source, sink = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
    named = nodes.new('GeometryNodeInputNamedAttribute')
    named.data_type = layer.kind
    named.inputs["Name"].default_value = ATTRIBUTE
    values = next(socket for socket in named.outputs if socket.enabled and socket.name == "Attribute")
    exists = next(socket for socket in named.outputs if socket.name == "Exists")
    if layer.is_mask:
        setter, flip = nodes.new('GeometryNodeToolSetSelection'), nodes.new('ShaderNodeMath')
        setter.selection_type = 'FLOAT'          # in Sculpt mode a selection is 1 - mask
        flip.operation = 'SUBTRACT'
        flip.inputs[0].default_value = 1.0
        links.new(values, flip.inputs[1])
        links.new(flip.outputs[0], next(s for s in setter.inputs if s.enabled and s.name == "Selection"))
    else:
        setter = nodes.new('GeometryNodeSetPosition')
        links.new(values, setter.inputs["Position"])
        links.new(exists, setter.inputs["Selection"])
    links.new(source.outputs[0], setter.inputs["Geometry"])
    links.new(setter.outputs[0], sink.inputs[0])
    bpy.context.window_manager.register_node_group_operators()
    return group


def remove_leftovers(mesh=None):
    """The temporary attribute and tool, if there (also the clean-up after a failed commit)."""
    attribute = mesh.attributes.get(ATTRIBUTE) if mesh is not None else None
    if attribute is not None:
        mesh.attributes.remove(attribute)
    group = bpy.data.node_groups.get(GROUP)
    if group is not None:
        bpy.data.node_groups.remove(group)
        bpy.context.window_manager.register_node_group_operators()


def _run_tool():
    space, name = OPERATOR.split(".")
    return getattr(getattr(bpy.ops, space), name)('EXEC_DEFAULT', True)


def commit(ob, layer, start, live, build_bvh):
    """Make `live` one undo step from `start`. Raises CommitError with the mesh back at `start`.
    `build_bvh()` must make Blender build the sculpt BVH of the active object. From source, the tool reads the BVH without
    a check, so it runs right before the tool, after every change that could free it. (The tool always crashes Blender
    in `-b` with a 3D View override; cause not found, so only ox can test a real commit.)"""
    mesh = ob.data
    try:
        if len(live) != len(start) or len(start) != len(mesh.vertices) * layer.width:
            raise CommitError("the vertex count changed")
        try:
            attribute = mesh.attributes.new(ATTRIBUTE, layer.kind, 'POINT')
            if attribute is None or attribute.name != ATTRIBUTE:
                raise CommitError("no temporary attribute")
            attribute.data.foreach_set(layer.field, live)
            _make_tool(layer)
            layer.write(mesh, start)
            bpy.context.view_layer.update()      # pending updates now, not inside the tool: they could free the BVH
            build_bvh()
            if _run_tool() != {'FINISHED'}:
                raise CommitError("the tool did not run")
            result = layer.read(mesh)
            if same(result, start) and not same(live, start):
                raise CommitError("the tool changed nothing")
            if not np.allclose(result, live, rtol=0.0, atol=1e-6 if layer.is_mask else 0.0):
                print("digits_vr: the kept stroke differs from the live one; its undo step is still exact")
        finally:
            remove_leftovers(mesh)
    except Exception as error:
        restore(ob, layer, start)
        raise error if isinstance(error, CommitError) else CommitError(str(error)) from error


def restore(ob, layer, start):
    """The start state back, shown. False when the mesh no longer fits it (then nothing is written)."""
    try:
        layer.write(ob.data, start)
    except (CommitError, ReferenceError):
        return False
    ob.data.update()
    return True
