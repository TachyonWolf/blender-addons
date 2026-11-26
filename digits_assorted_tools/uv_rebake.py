# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/uv_rebake.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""UV Rebake core: carry image textures from one UV map to another so seams and islands can move.

Each image is rebaked on its own, as flat colour, so the node setup stays the same and everything derived from an image
(masks, metallic, glow through colour ramps) follows it. All the parts on one image are baked together, from a throwaway
mesh at render subdivision, so the user's objects and materials are not touched until the images are swapped in.

    textures = find_textures(objects)
    for texture in textures: texture.bake = not texture.tiling
    results = rebake(context, textures, "UVMap", "UVMap_New", Settings(folder="//Baked"))

Parts of it for other bakes: `flat_mesh`, `bake_emission`, `box_down`, `fill_margin`, `save_image`.
"""
import os
from dataclasses import dataclass

import bmesh
import bpy
import numpy as np

from .object_tools import free_path

TILING_GROUPS = ("Hexes",)      # images inside these node groups are patterns, not painted textures
SOURCE_LAYER, TARGET_LAYER = "rebake_source", "rebake_target"
STAMP_RADIUS = 4                # final pixels of colour kept around a collapsed flat-colour face


class RebakeError(Exception):
    """A job that must stop; the message says why and what to do."""


@dataclass
class Settings:
    size: int = 0               # output pixels on the long side; 0 = same as each image
    supersample: int = 2        # bake this many times bigger, then scale down
    margin: int = 16            # final pixels of colour pushed past island edges
    sharp: bool = True          # read images Closest, so a whole-pixel island move copies its pixels exactly
    folder: str = "//"
    suffix: str = ""            # output name ending; empty = the target UV name
    copy_missing: bool = False  # parts lacking the target UV get a copy of the source UV instead of stopping
    apply: bool = True          # swap the new images into the materials and make the target UV active


class Texture:
    """One image file as used in materials: its data-blocks, image nodes and the parts (object: material slots) on it."""

    def __init__(self, key, name):
        self.key, self.name = key, name
        self.images, self.nodes = [], []
        self.parts = {}
        self.tiling = False
        self.bake = True

    @property
    def image(self):
        return self.images[0]


# --- finding what to bake --------------------------------------------------------------------

def image_key(image):
    """Same key for data-blocks showing the same file (DigitBody and DigitBody.001)."""
    return os.path.normpath(bpy.path.abspath(image.filepath, library=image.library)) if image.filepath else image.name


def image_nodes(tree, groups=(), seen=None):
    """Every Image Texture node in a node tree and its groups, as (node, names of the groups around it)."""
    seen = set() if seen is None else seen
    if tree is None or tree in seen:
        return
    seen.add(tree)
    for node in tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            yield node, groups
        elif node.type == 'GROUP':
            yield from image_nodes(node.node_tree, groups + (node.node_tree.name if node.node_tree else "",), seen)


def is_tiling(node, groups):
    """A pattern read through its own coordinates, not painted on the UVs: left alone, it just reads the new UV."""
    if any(name.split(".")[0] in TILING_GROUPS for name in groups):
        return True
    links = node.inputs["Vector"].links
    return bool(links) and links[0].from_node.type != 'UVMAP'


def used_slots(mesh):
    counts = np.zeros(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get('material_index', counts)
    return set(np.unique(counts).tolist())


def find_textures(objects):
    """The Textures on the given meshes' faces, each with EVERY mesh in the file that shows it, selected or not:
    a rebaked image is wrong for any part left behind. A material slot no face uses does not count."""
    textures = {}
    for ob in objects:
        for index in used_slots(ob.data):
            material = ob.material_slots[index].material if index < len(ob.material_slots) else None
            if material and material.use_nodes:
                for node, groups in image_nodes(material.node_tree):
                    key = image_key(node.image)
                    texture = textures.setdefault(key, Texture(key, node.image.name))
                    if node.image not in texture.images:
                        texture.images.append(node.image)
                    texture.tiling = texture.tiling or is_tiling(node, groups)
    for ob in bpy.data.objects:
        if ob.type != 'MESH':
            continue
        for index in used_slots(ob.data):
            material = ob.material_slots[index].material if index < len(ob.material_slots) else None
            if not (material and material.use_nodes):
                continue
            for node, _groups in image_nodes(material.node_tree):
                texture = textures.get(image_key(node.image))
                if texture:
                    texture.parts.setdefault(ob, set()).add(index)
                    if node not in texture.nodes:
                        texture.nodes.append(node)
    return sorted(textures.values(), key=lambda t: t.name)


def check_job(textures, source, target, copy_missing=False):
    """Why these textures can't be rebaked, as a message; '' when they can."""
    if source == target:
        return "Source and target UV maps are the same"
    problems = []
    for texture in textures:
        lacking_source = sorted(ob.name for ob in texture.parts if source not in ob.data.uv_layers)
        lacking_target = sorted(ob.name for ob in texture.parts if target not in ob.data.uv_layers)
        if lacking_source:
            problems.append(f"{texture.name}: no UV map '{source}' on {', '.join(lacking_source)}")
        if lacking_target and not copy_missing:
            problems.append(f"{texture.name} is also used by {', '.join(lacking_target)}, which lack UV map '{target}': "
                            "add it there or turn on Copy to Missing Parts")
    return "; ".join(problems)


# --- plain pixel work ------------------------------------------------------------------------

def bake_size(image_size, size, supersample):
    """(final size, baked size), both (width, height). `size` is the long side; 0 keeps the image's own size."""
    width, height = image_size
    if size:
        scale = size / max(width, height)
        width, height = max(1, round(width * scale)), max(1, round(height * scale))
    return (width, height), (width * supersample, height * supersample)


def box_down(rgba, factor):
    """(rgb, covered) of an RGBA float bake at 1/factor size, alpha > 0.5 meaning baked. Each pixel averages only its baked
    samples, so unbaked black never darkens an island's edge."""
    height, width = rgba.shape[0] // factor, rgba.shape[1] // factor
    baked = (rgba[..., 3] > 0.5).astype(np.float32)
    colour = rgba[..., :3] * baked[..., None]
    if factor > 1:
        colour = colour.reshape(height, factor, width, factor, 3).sum(axis=(1, 3))
        baked = baked.reshape(height, factor, width, factor).sum(axis=(1, 3))
    covered = baked > 0
    colour[covered] /= baked[covered][:, None]
    return colour, covered


def fill_margin(channels, covered, pixels):
    """Push colour `pixels` past the covered area, in place. Each new pixel averages its covered neighbours."""
    height, width = covered.shape
    for _ in range(pixels):
        total = np.zeros_like(channels)
        count = np.zeros((height, width), dtype=np.float32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    to_y, from_y = slice(max(dy, 0), height + min(dy, 0)), slice(max(-dy, 0), height + min(-dy, 0))
                    to_x, from_x = slice(max(dx, 0), width + min(dx, 0)), slice(max(-dx, 0), width + min(-dx, 0))
                    mask = covered[from_y, from_x]
                    total[to_y, to_x] += channels[from_y, from_x] * mask[..., None]
                    count[to_y, to_x] += mask
        new = ~covered & (count > 0)
        if not new.any():
            return
        channels[new] = total[new] / count[new][:, None]
        covered |= new


def polygon_area(points):
    """Area of one polygon of 2D points (shoelace), any winding."""
    points = np.asarray(points, dtype=np.float64)
    x, y = points[:, 0], points[:, 1]
    return abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2


def collapsed_points(polygons, source_uvs, target_uvs, size):
    """Faces collapsed on the target map pick one flat colour and get no pixels of their own in a bake. Returns unique
    (source uv, target uv) corners of polygons (lists of loop indices) under one pixel in area, one per target pixel."""
    width, height = size
    points = {}
    for loops in polygons:
        if polygon_area(target_uvs[loops] * (width, height)) < 1:
            for loop in loops:
                pixel = (int(target_uvs[loop][0] * width), int(target_uvs[loop][1] * height))
                points.setdefault(pixel, (tuple(source_uvs[loop]), tuple(target_uvs[loop])))
    return list(points.values())


def output_name(image_name, suffix):
    """File stem of a rebaked image: the source's name without extension or Blender's .001, plus the suffix."""
    stem = image_name
    while True:
        head, ext = os.path.splitext(stem)
        if ext[1:].lower() in ("png", "jpg", "jpeg", "tga", "tif", "tiff", "exr", "bmp", "webp") or ext[1:].isdigit():
            stem = head
        else:
            return f"{stem}_{suffix}"


# --- the bake --------------------------------------------------------------------------------

class bake_scene:
    """Context manager: the scene set up for one-sample Cycles bakes, put back afterwards."""

    def __init__(self, scene):
        self.scene = scene
        self.saved = {}

    def set(self, owner, name, value):
        self.saved[owner, name] = getattr(owner, name)
        setattr(owner, name, value)

    def __enter__(self):
        self.set(self.scene.render, "engine", 'CYCLES')
        self.set(self.scene.render, "use_simplify", False)     # it would shrink textures and subdivision
        self.set(self.scene.cycles, "samples", 1)
        return self.scene

    def __exit__(self, *_exc):
        for (owner, name), value in self.saved.items():
            setattr(owner, name, value)


def render_mesh(context, ob):
    """A new mesh of `ob` with its modifiers at render settings: UVs interpolate exactly as they will in a render."""
    copy = ob.copy()
    context.scene.collection.objects.link(copy)
    try:
        copy.hide_viewport = False
        for modifier in copy.modifiers:
            modifier.show_viewport = modifier.show_render
            if modifier.type in ('SUBSURF', 'MULTIRES'):
                modifier.levels = modifier.render_levels
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        return bpy.data.meshes.new_from_object(copy.evaluated_get(depsgraph), preserve_all_data_layers=True,
                                               depsgraph=depsgraph)
    finally:
        bpy.data.objects.remove(copy)


def keep_part(mesh, slots, source, target):
    """Cut a render mesh down to the faces of `slots` and the two UV maps, under the bake's own layer names."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index not in slots], context='FACES')
    bm.to_mesh(mesh)
    bm.free()
    for layer in [layer for layer in mesh.uv_layers if layer.name not in (source, target)]:
        mesh.uv_layers.remove(layer)
    if source == target:
        mesh.uv_layers.new(name=TARGET_LAYER)
        mesh.uv_layers[0].name = SOURCE_LAYER
        return
    mesh.uv_layers[source].name = SOURCE_LAYER
    mesh.uv_layers[target].name = TARGET_LAYER


def add_stamps(bm, points, size):
    """A small square of target UV per collapsed point, its whole source UV on the point's colour. Added before the real
    faces, so they only show where no island lands."""
    source, target = bm.loops.layers.uv[SOURCE_LAYER], bm.loops.layers.uv[TARGET_LAYER]
    rx, ry = STAMP_RADIUS / size[0], STAMP_RADIUS / size[1]
    for src, dst in points:
        corners = [(dst[0] + dx * rx, dst[1] + dy * ry) for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        face = bm.faces.new([bm.verts.new((x, y, 0.0)) for x, y in corners])
        for loop, corner in zip(face.loops, corners):
            loop[source].uv, loop[target].uv = src, corner


def part_points(ob, slots, source, target, size):
    """collapsed_points of one object's faces in `slots`."""
    mesh = ob.data
    count = len(mesh.loops) * 2
    source_uvs, target_uvs = np.zeros(count, np.float32), np.zeros(count, np.float32)
    mesh.uv_layers[source].uv.foreach_get('vector', source_uvs)
    mesh.uv_layers[target].uv.foreach_get('vector', target_uvs)
    polygons = [list(p.loop_indices) for p in mesh.polygons if p.material_index in slots]
    return collapsed_points(polygons, source_uvs.reshape(-1, 2), target_uvs.reshape(-1, 2), size)


def flat_mesh(context, parts, source, target, size):
    """One throwaway object of all `parts` {object: material slots} at render detail, with the two UV maps under the bake's
    layer names, plus stamps for collapsed faces."""
    bm = bmesh.new()
    bm.loops.layers.uv.new(SOURCE_LAYER)
    bm.loops.layers.uv.new(TARGET_LAYER)
    for ob, slots in parts.items():
        add_stamps(bm, part_points(ob, slots, source, target, size), size)
    for ob, slots in parts.items():
        mesh = render_mesh(context, ob)
        keep_part(mesh, slots, source, target)
        bm.from_mesh(mesh)
        bpy.data.meshes.remove(mesh)
    mesh = bpy.data.meshes.new("rebake_flat")
    bm.to_mesh(mesh)
    bm.free()
    flat = bpy.data.objects.new("rebake_flat", mesh)
    context.scene.collection.objects.link(flat)
    return flat


def emission_material(image, interpolation, extension, socket):
    """Image > Emission through an explicit UV Map node, plus an unlinked, active node that takes the bake."""
    material = bpy.data.materials.new("rebake_flat")
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    uv = nodes.new('ShaderNodeUVMap')
    uv.uv_map = SOURCE_LAYER
    read = nodes.new('ShaderNodeTexImage')
    read.image, read.interpolation, read.extension = image, interpolation, extension
    emit = nodes.new('ShaderNodeEmission')
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(uv.outputs[0], read.inputs["Vector"])
    links.new(read.outputs[socket], emit.inputs["Color"])
    links.new(emit.outputs[0], output.inputs["Surface"])
    write = nodes.new('ShaderNodeTexImage')
    nodes.active = write
    return material, write


def bake_emission(context, flat, material, write_node, size):
    """Bake `flat` with Emit into a new float image of `size`, UVs from its target layer. No margin here: fill_margin does
    it after scaling down. Returns the pixels as a float array, alpha 1 where baked, 0 elsewhere."""
    target = bpy.data.images.new("rebake_target", size[0], size[1], alpha=True, float_buffer=True)
    try:
        write_node.image = target
        flat.data.materials.clear()
        flat.data.materials.append(material)
        for ob in context.selected_objects:
            ob.select_set(False)
        flat.select_set(True)
        context.view_layer.objects.active = flat
        bpy.ops.object.bake(type='EMIT', margin=0, use_clear=True, target='IMAGE_TEXTURES', uv_layer=TARGET_LAYER,
                            use_selected_to_active=False, save_mode='INTERNAL')
        pixels = np.empty(size[0] * size[1] * 4, dtype=np.float32)
        target.pixels.foreach_get(pixels)
        return pixels.reshape(size[1], size[0], 4)
    finally:
        bpy.data.images.remove(target)


def has_alpha(image):
    """True when the image really uses its alpha channel."""
    if image.depth not in (32, 64, 128):
        return False
    pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return float(pixels[3::4].min()) < 1.0


def file_values(rgb, colorspace):
    """Scene-linear `rgb` as they go in an 8-bit file of `colorspace`: sRGB encoded, anything else stored as is."""
    if colorspace != 'sRGB':
        return rgb
    rgb = np.clip(rgb, 0.0, 1.0)
    return np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)


def save_image(name, path, source, rgb, alpha):
    """Write scene-linear `rgb` (+ `alpha` or None) to an 8-bit PNG in the source image's color space; returns it loaded."""
    height, width = rgb.shape[:2]
    pixels = np.ones((height, width, 4), dtype=np.float32)
    pixels[..., :3] = file_values(rgb, source.colorspace_settings.name)
    if alpha is not None:
        pixels[..., 3] = alpha
    image = bpy.data.images.new(name, width, height, alpha=alpha is not None)
    image.pixels.foreach_set(pixels.ravel())
    image.file_format = 'PNG'
    image.filepath_raw = path
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(path)
    image.name = name
    image.colorspace_settings.name = source.colorspace_settings.name
    image.alpha_mode = source.alpha_mode
    return image


def bake_texture(context, texture, source, target, settings, folder):
    """Rebake one Texture; returns the new image (not yet in any material)."""
    image = texture.image
    final, baked = bake_size(image.size, settings.size, settings.supersample)
    node = texture.nodes[0]
    interpolation = 'Closest' if settings.sharp else node.interpolation
    alpha_mode, wants_alpha = image.alpha_mode, has_alpha(image)
    flat = flat_mesh(context, texture.parts, source, target, final)
    materials = []
    try:
        image.alpha_mode = 'CHANNEL_PACKED'     # colour under transparent pixels is kept as painted
        material, write = emission_material(image, interpolation, node.extension, "Color")
        materials.append(material)
        rgb, covered = box_down(bake_emission(context, flat, material, write, baked), settings.supersample)
        fill_margin(rgb, covered.copy(), settings.margin)
        alpha = None
        if wants_alpha:
            material, write = emission_material(image, interpolation, node.extension, "Alpha")
            materials.append(material)
            value, covered = box_down(bake_emission(context, flat, material, write, baked), settings.supersample)
            fill_margin(value, covered.copy(), settings.margin)
            alpha = value[..., 0]
    finally:
        image.alpha_mode = alpha_mode
        mesh = flat.data
        bpy.data.objects.remove(flat)
        bpy.data.meshes.remove(mesh)
        for material in materials:
            bpy.data.materials.remove(material)
    stem = output_name(texture.name, settings.suffix or target)
    return save_image(stem, free_path(folder, stem), image, rgb, alpha)


def apply_rebake(texture, new_image, source, target):
    """Point the texture's nodes at the new image and make the target UV the one parts render and show. The old images get
    a fake user, so going back is one click."""
    for image in texture.images:
        image.use_fake_user = True
    for node in texture.nodes:
        node.image = new_image
    for ob in texture.parts:
        layer = ob.data.uv_layers[target]
        layer.active_render = True
        ob.data.uv_layers.active = layer
    for node in texture.nodes:
        for link in node.inputs["Vector"].links:
            if link.from_node.type == 'UVMAP' and link.from_node.uv_map == source:
                link.from_node.uv_map = target


def rebake(context, textures, source, target, settings):
    """Rebake every texture with .bake set. Returns [(Texture, new image)]; raises RebakeError before baking anything if
    the job can't be done. Tiling images are not baked: they read whatever UV the part renders with."""
    chosen = [t for t in textures if t.bake]
    if not chosen:
        raise RebakeError("No images chosen to bake")
    problem = check_job(chosen, source, target, settings.copy_missing)
    if problem:
        raise RebakeError(problem)
    if not os.path.isdir(folder := bpy.path.abspath(settings.folder)):
        os.makedirs(folder, exist_ok=True)
    for texture in chosen:
        for ob in texture.parts:
            if target not in ob.data.uv_layers:
                ob.data.uv_layers.new(name=target).uv.foreach_set(
                    'vector', uv_values(ob.data, source))
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    results = []
    try:
        with bake_scene(context.scene):
            for texture in chosen:
                results.append((texture, bake_texture(context, texture, source, target, settings, folder)))
    finally:
        for ob in context.selected_objects:
            ob.select_set(False)
        for ob in selected:
            ob.select_set(True)
        context.view_layer.objects.active = active
    if settings.apply:
        for texture, image in results:
            apply_rebake(texture, image, source, target)
    return results


def uv_values(mesh, name):
    values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    mesh.uv_layers[name].uv.foreach_get('vector', values)
    return values
