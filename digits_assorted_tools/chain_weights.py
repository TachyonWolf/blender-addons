# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/chain_weights.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Skin weights for chains of segment bones (Stretch To bones between face controls) running along
an edge loop (eyelid ring, lip line), plus weight clean-up helpers. Run inside Blender.

rebuild():

Weights along the loop: uniform quadratic B-spline over the chain's nodes (segment midpoints), so
neighbouring segments overlap and a lid/lip edge deforms as a smooth curve instead of straight
chords with kinks. Across the loop: smoothstep falloff by geodesic distance from the loop, with
per-node radii for the outer skin and the inner side (eye socket, mouth bag). The rest of each
vertex keeps its old non-chain weights (Head, brows, jaw...), renormalised; vertices that had none
take them from the nearest vertex on the same side that does.
smooth(): Laplacian weight smoothing that never mixes across a cut (upper vs lower lip).
respread(): smoothing ALONG a loop only: a vertex's share of a loop's groups by its loop position (B-spline).
symmetrize_center(): equal Left/Right weights on mirror-plane vertices (Mirror modifier seams).
transfer_from_surface() / transfer_from_loop(): parts on the skin take the skin's weights (a
  tube along an edge loop, like a lid liner, from the loop so its cross-section stays round).
"""
import bmesh, heapq, math
from collections import defaultdict
from mathutils import Vector
from mathutils.geometry import intersect_point_line

try:                                     # inside the add-on package
    from . import rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import rig_names as rn


def smoothstep(e0, e1, x):
    if e1 <= e0:
        return 0.0 if x < e0 else 1.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def bspline2(x):
    """Uniform quadratic B-spline centred on 0 (support -1.5..1.5, partition of unity)."""
    x = abs(x)
    if x < 0.5:
        return 0.75 - x * x
    if x < 1.5:
        return 0.5 * (1.5 - x) ** 2
    return 0.0


def bspline(x, degree=2):
    """Uniform B-spline of degree 1 (tent), 2 or 3 centred on 0 (support +-(degree+1)/2, partition of unity).
    Higher degree = wider and smoother (degree 3 is C2: no shading steps where weights blend)."""
    x = abs(x)
    if degree == 1:
        return max(0.0, 1.0 - x)
    if degree == 2:
        return bspline2(x)
    if x < 1:
        return 2 / 3 - x * x + 0.5 * x ** 3
    return (2 - x) ** 3 / 6 if x < 2 else 0.0


def basis(s, n, closed, degree=2, width=1.0):
    """{node index: weight} at parameter s over n nodes at integers 0..n-1 (B-spline of `degree`, see bspline,
    stretched to `width` node spacings; weights sum to 1)."""
    out = {}
    reach = (degree + 1) / 2 * width
    for k in range(math.floor(s - reach), math.ceil(s + reach) + 1):
        w = bspline((s - k) / width, degree)
        if w <= 0:
            continue
        kk = k % n if closed else min(max(k, 0), n - 1)   # open ends: clamp (end node absorbs)
        out[kk] = out.get(kk, 0.0) + w
    t = sum(out.values())
    return {k: w / t for k, w in out.items()}


def polyline_param(points, co):
    """Parameter (node index + t) of the closest point of `co` on the polyline `points`."""
    best = None
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        _, t = intersect_point_line(co, a, b)
        t = max(0.0, min(1.0, t))
        d = (a + (b - a) * t - co).length
        if best is None or d < best[0]:
            best = (d, i + t)
    return best[1]


def find_ring(bm, ctrl_pts, closed=True, tol=0.006, every=False):
    """Quad edge loop closest to a control polyline (edges within `tol` of it start a walk). Returns the
    vertex index list (ordered), or [] if none. every: all such loops instead, nearest first."""
    def pdist(p):
        best = 9
        n = len(ctrl_pts)
        for i in range(n if closed else n - 1):
            a, b = ctrl_pts[i], ctrl_pts[(i + 1) % n]
            q, t = intersect_point_line(p, a, b); t = max(0, min(1, t))
            best = min(best, (p - (a + (b - a) * t)).length)
        return best

    def walk(e, v0):
        loop = [v0]; v = e.other_vert(v0)
        for _ in range(400):
            loop.append(v)
            if v == loop[0]:
                return loop[:-1], True
            if len(v.link_edges) != 4:
                return loop, False
            fs = set(e.link_faces)
            nx = [x for x in v.link_edges if x != e and not (set(x.link_faces) & fs)]
            if len(nx) != 1:
                return loop, False
            e = nx[0]; v = e.other_vert(v)
        return loop, False
    best, found = None, {}
    for e in bm.edges:
        a, b = e.verts
        if pdist(a.co) > tol or pdist(b.co) > tol:
            continue
        L1, c1 = walk(e, a)
        if c1:
            full = L1
        else:
            L2, _ = walk(e, b)
            full = list(reversed(L2))[:-1] + L1
        if closed != c1:
            continue
        md = sum(pdist(v.co) for v in full) / len(full)
        if len(full) >= 10 and (best is None or md < best[0]):
            best = (md, [v.index for v in full])
        if every and len(full) >= 10:
            found.setdefault(frozenset(v.index for v in full), (md, [v.index for v in full]))
    if every:
        return [idx for _, idx in sorted(found.values(), key=lambda t: t[0])]
    return best[1] if best else []


def dijkstra(bm, sources, blocked=frozenset(), limit=1.0):
    dist = {i: 0.0 for i in sources}
    src = {i: i for i in sources}
    h = [(0.0, i) for i in sources]
    while h:
        d, i = heapq.heappop(h)
        if d > dist.get(i, 9e9) or d > limit:
            continue
        v = bm.verts[i]
        for e in v.link_edges:
            j = e.other_vert(v).index
            if j in blocked:
                continue
            nd = d + e.calc_length()
            if nd < dist.get(j, 9e9):
                dist[j] = nd; src[j] = src[i]
                heapq.heappush(h, (nd, j))
    return dist, src


def components(bm, cut):
    lab = {}
    sizes = []
    for v in bm.verts:
        if v.index in cut or v.index in lab:
            continue
        c = len(sizes); lab[v.index] = c; st = [v.index]; n = 1
        while st:
            x = st.pop()
            for e in bm.verts[x].link_edges:
                y = e.other_vert(bm.verts[x]).index
                if y not in cut and y not in lab:
                    lab[y] = c; st.append(y); n += 1
        sizes.append(n)
    return lab, sizes


class ChainSpec:
    """One chain. nodes: [(group name, rest position)], closed ring or open line.
    radii: per node (out_r0, out_r1, in_r0, in_r1) in metres. param: 'polar' (angle round
    `center` in the XZ plane, for eyes) or 'project' (closest point on the node polyline)."""
    def __init__(self, nodes, radii, closed, param='project', center=None):
        self.groups = [g for g, _ in nodes]
        self.pos = [p.copy() for _, p in nodes]
        self.radii = radii
        self.closed = closed
        self.param = param
        self.center = center
        if param == 'polar':
            self.ang = [self._angle(p) for p in self.pos]

    def _angle(self, co):
        return math.atan2(co.z - self.center.z, co.x - self.center.x)

    def s_of(self, co):
        if self.param == 'polar':
            a = self._angle(co); n = len(self.ang)
            for k in range(n):
                a0, a1 = self.ang[k], self.ang[(k + 1) % n]
                span = (a1 - a0) % (2 * math.pi) if self._dir > 0 else (a0 - a1) % (2 * math.pi)
                off = (a - a0) % (2 * math.pi) if self._dir > 0 else (a0 - a) % (2 * math.pi)
                if off <= span:
                    return k + off / span
            return 0.0
        return polyline_param(self.pos, co)

    def prepare(self):
        if self.param == 'polar':
            d = sum(math.sin(self.ang[(k + 1) % len(self.ang)] - self.ang[k]) for k in range(len(self.ang)))
            self._dir = 1 if d > 0 else -1

    def weights(self, s):
        n = len(self.groups)
        return basis(s, n, self.closed)

    def radius(self, s):
        b = basis(s, len(self.groups), self.closed)
        return [sum(w * self.radii[k][i] for k, w in b.items()) for i in range(4)]


class SegmentChainSpec(ChainSpec):
    """Chain of B-bone segments with neighbour handles (a smooth curve through the nodes): segment
    groups[k] spans nodes k..k+1, and a vertex belongs wholly to the segment it projects onto, since
    the curve itself is already smooth across the nodes. radii: per node, as in ChainSpec."""
    def __init__(self, groups, nodes, radii):
        super().__init__(list(zip(groups, nodes)), radii, closed=False)
        self.pos = [p.copy() for p in nodes]

    def weights(self, s):
        return {min(int(s), len(self.groups) - 1): 1.0}

    def radius(self, s):
        k = min(int(s), len(self.pos) - 2); t = s - k
        return [(1 - t) * self.radii[k][i] + t * self.radii[k + 1][i] for i in range(4)]


def loop_distance(co, pts, closed):
    """Straight-line distance from co to the polyline through pts."""
    n = len(pts)
    best = 9.0
    for k in range(n if closed else n - 1):
        a, b = pts[k], pts[(k + 1) % n]
        _, t = intersect_point_line(co, a, b)
        t = max(0.0, min(1.0, t))
        best = min(best, (a + (b - a) * t - co).length)
    return best


def respread(obj, groups, s_of, closed=True, degree=3, offset=0.5, width=lambda i: 1.0, limit=8, clean=0.002):
    """Smooth weights ALONG a loop: groups[k] (ordered along the loop, centred at s = k + offset) share each
    vertex's total of these groups by its loop position s_of(vertex index) with a B-spline of `degree` that is
    width(vertex index) group spacings wide (see basis), so the weights change smoothly round the loop instead
    of group by group. Only vertices with weight in `groups` change; their sum of `groups` and every other
    group stay exact. limit: most groups per vertex afterwards (the smallest loop shares are dropped first).
    Returns the vertices changed."""
    gi = {g.index: g.name for g in obj.vertex_groups}
    want = set(groups)
    vg = {g.name: g for g in obj.vertex_groups}
    for g in groups:
        if g not in vg:
            vg[g] = obj.vertex_groups.new(name=g)
    n = len(groups)
    done = []
    for v in obj.data.vertices:
        old = {gi[x.group]: x.weight for x in v.groups if x.weight > 0 and gi[x.group] in want}
        tot = sum(old.values())
        if tot <= 0:
            continue
        others = sum(1 for x in v.groups if x.weight > 0 and gi[x.group] not in want)
        new = {groups[k]: w for k, w in basis(s_of(v.index) - offset, n, closed, degree, width(v.index)).items()}
        new = dict(sorted(new.items(), key=lambda t: -t[1])[:max(1, limit - others)])
        top = max(new, key=new.get)
        new = {g: w for g, w in new.items() if w * tot >= clean or g == top}
        k = tot / sum(new.values())
        for g in old:
            vg[g].remove([v.index])
        for g, w in new.items():
            vg[g].add([v.index], w * k, 'REPLACE')
        done.append(v.index)
    return done


def rebuild(obj, margin_sets, specs_for, chain_groups, inner_side, free_groups, max_reach=0.04, limit=4, clean=0.01,
            damp_groups=frozenset(), straight=False):
    """margin_sets: {label: [vert idx]} loops whose union is the cut; specs_for(label) -> ChainSpec.
    inner_side(component sizes) -> component id of the inner side. free_groups: groups that may be
    rescaled (face bones, Head); any other group keeps its exact weight. damp_groups: skin owned by these
    (brows) gets less chain influence, by their share of the old base weight. straight: falloff by straight-line
    distance to the (closed, ordered) margin loop instead of the path along the edges, which zig-zags with
    the mesh and leaves ridges where the falloff is steep. Returns touched vertex indices."""
    me = obj.data
    bm = bmesh.new(); bm.from_mesh(me); bm.verts.ensure_lookup_table()
    gi = {g.index: g.name for g in obj.vertex_groups}
    gidx = {g.name: g.index for g in obj.vertex_groups}
    for g in chain_groups:
        if g not in gidx:
            gidx[g] = obj.vertex_groups.new(name=g).index; gi[gidx[g]] = g
    W = {v.index: {gi[g.group]: g.weight for g in v.groups if g.weight > 0} for v in me.vertices}
    cut = set().union(*margin_sets.values())
    lab, sizes = components(bm, cut)
    inner = inner_side(sizes)
    # nearest margin label + geodesic distance
    best = {}
    for label, verts in margin_sets.items():
        dist, _ = dijkstra(bm, verts, limit=max_reach)
        for i, d in dist.items():
            if i not in best or d < best[i][0]:
                best[i] = (d, label)
    for label, verts in margin_sets.items():
        for i in verts:
            best[i] = (0.0, label)
    if straight:
        loops = {label: [bm.verts[i].co.copy() for i in verts] for label, verts in margin_sets.items()}
        best = {i: (loop_distance(bm.verts[i].co, loops[label], True), label) for i, (d, label) in best.items()}
    touched = set(best) | {i for i, w in W.items() if any(g in chain_groups for g in w)}
    # base weights (non-chain), propagated into verts that have none, same label and side only
    base = {}
    keep = {i: {g: w for g, w in W[i].items() if g not in free_groups and g not in chain_groups} for i in touched}
    for i in touched:
        b = {g: w for g, w in W[i].items() if g not in chain_groups and g in free_groups}
        s = sum(b.values())
        if s > 0.05:
            base[i] = {g: w / s for g, w in b.items()}
    side = lambda i: (best.get(i, (0, None))[1], lab.get(i, -1) == inner)
    need = [i for i in touched if i not in base]
    if need:
        for i in need:
            cand = None
            # walk outward rings until a same-side vertex with base is found
            ring, seen = [i], {i}
            for _ in range(40):
                nxt = []
                for x in ring:
                    for e in bm.verts[x].link_edges:
                        y = e.other_vert(bm.verts[x]).index
                        if y in seen:
                            continue
                        seen.add(y); nxt.append(y)
                hits = [y for y in nxt if y in base and side(y)[1] == side(i)[1]]
                if hits:
                    cand = min(hits, key=lambda y: (bm.verts[y].co - bm.verts[i].co).length); break
                ring = nxt
            base[i] = dict(base[cand]) if cand is not None else {'Head': 1.0}
    new = {}
    for i in touched:
        d, label = best.get(i, (9.0, None))
        chain = {}
        if label is not None:
            co = bm.verts[i].co
            is_in = lab.get(i, -1) == inner
            sp = specs_for(label)
            s = sp.s_of(co)
            r0o, r1o, r0i, r1i = sp.radius(s)
            f = 1.0 - smoothstep(r0i, r1i, d) if is_in else 1.0 - smoothstep(r0o, r1o, d)
            if f > 0:
                for k, w in sp.weights(s).items():
                    chain[sp.groups[k]] = chain.get(sp.groups[k], 0) + w * f
        damp = sum(x for g, x in base[i].items() if g in damp_groups)
        chain = {g: x * (1 - damp) for g, x in chain.items()}
        room = max(0.0, 1.0 - sum(keep[i].values()))     # protected groups keep their exact weight
        chain = {g: x * room for g, x in chain.items()}
        tot = sum(chain.values())
        w = dict(chain)
        for g, bw in base[i].items():
            w[g] = w.get(g, 0) + bw * (room - tot)
        w = dict(sorted(w.items(), key=lambda t: -t[1])[:max(1, limit - len(keep[i]))])
        w = {g: x for g, x in w.items() if x >= clean}
        s = sum(w.values())
        w = {g: x * room / s for g, x in w.items()} if s > 0 else {}
        w.update(keep[i])
        new[i] = w
    bm.free()
    # write: clear chain groups + this vertex's old groups, then add
    for i, w in new.items():
        for g in set(W[i]) | set(chain_groups):
            if g in gidx:
                obj.vertex_groups[gidx[g]].remove([i])
        for g, x in w.items():
            if g not in gidx:
                gidx[g] = obj.vertex_groups.new(name=g).index
            obj.vertex_groups[gidx[g]].add([i], x, 'REPLACE')
    return set(new)


def zone(obj, margin_sets, reach):
    """Vertices within geodesic `reach` of the margin loops, labelled by the nearest loop."""
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.verts.ensure_lookup_table()
    best = {}
    for label, verts in margin_sets.items():
        dist, _ = dijkstra(bm, verts, limit=reach)
        for i, d in dist.items():
            if i not in best or d < best[i][0]:
                best[i] = (d, label)
    bm.free()
    return {i: l for i, (d, l) in best.items()}


def smooth(obj, labels, free_groups, iterations=4, factor=0.5, unblock=None, limit=4, clean=0.01, pinned=frozenset()):
    """Laplacian smoothing of the free groups on the labelled vertices. Edges between different
    labels are cut (upper/lower lip stay apart) unless unblock(i, j) says they may mix. Other
    groups keep their exact weight; the free part is renormalised to the room they leave.
    Pinned vertices keep their weights but still feed their neighbours."""
    me = obj.data
    gi = {g.index: g.name for g in obj.vertex_groups}
    W = {v.index: {gi[g.group]: g.weight for g in v.groups if g.weight > 0} for v in me.vertices}
    nb = defaultdict(list)
    for e in me.edges:
        a, b = e.vertices
        if a in labels or b in labels:
            if a in labels and b in labels and labels[a] != labels[b] and not (unblock and unblock(a, b)):
                continue
            nb[a].append(b); nb[b].append(a)
    free = {i: {g: w for g, w in W[i].items() if g in free_groups} for i in W}
    keep = {i: {g: w for g, w in W[i].items() if g not in free_groups} for i in labels}
    for _ in range(iterations):
        nxt = {}
        for i in labels:
            ns = nb[i]
            if not ns or i in pinned:
                continue
            avg = defaultdict(float)
            for j in ns:
                for g, w in free[j].items():
                    avg[g] += w / len(ns)
            gs = set(free[i]) | set(avg)
            nxt[i] = {g: (1 - factor) * free[i].get(g, 0) + factor * avg.get(g, 0) for g in gs}
        free.update(nxt)
    gidx = {g.name: g for g in obj.vertex_groups}
    for i in labels:
        room = max(0.0, 1 - sum(keep[i].values()))
        w = dict(sorted(free[i].items(), key=lambda t: -t[1])[:max(1, limit - len(keep[i]))])
        w = {g: x for g, x in w.items() if x >= clean}
        s = sum(w.values())
        w = {g: x * room / s for g, x in w.items()} if s > 0 else {}
        for g in W[i]:
            if g in free_groups:
                gidx[g].remove([i])
        for g, x in w.items():
            gidx[g].add([i], x, 'REPLACE')


def mirrors_groups(obj):
    """Whether a Mirror modifier on X copies this mesh's vertex groups to the other side."""
    return any(m.type == 'MIRROR' and m.use_axis[0] and m.use_mirror_vertex_groups for m in obj.modifiers)


def missing_mirror_groups(obj, only=None):
    """The Left/Right counterparts of the sided vertex groups (or only of those in `only`) the mesh lacks, sorted."""
    names = {g.name for g in obj.vertex_groups}
    return sorted({rn.flip(n) for n in names if only is None or n in only} - names)


def ensure_mirror_groups(obj, only=None):
    """Add the missing Left/Right counterpart of every sided vertex group (empty), or only of the groups
    named in `only`. A Mirror modifier only moves the copied half's weights to the other side's group
    when that group exists; without it the copy stays on the original side's bone. Returns the names added."""
    add = missing_mirror_groups(obj, only)
    for n in add:
        obj.vertex_groups.new(name=n)
    return add


def mirror_plane_x(obj):
    """Each vertex's X in the space the Mirror modifier mirrors in (its mirror object's, else the mesh's own)."""
    mirror = next(m for m in obj.modifiers if m.type == 'MIRROR' and m.use_axis[0] and m.use_mirror_vertex_groups)
    if not mirror.mirror_object:
        return [v.co.x for v in obj.data.vertices]
    to_mirror_space = mirror.mirror_object.matrix_world.inverted() @ obj.matrix_world
    return [(to_mirror_space @ v.co).x for v in obj.data.vertices]


def wrong_side_weights(obj, tol=1e-4):
    """{group name: vertex indices} of weight in the other side's Left/Right groups on the mesh's real half.
    A Mirror modifier that mirrors vertex groups fills the other side's groups for the copy, so the real half
    should only use its own side's groups. Mirror-plane vertices may use both and are never listed. The real
    side is the side whose groups hold most weight; {} when the mesh isn't mirrored that way, has verts on both
    halves, or it is unclear."""
    if not mirrors_groups(obj):
        return {}
    xs = mirror_plane_x(obj)
    plane_tol = tol * max(1.0, max((abs(x) for x in xs), default=0.0))
    off_plane = {i for i, x in enumerate(xs) if abs(x) > plane_tol}
    if not off_plane or len({xs[i] > 0 for i in off_plane}) > 1:
        return {}
    side_of_group = {g.index: rn.side_of(g.name) for g in obj.vertex_groups}
    weight_per_side = {'L': 0.0, 'R': 0.0}
    for i in off_plane:
        for g in obj.data.vertices[i].groups:
            if side_of_group[g.group] in weight_per_side:
                weight_per_side[side_of_group[g.group]] += g.weight
    if weight_per_side['L'] == weight_per_side['R']:
        return {}
    other_side = 'R' if weight_per_side['L'] > weight_per_side['R'] else 'L'
    wrong = {}
    for i in sorted(off_plane):
        for g in obj.data.vertices[i].groups:
            if side_of_group[g.group] == other_side and g.weight > tol:
                wrong.setdefault(obj.vertex_groups[g.group].name, []).append(i)
    return wrong


def clear_wrong_side_weights(obj, tol=1e-4):
    """Remove the weights `wrong_side_weights` lists. Returns how many (group, vertex) weights went."""
    wrong = wrong_side_weights(obj, tol)
    for name, vertex_indices in wrong.items():
        obj.vertex_groups[name].remove(vertex_indices)
    return sum(len(v) for v in wrong.values())


def symmetrize_center(obj, verts, tol=1e-4, limit=4, groups=None):
    """Vertices on the mirror plane: give each Left/Right group pair the same (average) weight,
    so the Mirror modifier's copy deforms like the original. Keeps the sum; trims to `limit`
    by dropping the smallest pairs/groups. `groups`: only these groups are touched (the others,
    e.g. groups no bone uses, stay exact and don't count towards the limit)."""
    me = obj.data
    gi = {g.index: g.name for g in obj.vertex_groups}
    gidx = {g.name: g for g in obj.vertex_groups}
    n = 0
    for i in verts:
        v = me.vertices[i]
        if abs(v.co.x) > tol:
            continue
        w = {gi[g.group]: g.weight for g in v.groups if g.weight > 0 and (groups is None or gi[g.group] in groups)}
        s0 = sum(w.values())
        sym = {}
        for g in w:
            m = rn.flip(g)
            sym[g] = sym[m] = (w.get(g, 0) + w.get(m, 0)) / 2 if m != g else w[g]
        items = sorted(sym.items(), key=lambda t: -t[1])
        while len(items) > limit:                     # drop the smallest group with its mirror
            g = items[-1][0]; m = rn.flip(g)
            items = [t for t in items if t[0] not in (g, m)]
        s = sum(x for _, x in items)
        new = {g: x * s0 / s for g, x in items}
        if new == w:
            continue
        for g in w:
            gidx[g].remove([i])
        for g, x in new.items():
            if g not in gidx:
                gidx[g] = obj.vertex_groups.new(name=g)
            gidx[g].add([i], x, 'REPLACE')
        n += 1
    return n


def _write_free(dst, i, acc, free_groups, limit, clean):
    """Set dst vertex i's free groups from `acc` (sum 1), keeping its other groups exact."""
    dgi = {g.index: g.name for g in dst.vertex_groups}
    gidx = {g.name: g for g in dst.vertex_groups}
    old = {dgi[g.group]: g.weight for g in dst.data.vertices[i].groups if g.weight > 0}
    keep = {g: w for g, w in old.items() if g not in free_groups}
    room = max(0.0, 1 - sum(keep.values()))
    w = dict(sorted(acc.items(), key=lambda t: -t[1])[:max(1, limit - len(keep))])
    w = {g: x for g, x in w.items() if x >= clean}
    s = sum(w.values())
    if s <= 0:
        return
    w = {g: x * room / s for g, x in w.items()}
    for g in old:
        gidx[g].remove([i])
    for g, x in {**w, **keep}.items():
        if g not in gidx:
            gidx[g] = dst.vertex_groups.new(name=g)
        gidx[g].add([i], x, 'REPLACE')


def _free_weights(obj, free_groups):
    gi = {g.index: g.name for g in obj.vertex_groups}
    return [{gi[g.group]: g.weight for g in v.groups if g.weight > 0 and gi[g.group] in free_groups}
            for v in obj.data.vertices]


def transfer_from_surface(src, dst, verts, free_groups, limit=4, clean=0.01):
    """Give dst's `verts` the src weights interpolated at the nearest point of src's surface (rest),
    for the free groups only; dst's other groups keep their exact weight."""
    from mathutils.bvhtree import BVHTree
    from mathutils.interpolate import poly_3d_calc
    sco = [src.matrix_world @ v.co for v in src.data.vertices]
    polys = [tuple(p.vertices) for p in src.data.polygons]
    bvh = BVHTree.FromPolygons(sco, polys)
    SW = _free_weights(src, free_groups)
    for i in verts:
        loc, _, pi, _ = bvh.find_nearest(dst.matrix_world @ dst.data.vertices[i].co)
        acc = defaultdict(float)
        for k, b in zip(polys[pi], poly_3d_calc([sco[k] for k in polys[pi]], loc)):
            for g, w in SW[k].items():
                acc[g] += w * b
        _write_free(dst, i, acc, free_groups, limit, clean)


def transfer_from_loop(src, loop, dst, verts, free_groups, closed=True, limit=4, clean=0.01, anchor=None):
    """Give dst's `verts` the src weights of the nearest point on an edge loop of src (rest),
    interpolated between its two loop vertices. Every cross-section of a tube that runs along the
    loop (a lid liner) gets one set of weights, so the tube keeps its shape. With `anchor` (a world
    point, e.g. a lash root) all `verts` take the weights at the loop point nearest to it: the part
    moves rigidly with that spot of the loop."""
    sco = [src.matrix_world @ src.data.vertices[k].co for k in loop]
    SW = _free_weights(src, free_groups)
    n = len(loop)
    for i in verts:
        p = anchor if anchor is not None else dst.matrix_world @ dst.data.vertices[i].co
        best = None
        for k in range(n if closed else n - 1):
            a, b = sco[k], sco[(k + 1) % n]
            _, t = intersect_point_line(p, a, b)
            t = max(0.0, min(1.0, t))
            d = (a + (b - a) * t - p).length
            if best is None or d < best[0]:
                best = (d, k, t)
        _, k, t = best
        acc = defaultdict(float)
        for idx, f in ((loop[k], 1 - t), (loop[(k + 1) % n], t)):
            for g, w in SW[idx].items():
                acc[g] += w * f
        _write_free(dst, i, acc, free_groups, limit, clean)
