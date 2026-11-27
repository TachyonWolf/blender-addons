# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/character_link.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Character Link: put a character from its master .blend into the open file as a library override.

The master is never written: the collection is linked (read-only) and overridden in this file, with
its armatures made editable so the character can be posed. Collections the master has turned off in
its view layer (alternate tails, outfits...) are turned off here too, and objects hidden there (bone
shape widgets...) are hidden, so the character looks the
same as in its own file. Used by batch_tools/make_inspect.py (every character's <Main>Inspect.blend) and Digit's Assorted Tools
(Texture Studio > Add Character); both get a synced copy.

    import character_link
    coll = character_link.link_character("//../Characters/X/X.blend", "X")
"""
import bpy
from mathutils import Matrix, Vector


def _master_excludes(path, collection_name):
    """({collection name: excluded}, {names of hidden objects}) from the first master scene whose view
    layer holds the collection.

    Reads the master's scene by linking it for a moment, then removes the linked scene again."""
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        dst.scenes = list(src.scenes)
    excludes, hidden = {}, set()
    try:
        for scene in dst.scenes:
            if scene is None:
                continue
            found = {}

            def walk(layer):
                found[layer.collection.name] = layer.exclude
                for child in layer.children:
                    walk(child)

            walk(scene.view_layers[0].layer_collection)
            if collection_name in found:
                excludes = found
                view_layer = scene.view_layers[0]
                hidden = {ob.name for ob in view_layer.objects if ob.hide_get(view_layer=view_layer)}
                break
    finally:
        for scene in dst.scenes:
            if scene is not None:
                bpy.data.scenes.remove(scene)
    return excludes, hidden


def apply_excludes(layer_collection, excludes):
    """Turn off (exclude) the collections under layer_collection that are off in excludes."""
    for child in layer_collection.children:
        if excludes.get(child.collection.name):
            child.exclude = True
        apply_excludes(child, excludes)


def find_layer_collection(layer_collection, collection):
    if layer_collection.collection == collection:
        return layer_collection
    for child in layer_collection.children:
        found = find_layer_collection(child, collection)
        if found:
            return found
    return None


def is_locked_override(ob):
    """True for an object that is a library override but still a system override (locked: no Add Modifier).
    Cheap (a few attribute reads): fine for a panel poll."""
    return ob is not None and ob.override_library is not None and ob.override_library.is_system_override


def make_editable(objects):
    """Make each locked override in `objects` editable (object level, so modifiers can be added); return how many changed."""
    changed = 0
    for ob in objects:
        if is_locked_override(ob):
            ob.override_library.is_system_override = False
            changed += 1
    return changed


def _finish_override(override, view_layer, excludes, hidden, editable_armatures, editable_all=False):
    """Make the override's armatures (or, with editable_all, every object) editable, turn off the master's turned-off
    collections, hide what it hides."""
    if editable_all:
        make_editable(override.all_objects)
    elif editable_armatures:
        make_editable(ob for ob in override.all_objects if ob.type == 'ARMATURE')
    layer = find_layer_collection(view_layer.layer_collection, override)
    if layer:
        apply_excludes(layer, excludes)
    for ob in override.all_objects:   # objects hidden in the master's viewport (H) stay hidden here
        if ob.name in hidden and ob.name in view_layer.objects:
            ob.hide_set(True, view_layer=view_layer)


def link_character(path, collection_name, scene=None, view_layer=None, editable_armatures=True):
    """Link collection_name from the .blend at path into scene as a library override; return it."""
    scene = scene or bpy.context.scene
    view_layer = view_layer or bpy.context.view_layer
    excludes, hidden = _master_excludes(path, collection_name)
    with bpy.data.libraries.load(path, link=True) as (src, dst):
        if collection_name not in src.collections:
            raise ValueError(f"no collection '{collection_name}' in {path}")
        dst.collections = [collection_name]
    linked = dst.collections[0]
    scene.collection.children.link(linked)  # the override needs an instance to replace
    override = linked.override_hierarchy_create(scene, view_layer, reference=linked, do_fully_editable=False)
    for child in list(scene.collection.children):  # drop the linked instance, keep the override
        if child is linked:
            scene.collection.children.unlink(child)
    _finish_override(override, view_layer, excludes, hidden, editable_armatures)
    return override


# ---------------------------------------------------------------- Make Posable (override what is already in the file)

def needs_override(ob):
    """True for an Empty that instances a library collection, or a linked object that is not overridden yet.
    Cheap (a few attribute reads on one object): fine for a panel poll."""
    if ob is None:
        return False
    if ob.type == 'EMPTY' and ob.instance_type == 'COLLECTION':
        return ob.instance_collection is not None and ob.instance_collection.library is not None
    return ob.library is not None and ob.override_library is None


def _main_armature(override):
    """The override's armature to pose: one with no parent first, else the first; None when it has none."""
    armatures = [ob for ob in override.all_objects if ob.type == 'ARMATURE']
    return next((ob for ob in armatures if ob.parent is None), armatures[0] if armatures else None)


def _linked_collection_of(ob):
    """The library collection a linked object sits in (the top one of its chain), else None."""
    return next((c for c in ob.users_collection if c.library is not None), None)


def make_posable(context, ob):
    """Make the linked thing `ob` a library override (what needs_override says): an instancing Empty is replaced by
    the override of its collection, a linked object by the override of its collection. Every object becomes editable
    (posable, can take modifiers), the master's turned-off collections stay off. Selects and activates the armature (else the first
    object) and returns it. Raises ValueError when it cannot (the message says why)."""
    scene, view_layer = context.scene, context.view_layer
    instancer = ob if ob.type == 'EMPTY' and ob.instance_type == 'COLLECTION' else None
    linked = instancer.instance_collection if instancer else _linked_collection_of(ob)
    if linked is None:
        raise ValueError(f"{ob.name} is linked, but not through a collection, so it cannot be overridden here")
    path = bpy.path.abspath(linked.library.filepath)
    try:
        excludes, hidden = _master_excludes(path, linked.name)
    except (OSError, RuntimeError):   # master file not at that path any more: still override, keep every collection on
        excludes, hidden = {}, set()
    if instancer:   # a fresh Empty (just dropped) has a stale matrix_world (identity) until the view layer updates
        view_layer.update()
        matrix = instancer.matrix_world @ Matrix.Translation(-Vector(linked.instance_offset))   # the instance puts the collection's offset point at the Empty
    else:
        matrix = None
    if instancer is None and linked.name not in scene.collection.children and linked.name not in scene.collection.children_recursive:
        scene.collection.children.link(linked)   # the override needs an instance to replace
    override = linked.override_hierarchy_create(scene, view_layer, reference=instancer or linked, do_fully_editable=False)
    if override is None:
        raise ValueError(f"Blender could not make an override of {linked.name}")
    if instancer is not None and instancer.name in bpy.data.objects:   # the override replaces the instancing Empty
        bpy.data.objects.remove(instancer)
    for parent in (scene.collection, *scene.collection.children_recursive):   # drop the linked original, keep the override
        if parent.library is None and linked in parent.children[:]:
            parent.children.unlink(linked)
    _finish_override(override, view_layer, excludes, hidden, True, editable_all=True)
    if matrix is not None:   # keep the place, turn and size the Empty had (roots have no parent: matrix_basis is their world matrix)
        for root in (o for o in override.all_objects if o.parent is None):
            root.matrix_basis = matrix @ root.matrix_basis
    rig = _main_armature(override) or next(iter(override.all_objects), None)
    if rig is None:
        raise ValueError(f"{linked.name} has no objects to select")
    for other in context.selected_objects:
        other.select_set(False)
    if rig.name in view_layer.objects:
        rig.select_set(True)
        view_layer.objects.active = rig
    return rig
