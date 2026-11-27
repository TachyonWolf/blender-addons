# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings remembered between sessions: a small JSON file in the extension's user folder (AddonPreferences only
save with preference auto-save, A21). Pure Python (no bpy); the path comes from the caller."""
import json
import math
import os

try:
    from . import display_types, edit_tool_settings, grab_order, hand_marker_math, pda_math
except ImportError:      # imported flat by the headless pure tests
    import display_types
    import grab_order
    import edit_tool_settings
    import hand_marker_math
    import pda_math

# Draw distance (the VR far clip, m): six buttons; the 5th is Blender's own VR default, the 6th 4 times further
# [user, 2026-11-27]. The shorter ones are spread about evenly (x3.75) down to 5 m.
DRAW_DISTANCES = (5.0, 20.0, 75.0, 250.0, 1000.0, 4000.0)
DEFAULT_DRAW_DISTANCE = DRAW_DISTANCES[4]

# Glass in VR (raytracing is always off in VR): hidden, shown opaque, or an alpha-blended stand-in [user, 2026-11-27]
GLASS_HIDE, GLASS_SOLID, GLASS_SEE_THROUGH = 'HIDE', 'SOLID', 'SEE_THROUGH'
GLASS_CHOICES = ((GLASS_HIDE, "Hide"), (GLASS_SOLID, "Solid"), (GLASS_SEE_THROUGH, "See-through"))
SEE_THROUGH_WARNING = "See-through uses more GPU memory"

# name -> (default, check(value) -> bool)
FIELDS = {
    "grab_mode": ('FREE', lambda value: value in ('FREE', 'LASER', 'SELECT_GRAB')),
    "grip_target": ('AIMED', lambda value: value in ('AIMED', 'SELECTION')),   # what a grip acts on: what you point at, or the selection [user, 2026-11-25]
    "box_shape": ('VOLUME', lambda value: value in ('VOLUME', 'LASER')),   # box select: 3D box or laser rectangle [user, 2026-11-25]
    "select_bubble_diameter": (0.15, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                               and 0.001 <= value <= 5.0),                  # m, world; set with B + hand up / down
    "snap_mode": ('OFF', lambda value: value in ('OFF', 'GRID', 'ALIGN')),   # grab snapping in Edit + Object mode, one at a time [user, 2026-11-25]
    "fine_control": (False, lambda value: isinstance(value, bool)),
    "help_on": (False, lambda value: isinstance(value, bool)),         # Tooltips (the Help panel's toggle): a tip beside what you point at
    "help_seen": (False, lambda value: isinstance(value, bool)),       # the Help panel opened itself once, on the first VR start [user, 2026-11-27]
    "paused": (False, lambda value: isinstance(value, bool)),         # Pause (desk toggle): placeholder, the Pause agent adds the behaviour [hook: settings.LISTENERS["paused"] + sticks.LEFT_CLICK_HANDLERS]
    "smart_select": (True, lambda value: isinstance(value, bool)),   # Smart select (desk top row): Object mode picks the top-most parent first, a quick second pick the exact part [user, 2026-11-26]
    "always_laser": (True, lambda value: isinstance(value, bool)),   # "Always show lasers" (desk: Lasers) [user, 2026-11-24]; off = a laser shows only while a finger rests on the trigger
    "name_tag": (True, lambda value: isinstance(value, bool)),         # name above what you point at [user, 2026-11-25]
    "touch_distance": (0.06, lambda value: isinstance(value, (int, float)) and 0.005 <= value <= 0.5),
    "hide_heavy_modifiers": (True, lambda value: isinstance(value, bool)),
    "compositor_off_in_vr": (True, lambda value: isinstance(value, bool)),      # Performance tab [user, 2026-11-24]
    "glass_in_vr": (GLASS_SEE_THROUGH, lambda value: value in dict(GLASS_CHOICES)),   # Performance tab; See-through is the default [user, 2026-11-27]
    "hide_transparent_in_vr": (False, lambda value: isinstance(value, bool)),   # [user, 2026-11-25]
    "draw_distance": (DEFAULT_DRAW_DISTANCE, lambda value: value in DRAW_DISTANCES),   # VR far clip in m [user, 2026-11-27]
    "lower_shadows_in_vr": (False, lambda value: isinstance(value, bool)),
    "annotate_color": ('red', lambda value: value in ('red', 'orange', 'yellow', 'green', 'blue', 'white')),
    "annotate_thickness": (3, lambda value: isinstance(value, (int, float)) and 1 <= value <= 10),
    "gp_radius": (0.01, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                  and 0.001 <= value <= 0.05),                                  # Grease Pencil stroke radius, m
    "push_speed": (1.5, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                   and 0.1 <= value <= 10.0),                                   # push / pull while holding, m/s
    "display_hidden": ([], display_types.valid_hidden),   # Display tab: what the VR view hides (keys of display_types) [user, 2026-11-25]
    "haptics": (False, lambda value: isinstance(value, bool)),            # Haptics pop-up (View tab): master switch; off = today's buzzes only [user, 2026-11-25]
    "haptics_strength": (1.0, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                         and 0.1 <= value <= 1.0),
    "haptics_point": (True, lambda value: isinstance(value, bool)),      # a pulse when what you point at changes
    "haptics_grab": (True, lambda value: isinstance(value, bool)),       # a different pulse for a grab
    "haptics_other": (True, lambda value: isinstance(value, bool)),      # the other buzzes (refused, limits, ticks)
    "scale_meter": (True, lambda value: isinstance(value, bool)),        # size readout + ruler while you scale (off: never) [user, 2026-11-25]
    "laser_length": (10.0, lambda value: isinstance(value, (int, float)) and 0.5 <= value <= 100.0),
}


def defaults():
    return {name: list(default) if isinstance(default, list) else default for name, (default, _check) in FIELDS.items()}


def clean(data):
    """Known, valid fields from `data`; everything else falls back to its default (bad values are logged)."""
    settings = defaults()
    if not isinstance(data, dict):
        return settings
    data = _migrated(data)
    for name, (_default, check) in FIELDS.items():
        if name in data:
            if check(data[name]):
                settings[name] = data[name]
            else:
                print(f"digits_vr: setting {name}={data[name]!r} is not valid, using the default")
    return settings


def nearest_draw_distance(value):
    """The draw distance button nearest to `value` m (on a log scale); 0 or less (the old "Blender's value") -> the 5th."""
    if value <= 0:
        return DEFAULT_DRAW_DISTANCE
    return min(DRAW_DISTANCES, key=lambda distance: abs(math.log(distance / value)))


def _migrated(data):
    """Older settings files: `grab_point` became the three `grab_order_*` lists (kept when the file has them). The
    raytracing settings ("raytracing_in_vr", "raytracing_off_in_vr") are dropped (raytracing is always off in VR now).
    A draw distance from the old slider goes to the nearest button. The old Hide glass toggle ("hide_glass_in_vr")
    becomes Glass in VR: on -> the default (See-through), off -> Solid."""
    if "grab_point" in data:          # the old "Grab at" setting became the per-mode orders (grab_order.migrated)
        data = {**grab_order.migrated(data["grab_point"]), **{name: value for name, value in data.items() if name != "grab_point"}}
    data = {key: value for key, value in data.items() if key not in ("raytracing_in_vr", "raytracing_off_in_vr")}
    hide_glass = data.pop("hide_glass_in_vr", None)
    if isinstance(hide_glass, bool) and "glass_in_vr" not in data:
        data["glass_in_vr"] = GLASS_SEE_THROUGH if hide_glass else GLASS_SOLID
    distance = data.get("draw_distance")
    if isinstance(distance, (int, float)) and not isinstance(distance, bool) and distance not in DRAW_DISTANCES:
        data = {**data, "draw_distance": nearest_draw_distance(distance)}
    return data


def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return clean(json.load(handle))
    except FileNotFoundError:
        return defaults()
    except (OSError, ValueError) as error:
        print(f"digits_vr: can't read settings {path}: {error}")
        return defaults()


def save(path, settings):
    """Write atomically (temp file + rename), so a crash never leaves half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(clean(settings), handle, indent=1, sort_keys=True)
        os.replace(temp_path, path)
    except OSError as error:
        print(f"digits_vr: can't save settings {path}: {error}")


# Desk (milestone 3): remembered position, size, open state and last tab. Added here so the table above stays
# untouched by other milestones.
def _numbers(count):
    return lambda value: value == [] or (isinstance(value, list) and len(value) == count
                                         and all(isinstance(item, (int, float)) for item in value))


def panel_fields(name, scale_range=(0.5, 2.5)):
    """The four remembered values of a floating panel (panel.py): open, size relative to you, place (`<name>_pinned`: below)."""
    low, high = scale_range
    return {
        name + "_open": (False, lambda value: isinstance(value, bool)),
        name + "_scale": (1.0, lambda value: isinstance(value, (int, float)) and low <= value <= high),
        name + "_location": ([], _numbers(3)),          # [] = not placed yet (opens in front of you)
        name + "_rotation": ([], _numbers(4)),          # quaternion (w, x, y, z)
    }


FIELDS.update(grab_order.fields())     # what each grab mode picks with, in order: laser, fingertip, palm [user, 2026-11-27]
FIELDS.update(panel_fields("desk"))
FIELDS.update(panel_fields("tool_options", (0.2, 2.5)))     # down to 0.2: docked on the tool belt it is small
FIELDS.update(panel_fields("viewpoints"))
FIELDS.update(panel_fields("find"))            # the Find window (find.py)
FIELDS.update(panel_fields("tool_gun"))        # open = the gun is out; the place is its menu's (the gun hangs beside it)
FIELDS["tool_gun_edit"] = (False, lambda value: isinstance(value, bool))      # Edit: the menu's handles show [user, 2026-11-26]
FIELDS["tool_gun_offset"] = ([], lambda value: _numbers(8)(value) or _numbers(9)(value))   # the menu's place in the gun's space: location, quaternion, scale, version (8 values = before the gun owned its size); [] = usual place [user, 2026-11-26]
FIELDS["tool_gun_tool"] = ('PLACE', lambda value: value in ('RESET', 'PLACE', 'MIRROR', 'LOOK', 'CLIPPING', 'DUPLICATE',
                                                            'HIDE', 'MEASURE', 'MATERIAL'))
FIELDS["tool_gun_reset"] = (['location', 'rotation', 'scale'], lambda value: isinstance(value, list) and bool(value)
                            and all(item in ('location', 'rotation', 'scale') for item in value))
FIELDS.update(panel_fields("pda"))
FIELDS.update(panel_fields("camera_view", (0.2, 2.5)))     # the Cam view panel; down to 0.2: docked on the tool belt [user, 2026-11-26]
FIELDS["camera_view_attached"] = (False, lambda value: isinstance(value, bool))   # pinned to its belt slot (held_item.attached)
FIELDS.update(panel_fields("help", (0.2, 2.5)))     # the Help panel [user, 2026-11-27]; down to 0.2: docked on the tool belt
FIELDS["help_attached"] = (False, lambda value: isinstance(value, bool))
for _panel_name in ("desk", "tool_options", "viewpoints", "find", "pda", "keyboard", "camera_view", "help"):
    FIELDS[_panel_name + "_pinned"] = (False, lambda value: isinstance(value, bool))    # pinned to your body frame (panel.py); the place is then saved relative to it
FIELDS["pda_tabs"] = ([], pda_math.valid)         # the PDA's tabs and slot links: in the add-on's settings, so they follow you across files [user, 2026-11-25]
FIELDS["pda_tab"] = (0, lambda value: isinstance(value, int) and not isinstance(value, bool) and 0 <= value < pda_math.MAX_TABS)
FIELDS["desk_tab"] = ('tools', lambda value: value in ('selected', 'grab', 'tools', 'assets', 'outliner', 'move', 'view', 'speed', 'body', 'hands', 'file',
                                                      'modifiers', 'display', 'performance'))   # 'grab' and the last three: before the redesign (mapped on load)
FIELDS["desk_extra"] = (0, lambda value: isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1800)   # (1800 = desk_layout.MAX_EXTRA, tested) pixels the desk is taller than normal: the top handle, up to 3 x [user, 2026-11-25]
FIELDS["show_hands"] = (True, lambda value: isinstance(value, bool))      # the simple capsule hands; Blender's controller marker off while on [user, 2026-11-25]
FIELDS["finger_poke"] = ('POINTER', lambda value: value in ('POINTER', 'ALL', 'NONE'))   # which fingertips press panel buttons [user, 2026-11-25]
FIELDS["hand_marker"] = (0.0, hand_marker_math.valid)   # hand marker size in m; 0 = the tiny default [user, 2026-11-25]


# Movement (milestone 4)
def _number_in(low, high):
    return lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


FIELDS.update({
    "move_mode": ('WALK', lambda value: value in ('WALK', 'TELEPORT', 'FLY', 'GEO')),
    "move_heading": ('HEAD', lambda value: value in ('HEAD', 'HAND')),     # left stick (walk, geometry, flight) follows the head or the left hand [user]
    "heading_hand": ('LEFT', lambda value: value in ('LEFT', 'RIGHT')),    # which hand's aim the Hand heading follows [user, 2026-11-26]
    "start_at": ('VIEWPORT', lambda value: value in ('VIEWPORT', 'CAMERA')),   # Start VR puts your head at the 3D View or the scene camera [user, 2026-11-27]
    "teleport_land": ('PLANE', lambda value: value in ('PLANE', 'GEO')),   # Teleport lands on the floor plane or on scene geometry [user]
    "fly_pitch": ('HORIZONTAL', lambda value: value in ('HORIZONTAL', 'FULL')),   # forward stays level, or flies up / down too [user]
    "turn_style": ('SNAP', lambda value: value in ('SNAP', 'SMOOTH')),
    "walk_speed": (1.5, _number_in(0.1, 10.0)),         # m/s
    "fly_speed": (2.5, _number_in(0.1, 20.0)),          # m/s
    "snap_angle": (30.0, _number_in(5.0, 90.0)),        # degrees per push
    "turn_speed": (120.0, _number_in(10.0, 360.0)),     # degrees per second (smooth)
    "eye_height": (1.6, _number_in(0.5, 2.5)),           # m: your eyes above the floor (sets where the plane is)
    "plane_height": (0.0, _number_in(-100.0, 100.0)),   # m: the floor plane in the scene
    "geo_slide_speed": (0.5, _number_in(0.05, 5.0)),    # m/s: how fast your height slides (Walk on geometry)
    "geo_step_height": (0.4, _number_in(0.05, 2.0)),    # m: the highest step you climb; taller is a wall
    "size_gesture": (True, lambda value: isinstance(value, bool)),   # two grips on nothing scale you [user, 2026-11-25]
    "size_invert": (False, lambda value: isinstance(value, bool)),   # pulling apart makes you bigger [user, 2026-11-25]
})


# Tool belt (belt.py): all numbers
FIELDS.update({
    "belt_on": (True, lambda value: isinstance(value, bool)),          # the belt can be turned off [user, 2026-11-25]
    "belt_height": (0.73, _number_in(0.3, 1.2)),                       # m below your eyes (times your size); 0.65 before the Options page [user, 2026-11-26]
    "belt_forward": (-0.12, _number_in(-0.4, 0.4)),                    # m the belt hangs ahead of your body frame (minus = towards your back) [user, 2026-11-26]
    "belt_side": (0.0, _number_in(-0.3, 0.3)),                         # m to the right (minus = left)
    "finger_forward": (0.0, _number_in(-0.05, 0.05)),                  # m the tool point moves along the finger (plus = further out) [user, 2026-11-26]
    "finger_up": (0.0, _number_in(-0.05, 0.05)),                       # m the tool point moves up from the finger
    "belt_size": (1.0, _number_in(0.5, 2.0)),                          # slot ring and docked items, times your size
    "belt_take_fingertip": (True, lambda value: isinstance(value, bool)),   # taking from a slot: fingertip, else the grip [user, 2026-11-25]
    "belt_snap_back": (3.0, _number_in(0.5, 10.0)),                    # m (times your size): an Attached item farther away snaps back [user: 3 m]
    "tool_options_attached": (False, lambda value: isinstance(value, bool)),   # pinned to its belt slot: snaps back (held_item.attached)
    "tool_gun_attached": (False, lambda value: isinstance(value, bool)),
    "pda_attached": (False, lambda value: isinstance(value, bool)),
})


FIELDS.update(edit_tool_settings.fields())     # Edit mode: the active tool and each tool's settings [user, 2026-11-25]
