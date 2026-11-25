# SPDX-License-Identifier: GPL-3.0-or-later
"""Modifier order rules for the Oops Debugger (shared source; scene_checks.py registers the checks, nothing here runs by itself).

Three rules, each a pure `plan(modifiers)` that returns the wanted order as modifier names, or None when the stack is fine:
  - Armature first: a modifier that works on the shape (Subdivision, Bevel, Lattice, Shrinkwrap...) must not sit before an Armature.
  - Toony before Armature: a Toony modifier (the Digit's Modifiers groups) must not sit before an Armature.
  - Subdivision and Weld Normals last: they go after every other modifier, Subdivision first, Weld Normals right after it.
`apply_order` is the one fix: it only moves modifiers, so every setting stays. Exceptions are data below, not special cases.
A modifier that is off in both viewport and render does nothing, so it never counts for or against a stack.
"""
from .instance_array import COPY_SUFFIX, is_instance_array
from .toony_ui import is_toony

# These need the posed (Armature) shape, or smooth / re-grid it: before an Armature they work on the wrong shape.
# Not listed on purpose: Mirror, Mask, Solidify, Array, Weld, vertex weight modifiers (normal before an Armature).
SHAPE_TYPES = frozenset({'SUBSURF', 'MULTIRES', 'REMESH', 'DECIMATE', 'TRIANGULATE', 'BEVEL', 'SMOOTH', 'CORRECTIVE_SMOOTH',
                         'LAPLACIANSMOOTH', 'SHRINKWRAP', 'SURFACE_DEFORM', 'LATTICE', 'SIMPLE_DEFORM', 'CURVE', 'WEIGHTED_NORMAL'})
BEFORE_ARMATURE_GROUPS = frozenset({"Bubbles Rest"})   # Toony groups that are made to sit right before the Armature
WELD_NORMALS_GROUP = "Weld Normals"                      # blends normals of the final shape: goes after Subdivision
LAST_GROUPS = frozenset({"Bubbles"})                     # made to be last in the stack (Instance Array is too): may follow Subdivision
AFTER_SUBDIVISION_TYPES = frozenset({'WEIGHTED_NORMAL', 'NORMAL_EDIT', 'TRIANGULATE', 'SHRINKWRAP', 'DATA_TRANSFER'})   # normal after it

IGNORED, REGULAR, SUBDIVISION, WELD_NORMALS, TAIL = "ignored", "regular", "subdivision", "weld_normals", "tail"
FINISHER_KINDS = (SUBDIVISION, WELD_NORMALS)   # in this order at the end


def is_on(modifier):
    return modifier.show_viewport or modifier.show_render


def group_name(modifier):
    """The node group's name without a copy suffix (".001"), "" for a modifier with no group."""
    group = getattr(modifier, "node_group", None) if modifier.type == 'NODES' else None
    return COPY_SUFFIX.sub("", group.name) if group else ""


def is_subdivision(modifier):
    return modifier.type == 'SUBSURF' and bool(modifier.levels or modifier.render_levels)


def is_armature(modifier):
    return modifier.type == 'ARMATURE' and is_on(modifier)


def wants_armature_first(modifier):
    """Armature-first offender: a shape modifier (not Toony, those have their own check)."""
    if not is_on(modifier) or modifier.type not in SHAPE_TYPES:
        return False
    return is_subdivision(modifier) if modifier.type == 'SUBSURF' else True


def toony_before_armature(modifier):
    """Toony offender: a Toony modifier that is not one of the groups made to sit before the Armature."""
    return is_on(modifier) and is_toony(modifier) and group_name(modifier) not in BEFORE_ARMATURE_GROUPS


def armature_first_plan(modifiers, is_offender):
    """The stack with every Armature that sits after the first offender moved to just before it. None when none does."""
    modifiers = list(modifiers)
    armature_places = [place for place, modifier in enumerate(modifiers) if is_armature(modifier)]
    for place, modifier in enumerate(modifiers):
        late_armatures = [modifiers[armature] for armature in armature_places if armature > place]
        if is_offender(modifier) and late_armatures:
            rest = [other for other in modifiers[place:] if other not in late_armatures]
            return [other.name for other in modifiers[:place] + late_armatures + rest]
    return None


def finish_kind(modifier):
    if not is_on(modifier):
        return IGNORED
    if is_subdivision(modifier):
        return SUBDIVISION
    name = group_name(modifier)
    if name == WELD_NORMALS_GROUP:
        return WELD_NORMALS
    if modifier.type in AFTER_SUBDIVISION_TYPES or is_instance_array(modifier) or name in LAST_GROUPS:
        return TAIL
    return REGULAR


def finishers_last_plan(modifiers):
    """The stack with Subdivision, then Weld Normals, right after the last ordinary modifier. None when already so."""
    modifiers = list(modifiers)
    kinds = {modifier.name: finish_kind(modifier) for modifier in modifiers}
    finishers = [modifier for kind in FINISHER_KINDS for modifier in modifiers if kinds[modifier.name] == kind]
    others = [modifier for modifier in modifiers if kinds[modifier.name] not in FINISHER_KINDS]
    last_regular = max((place for place, modifier in enumerate(others) if kinds[modifier.name] == REGULAR), default=-1)
    wanted = [modifier.name for modifier in others[:last_regular + 1] + finishers + others[last_regular + 1:]]
    return wanted if wanted != [modifier.name for modifier in modifiers] else None


def apply_order(ob, wanted_names):
    """Move the modifiers into this order. Only moves: no setting changes."""
    for place, name in enumerate(wanted_names):
        current = ob.modifiers.find(name)
        if current != place:
            ob.modifiers.move(current, place)
