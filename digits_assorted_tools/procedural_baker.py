# SPDX-License-Identifier: GPL-3.0-or-later
"""Procedural Baker (Digit's Tools > Export): bake the selected objects' procedural materials to game textures
(albedo, normal, glow, roughness, metallic, AO, packed ORM) as PNG files, optionally with a new material that uses them.
Scene property `procedural_baker` and operator `pbake.bake` are kept from the former add-on."""

import os
from typing import NamedTuple

import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from .ui_cards import action_row, hints, prop_group, section, toggles


# key, label, Cycles bake type, colorspace
MAPS = (
    ("albedo", "Albedo", "DIFFUSE", "sRGB"),
    ("normal", "Normal", "NORMAL", "Non-Color"),
    ("glow", "Glow", "EMIT", "sRGB"),
    ("roughness", "Roughness", "ROUGHNESS", "Non-Color"),
    ("metallic", "Metallic", "EMIT", "Non-Color"),  # baked through emission, see route_metallic
    ("ao", "AO", "AO", "Non-Color"),
)

# Maps packed into one ORM texture (R, G, B), the layout Godot and glTF use.
ORM_KEYS = ("ao", "roughness", "metallic")

# Maps that are often all black. They can be skipped then.
SKIP_IF_EMPTY = ("glow", "metallic")

# Principled inputs that hide the base color in the diffuse color pass.
# They are set to 0 while baking albedo, then put back.
ALBEDO_ZERO_INPUTS = ("Metallic", "Transmission Weight")

GLTF_GROUP = "glTF Material Output"


class PBAKE_Settings(bpy.types.PropertyGroup):
    resolution: EnumProperty(
        name="Size",
        items=[(s, s, f"{s} x {s} pixels") for s in ("256", "512", "1024", "2048", "4096")],
        default="1024",
    )
    output_dir: StringProperty(
        name="Folder",
        description="Where the texture files go. // means next to the .blend file",
        subtype='DIR_PATH',
        default="//textures/",
    )
    bake_albedo: BoolProperty(name="Albedo", description="Base color, no light or shadow", default=True)
    bake_normal: BoolProperty(name="Normal", description="Tangent space normal map (OpenGL, Y+). Works in Godot", default=True)
    bake_glow: BoolProperty(name="Glow", description="Emission color", default=True)
    bake_roughness: BoolProperty(name="Roughness", description="How rough or shiny", default=False)
    bake_metallic: BoolProperty(name="Metallic", description="White where it's metal", default=False)
    bake_ao: BoolProperty(name="AO", description="Ambient occlusion: dark in cracks and corners", default=False)
    pack_orm: BoolProperty(
        name="Pack ORM",
        description="Also save AO, Roughness and Metallic in one texture (R, G, B). "
                    "Godot's ORM material uses this",
        default=False,
    )
    skip_black_glow: BoolProperty(
        name="Skip Empty Maps",
        description="Don't save glow or metallic if it's all black",
        default=True,
    )
    high_bit: BoolProperty(
        name="16-bit",
        description="Save 16-bit PNGs. Smoother normals, bigger files",
        default=False,
    )
    margin: IntProperty(
        name="Margin",
        description="Pixels to bleed past UV edges, so seams don't show",
        default=16, min=0, max=64,
    )
    samples: IntProperty(
        name="Samples",
        description="More samples = smoother edges, slower bake",
        default=16, min=1, max=1024,
    )
    ao_samples: IntProperty(
        name="AO Samples",
        description="AO is grainy with few samples, so it gets its own count",
        default=128, min=1, max=4096,
    )
    auto_uv: BoolProperty(
        name="Auto UV",
        description="Unwrap objects that have no UV map (Smart UV Project)",
        default=True,
    )
    make_material: BoolProperty(
        name="Make Baked Material",
        description="Make a new material that uses the baked textures",
        default=True,
    )
    use_material: BoolProperty(
        name="Put It On The Object",
        description="Swap the object's materials for the baked one. "
                    "The old materials are kept in the file",
        default=False,
    )


def wanted_maps(settings):
    return [m for m in MAPS
            if getattr(settings, "bake_" + m[0]) or (settings.pack_orm and m[0] in ORM_KEYS)]


def unique_materials(obj):
    seen = []
    for slot in obj.material_slots:
        mat = slot.material
        if mat and mat.node_tree and mat not in seen:
            seen.append(mat)
    return seen


def smart_uv(context, obj):
    for o in context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')


class TreeEdits:
    """Temporary material edits that can all be put back with restore()."""

    def __init__(self):
        self.undo = []

    def set_input(self, tree, sock, value):
        links = [l.from_socket for l in sock.links]
        old = sock.default_value
        for l in list(sock.links):
            tree.links.remove(l)
        sock.default_value = value

        def back():
            sock.default_value = old
            for from_sock in links:
                tree.links.new(from_sock, sock)
        self.undo.append(back)

    def swap_output(self, tree, old_out, new_out):
        """Move every link that leaves old_out so it leaves new_out."""
        targets = [l.to_socket for l in old_out.links]
        for l in list(old_out.links):
            tree.links.remove(l)
        for to_sock in targets:
            tree.links.new(new_out, to_sock)

        def back():
            for to_sock in targets:
                tree.links.new(old_out, to_sock)
        self.undo.append(back)

    def add_node(self, tree, node_type):
        node = tree.nodes.new(node_type)
        self.undo.append(lambda: tree.nodes.remove(node))
        return node

    def restore(self):
        for back in reversed(self.undo):
            back()
        self.undo.clear()


def zero_albedo_blockers(edits, materials):
    """Set Metallic etc. to 0 on Principled nodes."""
    for mat in materials:
        tree = mat.node_tree
        for node in tree.nodes:
            if node.type != 'BSDF_PRINCIPLED':
                continue
            for name in ALBEDO_ZERO_INPUTS:
                sock = node.inputs.get(name)
                if sock is not None:
                    edits.set_input(tree, sock, 0.0)


def route_metallic(edits, materials):
    """Make each Principled node glow with its Metallic value, so an EMIT bake
    captures metallic. Mix shaders still mix it right. Other glow is turned off."""
    for mat in materials:
        tree = mat.node_tree
        for node in list(tree.nodes):
            if node.type == 'EMISSION':
                edits.set_input(tree, node.inputs["Strength"], 0.0)
            if node.type != 'BSDF_PRINCIPLED':
                continue
            emit = edits.add_node(tree, 'ShaderNodeEmission')
            emit.inputs["Strength"].default_value = 1.0
            metal = node.inputs["Metallic"]
            if metal.links:
                tree.links.new(metal.links[0].from_socket, emit.inputs["Color"])
            else:
                v = metal.default_value
                emit.inputs["Color"].default_value = (v, v, v, 1.0)
            edits.swap_output(tree, node.outputs["BSDF"], emit.outputs["Emission"])


def channel(image):
    px = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(px)
    return px[0::4]


def is_black(image):
    px = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(px)
    rgb = px.reshape(-1, 4)[:, :3]
    return float(rgb.max()) <= 1.0 / 255.0


def save_png(image, path, high_bit):
    image.filepath_raw = path
    image.file_format = 'PNG'
    if high_bit:
        save_png16(image)
    else:
        image.save()


def pack_orm(name, images, high_bit):
    size = images["ao"].size[0]
    rgba = np.ones(size * size * 4, dtype=np.float32)
    for i, key in enumerate(ORM_KEYS):
        rgba[i::4] = channel(images[key])
    image = new_image(name, size, "Non-Color", high_bit)
    image.pixels.foreach_set(rgba)
    return image


def new_image(name, size, colorspace, high_bit):
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    image = bpy.data.images.new(name, size, size, alpha=False, float_buffer=high_bit)
    image.colorspace_settings.name = colorspace
    return image


def gltf_output_group():
    """The node group the glTF exporter reads AO from."""
    group = bpy.data.node_groups.get(GLTF_GROUP)
    if group is None:
        group = bpy.data.node_groups.new(GLTF_GROUP, 'ShaderNodeTree')
        group.interface.new_socket("Occlusion", in_out='INPUT', socket_type='NodeSocketFloat')
    return group


def save_png16(image):
    """Save a float image as a 16-bit PNG.

    Image.save() only writes 8-bit, so this goes through save_render with a
    throwaway scene. Its Standard view keeps colors as baked (no AgX look).
    """
    tmp = bpy.data.scenes.new("pbake_tmp")
    try:
        tmp.view_settings.view_transform = 'Standard'
        tmp.view_settings.look = 'None'
        s = tmp.render.image_settings
        s.file_format = 'PNG'
        s.color_depth = '16'
        s.color_mode = 'RGB'
        image.save_render(image.filepath_raw, scene=tmp)
    finally:
        bpy.data.scenes.remove(tmp)
    image.source = 'FILE'
    image.reload()


def make_baked_material(obj, images, name=None):
    name = name or f"{obj.name}_baked"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not mat.node_tree:
        mat.use_nodes = True  # Blender 4.x; 5.x materials always have nodes
    mat.use_fake_user = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')
    out.location = (400, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def tex(key, y):
        node = nodes.new('ShaderNodeTexImage')
        node.image = images[key]
        node.location = (-500, y)
        return node

    if "albedo" in images:
        links.new(tex("albedo", 300).outputs["Color"], bsdf.inputs["Base Color"])
    ao_out = None
    if "orm" in images:
        split = nodes.new('ShaderNodeSeparateColor')
        split.location = (-200, 0)
        links.new(tex("orm", 0).outputs["Color"], split.inputs["Color"])
        ao_out = split.outputs[0]
        links.new(split.outputs[1], bsdf.inputs["Roughness"])
        links.new(split.outputs[2], bsdf.inputs["Metallic"])
    else:
        if "roughness" in images:
            links.new(tex("roughness", 0).outputs["Color"], bsdf.inputs["Roughness"])
        if "metallic" in images:
            links.new(tex("metallic", 150).outputs["Color"], bsdf.inputs["Metallic"])
        if "ao" in images:
            ao_out = tex("ao", -900).outputs["Color"]
    if ao_out is not None:
        gltf = nodes.new('ShaderNodeGroup')
        gltf.node_tree = gltf_output_group()
        gltf.location = (400, -300)
        links.new(ao_out, gltf.inputs["Occlusion"])
    if "normal" in images:
        nmap = nodes.new('ShaderNodeNormalMap')
        nmap.location = (-200, -300)
        links.new(tex("normal", -300).outputs["Color"], nmap.inputs["Color"])
        links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    if "glow" in images:
        links.new(tex("glow", -600).outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


PROCEDURAL_NODES = {'TEX_NOISE', 'TEX_VORONOI', 'TEX_WAVE', 'TEX_GRADIENT', 'TEX_BRICK', 'TEX_CHECKER', 'TEX_MAGIC',
                    'TEX_WHITE_NOISE', 'TEX_MUSGRAVE', 'TEX_GABOR', 'ATTRIBUTE'}
VIEW_DEPENDENT_NODES = {'FRESNEL', 'LAYER_WEIGHT', 'LIGHT_PATH', 'CAMERA'}   # look changes with the viewer: a bake is a guess


class MaterialScan(NamedTuple):
    needs_bake: bool        # a game engine could not read this material as it is (procedural, or not UV mapped)
    view_dependent: bool    # has nodes whose result depends on the viewing angle


def vector_is_uv(socket, depth=0):
    """True when an Image Texture's Vector input ends in UV coordinates (nothing linked counts: it defaults to UV)."""
    if not socket.is_linked or depth > 20:
        return True
    link = socket.links[0]
    node = link.from_node
    if node.type == 'TEX_COORD':
        return link.from_socket.name == "UV"
    if node.type == 'MAPPING':
        return vector_is_uv(node.inputs["Vector"], depth + 1)
    if node.type == 'REROUTE':
        return vector_is_uv(node.inputs[0], depth + 1)
    return node.type in ('UVMAP', 'GROUP_INPUT')


def scan_material(material, _seen=None):
    """Does this material need baking for a game? Procedural texture nodes, Attribute nodes, or an Image Texture that
    is not read through UVs (Generated / Object / Box ...) say yes (groups are searched). Fresnel, Layer Weight, Light
    Path and Camera Data say yes too, flagged view_dependent. Image textures on UVs and plain values say no."""
    seen = _seen if _seen is not None else set()
    tree = getattr(material, "node_tree", None)
    if tree is None or tree in seen:
        return MaterialScan(False, False)
    seen.add(tree)
    needs_bake = view_dependent = False
    for node in tree.nodes:
        if node.type in PROCEDURAL_NODES:
            needs_bake = True
        elif node.type in VIEW_DEPENDENT_NODES:
            needs_bake = view_dependent = True
        elif node.type == 'TEX_IMAGE' and (node.projection != 'FLAT' or not vector_is_uv(node.inputs["Vector"])):
            needs_bake = True
        elif node.type == 'GROUP' and node.node_tree:
            inner = scan_material(node, seen)   # a group node has a node_tree too
            needs_bake, view_dependent = needs_bake or inner.needs_bake, view_dependent or inner.view_dependent
    return MaterialScan(needs_bake, view_dependent)


class BakeResult(NamedTuple):
    saved: int
    problems: list
    baked: dict     # (object name, material name) -> its baked material; only in per-material mode


def bake_jobs(obj, only, per_material):
    """What to bake on one object: [(file name base, materials)]. One job for all its materials (the card's way),
    or one per material (per_material). `only(material)` limits which materials take part."""
    base = bpy.path.clean_name(obj.name)
    indices = np.empty(len(obj.data.polygons), dtype=np.int32)
    obj.data.polygons.foreach_get("material_index", indices)
    used = {int(index) for index in np.unique(indices)}
    on_faces = {slot.material for index, slot in enumerate(obj.material_slots) if index in used}   # else: "No faces found"
    materials = [mat for mat in unique_materials(obj) if mat in on_faces and (only is None or only(mat))]
    if per_material:
        return [(f"{base}_{bpy.path.clean_name(mat.name)}", [mat]) for mat in materials]
    return [(base, materials)] if materials else []


def bake_objects(context, objects, settings, out_dir, only=None, per_material=False, make_material=None,
                 use_material=None):
    """Bake the objects' materials to PNGs in `out_dir` (made if missing) with the settings' maps, size, samples. The
    card's bake and the Bake to Game Asset process both run this. `make_material` / `use_material` override the
    settings' two options. In per-material mode a baked material replaces only the slots of the baked material.
    Cycles and the selection are put back afterwards. Returns a BakeResult; problems are texts, never raised."""
    maps = wanted_maps(settings)
    make_material = settings.make_material if make_material is None else make_material
    use_material = settings.use_material if use_material is None else use_material
    os.makedirs(out_dir, exist_ok=True)
    scene = context.scene
    old_active = context.view_layer.objects.active
    old_selected = list(context.selected_objects)
    old_engine = scene.render.engine
    scene.render.engine = 'CYCLES'
    old_samples = scene.cycles.samples
    scene.cycles.samples = settings.samples

    plans = [(obj, bake_jobs(obj, only, per_material)) for obj in objects]
    wm = context.window_manager
    wm.progress_begin(0, max(1, sum(len(jobs) for _obj, jobs in plans) * len(maps)))
    done = 0
    saved = 0
    problems = []
    baked_materials = {}
    try:
        for obj, jobs in plans:
            if not unique_materials(obj):
                problems.append(f"{obj.name}: no material")
                continue
            runnable = []
            for job_name, materials in jobs:
                if any(mat.library for mat in materials):
                    problems.append(f"{obj.name}: linked material, can't edit")
                    done += len(maps)
                else:
                    runnable.append((job_name, materials))
            if runnable and not obj.data.uv_layers:
                if not settings.auto_uv:
                    problems.append(f"{obj.name}: no UV map")
                    done += len(maps) * len(runnable)
                    continue
                smart_uv(context, obj)

            for job_name, materials in runnable:
                for other in context.view_layer.objects:
                    other.select_set(False)
                obj.select_set(True)
                context.view_layer.objects.active = obj

                baked = {}
                try:
                    for key, label, bake_type, colorspace in maps:
                        baked[key] = bake_map(context, materials, f"{job_name}_{key}", key, bake_type, colorspace)
                        done += 1
                        wm.progress_update(done)
                except RuntimeError as error:     # Blender's bake refused (no faces, missing UVs...): carry on
                    for image in baked.values():
                        bpy.data.images.remove(image)
                    problems.append(f"{obj.name}: {str(error).strip().splitlines()[-1]}")
                    continue

                if settings.pack_orm:
                    baked["orm"] = pack_orm(f"{job_name}_orm", baked, settings.high_bit)

                images = {}
                for key, image in baked.items():
                    wanted = key == "orm" or getattr(settings, "bake_" + key)
                    empty = key in SKIP_IF_EMPTY and settings.skip_black_glow and is_black(image)
                    if not wanted or empty:
                        bpy.data.images.remove(image)
                        continue
                    save_png(image, os.path.join(out_dir, image.name + ".png"), settings.high_bit)
                    images[key] = image
                    saved += 1

                if make_material and images:
                    material_name = f"{obj.name}_{materials[0].name}_baked" if per_material else None
                    mat = make_baked_material(obj, images, material_name)
                    if per_material:
                        baked_materials[(obj.name, materials[0].name)] = mat
                    if use_material:
                        for slot in obj.material_slots:
                            if not per_material or slot.material in materials:
                                slot.material = mat
    finally:
        wm.progress_end()
        scene.cycles.samples = old_samples
        scene.render.engine = old_engine
        for other in context.view_layer.objects:
            other.select_set(other in old_selected)
        context.view_layer.objects.active = old_active
    return BakeResult(saved, problems, baked_materials)


class PBAKE_OT_bake(bpy.types.Operator):
    """Bake the selected objects' materials to texture files"""
    bl_idname = "pbake.bake"
    bl_label = "Bake Textures"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

    def execute(self, context):
        settings = context.scene.procedural_baker
        if not wanted_maps(settings):
            self.report({'ERROR'}, "Pick at least one texture to bake")
            return {'CANCELLED'}
        out_dir = settings.output_dir
        if out_dir.startswith("//") and not bpy.data.filepath:
            self.report({'ERROR'}, "Save the .blend file first, or pick a full folder path")
            return {'CANCELLED'}
        out_dir = bpy.path.abspath(out_dir)
        objects = [o for o in context.selected_objects if o.type == 'MESH']
        result = bake_objects(context, objects, settings, out_dir)
        msg = f"Saved {result.saved} textures to {out_dir}"
        if result.problems:
            self.report({'WARNING'}, msg + ". Skipped: " + "; ".join(result.problems))
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


def bake_map(context, materials, name, key, bake_type, colorspace):
    """Bake one map of the active object into a new, unsaved image."""
    scene = context.scene
    settings = scene.procedural_baker
    image = new_image(name, int(settings.resolution), colorspace, settings.high_bit)
    if key == "normal":
        image.generated_color = (0.5, 0.5, 1.0, 1.0)

    edits = TreeEdits()
    for mat in materials:
        node = edits.add_node(mat.node_tree, 'ShaderNodeTexImage')
        node.image = image
        node.location = (-1000, 0)
        mat.node_tree.nodes.active = node
    if key == "albedo":
        zero_albedo_blockers(edits, materials)
    if key == "metallic":
        route_metallic(edits, materials)

    old_samples = scene.cycles.samples
    if key == "ao":
        scene.cycles.samples = settings.ao_samples
    try:
        kwargs = dict(
            type=bake_type,
            margin=settings.margin,
            use_clear=True,
            use_selected_to_active=False,
            target='IMAGE_TEXTURES',
        )
        if bake_type == 'DIFFUSE':
            kwargs["pass_filter"] = {'COLOR'}
        if bake_type == 'NORMAL':
            kwargs["normal_space"] = 'TANGENT'
        bpy.ops.object.bake(**kwargs)
    finally:
        scene.cycles.samples = old_samples
        edits.restore()
    return image


def draw_map_options(layout, settings, extra=()):
    """The Textures section (which maps) and the Size; the card and the Bake to Game Asset process show the same.
    `extra` = more property names for the Size group."""
    sec = section(layout, "pbake_textures", "Textures", icon='TEXTURE')
    if sec:
        toggles(sec, settings, [("bake_albedo", "Albedo"), ("bake_normal", "Normal"), ("bake_glow", "Glow"),
                                ("bake_roughness", "Roughness"), ("bake_metallic", "Metallic"), ("bake_ao", "AO"),
                                ("pack_orm", "Pack ORM")])
    prop_group(layout, settings, ["resolution", *extra])


def draw_card(layout, context):
    settings = context.scene.procedural_baker
    draw_map_options(layout, settings, extra=["output_dir"])
    prop_group(layout, settings, ["make_material"])
    use = layout.column()
    use.active = settings.make_material
    prop_group(use, settings, ["use_material"])
    action_row(layout).operator(PBAKE_OT_bake.bl_idname, icon='RENDER_STILL')
    hints(layout, ["Needs a mesh with a material; Cycles bakes it"], context)
    more = section(layout, "pbake_more", "More Options", default_closed=True)
    if more:
        prop_group(more, settings, ["samples", "ao_samples", "margin", "high_bit", "skip_black_glow", "auto_uv"])


classes = (PBAKE_Settings, PBAKE_OT_bake)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.procedural_baker = PointerProperty(type=PBAKE_Settings)


def unregister():
    del bpy.types.Scene.procedural_baker
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
