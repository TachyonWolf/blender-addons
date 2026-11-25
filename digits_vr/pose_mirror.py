# SPDX-License-Identifier: GPL-3.0-or-later
"""Pose X-Axis Mirror for a VR grab. The grab writes pose channels itself, so Blender's own transform mirror never runs: this
does the same maths (the twin's basis = the moved basis flipped in X; Relative Mirror keeps the twin's own start offset)."""
import bpy
from mathutils import Matrix

from .context_helper import run_in_view3d
from .transform_math import Channels, Locks, channels_from_basis

FLIP = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))


def flipped(basis):
    return FLIP @ basis @ FLIP


class MirrorTwin:
    """The opposite-named bone of one grabbed bone, from its state at the grab's start."""

    def __init__(self, pose_bone, twin, relative):
        self.name = twin.name
        self.start_channels = Channels.of(twin)
        self.locks = Locks.of(twin, connected=bool(twin.bone.use_connect and twin.parent))
        self.offset = twin.matrix_basis @ flipped(pose_bone.matrix_basis).inverted_safe() if relative else Matrix.Identity(4)

    def apply(self, pose, pose_bone):
        twin = pose.bones.get(self.name)
        if twin is not None:
            basis = self.offset @ flipped(pose_bone.matrix_basis)
            channels_from_basis(basis, self.start_channels, self.locks, use_scale=True).write(twin)


def twin_of(ob, pose_bone):
    """The MirrorTwin of a bone about to be moved, or None (mirror off, no opposite bone)."""
    if not ob.pose.use_mirror_x:
        return None
    twin = ob.pose.bones.get(bpy.utils.flip_name(pose_bone.name))
    if twin is None or twin.name == pose_bone.name:
        return None
    return MirrorTwin(pose_bone, twin, ob.pose.use_mirror_relative)


def mirror_selected(context):
    """Copy the selected bones' pose, paste it flipped onto the other side (Blender's operators). False: no 3D View."""
    def run():
        bpy.ops.pose.copy()
        bpy.ops.pose.paste(flipped=True)
    return run_in_view3d(context, run)


def mirror_bone(context, ob, pose_bone):
    """mirror_selected for one bone; selection and active object stay as they were."""
    layer = context.view_layer
    active, chosen = layer.objects.active, [bone.name for bone in ob.pose.bones if bone.select]
    for bone in ob.pose.bones:
        bone.select = bone == pose_bone
    layer.objects.active = ob
    try:
        return mirror_selected(context)
    finally:
        layer.objects.active = active
        for bone in ob.pose.bones:
            bone.select = bone.name in chosen
