# SPDX-License-Identifier: GPL-3.0-or-later
"""Setting up a Geometry Nodes modifier on rigged meshes from an add-on button: get the node group
(from a bundled .blend or the asset libraries), put the modifier after the Armature modifier,
fill in its inputs, and make a starter path curve along a posed bone chain.

Shared by the Stretchy Limb and Digit's Modifiers (Setup Helper) extensions (an installed extension can't
import its neighbour). This file is the ONE source; sync_shared.py copies it into each extension
folder as modifier_setup.py (next to the bone_chain.py copy it imports).
"""

import os

import bpy
from mathutils import Matrix

from .bone_chain import chain_bone_names, write_chain_group


def _append(kind, name, blend_path):
    """Datablock `name` of bpy.data.<kind>, appended from blend_path if this file lacks it."""
    collection = getattr(bpy.data, kind)
    block = collection.get(name)
    if block is None and blend_path and os.path.exists(blend_path):
        with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
            setattr(dst, kind, [name] if name in getattr(src, kind) else [])
        block = collection.get(name)
        if block:
            block.use_fake_user = True
            # An append keeps the asset mark: without this, every file that uses the group shows up
            # as one more copy of it in the asset browser (via the "Digit World" library).
            if block.asset_data:
                block.asset_clear()
    return block


def append_group(name, blend_path):
    """Node group `name`, appended from blend_path if this file lacks it (None if not there)."""
    return _append("node_groups", name, blend_path)


def append_material(name, blend_path):
    """Material `name`, appended from blend_path if this file lacks it (None if not there)."""
    return _append("materials", name, blend_path)


def set_first_material_slot(ob, material):
    """Make `material` the object's first material slot (made if missing). The slot is linked to
    the Object, not the mesh: a Geometry Nodes result that is built from scratch carries no mesh
    materials, so only an object-linked slot reaches it."""
    if not ob.material_slots:
        ob.data.materials.append(None)
    slot = ob.material_slots[0]
    slot.link = 'OBJECT'
    slot.material = material


def empty_curve_data(name):
    """A one point curve: for objects that only carry a curve-generating modifier (Spiral Curve, Curve to Knot)."""
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.splines.new('BEZIER')
    return curve


BUNDLED_ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")  # an extension's own .blend files


def library_file(filename):
    """Path of `filename` in the extension's bundled `assets/` folder, else in one of the Preferences'
    asset libraries (the folder or one level down), or None."""
    bundled = os.path.join(BUNDLED_ASSETS, filename)
    if os.path.exists(bundled):
        return bundled
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        root = bpy.path.abspath(lib.path)
        subdirs = [e.path for e in os.scandir(root) if e.is_dir()] if os.path.isdir(root) else []
        for folder in [root] + subdirs:
            path = os.path.join(folder, filename)
            if os.path.exists(path):
                return path
    return None


def modifier_input(mod, name):
    """The input item of a Geometry Nodes modifier by socket name (Blender 5.x: the value is
    `.value`, or `.attribute_name` when `.type` is 'ATTRIBUTE'; not mod["Socket_N"] any more)."""
    ident = next(i.identifier for i in mod.node_group.interface.items_tree
                 if i.item_type == 'SOCKET' and i.in_out == 'INPUT' and i.name == name)
    return getattr(mod.properties.inputs, ident)


MORE_PANEL = "More"   # the closed node group panel / Selected card group holding the inputs that are not main
WIRING_TYPES = ('NodeSocketGeometry', 'NodeSocketObject', 'NodeSocketCollection', 'NodeSocketMaterial', 'NodeSocketString')


def more_inputs(tree, main):
    """The value inputs of a modifier node group that are not in `main` (socket names), in interface order, panelled
    ones included: everything but the wiring (geometry, objects, collections, materials, bone names). The Selected
    card folds these under More and the node group builders put the top-level ones in a closed "More" panel."""
    return [item for item in tree.interface.items_tree
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT'
            and item.socket_type not in WIRING_TYPES and item.name not in main]


def set_modifier_input(mod, name, value, attribute=False):
    """Set a Geometry Nodes modifier input by socket name; attribute=True: value is an attribute
    (vertex group) name."""
    item = modifier_input(mod, name)
    if attribute:
        item.type = 'ATTRIBUTE'
        item.attribute_name = value
    else:
        item.value = value


def set_modifier_value(mod, name, value):
    """Set `name` on any modifier: a socket by name on a Geometry Nodes one, else the property."""
    if mod.type == 'NODES':
        set_modifier_input(mod, name, value)
    else:
        setattr(mod, name, value)


def slot_after_armature(ob, group_prefix):
    """Modifier index for a new one: after the Armature modifier and any modifiers already
    following it whose node group name starts with group_prefix, else at the end."""
    mods = list(ob.modifiers)
    arm = next((i for i, m in enumerate(mods) if m.type == 'ARMATURE'), None)
    if arm is None:
        return len(mods)
    slot = arm + 1
    while slot < len(mods) and mods[slot].type == 'NODES' and mods[slot].node_group \
            and mods[slot].node_group.name.startswith(group_prefix):
        slot += 1
    return slot


def add_after_armature(ob, group, name, group_prefix=None, modifier_type='NODES'):
    """A new modifier placed by slot_after_armature: a Geometry Nodes one with `group` (after
    earlier ones whose group name starts with group_prefix, default the group's name), or with
    group None a built-in `modifier_type` straight after the Armature modifier."""
    slot = slot_after_armature(ob, group_prefix or (group.name if group else "\0"))
    mod = ob.modifiers.new(name, modifier_type)
    if group:
        mod.node_group = group
    ob.modifiers.move(len(ob.modifiers) - 1, slot)
    return mod


def add_before_armature(ob, group, name):
    """A new Geometry Nodes modifier with `group` right before the Armature modifier (after Mirror
    and the like), else at the end."""
    arm = next((i for i, m in enumerate(ob.modifiers) if m.type == 'ARMATURE'), len(ob.modifiers))
    mod = ob.modifiers.new(name, 'NODES')
    mod.node_group = group
    ob.modifiers.move(len(ob.modifiers) - 1, arm)
    return mod


def smooth_handles(points):
    """Bezier handles (left, right) per point for a smooth curve through the points (Catmull-Rom
    tangents; the ends aim at their neighbour)."""
    out = []
    for i, co in enumerate(points):
        before, after = points[max(i - 1, 0)], points[min(i + 1, len(points) - 1)]
        step = (after - before) / (6 if 0 < i < len(points) - 1 else 3)
        out.append((co - step, co + step))
    return out


# Everything that shows an object in a render or the rendered viewport (hide_render alone leaves the rendered viewport).
RENDER_HIDE = ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission", "visible_volume_scatter",
               "visible_shadow")
PROBE_HIDE = ("hide_probe_volume", "hide_probe_sphere", "hide_probe_plane")


def style_helper(ob, in_front=False):
    """Make `ob` a helper object: a wire in the viewport that no render or reflection ever sees. Modifiers still read it."""
    ob.display_type = 'WIRE'
    ob.hide_render = True
    for prop in RENDER_HIDE:
        setattr(ob, prop, False)
    for prop in PROBE_HIDE:
        setattr(ob, prop, True)
    ob.show_in_front = in_front


def parent_keep_world(context, ob, parent, bone=None):
    """Parent `ob` to `parent` (or to its bone `bone`) without moving it in the world."""
    world = ob.matrix_world.copy()
    ob.parent = parent
    if bone:
        ob.parent_type, ob.parent_bone = 'BONE', bone
    context.view_layer.update()
    ob.matrix_world = world


def make_path_curve(context, rig, points, name, parent_bone=None, handles=None, resolution=64,
                    collection=None):
    """Bezier path through world `points` (with (left, right) `handles` per point, else smooth
    ones), parented to the rig's `parent_bone` (else the rig; no rig: not parented) so it follows
    the character, in `collection` (default the rig's, else the scene's). Returns the curve object."""
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = resolution
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points) - 1)
    handles = handles or smooth_handles(points)
    for bp, co, (left, right) in zip(spline.bezier_points, points, handles):
        bp.handle_left_type = bp.handle_right_type = 'FREE'
        bp.co, bp.handle_left, bp.handle_right = co, left, right
    ob = bpy.data.objects.new(name, curve)
    if collection is None:
        collection = rig.users_collection[0] if rig and rig.users_collection else context.scene.collection
    collection.objects.link(ob)
    if rig:
        parent_keep_world(context, ob, rig, parent_bone)  # points are in world space: ob stays at identity
    return ob


# ---------------------------------------------------------------------------
# Stretchy Limb (used by the Stretchy Limb extension and Digit's Modifiers (Setup Helper))
# ---------------------------------------------------------------------------

STRETCHY_GROUP = "Stretchy Limb"


def limb_points(rig, root, mid, tip):
    """World positions of the posed limb: root head, mid head (if any), tip tail."""
    pb = rig.pose.bones
    points = [pb[root].head] + ([pb[mid].head] if mid else []) + [pb[tip].tail]
    return [rig.matrix_world @ p for p in points]


def limb_handles(points):
    """Bezier handles (left, right) per point that trace the modifier's own limb curve: leave the
    root along root>mid, pass mid parallel to root>tip, reach the tip along mid>tip (straight
    without a mid). Matches through_mid() in the Stretchy Limb builder."""
    if len(points) == 2:
        root, tip = points
        step = (tip - root) / 3
        return [(root - step, root + step), (tip - step, tip + step)]
    root, mid, tip = points
    across = (tip - root).normalized()
    to_mid, from_mid = (mid - root) / 3, (tip - mid) / 3
    return [(root - to_mid, root + to_mid),
            (mid - across * (mid - root).length / 3, mid + across * (tip - mid).length / 3),
            (tip - from_mid, tip + from_mid)]


def make_limb_path(context, rig, root, mid, tip, name):
    """Bezier path along the posed limb, ending exactly at the tip (so Stretch 1 looks unchanged
    until it is edited), parented to the root bone's parent bone (else the rig) so it follows
    the character. Returns the new curve object."""
    points = limb_points(rig, root, mid, tip)
    parent_bone = rig.data.bones[root].parent
    return make_path_curve(context, rig, points, name, parent_bone.name if parent_bone else None,
                           handles=limb_handles(points))


def add_stretchy_modifier(ob, group, rig, root, mid, tip, path, selection, end_part):
    """Stretchy Limb modifier after the Armature modifier and any Stretchy Limbs already
    following it (stack: limbs first, torso / neck later)."""
    mod = add_after_armature(ob, group, f"Stretch {root}", STRETCHY_GROUP)
    for name, value in (("Rig", rig), ("Root Bone", root), ("Tip Bone", tip),
                        ("Mid Bone", mid), ("Path", path)):
        set_modifier_input(mod, name, value)
    set_modifier_input(mod, "Selection", selection, attribute=True)
    if end_part:
        set_modifier_input(mod, "End Part", end_part, attribute=True)
    ob.update_tag()
    return mod


def add_stretchy_limb(context, group, rig, root, mid, tip, meshes):
    """Selection group (root bone chain), End Part group (bones below the tip, if any), a Path
    curve along the posed limb and a Stretchy Limb modifier (node group `group`) on each mesh that
    has weights in the chain. Returns (path object, [meshes set up])."""
    bones = rig.data.bones
    chain = chain_bone_names(rig, [bones[root]])
    end_bones = chain_bone_names(rig, bones[tip].children)
    selection, end_part = f"Stretch_{root}", f"StretchEnd_{root}"
    done = []
    for ob in meshes:
        if write_chain_group(ob, chain, selection)[0] == 0:
            ob.vertex_groups.remove(ob.vertex_groups[selection])
            continue
        has_end = bool(end_bones) and write_chain_group(ob, end_bones, end_part)[0] > 0
        if not has_end and end_part in ob.vertex_groups:
            ob.vertex_groups.remove(ob.vertex_groups[end_part])
        done.append(ob)
    if not done:
        return None, done
    path = make_limb_path(context, rig, root, mid, tip, f"StretchPath_{root}")
    for ob in done:
        add_stretchy_modifier(ob, group, rig, root, mid, tip, path, selection,
                              end_part if end_part in ob.vertex_groups else None)
    return path, done
