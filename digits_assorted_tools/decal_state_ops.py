# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the state operators (Stick, Unstick, Rebind, Attach / Re-aim, Detach) and the Target pick. Each acts on
the decal named in `decal_name`, or the active object when that is empty. All work is done by decal_mesh; these
only find the decal, report and make one undo step. Used by the Decals card and the Selected panel alike."""

from math import radians

import bpy
from bpy.props import BoolProperty, StringProperty

from . import decal_mesh
from .decal_recipe import STUCK, UNATTACHED
from .placement_math import precise, ray_plane_point, snap_angle, spin_angle
from .rig_placement import PickOperator
from .view_ray import cast_surface, mouse_ray  # generated copy

AIM_HELP = "Click the surface for the decal  ·  Esc / Right-click: cancel"
SPIN_HELP = "Turn the decal to face the mouse  ·  Ctrl: 15° steps  ·  Shift: precise  ·  Click: done  ·  Esc: keep"
SPIN_SNAP = radians(15)
TARGET_HELP = "Click the mesh that gets decals  ·  Esc / Right-click: cancel"


def named_decal(context, name):
    """The decal called `name`, else the active object when it is a decal, else None."""
    ob = bpy.data.objects.get(name) if name else context.active_object
    return ob if decal_mesh.is_decal(ob) else None


def surface_under(context, view):
    """(point, normal, object) of the first mesh along the view ray that is not a decal, or None."""
    found = cast_surface(context.scene, context.evaluated_depsgraph_get(), view.eye, view.forward,
                         skip=decal_mesh.is_decal)
    if found is None or found[2].type != 'MESH':
        return None
    return found


def report_warnings(operator, warnings):
    for warning in warnings:
        operator.report({'WARNING'}, warning)


class DecalOperator:
    """Shared: the decal_name property and one undo step (buttons are only drawn for a decal; execute checks)."""
    bl_options = {'REGISTER', 'UNDO'}
    decal_name: StringProperty(name="Decal", options={'HIDDEN', 'SKIP_SAVE'},
                               description="The decal to change (empty: the active object)")

    def decal(self, context):
        return named_decal(context, self.decal_name)


class StickDecal(DecalOperator):
    """Shared by Stick and Rebind (Stick on a Stuck decal re-sticks it from its aim)."""

    def execute(self, context):
        decal = self.decal(context)
        if decal is None or decal.digit_decal.state == UNATTACHED:
            self.report({'ERROR'}, "Attach the decal to a surface first")
            return {'CANCELLED'}
        report_warnings(self, decal_mesh.stick(context, decal))
        return {'FINISHED'}


class DECAL_OT_stick(StickDecal, bpy.types.Operator):
    """Stick the decal: it stops sliding and follows the rig, shape keys and deforming modifiers"""
    bl_idname = "decal.stick"
    bl_label = "Stick"


class DECAL_OT_rebind(StickDecal, bpy.types.Operator):
    """Stick the decal again: the target's mesh changed, so it stopped following"""
    bl_idname = "decal.rebind"
    bl_label = "Rebind"


class DECAL_OT_unstick(DecalOperator, bpy.types.Operator):
    """Unstick the decal: it slides on the surface again and can be moved, sized and turned"""
    bl_idname = "decal.unstick"
    bl_label = "Unstick"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None or decal.digit_decal.state != STUCK:
            return {'CANCELLED'}
        decal_mesh.unstick(decal)
        return {'FINISHED'}


class DECAL_OT_detach(DecalOperator, bpy.types.Operator):
    """Take the decal off its surface: it stays where it is, flat, ready to be attached again"""
    bl_idname = "decal.detach"
    bl_label = "Detach"

    def execute(self, context):
        decal = self.decal(context)
        if decal is None or decal.digit_decal.state == UNATTACHED:
            return {'CANCELLED'}
        decal_mesh.detach(decal)
        return {'FINISHED'}


class DECAL_OT_aim(DecalOperator, PickOperator, bpy.types.Operator):
    """Click a surface to put the decal there (Attach, or Re-aim a placed one), then (Aim After Place) turn it to
    face the mouse around the surface normal and click. A Stuck decal sticks again"""
    bl_idname = "decal.aim"
    bl_label = "Re-aim"
    pick_help = AIM_HELP
    refine_help = SPIN_HELP
    stick_after: BoolProperty(name="Stick After", options={'HIDDEN', 'SKIP_SAVE'},
                              description="Stick the decal once it is placed")
    _placed = None    # (decal name, re-stick after?) once the click has placed it

    def prepare(self):
        self._placed = None
        return named_decal(bpy.context, self.decal_name) is not None

    def readout(self, context, view):
        found = surface_under(context, view)
        return found[2].name if found else None

    def place(self, context, view):
        """Put the decal at the surface under `view`; False when there is none."""
        decal = named_decal(context, self.decal_name)
        found = surface_under(context, view)
        if decal is None or found is None:
            return False
        point, normal, target = found
        stick_again = decal.digit_decal.state == STUCK or self.stick_after
        decal_mesh.attach(context, decal, target, point, normal)
        context.scene.digit_decals.target = target
        self._placed = (decal.name, stick_again)
        return True

    def refine_start(self, context, view, region, rv3d):
        """The click placed the decal; with Aim After Place, the second step turns it."""
        if not self.place(context, view) or not context.scene.digit_decals.aim_after_place or rv3d is None:
            return False
        decal = bpy.data.objects[self._placed[0]]
        self._spin = (region, rv3d, decal.matrix_world.translation.copy(), decal_mesh.base_frame_world(decal),
                      decal.digit_decal.rotation)
        return True

    def refine_move(self, context, mouse):
        region, rv3d, centre, (_point, normal, up), start = self._spin
        origin, direction = mouse_ray(region, rv3d, mouse)
        on_dial = ray_plane_point(origin, direction, centre, normal)
        angle = spin_angle(up, on_dial - centre, normal) if on_dial is not None else None
        if angle is None:
            return
        if self._ctrl:
            angle = snap_angle(angle, SPIN_SNAP)
        decal_mesh.drag_frame(bpy.data.objects[self._placed[0]], rotation=precise(start, angle, self._shift))

    def refine_cancel(self, context):
        """Esc: keep the angle it was placed with."""
        decal = bpy.data.objects[self._placed[0]]
        decal_mesh.drag_frame(decal, rotation=self._spin[4])
        decal_mesh.finish_drag(context, decal, self._placed[1])

    def picked(self, context, view):
        if self._placed is None and not self.place(context, view):
            self.report({'WARNING'}, "No mesh there: click a surface")
            return {'CANCELLED'}
        decal = bpy.data.objects[self._placed[0]]
        report_warnings(self, decal_mesh.finish_drag(context, decal, self._placed[1]))
        return {'FINISHED'}


class DECAL_OT_pick_target(PickOperator, bpy.types.Operator):
    """Click the mesh whose decals the card lists and where new decals go"""
    bl_idname = "decal.pick_target"
    bl_label = "Pick Target"
    bl_options = {'REGISTER', 'UNDO'}
    pick_help = TARGET_HELP

    def readout(self, context, view):
        found = surface_under(context, view)
        return found[2].name if found else None

    def picked(self, context, view):
        found = surface_under(context, view)
        if found is None:
            self.report({'WARNING'}, "No mesh there")
            return {'CANCELLED'}
        context.scene.digit_decals.target = found[2]
        return {'FINISHED'}


CLASSES = (DECAL_OT_stick, DECAL_OT_rebind, DECAL_OT_unstick, DECAL_OT_detach, DECAL_OT_aim, DECAL_OT_pick_target)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
