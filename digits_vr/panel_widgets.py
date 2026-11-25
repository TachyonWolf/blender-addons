# SPDX-License-Identifier: GPL-3.0-or-later
"""Makers of the widgets every panel page uses (card, toggle, slider, dropdown, its list, a pop-up's head, a pager). Pure
Python (no bpy)."""
from .panel_layout import CARD, DROPDOWN, LABEL, SLIDER, TITLE, TOGGLE, Widget, popup

LIST_ROW, LIST_STEP = 56, 64        # a dropdown list's rows


def card(identifier, x, y, w, h, text, action=(), size=30, **more):
    return Widget(identifier, CARD, x, y, w, h, label=text, action=action, size=size, **more)


def toggle(identifier, x, y, w, h, text, setting, on, size=28, **more):
    return Widget(identifier, TOGGLE, x, y, w, h, label=text, action=("toggle", setting), active=on, size=size, **more)


def slider(identifier, x, y, w, h, caption, value, value_range, unit="cm", step=0.5, factor=0.01, size=28, **more):
    return Widget(identifier, SLIDER, x, y, w, h, label=caption, action=("slider", identifier, factor), value=value,
                  minimum=value_range[0], maximum=value_range[1], unit=unit, step=step, size=size, **more)


def dropdown(identifier, x, y, w, h, text, action, is_open, caret="▼", size=30, **more):
    return Widget(identifier, DROPDOWN, x, y, w, h, label=text, action=action, active=is_open, caret=caret, size=size,
                  **more)


def dropdown_list(prefix, x, y, w, items, close_action, body):
    """A dropdown list under its opener: rows of (identifier, label, action, active)."""
    height = 26 + len(items) * LIST_STEP - 8
    widgets = popup(prefix, x, y, w, height, close_action, body, radius=12)
    for index, (identifier, text, action, active) in enumerate(items):
        widgets.append(card(identifier, x + 13, y + 13 + index * LIST_STEP, w - 26, LIST_ROW, text, action,
                            active=active))
    return widgets


def popup_head(prefix, x, y, w, title, extra=()):
    """A pop-up's title and its Close button (plus `extra` buttons left of it)."""
    widgets = [Widget(prefix + "_title", LABEL, x + 27, y + 23, w - 220, 56, label=title, size=30, style=TITLE)]
    widgets.append(card(prefix + "_close", x + w - 177, y + 23, 150, 56, "Close", ("popup", ""), size=26))
    return widgets + list(extra)


def pager(prefix, x, y, w, page, pages, action, button_width=150, height=56, text=None, size=26):
    return [card(prefix + "_prev", x, y, button_width, height, "‹ Prev", (action, -1), size=size, enabled=page > 0),
            Widget(prefix + "_page", LABEL, x + button_width, y, w - 2 * button_width, height,
                   label=text if text is not None else f"Page {page + 1} of {pages}", size=24, style='pager'),
            card(prefix + "_next", x + w - button_width, y, button_width, height, "Next ›", (action, 1), size=size,
                 enabled=page + 1 < pages)]
