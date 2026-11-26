# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's screen: widget layout in screen pixels. Pure Python (no bpy), tested headless. The shared parts (Widget,
kinds, palette, hit-test, geometry) live in panel_layout.py and are re-exported here.

Pixel space: origin top-left, x right, y down, SCREEN_WIDTH x SCREEN_HEIGHT. The two handles sit just outside the
screen (x < 0 and x > SCREEN_WIDTH). The layout is rebuilt from a DeskModel (a frozen snapshot of what the screen
shows), so equal models mean the screen did not change and needs no redraw.

The approved redesign (docs/redesign/DeskInteractive.dc.html, positions taken from it): top row (modes, Lasers,
Pause), 8 tabs in two groups, the open tab's page (y 180-748; the Selected tab's Rig page: rig_layout.py), the ledge
(Undo, Redo, Tool options, Viewpoints, Cam view, the note line). An open pop-up or dropdown list is a last layer:
its backdrop covers the whole desk (a press there closes it)."""
import functools
from dataclasses import dataclass, replace

from . import outliner_layout, display_types, hand_marker_math as marker_math, help_layout, router, tool_rows
from .router import HIDDEN_GESTURES
from .subdiv_math import SubdivView
from .scale_math import PRESETS, preset_label
from .tool_rows import EditView, SculptView, ToolsModel  # noqa: F401
from .panel_widgets import (card as _card, dropdown as _dropdown, dropdown_list, pager as _pager,  # noqa: F401
                            popup_head as _popup_head, scrollbar as _scrollbar, slider as _slider, toggle as _toggle)
from .panel_layout import (ACCENT, ACTIVE, BACKDROP, BUTTON, BUTTON_FACE, BUTTON_SHADOW, CARD, DROPDOWN, FILL,  # noqa: F401
                           FILL_DIM, GOOD, GRIP_GREY, HANDLE, HINT, LABEL, LEDGE, LEDGE_EDGE, LEFT_HANDLE,
                           METERS_PER_PIXEL, MODE, NAVY_BOTTOM, NAVY_TOP, NOTICE, POPUP, RADIUS, SLIDER, TOP_HANDLE,
                           STAT, TAB, TEXT, TEXT_ON_ACCENT, THUMB, TITLE, TOGGLE, WARN, PanelSpec, Widget,
                           divider, frame_rects, grid, hint, hit_test, label as _label, popup as _popup, rgba,
                           rounded_outline, section, SCROLL_WIDTH, SCROLLBAR, side_handle, slider_fraction, slider_value, top_handle)

SCREEN_WIDTH, SCREEN_HEIGHT = 1024, 760     # the screen; below it the desk top (ledge)
DESK_WIDTH, DESK_HEIGHT = 1024, 900         # the whole texture: screen + ledge
EXTRA_STEP, MAX_EXTRA = 60, 2 * DESK_HEIGHT     # the desk may grow taller by up to 2 x its height (3 x in all) [user], in these steps
SPEC = PanelSpec(DESK_WIDTH, DESK_HEIGHT)   # desk scale 1.0 (not taller): about 46 x 40 cm
SIDE_HANDLE_TOP, SIDE_HANDLE_LENGTH = 230, 300      # side handles: top edge at the normal height; they keep their distance from the BOTTOM edge when the desk grows [user, 2026-11-26]
BODY = (DESK_WIDTH, DESK_HEIGHT)            # a pop-up's backdrop at the normal height (build() stretches it to a taller desk)
PAGE_TOP = 180                      # y of the open tab's page
PAGE_BOTTOM = 748                   # the page's usable bottom
LIST_BOTTOM = 888                   # a dropdown list may reach over the ledge, not past the desk
MODES = (('OBJECT', "Object"), ('EDIT_MESH', "Edit"), ('POSE', "Pose"), ('SCULPT', "Sculpt"),
         ('PAINT_GREASE_PENCIL', "Draw"))   # Draw: a Grease Pencil object; Sculpt: an editable mesh
WORK_TABS = (('selected', "Selected"), ('tools', "Tools"), ('grab', "Grab"), ('assets', "Assets"), ('outliner', "Outliner"), ('options', "Options"))
SETUP_TABS = (('file', "File"),)
TABS = WORK_TABS + SETUP_TABS
OPTION_TABS = (('move', "Move"), ('view', "View"), ('speed', "Speed"), ('body', "Body offsets"))   # Options: its sections [user, 2026-11-26]
OPTION_IDS = tuple(identifier for identifier, _label in OPTION_TABS)
TAB_IDS = tuple(identifier for identifier, _label in TABS if identifier != 'options') + OPTION_IDS
OLD_TABS = {'modifiers': 'selected', 'display': 'view', 'performance': 'speed'}    # tabs before the redesign
TAB_BOXES = ((24, 147), (181, 110), (301, 98), (409, 123), (542, 149), (752, 140), (902, 98))   # x, width: Options and File sit at the right end, Outliner sits after Assets
OPTION_BOXES = ((24, 120), (154, 120), (284, 130), (424, 220))                       # the Options section chips: x, width
OPTION_CHIPS_Y, OPTION_CHIPS_HEIGHT = 172, 40
OPTIONS_SHIFT = 44                          # an Options page starts this far lower (the chip row sits above it)
SHADINGS = (('SOLID', "Solid"), ('MATERIAL', "Material Preview"))
GRAB_MODES = (('FREE', "Free", "What your hand touches"), ('LASER', "Laser", "What the laser hits"),
              ('SELECT_GRAB', "Grab selected", "Laser selects, grip moves"))
FINGER_POKES = (('POINTER', "Pointer"), ('ALL', "All"), ('NONE', "None"))
MAX_MODIFIER_ROWS = 5     # the Subdivision ticker row took one row of room
TOUCH_RANGE_CM = (0.5, 50.0)
PUSH_SPEED_RANGE = (0.1, 10.0)   # m/s
LASER_LENGTH_RANGE = (0.5, 20.0)   # m
BELT_SNAP_RANGE, BELT_SIZE_RANGE = (0.5, 10.0), (0.5, 2.0)     # the tool belt's sliders (m, x)
# Options > Body offsets rows: (setting, caption, range in cm, minus button, plus button, readout words (minus, plus))
# The belt height is metres BELOW your eyes: its slider runs from up (left) to down (right).
BODY_ROWS = (("belt_forward", "Forward / back", (-40.0, 40.0), "Back", "Fwd", ("back", "forward")),
             ("belt_height", "Up / down", (30.0, 120.0), "Up", "Down", ("up", "down")),
             ("belt_side", "Left / right", (-30.0, 30.0), "Left", "Right", ("left", "right")),
             ("finger_forward", "Along the finger", (-5.0, 5.0), "In", "Out", ("in", "out")),
             ("finger_up", "Up / down", (-5.0, 5.0), "Down", "Up", ("down", "up")))
BODY_STEP_CM = {"belt_forward": 1.0, "belt_height": 1.0, "belt_side": 1.0, "finger_forward": 0.5, "finger_up": 0.5}
EYE_HEIGHT_RANGE_CM = (50.0, 250.0)
MOVE_MODES = (('WALK', "Walk on plane"), ('TELEPORT', "Teleport"), ('GEO', "Walk on geometry"), ('FLY', "Free flight"))
MOVE_HEADINGS = (('HEAD', "Heading: Head"), ('HAND', "Heading: Hand"))      # which way the left stick's forward points
FLY_PITCHES = (('HORIZONTAL', "Pitch: Horizontal"), ('FULL', "Pitch: Full"))   # Free flight: level forward, or dead ahead
TELEPORT_LANDS = (('PLANE', "Land on: Plane"), ('GEO', "Land on: Geometry"))   # Teleport: where the arc lands
TURN_STYLES = (('SNAP', "Snap turn"), ('SMOOTH', "Smooth turn"))
DRAW_DISTANCE_RANGE = (2.0, 1000.0)                                  # m, the VR far clip
WALK_SPEED_RANGE, FLY_SPEED_RANGE = (0.1, 10.0), (0.1, 20.0)      # m/s
SNAP_ANGLE_RANGE, TURN_SPEED_RANGE = (5.0, 90.0), (10.0, 360.0)   # degrees, degrees per second
PLANE_HEIGHT_RANGE = (-500.0, 500.0)                              # cm
SLIDE_SPEED_RANGE, STEP_HEIGHT_RANGE = (0.05, 5.0), (5.0, 200.0)   # m/s, cm (Walk on geometry)
LIST_POPUPS = ('layer', 'lib', 'poke')     # dropdown lists: a pick closes them
HEAVY_HINT = "Heavy modifiers off for every object: Speed tab."


@functools.lru_cache(maxsize=64)
def spec_for(extra):
    """The desk's spec when it is `extra` pixels taller than its normal size (the extra sits between the screen and the desk top)."""
    return PanelSpec(DESK_WIDTH, DESK_HEIGHT + extra)


def clamp_extra(extra):
    """A wanted extra height, in whole steps within 0 .. MAX_EXTRA."""
    return int(min(MAX_EXTRA, max(0, round(extra / EXTRA_STEP) * EXTRA_STEP)))


@dataclass(frozen=True)
class AssetsView:
    """What the Assets page shows (plain values: equal views need no redraw)."""
    libraries: tuple = ()       # library names
    library: int = 0            # index of the open library
    chips: tuple = ()           # ((catalog id or None for All, label), ...) the catalog pop-up's page of chips
    chip_page: int = 0
    chip_pages: int = 1
    catalog: object = None      # the chosen catalog id (None = all)
    catalog_label: str = "All"
    tiles: tuple = ()           # ((key, name, kind label), ...) of the page
    page: int = 0
    pages: int = 1
    total: int = 0              # assets in the library + catalog
    message: str = ""           # a line in the pager row (scan state, a hint, what a drop did)
    primitives: bool = False    # the Primitives list is open (no catalogs)


@dataclass(frozen=True)
class PerfView:
    """The Performance tab's numbers (plain values: equal views need no redraw)."""
    fps: int = 0                # headset frames per second (0 = no frames seen)
    python_p95: float = 0.0     # ms of our Python per headset frame, p95
    triangles: int = -1         # evaluated triangles of visible meshes (-1 = not counted yet)
    counting: bool = False
    heavy_off: int = 0          # heavy modifiers VR turned off
    heavy_on: int = 0           # heavy modifiers still on in the viewport
    raytracing: bool = False
    shadow_scale: float = 1.0
    taa_samples: int = 16
    compositor: str = 'DISABLED'
    objects_hidden: int = 0     # objects hidden for VR (glass / transparent)
    draw_distance: float = 0.0  # the VR far clip in m now


@dataclass(frozen=True)
class DeskModel(ToolsModel):
    """Everything the screen shows. Frozen and made of plain values, so `model == last_model` means no redraw."""
    extra: int = 0              # pixels the desk is taller than normal (the user's top handle): lists show more rows
    tab: str = 'grab'
    grab_mode: str = 'FREE'
    grip_target: str = 'AIMED'
    touch_distance_cm: float = 6.0
    fine_control: bool = False
    name_tag: bool = True
    show_hands: bool = True
    hand_marker: float = 0.0    # the hand marker size in m (0 = the tiny default)
    finger_poke: str = 'POINTER'
    push_speed: float = 1.5     # m/s
    always_laser: bool = True
    paused: bool = False
    smart_select: bool = True
    workspace_label: str = outliner_layout.EVERYTHING_LABEL    # the workspace collection's name (chip on the ledge)
    workspace_current: str = ""      # its name_full ("" = Everything)
    workspace_rows: tuple = ()       # the Outliner tab: OutlinerRow of the page on show
    workspace_scroll: int = 0       # first Outliner row on show
    workspace_last: int = 0         # the highest first row (0 = everything shows: no scroll bar)
    outliner_drag: str = ""          # name_full of the object being dragged (reparent)
    outliner_drop: str = ""          # fold key of the row under the dragged object (glows)
    help_on: bool = False
    help_rows: tuple = ()       # the Controls pop-up: ((hand, button, title, second line), ...)
    hide_heavy: bool = True
    perf: PerfView = PerfView()
    compositor_off: bool = True
    raytracing_off: bool = True
    lower_shadows: bool = False
    hide_transparent: bool = False
    draw_distance: float = 0.0          # the setting in m (0 = Blender's own value is used)
    shading: str = 'MATERIAL'
    show_floor: bool = True
    object_name: str = ""
    modifiers: tuple = ()       # ((name, type label, shown in VR), ...)
    subdiv: SubdivView = SubdivView()   # the Subdivision ticker row (Selected > Modifiers)
    disabled_modes: tuple = ()  # modes the active object can't enter (Pose needs an armature)
    assets: AssetsView = AssetsView()
    move_mode: str = 'WALK'
    move_heading: str = 'HEAD'
    teleport_land: str = 'PLANE'
    fly_pitch: str = 'HORIZONTAL'
    turn_style: str = 'SNAP'
    walk_speed: float = 1.5     # m/s
    fly_speed: float = 2.5
    snap_angle: float = 30.0    # degrees
    turn_speed: float = 120.0   # degrees per second
    plane_height_cm: float = 0.0
    geo_slide_speed: float = 0.5   # m/s
    geo_step_height_cm: float = 40.0
    size_preset: float = 1.0    # the preset your size is on (0 = between presets, after the two-hand gesture)
    size_gesture: bool = True   # two grips on empty space scale you
    size_invert: bool = False   # pulling apart makes you bigger
    display_hidden: tuple = ()  # View tab: keys of display_types the VR view hides
    selected_sub: str = 'rig'   # Selected tab: 'rig' or 'mods'
    grab_more: bool = False     # Grab tab: the More foldout is open
    eye_height_cm: float = 160.0
    laser_length: float = 10.0  # m
    belt_on: bool = True        # Grab > More: the tool belt (belt.py)
    belt_height: float = 0.73   # m below the eyes
    belt_forward_cm: float = -12.0   # Options > Body offsets (cm; minus = towards your back)
    belt_side_cm: float = 0.0
    finger_forward_cm: float = 0.0
    finger_up_cm: float = 0.0
    belt_size: float = 1.0
    belt_snap_back: float = 3.0  # m
    belt_take_fingertip: bool = True
    tool_options_open: bool = False
    tool_gun_open: bool = False
    pda_open: bool = False
    rig: object = None          # the Selected tab's rig_layout.RigView (None = empty)
    viewpoints_open: bool = False   # the viewpoints window (its ledge button lit)
    camera_view_open: bool = False  # the Cam view panel (camera_panel.py) is open
    haptics: bool = False           # View tab: the Haptics pop-up's settings and the Scale meter toggle
    haptics_strength: float = 1.0
    haptics_point: bool = True
    haptics_grab: bool = True
    haptics_other: bool = True
    scale_meter: bool = False
    note: str = ""              # a short message on the desk top (no camera, recentered, failsafe): replaces the title
    file_name: str = ""         # File tab: the open file's name ("" = untitled)
    file_status: str = ""       # File tab: Saved / Unsaved changes / Not saved yet
    file_message: str = ""      # File tab: a refusal or failure



def _list(*arguments):
    return dropdown_list(*arguments, BODY)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _grab_page(model, top):
    widgets = grid("grab", GRAB_MODES, 24, top, 976, 3, 68, lambda index, item, x, y, w, h: Widget(
        "grab_" + item[0], CARD, x, y, w, h, label=item[1], detail=item[2], action=("grab_mode", item[0]), size=30,
        active=model.grab_mode == item[0]))
    widgets += grid("grip_target", router.GRIP_TARGETS, 24, top + 76, 976, 2, 48, lambda index, item, x, y, w, h: Widget(
        "grip_" + item[0], CARD, x, y, w, h, label="Grip: " + item[1], detail=item[2], action=("grip_target", item[0]), size=24,
        active=model.grip_target == item[0]))
    top += 40                                        # (the rows below make room for the grip target)
    widgets += [_slider("touch_distance", 24, top + 92, 480, 68, "Touch distance", model.touch_distance_cm, TOUCH_RANGE_CM),
                _slider("push_speed", 520, top + 92, 480, 68, "Push speed", model.push_speed, PUSH_SPEED_RANGE,
                        unit="m/s", step=0.1, factor=1.0)]
    widgets += grid("toggles", (("fine_control", "Fine control (B)", model.fine_control),
                                ("name_tag", "Show names", model.name_tag), ("show_hands", "Show hands", model.show_hands)),
                    24, top + 172, 976, 3, 52, lambda index, item, x, y, w, h: _toggle(
                        item[0], x, y, w, h, item[1], item[0], item[2], size=24))
    more = model.grab_more
    widgets.append(Widget("grab_more", DROPDOWN, 24, top + 232, 976, 56, size=28,
                          label="More: finger poke, laser, hand marker, belt",
                          caret="▾" if more else "▸", action=("grab_more",)))
    if not more:
        return widgets
    y = top + 300
    poke_label = dict(FINGER_POKES)[model.finger_poke]
    marker_cm, marker_text = marker_math.slider_cm(model.hand_marker)
    widgets += [_dropdown("poke", 24, y, 480, 56, "Finger poke: " + poke_label, ("popup", "poke"),
                          model.popup == 'poke', size=26)]
    widgets += [_slider("laser_length", 24, y + 80, 315, 68, "Laser length", model.laser_length, LASER_LENGTH_RANGE,
                        unit="m", step=0.5, factor=1.0, size=24),
                _slider("hand_marker", 355, y + 80, 315, 68, "Marker", marker_cm, marker_math.RANGE_CM, size=24, text=marker_text),
                _slider("belt_snap_back", 685, y + 80, 315, 68, "Snap back", model.belt_snap_back, BELT_SNAP_RANGE, unit="m",
                        step=0.5, factor=1.0, size=24)]
    widgets.append(_card("hand_marker_default", 355, y + 156, 315, 52, "Marker: Default", ("hand_marker_default",), size=24,
                         enabled=model.hand_marker > 0))
    widgets += [_toggle("belt_take_fingertip", 766, y, 234, 56, "Take: fingertip", "belt_take_fingertip",
                        model.belt_take_fingertip, size=22)]
    return widgets


def _grab_overlay(model, top):
    y = top + 312 + 64
    if model.popup == 'poke':
        return _list("poke_list", 24, y, 480, [("poke_" + key, text, ("finger_poke", key), model.finger_poke == key)
                                               for key, text in FINGER_POKES], ("popup", ""))
    return []


def _move_page(model, top):
    """Your size (presets, two-hand toggle, Recenter), movement, its options and turn, the speeds in two columns."""
    widgets = [section("size_title", "Your size", 24, top + 12, 190),
               _toggle("size_gesture", 224, top, 350, 52, "Two-hand scaling", "size_gesture", model.size_gesture, size=25),
               _toggle("size_invert", 590, top, 214, 52, "Invert", "size_invert", model.size_invert, size=25),
               _card("recenter", 820, top, 180, 52, "Recenter", ("recenter",), size=26)]
    widgets += grid("size", PRESETS, 24, top + 64, 976, len(PRESETS), 60, lambda index, item, x, y, w, h: _card(
        "size_%g" % item, x, y, w, h, preset_label(item), ("size_preset", item), size=26,
        active=model.size_preset == item), gap_x=8)
    widgets.append(divider("move_line", 24, top + 140))
    widgets += grid("move", MOVE_MODES, 24, top + 158, 976, 4, 64, lambda index, item, x, y, w, h: _card(
        "move_" + item[0], x, y, w, h, item[1], ("move_mode", item[0]), size=26, active=model.move_mode == item[0]))
    if model.move_mode == 'TELEPORT':       # Teleport has its own arc (no heading): choose where it lands
        options = [("land_" + key, text, ("teleport_land", key), model.teleport_land == key) for key, text in TELEPORT_LANDS]
    else:           # Heading for every stick move; Pitch only in flight
        options = [("heading_" + key, text, ("move_heading", key), model.move_heading == key) for key, text in MOVE_HEADINGS]
        if model.move_mode == 'FLY':
            options += [("pitch_" + key, text, ("fly_pitch", key), model.fly_pitch == key) for key, text in FLY_PITCHES]
    options += [("turn_" + key, text, ("turn_style", key), model.turn_style == key) for key, text in TURN_STYLES]
    two_rows = len(options) > 4       # Free flight: Pitch adds a second row of options, so the rows below are a little tighter
    widgets += grid("options", options, 24, top + 234, 976, 4, 44 if two_rows else 52, lambda index, item, x, y, w, h: _card(
        item[0], x, y, w, h, item[1], item[2], size=24, active=item[3]), gap_y=8 if two_rows else 10)
    snap = model.turn_style == 'SNAP'
    sliders = [("walk_speed", "Walk speed", model.walk_speed, WALK_SPEED_RANGE, "m/s", 0.1, 1.0),
               ("fly_speed", "Flight speed", model.fly_speed, FLY_SPEED_RANGE, "m/s", 0.1, 1.0),
               ("snap_angle", "Snap angle", model.snap_angle, SNAP_ANGLE_RANGE, "deg", 5.0, 1.0) if snap else
               ("turn_speed", "Turn speed", model.turn_speed, TURN_SPEED_RANGE, "deg/s", 5.0, 1.0)]
    geo = model.move_mode == 'GEO'
    if geo:       # the plane height means nothing on geometry: its row (and Reset) give way to the slide options
        sliders += [("geo_slide_speed", "Height slide speed", model.geo_slide_speed, SLIDE_SPEED_RANGE, "m/s", 0.05, 1.0),
                    ("geo_step_height", "Max step height", model.geo_step_height_cm, STEP_HEIGHT_RANGE, "cm", 5.0, 0.01)]
    else:
        sliders.append(("plane_height", "Plane height", model.plane_height_cm, PLANE_HEIGHT_RANGE, "cm", 1.0, 0.01))
    sliders.append(("eye_height", "Eye height", model.eye_height_cm, EYE_HEIGHT_RANGE_CM, "cm", 1.0, 0.01))
    slider_top, height = (top + 338, 56) if two_rows else (top + 298, 64)
    widgets += grid("sliders", sliders, 24, slider_top, 976, 2, height, lambda index, item, x, y, w, h: _slider(
        item[0], x, y, w, h, item[1], item[2], item[3], unit=item[4], step=item[5], factor=item[6], size=26,
        decimals=2 if item[5] < 0.1 else (1 if item[5] < 1 else 0)), gap_y=10 if not two_rows else 6)
    if not geo:
        index = len(sliders)
        x = 24 + (index % 2) * 496
        y = slider_top + (index // 2) * (height + (10 if not two_rows else 6))
        widgets.append(_card("plane_reset", x, y, 480, height, "Plane height: Reset", ("plane_reset",), size=26))
    return widgets


def offset_text(cm, words):
    """A Body offsets readout: "12 cm back", "0 cm" (`words` = the minus and the plus direction)."""
    if abs(cm) < 0.05:
        return "0 cm"
    return f"{abs(cm):g} cm {words[0] if cm < 0 else words[1]}"


def body_value_cm(model, setting):
    """The cm a Body offsets slider shows for `setting` (the belt height is shown in cm below the eyes)."""
    return model.belt_height * 100.0 if setting == "belt_height" else getattr(model, setting + "_cm")


def _body_page(model, top):
    """Options > Body offsets: the belt (on, size, forward / back, up / down, left / right) and the tool point on your finger
    (along, up / down), each a slider with a button either side; Reset to defaults and the live hint [user, 2026-11-26]."""
    widgets = [section("belt_title", "Belt", 24, top), section("finger_title", "Finger point (sculpt, select, laser start)", 24, top + 296),
               _toggle("belt_on", 24, top + 32, 300, 60, "Tool belt", "belt_on", model.belt_on, size=26),
               _slider("belt_size", 340, top + 32, 660, 60, "Belt size", model.belt_size, BELT_SIZE_RANGE, unit="x", step=0.05,
                       factor=1.0, size=26, decimals=2)]
    ys = (top + 100, top + 166, top + 232, top + 328, top + 394)
    for y, (setting, caption, (low, high), minus, plus, words) in zip(ys, BODY_ROWS):
        cm, step = body_value_cm(model, setting), BODY_STEP_CM[setting]
        belt_height = setting == "belt_height"
        widgets += [_card("nudge_minus_" + setting, 24, y, 88, 60, minus, ("nudge", setting, -step), size=24),
                    _slider(setting, 124, y, 752, 60, caption, cm, (low, high), unit="cm", step=step, factor=0.01, size=26,
                            decimals=1 if step < 1 else 0,
                            text=f"{cm:g} cm below eyes" if belt_height else offset_text(cm, words)),
                    _card("nudge_plus_" + setting, 888, y, 112, 60, plus, ("nudge", setting, step), size=24)]
    widgets += [_card("body_reset", 24, top + 472, 300, 52, "Reset to defaults", ("body_reset",), size=26),
                hint("body_hint", "Live: the belt and a ball at each tool point show while this page is open. Move your hands to check.",
                     348, top + 472, 652, 50, style=GOOD, size=22)]
    return widgets


def _tools_page(model, top):
    """The current mode's tools and settings: the Tool options panel's rows (tool_rows.py) in two columns."""
    return tool_rows.wide(model, 24, top, 976)


def _modifiers_page(model, top):
    """Selected > Modifiers: which of the selected object's modifiers show in VR."""
    if not model.object_name:
        return [hint("modifiers_hint", "Select an object to choose which modifiers show in VR.", 24, top, size=28, h=36)]
    widgets = [section("modifiers_title", "Show in VR: " + model.object_name, 24, top)] + _subdiv_row(model.subdiv, top + 40)
    top += 72                                       # the stack's rows start under the ticker row
    if not model.modifiers:
        widgets.append(hint("modifiers_none", "This object has no modifiers.", 24, top + 40, size=28, h=36))
    for index, (name, type_label, shown) in enumerate(model.modifiers[:MAX_MODIFIER_ROWS]):
        widgets.append(Widget(f"modifier_{index}", TOGGLE, 24, top + 40 + index * 72, 976, 60, label=name,
                              detail=f"({type_label})", action=("modifier", index), active=shown, size=30))
    rows = min(len(model.modifiers), MAX_MODIFIER_ROWS)
    y = top + 40 + max(rows, 1) * 72
    if len(model.modifiers) > MAX_MODIFIER_ROWS:
        extra = len(model.modifiers) - MAX_MODIFIER_ROWS
        widgets.append(hint("modifiers_more", f"+ {extra} more (sidebar).  " + HEAVY_HINT, 24, y))
    else:
        widgets.append(hint("modifiers_heavy_hint", HEAVY_HINT, 24, y))
    return widgets


def _subdiv_row(view, y):
    """The Subdivision ticker: name, - level +, a short note. Always there; dimmed when the object can't take it."""
    return [Widget("subdiv_label", LABEL, 24, y, 300, 60, label="Subdivision", size=30, **({"style": HINT} if view.dimmed else {})),
            _card("subdiv_down", 340, y, 96, 60, "−", ("subdiv", -1), size=40, enabled=view.minus),
            Widget("subdiv_level", LABEL, 444, y, 96, 60, label=str(view.level), size=40, style=HINT if view.dimmed else TITLE),
            _card("subdiv_up", 548, y, 96, 60, "+", ("subdiv", 1), size=40, enabled=view.plus),
            hint("subdiv_note", view.note, 660, y, 340, 60, style=WARN if view.warn else HINT)]


def _selected_page(model, top):
    """Selected: a Rig / Modifiers switch, then that page."""
    from .rig_layout import selected_page     # here: rig_layout builds on this module's widgets
    widgets = grid("sub", (('rig', "Rig"), ('mods', "Modifiers")), 24, top, 976, 2, 56, lambda index, item, x, y, w, h:
                   _card("sub_" + item[0], x, y, w, h, item[1], ("selected_sub", item[0]),
                         active=model.selected_sub == item[0]))
    if model.selected_sub == 'mods':
        return widgets + _modifiers_page(model, top + 68)
    return widgets + selected_page(model.rig, top + 68, model.extra)


def _snapshot_button(y, text):
    """Snapshot (camera_preview.snapshot: the scene camera's view) and Screenshot (screenshot.py: what you see in the
    headset), both saved as PNGs. On the View and File tabs."""
    return [Widget("snapshot", BUTTON, 24, y, 300, 84, label="Snapshot", action=("snapshot",), size=34),
            Widget("screenshot", BUTTON, 340, y, 300, 84, label="Screenshot", action=("screenshot",), size=34),
            hint("snapshot_hint", text, 656, y, 344, 84)]


def _view_page(model, top):
    """View: shading, what the VR view shows (the old Display tab; the floor is one of them), Snapshot."""
    hidden = model.display_hidden
    widgets = [section("shading_title", "Shading", 24, top)]
    widgets += grid("shading", SHADINGS, 24, top + 40, 976, 2, 64, lambda index, item, x, y, w, h: _card(
        "shading_" + item[0], x, y, w, h, item[1], ("shading", item[0]), size=32, active=model.shading == item[0]))
    widgets += [divider("view_line", 24, top + 116), section("display_title", "Show in VR (lit = shown)", 24, top + 134, 720),
                _card("display_all", 760, top + 124, 240, 48, "Show all", ("display_all",), size=26, enabled=bool(hidden))]
    items = list(display_types.MAIN) + [None]
    widgets += grid("display", items, 24, top + 182, 976, 4, 56, lambda index, item, x, y, w, h: (
        _dropdown("display_more", x, y, w, h, "More types", ("popup", "types"), model.popup == 'types', caret="▸", size=24)
        if item is None else Widget("display_" + item.key, TOGGLE, x, y, w, h, label=item.label,
                                    action=("display", item.key), active=item.key not in hidden, size=24)), gap_y=10)
    widgets += [hint("display_hint", "Display choices are VR only.", 24, top + 312),
                divider("view_line_2", 24, top + 348)]
    widgets += _snapshot_button(top + 362, "Snapshot: the camera's view. Screenshot: your headset view. Both are PNGs.")
    return widgets + [_dropdown("haptics_more", 24, top + 462, 480, 52, "Haptics" + (": on" if model.haptics else ""),
                                ("popup", "haptics"), model.popup == 'haptics', caret="▸", size=26),
                      _toggle("scale_meter", 520, top + 462, 480, 52, "Scale meter", "scale_meter", model.scale_meter, size=26)]


HAPTIC_TESTS = (("right", "Right"), ("left", "Left"), ("point", "Point tick"), ("grab", "Grab"))   # haptics_test.py


def _haptics_overlay(model):
    """Haptics pop-up: master switch (off = today's buzzes only), strength, one toggle per kind [user, 2026-11-25]."""
    x, y, w = 64, 190, 896
    widgets = _popup("haptics_popup", x, y, w, 490, ("popup", ""), BODY)
    widgets += _popup_head("haptics_popup", x, y, w, "Haptics")
    on = model.haptics
    widgets += [_toggle("haptics", x + 27, y + 93, w - 54, 60, "Haptics (off = only today's buzzes)", "haptics", on, size=26),
                _slider("haptics_strength", x + 27, y + 165, w - 54, 68, "Strength", model.haptics_strength, (0.1, 1.0),
                        unit="", step=0.1, factor=1.0, decimals=1, enabled=on),
                _toggle("haptics_point", x + 27, y + 245, w - 54, 56, "Pulse when what you point at changes",
                        "haptics_point", model.haptics_point, size=24, enabled=on),
                _toggle("haptics_grab", x + 27, y + 313, (w - 70) // 2, 56, "A different pulse for a grab",
                        "haptics_grab", model.haptics_grab, size=24, enabled=on),
                _toggle("haptics_other", x + 43 + (w - 70) // 2, y + 313, (w - 70) // 2, 56, "Refused, limits, ticks",
                        "haptics_other", model.haptics_other, size=24, enabled=on)]
    widgets += grid("haptics_test", HAPTIC_TESTS, x + 27, y + 385, w - 54, 4, 60, lambda index, item, cx, cy, cw, ch: _card(
        "haptics_test_" + item[0], cx, cy, cw, ch, "Test: " + item[1], ("haptics_test", item[0]), size=22))
    return widgets


def _types_overlay(model):
    x, y, w = 64, 190, 896
    hidden = model.display_hidden
    widgets = _popup("types_popup", x, y, w, 418, ("popup", ""), BODY)
    widgets += _popup_head("types_popup", x, y, w, "More types (lit = shown)")
    widgets += grid("display_more_types", display_types.MORE, x + 27, y + 93, w - 54, 3, 56, lambda index, item, cx, cy, cw, ch:
                    Widget("display_" + item.key, TOGGLE, cx, cy, cw, ch, label=item.label, action=("display", item.key),
                           active=item.key not in hidden, size=26))
    widgets.append(hint("display_warn", "Warning: " + display_types.MESH_WARNING + ".", x + 27, y + 367, w - 54,
                        style=WARN))
    return widgets


COMPOSITOR_LABELS = {'DISABLED': "off", 'CAMERA': "camera only", 'ALWAYS': "always"}


def perf_lines(perf, shading):
    """The stats as (label, value) rows, filled column by column (left column first)."""
    triangles = "..." if perf.triangles < 0 else f"{perf.triangles:,}" + (" (counting)" if perf.counting else "")
    return [("Frame rate", f"{perf.fps} fps" if perf.fps else "no frames"),
            ("Our Python", f"{perf.python_p95:.2f} ms p95"),
            ("Triangles", triangles),
            ("Heavy modifiers", f"{perf.heavy_off} off, {perf.heavy_on} on"),
            ("Shading", dict(SHADINGS).get(shading, shading)),
            ("Raytracing", "on" if perf.raytracing else "off"),
            ("Shadows scale", f"{perf.shadow_scale:g}"),
            ("TAA samples", str(perf.taa_samples)),
            ("Compositor", COMPOSITOR_LABELS.get(perf.compositor, perf.compositor.lower())),
            ("Hidden for VR", str(perf.objects_hidden))]


def _speed_page(model, top):
    """Speed (was Performance): three stat tiles + All stats, the lighter-in-VR toggles, Safe settings, draw distance."""
    lines = dict(perf_lines(model.perf, model.shading))
    tiles = (("Frame rate", lines["Frame rate"]), ("Our Python (p95)", f"{model.perf.python_p95:.2f} ms"),
             ("Triangles", lines["Triangles"]))
    widgets = [Widget(f"perf_tile_{index}", LABEL, 24 + index * 248, top, 232, 96, label=value, detail=caption,
                      style=STAT) for index, (caption, value) in enumerate(tiles)]
    widgets += [_dropdown("perf_stats", 768, top, 232, 96, "All stats", ("popup", "stats"), model.popup == 'stats',
                          caret="▸", size=28),
                divider("speed_line", 24, top + 112), section("speed_title", "Lighter in VR (put back when VR ends)", 24, top + 130)]
    toggles = (("perf_heavy", "Heavy modifiers off", "hide_heavy_modifiers", model.hide_heavy),
               ("perf_compositor", "Compositor off", "compositor_off_in_vr", model.compositor_off),
               ("perf_raytracing", "Raytracing off (hides glass)", "raytracing_off_in_vr", model.raytracing_off),
               ("perf_shadows", "Lower shadow resolution", "lower_shadows_in_vr", model.lower_shadows),
               ("perf_transparent", "Hide transparent materials", "hide_transparent_in_vr", model.hide_transparent), None)
    widgets += grid("perf", toggles, 24, top + 170, 976, 2, 60, lambda index, item, x, y, w, h: (
        _card("safe_settings", x, y, w, h, "Safe settings now", ("safe_settings",), size=26) if item is None else
        _toggle(item[0], x, y, w, h, item[1], item[2], item[3], size=24)))
    distance = model.draw_distance or model.perf.draw_distance
    widgets += [_slider("draw_distance", 24, top + 386, 800, 76, "Draw distance", distance, DRAW_DISTANCE_RANGE, unit="m",
                        step=0.1, factor=1.0, log=True, decimals=0 if distance >= 10 else 1,
                        text="" if model.draw_distance else f"Blender's ({distance:g} m)"),
                _card("draw_distance_reset", 840, top + 386, 160, 76, "Default", ("draw_distance_reset",),
                      enabled=model.draw_distance > 0),
                hint("perf_hint", "Still slow? Lower SteamVR's render resolution for Blender (per-app setting).", 24, top + 474)]
    return widgets


def _stats_overlay(model):
    x, y, w = 144, 220, 736
    widgets = _popup("stats_popup", x, y, w, 371, ("popup", ""), BODY)
    widgets += _popup_head("stats_popup", x, y, w, "All stats", (
        _card("perf_recount", x + w - 359, y + 23, 170, 56, "Recount", ("perf_recount",), size=26),))
    column_width = (w - 54 - 24) / 2
    for index, (name, value) in enumerate(perf_lines(model.perf, model.shading)):
        column, row_number = index % 2, index // 2
        cx, cy = x + 27 + column * (column_width + 24), y + 93 + row_number * 48
        widgets += [Widget(f"perf_stat_{index}", LABEL, cx, cy, column_width, 32, label=name, size=26, style=HINT),
                    Widget(f"perf_value_{index}", LABEL, cx, cy, column_width, 32, label=value, size=26, style='right'),
                    divider(f"perf_rule_{index}", cx, cy + 38, column_width)]
    return widgets


ASSET_COLUMNS, ASSET_ROWS = 5, 2
ASSET_TILE_WIDTH, ASSET_TILE_HEIGHT, ASSET_GAP = 176, 200, 12     # a scroll bar fits right of the five columns
ASSET_CHIP_SLOTS = 9                # catalogs per page of the Catalog pop-up (3 x 3)
TILE_THUMB = 128                    # thumbnail edge in pixels (previews are stored at this size)


def asset_rows(extra=0):
    """Rows of tiles on a page: two, and one more for each tile row of extra desk height."""
    return ASSET_ROWS + extra // (ASSET_TILE_HEIGHT + ASSET_GAP)


def assets_per_page(extra=0):
    return ASSET_COLUMNS * asset_rows(extra)


def asset_tile_rect(index, top):
    """(x, y, w, h) of tile number `index` (row by row) on the Assets page."""
    column, row_number = index % ASSET_COLUMNS, index // ASSET_COLUMNS
    return (24 + column * (ASSET_TILE_WIDTH + 14), top + 76 + row_number * (ASSET_TILE_HEIGHT + ASSET_GAP),
            ASSET_TILE_WIDTH, ASSET_TILE_HEIGHT)


def _assets_page(model, top):
    view = model.assets
    widgets = []
    if view.libraries:
        widgets.append(_dropdown("library", 24, top, 480, 60, "Library: " + view.libraries[view.library],
                                 ("popup", "lib"), model.popup == 'lib'))
    if view.libraries and not view.primitives:
        widgets.append(_dropdown("catalog", 520, top, 480, 60, "Catalog: " + view.catalog_label, ("popup", "cat"),
                                 model.popup == 'cat', caret="▸"))
    for index, (key, name, kind) in enumerate(view.tiles):
        x, y, w, h = asset_tile_rect(index, top)
        widgets.append(Widget(f"asset_{index}", THUMB, x, y, w, h, label=name, action=("asset", index), size=24))
    rows = asset_rows(model.extra)
    grid_height = rows * (ASSET_TILE_HEIGHT + ASSET_GAP) - ASSET_GAP
    widgets += _scrollbar("asset_scroll", 972, top + 76, grid_height, view.page, view.pages - 1, "asset_page",
                           area=(24, top + 76, 940, grid_height))
    widgets += _pager("asset", 24, top + 76 + grid_height + 16, 976, view.page, view.pages, "asset_page", button_width=180,
                      height=60, text=view.message or f"Page {view.page + 1} of {view.pages}  ({view.total})")
    return widgets


def _assets_overlay(model, top):
    view = model.assets
    if model.popup == 'lib' and view.libraries:
        return _list("library_list", 24, top + 68, 480, [(f"library_{index}", name, ("asset_library", index),
                                                          index == view.library) for index, name in enumerate(view.libraries)],
                     ("popup", ""))
    if model.popup != 'cat' or not view.libraries or view.primitives:
        return []
    x, y, w = 144, 250, 736
    widgets = _popup("catalog_popup", x, y, w, 378, ("popup", ""), BODY)
    widgets += _popup_head("catalog_popup", x, y, w, "Catalog")
    widgets += _scrollbar("chip_scroll", x + w - 27 - SCROLL_WIDTH, y + 93, 3 * 68 - 12, view.chip_page, view.chip_pages - 1,
                          "asset_chips", area=(x + 27, y + 93, w - 54 - SCROLL_WIDTH - 12, 3 * 68 - 12))
    widgets += grid("chip", view.chips, x + 27, y + 93, w - 54 - SCROLL_WIDTH - 12, 3, 56, lambda index, chip, cx, cy, cw, ch: _card(
        f"chip_{index}", cx, cy, cw, ch, chip[1], ("asset_catalog", chip[0]), size=26, active=view.catalog == chip[0]))
    return widgets + _pager("chip", x + 27, y + 299, w - 54, view.chip_page, view.chip_pages, "asset_chips")


def _file_page(model, top):
    """File tab: the file name, Save and its status, Snapshot, Restore my settings (later)."""
    dirty = model.file_status == "Unsaved changes"
    status_style = WARN if dirty or model.file_status == "Not saved yet" else GOOD
    status = "● " + model.file_status if dirty else model.file_status
    return [section("file_title", "File", 24, top),
            Widget("file_name", LABEL, 24, top + 40, 976, 56, label=model.file_name or "Untitled", size=44, style=TITLE),
            Widget("file_save", BUTTON, 24, top + 114, 300, 96, label="Save", action=("file_save",), size=44),
            Widget("file_status", LABEL, 348, top + 114, 652, 96, label=status, size=34, style=status_style),
            hint("file_message", model.file_message, 24, top + 228, style=WARN) if model.file_message else
            hint("file_hint", "Saves your work. VR-only changes are never saved into the file.", 24, top + 228),
            divider("file_line", 24, top + 278)] + _snapshot_button(top + 302, "Snapshot: the camera's view. Screenshot: your headset view.") + [
            _card("restore_settings", 24, top + 410, 480, 64, "Restore my settings (later)", size=26, enabled=False)]


def page_widgets(model, top):
    if model.tab == 'selected':
        return _selected_page(model, top)
    if model.tab == 'assets':
        return _assets_page(model, top)
    if model.tab == 'grab':
        return _grab_page(model, top)
    if model.tab == 'outliner':
        return outliner_layout.page_widgets(model, top)
    if model.tab == 'view':
        return _view_page(model, top)
    if model.tab == 'move':
        return _move_page(model, top)
    if model.tab == 'tools':
        return _tools_page(model, top)
    if model.tab == 'speed':
        return _speed_page(model, top)
    if model.tab == 'body':
        return _body_page(model, top)
    if model.tab == 'file':
        return _file_page(model, top)
    return []


def overlay_widgets(model, top):
    """The open pop-up or dropdown list of the page, drawn over everything (empty when none is open)."""
    if model.popup == 'help':
        return help_layout.build(model.help_rows, HIDDEN_GESTURES, BODY)
    if model.tab == 'selected' and model.selected_sub == 'rig' and model.rig is not None and model.rig.picker_open:
        from .rig_layout import picker_overlay
        return picker_overlay(model.rig, top + 68, model.extra)
    if not model.popup:
        return []
    if model.tab == 'tools':
        return tool_rows.overlay(model, _tools_page(model, top), BODY, LIST_BOTTOM + model.extra)
    if model.tab == 'grab' and model.grab_more:
        return _grab_overlay(model, top)
    if model.tab == 'assets':
        return _assets_overlay(model, top)
    if model.tab == 'view' and model.popup == 'types':
        return _types_overlay(model)
    if model.tab == 'view' and model.popup == 'haptics':
        return _haptics_overlay(model)
    if model.tab == 'speed' and model.popup == 'stats':
        return _stats_overlay(model)
    return []


def _tab_row(model):
    """The tab buttons in two groups (work, setup), as wide as their labels (the mock-up's widths). Options is lit while one
    of its sections is open."""
    return [Widget("tab_" + identifier, TAB, x, 104, width, 60, label=text, action=("tab", identifier),
                   active=model.tab == identifier or (identifier == 'options' and model.tab in OPTION_IDS), size=27)
            for (identifier, text), (x, width) in zip(TABS, TAB_BOXES)]


def _option_chips(model):
    """Options: its sections (Move, View, Speed, Body offsets) in a smaller tab row above the page."""
    return [Widget("tab_" + identifier, TAB, x, OPTION_CHIPS_Y, width, OPTION_CHIPS_HEIGHT, label=text,
                   action=("tab", identifier), active=model.tab == identifier, size=24)
            for (identifier, text), (x, width) in zip(OPTION_TABS, OPTION_BOXES)]


def build(model):
    """All widgets of the desk for `model`, back to front."""
    widgets = grid("mode", MODES, 24, 18, 440, len(MODES), 72, lambda index, item, x, y, w, h: Widget(
        "mode_" + item[0], MODE, x, y, w, h, label=item[1], action=("mode", item[0]), active=model.mode == item[0],
        enabled=item[0] not in model.disabled_modes, size=24), gap_x=8)
    widgets += [_toggle("always_laser", 472, 18, 168, 72, "Lasers", "always_laser", model.always_laser, size=26),   # [user]
                _toggle("smart_select", 648, 18, 176, 72, "Smart", "smart_select", model.smart_select, size=26),   # [user, 2026-11-26]
                _toggle("pause", 832, 18, 168, 72, "Pause", "paused", model.paused, size=26)]   # the setting `paused`: its behaviour is the Pause agent's
    widgets += _tab_row(model)
    in_options = model.tab in OPTION_IDS
    widgets += _option_chips(model) if in_options else []
    widgets += page_widgets(model, PAGE_TOP + (OPTIONS_SHIFT if in_options else 0))
    # the ledge below the screen: the raised buttons and the note line
    ledge = (("undo", "Undo", ("undo",), False, 88, 26), ("redo", "Redo", ("redo",), False, 88, 26),
             ("tool_options", "Tool options", ("panel", "tool_options"), model.tool_options_open, 160, 24),
             ("tool_gun", "Tool gun", ("panel", "tool_gun"), model.tool_gun_open, 118, 24),
             ("viewpoints", "Viewpoints", ("panel", "viewpoints"), model.viewpoints_open, 138, 24),
             ("camera_preview", "Cam view", ("panel", "camera_view"), model.camera_view_open, 122, 24),
             ("help", "Help", ("toggle", "help_on"), model.help_on, 84, 24),      # Help on the ledge [user, 2026-11-25]
             ("pda", "PDA", ("panel", "pda"), model.pda_open, 76, 24))
    x = 24
    for identifier, text, action, active, width, size in ledge:
        widgets.append(Widget(identifier, BUTTON, x, 780 + model.extra, width, 74, label=text, action=action, active=active, size=size))
        x += width + 12
    widgets.append(Widget("title", LABEL, 24, 860 + model.extra, 620, 30, label=model.note or "Digit's VR", size=24,
                          style=NOTICE if model.note else 'note'))
    widgets.append(_card("workspace_chip", 654, 856 + model.extra, 346, 38, outliner_layout.chip_text(model.workspace_label),   # opens the Outliner tab
                         ("tab", "outliner"), size=22, active=bool(model.workspace_current)))
    widgets += [side_handle('LEFT', DESK_WIDTH, SIDE_HANDLE_TOP + model.extra, SIDE_HANDLE_LENGTH), side_handle('RIGHT', DESK_WIDTH, SIDE_HANDLE_TOP + model.extra, SIDE_HANDLE_LENGTH), top_handle(DESK_WIDTH)]
    full_height = DESK_HEIGHT + model.extra          # a pop-up's veil covers the whole (taller) desk
    widgets += [replace(widget, h=full_height) if widget.kind == BACKDROP else widget
                for widget in overlay_widgets(model, PAGE_TOP)]
    if model.paused:     # Pause: everything dims except the Pause toggle and the handles; a bar says why
        widgets = [widget if widget.id == "pause" or widget.kind == HANDLE else replace(widget, enabled=False)
                   for widget in widgets]
        if model.popup != 'help':
            widgets.append(Widget("paused_bar", LABEL, 24, 330, 976, 120, label="Paused: press Pause or the left stick to go on",
                                  size=34, style=NOTICE))
    return widgets


def on_screen(px, py):
    """Inside the desk body (screen + desk top)."""
    return SPEC.on_body(px, py)


def pixel_to_local(px, py):
    """Desk-local metres (scale 1) of a texture pixel (see panel_layout)."""
    return SPEC.pixel_to_local(px, py)


def local_to_pixel(x, y):
    return SPEC.local_to_pixel(x, y)


def body_rects(extra=0):
    """The desk body: the bezel, the screen with its navy gradient (`extra` pixels taller), the desk top (ledge) below it.
    (x, y, w, h, radius, colour or f(pixel y))."""
    ledge_top = SCREEN_HEIGHT + extra + 6
    return frame_rects(DESK_WIDTH, SCREEN_HEIGHT + extra) + [
        (0, ledge_top, DESK_WIDTH, DESK_HEIGHT + extra - ledge_top, 22, rgba(LEDGE_EDGE)),
        (3, ledge_top + 3, DESK_WIDTH - 6, DESK_HEIGHT + extra - ledge_top - 6, 20, rgba(LEDGE))]
