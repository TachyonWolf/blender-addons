# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool gun's live state (data only, no bpy): what the first shot of a two-shot tool picked, the running hold, the
measurement, the material pick and the menu's note. Nothing is saved; gun_shots.end drops it."""
from dataclasses import dataclass, field

from .runtime import RUNTIME


@dataclass(frozen=True)
class Pending:
    """What the first shot picked. An undo / redo or a mode change drops it."""
    name: str
    generation: int
    mode: str


@dataclass(frozen=True)
class Measured:
    start: object = None
    end: object = None
    text: str = ""


@dataclass
class GunState:
    pending: Pending = None
    hold: object = None             # gun_tools.PlaceHold while the trigger is held
    hold_hand: str = ""
    hold_generation: int = -1
    hold_mode: str = ""
    last_frame: int = -1
    measured: Measured = field(default_factory=Measured)
    measured_version: int = 0
    material: str = ""              # Material.name_full of the chosen material
    material_page: int = 0
    eyedrop: bool = False
    note: str = ""
    warn: bool = False

    def say(self, note, warn=False):
        self.note, self.warn = note, warn

    def remember(self, name, mode):
        self.pending = Pending(name, RUNTIME.generation, mode)

    def measure(self, measured):
        self.measured = measured
        self.measured_version += 1

    def drop_pending(self):
        """Forget the first shot (and a half-done measurement) and the note about it."""
        self.pending, self.eyedrop = None, False
        if self.measured.end is None:
            self.measure(Measured())
        self.say("")


STATE = GunState()
