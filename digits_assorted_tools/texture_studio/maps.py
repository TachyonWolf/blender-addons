"""Texture Studio: the one list of maps it writes (plain data, no bpy).

Each map: what it is for, PNG depth, colour mode, and how colours are saved:
  scene    = the scene's View Transform + Look (Khronos PBR Neutral, Medium High Contrast): a "photo"
  standard = View Transform Standard, no Look: true colours that load back 1:1 as an sRGB texture
  raw      = View Transform Raw: data (normals, roughness, masks); load as Non-Color
The compositor (compositor.py), the panel / capture (studio.py), the test and the notes doc
(notes/wip/texture-studio.md) all read this list.
"""

# key -> (Principled BSDF input it copies, AOV type). The AOV pass is called aov_name(key).
AOVS = {
    "base_color": ("Base Color", "COLOR"),
    "roughness": ("Roughness", "VALUE"),
    "metallic": ("Metallic", "VALUE"),
    "specular": ("Specular IOR Level", "VALUE"),
    "subsurface": ("Subsurface Weight", "VALUE"),
    "transmission": ("Transmission Weight", "VALUE"),
    "coat": ("Coat Weight", "VALUE"),
    "sheen": ("Sheen Weight", "VALUE"),
}


def aov_name(key):
    return "ts_" + key


def _map(name, what, colors="raw", depth="16", mode="RGBA"):
    return {"name": name, "what": what, "colors": colors, "depth": depth, "mode": mode}


MAPS = [
    _map("beauty", "full render with the studio lights, highlights and all", "scene"),
    _map("matte", "lit by the studio light without any specular: denoised (Diffuse Direct + Indirect) "
                  "x Diffuse Color + (Transmission Direct + Indirect) x Transmission Color (glass shows the grey glass "
                  "backdrop) + Emission; the safe image for posters in lit rooms", "scene"),
    _map("albedo", "flat surface colour, no light at all (Diffuse Color pass; metal and glass are dark)",
         "standard"),
    _map("shaded_albedo", "albedo x soft shading (AO and a gentle camera-facing falloff): form reads, "
                          "no highlights", "standard"),
    _map("emission", "glow only (Emission pass), black elsewhere", "scene"),
    _map("normal", "tangent normal map for a flat plane facing the viewer (OpenGL, +Y up), flat blue "
                   "outside the character", mode="RGB"),
    *[_map(key, f"{name} copied from the materials (AOV)", "standard" if kind == "COLOR" else "raw")
      for key, (name, kind) in AOVS.items()],
    _map("ao", "ambient occlusion (AO pass, denoised)"),
    _map("shading", "grey shading only: AO x camera-facing falloff (what shaded_albedo multiplies by)"),
    _map("depth", "nearness: white = closest to the camera, black = farthest (inverted Mist pass)"),
    _map("mask", "alpha cutout: white = character", depth="8", mode="BW"),
    _map("border", "the mask grown outward (Border, a fraction of the long edge): the white cardboard edge of a standee",
         depth="8", mode="BW"),
]
MAP_NAMES = [m["name"] for m in MAPS]
MAP_BY_NAME = {m["name"]: m for m in MAPS}

FACING = 0.35  # how much the camera-facing falloff darkens shading / shaded_albedo (0 = AO only)
