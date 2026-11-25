# SPDX-License-Identifier: GPL-3.0-or-later
"""The keyboard's screen (DESIGN "Keyboard and simple hand"): a prompt, the typed text with a cursor, the Copy / Paste /
Clear buttons (on every page), then a real-style keyboard: a number row with Backspace, Tab + QWERTY, Caps + home row +
Enter (a half key in), Shift + Z row + Shift (a key in), and a bottom row with the Space bar under C to M. A second page
has symbols. A held Paste opens the paste history list over the keys. Pure Python (no bpy), tested headless: the typing
rules (`type_action`) live here too."""
from dataclasses import dataclass, replace

from .paste_history import tidy
from .panel_layout import BUTTON, CARD, PanelSpec, label, side_handle, Widget

SPEC = PanelSpec(1666, 650)          # about 75 x 29 cm at scale 1 (the most the user wants)
MARGIN, GAP = 24, 6
UNITS = 16.1                         # the widest row (main block + gap + arrow cluster), in key widths
MAIN_UNITS, CLUSTER_X = 12.75, 13.15  # the main block's width, and where the cluster starts
MAX_LENGTH = 256
VISIBLE_CHARS = 38                   # the text line shows a window of this many characters around the cursor
CHAR_ADVANCE = 24.5                  # pixels per character of the text line (an estimate, for tapping a place)
LETTERS, SYMBOLS = 'letters', 'symbols'
OFF, ONCE, CAPS = 'off', 'once', 'caps'
DIGITS = "1234567890"
PAGES = {LETTERS: ("qwertyuiop'", "asdfghjkl", "zxcvbnm"), SYMBOLS: ("!@#$%^&*()?", "-_=+/\\;:\"", "'~,.<>|")}
ROW_TOP, ROW_STEP, KEY_HEIGHT = 150, 96, 84
PAGE_BUTTONS = {LETTERS: "123", SYMBOLS: "ABC"}
CLIP_TOP, CLIP_WIDTH, CLIP_HEIGHT, CLIP_GAP = 60, 150, 70, 8
DROP_ROWS, DROP_WIDTH, DROP_HEIGHT, DROP_STEP = 10, 640, 46, 50
TEXT_X, TEXT_Y, TEXT_HEIGHT = MARGIN, 66, 74


@dataclass(frozen=True)
class Edit:
    """The text being edited: the text, the cursor (0..len), the selection anchor (None = no selection; the selection
    runs between the anchor and the cursor), the page, Shift / Caps and the one-shot Ctrl."""
    text: str = ""
    cursor: int = 0
    anchor: object = None
    page: str = LETTERS
    shift: str = OFF
    ctrl: bool = False


@dataclass(frozen=True)
class KeyboardModel:
    """What the keyboard shows (plain values: equal models need no redraw)."""
    prompt: str = ""
    text: str = ""
    page: str = LETTERS
    shift: str = OFF
    dropdown: object = None     # None = closed; else the paste history's row labels (newest first)
    loading: bool = False       # the OS history has not answered yet (and there is no other list to show)
    cursor: int = -1            # -1 = at the end
    anchor: object = None
    ctrl: bool = False


def selection(edit):
    """(start, end) of the selected text, or None."""
    if edit.anchor is None or edit.anchor == edit.cursor:
        return None
    return min(edit.anchor, edit.cursor), max(edit.anchor, edit.cursor)


def window_start(length, cursor):
    """Where the text line's window starts: the whole text when it fits, else VISIBLE_CHARS around the cursor."""
    if length <= VISIBLE_CHARS:
        return 0
    return min(max(0, cursor - VISIBLE_CHARS // 2), length - VISIBLE_CHARS)


def shown_text(text, cursor=-1, anchor=None):
    """The text line: a window of the text, the cursor `|` where it is, a selection in [brackets], "..." where cut."""
    cursor = len(text) if cursor < 0 else min(cursor, len(text))
    start = window_start(len(text), cursor)
    end = min(len(text), start + VISIBLE_CHARS)
    low, high = (min(anchor, cursor), max(anchor, cursor)) if anchor is not None and anchor != cursor else (None, None)
    pieces = []
    for index in range(start, end + 1):
        if index == low:
            pieces.append("[")
        if index == cursor:
            pieces.append("|")
        if index == high:
            pieces.append("]")
        if index < end:
            pieces.append(text[index])
    return ("..." if start > 0 else "") + "".join(pieces) + ("..." if end < len(text) else "")


def place_cursor(edit, pixel_x):
    """The cursor index for a tap at `pixel_x` on the text line (an estimate from CHAR_ADVANCE; the window is the same
    one shown_text draws)."""
    start = window_start(len(edit.text), edit.cursor)
    lead = 3 if start > 0 else 0
    index = start + int(round((pixel_x - TEXT_X) / CHAR_ADVANCE)) - lead
    return min(len(edit.text), max(0, index))


def keycap(character, shift):
    return character.upper() if shift != OFF else character


def _insert(edit, string):
    """Replace the selection (if any) by `string` at the cursor; never past MAX_LENGTH."""
    span = selection(edit) or (edit.cursor, edit.cursor)
    room = MAX_LENGTH - (len(edit.text) - (span[1] - span[0]))
    string = string[:max(0, room)]
    return replace(edit, text=edit.text[:span[0]] + string + edit.text[span[1]:], cursor=span[0] + len(string), anchor=None)


def _delete(edit, backwards):
    span = selection(edit)
    if span is None:
        if backwards and edit.cursor > 0:
            span = (edit.cursor - 1, edit.cursor)
        elif not backwards and edit.cursor < len(edit.text):
            span = (edit.cursor, edit.cursor + 1)
        else:
            return replace(edit, anchor=None)
    return replace(edit, text=edit.text[:span[0]] + edit.text[span[1]:], cursor=span[0], anchor=None)


def word_left(text, cursor):
    """Jump back to the start of the word before the cursor."""
    while cursor > 0 and text[cursor - 1] == " ":
        cursor -= 1
    while cursor > 0 and text[cursor - 1] != " ":
        cursor -= 1
    return cursor


def word_right(text, cursor):
    """Jump forward to the start of the next word (the end of the text at the last one)."""
    while cursor < len(text) and text[cursor] != " ":
        cursor += 1
    while cursor < len(text) and text[cursor] == " ":
        cursor += 1
    return cursor


def _move(edit, cursor):
    return replace(edit, cursor=cursor, anchor=None)


def needs_clipboard(edit, action):
    """Does this key read the clipboard (Paste, Ctrl+V)?"""
    return action[0] == "paste" or (edit.ctrl and action[0] == "key" and action[1] == "v")


def apply(edit, action, clipboard=""):
    """One key press on an Edit. `action` is the widget's action tuple. Returns (new Edit, outcome, copied): outcome is
    None, 'done' (Enter) or 'cancel' (Esc); `copied` is a text for the system clipboard (Copy, Ctrl+C, Ctrl+X) or None.
    `clipboard` is what Paste / Ctrl+V insert at the cursor: new lines become spaces, at most 256 characters."""
    kind = action[0]
    if kind == "shift":
        return replace(edit, shift=ONCE if edit.shift == OFF else OFF), None, None
    if kind == "caps":
        return replace(edit, shift=OFF if edit.shift == CAPS else CAPS), None, None
    if kind == "ctrl":
        return replace(edit, ctrl=not edit.ctrl), None, None
    if kind == "alt":
        return edit, None, None
    ctrl, edit = edit.ctrl, replace(edit, ctrl=False)          # Ctrl lasts for one key
    span = selection(edit)
    chosen = edit.text[span[0]:span[1]] if span else edit.text
    if kind == "key" and ctrl:
        if action[1] == "c":
            return edit, None, chosen or None                       # the selection, else the whole text
        shortcut = {"v": ("paste",), "x": ("cut",), "a": ("select_all",)}.get(action[1])
        return apply(edit, shortcut, clipboard) if shortcut else (edit, None, None)
    if kind == "key":
        if len(edit.text) >= MAX_LENGTH and span is None:
            return edit, None, None
        return replace(_insert(edit, keycap(action[1], edit.shift if edit.page == LETTERS else OFF)),
                       shift=OFF if edit.shift == ONCE else edit.shift), None, None
    if kind == "space":
        return _insert(edit, " "), None, None
    if kind == "backspace":
        return _delete(edit, True), None, None
    if kind == "delete":
        return _delete(edit, False), None, None
    if kind == "clear":
        return replace(edit, text="", cursor=0, anchor=None), None, None
    if kind == "paste":
        return _insert(edit, tidy(clipboard)), None, None
    if kind == "copy":
        return edit, None, edit.text or None
    if kind == "cut":
        return (_delete(edit, True) if span else replace(edit, text="", cursor=0, anchor=None)), None, chosen or None
    if kind == "select_all":
        return replace(edit, cursor=len(edit.text), anchor=0), None, None
    if kind == "left":
        if ctrl:
            return _move(edit, word_left(edit.text, edit.cursor)), None, None
        return _move(edit, span[0] if span else max(0, edit.cursor - 1)), None, None
    if kind == "right":
        if ctrl:
            return _move(edit, word_right(edit.text, edit.cursor)), None, None
        return _move(edit, span[1] if span else min(len(edit.text), edit.cursor + 1)), None, None
    if kind in ("up", "home"):
        return _move(edit, 0), None, None
    if kind in ("down", "end"):
        return _move(edit, len(edit.text)), None, None
    if kind == "place":
        return _move(edit, action[1]), None, None
    if kind == "page":
        return replace(edit, page=SYMBOLS if edit.page == LETTERS else LETTERS), None, None
    return edit, ('done' if kind == "enter" else 'cancel' if kind == "cancel" else None), None


def clear_of(offset, keyboard_half, other_half, gap):
    """Where the keyboard's centre goes sideways so it does not sit over another panel. `offset` = (dx, dy) from that
    panel's centre to the keyboard's, `*_half` = (half width, half height) of each including handles, all in metres in
    the plane of the panel that asked. Returns the new dx (dy never changes): pushed away along x when they overlap."""
    dx, dy = offset
    reach_x, reach_y = keyboard_half[0] + other_half[0] + gap, keyboard_half[1] + other_half[1] + gap
    if abs(dy) >= reach_y or abs(dx) >= reach_x:
        return dx
    return (reach_x if dx >= 0 else -reach_x)


def _rows(page):
    """The key rows: items are ("gap", units), ("key", character, units) or ("ctl", id, units, label, action)."""
    first, second, third = PAGES[page]
    plain = lambda characters: [("key", character, 1.0) for character in characters]       # noqa: E731
    cluster = CLUSTER_X - MAIN_UNITS
    return [[("ctl", "cancel", 1.0, "Esc", ("cancel",))] + plain(DIGITS) + [("ctl", "backspace", 1.75, "Del", ("backspace",))],
            [("ctl", "tab", 1.5, "Tab", ("space",))] + plain(first),
            [("ctl", "caps", 2.0, "Caps", ("caps",))] + plain(second) + [("ctl", "enter", 1.75, "Enter", ("enter",)),
             ("gap", cluster), ("ctl", "home", 1.0, "Home", ("home",)), ("ctl", "end", 1.0, "End", ("end",)),
             ("ctl", "delete", 1.0, "Del>", ("delete",))],
            [("ctl", "shift", 2.5, "Shift", ("shift",))] + plain(third) + [("ctl", "shift_right", 3.25, "Shift", ("shift",)),
             ("gap", cluster + 1.0), ("ctl", "up", 1.0, "Up", ("up",))],
            [("ctl", "ctrl", 1.5, "Ctrl", ("ctrl",)), ("ctl", "page", 1.5, PAGE_BUTTONS[page], ("page",)),
             ("ctl", "alt", 1.5, "Alt", ("alt",)), ("ctl", "space", 5.0, "space", ("space",)),
             ("ctl", "alt_right", 1.25, "Alt", ("alt",)), ("ctl", "ctrl_right", 2.0, "Ctrl", ("ctrl",)),
             ("gap", cluster), ("ctl", "left", 1.0, "<", ("left",)), ("ctl", "down", 1.0, "Down", ("down",)),
             ("ctl", "right", 1.0, ">", ("right",))]]


def _key_widgets(model):
    unit = (SPEC.width - 2 * MARGIN + GAP) / UNITS
    widgets = []
    for row_index, row in enumerate(_rows(model.page)):
        x, y = MARGIN, ROW_TOP + row_index * ROW_STEP
        for item in row:
            width = item[1] if item[0] == "gap" else item[2]
            if item[0] == "key":
                widgets.append(Widget("key_" + item[1], CARD, x, y, width * unit - GAP, KEY_HEIGHT,
                                      label=keycap(item[1], model.shift if model.page == LETTERS else OFF), size=44,
                                      action=("key", item[1])))
            elif item[0] == "ctl":
                name, text, action = item[1], item[3], item[4]
                active = ((name == "caps" and model.shift == CAPS) or (name.startswith("shift") and model.shift == ONCE)
                          or (name.startswith("ctrl") and model.ctrl))
                widgets.append(Widget(name, BUTTON if name == "enter" else CARD, x, y, width * unit - GAP, KEY_HEIGHT,
                                      label=text, size=30, action=action, active=active, enabled=not name.startswith("alt")))
            x += width * unit
    return widgets


def _clipboard_buttons(model):
    left = SPEC.width - MARGIN - 3 * CLIP_WIDTH - 2 * CLIP_GAP
    return [Widget(name, BUTTON, left + index * (CLIP_WIDTH + CLIP_GAP), CLIP_TOP, CLIP_WIDTH, CLIP_HEIGHT, label=text,
                   size=32, action=(name,)) for index, (name, text) in enumerate((("copy", "Copy"), ("paste", "Paste"),
                                                                                   ("clear", "Clear")))]


def _dropdown_widgets(model):
    """The paste history list: a catcher behind it (a tap outside closes) and one row per entry, newest first."""
    left = SPEC.width - MARGIN - DROP_WIDTH
    widgets = [Widget("dd_outside", CARD, MARGIN, ROW_TOP, SPEC.width - 2 * MARGIN, SPEC.height - ROW_TOP - MARGIN,
                      label="Tap outside the list to close", size=28, action=("dd_close",), enabled=True)]
    if not model.dropdown:
        widgets.append(Widget("dd_empty", CARD, left, ROW_TOP + 8, DROP_WIDTH, DROP_HEIGHT, size=30, action=("dd_close",),
                              label="Loading..." if model.loading else "Nothing copied yet"))
    for index, text in enumerate(model.dropdown or ()):
        widgets.append(Widget("dd_row_%d" % index, CARD, left, ROW_TOP + 8 + index * DROP_STEP, DROP_WIDTH, DROP_HEIGHT,
                              label=text, size=30, action=("paste_entry", index)))
    return widgets


def build(model):
    """All widgets, back to front."""
    text_width = SPEC.width - 2 * MARGIN - 3 * CLIP_WIDTH - 2 * CLIP_GAP - 24
    widgets = [label("prompt", model.prompt, MARGIN, 16, w=SPEC.width - 2 * MARGIN, size=30),
               Widget("text_field", CARD, TEXT_X, TEXT_Y, text_width, TEXT_HEIGHT, action=("place",)),     # a tap places the cursor
               label("text_line", shown_text(model.text, model.cursor, model.anchor), TEXT_X + 4, TEXT_Y + 10, w=text_width - 8, size=48)]
    widgets += _clipboard_buttons(model)
    widgets += _dropdown_widgets(model) if model.dropdown is not None else _key_widgets(model)
    widgets += [side_handle('LEFT', SPEC.width, 230, 280), side_handle('RIGHT', SPEC.width, 230, 280)]
    return widgets
