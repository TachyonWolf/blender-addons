# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/weight_cleanup.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Vertex group clean-up logic (Digit's Tools > Weights): Remove Disconnected Islands and Merge Vertex Groups. Plain
functions on a mesh object, no UI and no modal code (weight_tools_ui.py has those), so tests can run them headless.
Merging reuses combine_bones.merge_weights; `normalise_vertices` is the one "make this vertex sum to 1" helper."""
from collections import deque

try:
    from . import combine_bones as cb  # generated copy
except ImportError:   # run from the shared_addon folder itself
    import combine_bones as cb

DEFAULT_THRESHOLD = 0.05
KEEP_SPILL = "Spill"   # suffix of the group "Move to New Group" makes: "<group> Spill"
EPS = 1e-6


# ---------------------------------------------------------------- reading weights
def group_weights(ob, group):
    """{vertex index: weight} of the vertices with weight in the named group (above 0)."""
    vg = ob.vertex_groups.get(group)
    if vg is None:
        return {}
    return {v.index: g.weight for v in ob.data.vertices for g in v.groups if g.group == vg.index and g.weight > EPS}


def deform_group_names(ob, skip=()):
    """Names of the groups that deform the mesh: those named like a deform bone of its Armature modifier's rig; with no
    rig, every group. `skip` names are left out."""
    rig = next((m.object for m in ob.modifiers if m.type == 'ARMATURE' and m.object), None)
    bones = rig.data.bones if rig else None
    return {g.name for g in ob.vertex_groups
            if g.name not in skip and (bones is None or (g.name in bones and bones[g.name].use_deform))}


# ---------------------------------------------------------------- the click: which vertex
def vertex_from_hit(ob, evaluated_mesh, face_index, local_hit):
    """Original vertex index nearest to a ray hit. `evaluated_mesh` is the mesh the ray hit (modifiers applied) and
    `face_index` its face. When the modifiers kept the topology (Armature, Shape Keys, Lattice...: same vertex and face
    counts) the evaluated face's vertex indices ARE the original ones. When they changed it (Subdivision, Mirror,
    Solidify...) the original index of an evaluated vertex is not exposed to Python, so the base mesh vertex nearest to the
    hit (object space) is used: right in rest pose, approximate in a strong pose."""
    me = ob.data
    if len(evaluated_mesh.vertices) == len(me.vertices) and len(evaluated_mesh.polygons) == len(me.polygons):
        pool = [(evaluated_mesh.vertices[i].co, i) for i in evaluated_mesh.polygons[face_index].vertices]
    else:
        pool = [(v.co, v.index) for v in me.vertices]
    return min(pool, key=lambda pair: (pair[0] - local_hit).length_squared)[1]


def topology_changed(ob, evaluated_mesh):
    return len(evaluated_mesh.vertices) != len(ob.data.vertices) or len(evaluated_mesh.polygons) != len(ob.data.polygons)


# ---------------------------------------------------------------- islands
def flood(edges, weights, seed, threshold):
    """Vertices connected to `seed` through edges, walking only over vertices whose weight is at least `threshold`.
    `edges` = pairs of vertex indices, `weights` = {vertex: weight}. Empty when the seed itself is below it."""
    if weights.get(seed, 0.0) < threshold:
        return set()
    near = {}
    for a, b in edges:
        near.setdefault(a, []).append(b)
        near.setdefault(b, []).append(a)
    keep, queue = {seed}, deque([seed])
    while queue:
        for n in near.get(queue.popleft(), ()):
            if n not in keep and weights.get(n, 0.0) >= threshold:
                keep.add(n)
                queue.append(n)
    return keep


def split_island(ob, group, seed, threshold):
    """(keep, spill): vertex indices of the group's connected island around `seed`, and the group's other vertices."""
    weights = group_weights(ob, group)
    keep = flood([tuple(e.vertices) for e in ob.data.edges], weights, seed, threshold)
    return keep, set(weights) - keep


def normalise_vertices(ob, indices, names):
    """Each listed vertex: its weights in the groups `names` are scaled to sum to 1 (vertices with none are skipped).
    Other groups are left alone. Returns the number changed."""
    changed = 0
    for i in indices:
        row = {ob.vertex_groups[g.group].name: g.weight for g in ob.data.vertices[i].groups
               if ob.vertex_groups[g.group].name in names and g.weight > EPS}
        total = sum(row.values())
        if total > EPS and abs(total - 1.0) > EPS:
            for name, w in row.items():
                ob.vertex_groups[name].add([i], w / total, 'REPLACE')
            changed += 1
    return changed


def remove_and_normalize(ob, group, spill):
    """Drop the spill vertices from `group`; each one's weight goes to its other deform groups in proportion, so it
    still sums to 1. A vertex with no other deform weight is left in the group. Returns (removed, left_alone)."""
    vg = ob.vertex_groups[group]
    others = deform_group_names(ob, skip=(group,))
    removed, left, touched = 0, 0, []
    for i in sorted(spill):
        has_other = any(ob.vertex_groups[g.group].name in others and g.weight > EPS for g in ob.data.vertices[i].groups)
        if not has_other:
            left += 1
            continue
        vg.remove([i])
        touched.append(i)
        removed += 1
    normalise_vertices(ob, touched, others)
    return removed, left


def move_to_new_group(ob, group, spill):
    """The spill vertices' weights go to the group "<group> Spill" (made, or reused and overwritten) and leave `group`.
    Returns (count, new group name)."""
    weights = group_weights(ob, group)
    name = f"{group} {KEEP_SPILL}"
    target = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
    for i in sorted(spill):
        target.add([i], weights[i], 'REPLACE')
    if spill:
        ob.vertex_groups[group].remove(sorted(spill))
    return len(spill), name


def status_text(keeps, removes):
    return f"Keeps {keeps} · removes {removes}"


# ---------------------------------------------------------------- merging
def merge_groups(ob, target, sources, mode='ADD', remove_merged=True, normalise=False):
    """Weights of the `sources` groups join `target` (ADD: summed, clamped to 1; MAX: the larger of each pair). Sources
    are deleted when `remove_merged`. With `normalise`, every touched vertex's deform weights are scaled to sum to 1.
    Returns the number of vertices that gained weight."""
    names = [n for n in dict.fromkeys(sources) if n != target and n in ob.vertex_groups]
    touched = cb.merge_weights(ob, target, names, mode=mode, remove=remove_merged)
    if normalise and touched:
        sources_gone = set(names) if remove_merged else set()
        group = ob.vertex_groups.get(target)
        affected = [v.index for v in ob.data.vertices if any(g.group == group.index for g in v.groups)]
        normalise_vertices(ob, affected, deform_group_names(ob) - sources_gone)
    return touched
