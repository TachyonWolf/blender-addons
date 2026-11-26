# SPDX-License-Identifier: GPL-3.0-or-later
"""Live Look controls, scene data only (no UI): the applied compositor chain's group nodes (found by
node label, so any applied preset, built-in or saved, gets them), which of their inputs a driver sets
(Fog Marks), reading their values back for a saved preset, writing a starting look, and the world
colour for Depth Fog's Sample World."""

import bpy

from . import builtin_presets as bp, compositor_chain, fog_marks

FOG_GROUP = "Depth Fog"
FOG_COLOUR = "Fog Colour"
HIDDEN_LOOK = "Off"        # every group has its own On, so the presets' "Off" look isn't offered
SAMPLE_SIZE = (16, 8)      # an environment image is shrunk to this before averaging


# ---------------------------------------------------------------------------
# Chain nodes and drivers
# ---------------------------------------------------------------------------

chain_node = compositor_chain.chain_node   # the one finder of a chain's group node


def driven_inputs(node):
    """Names of the node's inputs a driver sets (they show "from mark" and are never written)."""
    animation = node.id_data.animation_data
    if animation is None or not animation.drivers:
        return set()
    return {socket.name for socket in node.inputs if fog_marks.is_driven(node, socket.name)}


def plain_value(value):
    """A socket value as JSON-friendly data (colours as lists, floats rounded)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, int):
        return value
    return [round(component, 5) for component in value]


def read_look(scene, groups):
    """{group: {input name: value}} of the live, undriven Look inputs of these groups' nodes."""
    look = {}
    for group in groups:
        node = chain_node(scene, group)
        if node is None:
            continue
        driven = driven_inputs(node)
        values = {name: plain_value(node.inputs[name].default_value)
                  for name in bp.LOOK_INPUTS.get(group, ()) if name in node.inputs and name not in driven}
        if values:
            look[group] = values
    return look


def write_values(node, values):
    """Write input values onto a chain node, leaving driven inputs alone."""
    driven = driven_inputs(node)
    return compositor_chain.apply_values(node, {name: value for name, value in values.items() if name not in driven})


# ---------------------------------------------------------------------------
# Starting looks
# ---------------------------------------------------------------------------

def starting_looks(group):
    """The names a group's Start With picker offers ("Off" left out), from the packaged presets module."""
    module = compositor_chain.load_group_presets(group)
    return [name for name in module.PRESETS if name != HIDDEN_LOOK] if module else []


def write_starting_look(scene, group, look_name):
    """Put a starting look onto the live chain node of `group` (nothing when there is none)."""
    node = chain_node(scene, group)
    module = compositor_chain.load_group_presets(group)
    if node is None or module is None or look_name not in module.PRESETS:
        return False
    return write_values(node, module.preset_values(look_name))


# ---------------------------------------------------------------------------
# Sample World (button press only)
# ---------------------------------------------------------------------------

def world_colour(scene):
    """(colour, "") for Depth Fog's Fog Colour from the scene's world, or (None, why not).
    Background colour when unlinked, else the average of the environment image feeding it, else the
    world's own colour when it has no Background node."""
    world = scene.world
    if world is None:
        return None, "This scene has no world"
    background = _background_node(world)
    if background is None:
        return (*world.color, 1.0), ""
    colour_input = background.inputs["Color"]
    if not colour_input.is_linked:
        return tuple(colour_input.default_value), ""
    source = colour_input.links[0].from_node
    image = getattr(source, "image", None) if source.bl_idname == "ShaderNodeTexEnvironment" else None
    if image is None:
        return None, "The world colour comes from nodes that can't be sampled; pick the colour by hand"
    return average_image_colour(image), ""


def _background_node(world):
    tree = world.node_tree
    if tree is None:
        return None
    return next((node for node in tree.nodes if node.bl_idname == "ShaderNodeBackground"), None)


def average_image_colour(image):
    """The mean colour of a shrunk copy of an image (the original is untouched)."""
    copy = image.copy()
    try:
        copy.scale(*SAMPLE_SIZE)
        pixels = list(copy.pixels)
    finally:
        bpy.data.images.remove(copy)
    count = max(1, len(pixels) // 4)
    return tuple(sum(pixels[channel::4]) / count for channel in range(3)) + (1.0,)
