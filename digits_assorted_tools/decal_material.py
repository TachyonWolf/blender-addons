# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: images and materials.

- `ensure_group()`: the ONE shared shader group "Digit Decal" (built here in code, reused by name): map inputs
  (Color + its alpha, Normal, Glow, Roughness, Metal, Alpha, Height) and the Look values (Tint, Opacity, Glow,
  Bump, Roughness). The Look sliders in the card draw this node's inputs directly (one source per value).
- `make_material(name, images)`: a decal's own material (own Look values), images shared between decals.
- `set_map` / `map_image`: a map slot of a material, by role (decal_maps.ROLES).
- `load_image(path, role)`: loads (or reuses) an image, Non-Color for data roles.
- `visible_crop(color, alpha)`: the visible rectangle of a decal's image (one pixel read, numpy).
Render method Dithered; image nodes use Extension CLIP so nothing tiles outside the crop."""

import bpy
import numpy as np

from . import decal_maps
from .decal_nodes import FADE_ATTRIBUTE

GROUP_NAME = "Digit Decal"
GROUP_NODE = "Digit Decal"         # name of the group node inside every decal material
MAP_NODE = "Map {}"                # image node name per role
# role -> (group input fed by the image's Color output, group input fed by its Alpha output or None)
MAP_INPUTS = {"COLOR": ("Color", "Color Alpha"), "NORMAL": ("Normal", None), "GLOW": ("Glow Color", None),
              "ROUGHNESS": ("Roughness Map", None), "METAL": ("Metallic", None), "ALPHA": ("Alpha", None),
              "HEIGHT": ("Height", None)}
# the back map set (seen from behind, chosen by Backfacing): role BACK_<role> feeds "Back <input>"
BACK = "Back {}"
MAP_INPUTS.update({decal_maps.back_role(role): (BACK.format(color), alpha and BACK.format(alpha))
                   for role, (color, alpha) in list(MAP_INPUTS.items())})
HAS_BACK = "Has Back"              # 1 = the back maps show from behind; 0 = the front maps on both sides
USE_ROUGHNESS_MAP = "Use Roughness Map"
FADE_OUT = "Fade Out"               # 1 = faded away (from the decal's fade attribute, see decal_nodes)
FADE_NODE = "Decal Fade"
UNLIT = "Unlit"                    # 1 = the colour shown as it is (emission 1), not lit by the scene
# Look inputs the card shows, in mockup order: (input name, label)
LOOK_INPUTS = (("Tint", "Tint"), ("Opacity", "Opacity"), ("Glow", "Glow"), ("Bump", "Bump"),
               ("Roughness", "Roughness"))
# (name, socket type, default, min, max); map inputs first, then the Look values
GROUP_INPUTS = (("Color", 'NodeSocketColor', (1, 1, 1, 1), None, None),
                ("Color Alpha", 'NodeSocketFloat', 1.0, 0.0, 1.0),
                ("Alpha", 'NodeSocketFloat', 1.0, 0.0, 1.0),
                ("Normal", 'NodeSocketColor', (0.5, 0.5, 1.0, 1.0), None, None),
                ("Glow Color", 'NodeSocketColor', (0, 0, 0, 1), None, None),
                ("Roughness Map", 'NodeSocketFloat', 0.5, 0.0, 1.0),
                (USE_ROUGHNESS_MAP, 'NodeSocketFloat', 0.0, 0.0, 1.0),
                ("Metallic", 'NodeSocketFloat', 0.0, 0.0, 1.0),
                ("Height", 'NodeSocketFloat', 0.0, None, None),
                ("Tint", 'NodeSocketColor', (1, 1, 1, 1), None, None),
                ("Opacity", 'NodeSocketFloat', 1.0, 0.0, 1.0),
                ("Glow", 'NodeSocketFloat', 2.0, 0.0, 100.0),
                ("Bump", 'NodeSocketFloat', 1.0, 0.0, 10.0),
                ("Roughness", 'NodeSocketFloat', 0.5, 0.0, 1.0),
                (UNLIT, 'NodeSocketFloat', 0.0, 0.0, 1.0),
                (FADE_OUT, 'NodeSocketFloat', 0.0, 0.0, 1.0))
# the map inputs that have a back twin, and the back inputs themselves (same type and default)
SIDED_INPUTS = ("Color", "Color Alpha", "Alpha", "Normal", "Glow Color", "Roughness Map", "Metallic", "Height")
GROUP_INPUTS += tuple((BACK.format(name), *rest) for name, *rest in GROUP_INPUTS if name in SIDED_INPUTS) + (
    (HAS_BACK, 'NodeSocketFloat', 0.0, 0.0, 1.0),)


def ensure_group():
    """The shared Digit Decal shader group: reused when it is up to date, built when missing, and brought up to
    date in place when an older file's group lacks an input (inputs are only added, so materials keep their
    links; the inside is rebuilt)."""
    group = bpy.data.node_groups.get(GROUP_NAME)
    if group is not None and group.bl_idname == 'ShaderNodeTree':
        if _add_missing_sockets(group):
            group.nodes.clear()
            _build_group_nodes(group)
        return group
    group = bpy.data.node_groups.new(GROUP_NAME, 'ShaderNodeTree')
    _add_missing_sockets(group)
    _build_group_nodes(group)
    return group


def _add_missing_sockets(group):
    """Add the GROUP_INPUTS (and the Shader output) the group lacks. True when any was added."""
    have = {item.name for item in group.interface.items_tree if item.item_type == 'SOCKET'}
    added = False
    for name, socket_type, default, minimum, maximum in GROUP_INPUTS:
        if name in have:
            continue
        socket = group.interface.new_socket(name, in_out='INPUT', socket_type=socket_type)
        socket.default_value = default
        if minimum is not None:
            socket.min_value, socket.max_value = minimum, maximum
        added = True
    if "Shader" not in have:
        group.interface.new_socket("Shader", in_out='OUTPUT', socket_type='NodeSocketShader')
        added = True
    return added


def _build_group_nodes(group):
    nodes, links = group.nodes, group.links
    inputs = nodes.new('NodeGroupInput')
    output = nodes.new('NodeGroupOutput')
    output.location = (900, 0)
    side = _sides(nodes, links, inputs)
    tinted = nodes.new('ShaderNodeMix')
    tinted.data_type, tinted.blend_type = 'RGBA', 'MULTIPLY'
    tinted.inputs["Factor"].default_value = 1.0
    links.new(side("Color"), tinted.inputs["A"])
    links.new(inputs.outputs["Tint"], tinted.inputs["B"])
    alpha = _math(nodes, links, 'MULTIPLY', side("Color Alpha"), side("Alpha"))
    alpha = _math(nodes, links, 'MULTIPLY', alpha.outputs[0], inputs.outputs["Opacity"])
    shown = nodes.new('ShaderNodeMath')
    shown.operation = 'SUBTRACT'
    shown.inputs[0].default_value = 1.0
    links.new(inputs.outputs[FADE_OUT], shown.inputs[1])
    alpha = _math(nodes, links, 'MULTIPLY', alpha.outputs[0], shown.outputs[0])
    roughness = nodes.new('ShaderNodeMix')
    roughness.data_type = 'FLOAT'
    links.new(inputs.outputs[USE_ROUGHNESS_MAP], roughness.inputs["Factor"])
    links.new(inputs.outputs["Roughness"], roughness.inputs["A"])
    links.new(side("Roughness Map"), roughness.inputs["B"])
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(side("Normal"), normal_map.inputs["Color"])
    links.new(inputs.outputs["Bump"], normal_map.inputs["Strength"])
    bump = nodes.new('ShaderNodeBump')
    links.new(side("Height"), bump.inputs["Height"])
    links.new(inputs.outputs["Bump"], bump.inputs["Strength"])
    links.new(normal_map.outputs["Normal"], bump.inputs["Normal"])
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    shader.location = (600, 0)
    links.new(tinted.outputs["Result"], shader.inputs["Base Color"])
    links.new(side("Metallic"), shader.inputs["Metallic"])
    links.new(roughness.outputs["Result"], shader.inputs["Roughness"])
    links.new(alpha.outputs[0], shader.inputs["Alpha"])
    links.new(bump.outputs["Normal"], shader.inputs["Normal"])
    links.new(side("Glow Color"), shader.inputs["Emission Color"])
    links.new(inputs.outputs["Glow"], shader.inputs["Emission Strength"])
    # Unlit: the tinted colour as emission (strength 1) over transparency by alpha, not lit by the scene
    emission = nodes.new('ShaderNodeEmission')
    links.new(tinted.outputs["Result"], emission.inputs["Color"])
    emission.inputs["Strength"].default_value = 1.0
    transparent = nodes.new('ShaderNodeBsdfTransparent')
    unlit = nodes.new('ShaderNodeMixShader')
    links.new(alpha.outputs[0], unlit.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], unlit.inputs[1])
    links.new(emission.outputs["Emission"], unlit.inputs[2])
    choose = nodes.new('ShaderNodeMixShader')
    choose.location = (750, 0)
    links.new(inputs.outputs[UNLIT], choose.inputs["Fac"])
    links.new(shader.outputs["BSDF"], choose.inputs[1])
    links.new(unlit.outputs["Shader"], choose.inputs[2])
    links.new(choose.outputs["Shader"], output.inputs["Shader"])


def _sides(nodes, links, inputs):
    """side(name): the front map input, or its "Back ..." twin where the face is seen from behind and the decal
    has back maps (Backfacing x Has Back). The back normal map's X is flipped: the back shot is mirrored."""
    geometry = nodes.new('ShaderNodeNewGeometry')
    back = _math(nodes, links, 'MULTIPLY', geometry.outputs["Backfacing"], inputs.outputs[HAS_BACK])
    made = {}

    def back_socket(name):
        socket = inputs.outputs[BACK.format(name)]
        if name != "Normal":
            return socket
        split = nodes.new('ShaderNodeSeparateColor')
        links.new(socket, split.inputs["Color"])
        flipped = nodes.new('ShaderNodeMath')
        flipped.operation = 'SUBTRACT'
        flipped.inputs[0].default_value = 1.0
        links.new(split.outputs["Red"], flipped.inputs[1])
        join = nodes.new('ShaderNodeCombineColor')
        links.new(flipped.outputs[0], join.inputs["Red"])
        links.new(split.outputs["Green"], join.inputs["Green"])
        links.new(split.outputs["Blue"], join.inputs["Blue"])
        return join.outputs["Color"]

    def side(name):
        if name not in made:
            front = inputs.outputs[name]
            mix = nodes.new('ShaderNodeMix')
            mix.data_type = 'RGBA' if front.type == 'RGBA' else 'FLOAT'
            links.new(back.outputs[0], mix.inputs["Factor"])
            links.new(front, mix.inputs["A"])
            links.new(back_socket(name), mix.inputs["B"])
            made[name] = mix.outputs["Result"]
        return made[name]
    return side


def _math(nodes, links, operation, first, second):
    node = nodes.new('ShaderNodeMath')
    node.operation = operation
    links.new(first, node.inputs[0])
    links.new(second, node.inputs[1])
    return node


def make_material(name, images):
    """A new decal material `name` with the shared group and an image node per {role: image}."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.surface_render_method = 'DITHERED'
    material.use_backface_culling = False
    material.use_transparent_shadow = True     # never darkens what is under it, even where it casts
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (400, 0)
    group_node = nodes.new('ShaderNodeGroup')
    group_node.node_tree = ensure_group()
    group_node.name = group_node.label = GROUP_NODE
    material.node_tree.links.new(group_node.outputs["Shader"], output.inputs["Surface"])
    for role, image in images.items():
        set_map(material, role, image)
    return material


def shading_of(material):
    """'LIT' or 'UNLIT' of a decal material ('LIT' without the Digit Decal node)."""
    node = look_node(material)
    socket = node.inputs.get(UNLIT) if node is not None else None
    return 'UNLIT' if socket is not None and socket.default_value >= 0.5 else 'LIT'


def set_shading(material, shading):
    """Lit or Unlit (baked): the Digit Decal node's Unlit input is the one home of this choice."""
    node = look_node(material)
    if node is not None and node.inputs.get(UNLIT) is None:
        ensure_group()   # an older file's group: add the Unlit input first
    if node is not None:
        node.inputs[UNLIT].default_value = 1.0 if shading == 'UNLIT' else 0.0


def ensure_fade_input(material):
    """Feed the decal's fade attribute into the Digit Decal node (added once; older materials get it too)."""
    node = look_node(material)
    if node is None or material.node_tree.nodes.get(FADE_NODE) is not None:
        return
    if node.inputs.get(FADE_OUT) is None:
        ensure_group()
    attribute = material.node_tree.nodes.new('ShaderNodeAttribute')
    attribute.name = attribute.label = FADE_NODE
    attribute.attribute_type = 'GEOMETRY'
    attribute.attribute_name = FADE_ATTRIBUTE
    attribute.location = (-400, 260)
    material.node_tree.links.new(attribute.outputs["Fac"], node.inputs[FADE_OUT])


def look_node(material):
    """The Digit Decal group node of a decal material, or None."""
    if material is None or material.node_tree is None:
        return None
    return material.node_tree.nodes.get(GROUP_NODE)


def has_back(material):
    """True when the decal material has back maps (shown from behind)."""
    return any(map_image(material, decal_maps.back_role(role)) is not None for role, _label in decal_maps.ROLES)


def map_image(material, role):
    """The image in a material's map slot `role`, or None."""
    node = material.node_tree.nodes.get(MAP_NODE.format(role)) if material and material.node_tree else None
    return node.image if node else None


def set_map(material, role, image):
    """Put `image` in the map slot `role` (None empties it)."""
    tree = material.node_tree
    group_node = tree.nodes[GROUP_NODE]
    node = tree.nodes.get(MAP_NODE.format(role))
    color_input, alpha_input = MAP_INPUTS[role]
    if image is None:
        if node is not None:
            tree.nodes.remove(node)
        if role == "ROUGHNESS":
            group_node.inputs[USE_ROUGHNESS_MAP].default_value = 0.0
        if group_node.inputs.get(HAS_BACK) is not None and not has_back(material):
            group_node.inputs[HAS_BACK].default_value = 0.0
        return
    if node is None:
        node = tree.nodes.new('ShaderNodeTexImage')
        node.name = node.label = MAP_NODE.format(role)
        roles = [role_id for role_id, _ in decal_maps.ROLES]
        front = decal_maps.front_role(role)
        node.location = (-400 - 300 * (front != role), -260 * roles.index(front))
    node.image = image
    node.extension = 'CLIP'
    tree.links.new(node.outputs["Color"], group_node.inputs[color_input])
    if alpha_input:
        tree.links.new(node.outputs["Alpha"], group_node.inputs[alpha_input])
    if decal_maps.front_role(role) == "ROUGHNESS":
        group_node.inputs[USE_ROUGHNESS_MAP].default_value = 1.0
    if role != decal_maps.front_role(role):
        group_node.inputs[HAS_BACK].default_value = 1.0
    if role == "COLOR":
        tree.nodes.active = node   # Workbench's Texture colour shows the active image node


def load_image(path, role):
    """Load the image at `path` (reused if already loaded), Non-Color for data roles."""
    image = bpy.data.images.load(path, check_existing=True)
    set_role_colorspace(image, role)
    return image


def set_role_colorspace(image, role):
    if decal_maps.is_data(role):
        image.colorspace_settings.is_data = True


def visible_crop(color_image, alpha_image=None):
    """decal_maps.Crop of the visible part: the Alpha map's red channel when given, else the color image's
    alpha. One pixel read into float32."""
    source = alpha_image or color_image
    width, height = source.size
    if width == 0 or height == 0:
        return decal_maps.Crop(0.0, 0.0, 1.0, 1.0, 1, 1)
    pixels = np.empty(width * height * 4, dtype=np.float32)
    source.pixels.foreach_get(pixels)
    channel = 0 if alpha_image is not None else 3
    return decal_maps.crop_rect(pixels[channel::4].reshape(height, width))
