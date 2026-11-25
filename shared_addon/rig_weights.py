# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, skin weights: the body by Blender's automatic weights, then the face and the part chains on top,
and Keep Weights (painted weights survive a re-weight). Bone-only: no shape keys, no corrective bones.

    saved = remember_weights(rig, meshes)              # Keep Weights: before re-weighting
    report = weigh_all(rig, meshes, dict(face=face_step, chains=[['Tail1', ...], ['Ear1.L', ...]], keep=saved))

Order (weigh_all): body weights (automatic weights on the BODY deform bones only: face, part-chain and helper deform
bones are switched off for the operator, then back on; run on a copy with seam-split vertices welded, so a mesh cut
at its UV seams doesn't tear) -> the face step (face_rig_core takes the face's weights from the Head's, so the Head
must be weighted first) -> the part chains (chain_weights blends them over the body's weights) ->
Keep Weights. Automatic weights leave small closed shells unweighted without saying so: those vertices take the weights
of the nearest weighted vertex (KD-tree), then every small loose shell (eyes, teeth, buttons) that is mostly one bone
becomes rigid on that bone, so it can't smear. Eyes end up rigid on the Head; the face step moves them to the eye bones.
The Jaw keeps its automatic weight only on the lower jaw (trim_jaw: not the upper neck, the back of the head or the snout).
A Mirror-modifier half mesh is weighted on its own side's bones (and centre), then gets the other side's groups
(ensure_mirror_groups) and equal Left/Right weights on the mirror plane (symmetrize_center); the Armature modifier
goes after the Mirror so each half follows its own side.
"""
import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

try:                                     # inside the add-on package
    from . import body_rig as br, chain_weights as cw, face_rig_core as fr, limb_rig as lr, part_chains as pc, \
        rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import chain_weights as cw
    import face_rig_core as fr
    import limb_rig as lr
    import part_chains as pc
    import rig_names as rn

LIMIT = 4                  # bone influences per vertex
FLOOR = 1e-4               # a weight under this counts as none
WELD = 1e-5                # vertices closer than this share of the mesh's size are one (seams split for UVs)
SMALL_SHELL = 0.08         # a loose shell smaller than this share of the rig's height is a small part (eye, tooth)
RIGID_SHARE = 0.6          # ... and goes rigid on its main bone when that bone holds this share of its weight
SMOOTH = 4                 # smoothing passes over the automatic weights (softer creases at the shoulders)
JAW = 'Jaw'                # the body's jaw bone: its automatic weights reach into the upper neck and the snout, so
JAW_ALONG = (0.0, 0.35)    # trim_jaw keeps them only in front of the hinge (fading in over this share of its length),
JAW_ABOVE = (0.05, 0.2)    # under the mouth line (the jaw bone: fading out this far above it)
JAW_BELOW = (0.35, 0.7)    # and above the throat (fading out this far below it); shares of the jaw's length


# ---------------------------------------------------------------- helpers
def body_deform_bones(rig):
    """The deform bones build_body made (from its record), so face, part and helper bones stay out."""
    bones = rig.data.bones
    return [n for n in br.read_record(rig).get('bones', []) if n in bones and bones[n].use_deform]


def rig_height(rig, names):
    zs = [z for n in names for z in (rig.data.bones[n].head_local.z, rig.data.bones[n].tail_local.z)]
    return (max(zs) - min(zs)) * max(rig.matrix_world.to_scale()) if zs else 1.0


def bone_weights(obj, bones):
    """Per vertex {bone group: weight} of the groups named in `bones`, weights over FLOOR."""
    gi = {g.index: g.name for g in obj.vertex_groups if g.name in bones}
    return [{gi[e.group]: e.weight for e in v.groups if e.group in gi and e.weight > FLOOR} for v in obj.data.vertices]


def write_row(obj, i, row, bones):
    """Vertex i's bone groups (those in `bones`) become `row`; its other groups stay as they are."""
    groups = obj.vertex_groups
    for e in list(obj.data.vertices[i].groups):
        if groups[e.group].name in bones:
            groups[e.group].remove([i])
    for n, w in row.items():
        (groups.get(n) or groups.new(name=n)).add([i], w, 'REPLACE')


def normalise(obj, bones, limit=LIMIT):
    """Every vertex: its `limit` strongest bone weights, summing to 1. Other vertex groups (masks) are left alone."""
    for i, row in enumerate(bone_weights(obj, bones)):
        top = dict(sorted(row.items(), key=lambda kv: -kv[1])[:limit])
        total = sum(top.values())
        if total > 0 and (top != row or abs(total - 1) > 1e-5):
            write_row(obj, i, {n: w / total for n, w in top.items()}, bones)


def is_half(obj):
    """A mesh with an X Mirror modifier and (almost) nothing on the other side of x = 0: weighted as its left or right
    half. Returns 'L' / 'R' (the side it has), or None."""
    if not fr.has_mirror(obj) or not obj.data.vertices:
        return None
    xs = [v.co.x for v in obj.data.vertices]
    tol = 1e-4 + 1e-3 * (max(xs) - min(xs))
    if min(xs) >= -tol:
        return 'L'
    if max(xs) <= tol:
        return 'R'
    return None


def shells(obj):
    """Loose parts of the mesh: lists of vertex indices."""
    parent = list(range(len(obj.data.vertices)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for e in obj.data.edges:
        a, b = root(e.vertices[0]), root(e.vertices[1])
        if a != b:
            parent[a] = b
    out = {}
    for i in range(len(parent)):
        out.setdefault(root(i), []).append(i)
    return list(out.values())


# ---------------------------------------------------------------- automatic weights
class DeformOnly:
    """Only the bones in `keep` deform while inside (the automatic-weights operator weights every deform bone)."""

    def __init__(self, rig, keep):
        self.rig, self.keep = rig, set(keep)

    def __enter__(self):
        self.was = {b.name: b.use_deform for b in self.rig.data.bones}
        for b in self.rig.data.bones:
            b.use_deform = b.name in self.keep
        return self

    def __exit__(self, *exc):
        for b in self.rig.data.bones:
            b.use_deform = self.was[b.name]


def armature_after_mirror(obj, rig):
    """The rig's Armature modifier sits after the last Mirror (the operator puts it first: both halves would follow
    one side)."""
    mods = list(obj.modifiers)
    arm = next((i for i, m in enumerate(mods) if m.type == 'ARMATURE' and m.object == rig), None)
    last_mirror = max((i for i, m in enumerate(mods) if m.type == 'MIRROR'), default=None)
    if arm is not None and last_mirror is not None and arm < last_mirror:
        obj.modifiers.move(arm, last_mirror)


def add_armature(obj, rig, name='Armature'):
    """An Armature modifier `name` for `rig` right after the last Mirror (first without one), the Mirror's vertex groups
    on, so the right half follows the right-side bones. Re-running reuses it."""
    mod = obj.modifiers.get(name) or obj.modifiers.new(name, 'ARMATURE')
    mod.object = rig
    mods = list(obj.modifiers)
    mirrors = [i for i, m in enumerate(mods) if m.type == 'MIRROR']
    for i in mirrors:
        mods[i].use_mirror_vertex_groups = True
    at, to = mods.index(mod), (mirrors[-1] + 1 if mirrors else 0)
    to = to if to <= at else to - 1
    if to != at:                         # (a lone modifier is already in place: move() refuses a no-op past the end)
        obj.modifiers.move(at, to)
    return mod


def auto_weights(rig, meshes, bones):
    """Blender's automatic weights from `bones` only, on `meshes` (parented to the rig, Armature modifier added)."""
    view = bpy.context.view_layer
    state = [(o, o.hide_get(), o.select_get()) for o in meshes + [rig]]
    active = view.objects.active
    for o in meshes + [rig]:
        o.hide_set(False)
        o.select_set(True)
    view.objects.active = rig
    try:
        with DeformOnly(rig, bones), bpy.context.temp_override(active_object=rig, object=rig,
                                                               selected_objects=meshes + [rig],
                                                               selected_editable_objects=meshes + [rig]):
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    finally:
        for o, hidden, selected in state:
            o.select_set(selected)
            o.hide_set(hidden)
        view.objects.active = active


def fill_unweighted(meshes, bones):
    """Vertices without bone weight take the weights of the nearest weighted vertex: of the same mesh, else of any.
    Returns {mesh name: vertices filled}."""
    rows = {o.name: bone_weights(o, bones) for o in meshes}
    def tree(objs):
        pts = [(o, i) for o in objs for i, row in enumerate(rows[o.name]) if row]
        kd = KDTree(len(pts))
        for k, (o, i) in enumerate(pts):
            kd.insert(o.matrix_world @ o.data.vertices[i].co, k)
        kd.balance()
        return kd, pts
    every = None
    out = {}
    for o in meshes:
        empty = [i for i, row in enumerate(rows[o.name]) if not row]
        out[o.name] = len(empty)
        if not empty:
            continue
        if len(empty) < len(rows[o.name]):
            kd, pts = tree([o])
        else:                            # nothing on this mesh is weighted: the nearest of any mesh
            every = every or tree(meshes)
            kd, pts = every
        if not pts:
            continue
        for i in empty:
            _, k, _ = kd.find(o.matrix_world @ o.data.vertices[i].co)
            src, j = pts[k]
            write_row(o, i, rows[src.name][j], bones)
    return out


def nearest_bones(rig, obj, indices, bones, limit=LIMIT):
    """The fallback when automatic weights found nothing on a mesh: each vertex on its nearest bones (distance to the
    bone's segment), falling off as 1 / distance^4 so the nearest one leads. Returns how many vertices."""
    from mathutils.geometry import intersect_point_line
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    segs = [(n, rig.data.bones[n].head_local, rig.data.bones[n].tail_local) for n in bones]
    for i in indices:
        p = to_rig @ obj.data.vertices[i].co
        dist = []
        for n, a, b in segs:
            q, t = intersect_point_line(p, a, b)
            q = a if t < 0 else b if t > 1 else q
            dist.append((max((p - q).length, 1e-6), n))
        near = sorted(dist)[:limit]
        w = {n: (near[0][0] / d) ** 4 for d, n in near}
        total = sum(w.values())
        write_row(obj, i, {n: x / total for n, x in w.items() if x / total > FLOOR}, set(bones))
    return len(indices)


def distance_weights(points, segs, limit=LIMIT, power=4):
    """Per point (any space) a list of weights, one per segment `(head, tail)`: 1 / distance^power to the segment
    (+1e-12), the strongest `limit` kept, summing to 1."""
    from mathutils.geometry import intersect_point_line
    rows = []
    for p in points:
        w = []
        for a, b in segs:
            q, t = intersect_point_line(p, a, b)
            q = a if t < 0 else b if t > 1 else q
            w.append(1.0 / (p - q).length ** power + 1e-12)
        rows.append(keep_top(w, limit))
    return rows


def keep_top(w, limit=LIMIT):
    """`w` with only its `limit` biggest entries (the rest 0), normalised to sum 1."""
    keep = set(sorted(range(len(w)), key=lambda k: -w[k])[:limit])
    top = [x if k in keep else 0.0 for k, x in enumerate(w)]
    total = sum(top) or 1.0
    return [x / total for x in top]


def spatial_smooth(points, rows, reach, passes=10, factor=0.6, limit=LIMIT):
    """Smooth weight rows in SPACE: each point blends toward the mean of all points within `reach` (a KDTree, not
    mesh edges), so separate pieces that touch end up with the same weights. Then the top `limit`, normalised."""
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    near = [[j for _, j, _ in tree.find_range(p, reach) if j != i] for i, p in enumerate(points)]
    width = len(rows[0]) if rows else 0
    for _ in range(passes):
        new = []
        for row, ids in zip(rows, near):
            if not ids:
                new.append(row)
                continue
            mean = [sum(rows[j][k] for j in ids) / len(ids) for k in range(width)]
            new.append([r + factor * (m - r) for r, m in zip(row, mean)])
        rows = new
    return [keep_top(r, limit) for r in rows]


def smooth_bones(rig, objs, bones, reach_share=0.03, limit=LIMIT):
    """Smooth weights of `objs` (meshes, weighed together) on `bones`: distance weights, spatial smoothing with a reach of
    `reach_share` of the bones' span, top `limit`. World space, undeformed vertices (a Mirror modifier's other side
    follows its use_mirror_vertex_groups). Only the `bones` groups change. Returns how many vertices."""
    mw = rig.matrix_world
    segs = [(mw @ rig.data.bones[n].head_local, mw @ rig.data.bones[n].tail_local) for n in bones]
    ends = [v for seg in segs for v in seg]
    span = max(max(v[k] for v in ends) - min(v[k] for v in ends) for k in range(3))
    points = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    rows = spatial_smooth(points, distance_weights(points, segs, limit), max(span * reach_share, 1e-6), limit=limit)
    k = 0
    for o in objs:
        for i in range(len(o.data.vertices)):
            write_row(o, i, {n: w for n, w in zip(bones, rows[k]) if w > FLOOR}, set(bones))
            k += 1
    return k


def rigid_small_shells(obj, bones, height):
    """Small loose shells (eyes, teeth) that are mostly one bone go rigid on it. Returns how many."""
    rows = bone_weights(obj, bones)
    count = 0
    co = [obj.matrix_world @ v.co for v in obj.data.vertices]
    for shell in shells(obj):
        lo = Vector((min(co[i][k] for i in shell) for k in range(3)))
        hi = Vector((max(co[i][k] for i in shell) for k in range(3)))
        if (hi - lo).length > SMALL_SHELL * height:
            continue
        share = {}
        for i in shell:
            for n, w in rows[i].items():
                share[n] = share.get(n, 0.0) + w / len(shell)
        if not share:
            continue
        main = max(share, key=share.get)
        if share[main] < RIGID_SHARE * sum(share.values()):
            continue
        for i in shell:
            if rows[i] != {main: 1.0}:
                write_row(obj, i, {main: 1.0}, bones)
        count += 1
    return count


def symmetrize(obj, bones, tol=1e-3):
    """A symmetric mesh gets symmetric weights: each vertex and its mirror twin (within `tol` x the mesh's size) share
    the average (the heat solve drifts a little apart near the shoulders); mirror-plane vertices get equal Left/Right
    weights. Unmatched vertices (an asymmetric mesh) stay. Returns the number of twin pairs."""
    cos = [v.co.copy() for v in obj.data.vertices]
    if not cos:
        return 0
    size = max(obj.dimensions) / max(max(obj.matrix_world.to_scale()), 1e-9) or 1.0
    kd = KDTree(len(cos))
    for i, c in enumerate(cos):
        kd.insert(c, i)
    kd.balance()
    rows = bone_weights(obj, bones)
    plane = tol * size
    pairs = 0
    for i, c in enumerate(cos):
        if c.x <= plane:
            continue
        _, j, d = kd.find(Vector((-c.x, c.y, c.z)))
        if d > plane:
            continue
        mine, twin = rows[i], {rn.flip(g): w for g, w in rows[j].items()}
        avg = {g: (mine.get(g, 0.0) + twin.get(g, 0.0)) / 2 for g in set(mine) | set(twin)}
        if avg != mine:
            write_row(obj, i, avg, bones)
            write_row(obj, j, {rn.flip(g): w for g, w in avg.items()}, bones)
        pairs += 1
    cw.symmetrize_center(obj, [i for i, c in enumerate(cos) if abs(c.x) <= plane], tol=plane, limit=LIMIT * 2,
                         groups=bones)
    return pairs


def mirror_half(obj, rig):
    """A half mesh: the other side's (empty) groups for the Mirror modifier, equal Left/Right weights on the plane."""
    bones = {b.name for b in rig.data.bones}
    cw.ensure_mirror_groups(obj, only=bones)
    mirror = next(m for m in obj.modifiers if m.type == 'MIRROR' and m.use_axis[0])
    tol = max(mirror.merge_threshold, 1e-4) if mirror.use_mirror_merge else 1e-4
    seam = [v.index for v in obj.data.vertices if abs(v.co.x) <= tol]
    cw.symmetrize_center(obj, seam, tol=tol, limit=LIMIT, groups=bones)
    armature_after_mirror(obj, rig)


def trim_jaw(rig, obj, bones, jaw=JAW, heir='Head'):
    """Keep the Jaw's automatic weight to the lower jaw: in front of its hinge, under the mouth line, above the throat
    (JAW_*). The weight it loses goes to the vertex's other bones (or the Head), so the back of the head, the upper
    neck and the snout stay still when the jaw opens. Returns the number of vertices changed."""
    if jaw not in rig.data.bones or jaw not in obj.vertex_groups:
        return 0
    b = rig.data.bones[jaw]
    hinge, along = b.head_local, (b.tail_local - b.head_local).normalized()
    up = Vector((0, 0, 1)) - along * along.z
    up = up.normalized() if up.length > 1e-6 else Vector((0, -1, 0))
    length = b.length
    to_rig = rig.matrix_world.inverted() @ obj.matrix_world
    ramp = lambda lo, hi, x: cw.smoothstep(lo, hi, x)
    changed = 0
    for i, row in enumerate(bone_weights(obj, bones)):
        w = row.get(jaw, 0.0)
        if w <= FLOOR:
            continue
        r = to_rig @ obj.data.vertices[i].co - hinge
        a, h = r.dot(along) / length, r.dot(up) / length
        keep = ramp(*JAW_ALONG, a) * (1 - ramp(*JAW_ABOVE, h)) * (1 - ramp(*JAW_BELOW, -h))
        if keep >= 1 - 1e-6:
            continue
        lost = w * (1 - keep)
        rest = {n: x for n, x in row.items() if n != jaw}
        total = sum(rest.values())
        new = {n: x + lost * x / total for n, x in rest.items()} if total > FLOOR else {heir: lost}
        if w * keep > FLOOR:
            new[jaw] = w * keep
        write_row(obj, i, new, bones)
        changed += 1
    return changed


def welded_proxy(obj):
    """A copy of the mesh with coincident vertices welded (a model split at UV seams, a glTF import, falls apart into
    shells that automatic weights would weigh apart: the seams tear) and no vertex groups or modifiers, at the same
    place. Returns (proxy, {original vertex index: proxy vertex index} as a list)."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for layer in list(bm.verts.layers.deform.values()):
        bm.verts.layers.deform.remove(layer)
    pos = [v.co.copy() for v in bm.verts]
    size = max((max(c[k] for c in pos) - min(c[k] for c in pos) for k in range(3)), default=1.0) if pos else 1.0
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=WELD * (size or 1.0))
    me = bpy.data.meshes.new(obj.name + ' (weights)')
    bm.to_mesh(me)
    bm.free()
    proxy = bpy.data.objects.new(me.name, me)
    bpy.context.scene.collection.objects.link(proxy)
    proxy.matrix_world = obj.matrix_world.copy()
    kd = KDTree(len(me.vertices))
    for v in me.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    return proxy, [kd.find(p)[1] for p in pos]


def attach(obj, rig):
    """Parented to the rig where it stands, with an Armature modifier on it (after any Mirror)."""
    if obj.parent != rig:
        world = obj.matrix_world.copy()
        obj.parent, obj.parent_type = rig, 'OBJECT'
        obj.matrix_parent_inverse = rig.matrix_world.inverted() @ world @ obj.matrix_basis.inverted()
    if not any(m.type == 'ARMATURE' and m.object == rig for m in obj.modifiers):
        obj.modifiers.new(rig.name, 'ARMATURE').object = rig
    armature_after_mirror(obj, rig)


def body_weights(rig, meshes, deform_bones=None, limit=LIMIT):
    """Body skin weights on `meshes` from the body's deform bones (default: body_deform_bones). The meshes' groups of
    every rig bone are cleared first (the face and part steps weight theirs afterwards: use weigh_all). The work runs
    on welded copies (welded_proxy), then is copied back: Blender's automatic weights, the nearest-vertex fill, small
    shells rigid, symmetric weights on symmetric meshes, `limit` influences summing to 1; half meshes mirrored after.
    When automatic weights find nothing on any mesh (badly broken geometry), every vertex goes on its nearest bones.
    Meshes end parented to the rig with an Armature modifier. The rig must be in the view layer.
    Returns {mesh name: dict(filled=vertices that had no weight, rigid=shells made rigid, half=side or None,
    nearest=vertices weighted by the nearest-bone fallback)}."""
    deform = list(deform_bones or body_deform_bones(rig))
    if not deform:
        raise ValueError(f'{rig.name} has no body deform bones: build the body first')
    if rig.mode != 'OBJECT':
        lr.set_mode(rig, 'OBJECT')
    every = {b.name for b in rig.data.bones}
    halves = {o.name: is_half(o) for o in meshes}
    proxies = {o.name: welded_proxy(o) for o in meshes}
    work = [proxies[o.name][0] for o in meshes]
    try:
        for side in (None, 'L', 'R'):
            part = [proxies[o.name][0] for o in meshes if halves[o.name] == side]
            if part:
                auto_weights(rig, part, [n for n in deform if side is None or rn.side_of(n) in ('', side)])
        fallback = {}
        if not any(any(r) for o in work for r in bone_weights(o, set(deform))):
            for o in work:               # automatic weights failed everywhere (a mesh it can't solve): nearest bones
                fallback[o.name] = nearest_bones(rig, o, range(len(o.data.vertices)), deform)
        filled = fill_unweighted(work, set(deform))
        height = rig_height(rig, deform)
        report = {}
        for o in meshes:
            proxy, index = proxies[o.name]
            if SMOOTH:                   # the proxy has bone groups only, so the whole weight is free to move
                cw.smooth(proxy, dict.fromkeys(range(len(proxy.data.vertices)), 0), set(deform), SMOOTH, limit=limit)
            trim_jaw(rig, proxy, set(deform))
            rigid = rigid_small_shells(proxy, set(deform), height)
            if not halves[o.name]:
                symmetrize(proxy, set(deform))
            normalise(proxy, set(deform), limit)
            rows = bone_weights(proxy, set(deform))
            for g in [g for g in o.vertex_groups if g.name in every]:
                o.vertex_groups.remove(g)
            for i, j in enumerate(index):
                if rows[j]:
                    write_row(o, i, rows[j], every)
            attach(o, rig)
            if halves[o.name]:
                mirror_half(o, rig)
            report[o.name] = dict(filled=filled[proxy.name], rigid=rigid, half=halves[o.name],
                                  nearest=fallback.get(proxy.name, 0))
    finally:
        for proxy, _ in proxies.values():
            me = proxy.data
            bpy.data.objects.remove(proxy)
            bpy.data.meshes.remove(me)
    return report


# ---------------------------------------------------------------- Keep Weights
def remember_weights(rig, meshes):
    """What Keep Weights needs from before a re-weight: every mesh's weights (face_rig_core.snapshot) and the bones
    that deformed then."""
    return dict(deform={b.name for b in rig.data.bones if b.use_deform},
                weights={o.name: fr.snapshot(o) for o in meshes})


def keep_weights(rig, saved, limit=LIMIT):
    """After a re-weight: every vertex gets back its old weights on the bones that still deform (painted ones too);
    the share it had on bones that are gone is filled by the fresh weights; a vertex that had no old bone weight keeps
    the fresh ones. Other groups stay as they are now. Written back with face_rig_core.restore_weights.
    Returns the names of meshes skipped (changed vertex count)."""
    bones = {b.name for b in rig.data.bones}
    deform = {b.name for b in rig.data.bones if b.use_deform}
    gone = saved['deform'] - deform
    skipped = []
    for name, old in saved['weights'].items():
        o = bpy.data.objects.get(name)
        if o is None or len(o.data.vertices) != len(old):
            skipped.append(name)
            continue
        merged = []
        for was, now in zip(old, fr.snapshot(o)):
            row = {g: w for g, w in now.items() if g not in bones and g not in gone}
            kept = {g: w for g, w in was.items() if g in deform and w > FLOOR}
            fresh = {g: w for g, w in now.items() if g in deform and w > FLOOR}
            if kept:
                lost = sum(w for g, w in was.items() if g in gone)
                total = sum(fresh.values())
                fresh = {g: lost * w / total for g, w in fresh.items()} if lost > FLOOR and total > 0 else {}
                for g, w in fresh.items():
                    kept[g] = kept.get(g, 0.0) + w
                row.update(kept)
            else:
                row.update(fresh)
            merged.append(row)
        fr.restore_weights({name: merged})
        for g in [g for g in o.vertex_groups if g.name in gone]:
            o.vertex_groups.remove(g)
        normalise(o, bones, limit)
    return skipped


# ---------------------------------------------------------------- the whole order
def nearest_mesh(meshes, point):
    """The mesh with a vertex nearest `point` (world space)."""
    def gap(o):
        local = o.matrix_world.inverted() @ point
        return min(((v.co - local).length for v in o.data.vertices), default=float('inf')) * max(o.matrix_world.to_scale())
    return min(meshes, key=gap)


def chain_mesh(rig, meshes, chain):
    """The mesh a part chain is on: the one with a vertex nearest the chain's tip."""
    return nearest_mesh(meshes, rig.matrix_world @ rig.data.bones[chain[-1]].tail_local)


def weigh_chains(rig, meshes, chains, limit=LIMIT):
    """Part chain weights (part_chains.chain_weights, blended over the body's): `chains` = lists of chain bone names
    root first, or dicts {bones, mesh, vertices}; a chain without a mesh goes on the nearest one. A half mesh (Mirror
    modifier) gets only its own side's chains. Returns {first bone: vertices weighted}."""
    by_name, out = {o.name: o for o in meshes}, {}
    for item in chains if meshes else ():     # a bare rig (no mesh): nothing to weigh the parts to
        item = item if isinstance(item, dict) else dict(bones=item)
        chain = item['bones']
        mesh = by_name.get(item.get('mesh')) or chain_mesh(rig, meshes, chain)
        if is_half(mesh) and rn.side_of(chain[0]) not in ('', is_half(mesh)):
            continue                     # the Mirror modifier makes the other side's part
        out[chain[0]] = pc.chain_weights(rig, mesh, chain, item.get('vertices'), limit=limit)
    return out


def weigh_all(rig, meshes, cfg=None):
    """Weight the character in Generate's order: body (body_weights) -> face (cfg['face'](rig, meshes), a callback:
    face_rig_core takes its weights from the Head, so it comes after the body) -> part chains (cfg['chains']: lists of
    chain bone names root first, or dicts {bones, mesh, vertices}; chain_weights blends them over the body) -> other
    parts (cfg['parts']: callbacks (rig, meshes) -> report, e.g. Add Rig Component's parts) -> Keep
    Weights (cfg['keep'] = remember_weights(...) from before, else fresh weights stay). cfg['body_bones'] overrides the
    body's deform bones, cfg['limit'] the influences. Bones must all exist already. Returns a report dict."""
    cfg = cfg or {}
    limit = cfg.get('limit', LIMIT)
    report = dict(body=body_weights(rig, meshes, cfg.get('body_bones'), limit), face=None)
    if cfg.get('face'):
        report['face'] = cfg['face'](rig, meshes)
    report['chains'] = weigh_chains(rig, meshes, cfg.get('chains', []), limit)
    report['parts'] = [step(rig, meshes) for step in cfg.get('parts', [])]
    if cfg.get('keep'):
        report['kept_skipped'] = keep_weights(rig, cfg['keep'], limit)
    return report
