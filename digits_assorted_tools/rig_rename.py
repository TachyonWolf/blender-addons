# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/rig_rename.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rename a rig to docs/BONE_NAMES.md: work out the map (rig_names knows the names, this file reads the rig), rename
through Blender's data so weights, constraints and drivers follow, then fix by hand what Blender leaves alone: unused
actions and pose assets, stored text (the `Limb` JSON, the face rig's records), tool settings and modifier fields.
This file is the ONE source; sync_shared.py copies it into each add-on / script folder.

    table, clashes = work_out_map(arm)
    report = rename(arm, table)
"""
import json
import re

import bpy

try:                                     # inside the add-on package
    from . import bone_collections as bc, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import bone_collections as bc
    import rig_names as rn

TOOL_SETTINGS = ('digit_limbs', 'digit_face_rig')             # property groups on the armature object
RECORDS = ('face_rig_built', 'face_rig_eye', 'face_rig_maw')  # JSON on the armature data
POSE_PATH = re.compile(r'pose\.bones\["([^"]+)"\]')


def work_out_map(arm):
    """({old name: new name}, {new name: [old names]}): what a rename would do and what stands in its way. Bones in a
    clash stay out of the map."""
    plan = bc.plan_rig(arm)
    table, clashes = rn.rename_plan({name: plan[name] for name in plan})
    stuck = {old for names in clashes.values() for old in names}
    return {old: new for old, new in table.items() if old not in stuck}, clashes


def rename_bones(arm, table):
    """Rename through bone.name. X-Axis Mirror is off meanwhile (with it on, Blender renames the mirrored bone too, which
    cancels a scripted edit of both sides), and every name goes through a temporary one, so a map may swap names."""
    data, mirror = arm.data, arm.data.use_mirror_x
    data.use_mirror_x = False
    try:
        live = {old: new for old, new in table.items() if old in data.bones}
        for k, old in enumerate(live):
            data.bones[old].name = f'__rename{k}'
        for k, new in enumerate(live.values()):
            data.bones[f'__rename{k}'].name = new
    finally:
        data.use_mirror_x = mirror
    return live


def fix_pose_text(arm, table):
    """Strings on pose bones (the `Limb` JSON) and the id property's default. Returns how many changed."""
    changed = 0
    for pb in arm.pose.bones:
        for key in pb.keys():
            if isinstance(pb[key], str):
                new = rn.replace_names(pb[key], table)
                if new != pb[key]:
                    pb[key] = new
                    pb.id_properties_ui(key).update(default=new)
                    changed += 1
    return changed


def fix_records(arm, table):
    """The face rig's build record and stored configs: whole JSON strings only. Bone names are keys in the build record
    alone; a config's keys are its fields ('head') and guides, which a bone of the same name must not rename."""
    def walk(value, keys):
        if isinstance(value, dict):
            return {(table.get(k, k) if keys else k): walk(v, keys) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, keys) for v in value]
        return table.get(value, value) if isinstance(value, str) else value
    for key in RECORDS:
        if key in arm.data:
            arm.data[key] = json.dumps(walk(json.loads(arm.data[key]), key == RECORDS[0]))


def action_channelbags(action):
    for layer in action.layers:
        for strip in layer.strips:
            yield from strip.channelbags


def fix_actions(arm, table):
    """Blender only fixes the actions in use: the others, and pose assets, by hand. Returns (fcurves fixed, dead ones:
    channels of bones that are in no armature and not in the map)."""
    bones = {b.name for a in bpy.data.armatures for b in a.bones}
    fixed = dead = 0
    for action in bpy.data.actions:
        for bag in action_channelbags(action):
            for group in bag.groups:
                group.name = table.get(group.name, group.name)
            for fc in bag.fcurves:
                m = POSE_PATH.match(fc.data_path)
                if not m or m.group(1) in bones:
                    continue
                if m.group(1) in table:
                    fc.data_path = fc.data_path.replace(f'["{m.group(1)}"]', f'["{table[m.group(1)]}"]', 1)
                    fixed += 1
                else:
                    dead += 1
    return fixed, dead


def string_props(group):
    return [p.identifier for p in group.bl_rna.properties if p.type == 'STRING' and not p.is_readonly]


def fix_group_strings(group, table):
    changed = 0
    for key in string_props(group):
        if getattr(group, key) in table:
            setattr(group, key, table[getattr(group, key)])
            changed += 1
    return changed


def fix_tool_settings(arm, table):
    """Bone fields of the tool cards on the armature (the Limbs card's list too)."""
    changed = 0
    for attr in TOOL_SETTINGS:
        group = getattr(arm, attr, None)
        if group is None:
            continue
        changed += fix_group_strings(group, table)
        for item in getattr(group, 'limbs', []):
            changed += fix_group_strings(item, table)
    return changed


def string_inputs(mod):
    """The string input fields of a Geometry Nodes modifier."""
    sockets = mod.node_group.interface.items_tree if mod.node_group else []
    return [getattr(mod.properties.inputs, s.identifier) for s in sockets
            if s.item_type == 'SOCKET' and s.in_out == 'INPUT' and s.socket_type == 'NodeSocketString']


def fix_modifier_fields(arm, table):
    """Bone names typed into Geometry Nodes modifier fields (Stretchy Limb's Root Bone) of meshes on this rig."""
    changed = 0
    for ob in bpy.data.objects:
        if any(m.type == 'ARMATURE' and m.object == arm for m in ob.modifiers):
            for mod in (m for m in ob.modifiers if m.type == 'NODES'):
                for field in string_inputs(mod):
                    if field.value in table:
                        field.value = table[field.value]
                        changed += 1
    return changed


def leftover_groups(arm, table):
    """{mesh: old names still on its vertex groups}: Blender renames groups on the meshes that use the rig only."""
    out = {}
    for ob in bpy.data.objects:
        if ob.type == 'MESH':
            left = [g.name for g in ob.vertex_groups if g.name in table and g.name not in arm.data.bones]
            if left:
                out[ob.name] = left
    return out


def rename(arm, table):
    """Rename by `table` and fix what Blender doesn't. Returns a report dict."""
    table = rename_bones(arm, table)
    fixed, dead = fix_actions(arm, table)
    fix_records(arm, table)
    return dict(renamed=len(table), text=fix_pose_text(arm, table), fcurves=fixed, dead_fcurves=dead,
                settings=fix_tool_settings(arm, table), fields=fix_modifier_fields(arm, table),
                leftover_groups=leftover_groups(arm, table))


def report_lines(report):
    lines = [f"{report['renamed']} bones renamed, {report['text']} stored texts, {report['fcurves']} action curves, "
             f"{report['settings']} tool settings, {report['fields']} modifier fields fixed"]
    if report['dead_fcurves']:
        lines.append(f"{report['dead_fcurves']} action curves name bones that don't exist (left as they were)")
    lines += [f"{mesh}: vertex groups on old names: {', '.join(names[:4])}" for mesh, names in report['leftover_groups'].items()]
    return lines
