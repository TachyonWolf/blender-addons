"""Span bones: a deforming B-bone that spans from one bone to another (head on A, tail on B, parented to A,
Stretch To B), linked to neighbouring spans by its B-bone handles so a chain of spans bends as one smooth
curve. The ONE source: sync_shared.py copies it into Digit's Assorted Tools (which has the buttons).

    make_span(arm, a, b, ...)  -> span names made (plus the mirrored span)
    flip_span(arm, name, ...)  -> swap a span's direction (Span_<B>_<A>), weights follow the rename
    reset_spans(arm, ...)      -> realign every span to its bones, Stretch To reset, handles / ease / pose reset

Spans carry custom properties: span_bone (True), span_from, span_to, span_segments, span_handles.
"""
import bpy
from mathutils.geometry import intersect_point_line

try:                                     # inside the add-on package
    from . import bone_collections as bc, rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import bone_collections as bc
    import rig_names as rn

SPAN_PROP = 'span_bone'
HANDLE_MODES = [
    ('SMART', "Smart (recommended)", "Tangent to the neighbouring span where one meets this end, so a chain of spans is "
              "one smooth curve even when they aren't connected; Automatic where there is none"),
    ('AUTO', "Automatic", "Blender's automatic handle (ignores neighbours that aren't connected)"),
    ('ABSOLUTE', "Absolute", "The neighbouring span's position is the handle"),
    ('RELATIVE', "Relative", "The neighbouring span's offset from its rest position is the handle"),
    ('TANGENT', "Tangent", "The neighbouring span's direction is the handle"),
]
MAX_NAME = 63


def span_name(a, b, taken=()):
    """'Span_<A>_<B>', both names shortened evenly to fit Blender's 63 characters, unique among `taken`."""
    name = f'Span_{a}_{b}'
    if len(name) > MAX_NAME:
        room = (MAX_NAME - 6) // 2
        name = f'Span_{a[:room]}_{b[:MAX_NAME - 6 - min(len(a), room)]}'
    base, k = name, 1
    while name in taken:
        tail = f'.{k:03d}'
        name = base[:MAX_NAME - len(tail)] + tail
        k += 1
    return name


def is_span(bone):
    return bool(bone.get(SPAN_PROP))


def spans(bones):
    return [b for b in bones if is_span(b)]


def neighbours(bones, eb):
    """(previous, next) span of a span: the span ending where it starts, the span starting where it ends."""
    a, b = eb.get('span_from'), eb.get('span_to')
    prev = next((s for s in spans(bones) if s != eb and s.get('span_to') == a), None)
    nxt = next((s for s in spans(bones) if s != eb and s.get('span_from') == b), None)
    return prev, nxt


def set_handles(bones, eb):
    """This span's start / end handles from its neighbours, by its handle mode (span_handles)."""
    mode = eb.get('span_handles', 'SMART')
    prev, nxt = neighbours(bones, eb)
    for end, nb in (('start', prev), ('end', nxt)):
        kind = ('TANGENT' if nb else 'AUTO') if mode == 'SMART' else mode
        setattr(eb, f'bbone_handle_type_{end}', kind)
        setattr(eb, f'bbone_custom_handle_{end}', nb if kind != 'AUTO' else None)


def relink(bones, names):
    """Handles of the named spans, of every span next to them and of spans whose handles still point at them."""
    todo = set()
    named = {bones[n] for n in names if bones.get(n) is not None}
    for eb in named:
        todo.add(eb)
        todo.update(x for x in neighbours(bones, eb) if x)
    todo.update(s for s in spans(bones) if s.bbone_custom_handle_start in named or s.bbone_custom_handle_end in named)
    for eb in todo:
        set_handles(bones, eb)


def mirror_pair(arm, a, b):
    """Names of the mirrored bones of a and b, or None (no side, missing, or the span is its own mirror)."""
    ma, mb = rn.flip(a), rn.flip(b)
    if (ma, mb) == (a, b) or {ma, mb} == {a, b} or ma not in arm.data.bones or mb not in arm.data.bones:
        return None
    return ma, mb


class Kept:
    """Runs a span operation on the armature in Object Mode (X-Axis Mirror off, so nothing is mirrored behind our
    back) and gives back the mode, mirror setting and active object afterwards. edit() / done() enter and leave
    Edit Mode inside."""
    def __init__(self, arm):
        self.arm = arm

    def __enter__(self):
        view = bpy.context.view_layer
        self.active, self.mode = view.objects.active, self.arm.mode
        if self.active is not None and self.active.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.hidden = self.arm.hide_get()          # a hidden rig can't enter Edit Mode: show it while we work
        if self.hidden:
            self.arm.hide_set(False)
        view.objects.active = self.arm
        self.mirror, self.arm.data.use_mirror_x = self.arm.data.use_mirror_x, False
        return self

    def edit(self):
        bpy.ops.object.mode_set(mode='EDIT')
        return self.arm.data.edit_bones

    def done(self):
        bpy.ops.object.mode_set(mode='OBJECT')

    def __exit__(self, *exc):
        if self.arm.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        self.arm.data.use_mirror_x = self.mirror
        bpy.context.view_layer.update()
        if self.mode in ('POSE', 'EDIT'):
            bpy.ops.object.mode_set(mode=self.mode)
        bpy.context.view_layer.objects.active = self.active
        if self.hidden:
            self.arm.hide_set(True)
        return False


def place(eb, a, b, E, segments, handles):
    eb.head, eb.tail = E[a].head.copy(), E[b].head.copy()
    eb.roll = E[a].roll
    eb.parent = E[a]
    eb.use_connect = False
    eb.use_deform = True
    eb.bbone_segments = segments
    bc.thin_bbones([eb])
    eb.bbone_easein = eb.bbone_easeout = 1.0
    eb[SPAN_PROP] = True
    eb['span_from'], eb['span_to'] = a, b
    eb['span_segments'], eb['span_handles'] = segments, handles


def setup_pose(arm, name, target):
    """Stretch To the end bone (reset rest length, no volume change), pose and bendy values cleared."""
    pb = arm.pose.bones[name]
    for c in [c for c in pb.constraints if c.type == 'STRETCH_TO']:
        pb.constraints.remove(c)
    c = pb.constraints.new('STRETCH_TO')
    c.name = 'Span'
    c.target, c.subtarget = arm, target
    c.volume, c.bulge, c.keep_axis = 'NO_VOLUME', 1.0, 'SWING_Y'
    c.rest_length = rest_length(arm, pb.bone, c)
    clear_pose(pb)


def rest_length(arm, bone, c):
    """A Stretch To's rest length measured in the rest pose (the constraint's Reset button measures the current
    pose): owner head to the target point on the target bone. 0 (= measured on the next evaluation) for a
    target that isn't a bone of this armature."""
    t = arm.data.bones.get(c.subtarget) if c.target == arm else None
    if t is None:
        return 0.0
    point = t.head_local.lerp(t.tail_local, c.head_tail)
    return (point - bone.head_local).length


def reset_stretch(arm, names):
    """Stretch To constraints of the named bones: rest length from the rest pose, volume variation 1 (their
    volume mode, edit-mode bones and B-bone settings stay as they are)."""
    n = 0
    for name in names:
        pb = arm.pose.bones[name]
        for c in pb.constraints:
            if c.type == 'STRETCH_TO':
                c.rest_length = rest_length(arm, pb.bone, c)
                c.bulge = 1.0
                n += 1
    return n


def stretch_bones(arm):
    """Bones of the armature with a Stretch To constraint."""
    return [pb.name for pb in arm.pose.bones if any(c.type == 'STRETCH_TO' for c in pb.constraints)]


def clear_pose(pb):
    pb.location = (0, 0, 0)
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.rotation_axis_angle = (0, 0, 1, 0)
    pb.scale = (1, 1, 1)
    for attr in ('bbone_curveinx', 'bbone_curveinz', 'bbone_curveoutx', 'bbone_curveoutz', 'bbone_rollin',
                 'bbone_rollout', 'bbone_easein', 'bbone_easeout'):
        setattr(pb, attr, 0.0)
    pb.bbone_scalein = pb.bbone_scaleout = (1, 1, 1)


def deformed_meshes(arm):
    return [o for o in bpy.data.objects if o.type == 'MESH'
            and any(m.type == 'ARMATURE' and m.object == arm for m in o.modifiers)]


def transfer_weights(arm, bone_names, span_names):
    """Weights of the spanned bones go onto the spans: a vertex's weight of bone X goes to the span touching X
    whose segment it lies nearest to (the segment weighting of a chain, kept simple)."""
    B = arm.data.bones
    segs = {s: (B[s].head_local, B[s].tail_local) for s in span_names}
    touching = {x: [s for s in span_names if x in (B[s].get('span_from'), B[s].get('span_to'))] for x in bone_names}
    moved = 0
    for o in deformed_meshes(arm):
        M = arm.matrix_world.inverted() @ o.matrix_world
        for x in bone_names:
            vg = o.vertex_groups.get(x)
            if vg is None or not touching[x]:
                continue
            for v in o.data.vertices:
                w = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                if w <= 0:
                    continue
                p = M @ v.co

                def dist(s):
                    h, t = segs[s]
                    _, f = intersect_point_line(p, h, t)
                    f = max(0.0, min(1.0, f))
                    return (h.lerp(t, f) - p).length
                best = min(touching[x], key=dist)
                tg = o.vertex_groups.get(best) or o.vertex_groups.new(name=best)
                cur = next((g.weight for g in v.groups if g.group == tg.index), 0.0)
                tg.add([v.index], min(1.0, cur + w), 'REPLACE')
                vg.remove([v.index])
                moved += 1
    return moved


def make_span(arm, a, b, segments=6, mirror=True, handles='SMART', disable_deform=True, transfer=True):
    """Span bone(s) from bone a to bone b (and from a's mirror to b's mirror). Returns the new span names."""
    pairs = [(a, b)]
    if mirror and mirror_pair(arm, a, b):
        pairs.append(mirror_pair(arm, a, b))
    made = []
    with Kept(arm) as k:
        E = k.edit()
        for x, y in pairs:
            name = span_name(x, y, {e.name for e in E})
            eb = E.new(name)
            place(eb, x, y, E, segments, handles)
            made.append(eb.name)
        relink(E, made)
        k.done()
        for (x, y), name in zip(pairs, made):
            setup_pose(arm, name, y)
            bc.place_bone(arm, name, None, True)      # constraint-driven deform bone: Deform only
        spanned = sorted({n for p in pairs for n in p})
        if disable_deform:
            if transfer:
                transfer_weights(arm, spanned, made)
            for n in spanned:
                if not is_span(arm.data.bones[n]):
                    arm.data.bones[n].use_deform = False
    return made


def flip_span(arm, name, mirror=True):
    """Swap a span's direction (and its mirror's): head on the old end bone, Stretch To the old start bone,
    renamed Span_<B>_<A> with its vertex groups. Returns the new names."""
    B = arm.data.bones
    names = [name]
    if mirror:
        a, b = B[name].get('span_from'), B[name].get('span_to')
        pair = mirror_pair(arm, a, b)
        twin = next((s.name for s in spans(B) if pair and (s.get('span_from'), s.get('span_to')) == pair), None)
        if twin and twin != name:
            names.append(twin)
    renamed = {}
    with Kept(arm) as k:
        E = k.edit()
        for n in names:
            eb = E[n]
            a, b = eb['span_from'], eb['span_to']
            new = span_name(b, a, {e.name for e in E} - {n})
            place(eb, b, a, E, eb.get('span_segments', 6), eb.get('span_handles', 'SMART'))
            eb.name = new
            renamed[n] = eb.name
        relink(E, list(renamed.values()))
        k.done()
        for old, new in renamed.items():
            for o in deformed_meshes(arm):
                vg = o.vertex_groups.get(old)
                if vg and old != new:
                    vg.name = new
            setup_pose(arm, new, B[new]['span_to'])
    return list(renamed.values())


def reset_spans(arm, handles=None, segments=None):
    """Every span of the armature: head / tail back on its bones (rest), segments, handles (its own mode, or
    `handles` for all, stored), ease 1; Stretch To rest length and volume reset; pose and bendy values cleared.
    Every other bone with a Stretch To (lid rings, hand-made stretch bones): only the Stretch To reset.
    Returns {'spans': n, 'stretch': m}."""
    names = [b.name for b in spans(arm.data.bones)]
    others = [n for n in stretch_bones(arm) if n not in names]
    with Kept(arm) as k:
        reset_stretch(arm, others)
        if not names:
            return {'spans': 0, 'stretch': len(others)}
        E = k.edit()
        for n in names:
            eb = E[n]
            a, b = eb.get('span_from'), eb.get('span_to')
            if a not in E or b not in E:
                continue
            place(eb, a, b, E, segments or eb.get('span_segments', 6), handles or eb.get('span_handles', 'SMART'))
        relink(E, names)
        k.done()
        for n in names:
            setup_pose(arm, n, arm.data.bones[n]['span_to'])
    return {'spans': len(names), 'stretch': len(others)}
