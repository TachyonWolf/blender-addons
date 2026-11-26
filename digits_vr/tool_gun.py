# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool gun (DESIGN "Tool gun"): a held item you take with the grip, and its menu. The GUN owns the transform: its
scale is always Your size (times the belt's fit while docked), whatever size you give the menu. The menu is the gun's
matrix times `offset` (its place, turn and size in the gun's space: what Edit changes and what is saved). Menu open = the
gun is out; only a gun placed by someone else (the belt) is shown without its menu, until you take it. Held, its grip sits
in the drawn hand's closed fist (hands.drawn_hand_pose, hand_model.fist_centre) with the barrel forward along the aim."""
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import gun_layout as layout, gun_shots, gun_tools, hand_model, hide, scale_math, settings
from .action_map import HANDS, LEFT, buzz
from .gun_state import STATE
from .hands import HandPose, drawn_hand_pose
from .held_item import HeldItem
from .panel import Panel
from .panel_state import TOUCH_REACH
from .size_state import SIZE

# The gun in its own space (metres at Your size 1; -Z = where it aims, +Y = up): (name, min corner, max corner).
# The grip is about a palm wide (8 cm) [user, 2026-11-26: "the grip is too long"].
PARTS = (('body', (-0.016, -0.018, -0.12), (0.016, 0.022, 0.05)),
         ('grip', (-0.012, -0.098, 0.016), (0.012, -0.018, 0.044)),
         ('muzzle', (-0.009, -0.009, -0.16), (0.009, 0.009, -0.12)))
BOX_MIN = Vector([min(low[axis] for _name, low, _high in PARTS) for axis in range(3)])
BOX_MAX = Vector([max(high[axis] for _name, _low, high in PARTS) for axis in range(3)])
GRIP_CENTRE = next((Vector(low) + Vector(high)) / 2 for name, low, high in PARTS if name == 'grip')


def hold_offset(hand):
    """The gun in the drawn hand's space (grip location, aim turn, metres at size 1): its grip's middle in the closed fist,
    barrel forward along the aim, up = the thumb side. Same axes as the gun, so no turn."""
    return Matrix.Translation(Vector(hand_model.fist_centre(-1.0 if hand == LEFT else 1.0)) - GRIP_CENTRE)


def proper(matrix, scale):
    """`matrix` with its rotation kept and a positive uniform `scale`: never mirrored, never squashed."""
    location, rotation, _scale = matrix.decompose()
    return Matrix.LocRotScale(location, rotation.normalized(), (abs(scale),) * 3)
MENU_GAP, MENU_BACK, MENU_TURN = 0.06, 0.05, math.radians(15.0)
HIDDEN, MATERIALS = 'HIDE', 'MATERIAL'
SIDES = {'LEFT': -1.0, 'RIGHT': 1.0}


def _default_offset():
    """The menu's place in the gun's space: on its left, turned a little towards you."""
    width = layout.SPEC.width * layout.SPEC.meters_per_pixel
    return Matrix.Translation((-(width / 2 + MENU_GAP), 0.04, MENU_BACK)) @ Matrix.Rotation(MENU_TURN, 4, 'Y')


DEFAULT_OFFSET = _default_offset()
OFFSET_SCALE_RANGE = (0.5, 2.5)         # the menu's size against the gun's


def facing_back(offset):
    """The menu's front must face the gun's back (+Z: towards you while you aim): an Edit turn that left it facing
    forward is turned round about the menu's own up axis, so you never read it from behind."""
    if (offset.to_3x3() @ Vector((0.0, 0.0, 1.0))).z >= 0.0:
        return offset
    return offset @ Matrix.Rotation(math.pi, 4, 'Y')


OFFSET_VERSION = 2.0          # saved after the scale: 2 = the gun owns the transform (2026-11-26); none = the menu did


def offset_to_list(offset):
    location, rotation, scale = offset.decompose()
    return [*location, *rotation, abs(scale.x), OFFSET_VERSION]


def offset_from_list(values, menu_size=1.0):
    """A saved offset (location, quaternion, scale[, version]), or the default for an empty list. An old one (no version)
    was saved while the gun's size came from the menu's: the menu keeps the size it had relative to you (`menu_size`, its
    saved scale) and its distance from the gun grows with it, so it hangs about where you left it."""
    if not values:
        return DEFAULT_OFFSET.copy()
    location, rotation, scale = Vector(values[:3]), Quaternion(values[3:7]).normalized(), abs(values[7]) or 1.0
    if len(values) < 9:
        new_scale = _clamp_offset_scale(menu_size)
        location, scale = location * (new_scale / scale), new_scale
    return Matrix.LocRotScale(location, rotation, (_clamp_offset_scale(scale),) * 3)


def _clamp_offset_scale(scale):
    return min(OFFSET_SCALE_RANGE[1], max(OFFSET_SCALE_RANGE[0], scale))


class ToolGun(HeldItem):
    name = "tool_gun"
    home_on_belt = True
    follows_hand = True          # the belt does not carry it: it snaps to the hand by itself

    def __init__(self):
        super().__init__()
        self.docked = False
        self.shown, self.stowed = False, True
        self.world = Matrix.Identity(4)
        self.set_offset(DEFAULT_OFFSET)

    def set_offset(self, offset):
        """The menu's place in the gun's space (location, turn, and its size against the gun's), never mirrored."""
        self.offset = proper(offset, offset.median_scale)
        self.offset_inverse = self.offset.inverted()

    def matrix(self):
        return self.world

    def _scale_for(self, matrix):
        """Docked: the belt's fit. Anywhere else: Your size, whatever was asked."""
        return matrix.median_scale if self.docked and self.held_by is None else SIZE.factor

    def _place(self, matrix):
        """The gun goes to `matrix` (its scale fixed by `_scale_for`); the menu follows at `offset`."""
        self.world = proper(matrix, self._scale_for(matrix))
        PANEL.state.set_matrix(self.world @ self.offset)
        PANEL.state.placed = True

    def follow_menu(self):
        """The menu was placed by the panel code (opened in front of you, called, loaded): the gun comes to it."""
        self._place(PANEL.state.matrix() @ self.offset_inverse)

    def rescale(self, pivot, old_size, new_size):
        self.world = scale_math.rescale_matrix(self.world, pivot, old_size, new_size)

    def move_by(self, world_delta):
        location, rotation, _scale = (world_delta @ self.world).decompose()
        self.world = Matrix.LocRotScale(location, rotation.normalized(), (self.world.median_scale,) * 3)

    def reset_offset(self):
        """Edit's Reset: the menu goes back to its usual place beside the gun."""
        matrix = self.matrix()
        self.set_offset(DEFAULT_OFFSET)
        self._place(matrix)

    def keep_gun_still(self, gun_matrix):
        """A handle moved the menu: the gun stays where it was, so the menu's place in the gun's space changes."""
        local = gun_matrix.inverted_safe() @ PANEL.state.matrix()
        self.set_offset(facing_back(proper(local, _clamp_offset_scale(local.median_scale))))
        self._place(gun_matrix)

    def set_matrix(self, matrix):
        """Someone else (the belt) places it: the menu stays away until you take the gun."""
        self._place(matrix)
        if self.docked and PANEL.state.open and self.held_by is None:
            PANEL.hide_menu()

    def dock_bounds(self):
        return BOX_MIN, BOX_MAX

    def entered_belt(self):
        """In a belt slot: the gun shows there, its menu stays away."""
        self.docked, self.shown, self.stowed = True, True, False
        PANEL.state.docked = True           # its transform may be tiny there (no size clamp)
        if PANEL.state.open:
            PANEL.hide_menu()

    def left_belt(self):
        """Out of its slot. Not taken by a hand or the desk button (the belt stopped): put away."""
        was_docked, self.docked = self.docked, False
        PANEL.state.docked = False
        if was_docked and self.held_by is None:
            super().stow()

    def grip_hit(self, position):
        if not self.shown or self.held_by is not None:
            return False
        matrix = self.matrix()
        local, reach = matrix.inverted_safe() @ Vector(position), TOUCH_REACH * SIZE.factor / matrix.median_scale
        return all(low - reach <= value <= high + reach for low, value, high in zip(BOX_MIN, local, BOX_MAX))

    def on_grab(self, hand):
        super().on_grab(hand)
        self.docked = False
        PANEL.state.docked = False
        self.shown, self.stowed = True, False
        matrix = self.matrix()
        self._place(matrix)
        if not PANEL.state.open:
            PANEL.open(bpy.context, None, remember=False)

    def on_release(self, hand):
        if self.held_by != hand:
            return
        super().on_release(hand)
        gun_shots.let_go()
        PANEL.remember()

    def follow(self, context, state):
        """Held: the grip in the drawn hand's fist (the same pose the simple hand is drawn with), barrel forward."""
        location, rotation = drawn_hand_pose(context, state, HANDS.index(self.held_by))
        self._place(Matrix.LocRotScale(location, rotation, (SIZE.factor,) * 3) @ hold_offset(self.held_by))

    def stow(self):
        """Put away: its home is the belt; with no belt it is just gone."""
        super().stow()
        gun_shots.clear()
        if PANEL.state.open:
            PANEL.hide_menu()


def grip_pressed(context, state, hand):
    """A grip press near the gun takes it. True when it did."""
    if not GUN.shown or not GUN.grip_hit(HandPose(context, state, hand, with_grip_rotation=False).grip_location):
        return False
    GUN.on_grab(hand)
    GUN.follow(context, state)
    buzz(context, state, hand, duration=0.02, amplitude=0.3)
    return True


def grip_released(hand):
    if GUN.held_by == hand:
        GUN.on_release(hand)


def tool_label():
    return layout.TOOL_LABELS[settings.get("tool_gun_tool")]


def build_model(context):
    tool = settings.get("tool_gun_tool")
    fields = dict(tool=tool, note=STATE.note, warn=STATE.warn, channels=tuple(settings.get("tool_gun_reset")),
                  copying=STATE.pending is not None, editing=settings.get("tool_gun_edit"))
    if tool == HIDDEN:
        names, page, pages, total, _can_hide = hide.view(context)
        fields.update(names=names, page=page, pages=pages, total=total)
    elif tool == MATERIALS:
        names, STATE.material_page, pages = hide.page_of(gun_tools.material_names(), STATE.material_page)
        fields.update(names=names, page=STATE.material_page, pages=pages, material=STATE.material, eyedrop=STATE.eyedrop)
    return layout.GunModel(**fields)


def _toggle_edit():
    """Edit on: the menu shows two handles. Off: they go and the menu is locked to the gun."""
    editing = not settings.get("tool_gun_edit")
    settings.put("tool_gun_edit", editing)
    if not editing:
        PANEL.state.grabs.clear()
        PANEL.two_hand = None


def _pick_tool(tool):
    gun_shots.let_go()                   # a running hold belongs to the old tool
    STATE.drop_pending()
    settings.put("tool_gun_tool", tool)


def _pick_channel(context, channel):
    """A press lights only that channel; with A held it is added / removed (one always stays)."""
    lit = settings.get("tool_gun_reset")
    if not gun_shots.toggle_held(context):
        lit = [channel]
    elif channel not in lit:
        lit = [*lit, channel]
    else:
        lit = [other for other in lit if other != channel] or lit
    settings.put("tool_gun_reset", list(lit))


def perform(context, widget):
    if not widget.enabled or not widget.action:
        return False
    kind, *arguments = widget.action
    if kind == "unhide_all":
        return hide.unhide_all(context)
    if kind == "unhide_one":
        return hide.unhide_one(context, arguments[0])
    if kind == "hide_page":
        return hide.turn_page(arguments[0])
    if kind == "gun_tool":
        _pick_tool(arguments[0])
    elif kind == "gun_reset":
        _pick_channel(context, arguments[0])
    elif kind == "gun_edit":
        _toggle_edit()
    elif kind == "gun_edit_reset":
        GUN.reset_offset()
        PANEL.remember()
    elif kind == "gun_copy_reset":
        STATE.drop_pending()
    elif kind == "gun_eyedrop":
        STATE.eyedrop = not STATE.eyedrop
    elif kind == "gun_material":
        STATE.material, STATE.eyedrop = arguments[0], False
    elif kind == "gun_material_page":
        STATE.material_page = max(0, STATE.material_page + arguments[0])
    else:
        return False
    return True


class GunPanel(Panel):
    name = "tool_gun"
    spec = layout.SPEC
    pinnable = False            # the menu hangs beside the gun
    open_side = 0.0
    open_drop = 0.2

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget)

    def open(self, context, state, remember=True):
        GUN.shown, GUN.stowed, GUN.docked = True, False, False
        super().open(context, state, remember)
        if GUN.held_by is None:
            GUN.follow_menu()           # opened in front of you (or where it was): the gun comes along

    def bring_to_you(self, state):
        super().bring_to_you(state)
        if GUN.held_by is None:
            GUN.follow_menu()

    def close(self):
        """The desk's Tool gun button near the gun: put it away."""
        GUN.stow()

    def hide_menu(self):
        super().close()

    def teardown(self):
        super(ToolGun, GUN).stow()            # (not GUN.stow: the remembered open state stays)
        gun_shots.clear()
        super().teardown()

    def remembered(self):
        return {"tool_gun_offset": offset_to_list(GUN.offset)}

    def load(self):
        settings.put("tool_gun_edit", False)            # Edit starts off each session (the place stays) [user, 2026-11-26]
        GUN.set_offset(offset_from_list(settings.get("tool_gun_offset"), self.state.scale / self.state.size))
        GUN.follow_menu()

    def _drag(self, context, state):
        """A handle moves the menu, not the gun: the change goes into the menu's place in the gun's space."""
        if not self.state.grabs:
            return
        if GUN.held_by is not None:
            GUN.follow(context, state)
        gun_matrix = GUN.matrix()
        super()._drag(context, state)
        GUN.keep_gun_still(gun_matrix)
        if not self.state.grabs:
            self.remember()                     # (the let-go save came before the offset was updated)

    def update(self, context, state):
        if GUN.held_by is not None:
            GUN.follow(context, state)

    def draw(self, new_frame):
        state = bpy.context.window_manager.xr_session_state if new_frame and GUN.held_by is not None else None
        if state is not None:
            GUN.follow(bpy.context, state)
        super().draw(new_frame)


GUN = ToolGun()
PANEL = GunPanel()
