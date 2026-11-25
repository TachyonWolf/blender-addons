# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode in VR, pure maths (numpy, no bpy): what may be edited, vertex picking by the laser / the hand, and
moving local vertex coordinates by a world delta. Points here are (n, 3) float arrays; matrices are 4x4 numpy arrays."""
import numpy as np

try:
    from . import pick_math
except ImportError:        # the headless pure tests import the modules top-level
    import pick_math

MAX_FACES = 250_000       # bigger meshes are refused: entering costs 160 ms at 250k (headless), one select 40 ms
HOVER_MAX_VERTS = 20_000  # vertex hover preview only up to here (brute-force numpy: 0.27 ms at 20k, 3.3 ms at 250k)
HOVER_MAX_FACES = 60_000  # edge / face hover only up to here (the lazy face BVH: 50 ms at 50k faces, 245 ms at 250k)
TRIS_EACH_FRAME_FACES = 60_000   # update_edit_mesh(loop_triangles=True) per frame only up to here (3.4 ms at 250k, 0.2 ms without)
MAX_GRAB_VERTS = 3000     # selected vertices one grab moves (Python writes v.co per frame: 20k = 2-4 ms headless; ox 2k = 1.5 ms)
LASER_PICK_RADIUS = 0.03  # m at user size 1: a vertex this close to the laser can be picked
TWIN_TOLERANCE = 1e-4     # m (object space): a mirror twin lies this close to the mirrored point
MIN_MOVE = 1e-7           # m: a grab that moved less than this changed nothing (no undo step)


def refusal(facts):
    """Why Edit mode in VR can't work on this mesh (short text for the desk), or None. `facts` is a dict made by
    edit_state.facts(): linked, objects_in_mode, key_locked, faces, scale_zero."""
    if facts["linked"]:
        return "Linked mesh: can't edit"
    if facts["objects_in_mode"] > 1:
        return "More than one object in Edit mode"
    if facts["key_locked"]:
        return "The active shape key is locked"
    if facts["faces"] > MAX_FACES:
        return f"Over {MAX_FACES // 1000}k faces: not in VR yet"
    if facts["scale_zero"]:
        return "Object scale is zero"
    return None


def to_world(points, matrix):
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def nearest_to_ray(origin, direction, points, radius, max_length):
    """Index of the vertex a laser points at (world points), or None. Candidates lie within `radius` of the ray and
    in front of the hand; of those the front layer wins (within 2 radii of the nearest along the ray), then the one
    closest to the ray, so a back vertex behind a front one is never picked."""
    if len(points) == 0:
        return None
    relative = points - origin
    along = relative @ direction
    perpendicular = relative - along[:, None] * direction
    squared = np.einsum("ij,ij->i", perpendicular, perpendicular)
    near = (along > 0.0) & (along <= max_length) & (squared <= radius * radius)
    if not near.any():
        return None
    front = along[near].min()
    layer = near & (along <= front + 2.0 * radius)
    return int(np.argmin(np.where(layer, squared, np.inf)))


def nearest_to_point(point, points, radius):
    """Index of the nearest of world `points` within `radius` of `point`, or None."""
    if len(points) == 0:
        return None
    relative = points - point
    squared = np.einsum("ij,ij->i", relative, relative)
    index = int(np.argmin(squared))
    return index if squared[index] <= radius * radius else None


def local_delta(world_matrix, world_delta):
    """The world delta as a delta of the object's local space: M^-1 . delta . M."""
    return np.linalg.inv(world_matrix) @ world_delta @ world_matrix


def move_points(base, delta):
    """`base` (n, 3) moved by the 4x4 `delta`."""
    return base @ delta[:3, :3].T + delta[:3, 3]


def moved_enough_points(base, now):
    return bool(len(base)) and float(np.abs(now - base).max()) > MIN_MOVE


def visible_edges(edges, vertex_visible, edge_hidden):
    """Edges to draw: not hidden themselves and both vertices visible."""
    keep = ~edge_hidden & vertex_visible[edges[:, 0]] & vertex_visible[edges[:, 1]]
    return edges[keep]


def mirror_x(points):
    """`points` mirrored across the object's local x = 0."""
    mirrored = points.copy()
    mirrored[:, 0] = -mirrored[:, 0]
    return mirrored


class MirrorPlan:
    """Mirror X for ONE grab, worked out at its start (the rows never change while it runs). `indices` (k) are the
    selected vertices, `base` (k, 3) their start points, `twins` (k) the twin vertex index of each (-1 none, itself on
    the axis). We never SELECT twins: an unselected twin follows its vertex mirrored (`extra_*`); when both sides are
    selected, the side of `driver_sign` (the grabbed vertex's) drives and the other copies it mirrored; a vertex on the
    axis stays on x = 0."""

    def __init__(self, indices, base, twins, driver_sign):
        rows = {int(index): row for row, index in enumerate(indices.tolist())}
        self.on_axis = np.flatnonzero(twins == indices)
        extra_rows, extra_indices, follower, driver = [], [], [], []
        for row, (index, twin) in enumerate(zip(indices.tolist(), twins.tolist())):
            if twin < 0 or twin == index:
                continue
            other = rows.get(twin)
            if other is None:
                extra_rows.append(row)
                extra_indices.append(twin)
            elif base[row, 0] * driver_sign < 0:
                follower.append(row)
                driver.append(other)
        self.extra_rows, self.extra_indices = np.array(extra_rows, int), np.array(extra_indices, int)
        self.follower, self.driver = np.array(follower, int), np.array(driver, int)

    def apply(self, moved):
        """(moved, extra_points): `moved` with followers copied and axis vertices on x = 0, and the points of the
        unselected twins."""
        moved = moved.copy()
        moved[self.on_axis, 0] = 0.0
        if len(self.follower):
            moved[self.follower] = mirror_x(moved[self.driver])
        return moved, mirror_x(moved[self.extra_rows])

    @property
    def active(self):
        return bool(len(self.on_axis) or len(self.extra_rows) or len(self.follower))


VERT, EDGE, FACE = 'VERT', 'EDGE', 'FACE'


def select_kind(mode_flags):
    """The element we pick from Blender's own select mode (tool_settings.mesh_select_mode = (vert, edge, face)):
    vertex wins when several are on, then edge, then face (as a click does in Blender's mixed mode)."""
    vertex, edge, face = mode_flags
    return VERT if vertex else EDGE if edge else FACE if face else VERT


def nearest_edge_to_ray(origin, direction, heads, tails, radius, max_length):
    """Index of the edge (world segments) a laser points at, or None: within `radius` of the ray; the front layer
    (within 2 radii of the nearest along the ray) wins, then the closest to the ray."""
    if len(heads) == 0:
        return None
    gap, along = pick_math.ray_segment_distances(origin, direction, heads, tails)
    near = (gap <= radius) & (along <= max_length)
    if not near.any():
        return None
    layer = near & (along <= along[near].min() + 2.0 * radius)
    return int(np.argmin(np.where(layer, gap, np.inf)))


def nearest_edge_to_point(point, heads, tails, radius):
    if len(heads) == 0:
        return None
    gap = pick_math.segment_distances(point, heads, tails)
    index = int(np.argmin(gap))
    return index if gap[index] <= radius else None
