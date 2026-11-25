"""Texture Studio core: find the subject, frame it, light it, capture every map, write the report.

The panel (panel.py) and the headless capture (capture.py) both call capture(scene); options come
from scene.texture_studio (settings.py). Nothing here saves a .blend: material AOVs, hidden
objects, mirrored lights and compositor links are all put back in finally blocks.

Front is the -Y side (the subject faces -Y, like Photo Backdrop). The back shot turns the camera
180 degrees around the subject's vertical axis and mirrors the image left-right; the lights are
reflected across the subject's frontal plane (Swing -> 180 - Swing), so a light on her right hand
from the front lights her right hand from behind too.
"""
import datetime
import os
import re
from contextlib import contextmanager
from math import atan, pi, tan

import bpy
from mathutils import Matrix, Vector

from .. import camera_rig, light_rig, light_rig_spec  # rig helpers, used without registering them
from . import aov_inject, compositor, map_check, maps, settings

RENDERABLE = {"MESH", "CURVE", "CURVES", "SURFACE", "META", "FONT", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}
CLEARANCE = 2.0  # m between the camera and the subject's near side (orthographic)


# ---------------------------------------------------------------------------
# Subject
# ---------------------------------------------------------------------------

def _render_visible_collections(view_layer):
    """Collections whose objects render: not excluded, not disabled for render, nor any parent."""
    visible = set()

    def walk(layer):
        if layer.exclude or layer.collection.hide_render:
            return
        visible.add(layer.collection)
        for child in layer.children:
            walk(child)

    walk(view_layer.layer_collection)
    return visible


def renderable(ob, view_layer, visible_collections):
    return (ob.type in RENDERABLE and not ob.hide_render
            and any(c in visible_collections for c in ob.users_collection))


def subject_name(s):
    subject = s.subject_object or s.subject_collection
    return subject.name if subject else None


def _custom_shapes(scene):
    """Objects used as bone shapes (rig controls) by any armature in the scene."""
    return {pb.custom_shape for ob in scene.objects if ob.type == "ARMATURE" and ob.pose
            for pb in ob.pose.bones if pb.custom_shape}


def character_part(ob, armatures, shapes):
    """True if ob belongs to the character: deformed by or parented under one of its armatures."""
    if ob in shapes:
        return False
    if any(m.type == "ARMATURE" and m.object in armatures for m in getattr(ob, "modifiers", [])):
        return True
    parent = ob.parent
    while parent is not None:
        if parent in armatures:
            return True
        parent = parent.parent
    return False


def subject_objects(scene, view_layer, s):
    """(objects to capture, subject objects hidden in the render, extras left out).

    Unless Include All Objects is on, a subject with armatures is only its character: objects deformed
    by or parented under those armatures, never bone shapes. Without an armature, every visible object."""
    if s.subject_object:
        candidates = [s.subject_object, *s.subject_object.children_recursive]
    elif s.subject_collection:
        candidates = list(s.subject_collection.all_objects)
    else:
        raise ValueError("pick a subject: a collection or an object")
    visible = _render_visible_collections(view_layer)
    shown = [ob for ob in candidates if renderable(ob, view_layer, visible)]
    hidden = [ob for ob in candidates if ob.type in RENDERABLE and ob not in shown]
    extras = []
    armatures = {ob for ob in candidates if ob.type == "ARMATURE"}
    if armatures and not s.include_all:
        shapes = _custom_shapes(scene)
        extras = [ob for ob in shown if not character_part(ob, armatures, shapes)]
        shown = [ob for ob in shown if ob not in extras]
    if not shown:
        raise ValueError(f"'{subject_name(s)}' has no visible, renderable objects")
    return shown, hidden, extras


def materials_of(objects):
    mats = []
    for ob in objects:
        for slot in getattr(ob, "material_slots", []):
            if slot.material and slot.material not in mats:
                mats.append(slot.material)
    return mats


def bounds(objects, depsgraph):
    corners = [ob.matrix_world @ Vector(c) for ob in objects for c in ob.evaluated_get(depsgraph).bound_box]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    return lo, hi


@contextmanager
def only_subject_renders(scene, view_layer, subject):
    """Hide every other renderable object in the render for the capture, then put them back."""
    visible = _render_visible_collections(view_layer)
    others = [ob for ob in scene.objects if ob not in subject and renderable(ob, view_layer, visible)]
    for ob in others:
        ob.hide_render = True
    try:
        yield others
    finally:
        for ob in others:
            ob.hide_render = False


# ---------------------------------------------------------------------------
# Camera and lights
# ---------------------------------------------------------------------------

def find_tagged(scene, tag):
    return next((ob for ob in scene.objects if ob.get(tag) is not None), None)


def camera_dolly(scene):
    dolly = find_tagged(scene, camera_rig.TAG)
    if dolly is None:
        raise RuntimeError("no Camera Rig in the scene (run build_studio.py)")
    return dolly


def light_rig_root(scene):
    return find_tagged(scene, light_rig_spec.ROOT_TAG)


def framing(lo, hi, s, back=False):
    """Camera settings that fit the box lo..hi: dict of location, target, ortho scale, resolution."""
    center = (lo + hi) / 2
    size = hi - lo
    pad = 1.0 + 2.0 * s.padding
    width, height, depth = max(size.x * pad, 1e-3), max(size.z * pad, 1e-3), size.y
    if width >= height:
        res = (s.resolution, max(1, round(s.resolution * height / width)))
    else:
        res = (max(1, round(s.resolution * width / height)), s.resolution)
    longest = max(width, height)
    if s.orthographic:
        distance = depth / 2 + CLEARANCE
    else:
        half_fov = atan(18.0 / s.lens)  # sensor 36 mm, fitted to the long side
        distance = longest / 2 / tan(half_fov) + depth / 2
    side = 1.0 if back else -1.0
    location = Vector((center.x, center.y + side * distance, center.z))
    return {"location": location, "target": center, "ortho_scale": longest, "resolution": res,
            "near": distance - depth / 2, "depth": depth, "distance": distance}


def place_camera(scene, frame, s):
    dolly = camera_dolly(scene)
    cam = camera_rig.part(dolly, "camera")
    aim = camera_rig.part(dolly, "aim")
    bpy.context.view_layer.update()
    offset = cam.matrix_world.translation - dolly.matrix_world.translation  # camera's place on the dolly
    dolly.location = frame["location"] - offset
    bpy.context.view_layer.update()
    follow = bool(dolly.get(camera_rig.FOLLOW_PROP, False))
    aim.matrix_basis = camera_rig.aim_basis_for_mode(dolly, Matrix.Translation(frame["target"]), follow)
    data = cam.data
    data.type = "ORTHO" if s.orthographic else "PERSP"
    data.ortho_scale = frame["ortho_scale"]
    data.lens, data.sensor_fit, data.sensor_width = s.lens, "AUTO", 36.0
    data.dof.use_dof = False
    data.clip_start = max(0.01, min(0.1, frame["near"] / 2))
    data.clip_end = frame["distance"] + frame["depth"] + 10.0
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = frame["resolution"]
    scene.render.resolution_percentage = 100
    world = scene.world
    if world:  # mist (depth map) spans the subject; AO reaches a tenth of its height
        world.mist_settings.start, world.mist_settings.depth = frame["near"], max(frame["depth"], 1e-3)
        world.mist_settings.falloff = "LINEAR"
        world.light_settings.distance = max(0.05, frame["ortho_scale"] * 0.1)
    bpy.context.view_layer.update()
    return cam


def mirrored_swing(angle):
    """Swing (radians) of the light reflected across the subject's frontal plane."""
    a = pi - angle
    return (a + pi) % (2 * pi) - pi


@contextmanager
def mirrored_lights(rig):
    """Reflect every light front <-> back for the back shot (same side, same height), then undo."""
    if rig is None:
        yield
        return
    names = [f"{light} Swing" for light in light_rig_spec.LIGHTS]
    old = {n: rig[n] for n in names}
    for n in names:
        rig[n] = mirrored_swing(old[n])
    rig.update_tag()
    bpy.context.view_layer.update()
    try:
        yield
    finally:
        for n in names:
            rig[n] = old[n]
        rig.update_tag()
        bpy.context.view_layer.update()


def frame_subject(scene, s, back=False):
    """Fit the camera to the subject; returns the framing dict. On the front shot the light rig is
    fitted too and turned to face the camera; the back shot keeps it (mirrored_lights flips it)."""
    view_layer = bpy.context.view_layer
    objects, _hidden, _extras = subject_objects(scene, view_layer, s)
    lo, hi = bounds(objects, bpy.context.evaluated_depsgraph_get())
    frame = framing(lo, hi, s, back)
    cam = place_camera(scene, frame, s)
    rig = light_rig_root(scene)
    if rig is not None and not back:
        light_rig.fit_to_objects(rig, objects, bpy.context.evaluated_depsgraph_get())
        bpy.context.view_layer.update()
        light_rig.face_camera(rig, cam)
        bpy.context.view_layer.update()
    return frame


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def border_px(scene, s):
    """Border grow in pixels: the Border fraction of the image's long edge (at least 1 px)."""
    return max(1, round(s.border * max(scene.render.resolution_x, scene.render.resolution_y)))


def check(s):
    if s.front_and_back and not s.orthographic:
        raise ValueError("Front and Back needs Orthographic on (a perspective back shot would not line up)")
    if not (s.subject_object or s.subject_collection):
        raise ValueError("pick a subject: a collection or an object")


def output_folder(s, out_dir=None):
    if out_dir:
        return os.path.abspath(bpy.path.abspath(out_dir))
    base = bpy.path.abspath(s.output or settings.DEFAULT_OUTPUT)
    safe = re.sub(r"[^\w.-]+", "_", subject_name(s))
    return os.path.join(base, safe, datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))


def tidy_names(directory, wanted):
    """File Output adds the frame number (beauty0001.png): rename to beauty.png."""
    for name in wanted:
        pattern = re.compile(rf"^{re.escape(name)}\d+\.png$")
        for entry in os.listdir(directory):
            if pattern.match(entry):
                os.replace(os.path.join(directory, entry), os.path.join(directory, name + ".png"))


def _names(objects, limit=12):
    names = sorted(ob.name for ob in objects)
    return ", ".join(names[:limit]) + (f", ... {len(names) - limit} more" if len(names) > limit else "")


def _headline(subject, results, doubtful, hair, flags):
    if flags is None:
        when = " (before rendering: the written maps are checked after a capture)"
    else:
        when = ""
    reasons = []
    if doubtful:
        reasons.append(f"{len(doubtful)} of {len(results)} materials have guessed or missing values "
                       f"({', '.join(doubtful)}): check the value maps on those parts")
    if hair:
        reasons.append("hair shaders are dark in matte and albedo")
    for name, level, _text in flags or []:
        reasons.append(f"{name} {'looks wrong' if level == 'bad' else 'needs a look'}")
    if not reasons:
        return (f"ALL MAPS TRUSTWORTHY for '{subject}': every material value was read from a Principled "
                f"BSDF{' and every written map passed the check' if flags is not None else ''}.{when}")
    return f"NOT ALL MAPS TRUSTWORTHY for '{subject}': " + "; ".join(reasons) + "." + when


def report_lines(subject, objects, hidden, extras, results, shots, wanted, folder, flags=None):
    """The report; flags = map_check.check() after a capture (None before rendering)."""
    statuses = {r["material"]: aov_inject.status(r) for r in results}
    doubtful = sorted(m for m, st in statuses.items() if st != "exact")
    hair = sorted(r["material"] for r in results if "hair shader" in r["notes"].skipped)
    curves = [ob.name for ob in objects if ob.type == "CURVES"]
    lines = [_headline(subject, results, doubtful, hair, flags), "",
             f"Output: {folder}", f"Shots: {', '.join(shots)}   Maps: {', '.join(wanted)}",
             f"Objects rendered: {len(objects)}   hidden in the render (skipped): {len(hidden)}"
             + (f" ({_names(hidden)})" if hidden else ""),
             f"Left out, not part of the character (Include All Objects captures them): {len(extras)}"
             + (f" ({_names(extras)})" if extras else ""),
             f"Hair curves objects: {len(curves)}" + (f" ({', '.join(curves)})" if curves else "")]
    if hair:
        lines.append("Hair shaders (" + ", ".join(hair) + "): hair BSDFs render into the glossy and "
                     "transmission passes, so hair is dark in matte and black in albedo; base_color has "
                     "its colour.")
    if flags:
        lines += ["", "Map check (written images):"] + [f"  {name}: {text}" for name, _level, text in flags]
    elif flags is not None:
        lines += ["", "Map check (written images): every map has content where expected."]
    expected = map_check.expectations(results)
    lines += ["", "Expected value maps: " + ", ".join(
        f"{key} {'from nodes' if how == 'nodes' else ('mixed constants' if v is None else f'= {v:g}')}"
        for key, (how, v) in expected.items())]
    lines += ["", "Materials (value maps):"]
    for st in ("exact", "guess", "partial", "eevee", "none"):
        names = sorted(m for m, x in statuses.items() if x == st)
        if names:
            lines.append(f"  {st} - {aov_inject.STATUS_TEXT[st]}:")
            for r in results:
                if r["material"] in names:
                    n = r["notes"]
                    extra = []
                    if n.guessed:
                        extra.append("guessed from " + ", ".join(sorted(n.guessed)))
                    if n.unknown:
                        extra.append("no values from " + ", ".join(sorted(n.unknown)))
                    missing = [k for k in maps.AOVS if k not in r["found"]]
                    if missing and r["found"]:
                        extra.append("missing " + ", ".join(missing))
                    if r["linked"]:
                        extra.append("linked/override: edited in memory only")
                    lines.append(f"    {r['material']}" + (f"  ({'; '.join(extra)})" if extra else ""))
    return lines


def capture(scene, out_dir=None, dry_run=False, log=print):
    """Render every wanted map (front, and back if asked); returns the report lines.

    dry_run: inject the AOVs, write nothing and render nothing, just return the report."""
    s = scene.texture_studio
    check(s)
    view_layer = bpy.context.view_layer
    objects, hidden, extras = subject_objects(scene, view_layer, s)
    wanted = settings.wanted_maps(s)
    folder = output_folder(s, out_dir)
    shots = ["front", "back"] if s.front_and_back else ["front"]
    materials = materials_of(objects)
    removed = []
    try:
        results = aov_inject.inject(materials)
        lines = report_lines(subject_name(s), objects, hidden, extras, results, shots, wanted, folder)
        if dry_run:
            return ["DRY RUN (nothing rendered or written)"] + lines
        removed = compositor.unlink_unwanted(scene, wanted)
        scene.cycles.samples = s.samples
        rig = light_rig_root(scene)
        with only_subject_renders(scene, view_layer, objects):
            for shot in shots:
                back = shot == "back"
                directory = os.path.join(folder, shot) if len(shots) > 1 else folder
                os.makedirs(directory, exist_ok=True)
                frame_subject(scene, s, back=back)
                compositor.configure(scene, directory, scene.camera.matrix_world, back, border_px(scene, s))
                with mirrored_lights(rig if back else None):
                    log(f"TEXTURE STUDIO rendering {shot} -> {directory}")
                    bpy.ops.render.render(write_still=False)
                tidy_names(directory, wanted)
        first = os.path.join(folder, shots[0]) if len(shots) > 1 else folder
        flags = map_check.check(first, wanted, results)
        lines = report_lines(subject_name(s), objects, hidden, extras, results, shots, wanted, folder, flags)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "report.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        return lines
    finally:
        compositor.relink(scene, removed)
        aov_inject.remove(materials)
