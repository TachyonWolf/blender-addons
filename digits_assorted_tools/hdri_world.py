# SPDX-License-Identifier: GPL-3.0-or-later
"""HDRI World (Digit's Tools > Setups): builds / updates the scene's World node tree for an HDRI.

Node tree (every node carries the custom property spec.TAG = its role, so the tool finds its own nodes):
Texture Coordinate > Mapping (Rotation) > Environment Texture "light" > Background (Strength) \\
                                                                                              Mix Shader (Is Camera Ray) > World Output
                    Mapping + jitter (Noise, Blur) > Environment Texture "view" > Background (Background Strength) /
Light rays use the sharp lookup at Strength, camera rays the blurred one at Background Strength."""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from . import hdri_world_spec as spec
from .ui_cards import action_row, choice_row, hints, prop_group, section, status  # generated copy

BACKGROUND_ITEMS = (("SHOW", "Show", "The HDRI is the picture behind the subject"),
                    ("HIDE", "Hide", "Transparent background; the HDRI still lights the subject"))
_items_cache = []   # dynamic enum items must stay alive after the callback returns
_items_key = None


# ---------------------------------------------------------------------------
# Finding HDRIs
# ---------------------------------------------------------------------------

def default_folder():
    home = os.path.expanduser("~")
    return next((p for p in (os.path.join(home, c) for c in spec.FOLDER_CANDIDATES) if os.path.isdir(p)), "")


def bundled_folder():
    return os.path.join(bpy.utils.system_resource('DATAFILES'), "studiolights", "world")


def list_hdris(folder, depth=1):
    """Sorted [(name, path)] of .hdr / .exr files in folder (and subfolders down to `depth`)."""
    found = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError:
        return found
    for entry in entries:
        if entry.is_file() and entry.name.lower().endswith(spec.IMAGE_EXTENSIONS):
            found.append((os.path.splitext(entry.name)[0], entry.path))
        elif entry.is_dir() and depth > 0:
            found += list_hdris(entry.path, depth - 1)
    return found


def hdri_items(user_folder):
    """Enum items [(identifier = path, label, tooltip)] for the bundled lights then the user's folder."""
    items = [(spec.NO_HDRI, spec.NO_HDRI_LABEL, "Use the file path above")]
    for title, folder in (("Blender Studio Lights", bundled_folder()), ("HDRI Folder", bpy.path.abspath(user_folder))):
        found = list_hdris(folder) if folder else []
        if found:
            items.append(("", title, ""))
            items += [(path, name, path) for name, path in found]
    return items


def _enum_items(self, context):
    global _items_cache, _items_key
    folder = context.scene.hdri_world_folder if context else ""
    if _items_key != folder:
        _items_cache, _items_key = hdri_items(folder), folder
    return _items_cache


def refresh_items():
    """Forget the cached list (after the folder changes)."""
    global _items_key
    _items_key = None


def chosen_path(scene):
    """The file to use: the typed path if any, else the list's pick ('' for none)."""
    path = bpy.path.abspath(scene.hdri_world_path)
    return path or ("" if scene.hdri_world_pick == spec.NO_HDRI else scene.hdri_world_pick)


# ---------------------------------------------------------------------------
# The node tree
# ---------------------------------------------------------------------------

def tagged(world):
    """{role: node} of the tool's nodes in a world."""
    tree = world.node_tree if world else None
    return {n[spec.TAG]: n for n in tree.nodes if spec.TAG in n} if tree else {}


def is_ours(world):
    """True for a world whose every node was built by this tool (safe to rebuild / update)."""
    tree = world.node_tree if world else None
    return bool(tree and tree.nodes and all(spec.TAG in n for n in tree.nodes))


def is_untouched(world):
    """True for a world with no user work: no nodes, or just the default Background > World Output."""
    tree = world.node_tree if world else None
    if tree is None or not tree.nodes:
        return True
    kinds = sorted(n.bl_idname for n in tree.nodes)
    if kinds != ["ShaderNodeBackground", "ShaderNodeOutputWorld"]:
        return False
    background = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeBackground")
    return not any(s.is_linked for s in background.inputs) and background.inputs["Strength"].default_value == 1.0


def world_for_apply(scene):
    """The world to build in: ours or untouched as is; otherwise a (reused) separate 'HDRI World'."""
    world = scene.world
    if world is None or is_ours(world) or is_untouched(world):
        world = world or bpy.data.worlds.new(spec.WORLD_NAME)
    else:
        existing = bpy.data.worlds.get(spec.WORLD_NAME)
        world = existing if existing and (is_ours(existing) or is_untouched(existing)) else bpy.data.worlds.new(spec.WORLD_NAME)
    scene.world = world
    return world


def _new(nodes, links, kind, role, x, y):
    node = nodes.new(kind)
    node[spec.TAG] = role
    node.location = (x, y)
    return node


def build_tree(world):
    """(Re)build the whole node tree in `world` (which must be ours or untouched)."""
    if world.node_tree is None:
        world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()
    nodes, links = tree.nodes, tree.links
    new = lambda kind, role, x, y: _new(nodes, links, kind, role, x, y)  # noqa: E731
    coord = new("ShaderNodeTexCoord", "coord", -1100, 0)
    mapping = new("ShaderNodeMapping", "mapping", -900, 0)
    noise = new("ShaderNodeTexNoise", "noise", -900, -350)
    centre = new("ShaderNodeVectorMath", "noise_centre", -700, -350)
    amount = new("ShaderNodeVectorMath", "blur", -700, -500)
    jitter = new("ShaderNodeVectorMath", "jitter", -500, -350)
    env_light = new("ShaderNodeTexEnvironment", "light_image", -600, 250)
    env_view = new("ShaderNodeTexEnvironment", "view_image", -300, -350)
    light = new("ShaderNodeBackground", "light", -300, 250)
    view = new("ShaderNodeBackground", "view", 0, -350)
    camera_ray = new("ShaderNodeLightPath", "camera_ray", 0, 100)
    mix = new("ShaderNodeMixShader", "mix", 250, 0)
    out = new("ShaderNodeOutputWorld", "output", 450, 0)
    noise.inputs["Scale"].default_value, noise.inputs["Detail"].default_value = 500.0, 0.0
    centre.operation, centre.inputs[1].default_value = 'SUBTRACT', (0.5, 0.5, 0.5)
    amount.operation = 'SCALE'
    jitter.operation = 'ADD'
    for src, dst in ((coord.outputs["Generated"], mapping.inputs["Vector"]),
                     (coord.outputs["Generated"], noise.inputs["Vector"]),
                     (noise.outputs["Color"], centre.inputs[0]),
                     (centre.outputs["Vector"], amount.inputs[0]),
                     (mapping.outputs["Vector"], jitter.inputs[0]),
                     (amount.outputs["Vector"], jitter.inputs[1]),
                     (mapping.outputs["Vector"], env_light.inputs["Vector"]),
                     (jitter.outputs["Vector"], env_view.inputs["Vector"]),
                     (env_light.outputs["Color"], light.inputs["Color"]),
                     (env_view.outputs["Color"], view.inputs["Color"]),
                     (camera_ray.outputs["Is Camera Ray"], mix.inputs["Fac"]),
                     (light.outputs["Background"], mix.inputs[1]),
                     (view.outputs["Background"], mix.inputs[2]),
                     (mix.outputs["Shader"], out.inputs["Surface"])):
        links.new(src, dst)


def set_options(world, path, strength, bg_strength, rotation, blur):
    """Put an HDRI file (None for no image) and the options on the tagged nodes of `world`."""
    parts = tagged(world)
    image = bpy.data.images.load(path, check_existing=True) if path and os.path.isfile(path) else None
    for role in ("light_image", "view_image"):
        parts[role].image = image
    parts["light"].inputs["Strength"].default_value = strength
    parts["view"].inputs["Strength"].default_value = bg_strength
    parts["mapping"].inputs["Rotation"].default_value[2] = rotation
    parts["blur"].inputs[3].default_value = blur * spec.BLUR_SCALE


def update_tree(scene):
    """Push the scene's options onto the tagged nodes of its world. False if the world isn't ours."""
    world = scene.world
    if not (tagged(world) and is_ours(world)):
        return False
    set_options(world, chosen_path(scene), scene.hdri_world_strength, scene.hdri_world_bg_strength,
                scene.hdri_world_rotation, scene.hdri_world_blur)
    scene.render.film_transparent = scene.hdri_world_background == 'HIDE'
    return True


def new_hdri_world(path, name):
    """A new world `name` lit by the HDRI file `path`: the card's node tree at the options' defaults (used for
    ready-made HDRI World assets)."""
    world = bpy.data.worlds.new(name)
    build_tree(world)
    set_options(world, path, 1.0, 1.0, 0.0, 0.0)
    return world


def apply_hdri(scene):
    """Build (or rebuild) the HDRI world in the scene and set the options on it."""
    world = world_for_apply(scene)
    build_tree(world)
    update_tree(scene)
    return world


def current_name(scene):
    """The HDRI file name of the scene's HDRI world, '' when there is none."""
    world = scene.world
    node = tagged(world).get("light_image") if is_ours(world) else None
    if node is None:
        return ""
    return os.path.basename(node.image.filepath) if node.image else "(no image)"


# ---------------------------------------------------------------------------
# Operator, card, registration
# ---------------------------------------------------------------------------

class HDRIWORLD_OT_apply(bpy.types.Operator):
    bl_idname = "setups.hdri_world_apply"
    bl_label = "Apply HDRI"
    bl_description = spec.APPLY_HELP
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(chosen_path(context.scene))

    def execute(self, context):
        path = chosen_path(context.scene)
        if not os.path.isfile(path):
            self.report({'ERROR'}, f"HDRI file not found: {path}")
            return {'CANCELLED'}
        world = apply_hdri(context.scene)
        self.report({'INFO'}, f"HDRI {os.path.basename(path)} in world {world.name}")
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    scene = context.scene
    name = current_name(scene)
    status(body, name or "No HDRI yet: pick one", icon='WORLD_DATA' if name else 'INFO')
    action_row(body).operator(HDRIWORLD_OT_apply.bl_idname, text="Apply HDRI" if not name else "Rebuild HDRI World", icon='WORLD')
    hints(body, ["Pick an HDRI from the list or set a file"] if not chosen_path(scene) else [], context)
    pick = section(body, "setups_hdri_world_pick", "Image", icon='IMAGE_DATA')
    if pick:
        prop_group(pick, scene, [("hdri_world_pick", "HDRI"), ("hdri_world_path", "File")])
    light = section(body, "setups_hdri_world_light", "Lighting", icon='LIGHT_SUN')
    if light:
        prop_group(light, scene, ["hdri_world_strength", "hdri_world_rotation"])
    back = section(body, "setups_hdri_world_background", "Background", icon='IMAGE_BACKGROUND')
    if back:
        choice_row(back, scene, "hdri_world_background")
        prop_group(back, scene, [("hdri_world_bg_strength", "Strength"), ("hdri_world_blur", "Blur")])
    lib = section(body, "setups_hdri_world_library", "Library", icon='FILE_FOLDER', default_closed=True)
    if lib:
        prop_group(lib, scene, [("hdri_world_folder", "HDRI Folder")])


def _live(self, context):
    update_tree(self)


def _pick_changed(self, context):
    if self.hdri_world_pick != spec.NO_HDRI and self.hdri_world_path:
        self.hdri_world_path = ""   # the update of the path changes the tree, so skip it below
    else:
        update_tree(self)


def _path_changed(self, context):
    update_tree(self)


def _folder_changed(self, context):
    refresh_items()


def register():
    scene = bpy.types.Scene
    scene.hdri_world_pick = EnumProperty(name="HDRI", items=_enum_items, update=_pick_changed, description=spec.PICK_HELP)
    scene.hdri_world_path = StringProperty(name="File", subtype='FILE_PATH', update=_path_changed, description=spec.PATH_HELP)
    scene.hdri_world_folder = StringProperty(name="HDRI Folder", subtype='DIR_PATH', default=default_folder(),
                                             update=_folder_changed, description=spec.FOLDER_HELP)
    scene.hdri_world_strength = FloatProperty(name="Strength", default=1.0, min=0.0, soft_max=10.0, update=_live,
                                              description=spec.STRENGTH_HELP)
    scene.hdri_world_rotation = FloatProperty(name="Rotation", default=0.0, subtype='ANGLE', unit='ROTATION',
                                              update=_live, description=spec.ROTATION_HELP)
    scene.hdri_world_background = EnumProperty(name="Background", items=BACKGROUND_ITEMS, default='SHOW',
                                               update=_live, description=spec.BACKGROUND_HELP)
    scene.hdri_world_bg_strength = FloatProperty(name="Background Strength", default=1.0, min=0.0, soft_max=10.0,
                                                 update=_live, description=spec.BG_STRENGTH_HELP)
    scene.hdri_world_blur = FloatProperty(name="Background Blur", default=0.0, min=0.0, max=1.0, update=_live,
                                          description=spec.BLUR_HELP)
    bpy.utils.register_class(HDRIWORLD_OT_apply)


def unregister():
    bpy.utils.unregister_class(HDRIWORLD_OT_apply)
    scene = bpy.types.Scene
    for prop in ("pick", "path", "folder", "strength", "rotation", "background", "bg_strength", "blur"):
        delattr(scene, f"hdri_world_{prop}")
