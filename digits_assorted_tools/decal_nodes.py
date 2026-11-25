# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the Geometry Nodes groups of a decal's modifier stack, built in code and reused by name (one place for
all three):

- "Digit Decal Lift": moves along the normal by (Lift + Layer Lift) in WORLD units (divided by the object's own
  scale along the normal), so scaling the decal with S never changes the real lift.
- "Digit Decal Bend": lays the flat grid onto the target like a sticker, keeping distances along the surface: every
  point walks from the aim point (the object origin, on the surface) towards where it sits on the flat grid, in
  `Steps` short steps; after each step it is snapped to the surface (a step that overshoots a convex edge into the
  air is pushed down by the overshoot first, so it lands on the far face; a short ray along the walk catches a wall
  ahead in a concave corner, so it climbs it) and its walking direction is turned with the
  surface (the minimal rotation from the old surface normal to the new one), so it carries on over an edge and down
  the other side instead of piling up there (a discrete exponential map, as in "Interactive decal compositing with
  discrete exponential maps", Schmidt et al. 2006). Works on the posed target, live.
- "Digit Decal Fade": where the decal's surface turns more than `Edge Angle` away from its aim (local +Z), it fades
  out (over the last FADE_RAMP); stored as the point attribute FADE_ATTRIBUTE (0 = shown, 1 = gone; a missing
  attribute reads 0, so decals without it show fully), read by the decal material's Attribute node.
All work in the decal object's local space (targets via Object Info, Relative)."""

from math import radians

import bpy

from .modifier_setup import set_modifier_input  # generated copy

VERSION_KEY = "digit_decal_version"
# Lowest version of each group the code accepts: raise a group's number when its inputs or inside change; an
# older file's group is then rebuilt in place and every decal using it gets its inputs again (decal_mesh).
GROUP_VERSIONS = {"Digit Decal Lift": 2, "Digit Decal Fade": 2, "Digit Decal Bend": 4, "Digit Decal Project": 4,
                  "Digit Decal Snap": 4}
rebuilt_groups = set()                    # names rebuilt in place since decal_mesh last refreshed their users
LIFT_GROUP = "Digit Decal Lift"
PROJECT_GROUP = "Digit Decal Project"
SNAP_GROUP = "Digit Decal Snap"
REACH_INPUT = "Reach"
LIFT_INPUT = "Lift"
LAYER_INPUT = "Layer Lift"
BEND_GROUP = "Digit Decal Bend"
FADE_GROUP = "Digit Decal Fade"
FADE_ATTRIBUTE = "decal_fade_out"
EDGE_ANGLE_INPUT = "Edge Angle"
FADE_RAMP = radians(15)
BEND_STEPS = 16
WALK_DIRECTION = "decal_walk_direction"   # temporary attributes of the Bend walk (removed at its end)
WALK_NORMAL = "decal_walk_normal"
WALK_STEP = "decal_walk_step"


def _group(name):
    """The Geometry Nodes group called `name` when it is up to date (GROUP_VERSIONS), else that group emptied (an
    older file's; noted in `rebuilt_groups`) or a new one, as a modifier group with Geometry in / out (second value
    True: needs building)."""
    group = bpy.data.node_groups.get(name)
    if group is not None and group.bl_idname == 'GeometryNodeTree':
        if group.get(VERSION_KEY, 0) >= GROUP_VERSIONS[name]:
            return group, False
        group.nodes.clear()
        group.interface.clear()
        rebuilt_groups.add(name)
    else:
        group = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    group[VERSION_KEY] = GROUP_VERSIONS[name]
    group.is_modifier = True
    group.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    return group, True


def _surface_inputs(group):
    _input(group, "Target", 'NodeSocketObject')


def _input(group, name, socket_type, subtype=None, default=None, minimum=None, maximum=None):
    socket = group.interface.new_socket(name, in_out='INPUT', socket_type=socket_type)
    if subtype:
        socket.subtype = subtype
    if default is not None:
        socket.default_value = default
    if minimum is not None:
        socket.min_value = minimum
    if maximum is not None:
        socket.max_value = maximum
    return socket


class Builder:
    """Small helper to wire a node group: `node(kind, **settings)`, `math(op, a, b)`, `vector(op, a, b)`; inputs
    may be sockets or plain values."""

    def __init__(self, group):
        self.nodes, self.links = group.nodes, group.links
        self.group_in = self.nodes.new('NodeGroupInput')
        self.group_out = self.nodes.new('NodeGroupOutput')

    def node(self, kind, **settings):
        node = self.nodes.new(kind)
        for name, value in settings.items():
            setattr(node, name, value)
        return node

    def feed(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        elif value is not None:
            socket.default_value = value

    def math(self, operation, first, second=None):
        node = self.node('ShaderNodeMath', operation=operation)
        self.feed(node.inputs[0], first)
        self.feed(node.inputs[1], second)
        return node.outputs[0]

    def vector(self, operation, first, second=None, output="Vector"):
        node = self.node('ShaderNodeVectorMath', operation=operation)
        self.feed(node.inputs[0], first)
        if operation == 'SCALE':
            self.feed(node.inputs["Scale"], second)
        else:
            self.feed(node.inputs[1], second)
        return node.outputs[output]

    def switch(self, input_type, condition, when_false, when_true):
        node = self.node('GeometryNodeSwitch', input_type=input_type)
        self.feed(node.inputs["Switch"], condition)
        self.feed(node.inputs["False"], when_false)
        self.feed(node.inputs["True"], when_true)
        return node.outputs["Output"]

    def named(self, name, data_type='FLOAT_VECTOR'):
        node = self.node('GeometryNodeInputNamedAttribute', data_type=data_type)
        node.inputs["Name"].default_value = name
        return node.outputs["Attribute"]

    def store(self, geometry, name, value, data_type='FLOAT_VECTOR'):
        node = self.node('GeometryNodeStoreNamedAttribute', data_type=data_type, domain='POINT')
        self.feed(node.inputs["Geometry"], geometry)
        node.inputs["Name"].default_value = name
        self.feed(node.inputs["Value"], value)
        return node.outputs["Geometry"]

    def set_position(self, geometry, position):
        node = self.node('GeometryNodeSetPosition')
        self.feed(node.inputs["Geometry"], geometry)
        self.feed(node.inputs["Position"], position)
        return node.outputs["Geometry"]

    def surface(self):
        """The surface a decal lands on: the Target object's evaluated (posed) mesh, in the decal's own space."""
        info = self.node('GeometryNodeObjectInfo', transform_space='RELATIVE')
        self.feed(info.inputs["Object"], self.group_in.outputs["Target"])
        return info.outputs["Geometry"]

    def constant(self, vector):
        """A vector as a node output (a plain default on a Position-like input would mean "each point's own")."""
        return self.node('FunctionNodeInputVector', vector=vector).outputs[0]

    def position(self):
        return self.node('GeometryNodeInputPosition').outputs["Position"]

    def nearest(self, surface, position):
        """(position, normal) on `surface` nearest to `position` (smooth normals)."""
        proximity = self.node('GeometryNodeProximity', target_element='FACES')
        self.feed(proximity.inputs["Geometry"], surface)
        self.feed(proximity.inputs["Sample Position"], position)
        sample = self.node('GeometryNodeSampleNearestSurface', data_type='FLOAT_VECTOR')
        self.feed(sample.inputs["Mesh"], surface)
        self.feed(sample.inputs["Value"], self.node('GeometryNodeInputNormal').outputs["Normal"])
        self.feed(sample.inputs["Sample Position"], proximity.outputs["Position"])
        return proximity.outputs["Position"], sample.outputs["Value"]


# --- Lift --------------------------------------------------------------------------------------------------------

def ensure_lift_group():
    group, new = _group(LIFT_GROUP)
    if not new:
        return group
    for name in (LIFT_INPUT, LAYER_INPUT):
        _input(group, name, 'NodeSocketFloat', 'DISTANCE', minimum=0.0)
    build = Builder(group)
    normal = build.node('GeometryNodeInputNormal').outputs["Normal"]
    info = build.node('GeometryNodeObjectInfo', transform_space='ORIGINAL')
    build.feed(info.inputs["Object"], build.node('GeometryNodeSelfObject').outputs[0])
    stretch = build.vector('LENGTH', build.vector('MULTIPLY', info.outputs["Scale"], normal), output="Value")
    total = build.math('ADD', build.group_in.outputs[LIFT_INPUT], build.group_in.outputs[LAYER_INPUT])
    offset = build.vector('SCALE', normal, build.math('DIVIDE', total, stretch))
    move = build.node('GeometryNodeSetPosition')
    build.feed(move.inputs["Geometry"], build.group_in.outputs["Geometry"])
    build.feed(move.inputs["Offset"], offset)
    build.feed(build.group_out.inputs["Geometry"], move.outputs["Geometry"])
    return group


# --- Bend --------------------------------------------------------------------------------------------------------

def ensure_bend_group():
    group, new = _group(BEND_GROUP)
    if not new:
        return group
    _surface_inputs(group)
    _input(group, "Steps", 'NodeSocketInt', default=BEND_STEPS, minimum=1, maximum=64)
    build = Builder(group)
    surface = build.surface()
    steps = build.group_in.outputs["Steps"]
    # start: every point at the aim point (origin) snapped to the surface, heading towards its flat-grid spot
    flat = build.node('GeometryNodeInputPosition').outputs["Position"]
    across = build.vector('MULTIPLY', flat, (1.0, 1.0, 0.0))
    start, start_normal = build.nearest(surface, build.constant((0.0, 0.0, 0.0)))
    geometry = build.store(build.group_in.outputs["Geometry"], WALK_DIRECTION, build.vector('NORMALIZE', across))
    geometry = build.store(geometry, WALK_STEP, build.math('DIVIDE', build.vector('LENGTH', across, output="Value"),
                                                               steps), 'FLOAT')
    geometry = build.store(geometry, WALK_NORMAL, start_normal)
    geometry = build.set_position(geometry, start)
    # the walk
    repeat_in = build.node('GeometryNodeRepeatInput')
    repeat_out = build.node('GeometryNodeRepeatOutput')
    repeat_in.pair_with_output(repeat_out)
    build.feed(repeat_in.inputs["Iterations"], steps)
    build.feed(repeat_in.inputs["Geometry"], geometry)
    here = build.node('GeometryNodeInputPosition').outputs["Position"]
    direction = build.named(WALK_DIRECTION)
    old_normal = build.named(WALK_NORMAL)
    ahead = build.vector('ADD', here, build.vector('SCALE', direction, build.named(WALK_STEP, 'FLOAT')))
    # past a convex edge the step ends in the air: push it down by what it overshot, so it lands on the far face
    # with its length kept (and the far face's normal), instead of sticking to the edge
    first, _normal = build.nearest(surface, ahead)
    overshoot = build.vector('DISTANCE', ahead, first, output="Value")
    probe = build.vector('SUBTRACT', ahead, build.vector('SCALE', old_normal, overshoot))
    over, over_normal = build.nearest(surface, probe)
    # into a concave corner (a wall ahead): a short ray along the walk, from just above the surface, hits it first
    step = build.named(WALK_STEP, 'FLOAT')
    ray = build.node('GeometryNodeRaycast')
    build.feed(ray.inputs["Target Geometry"], surface)
    build.feed(ray.inputs["Source Position"], build.vector('ADD', here, build.vector('SCALE', old_normal,
                                                                                       build.math('MULTIPLY', step, 0.05))))
    build.feed(ray.inputs["Ray Direction"], direction)
    build.feed(ray.inputs["Ray Length"], step)
    landed, new_normal = (build.switch('VECTOR', ray.outputs["Is Hit"], over, ray.outputs["Hit Position"]),
                          build.switch('VECTOR', ray.outputs["Is Hit"], over_normal, ray.outputs["Hit Normal"]))
    # minimal rotation old normal > new normal, for a direction lying in the old plane:
    # d' = d - (a + b) (d . b) / (1 + a . b)
    along_new = build.vector('DOT_PRODUCT', direction, new_normal, output="Value")
    agree = build.math('MAXIMUM', build.math('ADD', build.vector('DOT_PRODUCT', old_normal, new_normal, output="Value"),
                                             1.0), 0.001)
    turned = build.vector('SUBTRACT', direction, build.vector('SCALE', build.vector('ADD', old_normal, new_normal),
                                                              build.math('DIVIDE', along_new, agree)))
    flat_again = build.vector('SUBTRACT', turned, build.vector(
        'SCALE', new_normal, build.vector('DOT_PRODUCT', turned, new_normal, output="Value")))
    # capture all three on the geometry as it is, then move: fields read after a move would see the new place
    capture = build.node('GeometryNodeCaptureAttribute', domain='POINT')
    for name in ("Landed", "Direction", "Normal"):
        capture.capture_items.new('VECTOR', name)
    build.feed(capture.inputs["Geometry"], repeat_in.outputs["Geometry"])
    build.feed(capture.inputs["Landed"], landed)
    build.feed(capture.inputs["Direction"], build.vector('NORMALIZE', flat_again))
    build.feed(capture.inputs["Normal"], new_normal)
    walked = build.set_position(capture.outputs["Geometry"], capture.outputs["Landed"])
    walked = build.store(walked, WALK_DIRECTION, capture.outputs["Direction"])
    walked = build.store(walked, WALK_NORMAL, capture.outputs["Normal"])
    build.feed(repeat_out.inputs["Geometry"], walked)
    clean = build.node('GeometryNodeRemoveAttribute')
    build.feed(clean.inputs["Geometry"], repeat_out.outputs["Geometry"])
    clean.inputs["Pattern Mode"].default_value = 'Wildcard'
    clean.inputs["Name"].default_value = "decal_walk_*"
    build.feed(build.group_out.inputs["Geometry"], clean.outputs["Geometry"])
    return group


# --- Fade --------------------------------------------------------------------------------------------------------

def ensure_fade_group():
    group, new = _group(FADE_GROUP)
    if not new:
        return group
    _input(group, EDGE_ANGLE_INPUT, 'NodeSocketFloat', 'ANGLE', radians(60), 0.0, radians(180))
    build = Builder(group)
    normal = build.node('GeometryNodeInputNormal').outputs["Normal"]
    facing = build.vector('DOT_PRODUCT', normal, (0.0, 0.0, 1.0), output="Value")
    turned = build.math('ARCCOSINE', build.math('MINIMUM', build.math('MAXIMUM', facing, -1.0), 1.0))
    edge = build.group_in.outputs[EDGE_ANGLE_INPUT]
    ramp = build.node('ShaderNodeMapRange', clamp=True)
    build.feed(ramp.inputs["Value"], turned)
    build.feed(ramp.inputs["From Min"], build.math('SUBTRACT', edge, FADE_RAMP))
    build.feed(ramp.inputs["From Max"], edge)
    geometry = build.store(build.group_in.outputs["Geometry"], FADE_ATTRIBUTE, ramp.outputs["Result"], 'FLOAT')
    build.feed(build.group_out.inputs["Geometry"], geometry)
    return group


# --- Project (Squash), Snap ----------------------------------------------------------------------------------

def ensure_project_group():
    """One way down (local -Z) at most `Reach`, the first surface hit wins; a point that hits nothing goes to the
    nearest surface (not mid-air)."""
    group, new = _group(PROJECT_GROUP)
    if not new:
        return group
    _surface_inputs(group)
    _input(group, REACH_INPUT, 'NodeSocketFloat', 'DISTANCE', 0.05, 0.0)
    build = Builder(group)
    surface, here = build.surface(), build.position()
    ray = build.node('GeometryNodeRaycast')
    build.feed(ray.inputs["Target Geometry"], surface)
    build.feed(ray.inputs["Source Position"], here)
    build.feed(ray.inputs["Ray Direction"], build.constant((0.0, 0.0, -1.0)))
    build.feed(ray.inputs["Ray Length"], build.group_in.outputs[REACH_INPUT])
    near, _normal = build.nearest(surface, here)
    choose = build.node('GeometryNodeSwitch', input_type='VECTOR')
    build.feed(choose.inputs["Switch"], ray.outputs["Is Hit"])
    build.feed(choose.inputs["False"], near)
    build.feed(choose.inputs["True"], ray.outputs["Hit Position"])
    build.feed(build.group_out.inputs["Geometry"], build.set_position(build.group_in.outputs["Geometry"],
                                                                      choose.outputs["Output"]))
    return group


def ensure_snap_group():
    """Every point to the nearest surface (Stuck: puts Detail's new points on it, at the render level too)."""
    group, new = _group(SNAP_GROUP)
    if not new:
        return group
    _surface_inputs(group)
    build = Builder(group)
    near, _normal = build.nearest(build.surface(), build.position())
    build.feed(build.group_out.inputs["Geometry"], build.set_position(build.group_in.outputs["Geometry"], near))
    return group


def surface_inputs(recipe):
    """The surface inputs of a decal's groups, from its recipe."""
    return {"Target": recipe.target}


def add_modifier(ob, name, group, **inputs):
    """A Geometry Nodes modifier `name` with `group` and its inputs set by socket name."""
    modifier = ob.modifiers.new(name, 'NODES')
    modifier.node_group = group
    for socket, value in inputs.items():
        set_modifier_input(modifier, socket.replace("_", " "), value)
    return modifier
