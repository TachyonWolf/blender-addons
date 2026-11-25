"""Texture Studio scene setup: make a studio scene (stage, render settings, world, compositor) and put a
character into it. The one place that builds a studio: "Add Studio to This File", Add Character and the
headless build_studio.py all call it, so a studio made any way is the same.

A studio scene carries the marker scene.texture_studio.is_studio; the sidebar panel's poll reads only that.
"""
import os

import bpy

from .. import camera_rig, camera_rig_spec, character_link, light_rig, light_rig_spec, render_settings, rig_common
from ..modifier_setup import library_file  # generated copy
from . import compositor, settings

SCENE_NAME = "Texture Studio"
STAGE_NAME = "Stage"
LIGHT_PRESET = "Toon Flat"  # soft key, fill ratio 1.5: even light, so matte stays flat
SAMPLES = 1024
BACKGROUND = (0.05, 0.05, 0.05, 1.0)
# What glass (a visor) reflects and refracts: a neutral grey sweep, seen only by glossy and transmission rays.
# Diffuse light stays the dark BACKGROUND, so matte keeps the flat Toon Flat light. Without it glass shows the near
# black world and reads as a hole in beauty and matte.
GLASS_BACKDROP = (0.5, 0.5, 0.5, 1.0)


def is_studio_scene(scene):
    """Cheap: one property read. The panel poll uses this."""
    studio = getattr(scene, "texture_studio", None)
    return bool(studio and studio.is_studio)


def find_studio_scene(data=None):
    return next((scene for scene in (data or bpy.data).scenes if is_studio_scene(scene)), None)


def library_path(filename, library_dir=None):
    """A rig's .blend: in library_dir when given (headless builds), else in the bundled assets / asset libraries."""
    path = os.path.join(library_dir, filename) if library_dir else library_file(filename)
    if not path or not os.path.exists(path):
        raise ValueError(f"{filename} not found in your asset libraries")
    return path


def build_stage(scene, library_dir=None):
    """Camera Rig (dolly at the origin, no depth of field, scene camera) and Three Point Light (Toon Flat) in a
    "Stage" collection of the scene."""
    context = bpy.context
    stage = bpy.data.collections.new(STAGE_NAME)
    scene.collection.children.link(stage)
    camera_collection = rig_common.append_collection(
        context, library_path(camera_rig_spec.LIBRARY_FILE, library_dir), camera_rig_spec.ASSET_NAME, stage)
    camera = next(ob for ob in camera_collection.objects if ob.type == "CAMERA")
    camera.location = (0.0, 0.0, 0.0)  # the dolly is where the camera is
    camera.data.dof.use_dof = False
    scene.camera = camera
    rig = rig_common.append_rig(context, library_path(light_rig_spec.LIBRARY_FILE, library_dir),
                                light_rig_spec.ASSET_NAME, light_rig_spec.ROOT_TAG, stage)[1]
    light_rig.apply_preset(rig, LIGHT_PRESET)


def set_render_settings(scene):
    """The user's colour and Cycles defaults, Cycles with a transparent film and a dark grey world."""
    notes = []
    render_settings.apply_group("color", scene, notes)
    render_settings.apply_group("cycles", scene, notes)
    scene.render.engine = "CYCLES"
    scene.render.film_transparent = True
    scene.cycles.samples = SAMPLES
    world = bpy.data.worlds.new("Texture Studio World")
    if world.node_tree is None:  # worlds always have nodes in 5.x; older versions need use_nodes
        world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = BACKGROUND
    add_glass_backdrop(world.node_tree)
    scene.world = world


def add_glass_backdrop(tree):
    """World colour = GLASS_BACKDROP for glossy and transmission rays (Light Path), BACKGROUND for the rest."""
    nodes, links = tree.nodes, tree.links
    background = nodes["Background"]
    light_path = nodes.new("ShaderNodeLightPath")
    either = nodes.new("ShaderNodeMath")
    either.operation, either.use_clamp = "ADD", True
    links.new(light_path.outputs["Is Glossy Ray"], either.inputs[0])
    links.new(light_path.outputs["Is Transmission Ray"], either.inputs[1])
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.inputs["A"].default_value, mix.inputs["B"].default_value = BACKGROUND, GLASS_BACKDROP
    links.new(either.outputs[0], mix.inputs["Factor"])
    links.new(mix.outputs["Result"], background.inputs["Color"])


def add_studio_scene(library_dir=None, name=SCENE_NAME):
    """A new scene with the whole studio in it (stage, render settings, passes, compositor), marked as a studio.
    No subject yet. Does not switch the window to it."""
    scene = bpy.data.scenes.new(name)
    try:
        settings.register()
        scene.texture_studio.is_studio = True
        set_render_settings(scene)
        build_stage(scene, library_dir)
        compositor.setup_passes(scene.view_layers[0])
        compositor.build(scene)
    except Exception:
        bpy.data.scenes.remove(scene)  # no half-built studio left in the file
        raise
    return scene


def link_subject(scene, path, collection_name):
    """Link a character collection from its master .blend as a library override (the master is never edited)
    and make it the scene's subject. Returns the override collection."""
    studio = scene.texture_studio
    subject = character_link.link_character(path, collection_name, scene, scene.view_layers[0])
    studio.subject_object = None
    studio.subject_collection = subject
    return subject


def link_existing_subject(scene, collection):
    """Link a collection that is already in this file into the studio scene (the same collection, no copy) and make
    it the subject."""
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    studio = scene.texture_studio
    studio.subject_object = None
    studio.subject_collection = collection
    return collection


_names_cache = {}  # path -> (modified time, items): the file is read again only when it changes


def character_collection_items(path):
    """Enum items (id, name, description) for the collections of the .blend at `path`; empty without a valid file.
    Reads only the name lists (nothing is loaded)."""
    path = bpy.path.abspath(path)
    if not path.lower().endswith(".blend") or not os.path.isfile(path):
        return [("", "(pick a .blend file)", "")]
    stamp = os.path.getmtime(path)
    if _names_cache.get(path, (None,))[0] != stamp:
        with bpy.data.libraries.load(path, link=True) as (source, _target):
            names = sorted(source.collections)
        _names_cache[path] = (stamp, [(name, name, "") for name in names] or [("", "(no collections)", "")])
    return _names_cache[path][1]
