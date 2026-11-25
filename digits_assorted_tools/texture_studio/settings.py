"""Texture Studio options: one PropertyGroup on the scene (scene.texture_studio).

is_studio marks a studio scene: the sidebar panel shows only there (scene_setup.is_studio_scene). The sidebar panel draws it and the headless capture sets it from its command line, so both run
the same capture with the same options. Map toggles (map_<name>) are made from maps.MAPS.
"""
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from .. import local_defaults  # generated copy
from . import maps

DEFAULT_OUTPUT = local_defaults.get("texture_studio_output",
                                    os.path.join(os.path.expanduser("~"), "Pictures", "TextureStudio", ""))


def character_collection_items(self, _context):
    """The collections of the picked character file (read once per file version, see scene_setup)."""
    from . import scene_setup  # noqa: PLC0415  (scene_setup imports this module)
    return scene_setup.character_collection_items(self.character_file)


class TextureStudioSettings(bpy.types.PropertyGroup):
    is_studio: BoolProperty(options={'HIDDEN'}, description="This scene is a Texture Studio (the panel shows only here)")
    character_file: StringProperty(
        name="Character File", subtype='FILE_PATH', options={'PATH_SUPPORTS_BLEND_RELATIVE'},
        description="The character's master .blend. It is linked as a library override and never edited")
    character_collection: EnumProperty(
        name="Collection", items=character_collection_items,
        description="Which collection of that file to add (usually the character's name)")
    subject_collection: PointerProperty(
        name="Collection", type=bpy.types.Collection,
        description="What to photograph: every visible, renderable object in this collection")
    subject_object: PointerProperty(
        name="Object", type=bpy.types.Object,
        description="What to photograph instead of the collection: this object and its children")
    include_all: BoolProperty(
        name="Include All Objects", default=False,
        description="Capture every visible object in the subject. Off: with an armature, only the "
                    "character (objects deformed by or parented under it, no bone shapes)")
    orthographic: BoolProperty(
        name="Orthographic", default=True,
        description="Flat orthographic camera (no perspective distortion, best for prints). "
                    "Off = perspective camera")
    front_and_back: BoolProperty(
        name="Front and Back", default=False,
        description="Also shoot from directly behind (same framing, mirrored left-right so it lines up "
                    "with the front on a two-sided standee). Needs Orthographic")
    lens: FloatProperty(name="Focal Length", default=85.0, min=10.0, max=500.0, subtype="DISTANCE_CAMERA",
                        description="Perspective camera lens (mm); only used with Orthographic off")
    resolution: IntProperty(name="Long Edge", default=2048, min=64, max=16384, subtype="PIXEL",
                            description="Image size along the longer side; the other side fits the subject")
    padding: FloatProperty(name="Padding", default=0.04, min=0.0, max=1.0, subtype="FACTOR",
                           description="Empty space around the subject, as a fraction of its size")
    border: FloatProperty(name="Border", default=0.01, min=0.0, max=0.25, subtype="FACTOR",
                          description="How far the border mask grows past the subject, as a fraction of the "
                                      "long edge (0.01 = 20 px at 2048, 5 px at 512)")
    samples: IntProperty(name="Samples", default=1024, min=1, max=65536,
                         description="Cycles max samples (adaptive sampling stops earlier where clean)")
    output: StringProperty(name="Output", default=DEFAULT_OUTPUT, subtype="DIR_PATH",
                           description="Base folder: maps go to <output>/<subject>/<date_time>/")


for _spec in maps.MAPS:
    TextureStudioSettings.__annotations__["map_" + _spec["name"]] = BoolProperty(
        name=_spec["name"], default=True, description=_spec["what"])


def wanted_maps(settings):
    return [name for name in maps.MAP_NAMES if getattr(settings, "map_" + name)]


def register():
    if not hasattr(bpy.types.Scene, "texture_studio"):
        bpy.utils.register_class(TextureStudioSettings)
        bpy.types.Scene.texture_studio = PointerProperty(type=TextureStudioSettings)


def unregister():
    if hasattr(bpy.types.Scene, "texture_studio"):
        del bpy.types.Scene.texture_studio
        bpy.utils.unregister_class(TextureStudioSettings)
