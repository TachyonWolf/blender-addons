"""Writes placement_general.dat, the Placement: General tool icon: a map pin dropping onto a flat dial (an ellipse ring).
Run: python3 make_placement_icon.py   (format and colours: make_mirror_icon.py)"""
import os
from math import cos, pi, sin

from make_mirror_icon import COPY_COLOR, REAL_COLOR, icon_bytes, quad_triangles

RING_CENTRE, RING_RADII, RING_WIDTH, RING_STEPS = (127, 62), (100, 38), 12, 32
PIN_TIP, PIN_TOP, PIN_HALF_WIDTH = (127, 66), 236, 44
PIN_BODY_STEPS = 12


def ring_triangles():
    """The dial: a band between two ellipses, as quads."""
    (centre_x, centre_y), (radius_x, radius_y) = RING_CENTRE, RING_RADII
    result = []
    for step in range(RING_STEPS):
        quad = []
        for index, inset in ((step, 0), (step + 1, 0), (step + 1, RING_WIDTH), (step, RING_WIDTH)):
            angle = 2 * pi * index / RING_STEPS
            quad.append((round(centre_x + (radius_x - inset) * cos(angle)),
                         round(centre_y + (radius_y - inset * radius_y / radius_x) * sin(angle))))
        result += [(tri, COPY_COLOR) for tri in quad_triangles(quad)]
    return result


def pin_triangles():
    """The pin: a round head (a fan) on a point that touches the dial's middle."""
    head_y = PIN_TOP - PIN_HALF_WIDTH
    head = [(round(PIN_TIP[0] + PIN_HALF_WIDTH * cos(pi * step / PIN_BODY_STEPS)),
             round(head_y + PIN_HALF_WIDTH * sin(pi * step / PIN_BODY_STEPS))) for step in range(PIN_BODY_STEPS + 1)]
    centre = (PIN_TIP[0], head_y)
    result = [((centre, head[step], head[step + 1]), REAL_COLOR) for step in range(PIN_BODY_STEPS)]
    result.append((((PIN_TIP[0] + PIN_HALF_WIDTH, head_y), (PIN_TIP[0] - PIN_HALF_WIDTH, head_y), PIN_TIP), REAL_COLOR))
    return result


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "placement_general.dat")
    with open(path, "wb") as icon_file:
        icon_file.write(icon_bytes(ring_triangles() + pin_triangles()))
    print("wrote", path)
