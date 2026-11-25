# SPDX-License-Identifier: GPL-3.0-or-later
"""The keyboard's paste history: the last texts copied with the Copy key or seen on the clipboard when Paste was
pressed, newest first, without duplicates, at most CAP. Pure Python (no bpy), tested headless. It lives in memory only
and is never written to a file (a clipboard can hold private text); it is gone when Blender closes."""
CAP = 10
MAX_PASTE = 256


def tidy(raw):
    """Clipboard text for the keyboard: new lines and tabs become spaces, at most MAX_PASTE characters."""
    return " ".join(str(raw).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ").split("\n"))[:MAX_PASTE]


def one_line(text, limit=44):
    """A history row's label: one line, cut short with an ellipsis."""
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 3] + "..."


class PasteHistory:
    def __init__(self):
        self.entries = []

    def add(self, raw):
        """Remember a text (tidied). Empty text is ignored; a text already there moves to the front."""
        text = tidy(raw)
        if not text.strip():
            return
        if text in self.entries:
            self.entries.remove(text)
        self.entries.insert(0, text)
        del self.entries[CAP:]

    def labels(self):
        return tuple(one_line(entry) for entry in self.entries)

    def clear(self):
        self.entries.clear()
