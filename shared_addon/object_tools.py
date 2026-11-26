"""Small object helpers used by several add-ons: selection, removal, mode switches, free file names."""

import os

import bpy


def select_only(context, objects, active=None):
    """Select exactly `objects` and make `active` the active object (when given).
    Loops over the view layer, not context.selected_objects: that can hold removed objects."""
    wanted = set(objects)
    for ob in context.view_layer.objects:
        if ob not in wanted and ob.select_get():
            ob.select_set(False)
    for ob in wanted:  # not only the view layer's list: a new object may not be in it yet
        ob.select_set(True)
    if active is not None:
        context.view_layer.objects.active = active


def remove_object(ob):
    """Remove the object, then its data when nothing else uses it."""
    data = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.batch_remove([data])


def set_mode(ob, mode):
    """Make `ob` active and put it in `mode`. It must be in the view layer."""
    bpy.context.view_layer.objects.active = ob
    with bpy.context.temp_override(active_object=ob, object=ob, selected_objects=[ob]):
        bpy.ops.object.mode_set(mode=mode)


def ensure_object_mode(context):
    """Leave Edit, Pose or any other mode for Object Mode."""
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def free_path(folder, stem, ext=".png"):
    """folder/stem+ext, or stem-2, stem-3 ... if that exists. Never an existing path."""
    path, number = os.path.join(folder, stem + ext), 2
    while os.path.exists(path):
        path, number = os.path.join(folder, f"{stem}-{number}{ext}"), number + 1
    return path
