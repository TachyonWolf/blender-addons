# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/combine_bones.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Combine Bones: several bones of a rig become one. The main bone stays; the others are removed, their vertex group
weights are added to the main's, their children go to the main, and what pointed at them (constraints, driver
variables, bone-parented objects) points at the main. This file is the ONE source; sync_shared.py copies it into the
add-on as combine_bones.py.

    report = combine_bones(arm, "Spine2", ["Spine3", "Spine4"])
    lines = report_lines(report)

Also the walkers over every constraint and driver variable in the file (`constraint_links`, `driver_targets`), which
Combine Parts uses to point things at the joined rig.
"""
import re

import bpy

try:                                     # inside the add-on package
    from . import span_bones as sb
    from .object_tools import set_mode
except ImportError:                      # script folder copy
    import span_bones as sb
    from object_tools import set_mode

BONE_PATH = re.compile(r'^(?:pose\.)?bones\["([^"]+)"\]')   # an fcurve / driver path on a (pose) bone


# ---------------------------------------------------------------- walking constraints and drivers
def constraint_links(ob):
    """(pose bone or None, link) for everything a constraint of the object or its pose bones points at. A link has
    `.target` and `.subtarget`: the constraint itself, or one entry of an Armature constraint's targets."""
    owners = [(None, c) for c in ob.constraints]
    if ob.pose:
        owners += [(pb, c) for pb in ob.pose.bones for c in pb.constraints]
    for pb, con in owners:
        if hasattr(con, 'target'):
            yield pb, con
        for entry in getattr(con, 'targets', ()):
            yield pb, entry


def animated_ids():
    """Every object, its data and its shape keys once: the places drivers live."""
    seen = set()
    for ob in bpy.data.objects:
        data = ob.data
        for item in (ob, data, getattr(data, 'shape_keys', None)):
            if item is not None and item.as_pointer() not in seen:
                seen.add(item.as_pointer())
                yield item


def drivers(item):
    return list(item.animation_data.drivers) if item.animation_data else []


def driver_targets():
    """(id owning the driver, fcurve, variable target) for every driver variable in the file."""
    for item in animated_ids():
        for fcurve in drivers(item):
            for var in fcurve.driver.variables:
                for target in var.targets:
                    yield item, fcurve, target


# ---------------------------------------------------------------- weights
def merge_weights(ob, main, removed, mode='ADD', remove=True):
    """On one mesh: the groups named in `removed` are added onto `main`'s group (made if missing). mode ADD: summed and
    clamped at 1; MAX: the larger weight wins. The merged groups are deleted when `remove`. Returns the number of
    vertices that gained weight."""
    gone = {g.index: g for g in (ob.vertex_groups.get(n) for n in removed) if g is not None}
    if not gone:
        return 0
    target = ob.vertex_groups.get(main) or ob.vertex_groups.new(name=main)
    moved = 0
    for v in ob.data.vertices:
        incoming = [g.weight for g in v.groups if g.group in gone]
        if incoming and any(w > 0 for w in incoming):
            current = next((g.weight for g in v.groups if g.group == target.index), 0.0)
            merged = max([current] + incoming) if mode == 'MAX' else min(1.0, current + sum(incoming))
            target.add([v.index], merged, 'REPLACE')
            moved += 1
    if remove:
        for group in list(gone.values()):
            ob.vertex_groups.remove(group)
    return moved


def meshes_by_data(arm):
    """The meshes this armature deforms, one object per mesh data (vertex groups belong to the data)."""
    out = {}
    for ob in sb.deformed_meshes(arm):
        out.setdefault(ob.data.name, ob)
    return list(out.values())


# ---------------------------------------------------------------- what points at the removed bones
def retarget_constraints(arm, main, removed):
    """Constraints aimed at a removed bone of `arm` aim at `main`. Returns (retargeted, left): `left` are constraints
    on the main bone itself (they would aim at themselves)."""
    done = left = 0
    for ob in bpy.data.objects:
        for pb, link in constraint_links(ob):
            if link.target != arm or link.subtarget not in removed:
                continue
            if pb is not None and ob == arm and pb.name == main:
                left += 1
            else:
                link.subtarget = main
                done += 1
    return done, left


def retarget_drivers(arm, main, removed):
    """Driver variables aimed at a removed bone of `arm` aim at `main`. Returns (retargeted, left): `left` read a
    property of a removed bone, which the main bone may not have."""
    done = left = 0
    for _item, _fcurve, target in driver_targets():
        if target.id != arm:
            continue
        if target.bone_target in removed:
            target.bone_target = main
            done += 1
        elif (m := BONE_PATH.match(target.data_path)) and m.group(1) in removed:
            left += 1
    return done, left


def remove_own_drivers(arm, removed):
    """Drivers on the removed bones' own properties go with them. Returns how many."""
    count = 0
    for item in (arm, arm.data):
        for fcurve in drivers(item):
            m = BONE_PATH.match(fcurve.data_path)
            if m and m.group(1) in removed:
                item.animation_data.drivers.remove(fcurve)
                count += 1
    return count


def move_bone_children(arm, main, removed):
    """Objects bone-parented to a removed bone are parented to `main`, keeping their world position."""
    children = [ob for ob in bpy.data.objects
                if ob.parent == arm and ob.parent_type == 'BONE' and ob.parent_bone in removed]
    bpy.context.view_layer.update()
    for ob in children:
        world = ob.matrix_world.copy()
        ob.parent_bone = main
        bpy.context.view_layer.update()       # the new parent's matrix, before the world matrix is put back
        ob.matrix_world = world
    return len(children)


# ---------------------------------------------------------------- the hierarchy (Edit Mode)
def survivor(bone, removed):
    """The nearest ancestor of an edit bone that is not removed, else None."""
    parent = bone.parent
    while parent is not None and parent.name in removed:
        parent = parent.parent
    return parent


def fix_hierarchy(edit_bones, main, removed):
    """Children of removed bones go to the main bone, keeping their rest position. The main bone goes to its nearest
    surviving ancestor. A child that is itself an ancestor of the main bone goes to the removed bone's survivor
    instead (else the two would be each other's parent). Removes the bones. Returns the children reparented."""
    keep = edit_bones[main]
    ancestors = set()
    parent = keep.parent
    while parent is not None:
        ancestors.add(parent.name)
        parent = parent.parent
    moves = {}
    for bone in edit_bones:
        if bone.name in removed or bone.parent is None or bone.parent.name not in removed:
            continue
        if bone.name == main:
            moves[bone.name] = survivor(bone, removed)
        else:
            moves[bone.name] = survivor(bone, removed) if bone.name in ancestors else keep
    for name, new_parent in moves.items():
        bone = edit_bones[name]
        bone.use_connect = False
        bone.parent = new_parent
    for name in removed:
        edit_bones.remove(edit_bones[name])
    return len([n for n in moves if n != main])


# ---------------------------------------------------------------- the whole run
def combine_bones(arm, main, removed):
    """Combine the bones named in `removed` into the bone `main` of the armature object `arm` (Object, Pose or Edit Mode;
    the mode is restored). Returns a report dict: removed, meshes (names), moved (vertices), deform_on, reparented,
    constraints, drivers, children (bone-parented objects), own_drivers, left (what could not be pointed at the main)."""
    removed = [n for n in dict.fromkeys(removed) if n != main]
    bones = arm.data.bones
    if main not in bones or any(n not in bones for n in removed):
        raise ValueError("combine_bones: unknown bone name")
    mode = arm.mode
    set_mode(arm, 'OBJECT')
    gone = set(removed)
    report = dict(removed=len(removed), meshes=[], moved=0, deform_on=False)
    for ob in meshes_by_data(arm):
        moved = merge_weights(ob, main, removed)
        if moved:
            report['meshes'].append(ob.name)
            report['moved'] += moved
    if report['moved'] and not bones[main].use_deform:
        bones[main].use_deform = True
        report['deform_on'] = True
    report['children'] = move_bone_children(arm, main, gone)
    report['constraints'], left_constraints = retarget_constraints(arm, main, gone)
    report['drivers'], left_drivers = retarget_drivers(arm, main, gone)
    report['own_drivers'] = remove_own_drivers(arm, gone)
    report['left'] = left_constraints + left_drivers
    set_mode(arm, 'EDIT')
    report['reparented'] = fix_hierarchy(arm.data.edit_bones, main, gone)
    set_mode(arm, mode)
    return report


def report_lines(report):
    """The result as a few short lines (the first is the summary)."""
    lines = [f"{report['removed']} bones removed, {len(report['meshes'])} meshes changed, "
             f"{report['reparented']} children reparented"]
    pointed = [f"{report[key]} {label}" for key, label in (
        ('constraints', "constraints"), ('drivers', "driver variables"), ('children', "bone-parented objects"))
        if report[key]]
    if pointed:
        lines.append("Now on the main bone: " + ", ".join(pointed))
    if report['own_drivers']:
        lines.append(f"{report['own_drivers']} drivers on the removed bones removed")
    if report['deform_on']:
        lines.append("Deform was off on the main bone: turned on, it now carries weights")
    if report['left']:
        lines.append(f"{report['left']} constraints or drivers still point at a removed bone (on the main bone itself, "
                     f"or reading a property it may not have)")
    return lines
