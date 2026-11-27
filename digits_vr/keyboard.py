# SPDX-License-Identifier: GPL-3.0-or-later
"""The VR keyboard (bpy side): one floating panel on the shared panel system. Ask for text with
    keyboard.ask(prompt, initial_text, on_done, on_cancel=None, near=panel)
It opens below the panel that asked (`near`), shows the prompt and the text with a cursor, and gives the text to
`on_done(text)` on Enter (`on_cancel()` on Cancel). Type with the laser + trigger or poke the keys with a fingertip
(poke.py): both end in `perform`. HOOKS for later features (PDA tab names, searches): call `ask` from their button's
`perform`, as viewpoints.py does for a spot's name. Closed it costs nothing; open it is one panel texture (the key
labels are drawn once, when the text or page changes), no per-key GPU objects. Nothing is remembered (no settings).

Clipboard: Copy puts the whole text on Blender's system clipboard (`window_manager.clipboard`, shared with the desktop),
Paste inserts it at the end, Clear empties the line. A short press of Paste pastes when it is let go; holding it for
0.5 s opens the paste history list (clipboard_history.py: the OS history, fetched in a background thread from the press
on, never in the frame; the add-on's own in-memory paste_history.py is the fallback). A tap on a row pastes it; a tap
outside closes the list."""
import time

import bpy
from mathutils import Vector

from . import clipboard_history, keyboard_layout as layout, panel_layout, settings
from .action_map import buzz
from .paste_history import PasteHistory, one_line
from .panel import Panel, REGISTRY
from .panel_layout import METERS_PER_PIXEL
from .runtime import RUNTIME
from .size_state import SIZE

GAP_BELOW = 0.04            # metres between the asking panel and the keyboard (your space)
HOLD_SECONDS = 0.5          # a Paste held this long opens the history list
HISTORY = PasteHistory()    # the add-on's own paste history: memory only, never saved
FETCH = clipboard_history.HistoryFetch()
_session = {"prompt": "", "edit": layout.Edit(), "on_done": None, "on_cancel": None, "on_change": None, "dropdown": False}
_hold = {"hand": None, "start": 0.0}


class SystemClipboard:
    """Blender's clipboard (shared with the desktop). Tests swap `keyboard.CLIPBOARD` for a fake with the same two calls."""

    def get(self):
        return bpy.context.window_manager.clipboard

    def set(self, text):
        bpy.context.window_manager.clipboard = text


CLIPBOARD = SystemClipboard()


def _forget():
    _session.update(prompt="", edit=layout.Edit(), on_done=None, on_cancel=None, on_change=None, dropdown=False)
    _hold.update(hand=None, start=0.0)
    FETCH.reset()


def history_entries():
    """The texts the list shows, newest first: the OS history when it answered, else the add-on's own."""
    answer = FETCH.result()
    return list(answer) if answer else list(HISTORY.entries)


def build_model():
    entries = history_entries()
    dropdown = tuple(one_line(entry) for entry in entries) if _session["dropdown"] else None
    edit = _session["edit"]
    return layout.KeyboardModel(_session["prompt"], edit.text, edit.page, edit.shift, dropdown,
                                bool(_session["dropdown"]) and FETCH.pending() and not entries, edit.cursor, edit.anchor, edit.ctrl)


def current_text():
    return _session["edit"].text


def _clipboard_text():
    try:
        return CLIPBOARD.get() or ""
    except (AttributeError, RuntimeError, TypeError):
        return ""


def _paste(text):
    before = _session["edit"].text
    _session["edit"] = layout.apply(_session["edit"], ("paste",), text)[0]
    _session["dropdown"] = False
    if _session["edit"].text != before and _session["on_change"] is not None:
        _session["on_change"](_session["edit"].text)


def _clipboard_effects(copied):
    if copied is not None:
        CLIPBOARD.set(copied)
        HISTORY.add(copied)


def perform(context, widget, pixel_x):
    """A key press. True when the screen changed. Enter / Esc close the keyboard, then call back."""
    if not widget.action or not widget.enabled:
        return False
    kind, edit = widget.action[0], _session["edit"]
    if kind == "paste_entry":
        entries = history_entries()
        if 0 <= widget.action[1] < len(entries):
            _paste(entries[widget.action[1]])
        _session["dropdown"] = False
        return True
    if kind == "dd_close":
        _session["dropdown"] = False
        return True
    action = ("place", layout.place_cursor(edit, pixel_x)) if kind == "place" else widget.action
    clipboard = _clipboard_text() if layout.needs_clipboard(edit, action) else ""
    if clipboard:
        HISTORY.add(clipboard)
    new_edit, outcome, copied = layout.apply(edit, action, clipboard)
    _session["edit"] = new_edit
    _clipboard_effects(copied)
    if outcome is None and new_edit.text != edit.text and _session["on_change"] is not None:
        _session["on_change"](new_edit.text)         # a search that follows every key (find.py)
    if outcome is not None:
        callback = _session["on_done"] if outcome == 'done' else _session["on_cancel"]
        PANEL.close()
        if callback is not None:
            callback(new_edit.text) if outcome == 'done' else callback()
    return True


class KeyboardPanel(Panel):
    name = "keyboard"
    spec = layout.SPEC
    open_distance, open_drop = 0.45, 0.35

    def build_model(self, context):
        return build_model()

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget, pixel_x)

    def take_trigger(self, context, state, hand, widget):
        """Paste is decided on release (short) or after HOLD_SECONDS (list): the press only starts the clock and asks the
        OS history in the background."""
        if widget.id != "paste" or _session["dropdown"] or _hold["hand"] is not None:
            return False
        HISTORY.add(_clipboard_text())
        FETCH.start()
        _hold.update(hand=hand, start=time.perf_counter())
        buzz(context, state, hand, duration=0.015, amplitude=0.5)
        return True

    def update(self, context, state):
        """Every tick while open: Paste let go = paste; held long enough = the list; the OS answer arrived = refresh."""
        hand = _hold["hand"]
        if hand is not None:
            held = RUNTIME.hands[hand].trigger_down or self.state.pressed.get(hand) == "paste"
            if not held:
                _hold["hand"] = None
                _paste(_clipboard_text())
                self.refresh(context, force=True)
                buzz(context, state, hand, duration=0.015, amplitude=0.5)
            elif time.perf_counter() - _hold["start"] >= HOLD_SECONDS:
                _hold["hand"] = None
                _session["dropdown"] = True
                self.refresh(context, force=True)
                buzz(context, state, hand, duration=0.04, amplitude=0.7)
        elif _session["dropdown"] and not FETCH.pending() and FETCH.result() is not None and self.ticks % 3 == 0:
            self.refresh(context)

    def start(self, context):
        """Session start: no remembered place or open state; the keyboard opens only when something asks."""
        self.state.size = SIZE.factor
        self.state.scale = SIZE.factor
        self.state.placed = False
        self.state.pinned, self.state.pin_offset, self.state.pin_last = settings.get(self.key("pinned")), None, None
        self.ticks, self.last_frame, self.last_pin_frame, self.two_hand = 0, -1, -1, None

    def remember(self):
        """Nothing is saved: the keyboard belongs to the one ask that opened it."""

    def closed(self):
        _forget()

    def _half_size(self, panel):
        """(half width, half height) in metres of a panel with its handles."""
        scale = panel.state.scale * METERS_PER_PIXEL
        return ((panel.spec.width / 2 + panel_layout.HANDLE_WIDTH + panel_layout.HANDLE_GAP) * scale, panel.spec.height / 2 * scale)

    def place_below(self, other, avoid=()):
        """Put the keyboard just under the panel that asked, turned the same way and the same size, and slid sideways
        off any other open panel (the desk) it would sit over."""
        other_state = other.state
        scale = other_state.scale
        drop = ((other.spec.height + layout.SPEC.height) / 2 * METERS_PER_PIXEL * scale) + GAP_BELOW * SIZE.factor
        self.state.rotation = other_state.rotation.copy()
        self.state.location = other_state.location + other_state.rotation @ Vector((0.0, -drop, 0.03 * scale))
        self.state.scale = scale
        self.state.size = other_state.size
        self.state.placed = True
        rotation = other_state.rotation
        right, up = rotation @ Vector((1.0, 0.0, 0.0)), rotation @ Vector((0.0, 1.0, 0.0))
        for panel in avoid:
            offset = self.state.location - panel.state.location
            dx = layout.clear_of((offset.dot(right), offset.dot(up)), self._half_size(self), self._half_size(panel),
                                 GAP_BELOW * SIZE.factor)
            self.state.location = self.state.location + right * (dx - offset.dot(right))


PANEL = KeyboardPanel()


def ask(prompt, initial_text, on_done, on_cancel=None, near=None, on_change=None):
    """Open the keyboard for one text. `near`: the Panel that asked (the keyboard goes below it, not over it), else it
    opens in front of you. `on_change(text)`: called after every key that changed the text. A keyboard already open for another ask is closed first (its Cancel callback runs)."""
    context = bpy.context
    previous_cancel = _session["on_cancel"] if PANEL.is_open() else None
    if PANEL.is_open():
        PANEL.close()
        if previous_cancel is not None:
            previous_cancel()
    _forget()
    text = initial_text[:layout.MAX_LENGTH]
    _session.update(prompt=prompt, edit=layout.Edit(text, len(text)), on_done=on_done, on_cancel=on_cancel, on_change=on_change)
    state = context.window_manager.xr_session_state
    if near is not None and near.state.placed:
        PANEL.place_below(near, [panel for panel in REGISTRY.values() if panel.is_open() and panel not in (near, PANEL)])
        PANEL.open(context, None)
    elif state is not None:
        PANEL.state.placed = False
        PANEL.open(context, state)
    else:
        return False
    return True
