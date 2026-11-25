"""Texture Studio compositor: the render passes it needs and the node tree that turns them into maps.

setup_passes() turns on the Cycles passes and the view layer AOVs; build() makes the compositor tree
"Texture Studio" with one File Output input per map in maps.MAPS. Every pass goes through a Flip
node first ("TS Flip <pass>"), so the back shot can be mirrored without touching anything else.
The capture (studio.py) only sets values on named nodes (configure(): camera axes for the normal map,
border grow in px, the Flip X toggles, the File Output directory) and unlinks maps it should skip.
"""
import os

import bpy

from .. import compositor_common  # generated copy: shared node helpers (TreeBuilder)
from . import maps

TREE_NAME = "Texture Studio"
OUTPUT = "TS Output"
BORDER = "TS Border"
CAM_AXIS = "TS Camera {}"   # .format("X" / "Y" / "Z"): Dot Product nodes, input 1 = camera axis
FLIP = "TS Flip "

PASSES = ("use_pass_combined", "use_pass_z", "use_pass_mist", "use_pass_normal", "use_pass_diffuse_direct",
          "use_pass_diffuse_indirect", "use_pass_diffuse_color", "use_pass_transmission_direct",
          "use_pass_transmission_indirect", "use_pass_transmission_color", "use_pass_emit",
          "use_pass_ambient_occlusion")
VIEWS = {"standard": "Standard", "raw": "Raw"}  # maps.MAPS "colors" -> View Transform ("scene" = follow)


def setup_passes(view_layer):
    for name in PASSES:
        setattr(view_layer, name, True)
    for aov in [a for a in view_layer.aovs if a.name.startswith("ts_")]:
        view_layer.aovs.remove(aov)
    for key, (_input, kind) in maps.AOVS.items():
        aov = view_layer.aovs.add()
        aov.name, aov.type = maps.aov_name(key), kind


class _Tree(compositor_common.TreeBuilder):
    """The shared TreeBuilder plus the Render Layers node and per-pass Flip nodes, so the map recipes
    below read like formulas."""

    def __init__(self, tree, scene):
        super().__init__(tree)
        self.rl = self.node("CompositorNodeRLayers", "Render Layers", (-900, 0))
        self.rl.scene, self.rl.layer = scene, scene.view_layers[0].name  # not the current scene: it may lack the passes
        self.flipped = {}

    def p(self, name):
        """Render pass output, through its own Flip node (Flip X is turned on for the back shot)."""
        if name not in self.flipped:
            y = -120 * len(self.flipped)
            flip = self.node("CompositorNodeFlip", FLIP + name, (-650, y))
            self.links.new(self.rl.outputs[name], flip.inputs["Image"])
            self.flipped[name] = flip.outputs[0]
        return self.flipped[name]

    def with_alpha(self, image, alpha=None):
        """Image (premultiplied, like every pass) with the render's Alpha as its alpha."""
        return self.set_alpha(image, self.p("Alpha") if alpha is None else alpha)


def _lit(t, kind, straight_alpha):
    """Light of one kind without specular: denoise(Direct + Indirect) x Color.

    The light is made straight (divided by alpha) before the multiply: Color is already
    premultiplied, so edges don't get darkened twice."""
    light = t.denoise(t.mix("ADD", t.p(kind + " Direct"), t.p(kind + " Indirect")))
    return t.mix("MULTIPLY", t.mix("DIVIDE", light, straight_alpha), t.p(kind + " Color"))


def _recipes(t):
    """{map name: output socket}, one entry per maps.MAPS name."""
    alpha = t.p("Alpha")
    straight_alpha = t.math("MAXIMUM", alpha, 1e-4)
    # Cycles counts subsurface scattering as diffuse (no separate passes since 4.0). Transmission is glass (Digit's
    # visor): the studio's grey glass backdrop seen through it (scene_setup.GLASS_BACKDROP), else glass is black.
    lit = t.mix("ADD", _lit(t, "Diffuse", straight_alpha), _lit(t, "Transmission", straight_alpha))
    matte = t.mix("ADD", lit, t.p("Emission"))
    normal = t.vmath("NORMALIZE", t.p("Normal"))
    axes = [t.vmath("DOT_PRODUCT", normal, (1.0, 0.0, 0.0), CAM_AXIS.format(a)) for a in "XYZ"]
    cam_normal = t.node("ShaderNodeCombineXYZ", X=axes[0], Y=axes[1], Z=axes[2]).outputs[0]
    normal_rgb = t.vmath("MULTIPLY_ADD", cam_normal, (0.5, 0.5, 0.5), v2=(0.5, 0.5, 0.5))
    ao = t.denoise(t.p("Ambient Occlusion"))
    facing = t.math("MULTIPLY_ADD", t.math("MAXIMUM", axes[2], 0.0), maps.FACING, 1.0 - maps.FACING)
    shading = t.math("MULTIPLY", t.math("DIVIDE", ao, straight_alpha), facing)  # straight (not premultiplied)
    out = {
        "beauty": t.p("Image"),
        "matte": t.with_alpha(matte),
        "albedo": t.with_alpha(t.p("Diffuse Color")),
        "shaded_albedo": t.with_alpha(t.mix("MULTIPLY", t.p("Diffuse Color"), shading)),
        "emission": t.with_alpha(t.p("Emission")),
        "normal": t.mix("MIX", (0.5, 0.5, 1.0, 1.0), normal_rgb, alpha),
        "ao": t.with_alpha(ao),
        "shading": t.with_alpha(t.math("MULTIPLY", shading, alpha)),
        "depth": t.with_alpha(t.math("SUBTRACT", 1.0, t.p("Mist"))),
        "mask": alpha,
        "border": t.node("CompositorNodeDilateErode", BORDER, Mask=alpha, Size=8, Type="Distance").outputs[0],
    }
    for key in maps.AOVS:
        out[key] = t.with_alpha(t.p(maps.aov_name(key)))
    return out


def _add_item(node, spec, scene):
    item = node.file_output_items.new("RGBA", spec["name"])
    item.override_node_format = True
    item.save_as_render = True
    fmt = item.format
    fmt.file_format, fmt.color_mode, fmt.color_depth = "PNG", spec["mode"], spec["depth"]
    fmt.compression = 15
    if spec["colors"] in VIEWS:
        fmt.color_management = "OVERRIDE"
        fmt.view_settings.view_transform = VIEWS[spec["colors"]]
        fmt.view_settings.look = "None"
        fmt.view_settings.exposure, fmt.view_settings.gamma = 0.0, 1.0
    return item


def build(scene):
    """(Re)make the Texture Studio compositor tree on scene; returns it."""
    old = bpy.data.node_groups.get(TREE_NAME)
    if old:
        bpy.data.node_groups.remove(old)
    tree = bpy.data.node_groups.new(TREE_NAME, "CompositorNodeTree")
    scene.compositing_node_group = tree
    scene.render.use_compositing = True
    t = _Tree(tree, scene)
    recipes = _recipes(t)
    out = t.node("CompositorNodeOutputFile", OUTPUT, (900, 0))
    out.format.media_type = "IMAGE"  # one file per input (the default is one multilayer EXR)
    out.format.file_format = "PNG"
    out.save_as_render = True
    out.use_file_extension = True
    out.file_name = ""  # the default "{blend_name}" would prefix every file
    for spec in maps.MAPS:
        _add_item(out, spec, scene)
        t.links.new(recipes[spec["name"]], out.inputs[spec["name"]])
    return tree


def tree_of(scene):
    tree = scene.compositing_node_group
    if tree is None or tree.nodes.get(OUTPUT) is None:
        raise RuntimeError("this scene has no Texture Studio compositor (run build_studio.py)")
    return tree


def configure(scene, directory, camera_matrix, mirror, border_px):
    """Set the per-shot values: output folder, camera axes for the normal map, mirror, border size."""
    tree = tree_of(scene)
    tree.nodes[OUTPUT].directory = os.path.join(directory, "")  # trailing slash: files go inside it
    tree.nodes[OUTPUT].file_name = ""  # studios built before this fix had "{blend_name}"
    rot = camera_matrix.to_3x3().normalized()
    for i, axis in enumerate("XYZ"):
        vec = rot.col[i].copy()
        if axis == "X" and mirror:  # in the mirrored image, right is the camera's left
            vec.negate()
        tree.nodes[CAM_AXIS.format(axis)].inputs[1].default_value = vec
    for node in tree.nodes:
        if node.name.startswith(FLIP):
            node.inputs["Flip X"].default_value = mirror
    tree.nodes[BORDER].inputs["Size"].default_value = int(border_px)


def unlink_unwanted(scene, wanted):
    """Unlink the File Output inputs of maps not in wanted (unlinked inputs are not written).

    Returns [(from socket, map name)] for relink()."""
    tree = tree_of(scene)
    out, removed = tree.nodes[OUTPUT], []
    for spec in maps.MAPS:
        if spec["name"] not in wanted:
            for link in list(out.inputs[spec["name"]].links):
                removed.append((link.from_socket, spec["name"]))
                tree.links.remove(link)
    return removed


def relink(scene, removed):
    tree = tree_of(scene)
    out = tree.nodes[OUTPUT]
    for from_socket, name in removed:
        tree.links.new(from_socket, out.inputs[name])
