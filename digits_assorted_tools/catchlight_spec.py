# SPDX-License-Identifier: GPL-3.0-or-later
"""Catchlight: the one place for its names, option defaults and teaching tooltips. Plain data (no bpy), used
by catchlight.py and the tests."""

NAME = "Catchlight"
TAG = "setups_catchlight"          # custom property on the light object, so the card finds it whatever it is renamed to

DEFAULT_SIZE = 0.1                 # m
DEFAULT_STRENGTH = 40.0            # W (area light)
DEFAULT_COLOUR = (1.0, 1.0, 1.0)
DEFAULT_DISTANCE = 0.8             # m from the character's eye to the light
DEFAULT_CLOCK = '10'
DEFAULT_SHAPE = 'ROUND'

CLOCK_ITEMS = (  # (identifier, label, tooltip); the identifier is the clock hour
    ('10', "10 o'clock", "Up and to the viewer's left: the classic high catchlight, like the sun or a window above"),
    ('12', "12 o'clock", "Straight above: a centred sparkle, calm and symmetrical"),
    ('2', "2 o'clock", "Up and to the viewer's right: the mirror of 10 o'clock"),
)
SHAPE_ITEMS = (
    ('ROUND', "Round", "A round dot, like the sun or a lamp"),
    ('SQUARE', "Square", "A square sparkle: reads like a window"),
)

SIZE_HELP = ("Size of the light (m). Smaller = a crisper, tighter dot in the eye; larger = a bigger, softer reflection "
             "(the dot also grows if you bring the light closer)")
STRENGTH_HELP = "Brightness of the sparkle (W). It only has to outshine the eye's own highlights, so raise it until the dot is clearly white"
SHAPE_HELP = "Shape of the reflection: Round for a sun or lamp, Square for a window"
COLOUR_HELP = "Colour of the sparkle: white is neutral; a slightly warm or cool tint suggests a lamp or the sky"
DISTANCE_HELP = ("How far the light sits from the character's eye (m), on the viewer's side. Closer = a bigger, softer dot; "
                 "farther = a smaller one")
CLOCK_HELP = ("Where the sparkle sits in the eye, like a clock face seen by the viewer. Catchlights high on the eye "
              "(10 or 2 o'clock) look natural, like the sun or a window above; low ones look eerie")
BOTH_EYES_NOTE = "One light sparkles in both eyes when they face the same way"

LINK_EYES = "Linked to the eyes"
LINK_OBJECT = "Linked to the clicked object"

# The light sits this angle off the line from the viewer to the eye, so the reflection (halfway round the
# eyeball) lands about at the clock position, not in the pupil centre
OFFSET_ANGLE = 35.0   # degrees
