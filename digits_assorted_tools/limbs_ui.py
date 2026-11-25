# SPDX-License-Identifier: GPL-3.0-or-later
"""Limbs settings and Upgrade Limbs (the Full Character Rig card's Existing Rig section runs it): Rigify-style upgrades for a character's arms and legs (IK stretch, parent switching, IK/FK snap
data, digitigrade hock rebuild) on the controls the rig already has. The bones are guessed from names and chain
structure (limb_rig.guess_table), shown under Advanced for checking, and used by Upgrade Limbs. All rig logic is
in limb_rig (generated copy of Addons/shared_addon/limb_rig.py); the IK/FK snap and parent buttons are in the
Selected card's Rig Switches.

Settings live on the armature object (`Object.digit_limbs`)."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, PointerProperty, StringProperty

from . import body_rig as br, limb_rig as lr  # generated copies
from .face_rig_ui import character

LIMB_KEYS = ('ctrl', 'ik', 'tip', 'target', 'heel', 'hock', 'hock_target', 'twist')
LIMB_LABELS = dict(ctrl="Control", ik="IK Bone", tip="Hand / Foot", target="Foot Target", heel="Heel",
                   hock="Hock Control", hock_target="Hock Target", twist="Twist Forearm")
PARENT_KEYS = tuple(k.lower() for k in lr.PARENT_NAMES)
guess_cache = {}


class DIGITOOLS_PG_limb(bpy.types.PropertyGroup):
    """One limb's bones, left side (the right side is flipped)."""
    __annotations__ = {key: StringProperty(name=LIMB_LABELS[key]) for key in LIMB_KEYS}


class DIGITOOLS_PG_limbs(bpy.types.PropertyGroup):
    stretch: BoolProperty(name="Stretch", default=True,
                          description="Add the IK_Stretch slider to every limb control (starts at 1; 0 = no stretch)")
    parent_switch: BoolProperty(name="Parent Switch", default=True,
                                description="Add the IK_Parent switch: the control can follow Root, Pelvis, Chest or Head")
    hock: BoolProperty(name="Hock Rebuild", default=True,
                       description="Rebuild digitigrade legs with a hock control (the rest pose stays as it is)")
    root: StringProperty(name="Root", description="Root bone; its scale keeps hands and feet their size")
    pelvis: StringProperty(name="Pelvis")
    chest: StringProperty(name="Chest")
    head: StringProperty(name="Head")
    pole_lines: BoolProperty(name="Pole Lines", default=True,
                             description="A line from each elbow and knee to its pole, shown in IK")
    pole_follow: BoolProperty(name="Pole Follow", default=True,
                              description="PoleFollow on each IK control: the pole follows the body (1) or stays with the "
                                          "Root (0). Replaces an older Knee Follow, keeping its value")
    foot_bank: BoolProperty(name="Foot Bank & Heel Swivel", default=True,
                            description="FootBank and HeelSwivel on each foot control (needs the foot roll pivots)")
    head_follow: BoolProperty(name="Head / Neck Follow", default=True,
                              description="HeadFollow and NeckFollow on the Head: 1 = turn with the torso, 0 = keep their "
                                          "own turn while the torso bends")
    neck_ik: BoolProperty(name="Neck IK", default=True,
                          description="IK-Head: move it to bend the neck, turn it to turn the head (IK_FK, parent "
                                      "switch Root / Pelvis / Chest). A rig's own IK-Head is kept and gets the switches")
    hock_mch: BoolProperty(name="Hock Helpers", description="Rebuild the hock with helper bones (off: the rig keeps its old hock)")
    limbs: CollectionProperty(type=DIGITOOLS_PG_limb)
    report: StringProperty(name="Report", description="What the last Upgrade Limbs did, one line per limb")


def table_from(s):
    """The table limb_rig.upgrade takes, from the settings (empty fields left out)."""
    parents = {name: getattr(s, name.lower()) for name in lr.PARENT_NAMES}
    limbs = [{k: getattr(item, k) for k in LIMB_KEYS if getattr(item, k)} for item in s.limbs]
    return dict(parents=parents, hock_mch=s.hock_mch or None, limbs=limbs)


def fill_settings(s, table):
    """Put a guessed table into the settings (the options stay)."""
    for name, bone in table['parents'].items():
        setattr(s, name.lower(), bone)
    s.hock_mch = bool(table['hock_mch'])
    s.limbs.clear()
    for entry in table['limbs']:
        item = s.limbs.add()
        for key, bone in entry.items():
            setattr(item, key, bone)


def guessed(arm):
    """The guessed table, kept until the rig's bone count changes (the card asks every redraw)."""
    key = (arm.name, len(arm.data.bones))
    if key not in guess_cache:
        guess_cache.clear()
        guess_cache[key] = lr.guess_table(arm)
    return guess_cache[key]


def describe(arm, table):
    """Status text: the limbs of a table and whether they are upgraded already."""
    ctrls = [e['ctrl'] for e in table['limbs']]
    if not ctrls:
        return "no limbs found (an IK with a pole and a hand or foot below it)", 'ERROR'
    names = ", ".join(e['ctrl'] + (" +hock" if e.get('hock') else "") for e in table['limbs'])
    done = sum('Limb' in arm.pose.bones[c] for c in ctrls if c in arm.pose.bones)
    text = f"{len(ctrls)} limbs found: {names}"
    return (text + " (upgraded)" if done == len(ctrls) else text), 'CHECKMARK' if done == len(ctrls) else 'ARMATURE_DATA'


def problem(context):
    """Why the upgrade can't run now, or ''."""
    arm = character(context)
    if arm is None:
        return "Select the character (or its rig)"
    if context.mode not in ('OBJECT', 'POSE'):
        return "Leave Edit mode first"
    return ""


class DIGITOOLS_OT_limbs_guess(bpy.types.Operator):
    """Look at the rig again and fill the bone list (under Advanced) with the guess"""
    bl_idname = "digits_assorted_tools.limbs_guess"
    bl_label = "Guess Limbs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return character(context) is not None

    def execute(self, context):
        arm = character(context)
        guess_cache.clear()
        fill_settings(arm.digit_limbs, guessed(arm))
        self.report({'INFO'}, describe(arm, table_from(arm.digit_limbs))[0])
        return {'FINISHED'}


class DIGITOOLS_OT_limbs_upgrade(bpy.types.Operator):
    """Add IK stretch, parent switching and IK/FK snap data (and rebuild digitigrade hocks) on the character's arms
    and legs, using the bones listed under Advanced (guessed when the list is empty). Safe to run again; sliders
    start at 0, so the pose stays as it is"""
    bl_idname = "digits_assorted_tools.limbs_upgrade"
    bl_label = "Upgrade Limbs"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        arm = character(context)
        s = arm.digit_limbs
        if not len(s.limbs):
            fill_settings(s, guessed(arm))
        table = table_from(s)
        if not table['limbs']:
            self.report({'ERROR'}, "No limbs found: an IK with a pole and a hand or foot below it")
            return {'CANCELLED'}
        context.view_layer.objects.active = arm
        report = lr.upgrade(arm, table, stretch=s.stretch, parent_switch=s.parent_switch, hock=s.hock)
        lines = lr.report_lines(report)
        s.report = "\n".join(lines)
        self.report({'INFO'}, f"Upgraded {len(report['limbs'])} limbs" + (f", skipped {len(report['skipped'])}" if report['skipped'] else ""))
        return {'FINISHED'}


class DIGITOOLS_OT_body_features_add(bpy.types.Operator):
    """Add the Full Character Rig's Pole Lines, Pole Follow, Foot Bank & Heel Swivel and Head / Neck Follow (the ones
    ticked under Limb Options) to this rig, placed from its own bones. Nothing moves; what the rig has already is left
    alone, so it is safe to run again"""
    bl_idname = "digits_assorted_tools.body_features_add"
    bl_label = "Add Body Features"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        why = problem(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def execute(self, context):
        arm = character(context)
        s = arm.digit_limbs
        report = br.add_features(arm, [f for f in br.FEATURES if getattr(s, f)])
        s.report = "\n".join(report['done'] + report['skipped'])
        if not report['done']:
            self.report({'INFO'}, "Nothing to add" + (f": {report['skipped'][0]}" if report['skipped'] else ""))
        else:
            self.report({'INFO'}, f"Added {len(report['done'])} features, {len(report['added'])} bones"
                        + (f", skipped {len(report['skipped'])}" if report['skipped'] else ""))
        return {'FINISHED'}


classes = (DIGITOOLS_PG_limb, DIGITOOLS_PG_limbs, DIGITOOLS_OT_limbs_guess, DIGITOOLS_OT_limbs_upgrade,
           DIGITOOLS_OT_body_features_add)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_limbs = PointerProperty(type=DIGITOOLS_PG_limbs)


def unregister():
    del bpy.types.Object.digit_limbs
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
