# SPDX-License-Identifier: GPL-3.0-or-later
"""Triangle counts and a simple "reduce to about N triangles" for mesh objects (Decimate Collapse), used by the Bake to
Game Asset process through Digit's Assorted Tools. UV seams and vertex group weights survive a collapse. Not the VRChat
per-character passes."""
import bpy

MIN_RATIO = 0.01


def triangle_count(objects):
    """Triangles of the objects' own meshes (no modifiers). Cheap, but a real count: call it on a button, not in draw."""
    total = 0
    for ob in objects:
        if ob.type == 'MESH':
            ob.data.calc_loop_triangles()
            total += len(ob.data.loop_triangles)
    return total


def drop_shape_keys(objects):
    """Decimate refuses meshes with shape keys. Returns how many objects lost theirs."""
    dropped = 0
    for ob in objects:
        if ob.type == 'MESH' and ob.data.shape_keys:
            ob.shape_key_clear()
            dropped += 1
    return dropped


def apply_decimate(context, ob, ratio):
    """Collapse-decimate one object's mesh to `ratio` of its triangles, applied (first in the stack, so any Armature
    modifier after it stays). The mesh data is made single-user first."""
    if ob.data.users > 1:
        ob.data = ob.data.copy()
    modifier = ob.modifiers.new("Reduce", 'DECIMATE')
    modifier.decimate_type = 'COLLAPSE'
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = False
    ob.modifiers.move(len(ob.modifiers) - 1, 0)
    with context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def reduce_triangles(context, objects, target):
    """Reduce the meshes together to about `target` triangles: every mesh gets the same ratio (so a big mesh loses
    more triangles than a small one). Shape keys are dropped first. Returns (triangles before, after, shape key
    objects dropped). Meshes already under the target are left alone."""
    meshes = [ob for ob in objects if ob.type == 'MESH']
    dropped = drop_shape_keys(meshes)
    before = triangle_count(meshes)
    if before > target > 0:
        ratio = max(MIN_RATIO, target / before)
        for ob in meshes:
            apply_decimate(context, ob, ratio)
    return before, triangle_count(meshes), dropped
