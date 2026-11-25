# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: plain rules, no bpy (tested in tests/test_decal_maps.py with plain Python).

- Map roles: which job an image file has (Color, Normal, Glow, ...), guessed from its name ending; which roles hold
  data (Non-Color) rather than colour.
- Names: the stem shared by a map set (`logo_color.png` -> `logo`) and the decal name `Decal.<stem>`.
- Sibling maps: the other files of a set in the same folder.
- Crop: the rectangle of an image's alpha that is visible, as normalised UVs.
- Grid: the light base grid (BASE_QUADS on the long side) and the Detail (Subdivision levels) a target needs.
- Layer lift: how far a decal floats for its layer, so layers don't z-fight."""

import os
import re
from dataclasses import dataclass

# Role id -> label, in the order the Maps box shows them (every slot, always)
ROLES = (("COLOR", "Color"), ("NORMAL", "Normal"), ("GLOW", "Glow"), ("ROUGHNESS", "Roughness"),
         ("METAL", "Metal"), ("ALPHA", "Alpha"), ("HEIGHT", "Height"))
SKIP = "SKIP"
ROLE_LABELS = dict(ROLES)
BACK_PREFIX = "BACK_"     # a back map's role: BACK_COLOR... (the side seen from behind, decal_material)


def back_role(role):
    return BACK_PREFIX + role


def front_role(role):
    """COLOR for BACK_COLOR (and for COLOR)."""
    return role[len(BACK_PREFIX):] if role.startswith(BACK_PREFIX) else role

# Images that hold data, not colour: loaded as Non-Color
DATA_ROLES = {"NORMAL", "ROUGHNESS", "METAL", "ALPHA", "HEIGHT"}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".webp", ".exr", ".bmp")
IMAGE_EXTENSIONS_TEXT = ";".join(IMAGE_EXTENSIONS)   # FileHandler / file browser filter form

# Name endings per role (lower case, after a "_", "-", "." or " "). Longest match wins.
ENDINGS = {"COLOR": ("color", "colour", "col", "basecolor", "base_color", "albedo", "diffuse", "diff", "base"),
           "NORMAL": ("normal", "nrm", "nor", "norm", "normalgl", "normal_gl", "normal_opengl"),
           "GLOW": ("emit", "emission", "emissive", "glow"),
           "ROUGHNESS": ("rough", "roughness", "rgh"),
           "METAL": ("metal", "metallic", "metalness", "mtl"),
           "ALPHA": ("alpha", "opacity", "mask"),
           "HEIGHT": ("height", "disp", "displacement", "bump")}
SKIP_ENDINGS = ("preview", "thumb", "thumbnail")
SEPARATORS = "_-. "

BASE_QUADS = 12               # quads along the long side of the light base grid (the short side by aspect)
MIN_BASE_QUADS = 2
QUADS_PER_TARGET_EDGE = 4      # wanted after Detail: finer than the target, so decal edges crossing a convex ridge
                               # stay above it
MAX_DETAIL = 4                 # Detail = Subdivision (Simple) levels on top of the base grid
DEFAULT_DETAIL = 2
RENDER_EXTRA_DETAIL = 1        # render level = Detail + this
PROJECT_FRACTION = 0.25        # Project wrap: the flat grid starts this part of the size above the surface ...
PROJECT_HEIGHT = (0.005, 0.05) # ... kept within these metres, and projects down at most twice that far
DEFAULT_LIFT = 0.001           # metres above the surface, world space (default; a setting)
ALPHA_THRESHOLD = 0.01
LAYER_STEP = 0.0001            # metres between decal layers (default; a setting)
LAYER_STEP_SIZE = 0.1          # decals bigger than this (metres) get a proportionally bigger step


def _ending_table():
    pairs = [(ending, role) for role, endings in ENDINGS.items() for ending in endings]
    pairs += [(ending, SKIP) for ending in SKIP_ENDINGS]
    return sorted(pairs, key=lambda pair: -len(pair[0]))


ENDING_TABLE = _ending_table()


def split_name(filename):
    """(stem, role) of an image file name: `logo_color.png` -> ("logo", "COLOR"). No known ending -> (name, None)."""
    base = os.path.splitext(os.path.basename(filename))[0]
    lowered = base.lower()
    for ending, role in ENDING_TABLE:
        if lowered.endswith(ending) and len(base) > len(ending) and base[-len(ending) - 1] in SEPARATORS:
            return base[:-len(ending) - 1], role
    return base, None


def guess_roles(filenames):
    """{filename: role} for a set of images: name endings first; a file with no known ending is Color when the set
    has no Color yet (the first one), else skipped. One image alone is always Color (a sticker)."""
    if len(filenames) == 1:
        return {filenames[0]: "COLOR"}
    roles = {name: split_name(name)[1] for name in filenames}
    for name in filenames:
        if roles[name] is None:
            roles[name] = "COLOR" if "COLOR" not in roles.values() else SKIP
    return roles


def is_data(role):
    """True for roles loaded as Non-Color (back roles like their front role)."""
    return front_role(role) in DATA_ROLES


def stem_of(filenames):
    """The shared stem of a map set: the Color file's stem, else the first file's."""
    roles = guess_roles(list(filenames))
    color = next((name for name, role in roles.items() if role == "COLOR"), None)
    return split_name(color or filenames[0])[0]


def decal_name(stem):
    """Object / mesh / material name for a decal. Blender adds `.001` on repeats; a side ending (`Freckles.L`)
    is kept as it is."""
    return "Decal." + clean_stem(stem)


def clean_stem(stem):
    """Stem with spaces and stray separators tidied: `my logo_` -> `my_logo`."""
    cleaned = re.sub(r"\s+", "_", stem.strip()).strip("_-")
    return cleaned or "Decal"


def sibling_maps(path, names_in_folder):
    """{role: filename} of the other maps of `path`'s set found among `names_in_folder` (its own folder's file
    names): same stem (case-insensitive), a known role ending, an image extension. `path` itself is left out."""
    own = os.path.basename(path)
    stem = split_name(own)[0].lower()
    found = {}
    for name in sorted(names_in_folder):
        if name == own or not name.lower().endswith(IMAGE_EXTENSIONS):
            continue
        name_stem, role = split_name(name)
        if role and role != SKIP and name_stem.lower() == stem and role not in found:
            found[role] = name
    return found


@dataclass
class Crop:
    """The visible part of an image: normalised UV rectangle (u0, v0, u1, v1) and its size in pixels."""
    u0: float
    v0: float
    u1: float
    v1: float
    width_px: int
    height_px: int

    @property
    def rect(self):
        return (self.u0, self.v0, self.u1, self.v1)

    @property
    def aspect(self):
        """Width / height of the visible part."""
        return self.width_px / max(1, self.height_px)


def crop_rect(alpha, threshold=ALPHA_THRESHOLD):
    """Crop of a 2D alpha array (rows bottom to top, as Blender stores pixels; values 0..1). Nothing visible ->
    the whole image."""
    height, width = alpha.shape
    rows = (alpha > threshold).any(axis=1).nonzero()[0]
    columns = (alpha > threshold).any(axis=0).nonzero()[0]
    if len(rows) == 0:
        return Crop(0.0, 0.0, 1.0, 1.0, width, height)
    first_row, last_row = int(rows[0]), int(rows[-1]) + 1
    first_column, last_column = int(columns[0]), int(columns[-1]) + 1
    return Crop(first_column / width, first_row / height, last_column / width, last_row / height,
                last_column - first_column, last_row - first_row)


def decal_dimensions(size, aspect):
    """(width, height) in metres of a decal whose long side is `size`."""
    return (size, size / aspect) if aspect >= 1 else (size * aspect, size)


def base_grid_counts(width, height):
    """(columns, rows) of the light base grid: BASE_QUADS along the long side, the short side by aspect (at least
    MIN_BASE_QUADS). The Detail modifier adds the density; the base only follows big curves."""
    long_side = max(width, height, 1e-9)

    def count(length):
        return max(MIN_BASE_QUADS, round(BASE_QUADS * length / long_side))
    return count(width), count(height)


def projection_height(size):
    """How far above the surface a Project-wrapped decal's flat grid starts (metres): it projects one way, down
    into the surface, at most twice this far, so the first surface below wins and nothing far away is hit."""
    low, high = PROJECT_HEIGHT
    return min(high, max(low, size * PROJECT_FRACTION))


def detail_levels(long_side, target_edge):
    """Subdivision levels that give about QUADS_PER_TARGET_EDGE decal quads per target edge on top of the base
    grid, 0..MAX_DETAIL."""
    wanted = long_side / (max(target_edge, 1e-6) / QUADS_PER_TARGET_EDGE)
    levels = 0
    while BASE_QUADS * 2 ** levels < wanted and levels < MAX_DETAIL:
        levels += 1
    return levels


def layer_lift(layer, size, step=LAYER_STEP):
    """Extra lift (metres) for layer number `layer` (0 = bottom): `step` per layer, scaled up for decals bigger
    than LAYER_STEP_SIZE so big overlapping decals stay apart."""
    return layer * step * max(1.0, size / LAYER_STEP_SIZE)


def mirror_uv_offset(u0, u1):
    """Mirror modifier `mirror_offset_u` that flips U inside the crop (u -> u0 + u1 - u), so a mirrored copy
    reads the right way round."""
    return u0 + u1 - 1.0
