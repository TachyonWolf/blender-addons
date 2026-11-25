"""Mirror Transform: one Edit Mesh toolbar tool (after Blender's Transform) whose gizmo (move arrows, rotate dials, scale
boxes) sits on the mirrored centre: the selection plus its Mirror modifier copies, see mirror_pivot.py. Blender's own
gizmos cannot be moved by an add-on. Rotate and Scale use the mirrored centre as center_override.

They ignore the Median Point with Mirror mode and Only when On Cage: any Mirror enabled in viewport and Edit Mode
counts; with none, the centre is the plain median. The gizmo group shows only while this tool is the active one and recomputes the centre in `refresh` (Blender calls it
on redraw / selection change while the tool is active). No handlers, timers or msgbus."""
import os
from dataclasses import dataclass

import bpy
from mathutils import Matrix, Vector

from . import mirror_pivot

AXIS_VECTORS = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
AXIS_COLORS = ((0.9, 0.2, 0.3), (0.5, 0.8, 0.1), (0.2, 0.5, 0.95))
SUPPORTED_ORIENTATIONS = ('GLOBAL', 'LOCAL')
MOVE_ARROW_LENGTH = 1.3
SCALE_ARROW_LENGTH = 0.8
DIAL_SIZE = 1.0
UNIFORM_SIZE = 0.6
VIEW_COLOR = (0.9, 0.9, 0.9)
ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "mirror_transform")   # + .dat


# ---------------------------------------------------------------------------
# Pure helpers (also used by the tests)
# ---------------------------------------------------------------------------

def axis_rotation(axis_index):
    """3x3 matrix whose Z column is the given axis: a dial / arrow drawn along Z then points along that axis."""
    z_axis = AXIS_VECTORS[axis_index]
    x_axis = AXIS_VECTORS[(axis_index + 1) % 3]
    y_axis = z_axis.cross(x_axis)
    return Matrix((x_axis, y_axis, z_axis)).transposed()


def gizmo_matrix(center, orientation, axis_index):
    """4x4 for the gizmo of one axis: at center, axes turned by the 3x3 orientation."""
    return Matrix.Translation(center) @ (orientation @ axis_rotation(axis_index)).to_4x4()


def orientation_type(context):
    """'GLOBAL' or 'LOCAL' from the scene's transform orientation (anything else counts as Global)."""
    slot_type = context.scene.transform_orientation_slots[0].type
    return slot_type if slot_type in SUPPORTED_ORIENTATIONS else 'GLOBAL'


def orientation_matrix(context):
    """3x3 orientation of the gizmo axes, matching orientation_type."""
    active = context.active_object
    if orientation_type(context) == 'LOCAL' and active is not None:
        return active.matrix_world.to_3x3().normalized()
    return Matrix.Identity(3)


def operator_arguments(context, center, axis_index=None):
    """Keyword arguments every gizmo target / drag passes to transform.rotate / transform.resize. axis_index None =
    view axis (rotate) or uniform (scale)."""
    constraint = tuple(index == axis_index for index in range(3))
    return {"center_override": tuple(center), "orient_type": orientation_type(context), "constraint_axis": constraint}


def active_tool_widget(context):
    """Gizmo group idname of the active 3D view tool in the current mode ("" when none)."""
    tool = context.workspace.tools.from_space_view3d_mode(context.mode, create=False)
    return tool.widget if tool is not None else ""


def fill_operator(properties, arguments):
    for name, value in arguments.items():
        setattr(properties, name, value)


# ---------------------------------------------------------------------------
# Gizmo groups
# ---------------------------------------------------------------------------

@dataclass
class GizmoSpec:
    gizmo: object
    axis_index: object          # 0-2, or None for a gizmo that faces the viewer
    extra_arguments: dict       # operator properties on top of operator_arguments
    operator_idname: str = "transform.resize"


class MIRRORPIVOT_GGT_transform(bpy.types.GizmoGroup):
    """Move arrows, rotate dials and scale boxes. An axis gizmo (axis_index 0-2) sits on the centre turned along that
    axis; a view one (axis_index None) sits on the centre and faces the viewer."""
    bl_idname = "MIRRORPIVOT_GGT_transform"
    bl_label = "Mirror Transform Widget"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and active_tool_widget(context) == cls.bl_idname

    def setup(self, context):
        self.specs, self.center = [], None
        for axis_index, letter in enumerate(mirror_pivot.AXIS_LETTERS):
            move = self.add_gizmo('GIZMO_GT_arrow_3d', axis_index, "transform.translate")
            move.length = MOVE_ARROW_LENGTH
            scale = self.add_gizmo('GIZMO_GT_arrow_3d', axis_index, "transform.resize")
            scale.draw_style = 'BOX'
            scale.length = SCALE_ARROW_LENGTH
            dial = self.add_gizmo('GIZMO_GT_dial_3d', axis_index, "transform.rotate", {"orient_axis": letter})
            dial.draw_options = {'CLIP'}
            dial.scale_basis = DIAL_SIZE
        view_dial = self.add_gizmo('GIZMO_GT_dial_3d', None, "transform.rotate",
                                   {"orient_axis": 'Z', "orient_type": 'VIEW'})
        view_dial.scale_basis = DIAL_SIZE * 1.2
        uniform = self.add_gizmo('GIZMO_GT_dial_3d', None, "transform.resize")
        uniform.scale_basis = UNIFORM_SIZE

    def add_gizmo(self, gizmo_type, axis_index, operator_idname, extra_arguments=None):
        gizmo = self.gizmos.new(gizmo_type)
        gizmo.color = gizmo.color_highlight = AXIS_COLORS[axis_index] if axis_index is not None else VIEW_COLOR
        gizmo.alpha = 0.6
        gizmo.alpha_highlight = 1.0
        gizmo.use_draw_modal = True
        gizmo.target_set_operator(operator_idname)
        self.specs.append(GizmoSpec(gizmo, axis_index, extra_arguments or {}, operator_idname))
        return gizmo

    def refresh(self, context):
        """Blender calls this on redraw / selection change while the tool is active: cheap, selected verts only."""
        self.center = mirror_pivot.tool_center(context)
        orientation = orientation_matrix(context)
        for spec in self.specs:
            spec.gizmo.hide = self.center is None
            if self.center is not None and spec.axis_index is not None:
                spec.gizmo.matrix_basis = gizmo_matrix(self.center, orientation, spec.axis_index)

    def draw_prepare(self, context):
        if self.center is None or context.region_data is None:
            return
        facing = context.region_data.view_matrix.inverted().to_3x3().to_4x4()
        for spec in self.specs:
            if spec.axis_index is None:
                spec.gizmo.matrix_basis = Matrix.Translation(self.center) @ facing

    def invoke_prepare(self, context, gizmo):
        """Just before a gizmo runs its operator: put the fresh centre (and axis) into the operator properties."""
        spec = next(spec for spec in self.specs if spec.gizmo == gizmo)
        arguments = operator_arguments(context, self.center, spec.axis_index)
        if spec.operator_idname == "transform.translate":
            del arguments["center_override"]   # moving has no centre
        arguments.update(spec.extra_arguments)
        properties = gizmo.target_set_operator(spec.operator_idname)
        fill_operator(properties, arguments)
        properties.release_confirm = True


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class MIRRORPIVOT_TOOL_transform(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'
    bl_idname = "mirror_pivot.tool"
    bl_label = "Mirror Transform"
    bl_description = ("Move, rotate and scale with the gizmo on the selection plus its Mirror modifier copies "
                      "(rotate and scale pivot there)")
    bl_icon = ICON_PATH
    bl_widget = MIRRORPIVOT_GGT_transform.bl_idname
    bl_keymap = (   # click selects, drag box-selects, like Tweak
        ("view3d.select", {"type": 'LEFTMOUSE', "value": 'CLICK'}, {"properties": [("deselect_all", True)]}),
        ("view3d.select_box", {"type": 'LEFTMOUSE', "value": 'CLICK_DRAG'}, {"properties": [("mode", 'SET')]}),
    )


classes = (MIRRORPIVOT_GGT_transform,)
registered_tools = []


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    try:
        bpy.utils.register_tool(MIRRORPIVOT_TOOL_transform, after={"builtin.transform"}, separator=False, group=False)
    except Exception as error:   # no toolbar in background mode on some builds
        print(f"Mirror Transform: could not register the tool: {error}")
        return
    registered_tools.append(MIRRORPIVOT_TOOL_transform)


def unregister():
    for tool in reversed(registered_tools):
        bpy.utils.unregister_tool(tool)
    registered_tools.clear()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
