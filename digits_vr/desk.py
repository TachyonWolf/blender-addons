# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk: the main floating panel (panel.Panel) and its own buttons. Runs inside the session tick (panels.tick):
- the right stick click (open / call / close) and the left undo / redo buttons (Touch: X / Y; Index: A / B), polled even when closed;
- the screen (desk_layout, desk_actions), the Assets page's thumbnails (grip or laser drag), the rig sliders' undo.
The laser, trigger presses, sliders and the two handles are the shared panel machinery (panel.py)."""

from . import asset_draw, outliner_drag, help_art, asset_page, desk_actions, pda, desk_layout as layout, rig_tab, router, settings
from . import panel_layout
from .action_map import LEFT, RIGHT, buzz, value
from .desk_state import DESK
from .panel import Panel
from .runtime import RUNTIME

BUTTON_POLL_TICKS = 2          # stick click and D-pad are polled every other tick (~15 Hz)
_state = {"undo_down": False, "redo_down": False}


class DeskPanel(Panel):
    name = "desk"
    spec = layout.SPEC
    resize_handle = panel_layout.TOP_HANDLE        # drag it up or down: the desk grows to 3 x its height [user, 2026-11-25]

    def build_model(self, context):
        return desk_actions.build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return desk_actions.perform(context, widget, pixel_x)

    def body_rects(self):
        return layout.body_rects(DESK.extra)

    def resize_to(self, context, height):
        return self.set_extra(context, height - layout.DESK_HEIGHT)

    def set_extra(self, context, wanted):
        """Make the desk `wanted` pixels taller than normal (rounded to a step, kept within 0 .. 3 x). True when it changed.
        The texture is made again only when a step is crossed (a new offscreen each frame would churn the GPU)."""
        extra = layout.clamp_extra(wanted)
        if extra == DESK.extra and self.spec is layout.spec_for(extra):
            return False
        DESK.extra = extra
        self.spec = DESK.spec()
        self.renderer.set_spec(self.spec)
        if context is not None:         # (at session start the panel's own open() builds the screen)
            self.refresh(context, force=True)
        return True

    def refresh(self, context, force=False):
        if force:                       # a press changed something: read the model again (desk_actions gate)
            desk_actions.forget_model()
        super().refresh(context, force)

    def load(self):
        tab = settings.get("desk_tab")
        DESK.tab = layout.OLD_TABS.get(tab, tab)       # a tab from before the redesign opens its new home
        DESK.options_last = DESK.tab if DESK.tab in layout.OPTION_IDS else 'move'
        DESK.selected_sub = 'mods' if tab == 'modifiers' else 'rig'
        DESK.popup, DESK.grab_more = "", False
        self.set_extra(None, settings.get("desk_extra"))

    def remembered(self):
        return {"desk_tab": DESK.tab, "desk_extra": DESK.extra}

    def take_trigger(self, context, state, hand, widget):
        if pda.take_pick(context, widget):         # a PDA slot waits for a control: this press is its link
            return True
        if DESK.tab == 'outliner' and outliner_drag.press(context, state, hand, widget.id, self.model.workspace_rows):
            return True                # an object's name: a drag to reparent
        # a laser drag of a thumbnail: it drops where the laser points
        return widget.kind == layout.THUMB and DESK.tab == 'assets' and asset_page.trigger_pressed(context, state, hand, widget.id)

    def take_grip(self, context, state, hand, matrix):
        # a thumbnail follows the hand (checked before the handles: tiles sit near them)
        return DESK.tab == 'assets' and asset_page.grip_pressed(context, state, hand, matrix, DESK.hover.get(hand))

    def trigger_released(self, context):
        rig_tab.released(context)       # a rig slider drag: one undo step at the release

    def update(self, context, state):
        asset_page.update_drag(context, state, DESK.matrix())
        if outliner_drag.drag() is not None and outliner_drag.update(context, state, self.model.workspace_rows):
            self.refresh(context, force=True)

    def draw_extra(self, new_frame):
        asset_draw.draw_drag(new_frame)

    def closed(self):
        DESK.popup = ""
        outliner_drag.cancel()
        asset_page.close()
        asset_draw.free()
        help_art.free()

    def teardown(self):
        super().teardown()
        rig_tab.forget()


PANEL = DeskPanel(DESK)


def reset_buttons():
    _state.update(undo_down=False, redo_down=False, ticks=0)


def right_click(context, state):
    """A right stick click on its own (sticks.py decides: a two-stick hold is not one)."""
    PANEL.toggle(context, state)
    buzz(context, state, RIGHT, duration=0.02, amplitude=0.4)


def reset(context, state):
    """The failsafe: the desk open, in front of you, at its normal size."""
    DESK.scale = DESK.size
    PANEL.set_extra(context, 0)
    DESK.clear_live()
    PANEL.open(context, state)


def _history_buttons(context, state):
    for name, redo in (("undo", False), ("redo", True)):
        _state[name + "_down"], pressed, _released = router.button_edge(_state[name + "_down"],
                                                                         value(context, state, name + "_button", LEFT))
        if pressed and not desk_actions.history(context, redo):
            buzz(context, state, LEFT)


def poll_buttons(context, state):
    """Every tick, open or closed: three action reads every other tick keep the idle cost down."""
    if RUNTIME.ticks % BUTTON_POLL_TICKS == 0:     # even ticks, with the stick clicks; move.py polls on the odd ones
        _history_buttons(context, state)


def register():
    desk_actions.register()


def unregister():
    desk_actions.unregister()
