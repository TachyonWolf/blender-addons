# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/compositor_common.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Shared pieces for building compositor node trees from Python (Depth Fog, Film Look, Texture Studio).
Used by the Scripts builders and by Digit's Assorted Tools (Texture Studio); both get a synced copy.

TreeBuilder: small helpers so node recipes read like formulas (node, math, mix, vmath, ...), plus the
look helpers the effects share (bright_pass, blur, tint, luma, relative_px). new_group makes an asset
node group with a typed interface; save_group_library saves it to the Library as a Compositor asset.
In 5.x the compositor uses the shader Math / Mix / Map Range / Noise nodes; the old Compositor*
versions of those are gone.
"""
import bpy

COMPOSITOR_CATALOG_ID = "9bbfc3a4-d137-4687-ab3b-e0f4b560d0df"  # Compositor
LUMA = (0.2126, 0.7152, 0.0722)


def input_named(node, identifier):
    """The input socket by identifier (names repeat on Mix / Glare, identifiers don't)."""
    return next(s for s in node.inputs if s.identifier == identifier)


def output_named(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)


class TreeBuilder:
    """Node helpers over one tree. Values are numbers / tuples (default values) or sockets (links)."""

    def __init__(self, tree):
        self.tree, self.nodes, self.links = tree, tree.nodes, tree.links

    def node(self, idname, name=None, location=(0, 0), **inputs):
        n = self.nodes.new(idname)
        if name:
            n.name = n.label = name
        n.location = location
        for key, value in inputs.items():
            self.set(n.inputs[key.replace("_", " ")], value)
        return n

    def set(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        n = self.node("ShaderNodeMath")
        n.operation, n.use_clamp = op, clamp
        for socket, value in zip(n.inputs, (a, b, c)):
            self.set(socket, value)
        return n.outputs[0]

    def vmath(self, op, a, b=(0.0, 0.0, 0.0), name=None, **extra):
        n = self.node("ShaderNodeVectorMath", name)
        n.operation = op
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        for key, value in extra.items():
            self.set(n.inputs[int(key[1:])], value)
        return n.outputs["Value" if op == "DOT_PRODUCT" else "Vector"]

    def mix(self, blend, a, b, factor=1.0, clamp=True):
        """Colour mix (blend: 'MIX', 'ADD', 'MULTIPLY', ...)."""
        n = self.node("ShaderNodeMix")
        n.data_type, n.blend_type, n.clamp_factor = "RGBA", blend, clamp
        self.set(input_named(n, "Factor_Float"), factor)
        self.set(input_named(n, "A_Color"), a)
        self.set(input_named(n, "B_Color"), b)
        return output_named(n, "Result_Color")

    def mix_float(self, a, b, factor):
        n = self.node("ShaderNodeMix")
        n.data_type = "FLOAT"
        self.set(input_named(n, "Factor_Float"), factor)
        self.set(input_named(n, "A_Float"), a)
        self.set(input_named(n, "B_Float"), b)
        return output_named(n, "Result_Float")

    def map_range(self, value, from_min, from_max, to_min=0.0, to_max=1.0, clamp=True):
        n = self.node("ShaderNodeMapRange")
        n.data_type, n.clamp = "FLOAT", clamp
        for ident, v in (("Value", value), ("From Min", from_min), ("From Max", from_max),
                         ("To Min", to_min), ("To Max", to_max)):
            self.set(input_named(n, ident), v)
        return output_named(n, "Result")

    def rgb(self, color):
        """The R, G, B, A float outputs of a colour."""
        return self.node("CompositorNodeSeparateColor", Image=color).outputs

    def set_alpha(self, color, alpha):
        """Colour with `alpha` (float) as its alpha."""
        n = self.node("CompositorNodeSetAlpha", Image=color, Alpha=alpha)
        n.inputs["Type"].default_value = "Replace Alpha"
        return n.outputs[0]

    def luma(self, color):
        """Brightness of a colour (Rec.709 weights)."""
        return self.vmath("DOT_PRODUCT", color, LUMA)

    def relative_px(self, fraction, image, axis="X"):
        """A size given as a fraction of the image width (axis "X") or height ("Y"), in pixels."""
        n = self.node("CompositorNodeRelativeToPixel", Float_Value=fraction, Image=image)
        n.reference_dimension = axis
        return n.outputs[0]

    def frame(self):
        """The scene's current frame number (float socket)."""
        return self.node("CompositorNodeSceneTime").outputs["Frame"]

    def xyz(self, x, y=0.0, z=0.0):
        return self.node("ShaderNodeCombineXYZ", X=x, Y=y, Z=z).outputs[0]

    def split_xy(self, vector):
        n = self.node("ShaderNodeSeparateXYZ", Vector=vector)
        return n.outputs["X"], n.outputs["Y"]

    def white_noise(self, vector, w):
        """A random 0..1 value per distinct (vector, w) (hash, not smooth noise)."""
        n = self.node("ShaderNodeTexWhiteNoise")
        n.noise_dimensions = "4D"
        self.set(n.inputs["Vector"], vector)
        self.set(n.inputs["W"], w)
        return n.outputs["Value"]

    def blur(self, image, size_px, gaussian=True):
        """Blur by size_px (float, pixels, same in X and Y)."""
        size = self.node("ShaderNodeCombineXYZ", X=size_px, Y=size_px, Z=0.0).outputs[0]
        n = self.node("CompositorNodeBlur", Image=image, Size=size)
        n.inputs["Type"].default_value = "Gaussian" if gaussian else "Fast Gaussian"
        return n.outputs[0]

    def bright_pass(self, image, threshold, smoothness=0.1, cap=None, quality="Low"):
        """The parts of the image brighter than threshold (the Glare node's Highlights output);
        cap clamps the highlight values (so a very bright light can't drive huge glows)."""
        n = self.node("CompositorNodeGlare", Image=image)
        n.inputs["Quality"].default_value = quality
        self.set(input_named(n, "Highlights Threshold"), threshold)
        self.set(input_named(n, "Highlights Smoothness"), smoothness)
        self.set(input_named(n, "Strength"), 0.0)
        if cap is not None:
            self.set(input_named(n, "Clamp Highlights"), True)
            self.set(input_named(n, "Maximum Highlights"), cap)
        return output_named(n, "Highlights")

    # -- procedural line / speck / hair textures (random per grid cell, 0..1 floats) ----------

    def _cells(self, pixel, cell_w, cell_h):
        """(cell id vector, x and y inside the cell, a random(k) function) for a grid of cells.
        random(k) gives a different 0..1 value per cell for every k."""
        x, y = self.split_xy(pixel)
        idx = self.math("FLOOR", self.math("DIVIDE", x, cell_w))
        idy = self.math("FLOOR", self.math("DIVIDE", y, cell_h))
        local_x = self.math("SUBTRACT", x, self.math("MULTIPLY", idx, cell_w))
        local_y = self.math("SUBTRACT", y, self.math("MULTIPLY", idy, cell_h))
        cell = self.xyz(idx, idy)
        return local_x, local_y, (lambda seed, k: self.white_noise(cell, self.math("ADD", seed, float(k))))

    def line_texture(self, pixel, cell_w, cell_h, density, seed, angle, length, width_px):
        """Thin straight lines, one candidate per cell (each exists with probability `density`).
        angle / length: (min, max) in radians / pixels (numbers or sockets); width_px: line width.
        A line stays inside its own cell. Different `seed` = different lines."""
        lx, ly, rnd = self._cells(pixel, cell_w, cell_h)
        m = self.math
        theta = m("ADD", angle[0], m("MULTIPLY", rnd(seed, 3), m("SUBTRACT", angle[1], angle[0])))
        span = m("ADD", length[0], m("MULTIPLY", rnd(seed, 4), m("SUBTRACT", length[1], length[0])))
        dx = m("SUBTRACT", lx, m("MULTIPLY", rnd(seed, 1), cell_w))
        dy = m("SUBTRACT", ly, m("MULTIPLY", rnd(seed, 2), cell_h))
        cos, sin = m("COSINE", theta), m("SINE", theta)
        along = m("ADD", m("MULTIPLY", dx, cos), m("MULTIPLY", dy, sin))
        across = m("SUBTRACT", m("MULTIPLY", dy, cos), m("MULTIPLY", dx, sin))
        profile = m("SUBTRACT", 1.0, m("DIVIDE", m("ABSOLUTE", across), width_px), clamp=True)
        inside = m("LESS_THAN", m("ABSOLUTE", along), m("MULTIPLY", span, 0.5))
        exists = m("LESS_THAN", rnd(seed, 0), density)
        brightness = m("ADD", 0.5, m("MULTIPLY", rnd(seed, 5), 0.5))
        return m("MULTIPLY", m("MULTIPLY", profile, inside), m("MULTIPLY", exists, brightness))

    def speck_texture(self, pixel, cell, density, seed, radius_px):
        """Round dust specks, one candidate per square cell (probability `density`), radius up to radius_px."""
        lx, ly, rnd = self._cells(pixel, cell, cell)
        m = self.math
        dx = m("SUBTRACT", lx, m("MULTIPLY", rnd(seed, 1), cell))
        dy = m("SUBTRACT", ly, m("MULTIPLY", rnd(seed, 2), cell))
        dist = m("SQRT", m("ADD", m("MULTIPLY", dx, dx), m("MULTIPLY", dy, dy)))
        radius = m("MULTIPLY", radius_px, m("ADD", 0.35, m("MULTIPLY", rnd(seed, 3), 0.65)))
        speck = self.map_range(dist, radius, 0.0)
        return m("MULTIPLY", speck, m("LESS_THAN", rnd(seed, 0), density))

    def hair_texture(self, pixel, cell, density, seed, radius_px, width_px):
        """Short curved hairs (an arc of a circle of about radius_px), rare: one candidate per cell."""
        lx, ly, rnd = self._cells(pixel, cell, cell)
        m = self.math
        dx = m("SUBTRACT", lx, m("MULTIPLY", rnd(seed, 1), cell))
        dy = m("SUBTRACT", ly, m("MULTIPLY", rnd(seed, 2), cell))
        radius = m("MULTIPLY", radius_px, m("ADD", 0.6, m("MULTIPLY", rnd(seed, 3), 0.8)))
        dist = m("SQRT", m("ADD", m("MULTIPLY", dx, dx), m("MULTIPLY", dy, dy)))
        profile = m("SUBTRACT", 1.0, m("DIVIDE", m("ABSOLUTE", m("SUBTRACT", dist, radius)), width_px), clamp=True)
        start = m("SUBTRACT", m("MULTIPLY", rnd(seed, 4), 3.0), 2.0)       # arc start angle, -2 .. 1 rad
        turned = m("SUBTRACT", m("ARCTAN2", dy, dx), start)
        on_arc = m("MULTIPLY", m("GREATER_THAN", turned, 0.0), m("LESS_THAN", turned, 1.0))
        return m("MULTIPLY", m("MULTIPLY", profile, on_arc), m("LESS_THAN", rnd(seed, 0), density))

    def lit_by_highlights(self, image, texture, threshold, spread, cap=2.0):
        """Light to ADD for a texture that only shows near bright lights (lens dirt, lens scratches):
        the blurred, capped bright parts of the image (spread = fraction of the image width) times the
        0..1 float texture. Nothing bright in the image = black."""
        bright = self.bright_pass(image, threshold, 0.3, cap=cap)
        glow = self.blur(bright, self.relative_px(spread, image))
        return self.vmath("MULTIPLY", glow, self.xyz(texture, texture, texture))

    def tint(self, color, tint_color, amount=1.0):
        """Colour multiplied by tint_color, faded in by amount (0 = unchanged)."""
        return self.mix("MULTIPLY", color, tint_color, amount)

    def denoise(self, image, albedo=None, normal=None, hdr=True):
        """OpenImageDenoise; albedo / normal (e.g. Denoising Albedo / Normal passes) guide it."""
        n = self.node("CompositorNodeDenoise", Image=image, HDR=hdr)
        if albedo is not None:
            self.set(n.inputs["Albedo"], albedo)
        if normal is not None:
            self.set(n.inputs["Normal"], normal)
        return n.outputs[0]

    def add_over(self, base, extra, amount):
        """base + extra * amount (clamped to nothing: light adds beyond 1)."""
        return self.mix("ADD", base, extra, amount, clamp=True)


# ---------------------------------------------------------------------------
# Asset groups

def new_group(name, description, inputs, output="Image"):
    """(Re)create the compositor asset group `name`.

    inputs: [(name, socket type, default, extra)] where extra is a dict of min / max / description /
    subtype / panel (name of an interface panel the socket goes into, created on first use).
    One Color output called `output`. Returns (group, group input node, group output node)."""
    old = bpy.data.node_groups.get(name)
    if old:
        bpy.data.node_groups.remove(old)
    group = bpy.data.node_groups.new(name, "CompositorNodeTree")
    group.description = description
    group.interface.new_socket(output, in_out="OUTPUT", socket_type="NodeSocketColor")
    add_inputs(group, inputs)
    return group, group.nodes.new("NodeGroupInput"), group.nodes.new("NodeGroupOutput")


def add_inputs(group, inputs):
    """Add `inputs` (same entries as new_group) to the group's interface; an interface panel that
    already exists is reused, so this also extends a group that was built earlier."""
    panels = {p.name: p for p in group.interface.items_tree if p.item_type == "PANEL"}
    for sock_name, sock_type, default, extra in inputs:
        extra = dict(extra)
        panel_name = extra.pop("panel", None)
        if panel_name and panel_name not in panels:
            panels[panel_name] = group.interface.new_panel(panel_name)
        item = group.interface.new_socket(sock_name, in_out="INPUT", socket_type=sock_type,
                                          parent=panels.get(panel_name))
        if default is not None:
            item.default_value = default
        for key, value in extra.items():
            setattr(item, {"min": "min_value", "max": "max_value"}.get(key, key), value)


def sock(name, kind, default, description="", **extra):
    """Interface entry for new_group; kind is 'float', 'color', 'bool', 'vector' or 'int'."""
    types = {"float": "NodeSocketFloat", "color": "NodeSocketColor", "bool": "NodeSocketBool",
             "vector": "NodeSocketVector", "int": "NodeSocketInt"}
    return (name, types[kind], default, {"description": description, **extra})


def mark_group(group, description, tags):
    """Mark the group as a Compositor catalog asset (kept with a fake user). Scripts only: needs geonodes_common."""
    import geonodes_common as common   # noqa: PLC0415  (lives in the project's Scripts folder, not the add-on)
    common.mark_asset(group, description, tags, COMPOSITOR_CATALOG_ID)


def build_asset_file(make_group, default_file):
    """Build into an empty file and save it into the Library (geonodes_common.save_library; the
    argument after -- may give another path). Scripts only."""
    import geonodes_common as common   # noqa: PLC0415
    common.save_library(make_group, default_file)


# ---------------------------------------------------------------------------
# Effect presets (shared by Film Look and Lens Effects)

def preset_values(effects, presets, name):
    """{socket name: value} for every "<effect> On" / "<effect> Amount" socket: effects missing
    from presets[name] are off; presets[name] maps effect -> amount."""
    amounts = presets[name]
    values = {}
    for effect in effects:
        values[f"{effect} On"] = effect in amounts
        if effect in amounts:
            values[f"{effect} Amount"] = amounts[effect]
    return values


def apply_values(group_node, values):
    """Write {input name: value} onto a group node's inputs (the one value setter for presets and saved
    looks). Names the node doesn't have are skipped. Returns the names written."""
    written = []
    for socket_name, value in values.items():
        socket = group_node.inputs.get(socket_name)
        if socket is not None:
            socket.default_value = value
            written.append(socket_name)
    return written


def apply_preset(group_node, effects, presets, name):
    apply_values(group_node, preset_values(effects, presets, name))


def effect_sockets(panel, name, amount, on, amount_help):
    """The On + Amount sockets every effect has, in the interface panel `panel`."""
    return [sock(f"{name} On", "bool", on, f"Turn {name} on", panel=panel),
            sock(f"{name} Amount", "float", amount, amount_help, min=0.0, max=2.0, panel=panel)]


def effect_amount(t, gin, name):
    """Amount x On of an effect: 0 means the effect is exactly skipped."""
    return t.math("MULTIPLY", gin.outputs[f"{name} Amount"], gin.outputs[f"{name} On"])
