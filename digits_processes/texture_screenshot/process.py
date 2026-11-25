# SPDX-License-Identifier: GPL-3.0-or-later
"""The Make Object Texture Data Screenshot run (the operator and the tests call run()):

1. Build a temporary Texture Studio scene (scene_setup.add_studio_scene) and put the target in it.
2. Capture the maps with the studio's own capture (Cycles), under a context override: the window stays put.
3. Remove the studio scene and every datablock it added (temp_data), also after an error.
4. Glass is see-through: capture again with the glass clear and combine (glass_alpha).
5. Load the maps as images (relative paths, or packed), then add the decal (decal_step); with Front + Back the
   same decal shows the back shot from behind (back maps, chosen by Backfacing).
Nothing of the studio is copied here: it all comes from Digit's Assorted Tools (assorted_tools).
"""
import os
import shutil
import tempfile
from dataclasses import dataclass, field

import bpy
from mathutils import Vector

from .. import assorted_tools, temp_data
from . import decal_step, glass_alpha, map_sets
from .save_paths import SavePlan

SUBJECT_COLLECTION = "Screenshot Subject"   # holds an object target inside the temporary studio
DECAL_GAP = 0.1                             # gap beside the target, as a fraction of the decal's width


@dataclass
class Job:
    target: object                 # a bpy Object or Collection
    maps: list                     # studio map names (map_sets.studio_maps)
    colour_maps: list              # the Map Set's colour maps (win the decal's COLOR role)
    save: SavePlan
    front_and_back: bool = False
    resolution: int = 1024
    add_decal: bool = True
    facing: str = decal_step.FRONT_FACING   # world axis the front decal faces (or Custom); with Front + Back its back shows the back shot
    custom_facing: tuple = decal_step.DEFAULT_CUSTOM   # the direction Custom faces
    see_through: object = None     # None = off; 0..1 = how clear glass is on the decal (glass_alpha)
    notes: list = field(default_factory=list)   # lines for the user from making the job (a skipped Glow)

    def loaded_maps(self):
        """The maps loaded as images: the studio's, plus the combined alpha when glass is see-through."""
        return self.maps + ([glass_alpha.ALPHA_MAP] if self.see_through is not None else [])


@dataclass
class Result:
    lines: list = field(default_factory=list)     # the studio's report
    images: list = field(default_factory=list)    # (shot, map name, image)
    decals: list = field(default_factory=list)    # the decal (one, also with Front + Back)
    notes: list = field(default_factory=list)     # short lines for the user
    removed: list = field(default_factory=list)   # temporary datablocks removed


def target_objects(target):
    if isinstance(target, bpy.types.Collection):
        return list(target.all_objects)
    return [target, *target.children_recursive]


def _tree_has(tree, seen, node_test):
    """True when a node tree (or a group in it) has a node that passes node_test."""
    for node in tree.nodes:
        if node_test(node):
            return True
        group = getattr(node, "node_tree", None)
        if group is not None and group not in seen:
            seen.add(group)
            if _tree_has(group, seen, node_test):
                return True
    return False


def _node_glows(node):
    if node.bl_idname == "ShaderNodeEmission":
        return True
    if node.bl_idname == "ShaderNodeBsdfPrincipled":
        strength, colour = node.inputs["Emission Strength"], node.inputs["Emission Color"]
        return (strength.is_linked or strength.default_value > 0) and (
            colour.is_linked or any(channel > 0 for channel in colour.default_value[:3]))
    return False


def target_has_node(target, node_test):
    """True when any material of the target has a node passing node_test (cheap node scan; run time only)."""
    seen = set()
    for ob in target_objects(target):
        for slot in getattr(ob, "material_slots", []):
            material = slot.material
            if material and material.node_tree and _tree_has(material.node_tree, seen, node_test):
                return True
    return False


def target_glows(target):
    return target_has_node(target, _node_glows)


def target_transmissive(target):
    """True when any material of the target is glass (a Principled BSDF with Transmission)."""
    return target_has_node(target, glass_alpha.has_transmission)


def put_subject(scene, scene_setup, target):
    """Make the target the studio's subject: a collection is linked as is, an object (and its children) goes into
    a temporary collection of the studio scene."""
    if isinstance(target, bpy.types.Collection):
        scene_setup.link_existing_subject(scene, target)
        return
    holder = bpy.data.collections.new(SUBJECT_COLLECTION)
    scene.collection.children.link(holder)
    for ob in target_objects(target):
        holder.objects.link(ob)
    scene.texture_studio.subject_collection = None
    scene.texture_studio.subject_object = target


def set_options(settings, job, map_names, samples=None):
    for name in map_names:
        setattr(settings, "map_" + name, name in job.maps)
    settings.orthographic = True   # true size for the decal; Front + Back needs it too
    settings.front_and_back = job.front_and_back
    settings.resolution = job.resolution
    if samples:
        settings.samples = samples


def captured_size(scene):
    """(width, height) in metres of the last framed shot (orthographic)."""
    longest = max(scene.render.resolution_x, scene.render.resolution_y)
    scale = scene.camera.data.ortho_scale
    return scale * scene.render.resolution_x / longest, scale * scene.render.resolution_y / longest


def capture(context, job, folder, library_dir=None, samples=None, dry_run=False, log=print, removed=None,
            hide_glass=False):
    """Steps 1-3. Returns (studio report lines, captured size). hide_glass: the under-glass capture (glass_alpha)."""
    scene_setup = assorted_tools.module("texture_studio.scene_setup", context)
    studio = assorted_tools.module("texture_studio.studio", context)
    studio_maps = assorted_tools.module("texture_studio.maps", context)
    with temp_data.temporary_data(removed):
        scene = scene_setup.add_studio_scene(library_dir)
        put_subject(scene, scene_setup, job.target)
        set_options(scene.texture_studio, job, studio_maps.MAP_NAMES, samples)
        materials = [slot.material for ob in target_objects(job.target) for slot in getattr(ob, "material_slots", [])]
        with context.temp_override(scene=scene, view_layer=scene.view_layers[0]), \
                glass_alpha.glass_hidden(materials if hide_glass else []):
            lines = studio.capture(scene, out_dir=folder or None, dry_run=dry_run, log=log)
        size = None if dry_run else captured_size(scene)
    return lines, size


def shot_folders(folder, front_and_back):
    """[(shot, folder)] as the studio writes them: <folder>/front and /back, or just <folder>."""
    if front_and_back:
        return [(shot, os.path.join(folder, shot)) for shot in ("front", "back")]
    return [("front", folder)]


def load_images(context, job, folder):
    """Load every written map as an image (data maps as Non-Color). Returns ([(shot, map, image, path)], notes)."""
    studio_maps = assorted_tools.module("texture_studio.maps", context)
    loaded, notes = [], []
    for shot, directory in shot_folders(folder, job.front_and_back):
        for name in job.loaded_maps():
            path = os.path.join(directory, name + ".png")
            if not os.path.isfile(path):
                notes.append(f"Missing map: {name} ({shot})")
                continue
            image = bpy.data.images.load(path, check_existing=True)
            image.reload()   # a re-run overwrote the file of an image loaded before
            image.name = f"{job.target.name} {name}" if shot == "front" else f"{job.target.name} {shot} {name}"
            if name == glass_alpha.ALPHA_MAP or studio_maps.MAP_BY_NAME[name]["colors"] == "raw":
                image.colorspace_settings.is_data = True
            if job.save.relative:
                image.filepath = bpy.path.relpath(path)
            loaded.append((shot, name, image, path))
    return loaded, notes


def decal_location(context, target, width):
    """Beside the target: right of its bounds (+X), centred on its height and depth."""
    studio = assorted_tools.module("texture_studio.studio", context)
    objects = [ob for ob in target_objects(target) if ob.type in studio.RENDERABLE]
    if not objects:
        return Vector((0.0, 0.0, 0.0))
    low, high = studio.bounds(objects, context.evaluated_depsgraph_get())
    centre = (low + high) / 2
    return Vector((high.x + width * (0.5 + DECAL_GAP), centre.y, centre.z))


def shot_decal_maps(job, loaded, shot):
    roles = map_sets.decal_roles(job.maps, job.colour_maps)
    if job.see_through is not None:
        roles["ALPHA"] = glass_alpha.ALPHA_MAP   # the combined alpha replaces the plain mask
    paths = {name: path for each_shot, name, _image, path in loaded if each_shot == shot}
    return {role: paths[name] for role, name in roles.items() if name in paths}


def add_decals(context, job, loaded, size):
    """The decal beside the target. With Front + Back it is ONE decal: the front shot from the front, the back shot
    (mirrored by the studio to line up with the front) from behind. Returns (decals, notes)."""
    location = decal_location(context, job.target, size[0])
    shading = map_sets.decal_shading(job.colour_maps)
    facing = decal_step.resolved(job.facing, job.custom_facing)
    back = shot_decal_maps(job, loaded, "back") if job.front_and_back else None
    decal, note = decal_step.add_decal(shot_decal_maps(job, loaded, "front"), job.target.name, location, size,
                                       context, facing, shading=shading, back_maps=back or None)
    return ([decal] if decal else []), [note]


def see_through_glass(context, job, folder, library_dir, samples, removed):
    """Capture again with the glass clear (a temporary folder), then write alpha.png and mix the maps per shot."""
    studio_maps = assorted_tools.module("texture_studio.maps", context)
    blended = {name: studio_maps.MAP_BY_NAME[name]["colors"] == "raw" for name in job.maps
               if name not in glass_alpha.HELPER_MAPS}
    under_root = tempfile.mkdtemp(prefix="digits_processes_glass_")
    try:
        capture(context, job, under_root, library_dir, samples, log=lambda *_: None, removed=removed, hide_glass=True)
        for (_shot, directory), (_same, under) in zip(shot_folders(folder, job.front_and_back),
                                                      shot_folders(under_root, job.front_and_back)):
            glass_alpha.write_alpha(directory, job.see_through, under)
            glass_alpha.blend_maps(directory, under, job.see_through, blended)
    finally:
        shutil.rmtree(under_root, ignore_errors=True)


def run(context, job, library_dir=None, samples=None, dry_run=False, log=print):
    """The whole process. library_dir / samples are for tests (rig .blend folder, Cycles samples)."""
    if context.mode != 'OBJECT':
        raise ValueError("Switch to Object Mode first")
    result = Result(notes=list(job.notes))
    temporary_folder = tempfile.mkdtemp(prefix="digits_processes_") if job.save.pack and not dry_run else ""
    folder = temporary_folder or job.save.folder
    try:
        result.lines, size = capture(context, job, folder, library_dir, samples, dry_run, log, result.removed)
        if dry_run:
            return result
        if job.see_through is not None:
            see_through_glass(context, job, folder, library_dir, samples, result.removed)
        loaded, load_notes = load_images(context, job, folder)
        result.notes += load_notes
        result.images = [(shot, name, image) for shot, name, image, _path in loaded]
        if job.add_decal and loaded:
            result.decals, notes = add_decals(context, job, loaded, size)
            result.notes += notes
        if job.save.pack:
            for _shot, _name, image in result.images:
                image.pack()
            result.notes.insert(0, f"Packed {len(result.images)} images into the .blend")
        else:
            result.notes.insert(0, f"Saved {len(result.images)} images to {folder}")
        if job.save.note:
            result.notes.append(job.save.note)
        return result
    finally:
        if temporary_folder:
            shutil.rmtree(temporary_folder, ignore_errors=True)
