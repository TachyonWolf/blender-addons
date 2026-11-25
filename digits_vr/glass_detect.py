# SPDX-License-Identifier: GPL-3.0-or-later
"""Which objects are glass / transparent, ONE detector for both Performance options (raytracing off hides GLASS;
"hide transparent" hides GLASS and CLEAR). Per material, flags:
- GLASS: a Glass or Refraction BSDF, or a Principled BSDF with Transmission Weight above the threshold (looks wrong
  without EEVEE raytracing, e.g. Digit's Visor).
- CLEAR: Principled Alpha below 1 or linked (a texture), a Transparent BSDF, or the material's render method is
  Blended (blend_method before 4.2).
Looks into node groups. A node counts even when it is not wired to the output (cheap, errs towards hiding)."""
TRANSMISSION_LIMIT = 0.3
GLASS, CLEAR = "glass", "clear"
GLASS_NODE_TYPES = frozenset({'BSDF_GLASS', 'BSDF_REFRACTION'})
MAX_GROUP_DEPTH = 4
NO_FLAGS = frozenset()


def _principled_flags(node):
    flags = set()
    transmission = node.inputs.get("Transmission Weight")
    if transmission is not None and not transmission.is_linked and transmission.default_value > TRANSMISSION_LIMIT:
        flags.add(GLASS)
    alpha = node.inputs.get("Alpha")
    if alpha is not None and (alpha.is_linked or alpha.default_value < 1.0):
        flags.add(CLEAR)
    return flags


def _tree_flags(tree, depth, seen):
    flags = set()
    if tree is None or id(tree) in seen:
        return flags
    seen.add(id(tree))
    for node in tree.nodes:
        if node.type in GLASS_NODE_TYPES:
            flags.add(GLASS)
        elif node.type == 'BSDF_TRANSPARENT':
            flags.add(CLEAR)
        elif node.type == 'BSDF_PRINCIPLED':
            flags |= _principled_flags(node)
        elif node.type == 'GROUP' and depth < MAX_GROUP_DEPTH:
            flags |= _tree_flags(node.node_tree, depth + 1, seen)
    return flags


def _blended(material):
    method = getattr(material, "surface_render_method", None) or getattr(material, "blend_method", None)
    return method in ('BLENDED', 'BLEND')


def material_flags(material, memo=None):
    """frozenset of GLASS / CLEAR for one material (memo: dict of name -> flags, to share work between objects)."""
    if material is None:
        return NO_FLAGS
    key = material.name_full
    if memo is not None and key in memo:
        return memo[key]
    flags = set(_tree_flags(material.node_tree, 0, set())) if material.use_nodes else set()
    if _blended(material):
        flags.add(CLEAR)
    result = frozenset(flags)
    if memo is not None:
        memo[key] = result
    return result


def objects_with(scene, wanted, memo=None):
    """The visible objects of the scene that carry a material with any of the `wanted` flags."""
    memo = {} if memo is None else memo
    return [ob for ob in scene.objects
            if ob.visible_get() and any(material_flags(slot.material, memo) & wanted for slot in ob.material_slots)]


def glass_objects(scene, memo=None):
    return objects_with(scene, frozenset({GLASS}), memo)


def transparent_objects(scene, memo=None):
    return objects_with(scene, frozenset({GLASS, CLEAR}), memo)
