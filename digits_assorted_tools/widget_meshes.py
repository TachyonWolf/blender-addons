# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/widget_meshes.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Control shape meshes made from data (face_rig_core.ensure_widget builds them): shapes drawn by hand that no formula
makes, plus the shapes made from a few numbers in their name (`parametric`, Bone Workshop). No bpy.

SelectionPaw: a plain flat paw print in the XY plane, toes
along +Y, about 1.17 wide: the IK hand and foot controls (body_rig SHAPES)."""

import math
import re

def _paw():
    """A plain paw print built from extruded discs: one pad and four toes."""
    verts, faces = [], []
    for cx, cy, rx, ry in ((0, 0, .3, .27), (-.42, .25, .14, .16), (-.16, .46, .14, .17),
                           (.16, .46, .14, .17), (.42, .25, .14, .16)):
        base, n = len(verts), 16
        for z in (-.01376, .01376):
            verts += [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n), z)
                      for i in range(n)]
        faces.append(tuple(base + n - 1 - i for i in range(n)))
        faces.append(tuple(base + n + i for i in range(n)))
        faces += [(base + i, base + (i + 1) % n, base + n + (i + 1) % n, base + n + i) for i in range(n)]
    return dict(verts=verts, faces=faces)


PAW = _paw()
MESHES = {'SelectionPaw': PAW}


# ---------------------------------------------------------------- shapes made from a few numbers (Bone Workshop)
# The name holds the setting, so one setting = one name = one mesh shared by every bone that uses it. Percent values
# are whole numbers. Flat shapes lie in the XZ plane (like WGT-Ring: square to the bone), the capsule in XY along it.
#   WGT-Ngon<sides>[Flat]                        regular polygon, radius 1, a corner at the top (Flat: a side)
#   WGT-Star<points>-<inner %>[Flat]             star, outer radius 1, inner radius inner %
#   WGT-Gear<teeth>-<depth %>-<width %>[Hole]    gear, outer radius 1, teeth depth % deep and width % of their step wide
#   WGT-Capsule<thickness %>                     capsule along the bone (+Y, 1 long), thickness % of its length wide
#   WGT-FourArrows                               a small ring with four arrows out of it (move in any direction)
NGON_SIDES = (3, 32)
GEAR_TEETH = (4, 48)
HOLE_RADIUS = 0.28
CIRCLE_SEGMENTS = 32
CAP_SEGMENTS = 8
PARAMETRIC = re.compile(r'^WGT-(?:(Ngon)(\d+)(Flat)?|(Star)(\d+)-(\d+)(Flat)?|(Gear)(\d+)-(\d+)-(\d+)(Hole)?|'
                        r'(Capsule)(\d+)|(FourArrows))$')


def percent(value):
    return int(round(min(max(value, 0.0), 1.0) * 100))


def ngon_name(sides, flat=False, star=False, inner=0.5):
    sides = int(min(max(sides, NGON_SIDES[0]), NGON_SIDES[1]))
    flat_tag = "Flat" if flat else ""
    return f"WGT-Star{sides}-{max(percent(inner), 5)}{flat_tag}" if star else f"WGT-Ngon{sides}{flat_tag}"


def gear_name(teeth, depth=0.25, width=0.5, hole=True):
    teeth = int(min(max(teeth, GEAR_TEETH[0]), GEAR_TEETH[1]))
    return f"WGT-Gear{teeth}-{max(percent(depth), 5)}-{max(percent(width), 5)}{'Hole' if hole else ''}"


def capsule_name(thickness=0.3):
    return f"WGT-Capsule{max(percent(thickness), 5)}"


FOUR_ARROWS = "WGT-FourArrows"


def is_parametric(name):
    return PARAMETRIC.match(name) is not None


def on_xz(radius, angle):
    """A point of the XZ plane; angle 0 = straight up (+Z), turning towards +X."""
    return (radius * math.sin(angle), 0.0, radius * math.cos(angle))


def loop(points):
    """(verts, edges) of a closed loop through `points`."""
    count = len(points)
    return list(points), [(k, (k + 1) % count) for k in range(count)]


def join(*parts):
    """One (verts, edges) of several, edge indices shifted."""
    verts, edges = [], []
    for part_verts, part_edges in parts:
        start = len(verts)
        verts += part_verts
        edges += [(a + start, b + start) for a, b in part_edges]
    return verts, edges


def circle(radius, segments=CIRCLE_SEGMENTS):
    return loop([on_xz(radius, 2 * math.pi * k / segments) for k in range(segments)])


def star_points(points, inner, flat):
    start = math.pi / points if flat else 0.0
    step = math.pi / points
    out = []
    for k in range(points):
        out.append(on_xz(1.0, start + 2 * k * step))
        if inner is not None:
            out.append(on_xz(inner, start + (2 * k + 1) * step))
    return loop(out)


def gear(teeth, depth, width, hole):
    seg = 2 * math.pi / teeth
    half = seg * width / 2
    inner = 1.0 - depth
    points = []
    for k in range(teeth):
        centre = k * seg
        points += [on_xz(inner, centre - half * 1.15), on_xz(1.0, centre - half * 0.8),
                   on_xz(1.0, centre + half * 0.8), on_xz(inner, centre + half * 1.15)]
    return join(loop(points), circle(HOLE_RADIUS, 16)) if hole else loop(points)


def capsule(thickness):
    radius = min(thickness / 2, 0.5)
    points = []
    for k in range(CAP_SEGMENTS + 1):                       # bottom cap, round the far side of the head
        a = math.pi + math.pi * k / CAP_SEGMENTS
        points.append((radius * math.cos(a), radius + radius * math.sin(a), 0.0))
    for k in range(CAP_SEGMENTS + 1):                       # top cap
        a = math.pi * k / CAP_SEGMENTS
        points.append((radius * math.cos(a), 1 - radius + radius * math.sin(a), 0.0))
    return loop(points)


def four_arrows():
    parts = [circle(0.5, 24)]
    for k in range(4):
        a = k * math.pi / 2
        tip, base = on_xz(1.25, a), on_xz(0.5, a)
        side = (math.cos(a) * 0.18, 0.0, -math.sin(a) * 0.18)
        back = on_xz(1.03, a)
        wings = [(back[0] + side[0], 0.0, back[2] + side[2]), (back[0] - side[0], 0.0, back[2] - side[2])]
        parts.append(([base, tip, *wings], [(0, 1), (1, 2), (1, 3)]))
    return join(*parts)


def parametric(name):
    """(verts, edges) of a shape made from the numbers in its name (see above), or None for any other name."""
    m = PARAMETRIC.match(name)
    if m is None:
        return None
    g = m.groups()
    if g[0]:
        return star_points(int(g[1]), None, bool(g[2]))
    if g[3]:
        return star_points(int(g[4]), int(g[5]) / 100, bool(g[6]))
    if g[7]:
        return gear(int(g[8]), int(g[9]) / 100, int(g[10]) / 100, bool(g[11]))
    if g[12]:
        return capsule(int(g[13]) / 100)
    return four_arrows()
