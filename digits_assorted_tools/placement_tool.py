# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement: General, a left-toolbar tool (own group Placement) in Object, Pose, Edit Mesh and Edit Armature.
Blender does the work; this only chains its own operators:

1. Grab: Object Mode = one ray at the click, up the parent tree by the Grab option, select that ONE object (its
   children follow by parenting). Pose Mode = select the clicked bone. Edit modes = the selection.
2. Drop: Live Follow on = Blender's Move (`transform.translate`) with snapping (Place On = Face, Middle of
   Depth = Volume); a click drops it. Live Follow off = nothing follows; the next click casts one ray (two for
   Middle of Depth) and the item jumps there (Snap Selection to Cursor, Offset).
3. Aim (Aim After Place): Object / Pose first turn the Front Axis to face the mouse on the Spin Axis dial, then
   Blender's Rotate around the Spin Axis takes over (its own X / Y / Z keys, click, right-click / Esc).
Nothing runs in Python per mouse move; the scene's snap settings and 3D cursor are put back."""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty

from . import placement_math as pm
from .character_rig import rig_meshes
from .rig_placement import armature_of
from .pose_ops import is_selected
from .view_ray import begin_click, cast_hit, click_kind, end_click, hit_under_mouse  # generated copy

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "placement_general")   # + .dat
TOOL_IDNAME = "digits.placement_general"
TOOL_MODES = ('OBJECT', 'POSE', 'EDIT_MESH', 'EDIT_ARMATURE')
TRANSLATE_IDS = {"TRANSFORM_OT_translate", "transform.translate"}
SNAP_SETTINGS = ("use_snap", "snap_elements", "snap_target", "use_snap_selectable")
SKIP_STEP = 1e-4          # the second ray (Middle of Depth) starts this far past the first hit (m)
CLICK_HELP = "Click where it goes  ·  Esc / Right-click: cancel"
SIGNED_AXES = [(name, name, f"The item's {name} side faces the mouse") for name in ("X", "-X", "Y", "-Y", "Z", "-Z")]


class PlacementSettings(bpy.types.PropertyGroup):
    live_follow: BoolProperty(name="Live Follow", default=True,
                              description="The item follows the mouse (Blender's Move with snapping); "
                                          "off: it jumps to the next click")
    place_mode: EnumProperty(name="Place Mode", default='SURFACE', items=(
        ('SURFACE', "Place On", "Onto the surface under the mouse"),
        ('MIDDLE', "Middle of Depth", "Into the middle of the object under the mouse")))
    set_depth: BoolProperty(name="Set Depth", default=False,
                            description="Middle of Depth: Depth behind the surface instead of the middle")
    depth: FloatProperty(name="Depth", default=0.1, min=0.0, soft_max=2.0, unit='LENGTH',
                         description="How far behind the surface the item goes when Set Depth is on")
    grab: EnumProperty(name="Grab", default='RIG', items=(
        ('RIG', "Parent Rig", "Move the armature the clicked object belongs to"),
        ('NONE', "None", "Move only the clicked object"),
        ('ROOT', "Root Parent", "Move the top of the clicked object's hierarchy")))
    spin_axis: EnumProperty(name="Spin Axis", default='Z',
                            items=[(name, name, f"Aim by turning around world {name}") for name in "XYZ"])
    front_axis: EnumProperty(name="Front Axis", default='-Y', items=SIGNED_AXES)
    aim_after_place: BoolProperty(name="Aim After Place", default=True,
                                  description="After the drop, turn the item around the Spin Axis")


def draw_settings(context, layout, tool):
    settings = context.scene.digit_placement
    layout.prop(settings, "live_follow")
    layout.prop(settings, "place_mode", text="")
    if settings.place_mode == 'MIDDLE':
        layout.prop(settings, "set_depth")
        depth = layout.row()
        depth.active = settings.set_depth
        depth.prop(settings, "depth")
    if context.mode == 'OBJECT':
        layout.prop(settings, "grab")
    layout.prop(settings, "aim_after_place")
    aim = layout.row()
    aim.active = settings.aim_after_place
    aim.prop(settings, "spin_axis")
    aim.prop(settings, "front_axis")


def grab_target(clicked, grab_mode):
    """The ONE object a click on `clicked` moves: itself ('NONE'), the top of its parent chain ('ROOT') or its
    armature ('RIG': Armature modifier or armature parent; none = itself)."""
    if grab_mode == 'ROOT':
        while clicked.parent is not None:
            clicked = clicked.parent
        return clicked
    return (armature_of(clicked) or clicked) if grab_mode == 'RIG' else clicked


def grab(context, event, grab_mode):
    """Select what the click grabs. False: nothing under the mouse / nothing selected."""
    if context.mode == 'OBJECT':
        found = hit_under_mouse(context, event)
        if found is None or found[1] is None:
            return False
        target = grab_target(found[1], grab_mode)
        for ob in context.selected_objects:
            ob.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        return True
    if context.mode == 'POSE':
        region = context.region
        bpy.ops.view3d.select(deselect_all=True, location=(event.mouse_x - region.x, event.mouse_y - region.y))
        return context.active_pose_bone is not None and is_selected(context.active_pose_bone)
    if context.mode == 'EDIT_MESH':
        return context.edit_object.data.total_vert_sel > 0
    return bool(context.selected_editable_bones)


def moving_with(context):
    """Objects that move along with the item (children, and the meshes an armature deforms), so snapping must
    skip them: Digit would snap onto her own body otherwise. Selected objects are skipped by Blender already."""
    if context.mode not in ('OBJECT', 'POSE'):
        return []
    found = set()
    for item in context.selected_objects or [context.active_object]:
        found.update(item.children_recursive)
        if item.type == 'ARMATURE':
            found.update(rig_meshes(item))
    return [ob for ob in found if not ob.select_get() and not ob.hide_select]


def aim_frame(context):
    """(pivot, world 3x3) of the active object / bone in Object / Pose Mode; None in edit modes (Blender's
    pivot setting turns the selection)."""
    context.view_layer.update()
    if context.mode == 'OBJECT':
        matrix = context.active_object.matrix_world
    elif context.mode == 'POSE':
        matrix = context.active_object.matrix_world @ context.active_pose_bone.matrix
    else:
        return None
    return matrix.translation.copy(), matrix.to_3x3().normalized()


def translate_arguments(mode, settings):
    """Blender's Move with snapping for this run only (operator properties win over the scene's snap settings)."""
    return {"snap": True, "snap_elements": pm.snap_elements(settings.place_mode, settings.set_depth),
            "snap_target": 'MEDIAN' if mode.startswith('EDIT') else 'ACTIVE', "use_snap_project": False,
            "snap_align": False, "release_confirm": False}


def last_operator(context):
    operators = context.window_manager.operators
    return operators[-1].as_pointer() if len(operators) else None


class PLACEMENT_OT_general(bpy.types.Operator):
    """Grab one item, drop it with Blender's Move (or a click), then turn it with Blender's Rotate"""
    bl_idname = "placement.general"
    bl_label = "Place"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and context.mode in TOOL_MODES

    def invoke(self, context, event):
        settings = context.scene.digit_placement
        if not grab(context, event, settings.grab):
            if context.mode.startswith('EDIT'):
                self.report({'WARNING'}, "Select something to place first")
            return {'CANCELLED'}
        tool_settings = context.scene.tool_settings
        self.saved_snap = {name: getattr(tool_settings, name) for name in SNAP_SETTINGS}
        self.live = settings.live_follow
        if not self.live:
            return begin_click(context, self, 'CROSSHAIR', CLICK_HELP)
        self.before_move = last_operator(context)
        self.unsnappable = [ob.name for ob in moving_with(context)]
        for name in self.unsnappable:
            bpy.data.objects[name].hide_select = True
        tool_settings.use_snap_selectable = True          # snap only to selectable objects: not to itself
        context.window_manager.modal_handler_add(self)    # first, so Blender's Move sits above it
        bpy.ops.transform.translate('INVOKE_DEFAULT', **translate_arguments(context.mode, settings))
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self.live:
            if any(op.bl_idname in TRANSLATE_IDS for op in context.window.modal_operators):
                return {'PASS_THROUGH'}      # Blender's Move is still running
            self._restore_snap(context)
            if last_operator(context) == self.before_move:
                return {'CANCELLED'}         # Move cancelled
            self._push_depth(context, event)
            return self._aim(context, event)
        kind = click_kind(event)
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind == 'cancel':
            end_click(context)
            return {'CANCELLED'}
        if kind == 'click':
            if not self._jump(context, event):
                return {'RUNNING_MODAL'}
            end_click(context)
            return self._aim(context, event)
        return {'RUNNING_MODAL'}

    def _restore_snap(self, context):
        for name, value in self.saved_snap.items():
            setattr(context.scene.tool_settings, name, value)
        for name in getattr(self, "unsnappable", ()):
            if name in bpy.data.objects:
                bpy.data.objects[name].hide_select = False
        self.unsnappable = []

    def _push_depth(self, context, event):
        """Live Follow + Set Depth: Depth further along the view ray, once."""
        settings = context.scene.digit_placement
        if settings.place_mode == 'MIDDLE' and settings.set_depth:
            found = hit_under_mouse(context, event)
            if found is not None:
                bpy.ops.transform.translate(value=found[3].normalized() * settings.depth, orient_type='GLOBAL')

    def _jump(self, context, event):
        """Live Follow off: one ray (two for Middle of Depth) at the click; the selection jumps there."""
        settings = context.scene.digit_placement
        found = hit_under_mouse(context, event)
        if found is None:
            return False
        first, _ob, origin, direction = found
        second = None
        if first is not None and settings.place_mode == 'MIDDLE' and not settings.set_depth:
            second = cast_hit(context.scene, context.view_layer.depsgraph, first + direction * SKIP_STEP, direction)[0]
        point = pm.click_point(first, second, direction, settings.place_mode, settings.set_depth, settings.depth)
        if point is None:
            self.report({'WARNING'}, "No surface there" if first is None else "No far side there: nothing moved")
            return False
        cursor = context.scene.cursor
        kept = cursor.location.copy()
        cursor.location = point
        bpy.ops.view3d.snap_selected_to_cursor(use_offset=True)
        cursor.location = kept
        return True

    def _aim(self, context, event):
        """Front Axis towards the mouse on the dial (one Rotate by the dial angle), then Blender's Rotate."""
        settings = context.scene.digit_placement
        if not settings.aim_after_place:
            return {'FINISHED'}
        axis = pm.AXES[settings.spin_axis]
        arguments = {"orient_axis": settings.spin_axis, "orient_type": 'GLOBAL',
                     "constraint_axis": tuple(name == settings.spin_axis for name in "XYZ")}
        frame = aim_frame(context)
        found = hit_under_mouse(context, event) if frame is not None else None
        if found is not None:
            pivot, rotation = frame
            arguments["center_override"] = pivot
            on_dial = pm.ray_plane_point(found[2], found[3], pivot, axis)
            angle = pm.spin_angle(rotation @ pm.axis_vector(settings.front_axis), on_dial - pivot, axis) \
                if on_dial is not None else None
            if angle is not None:
                bpy.ops.transform.rotate(value=angle, **arguments)
        bpy.ops.transform.rotate('INVOKE_DEFAULT', release_confirm=False, **arguments)
        return {'FINISHED'}


def tool_class(mode):
    """One WorkSpaceTool per mode, all the same tool."""
    return type(f"PLACEMENT_TOOL_general_{mode.lower()}", (bpy.types.WorkSpaceTool,), {
        "bl_space_type": 'VIEW_3D',
        "bl_context_mode": mode,
        "bl_idname": TOOL_IDNAME,
        "bl_label": "Placement: General",
        "bl_description": "Click an item, click where it goes (snapping), then turn it. Edit modes move the selection",
        "bl_icon": ICON_PATH,
        "bl_keymap": ((PLACEMENT_OT_general.bl_idname, {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),),
        "draw_settings": draw_settings,
    })


TOOLS = tuple(tool_class(mode) for mode in TOOL_MODES)
classes = (PlacementSettings, PLACEMENT_OT_general)
registered_tools = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.digit_placement = PointerProperty(type=PlacementSettings)
    for tool in TOOLS:
        try:
            bpy.utils.register_tool(tool, separator=True, group=True)
        except Exception as error:   # no toolbar in background mode on some builds
            print(f"Placement: could not register the {tool.bl_context_mode} tool: {error}")
            continue
        registered_tools.append(tool)


def unregister():
    for tool in reversed(registered_tools):
        bpy.utils.unregister_tool(tool)
    registered_tools.clear()
    del bpy.types.Scene.digit_placement
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
