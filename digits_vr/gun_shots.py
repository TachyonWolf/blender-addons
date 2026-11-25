# SPDX-License-Identifier: GPL-3.0-or-later
"""Firing the tool gun: a trigger pull is one shot of the chosen tool, ONE undo step when it changed something. Place
goes on while the trigger is held. Undo / redo drops a running hold and a first shot (its data is stale); a mode change
keeps the hold (one step) and drops the first shot; Pause, letting go and the session end finish it (end)."""
from . import gun_tools, router
from .action_map import RIGHT, buzz, value
from .gun_state import STATE, Measured
from .gun_targets import Refused, Shot
from .hands import HandPose
from .runtime import RUNTIME
from .tools import push_undo


def picks_bones(context):
    """The chosen tool points at bones now (hover.py shows the same)."""
    return gun_tools.current().bones and router.mode_kind(context.mode) == router.POSE


def _drop_stale(context):
    pending = STATE.pending
    if pending and gun_tools.current().keeps_pick and pending.mode == context.mode:
        return
    if pending and (pending.generation != RUNTIME.generation or pending.mode != context.mode):
        STATE.drop_pending()


def press(context, state, hand):
    """The trigger of the hand that holds the gun."""
    if STATE.hold is not None:
        return
    _drop_stale(context)
    tool = gun_tools.current()
    try:
        if router.mode_kind(context.mode) not in tool.modes:
            raise Refused("This tool does not work in this mode")
        STATE.say("")
        result = tool.shoot(context, Shot(hand, HandPose(context, state, hand)))
    except Refused as refusal:
        STATE.say(str(refusal), warn=True)
        buzz(context, state, hand)
        return
    buzz(context, state, hand, duration=0.02, amplitude=0.4)
    if isinstance(result, str):
        if result:
            push_undo(result)
        return
    STATE.hold, STATE.hold_hand = result, hand
    STATE.hold_generation, STATE.hold_mode, STATE.last_frame = RUNTIME.generation, context.mode, RUNTIME.frame


def release(hand):
    """A trigger let go."""
    if STATE.hold is not None and STATE.hold_hand == hand:
        _finish_hold(commit=True)


def _finish_hold(commit):
    hold, STATE.hold = STATE.hold, None
    if hold is None:
        return
    message = hold.finish()
    if commit and message and STATE.hold_generation == RUNTIME.generation:
        push_undo(message)


def update(context, state):
    """Once per tick. True while a hold runs (the timer then runs every frame)."""
    if STATE.hold is None:
        return False
    if STATE.hold_generation != RUNTIME.generation:
        _finish_hold(commit=False)
        return False
    if STATE.hold_mode != context.mode:
        _finish_hold(commit=True)
        return False
    if STATE.last_frame != RUNTIME.frame:
        STATE.last_frame = RUNTIME.frame
        STATE.hold.update(context, HandPose(context, state, STATE.hold_hand))
    return True


def end(commit):
    """Pause, the session end: finish the running hold, forget the first shot."""
    _finish_hold(commit)
    STATE.drop_pending()


def let_go():
    """The gun left the hand: a running hold is kept; the first shot stays (pick the gun up again and go on)."""
    _finish_hold(commit=True)


def clear():
    """The gun is put away or the session is over: the measurement goes too."""
    end(commit=True)
    STATE.measure(Measured())


def toggle_held(context):
    """A held (menu: add to what is lit)."""
    state = context.window_manager.xr_session_state
    return state is not None and value(context, state, "toggle", RIGHT) > 0.5
