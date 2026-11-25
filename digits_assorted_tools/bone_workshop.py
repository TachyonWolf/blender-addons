# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop logic (no UI): which bones a click changes (targets + their mirror bones), and the changes: shape,
size & placement, colour, collections, settings, role, copying a look, mirroring. Everything here runs from a
button or a property set; nothing runs in the background.

Rule: property setters (bone_workshop_props) only write plain bone values through `write_targets`. Anything
structural (mode switches, renames, new objects, collections) is an operator."""
import json
import math
import os
import statistics

import bpy
from mathutils import Euler, Matrix, Vector

from . import bone_collections as bc, body_rig as br, face_rig_core as fr, limb_rig as lr, rig_names as rn, rig_rename, \
    scene_checks as sc, widget_meshes as wm  # generated copies
from . import bone_workshop_spec as spec
from .pose_ops import set_selected
from .save_pose import set_rotation, rotation_values


# ---------------------------------------------------------------- what can be changed
def why_not(rig, need='pose'):
    """Why the rig can't take this kind of change, or "". need: 'pose' (pose bone values), 'data' (Bone values,
    colours, collections) or 'edit' (Edit Mode: new bones, Connected)."""
    if rig.library:
        return spec.LINKED
    if need == 'edit' and (rig.override_library or rig.data.override_library or rig.data.library):
        return spec.OVERRIDE_EDIT
    if need == 'data' and (rig.data.library or rig.data.override_library):
        return spec.OVERRIDE_DATA
    return ""


class Targets:
    """The bones a click changes: the active bone or every selected one (several armatures in Pose Mode too), plus
    their mirror bones when `mirror`. `missing` = bones with a side whose mirror bone the rig lacks."""

    def __init__(self, context, all_selected=True, mirror=True):
        active = context.active_pose_bone
        chosen = list(context.selected_pose_bones or []) if all_selected else []
        if active is not None and active not in chosen:
            chosen.insert(0, active)
        seen, self.bones, self.missing, self.mirrors = set(), [], [], {}
        for pb in chosen:
            self._add(pb, seen)
        if mirror:
            for pb in list(self.bones):
                other = mirror_of(pb)
                if other is None:
                    if rn.has_side(pb.name):
                        self.missing.append(pb.name)
                    continue
                if self._add(other, seen):
                    self.mirrors[(other.id_data.name, other.name)] = pb
        self.active = active

    def _add(self, pb, seen):
        key = (pb.id_data.name, pb.name)
        if key in seen:
            return False
        seen.add(key)
        self.bones.append(pb)
        return True

    @property
    def rigs(self):
        return list(dict.fromkeys(pb.id_data for pb in self.bones))

    def source_of(self, pb):
        """The bone a mirror bone was added for (None for a chosen bone)."""
        return self.mirrors.get((pb.id_data.name, pb.name))

    def usable(self, need='pose'):
        """(bones whose rig takes the change, reasons for the others)."""
        reasons = {rig.name: why_not(rig, need) for rig in self.rigs}
        ok = [pb for pb in self.bones if not reasons[pb.id_data.name]]
        return ok, list(dict.fromkeys(r for r in reasons.values() if r))

    def summary(self):
        """"12 bones on 2 rigs · 3 without a mirror bone"."""
        rigs = len(self.rigs)
        text = f"{len(self.bones)} bone{'s' if len(self.bones) != 1 else ''}"
        if rigs > 1:
            text += f" on {rigs} rigs"
        if self.missing:
            text += f" · {len(self.missing)} without a mirror bone"
        return text


def mirror_of(pb):
    """The pose bone on the other side (same rig), or None for a middle bone or a missing one."""
    other = rn.flip(pb.name)
    return None if other == pb.name else pb.id_data.pose.bones.get(other)


def targets(context):
    settings = context.scene.digit_bone_workshop
    return Targets(context, settings.target == 'SELECTED', settings.mirror)


def refresh(rigs):
    """Viewport update after a write from a property setter (they send no depsgraph update of their own)."""
    for rig in rigs:
        rig.update_tag()
    screen = getattr(bpy.context, "screen", None)
    for area in (screen.areas if screen else []):
        if area.type in ('VIEW_3D', 'PROPERTIES'):
            area.tag_redraw()


def write_targets(context, write, need='pose'):
    """write(pose bone) on every usable target; returns the count. The one path property setters write through."""
    bones, _why = targets(context).usable(need)
    for pb in bones:
        write(pb)
    refresh({pb.id_data for pb in bones})
    return len(bones)


def report_line(done, what, found):
    """"Ring on 12 bones · 3 without a mirror bone · 1 rig skipped: <why>"."""
    text = f"{what} on {done} bone{'s' if done != 1 else ''}"
    if found.missing:
        text += f" · {len(found.missing)} without a mirror bone"
    return text


# ---------------------------------------------------------------- shapes
def widget_name(pb):
    shape = pb.custom_shape
    return shape.name if shape else ""


def drop_if_unused(ob):
    """Remove a made-from-numbers widget no bone uses any more (a slider drag passes many values: only the last
    stays). Linked, hand-made and other widgets are kept."""
    if ob is None or ob.library or not wm.is_parametric(ob.name) or ob.users_collection:
        return False
    if ob.users > (1 if ob.use_fake_user else 0):
        return False
    mesh = ob.data
    bpy.data.objects.remove(ob)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    return True


def set_shape(bones, widget):
    """Give `bones` the shared widget `widget` (built when missing; None clears). Old made-from-numbers widgets left
    unused are removed. Returns the count."""
    shape = fr.ensure_widget(widget) if widget else None
    old = {pb.custom_shape for pb in bones if pb.custom_shape is not None and pb.custom_shape != shape}
    for pb in bones:
        pb.custom_shape = shape
    for ob in old:
        drop_if_unused(ob)
    return len(bones)


def shape_options(pb, settings):
    """(tile id, shape options) of the bone's shape; options not in its name come from the last used ones."""
    tile, options = spec.options_of(widget_name(pb))
    return tile, dict(last_options(settings), **options)


def last_options(settings):
    return {key: getattr(settings, f"last_{key}") for key in spec.SHAPE_DEFAULTS}


def reshape(context, changes):
    """A shape option changed (Sides, Star ...): each target of the same shape kind as the active bone gets the widget
    with that option; new values are remembered for the next tile click."""
    settings = context.scene.digit_bone_workshop
    active = context.active_pose_bone
    if active is None:
        return 0
    tile, options = shape_options(active, settings)
    if tile not in ('ngon', 'gear', 'capsule'):
        return 0
    options.update(changes)
    for key, value in changes.items():
        setattr(settings, f"last_{key}", value)
    bones, _why = targets(context).usable()
    same = [pb for pb in bones if spec.options_of(widget_name(pb))[0] == tile]
    done = set_shape(same, spec.widget_of(tile, options))
    refresh({pb.id_data for pb in same})
    return done


def edit_shape_matrix(pb):
    """World matrix that puts a widget copy where Blender draws the bone's custom shape."""
    rig = pb.id_data
    base = pb.custom_shape_transform or pb
    scale = Vector(pb.custom_shape_scale_xyz) * (pb.bone.length if pb.use_custom_shape_bone_size else 1.0)
    local = Matrix.LocRotScale(Vector(pb.custom_shape_translation), Euler(pb.custom_shape_rotation_euler), scale)
    return rig.matrix_world @ base.matrix @ local


def own_copy(pb):
    """A single-user copy of the bone's widget (WGT-Ring -> WGT-Ring.Forearm.L) for this bone only."""
    shape = pb.custom_shape
    copy = shape.copy()
    copy.data = shape.data.copy()
    copy.name = copy.data.name = f"{shape.name}.{pb.name}"
    copy.use_fake_user = True
    return copy


# ---------------------------------------------------------------- size & placement
def fit_to_mesh(bones, rays=8):
    """Each bone's shape sized to the mesh around its middle (median of `rays` casts across the bone, in its X/Z
    plane, world space, so the rig's object scale counts). Returns (fitted, missed)."""
    fitted, missed, probes = 0, 0, {}
    for pb in bones:
        rig = pb.id_data
        if rig.name not in probes:
            meshes = sc.rig_meshes(rig, bpy.context.scene.objects)
            probes[rig.name] = br.Probe.from_objects(meshes) if meshes else None
        probe = probes[rig.name]
        world = rig.matrix_world @ pb.matrix
        mid = world @ Vector((0, pb.length / 2, 0))
        axis_x, axis_z = (world.to_3x3() @ Vector(v) for v in ((1, 0, 0), (0, 0, 1)))
        unit = axis_x.length or 1.0
        hits = []
        for k in range(rays):
            angle = 2 * math.pi * k / rays
            way = axis_x.normalized() * math.cos(angle) + axis_z.normalized() * math.sin(angle)
            far = probe.exit_distance(mid, way.normalized(), 10.0 * max(pb.length, 0.01) * unit) if probe else None
            if far:
                hits.append(far)
        if len(hits) < rays // 2:
            missed += 1
            continue
        radius = statistics.median(hits) * 1.15 / unit
        if pb.use_custom_shape_bone_size:
            radius /= max(pb.bone.length, 1e-6)
        pb.custom_shape_scale_xyz = (radius, radius, radius)
        fitted += 1
    return fitted, missed


PLACEMENT = ('custom_shape_scale_xyz', 'custom_shape_translation', 'custom_shape_rotation_euler',
             'custom_shape_wire_width', 'use_custom_shape_bone_size')
RESET = dict(custom_shape_scale_xyz=(1.0, 1.0, 1.0), custom_shape_translation=(0.0, 0.0, 0.0),
             custom_shape_rotation_euler=(0.0, 0.0, 0.0), custom_shape_wire_width=1.0, custom_shape_transform=None)


def copy_placement(source, pb):
    for name in PLACEMENT:
        setattr(pb, name, getattr(source, name))
    follow = source.custom_shape_transform
    pb.custom_shape_transform = None if follow is None else pb.id_data.pose.bones.get(
        rn.flip(follow.name) if is_mirror(source, pb) else follow.name)


def reset_placement(pb):
    for name, value in RESET.items():
        setattr(pb, name, value)


def is_mirror(source, pb):
    return source.id_data == pb.id_data and rn.flip(source.name) == pb.name and source.name != pb.name


# ---------------------------------------------------------------- colour
def set_colour(pb, palette, where='BOTH', custom=None):
    """Bone colour shown in Pose Mode (pose bone), Edit (the bone's own: Pose Mode keeps what it showed) or Both.
    `custom` = a BoneColor to copy for a CUSTOM palette."""
    bone = pb.bone
    if where in ('EDIT', 'BOTH'):
        shown = shown_colour(pb)
        bone.color.palette = palette
        if palette == 'CUSTOM' and custom is not None:
            copy_custom(custom, bone.color)
        if where == 'EDIT':
            pb.color.palette = shown[0]
            if shown[0] == 'CUSTOM':
                copy_custom(shown[1], pb.color)
        else:
            pb.color.palette = 'DEFAULT'
    else:
        pb.color.palette = palette
        if palette == 'CUSTOM' and custom is not None:
            copy_custom(custom, pb.color)


def shown_colour(pb):
    """(palette, BoneColor) shown in Pose Mode: the pose bone's unless it is Default."""
    return (pb.color.palette, pb.color) if pb.color.palette != 'DEFAULT' else (pb.bone.color.palette, pb.bone.color)


def copy_custom(source, target):
    for name in ('normal', 'select', 'active'):
        setattr(target.custom, name, getattr(source.custom, name))
    target.custom.show_colored_constraints = source.custom.show_colored_constraints


def copy_colour(source, pb):
    for src, dst in ((source.bone.color, pb.bone.color), (source.color, pb.color)):
        dst.palette = src.palette
        if src.palette == 'CUSTOM':
            copy_custom(src, dst)


def home_of(pb):
    """The bone's home: its deepest collection outside Rigging (else its deepest one), or None."""
    colls = list(pb.bone.collections)
    plain = [c for c in colls if not bc.is_rigging(c)] or colls
    return max(plain, key=depth).name if plain else None


def depth(coll):
    level = 0
    while coll.parent is not None:
        coll, level = coll.parent, level + 1
    return level


# ---------------------------------------------------------------- collections
def mirrored_home(rig, home, source, pb):
    """A home with a side word, for a mirror bone: the other side's collection when the rig has it (or it is a LAYOUT
    one still to be made)."""
    if source is None:
        return home
    other = rn.flip(home)
    return other if other in rig.data.collections_all or other in bc.PARENT else home


def is_parent(coll):
    return len(coll.children) > 0


def can_hold(rig, name):
    """Why bones can't go in collection `name` of the rig, or ""."""
    coll = rig.data.collections_all.get(name)
    if coll is None:
        return "" if name in bc.PARENT and name not in {p for p, _n, _c in bc.LAYOUT if p} else f"No collection {name}"
    if is_parent(coll):
        return f"{name} holds other collections: bones go in the deepest one"
    if not coll.is_editable:
        return f"{name} comes from a library"
    return ""


def move_home(found, home):
    """Every target into `home` (and its deform collection when it deforms). Returns (done, skipped lines)."""
    bones, why = found.usable('data')
    done = 0
    for pb in bones:
        rig = pb.id_data
        name = mirrored_home(rig, home, found.source_of(pb), pb)
        reason = can_hold(rig, name)
        if reason:
            why.append(reason)
            continue
        bc.move_to(rig, pb.name, name, pb.bone.use_deform, keep_driven=True)
        done += 1
    return done, list(dict.fromkeys(why))


def also_add(found, name, add=True):
    bones, why = found.usable('data')
    done = 0
    for pb in bones:
        rig = pb.id_data
        coll_name = mirrored_home(rig, name, found.source_of(pb), pb)
        coll = rig.data.collections_all.get(coll_name)
        if coll is None or not coll.is_editable or (add and is_parent(coll)):
            continue
        (coll.assign if add else coll.unassign)(pb.bone)
        done += 1
    return done, why


def auto_sort(bones):
    """The bones sorted into their standard homes by name (bone_collections.plan_rig, part rigs by their region),
    the FK limb collections updated as Sort Bone Collections does. Colours are left alone. Returns the count."""
    for rig in {pb.id_data for pb in bones}:
        plan = bc.plan_rig(rig)
        extra = bc.extra_adjustment(rig, plan)
        for pb in (b for b in bones if b.id_data == rig):
            home, deform = plan[pb.name]
            bc.move_to(rig, pb.name, home, deform)
            if pb.name in extra:
                bc.ensure_home(rig, "Adjustment").assign(pb.bone)
        bc.place_fk(rig)
    return len(bones)


def set_deform(pb, on):
    """Deform on adds the Body / Face Deform collection, off takes the bone out of the deform collections. A bone in
    no collection yet gets none (the hidden deform collection would hide it): returns False then."""
    pb.bone.use_deform = on
    rig = pb.id_data
    if on:
        if not any(not bc.is_rigging(c) for c in pb.bone.collections):
            return False
        bc.ensure_deform(rig, pb.name, home_of(pb)).assign(pb.bone)
    else:
        for coll in list(pb.bone.collections):
            if coll.name.lower() in bc.DEFORM_SETS:
                coll.unassign(pb.bone)
    return True


# ---------------------------------------------------------------- presets
def presets_path():
    """The saved presets file in the extension's user folder (every .blend sees them)."""
    try:
        folder = bpy.utils.extension_path_user(__package__, create=True)
    except (ValueError, AttributeError):   # loaded as a plain add-on (tests)
        folder = bpy.utils.user_resource('CONFIG', path="digits_assorted_tools", create=True)
    return os.path.join(folder, "bone_presets.json")


def saved_presets(path=None):
    try:
        with open(path or presets_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def store_presets(presets, path=None):
    with open(path or presets_path(), "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=1, sort_keys=True)


def look_of(pb):
    """A preset made from a bone: its widget, scale and colour."""
    palette, _c = shown_colour(pb)
    return dict(widget=widget_name(pb), scale=pb.custom_shape_scale_xyz[0], colour=palette if palette != 'CUSTOM' else 'DEFAULT')


def preset_look(preset_id, saved=None):
    """(widget, scale, colour) of a built-in or saved preset, or None."""
    if preset_id in spec.PRESET_BY_ID:
        p = spec.PRESET_BY_ID[preset_id]
        return spec.widget_of(*p.shape), p.scale, p.colour
    entry = (saved if saved is not None else saved_presets()).get(preset_id)
    return (entry['widget'], entry['scale'], entry['colour']) if entry else None


def matches(pb, look):
    widget, scale, colour = look
    return (widget_name(pb) == widget and abs(pb.custom_shape_scale_xyz[0] - scale) < 1e-3
            and shown_colour(pb)[0] == colour)


def apply_preset(found, look, where='BOTH', sort=True):
    """Shape, size and colour of a preset on the targets; built-in presets also sort each bone into its home by
    name. Returns (done, skipped lines)."""
    widget, scale, colour = look
    bones, why = found.usable('data')
    if widget and (widget in bpy.data.objects or widget.startswith(('WGT-', 'Selection'))):
        set_shape(bones, widget)
    for pb in bones:
        pb.custom_shape_scale_xyz = (scale, scale, scale)
        set_colour(pb, colour, where)
    if sort:
        auto_sort(bones)
    return len(bones), why


# ---------------------------------------------------------------- copying and mirroring
LOOK_BONE = ('show_wire',)
SETTINGS_BONE = ('use_deform', 'use_inherit_rotation', 'use_local_location', 'inherit_scale', 'bbone_segments')
SETTINGS_POSE = ('rotation_mode', 'lock_location', 'lock_rotation', 'lock_scale', 'hide')


def copy_look(source, pb):
    """Shape, size & placement, wire and colour of `source` onto `pb`."""
    pb.custom_shape = source.custom_shape
    copy_placement(source, pb)
    for name in LOOK_BONE:
        setattr(pb.bone, name, getattr(source.bone, name))
    copy_colour(source, pb)


def copy_settings(source, pb):
    for name in SETTINGS_BONE:
        setattr(pb.bone, name, getattr(source.bone, name))
    if pb.rotation_mode != source.rotation_mode:
        values = rotation_values(pb)
        mode = pb.rotation_mode
        pb.rotation_mode = source.rotation_mode
        set_rotation(pb, mode, values)
    for name in SETTINGS_POSE[1:]:
        setattr(pb, name, getattr(source, name))


def mirror_to_side(found):
    """Each chosen bone's look, settings and home (side swapped) onto its mirror bone. Returns (done, skipped)."""
    bones, why = found.usable('data')
    done = 0
    for pb in bones:
        if found.source_of(pb) is not None:
            continue
        other = mirror_of(pb)
        if other is None or other.id_data.name != pb.id_data.name:
            continue
        copy_look(pb, other)
        copy_settings(pb, other)
        home = home_of(pb)
        if home:
            target = rn.flip(home)
            target = target if target in other.id_data.data.collections_all or target in bc.PARENT else home
            if not can_hold(other.id_data, target):
                bc.move_to(other.id_data, other.name, target, other.bone.use_deform, keep_driven=True)
        done += 1
    return done, why


# ---------------------------------------------------------------- names
def rename_plan(rig, table):
    """`table` {old: new} without clashes: a new name another bone already has (and keeps) is dropped.
    Returns (renames, clash lines)."""
    keeps = set(rig.data.bones.keys()) - set(table)
    renames, clashes, taken = {}, [], set()
    for old, new in table.items():
        if new == old:
            continue
        if new in keeps or new in taken:
            clashes.append(f"{old}: {new} is taken")
            continue
        renames[old] = new
        taken.add(new)
    return renames, clashes


def rename(rig, table):
    """Rename bones through rig_rename (fixes animation, records, modifier fields). Returns (count, clash lines)."""
    renames, clashes = rename_plan(rig, table)
    if renames:
        rig_rename.rename(rig, renames)
    return len(renames), clashes


def standard_table(rig, names):
    """{old: standard name} for bones off the standard (rig_names.standard with the bone's home and deform)."""
    return {n: rn.standard(n, home_of(rig.pose.bones[n]), rig.data.bones[n].use_deform) for n in names
            if n in rig.data.bones and not rn.is_standard(n)}


def select_only(context, pairs):
    """Select these (rig, bone name) pairs only, the first active."""
    for pb in context.selected_pose_bones or []:
        set_selected(pb, False)
    for k, (rig, name) in enumerate(pairs):
        pb = rig.pose.bones.get(name)
        if pb is None:
            continue
        set_selected(pb, True)
        if k == 0:
            rig.data.bones.active = pb.bone


# ---------------------------------------------------------------- constraints on a bone
SKIP_PROPS = {'rna_type', 'name', 'type', 'is_valid', 'is_override_data_editable', 'error_location', 'error_rotation'}


def flip_names(rig):
    """{bone: its mirror bone} for every sided bone of the rig (for names in texts, data paths and subtargets)."""
    return {b.name: rn.flip(b.name) for b in rig.data.bones if rn.flip(b.name) != b.name}


def copy_constraint(source, owner, table):
    """A copy of constraint `source` on pose bone `owner` (one of that name there is replaced), its bone names
    swapped by `table`; Armature targets too."""
    rig = owner.id_data
    old = owner.constraints.get(source.name)
    if old is not None:
        lr.remove_constraint(rig, owner.name, source.name)
    new = owner.constraints.new(source.type)
    new.name = source.name
    for prop in source.bl_rna.properties:
        name = prop.identifier
        if prop.is_readonly or name in SKIP_PROPS or prop.type == 'COLLECTION':
            continue
        value = getattr(source, name)
        if isinstance(value, str) and name.endswith('subtarget'):
            value = table.get(value, value)
        try:
            setattr(new, name, value)
        except (AttributeError, TypeError, ValueError):
            pass
    if source.type == 'ARMATURE':
        for target in source.targets:
            copy = new.targets.new()
            copy.target, copy.subtarget, copy.weight = target.target, table.get(target.subtarget, target.subtarget), target.weight
    return new


def mirror_constraints(source):
    """Every constraint of `source` copied to its mirror bone (same names replaced), with their drivers, bone names
    swapped. Returns (count, the mirror bone or None)."""
    other = mirror_of(source)
    if other is None:
        return 0, None
    rig = source.id_data
    table = flip_names(rig)
    for c in source.constraints:
        copy_constraint(c, other, table)
    drivers = rig.animation_data.drivers if rig.animation_data else []
    prefix = f'pose.bones["{source.name}"].constraints['
    for fc in [fc for fc in drivers if fc.data_path.startswith(prefix)]:
        path = rn.replace_names(fc.data_path, table)
        old = drivers.find(path, index=fc.array_index)
        if old:
            drivers.remove(old)
        new = drivers.from_existing(src_driver=fc)
        new.data_path = path
        for var in new.driver.variables:
            for target in var.targets:
                target.data_path = rn.replace_names(target.data_path, table)
                target.bone_target = table.get(target.bone_target, target.bone_target)
    return len(source.constraints), other
