# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's Assorted Tools: the Selected card at the top of the panel (selected_ui.py): the live controls of a selected
Camera Rig, Lighting Rig, Bounce Card, Photo Backdrop, Shadow Catcher Floor or Catchlight. Below it the tool
card, whose header is the tool dropdown. Convert: Make Modifier Helper (selected objects become modifier helpers).
Object: Add Mirrored Mesh (a primitive as only the half a Mirror modifier completes; mirrored_mesh*.py), Add Modifier Helper (a styled primitive at the 3D cursor; helper_object_ui.py). Export: Combine Into One Model (Combine
Multi Part Model: a rigged character's parts and nested rigs into one rig + one mesh, saved as a new file; output name
and folder in output_file.py) and Game Rig (game_rig_ui.py, also exports FBX / glTF / Blend). Character Rigs: Combine
Bones (combine_bones_ui.py), Bone Workshop (bone_workshop*.py: shape, size, colour, collections, settings and name of
the selected bones and their mirror bones; Rig Check in rig_check.py), Full Character Rig (full_rig_ui.py; its Existing Rig section holds Rebuild Face, Upgrade Limbs
and Sort Bone Collections for rigs made before it: face_rig_ui.py / limbs_ui.py keep their operators), Rename Bones (rename_ui.py, logic in rig_rename.py) and
Bendy Span Bone (span_ui.py, logic in span_bones.py), B-Bone Chain Builder (bbone_builder_ui.py, logic in bbone_builder.py). Weights: Combined Weight From Bones (bone_chain_ui.py, shared with
Digit's Modifiers: a vertex group from a bone chain's summed weights, minus Excluded Bones).
Check also has Pre-Render Check (pre_render_check.py); Scene: Composition Guides (composition_overlay.py) and Fast Viewport (fast_viewport.py); Character Rigs also has
Save Pose (save_pose.py) and Rig Stress Pose Test (rig_stress_ui.py, logic in rig_stress.py). Folded in from former add-ons: Reset Pose / IK-FK snap / parent switch operators (pose_ops.py, the
Pose > Transform menu entry; the rig panel's part, bone group, reset and copy operators in rig_panel_ops.py), Bones In Front While Posing (Scene;
bones_in_front.py, the one timer, on only while its preference is on) and Procedural Baker (Export; procedural_baker.py).
Remove Disconnected Islands and Merge Vertex Groups (weight_tools_ui.py, logic in weight_cleanup.py).
Setups: Camera Rig, Lighting Rig, Photo Backdrop, Shadow Catcher Floor, HDRI World; the Lighting Rig card also holds the
folded Catchlight (catchlight.py) and Bounce Cards (bounce_cards.py) Deploy sections and Catchlight's Remove (they are no longer
dropdown tools).
Texture: UV Rebake (uv_rebake_ui.py, logic in uv_rebake.py).
Scene > Texture Studio (texture_studio/: the starter card; its own sidebar panel shows only in a studio scene; File > New > Texture Studio).
The sidebar panel shows one tool at a time, picked in a dropdown (the TOOLS registry below).

Self-contained on purpose: the extension is installed as a copy, so it can't import the
charfix scripts that live next to it in the source folder.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from mathutils import Matrix

from .ui_cards import action_row, header_right, hints, prop_group, section, status, toggles  # generated copy
from . import bbone_builder_ui, bone_chain_ui, bone_workshop_ui, bounce_cards, camera_rig, catchlight, character_rig, bones_in_front, make_posable, composition_overlay, rig_placement, combine_bones as cb, combine_bones_ui, digit_world_library, face_rig_ui, fast_viewport, full_rig_ui, game_rig_ui, hdri_world, helper_object_ui, light_rig, limbs_ui, look_at, move_alone, f3_menus, mirror_pivot, mirror_pivot_tools, mirrored_mesh_ui, placement_tool, origin_tool, output_file as of, path_generators, photo_backdrop, pose_as_rest_ui, pose_ops, pose_shape_keys, rig_panel_ops, pre_render_check, procedural_baker, rename_ui, rig_component_ui, rig_modifiers, rig_stress_ui, save_pose, select_non_manifold_smart, selected_ui, shadow_catcher, span_ui, weight_tools_ui
from .scene_checks import belongs_to, find_rig, rig_of_object  # noqa: F401  (generated copy; also used by other modules)
from . import drivers_ui, oops_ui, uv_rebake_ui
from . import decal_recipe, decal_state_ops, decal_layer_ops, decal_import_ops, decal_drop, decal_gizmo, decal_ui
from .texture_studio import panel as texture_studio_ui
from . import rig_switches_ui  # generated copy: the rig card's search field
from . import prefs, tool_menu
from .tool_menu import BEGINNER, EXPERT
from .tool_picker import enum_items, tool_id  # generated copy of shared_addon/tool_picker.py
from .prefs import DigitToolsPreferences

KEPT_MODIFIERS = {'ARMATURE', 'SUBSURF'}  # never applied
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT'}
SUFFIX = "-Whole"


# ---------------------------------------------------------------------------
# Finding the character (rig_of_object, find_rig, belongs_to come from scene_checks, shared with Oops Debugger / Drivers)
# ---------------------------------------------------------------------------

def protected_objects(names):
    """Objects in the named collections (and their children): never touched."""
    result = set()
    for name in names:
        coll = bpy.data.collections.get(name)
        if coll is not None:
            result.update(coll.all_objects)
    return result


def is_visible(ob, view_layer):
    try:
        return ob.name in view_layer.objects and ob.visible_get(view_layer=view_layer)
    except RuntimeError:
        return False


def split_parts(context, rig, keep_names=(), remove_hidden=False):
    """(parts to merge, spares to delete) of the character, protected collections left out.
    Hidden parts are spares when remove_hidden, else merged like the visible ones."""
    view_layer = context.view_layer
    skip = protected_objects(keep_names)
    parts, spares = [], []
    for ob in context.scene.objects:
        if ob.type not in GEOMETRY_TYPES or ob in skip or not belongs_to(ob, rig):
            continue
        (parts if not remove_hidden or is_visible(ob, view_layer) else spares).append(ob)
    return parts, spares


# ---------------------------------------------------------------------------
# Applying modifiers
# ---------------------------------------------------------------------------

def applicable_modifiers(ob):
    return [m for m in ob.modifiers if m.type not in KEPT_MODIFIERS and m.show_viewport]


def evaluated_mesh(ob):
    """Mesh of the object as evaluated now (modifiers, shape keys), without shape keys."""
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                           depsgraph=depsgraph)


def coords(mesh):
    flat = [0.0] * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get('co', flat)
    return flat


def shape_keys_rebuildable(ob):
    """Shape keys can be re-made after modifiers when they are all relative to the basis."""
    blocks = ob.data.shape_keys.key_blocks
    return all(b.relative_key == blocks[0] and not b.vertex_group for b in blocks[1:])


def bake_with_shape_keys(ob):
    """Evaluate each shape key on its own and rebuild the keys on the modified mesh.
    Returns (mesh, keys) or None when a modifier changes the vertex count per key."""
    blocks = ob.data.shape_keys.key_blocks
    saved = [(b.value, b.mute, b.slider_max) for b in blocks]
    only_key = ob.show_only_shape_key
    ob.show_only_shape_key = False
    try:
        for b in blocks:
            b.value, b.mute = 0.0, False
        base = evaluated_mesh(ob)
        keys = []
        for b in list(blocks)[1:]:
            b.slider_max = max(b.slider_max, 1.0)
            b.value = 1.0
            mesh = evaluated_mesh(ob)
            keys.append((b, coords(mesh), len(mesh.vertices)))
            bpy.data.meshes.remove(mesh)
            b.value = 0.0
    finally:
        for b, (value, mute, slider_max) in zip(blocks, saved):
            b.value, b.mute, b.slider_max = value, mute, slider_max
        ob.show_only_shape_key = only_key
    if any(count != len(base.vertices) for _, _, count in keys):
        bpy.data.meshes.remove(base)
        return None
    return base, keys


def restore_shape_keys(ob, base, keys, old_blocks):
    ob.data = base
    ob.shape_key_add(name=old_blocks[0].name, from_mix=False)
    for (block, co, _count) in keys:
        new = ob.shape_key_add(name=block.name, from_mix=False)
        new.data.foreach_set('co', co)
        new.value, new.slider_min, new.slider_max = block.value, block.slider_min, block.slider_max
        new.mute, new.interpolation = block.mute, block.interpolation


def apply_modifiers(ob, report):
    """Replace the object's geometry with the result of its modifiers (Armature and Subsurf excepted).
    Armature is skipped so everything is applied in rest pose; modifiers after Armature are applied
    to the rest-pose mesh too (as if they came before it). Modifiers off in the viewport are dropped."""
    mods = applicable_modifiers(ob)
    if not mods:
        return
    hidden = [m for m in ob.modifiers if m.type in KEPT_MODIFIERS and m.show_viewport]
    for m in hidden:
        m.show_viewport = False
    try:
        has_keys = ob.type == 'MESH' and ob.data.shape_keys is not None
        if has_keys:
            old = [(b.name, b.value) for b in ob.data.shape_keys.key_blocks]
            rebuilt = bake_with_shape_keys(ob) if shape_keys_rebuildable(ob) else None
            if rebuilt is not None:
                old_blocks = list(ob.data.shape_keys.key_blocks)
                old_data = ob.data
                restore_shape_keys(ob, *rebuilt, old_blocks)
                if old_data.users == 0:
                    bpy.data.meshes.remove(old_data)
                report.notes.append(f"{ob.name}: shape keys rebuilt after modifiers")
                return
            report.warn(f"{ob.name}: shape keys lost (modifiers change the vertex count or keys are not "
                        f"relative to the basis); baked at current values {[n for n, v in old if v]}")
        mesh = evaluated_mesh(ob)
        old_data = ob.data
        ob.data = mesh
        if old_data.users == 0:
            bpy.data.meshes.remove(old_data)
    finally:
        for m in hidden:
            m.show_viewport = True


def curve_to_mesh_object(ob, report):
    """New mesh object (same place in the scene) from a visible curve/text/surface, or None."""
    if any(m.type == 'ARMATURE' for m in ob.modifiers):
        report.warn(f"{ob.name}: curve deformed by the armature can't be merged, skipped")
        return None
    hidden = [m for m in ob.modifiers if m.type in KEPT_MODIFIERS and m.show_viewport]
    for m in hidden:
        m.show_viewport = False
    mesh = evaluated_mesh(ob)
    for m in hidden:
        m.show_viewport = True
    new = bpy.data.objects.new(ob.name + "_mesh", mesh)
    for coll in ob.users_collection:
        coll.objects.link(new)
    new.parent, new.parent_type, new.parent_bone = ob.parent, ob.parent_type, ob.parent_bone
    new.matrix_parent_inverse = ob.matrix_parent_inverse
    new.matrix_world = ob.matrix_world
    report.notes.append(f"{ob.name}: converted to mesh")
    return new


# ---------------------------------------------------------------------------
# Joining
# ---------------------------------------------------------------------------

def part_rig(ob, main):
    """The rig that deforms this part: its first Armature modifier's object, its bone parent's armature,
    else the main rig."""
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object
    if ob.parent and ob.parent.type == 'ARMATURE' and ob.parent_type == 'BONE':
        return ob.parent
    return main


def weight_bone_parented(ob):
    """A mesh parented to a bone (no Armature modifier) gets a full-weight group for that bone."""
    if not (ob.parent and ob.parent.type == 'ARMATURE' and ob.parent_type == 'BONE' and ob.parent_bone):
        return
    if any(m.type == 'ARMATURE' for m in ob.modifiers):
        return
    group = ob.vertex_groups.get(ob.parent_bone) or ob.vertex_groups.new(name=ob.parent_bone)
    group.add(range(len(ob.data.vertices)), 1.0, 'REPLACE')


def warn_multiple_rigs(ob, report):
    rigs = {m.object.name for m in ob.modifiers if m.type == 'ARMATURE' and m.object}
    if len(rigs) > 1:
        report.warn(f"{ob.name}: deformed by several armatures {sorted(rigs)}; only the first is joined into the rig")


# ---------------------------------------------------------------------------
# Joining swap rigs into the main rig
# ---------------------------------------------------------------------------

def carrying_bone(swap_rig, main):
    """Main-rig bone that carries the swap rig object (bone parent or Child Of constraint), else None."""
    if swap_rig.parent == main and swap_rig.parent_type == 'BONE' and swap_rig.parent_bone in main.data.bones:
        return swap_rig.parent_bone
    for con in swap_rig.constraints:
        if con.type == 'CHILD_OF' and con.target == main and con.subtarget in main.data.bones:
            return con.subtarget
    return None


def rename_clashing_bones(swap_rig, taken, parts):
    """Give the swap rig's bones that clash with `taken` names a unique name, and the same to the
    matching vertex groups of its parts. Returns the number renamed."""
    renamed = 0
    for bone in list(swap_rig.data.bones):
        old = bone.name
        if old not in taken:
            taken.add(old)
            continue
        new, n = f"{old}.{swap_rig.name}"[:60], 1
        while new in taken:
            new = f"{old}.{swap_rig.name}"[:55] + f".{n:03d}"
            n += 1
        bone.name = new  # Blender also fixes constraint subtargets, drivers and groups of deformed meshes
        for ob in parts:
            group = ob.vertex_groups.get(old)
            if group is not None:
                group.name = new
        taken.add(new)
        renamed += 1
    return renamed


def retarget_to(old_rigs, main):
    """Constraints and driver variables that point at a rig about to be joined point at the main rig."""
    for ob in bpy.data.objects:
        for _pb, link in cb.constraint_links(ob):
            if link.target in old_rigs:
                link.target = main
    for _item, _fcurve, target in cb.driver_targets():
        if target.id in old_rigs:
            target.id = main


def reparent_keep_world(objects, rig):
    for ob in objects:
        world = ob.matrix_world.copy()
        ob.parent, ob.parent_type, ob.parent_bone = rig, 'OBJECT', ""
        ob.matrix_world = world


def make_selectable(context, ob):
    """Swap rigs often sit in hidden or excluded collections; join needs them in the view layer, visible."""
    if ob.name not in context.view_layer.objects:
        context.scene.collection.objects.link(ob)
    ob.hide_viewport = ob.hide_select = False
    ob.hide_set(False)


def join_swap_rigs(context, main, swaps, report):
    """Join the swap armatures into the main one (bones keep their world rest position). A swap rig carried
    by a main bone gets its root bones parented to that bone, so it follows as before."""
    taken = {b.name for b in main.data.bones}
    # (carrying bone, root bone names) per rig, read now: the rig objects are gone after the join
    attach = [(carrying_bone(r, main), [b.name for b in r.data.bones if b.parent is None]) for r in swaps]
    for r in swaps:
        if r.animation_data and r.animation_data.action:
            report.warn(f"{r.name}: animation on the rig object is not carried over")
    retarget_to(set(swaps), main)
    datas = [r.data for r in swaps]
    for ob in context.selected_objects:
        ob.select_set(False)
    for r in swaps:
        make_selectable(context, r)
        r.select_set(True)
    main.select_set(True)
    context.view_layer.objects.active = main
    bpy.ops.object.join()
    for data in datas:
        if data.users == 0:
            bpy.data.armatures.remove(data)
    if any(bone for bone, _ in attach):
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = main.data.edit_bones
        for bone, root_names in attach:
            for name in root_names:
                child = edit_bones.get(name)
                if bone and child:
                    child.parent, child.use_connect = edit_bones[bone], False
        bpy.ops.object.mode_set(mode='OBJECT')


def other_users(rig, gone):
    """True if an object that stays uses the rig (Armature modifier or constraint target)."""
    for ob in bpy.data.objects:
        if ob in gone:
            continue
        if any(m.type == 'ARMATURE' and m.object == rig for m in ob.modifiers):
            return True
        if any(link.target == rig for _pb, link in cb.constraint_links(ob)):
            return True
    return False


def subsurf_levels(parts):
    """(max viewport, max render, number of parts with subsurf, set of distinct level pairs)."""
    pairs = [(m.levels, m.render_levels) for ob in parts for m in ob.modifiers if m.type == 'SUBSURF']
    if not pairs:
        return None
    return max(p[0] for p in pairs), max(p[1] for p in pairs), set(pairs)


def uv_name_sets(parts):
    return {tuple(uv.name for uv in ob.data.uv_layers) for ob in parts if ob.type == 'MESH'}


def render_uv_to_uvmap(ob):
    """Make the part's render UV the layer named "UVMap", so a join (which matches UV layers by name) keeps its coordinates.
    The old "UVMap" is kept as "UVMap_Old"; every other layer (e.g. ones used by UV Map nodes) is left alone."""
    layers = ob.data.uv_layers
    render = next((uv for uv in layers if uv.active_render), None)
    if render is None or render.name == "UVMap":
        return False
    old = layers.get("UVMap")
    if old:
        old.name = "UVMap_Old"
    coords = [0.0] * (2 * len(render.data))
    render.data.foreach_get("uv", coords)
    new = layers.new(name="UVMap")
    new.data.foreach_set("uv", coords)
    new.active_render = new.active = True
    return True


def set_mode_object():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def reparent_children(parents, rig, skip=()):
    """Objects left behind under objects that will be deleted go to the rig, keeping their world position."""
    reparent_keep_world([ob for ob in bpy.data.objects if ob.parent in parents and ob not in skip], rig)


def remove_object(ob):
    data = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.batch_remove([data])


class Report:
    def __init__(self):
        self.warnings, self.notes = [], []
        self.merged = self.spares = self.rigs_joined = self.rigs_deleted = 0
        self.saved_path = None
        self.islands = self.manifold = self.seconds = None
        self.island_names = []
        self.thickened = 0
        self.uv_fixed = []

    def warn(self, text):
        self.warnings.append(text)

    def summary(self):
        text = f"Merged {self.merged} parts, deleted {self.spares} spare parts"
        if self.rigs_joined or self.rigs_deleted:
            text += f", joined {self.rigs_joined} swap rigs, deleted {self.rigs_deleted} spare rigs"
        if self.warnings:
            text += f", {len(self.warnings)} warning(s): " + "; ".join(self.warnings)
        return text


def drop_custom_normals(context, ob):
    """Remove the custom split normals so Geometry Nodes modifiers behave."""
    context.view_layer.objects.active = ob
    if ob.data.has_custom_normals:
        bpy.ops.mesh.customdata_custom_splitnormals_clear()


def make_whole(context, rig, keep_names=(), remove_hidden=False, drop_normals=False):
    """Merge the character's parts into one mesh (hidden ones are deleted instead when remove_hidden; custom normals removed when drop_normals). Returns (object, Report) or (None, Report)."""
    report = Report()
    set_mode_object()
    parts, spares = split_parts(context, rig, keep_names, remove_hidden)
    parts = [ob for ob in parts if ob.library is None]
    if not parts:
        report.warn("no parts to merge")
        return None, report

    part_rigs = {part_rig(ob, rig) for ob in parts}
    spare_rigs = {part_rig(ob, rig) for ob in spares} - part_rigs - {rig}
    pose_positions = {r: r.data.pose_position for r in part_rigs | spare_rigs | {rig}}
    for r in pose_positions:
        r.data.pose_position = 'REST'
    try:
        originals, merge = [], []
        for ob in parts:
            if ob.type == 'MESH':
                apply_modifiers(ob, report)
                merge.append(ob)
            else:
                new = curve_to_mesh_object(ob, report)
                if new is not None:
                    merge.append(new)
                    originals.append(ob)
        if not merge:
            report.warn("nothing could be merged")
            return None, report
        context.view_layer.update()

        levels = subsurf_levels(parts)
        for ob in merge:
            if ob.type == 'MESH' and render_uv_to_uvmap(ob):
                report.uv_fixed.append(ob.name)
        uv_sets = uv_name_sets(merge)
        rig_of_part = {}
        for ob in merge:
            warn_multiple_rigs(ob, report)
            weight_bone_parented(ob)
            rig_of_part[ob] = part_rig(ob, rig)
        swaps = sorted(set(rig_of_part.values()) - {rig}, key=lambda r: r.name)
        taken = {b.name for b in rig.data.bones}
        for r in swaps:
            rename_clashing_bones(r, taken, [ob for ob in merge if rig_of_part[ob] == r])
        for ob in merge:
            for mod in list(ob.modifiers):
                ob.modifiers.remove(mod)
        preserve = any(m.use_deform_preserve_volume for ob in parts for m in ob.modifiers
                       if m.type == 'ARMATURE' and m.object == rig)

        target = merge[0]
        gone_objects = set(spares) | set(originals)
        spare_rigs = {r for r in spare_rigs if not other_users(r, gone_objects | set(merge) | spare_rigs | set(swaps))}
        reparent_children(gone_objects | set(swaps) | spare_rigs, rig, skip=gone_objects | set(swaps) | spare_rigs)
        if swaps:
            join_swap_rigs(context, rig, swaps, report)
            report.rigs_joined = len(swaps)
        for ob in context.selected_objects:
            ob.select_set(False)
        for ob in merge:
            make_selectable(context, ob)
            ob.select_set(True)
        context.view_layer.objects.active = target
        if len(merge) > 1:
            bpy.ops.object.join()
        for ob in originals + spares + list(spare_rigs):
            remove_object(ob)
        report.rigs_deleted = len(spare_rigs)
        report.merged, report.spares = len(parts), len(spares)
    finally:
        for r, position in pose_positions.items():
            try:
                r.data.pose_position = position
            except ReferenceError:  # rig was joined or deleted
                pass

    if report.uv_fixed:
        report.notes.append(f"render UV copied to \"UVMap\" on: {', '.join(report.uv_fixed)}")
    if len(uv_sets) > 1:
        report.warn("parts have different UV map names; layers with the same name are joined, the others stay on their own parts")
    target.name = target.data.name = rig.name + "_Whole"
    if drop_normals:
        drop_custom_normals(context, target)
    world = target.matrix_world.copy()
    target.parent, target.parent_type, target.parent_bone = rig, 'OBJECT', ""
    target.matrix_world = world

    arm = target.modifiers.new("Armature", 'ARMATURE')
    arm.object, arm.use_deform_preserve_volume = rig, preserve
    sub = target.modifiers.new("Subdivision", 'SUBSURF')
    if levels is None:
        report.warn("no part had Subdivision Surface; added one at levels 1 / render 2")
        sub.levels, sub.render_levels = 1, 2
    else:
        sub.levels, sub.render_levels = levels[0], levels[1]
        if len(levels[2]) > 1:
            report.warn(f"subdivision levels differed {sorted(levels[2])}; used highest {levels[0]} / {levels[1]}")
    return target, report


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def whole_path(filepath, name="", folder="", rig_name=""):
    """The file Combine saves: <file>-Whole.blend next to the file (a never saved file: <rig>-Whole.blend, only when a
    folder is typed), -2, -3 ... if taken, or the typed name / folder. Never an existing path. None: nowhere to save."""
    stem = os.path.splitext(os.path.basename(filepath))[0] if filepath else rig_name
    return of.output_path(name, folder, stem + SUFFIX, ".blend", filepath)


def save_as_whole(name="", folder="", rig_name=""):
    """Save the session as a new file (see whole_path; keeps relative paths valid).
    Returns the path, or None when there is nowhere to save it."""
    path = whole_path(bpy.data.filepath, name, folder, rig_name)
    if path is None:
        return None
    of.make_folder(path)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path


# ---------------------------------------------------------------------------
# Operator and panel
# ---------------------------------------------------------------------------

REMOVE_HIDDEN_HELP = "On: hidden parts of the character are left out of the merge and deleted. Off: everything is merged, hidden parts included"
DROP_NORMALS_HELP = "On: the combined mesh has no custom split normals (Geometry Nodes modifiers work badly on meshes with them). Off: normals are kept"


def keep_names_of(scene):
    return [n.strip() for n in scene.whole_keep_collections.split(",") if n.strip()]


class CHARTOOLS_OT_combine(bpy.types.Operator):
    """Combine the character's parts and nested rigs into one rig + one mesh, save as a new file"""
    bl_idname = "digits_assorted_tools.combine_multi_part"
    bl_label = "Combine Multi Part Model"
    bl_options = {'REGISTER'}

    drop_normals: BoolProperty(
        name="Clear custom normals", default=False,
        description=DROP_NORMALS_HELP)

    @classmethod
    def poll(cls, context):
        return find_rig(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        rig = find_rig(context)
        whole, report = make_whole(context, rig, keep_names_of(context.scene), context.scene.whole_remove_hidden, self.drop_normals)
        if whole is None:
            self.report({'WARNING'}, report.summary())
            return {'CANCELLED'}
        scene = context.scene
        path = save_as_whole(scene.whole_output_name, scene.whole_output_folder, rig.name)
        text = report.summary()
        text += f". Saved as {os.path.basename(path)}" if path else ". File not saved yet: done in place"
        self.report({'WARNING'} if report.warnings else {'INFO'}, text)
        return {'FINISHED'}


class CHARTOOLS_PT_selected(bpy.types.Panel):
    """The Selected panel: its own top-level sidebar panel (collapse, drag to reorder), first in the tab."""
    bl_label = "Selected"
    bl_idname = "CHARTOOLS_PT_selected"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Digit's Tools"
    bl_order = 0

    def draw_header_preset(self, context):
        header_right(self.layout, selected_ui.header_summary(context))

    def draw(self, context):
        selected_ui.draw_body(self.layout, context)


class CHARTOOLS_PT_panel(bpy.types.Panel):
    """The Tools panel: the tool dropdown on top, the chosen tool's card under it."""
    bl_label = "Tools"
    bl_idname = "CHARTOOLS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Digit's Tools"
    bl_order = 1

    def draw(self, context):
        chosen = context.window_manager.digit_tool
        tool_menu.draw_legend(self.layout)
        tool_menu.draw_dropdown(self.layout, chosen)
        draw_tool(self.layout, context, chosen)

    @staticmethod
    def draw_combine(layout, context):
        scene = context.scene
        rig = find_rig(context)
        body = layout   # the tool dropdown is the title
        if rig is None:
            status(body, "Select the character (or its rig)")
            return
        parts, spares = split_parts(context, rig, keep_names_of(scene), scene.whole_remove_hidden)
        status(body, f"{len(parts)} to merge · {len(spares)} to delete", icon='ARMATURE_DATA')
        op = action_row(body).operator(CHARTOOLS_OT_combine.bl_idname, icon='MESH_DATA')
        op.drop_normals = scene.whole_drop_normals
        path = whole_path(bpy.data.filepath, scene.whole_output_name, scene.whole_output_folder, rig.name)
        hints(body, [f"Saves as {os.path.basename(path)}" if path else "File not saved yet: done in place"], context)
        opts = section(body, "chartools_combine_options", "Options", icon='PREFERENCES')
        if opts:
            toggles(opts, scene, [("whole_remove_hidden", "Remove Hidden Parts"),
                                  ("whole_drop_normals", "Clear Custom Normals")], columns=1)
            prop_group(opts, scene, [("whole_keep_collections", "Keep Collections")])
        auto = whole_path(bpy.data.filepath, "", scene.whole_output_folder, rig.name)
        of.draw_output(body, "chartools_combine_output", scene, "whole_output_name", "whole_output_folder",
                       os.path.basename(auto) if auto else "", of.resolve_folder("", bpy.data.filepath))


CHAIN_TOOL = bone_chain_ui.BoneChainTool(__package__)   # the combined weight group tool (shared with Digit's Modifiers)

# The tools the panel's dropdown offers: one line each, (category, label, draw function(layout, context)).
# Adding a tool = adding its line here. The dropdown lists categories as headings, tools A-Z under each.
TOOLS = (("Export", "Combine Into One Model", CHARTOOLS_PT_panel.draw_combine),
         ("Check", "Oops Debugger", oops_ui.draw_card),
         ("Check", "Pre-Render Check", pre_render_check.draw_card),
         ("Convert", "Make Modifier Helper", helper_object_ui.draw_card),
         ("Object", "Add Mirrored Mesh", mirrored_mesh_ui.draw_card),
         ("Object", "Add Modifier Helper", helper_object_ui.draw_add_card),
         ("Object", "Decals", decal_ui.draw_card),
         ("Object", "Origin Tool", origin_tool.draw_card),
         ("Object", "Path Generators", path_generators.draw_card),
         ("Character Rigs", "Add Rig Component", rig_component_ui.draw_card),
         ("Character Rigs", "Bone Workshop", bone_workshop_ui.draw_card),
         ("Character Rigs", "Combine Bones", combine_bones_ui.draw_card),
         ("Character Rigs", "Drivers", drivers_ui.draw_card),
         ("Character Rigs", "Full Character Rig", full_rig_ui.draw_card),
         ("Character Rigs", "Look At", look_at.draw_card),
         ("Character Rigs", "Rename Bones", rename_ui.draw_card),
         ("Character Rigs", "Apply Pose as Rest", pose_as_rest_ui.draw_card),
         ("Character Rigs", "Rig Stress Pose Test", rig_stress_ui.draw_card),
         ("Character Rigs", "Poses to Shape Keys", pose_shape_keys.draw_card),
         ("Character Rigs", "Save Pose", save_pose.draw_card),
         ("Character Rigs", "Bendy Span Bone", span_ui.draw_card),
         ("Character Rigs", "B-Bone Chain Builder", bbone_builder_ui.draw_card),
         ("Export", "Game Rig", game_rig_ui.draw_card),
         ("Export", "Procedural Baker", procedural_baker.draw_card),
         ("Scene", "Bones In Front", bones_in_front.draw_card),
         ("Scene", "Composition Guides", composition_overlay.draw_card),
         ("Scene", "Fast Viewport", fast_viewport.draw_card),
         ("Setups", "Camera Rig", camera_rig.draw_card),
         ("Setups", "HDRI World", hdri_world.draw_card),
         ("Setups", "Photo Backdrop", photo_backdrop.draw_card),
         ("Setups", "Shadow Catcher Floor", shadow_catcher.draw_card),
         ("Setups", "Lighting Rig", light_rig.draw_card),
         ("Weights", bone_chain_ui.DISPLAY_NAME, CHAIN_TOOL.draw_body),
         ("Weights", weight_tools_ui.MERGE_NAME, weight_tools_ui.draw_merge_card),
         ("Weights", weight_tools_ui.ISLAND_NAME, weight_tools_ui.draw_island_card),
         ("Scene", "Texture Studio", texture_studio_ui.draw_card),
         ("Texture", "UV Rebake", uv_rebake_ui.draw_card))


# Each tool's dropdown icon and skill badge (BEGINNER, EXPERT or None), keyed by the TOOLS label.
TOOL_LOOKS = {"Oops Debugger": ('ERROR', BEGINNER),
              "Pre-Render Check": ('CHECKMARK', None),
              "Add Mirrored Mesh": ('MOD_MIRROR', BEGINNER),
              "Add Modifier Helper": ('EMPTY_AXIS', None),
              "Origin Tool": ('OBJECT_ORIGIN', BEGINNER),
              "Decals": ('IMAGE_PLANE', None),
              "Path Generators": ('CURVE_DATA', BEGINNER),
              "Make Modifier Helper": ('EMPTY_ARROWS', EXPERT),
              "Rig Stress Pose Test": ('MOD_SIMPLEDEFORM', None),
              "Add Rig Component": ('BONE_DATA', None),
              "Bone Workshop": ('BONE_DATA', BEGINNER),
              "Combine Bones": ('GROUP_BONE', EXPERT),
              "Drivers": ('DRIVER', EXPERT),
              "Full Character Rig": ('ARMATURE_DATA', None),
              "Look At": ('HIDE_OFF', None),
              "Rename Bones": ('SORTALPHA', EXPERT),
              "Apply Pose as Rest": ('MOD_ARMATURE', EXPERT),
              "Poses to Shape Keys": ('SHAPEKEY_DATA', EXPERT),
              "Save Pose": ('POSE_HLT', None),
              "Bendy Span Bone": ('BONE_DATA', None),
              "B-Bone Chain Builder": ('CURVE_BEZCURVE', None),
              "Combine Into One Model": ('PACKAGE', None),
              "Game Rig": ('EXPORT', EXPERT),
              "Procedural Baker": ('NODE_TEXTURE', EXPERT),
              "Bones In Front": ('XRAY', None),
              "Composition Guides": ('MESH_GRID', None),
              "Fast Viewport": ('TIME', None),
              "Camera Rig": ('CAMERA_DATA', BEGINNER),
              "HDRI World": ('WORLD', BEGINNER),
              "Photo Backdrop": ('IMAGE_BACKGROUND', BEGINNER),
              "Shadow Catcher Floor": ('CON_FLOOR', None),
              "Lighting Rig": ('LIGHT', BEGINNER),
              bone_chain_ui.DISPLAY_NAME: ('GROUP_VERTEX', None),
              weight_tools_ui.MERGE_NAME: ('AUTOMERGE_ON', None),
              weight_tools_ui.ISLAND_NAME: ('UNLINKED', None),
              "UV Rebake": ('UV', EXPERT),
              "Texture Studio": ('IMAGE_DATA', None)}


def sorted_tools():
    return sorted(TOOLS, key=lambda tool: (tool[0], tool[1]))


def tool_items():
    return enum_items([(category, label) for category, label, _ in sorted_tools()])


TOOL_ITEMS = tool_items()  # kept at module level: Blender reads the list lazily


def draw_tool(layout, context, chosen):
    """Draw the card of the chosen tool."""
    for _, label, draw in TOOLS:
        if tool_id(label) == chosen:
            draw(layout, context)


classes = (DigitToolsPreferences, CHARTOOLS_OT_combine, CHARTOOLS_PT_selected, CHARTOOLS_PT_panel, *tool_menu.classes, *character_rig.classes, *make_posable.classes, *rig_modifiers.classes)


def register():
    prefs.register()   # before the preferences class, which points at its settings
    rig_switches_ui.register()
    bpy.types.WindowManager.digit_tool = EnumProperty(
        name="Tool", items=TOOL_ITEMS, default=tool_id(sorted_tools()[0][1]),
        description="Which tool the panel shows")
    bpy.types.Scene.whole_keep_collections = StringProperty(
        name="Keep Collections",
        description="Comma separated collection names whose objects are never merged or deleted (WIP)")
    bpy.types.Scene.whole_remove_hidden = BoolProperty(
        name="Remove hidden child items", default=False,
        description=REMOVE_HIDDEN_HELP)
    bpy.types.Scene.whole_output_name = of.name_property()
    bpy.types.Scene.whole_output_folder = of.folder_property()
    bpy.types.Scene.whole_drop_normals = BoolProperty(
        name="Clear custom normals", default=False, description=DROP_NORMALS_HELP)
    for cls in classes:
        bpy.utils.register_class(cls)
    CHAIN_TOOL.register()
    weight_tools_ui.register()
    oops_ui.register()
    drivers_ui.register()
    fast_viewport.register()
    origin_tool.register()
    composition_overlay.register()
    save_pose.register()
    look_at.register()
    move_alone.register()
    rig_stress_ui.register()
    pose_shape_keys.register()
    pose_as_rest_ui.register()
    face_rig_ui.register()
    limbs_ui.register()
    full_rig_ui.register()
    rig_component_ui.register()
    rename_ui.register()
    span_ui.register()
    bbone_builder_ui.register()
    game_rig_ui.register()
    combine_bones_ui.register()
    bone_workshop_ui.register()
    helper_object_ui.register()
    mirrored_mesh_ui.register()
    path_generators.register()
    rig_placement.register()
    camera_rig.register()
    light_rig.register()
    hdri_world.register()
    digit_world_library.add_library()
    bounce_cards.register()
    photo_backdrop.register()
    shadow_catcher.register()
    catchlight.register()
    pose_ops.register()
    rig_panel_ops.register()
    bones_in_front.register()
    procedural_baker.register()
    select_non_manifold_smart.register()
    mirror_pivot.register()
    mirror_pivot_tools.register()
    placement_tool.register()
    f3_menus.register()
    uv_rebake_ui.register()
    texture_studio_ui.register()
    decal_recipe.register()
    decal_state_ops.register()
    decal_layer_ops.register()
    decal_import_ops.register()
    decal_drop.register()
    decal_gizmo.register()


def unregister():
    decal_gizmo.unregister()
    decal_drop.unregister()
    decal_import_ops.unregister()
    decal_layer_ops.unregister()
    decal_state_ops.unregister()
    decal_recipe.unregister()
    texture_studio_ui.unregister()
    uv_rebake_ui.unregister()
    f3_menus.unregister()
    placement_tool.unregister()
    mirror_pivot_tools.unregister()
    mirror_pivot.unregister()
    select_non_manifold_smart.unregister()
    procedural_baker.unregister()
    bones_in_front.unregister()
    rig_panel_ops.unregister()
    pose_ops.unregister()
    rig_switches_ui.unregister()
    catchlight.unregister()
    shadow_catcher.unregister()
    photo_backdrop.unregister()
    bounce_cards.unregister()
    digit_world_library.remove_library()
    hdri_world.unregister()
    light_rig.unregister()
    camera_rig.unregister()
    rig_placement.unregister()
    path_generators.unregister()
    mirrored_mesh_ui.unregister()
    helper_object_ui.unregister()
    bone_workshop_ui.unregister()
    combine_bones_ui.unregister()
    game_rig_ui.unregister()
    bbone_builder_ui.unregister()
    span_ui.unregister()
    rename_ui.unregister()
    rig_component_ui.unregister()
    full_rig_ui.unregister()
    limbs_ui.unregister()
    face_rig_ui.unregister()
    CHAIN_TOOL.unregister()
    pose_as_rest_ui.unregister()
    pose_shape_keys.unregister()
    move_alone.unregister()
    look_at.unregister()
    rig_stress_ui.unregister()
    save_pose.unregister()
    fast_viewport.unregister()
    origin_tool.unregister()
    composition_overlay.unregister()
    drivers_ui.unregister()
    oops_ui.unregister()
    weight_tools_ui.unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.whole_keep_collections
    del bpy.types.Scene.whole_remove_hidden
    del bpy.types.Scene.whole_drop_normals
    del bpy.types.Scene.whole_output_name
    del bpy.types.Scene.whole_output_folder
    del bpy.types.WindowManager.digit_tool
    prefs.unregister()
