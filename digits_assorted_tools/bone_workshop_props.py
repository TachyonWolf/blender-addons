# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop settings (Scene.digit_bone_workshop). Most bone values are *virtual* properties: `get` reads the
active bone (the card always shows the truth, no stale copy), `set` writes every target (bone_workshop.targets), so
one slider drag changes all of them and the Scene's undo push makes it one undo step. Setters only write plain
values (no mode switch, rename or collection: those are operators).

LIVE_SLIDERS = False switches to the fallback: the card draws the active bone's own properties and a small
copy-to-targets button per row (bone_workshop_ops.DIGITOOLS_OT_bw_copy_setting), from the same VALUES table."""
from collections import namedtuple

import bpy
from bpy.props import BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty, FloatVectorProperty, \
    IntProperty, PointerProperty, StringProperty

from . import bone_workshop as bw, bone_workshop_spec as spec, rig_names as rn
from .save_pose import rotation_values, set_rotation

LIVE_SLIDERS = True

Value = namedtuple('Value', 'prop owner attr')    # owner: 'pose' (PoseBone) or 'bone' (Bone)
VALUES = (
    Value('scale_xyz', 'pose', 'custom_shape_scale_xyz'), Value('offset', 'pose', 'custom_shape_translation'),
    Value('rotation', 'pose', 'custom_shape_rotation_euler'), Value('wire_width', 'pose', 'custom_shape_wire_width'),
    Value('wireframe', 'bone', 'show_wire'), Value('bone_length', 'pose', 'use_custom_shape_bone_size'),
    Value('inherit_rotation', 'bone', 'use_inherit_rotation'), Value('local_location', 'bone', 'use_local_location'),
    Value('hide', 'pose', 'hide'), Value('inherit_scale', 'bone', 'inherit_scale'),
    Value('rotation_mode', 'pose', 'rotation_mode'), Value('bbone_segments', 'bone', 'bbone_segments'),
    Value('lock_location', 'pose', 'lock_location'), Value('lock_rotation', 'pose', 'lock_rotation'),
    Value('lock_scale', 'pose', 'lock_scale'),
)
VALUE_BY_PROP = {v.prop: v for v in VALUES}


def owner_of(pb, value):
    return pb.bone if value.owner == 'bone' else pb


def need_of(value):
    return 'data' if value.owner == 'bone' else 'pose'


def write_value(pb, value, new):
    if value.attr == 'rotation_mode':          # converted, as Blender's own menu does not
        old_mode, old_values = pb.rotation_mode, rotation_values(pb)
        pb.rotation_mode = new
        set_rotation(pb, old_mode, old_values)
        return
    setattr(owner_of(pb, value), value.attr, new)


def enum_items(struct, attr):
    """(id, name, description, number) items of a Blender enum, so a virtual enum's get can return a number."""
    return [(i.identifier, i.name, i.description, k) for k, i in enumerate(struct.bl_rna.properties[attr].enum_items)]


ENUMS = {'inherit_scale': enum_items(bpy.types.Bone, 'inherit_scale'),
         'rotation_mode': enum_items(bpy.types.PoseBone, 'rotation_mode')}


def virtual(prop):
    """(get, set) of a virtual property over the active bone / the targets."""
    value = VALUE_BY_PROP[prop]
    items = ENUMS.get(prop)

    def get(_self):
        pb = bpy.context.active_pose_bone
        if pb is None:
            return DEFAULTS[prop]
        got = getattr(owner_of(pb, value), value.attr)
        if items:
            return next((k for ident, _n, _d, k in items if ident == got), 0)
        return tuple(got) if hasattr(got, "__len__") else got

    def set(_self, new):
        if items:
            new = items[new][0]
        plain = tuple(new) if hasattr(new, "__len__") and not isinstance(new, str) else new
        bw.write_targets(bpy.context, lambda pb: write_value(pb, value, plain), need_of(value))
    return dict(get=get, set=set)


DEFAULTS = dict(scale_xyz=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0), wire_width=1.0,
                wireframe=False, bone_length=True, inherit_rotation=True, local_location=True, hide=False,
                inherit_scale=0, rotation_mode=0, bbone_segments=1, lock_location=(False,) * 3,
                lock_rotation=(False,) * 3, lock_scale=(False,) * 3, scale=1.0)


def uniform_get(_self):
    pb = bpy.context.active_pose_bone
    return pb.custom_shape_scale_xyz[0] if pb else 1.0


def uniform_set(_self, new):
    bw.write_targets(bpy.context, lambda pb: setattr(pb, 'custom_shape_scale_xyz', (new, new, new)))


def follow_get(_self):
    pb = bpy.context.active_pose_bone
    return pb.custom_shape_transform.name if pb and pb.custom_shape_transform else ""


def follow_set(_self, name):
    """Every target's shape drawn at bone `name` (a mirror bone: at the other side's bone)."""
    found = bw.targets(bpy.context)
    bones, _why = found.usable()
    for pb in bones:
        bone_name = rn.flip(name) if found.source_of(pb) is not None and name else name
        pb.custom_shape_transform = pb.id_data.pose.bones.get(bone_name) if bone_name else None
    bw.refresh({pb.id_data for pb in bones})


def follow_search(_self, context, text):
    pb = context.active_pose_bone
    return [b.name for b in (pb.id_data.pose.bones if pb else []) if text.lower() in b.name.lower() and b != pb]


def shape_option(key):
    """(get, set) of a shape option (Sides, Star ...): read from the active bone's widget name, set = that widget
    with the new value on every target of the same shape kind."""
    def get(self):
        pb = bpy.context.active_pose_bone
        if pb is None:
            return spec.SHAPE_DEFAULTS[key]
        return bw.shape_options(pb, self)[1][key]

    def set(_self, new):
        bw.reshape(bpy.context, {key: new})
    return dict(get=get, set=set)


TARGETS = (('ACTIVE', "Active Only", "Change only the active bone (the one you clicked last)"),
           ('SELECTED', "All Selected", "Change every selected bone"))
WHERE = (('POSE', "Pose", "The colour shows in Pose Mode only (the pose bone's colour)"),
         ('EDIT', "Edit", "The bone's own colour (Edit Mode); Pose Mode keeps the colour it showed"),
         ('BOTH', "Both", "One colour in Pose and Edit Mode"))


class DIGITOOLS_PG_bone_workshop(bpy.types.PropertyGroup):
    target: EnumProperty(name="Change", items=TARGETS, default='SELECTED', description="Which bones the buttons change")
    mirror: BoolProperty(name="Also Change the Mirror Side", default=True,
                         description="Also change the bone on the other side (.L and .R), if the rig has it")
    show_hints: BoolProperty(name="Hints", default=True, description="Show the short help lines under each part")
    uniform: BoolProperty(name="Uniform", default=True, description="One scale for X, Y and Z. Off: three values")
    colour_where: EnumProperty(name="Show In", items=WHERE, default='BOTH', description="Where a picked colour shows")
    use_mesh: PointerProperty(name="Mesh", type=bpy.types.Object, poll=lambda _s, ob: ob.type == 'MESH',
                              description="A mesh object to use as the bone's shape")
    picked: StringProperty(name="Picked Collection", description="The collection row you clicked last")
    editing_shape: StringProperty(description="The widget copy being edited (Edit Shape)")
    editing_rig: StringProperty(description="The rig to go back to after Edit Shape")
    preset_name: StringProperty(name="Name", default="My Preset", description="The name of the new preset")
    new_collection: StringProperty(name="Name", default="New Collection", description="The new collection's name")
    new_parent: StringProperty(name="Inside", description="The collection the new one goes in (empty: top level)")
    # shape options: what the active bone's shape has; the last used ones for the next tile click
    sides: IntProperty(name="Sides", min=3, max=32, description="How many sides (or star points)", **shape_option('sides'))
    flat: BoolProperty(name="Flat Side", description="Start with a flat side at the top (off: a point)", **shape_option('flat'))
    star: BoolProperty(name="Star", description="Turn the sides into points", **shape_option('star'))
    inner: FloatProperty(name="Inner Radius", min=0.05, max=0.95, step=5, subtype='FACTOR',
                         description="How deep the star points are: small = sharp points", **shape_option('inner'))
    teeth: IntProperty(name="Teeth", min=4, max=48, description="How many teeth the gear has", **shape_option('teeth'))
    depth: FloatProperty(name="Tooth Depth", min=0.05, max=0.6, step=5, subtype='FACTOR',
                         description="How long the teeth are", **shape_option('depth'))
    tooth_width: FloatProperty(name="Tooth Width", min=0.1, max=0.9, step=5, subtype='FACTOR',
                               description="How wide each tooth is", **shape_option('tooth_width'))
    hole: BoolProperty(name="Centre Hole", description="A small circle in the middle of the gear", **shape_option('hole'))
    thickness: FloatProperty(name="Thickness", min=0.05, max=1.0, step=5, subtype='FACTOR',
                             description="How wide the capsule is, as a share of the bone's length", **shape_option('thickness'))
    last_sides: IntProperty(default=6, min=3, max=32)
    last_flat: BoolProperty(default=False)
    last_star: BoolProperty(default=False)
    last_inner: FloatProperty(default=0.5)
    last_teeth: IntProperty(default=10, min=4, max=48)
    last_depth: FloatProperty(default=0.25)
    last_tooth_width: FloatProperty(default=0.5)
    last_hole: BoolProperty(default=True)
    last_thickness: FloatProperty(default=0.3)
    # Constraint Setups (bone_setups): the chosen setup and every setup's options
    setup: StringProperty(name="Setup", default="ik", description="The constraint setup the Setups part shows")
    ik_new: EnumProperty(name="IK Bone", items=(('NEW', "Add New", "Make a new IK- control bone"),
                                                ('EXISTING', "Use Existing", "Use a bone the rig has as the IK control")),
                         default='NEW', description="Make the IK control, or use one you have")
    ik_bone: StringProperty(name="IK Bone", description="The bone to use as the IK control", search=lambda _s, c, t: [
        b.name for b in (c.active_object.pose.bones if c.active_object and c.active_object.pose else []) if t.lower() in b.name.lower()])
    ik_place: EnumProperty(name="Place It", items=(
        ('INLINE', "Inline", "The IK bone lies along the hand; the hand turns with it (Copy Rotation). What the Full "
                             "Character Rig builds"),
        ('END', "At End", "A small IK bone at the tip of the chain; the hand keeps its own turn")),
        default='INLINE', description="Where the new IK bone goes")
    limb_parent_switch: BoolProperty(name="Parent Switch", default=True,
                                     description="The IK control can follow Root, Pelvis, Chest or Head (IK_Parent slider)")
    stretchy: BoolProperty(name="Stretchy", default=False, description="The limb stretches when the control is out of "
                                                                         "reach (IK_Stretch slider). Needs a Root bone")
    pole_line: BoolProperty(name="Pole Line", default=True, description="A line from the elbow or knee to its pole, "
                                                                         "shown in IK, so you see where it points")
    twist_share: FloatProperty(name="Share", default=0.33, min=0.0, max=1.0, subtype='FACTOR',
                               description="How much of the hand's roll the forearm takes")
    curl_angle: FloatProperty(name="Curl at Fist", default=-1.151917, min=-3.14159, max=0.0, subtype='ANGLE',
                              description="How far each finger base turns in a full fist (later segments follow it)")
    thumb: EnumProperty(name="Thumb", items=(('CURLS', "Curls", "The thumb aims across the palm and curls in"),
                                             ('SEPARATE', "Separate", "The thumb stays out of the fist")),
                        default='CURLS', description="What the thumb does in a fist")
    fan: BoolProperty(name="Fan on Z", default=True, description="Turning the Palm on Z spreads the fingers")
    roll_break: FloatProperty(name="Roll Break", default=0.610865, min=0.0, max=1.5, subtype='ANGLE',
                              description="How far the foot rolls on the ball before it rolls on the toe tip")
    foot_bank: BoolProperty(name="Foot Bank", default=True, description="Also FootBank and HeelSwivel sliders (rock "
                                                                         "the foot onto its edge, turn it on its heel)")
    curl_follow: FloatProperty(name="Follow", default=1.0, min=0.0, max=1.0, subtype='FACTOR',
                          description="How much the second bone follows the first one's turn")
    fade: FloatProperty(name="Fade per Bone", default=0.1, min=0.0, max=0.5, subtype='FACTOR',
                        description="Each next bone follows this much less")
    curl_axes: BoolVectorProperty(name="Axes", size=3, default=(True, False, True), subtype='XYZ',
                                  description="Which turns the chain copies (X and Z bend it, Y twists it)")
    volume: EnumProperty(name="Volume", items=[(i.identifier, i.name, i.description) for i in
                                               bpy.types.StretchToConstraint.bl_rna.properties['volume'].enum_items],
                         default='VOLUME_XZX', description="Which sides get thinner as the bone stretches")
    aim_slider: BoolProperty(name="Aim Slider", default=True, description="An Aim slider on the target turns the aim "
                                                                           "on and off")
    # virtual bone values (see VALUES)
    scale: FloatProperty(name="Scale", min=0.0, soft_max=10.0, step=10, get=uniform_get, set=uniform_set,
                         description="How big the shape is drawn (times the bone's length when Scale to Bone Length is on)")
    scale_xyz: FloatVectorProperty(name="Scale", size=3, min=0.0, soft_max=10.0, step=10, **virtual('scale_xyz'),
                                   description="The shape's size on X, Y and Z")
    offset: FloatVectorProperty(name="Offset", size=3, subtype='TRANSLATION', unit='LENGTH', **virtual('offset'),
                                description="Move the shape away from the bone without moving the bone")
    rotation: FloatVectorProperty(name="Rotation", size=3, subtype='EULER', **virtual('rotation'),
                                  description="Turn the shape without turning the bone")
    wire_width: FloatProperty(name="Wire Width", min=1.0, max=16.0, **virtual('wire_width'),
                              description="How thick the shape's lines are drawn")
    wireframe: BoolProperty(name="Wireframe", **virtual('wireframe'),
                            description="Draw the shape as lines only, even if the mesh has faces")
    bone_length: BoolProperty(name="Scale to Bone Length", **virtual('bone_length'),
                              description="The shape grows with the bone's length. Off: Scale is in metres")
    follow: StringProperty(name="Shape Follows", get=follow_get, set=follow_set, search=follow_search,
                           description="Draw the shape at another bone (empty: at this bone). Handy for IK controls")
    inherit_rotation: BoolProperty(name="Inherit Rotation", **virtual('inherit_rotation'),
                                   description="The bone turns when its parent turns")
    local_location: BoolProperty(name="Local Location", **virtual('local_location'),
                                 description="Moving the bone uses its own axes. Off: the parent's axes")
    hide: BoolProperty(name="Hide", **virtual('hide'), description="Hide the bone in Pose Mode (Alt+H shows it again)")
    inherit_scale: EnumProperty(name="Inherit Scale", items=ENUMS['inherit_scale'], **virtual('inherit_scale'),
                                description="How the bone takes its parent's scale. Full is the usual one")
    rotation_mode: EnumProperty(name="Rotation Mode", items=ENUMS['rotation_mode'], **virtual('rotation_mode'),
                                description="How the bone's turn is stored. Quaternion never locks up; XYZ Euler is "
                                            "easier to read. The current turn is kept when you change it")
    bbone_segments: IntProperty(name="B-Bone Segments", min=1, max=32, **virtual('bbone_segments'),
                                description="More than 1 makes a bendy bone: it curves smoothly between its ends")
    lock_location: BoolVectorProperty(name="Lock Location", size=3, **virtual('lock_location'),
                                      description="Stop the bone from moving on this axis")
    lock_rotation: BoolVectorProperty(name="Lock Rotation", size=3, **virtual('lock_rotation'),
                                      description="Stop the bone from turning on this axis")
    lock_scale: BoolVectorProperty(name="Lock Scale", size=3, **virtual('lock_scale'),
                                   description="Stop the bone from scaling on this axis")


def settings_of(context):
    return context.scene.digit_bone_workshop


def register():
    bpy.utils.register_class(DIGITOOLS_PG_bone_workshop)
    bpy.types.Scene.digit_bone_workshop = PointerProperty(type=DIGITOOLS_PG_bone_workshop)


def unregister():
    del bpy.types.Scene.digit_bone_workshop
    bpy.utils.unregister_class(DIGITOOLS_PG_bone_workshop)
