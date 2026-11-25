# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/bbone_builder.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""B-Bone Chain Builder: you place points, give each a control level, then build a chain or a closed loop of B-bones
through them into a rig. B-bones point to point with Stretch To; the in-between points follow the points that are
more in charge. Curve From (`curve`, CURVES):
    'CONTROLS'    (default) each B-bone's handles are the controls at its two ends (TANGENT, part_chains.ring_handles
                  with nodes): the curve runs along a control's Y axis there, so turning a control steers the curve,
                  and scaling its Y makes the curve fuller there (handle ease). Each control points along the curve's
                  tangent at rest (previous point to next point; a chain end: towards its neighbour; a web point:
                  end a to end b). Web links too. Auto Turn (AUTO_TURN_KEY, 0..1, default 1, a slider on the chain's
                  first top-level control): each control keeps turning along the tangent as the points move, your own
                  turn on top (see Auto Turn below).
    'NEIGHBOURS'  each B-bone's handles are its neighbouring B-bones (ABSOLUTE), like Digit's eye lid ring
                  (lid_bbone_ring): one smooth curve, turning a control changes nothing about it. Web links: no handles.
Bone-only: constraints, no shape keys; one driver per handle (Auto Turn's influence).

    guide = new_guide(scene.collection, 'Tail', 'TAIL', location)      # the points: a small guide armature
    report = build(guide, rig, 'Tail', parent='Pelvis', loop=False, segments=8)
    weigh(rig, mesh, 'Tail')                                            # optional: a mesh on the chain's B-bones
    remove(rig, 'Tail')
    mirror_chain(guide, rig, 'Wing.L', parent='Chest')                  # Mirror to Other Side: 'Wing.R Points' + its build

The points: the guide armature "<Name> Points", one short bone per point (its head is the point). The bone parent chain
is the point order (Point -> next point), so Blender's dashed relationship lines show the order and deleting a point
in Edit Mode keeps it. Each point bone stores its level (LEVEL_KEY) and shows it by colour and length.

Control levels (follow_weights; a bigger number is more in charge):
    4  main (the top level, LEVEL_COUNT): moves only when you move it (under the parent bone)
    3, 2, 1  each follows the nearest point with a HIGHER level on each side along the chain (wrapping on a loop),
       blended by the distance along the chain; one side only (a chain end): that one fully. Your own move on top.
Guides saved with the old numbering (0 main, 1, 2) convert once (LEVELS_VERSION_KEY).
Built per point k (names: docs/BONE_NAMES.md):
    <Name>k                control (level 4 big purple sphere empty, 3 red diamond, 2 smaller yellow diamond, 1 tiny teal sphere empty), in the
                           collection <Name> (under Extras)
    MCH-<Name>Followk      a follower's parent: parentless, an Armature constraint on the driving controls (weights
                           1 - t / t), so their moves, turns and scale carry over (Mechanism)
    DEF-<Name>k            B-bone point k -> k + 1 (a loop closes back to 1), child of control k, Stretch To control
                           k + 1 (Deform)
Web points (add_web: pick 2 points, Add Web Between): one extra point joined to any two points (outline or web) by two
links. In the guide: a light blue point bone (WEB_KEY = its id, in the order added, so a web's ends always come
first) plus two thin light blue Wire "link" bones, each parented to its end point and drawn from it to the web point
(LINK_KEY = the web's id), not selectable. Links don't follow on their own while you move points in Edit Mode: every
card tool and Place Points put them back (sync_webs). Removing a point removes the webs on it. Built per web j:
    <Name>Webj             control (light blue wire cube, size by level), under MCH-<Name>WebFollowj: an Armature
                           constraint on its two end controls by distance share (web_weights), your own move on top
    DEF-<Name>Webja / jb   B-bone from each end's control to the web control (child of the end control, Stretch To)
Auto Turn (Curve From Controls only), per point or web point (node):
    MCH-<Name>Tangentk     head on the previous node's control, Damped Track to the next one's (a chain end: from itself
                           to its neighbour; a web: end a -> end b), under the parent bone: its Y is the curve's tangent
    MCH-<Name>Handlek      what the B-bones use (handles; DEF-<Name>k hangs under it), under the control's own parent:
                           Copy Rotation from the tangent (influence = Auto Turn), then the control's own move, turn and
                           scale on top (Copy Transforms, local, after), then the control's place (Copy Location). The
                           control draws at it (custom shape transform), so it shows the turn.
    The control itself never depends on a tangent, so tangents can track the controls without a dependency cycle.
    Webs: MCH-<Name>WebTangentj / MCH-<Name>WebHandlej.
Every built bone carries CHAIN_KEY = <Name>, so Rebuild and Remove find exactly them. The zero pose is the rest pose.
Rolls: each bone's local Z leans to the points' plane normal, worked out on the left side and mirrored for a .R chain
(side_up), so a .R chain's rolls mirror its .L chain's (X axis flipped, roll_R = -roll_L: Blender's left/right
convention). A .R chain whose built .L twin mirrors it (MIRROR_TOL) takes minus the twin's rolls exactly (.L leads, as
everywhere in the rig), so hand-fixed .L rolls carry over.
"""
import re
import bpy
from mathutils import Matrix, Vector

try:                                     # inside the add-on package
    from . import bone_collections as bc, chain_weights as cw, part_chains as pc, rig_names as rn, rig_weights as rw, \
        span_bones as sb
    from .face_rig_core import drive, follow, mk, shape, stretch, switch
except ImportError:                      # Scripts/batch_tools copy
    import bone_collections as bc
    import chain_weights as cw
    import part_chains as pc
    import rig_names as rn
    import rig_weights as rw
    import span_bones as sb
    from face_rig_core import drive, follow, mk, shape, stretch, switch

LEVEL_COUNT = 4                          # the top level; add a level: raise this and add one entry to each LEVEL_* / GUIDE_LENGTHS tuple
LEVELS = tuple(range(LEVEL_COUNT, 0, -1))   # left to right in the card: main first
LEVELS_VERSION = 2                       # 1 (or none): 0 main, 1, 2. 2: higher number = more in charge (adding levels keeps it)
LEVELS_VERSION_KEY = 'bbone_levels_version'   # on the guide armature data
LEVEL_KEY = 'bbone_level'                # on a guide point bone: its control level
CHAIN_KEY = 'bbone_chain'                # on every built bone: the chain's name
SIZE_KEY = 'bbone_point_size'            # on the guide armature data: the point bones' length (top level)
GUIDE_SUFFIX = ' Points'
LEVEL_COLORS = ((0.345, 0.769, 0.722), (0.941, 0.635, 0.227), (0.898, 0.325, 0.294),
               (0.690, 0.310, 0.870))   # levels 1 2 3 4: teal, orange, red, purple
LEVEL_SHAPES = ('WGT-SphereEmpty', 'WGT-Guide', 'WGT-Guide', 'WGT-SphereEmpty')  # levels 1 2 3 4: tiny sphere empty, small diamond, diamond, sphere empty
LEVEL_SIZES = (0.15, 0.21, 0.30, 0.38)         # control shape radius / the mean point spacing (level 2 = 70% of 3, level 1 = 40% of 4)
GUIDE_LENGTHS = (0.5, 0.75, 1.0, 1.25)         # point bone length / SIZE_KEY
CONTROL_LENGTH = 0.4                     # control bone length / the mean point spacing
SEGMENTS = 8
CURVES = ('CONTROLS', 'NEIGHBOURS')      # Curve From: the B-bones' handles are the controls (TANGENT) or the neighbours
MAPPING = 'CURVED'                       # vertices map onto the curved rest B-bone (as the lid ring)
POINT_SIZE = 0.04                        # default point bone length, metres
EXAMPLE_SIZE = 1.0                       # an example shape is this wide, metres
TWEAK_LEVELS = (1, 2)                    # controls (and web points) of these levels count as tweaks: the Show Bones Tweaks group shows them
MIRROR_TOL = 1e-4                        # metres (rig space): a .R bone this close to its .L twin's mirror counts as mirrored
WEB_KEY = 'bbone_web'                    # on a guide web point bone: its id (1, 2 ... in the order added)
LINK_KEY = 'bbone_link'                  # on a guide link bone: the id of the web point it joins (its parent = the end)
LINK_END_KEY = 'bbone_link_end'          # on a guide link bone: which end it is, 'a' or 'b'
LINK_ENDS = ('a', 'b')
WEB_COLOR = (0.420, 0.749, 1.0)          # light blue: web points, their links and their controls
WEB_SHAPE = 'WGT-Cube'
DIR_SHAPES = {'SelectionSphere': 'WGT-SphereDir', 'WGT-SphereEmpty': 'WGT-SphereEmptyDir', 'WGT-Guide': 'WGT-DiamondDir', 'WGT-Cube': 'WGT-CubeDir'}   # Curve From Controls: the shape plus a +Y pointer
WEB_SIZE = 0.6                           # web control cube half-size / the level's LEVEL_SIZES (a cube reaches further)
AUTO_TURN_KEY = 'auto_turn'              # the chain's Auto Turn slider (rig_parts SWITCHES: "Auto Turn")
TURN_WORDS = ('Tangent', 'Handle')     # Auto Turn's MCH bones per node: MCH-<Name>Tangentk, MCH-<Name>Handlek
AUTO_TURN = "Auto Turn"                  # the handle's Copy Rotation from its tangent (influence driven by the slider)
MIN_LINK = 1e-3                          # metres: a guide link bone is never shorter (Blender drops zero-length bones)
INSERT_RADIUS = 12                      # pixels: a click this close to the curve inserts a point there
PICK_RADIUS = 14                         # pixels: a click this close to a point picks it
# Start-from shapes (the mock-up's): (loop, default name, [(x, y, level, label)] in 0..1, y down, front view)
EXAMPLES = {
    'WING': (True, 'WingLoop', [(0.14, 0.20, 3, 'Root Top'), (0.30, 0.14, 1, ''), (0.47, 0.15, 2, 'Top Mid'),
                                (0.64, 0.24, 1, ''), (0.80, 0.42, 1, ''), (0.88, 0.66, 3, 'Tip'), (0.70, 0.66, 1, ''),
                                (0.52, 0.60, 2, 'Bottom Mid'), (0.33, 0.68, 1, ''), (0.15, 0.62, 3, 'Root Bottom')]),
    'TAIL': (False, 'TailChain', [(0.10, 0.50, 3, 'Base'), (0.22, 0.47, 1, ''), (0.34, 0.44, 2, ''),
                                  (0.46, 0.45, 1, ''), (0.58, 0.50, 3, 'Mid'), (0.70, 0.56, 1, ''),
                                  (0.80, 0.58, 2, ''), (0.90, 0.55, 3, 'Tip')]),
    'EMPTY': (False, 'Chain', []),
}


class Point:
    """One guide point: its bone name, place (world space) and control level."""

    def __init__(self, name, co, level):
        self.name, self.co, self.level = name, Vector(co), level


class Web(Point):
    """One web point: a Point plus the names of the two points it joins."""

    def __init__(self, name, co, level, ends):
        super().__init__(name, co, level)
        self.ends = tuple(ends)


# ---------------------------------------------------------------- follow maths (no bpy: the mock-up's posed())
def arc_lengths(cos, loop):
    """(distance along the chain from point 0 to each point, the whole length incl. a loop's closing edge)."""
    along = [0.0]
    for a, b in zip(cos, cos[1:]):
        along.append(along[-1] + (Vector(b) - Vector(a)).length)
    total = along[-1] + ((Vector(cos[0]) - Vector(cos[-1])).length if loop and len(cos) > 1 else 0.0)
    return along, total


def driver(levels, i, step, loop):
    """The nearest point before (step -1) or after (+1) point i, walking the chain (wrapping on a loop), whose level
    is above point i's, or -1."""
    count = len(levels)
    for k in range(1, count):
        j = i + step * k
        if not loop and not 0 <= j < count:
            return -1
        j %= count
        if j == i:
            return -1
        if levels[j] > levels[i]:
            return j
    return -1


def distance_along(along, total, start, end):
    """Distance walking forward along the chain from point `start` to point `end` (wrapping on a loop)."""
    d = along[end] - along[start]
    return d + total if d < 0 else d


def follow_weights(cos, levels, loop):
    """Per point {driving point index: weight}: empty for the top level (and for a point with nothing above it); two drivers
    blended by the distance along the chain (1 - t on the one before, t on the one after); one driver fully."""
    along, total = arc_lengths(cos, loop)
    out = []
    for i, level in enumerate(levels):
        before, after = (driver(levels, i, -1, loop), driver(levels, i, 1, loop)) if level < LEVEL_COUNT else (-1, -1)
        if before >= 0 and after >= 0 and before != after:
            d_before, d_after = distance_along(along, total, before, i), distance_along(along, total, i, after)
            t = d_before / (d_before + d_after) if d_before + d_after > 0 else 0.5
            out.append({before: 1.0 - t, after: t})
        elif before >= 0 or after >= 0:
            out.append({max(before, after): 1.0})
        else:
            out.append({})
    return out


def web_weights(co, end_a, end_b):
    """(weight on end a, weight on end b) of a web point at `co`: its distance share, the nearer end more."""
    d_a, d_b = (Vector(co) - Vector(end_a)).length, (Vector(co) - Vector(end_b)).length
    return (d_b / (d_a + d_b), d_a / (d_a + d_b)) if d_a + d_b > 0 else (0.5, 0.5)


def catmull_rom(points, loop, steps=12):
    """Samples of the smooth curve through 2D/3D points, one list per segment (as the B-bones run)."""
    count = len(points)
    def get(k):
        return points[k % count] if loop else points[max(0, min(count - 1, k))]
    out = []
    for i in range(count if loop else count - 1):
        p0, p1, p2, p3 = (Vector(get(k)) for k in (i - 1, i, i + 1, i + 2))
        seg = []
        for s in range(steps + 1):
            t = s / steps
            seg.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
        out.append(seg)
    return out


def nearest_point(screen, mouse, radius=PICK_RADIUS):
    """Index of the screen point nearest to `mouse` within `radius` pixels, or -1 (None entries are off screen)."""
    best, best_d = -1, radius
    for i, p in enumerate(screen):
        if p is not None and (Vector(p) - Vector(mouse)).length < best_d:
            best, best_d = i, (Vector(p) - Vector(mouse)).length
    return best


def insert_after(screen, mouse, loop, radius=INSERT_RADIUS):
    """The segment (index of the point it starts at) whose curve passes within `radius` pixels of `mouse`, or -1."""
    if len(screen) < 2 or any(p is None for p in screen):
        return -1
    best, best_d = -1, radius
    for i, seg in enumerate(catmull_rom(screen, loop)):
        for p in seg:
            d = (p - Vector(mouse)).length
            if d < best_d:
                best, best_d = i, d
    return best


# ---------------------------------------------------------------- the guide armature (the points)
def is_guide(ob):
    return ob is not None and ob.type == 'ARMATURE' and SIZE_KEY in ob.data


def convert_levels(guide, bones):
    """Once per guide: points saved with the old numbering (0 main, 1, 2) become 3, 2, 1. A guide without a version
    mark and without points is simply marked."""
    data = guide.data
    if data.get(LEVELS_VERSION_KEY, 1) >= LEVELS_VERSION:
        return
    for bone in bones:
        if LEVEL_KEY in bone:
            bone[LEVEL_KEY] = 3 - min(max(int(bone[LEVEL_KEY]), 0), 2)
    data[LEVELS_VERSION_KEY] = LEVELS_VERSION


def all_bones(guide):
    """Every guide bone: edit bones in Edit Mode, else bones."""
    return guide.data.edit_bones if guide.mode == 'EDIT' else guide.data.bones


def is_web(bone):
    return WEB_KEY in bone


def is_link(bone):
    return LINK_KEY in bone


def is_outline(bone):
    return not is_web(bone) and not is_link(bone)


def guide_bones(guide):
    """The (outline) point bones in chain order: edit bones in Edit Mode, else bones; no web points or links. Order =
    the parent chain (roots by name, a fork goes on with its first child by name, so nothing is ever lost)."""
    bones = [b for b in all_bones(guide) if is_outline(b)]
    convert_levels(guide, bones)
    children = {}
    for b in bones:
        children.setdefault(b.parent.name if b.parent and is_outline(b.parent) else None, []).append(b)
    order, todo = [], sorted(children.get(None, []), key=lambda b: b.name)[::-1]
    while todo:
        bone = todo.pop()
        order.append(bone)
        todo += sorted(children.get(bone.name, []), key=lambda b: b.name)[::-1]
    return order


def bone_head(bone):
    return bone.head if isinstance(bone, bpy.types.EditBone) else bone.head_local


def level_of(bone):
    return min(max(int(bone.get(LEVEL_KEY, 2)), 1), LEVEL_COUNT)


def guide_points(guide):
    """The points in chain order (world space)."""
    mw = guide.matrix_world
    return [Point(b.name, mw @ bone_head(b), level_of(b)) for b in guide_bones(guide)]


def paint(item, color):
    """A (pose) bone drawn in `color`: lighter when selected, white when active."""
    item.color.palette = 'CUSTOM'
    item.color.custom.normal = color
    item.color.custom.select = tuple(min(1.0, c * 0.5 + 0.5) for c in color)
    item.color.custom.active = (1.0, 1.0, 1.0)


def bone_direction(eb):
    return (eb.tail - eb.head).normalized() if eb.length > 1e-9 else Vector((0, 0, 1))


def style_point(guide, bone, level):
    """A point bone shows its level: length (level 4 longest) and colour (a web point: always light blue),
    direction kept."""
    bone[LEVEL_KEY] = level
    paint(bone, WEB_COLOR if is_web(bone) else LEVEL_COLORS[level - 1])
    if isinstance(bone, bpy.types.EditBone):
        bone.tail = bone.head + bone_direction(bone) * GUIDE_LENGTHS[level - 1] * guide.data[SIZE_KEY]


def add_point(guide, co, level, after=None, up=None):
    """Edit Mode: a new point at world `co` after the point bone named `after` (None: at the end of the chain), its
    bone pointing along world `up` (the view's up; default the guide's Z). Returns the new edit bone (selected and
    active, every other point deselected)."""
    E = guide.data.edit_bones
    order = guide_bones(guide)
    inv = guide.matrix_world.inverted()
    eb = E.new('Point')
    eb.head = inv @ Vector(co)
    direction = (inv.to_3x3() @ Vector(up)).normalized() if up is not None else Vector((0, 0, 1))
    eb.tail = eb.head + direction * guide.data[SIZE_KEY]
    previous = E[after] if after else (order[-1] if order else None)
    if previous is not None:
        for child in [b for b in E if b.parent == previous and b != eb and is_outline(b)]:
            child.parent = eb
        eb.parent = previous
    style_point(guide, eb, level)
    select_only(guide, eb)
    return eb


def select_only(guide, eb):
    for other in guide.data.edit_bones:
        other.select = other.select_head = other.select_tail = False
    eb.select = eb.select_head = eb.select_tail = True
    guide.data.edit_bones.active = eb


def selected_points(guide):
    """Edit Mode: the selected point bones (outline and web points; links can't be picked)."""
    return [b for b in guide.data.edit_bones if (b.select or b.select_head) and not is_link(b)]


def adjacent_pairs(guide, loop):
    """Edit Mode: the neighbouring selected point pairs as (chain index, next index); on a loop the last and first
    are neighbours too (only with 3+ points)."""
    order = guide_bones(guide)
    chosen = {b.name for b in selected_points(guide)}
    count = len(order)
    pairs = [(i, i + 1) for i in range(count - 1)]
    if loop and count > 2:
        pairs.append((count - 1, 0))
    return [(a, b) for a, b in pairs if order[a].name in chosen and order[b].name in chosen]


def subdivide(guide, loop, child):
    """Edit Mode: one new point in the middle of the smooth curve between each neighbouring selected pair, in chain
    order. Its level is the lower number of the pair (less in charge), 1 less (min 1) when `child`. The new points
    join the selection. Returns the new edit bones."""
    pairs = adjacent_pairs(guide, loop)
    order = guide_bones(guide)
    mw = guide.matrix_world
    curve = catmull_rom([mw @ bone_head(b) for b in order], loop)
    plan = []
    for a, b in pairs:
        level = max(min(level_of(order[a]), level_of(order[b])) - (1 if child else 0), 1)
        up = mw.to_3x3() @ (order[a].tail - order[a].head)
        plan.append((order[a].name, curve[a][len(curve[a]) // 2], level, up))
    keep = [b.name for b in selected_points(guide)]
    new = [add_point(guide, co, level, after, up) for after, co, level, up in plan]
    for eb in [guide.data.edit_bones[n] for n in keep] + new:
        eb.select = eb.select_head = eb.select_tail = True
    return new


def set_level(guide, bones, level):
    for bone in bones:
        style_point(guide, bone, level)


def remove_points(guide, bones):
    """Edit Mode: remove point bones; the chain closes over the gap (Blender gives the children the parent). A
    removed web point takes its links along, and so does every web point joined to a removed point."""
    E = guide.data.edit_bones
    doomed = {b.name for b in bones}
    while True:
        more = {web for web, ends in web_ends(guide).items()
                if web not in doomed and any(end.name in doomed for end in ends)}
        if not more:
            break
        doomed |= more
    by_id = web_ids(guide)
    for link in link_bones(guide):          # links first, so Blender never hands one to another point
        if by_id.get(int(link[LINK_KEY])) is None or by_id[int(link[LINK_KEY])].name in doomed:
            E.remove(link)
    for name in doomed:
        if name in E:
            E.remove(E[name])
    tidy_webs(guide)


# ---------------------------------------------------------------- web points (extra points joined to two points)
def web_bones(guide):
    """The web point bones, in the order they were added (their id)."""
    return sorted((b for b in all_bones(guide) if is_web(b)), key=lambda b: (int(b[WEB_KEY]), b.name))


def link_bones(guide):
    return [b for b in all_bones(guide) if is_link(b)]


def web_ids(guide):
    """{id: web point bone}; a duplicated id belongs to the first by name."""
    by_id = {}
    for web in web_bones(guide):
        by_id.setdefault(int(web[WEB_KEY]), web)
    return by_id


def web_ends(guide):
    """{web point name: (end a bone, end b bone)} for every web point whose two links have their end (parent)."""
    by_id = web_ids(guide)
    ends = {}
    for link in link_bones(guide):
        web = by_id.get(int(link[LINK_KEY]))
        if web is not None and link.parent is not None and link.parent != web:
            ends.setdefault(web.name, {})[link.get(LINK_END_KEY, 'a')] = link.parent
    return {web: (found['a'], found['b']) for web, found in ends.items() if set(found) == set(LINK_ENDS)}


def guide_webs(guide):
    """The complete web points in the order added (world space)."""
    mw = guide.matrix_world
    ends = web_ends(guide)
    return [Web(b.name, mw @ bone_head(b), level_of(b), [e.name for e in ends[b.name]])
            for b in web_bones(guide) if b.name in ends]


def add_web(guide, end_a, end_b, co=None, level=None, up=None):
    """Edit Mode: a web point joined to the point bones named `end_a` and `end_b` (outline or web points), at world
    `co` (default: midway between them), level `level` (default: one below the lower of the two, min 1), its bone
    along world `up` (default: end a's direction). Two link bones show the joins. Returns the new web point's edit
    bone (selected and active, every other point deselected)."""
    E = guide.data.edit_bones
    a, b = E[end_a], E[end_b]
    inv = guide.matrix_world.inverted()
    head = inv @ Vector(co) if co is not None else (a.head + b.head) / 2
    web_id = max(web_ids(guide), default=0) + 1
    web = E.new(f"Web{web_id}")
    web[WEB_KEY] = web_id
    web.head = head
    web.tail = head + ((inv.to_3x3() @ Vector(up)).normalized() if up is not None else bone_direction(a)) * guide.data[SIZE_KEY]
    for tag, end in zip(LINK_ENDS, (a, b)):
        link = E.new(f"{web.name} {tag}")
        link.head, link.tail = end.head, end.head + Vector((0, 0, MIN_LINK * 2))
        link.parent = end
        link[LINK_KEY], link[LINK_END_KEY] = web_id, tag
        link.hide_select = True
        link.display_type = 'WIRE'
        paint(link, WEB_COLOR)
    style_point(guide, web, level if level is not None else max(min(level_of(a), level_of(b)) - 1, 1))
    place_links(guide)
    select_only(guide, web)
    return web


def place_links(guide):
    """Edit Mode: each link bone runs from its end point to its web point. Returns whether one moved."""
    by_id = web_ids(guide)
    moved = False
    for link in link_bones(guide):
        web = by_id.get(int(link[LINK_KEY]))
        if web is None or link.parent is None:
            continue
        head, tail = link.parent.head.copy(), web.head.copy()
        if (tail - head).length < MIN_LINK:
            tail = head + Vector((0, 0, MIN_LINK))
        if (link.head - head).length > 1e-7 or (link.tail - tail).length > 1e-7:
            link.head, link.tail = head, tail
            moved = True
    return moved


def tidy_webs(guide):
    """Edit Mode: drop links that lost their web point or end, and web points that lost an end (then the webs joined
    to those, and so on). Returns how many bones went."""
    E = guide.data.edit_bones
    gone = 0
    while True:
        complete = web_ends(guide)
        doomed = [w for w in web_bones(guide) if w.name not in complete]
        names = {w.name for w in doomed}
        by_id = web_ids(guide)
        doomed += [link for link in link_bones(guide) if link.parent is None
                   or by_id.get(int(link[LINK_KEY])) is None or by_id[int(link[LINK_KEY])].name in names]
        if not doomed:
            return gone
        for bone in doomed:
            E.remove(bone)
        gone += len(doomed)


def sync_webs(guide):
    """Edit Mode: links back on their points after moves (they don't follow on their own), broken webs dropped.
    Returns whether anything changed."""
    return bool(tidy_webs(guide)) | place_links(guide)


def new_rig(collection, name):
    """A new empty armature object `name` (at the world origin, so rig space = world) in `collection`."""
    rig = bpy.data.objects.new(name, bc.new_armature(name))
    collection.objects.link(rig)
    return rig


def new_guide(collection, name, example='EMPTY', location=(0, 0, 0), size=POINT_SIZE):
    """A guide armature "<name> Points" at `location`, with the `example` shape's points (EXAMPLES, in the XZ plane
    as seen from the front, EXAMPLE_SIZE wide) or none. Shown in front, names and bone colours on."""
    arm = bpy.data.armatures.new(name + GUIDE_SUFFIX)
    arm[SIZE_KEY] = size
    arm[LEVELS_VERSION_KEY] = LEVELS_VERSION
    arm.display_type = 'OCTAHEDRAL'
    arm.show_names = True
    arm.show_bone_colors = True
    guide = bpy.data.objects.new(name + GUIDE_SUFFIX, arm)
    guide.location = location
    guide.show_in_front = True
    collection.objects.link(guide)
    _loop, _name, shape_points = EXAMPLES[example]
    if shape_points:
        with sb.Kept(guide) as kept:
            kept.edit()
            previous = None
            for x, y, level, label in shape_points:
                co = guide.matrix_world @ Vector(((x - 0.5) * EXAMPLE_SIZE, 0.0, (0.5 - y) * EXAMPLE_SIZE))
                eb = add_point(guide, co, level, previous, up=(0, 0, 1))
                if label:
                    eb.name = label
                previous = eb.name
            kept.done()
    return guide


# ---------------------------------------------------------------- hidden guides
USABLE = {}        # guide name -> {'saved': what to restore, 'depth': users of the make_usable() state, 'held': bool}


def layer_path(layer, collection, path=()):
    """The view-layer collections from `layer`'s child down to the one for `collection`, or None."""
    for child in layer.children:
        found = [*path, child] if child.collection == collection else layer_path(child, collection, [*path, child])
        if found:
            return found
    return None


def guides_collection(guide):
    """Where an orphaned guide goes: a collection that already holds guides in this scene, else "<rig name> Guides"
    (or "B-Bone Guides"), linked into the scene."""
    scene = bpy.context.scene
    for collection in scene.collection.children_recursive:
        if any(is_guide(ob) for ob in collection.objects):
            return collection
    target = guide.digit_bbone.target
    name = f"{target.name} Guides" if target else "B-Bone Guides"
    collection = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if collection not in scene.collection.children_recursive:
        scene.collection.children.link(collection)
    return collection


def object_hidden(ob):
    try:
        return ob.hide_get()
    except RuntimeError:             # not in the view layer
        return False


def make_usable(guide, hold=False):
    """Make the guide usable (Edit Mode, view-layer calls): an orphaned guide is linked to a guides collection and
    stays there; its collections are included and shown, the object unhidden. Remembers the user's states for
    restore_usable(). Calls nest. `hold`: kept until release_hold() (Edit Points)."""
    entry = USABLE.get(guide.name)
    if entry is None:
        if not guide.users_collection:
            guides_collection(guide).objects.link(guide)
        saved = []
        for collection in guide.users_collection:
            for layer in layer_path(bpy.context.view_layer.layer_collection, collection) or ():
                saved.append((layer, layer.exclude, layer.hide_viewport, layer.collection, layer.collection.hide_viewport))
        entry = USABLE[guide.name] = dict(saved=saved, depth=0, held=False, hidden=None)
    entry['depth'] += 1
    if hold and not entry['held']:
        entry['held'] = True
        entry['depth'] += 1
    for layer, *_ in entry['saved']:        # outermost first
        layer.exclude = layer.hide_viewport = layer.collection.hide_viewport = False
    bpy.context.view_layer.update()
    if entry['hidden'] is None:
        entry['hidden'] = object_hidden(guide)
    if object_hidden(guide):
        guide.hide_set(False)


def restore_usable(guide, hide=None):
    """One make_usable() less; the last one puts the user's exclude / hide states back (the object hidden when `hide`
    is True, else as it was)."""
    entry = USABLE.get(guide.name)
    if entry is None:
        return
    entry['depth'] -= 1
    if entry['depth'] > 0:
        return
    del USABLE[guide.name]
    if guide.name in bpy.context.view_layer.objects:
        want = entry['hidden'] if hide is None else hide
        if want != object_hidden(guide):
            guide.hide_set(want)
    for layer, exclude, hidden, collection, global_hidden in reversed(entry['saved']):
        collection.hide_viewport = global_hidden
        layer.hide_viewport = hidden
        layer.exclude = exclude


def drop_hold(guide):
    """End the hold of make_usable(hold=True) without restoring yet (its last restore_usable() does)."""
    entry = USABLE.get(guide.name)
    if entry and entry['held']:
        entry['held'] = False
        entry['depth'] -= 1


class usable:
    """with usable(guide): the guide works in the view layer and in Edit Mode; the user's exclude / hide states come
    back afterwards (an orphaned guide stays in its new collection). `hide`: end with the guide hidden."""
    def __init__(self, guide, hide=None):
        self.guide, self.hide = guide, hide

    def __enter__(self):
        make_usable(self.guide)
        return self.guide

    def __exit__(self, *exc):
        restore_usable(self.guide, self.hide)
        return False


# ---------------------------------------------------------------- build
def chain_names(name):
    """(part, side) of a chain name: 'Tail' -> ('Tail', ''), 'Wing.L' -> ('Wing', 'L')."""
    part, _dot, side = name.partition('.')
    return rn.pascal(part), side


def chain_bone(name, word, number, role=''):
    """A bone name of chain `name`: chain_bone('Wing.L', 'Follow', 2, 'MCH') -> 'MCH-WingFollow2.L'."""
    part, side = chain_names(name)
    return rn.build(part + word, side, number, role=role)


def control_name(name, k):
    return chain_bone(name, '', k + 1)


def follow_name(name, k):
    return chain_bone(name, 'Follow', k + 1, 'MCH')


def deform_name(name, k):
    return chain_bone(name, '', k + 1, 'DEF')


def web_control_name(name, j):
    return chain_bone(name, 'Web', j + 1)


def web_follow_name(name, j):
    return chain_bone(name, 'WebFollow', j + 1, 'MCH')


def web_deform_name(name, j, end):
    """The B-bone from web j's end `end` ('a' / 'b') to it: DEF-<Name>Web1a."""
    return chain_bone(name, 'Web', f"{j + 1}{end}", 'DEF')


def built_bones(arm, name):
    """The bones of chain `name` in `arm` (the ones a build tagged)."""
    return [b.name for b in arm.data.bones if b.get(CHAIN_KEY) == name]


def plane_up(cos):
    """The points' plane normal (Newell), or a side vector for points on a line."""
    normal = Vector()
    for a, b in zip(cos, cos[1:] + cos[:1]):
        normal += Vector(((a.y - b.y) * (a.z + b.z), (a.z - b.z) * (a.x + b.x), (a.x - b.x) * (a.y + b.y)))
    if normal.length > 1e-9:
        return normal.normalized()
    return pc.roll_reference(cos[-1] - cos[0] if len(cos) > 1 else Vector((0, 1, 0)))


def side_up(cos, side):
    """The roll reference of a chain on `side`: plane_up, worked out on the left side and mirrored back for 'R', so
    mirrored points give mirrored rolls (the plane normal itself flips sign under a mirror)."""
    if side != 'R':
        return plane_up(cos)
    return pc.mirror_x(plane_up([pc.mirror_x(c) for c in cos]))


class Layout:
    """Where one chain's bones go (armature space): the points, their levels, follow weights, tangents, sizes; the web
    points (Web with `ends` = node numbers: 0 .. count - 1 the points, count + j web j, always an earlier one)."""

    def __init__(self, cos, levels, loop, side='', webs=()):
        self.cos, self.levels, self.loop = [Vector(c) for c in cos], list(levels), loop
        self.webs = list(webs)
        count = len(self.cos)
        if count < 2 or (loop and count < 3):
            raise ValueError(f"a {'loop' if loop else 'chain'} needs at least {3 if loop else 2} points")
        for web in self.webs:
            if any((self.node_co(end) - web.co).length < MIN_LINK for end in web.ends):
                raise ValueError(f"web point {web.name} sits on a point it joins: move it off")
        self.weights = follow_weights(self.cos, self.levels, loop)
        self.up = side_up(self.cos, side)
        self.segments = count if loop else count - 1
        _along, total = arc_lengths(self.cos, loop)
        self.spacing = max(total / self.segments, 1e-4)

    def nodes(self):
        """Every node: the points 0 .. count - 1, then the web points."""
        return range(len(self.cos) + len(self.webs))

    def tangent_nodes(self, node):
        """(node before, node after) whose places give `node`'s tangent: a point's neighbours along the chain (a chain
        end: itself and its neighbour), a web point's two ends."""
        count = len(self.cos)
        if node >= count:
            return tuple(self.webs[node - count].ends)
        if self.loop:
            return (node - 1) % count, (node + 1) % count
        return max(node - 1, 0), min(node + 1, count - 1)

    def tangent(self, node):
        before, after = (self.node_co(n) for n in self.tangent_nodes(node))
        along = after - before
        if along.length < 1e-9 and node >= len(self.cos):     # a web whose ends meet: along the web to end b
            along = after - self.node_co(node)
        return along.normalized() if along.length > 1e-9 else Vector((0, 0, 1))

    def control_ends(self, node):
        """(head, tail) of a node's control: on the node, along its tangent."""
        head = self.node_co(node)
        return head, head + self.tangent(node) * CONTROL_LENGTH * self.spacing

    def tangent_bone(self, node):
        """(head, tail) of a node's tangent bone: on the node before, along the node's tangent (= its control's
        direction, so the rest pose is exact)."""
        head, tail = self.control_ends(node)
        start = self.node_co(self.tangent_nodes(node)[0])
        return start, start + (tail - head)

    def node_co(self, node):
        count = len(self.cos)
        return self.cos[node] if node < count else self.webs[node - count].co

    def node_bone(self, name, node, word='', role=''):
        """A bone name of a node: node_bone('Wing.L', 2, 'Tangent', 'MCH') -> 'MCH-WingTangent3.L'; a web node gets
        'Web' before the word: 'MCH-WingWebTangent1.L'."""
        count = len(self.cos)
        return chain_bone(name, word, node + 1, role) if node < count else chain_bone(name, 'Web' + word, node - count + 1, role)

    def has_follower(self, node):
        """Whether a node hangs under a follow parent (MCH-...Follow): every web, and every point that follows."""
        return node >= len(self.cos) or bool(self.weights[node])

    def web_weights(self, j):
        """{end node: weight} of web j (distance share)."""
        web = self.webs[j]
        return dict(zip(web.ends, web_weights(web.co, *(self.node_co(end) for end in web.ends))))


def check_names(arm, name, parent):
    """Raise when the chain's names would take bones that aren't its own, or the parent is one of its bones."""
    mine = set(built_bones(arm, name))
    if parent and parent in mine:
        raise ValueError(f"the parent {parent} is a bone of the chain itself")
    count = len(arm.data.bones)
    for k in range(count + 1):
        for bone in (control_name(name, k), follow_name(name, k), deform_name(name, k), web_control_name(name, k),
                     web_follow_name(name, k), *(web_deform_name(name, k, end) for end in LINK_ENDS),
                     *(chain_bone(name, web + word, k + 1, 'MCH') for web in ('', 'Web') for word in TURN_WORDS)):
            if bone in arm.data.bones and bone not in mine:
                raise ValueError(f"{arm.name} already has a bone {bone} that isn't from this chain: pick another name")


def leading_twin(arm, name):
    """The .L chain a .R chain `name` takes its rolls from, when it is built in `arm`, else ''."""
    other = rn.flip(name)
    return other if chain_names(name)[1] == 'R' and built_bones(arm, other) else ''


def copy_mirrored_rolls(E, bones, tol=MIRROR_TOL):
    """Edit Mode: each bone's roll = minus its other-side twin's (rn.flip), when every bone's head and tail mirror its
    twin's within `tol`; else nothing changes. Returns whether it did."""
    pairs = [(E[n], E.get(rn.flip(n))) for n in bones]
    if any(twin is None or (eb.head - pc.mirror_x(twin.head)).length > tol or (eb.tail - pc.mirror_x(twin.tail)).length > tol
           for eb, twin in pairs):
        return False
    for eb, twin in pairs:
        eb.roll = -twin.roll
    return True


def make_bones(arm, name, lay, parent, curve=CURVES[0]):
    """Edit Mode: per point a control (+ a follow parent for a follower), per segment a DEF B-bone; handles (`curve`,
    CURVES); per web point a control under its follow parent and a DEF B-bone from each end's control to it. Curve From
    Controls: per node also a tangent and a handle bone (Auto Turn); the DEF bones hang under the handles. A .R chain
    matching its built .L twin takes its rolls mirrored. Returns (deform bones, [(web deform bone, its web control)],
    the twin's name or '')."""
    count = len(lay.cos)
    turning = curve == 'CONTROLS'
    deform = [deform_name(name, k) for k in range(lay.segments)]
    # one run per web: first end -> web point -> second end, so the curve passes through the web point in line
    web_deform = [(web_deform_name(name, j, LINK_ENDS[0]), web_control_name(name, j)) if k == 0 else
                  (web_deform_name(name, j, LINK_ENDS[1]), lay.node_bone(name, web.ends[1]))
                  for j, web in enumerate(lay.webs) for k in range(2)]

    def anchor(node):                      # what a node's B-bones hang on and take as handle
        return lay.node_bone(name, node, 'Handle', 'MCH') if turning else lay.node_bone(name, node)

    twin = leading_twin(arm, name)
    with sb.Kept(arm) as kept:
        kept.edit()
        A = arm.data
        made = []
        for node in lay.nodes():
            head, tail = lay.control_ends(node)
            control, owner = lay.node_bone(name, node), parent
            if lay.has_follower(node):
                owner = lay.node_bone(name, node, 'Follow', 'MCH')
                mk(A, owner, head, tail).align_roll(lay.up)
                made.append(owner)
            mk(A, control, head, tail, owner).align_roll(lay.up)
            made.append(control)
            if turning:                    # the tangent's roll = the control's (same direction, same up): rest-exact
                tangent = lay.node_bone(name, node, 'Tangent', 'MCH')
                mk(A, tangent, *lay.tangent_bone(node), parent).align_roll(lay.up)
                mk(A, anchor(node), head, tail, owner).align_roll(lay.up)
                made += [tangent, anchor(node)]
        for k, bone in enumerate(deform):
            mk(A, bone, lay.cos[k], lay.cos[(k + 1) % count], anchor(k), deform=True).align_roll(lay.up)
        for j, web in enumerate(lay.webs):
            first, second = web.ends
            mk(A, web_deform_name(name, j, LINK_ENDS[0]), lay.node_co(first), web.co, anchor(first),
               deform=True).align_roll(lay.up)
            mk(A, web_deform_name(name, j, LINK_ENDS[1]), web.co, lay.node_co(second), anchor(count + j),
               deform=True).align_roll(lay.up)
        made += deform + [bone for bone, _web in web_deform]
        twin = twin if twin and copy_mirrored_rolls(A.edit_bones, made) else ''
        E = A.edit_bones
        if turning:
            pc.ring_handles(E, deform, [anchor(k) for k in range(count)], segments=SEGMENTS,
                            mapping=MAPPING, closed=lay.loop, ease=True)
            for j, web in enumerate(lay.webs):
                first, second = (E[anchor(node)] for node in web.ends)
                middle = E[anchor(count + j)]
                pc.bone_handles(E[web_deform_name(name, j, LINK_ENDS[0])], first, middle, ease=True)
                pc.bone_handles(E[web_deform_name(name, j, LINK_ENDS[1])], middle, second, ease=True)
        else:
            pc.ring_handles(E, deform, segments=SEGMENTS, mapping=MAPPING, closed=lay.loop)
        kept.done()
    return deform, web_deform, twin


def control_collection(arm, name):
    """The controls' collection: a standard one when the name is one (Tail, Wings...), else <Name> under Extras."""
    if name in bc.PARENT:
        return bc.ensure_home(arm, name)
    return arm.data.collections_all.get(name) or arm.data.collections.new(name, parent=bc.ensure_home(arm, part_home(name)))


def tweak_collection(arm, name):
    """Where the chain's tweak-level controls go: <Name> Tweak under the part's standard tweak collection (Wing.L Tweak
    under Wing Tweak), else under Extras Tweak. Shown by the Tweaks group (the sub-collection itself is left visible)."""
    tname = f"{name} Tweak"
    if tname in bc.PARENT:
        return bc.ensure_home(arm, tname)
    coll = arm.data.collections_all.get(tname)
    if coll is None:
        parent = bc.ensure_home(arm, bc.TWEAK_OF.get(part_home(name), "Extras Tweak"))
        coll = arm.data.collections.new(tname, parent=parent)
    return coll


def part_home(name):
    """The standard collection a chain's own collection goes under: Wing.L -> Wings, Tail.001 -> Tail; else Extras
    (so the Show Bones groups hide it with its part)."""
    base = re.split(r'[._ -]', rn.strip_side(name))[0]
    for home in (base, base + 's', base.rstrip('s')):
        if home in bc.PARENT and home not in ('Extras',):
            return home
    return 'Extras'




def bbone_collection_name(name):
    return f"{name} B-Bones"


def bbone_collection(arm, name):
    """The collection holding the chain's DEF bones: <Name> B-Bones, a child of the rig's Deform collection."""
    cname = bbone_collection_name(name)
    deform = bc.ensure_home(arm, 'Deform')
    coll = arm.data.collections_all.get(cname) or arm.data.collections.new(cname, parent=deform)
    if coll.parent != deform:
        coll.parent = deform
    return coll


def show_bbones(arm, name, deform_was_visible=None):
    """Make the chain's B-bones show: Deform and <Name> B-Bones visible. When Deform was hidden (`deform_was_visible`
    False; None: as it is now) and is turned on here, its other children are set hidden, so no other deform bones appear."""
    deform = bc.ensure_home(arm, 'Deform')
    shown = bbone_collection(arm, name)
    if deform_was_visible is None:
        deform_was_visible = deform.is_visible
    if not deform_was_visible:
        for child in deform.children:
            if child != shown:
                child.is_visible = False
        deform.is_visible = True
    shown.is_visible = True


def style_control(arm, home, bone, widget, size, color):
    """A control's look: custom shape `widget` of radius `size`, in collection `home` only, drawn in `color`."""
    pb, b = arm.pose.bones[bone], arm.data.bones[bone]
    pb.rotation_mode = 'XYZ'
    shape(pb, widget, size)
    for c in list(b.collections):
        c.unassign(b)
    home.assign(b)
    b.color.palette = 'DEFAULT'
    paint(pb, color)


def auto_turn(arm, name, lay, settings, value=1.0):
    """Curve From Controls: the tangent bones track their neighbour controls, each handle turns with its tangent by the
    Auto Turn slider on control `settings` (its value: `value`), the control's own move on top; the controls draw at
    their handles. Returns (tangents, handles)."""
    P = arm.pose.bones
    switch(P[settings], AUTO_TURN_KEY, 0.0, 1.0, "Each control turns by itself along the curve as the points move "
           "(0: only your own turns)", default=1.0, overshoot=1)
    P[settings][AUTO_TURN_KEY] = value
    tangents, handles = [], []
    for node in lay.nodes():
        control = lay.node_bone(name, node)
        tangent, handle = (lay.node_bone(name, node, word, 'MCH') for word in TURN_WORDS)
        before, after = (lay.node_bone(name, n) for n in lay.tangent_nodes(node))
        add_constraint(P[tangent], 'COPY_LOCATION', "On Previous", before)
        add_constraint(P[tangent], 'DAMPED_TRACK', "Aim Next", after)
        turn = add_constraint(P[handle], 'COPY_ROTATION', AUTO_TURN, tangent)
        drive(turn, 'influence', -1, 'turn', {'turn': (settings, AUTO_TURN_KEY)})
        own = add_constraint(P[handle], 'COPY_TRANSFORMS', "Own Move", control)
        own.mix_mode, own.owner_space, own.target_space = 'AFTER_FULL', 'LOCAL', 'LOCAL'
        add_constraint(P[handle], 'COPY_LOCATION', "On Control", control)   # its own move, not turned by the tangent
        P[control].custom_shape_transform = P[handle]
        tangents.append(tangent)
        handles.append(handle)
    return tangents, handles


def add_constraint(pb, kind, label, subtarget):
    """A `kind` constraint named `label` on pose bone `pb`, targeting bone `subtarget` of its own armature."""
    c = pb.constraints.new(kind)
    c.name, c.target, c.subtarget = label, pb.id_data, subtarget
    return c


def rig_bones(arm, name, lay, deform, web_deform, segments, curve=CURVES[0], turn=1.0):
    """Object Mode: tags, constraints, shapes, colours and collections; Curve From Controls: Auto Turn (`turn`: the
    slider's value). Returns (controls, followers, web controls, web followers, tangents, handles, every DEF bone)."""
    P, B = arm.pose.bones, arm.data.bones
    count = len(lay.cos)
    controls = [control_name(name, k) for k in range(count)]
    followers = [follow_name(name, k) for k in range(count) if lay.weights[k]]
    webs = [web_control_name(name, j) for j in range(len(lay.webs))]
    web_followers = [web_follow_name(name, j) for j in range(len(lay.webs))]
    stretched = [(bone, controls[(k + 1) % count]) for k, bone in enumerate(deform)] + list(web_deform)
    every_deform = [bone for bone, _target in stretched]
    tangents, handles = [], []
    if curve == 'CONTROLS':
        settings = controls[next(k for k in range(count) if not lay.weights[k])]   # a top-level point: there is always one
        tangents, handles = auto_turn(arm, name, lay, settings, turn)
    mechanism = followers + web_followers + tangents + handles
    for bone in controls + webs + mechanism + every_deform:
        B[bone][CHAIN_KEY] = name
    for bone, target in stretched:
        B[bone].bbone_segments = segments
        stretch(P[bone], target).rest_length = B[bone].length
        bc.place_bone(arm, bone, None, True)
    for bone in controls + webs + mechanism + every_deform:   # drawn thickness in B-Bone display (default 10% looks fat)
        bc.thin_bbone(B[bone], bone in every_deform)
    shown = bbone_collection(arm, name)
    for bone in every_deform:                       # drawn as bendy bones whatever the armature's display (STICK ...)
        shown.assign(B[bone])
    for k in range(count):
        if lay.weights[k]:
            follow(P[follow_name(name, k)], {controls[j]: w for j, w in lay.weights[k].items()})
    for j, bone in enumerate(web_followers):
        follow(P[bone], {lay.node_bone(name, node): w for node, w in lay.web_weights(j).items()})
    for bone in mechanism:
        bc.place_bone(arm, bone, 'Mechanism', False)
    home = control_collection(arm, name)
    tweaks = tweak_collection(arm, name)
    look = (lambda widget: DIR_SHAPES[widget]) if curve == 'CONTROLS' else (lambda widget: widget)   # Controls: show +Y
    for k, bone in enumerate(controls):
        level = lay.levels[k]
        style_control(arm, tweaks if level in TWEAK_LEVELS else home, bone, look(LEVEL_SHAPES[level - 1]), LEVEL_SIZES[level - 1] * lay.spacing,
                      LEVEL_COLORS[level - 1])
    for j, bone in enumerate(webs):
        style_control(arm, tweaks if lay.webs[j].level in TWEAK_LEVELS else home, bone, look(WEB_SHAPE), WEB_SIZE * LEVEL_SIZES[lay.webs[j].level - 1] * lay.spacing, WEB_COLOR)
    return controls, followers, webs, web_followers, tangents, handles, every_deform


def web_plans(guide, points, to_rig):
    """The guide's complete web points as Layout webs (rig space, ends as node numbers). A web joined to a point that
    isn't there is skipped (logged)."""
    nodes = {p.name: k for k, p in enumerate(points)}
    plans = []
    for web in guide_webs(guide):
        if not all(end in nodes for end in web.ends):
            print(f"B-Bone Chain Builder: web point {web.name} skipped: it joins {web.ends}, not all of them built")
            continue
        nodes[web.name] = len(points) + len(plans)
        plans.append(Web(web.name, to_rig @ web.co, web.level, [nodes[end] for end in web.ends]))
    return plans


def build(guide, arm, name, parent=None, loop=True, segments=SEGMENTS, curve=CURVES[0]):
    """Build (or rebuild: the old bones of `name` go first) the chain from the guide's points into `arm`. `parent`:
    the bone the top-level controls hang under (None: none). `curve`: Curve From (CURVES). The rig must be in the view layer. Returns {'controls',
    'followers', 'deform' (the chain's, then the webs'), 'webs', 'web_followers', 'bones', 'weights', 'web_weights',
    'rolls_from'} (weights = follow_weights, by point index; web_weights = {end node: weight} per web, nodes as in
    Layout; rolls_from = the .L chain whose rolls a .R build mirrored, or ''; Curve From Controls also 'tangents',
    'handles' (Auto Turn's MCH bones, per node; else empty) and 'settings' (the control with the Auto Turn slider, or
    ''). A rebuild keeps the slider's value."""
    points = guide_points(guide)          # in Edit Mode: the edit bones' current places
    parent = parent if parent and parent in arm.data.bones else None
    check_names(arm, name, parent)
    to_rig = arm.matrix_world.inverted()
    lay = Layout([to_rig @ p.co for p in points], [p.level for p in points], loop, chain_names(name)[1],
                 web_plans(guide, points, to_rig))
    before = arm.data.collections_all.get('Deform')
    deform_was_visible = before is not None and before.is_visible
    turn = auto_turn_value(arm, name)
    drop(arm, name)
    deform, web_deform, twin = make_bones(arm, name, lay, parent, curve)
    controls, followers, webs, web_followers, tangents, handles, deform = rig_bones(
        arm, name, lay, deform, web_deform, segments, curve, turn)
    mechanism = arm.data.collections_all.get('Mechanism')
    if mechanism is not None:
        mechanism.is_visible = False
    show_bbones(arm, name, deform_was_visible)
    settings = next((c for c in controls if AUTO_TURN_KEY in arm.pose.bones[c]), '')
    return dict(controls=controls, followers=followers, deform=deform, webs=webs, web_followers=web_followers,
                tangents=tangents, handles=handles, settings=settings,
                bones=controls + followers + webs + web_followers + tangents + handles + deform, weights=lay.weights,
                web_weights=[lay.web_weights(j) for j in range(len(lay.webs))], rolls_from=twin)


def auto_turn_value(arm, name, default=1.0):
    """The Auto Turn slider's value on chain `name`'s built controls, or `default`."""
    for bone in built_bones(arm, name):
        if AUTO_TURN_KEY in arm.pose.bones[bone]:
            return float(arm.pose.bones[bone][AUTO_TURN_KEY])
    return default


# ---------------------------------------------------------------- mirror to the other side
def sided(name):
    """Whether a chain name is on a side (ends in .L / .R): only those can be mirrored."""
    return chain_names(name)[1] in ('L', 'R')


class TwinError(ValueError):
    """The other side's rebuild failed; nothing of the previous twin (bones, guide) was changed."""


def mirror_guide(guide, name, arm=None, keep_old=False):
    """A guide for the other side of chain `name` ("<other name> Points"; an old one is replaced) next to `guide`:
    every point and web point mirrored across the rig's X = 0 (world X without a rig), same order, levels, point
    size, joins, and names (sided names flipped). Object Mode. `keep_old`: the old guide stays (the new one gets a
    numbered name; take_over() swaps them). Returns it."""
    other = rn.flip(name)
    space = arm.matrix_world if arm is not None else Matrix.Identity(4)
    flip_x = space @ Matrix.Scale(-1, 4, (1, 0, 0)) @ space.inverted()
    old = bpy.data.objects.get(other + GUIDE_SUFFIX)
    if is_guide(old) and old != guide and not keep_old:
        data = old.data
        bpy.data.objects.remove(old)
        if not data.users:
            bpy.data.armatures.remove(data)
    collection = guide.users_collection[0] if guide.users_collection else bpy.context.scene.collection
    mw = guide.matrix_world
    new = new_guide(collection, other, 'EMPTY', flip_x @ mw.translation, guide.data[SIZE_KEY])
    with sb.Kept(new) as kept:
        kept.edit()
        previous = None
        renamed = {}                        # this guide's point names -> the mirrored guide's
        for bone in guide_bones(guide):
            head, up = world_ends(guide, bone)
            eb = add_point(new, flip_x @ head, level_of(bone), previous, up=flip_x.to_3x3() @ up)
            eb.name = rn.flip(bone.name)
            previous = renamed[bone.name] = eb.name
        ends = web_ends(guide)
        for bone in web_bones(guide):
            if bone.name in ends and all(end.name in renamed for end in ends[bone.name]):
                head, up = world_ends(guide, bone)
                eb = add_web(new, *(renamed[end.name] for end in ends[bone.name]), flip_x @ head, level_of(bone),
                             flip_x.to_3x3() @ up)
                renamed[bone.name] = eb.name
        kept.done()
    return new


def discard_guide(ob):
    """Remove a guide object and its armature data."""
    data = ob.data
    bpy.data.objects.remove(ob)
    if not data.users:
        bpy.data.armatures.remove(data)


def take_over(new, old):
    """`new` (a mirror_guide(keep_old=True) guide) replaces the guide `old` and takes its name."""
    label = old.name
    discard_guide(old)
    new.name = new.data.name = label


def dry_build(guide, arm, name, parent, loop, segments, curve=CURVES[0]):
    """Build `name` into a throwaway copy of the rig: raises when the real build would. Leaves the rig as it is."""
    copy = arm.copy()
    copy.data = arm.data.copy()
    (arm.users_collection[0] if arm.users_collection else bpy.context.scene.collection).objects.link(copy)
    try:
        build(guide, copy, name, parent, loop, segments, curve)
    finally:
        data = copy.data
        bpy.data.objects.remove(copy)
        bpy.data.armatures.remove(data)


def world_ends(guide, bone):
    """(world head, world head-to-tail vector) of a guide bone."""
    mw = guide.matrix_world
    head = mw @ bone_head(bone)
    return head, mw @ (bone.tail if isinstance(bone, bpy.types.EditBone) else bone.tail_local) - head


def mirror_chain(guide, arm, name, parent=None, loop=True, segments=SEGMENTS, curve=CURVES[0]):
    """Mirror to Other Side: the other side's guide (mirror_guide) built into `arm`, under the other side's parent
    (the same one for a centre bone), rolls mirrored. Returns build()'s report plus 'guide', 'name' and 'parent'."""
    if not sided(name):
        raise ValueError(f"{name}: only a chain whose name ends in .L or .R can be mirrored")
    other = rn.flip(name)
    flipped = rn.flip(parent) if parent else None
    parent = flipped if flipped and flipped in arm.data.bones else parent
    old = bpy.data.objects.get(other + GUIDE_SUFFIX)
    old = old if is_guide(old) and old != guide else None
    new = mirror_guide(guide, name, arm, keep_old=True)
    try:
        if old is not None or built_bones(arm, other):      # replacing something: prove the build works first
            dry_build(new, arm, other, parent, loop, segments, curve)
    except Exception as exc:
        discard_guide(new)
        raise TwinError(f"{other} was not rebuilt, the previous one is kept: {type(exc).__name__}: {exc}") from exc
    if old is not None:
        take_over(new, old)
    report = build(new, arm, other, parent, loop, segments, curve)
    report.update(guide=new, name=other, parent=parent or '')
    return report


def twin_built(arm, name):
    """Whether chain `name` is on a side and its other-side twin is built in `arm`."""
    return sided(name) and bool(built_bones(arm, rn.flip(name)))


def rebuild_twin(guide, arm, name, parent=None, loop=True, segments=SEGMENTS, curve=CURVES[0]):
    """After (re)building chain `name`: when its twin is built in `arm`, rebuild the twin from the mirrored points
    (mirror_chain), so both sides match. Returns mirror_chain's report, or None without a twin."""
    if not twin_built(arm, name):
        return None
    return mirror_chain(guide, arm, name, parent, loop, segments, curve)


def drop(arm, name):
    """The chain's bones out of the rig (handles pointing at them cleared). Returns how many."""
    names = built_bones(arm, name)
    drop_drivers(arm, names)
    if names:
        with sb.Kept(arm) as kept:
            pc.drop_bones(kept.edit(), names)
            kept.done()
    return len(names)


def drop_drivers(arm, bones):
    """Remove the drivers on the pose bones `bones` (their constraints' too), so no driver is left pointing nowhere."""
    if arm.animation_data is None:
        return
    paths = tuple(f'pose.bones["{bone}"]' for bone in bones)
    for fc in [fc for fc in arm.animation_data.drivers if fc.data_path.startswith(paths)]:
        arm.animation_data.drivers.remove(fc)


def remove(arm, name):
    """Take chain `name` out: its bones, its B-bones' vertex groups on the meshes the rig deforms, and its control
    collection when that is left empty. Returns how many bones went."""
    deform = [n for n in built_bones(arm, name) if arm.data.bones[n].use_deform]
    count = drop(arm, name)
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and any(m.type == 'ARMATURE' and m.object == arm for m in ob.modifiers):
            for group in [ob.vertex_groups.get(n) for n in deform]:
                if group is not None:
                    ob.vertex_groups.remove(group)
    shown = arm.data.collections_all.get(bbone_collection_name(name))
    if shown is not None and not shown.bones and not shown.children:
        arm.data.collections.remove(shown)
    for cname in (f"{name} Tweak", name):
        coll = arm.data.collections_all.get(cname)
        if coll is not None and cname not in bc.PARENT and not coll.bones and not coll.children:
            arm.data.collections.remove(coll)
    return count


def reset_pose(arm, name):
    """The chain's controls back to rest (their own moves cleared)."""
    for bone in built_bones(arm, name):
        arm.pose.bones[bone].matrix_basis.identity()


def mirrored_by_modifier(ob, side):
    """Whether `ob` is a Mirror-modifier half mesh of the other side than `side`: its Mirror makes this side's half
    and copies the weights over (use_mirror_vertex_groups), so this side's chain writes no weights on it."""
    half = rw.is_half(ob)
    return side in ('L', 'R') and half is not None and half != side


def weigh(arm, mesh, name, smooth=False, reach=0.03, extra=()):
    """Weight the mesh to the chain's B-bones and give it an Armature modifier for the rig. Other bones' weights stay.
    Smooth: distance weights smoothed in space (rig_weights.smooth_bones; `extra` meshes are weighed together with it,
    `reach` = share of the chain's span). Otherwise each vertex on its nearest 2 bones. A Mirror-modifier half mesh
    (rig_weights.is_half) carries only its own side's weights; the other side's groups exist (empty) so the Mirror
    fills them, and the Armature modifier sits after the Mirror. Returns the vertices weighted."""
    deform = [n for n in built_bones(arm, name) if arm.data.bones[n].use_deform]
    if not deform:
        return 0
    side = chain_names(name)[1]
    meshes = [mesh] + [o for o in extra if o != mesh] if smooth else [mesh]
    own = [o for o in meshes if not mirrored_by_modifier(o, side)]
    done = 0
    if own and smooth:
        done = rw.smooth_bones(arm, own, deform, reach)
    elif own:
        done = rw.nearest_bones(arm, mesh, range(len(mesh.data.vertices)), deform, limit=2)
    for o in meshes:
        if cw.mirrors_groups(o) or rw.is_half(o):
            for group in deform:
                if o not in own and o.vertex_groups.get(group) is None:
                    o.vertex_groups.new(name=group)
            cw.ensure_mirror_groups(o, only=deform)
        rw.add_armature(o, arm)
    return done
