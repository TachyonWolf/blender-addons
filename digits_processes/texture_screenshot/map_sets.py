# SPDX-License-Identifier: GPL-3.0-or-later
"""Which Texture Studio maps a screenshot captures, and which decal role each one fills (plain data, no bpy).

Colour maps come from the Map Set (Simple / Baked Lighting / Custom ticks); Surface Detail adds one detail map;
Extra Maps (Glow, Roughness, Metallic, Alpha Mask) each add one more map, captured in the same render.
Glass is see-through adds mask + transmission and combines them into the decal's alpha (glass_alpha.py).
Map names are the studio's (texture_studio/maps.py); role ids are the Decals' (decal_maps.ROLES).
"""

SIMPLE, BAKED, CUSTOM = "SIMPLE", "BAKED", "CUSTOM"
MAP_SET_ITEMS = [
    (SIMPLE, "Simple", "Flat surface colour (albedo): no light at all"),
    (BAKED, "Baked Lighting", "Colour lit by the studio light (matte or beauty)"),
    (CUSTOM, "Custom", "Tick the maps you want"),
]
LIGHTING_ITEMS = [
    ("matte", "Matte", "Studio light without highlights: safe in lit rooms"),
    ("beauty", "Beauty", "Full render with highlights"),
]
DETAIL_ITEMS = [
    ("NONE", "None", "No surface detail map"),
    ("NORMALS", "Normals", "The studio's normal map: the decal's Normal"),
    ("HEIGHT", "Height + Bump", "The studio's depth map as a height map: the decal turns it into bump"),
]
DETAIL_MAP = {"NONE": None, "NORMALS": "normal", "HEIGHT": "depth"}

# Extra Maps tick boxes: (option, label, studio map, default, description). The card makes one checkbox
# "extra_<option>" per entry; Glow is skipped at run time when the target has no glowing material.
EXTRA_MAPS = [
    ("glow", "Glow", "emission", True, "Glowing parts (eyes, markings) glow on the decal too. Skipped when "
                                       "nothing in the target glows"),
    ("roughness", "Roughness", "roughness", False, "Shiny and rough parts of the materials, on the decal"),
    ("metallic", "Metallic", "metallic", False, "Metal parts of the materials, on the decal"),
    ("alpha", "Alpha Mask", "mask", False, "A separate cutout mask (the colour map already has alpha)"),
]
GLOW_MAP = "emission"

# studio map -> decal role. Maps not listed are saved as images but not put on the decal.
ROLE_OF_MAP = {
    "albedo": "COLOR", "shaded_albedo": "COLOR", "matte": "COLOR", "beauty": "COLOR", "base_color": "COLOR",
    "emission": "GLOW", "normal": "NORMAL", "roughness": "ROUGHNESS", "metallic": "METAL", "mask": "ALPHA",
    "depth": "HEIGHT",
}


# Colour maps that already hold the studio's light: their decal is Unlit, so the scene doesn't light it twice.
LIT_COLOUR_MAPS = {"matte", "beauty", "shaded_albedo"}


def decal_shading(colour_map_names):
    """"UNLIT" when the decal's colour map has the studio light baked in, else "LIT"."""
    return "UNLIT" if any(name in LIT_COLOUR_MAPS for name in colour_map_names) else "LIT"


def parse_custom(text):
    """The Custom ticks, stored as "albedo,normal"."""
    return [name for name in (part.strip() for part in text.split(",")) if name]


def toggle_custom(text, name):
    names = parse_custom(text)
    names = [other for other in names if other != name] if name in names else names + [name]
    return ",".join(names)


def colour_maps(map_set, lighting="matte", custom=""):
    if map_set == SIMPLE:
        return ["albedo"]
    if map_set == BAKED:
        return [lighting]
    return parse_custom(custom)


def extra_option(option):
    return "extra_" + option


def ticked_extras(owner):
    """The studio maps of the ticked Extra Maps checkboxes of `owner` (the card's options)."""
    return [studio_map for option, _label, studio_map, _default, _text in EXTRA_MAPS
            if getattr(owner, extra_option(option))]


def studio_maps(map_set, lighting, custom, detail, known_names, extras=()):
    """The studio maps to capture, in the studio's own order (known_names = maps.MAP_NAMES; extras = studio maps
    from Extra Maps)."""
    wanted = set(colour_maps(map_set, lighting, custom)) | set(extras)
    if DETAIL_MAP.get(detail):
        wanted.add(DETAIL_MAP[detail])
    unknown = sorted(wanted - set(known_names))
    if unknown:
        raise ValueError(f"unknown studio maps {unknown}")
    if not wanted:
        raise ValueError("tick at least one map")
    return [name for name in known_names if name in wanted]


def decal_roles(map_names, colour_first=()):
    """{role: map} for the decal: the first map per role. `colour_first` (the Map Set's colour maps) wins COLOR."""
    ordered = [name for name in colour_first if name in map_names] + [n for n in map_names if n not in colour_first]
    roles = {}
    for name in ordered:
        role = ROLE_OF_MAP.get(name)
        if role and role not in roles:
            roles[role] = name
    return roles
