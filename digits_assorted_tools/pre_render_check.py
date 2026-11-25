# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-Render Check (Digit's Tools > Check): problems worth fixing before a long render. Its checks are `Check`s of
the shared registry (scene_checks.py) in the area "Render" (the Oops Debugger shows them too when it looks for Render);
this card never lists the Oops ones. It always runs all of its checks (no Scans toggles). Select only unless a safe Clear exists. The card (oops_ui's rows, Select and Rescan buttons) scans
only while it is open; the scan is cached until the selection changes or Rescan. Nothing runs in the background.
Adding a check = a find() function and one `register(Check(...))` line below."""
import os

import bpy

from . import oops_ui, render_settings as rs, scene_checks as sc  # rs, sc: generated copies
from .ui_cards import section, status  # generated copy

AREA = sc.RENDER
NO_GEOMETRY = {'ARMATURE', 'CAMERA', 'LATTICE', 'SPEAKER', 'LIGHT_PROBE'}
SAMPLE_PATHS = {'CYCLES': "scene.cycles.samples", 'BLENDER_EEVEE': "scene.eevee.taa_render_samples"}
LOSSY_FORMATS = {'JPEG', 'WEBP'}
LOW_SAMPLES, DEFAULT_SAMPLES = 64, 4096   # Cycles samples below LOW_SAMPLES are flagged; the fix restores the default
ENGINE_NAMES = {'CYCLES': "Cycles", 'BLENDER_EEVEE': "EEVEE", 'BLENDER_WORKBENCH': "Workbench"}


# ---------------------------------------------------------------------------
# Helpers the checks share
# ---------------------------------------------------------------------------

def draws_geometry(ob):
    """False for objects that put nothing in the picture (rigs, cameras, plain empties...)."""
    if ob.type == 'EMPTY':
        return ob.instance_type == 'COLLECTION' and ob.instance_collection is not None
    return ob.type not in NO_GEOMETRY


def renders(ob, view_layer):
    """True when the object shows up in a render: in the view layer, not hidden for render, in a collection that renders."""
    return (ob.name in view_layer.objects and not ob.hide_render
            and any(not c.hide_render for c in ob.users_collection))


def rendered_objects(scope):
    view_layer = scope.view_layer
    return [ob for ob in view_layer.objects if draws_geometry(ob) and renders(ob, view_layer)]


def modifier_targets(mod):
    """The objects a modifier points at (its Object fields, and Geometry Nodes object inputs)."""
    found = [getattr(mod, p.identifier) for p in mod.bl_rna.properties
             if p.type == 'POINTER' and p.fixed_type and p.fixed_type.identifier == 'Object']
    if mod.type == 'NODES' and mod.node_group:
        found += [getattr(mod.properties.inputs, item.identifier).value for item in mod.node_group.interface.items_tree
                  if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.socket_type == 'NodeSocketObject']
    return [t for t in found if isinstance(t, bpy.types.Object)]



# ---------------------------------------------------------------------------
# The checks: find(scope) -> Finding or None. They look at the whole view layer, not at the selection.
# ---------------------------------------------------------------------------

def render_names(objects):
    return dict(objects=[ob.name for ob in objects])


def hide_from_render(obs):
    for ob in obs:
        ob.hide_render = True
    return len(obs)


def wire_and_bounds(scope):
    return [ob for ob in rendered_objects(scope) if ob.display_type in ('WIRE', 'BOUNDS')]


def find_wire_and_bounds(scope):
    obs = wire_and_bounds(scope)
    return sc.found(obs, **render_names(obs))


# Modifiers whose target is only a helper shape (a Boolean cutter, a Mesh Deform cage), so it should not render.
# Other targets (Shrinkwrap, Surface Deform, Geometry Nodes inputs...) are often real meshes, like the body.
HELPER_TARGET_MODIFIERS = {'BOOLEAN', 'MESH_DEFORM'}


def modifier_target_objects(scope):
    """Helper objects that a rendering modifier points at but that render themselves."""
    view_layer = scope.view_layer
    targets = {}
    for owner in view_layer.objects:
        for mod in owner.modifiers:
            if mod.show_render and mod.type in HELPER_TARGET_MODIFIERS:
                for target in modifier_targets(mod):
                    if target != owner and draws_geometry(target) and renders(target, view_layer):
                        targets[target.name] = target
    return list(targets.values())


def find_modifier_targets(scope):
    obs = modifier_target_objects(scope)
    return sc.found(obs, **render_names(obs))


def find_modifier_toggles(scope):
    return sc.find_mismatched_in(scope.view_layer.objects, scope.scene)


def objects_shown_differently(scope):
    """[(object, text)]: hidden in the viewport but renders, or the other way round."""
    view_layer = scope.view_layer
    found = []
    for ob in view_layer.objects:
        if draws_geometry(ob):
            in_viewport, in_render = ob.visible_get(view_layer=view_layer), renders(ob, view_layer)
            if in_viewport != in_render:
                found.append(ob)
    return found


def find_visibility(scope):
    obs = objects_shown_differently(scope)
    view_layer = scope.view_layer
    rows = [(ob.name, "hidden in the viewport, renders" if renders(ob, view_layer) else "shown, hidden from render",
             ob.name, "") for ob in obs]
    return sc.found(obs, rows=rows, **render_names(obs))


def find_missing_images(scope):
    missing = [img.name for img in bpy.data.images
               if img.users and img.source in ('FILE', 'SEQUENCE', 'MOVIE') and not img.packed_file
               and not sc.CACHE.exists(bpy.path.abspath(img.filepath, library=img.library))]
    return sc.found(missing)


def find_camera(scope):
    return None if scope.scene.camera else sc.Finding(1, "Set one in the Scene properties")


def find_output_folder(scope):
    path = bpy.path.abspath(scope.scene.render.filepath)
    folder = path if path.endswith(("/", os.sep)) else os.path.dirname(path)
    if folder and not sc.CACHE.exists(folder, folder=True):   # cached by path: a sleeping disk takes ~0.5 s
        return sc.Finding(1, os.path.basename(folder.rstrip("/\\")) or folder)
    return None


def render_of(scope):
    return scope.scene.render


def find_resolution_percent(scope):
    percent = render_of(scope).resolution_percentage
    return sc.Finding(1, f"{percent}%") if percent < 100 else None


def find_border(scope):
    return sc.Finding(1, "Only part of the frame renders") if render_of(scope).use_border else None


def find_simplify(scope):
    return sc.Finding(1, "Simplify cuts detail in the render") if render_of(scope).use_simplify else None


def find_cycles_quality(scope):
    scene = scope.scene
    if scene.render.engine != 'CYCLES':
        return None
    problems = ["denoise off"] * (not scene.cycles.use_denoising) + [f"{scene.cycles.samples} samples"] * (scene.cycles.samples < LOW_SAMPLES)
    return sc.Finding(len(problems), ", ".join(problems)) if problems else None


def find_output_format(scope):
    settings = render_of(scope).image_settings
    if settings.media_type != 'IMAGE':   # a video or a multilayer file is not judged
        return None
    if settings.file_format in LOSSY_FORMATS:
        return sc.Finding(1, f"{settings.file_format.title()} loses detail")
    if settings.file_format == 'PNG' and settings.color_depth == '8':
        return sc.Finding(1, "8-bit PNG")
    return None


def find_relative_output(scope):
    path = render_of(scope).filepath
    return sc.Finding(1, path) if path.startswith("//") and not bpy.data.filepath else None


def find_compositing_off(scope):
    scene = scope.scene
    if scene.compositing_node_group and not scene.render.use_compositing:
        return sc.Finding(1, scene.compositing_node_group.name)
    return None


def clear_resolution_percent(scope):
    render_of(scope).resolution_percentage = 100
    return 1


def clear_border(scope):
    render_of(scope).use_border = False
    return 1


def clear_simplify(scope):
    render_of(scope).use_simplify = False
    return 1


def clear_cycles_quality(scope):
    cycles = scope.scene.cycles
    cycles.use_denoising = True
    cycles.samples = max(cycles.samples, DEFAULT_SAMPLES) if cycles.samples < LOW_SAMPLES else cycles.samples
    return 1


def clear_output_format(scope):
    settings = render_of(scope).image_settings
    settings.file_format, settings.color_depth = 'PNG', '16'
    return 1


def clear_compositing_off(scope):
    render_of(scope).use_compositing = True
    return 1


def clear_wire_and_bounds(scope):
    return hide_from_render(wire_and_bounds(scope))


def clear_modifier_targets(scope):
    return hide_from_render(modifier_target_objects(scope))


sc.register(sc.Check("render_wire", AREA, "Wire Objects Render",
                     "Hides these Wire / Bounds objects from the render (they stay shown as they are).",
                     find_wire_and_bounds, clear_wire_and_bounds, "Hide in Render",
                     why="Objects shown as Wire or Bounds are often helpers. They still render as solid objects, so "
                         "they show up in the picture.",
                     keep="Keep it when you show a real object as Wire only to see through it while you work."))
sc.register(sc.Check("render_targets", AREA, "Targets Still Render",
                     "Hides these helper objects, used by a modifier, from the render.",
                     find_modifier_targets, clear_modifier_targets, "Hide in Render",
                     why="Boolean cutters and Mesh Deform cages are helper shapes. When they render, they show up as "
                         "extra objects in the picture.",
                     keep="Keep it when the cutter or cage should be seen in the render, for example as part of the "
                          "design."))
sc.register(sc.Check("render_modifiers", sc.SCENE_DIFFERENCES, "Modifiers Differ",
                     "Modifiers on in the viewport and off in the render, or the other way round. Fast Viewport is skipped.",
                     find_modifier_toggles, None, rows_title="Modifiers",
                     why="These modifiers are on in only the viewport or only the render. The render then looks "
                         "different from what you see.",
                     keep="Subdivision Surface off in the viewport and on in the render is a normal way to keep the "
                          "viewport fast."))
sc.register(sc.Check("render_visibility", sc.SCENE_DIFFERENCES, "Shown Differently",
                     "Objects hidden in the viewport that render, or shown but hidden from render.",
                     find_visibility, None,
                     why="These objects are hidden in the viewport but render, or shown but hidden from render. The "
                         "render then shows other objects than you see.",
                     keep="Fine for helpers you see while you work but don't render, like guides. Also fine for "
                          "objects you hide only to clear the view."))
sc.register(sc.Check("render_images", AREA, "Missing Images", "Image files that are not on disk.", find_missing_images, None,
                     why="A missing image renders as bright pink, or the texture is just gone. A long render is then "
                         "wasted.",
                     keep="Fine only when no object in the shot uses it."))
sc.register(sc.Check("render_camera", AREA, "No Camera", "The scene has no active camera.", find_camera, None,
                     why="Without an active camera, Blender can't render the scene at all.",
                     keep="Fine when you never render this scene, for example a file you only use for assets."))
sc.register(sc.Check("render_output", AREA, "Output Folder Missing", "The folder the render saves into does not exist.",
                     find_output_folder, None,
                     why="The folder the render saves into is missing. It may be a typo or a drive that is not "
                         "plugged in, so the frames may not save.",
                     keep="Fine for a still image that you save by hand from the render window."))
sc.register(sc.Check("render_percent", AREA, "Resolution Under 100%", "Sets the resolution percentage back to 100%.",
                     find_resolution_percent, clear_resolution_percent, "Set 100%",
                     why="Under 100%, Blender renders a smaller picture than the resolution says. The final image "
                         "then comes out small or blurry.",
                     keep="Keep it for quick test renders, then set it back for the final one."))
sc.register(sc.Check("render_border", AREA, "Render Region On", "Turns off Render Region, so the whole frame renders.",
                     find_border, clear_border, "Turn Off",
                     why="Render Region renders only part of the frame. The rest of the picture comes out empty.",
                     keep="Keep it while you test one part of the shot to save time."))
sc.register(sc.Check("render_simplify", AREA, "Simplify On", "Turns off Simplify for the render.",
                     find_simplify, clear_simplify, "Turn Off",
                     why="Simplify cuts subdivision levels, particles or texture sizes in the render. The final "
                         "picture then has less detail.",
                     keep="Keep it on for fast previews, or when you need it to save memory."))
sc.register(sc.Check("render_quality", AREA, "Cycles Quality Low",
                     "Turns denoise on, and sets the samples to 4096 if they are under 64.",
                     find_cycles_quality, clear_cycles_quality, "Restore",
                     why="With denoise off or under 64 samples, Cycles renders look grainy (full of noise dots).",
                     keep="Keep it for quick test renders, or when you denoise in the compositor yourself."))
sc.register(sc.Check("render_format", AREA, "Lossy / 8-bit Output", "Sets the output to PNG, 16-bit.",
                     find_output_format, clear_output_format, "PNG 16-bit",
                     why="JPEG and WEBP lose detail when they save, and 8-bit PNG has fewer shades. Smooth colour "
                         "changes then show bands, and later edits look worse.",
                     keep="Fine for quick previews, or a final image that goes straight to the web."))
sc.register(sc.Check("render_relative", AREA, "Output Path Relative",
                     "The output path starts with // but the file is not saved yet, so the render has no folder to go in.",
                     find_relative_output, None,
                     why="A path that starts with // is relative to the .blend file. The file is not saved yet, so "
                         "the render has no real folder to go in.",
                     keep="Fine when you save the file before you render: then the path works."))
sc.register(sc.Check("render_compositing", AREA, "Compositing Is Off",
                     "The scene has compositor nodes, but Compositing is turned off, so they are skipped.",
                     find_compositing_off, clear_compositing_off, "Turn On",
                     why="Compositing is off, so your compositor nodes are skipped. Colour changes, glare or denoise "
                         "set up there won't show in the render.",
                     keep="Keep it off when you want the plain render on purpose, for example to composite in another "
                          "app."))


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def summary_lines(scene):
    """Engine and samples, then resolution (two short status lines)."""
    r = scene.render
    engine = ENGINE_NAMES.get(r.engine, r.engine.title())
    samples = rs.read_settings(scene, [SAMPLE_PATHS[r.engine]] if r.engine in SAMPLE_PATHS else [])
    return [engine + (f", {next(iter(samples.values()))} samples" if samples else ""),
            f"{r.resolution_x} x {r.resolution_y} at {r.resolution_percentage}%"]


def scan(context):
    """The Render findings, cached until the selection changes or Rescan."""
    return sc.CACHE.get(("render",) + sc.context_key(context),
                        lambda: sc.run_all(sc.scope_of(context), sc.RENDER_AREAS))


def draw_card(layout, context):
    oops_ui.draw_back(layout, context)
    findings = scan(context)
    head = layout.row(align=True)
    if findings:
        head.label(text=f"{len(findings)} found", icon='ERROR')
    else:
        head.label(text=oops_ui.NOTHING, icon='CHECKMARK')
    head.operator(oops_ui.OOPS_OT_rescan.bl_idname, text="", icon='FILE_REFRESH')
    body = section(layout, "prerender_settings", "Render Settings")
    if body:
        for line in summary_lines(context.scene):
            status(body, line, icon='SCENE')
    if not findings:
        return
    for area, idname, title in ((AREA, "prerender_problems", "Problems"),
                                (sc.SCENE_DIFFERENCES, "prerender_differences", "Render Differences")):
        rows = [(c, f) for c, f in findings if c.area == area]
        body = section(layout, idname, title, right=f"{len(rows)} found") if rows else None
        if body:
            for check, finding in rows:
                oops_ui.draw_finding(body, check, finding)
    if any(check.clear is not None for check, _f in findings):
        oops_ui.draw_risk_legend(layout, context)
