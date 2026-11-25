# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool gun (DESIGN "Tool gun"): a held item you take with the grip, and its menu. Gun and menu are one rigid thing
with ONE transform, the menu's PanelState (so your size, viewpoints and the remembered place work like every panel): the
gun hangs beside it. Menu open = the gun is out; only a gun placed by someone else (the belt) is shown without its menu,
until you take it. Held, its barrel lies on the hand's laser."""
import math

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import gun_layout as layout, gun_shots, gun_tools, hide, settings
from .action_map import HANDS, buzz
from .gun_state import STATE
from .hands import HandPose
from .held_item import HeldItem
from .panel import Panel
from .panel_state import TOUCH_REACH

BOX_MIN, BOX_MAX = Vector((-0.02, -0.11, -0.16)), Vector((0.02, 0.03, 0.06))       # the gun in its own space (m)
MENU_GAP, MENU_BACK, MENU_TURN = 0.06, 0.05, math.radians(15.0)
HIDDEN, MATERIALS = 'HIDE', 'MATERIAL'
SIDES = {'LEFT': -1.0, 'RIGHT': 1.0}


def _menu_offset(place):
    """The menu's place in the gun's space: on its left or right, turned a little towards you, or centred right behind it
    (above the hand)."""
    width, height = (size * layout.SPEC.meters_per_pixel for size in (layout.SPEC.width, layout.SPEC.height))
    if place == 'BEHIND':
        return Matrix.Translation((0.0, height / 2 + BOX_MAX.y + 0.01, BOX_MAX.z + 0.02))
    side = SIDES[place]
    return Matrix.Translation((side * (width / 2 + MENU_GAP), 0.04, MENU_BACK)) @ Matrix.Rotation(-side * MENU_TURN, 4, 'Y')


OFFSETS = {place: _menu_offset(place) for place, _label in layout.MENU_PLACES}
INVERSES = {place: offset.inverted() for place, offset in OFFSETS.items()}


class ToolGun(HeldItem):
    name = "tool_gun"
    home_on_belt = True
    follows_hand = True          # the belt does not carry it: it snaps to the hand by itself

    def __init__(self):
        super().__init__()
        self.docked = False
        self.shown, self.stowed = False, True

    def matrix(self):
        return PANEL.state.matrix() @ INVERSES[settings.get("tool_gun_menu")]

    def _place(self, matrix):
        PANEL.state.set_matrix(matrix @ OFFSETS[settings.get("tool_gun_menu")])
        PANEL.state.placed = True

    def set_matrix(self, matrix):
        """Someone else (the belt) places it: the menu stays away until you take the gun."""
        self._place(matrix)
        if self.docked and PANEL.state.open and self.held_by is None:
            PANEL.hide_menu()

    def entered_belt(self):
        """In a belt slot: the gun shows there, its menu stays away."""
        self.docked, self.shown, self.stowed = True, True, False
        if PANEL.state.open:
            PANEL.hide_menu()

    def left_belt(self):
        """Out of its slot. Not taken by a hand or the desk button (the belt stopped): put away."""
        was_docked, self.docked = self.docked, False
        if was_docked and self.held_by is None:
            super().stow()

    def grip_hit(self, position):
        if not self.shown or self.held_by is not None:
            return False
        matrix = self.matrix()
        local, reach = matrix.inverted_safe() @ Vector(position), TOUCH_REACH * PANEL.state.size / matrix.median_scale
        return all(low - reach <= value <= high + reach for low, value, high in zip(BOX_MIN, local, BOX_MAX))

    def on_grab(self, hand):
        super().on_grab(hand)
        self.docked = False
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
        """Held: the barrel on the laser, at the hand."""
        pose = HandPose(context, state, self.held_by, with_grip_rotation=False)
        along = (pose.grip_location - pose.aim_location).dot(pose.aim_direction)
        rotation = Quaternion(state.controller_aim_rotation_get(context, HANDS.index(self.held_by)))
        self._place(Matrix.LocRotScale(pose.aim_location + pose.aim_direction * along, rotation,
                                       (PANEL.state.scale,) * 3))

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
                  copying=STATE.pending is not None, menu_place=settings.get("tool_gun_menu"))
    if tool == HIDDEN:
        names, page, pages, total, _can_hide = hide.view(context)
        fields.update(names=names, page=page, pages=pages, total=total)
    elif tool == MATERIALS:
        names, STATE.material_page, pages = hide.page_of(gun_tools.material_names(), STATE.material_page)
        fields.update(names=names, page=STATE.material_page, pages=pages, material=STATE.material, eyedrop=STATE.eyedrop)
    return layout.GunModel(**fields)


def _next_menu_place():
    """Left, right, behind: the menu moves, the gun stays where it is."""
    matrix, places = GUN.matrix(), [place for place, _label in layout.MENU_PLACES]
    settings.put("tool_gun_menu", places[(places.index(settings.get("tool_gun_menu")) + 1) % len(places)])
    GUN._place(matrix)


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
    elif kind == "gun_menu":
        _next_menu_place()
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

    def close(self):
        """The desk's Tool gun button near the gun: put it away."""
        GUN.stow()

    def hide_menu(self):
        super().close()

    def teardown(self):
        super(ToolGun, GUN).stow()            # (not GUN.stow: the remembered open state stays)
        gun_shots.clear()
        super().teardown()

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
