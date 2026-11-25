# SPDX-License-Identifier: GPL-3.0-or-later
"""Look At (Digit's Tools > Character Rigs; a row in the Selected card's Character Rig box too): click a spot in the 3D
viewport and the eyes, or the eyes and head, of a character look at that spot.

The click: on a surface the hit point (a ray cast of the evaluated scene), on empty space the point at the depth of
the character's eyes along the view ray. Esc / right click cancels. Clicking again later moves the spot.

A rig with a look rig (look_rig.py: HeadLookFocus, built by the Eye Rig): the click only moves HeadLookFocus there;
nothing is added. The card shows the rig's own Focus, Head Aim, Look Follow and Pupil Size sliders.

Any other rig: the spot is held by one small target empty per rig (a wire helper, never rendered, in the rig's
collection; grab it or key it like any object). It is not parented to anything. Blender does the tracking: one Damped
Track constraint named "Look At" on each eye bone (influence 1) and, in Eyes + Head mode, on the head bone (influence =
Head Amount). Off removes those constraints and every helper, so the rig is as before. Older builds aimed at an
object; turning them on, off or clicking a new spot clears that set-up the same way.

Eye Cross (helper path): each eye aims at its own helper (a child of an anchor that copies the target's position and
the head's turn) at the target plus (1 - Eye Cross) x the eye's offset from the eyes' midpoint: 1 = both eyes on the
target, 0 = parallel, above 1 = crossed, below 0 = wall-eyed. No bones are added.

Bones are found by standard name through rig_names (Eye.L / Eye1.L, Head, in any naming style). No handlers, no timers:
the click modal only lives while the user is picking."""
import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty
from mathutils import Vector

from . import look_rig, rig_names as rn, view_ray  # generated copies
from .modifier_setup import style_helper  # generated copy
from .bone_chain import rig_for_chain  # generated copy
from .rig_parts import prop_label  # generated copy
from .ui_cards import action_row, hints, prop_group, status  # generated copy

CONSTRAINT_NAME = "Look At"
MODE_ITEMS = (("EYES", "Eyes", "Only the eyes look at the spot"),
              ("EYES_HEAD", "Eyes + Head", "The eyes look at the spot and the head turns part of the way"))
FALLBACK_FORWARD = Vector((0.0, -1.0, 0.0))   # Blender's front view looks along +Y, characters face -Y
AXIS_NAMES = ("X", "Y", "Z")
HEAD_PART = "Head"
HELPER_KEY = "digit_look_at_helper"     # custom property of a helper object: the name of its rig
HELPER_EYE_KEY = "digit_look_at_eye"    # custom property of an eye helper: the eye bone it serves
TARGET_KEY = "digit_look_at_target"     # custom property of the target empty (the spot)
CROSS_RANGE = (-1.0, 3.0)
HELPER_SIZE = 0.03
TARGET_SIZE = 0.08
AHEAD = 1.0                             # metres: the spot when Look At is turned on without a click
RIG_SLIDERS = (look_rig.FOCUS_PROP, "HeadAim", look_rig.LOOK_FOLLOW, look_rig.PUPIL_SIZE, look_rig.IRIS_SIZE)   # on HeadLookFocus


# ---------------------------------------------------------------------------
# Finding the bones
# ---------------------------------------------------------------------------

def eye_bone_names(rig):
    """Names of the rig's eye bones: Eye.L / Eye.R (or Eye1.L of a numbered chain, or one Eye), standard names."""
    names = [pose_bone.name for pose_bone in rig.pose.bones]
    found = []
    for side in ("L", "R", ""):
        name = rn.find(names, rn.build("Eye", side)) or rn.find(names, rn.build("Eye", side, 1))
        if name and name not in found:
            found.append(name)
    return found


def head_bone_name(rig):
    """The standard-name head bone (any naming style rig_names reads), or None."""
    return rn.find([bone.name for bone in rig.pose.bones], HEAD_PART)


def look_at_constraints(rig):
    """[(pose bone, constraint)] of every Look At constraint on the rig."""
    return [(pose_bone, constraint) for pose_bone in rig.pose.bones for constraint in pose_bone.constraints
            if constraint.name == CONSTRAINT_NAME]


def is_on(rig):
    return bool(look_at_constraints(rig))


def eyes_point(rig):
    """World point between the eyes as posed (the head when there are no eyes, else the rig's origin)."""
    names = eye_bone_names(rig) or [name for name in [head_bone_name(rig)] if name]
    if not names:
        return rig.matrix_world.translation.copy()
    return rig.matrix_world @ (sum((rig.pose.bones[name].head for name in names), Vector()) / len(names))


def ahead_point(rig):
    """A spot straight in front of the eyes (Look At turned on without a click)."""
    eyes = eye_bone_names(rig)
    forward = sum(((rig.matrix_world @ rig.pose.bones[name].matrix).to_3x3().col[1] for name in eyes), Vector())
    forward = forward if forward.length > 1e-6 else rig.matrix_world.to_3x3() @ FALLBACK_FORWARD
    return eyes_point(rig) + forward.normalized() * AHEAD


# ---------------------------------------------------------------------------
# The rig's own look rig (HeadLookFocus)
# ---------------------------------------------------------------------------

def move_rig_focus(context, rig, point):
    """Put the rig's HeadLookFocus on the world `point` (keyed when auto-keying is on)."""
    pose_bone = rig.pose.bones[look_rig.FOCUS]
    matrix = pose_bone.matrix.copy()
    matrix.translation = rig.matrix_world.inverted() @ point
    pose_bone.matrix = matrix
    if look_rig.FOCUS_PROP in pose_bone:
        pose_bone[look_rig.FOCUS_PROP] = 1.0      # both eyes on the target
        if context.scene.tool_settings.use_keyframe_insert_auto:
            pose_bone.keyframe_insert(f'["{look_rig.FOCUS_PROP}"]')
    if context.scene.tool_settings.use_keyframe_insert_auto:
        pose_bone.keyframe_insert("location")


# ---------------------------------------------------------------------------
# Helper path: the target empty and the constraints
# ---------------------------------------------------------------------------

def forward_axis_name(rig, head_name, eye_names):
    """The Damped Track axis name ('TRACK_Z', 'TRACK_NEGATIVE_X'...) for the head bone's face-forward direction: the
    eye bones' pointing direction at rest, in the head bone's rest space (world -Y when there are no eyes)."""
    head_matrix = rig.data.bones[head_name].matrix_local.to_3x3()
    if eye_names:
        forward = sum((rig.data.bones[name].matrix_local.to_3x3().col[1] for name in eye_names), Vector())
    else:
        forward = FALLBACK_FORWARD
    local = head_matrix.inverted() @ forward
    axis = max(range(3), key=lambda index: abs(local[index]))
    return "TRACK_" + ("NEGATIVE_" if local[axis] < 0 else "") + AXIS_NAMES[axis]


def add_constraint(rig, bone_name, target, track_axis, influence):
    constraint = rig.pose.bones[bone_name].constraints.new('DAMPED_TRACK')
    constraint.name = CONSTRAINT_NAME
    constraint.target = target
    constraint.track_axis = track_axis
    constraint.influence = influence
    return constraint


def helper_objects(rig):
    return [ob for ob in bpy.data.objects if ob.get(HELPER_KEY) == rig.name]


def target_object(rig):
    """The rig's target empty (the spot), or None."""
    return next((ob for ob in helper_objects(rig) if ob.get(TARGET_KEY)), None)


def new_helper(rig, name, parent=None, size=HELPER_SIZE):
    """A wire empty for `rig` in its collection (or the scene's), styled as a helper and tagged so Off finds it."""
    ob = bpy.data.objects.new(f"{name} ({rig.name})", None)
    ob.empty_display_size = size
    ob[HELPER_KEY] = rig.name
    style_helper(ob)
    (rig.users_collection[0] if rig.users_collection else bpy.context.scene.collection).objects.link(ob)
    ob.parent = parent
    return ob


def place_target(context, rig, point):
    """The target empty at the world `point` (made when missing, straight ahead without a point; keyed when
    auto-keying is on). Returns it."""
    target = target_object(rig)
    if target is None:
        target = new_helper(rig, "Look At Target", size=TARGET_SIZE)
        target.empty_display_type = 'SPHERE'
        target[TARGET_KEY] = True
        point = ahead_point(rig) if point is None else point
    if point is not None:
        target.location = point
        if context.scene.tool_settings.use_keyframe_insert_auto:
            target.keyframe_insert("location")
    return target


def head_frame(rig, head_name):
    """(frame object, its bone or '', rest rotation of the frame in world space): the head bone, else the rig."""
    if head_name:
        return rig, head_name, (rig.matrix_world @ rig.data.bones[head_name].matrix_local).to_3x3().normalized()
    return rig, "", rig.matrix_world.to_3x3().normalized()


def eye_offsets(rig, eyes, head_name):
    """{eye bone: its rest offset from the eyes' midpoint, in the head frame (the helpers turn with the head)}."""
    centres = {name: rig.data.bones[name].head_local for name in eyes}
    if not centres:
        return {}
    midpoint = sum(centres.values(), Vector()) / len(centres)
    rest_rotation = head_frame(rig, head_name)[2]
    return {name: rest_rotation.inverted() @ (rig.matrix_world.to_3x3() @ (centre - midpoint))
            for name, centre in centres.items()}


def build_helpers(rig, target, eyes, head_name, cross):
    """The anchor (target position + head rotation) and one helper per eye; returns {eye bone: helper}."""
    anchor = new_helper(rig, "Look At Anchor")
    position = anchor.constraints.new('COPY_LOCATION')
    position.target = target
    frame_object, frame_bone, _rest = head_frame(rig, head_name)
    rotation = anchor.constraints.new('COPY_ROTATION')
    rotation.target, rotation.subtarget = frame_object, frame_bone
    helpers = {}
    for name in eyes:
        helpers[name] = new_helper(rig, f"Look At {name}", parent=anchor)
        helpers[name][HELPER_EYE_KEY] = name
    set_cross(rig, cross, head_name, eyes)
    return helpers


def set_cross(rig, cross, head_name=None, eyes=None):
    """Move the eye helpers for this Eye Cross value (1 = on the target, 0 = parallel, above 1 = crossed)."""
    head_name = head_bone_name(rig) if head_name is None else head_name
    offsets = eye_offsets(rig, eyes if eyes is not None else eye_bone_names(rig), head_name)
    for helper in helper_objects(rig):
        offset = offsets.get(helper.get(HELPER_EYE_KEY))
        if offset is not None:
            helper.location = offset * (1.0 - cross)


def remove_tracking(rig, keep_target=True):
    """Remove every Look At constraint and helper object (an older build's object-aimed set-up too), except the target
    empty when `keep_target`. Returns how many constraints were removed."""
    found = look_at_constraints(rig)
    for pose_bone, constraint in found:
        pose_bone.constraints.remove(constraint)
    for helper in helper_objects(rig):
        if not (keep_target and helper.get(TARGET_KEY)):
            bpy.data.objects.remove(helper)
    return len(found)


def turn_off(rig):
    """Look At off: constraints, helpers and the target empty go; the rig is as before."""
    return remove_tracking(rig, keep_target=False)


def turn_on(context, rig, point=None, include_head=False, head_amount=0.5, cross=1.0):
    """The eyes (and the head) of `rig` look at the world `point` (None: keep the current spot, else straight ahead).
    Rebuilds the tracking on the one target empty. Returns (eye bone names, head bone name or None); nothing is added
    when the rig has no eye bones (and no head to turn)."""
    eyes, head = eye_bone_names(rig), head_bone_name(rig)
    if not eyes and not (include_head and head):
        turn_off(rig)
        return [], None
    remove_tracking(rig)
    target = place_target(context, rig, point)
    helpers = build_helpers(rig, target, eyes, head or "", cross) if eyes else {}
    for name, helper in helpers.items():
        add_constraint(rig, name, helper, 'TRACK_Y', 1.0)
    if include_head and head:
        add_constraint(rig, head, target, forward_axis_name(rig, head, eyes), head_amount)
    return eyes, head if include_head and head else None


def settings_of(wm):
    return dict(include_head=wm.digit_look_mode == 'EYES_HEAD', head_amount=wm.digit_look_head_amount,
                cross=wm.digit_look_cross)


def look_at_point(context, rig, point=None):
    """Make the character look at the world `point` the one way its rig takes. Returns a report text; an error
    text starts with 'No '."""
    if look_rig.has_look_rig(rig):
        move_rig_focus(context, rig, ahead_point(rig) if point is None else point)
        return f"{look_rig.FOCUS} moved to the spot"
    eyes, head = turn_on(context, rig, point, **settings_of(context.window_manager))
    if not eyes and not head:
        return "No eye or head bones found"
    return f"Looking at the spot: {len(eyes)} eye bone(s)" + (", head" if head else "")


def refresh(self, context):
    """A setting changed while Look At is on: build it again on the same spot (a UI callback, not background work)."""
    rig = rig_for_chain(context)
    if rig is not None and is_on(rig):
        turn_on(context, rig, None, **settings_of(context.window_manager))


def refresh_cross(self, context):
    """Eye Cross moved: only the helpers move (while Look At is on)."""
    rig = rig_for_chain(context)
    if rig is not None and is_on(rig):
        set_cross(rig, context.window_manager.digit_look_cross)


# ---------------------------------------------------------------------------
# The click
# ---------------------------------------------------------------------------

def depth_point(origin, direction, reference):
    """The point on the ray at the depth of `reference` (a short way out when the reference is behind the view)."""
    direction = direction.normalized()
    return origin + direction * max((reference - origin).dot(direction), HELPER_SIZE)


def clicked_point(context, event, rig):
    """The world spot a click means for `rig`: the surface hit, else the point on the view ray at the eyes' depth.
    None when the mouse is over no 3D view."""
    found = view_ray.hit_under_mouse(context, event)
    if found is None:
        return None
    point, _ob, origin, direction = found
    return point if point is not None else depth_point(origin, direction, eyes_point(rig))


def usable_rig(cls, context):
    rig = rig_for_chain(context)
    if rig is None or rig.library:
        cls.poll_message_set("Select a local armature, or a mesh deformed by one")
        return False
    return True


class DIGITOOLS_OT_look_at_point(bpy.types.Operator):
    """Click where the eyes should look: a surface, or empty space at the eyes' depth. Esc or right click cancels"""
    bl_idname = "digits_assorted_tools.look_at_point"
    bl_label = "Look At a Spot"
    bl_options = {'REGISTER', 'UNDO'}

    location: FloatVectorProperty(name="Spot", subtype='TRANSLATION', options={'SKIP_SAVE'},
                                  description="World point to look at (scripts; a click sets it)")

    @classmethod
    def poll(cls, context):
        return usable_rig(cls, context)

    def execute(self, context):
        text = look_at_point(context, rig_for_chain(context), Vector(self.location))
        if text.startswith("No "):
            self.report({'WARNING'}, text)
            return {'CANCELLED'}
        self.report({'INFO'}, text)
        return {'FINISHED'}

    def invoke(self, context, event):
        if context.space_data is None or context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Click in the 3D viewport")
            return {'CANCELLED'}
        self.rig_name = rig_for_chain(context).name
        return view_ray.begin_click(context, self, 'CROSSHAIR', "Click where the eyes should look  ·  Esc / right click: cancel")

    def modal(self, context, event):
        kind = view_ray.click_kind(event)
        if kind == 'cancel':
            view_ray.end_click(context)
            return {'CANCELLED'}
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind == 'wait':
            context.window.cursor_modal_set('CROSSHAIR')   # other areas reset it as the mouse crosses them
            return {'RUNNING_MODAL'}
        rig = bpy.data.objects.get(self.rig_name)
        point = clicked_point(context, event, rig) if rig else None
        if point is None:      # a click outside every 3D view (sidebar, header): let the UI have it
            return {'PASS_THROUGH'}
        view_ray.end_click(context)
        self.location = point
        return self.execute(context)


class DIGITOOLS_OT_look_at(bpy.types.Operator):
    """Turn Look At on or off: on starts the click (the eyes look where you click). Off puts the rig back"""
    bl_idname = "digits_assorted_tools.look_at"
    bl_label = "Look At"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return usable_rig(cls, context)

    def invoke(self, context, event):
        in_viewport = context.space_data is not None and context.space_data.type == 'VIEW_3D'
        if is_on(rig_for_chain(context)) or not in_viewport:
            return self.execute(context)
        return bpy.ops.digits_assorted_tools.look_at_point('INVOKE_DEFAULT')

    def execute(self, context):
        rig = rig_for_chain(context)
        if is_on(rig):
            turn_off(rig)
            return {'FINISHED'}
        text = look_at_point(context, rig)
        if text.startswith("No "):
            self.report({'WARNING'}, text)
            return {'CANCELLED'}
        self.report({'INFO'}, text)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

def draw_toggle(layout, rig):
    """The Look At row (also used by the Selected card): a click-a-spot button, plus On / Off without a look rig."""
    row = action_row(layout)
    if look_rig.has_look_rig(rig):
        row.operator(DIGITOOLS_OT_look_at_point.bl_idname, text="Look At: Click a Spot", icon='EYEDROPPER')
        return
    on = is_on(rig)
    row.operator(DIGITOOLS_OT_look_at.bl_idname, text="Look At: On" if on else "Look At: Off",
                 icon='HIDE_OFF' if on else 'HIDE_ON', depress=on)
    row.operator(DIGITOOLS_OT_look_at_point.bl_idname, text="", icon='EYEDROPPER')


def draw_rig_sliders(layout, rig, keys):
    """The rig's own look sliders on HeadLookFocus."""
    pose_bone = rig.pose.bones[look_rig.FOCUS]
    col = layout.column(align=True)
    for key in keys:
        if key in pose_bone:
            col.prop(pose_bone, f'["{key}"]', text=prop_label(key), slider=key != look_rig.LOOK_FOLLOW)


def draw_eye_cross(layout, context, rig):
    """The Selected card's eye sliders: the rig's Focus, Pupil Size and Iris Size, else Eye Cross."""
    if look_rig.has_look_rig(rig):
        draw_rig_sliders(layout, rig, [look_rig.FOCUS_PROP, look_rig.PUPIL_SIZE, look_rig.IRIS_SIZE])
    else:
        prop_group(layout, context.window_manager, ["digit_look_cross"])


def draw_card(layout, context):
    rig = rig_for_chain(context)
    if rig is None:
        status(layout, "Select a character's armature")
        return
    wm = context.window_manager
    eyes, head = eye_bone_names(rig), head_bone_name(rig)
    status(layout, f"{len(eyes)} eye bone(s), head {'found' if head else 'missing'}", icon='HIDE_OFF')
    draw_toggle(layout, rig)
    hints(layout, ["Click where the eyes should look. Click again to move it"], context)
    if look_rig.has_look_rig(rig):
        draw_rig_sliders(layout, rig, RIG_SLIDERS)
        hints(layout, [f"The rig's own look target ({look_rig.FOCUS}) moves to the spot"], context)
        return
    prop_group(layout, wm, ["digit_look_mode"] + (["digit_look_head_amount"] if wm.digit_look_mode == 'EYES_HEAD' else [])
               + ["digit_look_cross"])
    hints(layout, ["A small target empty holds the spot: grab it or key it", "Off removes it and the rig is as before"],
          context)


CLASSES = (DIGITOOLS_OT_look_at_point, DIGITOOLS_OT_look_at)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    wm = bpy.types.WindowManager
    wm.digit_look_mode = EnumProperty(name="Track With", items=MODE_ITEMS, default='EYES', update=refresh)
    wm.digit_look_cross = FloatProperty(
        name="Eye Cross", default=1.0, min=CROSS_RANGE[0], max=CROSS_RANGE[1], update=refresh_cross,
        description="1 = both eyes look at the spot, 0 = the eyes look the same way (parallel), above 1 = crossed eyes, below 0 = wall-eyed")
    wm.digit_look_head_amount = FloatProperty(
        name="Head Amount", default=0.5, min=0.0, max=1.0, subtype='FACTOR', update=refresh,
        description="How far the head turns towards the spot (1 = all the way)")


def unregister():
    del bpy.types.WindowManager.digit_look_head_amount
    del bpy.types.WindowManager.digit_look_cross
    del bpy.types.WindowManager.digit_look_mode
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
