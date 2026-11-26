"""Compositor part of a render preset: a chain of the Library's compositor node groups (Render Polish,
Depth Fog, Lens Effects, Film Look), wired Render Layers > chain > output. Pure scene data, no UI.

Preset keys: "compositor_chain": [group names]; optional "compositor_presets": {group: preset name}
(each group's starting looks, from the packaged *_presets.py modules); optional "look":
{group: {input name: value}} (saved live tweaks, written after the starting look). Old files without
"look" load as before.

Replaces: a scene's existing compositor tree (the user's, or an earlier preset's) is swapped for the chain. The user's
tree is kept (fake user) and put back by Revert; an earlier preset's tree is simply removed (no stacking).
Revert removes exactly what apply added and turns passes it enabled back off.
"""
import json
import os

import bpy

from . import (compositor_common, depth_fog_presets, film_look_presets, lens_effects_presets, local_defaults,
               modifier_setup as ms, render_polish_presets)

PROJECT = os.path.expanduser(local_defaults.get("project_folder", "~/Blender"))
LIBRARY_DIR = os.path.join(PROJECT, "Library")      # fallback when no asset library has the file
GROUP_PRESET_MODULES = {"Render Polish": render_polish_presets, "Depth Fog": depth_fog_presets,
                        "Film Look": film_look_presets, "Lens Effects": lens_effects_presets}
# group -> [(Render Layers output, view layer flag)]; Position feeds Depth Fog's Height Fade
GROUP_NEEDS_PASS = {"Depth Fog": [("Depth", "use_pass_z"), ("Position", "use_pass_position")]}
GROUP_VERSIONS = {"Render Polish": ("render_polish_version", 2)}   # group -> (custom property, version the Library has)
LOOK_KEY = "look"                         # preset key: {group: {input name: value}}
STATE_KEY = "render_presets_compositor"   # scene custom property: JSON of what apply added
NOTE_KEY = "render_presets_compositor_note"
TREE_NAME = "Compositing"
STEP = 300


def wants_compositor(preset):
    return bool(preset.get("compositor_chain"))


def group_file(name):
    filename = name.replace(" ", "") + ".blend"
    return ms.library_file(filename) or os.path.join(LIBRARY_DIR, filename)


def load_group_presets(name):
    """The packaged presets module for a group (PRESETS, apply_preset(node, name)), or None."""
    return GROUP_PRESET_MODULES.get(name)


def apply_values(node, values):
    """compositor_common.apply_values (the one input setter): returns the input names written. Prints an
    error when there were values but none of the node's inputs matched."""
    written = compositor_common.apply_values(node, values)
    if values and not written:
        print(f"render_presets: no input of '{node.name}' matched any of {sorted(values)}; nothing written")
    return written


def current_tree(scene):
    return scene.compositing_node_group


def chain_node(scene, group_name):
    """The group node labelled `group_name` in the scene's compositor, or None."""
    tree = current_tree(scene)
    if tree is None:
        return None
    return next((node for node in tree.nodes
                 if node.bl_idname == "CompositorNodeGroup" and node.label == group_name), None)


def is_trivial(tree):
    return tree is None or len(tree.nodes) == 0


def chain_groups_in(tree):
    """The chain group names (node labels) in a compositor tree, left to right."""
    if tree is None:
        return []
    nodes = sorted((node for node in tree.nodes if node.bl_idname == "CompositorNodeGroup"
                    and node.label in GROUP_PRESET_MODULES), key=lambda node: node.location.x)
    return [node.label for node in nodes]


def remove_group(scene, group_name):
    """Take the chain group `group_name` out of the scene's compositor and join its neighbours: whatever fed
    its Image input now feeds what its Image output fed (the rest of the chain keeps working). Its drivers
    (Fog Marks) go too; the group datablock is dropped when nothing else uses it. True if a node was removed."""
    tree = current_tree(scene)
    node = chain_node(scene, group_name)
    if tree is None or node is None:
        return False
    source = next((link.from_socket for link in tree.links if link.to_socket == node.inputs["Image"]), None)
    targets = [link.to_socket for link in tree.links if link.from_socket == node.outputs["Image"]]
    if source is not None:
        for target in targets:
            tree.links.new(source, target)
    prefix = f'nodes["{node.name}"]'
    animation = tree.animation_data
    for fcurve in list(animation.drivers) if animation else ():
        if fcurve.data_path.startswith(prefix):
            animation.drivers.remove(fcurve)
    group = node.node_tree
    tree.nodes.remove(node)
    if group is not None and group.library is None and group.users - int(group.use_fake_user) == 0:
        bpy.data.node_groups.remove(group)
    return True


LIGHT_VIEW_MODES = ('DISABLED', 'CAMERA')   # the viewport compositor modes that stay cheap (never 'ALWAYS')


def lighten_viewports():
    """Every 3D view in the file: compositor 'ALWAYS' becomes 'CAMERA'. Returns how many views changed."""
    changed = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D' and space.shading.use_compositor not in LIGHT_VIEW_MODES:
                    space.shading.use_compositor = 'CAMERA'
                    changed += 1
    return changed


def lighten_for_data(scene):
    """Light data-file compositor: no Depth Fog in the scene's chain, no 'ALWAYS' 3D views (the file's).
    Returns notes on what changed (empty = nothing to do)."""
    notes = []
    if remove_group(scene, "Depth Fog"):
        notes.append("fog-removed")
    return notes


def replace_node_count(scene, preset):
    """How many compositor nodes applying this preset would replace (0 = nothing to confirm)."""
    tree = current_tree(scene)
    return 0 if not wants_compositor(preset) or is_trivial(tree) else len(tree.nodes)


def apply_chain(scene, preset):
    """Build the preset's chain in the scene's compositor. Returns a note for the user ("" = done silently)."""
    chain = preset.get("compositor_chain")
    if not chain:
        return ""
    revert_chain(scene)   # an earlier preset's chain goes; the user's own tree it replaced comes back first
    for name in chain:
        _retire_outdated_group(name)
    groups_before = set(bpy.data.node_groups.keys())
    groups = {}
    for name in chain:
        groups[name] = ms.append_group(name, group_file(name))
        if groups[name] is None:
            _discard_new_groups(groups_before)
            return f"Compositor not set up: node group {name!r} not found in the Library"
    state = {"new_groups": sorted(set(bpy.data.node_groups.keys()) - groups_before),
             "passes": []}
    tree = bpy.data.node_groups.new(TREE_NAME, "CompositorNodeTree")
    state["tree"] = tree.name
    old = current_tree(scene)
    if not is_trivial(old):
        state["original"] = {"name": old.name, "fake_user": old.use_fake_user}
        old.use_fake_user = True   # keeps it alive while the scene points elsewhere
    scene.compositing_node_group = tree
    _build(scene, tree, chain, groups, preset, state)
    scene[STATE_KEY] = json.dumps(state)
    return ""


def _retire_outdated_group(name):
    """A copy of the group already in this file that is older than the Library's (it lacks the newer
    inputs) is renamed "<name> (old)", so the Library version gets appended instead. Scenes using the
    old copy keep working."""
    key_version = GROUP_VERSIONS.get(name)
    group = bpy.data.node_groups.get(name)
    if key_version and group is not None and group.library is None and group.get(key_version[0], 0) < key_version[1]:
        group.name = f"{name} (old)"


def _build(scene, tree, chain, groups, preset, state):
    view_layer = scene.view_layers[0]
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    render_layers.scene = scene
    render_layers.layer = view_layer.name
    render_layers.location = (0, 0)
    previous = render_layers.outputs["Image"]
    for i, name in enumerate(chain):
        node = tree.nodes.new("CompositorNodeGroup")
        node.node_tree = groups[name]
        node.label = name
        node.location = ((i + 1) * STEP, 0)
        for output_name, flag in GROUP_NEEDS_PASS.get(name, ()):
            if not getattr(view_layer, flag):
                setattr(view_layer, flag, True)
                state["passes"].append([view_layer.name, flag])
            tree.links.new(render_layers.outputs[output_name], node.inputs[output_name])
        _apply_starting_look(node, name, preset)
        tree.links.new(previous, node.inputs["Image"])
        previous = node.outputs["Image"]
    x = (len(chain) + 1) * STEP
    tree.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    out = tree.nodes.new("NodeGroupOutput")
    out.location = (x, 100)
    tree.links.new(previous, out.inputs["Image"])
    viewer = tree.nodes.new("CompositorNodeViewer")
    viewer.location = (x, -100)
    tree.links.new(previous, viewer.inputs["Image"])


def _apply_starting_look(node, group_name, preset):
    """The group's starting look ("compositor_presets"), then the preset's saved input values ("look")."""
    preset_name = preset.get("compositor_presets", {}).get(group_name)
    module = load_group_presets(group_name) if preset_name else None
    if module is not None and preset_name in module.PRESETS:
        module.apply_preset(node, preset_name)
    values = preset.get(LOOK_KEY, {}).get(group_name)
    if values:
        apply_values(node, values)


def _discard_new_groups(groups_before):
    for name in set(bpy.data.node_groups.keys()) - groups_before:
        bpy.data.node_groups.remove(bpy.data.node_groups[name])


def revert_chain(scene):
    """Remove what apply_chain added (tree, appended groups, passes it turned on)."""
    state = json.loads(scene.get(STATE_KEY, "{}"))
    if state:
        tree = bpy.data.node_groups.get(state["tree"])
        original = bpy.data.node_groups.get(state.get("original", {}).get("name", ""))
        if original is not None:
            original.use_fake_user = state["original"]["fake_user"]
            scene.compositing_node_group = original
        elif tree is not None and current_tree(scene) == tree:
            scene.compositing_node_group = None
        if tree is not None:
            bpy.data.node_groups.remove(tree)
        for name in state["new_groups"]:
            group = bpy.data.node_groups.get(name)
            if group is not None:
                bpy.data.node_groups.remove(group)
        for layer_name, flag in state["passes"]:
            layer = scene.view_layers.get(layer_name)
            if layer is not None:
                setattr(layer, flag, False)
    for key in (STATE_KEY, NOTE_KEY):
        if key in scene:
            del scene[key]
