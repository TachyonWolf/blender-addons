"""Built-in render presets, defined in code (no bpy, so tests and the headless script can import it).

ONE option table (OPTIONS) describes every setup option: id, label, group, type, range, and what it
writes. Each built-in (BUILTINS) lists its default value per option and its fixed settings. A default
of None means "Keep": the option leaves its keys out of the preset, so the scene's value stays.
The UI builds its PropertyGroups and rows from OPTIONS, the headless `--option group.id=value` parser
uses it too, and options_to_preset() turns a built-in's option values into the preset dict that
preset_store / compositor_chain already understand.
"""
from dataclasses import dataclass, field

QUALITY, SPEED, OUTPUT, LOOK = "quality", "speed", "output", "look"
GROUP_ORDER = (QUALITY, SPEED, OUTPUT, LOOK)
GROUP_LABELS = {QUALITY: "Quality", SPEED: "Speed", OUTPUT: "Output", LOOK: "Look"}
TEXTURE_LIMITS = ("OFF", "128", "256", "512", "1024", "2048", "4096", "8192")
# The user's render defaults (same as render_settings' "color" group; this module can't import it).
USER_COLOUR_DEFAULTS = {"scene.view_settings.view_transform": "Khronos PBR Neutral",
                        "scene.view_settings.look": "Medium High Contrast"}
DEFAULT_LOOK = "Default"   # a starting look that adds nothing: the node group keeps its own values


@dataclass(frozen=True)
class Option:
    """One setup option. `paths`: scene path written with the option's value (direct options).
    `when_on` / `when_off`: {path: value} written for a bool option that sets several paths.
    `chain_group` / `look_name`: Look options, the compositor group they add and its starting look."""
    id: str
    label: str
    group: str
    type: str                       # "int" | "float" | "bool" | "choice"
    minimum: float = None
    maximum: float = None
    choices: tuple = ()
    paths: tuple = ()
    when_on: dict = field(default_factory=dict)
    when_off: dict = field(default_factory=dict)
    chain_group: str = ""
    look_name: str = ""


OPTIONS = (
    Option("samples", "Samples", QUALITY, "int", 1, 65536, paths=("scene.cycles.samples",)),
    Option("noise_threshold", "Noise Threshold", QUALITY, "float", 0.0, 1.0,
           paths=("scene.cycles.adaptive_threshold",)),
    Option("resolution_percent", "Resolution %", QUALITY, "int", 1, 100,
           paths=("scene.render.resolution_percentage",)),
    Option("denoise", "Denoise", QUALITY, "bool", paths=("scene.cycles.use_denoising",)),
    Option("bounces", "Bounces", QUALITY, "int", 0, 1024, paths=("scene.cycles.max_bounces",)),
    Option("simplify", "Simplify", SPEED, "bool", paths=("scene.render.use_simplify",)),
    Option("simplify_level", "Simplify Level", SPEED, "int", 0, 6,
           paths=("scene.render.simplify_subdivision_render",)),
    Option("texture_limit", "Texture Limit", SPEED, "choice", choices=TEXTURE_LIMITS,
           paths=("scene.cycles.texture_limit_render",)),
    Option("transparent", "Transparent Background", OUTPUT, "bool", paths=("scene.render.film_transparent",)),
    Option("png_rgba", "PNG RGBA", OUTPUT, "bool",
           when_on={"scene.render.image_settings.file_format": "PNG",
                    "scene.render.image_settings.color_mode": "RGBA"},
           when_off={"scene.render.image_settings.file_format": "PNG",
                     "scene.render.image_settings.color_mode": "RGB"}),
    Option("standard_view", "Standard View", OUTPUT, "bool",
           when_on={"scene.view_settings.view_transform": "Standard", "scene.view_settings.look": "None"},
           when_off=USER_COLOUR_DEFAULTS),
    Option("motion_blur", "Motion Blur", OUTPUT, "bool", paths=("scene.render.use_motion_blur",)),
    # Look options, in compositor chain order (Polish -> Fog -> Lens -> Film).
    Option("polish", "Polish", LOOK, "bool", chain_group="Render Polish"),
    Option("fog", "Fog", LOOK, "bool", chain_group="Depth Fog"),
    Option("lens", "Lens", LOOK, "bool", chain_group="Lens Effects", look_name="Clean"),
    Option("film", "Film", LOOK, "bool", chain_group="Film Look", look_name="Subtle"),
)
OPTION_BY_ID = {option.id: option for option in OPTIONS}


def options_in_group(group):
    return [option for option in OPTIONS if option.group == group]


# The live controls of each Look group: node group input names in drawing order. "<X> On" followed by
# "<X> Amount" is one effect row. Save as My Preset reads these inputs into the preset's "look" key.
LOOK_INPUTS = {
    "Render Polish": ("Glow Strength", "Bloom Strength", "Lens Fringe", "Vignette Strength", "Vignette Size",
                      "Vignette Softness", "Brightness", "Sharpen Amount", "Lines Opacity", "Glow Over Lines"),
    "Depth Fog": ("Density", "Fog Colour", "Start", "Falloff", "End", "Height Fade", "Height Level",
                  "Height Range", "Glow", "Glow Threshold", "Glow Size"),
    "Lens Effects": ("Flare On", "Flare Amount", "Lens Dirt On", "Lens Dirt Amount",
                     "Lens Scratches On", "Lens Scratches Amount"),
    "Film Look": ("Halation On", "Halation Amount", "Grain On", "Grain Amount", "Scratches On", "Scratches Amount",
                  "Weave On", "Weave Amount"),
}


# ---------------------------------------------------------------------------
# The built-ins. `defaults`: option id -> value; ids left out are Keep (None).
# `groups`: render_settings groups; `settings`: fixed paths (engine, compositing on/off).
# ---------------------------------------------------------------------------

COLOR_OUTPUT_CYCLES = ["color", "output", "cycles"]
LOOKS_OFF = {"polish": False, "fog": False, "lens": False, "film": False}

BUILTINS = {
    "Draft": {
        "groups": [], "settings": {"scene.render.engine": "CYCLES", "scene.render.use_compositing": False},
        "defaults": {"samples": 16, "noise_threshold": 0.1, "resolution_percent": 50, "denoise": True,
                     "bounces": 2, "simplify": True, "simplify_level": 0, "texture_limit": "512",
                     "motion_blur": False, **LOOKS_OFF}},
    "Preview": {
        "groups": [], "settings": {"scene.render.engine": "CYCLES", "scene.render.use_compositing": False},
        "defaults": {"samples": 64, "noise_threshold": 0.05, "resolution_percent": 50, "denoise": True,
                     "bounces": 4, "simplify": True, "simplify_level": 1, "texture_limit": "1024",
                     **LOOKS_OFF}},
    "Final": {
        "groups": COLOR_OUTPUT_CYCLES,
        "settings": {"scene.render.engine": "CYCLES", "scene.render.use_compositing": True},
        "defaults": {"samples": 4096, "noise_threshold": 0.02, "resolution_percent": 100,
                     "bounces": 12, "simplify": False, "texture_limit": "OFF", **LOOKS_OFF}},
    "Animation": {
        "groups": COLOR_OUTPUT_CYCLES,
        "settings": {"scene.render.engine": "CYCLES", "scene.render.use_compositing": True},
        "defaults": {"samples": 256, "noise_threshold": 0.03, "resolution_percent": 100, "denoise": True,
                     "bounces": 8, "simplify": False, "motion_blur": True, **LOOKS_OFF}},
    "Ref Sheet": {
        "groups": [], "settings": {"scene.render.engine": "CYCLES", "scene.render.use_compositing": False},
        "defaults": {"samples": 128, "resolution_percent": 100, "denoise": True, "transparent": True,
                     "png_rgba": True, "standard_view": True, "motion_blur": False, **LOOKS_OFF}},
}

# Old preset names -> (built-in, option overrides).
ALIASES = {
    "Fancy": ("Final", {"polish": True}),
    "Fancy Full": ("Final", {"polish": True, "fog": True, "lens": True, "film": True}),
    "Final Low VRAM": ("Final", {"simplify": True, "simplify_level": 2, "texture_limit": "2048"}),
}


def preset_names():
    return list(BUILTINS)


def default_options(builtin_name):
    """{option id: value or None (Keep)} for every option of a built-in."""
    defaults = BUILTINS[builtin_name]["defaults"]
    return {option.id: defaults.get(option.id) for option in OPTIONS}


# ---------------------------------------------------------------------------
# Options -> preset dict
# ---------------------------------------------------------------------------

def _option_settings(option, value):
    """The {path: value} one non-Keep option writes."""
    if option.paths:
        return {path: value for path in option.paths}
    return dict(option.when_on if value else option.when_off)


def default_look(option):
    """The starting look a Look option uses when none is picked."""
    return option.look_name or DEFAULT_LOOK


def _chain_and_looks(options, starts):
    """(compositor_chain, compositor_presets) for the Look options that are on. `starts`: option id ->
    starting look name (missing = the option's own; DEFAULT_LOOK adds nothing)."""
    chain, looks = [], {}
    for option in options_in_group(LOOK):
        if options.get(option.id):
            chain.append(option.chain_group)
            start = starts.get(option.id) or default_look(option)
            if start != DEFAULT_LOOK:
                looks[option.chain_group] = start
    return chain, looks


def options_to_preset(name, options, preset_name=None, starts=None):
    """The preset dict for built-in `name` with these option values. Options missing from `options`
    use the built-in's default; None = Keep (keys left out). `preset_name` renames the result (aliases).
    `starts`: {look option id: starting look name} (the Setup's Start With pickers)."""
    spec = BUILTINS[name]
    values = {**default_options(name), **options}
    settings = dict(spec["settings"])
    for option in OPTIONS:
        if values[option.id] is not None and option.group != LOOK:
            settings.update(_option_settings(option, values[option.id]))
    chain, looks = _chain_and_looks(values, starts or {})
    if chain:
        settings["scene.render.use_compositing"] = True   # a chain needs the compositor on
    preset = {"name": preset_name or name}
    if spec["groups"]:
        preset["groups"] = list(spec["groups"])
    preset["settings"] = settings
    if chain:
        preset["compositor_chain"] = chain
        if looks:
            preset["compositor_presets"] = looks
    return preset


def resolve_preset(name, overrides=None):
    """Preset dict for a built-in or alias name (None if unknown), with option overrides on top."""
    if name in ALIASES:
        builtin_name, alias_options = ALIASES[name]
        return options_to_preset(builtin_name, {**alias_options, **(overrides or {})}, preset_name=name)
    if name in BUILTINS:
        return options_to_preset(name, overrides or {})
    return None


# ---------------------------------------------------------------------------
# `--option look.fog=on` parser
# ---------------------------------------------------------------------------

_TRUE_WORDS, _FALSE_WORDS = ("on", "true", "yes", "1"), ("off", "false", "no", "0")
_KEEP_WORDS = ("keep", "none")


def _parse_value(option, text):
    word = text.strip().lower()
    if word in _KEEP_WORDS:
        return None
    if option.type == "bool":
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        raise ValueError(f"{option.id}: expected on/off/keep, got {text!r}")
    if option.type == "choice":
        match = [choice for choice in option.choices if choice.lower() == word]
        if not match:
            raise ValueError(f"{option.id}: expected one of {', '.join(option.choices)}, got {text!r}")
        return match[0]
    try:
        number = int(word) if option.type == "int" else float(word)
    except ValueError:
        raise ValueError(f"{option.id}: expected a {option.type} number, got {text!r}") from None
    if not option.minimum <= number <= option.maximum:
        raise ValueError(f"{option.id}: {number} is outside {option.minimum}..{option.maximum}")
    return number


def parse_option(text):
    """'look.fog=on' -> ('fog', True). The group prefix is checked; 'fog=on' is accepted too."""
    key, separator, value_text = text.partition("=")
    if not separator:
        raise ValueError(f"Option {text!r} must look like group.id=value")
    group, _, option_id = key.strip().rpartition(".")
    option = OPTION_BY_ID.get(option_id)
    if option is None:
        raise ValueError(f"Unknown option {key!r}; have: {', '.join(o.group + '.' + o.id for o in OPTIONS)}")
    if group and group != option.group:
        raise ValueError(f"Option {option_id!r} is in group {option.group!r}, not {group!r}")
    return option_id, _parse_value(option, value_text)


def parse_options(texts):
    """List of 'group.id=value' strings -> {option id: value}."""
    return dict(parse_option(text) for text in texts)
