# SPDX-License-Identifier: GPL-3.0-or-later
"""Driver scan (no UI): lists the drivers of a rig, its meshes' shape keys and modifiers, in plain words, with what
is wrong with each. The ONE place that reads drivers: the Drivers tool and Oops Debugger's driver check use it.
Nothing here runs by itself; callers scan when their card is open and cache the result.
"""
import re
from dataclasses import dataclass

import bpy

from .ui_cards import friendly_name

BONE_PATH = re.compile(r'^(?:pose\.)?bones\["(.+?)"\]\.?(.*)$')
KEY_PATH = re.compile(r'^key_blocks\["(.+?)"\]\.(.*)$')
MOD_PATH = re.compile(r'^modifiers\["(.+?)"\]\.(.*)$')
INNER_PATH = re.compile(r'^(?:constraints|modifiers)\["(.+?)"\]\.(.*)$')
CUSTOM_PATH = re.compile(r'^\["(.+?)"\]$')
AXES = {'location': "XYZ", 'rotation_euler': "XYZ", 'scale': "XYZ", 'rotation_quaternion': "WXYZ",
        'delta_location': "XYZ", 'delta_rotation_euler': "XYZ", 'delta_scale': "XYZ",
        'lock_location': "XYZ", 'lock_rotation': "XYZ", 'lock_scale': "XYZ"}
COMBINE = {'AVERAGE': "Average", 'SUM': "Sum", 'MIN': "Lowest", 'MAX': "Highest"}
ID_COLLECTIONS = ("objects", "armatures", "shape_keys")   # where a driver's owner is looked up in bpy.data


@dataclass
class DriverInfo:
    id_kind: str        # one of ID_COLLECTIONS
    id_name: str
    data_path: str
    index: int
    group: str          # what the driver belongs to: a bone's name, or the object / key it sits on
    title: str          # the driven property in plain words
    what: str           # the expression or the way the variables are combined
    error: str          # "" when fine
    muted: bool
    bone: str           # bone name, "" when the driven thing is not a bone

    @property
    def problem(self):
        return bool(self.error)


def property_words(path, index):
    """The driven property in plain words: 'location' + 2 -> 'Location Z', 'constraints["Copy"].influence' ->
    'Copy · Influence', '["smile"]' -> 'Smile'."""
    prefix = ""
    inner = INNER_PATH.match(path)
    if inner:
        prefix, path = friendly_name(inner.group(1)) + " · ", inner.group(2)
    custom = CUSTOM_PATH.match(path)
    if custom:
        return prefix + friendly_name(custom.group(1))
    words = friendly_name(path.split(".")[-1]).title()
    axes = AXES.get(path.split(".")[-1])
    if axes and 0 <= index < len(axes):
        words += " " + axes[index]
    return prefix + words


def describe_path(path, index, owner_name):
    """(group, bone, title) of a driven data path."""
    match = BONE_PATH.match(path)
    if match:
        bone = match.group(1)
        return friendly_name(bone), bone, property_words(match.group(2), index)
    match = KEY_PATH.match(path)
    if match:
        return friendly_name(owner_name), "", f"{friendly_name(match.group(1))} · {property_words(match.group(2), index)}"
    match = MOD_PATH.match(path)
    if match:
        return friendly_name(owner_name), "", f"{friendly_name(match.group(1))} · {property_words(match.group(2), index)}"
    return friendly_name(owner_name), "", property_words(path, index)


def expression_text(driver):
    if driver.type == 'SCRIPTED':
        return driver.expression or "(empty)"
    count = len(driver.variables)
    return f"{COMBINE.get(driver.type, driver.type.title())} of {count} variable{'' if count == 1 else 's'}"


def variable_error(owner, var):
    """What is wrong with a driver variable ('' when nothing)."""
    if not var.is_name_valid:
        return f"Variable '{var.name}' has a bad name"
    for target in var.targets:
        if var.type == 'CONTEXT_PROP':
            continue
        if target.id is None:
            return f"'{var.name}' has no target"
        if var.type == 'SINGLE_PROP' and target.data_path:
            try:
                target.id.path_resolve(target.data_path)
            except ValueError:
                return f"'{var.name}': property not found"
        elif var.type != 'SINGLE_PROP' and target.bone_target and target.id.type == 'ARMATURE':
            if target.bone_target not in target.id.pose.bones:
                return f"'{var.name}': bone '{target.bone_target}' missing"
    return ""


def driver_error(owner, fcurve):
    """What is wrong with a driver, in plain words ('' when it looks fine)."""
    driver = fcurve.driver
    try:
        owner.path_resolve(fcurve.data_path)
    except ValueError:
        return "The driven property is gone"
    if driver.type == 'SCRIPTED':
        if not driver.expression.strip():
            return "The expression is empty"
        try:
            compile(driver.expression, "<driver>", "eval")
        except SyntaxError:
            return "The expression has a typo"
    for var in driver.variables:
        error = variable_error(owner, var)
        if error:
            return error
    if not driver.is_valid:
        return "Blender could not run it"
    return ""


def owners(rig, meshes=()):
    """[(bpy.data collection name, ID, label)] that can hold drivers for this rig and meshes."""
    found = [("objects", rig, rig.name), ("armatures", rig.data, rig.name)]
    for ob in meshes:
        found.append(("objects", ob, ob.name))
        keys = getattr(ob.data, "shape_keys", None)
        if keys is not None:
            found.append(("shape_keys", keys, ob.name))
    return found


def scan(rig, meshes=()):
    """Every driver of the rig and, if given, the meshes' object / modifier / shape key drivers, as DriverInfo."""
    infos = []
    for kind, owner, label in owners(rig, meshes):
        if owner.animation_data is None:
            continue
        for fc in owner.animation_data.drivers:
            group, bone, title = describe_path(fc.data_path, fc.array_index, label)
            infos.append(DriverInfo(kind, owner.name, fc.data_path, fc.array_index, group, title,
                                    expression_text(fc.driver), driver_error(owner, fc), fc.mute, bone))
    return infos


def find_fcurve(info):
    """The F-curve a DriverInfo describes (looked up fresh, so it survives undo), or None."""
    owner = getattr(bpy.data, info.id_kind).get(info.id_name)
    if owner is None or owner.animation_data is None:
        return None
    return owner.animation_data.drivers.find(info.data_path, index=info.index)


def set_muted(info, muted):
    """Mute or unmute the driver. Returns False when it can't be found any more."""
    fc = find_fcurve(info)
    if fc is None:
        return False
    fc.mute = muted
    info.muted = muted
    return True


def matches(info, text="", only_problems=False):
    """Filter used by the Drivers card: problem filter and a case-insensitive text search over the words shown."""
    if only_problems and not info.problem:
        return False
    text = text.strip().lower()
    return not text or text in " ".join((info.group, info.title, info.what, info.error)).lower()


def group_by_owner(infos):
    """{group: [DriverInfo]} in first-seen order."""
    groups = {}
    for info in infos:
        groups.setdefault(info.group, []).append(info)
    return groups
