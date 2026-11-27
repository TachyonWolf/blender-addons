# SPDX-License-Identifier: GPL-3.0-or-later
"""Which objects are glass / transparent, ONE detector for both Performance options (raytracing off hides GLASS;
"hide transparent" hides GLASS and CLEAR). Per material, flags:
- GLASS: a Glass or Refraction BSDF, or a Principled BSDF with Transmission Weight above the threshold (looks wrong
  without EEVEE raytracing, e.g. Digit's Visor).
- CLEAR: Principled Alpha below 1 or linked (a texture), a Transparent BSDF, or the material's render method is
  Blended (blend_method before 4.2).
An object whose slots are only partly glass is listed apart: only those faces are hidden (glass_faces.py).
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


def split_objects(scene, wanted, memo=None, also_shown=frozenset()):
    """(whole, parts) of the visible objects of the scene that carry a material with any of the `wanted` flags:
    `whole` = objects where EVERY slot has one; `parts` = [(object, [slot indices that have one])] for the others (a
    character mesh with a glass visor slot). Objects named in `also_shown` (full names) count as visible: the ones
    hidden for VR stay on the list while they still qualify."""
    memo = {} if memo is None else memo
    whole, parts = [], []
    for ob in scene.objects:
        if not (ob.visible_get() or ob.name_full in also_shown):
            continue
        slots = [index for index, slot in enumerate(ob.material_slots) if material_flags(slot.material, memo) & wanted]
        if len(slots) == len(ob.material_slots) and slots:
            whole.append(ob)
        elif slots:
            parts.append((ob, slots))
    return whole, parts


def objects_with(scene, wanted, memo=None, also_shown=frozenset()):
    """Every object split_objects() finds, whole and partly."""
    whole, parts = split_objects(scene, wanted, memo, also_shown)
    return whole + [ob for ob, _slots in parts]


GLASS_ONLY = frozenset({GLASS})               # Raytracing Off hides these
GLASS_OR_CLEAR = frozenset({GLASS, CLEAR})    # Hide transparent materials hides these


def glass_objects(scene, memo=None, also_shown=frozenset()):
    return objects_with(scene, GLASS_ONLY, memo, also_shown)


def transparent_objects(scene, memo=None, also_shown=frozenset()):
    return objects_with(scene, GLASS_OR_CLEAR, memo, also_shown)
