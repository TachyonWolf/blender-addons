# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the decal object, its flat grid, its frame on the target and its modifier stack (tests:
tests/test_decals.py). Everything is rebuilt from the recipe (decal_recipe.py, `Object.digit_decal`).

The mesh is a LIGHT base grid (decal_maps.BASE_QUADS on the long side); the density comes from the Detail
modifier (Subdivision, Simple: square edges and UVs; render one level higher), so it lives only in the evaluated
mesh. States and stacks (modifier names below):
- Unattached: a flat grid in the world, no target ("ready to be attached"; made by scripts such as
  decal_api.create_decal, or by Detach) > Detail.
- Placing, by Over Edges (all Geometry Nodes, live on the posed Target):
  Squash / Fade: Detail > Wrap (Project group: one way down from just above, short reach, first surface wins,
  nearest surface for points that miss) > Mirror > [Fade] > Lift.
  Bend / Bend, then Fade: Detail > Bend (walk over the surface, decal_nodes) > Mirror > [Fade] > Lift.
  Mirror (Mirror X only): across the target's X, U flipped inside the crop. Fade: fades past the Edge Angle.
- Stuck: the light base holds the wrapped shape (baked) > Follow (Surface Deform, bound on the light base; copes
  with Subdivision levels that differ in renders) > Detail > Snap (GN, nearest surface: puts the subdivided points
  on it, at the render level too, fixes Surface Deform's small error at bends) > Lift.
Stick bakes the Placing stack without Detail and Lift (the Fade attribute comes along).
Lift is a small Geometry Nodes modifier ("Digit Decal Lift"): it moves along the normal by Lift + Layer Lift in
WORLD units, divided by the object's own scale, so scaling the decal with S never changes the real lift. Its Lift
input IS the Lift value (one source); Layer Lift is set from the layer number. Both work in either state without
rebinding. Size rebuilds the grid; the frame sets scale 1.
Nothing here runs on its own: every function is called by an operator or a property change."""

from contextlib import contextmanager

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import decal_maps, decal_material
from . import decal_nodes
from .decal_nodes import (EDGE_ANGLE_INPUT, LAYER_INPUT, LIFT_INPUT, REACH_INPUT,  # noqa: F401
                          add_modifier, ensure_bend_group, ensure_fade_group, ensure_lift_group, ensure_project_group,
                          ensure_snap_group, surface_inputs)
from .decal_recipe import BENDS, FADES
from .modifier_setup import modifier_input, set_modifier_input  # generated copy
from .decal_recipe import PLACING, STUCK, UNATTACHED
from .placement_math import axis_vector, default_up, surface_frame

WRAP = "Decal Wrap"
MIRROR = "Decal Mirror"
FOLLOW = "Decal Follow"
SNAP = "Decal Snap"
LIFT = "Decal Lift"
DETAIL = "Decal Detail"
BEND = "Decal Bend"
FADE = "Decal Fade"
DEFAULT_LIFT = decal_maps.DEFAULT_LIFT
DECALS_COLLECTION = "Decals"
UV_NAME = "UVMap"

_busy = set()   # decal names being rebuilt: their own property changes must not rebuild again


@contextmanager
def _rebuilding(decal):
    """While inside, the decal's own property changes don't trigger a rebuild."""
    _busy.add(decal.name)
    try:
        yield
    finally:
        _busy.discard(decal.name)


def is_decal(ob):
    return ob is not None and ob.type == 'MESH' and ob.digit_decal.is_decal


def decals_of(target):
    """The decals sitting on `target`, bottom layer first."""
    found = [child for child in target.children if is_decal(child) and child.digit_decal.target == target]
    return sorted(found, key=lambda decal: (decal.digit_decal.layer, decal.name))


def next_layer(target):
    decals = decals_of(target)
    return decals[-1].digit_decal.layer + 1 if decals else 0


def average_edge(target):
    """Average world edge length of the target's mesh (rough: mean object scale), 0.01 when it has no edges."""
    mesh = target.data
    if not mesh.edges:
        return 0.01
    coords = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coords)
    coords = coords.reshape(-1, 3)
    pairs = np.empty(len(mesh.edges) * 2, dtype=np.int32)
    mesh.edges.foreach_get("vertices", pairs)
    pairs = pairs.reshape(-1, 2)
    lengths = np.linalg.norm(coords[pairs[:, 0]] - coords[pairs[:, 1]], axis=1)
    scale = sum(abs(axis) for axis in target.matrix_world.to_scale()) / 3
    return float(lengths.mean()) * scale or 0.01


def render_mismatch(target):
    """Names of the target's modifiers that are on in only one of viewport / render: they can change its
    vertices between the two, so a Stuck decal may break in renders. (Subdivision levels that differ are fine:
    Surface Deform kept following in 5.3, see notes/wip/decals-plan.md P0.)"""
    return [modifier.name for modifier in target.modifiers if modifier.show_viewport != modifier.show_render]


def is_surface_of(decal, ob):
    """True for the mesh the decal lands on (its Target)."""
    return ob is not None and ob == decal.digit_decal.target


def decal_collection(context, target):
    """Where a new decal goes: the target's first collection when it is local, else a local `Decals`
    collection under the scene collection (a library-override or linked collection can't take new objects)."""
    for collection in target.users_collection:
        if collection.library is None and collection.override_library is None:
            return collection
    collection = bpy.data.collections.get(DECALS_COLLECTION)
    if collection is None or collection.library is not None or collection.override_library is not None:
        collection = bpy.data.collections.new(DECALS_COLLECTION)
    if collection.name not in context.scene.collection.children:
        context.scene.collection.children.link(collection)
    return collection


# --- grid and frame -------------------------------------------------------------------------------------------

def build_grid(decal):
    """Rebuild the decal's flat grid (local XY, facing +Z, real size) and its UVs from the recipe."""
    recipe = decal.digit_decal
    width, height = decal_maps.decal_dimensions(recipe.size, recipe.aspect)
    columns, rows = decal_maps.base_grid_counts(width, height)
    lifted = recipe.state == PLACING and recipe.over_edges not in BENDS
    start = decal_maps.projection_height(recipe.size) if lifted else 0.0   # projects down from here
    u0, v0, u1, v1 = recipe.crop
    if recipe.flip:
        u0, u1 = u1, u0
    points = []
    uvs = []
    for row in range(rows + 1):
        along_y = row / rows
        for column in range(columns + 1):
            along_x = column / columns
            points.append(((along_x - 0.5) * width, (along_y - 0.5) * height, start))
            uvs.append((u0 + (u1 - u0) * along_x, v0 + (v1 - v0) * along_y))
    faces = []
    for row in range(rows):
        for column in range(columns):
            first = row * (columns + 1) + column
            faces.append((first, first + 1, first + columns + 2, first + columns + 1))
    mesh = decal.data
    mesh.clear_geometry()
    mesh.from_pydata(points, [], faces)
    uv_layer = mesh.uv_layers.new(name=UV_NAME)
    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    uv_layer.data.foreach_set("uv", np.asarray(uvs, dtype=np.float32)[loop_vertices].ravel())
    mesh.shade_smooth()   # follows the target's curve without facets
    mesh.update()


def base_frame_world(decal):
    """(point, normal, up) of the recipe's base frame in world space."""
    recipe = decal.digit_decal
    matrix = recipe.target.matrix_world if recipe.target else Matrix.Identity(4)
    turn = matrix.to_3x3()
    return (matrix @ recipe.point.copy(), (turn @ recipe.normal.copy()).normalized(),
            (turn @ recipe.up.copy()).normalized())


def set_base_frame(decal, point, normal, up):
    """Store an aim (world point, normal, up) in the recipe, in the target's local space."""
    recipe = decal.digit_decal
    matrix = recipe.target.matrix_world if recipe.target else Matrix.Identity(4)
    turn_back = matrix.to_3x3().inverted_safe()
    recipe.point = matrix.inverted_safe() @ point
    recipe.normal = turn_back @ normal
    recipe.up = turn_back @ up


def apply_frame(decal):
    """Place the decal object on its base frame turned by Rotation (scale 1)."""
    point, normal, up = base_frame_world(decal)
    decal.matrix_world = surface_frame(point, normal, up, decal.digit_decal.rotation)


# --- modifier stack -------------------------------------------------------------------------------------------

def default_lift():
    """The scene's Default Lift setting (decal_maps.DEFAULT_LIFT without one)."""
    settings = getattr(bpy.context.scene, "digit_decals", None)
    return settings.default_lift if settings is not None else DEFAULT_LIFT


def _scale_of(decal):
    """The decal's visible scale in its own plane (mean of world X / Y scale; 1 = as built)."""
    scale = decal.matrix_world.to_scale()
    return (abs(scale.x) + abs(scale.y)) / 2


def _absorb_scale(decal, keep_size=False):
    """Fold a scale set with S into the recipe's Size (so the rebuild that follows, at scale 1, looks the same
    size and Size shows the real size). `keep_size`: the user just typed Size, which wins. Call inside
    _rebuilding."""
    factor = _scale_of(decal)
    if abs(factor - 1.0) > 1e-6 and not keep_size:
        decal.digit_decal.size *= factor


def lift_of(decal):
    """The decal's Lift (world units): the Lift modifier's input; an old file's Displace strength; else the
    scene's Default Lift."""
    modifier = decal.modifiers.get(LIFT)
    if modifier is None:
        return default_lift()
    if modifier.type == 'NODES':
        return modifier_input(modifier, LIFT_INPUT).value
    return modifier.strength


def set_lift(decal, value):
    """Lift lives on the Lift modifier (nothing to set while Unattached)."""
    modifier = decal.modifiers.get(LIFT)
    if modifier is not None and modifier.type == 'NODES':
        set_modifier_input(modifier, LIFT_INPUT, value)
        decal.update_tag()


def detail_of(decal):
    modifier = decal.modifiers.get(DETAIL)
    return modifier.levels if modifier else decal_maps.DEFAULT_DETAIL


def set_detail(decal, value):
    """Detail lives on the Detail modifier (viewport levels; render one more). After Follow in Stuck, so changing
    it never breaks the bind."""
    modifier = decal.modifiers.get(DETAIL)
    if modifier is not None:
        modifier.levels = value
        modifier.render_levels = min(value + decal_maps.RENDER_EXTRA_DETAIL, decal_maps.MAX_DETAIL + 1)


def layer_step():
    """The scene's Layer Step setting (decal_maps.LAYER_STEP without one)."""
    settings = getattr(bpy.context.scene, "digit_decals", None)
    return settings.layer_step if settings is not None else decal_maps.LAYER_STEP


def _detail(decal, levels):
    modifier = decal.modifiers.new(DETAIL, 'SUBSURF')
    modifier.subdivision_type = 'SIMPLE'
    modifier.uv_smooth = 'NONE'
    set_detail(decal, levels)
    return modifier


def _refresh_group_users(skip):
    """An older file's node group was just rebuilt in place (new inputs): give every other decal using it its
    inputs again from its recipe (no rebuild, so binds stay)."""
    rebuilt = set(decal_nodes.rebuilt_groups)
    decal_nodes.rebuilt_groups.clear()
    values = {WRAP: lambda recipe: dict(surface_inputs(recipe), Reach=2 * decal_maps.projection_height(recipe.size)),
              BEND: surface_inputs, SNAP: surface_inputs,
              FADE: lambda recipe: {"Edge_Angle": recipe.edge_angle}}
    for ob in bpy.data.objects:
        if ob == skip or not is_decal(ob):
            continue
        for modifier in ob.modifiers:
            if modifier.type == 'NODES' and modifier.node_group and modifier.node_group.name in rebuilt \
                    and modifier.name in values:
                for item in modifier.node_group.interface.items_tree:   # new inputs start at their defaults
                    if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and hasattr(item, "default_value"):
                        set_modifier_input(modifier, item.name, item.default_value)
                for name, value in values[modifier.name](ob.digit_decal).items():
                    set_modifier_input(modifier, name.replace("_", " "), value)
                ob.update_tag()


def update_layer_lift(decal):
    modifier = decal.modifiers.get(LIFT)
    if modifier is not None and modifier.type == 'NODES':
        recipe = decal.digit_decal
        set_modifier_input(modifier, LAYER_INPUT, decal_maps.layer_lift(recipe.layer, recipe.size, layer_step()))
        decal.update_tag()


def build_stack(decal, lift=None, detail=None):
    """Rebuild the decal's modifiers for its state (Surface Deform is added unbound). Lift and Detail carry over
    from the old stack unless given."""
    recipe = decal.digit_decal
    lift = lift_of(decal) if lift is None else lift
    detail = detail_of(decal) if detail is None else detail
    decal.modifiers.clear()
    if recipe.state == UNATTACHED:
        _detail(decal, detail)
        return
    if recipe.state == PLACING:
        _detail(decal, detail)
        surface = surface_inputs(recipe)
        if recipe.over_edges in BENDS:
            add_modifier(decal, BEND, ensure_bend_group(), **surface)
        else:
            reach = 2 * decal_maps.projection_height(recipe.size)   # one way down, from just above, short reach
            add_modifier(decal, WRAP, ensure_project_group(), Reach=reach, **surface)
        if recipe.mirror_x:
            mirror = decal.modifiers.new(MIRROR, 'MIRROR')
            mirror.use_axis = (True, False, False)
            mirror.mirror_object = recipe.target
            mirror.use_mirror_merge = False
            mirror.use_mirror_u = True
            mirror.mirror_offset_u = decal_maps.mirror_uv_offset(recipe.crop[0], recipe.crop[2])
        if recipe.over_edges in FADES:
            add_modifier(decal, FADE, ensure_fade_group(), Edge_Angle=recipe.edge_angle)
    else:
        follow = decal.modifiers.new(FOLLOW, 'SURFACE_DEFORM')
        follow.target = recipe.target
        _detail(decal, detail)
        add_modifier(decal, SNAP, ensure_snap_group(), **surface_inputs(recipe))
    add_modifier(decal, LIFT, ensure_lift_group(), Lift=lift)
    update_layer_lift(decal)
    if decal_nodes.rebuilt_groups:
        _refresh_group_users(decal)
    decal_material.ensure_fade_input(decal.active_material)


def facing_normal(facing):
    """The unit normal of `facing`: an axis name ("-Y", "+X", "Z") or any 3-vector (not zero)."""
    if isinstance(facing, str):
        return axis_vector(facing.lstrip("+"))
    normal = Vector(facing)
    if normal.length < 1e-6:
        raise ValueError("facing needs an axis name or a non-zero 3-vector")
    return normal.normalized()


# --- create and states ----------------------------------------------------------------------------------------

def new_decal(context, images, stem, size, location=(0.0, 0.0, 0.0), collection=None, facing="Z", flip=False,
              shading='LIT'):
    """A new Unattached decal: a flat real-size grid at world `location` facing the world axis `facing` ("Z",
    "-Y", "+X"...: placement_math.axis_vector names, a "+" allowed; or any 3-vector), image up = placement_math.default_up of
    that axis (world Z, or Y when facing up or down), with its material, no target and no wrap ("ready to be
    attached"). {role: image}, Color needed. Long side `size` metres. `flip` mirrors the image left to right.
    `shading` 'LIT' or 'UNLIT' (images that already hold their lighting). Casts no shadow, in any engine."""
    normal = facing_normal(facing)
    name = decal_maps.decal_name(stem)
    crop = decal_material.visible_crop(images["COLOR"], images.get("ALPHA"))
    mesh = bpy.data.meshes.new(name)
    decal = bpy.data.objects.new(name, mesh)
    (collection or context.collection or context.scene.collection).objects.link(decal)
    decal.visible_shadow = False             # Cycles and EEVEE: never darkens what is under it
    decal.visible_volume_scatter = False
    decal.is_holdout = False
    material = decal_material.make_material(name, images)
    decal_material.set_shading(material, shading)
    mesh.materials.append(material)
    with _rebuilding(decal):
        recipe = decal.digit_decal
        recipe.state = UNATTACHED
        recipe.size = size
        recipe.crop = crop.rect
        recipe.crop_pixels = (crop.width_px, crop.height_px)
        recipe.point = location
        recipe.normal = normal
        recipe.up = default_up(normal)
        recipe.flip = flip
        recipe.is_decal = True
        build_grid(decal)
        apply_frame(decal)
        build_stack(decal, detail=decal_maps.DEFAULT_DETAIL)
    return decal


def attach(context, decal, target, point, normal, up=None, lift=None):
    """Unattached (or Placing on another target) > Placing on `target`, aimed at world `point` / `normal`."""
    lift = lift_of(decal) if lift is None else lift
    detail = None
    with _rebuilding(decal):
        recipe = decal.digit_decal
        _absorb_scale(decal)
        if recipe.target != target:
            recipe.target = target
            recipe.layer = next_layer(target)
            recipe.target_edge = average_edge(target)
            detail = decal_maps.detail_levels(recipe.size, recipe.target_edge)
            _move_to(decal, decal_collection(context, target))
        decal.parent = target
        decal.matrix_parent_inverse = target.matrix_world.inverted_safe()
        recipe.state = PLACING
        set_base_frame(decal, point, normal, up if up is not None else default_up(normal.normalized()))
        build_grid(decal)
        apply_frame(decal)
        build_stack(decal, lift, detail)


def _move_to(decal, collection):
    if collection in decal.users_collection:
        return
    for old in list(decal.users_collection):
        old.objects.unlink(decal)
    collection.objects.link(decal)


def detach(decal):
    """Placing / Stuck > Unattached: a flat grid where the decal is now (its world frame), no target, no wrap."""
    with _rebuilding(decal):
        recipe = decal.digit_decal
        _absorb_scale(decal)
        world = decal.matrix_world.copy()
        decal.parent = None
        decal.matrix_world = world
        recipe.target = None
        recipe.state = UNATTACHED
        recipe.rotation = 0.0
        recipe.point = world.translation
        recipe.normal = world.to_3x3().col[2].normalized()
        recipe.up = world.to_3x3().col[1].normalized()
        build_grid(decal)
        apply_frame(decal)
        build_stack(decal)


def create_decal(context, target, images, point, normal, size, stem, up=None, lift=None, shading='LIT'):
    """A new Placing decal on `target` aimed at world `point` / `normal` (new_decal + attach). Lift: the scene's
    Default Lift unless given."""
    decal = new_decal(context, images, stem, size, collection=decal_collection(context, target), shading=shading)
    attach(context, decal, target, point, normal, up, lift)
    return decal


def stick(context, decal):
    """Placing > Stuck: bake the wrapped shape, add Surface Deform and bind it. Returns a list of warnings
    (empty when all is well)."""
    recipe = decal.digit_decal
    warnings = [f"{recipe.target.name}: modifier '{name}' is on in only one of viewport / render; the decal may "
                "not follow in renders" for name in render_mismatch(recipe.target)]
    lift = lift_of(decal)
    with _rebuilding(decal):
        if recipe.state == STUCK or abs(_scale_of(decal) - 1.0) > 1e-6:
            _unstick(decal, lift)   # Rebind, or a scale from S to fold in: back to the flat grid first
        for name in (DETAIL, LIFT):   # bake only the wrap on the light base: Detail and Lift stay live
            decal.modifiers[name].show_viewport = False
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        baked = bpy.data.meshes.new_from_object(decal.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                                depsgraph=depsgraph)
        old = decal.data
        decal.data = baked
        baked.name = old.name
        if old.users == 0:
            bpy.data.meshes.remove(old)
        recipe.state = STUCK
        build_stack(decal, lift)
        context.view_layer.update()
        follow = decal.modifiers[FOLLOW]
        if not follow.is_bound:   # the bind operator toggles: only call it when unbound
            with context.temp_override(object=decal, active_object=decal):
                bpy.ops.object.surfacedeform_bind(modifier=FOLLOW)
        if not follow.is_bound:
            warnings.append("Surface Deform could not bind: is the decal touching the target?")
        recipe.bound_vertex_count = len(recipe.target.data.vertices)
    return warnings


def unstick(decal):
    """Stuck > Placing: back to the flat grid on its base frame, sliding again."""
    with _rebuilding(decal):
        _unstick(decal, lift_of(decal))


def _unstick(decal, lift):
    _absorb_scale(decal)
    decal.digit_decal.state = PLACING
    build_grid(decal)
    apply_frame(decal)
    build_stack(decal, lift)


def needs_rebind(decal, vertex_count=None):
    """True when a Stuck decal no longer follows: Surface Deform missing / unbound, or the target's vertex count
    changed since the bind. `vertex_count`: the target's, when the caller already has it (one count per list)."""
    recipe = decal.digit_decal
    if recipe.state != STUCK:
        return False
    follow = decal.modifiers.get(FOLLOW)
    if follow is None or recipe.target is None:
        return True
    if follow.type != 'SURFACE_DEFORM' or not follow.is_bound:
        return True
    count = len(recipe.target.data.vertices) if vertex_count is None else vertex_count
    return recipe.bound_vertex_count != count


def rebind(context, decal):
    """Re-stick from the base frame (Unstick + Stick). Returns Stick's warnings."""
    return stick(context, decal)


def move_layer(decal, direction):
    """Swap the decal's layer with its neighbour above (direction 1) or below (-1). False at the end."""
    decals = decals_of(decal.digit_decal.target)
    index = decals.index(decal)
    other_index = index + direction
    if not 0 <= other_index < len(decals):
        return False
    decals[index], decals[other_index] = decals[other_index], decals[index]
    for layer, each in enumerate(decals):   # renumber 0..n-1: no gaps or ties left behind
        each.digit_decal.layer = layer
        update_layer_lift(each)
    return True


def fold_scale(decal):
    """Fold a scale set with S into Size now (rebuild at scale 1, same look). True when there was one."""
    if abs(_scale_of(decal) - 1.0) <= 1e-6:
        return False
    with _rebuilding(decal):
        lift = lift_of(decal)
        _absorb_scale(decal)
        build_grid(decal)
        apply_frame(decal)
        if decal.digit_decal.state != UNATTACHED:
            build_stack(decal, lift)
    return True


def drag_frame(decal, point=None, normal=None, up=None, rotation=None, size=None):
    """A handle drag step on a Placing decal: new aim (world point / normal / up), Rotation or Size, then only the
    grid (for a new size) and the frame are rebuilt; the stack is refreshed once, by finish_drag."""
    with _rebuilding(decal):
        recipe = decal.digit_decal
        if point is not None:
            set_base_frame(decal, point, normal, up)
        if rotation is not None:
            recipe.rotation = rotation
        if size is not None:
            recipe.size = size
            build_grid(decal)
        apply_frame(decal)


def finish_drag(context, decal, stick_again):
    """End of a handle drag: refresh the stack (project reach, layer lift follow the size); a decal that was
    Stuck before the drag sticks again. Returns Stick's warnings."""
    if decal.digit_decal.state == PLACING:
        with _rebuilding(decal):
            build_stack(decal)
    return stick(context, decal) if stick_again else []


def recipe_changed(decal, rebuild_grid, size_typed=False):
    """A recipe setting changed (Size, Rotation, Flip, Mirror X, Wrap): rebuild what it touches. A Stuck decal
    unsticks first (no bake or bind per change)."""
    if not is_decal(decal) or decal.name in _busy:
        return
    with _rebuilding(decal):
        recipe = decal.digit_decal
        _absorb_scale(decal, keep_size=size_typed)
        rebuild_grid = rebuild_grid or abs(_scale_of(decal) - 1.0) > 1e-6
        if recipe.state == UNATTACHED:
            build_grid(decal)
            apply_frame(decal)
            return
        lift = lift_of(decal)
        was_stuck = recipe.state == STUCK
        recipe.state = PLACING
        if rebuild_grid or was_stuck:
            build_grid(decal)
        apply_frame(decal)
        build_stack(decal, lift)
