# SPDX-License-Identifier: GPL-3.0-or-later
"""The Custom Facing arrow: a 3D viewport gizmo drawn from the target's centre along the decal's Custom direction.
Drag the arrow (shaft or head) to turn it as a trackball (see facing_math.py); Ctrl snaps to 15 degrees; Esc / right
click cancels the drag. It sets scene.digit_texture_screenshot.custom_facing, nothing else.

The group shows only while the Processes card of Make Object Texture Data Screenshot is the chosen process, Add as
Decal is on, Facing is Custom and the target is set: the poll is four property reads, no scans. The centre and length
are recomputed in `refresh` (Blender calls it on selection / scene changes), the direction in `draw_prepare`. No
handlers, timers or msgbus."""
import bpy
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from ..tool_picker import tool_id
from . import decal_step, facing_math

PROCESS_ID = tool_id("Make Object Texture Data Screenshot")
COLOR = (0.2, 0.7, 1.0)
HIGHLIGHT = (1.0, 0.85, 0.3)
MIN_LENGTH = 0.3
LENGTH_FACTOR = 0.75           # arrow length = this x the target's longest side
MAX_OBJECTS = 200              # the bounds loop stops here (a huge collection still gets a sensible arrow)
RENDERABLE = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'CURVES', 'POINTCLOUD', 'VOLUME', 'GPENCIL', 'GREASEPENCIL'}


# --- shapes (local Z, length 1) -------------------------------------------------------------------------------

def head_triangles(segments=16, base=0.78, radius=0.07):
    from math import cos, pi, sin
    ring = [(radius * cos(2 * pi * i / segments), radius * sin(2 * pi * i / segments), base) for i in range(segments)]
    triangles = []
    for i in range(segments):
        a, b = ring[i], ring[(i + 1) % segments]
        triangles += [a, b, (0, 0, 1.0), b, a, (0, 0, base)]
    return triangles


SHAFT = [(0, 0, 0), (0, 0, 0.8)]


# --- target frame ---------------------------------------------------------------------------------------------

def target_frame(target):
    """(centre, length) in world space of an Object (with its children) or a Collection, or None when empty."""
    from .process import target_objects
    low = high = None
    for count, ob in enumerate(target_objects(target)):
        if count >= MAX_OBJECTS:
            break
        if ob.type not in RENDERABLE:
            continue
        for corner in ob.bound_box:
            point = ob.matrix_world @ Vector(corner)
            low = point.copy() if low is None else Vector(map(min, low, point))
            high = point.copy() if high is None else Vector(map(max, high, point))
    if low is None:
        return None
    return (low + high) / 2, max(MIN_LENGTH, LENGTH_FACTOR * max(high - low))


def shown(context):
    """The cheap poll: card chosen, Add as Decal on, Facing = Custom, a target set. Returns the options or None."""
    if context.window_manager.digit_process != PROCESS_ID or context.mode != 'OBJECT':
        return None
    options = getattr(context.scene, "digit_texture_screenshot", None)
    if options is None or not options.add_decal or options.facing != decal_step.CUSTOM:
        return None
    from .ui import target_of
    return options if target_of(context, options) is not None else None


# --- gizmo ----------------------------------------------------------------------------------------------------

class DIGITPROCESSES_GT_facing_arrow(bpy.types.Gizmo):
    bl_idname = "DIGITPROCESSES_GT_facing_arrow"

    def setup(self):
        self.shaft = self.new_custom_shape('LINES', SHAFT)
        self.head = self.new_custom_shape('TRIS', head_triangles())
        self.start = None

    def draw(self, context):
        self.draw_custom_shape(self.shaft)
        self.draw_custom_shape(self.head)

    def draw_select(self, context, select_id):
        self.draw_custom_shape(self.shaft, select_id=select_id)
        self.draw_custom_shape(self.head, select_id=select_id)

    def invoke(self, context, event):
        self.start = tuple(context.scene.digit_texture_screenshot.custom_facing)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        if cancel and self.start is not None:
            context.scene.digit_texture_screenshot.custom_facing = self.start
        self.start = None

    def modal(self, context, event, tweak):
        group = self.group
        if group.centre is None or context.region_data is None:
            return {'RUNNING_MODAL'}
        options = context.scene.digit_texture_screenshot
        mouse = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, mouse)
        ray = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, mouse)
        direction = facing_math.tip_direction(origin, ray, group.centre, group.length,
                                              decal_step.custom_vector(options.custom_facing))
        if event.ctrl:
            direction = facing_math.snap_direction(direction)
        options.custom_facing = tuple(direction)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


class DIGITPROCESSES_GGT_facing(bpy.types.GizmoGroup):
    bl_idname = "DIGITPROCESSES_GGT_facing"
    bl_label = "Custom Facing Arrow"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D'}

    @classmethod
    def poll(cls, context):
        return shown(context) is not None

    def setup(self, context):
        self.centre, self.length = None, 1.0
        arrow = self.gizmos.new(DIGITPROCESSES_GT_facing_arrow.bl_idname)
        arrow.color, arrow.color_highlight = COLOR, HIGHLIGHT
        arrow.alpha, arrow.alpha_highlight = 0.8, 1.0
        arrow.line_width = 3
        arrow.use_draw_modal = True
        self.arrow = arrow
        self.refresh(context)

    def refresh(self, context):
        options = shown(context)
        frame = None
        if options is not None:
            from .ui import target_of
            frame = target_frame(target_of(context, options))
        self.centre, self.length = frame if frame else (None, 1.0)
        self.arrow.hide = self.centre is None

    def draw_prepare(self, context):
        options = shown(context)
        if self.centre is None or options is None:
            return
        turn = Vector((0, 0, 1)).rotation_difference(decal_step.custom_vector(options.custom_facing)).to_matrix()
        self.arrow.matrix_basis = Matrix.Translation(self.centre) @ turn.to_4x4() @ Matrix.Scale(self.length, 4)


CLASSES = (DIGITPROCESSES_GT_facing_arrow, DIGITPROCESSES_GGT_facing)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
