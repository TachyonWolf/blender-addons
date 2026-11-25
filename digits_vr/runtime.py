# SPDX-License-Identifier: GPL-3.0-or-later
"""The live state of one VR session (data only; session.py starts and tears it down). Everything here is dropped
by the central teardown, so nothing outlives the session."""
from dataclasses import dataclass, field

from .action_map import HANDS
from .picking import SceneCache


@dataclass
class HandState:
    laser_on: bool = False
    laser_target: object = None     # picking.Target or None
    touch_target: object = None
    last_pose: tuple = None         # (location, direction) at the last hover check
    touch_next: bool = False        # both hover picks wanted: which one runs next (they take turns)
    pending: list = field(default_factory=list)   # hover pick parts still to run: (kind, part, pose)
    partial: object = None          # the SURFACE half of a pick spread over two ticks (hover.py)
    trigger_amount: float = 0.0     # polled once per tick by controls.py, read by hover.py
    grip_amount: float = 0.0
    trigger_touched: bool = False
    trigger_down: bool = False
    grip_down: bool = False
    grab: object = None             # tools.Grab while the grip holds something (both hands: the same Grab)
    edit_hover_version: int = -1
    edit_hover_tick: int = -99      # session tick of this hand's last Edit hover pick
    edit_hover: object = None       # (element, index) of the Edit mode element this hand points at / touches
    gesture: object = None          # router.SelectGesture while A + trigger is held (decided at the release)
    pulse_key: object = None        # what this hand's laser / touch / Edit hover pointed at last (haptics: a change pulses)
    empty_grip: bool = False        # the grip is down on nothing (both hands = the size gesture)

    @property
    def grabbing(self):
        return self.grab is not None


@dataclass
class Runtime:
    active: bool = False
    generation: int = 0             # bumped by undo / redo / teardown: running grabs see it and stop
    scene_updates: int = 0          # depsgraph updates seen (session.on_depsgraph_update): views rebuilt on change
    hands: dict = field(default_factory=lambda: {hand: HandState() for hand in HANDS})
    cache: SceneCache = field(default_factory=SceneCache)
    grabbed: set = field(default_factory=set)   # Target keys being dragged (each item in one grab at most)
    fine_down: bool = False         # B held (fine control toggles on the press)
    ticks: int = 0
    frame: int = 0                  # headset frames drawn (counted by overlay.draw); drags apply once per frame
    last_pick_frame: int = -1       # hover picks at most once per frame
    draw_handle: object = None
    problems: list = field(default_factory=list)  # action map problems of this session (shown in the panel)

    def reset_hands(self):
        self.hands = {hand: HandState() for hand in HANDS}
        self.grabbed.clear()
        self.fine_down = False


RUNTIME = Runtime()
