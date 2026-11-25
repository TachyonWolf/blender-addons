# SPDX-License-Identifier: GPL-3.0-or-later
"""The add-on's preferences (one AddonPreferences class per add-on, so every tool that needs a saved setting adds its
property here): Bones In Front's switch, and the Oops Debugger's choices (what it looks for, which heavy Scans are on).
Also the Linked Modifiers ticks, which are never saved (window manager only)."""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from . import local_defaults  # generated copy
from . import scene_checks as sc  # generated copy


def addon_prefs(context=None):
    """The preferences, or None when run as a plain folder (tests) instead of an enabled add-on."""
    addon = (context or bpy.context).preferences.addons.get(__package__)
    return addon.preferences if addon else None


def bones_in_front_changed(self, context):
    from . import bones_in_front   # late: bones_in_front reads these preferences
    bones_in_front.apply_setting()


def ignore_prop(ignore):
    return f"ignore_{ignore.id}"


def scan_prop(scan):
    return f"scan_{scan.id}"


# One switch per heavy scan of the registry (sc.SCANS), off by default; plus the "Looking for" dropdown.
OopsSettings = type("DigitOopsSettings", (bpy.types.PropertyGroup,), {"__annotations__": {
    "kind": EnumProperty(name="Looking for", items=sc.KINDS, default=sc.OBJECT,
                         description="What are you looking for: only these checks are shown and scanned"),
    "clear_all_risk": EnumProperty(name="Clear up to risk", default=str(sc.MAX_CLEAR_ALL_RISK),
                                   items=[(str(level), f"Clear up to risk {level}", f"{name}: {text}") for level, (name, text) in sc.RISKS.items()],
                                   description="Clear All clears every leftover listed with a risk up to this level"),
    "scan_disabled": BoolProperty(name="Scan Disabled Collections", default=False,
                                  description="All: also scan objects in excluded (unchecked) collections"),
    **{ignore_prop(i): BoolProperty(name=i.label, default=i.default, description=i.help) for i in sc.IGNORES},
    **{scan_prop(s): BoolProperty(name=s.label, default=False,
                                  description=f"{s.help}. On: runs now and on every selection change. Off: never runs")
       for s in sc.SCANS}}})


def oops_settings(context=None):
    """The Oops Debugger's saved choices: in the preferences, or (run as a plain folder, tests) on the window manager."""
    prefs = addon_prefs(context)
    return prefs.oops if prefs else (context or bpy.context).window_manager.digit_oops


def clear_all_risk(settings):
    """The highest risk level Clear All clears (the select's choice, as a number)."""
    return int(settings.clear_all_risk)


def scans_on(settings):
    """The ids of the Scans turned on, plus those of the gating Ignores turned off (their checks run)."""
    return ({s.id for s in sc.SCANS if getattr(settings, scan_prop(s))}
            | {i.id for i in sc.IGNORES if not i.filters and not getattr(settings, ignore_prop(i))})


def ignores_on(settings):
    """The ids of the filtering Ignores turned on (the scope hands them to the checks that trim their lists)."""
    return frozenset(i.id for i in sc.IGNORES if i.filters and getattr(settings, ignore_prop(i)))


# Linked Modifiers' ticks: the one place they live. On the window manager, so never saved in the .blend or the
# preferences. Stored as the UNticked (data name, modifier name) pairs, so a new modifier starts ticked.
UNPICKED_PROPERTY = "digit_oops_unpicked"


def unpicked_modifiers(context=None):
    """{(data name, modifier name)} the user unticked for Apply Modifiers."""
    text = getattr((context or bpy.context).window_manager, UNPICKED_PROPERTY, "") or "[]"
    return frozenset(tuple(pair) for pair in json.loads(text))


def is_modifier_picked(context, data_name, modifier_name):
    return (data_name, modifier_name) not in unpicked_modifiers(context)


def set_modifier_picked(context, data_name, modifier_name, picked):
    unpicked = set(unpicked_modifiers(context))
    (unpicked.discard if picked else unpicked.add)((data_name, modifier_name))
    setattr(context.window_manager, UNPICKED_PROPERTY, json.dumps(sorted(unpicked)))


TEXTURE_STUDIO_FILE = local_defaults.get("texture_studio_file", "~/Blender/TextureStudio.blend")


class DigitToolsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    bones_in_front: BoolProperty(
        name="Bones In Front While Posing", default=True, update=bones_in_front_changed,
        description="Turn armature In Front on only while posing, editing or weight painting (uses one timer while on)")
    oops: PointerProperty(type=OopsSettings)
    texture_studio_file: StringProperty(
        name="Texture Studio File", subtype='FILE_PATH', default=TEXTURE_STUDIO_FILE,
        description="The studio .blend that File > New > Texture Studio opens as a new untitled file")

    def draw(self, context):
        self.layout.prop(self, "bones_in_front")
        self.layout.prop(self, "texture_studio_file")


def register():
    """OopsSettings before the preferences (they point at it), and the window manager fallback."""
    bpy.utils.register_class(OopsSettings)
    bpy.types.WindowManager.digit_oops = PointerProperty(type=OopsSettings)
    setattr(bpy.types.WindowManager, UNPICKED_PROPERTY, StringProperty(options={'HIDDEN', 'SKIP_SAVE'}))


def unregister():
    delattr(bpy.types.WindowManager, UNPICKED_PROPERTY)
    del bpy.types.WindowManager.digit_oops
    bpy.utils.unregister_class(OopsSettings)
