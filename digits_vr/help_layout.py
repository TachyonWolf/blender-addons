# SPDX-License-Identifier: GPL-3.0-or-later
"""The Help panel's screen (DESIGN "Help panel"): the Tooltips toggle, the line that says which button opens the menu, then
per hand a controller drawing, a short stack of label boxes (bold title, small dim second line) and a thin line from each
box to a dot on its button; two lines of hidden gestures. Pure Python (no bpy), tested headless. What the labels say comes
from router.help_labels; help_art.py draws the pictures, lines and dots."""
from dataclasses import dataclass

from .panel_layout import LABEL, SECTION, TITLE, PanelSpec, Widget, hint, side_handle
from .panel_widgets import toggle
from .router import HIDDEN_GESTURES, MENU_LINE

BOX, LINE, ART = 'help_box', 'help_line', 'help_art'       # LABEL styles
LEFT, RIGHT = 'LEFT', 'RIGHT'
ART_PIXELS = 128                    # the pictures are square
# where each button is in the LEFT picture (Kenney, Meta Quest Touch Plus); the right picture is its mirror
BUTTON_DOTS = {'trig': (64, 20), 'stick': (51, 40), 'click': (51, 40), 'b2': (71, 41), 'b1': (63, 53), 'grip': (75, 73)}
ORDER = ('trig', 'stick', 'click', 'b2', 'b1', 'grip')     # the stack, top to bottom
X, WIDTH = 24, 976
SPEC = PanelSpec(1024, 680, scale_range=(0.2, 2.5))     # about 46 x 31 cm at scale 1; down to 0.2: docked on the belt
MENU_Y, CONTROLS_Y, GESTURES_Y = 104, 154, 592
ROW, BOX_HEIGHT, BOX_WIDTH, ART_SIZE = 62, 56, 264, 300
STACK_TOP = 200
BOX_X = {LEFT: X + 20, RIGHT: X + WIDTH - 20 - BOX_WIDTH}
ART_X = {LEFT: X + 224, RIGHT: X + WIDTH - 224 - ART_SIZE}
ART_Y = STACK_TOP + (len(ORDER) * ROW - ART_SIZE) / 2


def dot(hand, button):
    """The pixel of a button's dot on the panel."""
    px, py = BUTTON_DOTS[button]
    if hand == RIGHT:
        px = ART_PIXELS - px
    return ART_X[hand] + px * ART_SIZE / ART_PIXELS, ART_Y + py * ART_SIZE / ART_PIXELS


@dataclass(frozen=True)
class HelpModel:
    rows: tuple = ()            # ((hand, button, title, second line), ...): only buttons that do something now
    tooltips: bool = False      # the setting `help_on`


def build(model):
    """All widgets, back to front (Pin is added by panel.py)."""
    widgets = [toggle("help_tooltips", X, 18, 360, 72, "Tooltips", "help_on", model.tooltips, size=28),
               hint("help_tooltips_note", "Point at a button: a tip says what it does.", X + 384, 40, WIDTH - 384, size=22),
               Widget("help_menu", LABEL, X, MENU_Y, WIDTH, 44, label=MENU_LINE, size=30, style=TITLE),
               Widget("help_controls", LABEL, X, CONTROLS_Y, WIDTH, 28, label="CONTROLS RIGHT NOW", size=24, style=SECTION)]
    boxes = []
    for hand in (LEFT, RIGHT):
        widgets.append(Widget("help_art_" + hand, LABEL, ART_X[hand], ART_Y, ART_SIZE, ART_SIZE, style=ART))
        mine = sorted((row for row in model.rows if row[0] == hand), key=lambda row: ORDER.index(row[1]))
        for index, (_hand, button, title, second) in enumerate(mine):
            x, y = BOX_X[hand], STACK_TOP + index * ROW
            boxes.append(Widget(f"help_box_{hand}_{button}", LABEL, x, y, BOX_WIDTH, BOX_HEIGHT, label=title, detail=second,
                                size=24, style=BOX))
            from_x, from_y = x + BOX_WIDTH if hand == LEFT else x, y + BOX_HEIGHT / 2
            to_x, to_y = dot(hand, button)          # a line: from the box (x, y) by (w, h) to the dot
            widgets.append(Widget(f"help_line_{hand}_{button}", LABEL, from_x, from_y, to_x - from_x, to_y - from_y, style=LINE))
    widgets += boxes
    widgets += [hint(f"help_gesture_{index}", text, X, GESTURES_Y + index * 30, WIDTH, size=20)
                for index, text in enumerate(HIDDEN_GESTURES)]
    return widgets + [side_handle('LEFT', SPEC.width, 100, 300), side_handle('RIGHT', SPEC.width, 100, 300)]
