"""Mirror Pivot: Scale / Rotate in mesh Edit Mode around the centre of the selection as if the Mirror modifier's
copy were real and selected ("Median Point with Mirror"), plus Cursor to Mirrored Selection.

The flag lives on the scene (`mirror_pivot_active`); the real pivot stays Median Point. S and R call a wrapper operator
that passes `center_override` to the built-in transform. No handlers, timers or msgbus: a flag left on while the
pivot is changed is cleared the next time S or R is pressed. Draw functions only read.

Layers: `mirrored_center` is pure maths (mathutils only); `mirror_planes_of` / `applicable_mirrors` read the modifiers;
`selection_center` joins them for the operators, the pivot panel and the header badge."""
from dataclasses import dataclass

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from mathutils import Vector

from .menu_entries import append_menus, remove_menus

AXIS_LETTERS = "XYZ"
CENTER_PIVOT = 'MEDIAN_POINT'


# ---------------------------------------------------------------------------
# Pure maths
# ---------------------------------------------------------------------------

@dataclass
class MirrorPlanes:
    """One Mirror modifier: world_to_plane maps world space into the space the planes live in (the object's local
    space, or the mirror object's); axes are the axis indices (0 X, 1 Y, 2 Z) in use; merge_distance is None when
    Merge is off, else points closer than that to a plane are not copied (they merge, so they exist once)."""
    world_to_plane: object
    axes: tuple
    merge_distance: float = None


def reflect_points(points, planes):
    """Copies of the world-space points reflected through each of the modifier's axes in turn (copies of copies
    included, as the real modifier builds them). Returns the new points only."""
    to_plane = planes.world_to_plane
    to_world = to_plane.inverted()
    current = [to_plane @ point for point in points]
    added = []
    for axis in planes.axes:
        copies = []
        for point in current:
            if planes.merge_distance is not None and abs(point[axis]) <= planes.merge_distance:
                continue
            copy = point.copy()
            copy[axis] = -copy[axis]
            copies.append(copy)
        added += copies
        current += copies
    return [to_world @ point for point in added]


def mirrored_center(point_groups):
    """(centre, axis letters used) of [(world-space points, [MirrorPlanes in stack order])], one group per object.
    Every group's points are mirrored by its own modifiers; the centre is the mean of all real + mirrored points.
    Returns (None, "") when there are no points."""
    everything = []
    used_axes = set()
    for points, planes_list in point_groups:
        group_points = [Vector(point) for point in points]
        for planes in planes_list:
            if group_points:
                group_points += reflect_points(group_points, planes)
                used_axes.update(planes.axes)
        everything += group_points
    if not everything:
        return None, ""
    center = sum(everything, Vector()) / len(everything)
    return center, "".join(AXIS_LETTERS[axis] for axis in sorted(used_axes))


# ---------------------------------------------------------------------------
# Which Mirror modifiers count
# ---------------------------------------------------------------------------

def applicable_mirrors(obj, only_on_cage):
    """(modifiers that count, skip reason). A Mirror counts when it is enabled in the viewport and in Edit Mode, has an
    axis on, and (with only_on_cage) has On Cage on. The reason is "" when some count, else a sentence for the report."""
    candidates = [mod for mod in obj.modifiers
                  if mod.type == 'MIRROR' and mod.show_viewport and mod.show_in_editmode and any(mod.use_axis)]
    if not candidates:
        return [], f'No Mirror modifier on "{obj.name}": using plain Median Point'
    counted = [mod for mod in candidates if mod.show_on_cage or not only_on_cage]
    if not counted:
        return [], "Mirror On Cage is off: using plain Median Point"
    return counted, ""


def mirror_planes_of(obj, modifier):
    mirror_object = modifier.mirror_object
    space = mirror_object.matrix_world if mirror_object else obj.matrix_world
    merge_distance = modifier.merge_threshold if modifier.use_mirror_merge else None
    axes = tuple(axis for axis in range(3) if modifier.use_axis[axis])
    return MirrorPlanes(space.inverted(), axes, merge_distance)


def selected_world_points(obj):
    mesh = bmesh.from_edit_mesh(obj.data)
    return [obj.matrix_world @ vert.co for vert in mesh.verts if vert.select]


def mirrored_groups(context, only_on_cage):
    """([(world points, [MirrorPlanes])] per mesh object in Edit Mode, first skip reason). only_on_cage is the one
    "which mirrors count" switch: True counts only Mirrors with On Cage on; the tools below pass False."""
    groups, reason = [], ""
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        modifiers, obj_reason = applicable_mirrors(obj, only_on_cage)
        reason = reason or obj_reason
        groups.append((selected_world_points(obj), [mirror_planes_of(obj, mod) for mod in modifiers]))
    return groups, reason


def selection_center(context, only_on_cage=None):
    """(centre or None, axis letters, skip reason) for the selection of every object in Edit Mode. The centre is None
    when no mirror applies to any of them (reason says why) or nothing is selected. only_on_cage None = the scene
    setting of Median Point with Mirror."""
    if only_on_cage is None:
        only_on_cage = context.scene.mirror_pivot_only_on_cage
    groups, reason = mirrored_groups(context, only_on_cage)
    if not any(planes_list for _points, planes_list in groups):
        return None, "", reason
    center, axes = mirrored_center(groups)
    return center, axes, reason


def tool_center(context):
    """Centre for the Mirror Rotate / Mirror Scale tools: ignores the Median Point with Mirror mode and On Cage (any
    Mirror enabled in viewport and Edit Mode counts); plain median of the selection when no mirror applies. None when
    nothing is selected."""
    groups, _reason = mirrored_groups(context, only_on_cage=False)
    return mirrored_center(groups)[0]


def mirror_axes_label(context):
    """Axis letters of the mirrors that apply to the objects in Edit Mode (for the header badge); "" when none."""
    only_on_cage = context.scene.mirror_pivot_only_on_cage
    axes = set()
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        for mod in applicable_mirrors(obj, only_on_cage)[0]:
            axes.update(AXIS_LETTERS[axis] for axis in range(3) if mod.use_axis[axis])
    return "".join(letter for letter in AXIS_LETTERS if letter in axes)


def is_active(context):
    """The mode is on and the real pivot is still Median Point."""
    return context.scene.mirror_pivot_active and context.tool_settings.transform_pivot_point == CENTER_PIVOT


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class MIRRORPIVOT_OT_enable(bpy.types.Operator):
    bl_idname = "mirror_pivot.enable"
    bl_label = "Median Point with Mirror"
    bl_description = ("Pivot for Scale and Rotate in Edit Mode: the middle of the selection plus its Mirror modifier "
                      "copies, as if the copy were real and selected")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.tool_settings.transform_pivot_point = CENTER_PIVOT
        context.scene.mirror_pivot_active = True
        return {'FINISHED'}


def start_transform(mode, center):
    """Start transform.resize ('RESIZE') or transform.rotate around center (None = the real pivot)."""
    transform = bpy.ops.transform.resize if mode == 'RESIZE' else bpy.ops.transform.rotate
    if center is None:
        return transform('INVOKE_DEFAULT')
    return transform('INVOKE_DEFAULT', center_override=center)


class MIRRORPIVOT_OT_transform(bpy.types.Operator):
    """Scale or Rotate (S / R keys); uses the mirrored centre while Median Point with Mirror is on"""
    bl_idname = "mirror_pivot.transform"
    bl_label = "Scale / Rotate with Mirror Pivot"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(name="Mode", items=[('RESIZE', "Scale", ""), ('ROTATE', "Rotate", "")], default='RESIZE')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        return start_transform(self.mode, self.mirrored_center_or_none(context))

    def mirrored_center_or_none(self, context):
        if not context.scene.mirror_pivot_active:
            return None
        if context.tool_settings.transform_pivot_point != CENTER_PIVOT:
            context.scene.mirror_pivot_active = False   # lazy turn-off: the pivot was changed elsewhere
            return None
        center, _axes, reason = selection_center(context)
        if reason:
            self.report({'INFO'}, reason)
        return center


class MIRRORPIVOT_OT_cursor_to_selected(bpy.types.Operator):
    bl_idname = "mirror_pivot.cursor_to_selected"
    bl_label = "Cursor to Mirrored Selection"
    bl_description = "Put the 3D cursor at the middle of the selection plus its Mirror modifier copies"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        center, _axes, reason = selection_center(context)
        if reason:
            self.report({'INFO'}, reason)
        if center is None:
            return {'CANCELLED'}
        context.scene.cursor.location = center
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# UI hooks (read only)
# ---------------------------------------------------------------------------

class MIRRORPIVOT_OT_set_pivot(bpy.types.Operator):
    bl_idname = "mirror_pivot.set_pivot"
    bl_label = "Set Pivot Point"
    bl_description = "Set the transform pivot point (and turn Median Point with Mirror off)"
    bl_options = {'INTERNAL'}

    pivot: StringProperty(name="Pivot", default=CENTER_PIVOT)

    def execute(self, context):
        context.tool_settings.transform_pivot_point = self.pivot
        context.scene.mirror_pivot_active = False
        return {'FINISHED'}


class MIRRORPIVOT_PT_pivot(bpy.types.Panel):
    """The pivot dropdown in the header: Blender's five pivots (as buttons that also clear our flag) plus ours."""
    bl_label = "Transform Pivot Point"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        layout = self.layout
        tool_settings = context.tool_settings
        layout.label(text="Transform Pivot Point")
        column = layout.column(align=True)
        mirror_active = is_active(context)
        for item in tool_settings.bl_rna.properties["transform_pivot_point"].enum_items:
            is_current = item.identifier == tool_settings.transform_pivot_point and not mirror_active
            button = column.operator(MIRRORPIVOT_OT_set_pivot.bl_idname, text=item.name, icon=item.icon,
                                     depress=is_current)
            button.pivot = item.identifier
        layout.separator()
        layout.operator(MIRRORPIVOT_OT_enable.bl_idname, text="Median Point with Mirror", icon='MOD_MIRROR',
                        depress=mirror_active)
        layout.prop(context.scene, "mirror_pivot_only_on_cage")
        if mirror_active:
            layout.label(text=header_badge_text(context))


def header_badge_text(context):
    """"MIR X" / "MIR XY" while active, "MIR off" when no mirror applies."""
    axes = mirror_axes_label(context)
    return f"MIR {axes}" if axes else "MIR off"


class PivotLayoutProxy:
    """Stands in for the header layout while Blender draws the transform tools. Everything is forwarded to the real
    layout except the pivot dropdown, which becomes a button opening our panel (Blender 5.3 has no popover to extend)."""

    def __init__(self, layout, context):
        self._layout = layout
        self._context = context

    def __getattr__(self, name):
        return getattr(self._layout, name)

    def prop(self, data, property_name, *args, **kwargs):
        if property_name != "transform_pivot_point" or self._context.mode != 'EDIT_MESH':
            return self._layout.prop(data, property_name, *args, **kwargs)
        if not is_active(self._context):
            return self._layout.prop_with_popover(data, property_name, text="", icon_only=True,
                                                  panel=MIRRORPIVOT_PT_pivot.__name__)
        # Active: one compact "[pivot icon] MIR" button (prop_with_popover with text would add "MIR:" + the long enum name)
        pivot_icon = data.bl_rna.properties[property_name].enum_items[getattr(data, property_name)].icon
        return self._layout.popover(MIRRORPIVOT_PT_pivot.__name__, text="MIR", icon=pivot_icon)


_original_xform_template = None


def install_pivot_dropdown():
    global _original_xform_template
    header = bpy.types.VIEW3D_HT_header
    _original_xform_template = header.draw_xform_template

    def draw_xform_template(layout, context):
        _original_xform_template(PivotLayoutProxy(layout, context), context)

    header.draw_xform_template = staticmethod(draw_xform_template)


def restore_pivot_dropdown():
    bpy.types.VIEW3D_HT_header.draw_xform_template = staticmethod(_original_xform_template)


def draw_cursor_item(self, context):
    if context.mode == 'EDIT_MESH':
        self.layout.operator(MIRRORPIVOT_OT_cursor_to_selected.bl_idname)


MENUS = (   # (Blender UI class name, our draw function)
    ("VIEW3D_MT_snap", draw_cursor_item),
    ("VIEW3D_MT_snap_pie", draw_cursor_item),
)
KEYMAP_ITEMS = (('S', 'RESIZE'), ('R', 'ROTATE'))
classes = (MIRRORPIVOT_PT_pivot, MIRRORPIVOT_OT_set_pivot, MIRRORPIVOT_OT_enable, MIRRORPIVOT_OT_transform, MIRRORPIVOT_OT_cursor_to_selected)
_keymap_items = []


def register_keymap():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:   # background mode
        return
    keymap = keyconfig.keymaps.new(name="Mesh", space_type='EMPTY')
    for key, mode in KEYMAP_ITEMS:
        item = keymap.keymap_items.new(MIRRORPIVOT_OT_transform.bl_idname, key, 'PRESS')
        item.properties.mode = mode
        _keymap_items.append((keymap, item))


def unregister_keymap():
    for keymap, item in _keymap_items:
        keymap.keymap_items.remove(item)
    _keymap_items.clear()


def register():
    bpy.types.Scene.mirror_pivot_active = BoolProperty(
        name="Median Point with Mirror", default=False, description="Pivot includes the Mirror modifier copies")
    bpy.types.Scene.mirror_pivot_only_on_cage = BoolProperty(
        name="Only when On Cage", default=False,
        description="Count a Mirror modifier only while its On Cage button is on")
    for cls in classes:
        bpy.utils.register_class(cls)
    append_menus(MENUS)
    install_pivot_dropdown()
    register_keymap()


def unregister():
    restore_pivot_dropdown()
    unregister_keymap()
    remove_menus(MENUS)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mirror_pivot_only_on_cage
    del bpy.types.Scene.mirror_pivot_active
