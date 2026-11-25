# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the viewport handles of the active decal (notes/wip/decals-mockups/AltB.dc.html, handles only), shown
only with the card's Gizmos On and a placed decal active:
- a blue frame around the decal; drag inside it = slide over the surface (re-aims the decal),
- four white corner squares = size,
- the orange dot on a stem above the top edge = rotate (Ctrl: 15 degree steps).
Shift = precise (Blender's convention). A drag on a Stuck decal unsticks it, moves it and sticks it again on
release; Esc / right-click puts everything back. One undo step per drag.

No handlers, timers or msgbus: the gizmo group's poll is two cheap checks (toggle, active object); its matrices are
set in draw_prepare from the active decal's frame. The drag maths are in placement_math (tested there)."""

from math import cos, pi, sin

import bpy
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from . import decal_maps, decal_mesh
from .decal_recipe import STUCK, UNATTACHED
from .decal_state_ops import SPIN_SNAP
from .placement_math import drag_angle, drag_scale, precise, ray_plane_point, snap_angle
from .view_ray import cast_surface, mouse_ray  # generated copy

FRAME_COLOR = (0.28, 0.45, 0.70)        # Blender's selection blue (#4772b3)
DOT_COLOR = (0.88, 0.63, 0.19)          # the mockup's orange (#e0a030)
CORNER_COLOR = (1.0, 1.0, 1.0)
HIGHLIGHT = (1.0, 1.0, 1.0)
CORNER_SIZE = 0.09                      # screen-relative (use_draw_scale) half size of a corner square
DOT_SIZE = 0.12                         # screen-relative radius of the rotate dot
STEM = 0.18                             # stem length, as a part of the decal's longer side
ROTATE_SNAP = SPIN_SNAP
CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
PARTS = (('MOVE', "Slide", "Slide the decal over the surface"), ('SIZE', "Size", "Make the decal bigger or smaller"),
         ('ROTATE', "Rotate", "Turn the decal around its normal"))
HELP = {'MOVE': "Slide the decal  ·  Shift: precise  ·  Esc / Right-click: cancel",
        'SIZE': "Size the decal  ·  Shift: precise  ·  Esc / Right-click: cancel",
        'ROTATE': "Rotate the decal  ·  Ctrl: 15° steps  ·  Shift: precise  ·  Esc / Right-click: cancel"}


def square(half=1.0):
    return [(-half, -half, 0), (half, -half, 0), (half, -half, 0), (half, half, 0), (half, half, 0), (-half, half, 0),
            (-half, half, 0), (-half, -half, 0)]


def filled_square(half=1.0):
    return [(-half, -half, 0), (half, -half, 0), (half, half, 0), (-half, -half, 0), (half, half, 0), (-half, half, 0)]


def filled_disk(radius=1.0, segments=20):
    points = []
    for index in range(segments):
        first, second = 2 * pi * index / segments, 2 * pi * (index + 1) / segments
        points += [(0, 0, 0), (radius * cos(first), radius * sin(first), 0), (radius * cos(second), radius * sin(second), 0)]
    return points


def active_placed_decal(context):
    """The active object when it is a decal on a surface (Placing or Stuck), else None."""
    ob = context.active_object
    return ob if decal_mesh.is_decal(ob) and ob.digit_decal.state != UNATTACHED else None


class DECAL_GT_shape(bpy.types.Gizmo):
    """One handle drawn from a custom shape; `invisible` handles only take clicks (the frame's inside)."""
    bl_idname = "DECAL_GT_shape"
    __slots__ = ("shape", "invisible")

    def setup(self):
        self.shape = None
        self.invisible = False

    def set_shape(self, kind, points, invisible=False):
        self.shape = self.new_custom_shape(kind, points)
        self.invisible = invisible

    def draw(self, context):
        if self.shape is not None and not self.invisible:
            self.draw_custom_shape(self.shape)

    def draw_select(self, context, select_id):
        if self.shape is not None:
            self.draw_custom_shape(self.shape, select_id=select_id)


class DECAL_GGT_handles(bpy.types.GizmoGroup):
    bl_idname = "DECAL_GGT_handles"
    bl_label = "Decal Handles"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "digit_decals", None)
        return settings is not None and settings.show_gizmos and active_placed_decal(context) is not None

    def add(self, kind, points, color, part=None, screen_sized=False, scale=1.0, invisible=False, pickable=True):
        gizmo = self.gizmos.new(DECAL_GT_shape.bl_idname)
        gizmo.set_shape(kind, points, invisible)
        gizmo.color = color
        gizmo.alpha = 0.0 if invisible else 0.9
        gizmo.color_highlight = HIGHLIGHT
        gizmo.alpha_highlight = 0.0 if invisible else 1.0
        gizmo.use_draw_scale = screen_sized
        gizmo.scale_basis = scale
        gizmo.line_width = 2.0
        gizmo.hide_select = not pickable
        if part is not None:
            gizmo.target_set_operator(DECAL_OT_handle_drag.bl_idname).part = part
        return gizmo

    def setup(self, context):
        # the inside first, so the corners and the dot (added later) win where they overlap it
        self.middle = self.add('TRIS', filled_square(), FRAME_COLOR, 'MOVE', invisible=True)
        self.frame = self.add('LINES', square(), FRAME_COLOR, pickable=False)
        self.stem = self.add('LINES', [(0, 0, 0), (0, 1, 0)], DOT_COLOR, pickable=False)
        self.corners = [self.add('TRIS', filled_square(), CORNER_COLOR, 'SIZE', True, CORNER_SIZE) for _ in CORNERS]
        self.dot = self.add('TRIS', filled_disk(), DOT_COLOR, 'ROTATE', True, DOT_SIZE)

    def draw_prepare(self, context):
        decal = active_placed_decal(context)
        if decal is None:
            return
        recipe = decal.digit_decal
        width, height = decal_maps.decal_dimensions(recipe.size, recipe.aspect)
        world = decal.matrix_world
        turn = world.to_3x3().normalized().to_4x4()
        self.middle.matrix_basis = world @ Matrix.Diagonal((width / 2, height / 2, 1, 1))
        self.frame.matrix_basis = self.middle.matrix_basis
        stem = STEM * max(width, height)
        self.stem.matrix_basis = world @ Matrix.Translation((0, height / 2, 0)) @ Matrix.Diagonal((1, stem, 1, 1))
        for gizmo, (along_x, along_y) in zip(self.corners, CORNERS):
            gizmo.matrix_basis = Matrix.Translation(world @ Vector((along_x * width / 2, along_y * height / 2, 0))) @ turn
        self.dot.matrix_basis = Matrix.Translation(world @ Vector((0, height / 2 + stem, 0))) @ turn


class DECAL_OT_handle_drag(bpy.types.Operator):
    """Drag a decal handle: slide, size or rotate it on the surface"""
    bl_idname = "decal.handle_drag"
    bl_label = "Drag Decal Handle"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
    part: EnumProperty(name="Handle", items=PARTS, options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        decal = active_placed_decal(context)
        if decal is None or context.region_data is None:
            return {'CANCELLED'}
        self.decal_name = decal.name
        recipe = decal.digit_decal
        self.was_stuck = recipe.state == STUCK
        if self.was_stuck:
            decal_mesh.unstick(decal)          # the only auto re-stick is this drag's release
        decal_mesh.fold_scale(decal)
        self.start = (recipe.size, recipe.rotation, *decal_mesh.base_frame_world(decal))
        self.centre = decal.matrix_world.translation.copy()
        self.normal = (decal.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        self.up = self.start[4]      # the aim's own up (Rotation turns away from it)
        self.start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.start_point = self.on_plane(context, self.start_mouse)
        centre_2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, self.centre)
        self.grab = (centre_2d - self.start_mouse) if centre_2d is not None else Vector((0, 0))
        context.workspace.status_text_set(HELP[self.part])
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def on_plane(self, context, mouse):
        origin, direction = mouse_ray(context.region, context.region_data, mouse)
        return ray_plane_point(origin, direction, self.centre, self.normal)

    def modal(self, context, event):
        decal = bpy.data.objects.get(self.decal_name)
        if decal is None:
            return self.end(context, {'CANCELLED'})
        if event.type == 'MOUSEMOVE':
            mouse = precise(self.start_mouse, Vector((event.mouse_region_x, event.mouse_region_y)), event.shift)
            getattr(self, "drag_" + self.part.lower())(context, decal, mouse, event)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            for warning in decal_mesh.finish_drag(context, decal, self.was_stuck):
                self.report({'WARNING'}, warning)
            return self.end(context, {'FINISHED'})
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            size, rotation, point, normal, up = self.start
            decal_mesh.drag_frame(decal, point, normal, up, rotation, size)
            decal_mesh.finish_drag(context, decal, self.was_stuck)
            return self.end(context, {'CANCELLED'})
        return {'RUNNING_MODAL'}

    def drag_move(self, context, decal, mouse, event):
        origin, direction = mouse_ray(context.region, context.region_data, mouse + self.grab)
        hit = cast_surface(context.scene, context.evaluated_depsgraph_get(), origin, direction,
                           skip=decal_mesh.is_decal)
        if hit is not None and decal_mesh.is_surface_of(decal, hit[2]):
            decal_mesh.drag_frame(decal, point=hit[0], normal=hit[1], up=self.up)

    def drag_size(self, context, decal, mouse, event):
        point = self.on_plane(context, mouse)
        factor = drag_scale(self.centre, self.start_point, point) if point and self.start_point else None
        if factor is not None:
            decal_mesh.drag_frame(decal, size=max(0.001, self.start[0] * factor))

    def drag_rotate(self, context, decal, mouse, event):
        point = self.on_plane(context, mouse)
        angle = drag_angle(self.centre, self.start_point, point, self.normal) if point and self.start_point else None
        if angle is None:
            return
        if event.ctrl:
            angle = snap_angle(angle, ROTATE_SNAP)
        decal_mesh.drag_frame(decal, rotation=self.start[1] + angle)

    def end(self, context, result):
        context.workspace.status_text_set(None)
        return result


CLASSES = (DECAL_GT_shape, DECAL_GGT_handles, DECAL_OT_handle_drag)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
