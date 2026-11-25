# SPDX-License-Identifier: GPL-3.0-or-later
"""Fog Marks: two optional empties you place with a crosshair click drive the Depth Fog node's distances.

- Clear View (empty "Fog Clear View") -> Start: the fog begins at this depth.
- Fogged Out (empty "Fog Out") -> End: the fog reaches its Density here. Not placed: twice the Clear View depth.

Depth is planar depth along the scene camera's view axis (what the Z pass measures), written as simple driver
expressions, so it works without Python auto-run. Start and End each compute their depths in ONE driver (no
driver-to-driver chain: Blender ran such chains in no fixed order, so fog lagged a frame behind animated marks);
a driver expression holds at most 256 characters, hence the compact form. Camera vars read `scene.camera.matrix_world` through the Scene,
so a camera switch is followed without a Retarget button (a timeline-marker switch lands one evaluation late).
Mark vars are world-space locations, so marks can be dragged, parented and keyframed.

Defaults for unplaced marks: Start 0 m; End twice Clear View, or (no marks at all, after removing the last one)
1000 m or the camera's Clip End if farther. With no marks the sliders are left alone.

The compositor tree is rebuilt by every preset Apply / Revert, which deletes the drivers: call
`rebuild_drivers(scene)` after each chain build. Nothing here runs in the background."""

import bpy
from bpy.props import EnumProperty, FloatVectorProperty
from mathutils import Vector

from . import compositor_chain, view_ray  # view_ray: generated copy

COLLECTION_NAME = "Fog Marks"
MARK_KEY = "fog_mark"            # custom property on the empty: which mark it is
EXPRESSION_LIMIT = 256           # Blender cuts driver expressions longer than this
GROUP_NAME = "Depth Fog"
CLEAR, OUT = "clear", "out"
MARKS = {CLEAR: ("Clear View", "Fog Clear View", "Start"),   # key -> (label, empty name, Depth Fog input)
         OUT: ("Fogged Out", "Fog Out", "End")}
MARK_ITEMS = [(key, label, "") for key, (label, _name, _socket) in MARKS.items()]
SOCKET_MAX = 10000.0             # the Depth Fog sockets' max
MIN_GAP = 0.01                   # End stays at least this far past Start
FAR_DEFAULT = 1000.0             # End with no marks: this, or the camera's Clip End if farther
EMPTY_SIZE = 0.5
CAMERA_VARS = (("fwd_x", 2, 0), ("fwd_y", 2, 1), ("fwd_z", 2, 2),   # matrix_world[column][row]: the -view axis
               ("cam_x", 3, 0), ("cam_y", 3, 1), ("cam_z", 3, 2))   # and the translation

STATE_NONE, STATE_NO_FOG, STATE_DRIVEN = "none", "no_fog_node", "driven"


# ---------------------------------------------------------------------------
# Plain maths (the driver expressions and their Python twin for readouts)
# ---------------------------------------------------------------------------

VIEW_AXIS_LENGTH = "sqrt(fwd_x*fwd_x+fwd_y*fwd_y+fwd_z*fwd_z)"   # the camera's scale along its view axis


def depth_numerator(key):
    """Planar depth of mark `key` (vars <key>_x/_y/_z) times VIEW_AXIS_LENGTH: (camera - mark) . view-axis column.
    Divide by VIEW_AXIS_LENGTH for metres (scale-proof)."""
    return "+".join(f"(cam_{axis}-{key}_{axis})*fwd_{axis}" for axis in "xyz")


def checked(expression):
    if len(expression) >= EXPRESSION_LIMIT:
        raise ValueError(f"driver expression too long ({len(expression)} chars)")
    return expression


def start_expression():
    """Start = the Clear View depth, clamped to 0 .. SOCKET_MAX - MIN_GAP."""
    return checked(f"clamp(({depth_numerator(CLEAR)})/{VIEW_AXIS_LENGTH},0,{SOCKET_MAX - MIN_GAP})")


def end_expression(clear_placed, out_placed):
    """End = the Fogged Out depth (else twice Start), at least Start + MIN_GAP, at most SOCKET_MAX. Worked on the
    unscaled numerators (MIN_GAP times the axis length), so the length is divided once."""
    length = VIEW_AXIS_LENGTH
    clear, out = depth_numerator(CLEAR), depth_numerator(OUT)
    if clear_placed and out_placed:
        far = f"max({out},max({clear},0)+{MIN_GAP}*{length})"
    elif clear_placed:   # Start + max(Start, MIN_GAP), Start >= 0
        far = f"(max({clear},0)+max({clear},{MIN_GAP}*{length}))"
    else:
        far = f"max({out},{MIN_GAP}*{length})"
    return checked(f"min({far}/{length},{SOCKET_MAX})")


def planar_depth(point, camera_matrix):
    """Depth of a world point along the camera's view axis (camera scale ignored)."""
    forward = (camera_matrix.to_3x3() @ Vector((0, 0, -1))).normalized()
    return (Vector(point) - camera_matrix.translation).dot(forward)


def default_end(scene):
    camera = scene.camera
    clip_end = camera.data.clip_end if camera is not None and camera.type == 'CAMERA' else 0.0
    return min(max(FAR_DEFAULT, clip_end), SOCKET_MAX)


# ---------------------------------------------------------------------------
# Scene data: the marks and the Depth Fog node
# ---------------------------------------------------------------------------

def marks_collection(scene, create=False):
    collection = next((c for c in scene.collection.children if c.get(MARK_KEY)), None)
    if collection is None and create:
        collection = bpy.data.collections.new(COLLECTION_NAME)
        collection[MARK_KEY] = True
        collection.hide_render = True
        scene.collection.children.link(collection)
    return collection


def mark_object(scene, key):
    """The empty for mark `key` in this scene, or None (found by tag, so renaming it is fine)."""
    collection = marks_collection(scene)
    if collection is None:
        return None
    return next((ob for ob in collection.objects if ob.get(MARK_KEY) == key), None)


def placed_keys(scene):
    return [key for key in MARKS if mark_object(scene, key) is not None]


def fog_node(scene):
    """The Depth Fog group node of the scene's compositor (found by label, else by group name), or None."""
    node = compositor_chain.chain_node(scene, GROUP_NAME)
    if node is not None:
        return node
    tree = compositor_chain.current_tree(scene)
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.type == 'GROUP' and node.node_tree is not None
                 and node.node_tree.name.startswith(GROUP_NAME)), None)


def mark_depth(scene, key):
    """Current planar depth of a placed mark from the scene camera, or None."""
    ob = mark_object(scene, key)
    if ob is None or scene.camera is None:
        return None
    return planar_depth(ob.matrix_world.translation, scene.camera.matrix_world)


def place_mark(scene, key, point):
    """Put mark `key` at the world point (an existing mark moves), then rebuild the drivers (returns the state)."""
    ob = mark_object(scene, key)
    if ob is None:
        ob = new_mark(scene, key)
    world = Vector(point)
    ob.location = ob.parent.matrix_world.inverted() @ world if ob.parent else world
    return rebuild_drivers(scene)


def new_mark(scene, key):
    _label, name, _socket = MARKS[key]
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = 'PLAIN_AXES'
    ob.empty_display_size = EMPTY_SIZE
    ob.show_name = True
    ob[MARK_KEY] = key
    marks_collection(scene, create=True).objects.link(ob)
    return ob


def remove_mark(scene, key):
    """Delete one mark. Its input goes back to its default; with no marks left both do (Start 0, End far)."""
    ob = mark_object(scene, key)
    if ob is not None:
        bpy.data.objects.remove(ob)
    if placed_keys(scene):
        return rebuild_drivers(scene)
    node = fog_node(scene)
    remove_drivers(node)
    if node is not None:
        node.inputs["Start"].default_value = 0.0
        node.inputs["End"].default_value = default_end(scene)
    remove_collection(scene)
    return STATE_NONE


def remove_all(scene):
    """Delete every mark and its drivers; the inputs keep their current values."""
    node = fog_node(scene)
    if node is not None:
        values = {socket: node.inputs[socket].default_value for _l, _n, socket in MARKS.values()}
        remove_drivers(node)
        for socket, value in values.items():
            node.inputs[socket].default_value = value
    collection = marks_collection(scene)
    for ob in list(collection.objects) if collection else ():
        bpy.data.objects.remove(ob)
    remove_collection(scene)


def remove_collection(scene):
    collection = marks_collection(scene)
    if collection is not None and not collection.objects:
        bpy.data.collections.remove(collection)


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def remove_drivers(node):
    if node is None:
        return
    for _label, _name, socket in MARKS.values():
        node.inputs[socket].driver_remove("default_value")


def rebuild_drivers(scene):
    """(Re)make the Depth Fog's Start / End drivers for the placed marks. Returns STATE_NONE (no marks: inputs
    left alone), STATE_NO_FOG (marks but no Depth Fog node) or STATE_DRIVEN. Safe to call any time."""
    placed = placed_keys(scene)
    if not placed:
        return STATE_NONE
    node = fog_node(scene)
    if node is None:
        return STATE_NO_FOG
    remove_drivers(node)
    marks = {key: mark_object(scene, key) for key in placed}
    clear_placed, out_placed = CLEAR in marks, OUT in marks
    if clear_placed:
        add_socket_driver(scene, node, "Start", start_expression(), {CLEAR: marks[CLEAR]})
    else:
        node.inputs["Start"].default_value = 0.0
    add_socket_driver(scene, node, "End", end_expression(clear_placed, out_placed), marks)
    return STATE_DRIVEN


def add_socket_driver(scene, node, socket, expression, marks):
    """Drive a Depth Fog input: scene-camera vars plus world-location vars <key>_x/_y/_z per mark."""
    driver = node.inputs[socket].driver_add("default_value").driver
    driver.type = 'SCRIPTED'
    for name, column, row in CAMERA_VARS:
        add_property_var(driver, name, 'SCENE', scene, f"camera.matrix_world[{column}][{row}]")
    # unused in the expression: it ties the driver to the Scene itself, so a camera switch re-runs it
    # (without it Blender keeps the old camera's depth until a mark moves)
    add_property_var(driver, "camera_switch", 'SCENE', scene, "frame_current")
    for key, ob in marks.items():
        for axis in "xyz":
            add_location_var(driver, f"{key}_{axis}", ob, axis)
    driver.expression = expression


def add_property_var(driver, name, id_type, owner, data_path):
    variable = driver.variables.new()
    variable.name, variable.type = name, 'SINGLE_PROP'
    target = variable.targets[0]
    target.id_type, target.id, target.data_path = id_type, owner, data_path


def add_location_var(driver, name, ob, axis):
    variable = driver.variables.new()
    variable.name, variable.type = name, 'TRANSFORMS'
    target = variable.targets[0]
    target.id = ob
    target.transform_type, target.transform_space = 'LOC_' + axis.upper(), 'WORLD_SPACE'


def is_driven(node, socket):
    tree = node.id_data
    path = node.inputs[socket].path_from_id("default_value")
    return bool(tree.animation_data) and tree.animation_data.drivers.find(path) is not None


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

def sky_point(scene, key, origin, direction, view_distance):
    """Where a click on empty sky puts a mark: along the ray at the mark's current distance, else the view distance."""
    ob = mark_object(scene, key)
    distance = (ob.matrix_world.translation - origin).length if ob is not None else view_distance
    return origin + direction.normalized() * distance


class RENDERPRESETS_OT_place_fog_mark(bpy.types.Operator):
    """Click in the 3D viewport to place this fog mark (a surface, or empty sky). Esc or right click cancels"""
    bl_idname = "render_presets.place_fog_mark"
    bl_label = "Place Fog Mark"
    bl_options = {'REGISTER', 'UNDO'}

    mark: EnumProperty(name="Mark", items=MARK_ITEMS)
    location: FloatVectorProperty(name="Location", subtype='TRANSLATION', options={'SKIP_SAVE'},
                                  description="World point (scripts; a click sets it)")

    def execute(self, context):
        if place_mark(context.scene, self.mark, self.location) == STATE_NO_FOG:
            self.report({'WARNING'}, "Mark placed. Apply a preset with Fog to use it")
        return {'FINISHED'}

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "Place marks in the 3D viewport")
            return {'CANCELLED'}
        return view_ray.begin_click(context, self, 'CROSSHAIR',
                                    f"Click where {MARKS[self.mark][0]} goes  ·  Esc / right click: cancel")

    def modal(self, context, event):
        kind = view_ray.click_kind(event)
        if kind == 'cancel':
            view_ray.end_click(context)
            return {'CANCELLED'}
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind == 'wait':
            context.window.cursor_modal_set('CROSSHAIR')   # other areas reset it as the mouse crosses them
            return {'RUNNING_MODAL'}
        found = view_ray.hit_under_mouse(context, event)
        if found is None:      # a click outside every 3D view (sidebar, header): let the UI have it
            return {'PASS_THROUGH'}
        point, _ob, origin, direction = found
        if point is None:
            region_data = view_ray.region_under_mouse(context.window.screen.areas, event.mouse_x, event.mouse_y)[1]
            point = sky_point(context.scene, self.mark, origin, direction, region_data.view_distance)
        view_ray.end_click(context)
        self.location = point
        return self.execute(context)


class RENDERPRESETS_OT_remove_fog_mark(bpy.types.Operator):
    """Remove this fog mark; its distance goes back to the default"""
    bl_idname = "render_presets.remove_fog_mark"
    bl_label = "Remove Fog Mark"
    bl_options = {'REGISTER', 'UNDO'}

    mark: EnumProperty(name="Mark", items=MARK_ITEMS)

    def execute(self, context):
        remove_mark(context.scene, self.mark)
        return {'FINISHED'}


class RENDERPRESETS_OT_remove_fog_marks(bpy.types.Operator):
    """Remove all fog marks and their drivers. The fog keeps its current Start and End"""
    bl_idname = "render_presets.remove_fog_marks"
    bl_label = "Remove Marks"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        remove_all(context.scene)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI rows (job C's Look section calls draw_rows)
# ---------------------------------------------------------------------------

def readout(scene, key, placed):
    """The distance text of a mark row."""
    if key not in placed:
        return "2 × Clear View" if key == OUT and CLEAR in placed else "default"
    depth = mark_depth(scene, key)
    return "no camera" if depth is None else f"{depth:.1f} m"


def draw_rows(layout, context):
    """One row per mark (name, distance or "default", crosshair, X), a note when there is no Depth Fog
    node to drive, and Remove Marks."""
    scene = context.scene
    placed = placed_keys(scene)
    column = layout.column(align=True)
    for key, (label, _name, _socket) in MARKS.items():
        row = column.row(align=True)
        row.label(text=label)
        row.label(text=readout(scene, key, placed))
        row.operator(RENDERPRESETS_OT_place_fog_mark.bl_idname, text="", icon='PIVOT_CURSOR').mark = key
        if key in placed:
            row.operator(RENDERPRESETS_OT_remove_fog_mark.bl_idname, text="", icon='X').mark = key
    if placed and fog_node(scene) is None:
        layout.label(text="Apply a preset with Fog to use", icon='INFO')
    if placed:
        layout.operator(RENDERPRESETS_OT_remove_fog_marks.bl_idname, icon='TRASH')


CLASSES = (RENDERPRESETS_OT_place_fog_mark, RENDERPRESETS_OT_remove_fog_mark, RENDERPRESETS_OT_remove_fog_marks)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
