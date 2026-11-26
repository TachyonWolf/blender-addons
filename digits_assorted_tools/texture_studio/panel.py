"""Texture Studio UI: the sidebar panel (Digit's Tools tab, shown only in a studio scene), the starter card
(Scene > Texture Studio in the tool dropdown) and the File > New entries.

Starting a studio: File > New > Texture Studio opens the studio file as a new untitled file (so a save can never
overwrite it); Add Studio to This File (card, File > New) builds a studio scene in the open file. Then pick the
subject: Add Character links a character's master .blend as a library override, Link Into Studio links a
collection of this file (the same collection, no copy). Frame, Check Model and Capture run studio.py.
"""
import os

import bpy
from bpy.props import StringProperty

from .. import prefs
from ..menu_entries import append_menus, remove_menus
from ..ui_cards import action_row, hints, section, status  # generated copy
from . import scene_setup, settings, studio

REPORT_TEXT = "Texture Studio Report"


def studio_file():
    """The studio .blend for File > New: the preference, else the default place."""
    chosen = getattr(prefs.addon_prefs(), "texture_studio_file", "") or prefs.TEXTURE_STUDIO_FILE
    return os.path.abspath(os.path.expanduser(bpy.path.abspath(chosen)))


def _show_report(context, lines):
    text = bpy.data.texts.get(REPORT_TEXT) or bpy.data.texts.new(REPORT_TEXT)
    text.clear()
    text.write("\n".join(lines) + "\n")
    return text


class _StudioOperator:
    @classmethod
    def poll(cls, context):
        s = getattr(context.scene, "texture_studio", None)
        return s is not None and (s.subject_object or s.subject_collection)

    def run(self, context, fn):
        try:
            return fn()
        except (ValueError, RuntimeError) as err:
            self.report({'ERROR'}, str(err))
            return None


class _InStudioOperator:
    """Poll: the current scene is a studio scene."""
    @classmethod
    def poll(cls, context):
        return scene_setup.is_studio_scene(context.scene)


class TEXTURESTUDIO_OT_use_selected(bpy.types.Operator):
    """Use the active object (and its children) as the subject"""
    bl_idname = "texture_studio.use_selected"
    bl_label = "Use Active Object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        context.scene.texture_studio.subject_object = context.active_object
        return {'FINISHED'}


class TEXTURESTUDIO_OT_add_studio(bpy.types.Operator):
    """Add a Texture Studio scene to this file: camera, lights, passes and compositor, ready to photograph a character"""
    bl_idname = "texture_studio.add_studio"
    bl_label = "Add Studio to This File"
    bl_options = {'REGISTER', 'UNDO'}

    subject: StringProperty(name="Subject Collection", description="A collection of this file to link into the studio "
                            "and photograph (no copy). Empty: set the subject later")

    @classmethod
    def poll(cls, context):
        if scene_setup.find_studio_scene() is not None:
            cls.poll_message_set("This file already has a Texture Studio scene")
            return False
        return True

    def execute(self, context):
        collection = bpy.data.collections.get(self.subject) if self.subject else None
        if self.subject and collection is None:
            self.report({'ERROR'}, f"No collection called '{self.subject}' in this file")
            return {'CANCELLED'}
        try:
            scene = scene_setup.add_studio_scene()
        except ValueError as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        if collection is not None:
            scene_setup.link_existing_subject(scene, collection)
        if context.window:
            context.window.scene = scene
        self.report({'INFO'}, "Studio added" + (f", subject {collection.name}" if collection else
                                                 ": add a character in the Texture Studio panel"))
        return {'FINISHED'}


class TEXTURESTUDIO_OT_add_character(_InStudioOperator, bpy.types.Operator):
    """Link the character's collection from its master .blend as a library override (the master is never edited) and
    make it the subject"""
    bl_idname = "texture_studio.add_character"
    bl_label = "Add Character"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.texture_studio
        path = bpy.path.abspath(s.character_file)
        if not os.path.isfile(path) or not s.character_collection:
            self.report({'ERROR'}, "Pick a character .blend and one of its collections first")
            return {'CANCELLED'}
        try:
            subject = scene_setup.link_subject(context.scene, path, s.character_collection)
        except (ValueError, RuntimeError) as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added {subject.name} as the subject: press Frame")
        return {'FINISHED'}


class TEXTURESTUDIO_OT_link_collection(_InStudioOperator, bpy.types.Operator):
    """Link the subject collection into this studio scene (the same collection, no copy)"""
    bl_idname = "texture_studio.link_collection"
    bl_label = "Link Into Studio"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.texture_studio
        if s.subject_collection is None:
            self.report({'ERROR'}, "Pick a subject collection first")
            return {'CANCELLED'}
        scene_setup.link_existing_subject(context.scene, s.subject_collection)
        return {'FINISHED'}


class TEXTURESTUDIO_OT_frame(_StudioOperator, bpy.types.Operator):
    """Fit the camera and lights to the subject (front view)"""
    bl_idname = "texture_studio.frame"
    bl_label = "Frame"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.texture_studio
        done = self.run(context, lambda: (studio.check(s), studio.frame_subject(context.scene, s)))
        return {'FINISHED'} if done else {'CANCELLED'}


class TEXTURESTUDIO_OT_check(_StudioOperator, bpy.types.Operator):
    """Write the coverage report (which maps to trust for this model) without rendering"""
    bl_idname = "texture_studio.check"
    bl_label = "Check Model"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        lines = self.run(context, lambda: studio.capture(context.scene, dry_run=True))
        if lines is None:
            return {'CANCELLED'}
        _show_report(context, lines)
        self.report({'INFO'}, lines[1] + f"  (full report: text '{REPORT_TEXT}')")
        return {'FINISHED'}


class TEXTURESTUDIO_OT_capture(_StudioOperator, bpy.types.Operator):
    """Render the subject and write every ticked map (renders once per shot)"""
    bl_idname = "texture_studio.capture"
    bl_label = "Capture"

    def execute(self, context):
        lines = self.run(context, lambda: studio.capture(context.scene))
        if lines is None:
            return {'CANCELLED'}
        _show_report(context, lines)
        self.report({'INFO'}, lines[0])
        return {'FINISHED'}


def draw_add_character(layout, s):
    body = section(layout, "texture_studio_add_character", "Add Character", icon='ARMATURE_DATA')
    if body is None:
        return
    body.prop(s, "character_file")
    body.prop(s, "character_collection")
    action_row(body).operator("texture_studio.add_character", icon='LINKED')


def draw_studio(layout, context):
    """The studio's controls (the sidebar panel body)."""
    s = context.scene.texture_studio
    draw_add_character(layout, s)
    col = layout.column()
    col.label(text="Subject")
    col.prop(s, "subject_collection")
    row = col.row(align=True)
    row.prop(s, "subject_object")
    row.operator("texture_studio.use_selected", text="", icon='EYEDROPPER')
    if s.subject_collection and s.subject_collection not in context.scene.collection.children_recursive:
        status(col, "The subject is not in this scene", icon='ERROR')
        col.operator("texture_studio.link_collection", icon='LINKED')
    col.prop(s, "include_all")
    col.separator()
    col.prop(s, "orthographic")
    row = col.row()
    row.enabled = s.orthographic
    row.prop(s, "front_and_back")
    if not s.orthographic:
        col.prop(s, "lens")
    col.prop(s, "resolution")
    col.prop(s, "padding")
    col.prop(s, "border")
    col.prop(s, "samples")
    col.prop(s, "output")
    box = col.box()
    box.label(text="Maps")
    grid = box.grid_flow(columns=2, even_columns=True)
    for name in settings.maps.MAP_NAMES:
        grid.prop(s, "map_" + name)
    col.separator()
    col.operator("texture_studio.frame", icon='VIEW_CAMERA')
    col.operator("texture_studio.check", icon='INFO')
    col.operator("texture_studio.capture", icon='RENDER_STILL')


class TEXTURESTUDIO_PT_panel(bpy.types.Panel):
    """Shows only in a studio scene (one property read)."""
    bl_label = "Texture Studio"
    bl_idname = "TEXTURESTUDIO_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Digit's Tools"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return scene_setup.is_studio_scene(context.scene)

    def draw(self, context):
        draw_studio(self.layout, context)


def draw_card(layout, context):
    """Scene > Texture Studio in the tool dropdown: the ways to start a studio."""
    hints(layout, ["Photographs a character into texture maps for posters and standees. The studio panel shows "
                   "while the scene is a studio."], context)
    if scene_setup.is_studio_scene(context.scene):
        status(layout, "This scene is a Texture Studio: see its panel", icon='CHECKMARK')
        return
    layout.prop_search(context.window_manager, "texture_studio_start_collection", bpy.data, "collections",
                       text="Subject")
    op = action_row(layout).operator("texture_studio.add_studio", icon='ADD')
    op.subject = context.window_manager.texture_studio_start_collection
    draw_new_file_button(layout)


def draw_new_file_button(layout):
    path = studio_file()
    row = layout.row()
    row.enabled = os.path.isfile(path)
    row.operator_context = 'INVOKE_DEFAULT'  # asks about unsaved changes first
    op = row.operator("wm.read_homefile", text="New Texture Studio File", icon='FILE_NEW')
    op.filepath, op.app_template, op.load_ui = path, "", False


def draw_file_new_entries(self, context):
    """File > New: Texture Studio (the studio file as a new untitled file)."""
    draw_new_file_button(self.layout)


def draw_camera_add_entries(self, context):
    """Add > Camera: Texture Studio in This File (a studio scene added to the open file)."""
    layout = self.layout
    layout.operator_context = 'EXEC_DEFAULT'
    layout.operator("texture_studio.add_studio", text="Texture Studio in This File", icon='SCENE_DATA')


MENUS = (("TOPBAR_MT_file_new", draw_file_new_entries), ("VIEW3D_MT_camera_add", draw_camera_add_entries))
CLASSES = (TEXTURESTUDIO_OT_use_selected, TEXTURESTUDIO_OT_add_studio, TEXTURESTUDIO_OT_add_character,
           TEXTURESTUDIO_OT_link_collection, TEXTURESTUDIO_OT_frame, TEXTURESTUDIO_OT_check,
           TEXTURESTUDIO_OT_capture, TEXTURESTUDIO_PT_panel)


def register():
    settings.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.texture_studio_start_collection = bpy.props.PointerProperty(
        type=bpy.types.Collection, name="Subject",
        description="A collection of this file to link into the new studio and photograph (optional)",
        options={'SKIP_SAVE'})
    append_menus(MENUS)


def unregister():
    remove_menus(MENUS)
    del bpy.types.WindowManager.texture_studio_start_collection
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    settings.unregister()
