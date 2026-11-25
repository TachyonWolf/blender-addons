# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/render_settings.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Render settings as data: property paths ("scene.cycles.samples") with values, the shared setting
groups (the user's render defaults), and apply / snapshot / diff helpers.

Used by the Render Presets add-on and by batch_tools/apply_render_defaults.py (both get a synced copy).
Paths start at the scene and may go through the camera ("scene.camera.data.dof.use_dof").
"""
import math

RENDER_FOLDER = "//renders/"


# ---------------------------------------------------------------------------
# Property paths
# ---------------------------------------------------------------------------

def _owner_and_attr(scene, path):
    """The object that owns the property and its attribute name; raises LookupError if missing."""
    names = path.split(".")
    if names[0] != "scene" or len(names) < 2:
        raise LookupError(path)
    owner = scene
    try:
        for name in names[1:-1]:
            owner = getattr(owner, name)
    except AttributeError as err:
        raise LookupError(path) from err
    if owner is None or not hasattr(owner, names[-1]):
        raise LookupError(path)  # e.g. no scene camera, or Cycles not enabled
    return owner, names[-1]


def get_value(scene, path):
    owner, attr = _owner_and_attr(scene, path)
    return getattr(owner, attr)


def set_value(scene, path, value):
    owner, attr = _owner_and_attr(scene, path)
    setattr(owner, attr, value)


def same_value(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, abs_tol=1e-6)
    return a == b


def apply_settings(scene, settings):
    """Set every path; returns the paths that could not be set (missing or rejected value)."""
    skipped = []
    for path, value in settings.items():
        try:
            set_value(scene, path, value)
        except (LookupError, TypeError, ValueError):
            skipped.append(path)
    return skipped


def read_settings(scene, paths):
    """{path: current value} for the paths that exist; plain JSON-friendly values only."""
    values = {}
    for path in paths:
        try:
            value = get_value(scene, path)
        except LookupError:
            continue
        if isinstance(value, (bool, int, float, str)):
            values[path] = value
    return values


def diff_settings(scene, settings):
    """[(path, current value, new value)] for the settings that would change something."""
    changes = []
    for path, new in settings.items():
        try:
            old = get_value(scene, path)
        except LookupError:
            continue
        if not same_value(old, new):
            changes.append((path, old, new))
    return changes


# ---------------------------------------------------------------------------
# The user's render defaults, as groups: each returns {path: value} for one scene
# ---------------------------------------------------------------------------

def color(sc, notes):
    return {"scene.view_settings.view_transform": "Khronos PBR Neutral",
            "scene.view_settings.look": "Medium High Contrast"}


def output(sc, notes):
    settings = {}
    r = sc.render
    path = r.filepath
    if path in ("", "/tmp/", "/tmp", "//") or (len(path) > 1 and path[1] == ":"):  # empty, temp or Windows
        settings["scene.render.filepath"] = RENDER_FOLDER
    else:
        notes.append(f"kept-out:{path}")
    if r.image_settings.file_format == "PNG":
        settings["scene.render.image_settings.color_depth"] = "16"
    else:
        notes.append(f"kept-fmt:{r.image_settings.file_format}")
    return settings


def cycles(sc, notes):
    return {"scene.cycles.device": "GPU",
            "scene.cycles.preview_samples": 256,
            "scene.cycles.use_preview_denoising": True,
            "scene.cycles.preview_denoiser": "OPTIX",
            "scene.cycles.use_denoising": True,
            "scene.cycles.use_adaptive_sampling": True,
            "scene.cycles.adaptive_threshold": 0.02}


def eevee(sc, notes):
    """Raytracing on, at full resolution without denoise: glass (a visor) stays crystal clear."""
    return {"scene.eevee.use_raytracing": True,
            "scene.eevee.ray_tracing_options.resolution_scale": "1",
            "scene.eevee.ray_tracing_options.use_denoise": False}


GROUPS = {"color": color, "output": output, "cycles": cycles, "eevee": eevee, "raytracing": eevee}
DEFAULT_GROUPS = ("color", "output", "cycles", "eevee")


def group_settings(sc, names, notes=None):
    """Merged {path: value} of the named groups for this scene."""
    notes = [] if notes is None else notes
    settings = {}
    for name in names:
        settings.update(GROUPS[name](sc, notes))
    return settings


def apply_group(name, sc, notes):
    apply_settings(sc, group_settings(sc, [name], notes))


# ---------------------------------------------------------------------------
# What "Save current as preset" can capture: group name -> property paths
# ---------------------------------------------------------------------------

CAPTURE_GROUPS = {
    "samples": ["scene.render.engine", "scene.cycles.samples", "scene.cycles.adaptive_threshold",
                "scene.cycles.use_adaptive_sampling", "scene.cycles.use_denoising",
                "scene.cycles.denoiser", "scene.cycles.time_limit", "scene.eevee.taa_render_samples"],
    "resolution": ["scene.render.resolution_x", "scene.render.resolution_y",
                   "scene.render.resolution_percentage", "scene.render.fps"],
    "light paths": ["scene.cycles.max_bounces", "scene.cycles.diffuse_bounces",
                    "scene.cycles.glossy_bounces", "scene.cycles.transmission_bounces",
                    "scene.cycles.volume_bounces", "scene.cycles.transparent_max_bounces",
                    "scene.cycles.caustics_reflective", "scene.cycles.caustics_refractive",
                    "scene.cycles.sample_clamp_direct", "scene.cycles.sample_clamp_indirect"],
    "simplify": ["scene.render.use_simplify", "scene.render.simplify_subdivision_render",
                 "scene.render.simplify_child_particles_render", "scene.cycles.texture_limit_render"],
    "colour": ["scene.view_settings.view_transform", "scene.view_settings.look",
               "scene.view_settings.exposure", "scene.view_settings.gamma"],
    "output": ["scene.render.image_settings.file_format", "scene.render.image_settings.color_depth",
               "scene.render.film_transparent", "scene.render.use_motion_blur",
               "scene.render.motion_blur_shutter", "scene.camera.data.dof.use_dof"],
    "compositor": ["scene.render.use_compositing", "scene.render.use_sequencer"],
}
