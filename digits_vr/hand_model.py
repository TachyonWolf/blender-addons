# SPDX-License-Identifier: GPL-3.0-or-later
"""The simple hand (DESIGN "Keyboard and simple hand"): 3 capsules per finger (the thumb too) and a palm block, in the
controller's GRIP space (metres, your size 1.0). Pure Python (no bpy, no mathutils), tested headless.

Grip space (right hand): fingers point along -Z, +Y is up (the thumb side), the palm faces -X. The left hand is the
mirror (x flipped). A finger curls towards the palm: its direction turns from forward (-Z) to the palm side. The
numbers are a guess at a Touch controller held in the hand; adjust them in the headset.

Curls are 0 (stretched) to 1 (fist) per finger: trigger -> index, grip -> middle / ring / pinky, a thumb input -> thumb."""
import math

FINGERS = ('thumb', 'index', 'middle', 'ring', 'pinky')
FORWARD = (0.0, 0.0, -1.0)
# The palm and the wrist: two flat beveled octagonal prisms in the Y-Z plane, as (centre z, half width y, half length z).
# The palm is the hand-sized one: all four fingers attach along its front (top) edge and the thumb comes off its side,
# near the bottom. The wrist is smaller and sits below it, towards the controller's handle, like a forearm stub.
PALM_HALF_THICKNESS, PALM_BEVEL, PALM_CORNER = 0.012, 0.004, 0.012
PALM_PARTS = ((-0.003, 0.040, 0.042), (0.062, 0.026, 0.025))
FINGER_ROOTS = {'index': (0.0, 0.033, -0.045), 'middle': (0.0, 0.011, -0.045), 'ring': (0.0, -0.011, -0.045),
                'pinky': (0.0, -0.033, -0.045), 'thumb': (-0.004, 0.036, 0.024)}      # x is for the right hand
SEGMENT_LENGTHS = {'thumb': (0.032, 0.028, 0.024), 'index': (0.040, 0.025, 0.020), 'middle': (0.044, 0.028, 0.021),
                   'ring': (0.040, 0.026, 0.020), 'pinky': (0.032, 0.020, 0.017)}
RADII = {'thumb': 0.0095, 'index': 0.0085, 'middle': 0.0085, 'ring': 0.008, 'pinky': 0.0075}
JOINT_DEGREES = (70.0, 90.0, 60.0)          # how far each finger joint bends at curl 1 (cumulative along the finger)
THUMB_REST = (0.0, 0.60, -0.80)              # thumb direction at rest (up and forward) and when pressed down
THUMB_DOWN = (-0.80, -0.30, -0.50)
THUMB_WEIGHTS = (0.6, 0.85, 1.0)
REST_CURLS = {'thumb': 0.0, 'index': 0.0, 'middle': 0.25, 'ring': 0.25, 'pinky': 0.25}
CURL_RATE = 18.0                             # per second: how fast a finger follows its target
EXTENDED_TRIGGER = 0.3                       # a trigger pulled less than this leaves the index pointing


def _normal(vector):
    length = math.sqrt(sum(part * part for part in vector))
    return tuple(part / length for part in vector)


def _plus(point, direction, length):
    return tuple(point[axis] + direction[axis] * length for axis in range(3))


def _mixed(first, second, amount):
    return _normal(tuple(first[axis] + (second[axis] - first[axis]) * amount for axis in range(3)))


def finger_directions(name, side, curl):
    """The direction of each of the finger's three segments at `curl` (0..1) for a hand on `side` (+1 right, -1 left)."""
    if name == 'thumb':
        rest = (THUMB_REST[0] * side, THUMB_REST[1], THUMB_REST[2])
        down = (THUMB_DOWN[0] * side, THUMB_DOWN[1], THUMB_DOWN[2])
        return [_mixed(rest, down, curl * weight) for weight in THUMB_WEIGHTS]
    directions, angle = [], 0.0
    for degrees in JOINT_DEGREES:
        angle += math.radians(degrees) * curl
        directions.append((-side * math.sin(angle), 0.0, -math.cos(angle)))      # forward turning to the palm side
    return directions


def finger_points(name, side, curl):
    """The four joint points of one finger (root, three segment ends)."""
    root = FINGER_ROOTS[name]
    points = [(root[0] * side, root[1], root[2])]
    for direction, length in zip(finger_directions(name, side, curl), SEGMENT_LENGTHS[name]):
        points.append(_plus(points[-1], direction, length))
    return points


def segments(side, curls):
    """All 15 capsules: [(start, end, radius, finger name)], from the curls {finger: 0..1}."""
    result = []
    for name in FINGERS:
        points = finger_points(name, side, curls[name])
        result += [(points[index], points[index + 1], RADII[name], name) for index in range(3)]
    return result


def fingertip(side, name, curls):
    """The tip of one finger (the end of its last capsule, pushed out by the capsule radius): the poke point."""
    points = finger_points(name, side, curls[name])
    direction = _normal(tuple(points[3][axis] - points[2][axis] for axis in range(3)))
    return _plus(points[3], direction, RADII[name])


FIST_FINGERS = ('middle', 'ring')


def fist_centre(side):
    """The middle of the closed fist (curl 1) of a hand on `side`, where a held handle sits: the mean of the middle and
    ring fingers' joints (grip space, metres, your size 1.0)."""
    points = [point for name in FIST_FINGERS for point in finger_points(name, side, 1.0)]
    return tuple(sum(point[axis] for point in points) / len(points) for axis in range(3))


def fingertips(side, curls, names=FINGERS):
    return {name: fingertip(side, name, curls) for name in names}


def targets(trigger, grip, thumb_down):
    """Target curls from the inputs: trigger (0..1), grip (0..1), thumb input (stick pushed / A, B, X, Y touched)."""
    wrap = REST_CURLS['middle'] + (1.0 - REST_CURLS['middle']) * min(1.0, max(0.0, grip))
    return {'thumb': 1.0 if thumb_down else 0.0, 'index': min(1.0, max(0.0, trigger)),
            'middle': wrap, 'ring': wrap, 'pinky': wrap}


def approach(current, target, seconds, rate=CURL_RATE):
    """Move every curl towards its target: an exponential ease that does not depend on the frame rate."""
    share = 1.0 - math.exp(-rate * max(0.0, seconds))
    return {name: value + (target[name] - value) * share for name, value in current.items()}


def quantized(curls, steps=16):
    """The curls as a hashable key (a cached mesh is reused for curls within 1/steps of each other)."""
    return tuple(round(curls[name] * steps) for name in FINGERS)


def curls_from_key(key, steps=16):
    return {name: value / steps for name, value in zip(FINGERS, key)}


def index_extended(trigger):
    return trigger < EXTENDED_TRIGGER
