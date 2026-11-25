# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings remembered between sessions: a small JSON file in the extension's user folder (AddonPreferences only
save with preference auto-save, A21). Pure Python (no bpy); the path comes from the caller."""
import json
import os

try:
    from . import display_types
except ImportError:      # imported flat by the headless pure tests
    import display_types

# name -> (default, check(value) -> bool)
FIELDS = {
    "grab_mode": ('FREE', lambda value: value in ('FREE', 'LASER', 'SELECT_GRAB')),
    "rotation_mode": ('AUTO', lambda value: value in ('PUPPET', 'STICK', 'AUTO')),
    "swap_linked": (True, lambda value: isinstance(value, bool)),     # Auto's swap distance = the touch distance
    "swap_distance": (0.06, lambda value: isinstance(value, (int, float)) and 0.005 <= value <= 2.0),
    "fine_control": (False, lambda value: isinstance(value, bool)),
    "always_laser": (True, lambda value: isinstance(value, bool)),   # lasers always drawn [user, 2026-11-24]   # B toggles it; off by default [user, Q4]
    "name_tag": (True, lambda value: isinstance(value, bool)),         # name above what you point at [user, 2026-11-25]
    "touch_distance": (0.06, lambda value: isinstance(value, (int, float)) and 0.005 <= value <= 0.5),
    "hide_heavy_modifiers": (True, lambda value: isinstance(value, bool)),
    "compositor_off_in_vr": (True, lambda value: isinstance(value, bool)),      # Performance tab [user, 2026-11-24]
    "raytracing_off_in_vr": (True, lambda value: isinstance(value, bool)),      # + glass objects hidden meanwhile
    "hide_transparent_in_vr": (False, lambda value: isinstance(value, bool)),   # [user, 2026-11-25]
    "draw_distance": (0.0, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                      and (value == 0 or 2.0 <= value <= 1000.0)),             # VR far clip in m; 0 = Blender's value [user]
    "lower_shadows_in_vr": (False, lambda value: isinstance(value, bool)),
    "annotate_color": ('red', lambda value: value in ('red', 'orange', 'yellow', 'green', 'blue', 'white')),
    "annotate_thickness": (3, lambda value: isinstance(value, (int, float)) and 1 <= value <= 10),
    "gp_radius": (0.01, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                  and 0.001 <= value <= 0.05),                                  # Grease Pencil stroke radius, m
    "push_speed": (1.5, lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
                   and 0.1 <= value <= 10.0),                                   # push / pull while holding, m/s
    "display_hidden": ([], display_types.valid_hidden),   # Display tab: what the VR view hides (keys of display_types) [user, 2026-11-25]
    "laser_length": (10.0, lambda value: isinstance(value, (int, float)) and 0.5 <= value <= 100.0),
}


def defaults():
    return {name: list(default) if isinstance(default, list) else default for name, (default, _check) in FIELDS.items()}


def clean(data):
    """Known, valid fields from `data`; everything else falls back to its default (bad values are logged)."""
    settings = defaults()
    if not isinstance(data, dict):
        return settings
    for name, (_default, check) in FIELDS.items():
        if name in data:
            if check(data[name]):
                settings[name] = data[name]
            else:
                print(f"digits_vr: setting {name}={data[name]!r} is not valid, using the default")
    return settings


def load(path):
    try:
        with open(path) as handle:
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
        with open(temp_path, "w") as handle:
            json.dump(clean(settings), handle, indent=1, sort_keys=True)
        os.replace(temp_path, path)
    except OSError as error:
        print(f"digits_vr: can't save settings {path}: {error}")


# Desk (milestone 3): remembered position, size, open state and last tab. Added here so the table above stays
# untouched by other milestones.
def _numbers(count):
    return lambda value: value == [] or (isinstance(value, list) and len(value) == count
                                         and all(isinstance(item, (int, float)) for item in value))


FIELDS.update({
    "desk_open": (False, lambda value: isinstance(value, bool)),
    "desk_tab": ('grab', lambda value: value in ('selected', 'grab', 'tools', 'assets', 'move', 'modifiers', 'view', 'display', 'performance')),
    "desk_scale": (1.0, lambda value: isinstance(value, (int, float)) and 0.5 <= value <= 2.5),
    "desk_location": ([], _numbers(3)),          # [] = not placed yet (opens in front of you)
    "desk_rotation": ([], _numbers(4)),          # quaternion (w, x, y, z)
})


# Movement (milestone 4)
def _number_in(low, high):
    return lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


FIELDS.update({
    "move_mode": ('WALK', lambda value: value in ('WALK', 'TELEPORT', 'FLY', 'GEO')),
    "move_heading": ('HEAD', lambda value: value in ('HEAD', 'HAND')),     # left stick (walk, geometry, flight) follows the head or the left hand [user]
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
})
