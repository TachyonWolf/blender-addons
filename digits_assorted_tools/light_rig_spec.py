# SPDX-License-Identifier: GPL-3.0-or-later
"""Lighting Rig: the one place for its styles (Single Overhead, Three Point, Clamshell, ...), and per style
its names, lights, slider definitions, defaults, presets and which light fields each slider drives. Plain
data (no bpy), used by the builder (Scripts/light_rig/build_light_rig.py), the sidebar panel (light_rig.py)
and the tests.

A style is one `style(...)` entry in STYLES: its lights (`light(...)`: where it sits, how soft, how warm,
how bright compared with the first, main light) and its presets. Every rig of every style has the same
structure (Rig > Focus > <Light>Orbit > <Light>, all lights aim at the Focus) and the same kind of sliders,
so adding a style is one entry here plus a build of its asset; no new code paths."""

from math import cos, pi, radians

ROOT_TAG = "tpl2_rig"        # on the rig root; pointers to the parts are "tpl2_<part>" (the name dates from Three Point Light)
PART_TAG = "tpl2_part"       # on every rig object: its part name
UNLOCKED_PROP = "tpl2_unlocked"  # set by Unlock: the lights have no drivers
STYLE_PROP = "tpl2_style"    # on the rig root: its style id; rigs made before styles have none (= Three Point)

SUBJECT_HEIGHT = 1.8   # at rig scale 1 the rig fits a subject this tall (m)
FOCUS_HEIGHT = 1.3     # Focus height above the rig root at scale 1 (m)
# Every style's default main brightness is set so its lights together give a standing figure this much light
# on the side the camera sees (subject_light), so switching styles keeps about the same subject brightness
SUBJECT_LIGHT = 1.4
TAGS = ("Light", "Lighting", "Rig")


def prop_def(name, default, lo, hi, soft=None, subtype="NONE", description=""):
    soft_lo, soft_hi = soft or (lo, hi)
    return {"name": name, "default": default, "min": lo, "max": hi, "soft_min": soft_lo,
            "soft_max": soft_hi, "subtype": subtype, "description": description}


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------

# How a light's brightness slider works. The first light of a style is the main one ("main"); the others
# follow it, as a main-to-light ratio ("ratio", the slider "<Light> Ratio") or a multiple ("times").
POWER_KINDS = ("main", "ratio", "times")


def light(name, role, swing, height, softness, temperature, shadow, power=None, kind="main", aspect=None):
    """One light of a style. Angles in degrees; softness = size / distance to the Focus; power: the
    default of its brightness slider (see POWER_KINDS; the main light's is left out: style() works it out
    from SUBJECT_LIGHT); aspect: a rectangle light whose height is this many times its width (5 = a tall
    strip, 0.4 = a wide one; None: square)."""
    assert kind in POWER_KINDS
    return {"name": name, "role": role, "swing": swing, "height": height, "softness": softness,
            "temperature": temperature, "shadow": shadow, "power": power, "kind": kind, "aspect": aspect}


def power_name(lt):
    return f"{lt['name']} Ratio" if lt["kind"] == "ratio" else f"{lt['name']} Strength"


def _power_prop(lt, main, alone):
    name = power_name(lt)
    if lt["kind"] == "main":
        return prop_def(name, lt["power"], 0.0, 1000.0, (0.0, 20.0), description=(
            f"Brightness of the {lt['role']} where it hits the subject (like a Sun strength)"
            + ("" if alone else ". The other lights follow it")))
    if lt["kind"] == "ratio":
        return prop_def(name, lt["power"], 1.0, 100.0, (1.0, 16.0), description=(
            f"{main['name']}-to-{lt['name'].lower()} ratio: 3 = the {lt['role']} is a third of the {main['role']}. "
            "Low = flat, high = dramatic shadows"))
    return prop_def(name, lt["power"], 0.0, 100.0, (0.0, 5.0), description=(
        f"Brightness of the {lt['role']} as a multiple of the {main['role']}: 1 = as bright as it"))


def _light_props(lt, main, alone):
    """The sliders of one light; angles in degrees here (stored as radians)."""
    name, side = lt["name"], lt["role"]
    return [
        _power_prop(lt, main, alone),
        prop_def(f"{name} Swing", lt["swing"], -180.0, 180.0, subtype="ANGLE",
           description=f"Turns the {side} around the subject: 0 = at the camera (rig -Y side), "
                       "positive = to the camera's left, 180 = straight behind"),
        prop_def(f"{name} Height", lt["height"], -89.0, 89.0, (-60.0, 89.0), "ANGLE",
           f"How high the {side} sits above the Focus, as an angle (0 = level, 89 = straight overhead, "
           "negative = below, aimed up)"),
        prop_def(f"{name} Softness", lt["softness"], 0.01, 3.0, (0.02, 1.5),
           description=f"Size of the {side} as a fraction of its distance to the Focus: small = "
                       "crisp shadows and highlights, large = soft. Stays the same at any rig scale"),
        prop_def(f"{name} Temperature", lt["temperature"], 800.0, 20000.0, (2000.0, 12000.0), "TEMPERATURE",
           f"Colour temperature of the {side} in Kelvin: lower = warmer (orange), higher = cooler (blue)"),
        prop_def(f"{name} Tint", (1.0, 1.0, 1.0), 0.0, 1.0, subtype="COLOR",
           description=f"Extra colour multiplied onto the {side}; white = temperature only"),
        prop_def(f"{name} Shadow", lt["shadow"], False, True,
           description=f"Whether the {side} casts shadows"),
    ]


def relative_power(lt):
    """A light's default brightness at the Focus as a fraction of the main light's."""
    if lt["kind"] == "main":
        return 1.0
    return 1.0 / lt["power"] if lt["kind"] == "ratio" else lt["power"]


def subject_light(lights):
    """Light on the side the camera sees of a standing figure at the Focus, per unit of main brightness: each
    light's brightness times the average of max(0, n.l) over that side, half for a head (a sphere's camera
    hemisphere: (1 + cos(Height) cos(Swing)) / 4) and half for a body (a vertical cylinder's camera half:
    cos(Height) (1 + cos(Swing)) / pi). A light straight overhead lights the head but hardly the body."""
    def facing(lt):
        h, a = radians(lt["height"]), radians(lt["swing"])
        return ((1 + cos(h) * cos(a)) / 4 + max(cos(h), 0.0) * (1 + cos(a)) / pi) / 2
    return sum(relative_power(lt) * facing(lt) for lt in lights)


def _energy(lt, main):
    """(expression, variables) of a light's power; d = distance to the Focus (m, world)."""
    tail = "pow(2, ev) * pi * d * d"
    base = {"s": power_name(main), "ev": "Exposure"}
    if lt["kind"] == "main":
        return f"s * {tail}", base
    if lt["kind"] == "ratio":
        return f"s / max(r, 0.01) * {tail}", {**base, "r": power_name(lt)}
    return f"s * r * {tail}", {**base, "r": power_name(lt)}


def _driven_fields(lt, main):
    name = lt["name"]
    expr, energy_vars = _energy(lt, main)
    size = "soft * d / max(sc, 0.0001)"
    fields = [("light", "energy", -1, expr, energy_vars),
              ("light", "size", -1, size, {"soft": f"{name} Softness"})]
    if lt["aspect"]:
        fields.append(("light", "size_y", -1, f"{size} * {lt['aspect']}", {"soft": f"{name} Softness"}))
    return fields + [
        ("light", "temperature", -1, "t", {"t": f"{name} Temperature"}),
        *[("light", "color", i, "c", {"c": (f"{name} Tint", i)}) for i in range(3)],
        ("light", "use_shadow", -1, "v", {"v": f"{name} Shadow"}),
        ("orbit", "rotation_euler", 0, "-h", {"h": f"{name} Height"}),
        ("orbit", "rotation_euler", 2, "-a", {"a": f"{name} Swing"}),
    ]


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def style(id, label, asset, library, prefix, tooltip, lights, presets, preset_info, distance=4.0):
    """One Lighting Rig style. presets: {name: {slider: value}}; the first preset is the defaults (its dict
    stays empty), the others list only what they change from the defaults (Exposure, the main brightness,
    tints and shadows are never part of a preset). distance: the lights' starting distance from the Focus
    at rig scale 1 (m). Objects are named <prefix>_Rig, <prefix>_Focus, <prefix>_<Light>(Orbit)."""
    main = {**lights[0], "power": round(SUBJECT_LIGHT / subject_light(lights), 2)}
    lights = [main, *lights[1:]]
    props = [prop_def("Exposure", 0.0, -10.0, 10.0, (-4.0, 4.0),
                      description="Overall brightness of all the lights in stops: +1 doubles, -1 halves")]
    for lt in lights:
        props += _light_props(lt, main, len(lights) == 1)
    names = [p["name"] for p in props]
    by_name = {p["name"]: p for p in props}
    preset_keys = [n for n in names if n not in ("Exposure", power_name(main))
                   and not n.endswith((" Tint", " Shadow"))]
    assert all(set(changes) <= set(preset_keys) for changes in presets.values()), f"{id}: unknown preset slider"
    defaults = {n: by_name[n]["default"] for n in preset_keys}
    return {
        "id": id, "label": label, "asset": asset, "library": library, "prefix": prefix, "tooltip": tooltip,
        "lights": tuple(lt["name"] for lt in lights), "light_defs": {lt["name"]: lt for lt in lights},
        "distance": distance, "props": props, "prop_names": names, "prop_by_name": by_name,
        "preset_keys": preset_keys, "presets": {n: {**defaults, **changes} for n, changes in presets.items()},
        "preset_info": preset_info,
        "brightness": ["Exposure"] + [power_name(lt) for lt in lights],
        "fields": {lt["name"]: _driven_fields(lt, main) for lt in lights},
        "description": (f"{label} lighting rig: {tooltip} Edit it on {prefix}_Rig (Object Properties > Custom "
                        "Properties, or the Selected card in Digit's Tools), or press Unlock in the sidebar to edit "
                        "the lights directly. Brightness at the subject stays the same when you move a light or "
                        "scale the rig."),
        "tags": TAGS + (label,),
    }


STYLES = (
    style("SINGLE_OVERHEAD", "Single Overhead", "Single Overhead Light", "SingleOverheadLight.blend", "Overhead",
          "One big soft light above the subject, leaning slightly towards the camera: a top-to-bottom gradient "
          "and a pool of light on the floor. Simple and clean, good with a Photo Backdrop.",
          [light("Top", "top light", 0.0, 75.0, 1.2, 5600.0, True)],
          {"Soft Top": {},
           "Hero Top": {"Top Height": 86.0, "Top Softness": 0.5},
           "Butterfly": {"Top Height": 50.0, "Top Softness": 0.7}},
          {"Soft Top": "Big soft box high above, leaning about 10 degrees towards the camera: bright head and shoulders falling off downwards, the light pooled around the feet.",
           "Hero Top": "Almost straight overhead and smaller: a stark top-to-bottom gradient, deep shadows under brows and chin.",
           "Butterfly": "High in front of the face (Paramount / butterfly light): a small shadow under the nose, "
                        "flattering and symmetrical."},
          distance=2.2),
    style("THREE_POINT", "Three Point", "Three Point Light", "ThreePointLight.blend", "TPL2",
          "Key, fill and rim lights: the classic portrait setup.",
          [light("Key", "main light", 40.0, 35.0, 0.35, 5200.0, True),
           light("Fill", "fill light", -55.0, 15.0, 0.7, 7000.0, False, 3.0, "ratio"),
           light("Rim", "rim (back) light", -135.0, 30.0, 0.2, 8000.0, True, 2.0, "times")],
          {"Portrait": {},
           "Dramatic": {
               "Key Swing": 65.0, "Key Height": 45.0, "Key Softness": 0.2, "Key Temperature": 4300.0,
               "Fill Swing": -60.0, "Fill Height": 10.0, "Fill Ratio": 8.0, "Fill Softness": 0.6,
               "Fill Temperature": 8500.0, "Rim Swing": -140.0, "Rim Height": 35.0, "Rim Strength": 2.5,
               "Rim Softness": 0.1, "Rim Temperature": 9500.0},
           "Toon Flat": {
               "Key Swing": 25.0, "Key Height": 30.0, "Key Softness": 0.6, "Key Temperature": 5600.0,
               "Fill Swing": -45.0, "Fill Height": 10.0, "Fill Ratio": 1.5, "Fill Softness": 0.9,
               "Fill Temperature": 6500.0, "Rim Swing": -140.0, "Rim Height": 25.0, "Rim Strength": 2.0,
               "Rim Softness": 0.15, "Rim Temperature": 7500.0},
           "Toon Hard": {
               "Key Swing": 45.0, "Key Height": 40.0, "Key Softness": 0.04, "Key Temperature": 5400.0,
               "Fill Swing": -55.0, "Fill Height": 15.0, "Fill Ratio": 2.5, "Fill Softness": 0.3,
               "Fill Temperature": 7000.0, "Rim Swing": -135.0, "Rim Height": 30.0, "Rim Strength": 2.0,
               "Rim Softness": 0.04, "Rim Temperature": 8000.0}},
          {"Portrait": "Soft, flattering light: key from the side and above, a gentle fill at 3:1, a warm key and a cool rim. "
                       "A safe start for most characters.",
           "Dramatic": "High, crisp key with a weak fill (8:1) and a strong rim: deep shadows and a moody look. "
                       "Use for tension, villains, night scenes.",
           "Toon Flat": "Very even light (1.5:1) with a thin strong rim: shapes read clearly and shadows stay light. "
                        "Use for cartoon and flat-shaded looks.",
           "Toon Hard": "Small, crisp light sources that give sharp shadow edges. Use for graphic, comic-style shading."},
          distance=3.0),
    style("CLAMSHELL", "Clamshell", "Clamshell Light", "ClamshellLight.blend", "Clamshell",
          "Beauty light: a soft key above the camera aimed down and a weaker soft fill below it aimed up, "
          "opening the shadows under the eyes and chin.",
          [light("Key", "top light", 0.0, 40.0, 0.6, 5600.0, True),
           light("Fill", "bottom fill", 0.0, -20.0, 0.8, 5600.0, False, 3.0, "ratio", aspect=0.4)],
          {"Beauty": {}, "Bright Beauty": {"Fill Ratio": 1.5, "Key Softness": 0.8}},
          {"Beauty": "Classic clamshell: key above the lens, fill from below at 3:1. Smooth skin, bright eyes.",
           "Bright Beauty": "Fill almost as bright as the key (1.5:1): nearly shadowless, glossy-magazine look."},
          distance=2.0),
    style("RIM_PAIR", "Rim Pair", "Rim Pair Light", "RimPairLight.blend", "RimPair",
          "Two edge lights (kickers) behind the subject, left and right, outlining it, plus a soft weak front fill.",
          [light("Left", "left rim light", 130.0, 12.0, 0.15, 7000.0, True),
           light("Right", "right rim light", -130.0, 12.0, 0.15, 7000.0, True, 1.0, "times"),
           light("Fill", "front fill", 0.0, 10.0, 0.9, 5600.0, False, 4.0, "ratio")],
          {"Edges": {}, "Cool Edges": {"Left Temperature": 10000.0, "Right Temperature": 10000.0, "Fill Ratio": 10.0}},
          {"Edges": "Both rims equal, a gentle front fill (6:1): bright outlines, the face still readable.",
           "Cool Edges": "Blue-white rims with a very weak fill: a cold, graphic silhouette."},
          distance=3.0),
    style("REMBRANDT", "Rembrandt", "Rembrandt Light", "RembrandtLight.blend", "Rembrandt",
          "Low-key light: one strong, fairly small key about 45 degrees to the side and 40 degrees up, a very "
          "weak fill. Dramatic shadows with a small triangle of light on the far cheek.",
          [light("Key", "main light", 45.0, 40.0, 0.2, 4800.0, True),
           light("Fill", "fill light", -60.0, 5.0, 0.8, 6500.0, False, 12.0, "ratio")],
          {"Rembrandt": {}, "Chiaroscuro": {"Fill Ratio": 40.0, "Key Softness": 0.12, "Key Height": 45.0}},
          {"Rembrandt": "Painterly key from the side and above, fill at 12:1: deep but not black shadows.",
           "Chiaroscuro": "Almost no fill (40:1) and a crisper key: the shadow side falls into darkness."},
          distance=3.0),
    style("PRODUCT", "Product", "Product Light", "ProductLight.blend", "Product",
          "Turntable light: a big soft top light plus two tall strip lights at the sides. Even and clean, with "
          "long highlights down the edges.",
          [light("Top", "top light", 0.0, 80.0, 1.2, 5600.0, True),
           light("Left", "left strip light", 90.0, 0.0, 0.2, 5600.0, False, 0.6, "times", aspect=3.5),
           light("Right", "right strip light", -90.0, 0.0, 0.2, 5600.0, False, 0.6, "times", aspect=3.5)],
          {"Clean": {}, "Contrast": {"Right Strength": 0.25, "Top Height": 70.0}},
          {"Clean": "Both strips equal: an even, shadowless product look with clean edge highlights.",
           "Contrast": "Right strip dimmed and the top light leaning forward: more shape and depth."},
          distance=3.0),
)
STYLE_BY_ID = {s["id"]: s for s in STYLES}
DEFAULT_STYLE = "THREE_POINT"        # a rig without STYLE_PROP (made before styles) is a Three Point Light
BACKDROP_STYLE = "SINGLE_OVERHEAD"   # Photo Backdrop's default
NO_STYLE = "NONE"                    # Photo Backdrop's "no lighting rig" choice

# Every slider by name, across styles (a name means the same kind of slider in every style)
_ALL_PROPS = {}
for _s in STYLES:
    for _p in _s["props"]:
        assert _ALL_PROPS.setdefault(_p["name"], _p)["subtype"] == _p["subtype"], _p["name"]
ALL_LIGHTS = tuple(dict.fromkeys(name for s in STYLES for name in s["lights"]))   # every light name, once


def style_items():
    """EnumProperty items for the Style dropdown, with tooltips."""
    return [(s["id"], s["label"], s["tooltip"]) for s in STYLES]


def preset_items(style_id=DEFAULT_STYLE):
    """EnumProperty items for a style's presets, with tooltips."""
    s = STYLE_BY_ID[style_id]
    return [(n, n, s["preset_info"][n]) for n in s["presets"]]


def all_preset_items():
    """Every preset of every style, once (the preset operator's items)."""
    seen = {}
    for s in STYLES:
        for n in s["presets"]:
            seen.setdefault(n, (n, n, s["preset_info"][n]))
    return list(seen.values())


def default_preset(style_id):
    return next(iter(STYLE_BY_ID[style_id]["presets"]))


def stored(name, value):
    """A spec-unit value as stored in the custom property (angles in radians)."""
    if _ALL_PROPS[name]["subtype"] == "ANGLE":
        return radians(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def driven_fields(light_name, style_id=DEFAULT_STYLE):
    """[(target, data_path, index, expression, {var: prop name | (prop name, index)})] for one light.

    target is "light" (the light datablock) or "orbit" (its <prefix>_<Light>Orbit pivot). Two extra
    variables exist on every light field: d (light-to-Focus distance, world) and sc (rig scale).
    Energy = strength * pi * d^2 keeps the brightness at the subject constant (area light, Normalize
    on: irradiance = power / (pi d^2)); size = softness * d / sc keeps softness at any scale."""
    return STYLE_BY_ID[style_id]["fields"][light_name]


# The Three Point style's tables under their old names (texture studio, inspect files, older scripts)
_TPL = STYLE_BY_ID["THREE_POINT"]
ASSET_NAME, LIBRARY_FILE, LIGHTS = _TPL["asset"], _TPL["library"], _TPL["lights"]
PROPS, PROP_NAMES, PROP_BY_NAME = _TPL["props"], _TPL["prop_names"], _TPL["prop_by_name"]
PRESET_KEYS, PRESETS, PRESET_INFO, DESCRIPTION = _TPL["preset_keys"], _TPL["presets"], _TPL["preset_info"], _TPL["description"]
LIGHT_DISTANCE = _TPL["distance"]
