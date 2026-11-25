# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Modifier Helper (Digit's Tools > Convert): turns the selected objects into helper objects for modifiers (Boolean
cutters, deform cages, Geometry Nodes targets): wire in the viewport, never in a render. The logic is
modifier_setup.style_helper (generated copy of Addons/shared_addon/modifier_setup.py).
Add Modifier Helper (Digit's Tools > Object, and the 3D View Add > Mesh menu): adds a primitive at the 3D cursor already
styled by the same style_helper."""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from .modifier_setup import style_helper  # generated copy
from .ui_cards import action_row, enum_label, hints, prop_group, section, status  # generated copy

# Object types with geometry: a rig, camera or light caught in the selection is left alone.
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'LATTICE', 'CURVES', 'POINTCLOUD', 'VOLUME', 'GREASEPENCIL'}


def plan(context):
    """(objects to change, why not): the selected objects that have geometry and aren't linked."""
    objects = [ob for ob in context.selected_objects if ob.type in GEOMETRY_TYPES and not ob.library]
    return objects, "" if objects else "Select the objects to use as helpers"


class DIGITOOLS_OT_make_helper_object(bpy.types.Operator):
    """Turn the selected objects into modifier helpers: wire display, hidden from renders, reflections and shadows.
    Modifiers still read them"""
    bl_idname = "digits_assorted_tools.make_helper_object"
    bl_label = "Make Modifier Helper"
    bl_options = {'REGISTER', 'UNDO'}

    in_front: BoolProperty(name="In Front", default=True, description="Draw the wire over other objects, so a helper "
                                                                      "inside a mesh stays visible")

    @classmethod
    def poll(cls, context):
        why = plan(context)[1]
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        objects = plan(context)[0]
        for ob in objects:
            style_helper(ob, self.in_front)
        self.report({'INFO'}, f"{len(objects)} helper object(s) set up")
        return {'FINISHED'}


# Shape: (id, label, tooltip). `size` is the overall width in metres for every shape.
SHAPES = (('CUBE', "Cube", "A cube"), ('UV_SPHERE', "UV Sphere", "A sphere of rings and segments"),
          ('ICO_SPHERE', "Ico Sphere", "A sphere of triangles"), ('PLANE', "Plane", "A flat square"),
          ('CIRCLE', "Circle", "A flat disc"), ('CYLINDER', "Cylinder", "A cylinder as tall as it is wide"),
          ('CONE', "Cone", "A cone as tall as it is wide"), ('TORUS', "Torus", "A ring"),
          ('MONKEY', "Monkey (Suzanne)", "Blender's test monkey"), ('GRID', "Grid", "A flat grid of squares"))


def add_primitive(shape, size):
    """Add the primitive `shape` of overall width `size` at the 3D cursor (selected and active)."""
    half = size / 2
    ops = bpy.ops.mesh
    if shape == 'CUBE':
        ops.primitive_cube_add(size=size)
    elif shape == 'UV_SPHERE':
        ops.primitive_uv_sphere_add(radius=half)
    elif shape == 'ICO_SPHERE':
        ops.primitive_ico_sphere_add(radius=half)
    elif shape == 'PLANE':
        ops.primitive_plane_add(size=size)
    elif shape == 'CIRCLE':
        ops.primitive_circle_add(radius=half, fill_type='NGON')
    elif shape == 'CYLINDER':
        ops.primitive_cylinder_add(radius=half, depth=size)
    elif shape == 'CONE':
        ops.primitive_cone_add(radius1=half, depth=size)
    elif shape == 'TORUS':
        ops.primitive_torus_add(major_radius=half * 0.75, minor_radius=half * 0.25)
    elif shape == 'MONKEY':
        ops.primitive_monkey_add(size=size / 1.366)  # Suzanne is 1.366 times wider than her size
    else:
        ops.primitive_grid_add(size=size)
    return bpy.context.object


class DIGITOOLS_OT_add_helper_object(bpy.types.Operator):
    """Add a primitive at the 3D cursor already set up as a modifier helper: wire display, hidden from renders.
    Modifiers still read it"""
    bl_idname = "digits_assorted_tools.add_helper_object"
    bl_label = "Add Modifier Helper"
    bl_options = {'REGISTER', 'UNDO'}

    shape: EnumProperty(name="Shape", items=SHAPES, default='CUBE', description="The shape of the helper")
    size: FloatProperty(name="Size", default=1.0, min=0.001, soft_max=100.0, unit='LENGTH',
                        description="Overall width of the helper (a cylinder and cone are as tall as wide)")
    in_front: BoolProperty(name="In Front", default=True, description="Draw the wire over other objects, so a helper "
                                                                      "inside a mesh stays visible")
    helper_name: StringProperty(name="Name", default="Helper", description="Name of the new helper object")

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        ob = add_primitive(self.shape, self.size)
        ob.name = self.helper_name or "Helper"
        ob.data.name = ob.name
        style_helper(ob, self.in_front)
        return {'FINISHED'}


def draw_add_card(layout, context):
    body = layout   # the tool dropdown is the title
    status(body, "Adds a wire helper at the cursor", icon='MESH_CUBE')
    op = action_row(body).operator(DIGITOOLS_OT_add_helper_object.bl_idname, icon='ADD')
    sec = section(body, "digitools_add_helper_shape", "Shape", icon='MESH_CUBE', right=enum_label(op, "shape"))
    if sec:  # drawn from the operator, so Blender remembers them
        prop_group(sec, op, [("shape", None), ("size", None), ("in_front", None), None, ("helper_name", None)])
    hints(body, ["Wire in the viewport, never in a render"] + ([] if context.mode == 'OBJECT' else ["Switch to Object Mode"]), context)


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    objects, why = plan(context)
    status(body, f"{len(objects)} object{'' if len(objects) == 1 else 's'} to set up" if objects else "Select the objects to set up",
           icon='OBJECT_DATA')
    action_row(body).operator(DIGITOOLS_OT_make_helper_object.bl_idname, icon='SHADING_WIRE')
    hints(body, ["Wire in the viewport, never in a render"] + [why], context)


classes = (DIGITOOLS_OT_make_helper_object, DIGITOOLS_OT_add_helper_object)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
