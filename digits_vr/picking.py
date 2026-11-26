# SPDX-License-Identifier: GPL-3.0-or-later
"""Target picking against the live scene: what a hand touches (Free mode) or the laser points at, by what
Blender draws (object_shapes.py): surfaces by their evaluated geometry (scene.ray_cast, closest_point_on_mesh;
world boxes only skip far objects, being inside a box never counts), line shapes (empties, lights, cameras,
curves without faces) and bones by their edges (pick_math.BoneEdges). This file feeds the math scene data and keeps
the caches (world boxes, line shapes, bone segments). Caches refresh only what the depsgraph says changed, and drop fully on undo / redo / load (A18).
Linked data is picked too (so hover can say "linked"), but marked, and the tools refuse it (Q7)."""
from dataclasses import dataclass

import numpy as np
from mathutils import Vector

from . import display_types, object_shapes, settings, pick_math, shape_math, workspace

OBJECT, BONE = 'OBJECT', 'BONE'
RAY_SKIPS = 8          # the laser passes through at most this many unpickable surfaces (hide_select, ...)


@dataclass
class Target:
    kind: str                # OBJECT or BONE
    object_name: str         # Object.name_full (refs die on undo: re-find by name)
    bone_name: str = ""
    linked: bool = False     # can't be changed (linked, not overridden)
    distance: float = 0.0    # along the laser, or the touch gap
    index: int = -1          # EDIT_VERT: the element index in the edit bmesh
    element: str = 'VERT'    # EDIT_VERT: which element: VERT, EDGE or FACE (Blender's select mode)

    def key(self):
        return self.kind, self.object_name, self.bone_name

    def find_object(self, data):
        return find_object(data, self.object_name)


def find_object(data, name_full):
    """Object by Object.name_full (local names directly; linked ones carry ' [library]')."""
    ob = data.objects.get(name_full)
    if ob is not None or "[" not in name_full:
        return ob
    return next((item for item in data.objects if item.name_full == name_full), None)


@dataclass
class SurfaceHit:
    """A surface a ray met, with its normal towards the ray's start."""
    owner: object            # the pickable object (a collection instance for its instanced parts)
    hit_object: object       # the evaluated object whose face was hit
    location: Vector
    normal: Vector
    face: int

    @property
    def instanced(self):
        return self.hit_object.original != self.owner


SURFACE, LINES, WHOLE = 'SURFACE', 'LINES', 'WHOLE'     # parts of one hover pick (Picker.laser_part / touch_part)


def nearest(*targets):
    """The nearest of some targets (None entries skipped), or None."""
    return min((target for target in targets if target), key=lambda target: target.distance, default=None)


def is_linked(ob):
    return bool(ob.library) and not ob.override_library


def pickable(ob, view_layer):
    return ob.visible_get(view_layer=view_layer) and not ob.hide_select


def _bone_visible(pose_bone):
    """Shown and selectable in Pose mode: not hidden (PoseBone.hide in 5.x; Bone.hide is the Edit mode flag), not
    unselectable (Bone.hide_select, e.g. the rig's pole lines), in a visible bone collection (or in none)."""
    bone = pose_bone.bone
    if pose_bone.hide or bone.hide_select:
        return False
    collections = bone.collections
    return not len(collections) or any(getattr(c, "is_visible_effectively", c.is_visible) for c in collections)


def _shape_offset(pose_bone):
    return pick_math.shape_offset(pose_bone.custom_shape_translation, pose_bone.custom_shape_rotation_euler,
                                  pose_bone.custom_shape_scale_xyz, pose_bone.bone.length,
                                  pose_bone.use_custom_shape_bone_size)


def bone_display_lines(pose_bone):
    """Armature-space line pairs of what Blender draws for a pose bone: its custom shape's edges placed by
    Blender's rule, or head-tail without a shape. Loose shape points become short crosses so they show."""
    geometry = object_shapes.shape_geometry(pose_bone.custom_shape) if pose_bone.custom_shape else None
    if geometry is None:
        return [tuple(pose_bone.head), tuple(pose_bone.tail)]
    source = pose_bone.custom_shape_transform or pose_bone
    matrix = np.array(source.matrix, dtype=np.float64) @ _shape_offset(pose_bone)
    points = pick_math.place_points(matrix[None], np.zeros(len(geometry[0]), dtype=np.int64), geometry[0])
    return object_shapes.line_points((points, geometry[1]))


def armature_lines(ob):
    """Line pairs (N x 3, armature space) of what Blender draws for an armature's visible bones, for the hover glow
    of the armature object (never its box)."""
    if ob.pose is None:
        return np.empty((0, 3), dtype=np.float32)
    lines = [np.asarray(bone_display_lines(pose_bone), dtype=np.float32).reshape(-1, 3)
             for pose_bone in ob.pose.bones if _bone_visible(pose_bone)]
    return np.vstack(lines) if lines else np.empty((0, 3), dtype=np.float32)


class BoneSegments:
    """World-space pick edges of one armature's visible bones (pick_math.BoneEdges): the custom shape's edges where a
    bone has one, else its segment. Which bones are visible and their shapes are read once (and again when bone
    visibility changes); positions are refreshed with foreach_get when the armature changes (fast on big rigs: no
    per-bone Python per refresh)."""

    def __init__(self, ob):
        self.visibility = _visibility_key(ob)
        pose_bones = ob.pose.bones
        index_of = {pose_bone.name: index for index, pose_bone in enumerate(pose_bones)}
        visible = [index for index, pose_bone in enumerate(pose_bones) if _bone_visible(pose_bone)]
        self.names = [pose_bones[index].name for index in visible]
        plain, sources, offsets, local, point_owner, edge_from, edge_to, owners, is_shape = [], [], [], [], [], [], [], [], []
        plain_count = sum(1 for index in visible if not self._geometry(pose_bones[index]))
        point_base = 2 * plain_count          # combined points: plain heads, plain tails, then shape points
        for position, index in enumerate(visible):
            pose_bone = pose_bones[index]
            geometry = self._geometry(pose_bone)
            if geometry is None:
                edge_from.append(len(plain))
                edge_to.append(plain_count + len(plain))
                plain.append(index)
                owners.append(position)
                is_shape.append(False)
                continue
            points, edges = geometry
            transform = pose_bone.custom_shape_transform
            sources.append(index_of.get(transform.name, index) if transform else index)
            offsets.append(_shape_offset(pose_bone))
            first = point_base + len(point_owner)
            local.append(points)
            point_owner += [len(sources) - 1] * len(points)
            edge_from += (edges[:, 0] + first).tolist()
            edge_to += (edges[:, 1] + first).tolist()
            owners += [position] * len(edges)
            is_shape += [True] * len(edges)
        self.plain = np.array(plain, dtype=np.int64)
        self.sources = np.array(sources, dtype=np.int64)
        self.offsets = np.array(offsets).reshape(-1, 4, 4)
        self.local = np.vstack(local) if local else np.empty((0, 3))
        self.point_owner = np.array(point_owner, dtype=np.int64)
        self.edge_from, self.edge_to = np.array(edge_from, dtype=np.int64), np.array(edge_to, dtype=np.int64)
        self.owners, self.is_shape = np.array(owners, dtype=np.int64), np.array(is_shape, dtype=bool)
        self.update_positions(ob)

    @staticmethod
    def _geometry(pose_bone):
        return object_shapes.shape_geometry(pose_bone.custom_shape) if pose_bone.custom_shape else None

    def update_positions(self, ob):
        count = len(ob.pose.bones)
        world = np.array(ob.matrix_world, dtype=np.float64)
        parts = []
        if len(self.plain):
            heads, tails = np.empty(count * 3), np.empty(count * 3)
            ob.pose.bones.foreach_get("head", heads)
            ob.pose.bones.foreach_get("tail", tails)
            for points in (heads, tails):
                parts.append(points.reshape(-1, 3)[self.plain] @ world[:3, :3].T + world[:3, 3])
        if len(self.sources):
            flat = np.empty(count * 16)
            ob.pose.bones.foreach_get("matrix", flat)            # column-major per bone
            pose_matrices = flat.reshape(-1, 4, 4).transpose(0, 2, 1)[self.sources]
            matrices = pick_math.display_matrices(world, pose_matrices, self.offsets)
            parts.append(pick_math.place_points(matrices, self.point_owner, self.local))
        points = np.vstack(parts) if parts else np.empty((0, 3))
        starts, ends = points[self.edge_from], points[self.edge_to]
        offset = ends - starts
        lengths = np.sqrt(np.einsum('ij,ij->i', offset, offset))
        touch_reach = np.where(self.is_shape, pick_math.SHAPE_TOUCH_REACH, pick_math.BONE_REACH_FACTOR * lengths)
        laser_reach = np.where(self.is_shape, pick_math.LASER_SHAPE_RADIUS,
                               pick_math.LASER_BONE_RADIUS + pick_math.LASER_BONE_FACTOR * lengths)
        self.segments = pick_math.BoneEdges(starts, ends, self.owners, touch_reach, laser_reach)
        self.reach = float(max(touch_reach.max(), laser_reach.max())) if len(lengths) else 0.0
        self.centre, radius = pick_math.bounding_sphere(points)
        self.radius = radius + self.reach   # every edge's reach lies inside: skip the armature when far

    def near_ray(self, origin, direction, length):
        return bool(self.names) and pick_math.ray_near_sphere(origin, direction, self.centre, self.radius, length)

    def near_point(self, point, margin):
        return bool(self.names) and pick_math.point_near_sphere(point, self.centre, self.radius + margin)


def _visibility_key(ob):
    """Cheap fingerprint of what can be picked on an armature: pose hide + hide_select flags, bone collection
    visibility, custom shapes. A change rebuilds its BoneSegments."""
    count = len(ob.pose.bones)
    hidden, unselectable = np.zeros(count, dtype=bool), np.zeros(count, dtype=bool)
    ob.pose.bones.foreach_get("hide", hidden)
    ob.data.bones.foreach_get("hide_select", unselectable)
    collections = tuple(getattr(c, "is_visible_effectively", c.is_visible) for c in ob.data.collections_all)
    return hidden.tobytes(), unselectable.tobytes(), collections


class ObjectEdges:
    """World-space pick edges of the line-shaped objects (pick_math.BoneEdges, one owner per object: its line shape,
    and a collection instance's parts without a surface). Rebuilt when any of them changes (usually a few dozen
    objects of a few dozen edges each)."""

    def __init__(self, names, shapes):
        self.names = names
        starts, ends, owners = [np.empty((0, 3))], [np.empty((0, 3))], [np.empty(0, dtype=np.int64)]
        for owner, parts in enumerate(shapes):
            for points, edges, world in parts:
                placed = shape_math.place(world, points)
                starts.append(placed[edges[:, 0]])
                ends.append(placed[edges[:, 1]])
                owners.append(np.full(len(edges), owner, dtype=np.int64))
        owners = np.concatenate(owners)
        self.segments = pick_math.BoneEdges(np.vstack(starts), np.vstack(ends), owners, np.zeros(len(owners)),
                                            np.full(len(owners), pick_math.LASER_SHAPE_RADIUS))


class SceneCache:
    """What can be picked, refreshed per changed object: world boxes + surfaces (objects with faces, collection
    instances), line shapes (ObjectEdges) and bone segments of armatures."""

    def __init__(self):
        self.clear()

    def clear(self):
        object_shapes.clear()    # evaluated geometry may have changed (undo / load)
        self.boxes = {}          # owner name_full -> (min, max) of its surfaces: a cheap distance pre-test only
        self.surfaces = {}       # owner name_full -> [(object with the surface, matrix to the owner's space or None)]
        self.lines = {}          # owner name_full -> [(local points, edges, world matrix)] of its line shapes
        self.part_owners = {}    # instanced object name_full -> {names of the collection instances showing it}
        self.bones = {}          # armature name_full -> BoneSegments
        self.changed = set()     # object names the depsgraph reported since the last refresh
        self.stale_bones = set()  # armatures whose bone positions must be re-read
        self._box_arrays = None
        self._edges = None       # ObjectEdges of the current line-shaped objects
        self._pose_key, self._pose_list = None, []
        self.all_dirty = True
        self.objects = None      # pickable objects (visible, selectable, in the workspace), None = rebuild
        self.workspace_key = None  # what the workspace filter was read for (workspace.key)
        self.by_name = {}
        self.everything = []     # every visible, pickable object whatever the workspace: what things are PLACED on
        self.surface_by_name = {}
        self.armatures = []
        self.fresh = False       # boxes / bones built for the current object list
        self.version = getattr(self, "version", 0) + 1   # bumped on every change: drawing caches compare it

    def mark_changed(self, names):
        self.changed.update(names)
        self.objects = None      # visibility or the object list may have changed too
        self.version += 1

    def pickable_objects(self, scene, view_layer):
        """The objects a pick may act on: pickable AND in the workspace (kept as refs until anything changes; all refs drop on
        undo / load). THE split of the workspace: this list is what you select, grab and aim tools at; `everything` (and the
        Picker's `placing` mode) is what things are put ONTO (tool gun Place, snapping): the stage still counts there."""
        workspace_key = workspace.key(scene)
        if self.all_dirty or self.objects is None or workspace_key != self.workspace_key:
            hidden = settings.get("display_hidden")      # Display tab: types the VR view hides can't be picked
            allowed = workspace.member_names(scene, refresh=True)     # the workspace and locks: the one place that filters picks
            self.workspace_key = workspace_key
            self.everything = [ob for ob in scene.objects if pickable(ob, view_layer)
                               and not (hidden and ob.instance_type != 'COLLECTION' and display_types.hides_type(hidden, ob.type))]
            self.surface_by_name = {ob.name_full: ob for ob in self.everything}
            self.objects = self.everything if allowed is None else [ob for ob in self.everything if ob.name_full in allowed]
            # (an Empty showing a collection, e.g. a character from the asset library, stays pickable: you still see it)
            self.by_name = {ob.name_full: ob for ob in self.objects}
            self.armatures = [ob for ob in self.objects if ob.type == 'ARMATURE']
            self.fresh = False
        return self.objects

    def _refresh(self, objects):
        if not self.all_dirty and not self.changed and getattr(self, "fresh", False):
            return                       # nothing changed since the last refresh: boxes and bones are current
        self.fresh = True
        self._box_arrays = None
        if self.all_dirty:
            self.version += 1            # e.g. after a drag: the hover glow batches (overlay) are stale too
            for table in (self.boxes, self.surfaces, self.lines, self.part_owners, self.bones):
                table.clear()
            self._edges = None
            object_shapes.clear()        # a pose deforms meshes the grab never named: their outlines must be read again
            self.all_dirty = False
            self.changed.clear()
        else:
            owners = set(self.changed)
            for name in self.changed:
                owners.update(self.part_owners.get(name, ()))    # an instanced object changed: its instances too
                self.stale_bones.add(name)
            object_shapes.forget(self.changed)
            for name in owners:
                self.boxes.pop(name, None)
                self.surfaces.pop(name, None)
                if self.lines.pop(name, None) is not None:
                    self._edges = None
            self.changed.clear()
        for ob in self.everything:       # (the tables cover every pickable object: a Picker keeps to `by_name`)
            name = ob.name_full
            if ob.type == 'ARMATURE':
                if name not in self.bones:
                    self.bones[name] = BoneSegments(ob)
                elif name in self.stale_bones:
                    if self.bones[name].visibility != _visibility_key(ob):
                        self.bones[name] = BoneSegments(ob)     # a bone was hidden / shown: new pick list
                    else:
                        self.bones[name].update_positions(ob)
            elif name not in self.surfaces and name not in self.lines:
                self._add(ob)
        self.stale_bones.clear()
        line_names = [ob.name_full for ob in objects if ob.name_full in self.lines]
        if self._edges is None or self._edges.names != line_names:
            self._edges = ObjectEdges(line_names, [self.lines[name] for name in line_names])

    def _add(self, ob):
        """Sort one object: surface (box + closest point / ray), line shape, or both for a collection instance."""
        name, world = ob.name_full, ob.matrix_world
        parts = object_shapes.instance_parts(ob)
        if not parts:
            if object_shapes.has_surface(ob):
                self.surfaces[name] = [(ob, None)]
                self.boxes[name] = pick_math.world_box([world @ Vector(corner) for corner in ob.bound_box])
            else:
                self.lines[name] = [(*object_shapes.line_shape(ob), np.array(world))]
            return
        lines, surfaces, corners = [(*object_shapes.line_shape(ob), np.array(world))], [], []
        for part, relative in parts:
            self.part_owners.setdefault(part.name_full, set()).add(name)
            if object_shapes.has_surface(part):
                surfaces.append((part, relative))
                corners += [world @ relative @ Vector(corner) for corner in part.bound_box]
            else:
                lines.append((*object_shapes.line_shape(part), np.array(world @ relative)))
        self.lines[name] = lines
        if surfaces:
            self.surfaces[name] = surfaces
            self.boxes[name] = pick_math.world_box(corners)

    def object_edges(self):
        return self._edges

    def pose_armatures(self, mode):
        """Armatures in Pose mode, cached until anything changes or the mode does."""
        key = (self.version, mode)
        if self._pose_key != key:
            self._pose_key, self._pose_list = key, [ob for ob in self.armatures if ob.mode == 'POSE']
        return self._pose_list

    def segments(self, ob):
        return self.bones.get(ob.name_full)

    def box_arrays(self):
        """(names, min array, max array) of all surface boxes, rebuilt only when the boxes changed."""
        if self._box_arrays is None:
            names = list(self.boxes)
            self._box_arrays = (names, [tuple(self.boxes[name][0]) for name in names],
                                [tuple(self.boxes[name][1]) for name in names])
        return self._box_arrays


class Picker:
    """Picks for one context (scene + view layer): laser and touch, for objects or for pose bones. `placing`: `surface_hit`
    meets every pickable object, not only the workspace's (what a thing is put onto, not what you act on)."""

    def __init__(self, context, cache, placing=False):
        self.context = context
        self.cache = cache
        self.placing = placing
        self.objects = cache.pickable_objects(context.scene, context.view_layer)
        cache._refresh(self.objects)

    # ----- pose bones (armatures in Pose mode) -----

    def _pose_armatures(self):
        return self.cache.pose_armatures(self.context.mode)

    def _best_bone(self, hit_for):
        best = None
        for ob in self._pose_armatures():
            segments = self.cache.segments(ob)
            if not segments or not segments.names:
                continue
            hit = hit_for(segments)
            if hit and (best is None or hit[1] < best.distance):
                best = Target(BONE, ob.name_full, segments.names[hit[0]], is_linked(ob), hit[1])
        return best

    def laser_bone(self, origin, direction, length):
        return self._best_bone(lambda seg: seg.near_ray(origin, direction, length)
                               and seg.segments.laser(origin, direction, length))

    def touch_bone(self, point, touch_distance):
        return self._best_bone(lambda seg: seg.near_point(point, touch_distance)
                               and seg.segments.nearest_touched(point, touch_distance))

    # ----- objects -----

    def _target(self, ob, distance):
        return Target(OBJECT, ob.name_full, linked=is_linked(ob), distance=distance)

    def _surface_owner(self, hit_ob, matrix):
        """The pickable object a ray hit shows: the object itself, or the collection instance whose instanced copy
        was hit (told apart by the hit's matrix). None: not pickable (hide_select, ...): the ray goes on."""
        ob = hit_ob.original
        name, surfaces = ob.name_full, self.cache.surfaces
        by_name = self.cache.surface_by_name if self.placing else self.cache.by_name
        if name in by_name and name in surfaces and object_shapes.same_matrix(matrix, ob.matrix_world):
            return ob
        for owner_name in self.cache.part_owners.get(name, ()):
            owner = by_name.get(owner_name)
            for part, relative in surfaces.get(owner_name, ()) if owner is not None else ():
                if part == ob and object_shapes.same_matrix(matrix, owner.matrix_world @ relative):
                    return owner
        return None

    def surface_hit(self, origin, direction, length, skip=(), skips=RAY_SKIPS):
        """First pickable surface along a ray (real geometry: scene.ray_cast) as a SurfaceHit, passing through
        unpickable ones and the objects named in `skip`."""
        depsgraph = self.context.evaluated_depsgraph_get()
        origin, direction = Vector(origin), Vector(direction)
        start = origin
        for _skip in range(skips):
            remaining = length - (start - origin).length
            if remaining <= 0:
                return None
            hit, location, normal, face, hit_ob, matrix = self.context.scene.ray_cast(
                depsgraph, start, direction, distance=remaining)
            if not hit or hit_ob is None:
                return None
            owner = self._surface_owner(hit_ob, matrix)
            if owner is not None and owner.name_full not in skip:
                return SurfaceHit(owner, hit_ob, location, -normal if normal.dot(direction) > 0.0 else normal, face)
            start = location + direction * 1e-4
        return None

    def _laser_surface(self, origin, direction, length):
        found = self.surface_hit(origin, direction, length)
        return found and self._target(found.owner, (found.location - Vector(origin)).length)

    def _laser_lines(self, origin, direction, length):
        """Nearest bone (armatures, Object mode) or object line (curves, empties, ...) along the laser."""
        candidates = []
        for ob in self.cache.armatures:
            segments = self.cache.segments(ob)
            bone_hit = segments and segments.near_ray(origin, direction, length) \
                and segments.segments.laser(origin, direction, length)
            if bone_hit:
                candidates.append(self._target(ob, bone_hit[1]))
        edges = self.cache.object_edges()
        line_hit = edges.segments.laser(origin, direction, length) if edges else None
        if line_hit and edges.names[line_hit[0]] in self.cache.by_name:
            candidates.append(self._target(self.cache.by_name[edges.names[line_hit[0]]], line_hit[1]))
        return nearest(*candidates)

    def laser_object(self, origin, direction, length):
        return nearest(self._laser_surface(origin, direction, length), self._laser_lines(origin, direction, length))

    def _touch_surface(self, point, touch_distance):
        """Nearest real surface within touch_distance of the hand (inside a box is not a hit)."""
        point = Vector(point)
        by_name = self.cache.by_name
        best = None
        names, box_min, box_max = self.cache.box_arrays()
        if names:
            depsgraph = self.context.evaluated_depsgraph_get()
            for index in pick_math.box_candidates(point, box_min, box_max, touch_distance):
                owner = by_name.get(names[index])
                for part, relative in self.cache.surfaces.get(names[index], ()) if owner is not None else ():
                    world = owner.matrix_world if relative is None else owner.matrix_world @ relative
                    scale = min(abs(value) for value in world.to_scale()) or 1.0
                    found, location, _normal, _face = part.closest_point_on_mesh(
                        world.inverted_safe() @ point, distance=touch_distance / scale, depsgraph=depsgraph)
                    gap = (world @ location - point).length if found else None
                    if found and gap <= touch_distance and (best is None or gap < best.distance):
                        best = self._target(owner, gap)
        return best

    def _touch_lines(self, point, touch_distance):
        """Nearest bone (armatures, Object mode) or object line within touch_distance of the hand."""
        by_name = self.cache.by_name
        candidates = []
        for ob in self.cache.armatures:
            segments = self.cache.segments(ob)
            bone_hit = segments and segments.near_point(point, touch_distance) \
                and segments.segments.nearest_touched(point, touch_distance)
            if bone_hit:
                candidates.append(self._target(ob, max(0.0, bone_hit[1] + touch_distance)))
        edges = self.cache.object_edges()
        line_hit = edges.segments.nearest_touched(point, touch_distance) if edges else None
        if line_hit and edges.names[line_hit[0]] in by_name:
            candidates.append(self._target(by_name[edges.names[line_hit[0]]], max(0.0, line_hit[1] + touch_distance)))
        return nearest(*(target for target in candidates if target.distance <= touch_distance))

    def touch_object(self, point, touch_distance):
        """Nearest real surface or line within touch_distance of the hand (inside a box is not a hit)."""
        return nearest(self._touch_surface(point, touch_distance), self._touch_lines(point, touch_distance))

    def laser_part(self, part, pose_mode, origin, direction, length):
        """One part of a laser pick (hover spreads a pick over ticks in busy scenes): SURFACE or LINES in Object
        mode; Pose mode has one part (WHOLE)."""
        if pose_mode:
            return self.laser_bone(origin, direction, length)
        return (self._laser_surface if part == SURFACE else self._laser_lines)(origin, direction, length)

    def touch_part(self, part, pose_mode, point, touch_distance):
        if pose_mode:
            return self.touch_bone(point, touch_distance)
        return (self._touch_surface if part == SURFACE else self._touch_lines)(point, touch_distance)

    # ----- one entry point for the tools -----

    def laser(self, pose_mode, origin, direction, length):
        return self.laser_bone(origin, direction, length) if pose_mode else self.laser_object(origin, direction, length)

    def touch(self, pose_mode, point, touch_distance):
        return self.touch_bone(point, touch_distance) if pose_mode else self.touch_object(point, touch_distance)
