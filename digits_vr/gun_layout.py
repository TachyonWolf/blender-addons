# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool gun's menu (DESIGN "Tool gun"): the nine tools, the settings of the chosen one, and a note line. It hangs
beside the gun, so it has no handle. Pure Python (no bpy), tested headless."""
from dataclasses import dataclass

from .panel_layout import CARD, HINT, LABEL, SCROLL_WIDTH, TITLE, TOGGLE, WARN, PanelSpec, Widget, divider, grid, hint, section, side_handle
from .panel_widgets import pager, scrollbar

PAGE_ROWS = 5                       # names per page of the gun's lists (hide.LIST_ROWS)

SPEC = PanelSpec(560, 760, meters_per_pixel=0.00035)        # about 20 x 27 cm at scale 1
TOOLS = (('RESET', "Reset"), ('PLACE', "Place"), ('MIRROR', "Mirror pose"), ('LOOK', "Look"),
         ('CLIPPING', "Fix clipping"), ('DUPLICATE', "Duplicate"), ('HIDE', "Hide"), ('MEASURE', "Measure"),
         ('MATERIAL', "Material"))
TOOL_LABELS = dict(TOOLS)
HINTS = {'RESET': "Shoot a bone or object. Hold A here to pick several.",
         'PLACE': "Shoot a thing, then a spot. Keep the trigger held and turn your wrist to rotate it.",
         'MIRROR': "Pose mode: shoot a bone; its pose goes to the other side.",
         'LOOK': "Shoot the character, then what to look at.",
         'CLIPPING': "Shoot a thing, then the surface it should sit on.",
         'DUPLICATE': "Shoot a thing, then click spots to paste copies, or drag the first shot out.",
         'HIDE': "Shoot a thing to hide it. Press a name to unhide it.",
         'MEASURE': "Shoot two points.",
         'MATERIAL': "Pick a material, then shoot a thing. Eyedrop: the next shot picks one up."}
CHANNELS = (('location', "Location"), ('rotation', "Rotation"), ('scale', "Scale"))
LEFT, WIDTH, OPTIONS_TOP = 26, 508, 400
HANDLES_TOP, HANDLES_HEIGHT = 300, 160        # Edit: the two small handles, at the middle of each side


@dataclass(frozen=True)
class GunModel:
    """What the menu shows (plain values: equal models need no redraw)."""
    tool: str = 'PLACE'
    note: str = ""              # what to shoot next, a result, or why a shot was refused
    warn: bool = False
    channels: tuple = ()        # RESET: the lit channels
    editing: bool = False       # the menu's two handles show (move, scale)
    copying: bool = False       # DUPLICATE: something is picked
    names: tuple = ()           # HIDE: hidden objects; MATERIAL: materials (one page)
    page: int = 0
    pages: int = 1
    total: int = 0
    material: str = ""
    eyedrop: bool = False


def _cards(prefix, items, action, lit, columns):
    return grid(prefix, items, LEFT, OPTIONS_TOP, WIDTH, columns, 64, lambda index, item, x, y, w, h: Widget(
        f"{prefix}_{item[0]}", CARD, x, y, w, h, label=item[1], size=26, action=(action, item[0]), active=item[0] in lit))


def _list(prefix, model, action, page_action, empty):
    """A page of names, and the pager when there are more."""
    if not model.names:
        return [hint(prefix + "_empty", empty, LEFT, OPTIONS_TOP + 70, WIDTH)]
    rows = [Widget(f"{prefix}_row_{index}", CARD, LEFT, OPTIONS_TOP + 62 + index * 44, WIDTH - SCROLL_WIDTH - 12, 40, label=name, size=22,
                   style='left', action=(action, name), active=name == model.material)
            for index, name in enumerate(model.names)]
    if model.pages > 1:
        rows += scrollbar(prefix + "_scroll", LEFT + WIDTH - SCROLL_WIDTH, OPTIONS_TOP + 62, PAGE_ROWS * 44 - 4, model.page,
                          model.pages - 1, page_action, area=(LEFT, OPTIONS_TOP + 62, WIDTH - SCROLL_WIDTH - 12, PAGE_ROWS * 44 - 4))
        rows += pager(prefix, LEFT, OPTIONS_TOP + 284, WIDTH, model.page, model.pages, page_action, height=40, size=22)
    return rows


def _options(model):
    if model.tool == 'RESET':
        return _cards("gun_reset", CHANNELS, "gun_reset", model.channels, 3)
    if model.tool == 'DUPLICATE':
        return [Widget("gun_copy_reset", CARD, LEFT, OPTIONS_TOP, WIDTH, 64, label="Reset: pick another", size=26,
                       action=("gun_copy_reset",), enabled=model.copying)]
    if model.tool == 'HIDE':
        return [Widget("unhide_all", CARD, LEFT, OPTIONS_TOP, WIDTH, 52, label=f"Unhide all ({model.total})", size=24,
                       action=("unhide_all",), enabled=model.total > 0)] + _list(
            "gun_hidden", model, "unhide_one", "hide_page", "Nothing is hidden")
    if model.tool == 'MATERIAL':
        return [Widget("gun_eyedrop", TOGGLE, LEFT, OPTIONS_TOP, WIDTH, 52, label="Eyedrop", size=24,
                       action=("gun_eyedrop",), active=model.eyedrop)] + _list(
            "gun_material", model, "gun_material", "gun_material_page", "This file has no materials")
    return []


def build(model):
    """All widgets, back to front."""
    widgets = [Widget("gun_title", LABEL, LEFT, 16, WIDTH - (320 if model.editing else 160), 40,
                      label="Edit menu" if model.editing else "Tool gun: " + TOOL_LABELS[model.tool], size=26, style=TITLE),
               Widget("gun_edit", TOGGLE, LEFT + WIDTH - 150, 12, 150, 46, label="Edit", size=22, action=("gun_edit",),
                      active=model.editing)]
    if model.editing:
        widgets += [Widget("gun_edit_reset", CARD, LEFT + WIDTH - 310, 12, 150, 46, label="Reset place", size=22,
                           action=("gun_edit_reset",)),
                    side_handle('LEFT', SPEC.width, HANDLES_TOP, HANDLES_HEIGHT),
                    side_handle('RIGHT', SPEC.width, HANDLES_TOP, HANDLES_HEIGHT)]
    widgets += grid("gun_tool", TOOLS, LEFT, 66, WIDTH, 3, 64, lambda index, item, x, y, w, h: Widget(
        "gun_tool_" + item[0], CARD, x, y, w, h, label=item[1], size=22, action=("gun_tool", item[0]),
        active=item[0] == model.tool), gap_x=12)
    widgets += [hint("gun_hint", HINTS[model.tool], LEFT, 294, WIDTH, 54, size=22),
                divider("gun_line", LEFT, 354, WIDTH), section("gun_options", "Settings", LEFT, 364, WIDTH)]
    widgets += _options(model)
    widgets.append(hint("gun_note", model.note, LEFT, 726, WIDTH, 28, style=WARN if model.warn else HINT, size=22))
    return widgets
