# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig, parts: generic bone chains (tail, ears, hair, breasts, butt, wing spars) with FK, B-bones, tweaks and
an IK/FK tip control (tail, ears), and their weights. Bone-only: no shape keys, no corrective bones.

A chain is Digit's part-rig style: connected FK bones that are control and deform bone at once (`Tail1`, `Ear1.L`,
`HairBack1`), optional B-bones, optional tweak controls. Tail and ears always get a tip IK control (`IK-Tail`,
`IK-Ear.L`) with the limbs' `IK_FK` switch and `Limb` data (limb_rig.store_limb_data, part 'Tail' / 'Ear'), so the rig
panel shows their IK | FK buttons, snaps and Copy To like an arm's. Names follow docs/BONE_NAMES.md.

    pts = make_chain_guides(guides_obj, 'tail', mesh=body, vertex_group='Tail', segments=6)
    report = build_chain(rig, 'tail', pts, dict(parent='Pelvis', tweaks=True))
    write_handles(guides_obj, 'ear', [base, mid, tip])            # a curved part's guide: Base, Mid, Tip to drag
    report = build_chain(rig, 'ear', curve_joints(handle_points(guides_obj, 'ear'), 5), dict(droop=True))
    chain_weights(rig, body, report['chains'][''], 'Tail')

Coordinates are armature space (meshes must sit on the armature, as in face_rig_core).
"""
import heapq
import math

from mathutils import Vector

try:                                     # inside the add-on package
    from . import bone_collections as bc, chain_weights as cw, limb_rig as lr, rig_names as rn, span_bones as sb
    from .face_rig_core import mk, shape, switch
except ImportError:                      # Scripts/batch_tools copy
    import bone_collections as bc
    import chain_weights as cw
    import limb_rig as lr
    import rig_names as rn
    import span_bones as sb
    from face_rig_core import mk, shape, switch

# kind -> part word, sided (ears, breasts, butt come in pairs, drawn on the left), bone collection, tweak collection,
# default B-bone segments, control shape, IK/FK: the IK_FK switch's default (1 = IK, as the limbs; 0 = FK; None = no tip
# IK); a short part also has the direction it sticks out (its root is the far end back); `droop_down`: its Droop bends
# the chain DOWN about the body's left-right axis (a breast), not about each bone's own X (see bone_up, set_droop)
KINDS = {
    'tail': dict(part='Tail', sided=False, home='Tail', tweak_home='Tail Tweak', bbones=4, widget='WGT-Ring', ik_fk=1.0),
    'ear': dict(part='Ear', sided=True, home='Ears', tweak_home='Ear Tweak', bbones=4, widget='WGT-Ring', ik_fk=1.0),
    'hair': dict(part='Hair', sided=False, home='Hair', tweak_home='Hair Tweak', bbones=3, widget='WGT-Ring'),
    'breast': dict(part='Breast', sided=True, home='Breasts', tweak_home=None, bbones=1, widget='WGT-Ico',
                   outward=(0, -1, 0), droop_down=True),
    'butt': dict(part='Butt', sided=True, home='Groin', tweak_home=None, bbones=1, widget='WGT-Ico',
                 outward=(0, 1, 0)),
    'wing': dict(part='Wing', sided=True, home='Wings', tweak_home='Wing Tweak', bbones=3, widget='WGT-Ring'),  # wing_rig's spars
    'fin': dict(part='Fin', sided=True, home='Wings', tweak_home='Wing Tweak', bbones=3, widget='WGT-Ring'),  # fin_rig's spokes
}
ALIASES = {'breasts': 'breast'}
DEFAULTS = dict(up=None, parent=None, word='', bbone_segments=None, tweaks=False, ik_count=None, radius=None, droop=False)
IK_FK = 'IK_FK'             # the switch on the tip IK control: the limbs' property (rig_parts.SWITCHES), same meaning
HANDLES = ('Base', 'Mid')   # a curved part's guide: bones Base (base -> mid) and Mid (mid -> tip), three points to drag
DROOP_DOWN_SHARE = 0.5      # ... a `droop_down` chain (breast) turns its bones this share of the way to straight down
DROOP_ANGLE = math.radians(120)     # the Droop slider at 1 bends a chain this far in all (shared by its later bones)
LATERAL = Vector((1, 0, 0))  # the axis a `droop_down` chain bends about: left-right, so the bend runs forward -> down
STRAIGHT = 1e-3             # three handles this close to a line (|cross| / lengths) make a straight chain
TWEAK_LENGTH = 0.3          # tweak bone length / its chain bone's
TWEAK_SHAPE = 0.12          # tweak shape radius / its chain bone's length
RING_SHAPE = 0.3            # chain control ring radius / its bone's length (opts radius overrides)
IK_MAX_BONES = 8
OUTER = 0.5                 # select_part reads a part's thickness on this outer share of its chain (free of the body)
SWELL = 2.0                 # ... and takes nothing further than this many times that thickness from the chain
TIP_GAP = 0.25              # ... and finds no part when the mesh is further than this x the chain's length from its tip
MIN_BONE = 1e-4


def kind_info(kind):
    kind = ALIASES.get(kind, kind)
    if kind not in KINDS:
        raise ValueError(f"unknown part kind {kind!r}; use one of {sorted(KINDS)}")
    return kind, KINDS[kind]


def sides_of(info):
    return ('L', 'R') if info['sided'] else ('',)


def stem_of(kind, word=''):
    """'Tail', 'HairBack', 'Ear'."""
    return KINDS[kind]['part'] + rn.pascal(word)


def chain_names(kind, count, side='', word=''):
    """The FK bones of one chain: Tail1..TailN, Ear1.L.., HairBack1.."""
    kind, _ = kind_info(kind)
    return [rn.build(stem_of(kind, word), side, i + 1) for i in range(count)]


def tweak_names(kind, count, side='', word=''):
    kind, _ = kind_info(kind)
    return [rn.build(stem_of(kind, word), side, i + 1, role='TWK') for i in range(count)]


def ik_name(kind, side='', word=''):
    kind, _ = kind_info(kind)
    return rn.build(stem_of(kind, word), side, role='IK')


def handle_names(kind, side='', word=''):
    """The two guide bones of a curved part: TailBase, TailMid; EarBase.L, EarMid.L."""
    kind, _ = kind_info(kind)
    return [rn.build(stem_of(kind, word) + handle, side) for handle in HANDLES]


def mirror_x(p):
    return Vector((-p[0], p[1], p[2]))


# ---------------------------------------------------------------- guides
def group_vertices(mesh, vertex_group):
    """Indices of the vertices with weight in a vertex group."""
    gi = mesh.vertex_groups[vertex_group].index
    return [v.index for v in mesh.data.vertices if any(e.group == gi and e.weight > 0 for e in v.groups)]


def part_vertices(arm, mesh, vertex_group=None, sided=False):
    """{vertex index: armature-space co} of a part: the vertex group's (or the whole mesh's) vertices; a sided part
    uses just its left half (x > 0), whichever sides the group holds."""
    to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
    picked = group_vertices(mesh, vertex_group) if vertex_group else range(len(mesh.data.vertices))
    out = {i: to_rig @ mesh.data.vertices[i].co for i in picked}
    return {i: co for i, co in out.items() if co.x > 0} if sided else out


def geodesic(mesh, verts, sources):
    """Distance along the mesh edges, inside `verts` ({index: co}), from the `sources` indices."""
    graph = {i: [] for i in verts}
    for e in mesh.data.edges:
        a, b = e.vertices
        if a in graph and b in graph:
            d = (verts[a] - verts[b]).length
            graph[a].append((b, d))
            graph[b].append((a, d))
    dist = {i: 0.0 for i in sources}
    heap = [(0.0, i) for i in sources]
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > dist.get(i, math.inf):
            continue
        for j, w in graph[i]:
            if d + w < dist.get(j, math.inf):
                dist[j] = d + w
                heapq.heappush(heap, (d + w, j))
    return dist


def principal_axis(cos):
    """Unit direction of the largest spread of the points (power iteration on their covariance)."""
    mean = sum(cos, Vector()) / len(cos)
    rel = [c - mean for c in cos]
    axis = max(rel, key=lambda r: r.length_squared).normalized()
    for _ in range(12):
        nxt = sum((r * r.dot(axis) for r in rel), Vector())
        if nxt.length < 1e-12:
            break
        axis = nxt.normalized()
    return axis


def root_sources(verts, outward, root, body_centre):
    """Vertices at the root end of a part. A short part (`outward` given): the end farthest back along it. Else the end
    of its principal axis nearest `root`, or nearest `body_centre` (a tail or ear tip is farther from the body)."""
    if outward is not None:
        axis, ends = Vector(outward).normalized(), None
    else:
        axis = principal_axis(list(verts.values()))
    proj = {i: co.dot(axis) for i, co in verts.items()}
    lo, hi = min(proj.values()), max(proj.values())
    margin = 0.05 * ((hi - lo) or 1.0)
    back = [i for i, p in proj.items() if p <= lo + margin]
    if outward is not None:
        return back
    front = [i for i, p in proj.items() if p >= hi - margin]
    target = Vector(root) if root is not None else Vector(body_centre) if body_centre is not None else None
    if target is None:
        return back
    return min((back, front), key=lambda g: min((verts[i] - target).length for i in g))


def lay_points(mesh, verts, segments, root=None, outward=None, body_centre=None):
    """segments + 1 joints along a part's centreline: the centroid of the vertices at equal distances along the mesh
    from the root end (see root_sources). Follows a curled tail, which a straight axis would not."""
    dist = geodesic(mesh, verts, root_sources(verts, outward, root, body_centre))
    step = (max(dist.values()) or 1.0) / segments
    points = []
    for k in range(segments + 1):
        half = step * (0.5 if 0 < k < segments else 0.25)
        near = [verts[i] for i, d in dist.items() if abs(d - k * step) <= half]
        points.append(sum(near, Vector()) / len(near) if near else None)
    for k, p in enumerate(points):                   # a gap in the mesh: halfway between the neighbours
        if p is None:
            a = next(q for q in reversed(points[:k]) if q is not None)
            b = next(q for q in points[k + 1:] if q is not None)
            points[k] = a.lerp(b, 0.5)
    return points


def middle_point(mesh, verts, base, tip, band=0.1):
    """The centreline point halfway along a part (`verts`: {index: co}) from `base` to `tip`: the centroid of its
    vertices halfway by distance along the mesh from the ones nearest `base` to the one nearest `tip` (within `band` x
    that distance). Follows a curled tail or a cupped ear; the straight midpoint when the mesh gives no answer."""
    near_base = sorted(verts, key=lambda i: (verts[i] - base).length)[:max(3, len(verts) // 20)]
    dist = geodesic(mesh, verts, near_base)
    end = dist.get(min(verts, key=lambda i: (verts[i] - tip).length)) or max(dist.values())
    near = [verts[i] for i, d in dist.items() if abs(d - end / 2) <= band * end]
    return sum(near, Vector()) / len(near) if near else base.lerp(tip, 0.5)


def make_chain_guides(arm_or_guides, kind, points=None, vertex_group=None, mesh=None, segments=4, root=None, word='',
                      write=True):
    """Joint points (segments + 1, armature space of `arm_or_guides`; the left side of a sided part) of a chain: the given
    `points`, or laid along `mesh` (just `vertex_group` of it, if given). With `write` they are also made into guide
    bones `Tail1..` (plus `.R` mirrors) in `arm_or_guides`, a separate guide armature object, for the user to drag
    (read back with guide_points). `root` = a point near the root end (default: the end nearest the mesh's centre)."""
    kind, info = kind_info(kind)
    if points is not None:
        points = [Vector(p) for p in points]
    else:
        if mesh is None:
            raise ValueError("make_chain_guides needs points or a mesh")
        verts = part_vertices(arm_or_guides, mesh, vertex_group, info['sided'])
        if len(verts) < 2:
            raise ValueError(f"no {kind} vertices found" + (f" in {vertex_group!r}" if vertex_group else ""))
        to_rig = arm_or_guides.matrix_world.inverted() @ mesh.matrix_world
        centre = sum((to_rig @ Vector(c) for c in mesh.bound_box), Vector()) / 8
        points = lay_points(mesh, verts, segments, root=root, outward=info.get('outward'), body_centre=centre)
    if write:
        write_guides(arm_or_guides, kind, points, word)
    return points


def write_guides(guides, kind, points, word='', names=None):
    """Guide bones along `points` (and the mirrored side of a sided part) in the guide armature object. `names(side)`
    gives the bone names (default: the chain's, Tail1..)."""
    kind, info = kind_info(kind)
    names = names or (lambda side: chain_names(kind, len(points) - 1, side, word))
    with sb.Kept(guides) as k:
        k.edit()
        for side in sides_of(info):
            pts = points if side != 'R' else [mirror_x(p) for p in points]
            parent = None
            for i, name in enumerate(names(side)):
                mk(guides.data, name, pts[i], pts[i + 1], parent, connect=i > 0)
                parent = name
        k.done()


def write_handles(guides, kind, handles, word=''):
    """A curved part's guide (tail, ears): two connected bones through its Base, Mid and Tip points."""
    write_guides(guides, kind, handles, word, lambda side: handle_names(kind, side, word))


def bone_points(guides, names):
    """Joint points of the connected guide bones `names` (as far as they exist), or None when the first is missing."""
    bones, found = guides.data.bones, []
    for n in names:
        if n not in bones:
            break
        found.append(bones[n])
    if not found:
        return None
    return [b.head_local.copy() for b in found] + [found[-1].tail_local.copy()]


def guide_points(guides, kind, word=''):
    """The joint points of a chain's guide bones (the left side of a sided part), or None when it has none."""
    kind, info = kind_info(kind)
    return bone_points(guides, chain_names(kind, 64, 'L' if info['sided'] else '', word))


def handle_points(guides, kind, word=''):
    """[Base, Mid, Tip] of a curved part's guide (the left side of a sided part), or None when it has none."""
    kind, info = kind_info(kind)
    points = bone_points(guides, handle_names(kind, 'L' if info['sided'] else '', word))
    return points if points and len(points) == len(HANDLES) + 1 else None


# ---------------------------------------------------------------- the curve through three handles
def circle_arc(base, mid, tip):
    """(centre, radius, u, v, sweep) of the circle arc from `base` through `mid` to `tip` (point at angle a =
    centre + radius (cos a u + sin a v), a from 0 to sweep), or None when the three are (nearly) in a line."""
    a, b = base - tip, mid - tip
    normal = a.cross(b)
    if normal.length < STRAIGHT * a.length * b.length:
        return None
    centre = tip + (b * a.length_squared - a * b.length_squared).cross(normal) / (2 * normal.length_squared)
    radius = (base - centre).length
    u = (base - centre) / radius
    v = (mid - base).cross(tip - base).normalized().cross(u)     # base -> mid -> tip runs counter-clockwise round it
    to_tip = tip - centre
    return centre, radius, u, v, math.atan2(to_tip.dot(v), to_tip.dot(u)) % (2 * math.pi)


def curve_joints(handles, count):
    """count + 1 joints at equal steps along the smooth curve through the three handles (Base, Mid, Tip): the circle
    arc through them, so a curled tail (Mid pulled to the side, even past the tip) bends evenly; a straight line
    when they are in a line."""
    base, mid, tip = (Vector(p) for p in handles)
    arc = circle_arc(base, mid, tip)
    if arc is None:
        return [base.lerp(tip, k / count) for k in range(count + 1)]
    centre, radius, u, v, sweep = arc
    angles = [sweep * k / count for k in range(count + 1)]
    return [centre + (u * math.cos(t) + v * math.sin(t)) * radius for t in angles]


def chain_position(points, co):
    """(where `co` sits along the polyline `points` in joint units, its distance from the polyline)."""
    u = cw.polyline_param(points, co)
    i = min(int(u), len(points) - 2)
    a, b = points[i], points[i + 1]
    t = u - i
    return u, (a + (b - a) * t - co).length


def grow(mesh, candidates, seeds):
    """The candidate vertices reachable from the seeds along the mesh edges, through candidates only."""
    graph = {i: [] for i in candidates}
    for e in mesh.data.edges:
        a, b = e.vertices
        if a in graph and b in graph:
            graph[a].append(b)
            graph[b].append(a)
    seen = {i for i in seeds if i in graph}         # a seed outside the candidates grows nothing
    todo = list(seen)
    while todo:
        for j in graph[todo.pop()]:
            if j not in seen:
                seen.add(j)
                todo.append(j)
    return seen


def select_part(arm, mesh, points, side='', reach=1.0, margin=1.15, swell=SWELL):
    """Vertex indices of the part that a chain over `points` (joints, armature space, root first) is for, so no vertex
    group is needed: grown along the mesh from the tip, only on the tip side of the base plane (through the root joint,
    square to the first bone, so the head / body stays out), inside a capsule round the chain. The capsule radius at each
    joint is measured from the first growth, then grown again inside `margin` x it. The first growth is capped: the
    part's thickness is read on its outer half (free of the body), and nothing further than `swell` x that from the
    chain counts (a thin tail on one mesh with the body would otherwise walk over the hips into the legs); `reach` x
    the chain's length is the upper bound. `side` 'R' mirrors the points (they are the left side's). A sided part keeps
    to its own side of x = 0. No part (empty) when the mesh is more than TIP_GAP x the chain's length from its tip
    (a default tail guide behind a character without a tail)."""
    points = [Vector(p) if side != 'R' else mirror_x(p) for p in points]
    to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
    cos = {v.index: to_rig @ v.co for v in mesh.data.vertices}
    total = sum((b - a).length for a, b in zip(points, points[1:]))
    normal = (points[1] - points[0]).normalized()
    behind = 0.05 * (points[1] - points[0]).length
    info = {}
    for i, co in cos.items():
        if (co - points[0]).dot(normal) >= -behind and (not side or (co.x > 0 if side == 'L' else co.x < 0)):
            info[i] = chain_position(points, co)
    tip = min(info, key=lambda i: (cos[i] - points[-1]).length, default=None)
    if tip is None or (cos[tip] - points[-1]).length > TIP_GAP * total:
        return []
    outer = grow(mesh, {i for i, (u, d) in info.items() if d <= reach * total and u >= OUTER * (len(points) - 1)}, [tip])
    thick = sorted(info[i][1] for i in outer)[int(0.95 * (len(outer) - 1))] if len(outer) > 2 else reach * total
    cap = min(reach * total, swell * thick) if swell else reach * total
    first = grow(mesh, {i for i, (u, d) in info.items() if d <= cap}, [tip])
    radius = []
    for k in range(len(points)):
        near = [info[i][1] for i in first if abs(info[i][0] - k) <= 0.75]
        radius.append(max(near, default=0.0))
    radius = [max(radius[max(k - 1, 0):k + 2]) for k in range(len(radius))]       # a joint is never thinner than its neighbours
    def allowed(u):
        k = min(int(u), len(points) - 2)
        return margin * (radius[k] + (radius[k + 1] - radius[k]) * (u - k))
    return sorted(grow(mesh, {i for i, (u, d) in info.items() if d <= allowed(u)}, [tip]))


def flat_normal(arm, mesh, indices, flatness=0.5):
    """The normal of a flat part (an ear blade) in armature space: its thinnest direction, or None when the part is not
    flat (spread along it over `flatness` x the spread along the blade's width). Sign: toward +Z, else toward -Y."""
    to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
    cos = [to_rig @ mesh.data.vertices[i].co for i in indices]
    mean = sum(cos, Vector()) / len(cos)
    rel = [c - mean for c in cos]
    length = principal_axis(rel)
    flat = [r - length * r.dot(length) for r in rel]
    width = principal_axis(flat)
    normal = length.cross(width).normalized()
    spread = lambda axis: math.sqrt(sum(r.dot(axis) ** 2 for r in rel) / len(rel))
    if spread(normal) > flatness * spread(width):
        return None
    return normal if (normal.z or -normal.y) > 0 else -normal


# ---------------------------------------------------------------- build
def roll_reference(direction):
    """The vector a chain's roll is aligned to: +Z, or -Y for a chain that runs up or down."""
    return Vector((0, -1, 0)) if abs(direction.normalized().z) > 0.9 else Vector((0, 0, 1))


def set_handles(E, names, tweaks, segments):
    """B-bone handles of a chain's edit bones: tangent to the neighbouring bone (one smooth curve), or at the
    tweak controls at the joints when there are tweaks (absolute, like Rigify: the tweak at a bone's tail; the first bone starts un-tweaked)."""
    for i, name in enumerate(names):
        eb = E[name]
        eb.bbone_segments = segments
        eb.bbone_easein = eb.bbone_easeout = 1.0
        for end, nb in (('start', i - 1), ('end', i + 1)):
            if segments == 1:
                handle, kind = None, 'AUTO'
            elif tweaks:
                handle = (tweaks[i - 1] if i > 0 else None) if end == 'start' else tweaks[i]
                kind = 'ABSOLUTE' if handle else 'AUTO'
            else:
                handle = names[nb] if 0 <= nb < len(names) else None
                kind = 'TANGENT' if handle else 'AUTO'
            setattr(eb, f'bbone_handle_type_{end}', kind)
            setattr(eb, f'bbone_custom_handle_{end}', E[handle] if handle else None)
        bc.thin_bbones([eb])


def ring_handles(E, names, nodes=None, corners=(), straight=(), segments=None, mapping=None, closed=True, ease=False):
    """B-bone handles of a closed ring of edit bones (names[k] runs from node k to node k + 1): one smooth closed curve,
    handles on the neighbouring segments (ABSOLUTE: Catmull-Rom tangents, the lid ring) or, with `nodes` (bone names,
    one per node), on the node bones (TANGENT: a node's Y axis is the curve's direction there, so turning the node
    turns the curve; the wing loop). No handle across the `corners` (node indices: a real corner) and none on the
    `straight` segments (indices). `segments` / `mapping`: B-bone segments and vertex mapping of every bone. `ease`:
    a handle's Y scale multiplies the ease at its end (scaling the node up makes the curve fuller there).
    closed=False: an open chain (names[k] from node k to node k + 1, one node more than bones): no neighbour handle
    past either end (the ring's node 0 then counts as a corner); node handles reach both ends."""
    count = len(names)
    if not closed and not nodes:
        corners = (*corners, 0, count)
    for k, name in enumerate(names):
        eb = E[name]
        after = (k + 1) % count if closed else k + 1
        start = None if k in corners or k in straight else (E[nodes[k]] if nodes else E[names[k - 1]])
        end = None if after in corners or k in straight else (E[nodes[after]] if nodes else E[names[after]])
        bone_handles(eb, start, end, 'TANGENT' if nodes else 'ABSOLUTE', ease)
        if segments is not None:
            eb.bbone_segments = segments
        if mapping is not None:
            eb.bbone_mapping_mode = mapping
        bc.thin_bbones([eb])


def bone_handles(eb, start, end, kind='TANGENT', ease=False):
    """An edit bone's B-bone handles: `start` / `end` edit bones (None: AUTO) of handle type `kind`; `ease`: each
    handle's Y scale multiplies the ease at its end."""
    for side, handle in (('start', start), ('end', end)):
        setattr(eb, f'bbone_handle_type_{side}', kind if handle else 'AUTO')
        setattr(eb, f'bbone_custom_handle_{side}', handle)
        setattr(eb, f'bbone_handle_use_ease_{side}', bool(ease and handle))


def drop_bones(E, names):
    """Remove edit bones, clearing any B-bone handle that points at them first."""
    for name in [n for n in names if n in E]:
        for other in E:
            for end in ('start', 'end'):
                if getattr(other, f'bbone_custom_handle_{end}') == E[name]:
                    setattr(other, f'bbone_custom_handle_{end}', None)
                    setattr(other, f'bbone_handle_type_{end}', 'AUTO')
        E.remove(E[name])


def build_chain(arm, kind, guide_points, opts=None):
    """Build (or rebuild) one part's chain from its joint points (armature space; the left side of a sided part, the
    right one is mirrored). Rebuilding with a feature off removes just that feature's bones.
    opts (all optional):
      parent         bone the chain hangs on (a sided chain uses the parent's mirror when there is one)
      word           names a further chain of the same kind: 'Back' -> HairBack1
      bbone_segments B-bone segments per bone (default by kind: tail 4, ear 4, hair 3, breast / butt 1 = off)
      tweaks         TWK- controls at the joints that bend the B-bones (tail / ear / hair; needs 2+ B-bone segments)
      ik_count       tail / ears always get an IK- control at the tip, IK on the last `ik_count` bones (default all, up
                     to IK_MAX_BONES); the control holds the IK_FK switch (1 = IK, 0 = FK; default by kind) and the
                     Limb data of the snap buttons. Other kinds get no tip IK. (An old `ik` option is ignored.)
      up             direction the bones' local Z points (their roll); give an ear's flat_normal so it bends about
                     its width. Default +Z (-Y for a chain that runs up or down)
      radius         control ring radius (default 0.3 of a bone's length)
      droop          a Droop slider on the first bone that folds the bones after it together (floppy ears; in IK it swings
                     the tip control about the chain's root via an MCH- parent)
    Returns {'chains': {side: [bones]}, 'tweaks': {side: [...]}, 'ik': {side: control}, 'bones': every bone made}."""
    kind, info = kind_info(kind)
    o = {**DEFAULTS, **(opts or {})}
    points = [Vector(p) for p in guide_points]
    count = len(points) - 1
    if count < 1:
        raise ValueError("a chain needs at least two points")
    if any((b - a).length < MIN_BONE for a, b in zip(points, points[1:])):
        raise ValueError("two guide points of the chain are on top of each other")
    use_tweaks = bool(o['tweaks']) and info['tweak_home'] is not None
    use_ik = info.get('ik_fk') is not None
    segments = o['bbone_segments'] or info['bbones']
    if use_tweaks:
        segments = max(2, segments)
    word = o['word']
    plan = {side: dict(pts=points if side != 'R' else [mirror_x(p) for p in points],
                       chain=chain_names(kind, count, side, word), tweaks=tweak_names(kind, count, side, word),
                       ik=ik_name(kind, side, word), droop_mch=rn.helper(ik_name(kind, side, word), 'Droop'))
            for side in sides_of(info)}
    use_droop_ik = use_ik and bool(o['droop']) and count > 1
    report = dict(chains={}, tweaks={}, ik={}, bones=[])
    with sb.Kept(arm) as k:
        E = k.edit()
        drop_bones(E, [n for p in plan.values() for n in (p['tweaks'] if not use_tweaks else []) + ([] if use_ik else [p['ik']]) + ([] if use_droop_ik else [p['droop_mch']])])
        left_roll = {}
        for side, p in plan.items():
            parent = next((n for n in (o['parent'] and rn.with_side(o['parent'], side), o['parent']) if n and n in E), None)
            pts, names = p['pts'], p['chain']
            for i, name in enumerate(names):
                eb = mk(arm.data, name, pts[i], pts[i + 1], parent if i == 0 else names[i - 1], deform=True, connect=i > 0)
                if side == 'R':
                    eb.roll = -left_roll[i]
                else:
                    eb.align_roll(bone_up(info, o, points, i))
                    left_roll[i] = eb.roll
            if use_tweaks:
                for i, name in enumerate(p['tweaks']):
                    mk(arm.data, name, pts[i + 1], pts[i + 1] + (pts[i + 1] - pts[i]) * TWEAK_LENGTH, names[i],
                       roll=E[names[i]].roll)
            set_handles(E, names, p['tweaks'] if use_tweaks else None, segments)
            if use_ik:
                reach = pts[-1] - pts[-2]
                ik_parent = o['parent'] if o['parent'] and o['parent'] in E else None
                if use_droop_ik:                                   # the control's parent: turns about the chain's root
                    mk(arm.data, p['droop_mch'], pts[0], pts[1], ik_parent, roll=E[names[0]].roll)
                    ik_parent = p['droop_mch']
                mk(arm.data, p['ik'], pts[-1], pts[-1] + reach.normalized() * max(reach.length, 0.15 * (pts[-1] - pts[0]).length),
                   ik_parent, roll=E[names[-1]].roll)
        k.done()
        for side, p in plan.items():
            style_chain(arm, info, p, o, use_tweaks, use_ik)
            report['chains'][side] = p['chain']
            if use_tweaks:
                report['tweaks'][side] = p['tweaks']
            if use_ik:
                report['ik'][side] = p['ik']
            report['bones'] += p['chain'] + (p['tweaks'] if use_tweaks else []) + ([p['ik']] if use_ik else []) + ([p['droop_mch']] if use_droop_ik else [])
    return report


def bone_up(info, o, points, i):
    """The direction bone i's local Z points (its roll): the `up` option, else for a `droop_down` chain the one that
    makes local X the left-right axis (so a +X turn tips the bone down, see set_droop), else a default."""
    if o['up'] is not None:
        return Vector(o['up'])
    if info.get('droop_down') and len(points) > 2:
        return LATERAL.cross(points[i + 1] - points[i])
    return roll_reference(points[-1] - points[0])


def style_chain(arm, info, p, o, use_tweaks, use_ik):
    """Pose side of a chain: control shapes, bone collections, the tip IK constraint and its IK/FK switch."""
    P = arm.pose.bones
    names, pts = p['chain'], p['pts']
    for i, name in enumerate(names):
        shape(P[name], info['widget'], o['radius'] or RING_SHAPE * (pts[i + 1] - pts[i]).length)
        bc.place_bone(arm, name, info['home'], True)
    if use_tweaks:
        for i, name in enumerate(p['tweaks']):
            shape(P[name], 'WGT-Ico', TWEAK_SHAPE * (pts[i + 1] - pts[i]).length)
            bc.place_bone(arm, name, info['tweak_home'], False)
    for name in names:                                             # a chain that grew had its IK one bone back
        lr.remove_constraint(arm, name, 'IK')
    switch_path = rig_tip_ik(arm, info, p, o) if use_ik else None
    if p['droop_mch'] in arm.data.bones:
        bc.place_bone(arm, p['droop_mch'], 'Mechanism', False)
    set_droop(arm, names, o['droop'] and len(names) > 1, switch_path, p['droop_mch'] if use_ik else None,
              down=bool(info.get('droop_down')))


def rig_tip_ik(arm, info, p, o):
    """The tip IK of a chain, built like a limb's: an IK constraint on the last bone (the last `ik_count` bones, no
    pole) whose influence is the control's IK_FK switch, and the control's Limb data (part = the kind's word) for the
    rig panel's IK | FK snap and Copy To. The chain bones stay the FK controls. Returns the switch's data path."""
    P = arm.pose.bones
    names, pts = p['chain'], p['pts']
    ctrl = P[p['ik']]
    shape(ctrl, 'WGT-Ico', 0.5 * (pts[-1] - pts[-2]).length)
    bc.place_bone(arm, ctrl.name, info['home'], False)
    count = min(o['ik_count'] or len(names), len(names), IK_MAX_BONES)
    con = lr.get_constraint(P[names[-1]], 'IK', 'IK')
    con.target, con.subtarget = arm, ctrl.name
    con.chain_count = count
    con.use_tail = True
    con.use_stretch = False
    lr.drop_prop(ctrl, 'IK')                                       # the old tip IK slider (before IK_FK)
    return switch_tip_ik(arm, ctrl.name, names, count, con, info['part'], info['ik_fk'])


def switch_tip_ik(arm, ctrl_name, names, count, con, part, default, pole=None, full=1.0):
    """The IK/FK switch of a tip IK (`con` on names[-1], moving the last `count` of the chain `names`): IK_FK on the
    control (1 = IK) drives the constraint's influence (times `full`, the influence it had), and the control's Limb
    data (part = the rig panel's page word) feeds the IK | FK snap. Returns the switch's data path."""
    ctrl = arm.pose.bones[ctrl_name]
    switch(ctrl, IK_FK, 0.0, 1.0, f"IK (1) or FK (0): the tip control, or the {part.lower()} bones themselves",
           default, overshoot=1)
    path = f'{lr.bone_path(ctrl_name)}["{IK_FK}"]'
    expr = 'ik' if abs(full - 1.0) < 1e-6 else f'ik * {full:.6f}'
    lr.add_driver(arm, f'{lr.bone_path(names[-1])}.constraints["{con.name}"].influence', None, expr, {'ik': path})
    lr.store_limb_data(arm, dict(ctrl=ctrl_name, chain=names[-count:], fk=names, tip=names[-1], target=ctrl_name,
                                 pole=pole, part=part), [])
    return path


def add_tip_switch(arm, ctrl_name, part):
    """Give an existing tip IK (a part armature's ponytail: an IK on the last DEF bone aimed at `ctrl_name`) the limbs'
    IK/FK switch, at 1 = IK so nothing moves. The bones the IK moves are the FK controls; those only in Deform /
    Mechanism collections also go in an "FK <part>" collection that shows while in FK. Returns the chain's names."""
    found = next(((pb, con) for pb, con in lr.tip_iks(arm) if con.subtarget == ctrl_name), None)
    if found is None:
        raise ValueError(f"no IK aims at {ctrl_name}")
    pb, con = found
    names = [b.name for b in reversed(lr.ik_chain(pb, con))]
    pole = con.pole_subtarget if con.pole_target == arm and con.pole_subtarget in arm.pose.bones else None
    switch_tip_ik(arm, ctrl_name, names, len(names), con, part, 1.0, pole, full=con.influence)
    bc.show_chain_in_fk(arm, ctrl_name, names, f"FK {part}")
    return names


def set_droop(arm, names, on, ik_switch=None, ik_mch=None, down=False):
    """A Droop slider (-1..1) on a chain's first bone that bends every later bone about its X axis by a share of
    DROOP_ANGLE: one control folds a floppy ear down (-1 the other way). A Transformation constraint adds the bend
    on top of each bone's own rotation, so the FK controls stay free. Off removes the slider and its constraints.
    `ik_switch` = data path of the chain's IK_FK: these bends fade out as the chain goes to IK (influence 1 - IK_FK),
    so they never fight the tip IK. In IK the same slider turns `ik_mch` (the IK control's parent, at the chain's
    root, same axes as the first bone) about X by the full DROOP_ANGLE: the tip control swings down and the IK chain
    follows. 0 = identity, so rest is exact.
    `down` (a breast): the bones are rolled so their local X is the left-right axis, so + Droop tips the chain down
    whatever its curve (bend_angles), not evenly about each bone."""
    P = arm.pose.bones
    first = P[names[0]]
    if ik_mch and ik_mch in P:
        arm.driver_remove(f'{lr.bone_path(ik_mch)}.rotation_euler', 0)
        P[ik_mch].rotation_euler = (0.0, 0.0, 0.0)
    for name in names[1:]:
        lr.remove_constraint(arm, name, 'Droop')
    if not on:
        if 'Droop' in first:
            del first['Droop']
        return
    lr.add_prop(first, 'Droop', 0.0, -1.0, 1.0, "Droop: 1 folds the part down along its length, -1 the other way")
    if ik_mch and ik_mch in P:
        P[ik_mch].rotation_mode = 'XYZ'
        lr.add_driver(arm, f'{lr.bone_path(ik_mch)}.rotation_euler', 0, f'droop * {DROOP_ANGLE:.6f}',
                      {'droop': f'{lr.bone_path(names[0])}["Droop"]'})
    angles = bend_angles(arm, names[1:]) if down else [DROOP_ANGLE / (len(names) - 1)] * (len(names) - 1)
    for name, angle in zip(names[1:], angles):
        con = P[name].constraints.new('TRANSFORM')
        con.name = 'Droop'
        con.target, con.subtarget = arm, names[0]      # any bone: the input is ignored (to min = to max)
        con.owner_space = con.target_space = 'LOCAL'
        con.from_min_x, con.from_max_x = -1.0, 1.0
        con.map_to = 'ROTATION'
        con.mix_mode_rot = 'AFTER'
        for end in ('min', 'max'):
            lr.add_driver(arm, f'{lr.bone_path(name)}.constraints["Droop"].to_{end}_x_rot', None,
                          f'droop * {angle:.6f}', {'droop': f'{lr.bone_path(names[0])}["Droop"]'})
        if ik_switch:
            lr.add_driver(arm, f'{lr.bone_path(name)}.constraints["Droop"].influence', None, '1 - ik', {'ik': ik_switch})


def bend_angles(arm, names):
    """The local bend (radians about X, per bone) a downward Droop of 1 gives `names`, the bones after a chain's first.
    Each bone's direction moves DROOP_DOWN_SHARE of the way to straight down (in the front-to-back plane), so a chain
    that curves down stays on that side of it: a bone's own bend is its move minus its parent's (the parent's turn
    carries it)."""
    angles, parent_turn = [], 0.0
    for name in names:
        bone = arm.data.bones[name]
        d = bone.tail_local - bone.head_local
        to_down = -math.pi / 2 - math.atan2(d.z, d.y)
        to_down = (to_down + math.pi) % (2 * math.pi) - math.pi           # the short way round, -pi..pi
        turn = DROOP_DOWN_SHARE * to_down
        angles.append(turn - parent_turn)
        parent_turn = turn
    return angles


# ---------------------------------------------------------------- weights
def write_part_weights(mesh, vi, share, along, blend, bone_groups, groups, limit=4):
    """One vertex's weights: the part's `share` ({bone: weight}, sums to 1) over what it had. Where the vertex already
    has other bone weights (the body's), the part takes over gradually: 0 at `along` 0 (the part's root) to all of it
    at `along` = `blend` (0 = the part replaces everything) and the body keeps the rest, so weights still sum to 1. At
    most `limit` influences. bone_groups = {group index: bone name} of the mesh, groups = {bone: vertex group}."""
    v = mesh.data.vertices[vi]
    old = {bone_groups[e.group]: e.weight for e in v.groups if e.group in bone_groups and bone_groups[e.group] not in share}
    rest = sum(old.values())
    take = cw.smoothstep(0.0, blend, along) if rest > 1e-6 and blend > 0 else 1.0
    new = {n: w * take for n, w in share.items()}
    if rest > 1e-6:
        new.update({n: w * (1 - take) / rest for n, w in old.items()})
    keep = dict(sorted(((n, w) for n, w in new.items() if w > 1e-4), key=lambda kv: -kv[1])[:limit])
    total = sum(keep.values())
    for e in list(v.groups):
        if e.group in bone_groups:
            mesh.vertex_groups[e.group].remove([vi])
    for n, w in keep.items():
        (groups.get(n) or mesh.vertex_groups[n]).add([vi], w / total, 'REPLACE')


def chain_weights(arm, mesh, chain, part_vertices=None, blend=0.3, degree=2, limit=4, mirror=True):
    """Weight the part's vertices to its chain (bone names, root first): each bone's share follows the vertex's place
    along the chain (chain_weights B-spline, so neighbouring bones blend smoothly). Where the vertex already has other
    bone weights (the body's), the chain takes over gradually: 0 at the root to all of it `blend` of the way along
    (0 = the chain replaces everything) and the body keeps the rest, so weights still sum to 1. At most `limit`
    influences per vertex. `part_vertices` = vertex indices or a vertex group name, or None to select the part from the
    chain itself (select_part). With `mirror` the missing
    opposite-side groups are added (empty), for a Mirror modifier. Returns the number of vertices weighted."""
    bones = arm.data.bones
    count = len(chain)
    to_rig = arm.matrix_world.inverted() @ mesh.matrix_world
    pts = [bones[n].head_local.copy() for n in chain] + [bones[chain[-1]].tail_local.copy()]
    groups = {n: mesh.vertex_groups.get(n) or mesh.vertex_groups.new(name=n) for n in chain}
    bone_groups = {g.index: g.name for g in mesh.vertex_groups if g.name in bones}
    mine = set(chain)
    if part_vertices is None:
        side = rn.side_of(chain[0])
        left = [bones[n].head_local.copy() for n in chain] + [bones[chain[-1]].tail_local.copy()]
        idx = select_part(arm, mesh, left if side != 'R' else [mirror_x(p) for p in left], side)
    else:
        idx = group_vertices(mesh, part_vertices) if isinstance(part_vertices, str) else list(part_vertices)
    for vi in idx:
        u = cw.polyline_param(pts, to_rig @ mesh.data.vertices[vi].co)
        share = cw.basis(u - 0.5, count, False, degree)
        write_part_weights(mesh, vi, {n: share.get(i, 0.0) for i, n in enumerate(chain)}, u / count, blend, bone_groups,
                           groups, limit)
    if mirror:
        cw.ensure_mirror_groups(mesh, only=mine)
    return len(idx)
