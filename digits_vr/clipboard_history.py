# SPDX-License-Identifier: GPL-3.0-or-later
"""The OS clipboard history for the keyboard's Paste list: `history(limit)` asks each backend in turn and returns the
first non-empty answer (newest first, text only, one line each, tidied: paste_history.tidy), or [] when none works (the
caller then uses the add-on's own in-memory history). Backends: KDE Plasma's Klipper over D-Bus; Windows (stub).
Nothing is saved to a file.

`history` runs a subprocess (up to 1 s): NEVER call it from the VR frame. `HistoryFetch` runs it in a thread; start it
when the Paste press begins and poll for the result. Pure Python (no bpy); the parser and the fallback are tested
headless, the real Klipper call only when Klipper answers."""
import ast
import shutil
import subprocess
import threading

from .paste_history import tidy

TIMEOUT = 1.0
LIMIT = 10
IMAGE_MARK = "\u25a8"
KLIPPER_ARGS = ("org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardHistoryMenu")


def clean_entries(items, limit=LIMIT):
    """Text entries only: tidied to one line, empty ones dropped, duplicates dropped, at most `limit`."""
    result = []
    for item in items:
        if not isinstance(item, str) or item.startswith(IMAGE_MARK):      # Klipper lists images as "▨ 123x45"
            continue
        text = tidy(item)
        if text.strip() and text not in result:
            result.append(text)
    return result[:limit]


def parse_gdbus(output):
    """The strings in `gdbus call` output for a method returning `as`: "(['one', 'two'],)". [] when it does not parse."""
    try:
        value = ast.literal_eval(output.strip())
    except (ValueError, SyntaxError):
        return []
    if isinstance(value, tuple) and value and isinstance(value[0], (list, tuple)):
        return [item for item in value[0] if isinstance(item, str)]
    return []


def parse_qdbus(output):
    """qdbus prints one string per line (an entry with a new line in it breaks into several: that is accepted)."""
    return [line for line in output.splitlines() if line.strip()]


def _run(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def klipper_history(limit=LIMIT):
    """KDE Plasma 6: Klipper runs inside plasmashell; its history comes over the session bus."""
    service, path, method = KLIPPER_ARGS
    gdbus = shutil.which("gdbus")
    if gdbus:
        return clean_entries(parse_gdbus(_run([gdbus, "call", "--session", "--dest", service, "--object-path", path,
                                               "--method", method])), limit)
    for name in ("qdbus6", "qdbus"):
        tool = shutil.which(name)
        if tool:
            return clean_entries(parse_qdbus(_run([tool, service, path, method])), limit)
    return []


def windows_history(limit=LIMIT):
    """TODO (Windows, later): the Win+V history through WinRT
    `Windows.ApplicationModel.DataTransfer.Clipboard.GetHistoryItemsAsync()` (text items only: `GetTextAsync`). Not built."""
    return []


BACKENDS = (klipper_history, windows_history)


def history(limit=LIMIT, backends=None):
    """The OS clipboard history, newest first; [] when no backend answers. Blocks up to a second per backend."""
    for backend in (BACKENDS if backends is None else backends):
        try:
            entries = backend(limit)
        except Exception as error:      # a backend must never break the keyboard
            print(f"digits_vr: clipboard history backend {backend.__name__} failed: {error}")
            continue
        if entries:
            return entries[:limit]
    return []


class HistoryFetch:
    """One history fetch in a background thread: `start()` at the Paste press, `result()` is None until it is done."""

    def __init__(self, backends=None):
        self.backends = backends
        self._entries = None
        self._thread = None

    def start(self):
        self._entries = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._entries = history(backends=self.backends)

    def pending(self):
        return self._thread is not None and self._entries is None

    def result(self):
        return self._entries

    def reset(self):
        self._entries, self._thread = None, None
