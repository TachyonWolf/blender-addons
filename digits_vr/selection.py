# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection of objects and pose bones by picking.Target, and the list of items a grab moves (parent-first:
an item whose ancestor also moves is left to follow it). Used by the select and grab tools."""
from . import edit_select, router, workspace
from .picking import BONE, is_linked


def pose_armatures(context):
    return [ob for ob in context.view_layer.objects if ob.type == 'ARMATURE' and ob.mode == 'POSE']


def is_selected(context, target):
    ob = target.find_object(context.blend_data)
    if ob is None:
        return False
    if target.kind == BONE:
        pose_bone = ob.pose.bones.get(target.bone_name)
        return bool(pose_bone and pose_bone.select)
    return ob.select_get(view_layer=context.view_layer)


def _set_bone(ob, pose_bone, selected):
    pose_bone.select = selected
    if selected:
        ob.data.bones.active = pose_bone.bone


def apply(context, target, outcome):
    """Apply a router select outcome (REPLACE / TOGGLE / CLEAR) for `target` (None for CLEAR). Returns True when
    something changed."""
    if router.mode_kind(context.mode) == router.EDIT:
        return edit_select.apply(context, target, outcome)
    layer = context.view_layer
    pose = router.mode_kind(context.mode) == router.POSE
    if outcome == router.CLEAR:
        if pose:
            for ob in pose_armatures(context):
                for pose_bone in ob.pose.bones:
                    pose_bone.select = False
        else:
            for ob in layer.objects:
                ob.select_set(False)
        return True
    ob = target.find_object(context.blend_data)
    if ob is None:
        return False
    if target.kind == BONE:
        pose_bone = ob.pose.bones.get(target.bone_name)
        if pose_bone is None:
            return False
        if outcome == router.REPLACE:
            for armature in pose_armatures(context):
                for other in armature.pose.bones:
                    other.select = False
            _set_bone(ob, pose_bone, True)
        else:
            _set_bone(ob, pose_bone, not pose_bone.select)
        return True
    if outcome == router.REPLACE:
        for other in layer.objects:
            other.select_set(False)
        ob.select_set(True)
        layer.objects.active = ob
    else:
        ob.select_set(not ob.select_get())
        if ob.select_get():
            layer.objects.active = ob
    return True


def _without_descendants(items, parent_of):
    """Keep items none of whose ancestors are in `items` (parent-first: a moved parent carries its children)."""
    chosen = set(items)
    kept = []
    for item in items:
        ancestor = parent_of(item)
        while ancestor is not None and ancestor not in chosen:
            ancestor = parent_of(ancestor)
        if ancestor is None:
            kept.append(item)
    return kept


def _select_for_grab(context, hit, grip_target=router.AIMED):
    """A grip on an unselected item selects only it first (Aimed); hit None keeps the selection."""
    if hit is not None and router.grab_targets(is_selected(context, hit), grip_target) == router.ONLY_HIT:
        apply(context, hit, router.REPLACE)


def grab_objects(context, hit=None, grip_target=router.AIMED):
    """Objects a grip on `hit` moves (editable, parent-first); hit None = the current selection."""
    _select_for_grab(context, hit, grip_target)
    objects = [ob for ob in context.view_layer.objects
               if ob.select_get() and not is_linked(ob) and workspace.reaches(context.scene, ob)]
    return _without_descendants(objects, lambda ob: ob.parent)


def grab_bones(context, hit=None, grip_target=router.AIMED):
    """[(armature, pose bone)] a grip on `hit` moves (editable armatures, parent-first); hit None = the current
    selection."""
    _select_for_grab(context, hit, grip_target)
    result = []
    for ob in pose_armatures(context):
        if is_linked(ob):
            continue
        bones = [pose_bone for pose_bone in ob.pose.bones if pose_bone.select and not pose_bone.bone.hide]
        result += [(ob, pose_bone) for pose_bone in _without_descendants(bones, lambda bone: bone.parent)]
    return result
