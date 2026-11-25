# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's screen: widget layout and hit-testing in screen pixels. Pure Python (no bpy), tested headless.

Pixel space: origin top-left, x right, y down, SCREEN_WIDTH x SCREEN_HEIGHT. The two handles sit just outside the
screen (x < 0 and x > SCREEN_WIDTH). The layout is rebuilt from a DeskModel (a frozen snapshot of what the screen
shows), so equal models mean the screen did not change and needs no redraw.

Top to bottom: Undo / Redo bar, Mode row (Object, Pose), tabs, the open tab's page (the Selected tab's page: rig_layout.py)."""
import math
from dataclasses import dataclass

from .annotate_math import PALETTE, THICKNESS_RANGE
from . import display_types
from .gpencil_math import RADIUS_RANGE_CM
from .scale_math import PRESETS, preset_label

SCREEN_WIDTH, SCREEN_HEIGHT = 1024, 760     # the screen; below it the desk top (ledge) with Undo / Redo
DESK_WIDTH, DESK_HEIGHT = 1024, 900         # the whole texture: screen + ledge
METERS_PER_PIXEL = 0.00045                  # desk scale 1.0: about 46 x 40 cm
ANNOTATE_WIDTH, HIDE_X, HIDE_ROWS = 590, 640, 4          # Object tools: x of the Hide column, rows of its list
PAGE_TOP = 178                      # y of the open tab's page
RADIUS = 9                                  # rounded corners of buttons and cards
BEZEL = 5                                   # the pale blue frame around the screen

ACCENT = "#7fd0ff"                  # pale blue: desk accents
ACTIVE = "#ffb36b"                  # orange: the active mode
NAVY_TOP, NAVY_BOTTOM = "#132333", "#0d1824"
FILL, FILL_DIM, FILL_PRESSED = "#1d3a52", "#15283a", "#2f6a94"
TEXT, TEXT_DIM, TEXT_ON_ACCENT = "#e6f4ff", "#5c7387", "#0d1824"
LEDGE, LEDGE_EDGE, BUTTON_FACE, BUTTON_SHADOW = "#1b2f43", "#3d6a8c", "#2f6a94", "#0a141e"
GRIP_GREY = "#c9d3de"

MODES = (('OBJECT', "Object"), ('POSE', "Pose"), ('PAINT_GREASE_PENCIL', "Draw"))   # Draw: a Grease Pencil object; Edit and Sculpt are Later
TABS = (('selected', "Selected"), ('grab', "Grab"), ('tools', "Tools"), ('assets', "Assets"), ('move', "Move"),
        ('modifiers', "Modifiers"), ('view', "View"), ('display', "Display"), ('performance', "Performance"))
TAB_IDS = tuple(identifier for identifier, _label in TABS)
SHADINGS = (('SOLID', "Solid"), ('MATERIAL', "Material Preview"))
GRAB_MODES = (('FREE', "Free"), ('LASER', "Laser"), ('SELECT_GRAB', "Select and Grab"))
ROTATIONS = (('PUPPET', "Puppet"), ('STICK', "On stick"), ('AUTO', "Auto"))
MAX_MODIFIER_ROWS = 6
TOUCH_RANGE_CM = (0.5, 50.0)
SWAP_RANGE_CM = (0.5, 200.0)
PUSH_SPEED_RANGE = (0.1, 10.0)   # m/s
MOVE_MODES = (('WALK', "Walk on plane"), ('TELEPORT', "Teleport on plane"), ('GEO', "Walk on geometry"), ('FLY', "Free flight"))
MOVE_HEADINGS = (('HEAD', "Heading: Head"), ('HAND', "Heading: Hand"))      # which way the left stick's forward points
FLY_PITCHES = (('HORIZONTAL', "Pitch: Horizontal"), ('FULL', "Pitch: Full"))   # Free flight: level forward, or dead ahead
TELEPORT_LANDS = (('PLANE', "Land on: Plane"), ('GEO', "Land on: Geometry"))   # Teleport: where the arc lands
TURN_STYLES = (('SNAP', "Snap turn"), ('SMOOTH', "Smooth turn"))
DRAW_DISTANCE_RANGE = (2.0, 1000.0)                                  # m, the VR far clip
WALK_SPEED_RANGE, FLY_SPEED_RANGE = (0.1, 10.0), (0.1, 20.0)      # m/s
SNAP_ANGLE_RANGE, TURN_SPEED_RANGE = (5.0, 90.0), (10.0, 360.0)   # degrees, degrees per second
PLANE_HEIGHT_RANGE = (-500.0, 500.0)                              # cm
SLIDE_SPEED_RANGE, STEP_HEIGHT_RANGE = (0.05, 5.0), (5.0, 200.0)   # m/s, cm (Walk on geometry)
BLURBS = {}

# widget kinds
BUTTON, MODE, TAB, CARD, TOGGLE, SLIDER, HANDLE, LABEL, THUMB = ('BUTTON', 'MODE', 'TAB', 'CARD', 'TOGGLE', 'SLIDER',
                                                                 'HANDLE', 'LABEL', 'THUMB')
LEFT_HANDLE, RIGHT_HANDLE = "handle_left", "handle_right"


@dataclass(frozen=True)
class Widget:
    id: str
    kind: str
    x: float
    y: float
    w: float
    h: float
    label: str = ""
    action: tuple = ()          # what a press does, e.g. ("mode", "EDIT"); () = nothing
    enabled: bool = True
    active: bool = False        # selected tab / mode / card, toggle on
    value: float = 0.0          # slider position (real units)
    minimum: float = 0.0
    log: bool = False           # slider: positions are logarithmic (for ranges like 2 m to 1000 m)
    maximum: float = 1.0
    size: int = 38              # text size in pixels
    unit: str = "cm"            # slider: shown after the value
    step: float = 0.5           # slider: values snap to multiples of this
    decimals: int = 1           # slider: digits shown after the point
    color: str = ""             # swatch: the colour it shows (hex)

    def contains(self, px, py):
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass(frozen=True)
class AssetsView:
    """What the Assets page shows (plain values: equal views need no redraw)."""
    libraries: tuple = ()       # library names
    library: int = 0            # index of the open library
    chips: tuple = ()           # ((catalog id or None for All, label), ...) the chips on show (More = the last)
    catalog: object = None      # the chosen catalog id (None = all)
    tiles: tuple = ()           # ((key, name, kind label), ...) of the page
    page: int = 0
    pages: int = 1
    total: int = 0              # assets in the library + catalog
    message: str = ""           # a line in the pager row (scan state, a hint, what a drop did)


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
class DeskModel:
    """Everything the screen shows. Frozen and made of plain values, so `model == last_model` means no redraw."""
    mode: str = 'OBJECT'
    tab: str = 'grab'
    grab_mode: str = 'FREE'
    touch_distance_cm: float = 6.0
    rotation_mode: str = 'AUTO'
    swap_linked: bool = True
    swap_distance_cm: float = 6.0
    fine_control: bool = False
    name_tag: bool = True
    push_speed: float = 1.5     # m/s
    always_laser: bool = True
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
    annotate_on: bool = False
    annotate_color: str = 'red'
    annotate_thickness: int = 3
    annotate_strokes: int = 0   # strokes our annotation layers hold (Erase last / Clear all need one)
    gp_materials: tuple = ()    # Draw mode: ((name, hex colour), ...) of the Grease Pencil object's materials
    gp_material: int = 0        # the active material's index
    gp_layer: str = ""          # the active layer's name
    gp_layer_index: int = 0
    gp_layer_count: int = 0
    gp_strokes: int = 0         # strokes of the active layer at this frame
    gp_radius_cm: float = 1.0
    hidden_shown: tuple = ()    # names of the hidden objects on this list page (Unhide from list)
    hidden_page: int = 0
    hidden_pages: int = 1
    hidden_total: int = 0
    can_hide: bool = False      # a visible object is selected
    display_hidden: tuple = ()  # Display tab: keys of display_types the VR view hides
    display_more: bool = False  # Display tab: the second page (more object types)
    rig: object = None          # the Selected tab's rig_layout.RigView (None = empty)


def hex_rgb(code):
    return tuple(int(code[index:index + 2], 16) / 255.0 for index in (1, 3, 5))


def _row(prefix, items, x, y, total_width, height, gap, make):
    """One horizontal row of equal widgets."""
    width = (total_width - gap * (len(items) - 1)) / len(items)
    return [make(index, item, x + index * (width + gap), y, width, height) for index, item in enumerate(items)]


def _label(identifier, text, x, y, w=976, size=34):
    return Widget(identifier, LABEL, x, y, w, size + 8, label=text, size=size)


def _grab_page(model, top):
    widgets = [_label("grab_title", "Grab mode", 24, top)]
    widgets += _row("grab", GRAB_MODES, 24, top + 44, 976, 72, 16, lambda index, item, x, y, w, h: Widget(
        "grab_" + item[0], CARD, x, y, w, h, label=item[1], action=("grab_mode", item[0]), size=36,
        active=model.grab_mode == item[0]))
    widgets.append(_label("rotation_title", "Rotation", 24, top + 124))
    widgets += _row("rotation", ROTATIONS, 24, top + 168, 976, 64, 16, lambda index, item, x, y, w, h: Widget(
        "rotation_" + item[0], CARD, x, y, w, h, label=item[1], action=("rotation_mode", item[0]), size=36,
        active=model.rotation_mode == item[0]))
    widgets.append(Widget("swap_linked", TOGGLE, 24, top + 242, 976, 52, label="Swap at the touch distance",
                          action=("toggle", "swap_linked"), active=model.swap_linked, size=34))
    widgets.append(Widget("swap_distance", SLIDER, 24, top + 302, 976, 70, label="Swap at", size=34,
                          action=("slider", "swap_distance"), enabled=not model.swap_linked,
                          value=model.touch_distance_cm if model.swap_linked else model.swap_distance_cm,
                          minimum=SWAP_RANGE_CM[0], maximum=SWAP_RANGE_CM[1]))
    widgets.append(Widget("fine_control", TOGGLE, 24, top + 376, 480, 52, label="Fine control (B)",
                          action=("toggle", "fine_control"), active=model.fine_control, size=34))
    widgets.append(Widget("name_tag", TOGGLE, 520, top + 376, 480, 52, label="Name tag",
                          action=("toggle", "name_tag"), active=model.name_tag, size=34))
    widgets.append(Widget("touch_distance", SLIDER, 24, top + 432, 976, 64, label="Touch distance", size=34,
                          action=("slider", "touch_distance"), value=model.touch_distance_cm,
                          minimum=TOUCH_RANGE_CM[0], maximum=TOUCH_RANGE_CM[1]))
    widgets.append(Widget("push_speed", SLIDER, 24, top + 500, 976, 64, label="Push speed", size=34,
                          action=("slider", "push_speed", 1.0), value=model.push_speed, unit="m/s", step=0.1,
                          minimum=PUSH_SPEED_RANGE[0], maximum=PUSH_SPEED_RANGE[1]))
    return widgets


def _move_page(model, top):
    """Your size (preset buttons + the two-hand gesture toggle), then movement. Everything fits above the ledge."""
    widgets = [_label("size_title", "Your size", 24, top, 300, 30),
               Widget("size_gesture", TOGGLE, 440, top - 4, 560, 44, label="Two-hand grip scales you", size=26,
                      action=("toggle", "size_gesture"), active=model.size_gesture)]
    widgets += _row("size", PRESETS, 24, top + 40, 976, 56, 8, lambda index, item, x, y, w, h: Widget(
        "size_%g" % item, CARD, x, y, w, h, label=preset_label(item), action=("size_preset", item), size=28,
        active=model.size_preset == item))
    widgets.append(_label("move_title", "Movement", 24, top + 106, 300, 30))
    widgets += _row("move", MOVE_MODES, 24, top + 142, 976, 60, 16, lambda index, item, x, y, w, h: Widget(
        "move_" + item[0], CARD, x, y, w, h, label=item[1], action=("move_mode", item[0]), size=32,
        active=model.move_mode == item[0]))
    if model.move_mode == 'TELEPORT':       # Teleport has its own arc (no heading): choose where it lands
        widgets += _row("land", TELEPORT_LANDS, 24, top + 208, 976, 48, 8,
                        lambda index, item, x, y, w, h: Widget("land_" + item[0], CARD, x, y, w, h, label=item[1], size=24,
                                                               action=("teleport_land", item[0]), active=model.teleport_land == item[0]))
    else:           # Heading for every stick move; Pitch only in flight
        widgets += _row("heading", MOVE_HEADINGS, 24, top + 208, 480 if model.move_mode == 'FLY' else 976, 48, 8,
                        lambda index, item, x, y, w, h: Widget("heading_" + item[0], CARD, x, y, w, h, label=item[1], size=24,
                                                               action=("move_heading", item[0]), active=model.move_heading == item[0]))
        if model.move_mode == 'FLY':
            widgets += _row("pitch", FLY_PITCHES, 520, top + 208, 480, 48, 8,
                            lambda index, item, x, y, w, h: Widget("pitch_" + item[0], CARD, x, y, w, h, label=item[1], size=24,
                                                                   action=("fly_pitch", item[0]), active=model.fly_pitch == item[0]))
    widgets += _row("turn", TURN_STYLES, 24, top + 262, 976, 56, 16, lambda index, item, x, y, w, h: Widget(
        "turn_" + item[0], CARD, x, y, w, h, label=item[1], action=("turn_style", item[0]), size=32,
        active=model.turn_style == item[0]))
    snap = model.turn_style == 'SNAP'
    turn_name, turn_value, turn_range = (("snap_angle", model.snap_angle, SNAP_ANGLE_RANGE) if snap
                                         else ("turn_speed", model.turn_speed, TURN_SPEED_RANGE))
    sliders = (("walk_speed", "Walk speed", model.walk_speed, WALK_SPEED_RANGE, "m/s", 0.1, 1.0),
               ("fly_speed", "Flight speed", model.fly_speed, FLY_SPEED_RANGE, "m/s", 0.1, 1.0),
               (turn_name, "Snap angle" if snap else "Turn speed", turn_value, turn_range,
                "deg" if snap else "deg/s", 5.0, 1.0),
               ("plane_height", "Plane height", model.plane_height_cm, PLANE_HEIGHT_RANGE, "cm", 1.0, 0.01))
    geo = model.move_mode == 'GEO'
    if geo:       # the plane height means nothing on geometry: its row (and Reset) give way to the slide options
        sliders = sliders[:3] + (("geo_slide_speed", "Height slide speed", model.geo_slide_speed, SLIDE_SPEED_RANGE,
                                  "m/s", 0.05, 1.0),
                                 ("geo_step_height", "Max step height", model.geo_step_height_cm, STEP_HEIGHT_RANGE,
                                  "cm", 5.0, 0.01))
    slider_top = 328
    spacing = 48 if geo else 58
    for index, (name, label, value, (low, high), unit, step, factor) in enumerate(sliders):
        y = top + slider_top + index * spacing        # five sliders (geometry) sit closer to fit the screen
        widgets.append(Widget(name, SLIDER, 24, y, 800 if name == "plane_height" else 976, spacing - 6, label=label, size=30,
                              action=("slider", name, factor), value=value, minimum=low, maximum=high, unit=unit,
                              step=step))
    if not geo:
        widgets.append(Widget("plane_reset", BUTTON, 848, top + slider_top + 3 * spacing, 152, spacing - 6, label="Reset", size=32,
                              action=("plane_reset",)))
    return widgets


def _hide_column(model, top):
    """Right column of the Object tools: Hide, Unhide and the Unhide-from-list rows (4 per page, Prev / Next)."""
    x, width = HIDE_X, 1000 - HIDE_X
    widgets = [_label("hide_title", "Hide", x, top, width),
               Widget("hide_selected", CARD, x, top + 44, width, 60, label="Hide selected", size=32,
                      action=("hide_selected",), enabled=model.can_hide),
               Widget("unhide_all", CARD, x, top + 112, width, 60, label="Unhide all", size=32,
                      action=("unhide_all",), enabled=model.hidden_total > 0),
               _label("hide_list_title", "Unhide from list (%d)" % model.hidden_total, x, top + 186, width, 30)]
    for index in range(layout_rows()):
        name = model.hidden_shown[index] if index < len(model.hidden_shown) else ""
        widgets.append(Widget("hide_row_%d" % index, CARD, x, top + 228 + index * 58, width, 52, label=name, size=28,
                              action=("unhide_one", name), enabled=bool(name)))
    pager_y = top + 228 + layout_rows() * 58
    half = (width - 12) / 2
    widgets.append(Widget("hide_prev", CARD, x, pager_y, half, 52, label="Prev", size=30, action=("hide_page", -1),
                          enabled=model.hidden_page > 0))
    widgets.append(Widget("hide_next", CARD, x + half + 12, pager_y, half, 52, label="Next", size=30,
                          action=("hide_page", 1), enabled=model.hidden_page + 1 < model.hidden_pages))
    return widgets


def layout_rows():
    return HIDE_ROWS


def _gpencil_page(model, top):
    """Tools of Draw mode: material swatches (the pick is the active material), radius, layer picker, Erase last,
    Clear layer."""
    width = 976
    widgets = [_label("gp_title", "Grease Pencil", 24, top), _label("gp_material_title", "Material", 24, top + 44)]
    if model.gp_materials:
        widgets += _row("gp_swatch", model.gp_materials, 24, top + 88, width, 64, 12, lambda index, item, x, y, w, h: Widget(
            "gp_material_%d" % index, CARD, x, y, w, h, action=("gp_material", index), color=item[1],
            active=model.gp_material == index))
    widgets.append(Widget("gp_radius", SLIDER, 24, top + 172, width, 78, label="Thickness (radius)", size=34,
                          action=("slider", "gp_radius", 0.01), value=model.gp_radius_cm, minimum=RADIUS_RANGE_CM[0],
                          maximum=RADIUS_RANGE_CM[1], unit="cm", step=0.1))
    has_layers = model.gp_layer_count > 0
    widgets += [_label("gp_layer_title", "Layer", 24, top + 270),
                Widget("gp_layer_prev", CARD, 24, top + 314, 160, 64, label="Prev", size=30, action=("gp_layer", -1),
                       enabled=model.gp_layer_index > 0),
                Widget("gp_layer_name", CARD, 200, top + 314, width - 400, 64, label=model.gp_layer or "-", size=32),
                Widget("gp_layer_next", CARD, width - 160 + 24, top + 314, 160, 64, label="Next", size=30,
                       action=("gp_layer", 1), enabled=model.gp_layer_index + 1 < model.gp_layer_count)]
    widgets += _row("gp_erase", (("gp_erase", "Erase last stroke"), ("gp_clear", "Clear layer at this frame")), 24,
                    top + 410, width, 72, 16, lambda index, item, x, y, w, h: Widget(
                        item[0], CARD, x, y, w, h, label=item[1], action=(item[0],), size=30,
                        enabled=model.gp_strokes > 0 and has_layers))
    return widgets


def _tools_page(model, top):
    """The current mode's tools: Annotate in Object mode, Clear transforms / Mirror pose in Pose mode."""
    if model.mode == 'OBJECT':
        widgets = [_label("tools_title", "Annotate", 24, top),
                   Widget("annotate_on", TOGGLE, 24, top + 44, ANNOTATE_WIDTH, 56, label="Draw with the trigger",
                          action=("annotate_toggle",), active=model.annotate_on, size=34),
                   _label("annotate_color_title", "Colour", 24, top + 116)]
        widgets += _row("swatch", PALETTE, 24, top + 160, ANNOTATE_WIDTH, 64, 12, lambda index, item, x, y, w, h: Widget(
            "annotate_color_" + item[0], CARD, x, y, w, h, action=("annotate_color", item[0]), color=item[2],
            active=model.annotate_color == item[0]))
        widgets.append(Widget("annotate_thickness", SLIDER, 24, top + 240, ANNOTATE_WIDTH, 78, label="Thickness", size=34,
                              action=("slider", "annotate_thickness", 1.0), value=model.annotate_thickness,
                              minimum=THICKNESS_RANGE[0], maximum=THICKNESS_RANGE[1], unit="px", step=1.0))
        has_strokes = model.annotate_strokes > 0
        widgets += _row("erase", (("annotate_erase", "Erase last stroke"), ("annotate_clear", "Clear all")), 24,
                        top + 338, ANNOTATE_WIDTH, 72, 16, lambda index, item, x, y, w, h: Widget(
                            item[0], CARD, x, y, w, h, label=item[1], action=(item[0],), size=30, enabled=has_strokes))
        widgets.append(Widget("gp_new", CARD, 24, top + 424, ANNOTATE_WIDTH, 64, label="New Grease Pencil", size=32,
                              action=("gp_new",)))
        return widgets + _hide_column(model, top)
    if model.mode == 'PAINT_GREASE_PENCIL':
        return _gpencil_page(model, top)
    if model.mode == 'POSE':
        return [_label("tools_title", "Pose tools (selected bones)", 24, top)] + _row(
            "pose", (("pose_clear", "Clear transforms"), ("pose_mirror", "Mirror pose")), 24, top + 44, 976, 72, 16,
            lambda index, item, x, y, w, h: Widget(item[0], CARD, x, y, w, h, label=item[1], action=(item[0],),
                                                   size=34))
    return [_label("tools_none", "No tools in this mode.", 24, top)]


def _modifiers_page(model, top):
    if not model.object_name:
        return [_label("modifiers_hint", "Select an object to choose which modifiers show in VR.", 24, top)]
    widgets = [_label("modifiers_title", "Show in VR: " + model.object_name, 24, top)]
    if not model.modifiers:
        widgets.append(_label("modifiers_none", "This object has no modifiers.", 24, top + 44, size=30))
    for index, (name, type_label, shown) in enumerate(model.modifiers[:MAX_MODIFIER_ROWS]):
        widgets.append(Widget(f"modifier_{index}", TOGGLE, 24, top + 44 + index * 54, 976, 48,
                              label=f"{name}   ({type_label})", action=("modifier", index), active=shown, size=34))
    if len(model.modifiers) > MAX_MODIFIER_ROWS:
        extra = len(model.modifiers) - MAX_MODIFIER_ROWS
        widgets.append(_label("modifiers_more", f"+ {extra} more (sidebar)", 24, top + 44 + MAX_MODIFIER_ROWS * 54,
                              size=28))
    widgets.append(Widget("hide_heavy", TOGGLE, 24, top + 44 + (MAX_MODIFIER_ROWS + 1) * 54 + 4, 976, 50,
                          label="Heavy modifiers off in VR", action=("toggle", "hide_heavy_modifiers"),
                          active=model.hide_heavy, size=34))
    return widgets


def _view_page(model, top):
    widgets = [_label("shading_title", "Shading", 24, top)]
    widgets += _row("shading", SHADINGS, 24, top + 40, 976, 84, 16, lambda index, item, x, y, w, h: Widget(
        "shading_" + item[0], CARD, x, y, w, h, label=item[1], action=("shading", item[0]),
        active=model.shading == item[0], size=36))
    widgets.append(Widget("floor", TOGGLE, 24, top + 150, 976, 56, label="Show floor", action=("floor",),
                          active=model.show_floor, size=34))
    return widgets


def _display_page(model, top):
    """Display tab: a toggle per thing the VR view can hide (lit = shown). Common ones first, the rest on a second page."""
    hidden = model.display_hidden

    def toggle(item, x, y, w):
        return Widget("display_" + item.key, TOGGLE, x, y, w, 56, label=item.label, action=("display", item.key),
                      active=item.key not in hidden, size=32)
    show_all = Widget("display_all", BUTTON, 524, top, 476, 56, label="Show all", action=("display_all",),
                      enabled=bool(hidden), size=32)
    if not model.display_more:
        widgets = [toggle(item, 24, top + index * 66, 476) for index, item in enumerate(display_types.MAIN)]
        widgets += [show_all, Widget("display_more", CARD, 524, top + 66, 476, 56, label="More types >",
                                     action=("display_more",), size=32),
                    _label("display_hint", "Lit = shown in VR. VR only: your scene is not changed.", 524, top + 150, w=476, size=26)]
        return widgets
    widgets = [toggle(item, 24 + (index % 3) * 332, top + (index // 3) * 66, 312) for index, item in enumerate(display_types.MORE)]
    rows = (len(display_types.MORE) + 2) // 3
    widgets += [Widget("display_back", CARD, 24, top + rows * 66 + 12, 312, 56, label="< Back", action=("display_more",), size=32),
                Widget("display_all", BUTTON, 356, top + rows * 66 + 12, 312, 56, label="Show all", action=("display_all",),
                       enabled=bool(hidden), size=32),
                _label("display_warn", "Warning: " + display_types.MESH_WARNING + ".", 24, top + rows * 66 + 84, size=26)]
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


def _performance_page(model, top):
    widgets = [_label("perf_title", "Now", 24, top, size=30),
               Widget("perf_recount", CARD, 796, top - 6, 204, 44, label="Recount", action=("perf_recount",), size=28)]
    lines = perf_lines(model.perf, model.shading)
    half = (len(lines) + 1) // 2
    for index, (name, value) in enumerate(lines):
        column, row = divmod(index, half)
        widgets.append(_label(f"perf_stat_{index}", f"{name}: {value}", 24 + column * 488, top + 44 + row * 36, w=480,
                              size=28))
    toggles = (("perf_compositor", "Compositor off in VR", "compositor_off_in_vr", model.compositor_off),
               ("perf_raytracing", "Raytracing off (hides glass)", "raytracing_off_in_vr", model.raytracing_off),
               ("perf_heavy", "Heavy modifiers off in VR", "hide_heavy_modifiers", model.hide_heavy),
               ("perf_shadows", "Lower shadow resolution", "lower_shadows_in_vr", model.lower_shadows),
               ("perf_transparent", "Hide transparent materials", "hide_transparent_in_vr", model.hide_transparent))
    for index, (name, label, setting, active) in enumerate(toggles):
        row, column = divmod(index, 2)
        widgets.append(Widget(name, TOGGLE, 24 + column * 496, top + 236 + row * 56, 480, 48, label=label,
                              action=("toggle", setting), active=active, size=30))
    distance = model.draw_distance or model.perf.draw_distance
    widgets += [Widget("draw_distance", SLIDER, 24, top + 404, 800, 72, label="Draw distance" if model.draw_distance
                       else "Draw distance (Blender's)", size=34, action=("slider", "draw_distance", 1.0),
                       value=distance, minimum=DRAW_DISTANCE_RANGE[0], maximum=DRAW_DISTANCE_RANGE[1], unit="m",
                       step=0.1, log=True),
                Widget("draw_distance_reset", BUTTON, 848, top + 404, 152, 72, label="Default", size=34,
                       action=("draw_distance_reset",), enabled=model.draw_distance > 0),
                _label("perf_shading_title", "Shading", 24, top + 494, w=200, size=30)]
    widgets += _row("perf_shading", SHADINGS, 240, top + 484, 760, 52, 16, lambda index, item, x, y, w, h: Widget(
        "perf_shading_" + item[0], CARD, x, y, w, h, label=item[1], action=("shading", item[0]),
        active=model.shading == item[0], size=30))
    widgets.append(_label("perf_hint", "Also lower SteamVR's render resolution for Blender (per-app setting).", 24,
                          top + 546, size=22))
    return widgets


ASSET_COLUMNS, ASSET_ROWS = 5, 2
ASSETS_PER_PAGE = ASSET_COLUMNS * ASSET_ROWS
ASSET_CHIP_SLOTS = 10               # two rows of five
TILE_THUMB = 128                    # thumbnail edge in pixels (previews are stored at this size)


def asset_tile_rect(index, top):
    """(x, y, w, h) of tile number `index` (row by row) on the Assets page."""
    width, height, gap = 184, 168, 14
    column, row = index % ASSET_COLUMNS, index // ASSET_COLUMNS
    return 24 + column * (width + gap), top + 156 + row * (height + 10), width, height


def _assets_page(model, top):
    view = model.assets
    widgets = []
    if view.libraries:
        widgets += _row("library", view.libraries, 24, top, 976, 52, 12, lambda index, name, x, y, w, h: Widget(
            f"library_{index}", CARD, x, y, w, h, label=name, action=("asset_library", index),
            active=view.library == index, size=30))
    else:
        widgets.append(_label("library_none", "No asset libraries in Preferences > File Paths.", 24, top, size=30))
    for slot, (catalog_id, label) in enumerate(view.chips[:ASSET_CHIP_SLOTS]):
        action = ("asset_chips",) if catalog_id == MORE_CHIPS else ("asset_catalog", catalog_id)
        column, row = slot % 5, slot // 5
        widgets.append(Widget(f"chip_{slot}", CARD, 24 + column * 196, top + 60 + row * 46, 184, 40, label=label,
                              action=action, active=catalog_id != MORE_CHIPS and view.catalog == catalog_id, size=24))
    for index, (key, name, kind) in enumerate(view.tiles):
        x, y, w, h = asset_tile_rect(index, top)
        widgets.append(Widget(f"asset_{index}", THUMB, x, y, w, h, label=name, action=("asset", index), size=22))
    widgets.append(Widget("asset_prev", CARD, 24, top + 516, 150, 44, label="< Prev", action=("asset_page", -1),
                          enabled=view.page > 0, size=28))
    widgets.append(_label("asset_message", view.message or f"Page {view.page + 1} of {view.pages}  ({view.total})",
                          190, top + 520, w=620, size=26))
    widgets.append(Widget("asset_next", CARD, 850, top + 516, 150, 44, label="Next >", action=("asset_page", 1),
                          enabled=view.page < view.pages - 1, size=28))
    return widgets


MORE_CHIPS = "__more__"             # chip id of the "More" chip (shows the next chips)


def page_widgets(model, top):
    if model.tab == 'selected':
        from .rig_layout import selected_page     # here: rig_layout builds on this module's widgets
        return selected_page(model.rig, top)
    if model.tab == 'assets':
        return _assets_page(model, top)
    if model.tab == 'grab':
        return _grab_page(model, top)
    if model.tab == 'modifiers':
        return _modifiers_page(model, top)
    if model.tab == 'view':
        return _view_page(model, top)
    if model.tab == 'display':
        return _display_page(model, top)
    if model.tab == 'move':
        return _move_page(model, top)
    if model.tab == 'tools':
        return _tools_page(model, top)
    if model.tab == 'performance':
        return _performance_page(model, top)
    return [_label("blurb", "Coming soon", 24, top, size=46), _label("blurb_text", BLURBS.get(model.tab, ""), 24, top + 66, size=30)]


def _tab_row(model):
    """The tab buttons, as wide as their labels (Performance is long)."""
    gap, size = 10, 28
    weights = [len(label) + 3 for _identifier, label in TABS]
    unit = (976 - gap * (len(TABS) - 1)) / sum(weights)
    widgets, x = [], 24.0
    for (identifier, label), weight in zip(TABS, weights):
        widgets.append(Widget("tab_" + identifier, TAB, x, 106, weight * unit, 56, label=label, action=("tab", identifier),
                              active=model.tab == identifier, size=size))
        x += weight * unit + gap
    return widgets


def build(model):
    """All widgets of the desk for `model`, back to front."""
    widgets = []
    widgets += _row("mode", MODES, 24, 22, 676, 70, 16, lambda index, item, x, y, w, h: Widget(
        "mode_" + item[0], MODE, x, y, w, h, label=item[1], action=("mode", item[0]), active=model.mode == item[0],
        enabled=item[0] not in model.disabled_modes))
    widgets.append(Widget("always_laser", TOGGLE, 716, 30, 284, 54, label="Lasers", action=("toggle", "always_laser"),
                          active=model.always_laser, size=30))   # top right, every tab [user]
    widgets += _tab_row(model)
    widgets += page_widgets(model, PAGE_TOP)
    # the desk top below the screen: two raised buttons and the small title
    widgets += [Widget("undo", BUTTON, 24, 786, 220, 88, label="Undo", action=("undo",), size=40),
                Widget("redo", BUTTON, 268, 786, 220, 88, label="Redo", action=("redo",), size=40),
                _label("title", "Digit's VR", 760, 818, w=240, size=24)]
    widgets += [Widget(LEFT_HANDLE, HANDLE, -86, 230, 70, 300, action=("handle",)),
                Widget(RIGHT_HANDLE, HANDLE, DESK_WIDTH + 16, 230, 70, 300, action=("handle",))]
    return widgets


def hit_test(widgets, px, py):
    """The topmost widget under a screen point, or None. Labels are not hit."""
    for widget in reversed(widgets):
        if widget.kind != LABEL and widget.contains(px, py):
            return widget
    return None


def on_screen(px, py):
    """Inside the desk body (screen + desk top)."""
    return 0 <= px <= DESK_WIDTH and 0 <= py <= DESK_HEIGHT


def slider_value(widget, px, padding=24):
    """Slider value for a pixel x (the track runs between the widget's padded edges)."""
    track_start, track_end = widget.x + padding, widget.x + widget.w - padding
    fraction = min(1.0, max(0.0, (px - track_start) / (track_end - track_start)))
    if widget.log:
        return float(f"{widget.minimum * (widget.maximum / widget.minimum) ** fraction:.2g}")   # 2 digits: 2.5, 31, 120
    value = widget.minimum + fraction * (widget.maximum - widget.minimum)
    return round(value / widget.step) * widget.step


def slider_fraction(widget):
    if widget.log:
        value = min(widget.maximum, max(widget.minimum, widget.value))
        return math.log(value / widget.minimum) / math.log(widget.maximum / widget.minimum)
    return (widget.value - widget.minimum) / (widget.maximum - widget.minimum)


def pixel_to_local(px, py):
    """Desk-local metres (scale 1) of a texture pixel: x right, y up, z out of the screen; origin at the middle of
    the whole desk."""
    return (px - DESK_WIDTH / 2) * METERS_PER_PIXEL, (DESK_HEIGHT / 2 - py) * METERS_PER_PIXEL


def local_to_pixel(x, y):
    return x / METERS_PER_PIXEL + DESK_WIDTH / 2, DESK_HEIGHT / 2 - y / METERS_PER_PIXEL


def rounded_outline(x, y, w, h, radius, segments=4):
    """Corner points (pixel space, clockwise from the top-left) of a rounded rectangle, for fans and outlines."""
    radius = min(radius, w / 2, h / 2)
    points = []
    for corner_x, corner_y, start in ((x + radius, y + radius, 180), (x + w - radius, y + radius, 270),
                                      (x + w - radius, y + h - radius, 0), (x + radius, y + h - radius, 90)):
        for step in range(segments + 1):
            angle = math.radians(start + 90.0 * step / segments)
            points.append((corner_x + radius * math.cos(angle), corner_y + radius * math.sin(angle)))
    return points


def handle_parts(widget):
    """Rects (x, y, w, h, radius) of a grip bar: the bar and two short arms joining the desk edge."""
    on_left = widget.x < 0
    edge = 0 if on_left else DESK_WIDTH
    arm_x = widget.x + widget.w - 2 if on_left else edge - 2
    arm_width = abs(edge - (widget.x + widget.w)) + 4 if on_left else widget.x - edge + 4
    return [(widget.x, widget.y, widget.w, widget.h, 22),
            (arm_x, widget.y + 36, arm_width, 30, 6), (arm_x, widget.y + widget.h - 66, arm_width, 30, 6)]
