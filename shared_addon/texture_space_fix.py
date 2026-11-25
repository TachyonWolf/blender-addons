"""Keep Texture Coordinate > Object patterns in place when a scale is applied.

Applying an object's scale changes its object space, so a material that reads Texture Coordinate > Object (no object
set) shifts and resizes its pattern. Convention (the same as the hand-made fix in the Cafe file):
- the object has a custom property `applied_scale_fix` (3 floats); a missing property reads as 0 in the Attribute node;
- the material multiplies the Object coordinates by (1 + applied_scale_fix): Attribute > Vector Math ADD (1, 1, 1) >
  Vector Math MULTIPLY with the TexCoord Object output > the old targets.
Direction: applying scale S (old) so the new scale is S' bakes S/S' into the mesh, so the object coordinates of a surface
point become old * S / S'. The fix multiplies them back, so (1 + fix) = S' / S (composed with an earlier fix).
Only scale is compensated; rotation applies also move Object coordinates and are not handled here.
Library and override materials cannot be edited and are skipped (with a note when the caller passes `notes`).
"""

from contextlib import contextmanager

import bpy

FIX_PROPERTY = "applied_scale_fix"
ATTRIBUTE_LABEL, ADD_LABEL, MULTIPLY_LABEL = "Applied scale fix", "1 + fix", "Old object coords"
EPSILON = 1e-6


def editable(datablock):
    return datablock is not None and not datablock.library and not datablock.override_library


def tree_with_groups(node_tree, found=None):
    """`node_tree` and every node group inside it, recursively (each once)."""
    found = [] if found is None else found
    if node_tree in found:
        return found
    found.append(node_tree)
    for node in node_tree.nodes:
        if node.bl_idname == 'ShaderNodeGroup' and node.node_tree is not None:
            tree_with_groups(node.node_tree, found)
    return found


def material_trees(ob):
    """(editable trees, blocked material names) of the materials on `ob`, node groups included."""
    trees, blocked = [], []
    for slot in ob.material_slots:
        material = slot.material
        if material is None or not material.use_nodes or material.node_tree is None:
            continue
        if not editable(material) or not editable(material.node_tree):
            blocked.append(material.name)
            continue
        for tree in tree_with_groups(material.node_tree):
            if tree not in trees:
                trees.append(tree)
    return trees, blocked


def object_coordinate_nodes(node_tree):
    """The Texture Coordinate nodes with no object set whose Object output is linked."""
    return [node for node in node_tree.nodes
            if node.bl_idname == 'ShaderNodeTexCoord' and node.object is None and node.outputs['Object'].is_linked]


def is_fix_attribute(node):
    return node.bl_idname == 'ShaderNodeAttribute' and node.attribute_type == 'OBJECT' and node.attribute_name == FIX_PROPERTY


def feeds_fix(texture_node):
    """True when the Object output already goes into a MULTIPLY whose other input is 1 + the fix attribute."""
    for link in texture_node.outputs['Object'].links:
        node = link.to_node
        if node.bl_idname != 'ShaderNodeVectorMath' or node.operation != 'MULTIPLY':
            continue
        for socket in node.inputs[:2]:
            if socket.is_linked and socket.links[0].from_node.bl_idname == 'ShaderNodeVectorMath' \
                    and socket.links[0].from_node.operation == 'ADD' \
                    and any(is_fix_attribute(add_input.links[0].from_node) for add_input in socket.links[0].from_node.inputs[:2]
                            if add_input.is_linked):
                return True
    return False


def add_fix_nodes(node_tree, texture_node):
    targets = [link.to_socket for link in texture_node.outputs['Object'].links]
    for target in targets:
        node_tree.links.remove(next(link for link in target.links if link.from_node == texture_node))
    x, y = texture_node.location
    attribute = node_tree.nodes.new('ShaderNodeAttribute')
    attribute.attribute_type, attribute.attribute_name, attribute.label = 'OBJECT', FIX_PROPERTY, ATTRIBUTE_LABEL
    attribute.location = (x + 200, y - 260)
    add = node_tree.nodes.new('ShaderNodeVectorMath')
    add.operation, add.label, add.location = 'ADD', ADD_LABEL, (x + 400, y - 260)
    add.inputs[1].default_value = (1.0, 1.0, 1.0)
    multiply = node_tree.nodes.new('ShaderNodeVectorMath')
    multiply.operation, multiply.label, multiply.location = 'MULTIPLY', MULTIPLY_LABEL, (x + 600, y)
    node_tree.links.new(attribute.outputs['Vector'], add.inputs[0])
    node_tree.links.new(texture_node.outputs['Object'], multiply.inputs[0])
    node_tree.links.new(add.outputs['Vector'], multiply.inputs[1])
    for target in targets:
        node_tree.links.new(multiply.outputs['Vector'], target)


def ensure_fix_nodes(node_tree):
    """Insert the fix after every Object-coordinate output that lacks it. Returns True when the tree reads Object
    coordinates at all (fixed now or before)."""
    nodes = object_coordinate_nodes(node_tree)
    for texture_node in nodes:
        if not feeds_fix(texture_node):
            add_fix_nodes(node_tree, texture_node)
    return bool(nodes)


def object_coordinate_trees(ob):
    """The trees of `ob`'s materials (groups included) that read Object coordinates, after making sure each has the fix
    nodes; plus the names of materials that could not be edited."""
    trees, blocked = material_trees(ob)
    return [tree for tree in trees if ensure_fix_nodes(tree)], blocked


def current_fix(ob):
    return tuple(ob.get(FIX_PROPERTY, (0.0, 0.0, 0.0)))


def compensate_scale(ob, old_scale, new_scale, notes=None):
    """Set `ob`'s fix so its Object-coordinate materials keep their pattern after the scale went old > new
    ((1 + fix) = new / old, times any earlier (1 + fix)). Returns True when the property changed."""
    if any(abs(old) <= EPSILON or abs(new) <= EPSILON for old, new in zip(old_scale, new_scale)):
        return False
    ratio = [new / old for old, new in zip(old_scale, new_scale)]
    if all(abs(value - 1.0) <= EPSILON for value in ratio):
        return False
    trees, blocked = object_coordinate_trees(ob)
    if notes is not None and blocked:
        notes.append(f"Texture space not kept on {ob.name}: material {', '.join(sorted(set(blocked)))} is linked and can't be edited")
    if not trees:
        return False
    ob[FIX_PROPERTY] = [(1.0 + fix) * value - 1.0 for fix, value in zip(current_fix(ob), ratio)]
    ob.update_tag()
    return True


def objects_sharing_data(objects):
    """`objects` plus every object using the same data (a shared-mesh apply changes all of them)."""
    datas = {ob.data for ob in objects if ob.data is not None}
    return list(dict.fromkeys(list(objects) + [ob for ob in bpy.data.objects if ob.data in datas]))


@contextmanager
def compensating_scale(objects, notes=None):
    """Around an apply-scale: remember the local scales of `objects` and of everything sharing their data, then set
    the fix on each whose scale changed."""
    watched = objects_sharing_data(objects)
    before = {ob: tuple(ob.scale) for ob in watched}
    yield
    changed = False
    for ob, old_scale in before.items():
        if compensate_scale(ob, old_scale, tuple(ob.scale), notes):
            changed = True
    if changed:
        bpy.context.view_layer.update()
