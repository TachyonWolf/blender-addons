# SPDX-License-Identifier: GPL-3.0-or-later
"""Held items (DESIGN "Held items contract"): things you hold in VR that can sit on the tool belt (tool gun, PDA, tool
options panel). The belt talks only to this interface; an item works without the belt and never imports it."""

from mathutils import Vector

from . import settings
from .panel_layout import HANDLE_GAP, HANDLE_WIDTH

REGISTRY = {}      # name -> HeldItem (filled as items are made)


def rescale_all(pivot, old_size, new_size):
    """Your size changed about `pivot` (user_scale.set_size, with panel.rescale_all): items that keep their own world
    place follow, like panels."""
    for item in REGISTRY.values():
        item.rescale(pivot, old_size, new_size)


def move_all(world_delta):
    """The view jumped (a viewpoint Go, with panel.move_all): items that keep their own world place move with you."""
    for item in REGISTRY.values():
        item.move_by(world_delta)


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
        """Pinned to its belt slot: moving away from it snaps it back to that slot. Remembered as the setting
        `<name>_attached` (old name kept so saved settings work); set with the Attached toggle or B with the fingertip at
        its slot (the belt pins the slot, belt_state.Slot.pinned) [user, 2026-11-25]."""
        return bool(settings.current().get(self.name + "_attached", False))

    @attached.setter
    def attached(self, value):
        settings.put(self.name + "_attached", bool(value))

    def matrix(self):
        """World matrix now."""
        raise NotImplementedError

    def set_matrix(self, matrix):
        raise NotImplementedError

    def rescale(self, pivot, old_size, new_size):
        """Your size changed: an item that keeps its own world matrix moves and scales with you (a panel's state does it
        itself: nothing to do)."""

    def move_by(self, world_delta):
        """The view jumped: an item that keeps its own world matrix moves rigidly (panels: nothing to do)."""

    def dock_bounds(self):
        """(low, high) corners of the box that must fit inside a belt slot, in the item's own space at scale 1 (metres). The
        belt shrinks the item so the longest side fills the slot and its middle sits at the slot's middle. Override."""
        return Vector((-0.05,) * 3), Vector((0.05,) * 3)

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

    def dock_bounds(self):
        """The body and its handles (both sides; the top one if the panel has it), flat."""
        spec, reach = self.panel.spec, HANDLE_WIDTH + HANDLE_GAP
        left, right = spec.pixel_to_local(-reach, 0)[0], spec.pixel_to_local(spec.width + reach, 0)[0]
        bottom, top = spec.pixel_to_local(0, spec.height)[1], spec.pixel_to_local(0, -reach if self.panel.resize_handle else 0)[1]
        return Vector((left, bottom, 0.0)), Vector((right, top, 0.0))

    def entered_belt(self):
        self.panel.state.docked = True

    def left_belt(self):
        self.panel.state.docked = False
        self.panel.remember()       # its full-size place (the docked size must never be what is saved)
