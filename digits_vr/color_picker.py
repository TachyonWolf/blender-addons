# SPDX-License-Identifier: GPL-3.0-or-later
"""The VR colour picker: ONE pop-up for any colour (today the Grease Pencil Add colour and edit). A big preview, a Hex field
(typed on the VR keyboard), RGB / HSV mode, one slider per channel plus Alpha, and a row of preset swatches. Press the apply
button to use the colour; what "use" means is the picker's `purpose` (desk_actions: gp_new adds a material, gp_edit changes
the active one). Pure Python (the keyboard is imported when asked), tested headless.

Pop-up names: POPUPS. The picker's own actions (KEEP_OPEN) leave the pop-up open; any other press (apply) closes it."""
from dataclasses import dataclass, replace

from . import color_math
from .color_math import CHANNELS, HSV, RANGES, RGB, Colour
from .gpencil_math import NEW_COLORS
from .panel_layout import CARD, Widget, hint, popup
from .panel_widgets import card, popup_head, slider

NEW, EDIT = 'gp_new', 'gp_edit'
POPUPS = ('gp_color', 'gp_color_edit')
KEEP_OPEN = ('color_mode', 'color_channel', 'color_hex', 'color_preset')
START = "#ff4a4a"                  # the first colour of a new material (the first preset)
ROW, SLIDER_HEIGHT, GAP = 56, 64, 12


@dataclass(frozen=True)
class PickerView:
    purpose: str = NEW
    mode: str = RGB
    colour: Colour = Colour()


class Picker:
    """What the open pop-up edits (one at a time)."""
    purpose, mode, colour, revision = NEW, RGB, color_math.from_code(START), 0

    def open(self, purpose, colour):
        self.purpose, self.colour = purpose, colour
        self.revision += 1

    def set_colour(self, colour):
        self.colour = colour
        self.revision += 1

    def set_mode(self, mode):
        self.mode = mode
        self.revision += 1


PICKER = Picker()


def view():
    return PickerView(PICKER.purpose, PICKER.mode, PICKER.colour)


def widgets(picker_view, x, y, w, body):
    """The pop-up at (x, y), `w` wide: backdrop, frame, title + Close, preview / Hex / mode row, sliders, presets, apply."""
    colour, pad = picker_view.colour, 27
    inner = w - 2 * pad
    editing = picker_view.purpose == EDIT
    height = pad + 56 + GAP + ROW + GAP + 4 * (SLIDER_HEIGHT + GAP) + ROW + GAP + ROW + pad
    found = popup("color", x, y, w, height, ("popup", ""), body)
    found += popup_head("color", x, y, w, "Edit colour" if editing else "New colour")
    top = y + pad + 56 + GAP
    cell = (inner - 3 * GAP) / 4
    found.append(Widget("color_preview", CARD, x + pad, top, cell, ROW, color=colour.code, enabled=False))
    found.append(card("color_hex", x + pad + cell + GAP, top, cell, ROW, colour.code, ("color_hex",), size=26))
    for index, (mode, label) in enumerate(((RGB, "RGB"), (HSV, "HSV"))):
        found.append(card("color_mode_" + mode, x + pad + (2 + index) * (cell + GAP), top, cell, ROW, label,
                          ("color_mode", mode), size=26, active=picker_view.mode == mode))
    top += ROW + GAP
    for index, (channel, label) in enumerate(CHANNELS[picker_view.mode]):
        maximum, unit = RANGES[channel]
        found.append(replace(slider("color_" + channel, x + pad, top + index * (SLIDER_HEIGHT + GAP), inner, SLIDER_HEIGHT,
                                    label, colour.get(channel), (0, maximum), unit=unit, step=1, factor=1.0, decimals=0,
                                    size=26), action=("color_channel", channel)))
    top += 4 * (SLIDER_HEIGHT + GAP)
    swatch = (inner - GAP * (len(NEW_COLORS) - 1)) / len(NEW_COLORS)
    for index, (_label, code) in enumerate(NEW_COLORS):
        found.append(Widget("color_preset_%d" % index, CARD, x + pad + index * (swatch + GAP), top, swatch, ROW,
                            action=("color_preset", code), color=code, active=code == colour.code))
    top += ROW + GAP
    found.append(card("color_apply", x + pad, top, inner, ROW, "Apply" if editing else "Add colour", ("color_apply",),
                      size=28, icon="ADD" if not editing else ""))
    return found


def perform(widget, pixel_x, slider_value):
    """A press or drag on one of the picker's widgets. None = not one of its actions."""
    kind, *arguments = widget.action
    if kind == "color_mode":
        done = PICKER.mode != arguments[0]
        PICKER.set_mode(arguments[0])
        return done
    if kind == "color_channel":
        value = slider_value(widget, pixel_x)
        if value == PICKER.colour.get(arguments[0]):
            return False
        PICKER.set_colour(PICKER.colour.with_channel(arguments[0], value))
        return True
    if kind == "color_preset":
        PICKER.set_colour(replace(color_math.from_code(arguments[0]), a=PICKER.colour.a))
        return True
    if kind == "color_hex":
        from . import keyboard
        return keyboard.ask("Colour as #rrggbb", PICKER.colour.code, _typed)
    return None


def _typed(text):
    found = color_math.from_code(text, PICKER.colour.a)
    if found is not None:
        PICKER.set_colour(found)
