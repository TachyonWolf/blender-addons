# SPDX-License-Identifier: GPL-3.0-or-later
"""The Controls pop-up of Help, on the desk (DESIGN "Help button"): per hand a controller drawing, a short stack of label
boxes (bold title, small dim second line) and a thin line from each box to a dot on its button. Pure Python (no bpy), tested
headless. What the labels say comes from router.help_labels; help_art.py draws the pictures, lines and dots."""
from .panel_layout import CARD, LABEL, TITLE, Widget, hint, popup

BOX, LINE, ART = 'help_box', 'help_line', 'help_art'       # LABEL styles
LEFT, RIGHT = 'LEFT', 'RIGHT'
ART_PIXELS = 128                    # the pictures are square
# where each button is in the LEFT picture (Kenney, Meta Quest Touch Plus); the right picture is its mirror
BUTTON_DOTS = {'trig': (64, 20), 'stick': (51, 40), 'click': (51, 40), 'b2': (71, 41), 'b1': (63, 53), 'grip': (75, 73)}
ORDER = ('trig', 'stick', 'click', 'b2', 'b1', 'grip')     # the stack, top to bottom
X, Y, WIDTH, HEIGHT = 24, 110, 976, 552
ROW, BOX_HEIGHT, BOX_WIDTH, ART_SIZE = 62, 56, 264, 300
STACK_TOP = Y + 96
BOX_X = {LEFT: X + 20, RIGHT: X + WIDTH - 20 - BOX_WIDTH}
ART_X = {LEFT: X + 224, RIGHT: X + WIDTH - 224 - ART_SIZE}
ART_Y = STACK_TOP + (len(ORDER) * ROW - ART_SIZE) / 2


def dot(hand, button):
    """The pixel of a button's dot on the desk."""
    px, py = BUTTON_DOTS[button]
    if hand == RIGHT:
        px = ART_PIXELS - px
    return ART_X[hand] + px * ART_SIZE / ART_PIXELS, ART_Y + py * ART_SIZE / ART_PIXELS


def build(rows, hidden_gestures, body):
    """The pop-up's widgets. `rows` = ((hand, button, title, second line), ...): only buttons that do something now."""
    widgets = popup("help_popup", X, Y, WIDTH, HEIGHT, ("popup", ""), body)
    widgets += [Widget("help_popup_title", LABEL, X + 27, Y + 20, 500, 56, label="Controls right now", size=30, style=TITLE),
                Widget("help_popup_close", CARD, X + WIDTH - 177, Y + 20, 150, 56, label="Close", action=("popup", ""), size=26)]
    boxes = []
    for hand in (LEFT, RIGHT):
        widgets.append(Widget("help_art_" + hand, LABEL, ART_X[hand], ART_Y, ART_SIZE, ART_SIZE, style=ART))
        mine = sorted((row for row in rows if row[0] == hand), key=lambda row: ORDER.index(row[1]))
        for index, (_hand, button, title, second) in enumerate(mine):
            x, y = BOX_X[hand], STACK_TOP + index * ROW
            boxes.append(Widget(f"help_box_{hand}_{button}", LABEL, x, y, BOX_WIDTH, BOX_HEIGHT, label=title, detail=second,
                                size=24, style=BOX))
            from_x, from_y = x + BOX_WIDTH if hand == LEFT else x, y + BOX_HEIGHT / 2
            to_x, to_y = dot(hand, button)          # a line: from the box (x, y) by (w, h) to the dot
            widgets.append(Widget(f"help_line_{hand}_{button}", LABEL, from_x, from_y, to_x - from_x, to_y - from_y, style=LINE))
    widgets += boxes
    return widgets + [hint(f"help_gesture_{index}", text, X + 27, Y + HEIGHT - 72 + index * 30, WIDTH - 54, size=20)
                      for index, text in enumerate(hidden_gestures)]
