# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool belt's live state (data only; belt.py runs it). Dropped by the belt's teardown: nothing here is saved."""
from dataclasses import dataclass, field

from mathutils import Matrix, Vector

from . import belt_math, settings
from .body_frame import BODY
from .size_state import SIZE


@dataclass
class Slot:
    index: int
    item: object = None            # a held_item.HeldItem docked here
    floating: Matrix = None        # that item's matrix before it docked (put back when it leaves)
    last_set: Matrix = None        # the matrix the belt gave it last (when it differs, someone else moved it)
    pocket: str = ""               # name_full of the model pocketed here (shrunk, in the slot)
    original: Matrix = None        # its real world matrix before it was pocketed
    center: Vector = None          # the middle of its real bounding box (world, with its children)
    placed: Matrix = None          # the world matrix the belt gave it last
    anchor: Vector = None          # the slot position that matrix was made for
    members: frozenset = frozenset()   # names of the object and its children (their depsgraph updates are the belt's own)

    def free(self):
        return self.item is None and not self.pocket


@dataclass
class Carry:
    """One thing a hand took off the belt and still holds: an item, or a model."""
    hand: str
    offset: Matrix
    item: object = None
    object_name: str = ""
    generation: int = 0


@dataclass
class BeltState:
    running: bool = False          # the belt works (setting on, session running)
    visible: bool = False          # drawn this tick
    ready: frozenset = frozenset()     # free slots a fingertip would drop into now (drawn blue)
    reconcile_due: bool = False     # an undo / redo ran: the slots follow the objects' markers on the next tick
    slots: list = field(default_factory=lambda: [Slot(index) for index in range(belt_math.SLOT_COUNT)])
    carries: dict = field(default_factory=dict)     # hand -> Carry
    watched: dict = field(default_factory=dict)     # item name -> (hand, grip location) while someone else holds it

    def reset(self):
        self.running = self.visible = False
        self.slots[:] = [Slot(index) for index in range(belt_math.SLOT_COUNT)]
        self.carries.clear()
        self.reconcile_due = False
        self.ready = frozenset()
        self.watched.clear()

    @property
    def frame(self):
        """The belt hangs on your body frame (body_frame.py)."""
        return BODY.matrix

    def size_factor(self):
        """Belt size setting times Your size: everything on the belt scales by it."""
        return settings.get("belt_size") * SIZE.factor

    def radius(self):
        return belt_math.BELT_RADIUS * self.size_factor()

    def room(self):
        """How long a pocketed model's longest side may be."""
        return belt_math.POCKET_ROOM * 2 * belt_math.SLOT_HALF * self.size_factor()

    def reach(self):
        return belt_math.SLOT_REACH * self.size_factor()

    def slot_matrix(self, index, scale=1.0):
        return belt_math.slot_matrix(self.frame, index, self.radius(), scale)

    def nearest(self, position, allowed):
        return belt_math.nearest_slot(self.frame, self.radius(), position, self.reach(), allowed)

    def free_indices(self):
        return [slot.index for slot in self.slots if slot.free()]

    def occupied_indices(self):
        return [slot.index for slot in self.slots if not slot.free()]


BELT = BeltState()
