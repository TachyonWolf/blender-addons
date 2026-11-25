# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/linked_modifiers.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply modifiers on linked (shared) mesh data, which Blender refuses to do. Used by the Oops Debugger's
Modifiers on Linked Data section (per group and Apply All). No UI in here.

For one shared mesh, users whose modifier stacks have the same settings (names ignored) are evaluated ONCE and all take
that one new mesh. A stack that references an object (Mirror object, Boolean, Shrinkwrap target, Geometry Nodes object
inputs...) cannot be compared by its settings: that user is evaluated on its own (the depsgraph result, so it counts
exactly). Results of the same shape then share one mesh. Users without modifiers keep the original mesh. Only the modifiers before the first Armature or Instance Array
modifier are applied: that one and anything after it stay (applying an Instance Array would drop its instanced copies). A user that cannot be applied is skipped with a reason (SKIPS).
Of those, the user can untick modifiers by name for each shared mesh (`unpicked`: {(data name, modifier name)}): the
ticked ones are evaluated alone and removed, the unticked ones stay in place. Applying one below a kept one gives what
Blender's own Apply gives (it applies onto the base mesh), which can differ from what the viewport shows.
"""
from collections import Counter
from dataclasses import dataclass, field

import bpy
import numpy as np

from .instance_array import is_instance_array
from .scene_checks import users_by_data

SHAPE_TOLERANCE = 1e-5   # object-space distance under which two evaluated vertices count as the same

SKIPS = {"not_mesh": "not a mesh", "library": "linked from a library", "shape_keys": "has shape keys",
         "hidden_object": "object hidden or not in the view layer", "muted_modifier": "a modifier is off in viewport and render",
         "only_armature": "nothing before the Armature / Instance Array modifier",
         "none_picked": "no modifier ticked"}


@dataclass
class ApplyResult:
    applied: int = 0                                  # objects whose modifiers were applied
    meshes: int = 0                                   # new meshes made
    skipped: Counter = field(default_factory=Counter)  # reason text -> object count

    def add(self, other):
        self.applied += other.applied
        self.meshes += other.meshes
        self.skipped.update(other.skipped)

    def report(self):
        text = f"Applied modifiers on {self.applied} objects into {self.meshes} meshes"
        if self.skipped:
            text += ". Skipped: " + ", ".join(f"{count} ({reason})" for reason, count in sorted(self.skipped.items()))
        return text


def modifiers_before_armature(ob):
    """The modifiers Apply takes: everything before the first Armature or Instance Array modifier (all without one)."""
    before = []
    for modifier in ob.modifiers:
        if modifier.type == 'ARMATURE' or is_instance_array(modifier):
            break
        before.append(modifier)
    return before


def offered_modifiers(ob):
    """The modifiers of `ob` the user can tick for Apply Modifiers (see modifiers_before_armature)."""
    return modifiers_before_armature(ob)


def offered_names(users):
    """The names of the offered modifiers of every user of one shared mesh, once each, in stack order."""
    return list(dict.fromkeys(modifier.name for ob in users for modifier in offered_modifiers(ob)))


def picked_modifiers(ob, unpicked=frozenset()):
    """The offered modifiers of `ob` that are still ticked for its shared mesh (`unpicked`: {(data name, modifier name)})."""
    return [modifier for modifier in offered_modifiers(ob) if (ob.data.name, modifier.name) not in unpicked]


def skip_reason(ob, view_layer, unpicked=frozenset()):
    """Why this user cannot be applied (a SKIPS key), or None when it can."""
    mesh = ob.data
    if ob.type != 'MESH':
        return "not_mesh"
    if mesh.library is not None or ob.library is not None or mesh.override_library is not None or ob.override_library is not None:
        return "library"
    if mesh.shape_keys is not None:
        return "shape_keys"
    if not ob.visible_get(view_layer=view_layer):
        return "hidden_object"
    if not offered_modifiers(ob):
        return "only_armature"
    to_apply = picked_modifiers(ob, unpicked)
    if not to_apply:
        return "none_picked"
    if not all(modifier.show_viewport or modifier.show_render for modifier in to_apply):
        return "muted_modifier"   # off everywhere: muted on purpose or by mistake, not ours to bake in
    return None


LEVEL_MODIFIERS = {'SUBSURF', 'MULTIRES'}   # their render look has its own level: `render_levels`


def render_look_settings(to_apply):
    """[(modifier, attribute, value while evaluating)] that give each modifier to apply its render look: one off in the
    viewport but on in render (the usual speed setup) is switched on, and a Subdivision / Multires uses its render
    levels, so the applied mesh is what the render showed."""
    settings = []
    for modifier in to_apply:
        if not modifier.show_viewport:
            settings.append((modifier, "show_viewport", True))
        if modifier.type in LEVEL_MODIFIERS:
            settings.append((modifier, "levels", modifier.render_levels))
    return settings


def evaluated_mesh_of(ob, to_apply):
    """A new mesh from `ob` evaluated with only `to_apply` on, in their render look (the other modifiers are off while
    it is evaluated; every setting is restored after). Vertex groups, UVs, custom normals and materials are kept by
    new_from_object."""
    kept = set(to_apply)
    changes = [(modifier, "show_viewport", False) for modifier in ob.modifiers if modifier not in kept]
    changes += render_look_settings(to_apply)
    saved = [(owner, attribute, getattr(owner, attribute)) for owner, attribute, _value in changes]
    for owner, attribute, value in changes:
        setattr(owner, attribute, value)
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        return bpy.data.meshes.new_from_object(ob.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph)
    finally:
        for owner, attribute, value in reversed(saved):
            setattr(owner, attribute, value)


def vertex_positions(mesh):
    positions = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", positions)
    return positions


def same_shape(a, b):
    """Same vertex and face count, vertex positions within SHAPE_TOLERANCE (object space)."""
    return (len(a.vertices) == len(b.vertices) and len(a.polygons) == len(b.polygons)
            and np.allclose(vertex_positions(a), vertex_positions(b), atol=SHAPE_TOLERANCE, rtol=0))


def subgroups_by_shape(meshes_by_objects):
    """[(mesh, [objects])] from [([objects], mesh)]: the entries whose meshes have the same shape merge into one kept
    mesh; the duplicates are deleted."""
    groups = []
    for objects, mesh in meshes_by_objects:
        match = next((group for group in groups if same_shape(group[0], mesh)), None)
        if match is None:
            groups.append((mesh, list(objects)))
        else:
            match[1].extend(objects)
            bpy.data.meshes.remove(mesh)
    return groups


NOT_COMPARABLE = "NOT_COMPARABLE"
NOT_A_SETTING = ("rna_type", "name", "persistent_uid", "is_active", "show_expanded")   # differ between identical stacks


MAX_NESTING = 4   # how deep property_value follows structs inside structs (a Bevel's custom profile and its points)


def property_value(owner, prop, depth=0):
    """One RNA property as a comparable value (nested structs and lists become tuples), or NOT_COMPARABLE when it points
    at an object, or is nested too deep to follow."""
    value = getattr(owner, prop.identifier)
    if isinstance(value, bpy.types.Object) or depth > MAX_NESTING:
        return NOT_COMPARABLE
    if isinstance(value, bpy.types.ID):
        return value.name
    if prop.type == 'COLLECTION':
        items = tuple(struct_values(item, depth + 1) for item in value)
        return NOT_COMPARABLE if NOT_COMPARABLE in items else items
    if prop.type == 'POINTER':
        return None if value is None else struct_values(value, depth + 1)
    return tuple(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


def struct_values(owner, depth=0):
    """The settings of an RNA struct as a tuple (see property_value); NOT_COMPARABLE if any of them is."""
    values = tuple(property_value(owner, prop, depth) for prop in owner.bl_rna.properties if prop.identifier not in NOT_A_SETTING)
    return NOT_COMPARABLE if NOT_COMPARABLE in values else values


def custom_value(value):
    """A custom property (a Geometry Nodes input) as a comparable value."""
    if isinstance(value, bpy.types.Object):
        return NOT_COMPARABLE
    if isinstance(value, bpy.types.ID):
        return value.name
    return tuple(value.to_list()) if hasattr(value, "to_list") else value


def modifier_signature(modifier):
    """(type, every setting except the name) of one modifier, or None when it cannot be compared by its settings: it
    references an object (Mirror object, Boolean, Shrinkwrap target, Geometry Nodes object inputs...) or reads global
    space (Global texture coordinates)."""
    if getattr(modifier, "texture_coords", None) == 'GLOBAL':
        return None
    values = [struct_values(modifier)]
    values += [custom_value(modifier[key]) for key in sorted(modifier.keys() if modifier.type == 'NODES' else [])]
    return None if NOT_COMPARABLE in values else (modifier.type, tuple(values))


def stack_signature(modifiers):
    """The settings of a stack of modifiers (names ignored), or None when any of them cannot be compared."""
    signatures = [modifier_signature(modifier) for modifier in modifiers]
    return None if None in signatures else tuple(signatures)


def evaluated_groups(applied_modifiers):
    """[([objects], new mesh)] from {object: modifiers to apply}: users with the same stack signature share ONE
    evaluation; a user whose stack cannot be compared by its settings is evaluated on its own."""
    same_stack, evaluated = {}, []
    for ob, modifiers in applied_modifiers.items():
        signature = stack_signature(modifiers)
        if signature is None:
            evaluated.append(([ob], evaluated_mesh_of(ob, modifiers)))
        else:
            same_stack.setdefault(signature, []).append(ob)
    for objects in same_stack.values():
        evaluated.append((objects, evaluated_mesh_of(objects[0], applied_modifiers[objects[0]])))
    return evaluated


def apply_shared_data(data, view_layer, unpicked=frozenset()):
    """Apply the ticked modifiers of every user of the shared mesh `data` (see the module doc). Returns an ApplyResult."""
    result = ApplyResult()
    applied_modifiers = {}
    for ob in users_by_data().get(data, []):
        if not ob.modifiers:
            continue
        reason = skip_reason(ob, view_layer, unpicked)
        if reason:
            result.skipped[SKIPS[reason]] += 1
            continue
        applied_modifiers[ob] = picked_modifiers(ob, unpicked)
    name, new_meshes = data.name, []
    for mesh, objects in subgroups_by_shape(evaluated_groups(applied_modifiers)):
        for ob in objects:
            ob.data = mesh
            for modifier in applied_modifiers[ob]:
                ob.modifiers.remove(modifier)
        new_meshes.append(mesh)
        result.applied += len(objects)
    result.meshes = len(new_meshes)
    if data.users == 0:
        bpy.data.meshes.remove(data)   # every user moved on: the new meshes can take its name
    for mesh in new_meshes:
        mesh.name = name
    return result


def apply_linked_modifiers(data_names, view_layer, unpicked=frozenset()):
    """Apply the ticked modifiers on every shared mesh named in `data_names`. Returns the summed ApplyResult."""
    result = ApplyResult()
    wanted = set(data_names)
    for data, users in list(users_by_data().items()):
        if data.name in wanted and len(users) > 1 and isinstance(data, bpy.types.Mesh):
            result.add(apply_shared_data(data, view_layer, unpicked))
        elif data.name in wanted and len(users) > 1:
            result.skipped[SKIPS["not_mesh"]] += sum(1 for ob in users if ob.modifiers)
    return result
