# SPDX-License-Identifier: GPL-3.0-or-later
"""Game Rig card: one button that makes a SIMPLE game-ready copy of the character (new rig + mesh copies in a
"<rig> Game" collection, the original untouched). All logic is in game_rig (generated copy of
Addons/shared_addon/game_rig.py), the bone names per engine in rig_names.

Output: This File (the rig stays in this file) or also an FBX / glTF Binary / Blend file of just the game rig and its
meshes, written to the same path every time (re-importing into an engine needs a stable path).
Settings live on the armature object (`Object.digit_game_rig`)."""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from . import game_rig as gr, output_file as of, rig_names  # generated copies
from .face_rig_ui import character
from .ui_cards import action_row, hints, prop_group, section, status  # generated copy


THIS_FILE = 'THIS_FILE'
OUTPUTS = [(THIS_FILE, "This File", "Only make the game rig in this file"),
           ('FBX', "FBX", "Also export the game rig and its meshes to an .fbx file"),
           ('GLB', "glTF Binary (.glb)", "Also export the game rig and its meshes to a .glb file"),
           ('BLEND', "Blend File", "Also write the game rig and its meshes to a .blend file that opens showing them")]
EXTENSIONS = {'FBX': ".fbx", 'GLB': ".glb", 'BLEND': ".blend"}
EXPORTER_CLASS = {'FBX': "EXPORT_SCENE_OT_fbx", 'GLB': "EXPORT_SCENE_OT_gltf"}   # present while the add-on is on
EXPORTER_NAME = {'FBX': "FBX", 'GLB': "glTF 2.0"}


class ExportError(RuntimeError):
    """An export that could not run or failed; the message is for the user."""


class DIGITOOLS_PG_game_rig(bpy.types.PropertyGroup):
    fingers: BoolProperty(name="Fingers", default=True, description="Keep one bone per finger segment (off: hands only)")
    face: BoolProperty(name="Face", default=False,
                       description="Also brows and lip corners (off: jaw and eyes only)")
    parts: BoolProperty(name="Parts", default=True,
                        description="Keep tail, ear, hair and wing rigs, cut to a few bones each (off: they go "
                                    "into the body bones)")
    engine: EnumProperty(name="Engine", items=rig_names.ENGINES, default=rig_names.DEFAULT_ENGINE,
                         description="Whose bone names the game rig uses")
    output: EnumProperty(name="Output", items=OUTPUTS, default=THIS_FILE,
                         description="Where the game rig goes. It is always made in this file; a file output also "
                                     "exports it (the same path every time, replacing the old file)")
    output_name: of.name_property()
    output_folder: of.folder_property()
    report: StringProperty(name="Report", description="What the last Make Game Rig did")


def main_rig(context):
    arm = character(context)
    return gr.root_rig(arm) if arm else None


def output_path(main, auto=False):
    """The file the chosen output writes (the same path every run), None for This File or when there is no folder.
    `auto`: ignore the typed name."""
    s = main.digit_game_rig
    ext = EXTENSIONS.get(s.output)
    if ext is None:
        return None
    return of.output_path("" if auto else s.output_name, s.output_folder, f"{main.name}-Game", ext,
                          bpy.data.filepath, overwrite=True)


def problem(context):
    """Why Make Game Rig can't run now, or ''."""
    main = main_rig(context)
    if main is None:
        return "Select the character (or its rig)"
    kind = main.digit_game_rig.output
    if kind == THIS_FILE:
        return ""
    if output_path(main) is None:
        return "Save this file first, or set an Output Folder"
    if kind in EXPORTER_CLASS and not hasattr(bpy.types, EXPORTER_CLASS[kind]):
        return f"The {EXPORTER_NAME[kind]} export add-on is off (Preferences > Add-ons)"
    return ""


# ---------------------------------------------------------------- exporting
def select_only(context, objects):
    for ob in context.view_layer.objects:
        ob.select_set(ob in objects)
    context.view_layer.objects.active = next(ob for ob in objects if ob.type == 'ARMATURE')


def write_blend(collection, path):
    """A .blend holding just the collection, in a scene of its own so the file opens showing it. Paths are remapped to
    the new location. The scene is removed again (the collection stays in this file)."""
    scene = bpy.data.scenes.new(os.path.splitext(os.path.basename(path))[0])
    scene.collection.children.link(collection)
    try:
        bpy.data.libraries.write(path, {scene}, path_remap='RELATIVE')
    finally:
        bpy.data.scenes.remove(scene)


def export_collection(context, collection, kind, path):
    """Write the game collection (rig + meshes, nothing else) to `path`. The user's selection and active object are
    back afterwards. Raises ExportError."""
    if kind in EXPORTER_CLASS and not hasattr(bpy.types, EXPORTER_CLASS[kind]):
        raise ExportError(f"the {EXPORTER_NAME[kind]} export add-on is off (Preferences > Add-ons)")
    view = context.view_layer
    active = view.objects.active.name if view.objects.active else None
    selected = [ob.name for ob in context.selected_objects]
    of.make_folder(path)
    try:
        if kind == 'BLEND':
            write_blend(collection, path)
            return
        select_only(context, set(collection.all_objects))
        if kind == 'FBX':
            bpy.ops.export_scene.fbx(filepath=path, use_selection=True, add_leaf_bones=False, bake_anim=False,
                                     path_mode='COPY', embed_textures=True)
        else:
            bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True, export_animations=False)
    except (RuntimeError, OSError) as exc:
        raise ExportError(str(exc).strip().splitlines()[-1] if str(exc).strip() else "export failed") from exc
    finally:
        for ob in view.objects:
            ob.select_set(ob.name in selected)
        view.objects.active = bpy.data.objects.get(active) if active else None


class DIGITOOLS_OT_game_rig(bpy.types.Operator):
    """Make a simple game-ready copy of the character: one new rig (single root, deform bones only, no constraints) and
    copies of the visible meshes with Mirror applied and at most 4 weights per vertex, in a '<rig> Game' collection.
    The original rig and meshes are not changed, and the rest pose is used, not the current pose"""
    bl_idname = "digits_assorted_tools.game_rig"
    bl_label = "Make Game Rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        main = main_rig(context)
        s = main.digit_game_rig
        name = of.clean_name(s.output_name, EXTENSIONS.get(s.output, "")) or None
        report = gr.make_game_rig(context, main, s.fingers, s.face, s.parts, s.engine, name)
        s.report = gr.info_line(report)
        path = output_path(main)
        if path:
            try:
                export_collection(context, report['rig'].users_collection[0], s.output, path)
            except ExportError as exc:      # the rig is made in this file anyway
                self.report({'ERROR'}, f"{s.report}. Not exported: {exc}")
                return {'FINISHED'}
            s.report += f"; exported {path}"
        self.report({'INFO'}, s.report)
        return {'FINISHED'}


def draw_card(layout, context):
    body = layout   # the tool dropdown is the title
    main = main_rig(context)
    if main is None:
        status(body, "Select the character (or its rig)")
        return
    s = main.digit_game_rig
    status(body, s.report.split(";")[0] if s.report else f"{main.name}: not made yet", icon='ARMATURE_DATA')
    action_row(body, 1.6).operator(DIGITOOLS_OT_game_rig.bl_idname, icon='ARMATURE_DATA')
    path = output_path(main)
    hints(body, [problem(context)] + (["dropped" + s.report.split("dropped")[1].split(";")[0]] if "dropped" in s.report else [])
          + ([f"{'Replaces' if os.path.exists(path) else 'Saves'} {os.path.basename(path)}"] if path else []), context)
    opts = section(body, "digitools_game_rig_options", "Include", icon='MODIFIER')
    if opts:
        prop_group(opts, s, ["engine", None, "fingers", "face", "parts"])
    auto = output_path(main, auto=True)
    of.draw_output(body, "digitools_game_rig_output", s, "output_name", "output_folder",
                   os.path.basename(auto) if auto else main.name, of.resolve_folder("", bpy.data.filepath),
                   with_folder=s.output != THIS_FILE, extra=lambda col: col.prop(s, "output"))


classes = (DIGITOOLS_PG_game_rig, DIGITOOLS_OT_game_rig)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_game_rig = PointerProperty(type=DIGITOOLS_PG_game_rig)


def unregister():
    del bpy.types.Object.digit_game_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
