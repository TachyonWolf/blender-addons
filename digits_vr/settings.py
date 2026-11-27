# SPDX-License-Identifier: GPL-3.0-or-later
"""The settings the sidebar shows, backed by the JSON file of settings_store.py (props use get / set callbacks on
one Python dict, so there is nothing to sync on file load). Saved on every change."""
import os
import tempfile

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty

from . import settings_store

FILE_NAME = "settings.json"
_current = {}


def user_folder():
    """DIGITS_VR_SETTINGS_DIR (tests), else the extension's user folder; a plain (non-extension) import falls back to
    Blender's temp folder (or the OS one: no literal "/tmp", it does not exist on Windows)."""
    folder = os.environ.get("DIGITS_VR_SETTINGS_DIR")
    if not folder:
        try:
            folder = bpy.utils.extension_path_user(__package__, create=True)
        except (ValueError, RuntimeError):
            folder = os.path.join(bpy.app.tempdir or tempfile.gettempdir(), "digits_vr")
    return folder


def settings_path():
    """settings.json in the user folder."""
    return os.path.join(user_folder(), FILE_NAME)


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


revision = 0     # bumped by every put: a quick "did any setting change" check (the desk's model gate)


def put(name, value):
    global revision
    revision += 1
    current()[name] = value
    settings_store.save(settings_path(), current())
    for listener in LISTENERS.get(name, ()):
        listener(value)


def put_many(values):
    """Set several settings with one file write (the desk saves its position, size and state together)."""
    global revision
    revision += 1
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


GRAB_MODE_ITEMS = (('FREE', "Free", "Picks with your palm by default; the order is set under Grab order"),
                   ('LASER', "Laser", "Picks with the laser by default; the order is set under Grab order"),
                   ('SELECT_GRAB', "Grab selected",
                    "The trigger selects; a grip anywhere moves the selection by the hand's motion"))
GRIP_TARGET_ITEMS = (('AIMED', "Aimed", "Acts on what you point at, unless it is already selected"),
                     ('SELECTION', "Selection", "Always acts on the selection"))
MOVE_MODE_ITEMS = (('WALK', "Walk on Plane", "The left stick walks you on a floor plane"),
                   ('TELEPORT', "Teleport on Plane",
                    "Hold the left stick forward to aim an arc; let go to jump to its end"),
                   ('GEO', "Walk on Geometry",
                    "The left stick walks you on real scene geometry; your height slides when you step up or down"),
                   ('FLY', "Free Flight", "The left stick moves you where you look; the right stick goes up and down"))
TURN_STYLE_ITEMS = (('SNAP', "Snap", "The right stick turns you in steps"),
                    ('SMOOTH', "Smooth", "The right stick turns you smoothly"))
MOVE_HEADING_ITEMS = (('HEAD', "Head", "The left stick moves you where your head looks (walking and flight)"),
                     ('HAND', "Hand", "The left stick moves you where your chosen hand points (walking and flight)"))
HEADING_HAND_ITEMS = (('LEFT', "Left", "The Hand heading follows your left hand"),
                      ('RIGHT', "Right", "The Hand heading follows your right hand"))
FLY_PITCH_ITEMS = (('HORIZONTAL', "Horizontal", "Free flight: forward stays level; the right stick goes up and down"),
                   ('FULL', "Full", "Free flight: forward flies dead ahead, up and down too (the right stick still adds height)"))
TELEPORT_LAND_ITEMS = (('PLANE', "Plane", "Teleport: the arc lands on the floor plane"),
                       ('GEO', "Geometry", "Teleport: the arc lands on scene geometry (no hit: the plane); your height then "
                                           "slides to the surface"))
START_AT_ITEMS = (('VIEWPORT', "Viewport", "Start VR with your head where the 3D View is, facing the same way"),
                  ('CAMERA', "Scene camera", "Start VR at the scene camera, as Blender does"))
FINGER_POKE_ITEMS = (('POINTER', "Pointer", "Only the index fingertip presses panel buttons, while its trigger is not pulled"),
                     ('ALL', "All", "Every fingertip presses panel buttons"),
                     ('NONE', "None", "Fingertips press nothing: the laser only"))
DRAW_DISTANCE_ITEMS = tuple((f"{distance:g}", f"{distance:g} m", "Far clip of the VR view" + (
    " (Blender's own)" if distance == settings_store.DEFAULT_DRAW_DISTANCE else "") + ". Put back when VR ends")
    for distance in settings_store.DRAW_DISTANCES)
GLASS_TIPS = {settings_store.GLASS_HIDE: "Glass is hidden in VR (only the glass faces of an object that is partly glass)",
              settings_store.GLASS_SOLID: "Glass shows as EEVEE draws it without raytracing: opaque",
              settings_store.GLASS_SEE_THROUGH: "Glass shows a see-through stand-in copy of its material in VR (alpha "
                                                "from transmission); objects that can't take it, or over the limit, are "
                                                "hidden. " + settings_store.SEE_THROUGH_WARNING}
GLASS_ITEMS = tuple((key, label, GLASS_TIPS[key] + ". Raytracing is always off in VR; put back when VR ends")
                    for key, label in settings_store.GLASS_CHOICES)
ENUMS = {"start_at": START_AT_ITEMS, "finger_poke": FINGER_POKE_ITEMS, "glass_in_vr": GLASS_ITEMS, "teleport_land": TELEPORT_LAND_ITEMS, "move_heading": MOVE_HEADING_ITEMS, "heading_hand": HEADING_HAND_ITEMS, "fly_pitch": FLY_PITCH_ITEMS, "grab_mode": GRAB_MODE_ITEMS, "grip_target": GRIP_TARGET_ITEMS, "move_mode": MOVE_MODE_ITEMS,
         "turn_style": TURN_STYLE_ITEMS}   # enum settings: identifiers in JSON


class DIGITSVR_PG_settings(bpy.types.PropertyGroup):
    grab_mode: EnumProperty(name="Grab Mode", items=GRAB_MODE_ITEMS, **_accessors("grab_mode"))
    grip_target: EnumProperty(name="Grip Target", items=GRIP_TARGET_ITEMS, **_accessors("grip_target"))
    touch_distance: FloatProperty(name="Touch Distance", subtype='DISTANCE', unit='LENGTH', min=0.005, max=0.5,
                                  description="How close a hand must be to grab in Free mode",
                                  **_accessors("touch_distance", float))
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
    smart_select: BoolProperty(name="Smart Select",
                               description="A first pick acts on the top-most parent; pick again quickly to get exactly what you point at (Object mode)",
                               **_accessors("smart_select", bool))
    paused: BoolProperty(name="Pause VR Tools",
                         description="Scene tools and stick movement off (for when an overlay app is on top); the left stick click toggles it",
                         **_accessors("paused", bool))
    show_hands: BoolProperty(name="Show Hands",
                             description="Draw a simple capsule hand on each controller",
                             **_accessors("show_hands", bool))
    finger_poke: EnumProperty(name="Finger Poke", items=FINGER_POKE_ITEMS, **_accessors("finger_poke"))
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
    glass_in_vr: EnumProperty(name="Glass in VR", items=GLASS_ITEMS, **_accessors("glass_in_vr"))
    hide_transparent_in_vr: BoolProperty(name="Hide Transparent Materials in VR",
                                         description="Objects with transparent materials (alpha, blended, Transparent / "
                                                     "Glass / Refraction BSDF, Transmission) are hidden while VR runs; "
                                                     "put back when VR ends",
                                         **_accessors("hide_transparent_in_vr", bool))
    draw_distance: EnumProperty(name="Draw Distance", items=DRAW_DISTANCE_ITEMS,
                                get=lambda _self: settings_store.DRAW_DISTANCES.index(get("draw_distance")),
                                set=lambda _self, index: put("draw_distance", settings_store.DRAW_DISTANCES[index]))
    lower_shadows_in_vr: BoolProperty(name="Lower Shadow Resolution in VR",
                                      description="EEVEE shadow resolution scale is lowered to 0.25 while VR runs",
                                      **_accessors("lower_shadows_in_vr", bool))
    move_mode: EnumProperty(name="Movement", items=MOVE_MODE_ITEMS, **_accessors("move_mode"))
    move_heading: EnumProperty(name="Flight Heading", items=MOVE_HEADING_ITEMS, **_accessors("move_heading"))
    heading_hand: EnumProperty(name="Heading Hand", items=HEADING_HAND_ITEMS, **_accessors("heading_hand"))
    start_at: EnumProperty(name="Start At", items=START_AT_ITEMS, **_accessors("start_at"))
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
                                           "bring together to grow (your head stays over the same spot)",
                               **_accessors("size_gesture", bool))
    size_invert: BoolProperty(name="Invert Two-Hand Size",
                              description="Pulling your hands apart makes you bigger instead of smaller",
                              **_accessors("size_invert", bool))
    laser_length: FloatProperty(name="Laser Length", subtype='DISTANCE', unit='LENGTH', min=0.5, max=100.0,
                                **_accessors("laser_length", float))
    belt_on: BoolProperty(name="Tool Belt",
                          description="A belt at your hip: drop a held item or a grabbed model at a slot, grip it out again",
                          **_accessors("belt_on", bool))
    belt_height: FloatProperty(name="Belt Height", subtype='DISTANCE', unit='LENGTH', min=0.3, max=1.2,
                               description="How far below your eyes the belt hangs (times Your size)",
                               **_accessors("belt_height", float))
    belt_size: FloatProperty(name="Belt Size", min=0.5, max=2.0, precision=2,
                             description="Size of the belt's slots and what sits in them (times Your size)",
                             **_accessors("belt_size", float))
    belt_snap_back: FloatProperty(name="Snap Back Distance", subtype='DISTANCE', unit='LENGTH', min=0.5, max=10.0,
                                  description="An Attached item farther from you than this goes back on the belt (times Your size)",
                                  **_accessors("belt_snap_back", float))


classes = (DIGITSVR_PG_settings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.digits_vr = PointerProperty(type=DIGITSVR_PG_settings)


def unregister():
    del bpy.types.WindowManager.digits_vr
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
