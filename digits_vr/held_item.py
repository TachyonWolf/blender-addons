# SPDX-License-Identifier: GPL-3.0-or-later
"""Held items (DESIGN "Held items contract"): things you hold in VR that can sit on the tool belt (tool gun, PDA, tool
options panel). The belt talks only to this interface; an item works without the belt and never imports it."""

from . import settings

REGISTRY = {}      # name -> HeldItem (filled as items are made)


def held_in(hand):
    """The item this hand holds, or None."""
    return next((item for item in REGISTRY.values() if item.held_by == hand), None)


class HeldItem:
    name = ""
    follows_hand = False       # it places itself in the hand: the belt hands it over and does not carry it
    home_on_belt = False       # docked in a belt slot at session start (the tool gun) [user, 2026-11-25]

    def __init__(self):
        self.held_by, self.shown = None, True
        self.stowed = False        # put away: a belt may dock it (set_matrix, shown = True); without a belt it stays hidden
        REGISTRY[self.name] = self

    @property
    def attached(self):
        """Locked to the belt: moving away from it snaps it back. Remembered as the setting `<name>_attached`; set with
        the Attached toggle or B with the fingertip at its slot [user, 2026-11-25]."""
        return bool(settings.current().get(self.name + "_attached", False))

    @attached.setter
    def attached(self, value):
        settings.put(self.name + "_attached", bool(value))

    def matrix(self):
        """World matrix now."""
        raise NotImplementedError

    def set_matrix(self, matrix):
        raise NotImplementedError

    def stow(self):
        """Put it away (its button, or a belt it is dropped on)."""
        self.held_by, self.shown, self.stowed = None, False, True

    def grip_hit(self, position):
        """Can a grip at this world position take it?"""
        return False

    def on_grab(self, hand):
        self.held_by = hand

    def on_release(self, hand):
        if self.held_by == hand:
            self.held_by = None


class PanelHeldItem(HeldItem):
    """A HeldItem backed by a Panel (`self.panel`): held while one of its handles is held, or while the belt carries it; no
    laser or poke input while docked (`left_belt` / `entered_belt` are the optional hooks the belt calls)."""
    panel = None
    _carried_by = None

    @property
    def held_by(self):
        return next(iter(self.panel.state.grabs), self._carried_by)

    @held_by.setter
    def held_by(self, hand):
        self._carried_by = hand

    def matrix(self):
        return self.panel.state.matrix()

    def entered_belt(self):
        self.panel.state.docked = True

    def left_belt(self):
        self.panel.state.docked = False
        self.panel.remember()       # its full-size place (the docked size must never be what is saved)
