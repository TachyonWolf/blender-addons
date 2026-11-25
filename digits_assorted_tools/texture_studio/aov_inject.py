"""Shader AOVs for the Texture Studio: copy material values (Roughness, Metallic...) into AOV passes.

inject(materials) adds, in each material, one AOV Output node per value in maps.AOVS, fed from the
same links / values that feed the shader's own inputs, so Cycles writes them as render passes. The
shading is never touched: only new nodes and new links into those nodes are added.

How a value is found (generic, works on any material): walk back from the Material Output's Surface.
- a shader node in SHADERS gives the value from its input (linked socket or its default), or a
  best guess constant for shader types without that input (Diffuse = roughness 1, ...)
- Mix Shader: the two values are mixed with the same Fac (new Mix node); Add Shader: averaged
- a node group: walked into. The group is never edited in place: a temporary copy gets an extra
  output per value, and the group node is pointed at the copy until remove() puts it back
- anything else (Emission, Transparent, Holdout, unknown nodes) gives nothing, so a mix with it
  uses the other side's value

Linked (library) materials are edited in memory only and never saved: the capture never saves the
studio, and remove() undoes everything (it runs in a finally block). report() lists per material
what was found, so you can tell which maps to trust.
"""
import bpy

from . import maps

TAG = "texture_studio_aov"            # on every node / group copy this module adds
ORIGINAL_TREE = "texture_studio_original_tree"  # on group nodes pointed at a copy
NODE_PREFIX = "TS AOV"

# bl_idname -> {aov key: input name (str) | constant (float or rgba tuple)}. Keys missing -> no value.
_P = {k: n for k, (n, _kind) in maps.AOVS.items()}
SHADERS = {
    "ShaderNodeBsdfPrincipled": dict(_P),
    "ShaderNodeBsdfDiffuse": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "specular": 0.0},
    "ShaderNodeBsdfToon": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "specular": 0.0},
    "ShaderNodeBsdfTranslucent": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0, "specular": 0.0},
    "ShaderNodeBsdfGlossy": {"base_color": "Color", "roughness": "Roughness", "metallic": 1.0, "specular": 1.0},
    "ShaderNodeBsdfMetallic": {"base_color": "Base Color", "roughness": "Roughness", "metallic": 1.0,
                               "specular": 1.0},
    "ShaderNodeBsdfGlass": {"base_color": "Color", "roughness": "Roughness", "metallic": 0.0,
                            "transmission": 1.0},
    "ShaderNodeBsdfRefraction": {"base_color": "Color", "roughness": "Roughness", "metallic": 0.0,
                                 "transmission": 1.0},
    "ShaderNodeBsdfSheen": {"base_color": "Color", "roughness": "Roughness", "sheen": 1.0, "metallic": 0.0},
    "ShaderNodeSubsurfaceScattering": {"base_color": "Color", "roughness": 1.0, "metallic": 0.0,
                                       "subsurface": 1.0},
    "ShaderNodeBsdfHairPrincipled": {"base_color": "Color", "roughness": "Roughness", "metallic": 0.0,
                                     "coat": "Coat"},
    "ShaderNodeBsdfHair": {"base_color": "Color", "roughness": "RoughnessU", "metallic": 0.0},
}
EXACT = {"ShaderNodeBsdfPrincipled"}       # values read straight from the shader's own inputs
NO_VALUES = {"ShaderNodeEmission", "ShaderNodeBsdfTransparent", "ShaderNodeHoldout",
             "ShaderNodeBackground", "ShaderNodeVolumePrincipled", "ShaderNodeVolumeScatter",
             "ShaderNodeVolumeAbsorption"}
HAIR = {"ShaderNodeBsdfHairPrincipled", "ShaderNodeBsdfHair"}
EEVEE_ONLY = {"ShaderNodeShaderToRGB"}


class _Walk:
    """Notes from walking one material: which shader types were met, and what was guessed."""

    def __init__(self):
        self.exact, self.guessed, self.skipped, self.unknown = set(), set(), set(), set()


def _socket(node, identifier):
    return next(s for s in node.inputs if s.identifier == identifier)


def _out(node, identifier):
    return next(s for s in node.outputs if s.identifier == identifier)


def _tag(node):
    node[TAG] = True
    node.name = node.label = f"{NODE_PREFIX} {node.bl_idname[10:]}"
    return node


def _source(socket):
    """The output socket feeding an input (through reroutes), or None."""
    while socket.is_linked:
        link = socket.links[0]
        if not link.is_valid or link.is_muted:
            return None
        src = link.from_socket
        if src.node.bl_idname == "NodeReroute":
            socket = src.node.inputs[0]
            continue
        return src
    return None


def _input_value(socket, kind):
    """('socket', output) when linked, else ('const', default value) for one shader input."""
    src = _source(socket)
    if src is not None:
        return ("socket", src)
    value = socket.default_value
    if kind == "COLOR":
        value = tuple(value) if hasattr(value, "__len__") else (value, value, value, 1.0)
    return ("const", value)


def _set_or_link(tree, target, value):
    kind, v = value
    if kind == "socket":
        tree.links.new(v, target)
    else:
        target.default_value = v


def _lerp(a, b, t):
    if isinstance(a, tuple):
        return tuple(x + (y - x) * t for x, y in zip(a, b))
    return a + (b - a) * t


def _mix(tree, factor, a, b, kind):
    """Value mixed like the shaders are; folded to a constant when nothing varies (keeps the map check
    able to predict uniform maps)."""
    if a[0] == b[0] == "const":
        if a[1] == b[1]:
            return a
        if factor[0] == "const":
            return ("const", _lerp(a[1], b[1], min(max(factor[1], 0.0), 1.0)))
    node = _tag(tree.nodes.new("ShaderNodeMix"))
    node.data_type = "RGBA" if kind == "COLOR" else "FLOAT"
    node.clamp_factor = True
    suffix = "Color" if kind == "COLOR" else "Float"
    _set_or_link(tree, _socket(node, "Factor_Float"), factor)
    _set_or_link(tree, _socket(node, "A_" + suffix), a)
    _set_or_link(tree, _socket(node, "B_" + suffix), b)
    return ("socket", _out(node, "Result_" + suffix))


class Injector:
    """Adds the AOV nodes; one instance per inject() run (shares group copies between materials)."""

    def __init__(self):
        self.copies = {}   # original group tree -> its temporary copy
        self.outputs = {}  # (copy name, output identifier, key) -> (value in the copy, notes)

    # -- walking ---------------------------------------------------------------------------
    def value(self, tree, src, key, notes):
        """Value of aov key for the shader coming out of output socket src, or None."""
        if src is None:
            return None
        node, kind = src.node, maps.AOVS[key][1]
        idname = node.bl_idname
        if idname in SHADERS:
            spec = SHADERS[idname].get(key)
            (notes.exact if idname in EXACT else notes.guessed).add(node.bl_label)
            if idname in HAIR:
                notes.skipped.add("hair shader")
            if spec is None:
                return None
            if isinstance(spec, str):
                if spec not in node.inputs:
                    return None
                return _input_value(node.inputs[spec], kind)
            if kind == "COLOR" and not isinstance(spec, tuple):
                spec = (spec, spec, spec, 1.0)
            return ("const", spec)
        if idname == "ShaderNodeMixShader":
            a = self.value(tree, _source(node.inputs[1]), key, notes)
            b = self.value(tree, _source(node.inputs[2]), key, notes)
            if a is None or b is None:
                return a or b
            return _mix(tree, _input_value(node.inputs[0], "VALUE"), a, b, kind)
        if idname == "ShaderNodeAddShader":
            a = self.value(tree, _source(node.inputs[0]), key, notes)
            b = self.value(tree, _source(node.inputs[1]), key, notes)
            if a is None or b is None:
                return a or b
            return _mix(tree, ("const", 0.5), a, b, kind)
        if idname == "ShaderNodeGroup" and node.node_tree is not None:
            return self.group_value(tree, node, src, key, notes)
        if idname in NO_VALUES:
            notes.skipped.add(node.bl_label)
            return None
        notes.unknown.add(node.bl_label)
        return None

    def group_value(self, tree, node, src, key, notes):
        original = node.get(ORIGINAL_TREE) or node.node_tree
        copy = self.copy_of(original)
        if node.node_tree is not copy:
            node[ORIGINAL_TREE] = original
            node.node_tree = copy
            src = next(o for o in node.outputs if o.identifier == src.identifier)
        cache_key = (copy.name, src.identifier, key)
        if cache_key not in self.outputs:
            self.outputs[cache_key] = self.walk_group(copy, src.identifier, key)
        inner, walk = self.outputs[cache_key]
        for name in ("exact", "guessed", "skipped", "unknown"):  # shared groups report in every material
            getattr(notes, name).update(getattr(walk, name))
        if inner is not None and inner[0] == "output":
            return ("socket", next(o for o in node.outputs if o.identifier == inner[1]))
        return inner

    def walk_group(self, copy, identifier, key):
        """(value inside the group copy as ('output', interface id) / ('const', v) / None, notes)."""
        walk = _Walk()
        outs = [n for n in copy.nodes if n.bl_idname == "NodeGroupOutput"]
        group_out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
        inner_in = next((s for s in group_out.inputs if s.identifier == identifier), None) if group_out else None
        inner = self.value(copy, _source(inner_in), key, walk) if inner_in else None
        if inner is not None and inner[0] == "socket":
            kind = maps.AOVS[key][1]
            socket_type = "NodeSocketColor" if kind == "COLOR" else "NodeSocketFloat"
            item = copy.interface.new_socket(f"{NODE_PREFIX} {key} {identifier}", in_out="OUTPUT",
                                             socket_type=socket_type)
            copy.links.new(inner[1], next(s for s in group_out.inputs if s.identifier == item.identifier))
            inner = ("output", item.identifier)
        return inner, walk

    def copy_of(self, group):
        if group not in self.copies:
            copy = group.copy()
            copy.name = f"{NODE_PREFIX} {group.name}"
            copy[TAG] = True
            copy.use_fake_user = False
            self.copies[group] = copy
        return self.copies[group]

    # -- one material ----------------------------------------------------------------------
    def inject(self, material):
        tree = material.node_tree if material.use_nodes else None
        notes = _Walk()
        found, consts = {}, {}  # key -> 'socket' / 'const'; key -> constant value
        output = tree.get_output_node("CYCLES") if tree else None
        if output is None:
            return {"material": material.name, "found": found, "consts": {}, "notes": notes,
                    "eevee_only": False, "linked": bool(material.library)}
        for key, (_input, kind) in maps.AOVS.items():
            # looked up per key: pointing a group node at its copy rebuilds its sockets
            value = self.value(tree, _source(output.inputs["Surface"]), key, notes)
            if value is None:
                continue
            aov = _tag(tree.nodes.new("ShaderNodeOutputAOV"))
            aov.name = aov.label = f"{NODE_PREFIX} {key}"
            aov.aov_name = maps.aov_name(key)
            aov.location = output.location.x, output.location.y - 160 - 60 * len(found)
            _set_or_link(tree, aov.inputs["Color" if kind == "COLOR" else "Value"], value)
            found[key] = value[0]
            if value[0] == "const":
                consts[key] = value[1]
        return {"material": material.name, "found": found, "consts": consts, "notes": notes,
                "eevee_only": _uses(tree, EEVEE_ONLY), "linked": bool(material.library or material.override_library)}


def _uses(tree, idnames, seen=None):
    seen = seen if seen is not None else set()
    for node in tree.nodes:
        if node.bl_idname in idnames:
            return True
        if node.bl_idname == "ShaderNodeGroup" and node.node_tree and node.node_tree not in seen:
            seen.add(node.node_tree)
            if _uses(node.node_tree, idnames, seen):
                return True
    return False


def inject(materials):
    """Add AOV outputs to every material; returns one result dict per material (see report())."""
    remove(materials)  # never stack two runs
    injector = Injector()
    return [injector.inject(m) for m in materials if m is not None]


def remove(materials=None):
    """Undo inject(): delete the added nodes, point group nodes back, delete the group copies."""
    materials = materials if materials is not None else bpy.data.materials
    for material in materials:
        tree = material.node_tree if material and material.use_nodes else None
        if tree is None:
            continue
        for node in list(tree.nodes):
            if node.get(TAG):
                tree.nodes.remove(node)
            elif node.get(ORIGINAL_TREE) is not None:
                node.node_tree = node[ORIGINAL_TREE]
                del node[ORIGINAL_TREE]
    copies = [g for g in bpy.data.node_groups if g.get(TAG)]
    if copies:
        bpy.data.batch_remove(copies)


def status(result):
    """'exact' (all values read from Principled inputs), 'guess', 'partial', 'none' or 'eevee'."""
    notes, found = result["notes"], result["found"]
    if result["eevee_only"]:
        return "eevee"
    if not found:
        return "none"
    if notes.unknown or notes.skipped - {"Emission", "Transparent BSDF", "Holdout"}:
        return "partial"
    if notes.guessed:
        return "guess"
    if len(found) < len(maps.AOVS):
        return "partial"
    return "exact"


STATUS_TEXT = {
    "exact": "values read from the Principled BSDF (through mixes and groups)",
    "guess": "non-Principled shader: best-guess values (e.g. Diffuse = roughness 1, Glossy = metallic 1)",
    "partial": "some shaders gave no values (unknown node or hair shader): those parts read 0",
    "none": "no usable shader found: reads 0 (black) in every value map",
    "eevee": "uses Shader to RGB (EEVEE only): Cycles renders this material differently",
}
