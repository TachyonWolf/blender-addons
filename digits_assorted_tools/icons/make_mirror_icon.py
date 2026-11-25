"""Writes mirror_transform.dat, the Mirror Transform tool icon: a shape and its mirror image either side of a dashed
centre line (like the Mirror modifier icon). Run: python3 make_mirror_icon.py
Format (read from Blender's own tool icons): b"VCO\\0" + b"\\xff\\xff\\x00\\x00", then every triangle's three (x, y)
byte pairs (0-255 grid), then every triangle's three RGBA colours."""
import os

HEADER = b"VCO\x00\xff\xff\x00\x00"
REAL_COLOR = (0xe5, 0xe5, 0xe5, 0xff)     # the two greys Blender's tool icons use
COPY_COLOR = (0xb3, 0xb3, 0xb3, 0xff)
CENTER_X = 127
HALF_SHAPE = ((52, 70), (112, 96), (112, 190), (52, 168))     # quad left of the centre line
DASHES = ((52, 84), (100, 132), (148, 180), (196, 204))      # (y start, y end) of each dash
DASH_HALF_WIDTH = 3


def mirror(point):
    return (254 - point[0], point[1])


def quad_triangles(quad):
    return [(quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])]


def dash_quad(y_start, y_end):
    left, right = CENTER_X - DASH_HALF_WIDTH, CENTER_X + DASH_HALF_WIDTH
    return ((left, y_start), (right, y_start), (right, y_end), (left, y_end))


def shapes():
    """[(triangle, colour)] for the whole icon."""
    mirrored_quad = tuple(mirror(point) for point in HALF_SHAPE)
    result = [(tri, REAL_COLOR) for tri in quad_triangles(HALF_SHAPE)]
    result += [(tri, COPY_COLOR) for tri in quad_triangles(mirrored_quad)]
    for y_start, y_end in DASHES:
        result += [(tri, COPY_COLOR) for tri in quad_triangles(dash_quad(y_start, y_end))]
    return result


def icon_bytes(triangles):
    """The .dat bytes for [(triangle, colour)] (also used by the other icon makers)."""
    coords = bytes(value for tri, _color in triangles for point in tri for value in point)
    colors = bytes(value for _tri, color in triangles for _vertex in range(3) for value in color)
    return HEADER + coords + colors


def build_bytes():
    return icon_bytes(shapes())


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_transform.dat")
    with open(path, "wb") as icon_file:
        icon_file.write(build_bytes())
    print("wrote", path)
