# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Mirrored Mesh: planning and doing one add, and redoing it in place when a card option changes afterwards.

`options` is anything with the card's option names (the card's settings group or the operator); both are built from
mirrored_mesh_options.OptionsMixin. Geometry is in mirrored_mesh.py."""
from dataclasses import dataclass

import bmesh
import bpy

from . import mirrored_mesh as mm
from .helper_object_ui import SHAPES

OPERATOR_ID = "digits_assorted_tools.add_mirrored_mesh"
OPTION_NAMES = ("size", "segments", "rings", "major_segments", "minor_segments", "subdivisions", "grid_divisions")
LABELS = {shape[0]: shape[1] for shape in SHAPES}
SUPPORTED_MODES = {'OBJECT', 'EDIT_MESH'}


def settings_of(options):
    return mm.PrimitiveSettings(*(getattr(options, name) for name in OPTION_NAMES))


def chosen_axes(options, context):
    """Axes (indices) to mirror: from the active object's Mirror modifiers in Edit Mode, else the options' own."""
    if context.mode == 'EDIT_MESH':
        return mm.claimed_axes(mm.mirror_claims(context.edit_object))
    return tuple(axis for axis in range(3) if options.axes[axis])


@dataclass
class AddPlan:
    label: str
    axes: tuple
    claims: list          # Edit Mode: [(MirrorPlanes, axes)]; empty in Object Mode
    settings: mm.PrimitiveSettings
    orientation: mm.Orientation


def plan_add(context, options):
    """(AddPlan, "") when the options can be added here, else (None, why not). Reads only; cached analysis."""
    if context.mode not in SUPPORTED_MODES:
        return None, "Switch to Object Mode or mesh Edit Mode"
    edit_mode = context.mode == 'EDIT_MESH'
    claims = mm.mirror_claims(context.edit_object) if edit_mode else []
    if edit_mode and not claims:
        return None, "Add a Mirror modifier first"
    axes = mm.claimed_axes(claims) if edit_mode else chosen_axes(options, context)
    if not axes:
        return None, "Choose at least one mirror axis"
    settings, label = settings_of(options), LABELS[options.primitive]
    orientations = mm.valid_orientations(options.primitive, settings, axes)
    if not orientations:
        return None, mm.no_orientation_message(label, options.primitive, settings, axes)
    chosen = next((turn for turn in orientations if turn.key == options.orientation), orientations[0])
    return AddPlan(label, axes, claims, settings, chosen), ""


@dataclass
class LastAdd:
    """What the latest add made, so a card change can redo it: the object's name, and (Edit Mode) how many vertices
    it added, which are the selection while nothing else has happened."""
    mode: str
    object_name: str
    vertex_count: int = 0


last_add = None   # set by add_half; only trusted while our operator is still the last one run


def half_name(plan):
    return f"{plan.label} Half"


def add_half(context, plan, primitive):
    """Do the add: a new object (Object Mode) or new geometry in the edited mesh (Edit Mode)."""
    global last_add
    half = mm.build_half(primitive, plan.settings, plan.axes, plan.orientation.rotation)
    if context.mode == 'EDIT_MESH':
        obj = context.edit_object
        append_to_object(obj, half, plan, context)
        last_add = LastAdd('EDIT_MESH', obj.name, len(half.verts))
    else:
        obj = mm.add_object(context, half, half_name(plan), plan.axes)
        last_add = LastAdd('OBJECT', obj.name)
    half.free()


def append_to_object(obj, half, plan, context):
    matrix = mm.placement_matrix(obj, plan.claims, context.scene.cursor.location)
    mesh = bmesh.from_edit_mesh(obj.data)
    mm.append_to_edit_mesh(mesh, half, matrix)
    bmesh.update_edit_mesh(obj.data)


def last_operator(context):
    operators = context.window_manager.operators
    return operators[-1] if operators and operators[-1].bl_idname == OPERATOR_ID else None


def can_redo_last_add(context):
    """True while the latest thing done was our add, still the active object / selection in the same mode."""
    if last_add is None or last_operator(context) is None or context.mode != last_add.mode:
        return False
    if last_add.mode == 'OBJECT':
        obj = bpy.data.objects.get(last_add.object_name)
        return obj is not None and context.object is obj
    obj = context.edit_object
    if obj is None or obj.name != last_add.object_name:
        return False
    return sum(vert.select for vert in bmesh.from_edit_mesh(obj.data).verts) == last_add.vertex_count


def redo_last_add(context, options):
    """Redo the latest add in place with the card's current options (no undo needed: we know what it made).
    Returns True when it did; False leaves everything alone and the options only apply to the next add."""
    global last_add
    if not can_redo_last_add(context):
        return False
    plan, _why = plan_add(context, options)
    if plan is None:
        return False
    half = mm.build_half(options.primitive, plan.settings, plan.axes, plan.orientation.rotation)
    if last_add.mode == 'OBJECT':
        obj = bpy.data.objects[last_add.object_name]
        mm.replace_object_mesh(obj, half, half_name(plan), plan.axes)
        last_add.object_name = obj.name
    else:
        obj = context.edit_object
        mesh = bmesh.from_edit_mesh(obj.data)
        mm.delete_selected(mesh)
        append_to_object(obj, half, plan, context)
        last_add.vertex_count = len(half.verts)
    half.free()
    return True
