# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool gun's nine tools. `shoot` does one shot and returns the undo message when the scene changed, "" when it did
not, or a hold (PlaceHold) that goes on while the trigger is held; Refused = buzz + a reason. Two-shot tools keep what the
first shot picked in gun_state.STATE.pending (by name: refs die on undo)."""
import math

import bpy
from mathutils import Matrix, Vector

from . import gun_targets as targets, hide, pose_mirror, rig_tab, router, select_gesture, settings, size_state, tools
from .context_helper import run_in_view3d, view3d_override
from .gun_state import STATE, Measured
from .gun_targets import Refused
from .picking import OBJECT, is_linked
from .runtime import RUNTIME
from .transform_math import Channels, Locks, channels_from_basis

TWIST_GAIN = 2.0             # degrees a placed thing turns per degree of wrist twist
SMALLEST_MOVE = 1e-6


class GunTool:
    modes = (router.OBJECT, router.POSE)
    keeps_pick = False       # an undo / redo does not drop what the first shot picked
    bones = False            # Pose mode: picks bones (else objects)

    def shoot(self, context, shot):
        raise NotImplementedError


class TwoShotTool(GunTool):
    """First shot: `first` returns the name of what it picked. Second shot: `second` uses it."""
    next_hint = "Now shoot a spot"

    def shoot(self, context, shot):
        if STATE.pending is None:
            name = self.first(context, shot)
            STATE.remember(name, context.mode)
            STATE.say(f"{name}: {self.next_hint[0].lower()}{self.next_hint[1:]}")
            return ""
        picked = targets.find(context, STATE.pending.name)
        if picked is None:
            STATE.pending = None
            raise Refused("The first one is gone")
        result = self.second(context, shot, picked)
        STATE.pending = None
        return result

    def first(self, context, shot):
        return targets.pick_mover(context, shot).name_full


def channel_values(owner):
    return (*owner.location, *owner.rotation_quaternion, *owner.rotation_euler, *owner.rotation_axis_angle, *owner.scale)


class Reset(GunTool):
    bones = True

    def shoot(self, context, shot):
        posing = router.mode_kind(context.mode) == router.POSE
        if not posing:
            owner, connected = targets.pick_mover(context, shot), False
        else:
            _ob, owner = targets.pick_bone(context, shot)
            connected = bool(owner.bone.use_connect and owner.parent)
        chosen, own = settings.get("tool_gun_reset"), Locks.of(owner, connected=connected)
        all_locked = (True,) * 3         # a channel that is not reset counts as locked: it keeps its value
        locks = Locks(own.location if 'location' in chosen else all_locked,
                      own.rotation if 'rotation' in chosen else all_locked,
                      own.scale if 'scale' in chosen else all_locked)
        before = channel_values(owner)
        channels_from_basis(Matrix.Identity(4), Channels.of(owner), locks, use_scale=True).write(owner)
        return "VR Reset" if channel_values(owner) != before else ""


class PlaceHold:
    """A placed thing while the trigger stays held: twisting the wrist turns it about the spot's normal."""

    def __init__(self, context, shot, mover, hit):
        self.item = tools.moved_object(mover)
        self.spot, self.normal = hit.location.copy(), hit.normal.copy()
        self.move = Matrix.Translation(self.spot - targets.rest_point(context, mover, self.normal))
        self.angle, self.last_rotation = 0.0, shot.pose.grip_rotation.copy()
        RUNTIME.grabbed.add(self.item.key())
        self._apply(context)

    def _apply(self, context):
        turn = Matrix.Translation(self.spot) @ Matrix.Rotation(self.angle, 4, self.normal) @ Matrix.Translation(-self.spot)
        self.item.apply(context.blend_data, turn @ self.move)

    def update(self, context, pose):
        step = pose.grip_rotation @ self.last_rotation.inverted()
        self.last_rotation = pose.grip_rotation.copy()
        twist = 2.0 * math.atan2(Vector(step[1:]).dot(pose.aim_direction), step.w)
        twist = math.remainder(twist, 2.0 * math.pi)
        self.angle -= twist * TWIST_GAIN * tools.motion_factor()      # rolling right turns it clockwise, seen by you
        self._apply(context)

    def finish(self):
        """Let go: the undo message when it moved."""
        RUNTIME.grabbed.discard(self.item.key())
        RUNTIME.cache.all_dirty = True
        moved = self.move.translation.length > SMALLEST_MOVE or abs(self.angle) > SMALLEST_MOVE
        return "VR Place" if moved else ""


class Place(TwoShotTool):
    def second(self, context, shot, mover):
        return PlaceHold(context, shot, mover, targets.spot(context, shot, mover))


class MirrorPose(GunTool):
    modes = (router.POSE,)
    bones = True

    def shoot(self, context, shot):
        ob, pose_bone = targets.pick_bone(context, shot)
        twin = ob.pose.bones.get(bpy.utils.flip_name(pose_bone.name))
        if twin is None or twin == pose_bone:
            raise Refused("This bone has no other side")
        before = channel_values(twin)
        if not pose_mirror.mirror_bone(context, ob, pose_bone):
            raise Refused("Needs a 3D View on the desktop")
        return "VR Mirror Pose" if channel_values(twin) != before else ""


class Look(TwoShotTool):
    next_hint = "Now shoot what to look at"

    def first(self, context, shot):
        if rig_tab.assorted_module("look_at") is None:
            raise Refused("Look needs Digit's Assorted Tools")
        rig = targets.rig_of(targets.pick_object(context, shot))
        if rig is None:
            raise Refused("That is not a character")
        targets.refuse_linked(rig)
        return rig.name_full

    def second(self, context, shot, rig):
        look_at = rig_tab.assorted_module("look_at")
        if look_at is None:
            raise Refused("Look needs Digit's Assorted Tools")
        text = look_at.look_at_point(context, rig, targets.spot(context, shot).location)
        if text.startswith("No "):
            raise Refused(text)
        STATE.say(text)
        return "VR Look"


class RemoveClipping(TwoShotTool):
    next_hint = "Now shoot the surface"

    def second(self, context, shot, mover):
        hit = targets.spot(context, shot, mover)
        shift = targets.clearing_shift(context, mover, hit)
        if abs(shift) < SMALLEST_MOVE:
            return ""
        tools.moved_object(mover).apply(context.blend_data, Matrix.Translation(hit.normal * shift))
        return "VR Remove Clipping"


class CopyDrag:
    """Duplicate's first shot while the trigger stays held: pulling away drags a linked copy out; a plain click makes none."""

    def __init__(self, mover, reach, start):
        self.name, self.reach, self.start, self.item = mover.name_full, reach, start, None
        self.threshold = select_gesture.start_distance(reach, size_state.scaled(select_gesture.BOX_START_DISTANCE))

    def update(self, context, pose):
        offset = pose.aim_location + pose.aim_direction * self.reach - self.start
        if self.item is None:
            mover = targets.find(context, self.name) if offset.length > self.threshold else None
            if mover is None:
                return
            copy = linked_copy(context, mover)
            context.view_layer.update()
            self.item = tools.moved_object(copy)
            RUNTIME.grabbed.add(self.item.key())
        self.item.apply(context.blend_data, Matrix.Translation(offset))

    def finish(self):
        if self.item is None:
            return ""
        RUNTIME.grabbed.discard(self.item.key())
        RUNTIME.cache.all_dirty = True
        return "VR Duplicate"


class Duplicate(GunTool):
    """Shoot a thing, then every click pastes a linked copy (Alt+D) on the spot, until the tool is reset; or drag the first
    shot out [user, 2026-11-25]."""
    modes = (router.OBJECT,)
    keeps_pick = True            # an undo takes a copy back, not what is being copied

    def shoot(self, context, shot):
        if STATE.pending is None:
            return self._pick(context, shot)
        mover = targets.find(context, STATE.pending.name)
        if mover is None:
            STATE.pending = None
            raise Refused("The first one is gone")
        refuse_uncopyable(context, mover)
        hit = targets.spot(context, shot, mover)
        move = Matrix.Translation(hit.location - targets.rest_point(context, mover, hit.normal))
        copy = linked_copy(context, mover)
        context.view_layer.update()
        tools.moved_object(copy).apply(context.blend_data, move)
        RUNTIME.cache.all_dirty = True
        return "VR Duplicate"

    @staticmethod
    def _pick(context, shot):
        mover = targets.pick_mover(context, shot)
        refuse_uncopyable(context, mover)
        start = targets.point(context, shot)
        STATE.remember(mover.name_full, context.mode)
        STATE.say(f"{mover.name}: click spots to paste copies")
        return CopyDrag(mover, (start - shot.pose.aim_location).length, start)


def refuse_uncopyable(context, mover):
    if not mover.visible_get() or mover.hide_select or view3d_override(context) is None:
        raise Refused("It can't be duplicated")


def linked_copy(context, mover):
    """Alt+D on the thing and, for a character, its parts (the operator re-links parents, modifiers and targets)."""
    chosen = targets.parts_of(context, mover) if mover.type == 'ARMATURE' else [mover]
    for ob in context.selected_objects:
        ob.select_set(False)
    for ob in chosen:
        if ob.visible_get():
            ob.select_set(True)
    context.view_layer.objects.active = mover
    run_in_view3d(context, lambda: bpy.ops.object.duplicate(linked=True))
    return context.view_layer.objects.active


class Hide(GunTool):
    def shoot(self, context, shot):
        ob = targets.pick_object(context, shot, change=False)     # hiding is the view layer's, not the linked data's
        hide.hide_objects([ob], push=False)
        return "VR Hide"


class Measure(GunTool):
    def shoot(self, context, shot):
        point = targets.point(context, shot)
        if STATE.measured.start is None or STATE.measured.end is not None:
            STATE.measure(Measured(point))
            STATE.say("Now shoot the second point")
            return ""
        start = STATE.measured.start
        units = context.scene.unit_settings
        text = bpy.utils.units.to_string(units.system, 'LENGTH', (point - start).length * units.scale_length,
                                         precision=4, compatible_unit=False).strip()
        STATE.measure(Measured(start, point, text))
        STATE.say(text)
        return ""


class Material(GunTool):
    def shoot(self, context, shot):
        hit = targets.spot(context, shot)
        slot = _slot(hit)
        if STATE.eyedrop:
            if slot is None or slot.material is None:
                raise Refused("No material there")
            STATE.material, STATE.eyedrop = slot.material.name_full, False
            STATE.say("Picked " + slot.material.name)
            return ""
        material = next((each for each in bpy.data.materials if each.name_full == STATE.material), None)
        if material is None:
            raise Refused("Pick a material first")
        ob = hit.owner
        if (OBJECT, ob.name_full, "") in RUNTIME.grabbed:
            raise Refused("A hand holds it")
        targets.refuse_linked(ob)
        if hit.instanced or not hasattr(ob.data, "materials"):
            raise Refused("It can't take a material")
        if (slot is None or slot.link == 'DATA') and is_linked(ob.data):
            raise Refused("Linked: can't be changed here")
        if slot is None:
            ob.data.materials.append(material)
        elif slot.material == material:
            return ""
        else:
            slot.material = material
        return "VR Material"


def _slot(hit):
    """The material slot of the face that was hit (the first one when the face can't tell), or None."""
    slots = hit.hit_object.original.material_slots
    if not len(slots):
        return None
    faces = getattr(hit.hit_object.data, "polygons", ())
    index = faces[hit.face].material_index if 0 <= hit.face < len(faces) else 0
    return slots[min(index, len(slots) - 1)]


def material_names():
    return sorted(each.name_full for each in bpy.data.materials if not each.is_grease_pencil)


TOOLS = {'RESET': Reset(), 'PLACE': Place(), 'MIRROR': MirrorPose(), 'LOOK': Look(), 'CLIPPING': RemoveClipping(),
         'DUPLICATE': Duplicate(), 'HIDE': Hide(), 'MEASURE': Measure(), 'MATERIAL': Material()}


def current():
    return TOOLS[settings.get("tool_gun_tool")]
