# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake to Game Asset: Game Rig, optional triangle reduction, bake of the procedural materials (one image set per
mesh and material), export. All the work is Digit's Assorted Tools' code (game_rig, mesh_reduce, procedural_baker,
game_rig_ui's Output) reached through the bridge; this file only chains it. The source rig, meshes and materials are
never changed: the game copy gets its own material copies before anything is baked."""
import os
from typing import NamedTuple

import bpy

from .. import assorted_tools

DEFAULT_TARGET_TRIANGLES = 30000
DEFAULT_WARN_ABOVE = 100000     # a PC hero character is about 50-100k; phones and VR want 10-30k


class Tools(NamedTuple):
    game_rig: object
    game_ui: object
    baker: object
    reduce: object
    output_file: object


def tools(context=None):
    """The Assorted Tools modules the chain uses. Raises assorted_tools.Missing."""
    return Tools(*(assorted_tools.module(name, context)
                   for name in ("game_rig", "game_rig_ui", "procedural_baker", "mesh_reduce", "output_file")))


class AssetResult(NamedTuple):
    rig: object
    triangles_before: int
    triangles_after: int
    shape_key_objects: int
    textures: int
    baked_materials: int
    view_dependent: list     # source material names that were baked though their look depends on the viewer
    problems: list
    export_path: str         # '' when nothing was exported
    export_error: str

    def line(self, game_report_line):
        text = f"{game_report_line}; {self.triangles_after:,} triangles"
        if self.triangles_after != self.triangles_before:
            text += f" (was {self.triangles_before:,})"
        if self.shape_key_objects:
            text += f"; shape keys dropped on {self.shape_key_objects} meshes"
        text += f"; baked {self.baked_materials} materials, {self.textures} textures"
        if self.view_dependent:
            text += "; view-dependent, look may differ: " + ", ".join(self.view_dependent)
        if self.problems:
            text += "; skipped: " + "; ".join(self.problems)
        if self.export_path:
            text += f"; exported {self.export_path}"
        if self.export_error:
            text += f"; not exported: {self.export_error}"
        return text


def game_meshes(rig):
    return [ob for ob in rig.users_collection[0].all_objects if ob.type == 'MESH']


def count_triangles(context, main):
    """(triangles, what): the game copy of `main` when it exists, else the meshes a game copy would be made from."""
    kit = tools(context)
    collections = kit.game_rig.game_collections(main)
    if collections:
        meshes = [ob for ob in collections[0].all_objects if ob.type == 'MESH']
        return kit.reduce.triangle_count(meshes), "game copy"
    return kit.reduce.triangle_count(kit.game_rig.source_meshes(context, main)[0]), "source"


def textures_folder(kit, main, collection_name):
    """Where the baked PNGs go: next to the exported file, or //textures/<game collection>/ for This File."""
    export_path = kit.game_ui.output_path(main)
    if export_path:
        stem = os.path.splitext(os.path.basename(export_path))[0]
        return os.path.join(os.path.dirname(export_path), stem + "_textures")
    return bpy.path.abspath(f"//textures/{collection_name}/")


def problem(context, main):
    """Why the chain can't run now, or ''. Game Rig's own checks, and a saved file for the textures of This File."""
    kit = tools(context)
    why = kit.game_ui.problem(context)
    if not why and main.digit_game_rig.output == kit.game_ui.THIS_FILE and not bpy.data.filepath:
        why = "Save this file first (the textures need a folder), or pick a file Output"
    return why


def own_procedural_materials(meshes, scan_material):
    """Give every game mesh its own copy of each material that needs baking (the source keeps its material, and a
    linked material can be baked). Returns (copies: the new materials, view_dependent: source names)."""
    copies, view_dependent = [], []
    for ob in meshes:
        made = {}
        for slot in ob.material_slots:
            original = slot.material
            if original is None:
                continue
            if original.name not in made:
                scan = scan_material(original)
                made[original.name] = None
                if scan.needs_bake:
                    copy = original.copy()
                    copy.name = original.name + " Game"
                    made[original.name] = copy
                    copies.append(copy)
                    if scan.view_dependent and original.name not in view_dependent:
                        view_dependent.append(original.name)
            if made[original.name]:
                slot.material = made[original.name]
    return copies, view_dependent


def run(context, main, low_poly, target_triangles):
    """The whole chain for the rig `main`, with the Game Rig options stored on it. Raises assorted_tools.Missing."""
    kit = tools(context)
    options = main.digit_game_rig
    name = kit.output_file.clean_name(options.output_name, kit.game_ui.EXTENSIONS.get(options.output, "")) or None
    report = kit.game_rig.make_game_rig(context, main, options.fingers, options.face, options.parts, options.engine, name)
    rig = report['rig']
    meshes = [bpy.data.objects[ob_name] for ob_name in report['meshes']]
    before = kit.reduce.triangle_count(meshes)
    after, dropped = before, 0
    if low_poly:
        before, after, dropped = kit.reduce.reduce_triangles(context, meshes, target_triangles)

    copies, view_dependent = own_procedural_materials(meshes, kit.baker.scan_material)
    textures, baked_materials, problems = 0, 0, []
    if copies:
        settings = context.scene.procedural_baker
        folder = textures_folder(kit, main, rig.users_collection[0].name)
        wanted = [ob for ob in meshes if any(slot.material in copies for slot in ob.material_slots)]
        result = kit.baker.bake_objects(context, wanted, settings, folder, only=lambda mat: mat in copies,
                                        per_material=True, make_material=True, use_material=True)
        textures, baked_materials, problems = result.saved, len(result.baked), result.problems
        for copy in copies:
            if not copy.users:
                bpy.data.materials.remove(copy)
        for (_object_name, copy_name), baked in result.baked.items():
            baked.name = copy_name      # the copy's name is free again: "Noise Game"

    export_path, export_error = kit.game_ui.output_path(main) or "", ""
    if export_path:
        try:
            kit.game_ui.export_collection(context, rig.users_collection[0], options.output, export_path)
        except kit.game_ui.ExportError as error:     # the game asset is made in this file anyway
            export_path, export_error = "", str(error)
    return AssetResult(rig, before, after, dropped, textures, baked_materials, view_dependent, problems,
                       export_path, export_error), report
