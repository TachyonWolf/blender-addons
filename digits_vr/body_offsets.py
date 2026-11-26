# SPDX-License-Identifier: GPL-3.0-or-later
"""Body offsets (DESIGN "Options page"): where the belt hangs against your body frame and where the tool point sits on your
finger, as the user set them on the desk's Options > Body offsets page. ONE place that reads the settings: the belt
(belt_state.frame) and the fingertip (hands.fingertip) ask here. Values are metres at your size 1; callers scale by Your size."""
from mathutils import Matrix, Vector

from . import settings
from .desk_state import DESK

PAGE = 'body'                       # the desk tab that shows the live preview
BODY_SETTINGS = ("belt_on", "belt_height", "belt_forward", "belt_side", "belt_size", "finger_forward", "finger_up")
OFFSET_SETTINGS = BODY_SETTINGS[1:]   # the numbers "Reset to defaults" puts back (belt_on is a switch, kept)


def belt_shift():
    """The belt's offset in the body frame (x right, y forward, z up), metres at size 1."""
    return Vector((settings.get("belt_side"), settings.get("belt_forward"), 0.0))


def belt_matrix():
    return Matrix.Translation(belt_shift())


def finger_shift():
    """The tool point's offset in the hand's own space (y up, -z along the finger), metres at size 1."""
    return Vector((0.0, settings.get("finger_up"), -settings.get("finger_forward")))


def previewing():
    """The Body offsets page is open: the belt and the tool point show so a change is seen at once."""
    return DESK.open and DESK.tab == PAGE


def defaults():
    """{setting: default} of the offsets (the Reset to defaults button)."""
    from .settings_store import FIELDS
    return {name: FIELDS[name][0] for name in OFFSET_SETTINGS}
