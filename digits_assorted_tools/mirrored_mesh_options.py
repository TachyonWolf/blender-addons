# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Mirrored Mesh: the one definition of the options (primitive, axes, orientation, size and counts).

OptionsMixin is the single set of properties; the card's scene settings group and the operator both inherit it, so
their names, defaults and limits cannot drift apart. Changing an option on the card redoes the latest add in place
(mirrored_mesh_add.redo_last_add) and keeps the operator's Adjust Last Operation panel showing the same values."""
from contextlib import contextmanager

import bpy
from bpy.props import BoolVectorProperty, EnumProperty, FloatProperty, IntProperty

from . import mirrored_mesh as mm
from . import mirrored_mesh_add as add
from .helper_object_ui import SHAPES

_primitive_items = []     # Blender needs the lists of dynamic enums kept alive
_orientation_items = []
_syncing = False          # true while one side is copied into the other, so that does not start another redo


@contextmanager
def syncing():
    global _syncing
    _syncing = True
    try:
        yield
    finally:
        _syncing = False


def primitive_items(options, context):
    """The primitives, those that fit no turn on the current axes (at default settings) marked with a warning."""
    axes = add.chosen_axes(options, bpy.context)
    _primitive_items[:] = [
        (primitive, label if mm.valid_orientations(primitive, mm.PrimitiveSettings(), axes) else f"{label} (no fit)",
         tooltip, 'NONE' if mm.valid_orientations(primitive, mm.PrimitiveSettings(), axes) else 'ERROR', number)
        for number, (primitive, label, tooltip) in enumerate(SHAPES)]
    return _primitive_items


def orientation_items(options, context):
    orientations = mm.valid_orientations(options.primitive, add.settings_of(options), add.chosen_axes(options, bpy.context))
    _orientation_items[:] = [(orientation.key, orientation.label, "") for orientation in orientations]
    return _orientation_items or [('NONE', "None fits", "")]


def on_option_changed(options, context):
    """Card update: redo the latest add with the new values, if it is still the latest thing done."""
    if _syncing or not isinstance(options, MirroredMeshCard):
        return
    with syncing():
        if add.redo_last_add(context, options):
            copy_options(options, add.last_operator(context).properties)


def copy_options(source, target, only_unset=False):
    """Copy every option from one holder (card or operator) to the other (with only_unset, just the ones the target
    was not given); orientation last, its list depends on the rest."""
    for name in ("primitive", "axes", *add.OPTION_NAMES, "orientation"):
        if only_unset and getattr(target, "properties", target).is_property_set(name):
            continue
        value = getattr(source, name)
        try:
            setattr(target, name, tuple(value) if name == "axes" else value)
        except TypeError:
            if name != "orientation":   # no turn fits: the list is empty and has nothing to set
                raise


class OptionsMixin:
    primitive: EnumProperty(name="Primitive", items=primitive_items, update=on_option_changed,
                            description="The shape to add, as a mirrored half")
    axes: BoolVectorProperty(name="Mirror Axes", size=3, default=(True, False, False), update=on_option_changed,
                             description="Axes of the Mirror modifier on the new object (Edit Mode uses the object's own)")
    orientation: EnumProperty(name="Orientation", items=orientation_items, update=on_option_changed,
                              description="How the shape is turned so that it mirrors exactly")
    size: FloatProperty(name="Size", default=mm.PrimitiveSettings.size, min=0.001, soft_max=100.0, unit='LENGTH',
                        update=on_option_changed, description="Overall width of the whole shape")
    segments: IntProperty(name="Segments", default=mm.PrimitiveSettings.segments, min=3, soft_max=128,
                          update=on_option_changed)
    rings: IntProperty(name="Rings", default=mm.PrimitiveSettings.rings, min=3, soft_max=64, update=on_option_changed)
    major_segments: IntProperty(name="Major Segments", default=mm.PrimitiveSettings.major_segments, min=3,
                                soft_max=128, update=on_option_changed)
    minor_segments: IntProperty(name="Minor Segments", default=mm.PrimitiveSettings.minor_segments, min=3,
                                soft_max=64, update=on_option_changed)
    subdivisions: IntProperty(name="Subdivisions", default=mm.PrimitiveSettings.subdivisions, min=1, max=6,
                              update=on_option_changed)
    grid_divisions: IntProperty(name="Divisions", default=mm.PrimitiveSettings.grid_divisions, min=1, soft_max=100,
                                update=on_option_changed)


class MirroredMeshCard(bpy.types.PropertyGroup, OptionsMixin):
    """The card's settings, on the scene: used by the next Add and, while it is the latest action, by the last one."""
