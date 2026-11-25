# SPDX-License-Identifier: GPL-3.0-or-later
"""Control shape meshes made from data (face_rig_core.ensure_widget builds them): shapes drawn by hand that no formula
makes, plus the shapes made from a few numbers in their name (`parametric`, Bone Workshop). No bpy.

SelectionPaw: the user's paw pad , a plain flat paw print in the XY plane, toes
along +Y, about 1.17 wide: the IK hand and foot controls (body_rig SHAPES)."""

import math
import re

PAW = dict(
    verts=[
    (0.21088, 0.21088, -0.01376), (0.33944, 0.41017, -0.01376), (0.01798, 0.40282, -0.01376), (0.31863, 0.55691,
    -0.01376), (0.28771, 0, -0.01376), (0, 0.28771, -0.01376), (0.26745, 0.3054, -0.01376), (0.32341, 0.42987,
    -0.01376), (0, 0, -0.01376), (0.42524, 0.26467, -0.01376), (0.16831, 0.47986, -0.01376), (0.21088, -0.21088,
    -0.01376), (0.27973, 0.17887, -0.01376), (0.51103, 0.11916, -0.01376), (0.57074, 0.35047, -0.01376), (0.24535,
    0.32954, -0.01376), (0.09126, 0.63019, -0.01376), (0, -0.28771, -0.01376), (0.3845, 0.10688, -0.01376),
    (0.58302, 0.22394, -0.01376), (0.46597, 0.42246, -0.01376), (0.0132, 0.52986, -0.01376), (0.11831, 0.32476,
    -0.01376), (0.2183, 0.63497, -0.01376), (0.21088, -0.21088, 0.01376), (0.21088, 0.21088, 0.01376), (0.27973,
    0.17887, 0.01376), (0.51103, 0.11916, 0.01376), (0.33944, 0.41017, 0.01376), (0.57074, 0.35047, 0.01376),
    (0.01798, 0.40282, 0.01376), (0.24535, 0.32954, 0.01376), (0.09126, 0.63019, 0.01376), (0.31863, 0.55691,
    0.01376), (0, -0.28771, 0.01376), (0.28771, 0, 0.01376), (0, 0.28771, 0.01376), (0.26745, 0.3054, 0.01376),
    (0.3845, 0.10688, 0.01376), (0.58302, 0.22394, 0.01376), (0.46597, 0.42246, 0.01376), (0.0132, 0.52986,
    0.01376), (0.11831, 0.32476, 0.01376), (0.32341, 0.42987, 0.01376), (0.2183, 0.63497, 0.01376), (0, 0, 0.01376),
    (0.42524, 0.26467, 0.01376), (0.16831, 0.47986, 0.01376), (-0.21088, 0.21088, -0.01376), (-0.33944, 0.41017,
    -0.01376), (-0.01798, 0.40282, -0.01376), (-0.31863, 0.55691, -0.01376), (-0.28771, 0, -0.01376), (-0.26745,
    0.3054, -0.01376), (-0.32341, 0.42987, -0.01376), (-0.42524, 0.26467, -0.01376), (-0.16831, 0.47986, -0.01376),
    (-0.21088, -0.21088, -0.01376), (-0.27973, 0.17887, -0.01376), (-0.51103, 0.11916, -0.01376), (-0.57074,
    0.35047, -0.01376), (-0.24535, 0.32954, -0.01376), (-0.09126, 0.63019, -0.01376), (-0.3845, 0.10688, -0.01376),
    (-0.58302, 0.22394, -0.01376), (-0.46597, 0.42246, -0.01376), (-0.0132, 0.52986, -0.01376), (-0.11831, 0.32476,
    -0.01376), (-0.2183, 0.63497, -0.01376), (-0.21088, -0.21088, 0.01376), (-0.21088, 0.21088, 0.01376), (-0.27973,
    0.17887, 0.01376), (-0.51103, 0.11916, 0.01376), (-0.33944, 0.41017, 0.01376), (-0.57074, 0.35047, 0.01376),
    (-0.01798, 0.40282, 0.01376), (-0.24535, 0.32954, 0.01376), (-0.09126, 0.63019, 0.01376), (-0.31863, 0.55691,
    0.01376), (-0.28771, 0, 0.01376), (-0.26745, 0.3054, 0.01376), (-0.3845, 0.10688, 0.01376), (-0.58302, 0.22394,
    0.01376), (-0.46597, 0.42246, 0.01376), (-0.0132, 0.52986, 0.01376), (-0.11831, 0.32476, 0.01376), (-0.32341,
    0.42987, 0.01376), (-0.2183, 0.63497, 0.01376), (-0.42524, 0.26467, 0.01376), (-0.16831, 0.47986, 0.01376)
    ],
    faces=[
    (17, 8, 4, 11), (8, 5, 0, 4), (12, 6, 9, 18), (18, 9, 19, 13), (9, 20, 14, 19), (6, 1, 20, 9), (2, 21, 10, 22),
    (22, 10, 7, 15), (10, 23, 3, 7), (21, 16, 23, 10), (12, 18, 38, 26), (22, 15, 31, 42), (18, 13, 27, 38), (16,
    21, 41, 32), (1, 6, 37, 28), (21, 2, 30, 41), (3, 23, 44, 33), (6, 12, 26, 37), (34, 24, 35, 45), (45, 35, 25,
    36), (26, 38, 46, 37), (38, 27, 39, 46), (46, 39, 29, 40), (37, 46, 40, 28), (30, 42, 47, 41), (42, 31, 43, 47),
    (47, 43, 33, 44), (41, 47, 44, 32), (17, 11, 24, 34), (2, 22, 42, 30), (19, 14, 29, 39), (11, 4, 35, 24), (7, 3,
    33, 43), (13, 19, 39, 27), (4, 0, 25, 35), (15, 7, 43, 31), (20, 1, 28, 40), (0, 5, 36, 25), (23, 16, 32, 44),
    (14, 20, 40, 29), (17, 57, 52, 8), (8, 52, 48, 5), (58, 63, 55, 53), (63, 59, 64, 55), (55, 64, 60, 65), (53,
    55, 65, 49), (50, 67, 56, 66), (67, 61, 54, 56), (56, 54, 51, 68), (66, 56, 68, 62), (58, 71, 81, 63), (67, 85,
    76, 61), (63, 81, 72, 59), (62, 77, 84, 66), (49, 73, 80, 53), (66, 84, 75, 50), (51, 78, 87, 68), (53, 80, 71,
    58), (34, 45, 79, 69), (45, 36, 70, 79), (71, 80, 88, 81), (81, 88, 82, 72), (88, 83, 74, 82), (80, 73, 83, 88),
    (75, 84, 89, 85), (85, 89, 86, 76), (89, 87, 78, 86), (84, 77, 87, 89), (17, 34, 69, 57), (50, 75, 85, 67), (64,
    82, 74, 60), (57, 69, 79, 52), (54, 86, 78, 51), (59, 72, 82, 64), (52, 79, 70, 48), (61, 76, 86, 54), (65, 83,
    73, 49), (48, 70, 36, 5), (68, 87, 77, 62), (60, 74, 83, 65)
    ])

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
