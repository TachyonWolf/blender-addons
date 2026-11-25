# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Object Texture Data Screenshot: its options (scene.digit_texture_screenshot), operators and card.
Draw reads a few properties and the cheap add-on lookups only."""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, PointerProperty, StringProperty

from .. import assorted_tools
from ..prefs import preferences
from ..ui_cards import action_row, choice_row, count_on, hints, prop_group, section, status, toggles  # generated copy
from . import decal_step, facing_gizmo, glass_alpha, map_sets, process, save_paths

OBJECT, COLLECTION = "OBJECT", "COLLECTION"


class TextureScreenshotOptions(bpy.types.PropertyGroup):
    target_kind: EnumProperty(name="Target", items=[
        (OBJECT, "Selected Object", "The active object and its children"),
        (COLLECTION, "Collection", "Every visible object of a collection")])
    collection: PointerProperty(name="Collection", type=bpy.types.Collection,
                                description="The collection to photograph")
    map_set: EnumProperty(name="Map Set", items=map_sets.MAP_SET_ITEMS, default=map_sets.SIMPLE,
                          description="Which colour maps to capture")
    lighting: EnumProperty(name="Lighting", items=map_sets.LIGHTING_ITEMS)
    custom_maps: StringProperty(name="Custom Maps", default="albedo", options={'HIDDEN'},
                                description="The ticked studio maps, comma separated")
    detail: EnumProperty(name="Surface Detail", items=map_sets.DETAIL_ITEMS, default="NORMALS",
                         description="One detail map added to the colour maps")
    front_and_back: BoolProperty(name="Front + Back", default=False,
                                 description="Also shoot from behind (mirrored to line up with the front)")
    resolution: IntProperty(name="Image Size", default=1024, min=64, max=16384, subtype='PIXEL',
                            description="Long edge of each image in pixels")
    save_to: EnumProperty(name="Save To", items=[save_paths.DEFAULT_ITEM, *save_paths.SAVE_ITEMS],
                          description="Where the images go (Default = the add-on's Preferences)")
    folder: StringProperty(name="Folder", subtype='DIR_PATH', description="Images go to <folder>/<target>/")
    add_decal: BoolProperty(name="Add as Decal", default=True,
                            description="Add the maps as a decal beside the target (not attached: attach it later)")
    facing: EnumProperty(name="Facing", items=decal_step.FACING_ITEMS, default=decal_step.FRONT_FACING,
                         description="World axis the decal faces (with Front + Back, its back side shows the back shot)")
    custom_facing: FloatVectorProperty(name="Direction", size=3, subtype='DIRECTION', default=decal_step.DEFAULT_CUSTOM,
                                       description="The direction a Custom decal faces. Drag the arrow in the "
                                       "viewport (Ctrl snaps to 15 degrees) or turn the ball")
    glass_see_through: BoolProperty(name="Glass is see-through", default=True,
                                    description="Glass (like a visor) is clear on the decal: its alpha follows the "
                                    "glass's Transmission. Skipped when nothing in the target is glass")
    see_through: FloatProperty(name="See-through", default=glass_alpha.DEFAULT_SEE_THROUGH, min=0.0, max=1.0,
                               subtype='FACTOR', description="How clear the glass is: 0 = opaque, 1 = fully clear")


for _option, _label, _map, _default, _text in map_sets.EXTRA_MAPS:
    TextureScreenshotOptions.__annotations__[map_sets.extra_option(_option)] = BoolProperty(
        name=_label, default=_default, description=_text)
EXTRA_PROPS = [(map_sets.extra_option(option), label) for option, label, *_rest in map_sets.EXTRA_MAPS]


def options_of(context):
    return context.scene.digit_texture_screenshot


def target_of(context, options):
    return options.collection if options.target_kind == COLLECTION else context.active_object


def save_mode(context, options):
    return save_paths.effective_mode(options.save_to, preferences(context).save_to)


def save_plan(context, options, target):
    prefs = preferences(context)
    return save_paths.resolve(save_mode(context, options), bpy.data.filepath, target.name,
                              bpy.path.abspath(options.folder) if options.folder else "", prefs.fallback_folder)


def make_job(context, options):
    """A process.Job from the card's options. Raises ValueError / assorted_tools.Missing with a user message."""
    target = target_of(context, options)
    if target is None:
        raise ValueError("Pick a collection" if options.target_kind == COLLECTION else "Select an object")
    names = assorted_tools.module("texture_studio.maps", context).MAP_NAMES
    colour = map_sets.colour_maps(options.map_set, options.lighting, options.custom_maps)
    extras, notes = map_sets.ticked_extras(options), []
    if map_sets.GLOW_MAP in extras and map_sets.GLOW_MAP not in colour and not process.target_glows(target):
        extras.remove(map_sets.GLOW_MAP)
        notes.append(f"No glow map: nothing in {target.name} glows")
    see_through = None
    if options.glass_see_through:
        if process.target_transmissive(target):
            see_through = options.see_through
            extras += [name for name in glass_alpha.HELPER_MAPS if name not in extras]
        else:
            notes.append(f"No see-through glass: nothing in {target.name} is glass")
    return process.Job(target=target, colour_maps=colour, notes=notes, see_through=see_through,
                       maps=map_sets.studio_maps(options.map_set, options.lighting, options.custom_maps,
                                                 options.detail, names, extras),
                       save=save_plan(context, options, target), front_and_back=options.front_and_back,
                       resolution=options.resolution,
                       add_decal=options.add_decal, facing=options.facing,
                       custom_facing=tuple(options.custom_facing))   # unavailable Decals: skipped with a note


class DIGITPROCESSES_OT_texture_screenshot(bpy.types.Operator):
    """Photograph the target in a temporary Texture Studio, save the maps as images and add them as a decal"""
    bl_idname = "digit_processes.texture_screenshot"
    bl_label = "Make Texture Screenshot"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and assorted_tools.is_enabled(context)

    def invoke(self, context, event):
        options = options_of(context)
        if not bpy.data.filepath and save_mode(context, options) == save_paths.BLEND:
            return context.window_manager.invoke_props_dialog(self, title="This file is not saved", confirm_text="Use Fallback Folder")
        return self.execute(context)

    def draw(self, context):
        folder = preferences(context).fallback_folder
        col = self.layout.column()
        col.label(text="Next to this .blend needs a saved file.")
        col.label(text="Cancel and save it first, or use the fallback:")
        col.label(text=folder or "(no fallback folder set in Preferences)", icon='FILE_FOLDER')

    def execute(self, context):
        try:
            job = make_job(context, options_of(context))
            result = process.run(context, job)
        except (ValueError, RuntimeError) as error:   # assorted_tools.Missing is a RuntimeError
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        for note in result.notes:
            self.report({'INFO'}, note)
        if result.lines:
            print("\n".join(result.lines))
        return {'FINISHED'}


class DIGITPROCESSES_OT_toggle_screenshot_map(bpy.types.Operator):
    """Tick or untick this map for the Custom map set"""
    bl_idname = "digit_processes.toggle_screenshot_map"
    bl_label = "Toggle Map"
    bl_options = {'INTERNAL', 'UNDO'}

    name: StringProperty()

    def execute(self, context):
        options = options_of(context)
        options.custom_maps = map_sets.toggle_custom(options.custom_maps, self.name)
        return {'FINISHED'}


def draw_custom_ticks(layout, options, map_names):
    ticked = set(map_sets.parse_custom(options.custom_maps))
    grid = layout.grid_flow(columns=2, align=True)
    for name in map_names:
        grid.operator(DIGITPROCESSES_OT_toggle_screenshot_map.bl_idname, text=name.replace("_", " ").title(),
                      depress=name in ticked).name = name


def target_line(context, options):
    target = target_of(context, options)
    if target is None:
        return "Pick a collection" if options.target_kind == COLLECTION else "Select an object", 'INFO'
    return f"Target: {target.name}", 'CHECKMARK'


def save_hint(context, options):
    mode = save_mode(context, options)
    if mode == save_paths.PACK:
        return "Packed into the .blend"
    if mode == save_paths.FOLDER:
        return "Into <folder>/<target>/" if options.folder else "Pick a folder"
    if bpy.data.filepath:
        return "Into //Textures/Decals/<target>/"
    return "File not saved: you are asked on Make"


def draw_card(layout, context):
    body = layout   # the process dropdown is the title
    if not assorted_tools.is_enabled(context):
        status(body, "Needs Digit's Assorted Tools", icon='ERROR')
        hints(body, ["Enable it in Preferences > Add-ons: this process uses its Texture Studio."], context)
        return
    options = options_of(context)
    status(body, *target_line(context, options))
    choice_row(body, options, "target_kind")
    if options.target_kind == COLLECTION:
        body.prop_search(options, "collection", bpy.data, "collections", text="")
    maps = section(body, "digit_processes_screenshot_maps", "Maps", icon='TEXTURE')
    if maps:
        choice_row(maps, options, "map_set", columns=3)
        if options.map_set == map_sets.BAKED:
            choice_row(maps, options, "lighting")
        elif options.map_set == map_sets.CUSTOM:
            draw_custom_ticks(maps, options, assorted_tools.module("texture_studio.maps", context).MAP_NAMES)
        prop_group(maps, options, [("detail", "Detail"), ("resolution", "Image Size"), "front_and_back"])
    extras = section(body, "digit_processes_screenshot_extras", "Extra Maps", icon='SHADING_TEXTURE',
                     right=count_on(options, [name for name, _label in EXTRA_PROPS]))
    if extras:
        toggles(extras, options, EXTRA_PROPS)
        toggles(extras, options, [("glass_see_through", "Glass is see-through")], columns=1)
        slider = extras.row()
        slider.enabled = options.glass_see_through
        slider.prop(options, "see_through", slider=True)
    save = section(body, "digit_processes_screenshot_save", "Save", icon='FILE_FOLDER')
    if save:
        prop_group(save, options, [("save_to", "Save To")])
        if save_mode(context, options) == save_paths.FOLDER:
            prop_group(save, options, [("folder", "Folder")])
        hints(save, [save_hint(context, options)], context)
    decal_ready = decal_step.is_available(context)
    row = body.row()
    row.enabled = decal_ready
    row.prop(options, "add_decal")
    if not decal_ready:
        hints(body, [decal_step.UNAVAILABLE_TEXT], context)
    elif options.add_decal:
        prop_group(body, options, [("facing", "Facing")])
        if options.facing == decal_step.CUSTOM:
            body.prop(options, "custom_facing", text="Direction")
            body.prop(options, "custom_facing", text="", expand=True)
            hints(body, ["Drag the arrow in the 3D view to turn it (Ctrl snaps to 15 degrees). Only the decal "
                         "turns: the photo stays the studio's front shot."], context)
    action_row(body).operator(DIGITPROCESSES_OT_texture_screenshot.bl_idname, icon='RENDER_STILL')


CLASSES = (TextureScreenshotOptions, DIGITPROCESSES_OT_texture_screenshot, DIGITPROCESSES_OT_toggle_screenshot_map)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.digit_texture_screenshot = PointerProperty(type=TextureScreenshotOptions)
    facing_gizmo.register()


def unregister():
    facing_gizmo.unregister()
    del bpy.types.Scene.digit_texture_screenshot
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
