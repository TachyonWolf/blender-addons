# SPDX-License-Identifier: GPL-3.0-or-later
"""The Subdivision ticker's rules (Selected > Modifiers), pure Python (no bpy), tested headless.

The row is always there for the active object; its level is the viewport `levels` of the LAST Subdivision Surface
modifier (0 when there is none). Range 0 to MAX_LEVEL; an existing level above that is shown as is and only changes on
a press (- steps down, + is dimmed). 0 never removes a modifier."""
from dataclasses import dataclass

MAX_LEVEL = 2
WARN_FACES = 250_000
SUPPORTED_TYPES = frozenset({'MESH', 'CURVE', 'SURFACE', 'FONT'})      # object types that take Subdivision Surface


@dataclass(frozen=True)
class SubdivView:
    """What the desk row shows (frozen: equal views = no redraw)."""
    level: int = 0
    minus: bool = False         # the - button works
    plus: bool = False          # the + button works
    note: str = ""              # a short line after the buttons ("" = none)
    warn: bool = False          # the note is a warning
    dimmed: bool = True         # the whole row is dimmed (the object can't take the modifier)


def unavailable_reason(object_type, linked, data_linked, system_override):
    """Why the row is dimmed ("" = it works)."""
    if object_type not in SUPPORTED_TYPES:
        return "Not for this type"
    if linked or data_linked:
        return "Linked: read only"
    if system_override:
        return "Override: read only"
    return ""


def estimated_faces(base_faces, level):
    return base_faces * 4 ** max(0, level)


def next_level(level, direction):
    """The level after a press (direction +1 / -1), or None when the press does nothing."""
    if direction > 0:
        return level + 1 if level < MAX_LEVEL else None
    return level - 1 if level > 0 else None


def view(level, reason, base_faces=0, show_viewport=True, show_edit=True):
    """The SubdivView for a level (the last modifier's, 0 for none). `reason` = unavailable_reason()."""
    if reason:
        return SubdivView(level, False, False, reason, False, True)
    faces = estimated_faces(base_faces, level)
    notes = []
    if level > 0 and not show_viewport:
        notes.append("Off in the viewport")
    elif level > 0 and not show_edit:
        notes.append("Not shown in Edit mode")
    heavy = faces > WARN_FACES
    if heavy:
        notes.append(f"Heavy: ~{faces / 1e6:.1f}M faces" if faces >= 1_000_000 else f"Heavy: ~{faces // 1000}k faces")
    return SubdivView(level, level > 0, level < MAX_LEVEL, "; ".join(notes), heavy, False)
