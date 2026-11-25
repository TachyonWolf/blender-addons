# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig based setups: Stretch To Curve and Balloon Twist on a bone chain (both from the same Selection +
Along groups, `write_part_groups`) and Stretchy Limb (shared code in modifier_setup.py, the same the
Stretchy Limb extension uses). All read their bones from the recipe's bone options."""

from .bone_chain import (chain_bone_names, chain_path, chain_points, deformed_meshes,  # generated copy
                         rig_for_chain, write_along_group, write_chain_group)
from .helpers import SetupError, get_group
from .modifier_setup import (STRETCHY_GROUP, add_after_armature, add_stretchy_limb,  # generated copy
                             make_path_curve, set_modifier_input)

STC_GROUP = "Stretch To Curve"
STC_FILE = "StretchToCurve.blend"  # bundled in the extension's assets
LIMB_FILE = "StretchyLimbs.blend"
BALLOON_GROUP = "Balloon Twist"
BALLOON_FILE = "BalloonTwist.blend"


def write_part_groups(rig, root, tip, meshes, selection, along):
    """On each mesh with weights in the root bone's chain: a Selection group `selection` (the chain's
    summed weights, fins and flukes included) and an Along group `along` (0 at the root .. 1 at the
    tip of the bone path root > tip, rest pose; past the tip 1). Returns (bone path, [meshes done])."""
    path = chain_path(rig, root, tip or None)
    chain = chain_bone_names(rig, [rig.data.bones[root]])
    done = []
    for ob in meshes:
        if write_chain_group(ob, chain, selection)[0] == 0:
            ob.vertex_groups.remove(ob.vertex_groups[selection])
            continue
        write_along_group(ob, rig, path, selection, along)
        done.append(ob)
    return path, done


def add_stretch_to_curve(context, group, rig, root, tip, meshes):
    """On each mesh with weights in the root bone's chain: a Selection group (the chain's summed
    weights, fins and flukes included) and an Along group (0 at the root .. 1 at the tip of the
    bone path root > tip, rest pose; past the tip 1, so it rides rigidly), a Stretch To Curve
    modifier after the Armature modifier at Progress 0 (no change until it is animated), and one
    starter curve through the posed bone joints.
    Returns (curve object, [meshes set up])."""
    selection, along = f"StretchCurve_{root}", f"StretchAlong_{root}"
    path, done = write_part_groups(rig, root, tip, meshes, selection, along)
    if not done:
        return None, done
    parent = rig.data.bones[root].parent
    curve = make_path_curve(context, rig, chain_points(rig, path), f"StretchCurve_{root}",
                            parent.name if parent else None)
    for ob in done:
        mod = add_after_armature(ob, group, STC_GROUP, "Stretch")  # after Stretchy Limbs too
        set_modifier_input(mod, "Curve", curve)
        set_modifier_input(mod, "Along", "Group")
        set_modifier_input(mod, "Along Group", along, attribute=True)
        set_modifier_input(mod, "Selection", selection, attribute=True)
        set_modifier_input(mod, "Progress", 0.0)  # nothing moves until Progress is animated
        ob.update_tag()
    return curve, done


def _rig_and_bones(context, values, keys):
    """The rig and the bone names `values[key]` for `keys` (the sidebar's Rig options; first one required)."""
    rig = rig_for_chain(context)
    if rig is None:
        raise SetupError("Select a rig or a mesh it deforms")
    names = [values[key] for key in keys]
    if not names[0]:
        raise SetupError("Pick the bones first (Modifiers tab, or the popup)")
    missing = [n for n in names if n and n not in rig.data.bones]
    if missing:
        raise SetupError(f"{rig.name} has no bone {', '.join(missing)}")
    return rig, names


def setup_stretch_to_curve(context, values):
    """Recipe setup: (active, selected, message). The curve is the control to grab."""
    rig, (root, tip) = _rig_and_bones(context, values, ("root", "tip"))
    curve, done = add_stretch_to_curve(context, get_group(STC_GROUP, STC_FILE), rig, root, tip,
                                       deformed_meshes(context, rig))
    if not done:
        raise SetupError(f"No mesh deformed by {rig.name} has weights in {root}'s chain")
    return curve, [curve], f"Stretch To Curve on {', '.join(ob.name for ob in done)}; edit the curve '{curve.name}'"


def add_balloon_twist(group, rig, root, tip, meshes):
    """Balloon Twist on the part of each mesh in the root bone's chain (Group mode on the chain's
    Along + Selection groups), after the Armature modifier. Returns [meshes set up]."""
    selection, along = f"BalloonPart_{root}", f"BalloonAlong_{root}"
    done = write_part_groups(rig, root, tip, meshes, selection, along)[1]
    for ob in done:
        mod = add_after_armature(ob, group, BALLOON_GROUP)
        set_modifier_input(mod, "Along", "Group")
        set_modifier_input(mod, "Along Group", along, attribute=True)
        set_modifier_input(mod, "Selection", selection, attribute=True)
        ob.update_tag()
    return done


def setup_balloon_twist(context, values):
    """Recipe setup: (active, selected, message). No helper objects: the mesh stays selected."""
    rig, (root, tip) = _rig_and_bones(context, values, ("root", "tip"))
    done = add_balloon_twist(get_group(BALLOON_GROUP, BALLOON_FILE), rig, root, tip, deformed_meshes(context, rig))
    if not done:
        raise SetupError(f"No mesh deformed by {rig.name} has weights in {root}'s chain")
    return done[0], done, f"Balloon Twist on {', '.join(ob.name for ob in done)} ({root}'s chain)"


def setup_stretchy_limb(context, values):
    rig, (root, mid, tip) = _rig_and_bones(context, values, ("root", "mid", "tip"))
    if not tip:
        raise SetupError("Pick the Tip bone too")
    path, done = add_stretchy_limb(context, get_group(STRETCHY_GROUP, LIMB_FILE), rig, root, mid, tip,
                                   deformed_meshes(context, rig))
    if not done:
        raise SetupError(f"No mesh deformed by {rig.name} has weights in {root}'s chain")
    return path, [path], f"Stretchy limb on {', '.join(ob.name for ob in done)}; edit the path '{path.name}'"
