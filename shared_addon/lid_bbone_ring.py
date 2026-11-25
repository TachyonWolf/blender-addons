"""Lid B-bone ring: per eye a closed ring of B-bone segments through the lid pivots' tips (inner corner ->
upper 1..n -> outer corner -> lower n..1 -> inner), neighbour handles all the way round (by default with a real
corner at the inner / outer corner), so the lid edge is one smooth closed curve. The face rig's "Ring" lid
deformation: the pivots still drive the lids but stop deforming; the ring deforms the lid skin.

The ONE source (Addons/shared_addon, synced into Digit's Assorted Tools and Scripts/batch_tools); Digit's CLI is
Scripts/face_rig/digit_lid_ring.py. Called by face_rig_core (lid_mode 'RING') after the pivot lids are weighted:
  build(arm, cfg=eye config, reach=REACH_MM, sharp_corners=True, log=print) -> ring bone names
  weights_ring_head(arm, cfg, falloff_mm, log, reach_upper, reach_lower): the weights step (pivot weights -> ring
      near the lid edge, the bones already on the vertex further out: ring share 1 at the edge, 0.5 at the reach,
      0 from twice that; optional split reach: upper lid vs lower lid + corners, blended round the ring)
  remove(arm, cfg=None, log=print): back to pivot lids (ring bones + groups out, pivot weights rebuilt)
  smooth_ring_weights(arm, cfg, degree): existing ring weights smoothed along the ring in place (older files)
cfg defaults to the eye config the builder stored on the armature. The skin's new head weights go to the other
bodies 1:1 by position (surface transfer where the heads differ); liners take the ring weights per cross-section
(rigid), other skin parts the skin's; lashes untouched.
"""
import re, math
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
try:                                     # inside an add-on package (shared_addon)
    from . import face_rig_core as core, chain_weights as cw, part_chains as pc, rig_names as rn
except ImportError:                      # Scripts copy
    import face_rig_core as core, chain_weights as cw
    import part_chains as pc
    import rig_names as rn

SEGMENTS = 8
MAPPING = 'CURVED'            # vertices map onto the curved rest segment (a bit better than STRAIGHT)
SHARP_CORNERS = True          # no smooth handles across the eye corners (a smooth closed ring bulges there when shut)





def tip_names(cfg):
    """The lid pivots' tips (Left) of a rig with the lid ring: MCH-LidTip* (face_rig_core.LID_TIP_ROLE)."""
    return core.lid_names(cfg['pivots'], 'RING')


def ring_names(pivots):
    return [rn.left(f'LidRing{k + 1}', 'DEF') for k in range(len(pivots))]


def both_sides(names):
    return set(names) | {rn.with_side(n, 'R') for n in names}


def build_bones(arm, pivots, segs, sharp_corners=SHARP_CORNERS):
    """Segment k: head on pivot k's tip (child of it), Stretch To pivot k+1's tip; neighbour handles all the
    way round (sharp_corners: except across the inner / outer corner, where the lid line has a real corner)."""
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    A = arm.data; E = A.edit_bones
    n = len(pivots)
    for k, seg in enumerate(segs):
        a, b = pivots[k], pivots[(k + 1) % n]
        ra, rb = rn.with_side(a, 'R'), rn.with_side(b, 'R')
        l, r = core.both(A, seg, E[a].tail.copy(), E[b].tail.copy(), a,
                         right=(core.mirror(E[ra].tail), core.mirror(E[rb].tail)), deform=True)
        l.align_roll(core.FWD)
        r.roll = -l.roll
    for side in core.SIDES:                           # the canthi are corners: no handles across them
        pc.ring_handles(E, [rn.with_side(s, side) for s in segs], corners=(0, n // 2) if sharp_corners else (),
                        segments=SEGMENTS, mapping=MAPPING)
    bpy.ops.object.mode_set(mode='OBJECT')
    deform = core.bc.ensure_home(arm, 'Face Deform')   # a first build in Ring mode: not made yet
    for side in core.SIDES:
        for k, seg in enumerate(segs):
            nm = rn.with_side(seg, side)
            bone = A.bones[nm]
            for c in list(bone.collections):
                c.unassign(bone)
            deform.assign(bone)
            pb = arm.pose.bones[nm]
            for c in list(pb.constraints):
                pb.constraints.remove(c)
            c = core.stretch(pb, rn.with_side(pivots[(k + 1) % n], side))
            c.head_tail = 1.0
            c.rest_length = bone.length


def ring_spec(arm, src, pivots, segs, ring_idx):
    """Polar SegmentChainSpec over the closed ring: s_of(vertex) = position along the ring by its angle round the eye."""
    nodes = [arm.data.bones[p].tail_local.copy() for p in pivots]
    rad = [(0.0, 0.0, 0.0, 0.0)] * (len(pivots) + 1)          # (no falloff use: positions only)
    spec = cw.SegmentChainSpec(segs, nodes + nodes[:1], rad)
    spec.param = 'polar'
    spec.center = sum((src.data.vertices[i].co for i in ring_idx), Vector()) / len(ring_idx)
    spec.ang = [spec._angle(p) for p in nodes]
    spec.prepare()
    return spec


def lid_loop(arm, src, cfg, pivots):
    """Skin edge loop along the given pivots' tips (the lid edge)."""
    nodes = [arm.data.bones[p].tail_local.copy() for p in pivots]
    idx = core.find_loop(src, nodes, True, 0.006 * cfg['size'])
    assert idx, 'lid edge loop not found'
    return idx


def has_any(o, groups):
    gi = {g.index: g.name for g in o.vertex_groups}
    return [v.index for v in o.data.vertices if any(gi[x.group] in groups and x.weight > 0 for x in v.groups)]


def unmatched_near(src, dst, verts):
    """dst vertices whose nearest src vertex is one of `verts` but not at the same position."""
    kd = KDTree(len(src.data.vertices))
    for v in src.data.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    out = []
    for v in dst.data.vertices:
        _, i, d = kd.find(v.co)
        if i in verts and d > 1e-6:
            out.append(v.index)
    return out


def copy_heads(src, others, verts, FREE, log):
    """The skin's weights to the other bodies: 1:1 by position, surface transfer where the heads differ."""
    for dst in others:
        miss = core.copy_head(src, dst, verts)
        moved = unmatched_near(src, dst, set(verts))
        if moved:
            cw.transfer_from_surface(src, dst, moved, FREE)
        log(f'LR# head copied to {dst.name}: {len(verts)} verts, unmatched {miss} (surface transfer: {len(moved)})')


def weight_parts(src, skip, liners, ring_idx, lid_groups, FREE):
    """Liners: every vertex takes the ring weights at its angle round the eye (rigid cross-sections).
    Other skin parts on lid weights: the skin's weights at their nearest surface point."""
    report = {}
    ring = [src.matrix_world @ src.data.vertices[k].co for k in ring_idx]
    ctr = sum(ring, Vector()) / len(ring)
    pol = lambda p: math.atan2(p.z - ctr.z, p.x - ctr.x)
    for o in bpy.data.objects:
        if o.type != 'MESH' or o is src or o in skip:
            continue
        vs = has_any(o, lid_groups)
        if not vs:
            continue
        if o is liners:
            for i in vs:
                p = o.matrix_world @ o.data.vertices[i].co
                cw.transfer_from_loop(src, ring_idx, o, [i], FREE, anchor=core.ring_at_angle(ring, ctr, pol(p)))
        else:
            cw.transfer_from_surface(src, o, vs, FREE)
        report[o.name] = len(vs)
    return report


def eye_config(arm, cfg=None):
    """The eye config: given, else the one the face rig builder stored on the armature, else the defaults."""
    return cfg or core.stored(arm, 'eye') or core.config('eye')


def rig_meshes(cfg):
    """(skin, other bodies with the same head, liner/lash mesh or None) from the config's mesh names."""
    O = bpy.data.objects
    meshes = [O[n] for n in cfg['meshes'] if n in O]
    if not meshes:
        raise ValueError('no skin mesh: the eye config lists none that exist')
    return meshes[0], meshes[1:], O.get(cfg.get('lash_mesh') or '')


def set_pivots_deform(arm, pivots, on):
    """The lid tips deform (Face Deform only) or are mechanism of the ring (Mechanism)."""
    for p in pivots:
        arm.data.bones[p].use_deform = on
        core.bc.place_bone(arm, p, None if on else 'Mechanism', on)


def finish_weights(arm, cfg, src, others, liners, touched, ring_idx, lid, FREE, log):
    """The skin's new lid weights to the other bodies and the parts on the skin, mirror groups."""
    copy_heads(src, others, sorted(set(has_any(src, lid)) | touched), FREE, log)
    log('LR# parts', weight_parts(src, set(others), liners, ring_idx, lid, FREE))
    for o in bpy.data.objects:
        if o.type == 'MESH' and core.has_mirror(o) and lid & set(o.vertex_groups.keys()):
            cw.ensure_mirror_groups(o, only=lid)


def build(arm, cfg=None, reach=None, sharp_corners=SHARP_CORNERS, log=print, reach_upper=None, reach_lower=None):
    """Ring lids on a rig whose pivot lids are built and weighted: ring bones, then weights_ring_head
    (reach_upper / reach_lower: optional split reach, see weights_ring_head)."""
    cfg = eye_config(arm, cfg)
    if any(core.is_lid_ring(b.name) for b in arm.data.bones):
        remove(arm, cfg, log)                 # start from the pivot weights
    core.name_lid_tips(arm, 'RING')           # Pivots tips (DEF-) become the ring's mechanism (MCH-), weights too
    pivots = tip_names(cfg)
    segs = ring_names(pivots)
    core.reset_pose(arm)
    build_bones(arm, pivots, segs, sharp_corners)
    weights_ring_head(arm, cfg, REACH_MM if reach is None else reach, log, reach_upper, reach_lower)
    return sorted(both_sides(segs))


def remove(arm, cfg=None, log=print):
    """Back to pivot lids: ring weights merge into their segment's pivot, the pivots deform again and get their
    lid weights rebuilt (face_rig_core.weight_lids, as the face rig builds them); ring bones go."""
    segs_made = [b.name for b in arm.data.bones if core.is_lid_ring(b.name)]
    if not segs_made:
        return []
    cfg = dict(eye_config(arm, cfg), lid_mode='PIVOTS')
    core.name_lid_tips(arm, 'PIVOTS')         # the tips deform again: DEF-
    pivots = core.cfg_lid_names(cfg)
    segs = ring_names(pivots)
    piv_all = both_sides(pivots)
    heir = dict(zip(segs, pivots))
    for o in bpy.data.objects:
        if o.type == 'MESH' and any(g.name in heir or g.name in segs_made for g in o.vertex_groups):
            core.merge_groups(o, heir)
            for n in segs_made:
                if n in o.vertex_groups:
                    o.vertex_groups.remove(o.vertex_groups[n])
    set_pivots_deform(arm, piv_all, True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    E = arm.data.edit_bones
    for n in segs_made:
        E.remove(E[n])
    bpy.ops.object.mode_set(mode='OBJECT')
    try:
        src, others, liners = rig_meshes(cfg)
    except ValueError:
        return segs_made
    core.reset_pose(arm)
    ring_idx = lid_loop(arm, src, cfg, pivots)
    FREE = core.free_groups(src, arm, cfg['head']) | piv_all
    touched = core.weight_lids(src, arm, cfg, {'side': 'L', 'eye_ring': ring_idx}, FREE)
    cw.symmetrize_center(src, touched)
    finish_weights(arm, cfg, src, others, liners, touched, ring_idx, piv_all, FREE, log)
    log(f'LR# ring removed: {len(segs_made)} bones, pivot lid weights rebuilt')
    return segs_made


# ---------------------------------------------------------------- ring only: pivots stop deforming
REACH_MM = FALLOFF_MM = 30.0   # the ring takes half of a lid pivot's weight this far (mm) from the lid edge (tested 5-30: 30 best)


SMOOTH_DEGREE = 3   # ring weights along the ring: cubic B-spline (C2: no segment-to-segment steps)
EDGE_WIDTH = 0.5    # its width (segments) at the lid edge: the reach of the old linear blend (a vertex on the edge
                    # follows its own segment, the B-bone curve is already smooth there)
WIDEN_MM = 8.0      # ... widening by one segment per this many mm from the lid edge (x size): the dome further out
                    # blends more segments, so it closes as one smooth dome instead of showing each segment
                    # (Digit Ring 30 mm, shut: dome crease 43 -> 21 deg, streaks mostly gone; 4 mm: smoother look
                    # but liners cross 2.4 mm in x_squeeze; 30 mm: no visible change)
RING_LIMIT = 8      # most groups per ring-weighted vertex (4 cut the wide blend's tails off: steps)


def kernel_width(d, size=1.0):
    """Along-ring kernel width (segments) for a vertex d metres from the lid edge."""
    return EDGE_WIDTH + d / (WIDEN_MM * core.MM * size)


def segment_blend(s, n, width=EDGE_WIDTH, degree=SMOOTH_DEGREE):
    """Ring-segment weights for position s along a closed ring of n segments (segment k spans s = k..k+1):
    a B-spline over the segment centres (chain_weights.basis), `width` segments wide (kernel_width)."""
    return cw.basis(s - 0.5, n, True, degree, width)


def side_ring(arm, src, cfg, side):
    """(polar ring spec of `side`'s ring on the skin, the lid edge loop's points, its segment names)."""
    names = tip_names(cfg)
    pivots = [rn.with_side(p, side) for p in names]
    segs = [rn.with_side(x, side) for x in ring_names(names)]
    idx = lid_loop(arm, src, cfg, pivots)
    return ring_spec(arm, src, pivots, segs, idx), [src.data.vertices[i].co.copy() for i in idx], segs


def chains(segs):
    """[(start index, segments)]: the upper and the lower lid (inner -> outer, outer -> inner corner). Smoothing
    stays inside each, so a vertex keeps its upper / lower lid split (the canthi are corners, hand-pinned there)."""
    h = len(segs) // 2
    return [(0, segs[:h]), (h, segs[h:])]


def chain_pos(s, start, m, n):
    """Ring position s -> position along the chain of m segments that starts at segment `start` (beyond its ends:
    negative / > m, nearest end; open B-spline ends clamp there)."""
    u = (s - start) % n
    return u - n if u > m + (n - m) / 2 else u


def smooth_ring_weights(arm, cfg=None, degree=SMOOTH_DEGREE, log=print):
    """Smooth the ring weights ALONG the ring on every mesh that has them (skin, other bodies, liners, parts),
    in place: each vertex keeps its total ring weight (and every other group), shared over the segments by
    its position round the ring with a B-spline of `degree`, kernel_width wide (chain_weights.respread): as
    Build weights them now. Fixes the closed lid's segment-to-segment streaks on files built with the linear
    blend; keeps hand-painted totals (not their split between segments).
    Works on any file with ring bones (Ring or the older Hybrid mode). Returns {mesh: vertices changed}."""
    cfg = eye_config(arm, cfg)
    assert any(core.is_lid_ring(b.name) for b in arm.data.bones), 'no lid ring'
    src = rig_meshes(cfg)[0]
    core.reset_pose(arm)
    out = {}
    for side in core.SIDES:
        segs = [rn.with_side(x, side) for x in ring_names(tip_names(cfg))]
        meshes = [o for o in bpy.data.objects if o.type == 'MESH' and has_any(o, set(segs))]
        if not meshes:
            continue
        flip = side == 'R' and core.has_mirror(src)
        spec, edge, _ = side_ring(arm, src, cfg, 'L' if flip else side)    # mirrored skin: no right ring, mirror the left
        for o in meshes:
            M = src.matrix_world.inverted() @ o.matrix_world
            at = lambda i, o=o, M=M: core.mirror(M @ o.data.vertices[i].co) if flip else M @ o.data.vertices[i].co
            width = lambda i, at=at: kernel_width(cw.loop_distance(at(i), edge, True), cfg['size'])
            done = set()
            for start, chain in chains(segs):
                local = lambda i, at=at, start=start, m=len(chain): chain_pos(spec.s_of(at(i)), start, m, len(segs))
                done |= set(cw.respread(o, chain, local, len(chain) == len(segs), degree, 0.5, width, RING_LIMIT))
            out[o.name] = out.get(o.name, 0) + len(done)
    log(f'LR# ring weights smoothed along the ring (degree {degree}): {out}')
    return out


def ring_share(d, falloff, size):
    """Share of a pivot's weight the ring takes at distance d (m) from the lid edge: 1 at the edge,
    0.5 at `falloff` mm, 0 from twice that (smoothstep)."""
    return 1.0 - cw.smoothstep(0.0, 2 * falloff * core.MM * size, d)


CORNER = 1 / 6   # share of the upper lid next to each corner that still takes the lower reach (0..<0.5; tested 0, 1/6)


def upper_share(s, n, corner=None):
    """How much position s along a closed ring of n segments (0 = inner corner, n/2 = outer corner, upper lid in
    between) belongs to the upper lid: 1 mid upper lid, 0 on the lower lid and at both corners (and `corner` of
    the upper lid next to them), smooth between."""
    c = CORNER if corner is None else corner
    return cw.smoothstep(math.sin(math.pi * c), 1.0, math.sin(2 * math.pi * s / n))


def reach_at(s, n, reach):
    """Reach (mm) at ring position s; reach = (upper, lower): upper on the upper lid, lower on the lower lid and
    the corners, blended by upper_share (no seam)."""
    up, low = reach
    return low + (up - low) * upper_share(s, n)


def pivot_verts(src, pivots):
    gi = {g.index: g.name for g in src.vertex_groups}
    return {v.index for v in src.data.vertices if any(gi[x.group] in pivots and x.weight > 0 for x in v.groups)}


def reweight_side(arm, src, cfg, side, FREE, reach):
    """Pivot weights of one eye (side 'L' / 'R') -> its ring segments near the lid edge (by position
    along the ring) and the bones that already weight the vertex further out; reach = (upper, lower) mm, see
    reach_at. Returns the vertices changed."""
    pivots = [rn.with_side(p, side) for p in tip_names(cfg)]
    segs = [rn.with_side(s, side) for s in ring_names(tip_names(cfg))]
    n = len(segs)
    s = cfg['size']
    ring_idx = lid_loop(arm, src, cfg, pivots)
    ring_pts = [src.data.vertices[i].co.copy() for i in ring_idx]
    spec = ring_spec(arm, src, pivots, segs, ring_idx)
    allpiv = both_sides(tip_names(cfg))
    gi = {g.index: g.name for g in src.vertex_groups}
    W = {v.index: {gi[x.group]: x.weight for x in v.groups if x.weight > 0} for v in src.data.vertices}
    todo = [i for i, w in W.items() if any(g in pivots for g in w)]
    base = lambda w: {g: x for g, x in w.items() if g in FREE and g not in allpiv and not core.is_lid_ring(g)}
    kd = KDTree(len(W))
    donors = [i for i, w in W.items() if sum(base(w).values()) > 0.5 and not any(g in allpiv for g in w)]
    for i in donors:
        kd.insert(src.data.vertices[i].co, i)
    kd.balance()
    for i in todo:
        w, co = W[i], src.data.vertices[i].co
        piv = sum(x for g, x in w.items() if g in pivots)
        pos = spec.s_of(co)
        dist = cw.loop_distance(co, ring_pts, True)
        f = ring_share(dist, reach_at(pos, n, reach), s)
        acc = {g: x for g, x in w.items() if g in segs or g in base(w)}
        for k, b in segment_blend(pos, n, kernel_width(dist, s)).items():
            acc[segs[k]] = acc.get(segs[k], 0) + piv * f * b
        rest = base(w) if sum(base(w).values()) >= 0.05 else base(W[kd.find(co)[1]])   # else the nearest skin's
        tot = sum(rest.values())
        for g, x in rest.items():
            acc[g] = acc.get(g, 0) + piv * (1 - f) * x / tot
        W[i] = acc
    return todo, W


def apply_side(src, todo, W, FREE):
    """Write the new free weights of `todo` (sum normalised, at most 4 groups, other groups exact)."""
    for i in todo:
        t = sum(W[i].values())
        cw._write_free(src, i, {g: x / t for g, x in W[i].items()}, FREE, RING_LIMIT, 0.01)


def weights_ring_head(arm, cfg=None, falloff_mm=FALLOFF_MM, log=print, reach_upper=None, reach_lower=None):
    """Ring lids' weights on a rig that has the lid ring: the lid pivots stop deforming and their vertex weights go
    to the ring segments near the lid edge (nearest segments by position along the ring, blended between
    neighbours) and, further out, to the bones that already weight those vertices (head, eye socket, ...), with a
    smooth falloff: ring share 1 at the edge, 0.5 at the reach, 0 from twice that. The reach is `falloff_mm`, or
    split: `reach_upper` on the upper lid, `reach_lower` on the lower lid and corners (each defaults to
    `falloff_mm`), blended smoothly round the ring (reach_at). Normalised, at most 4 groups
    per vertex, other groups exact; then the other bodies, liners and skin parts (finish_weights); emptied pivot
    groups are deleted. Returns {'verts': n}."""
    cfg = eye_config(arm, cfg)
    assert any(core.is_lid_ring(b.name) for b in arm.data.bones), 'no lid ring: build its bones first'
    src, others, liners = rig_meshes(cfg)
    core.reset_pose(arm)
    core.check_space(arm, src)
    names = tip_names(cfg)
    piv_all, seg_all = both_sides(names), both_sides(ring_names(names))
    FREE = core.free_groups(src, arm, cfg['head']) | piv_all | seg_all
    ring_idx = lid_loop(arm, src, cfg, names)              # the liners take the ring here (finish_weights)
    reach = (falloff_mm if reach_upper is None else reach_upper, falloff_mm if reach_lower is None else reach_lower)
    todo = []
    for side in core.SIDES:                              # a mirrored skin only has its left half; the right = mirror groups
        if not pivot_verts(src, [rn.with_side(p, side) for p in names]):
            continue
        idx, W = reweight_side(arm, src, cfg, side, FREE, reach)
        apply_side(src, idx, W, FREE)
        todo += idx
    finish_weights(arm, cfg, src, others, liners, set(todo), ring_idx, piv_all | seg_all, FREE, log)
    for o in bpy.data.objects:
        if o.type != 'MESH':
            continue
        left = sorted(pivot_verts(o, piv_all))
        if left and o is not src:                        # verts the head copy missed: the skin's surface
            cw.transfer_from_surface(src, o, left, FREE)
            left = sorted(pivot_verts(o, piv_all))
        assert not left, f'{o.name}: {len(left)} verts still on lid pivots'
        for g in [g for g in o.vertex_groups if g.name in piv_all]:
            o.vertex_groups.remove(g)
    set_pivots_deform(arm, piv_all, False)
    core.reset_pose(arm)
    log(f'LR# ring lids: {len(todo)} skin verts re-weighted, reach {reach[0]}/{reach[1]} mm (upper/lower), pivots off')
    return {'verts': len(todo)}
