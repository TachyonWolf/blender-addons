# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/bone_chain.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone chains: weight sums (vertex group = min(1, summed weights of a bone and all its descendants)),
the bone path from a root down a chain, and an along-the-chain gradient group.

Shared by the Digit's Modifiers and Stretchy Limb extensions (an installed extension can't
import its neighbour). This file is the ONE source; sync_shared.py copies it into each extension
folder as bone_chain.py.
"""


def chain_bone_names(rig, bones, excluded=(), exclude_children=True):
    """Names of the bones and all their descendants, without the `excluded` bone names (and, with `exclude_children`,
    without everything below them: leave out the jaw and its teeth when making a head group)."""
    names = set()
    for bone in bones:
        names.add(bone.name)
        names.update(b.name for b in bone.children_recursive)
    left_out = set(excluded)
    if exclude_children:
        for name in excluded:
            bone = rig.data.bones.get(name)
            if bone:
                left_out.update(b.name for b in bone.children_recursive)
    return names - left_out


def rig_for_chain(context):
    """The armature to read: the active armature, or the one deforming the active mesh."""
    ob = context.active_object
    if ob is None:
        return None
    if ob.type == 'ARMATURE':
        return ob
    for m in ob.modifiers:
        if m.type == 'ARMATURE' and m.object:
            return m.object
    return None


def selected_bones(rig):
    """Bones whose pose bone is selected (Blender 5 keeps selection on pose bones)."""
    return [pb.bone for pb in rig.pose.bones if pb.select]


def deformed_meshes(context, rig):
    """Meshes with an Armature modifier on the rig; in Weight Paint just the active mesh."""
    active = context.active_object
    if context.mode == 'PAINT_WEIGHT' and active and active.type == 'MESH':
        return [active]
    return [ob for ob in context.scene.objects
            if ob.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == rig for m in ob.modifiers)]


def write_chain_group(ob, names, group_name):
    """Clear/create group_name on ob; weight = min(1, sum of the weights in the groups named in names).
    Returns (vertices with weight > 0, vertices with weight 1)."""
    group = ob.vertex_groups.get(group_name)
    if group:
        ob.vertex_groups.remove(group)
    group = ob.vertex_groups.new(name=group_name)
    idx = {g.index for g in ob.vertex_groups if g.name in names and g.name != group_name}  # after the remove: indices shift
    touched = full = 0
    for v in ob.data.vertices:
        w = min(1.0, sum(e.weight for e in v.groups if e.group in idx))
        if w > 0:
            group.add([v.index], w, 'REPLACE')
            touched += 1
            full += w >= 1.0
    return touched, full


def chain_path(rig, root, tip=None):
    """Bones from `root` down to `tip` (names; root first). Without a tip: follow the child that
    starts at the bone's tail and points most the same way, while there is one within 60 degrees
    (a tail's segments, not the side fins or flukes)."""
    bones = rig.data.bones
    if tip:
        path = [bones[tip]]
        while path[-1].name != root and path[-1].parent:
            path.append(path[-1].parent)
        return [b.name for b in reversed(path)] if path[-1].name == root else [root]
    path = [bones[root]]
    while True:
        bone = path[-1]
        direction = (bone.tail_local - bone.head_local).normalized()
        best, best_dot = None, 0.5
        for child in bone.children:
            along = child.tail_local - child.head_local
            if (child.head_local - bone.tail_local).length > 1e-4 * max(bone.length, 1e-6) + 1e-5 \
                    or along.length < 1e-9:
                continue
            dot = along.normalized().dot(direction)
            if dot > best_dot:
                best, best_dot = child, dot
        if best is None:
            return [b.name for b in path]
        path.append(best)


def chain_points(rig, names, posed=True):
    """Joints of a bone path: each bone's head, then the last bone's tail; world space (posed)
    or armature space (rest)."""
    if posed:
        pb = rig.pose.bones
        return [rig.matrix_world @ p for p in [pb[n].head for n in names] + [pb[names[-1]].tail]]
    bones = rig.data.bones
    return [bones[n].head_local.copy() for n in names] + [bones[names[-1]].tail_local.copy()]


def along_fraction(points, co):
    """Where `co` sits along the polyline `points`: 0 at the first point .. 1 at the last, by arc
    length of its nearest point (clamped)."""
    lengths = [(b - a).length for a, b in zip(points, points[1:])]
    total = sum(lengths) or 1.0
    best, best_d, walked = 0.0, None, 0.0
    for a, b, seg in zip(points, points[1:], lengths):
        ab = b - a
        t = 0.0 if seg < 1e-12 else max(0.0, min(1.0, (co - a).dot(ab) / (seg * seg)))
        d = (a + ab * t - co).length
        if best_d is None or d < best_d:
            best, best_d = (walked + t * seg) / total, d
        walked += seg
    return best


def write_along_group(ob, rig, names, selection_group, group_name):
    """Clear/create group_name on ob: for vertices in selection_group, where they sit along the
    bone path `names` in the rest pose (0 root .. 1 tip; past the tip 1). Returns the count."""
    group = ob.vertex_groups.get(group_name)
    if group:
        ob.vertex_groups.remove(group)
    group = ob.vertex_groups.new(name=group_name)
    sel = ob.vertex_groups[selection_group].index
    to_rig = rig.matrix_world.inverted() @ ob.matrix_world
    points = chain_points(rig, names, posed=False)
    count = 0
    for v in ob.data.vertices:
        if any(e.group == sel and e.weight > 0 for e in v.groups):
            group.add([v.index], along_fraction(points, to_rig @ v.co), 'REPLACE')
            count += 1
    return count
