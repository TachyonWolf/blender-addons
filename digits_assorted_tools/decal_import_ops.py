# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: making decals from files.

- `decal.add_images` (card button "Add from Images…"): the file browser (many files), then the Import dialog.
- `decal.import_images`: the Import Decal Images dialog (one row per file with its guessed, editable role; Target,
  Place at, Size, Start as; a preview with the visible crop size). Import + Place makes ONE decal from the set.
  Place at Click on surface: the new decal waits Unattached at the 3D cursor and `decal.aim` asks for the click.
- `decal.drop_dialog` / `decal.drop_place`: the same, started by dropping images on the viewport (decal_drop.py):
  they aim at the surface under the mouse; drop_place skips the dialog when there is one.
- `decal.convert_reference`: a Reference / Image empty you lined up becomes a decal on what is behind it.
Nothing is loaded until Import + Place: the dialog's crop numbers come from a look at the file that is removed
again, the thumbnail from a previews collection, so Cancel leaves no images behind."""

import os

import bpy
import bpy.utils.previews
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty, StringProperty
from bpy.types import OperatorFileListElement
from mathutils import Vector

from . import decal_maps, decal_material, decal_mesh
from .decal_recipe import STUCK
from .view_ray import cast_surface, hit_under_mouse  # generated copy

ROLE_ITEMS = [(role, label, f"Use as the {label} map") for role, label in decal_maps.ROLES]
ROLE_ITEMS.append((decal_maps.SKIP, "(skip)", "Don't use this file"))
PLACE_ITEMS = (('CLICK', "Click on surface", "Click where the decal goes after Import"),
               ('CURSOR', "3D Cursor", "On the surface at the 3D cursor (along the cursor's Z)"))
START_ITEMS = (('PLACING', "Placing", "Slides on the surface: move, size and turn it first"),
               (STUCK, "Stuck", "Follows the rig right away"))
CURSOR_REACH = 0.05     # how far above / below the 3D cursor the surface may be (m)
NOTHING_BEHIND = "Nothing behind the image: aim it at an object"

_previews = None        # the dialog thumbnails (bpy.utils.previews), made on register


class DecalImportEntry(bpy.types.PropertyGroup):
    filename: StringProperty(name="File")
    role: EnumProperty(name="Used as", items=ROLE_ITEMS)


def surface_at_mouse(context, event):
    """(point, normal, object) of the mesh under the mouse (decals looked through), or None."""
    found = hit_under_mouse(context, event)
    if found is None:
        return None
    hit = cast_surface(context.scene, context.evaluated_depsgraph_get(), found[2], found[3], skip=decal_mesh.is_decal)
    return hit if hit is not None and hit[2].type == 'MESH' else None


def surface_at_cursor(context):
    """(point, normal, object) of the mesh at the 3D cursor along its Z (decals looked through), or None."""
    cursor = context.scene.cursor
    normal = cursor.matrix.to_3x3() @ Vector((0, 0, 1))
    start = cursor.location + normal * CURSOR_REACH
    hit = cast_surface(context.scene, context.evaluated_depsgraph_get(), start, -normal, skip=decal_mesh.is_decal)
    if hit is None or hit[2].type != 'MESH' or (hit[0] - cursor.location).length > CURSOR_REACH * 2:
        return None
    return hit


def peek_crop(path, alpha_path=None):
    """decal_maps.Crop of an image file without keeping it: images loaded only for this are removed again."""
    loaded = []

    def peek(file_path):
        existing = {image.name for image in bpy.data.images}
        image = bpy.data.images.load(file_path, check_existing=True)
        if image.name not in existing:
            loaded.append(image)
        return image
    try:
        return decal_material.visible_crop(peek(path), peek(alpha_path) if alpha_path else None)
    except RuntimeError:
        return None
    finally:
        for image in loaded:
            bpy.data.images.remove(image)


def thumbnail(path):
    """Preview icon id of an image file for the dialog (0 when it can't be read)."""
    if _previews is None or not path:
        return 0
    if path not in _previews:
        _previews.load(path, path, 'IMAGE')
    return _previews[path].icon_id


def make_decal(operator, context, images, stem, target, hit, place_at, size, start_as):
    """Shared by the dialog, the drop and Convert Reference: the decal from {role: image} on `hit` (point, normal,
    object), else at the 3D cursor surface, else Unattached at the cursor (Click on surface: then the click
    pick). Returns the decal."""
    settings = context.scene.digit_decals
    if hit is None and place_at == 'CURSOR':
        hit = surface_at_cursor(context)
        if hit is None:
            operator.report({'WARNING'}, "No surface at the 3D cursor: the decal waits there, unattached")
    if hit is not None:
        target = hit[2]
        decal = decal_mesh.create_decal(context, target, images, hit[0], hit[1], size, stem)
        settings.target = target
        if start_as == STUCK:
            for warning in decal_mesh.stick(context, decal):
                operator.report({'WARNING'}, warning)
    else:
        decal = decal_mesh.new_decal(context, images, stem, size, context.scene.cursor.location.copy())
    for ob in context.selected_objects:
        ob.select_set(False)
    decal.select_set(True)
    context.view_layer.objects.active = decal
    if hit is None and place_at == 'CLICK' and context.area is not None and context.area.type == 'VIEW_3D':
        bpy.ops.decal.aim('INVOKE_DEFAULT', decal_name=decal.name, stick_after=start_as == STUCK)
    return decal


class ImportImages:
    """The Import dialog's properties and steps, shared by the three import operators (a registered operator class
    can't be subclassed into another one, so they all build on this mixin)."""
    bl_options = {'REGISTER', 'UNDO'}
    aims_at_mouse = False      # drop operators: aim at the surface under the mouse

    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE', 'HIDDEN'})
    files: CollectionProperty(type=OperatorFileListElement, options={'SKIP_SAVE', 'HIDDEN'})
    entries: CollectionProperty(type=DecalImportEntry, options={'SKIP_SAVE'})
    target_name: StringProperty(name="Target", description="The mesh the decal goes on", options={'SKIP_SAVE'})
    place_at: EnumProperty(name="Place at", items=PLACE_ITEMS, default='CLICK')
    size: FloatProperty(name="Size", default=0.1, min=0.001, soft_max=1.0, subtype='DISTANCE', unit='LENGTH',
                        description="Length of the decal's long side")
    start_as: EnumProperty(name="Start as", items=START_ITEMS, default='PLACING')
    use_hit: BoolProperty(options={'HIDDEN', 'SKIP_SAVE'})
    hit_point: FloatVectorProperty(size=3, options={'HIDDEN', 'SKIP_SAVE'})
    hit_normal: FloatVectorProperty(size=3, options={'HIDDEN', 'SKIP_SAVE'})
    crop_text: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    crop_key: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    # --- files and roles
    def paths(self):
        return [os.path.join(self.directory, element.name) for element in self.files if element.name]

    def fill_entries(self):
        names = [os.path.basename(path) for path in self.paths()
                 if path.lower().endswith(decal_maps.IMAGE_EXTENSIONS)]
        self.entries.clear()
        for name, role in decal_maps.guess_roles(names).items() if names else ():
            entry = self.entries.add()
            entry.filename, entry.role = name, role

    def file_of(self, role):
        entry = next((entry for entry in self.entries if entry.role == role), None)
        return os.path.join(self.directory, entry.filename) if entry else None

    def update_crop(self):
        """Crop line for the current Color / Alpha files; True when it changed."""
        key = f"{self.file_of('COLOR')}|{self.file_of('ALPHA')}"
        if key == self.crop_key:
            return False
        self.crop_key = key
        color = self.file_of("COLOR")
        crop = peek_crop(color, self.file_of("ALPHA")) if color else None
        self.crop_text = f"Cropped to visible area: {crop.width_px} × {crop.height_px} px" if crop else ""
        return True

    # --- running
    def invoke(self, context, event):
        self.fill_entries()
        if not self.entries:
            self.report({'ERROR'}, "No images to import")
            return {'CANCELLED'}
        settings = context.scene.digit_decals
        target = settings.target or (context.active_object if context.active_object
                                     and context.active_object.type == 'MESH'
                                     and not decal_mesh.is_decal(context.active_object) else None)
        hit = surface_at_mouse(context, event) if self.aims_at_mouse else None
        if hit is not None:
            self.use_hit, self.hit_point, self.hit_normal = True, hit[0], hit[1]
            target = hit[2]
        self.target_name = target.name if target else ""
        self.update_crop()
        return self.after_invoke(context, hit)

    def after_invoke(self, context, hit):
        return context.window_manager.invoke_props_dialog(self, width=640, title="Import Decal Images",
                                                          confirm_text="Import + Place")

    def check(self, context):
        return self.update_crop()

    def execute(self, context):
        if not self.entries:
            self.fill_entries()
        images = {}
        for entry in self.entries:
            if entry.role != decal_maps.SKIP and entry.role not in images:
                path = os.path.join(self.directory, entry.filename)
                if os.path.isfile(path):
                    images[entry.role] = decal_material.load_image(path, entry.role)
        if "COLOR" not in images:
            self.report({'ERROR'}, "A decal needs a Color image: set one file's role to Color")
            return {'CANCELLED'}
        target = bpy.data.objects.get(self.target_name)
        hit = (Vector(self.hit_point), Vector(self.hit_normal), target) if self.use_hit and target else None
        stem = decal_maps.stem_of([entry.filename for entry in self.entries])
        make_decal(self, context, images, stem, target, hit, self.place_at, self.size, self.start_as)
        return {'FINISHED'}

    def draw(self, context):
        from .decal_ui import draw_import_dialog   # the dialog's look lives with the card's
        draw_import_dialog(self, self.layout, context)


class DECAL_OT_import_images(ImportImages, bpy.types.Operator):
    """Make a decal from images: one image is a sticker, a set (color, normal, glow...) is one full decal"""
    bl_idname = "decal.import_images"
    bl_label = "Import Decal Images"


class DECAL_OT_drop_dialog(ImportImages, bpy.types.Operator):
    """Make a decal from the dropped images: open the Import dialog, aimed at the surface under the mouse"""
    bl_idname = "decal.drop_dialog"
    bl_label = "Decal, open Import…"
    aims_at_mouse = True


class DECAL_OT_drop_place(ImportImages, bpy.types.Operator):
    """Make a decal from the dropped images right where they were dropped (no object there: the Import dialog)"""
    bl_idname = "decal.drop_place"
    bl_label = "Decal on Object"
    aims_at_mouse = True

    def after_invoke(self, context, hit):
        if hit is None:
            self.report({'INFO'}, "No object under the mouse: choose where in the Import dialog")
            return super().after_invoke(context, hit)
        return self.execute(context)


class DECAL_OT_add_images(bpy.types.Operator):
    """Pick one image (a sticker) or a set of maps (color, normal, glow...) for a new decal"""
    bl_idname = "decal.add_images"
    bl_label = "Add from Images…"
    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE', 'HIDDEN'})
    files: CollectionProperty(type=OperatorFileListElement, options={'SKIP_SAVE', 'HIDDEN'})
    filter_glob: StringProperty(default="*" + ";*".join(decal_maps.IMAGE_EXTENSIONS), options={'HIDDEN'})
    filter_image: BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        files = [{"name": element.name} for element in self.files if element.name]
        if not files:
            return {'CANCELLED'}
        bpy.ops.decal.import_images('INVOKE_DEFAULT', directory=self.directory, files=files)
        return {'FINISHED'}


# --- Convert Reference ---------------------------------------------------------------------------------------

def is_image_empty(ob):
    return ob is not None and ob.type == 'EMPTY' and ob.empty_display_type == 'IMAGE' and ob.data is not None


def reference_maps(image):
    """{role: image} for a Reference empty's image plus sibling maps next to its file (none for packed or
    generated images)."""
    images = {"COLOR": image}
    path = bpy.path.abspath(image.filepath) if image.source == 'FILE' and not image.packed_file else ""
    if not path or not os.path.isfile(path):
        return images
    folder = os.path.dirname(path)
    for role, name in decal_maps.sibling_maps(path, os.listdir(folder)).items():
        if role not in ("COLOR", decal_maps.SKIP):
            images[role] = decal_material.load_image(os.path.join(folder, name), role)
    return images


def reference_aim(empty, crop):
    """(world ray start, image width, height, local frame) of a Reference empty: the start is the middle of the
    image's visible part; width / height are the whole image's size in world units (scale included)."""
    image = empty.data
    width_px, height_px = image.size if image.size[0] else (1, 1)
    aspect = width_px / max(1, height_px)
    long_side = empty.empty_display_size
    width, height = (long_side, long_side / aspect) if aspect >= 1 else (long_side * aspect, long_side)
    offset_x, offset_y = empty.empty_image_offset
    middle_u, middle_v = (crop.u0 + crop.u1) / 2, (crop.v0 + crop.v1) / 2
    local = Vector(((offset_x + middle_u) * width, (offset_y + middle_v) * height, 0.0))
    scale = empty.matrix_world.to_scale()
    return empty.matrix_world @ local, width * abs(scale.x), height * abs(scale.y)


class DECAL_OT_convert_reference(bpy.types.Operator):
    """Turn the selected Reference image into a decal on the object behind it (projected along the image's facing).
    Sibling maps (_normal, _emit...) next to its file are used too. The empty is hidden, not deleted"""
    bl_idname = "decal.convert_reference"
    bl_label = "Convert to Decal"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return is_image_empty(context.active_object)

    def execute(self, context):
        empty = context.active_object
        images = reference_maps(empty.data)
        crop = decal_material.visible_crop(images["COLOR"], images.get("ALPHA"))
        start, width, height = reference_aim(empty, crop)
        facing = (empty.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        depsgraph = context.evaluated_depsgraph_get()
        hit = None
        for direction in (-facing, facing):   # behind the image first, then in front of it
            hit = cast_surface(context.scene, depsgraph, start, direction, skip=decal_mesh.is_decal)
            if hit is not None and hit[2].type == 'MESH':
                break
            hit = None
        if hit is None:
            self.report({'ERROR'}, NOTHING_BEHIND)
            return {'CANCELLED'}
        size = max((crop.u1 - crop.u0) * width, (crop.v1 - crop.v0) * height)
        up = empty.matrix_world.to_3x3() @ Vector((0, 1, 0))
        stem = decal_maps.split_name(empty.data.name)[0]
        decal = decal_mesh.create_decal(context, hit[2], images, hit[0], hit[1], size, stem, up=up)
        context.scene.digit_decals.target = hit[2]
        empty.hide_set(True)
        empty.hide_render = True
        decal.select_set(True)
        context.view_layer.objects.active = decal
        self.report({'INFO'}, f"{decal.name} · Placing (the reference is hidden, not deleted)")
        return {'FINISHED'}


CLASSES = (DecalImportEntry, DECAL_OT_import_images, DECAL_OT_drop_dialog, DECAL_OT_drop_place, DECAL_OT_add_images,
           DECAL_OT_convert_reference)


def register():
    global _previews
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _previews = bpy.utils.previews.new()


def unregister():
    global _previews
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
