# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings the sidebar shows, backed by the JSON file of settings_store.py (props use get / set callbacks on
one Python dict, so there is nothing to sync on file load). Saved on every change."""
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty

from . import settings_store

FILE_NAME = "settings.json"
_current = {}


def settings_path():
    """settings.json in the extension's user folder; DIGITS_VR_SETTINGS_DIR overrides it (tests), and a plain
    (non-extension) import falls back to Blender's temp folder."""
    folder = os.environ.get("DIGITS_VR_SETTINGS_DIR")
    if not folder:
        try:
            folder = bpy.utils.extension_path_user(__package__, create=True)
        except (ValueError, RuntimeError):
            folder = os.path.join(bpy.app.tempdir or "/tmp", "digits_vr")
    return os.path.join(folder, FILE_NAME)


def current():
    """The settings dict (loaded once)."""
    if not _current:
        _current.update(settings_store.load(settings_path()))
    return _current


def reload():
    _current.clear()
    return current()


def get(name):
    return current()[name]


def put(name, value):
    current()[name] = value
    settings_store.save(settings_path(), current())
    for listener in LISTENERS.get(name, ()):
        listener(value)


def put_many(values):
    """Set several settings with one file write (the desk saves its position, size and state together)."""
    current().update(values)
    settings_store.save(settings_path(), current())
    for name, value in values.items():
        for listener in LISTENERS.get(name, ()):
            listener(value)


LISTENERS = {}   # setting name -> [callback(value)], e.g. modifier state re-applies when hide_heavy_modifiers flips


def _accessors(name, cast=None):
    items = ENUMS.get(name)

    def getter(_self):
        value = get(name)
        return [identifier for identifier, _label, _tip in items].index(value) if items else value

    def setter(_self, value):
        if items:
            value = items[value][0]
        put(name, cast(value) if cast else value)
    return {"get": getter, "set": setter}


GRAB_MODE_ITEMS = (('FREE', "Free", "Grip grabs what the hand touches"),
                   ('LASER', "Laser", "Grip grabs what the laser points at"),
                   ('SELECT_GRAB', "Select and Grab",
                    "The trigger only selects; a grip anywhere moves the selection by the hand's motion"))
ROTATION_MODE_ITEMS = (('PUPPET', "Puppet", "The grabbed item turns with your wrist, as if held"),
                       ('STICK', "On Stick", "Wrist turning is ignored; the gripping hand's thumbstick turns it"),
                       ('AUTO', "Auto", "Puppet when closer than the swap distance, On Stick when farther"))
MOVE_MODE_ITEMS = (('WALK', "Walk on Plane", "The left stick walks you on a floor plane"),
                   ('TELEPORT', "Teleport on Plane",
                    "Hold the left stick forward to aim an arc; let go to jump to its end"),
                   ('GEO', "Walk on Geometry",
                    "The left stick walks you on real scene geometry; your height slides when you step up or down"),
                   ('FLY', "Free Flight", "The left stick moves you where you look; the right stick goes up and down"))
TURN_STYLE_ITEMS = (('SNAP', "Snap", "The right stick turns you in steps"),
                    ('SMOOTH', "Smooth", "The right stick turns you smoothly"))
MOVE_HEADING_ITEMS = (('HEAD', "Head", "The left stick moves you where your head looks (walking and flight)"),
                     ('HAND', "Hand", "The left stick moves you where your left hand points (walking and flight)"))
FLY_PITCH_ITEMS = (('HORIZONTAL', "Horizontal", "Free flight: forward stays level; the right stick goes up and down"),
                   ('FULL', "Full", "Free flight: forward flies dead ahead, up and down too (the right stick still adds height)"))
TELEPORT_LAND_ITEMS = (('PLANE', "Plane", "Teleport: the arc lands on the floor plane"),
                       ('GEO', "Geometry", "Teleport: the arc lands on scene geometry (no hit: the plane); your height then "
                                           "slides to the surface"))
ENUMS = {"teleport_land": TELEPORT_LAND_ITEMS, "move_heading": MOVE_HEADING_ITEMS, "fly_pitch": FLY_PITCH_ITEMS, "grab_mode": GRAB_MODE_ITEMS, "rotation_mode": ROTATION_MODE_ITEMS, "move_mode": MOVE_MODE_ITEMS,
         "turn_style": TURN_STYLE_ITEMS}   # enum settings: identifiers in JSON


class DIGITSVR_PG_settings(bpy.types.PropertyGroup):
    grab_mode: EnumProperty(name="Grab Mode", items=GRAB_MODE_ITEMS, **_accessors("grab_mode"))
    touch_distance: FloatProperty(name="Touch Distance", subtype='DISTANCE', unit='LENGTH', min=0.005, max=0.5,
                                  description="How close a hand must be to grab in Free mode",
                                  **_accessors("touch_distance", float))
    rotation_mode: EnumProperty(name="Grip Rotation", items=ROTATION_MODE_ITEMS, **_accessors("rotation_mode"))
    swap_linked: BoolProperty(name="Swap at Touch Distance",
                              description="Auto swaps from Puppet to On Stick at the touch distance",
                              **_accessors("swap_linked", bool))
    swap_distance: FloatProperty(name="Swap Distance", subtype='DISTANCE', unit='LENGTH', min=0.005, max=2.0,
                                 description="Auto: Puppet when the grab starts closer than this, On Stick when farther",
                                 **_accessors("swap_distance", float))
    push_speed: FloatProperty(name="Push Speed", min=0.1, max=10.0, precision=2,
                              description="While holding: the right trigger pushes the item away, the left pulls it "
                                          "closer, at this speed (m/s) at full pull",
                              **_accessors("push_speed", float))
    fine_control: BoolProperty(name="Fine Control",
                               description="Grabs move, turn and scale at about 1/4 of the hand's motion (B toggles it)",
                               **_accessors("fine_control", bool))
    always_laser: BoolProperty(name="Always Show Lasers",
                               description="Draw both lasers all the time, not only while a finger rests on the trigger",
                               **_accessors("always_laser", bool))
    name_tag: BoolProperty(name="Name Tag",
                           description="Show the name of the object or bone you point at, floating above the spot",
                           **_accessors("name_tag", bool))
    hide_heavy_modifiers: BoolProperty(name="Heavy Modifiers Off in VR",
                                       description="Subdivision, Geometry Nodes, Boolean, ... are off in the viewport "
                                                   "while VR runs (renders and saved files keep them)",
                                       **_accessors("hide_heavy_modifiers", bool))
    compositor_off_in_vr: BoolProperty(name="Viewport Compositor Off in VR",
                                       description="The viewport compositor is switched off in the headset while VR "
                                                   "runs (it costs a lot of frame rate); put back when VR ends",
                                       **_accessors("compositor_off_in_vr", bool))
    raytracing_off_in_vr: BoolProperty(name="Raytracing Off in VR",
                                       description="EEVEE raytracing is off while VR runs, and glass / refractive "
                                                   "objects are hidden meanwhile (they need it); put back when VR ends",
                                       **_accessors("raytracing_off_in_vr", bool))
    hide_transparent_in_vr: BoolProperty(name="Hide Transparent Materials in VR",
                                         description="Objects with transparent materials (alpha, blended, Transparent / "
                                                     "Glass / Refraction BSDF, Transmission) are hidden while VR runs; "
                                                     "put back when VR ends",
                                         **_accessors("hide_transparent_in_vr", bool))
    draw_distance: FloatProperty(name="Draw Distance", subtype='DISTANCE', unit='LENGTH', min=0.0, max=1000.0,
                                 description="Far clip of the VR view, 2 to 1000 m; 0 leaves Blender's value. "
                                             "Put back when VR ends",
                                 **_accessors("draw_distance", lambda value: 0.0 if value < 1.0 else max(2.0, float(value))))
    lower_shadows_in_vr: BoolProperty(name="Lower Shadow Resolution in VR",
                                      description="EEVEE shadow resolution scale is lowered to 0.25 while VR runs",
                                      **_accessors("lower_shadows_in_vr", bool))
    move_mode: EnumProperty(name="Movement", items=MOVE_MODE_ITEMS, **_accessors("move_mode"))
    move_heading: EnumProperty(name="Flight Heading", items=MOVE_HEADING_ITEMS, **_accessors("move_heading"))
    teleport_land: EnumProperty(name="Teleport Lands On", items=TELEPORT_LAND_ITEMS, **_accessors("teleport_land"))
    fly_pitch: EnumProperty(name="Flight Pitch", items=FLY_PITCH_ITEMS, **_accessors("fly_pitch"))
    turn_style: EnumProperty(name="Turning", items=TURN_STYLE_ITEMS, **_accessors("turn_style"))
    walk_speed: FloatProperty(name="Walk Speed", min=0.1, max=10.0, unit='VELOCITY', **_accessors("walk_speed", float))
    fly_speed: FloatProperty(name="Fly Speed", min=0.1, max=20.0, unit='VELOCITY', **_accessors("fly_speed", float))
    snap_angle: FloatProperty(name="Snap Angle", min=5.0, max=90.0, precision=0,
                              description="Degrees per push of the right stick (snap turning)",
                              **_accessors("snap_angle", float))
    turn_speed: FloatProperty(name="Turn Speed", min=10.0, max=360.0, precision=0,
                              description="Degrees per second (smooth turning)", **_accessors("turn_speed", float))
    plane_height: FloatProperty(name="Plane Height", subtype='DISTANCE', unit='LENGTH', min=-100.0, max=100.0,
                                description="Height of the floor plane (right stick up / down raises or lowers it)",
                                **_accessors("plane_height", float))
    eye_height: FloatProperty(name="Eye Height", subtype='DISTANCE', unit='LENGTH', min=0.5, max=2.5,
                              description="How high your eyes are above the floor when a plane mode starts "
                                          "(the floor plane is put that far below you)", **_accessors("eye_height", float))
    geo_slide_speed: FloatProperty(name="Height Slide Speed", min=0.05, max=5.0, unit='VELOCITY',
                                   description="Walk on Geometry: how fast your height slides to the ground "
                                               "after a step or an edge", **_accessors("geo_slide_speed", float))
    geo_step_height: FloatProperty(name="Max Step Height", subtype='DISTANCE', unit='LENGTH', min=0.05, max=2.0,
                                   description="Walk on Geometry: the highest step you climb; anything taller "
                                               "blocks you like a wall", **_accessors("geo_step_height", float))
    size_gesture: BoolProperty(name="Two-Hand Size Gesture",
                               description="Grip both hands on empty space and pull apart to shrink yourself, "
                                           "bring together to grow (about the point between your hands)",
                               **_accessors("size_gesture", bool))
    laser_length: FloatProperty(name="Laser Length", subtype='DISTANCE', unit='LENGTH', min=0.5, max=100.0,
                                **_accessors("laser_length", float))


classes = (DIGITSVR_PG_settings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.digits_vr = PointerProperty(type=DIGITSVR_PG_settings)


def unregister():
    del bpy.types.WindowManager.digits_vr
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
