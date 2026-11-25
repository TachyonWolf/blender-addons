# SPDX-License-Identifier: GPL-3.0-or-later
"""Glass is see-through: you see through the glass to what is behind it ON the character (Digit's face behind her
visor), and only see through the whole decal where nothing of the character is behind the glass.

Two captures line up pixel for pixel (same framing): the normal one, and an "under glass" one with every glass
material swapped for a clear Transparent BSDF (glass_hidden). With g = transmission x see_through:
- alpha.png  = mask x (1 - g) + g x under_mask   (combine; under_mask = 0 gives the old mask x (1 - g))
- each other map = the normal map mixed with the under-glass map by g, premultiplied by coverage (blend_maps), so
  the glass shows the face behind it; written over the normal map file.

The ONE place the combine happens, in numpy on the saved PNGs: nothing is added to the studio's compositor.
"""
import os
from contextlib import contextmanager

import bpy
import numpy as np

ALPHA_MAP = "alpha"           # the combined image's name (file <ALPHA_MAP>.png)
MASK_MAP, TRANSMISSION_MAP = "mask", "transmission"
HELPER_MAPS = [MASK_MAP, TRANSMISSION_MAP]   # studio maps captured to make it
DEFAULT_SEE_THROUGH = 0.8


def combine(mask, transmission, see_through, under_mask=0.0):
    """mask x (1 - g) + g x under_mask with g = transmission x see_through, values 0..1 (numpy arrays of one
    shape). under_mask = the character behind the glass (the under-glass capture's mask)."""
    clear = transmission * see_through
    return np.clip(mask * (1.0 - clear) + clear * under_mask, 0.0, 1.0)


def _read(path, is_data=True):
    """A PNG's pixels as a (height, width, 4) array (data maps read raw)."""
    image = bpy.data.images.load(path)
    try:
        image.colorspace_settings.is_data = is_data
        width, height = image.size
        pixels = np.empty(width * height * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        return pixels.reshape(height, width, 4)
    finally:
        bpy.data.images.remove(image)


def _channel(path):
    """The first channel of a PNG, read raw (data), as a (height, width) array."""
    return _read(path)[:, :, 0]


def _clear_and_under(folder, under_folder, see_through):
    """(g = transmission x see_through, mask, under_mask) of one shot."""
    mask = _channel(os.path.join(folder, MASK_MAP + ".png"))
    clear = _channel(os.path.join(folder, TRANSMISSION_MAP + ".png")) * see_through
    under = os.path.join(under_folder, MASK_MAP + ".png") if under_folder else ""
    return clear, mask, (_channel(under) if under and os.path.isfile(under) else np.zeros_like(mask))


def write_alpha(folder, see_through, under_folder=None):
    """Read <folder>/mask.png + transmission.png (+ <under_folder>/mask.png) and write <folder>/alpha.png.
    Returns the path."""
    clear, mask, under_mask = _clear_and_under(folder, under_folder, see_through)
    alpha = combine(mask, clear, 1.0, under_mask)
    height, width = alpha.shape
    path = os.path.join(folder, ALPHA_MAP + ".png")
    image = bpy.data.images.new("glass_alpha_tmp", width, height, alpha=False, float_buffer=False)
    try:
        image.colorspace_settings.is_data = True
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = alpha[:, :, None]
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()
    finally:
        bpy.data.images.remove(image)
    return path


def blend_maps(folder, under_folder, see_through, maps):
    """Mix each map {name: is_data} of <folder> with the same map of <under_folder> by g (premultiplied by the two
    masks), so glass shows what is behind it; written over <folder>/<name>.png in its own format."""
    clear, mask, under_mask = _clear_and_under(folder, under_folder, see_through)
    keep, show = (1.0 - clear) * mask, clear * under_mask
    weight = (keep + show)[:, :, None]
    for name, is_data in maps.items():
        path, under_path = os.path.join(folder, name + ".png"), os.path.join(under_folder, name + ".png")
        if not (os.path.isfile(path) and os.path.isfile(under_path)):
            continue
        image = bpy.data.images.load(path)
        try:
            image.colorspace_settings.is_data = is_data
            width, height = image.size
            pixels = np.empty(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            pixels = pixels.reshape(height, width, 4)
            under = _read(under_path, is_data)
            mixed = (pixels[:, :, :3] * keep[:, :, None] + under[:, :, :3] * show[:, :, None]) / np.maximum(weight, 1e-6)
            seen = (clear > 0.0)[:, :, None] & (weight > 1e-6)
            pixels[:, :, :3] = np.where(seen, mixed, pixels[:, :, :3])
            image.pixels.foreach_set(pixels.ravel())
            image.save()
        finally:
            bpy.data.images.remove(image)


def _glass_tree(tree, seen):
    """True when a node tree (or a group in it) has a glass Principled BSDF."""
    for node in tree.nodes:
        if has_transmission(node):
            return True
        group = getattr(node, "node_tree", None)
        if group is not None and group not in seen:
            seen.add(group)
            if _glass_tree(group, seen):
                return True
    return False


@contextmanager
def glass_hidden(materials):
    """Each glass material's surface swapped for a clear Transparent BSDF while inside (in memory; put back
    after, also after an error): the under-glass capture sees what is behind the glass."""
    swapped = []
    try:
        for material in {m for m in materials if m and m.node_tree}:
            if not _glass_tree(material.node_tree, set()):
                continue
            output = material.node_tree.get_output_node('CYCLES')
            if output is None or not output.inputs["Surface"].is_linked:
                continue
            old = output.inputs["Surface"].links[0].from_socket
            clear = material.node_tree.nodes.new("ShaderNodeBsdfTransparent")
            material.node_tree.links.new(clear.outputs["BSDF"], output.inputs["Surface"])
            swapped.append((material, output, old, clear))
        yield len(swapped)
    finally:
        for material, output, old, clear in reversed(swapped):
            material.node_tree.links.new(old, output.inputs["Surface"])
            material.node_tree.nodes.remove(clear)


def has_transmission(node):
    """A Principled BSDF whose Transmission Weight is above 0 or linked (the studio copies it via an AOV)."""
    if node.bl_idname != "ShaderNodeBsdfPrincipled":
        return False
    weight = node.inputs["Transmission Weight"]
    return weight.is_linked or weight.default_value > 0
