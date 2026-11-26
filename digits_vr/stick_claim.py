# SPDX-License-Identifier: GPL-3.0-or-later
"""A hand's thumbstick scrolls a list instead of moving you while that hand's laser points at the list (DESIGN "Taller desk and
scroll bars"). The one place that decides it: panels.tick calls `update` once per session tick, move.py asks `blocked(hand)`.
Pointing = the laser is on a list with a scroll bar (panel.list_under_laser). When the laser leaves, the stick stays blocked
until it has come back to the centre, so a push held from scrolling never starts moving you. Costs nothing while no hand points
at a list and none is locked (no stick read)."""
import time
from dataclasses import dataclass

from . import move_math, settings
from .action_map import HANDS, vector

ROWS_PER_SECOND = 6.0           # a list that shows several rows: full tilt scrolls this many rows a second
FLICK_ON, FLICK_OFF = 0.6, 0.3  # a paged list: one page per flick past FLICK_ON; the stick must drop below FLICK_OFF to flick again


@dataclass
class HandClaim:
    pointing: bool = False       # the laser is on a list now
    locked: bool = False         # it left, but the stick has not come back to the centre yet
    carry: float = 0.0           # rows not yet scrolled (fractions add up)
    flicked: bool = False        # a paged list already turned for this push
    last_time: float = 0.0


CLAIMS = {hand: HandClaim() for hand in HANDS}


def reset():
    for hand in HANDS:
        CLAIMS[hand] = HandClaim()


def blocked(hand):
    """move.py: this hand's stick scrolls a list (or has not rested since), so it must not move you."""
    claim = CLAIMS[hand]
    return claim.pointing or claim.locked


def steps_for(claim, tilt, visible, seconds):
    """Whole list positions to move for a stick tilt (-1 .. 1, up = towards the start of the list = negative): a list that
    shows several rows scrolls at a rate that follows the tilt; a paged list (visible 1) turns one page per flick."""
    if visible > 1:
        claim.carry += -tilt * ROWS_PER_SECOND * seconds
        whole = int(claim.carry)
        claim.carry -= whole
        return whole
    if abs(tilt) < FLICK_OFF:
        claim.flicked = False
    elif abs(tilt) >= FLICK_ON and not claim.flicked:
        claim.flicked = True
        return -1 if tilt > 0 else 1
    return 0


def update(context, state, open_panels):
    """Once per session tick (panels.tick, after the lasers moved)."""
    now = time.perf_counter()
    for hand in HANDS:
        claim = CLAIMS[hand]
        found = None
        if open_panels and not settings.get("paused"):
            for panel in open_panels:
                bar = panel.list_under_laser(hand)
                if bar is not None:
                    found = (panel, bar)
                    break
        if found is None and not claim.pointing and not claim.locked:
            continue
        raw = vector(context, state, "stick", hand)
        if found is None:
            if claim.pointing:                  # the laser left the list: wait for the stick to rest
                claim.pointing, claim.locked = False, True
            if move_math.stick_with_dead_zone(*raw) == (0.0, 0.0):
                claim.locked = False
            claim.carry, claim.flicked = 0.0, False
            continue
        if not claim.pointing:
            claim.pointing, claim.locked, claim.carry, claim.last_time = True, False, 0.0, now
        panel, bar = found
        seconds, claim.last_time = min(now - claim.last_time, 0.1), now
        steps = steps_for(claim, move_math.stick_with_dead_zone(*raw)[1], bar.visible, seconds)
        if steps:
            panel.stick_scroll(context, bar, steps)
