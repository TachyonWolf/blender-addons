"""Make the Bone Workshop shape-tile icons (icons/shapes/<tile id>.png) from the widget meshes themselves, so an icon
always shows what the tile gives. Run once after a tile or widget changes, headless:
blender -b --factory-startup --python make_shape_icons.py
The add-on only loads the PNGs (bone_workshop_ui, bpy.utils.previews)."""
import math
import os
import struct
import sys
import zlib

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from digits_assorted_tools import bone_workshop_spec as spec, face_rig_core as fr  # noqa: E402

SIZE, SUPER, MARGIN, WIDTH = 64, 4, 6, 2.2      # icon pixels, supersampling, margin and line width (icon pixels)
COLOUR = (230, 230, 230)
ISO = Matrix.Rotation(math.radians(-28), 3, 'X') @ Matrix.Rotation(math.radians(35), 3, 'Z')
VIEWS = {'front': lambda v: (v.x, v.z), 'top': lambda v: (v.x, v.y), 'iso': lambda v: ((ISO @ v).x, (ISO @ v).z)}
VIEW_OF = dict(sphere='iso', cube='iso', ico='iso', empty='iso', pointer='iso', cone='iso',
               arrow='top', line='top', capsule='top', paw='top')


def lines_of(ob):
    """Edges of a widget mesh (faces' outlines for a mesh with faces)."""
    me = ob.data
    edges = {tuple(sorted(e.vertices)) for e in me.edges}
    for poly in me.polygons:
        ring = list(poly.vertices)
        edges |= {tuple(sorted((a, b))) for a, b in zip(ring, ring[1:] + ring[:1])}
    return [v.co.copy() for v in me.vertices], sorted(edges)


def draw(points, edges):
    """Coverage (0..1) per pixel of the projected lines, supersampled."""
    big = SIZE * SUPER
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = (big - 2 * MARGIN * SUPER) / span
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    px = [((x - cx) * scale + big / 2, big / 2 - (y - cy) * scale) for x, y in points]
    grid = bytearray(big * big)
    radius = WIDTH * SUPER / 2
    for a, b in edges:
        (x0, y0), (x1, y1) = px[a], px[b]
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) / 0.5) + 1
        for k in range(steps + 1):
            x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
            for gy in range(int(y - radius), int(y + radius) + 1):
                for gx in range(int(x - radius), int(x + radius) + 1):
                    if 0 <= gx < big and 0 <= gy < big and (gx - x) ** 2 + (gy - y) ** 2 <= radius ** 2:
                        grid[gy * big + gx] = 1
    out = []
    for y in range(SIZE):
        row = []
        for x in range(SIZE):
            hits = sum(grid[(y * SUPER + j) * big + x * SUPER + i] for j in range(SUPER) for i in range(SUPER))
            row.append(hits / (SUPER * SUPER))
        out.append(row)
    return out


def write_png(path, cover):
    raw = b"".join(b"\x00" + b"".join(bytes((*COLOUR, int(255 * c))) for c in row) for row in cover)
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    folder = os.path.join(HERE, "shapes")
    os.makedirs(folder, exist_ok=True)
    for tile in spec.SHAPES:
        verts, edges = lines_of(fr.ensure_widget(spec.widget_of(tile.id)))
        project = VIEWS[VIEW_OF.get(tile.id, 'front')]
        write_png(os.path.join(folder, f"{tile.id}.png"), draw([project(Vector(v)) for v in verts], edges))
        print("ICON", tile.id)


main()
