# SPDX-License-Identifier: GPL-3.0-or-later
"""Collapsible cards (and sub-cards, status lines, action rows, hints) for add-on sidebar panels, shared by
Digit's Assorted Tools, Digit's Modifiers, Render Presets and Pose Reset (an installed extension can't import its neighbour). This file is the ONE source;
sync_shared.py copies it into each extension folder as ui_cards.py.
"""
import re
import textwrap
from contextlib import contextmanager


def header_right(header, text):
    """A grey summary at the right of a card or section header (what you see while it is folded). Nothing for
    empty text. The sub-row is right aligned and greyed; Blender cuts the title short, not the summary."""
    if text:
        cell = header.row()
        cell.alignment = 'RIGHT'
        cell.active = False
        cell.label(text=text)


def header_button(header, operator, icon, **props):
    """An icon-only operator button in a header row (a click on it runs the operator and does not fold the
    panel). Returns the operator properties, so callers can set more."""
    op = header.operator(operator, text="", icon=icon)
    for name, value in props.items():
        setattr(op, name, value)
    return op


def card(layout, idname, title, default_closed=False, icon='NONE', right=None, button=None, extra=None):
    """A collapsible card (Blender's layout panel; open/closed is remembered per region by
    `idname`). Draws the header (title, grey `right` summary, optional `button` = (operator, icon) at the very
    right, or `extra(header)` to draw anything else there, e.g. a modifier's viewport eye) and returns the body
    layout, or None while it is collapsed:

        body = card(layout, "my_addon_tools", "Tools", right="3 of 5 on")
        if body:
            body.operator(...)
    """
    header, body = layout.panel(idname, default_closed=default_closed)
    header.label(text=title, icon=icon)
    header_right(header, right)
    if button:
        header_button(header, *button)
    if extra:
        extra(header)
    return body


# The three levels, three looks: card = header strip at panel level, section = framed box with a header,
# group = plain arrow row inside a frame. A frame is never put inside a frame: while a Selected box is being
# drawn (inside_frame), section() gives a group.
_frame_depth = 0


@contextmanager
def inside_frame():
    """Everything drawn in this block sits in a framed box already: section() then draws plain groups."""
    global _frame_depth
    _frame_depth += 1
    try:
        yield
    finally:
        _frame_depth -= 1


def framed(layout):
    """A framed box (the look of every section and of the Selected card's object boxes): returns the column in it."""
    return layout.box().column(align=True)


def group(layout, idname, title, default_closed=False, icon='NONE', right=None, button=None, extra=None):
    """A plain arrow group (no frame) for inside a frame: closed or open by `default_closed`, body in split
    property layout. Returns the body or None while collapsed."""
    body = card(layout, idname, title, default_closed, icon, right, button, extra)
    if body is not None:
        body.use_property_split = True
        body.use_property_decorate = False
    return body


def sub_card(layout, idname, title, default_closed=True, icon='NONE', right=None, button=None):
    """A card inside a card (Options, Advanced...), drawn in its own frame (a plain group when already inside
    one): closed by default, its body uses split property layout. Returns the body or None while collapsed."""
    if not _frame_depth:
        layout = framed(layout)
    return group(layout, idname, title, default_closed, icon, right, button)


def section(layout, idname, title, icon='NONE', default_closed=False, right=None, button=None):
    """A titled section inside a card: a sub_card that is OPEN by default (commonly used options). Pass
    default_closed=True for Advanced / rarely used ones. The idname must be unique per region: prefix it with
    the add-on and tool, e.g. "setups_camera_rig_lens". `right` = grey state summary, `button` = (operator, icon)
    icon-only header button (Deploy's +)."""
    return sub_card(layout, idname, title, default_closed, icon, right, button)


def sub_heading(layout, text, icon='NONE'):
    """A small heading with a line under it, for parts of a section that don't fold (Key / Fill / Rim)."""
    col = layout.column(align=True)
    col.label(text=text, icon=icon)
    col.separator(type='LINE')
    return col


def is_bool(owner, name):
    """True when `name` (a registered property, or an ID custom property like '["x"]') is a single checkbox."""
    if name.startswith('["'):
        return isinstance(owner.get(name[2:-2]), bool)
    try:
        prop = owner.bl_rna.properties.get(name)
    except AttributeError:   # not a real Blender struct (the test fake)
        return False
    return prop is not None and prop.type == 'BOOLEAN' and not prop.is_array


def smart_prop(layout, owner, name, text=None, **kwargs):
    """layout.prop that stays readable inside a split layout: a checkbox is drawn full width (split rows push it
    into the right column, where its label gets cut off) and an expanded enum as one horizontal row."""
    vertical = kwargs.pop("vertical", False)
    if kwargs.get("expand") and not vertical:
        layout = layout.row(align=True)
        layout.use_property_split = False
    elif is_bool(owner, name):
        layout = layout.column(align=True)
        layout.use_property_split = False
    if text is None:
        layout.prop(owner, name, **kwargs)
    else:
        layout.prop(owner, name, text=text, **kwargs)


def prop_group(layout, owner, items, split=True):
    """Related properties in one aligned column. `items` are property names or (name, label) pairs;
    a None item draws a small gap. Checkboxes are drawn full width (a split row pushes them into the
    right column, where the label gets cut off). Returns the column."""
    col = layout.column(align=True)
    if split:
        col.use_property_split, col.use_property_decorate = True, False
    for item in items:
        if item is None:
            col.separator()
            continue
        name, label = (item, None) if isinstance(item, str) else item
        smart_prop(col, owner, name, label)
    return col


def toggles(layout, owner, items, columns=2):
    """Checkboxes in a compact grid, never split (names or (name, label) pairs; keep labels short).
    Returns the grid."""
    grid = layout.grid_flow(columns=columns, align=True)
    grid.use_property_split = False
    for item in items:
        name, label = (item, None) if isinstance(item, str) else item
        smart_prop(grid, owner, name, label)
    return grid


def choice_row(layout, owner, name, text=None, label=None, factor=0.3, columns=None, vertical=False):
    """An enum as one horizontal row of buttons (not Blender's tall split list), or a grid of `columns` for
    many choices. With `label` the row sits right of a left label column (`factor` of the width), so longer
    words fit: Legs | Plantigrade | Digitigrade. `vertical` stacks the choices, one full-width button per
    line (for long names or many choices, e.g. a multi-select flag enum)."""
    if vertical:
        column = layout.column(align=True)
        column.use_property_split = False
        smart_prop(column, owner, name, text, expand=True, vertical=True)
        return
    if label:
        layout = layout.split(factor=factor, align=True)
        layout.label(text=label)
    if columns:
        layout = layout.grid_flow(columns=columns, align=True)
        layout.use_property_split = False
    smart_prop(layout, owner, name, text, expand=True)


STATUS_MAX_CHARS = 35


def status(layout, text, icon='INFO'):
    """The status line at the top of a card: one short line (keep it under ~35 characters); a longer one
    wraps onto more lines instead of being cut off."""
    if len(text) > STATUS_MAX_CHARS:
        wrapped(layout, text, STATUS_MAX_CHARS - 1, icon)
    else:
        layout.label(text=text, icon=icon)


def friendly_name(name):
    """A name as plain words: "_" and "." become spaces, CamelCase is split ("Body_Mesh.001" -> "Body Mesh 001",
    "CamRig_Dolly" -> "Cam Rig Dolly")."""
    name = re.sub(r"[_.]+", " ", name)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return " ".join(name.split())


def object_box(layout, idname, title, default_closed=False, icon='NONE', right=None):
    """A framed, collapsible box headed by an object's plain-words name ("Camera Rig · Dolly"; the whole header
    row is the click target), for the context actions of the current selection: compact, buttons go full width
    under the heading. Returns the body or None while collapsed."""
    return card(framed(layout), idname, title, default_closed, icon, right)


def action_row(layout, scale=1.3):
    """A row for a card's main buttons (bigger, aligned)."""
    row = layout.row(align=True)
    row.scale_y = scale
    return row


DEFAULT_WIDTH_CHARS = 34   # about the default sidebar width (~280 px)
PIXELS_PER_CHAR = 7.0
SIDE_PADDING = 50          # px lost to margins and the icon


def width_chars(context=None):
    """How many characters of label text fit the region of `context` (the default sidebar width without one)."""
    region = getattr(context, "region", None)
    if region is None:
        return DEFAULT_WIDTH_CHARS
    scale = getattr(getattr(getattr(context, "preferences", None), "view", None), "ui_scale", 1.0) or 1.0
    return max(16, int((region.width / scale - SIDE_PADDING) / PIXELS_PER_CHAR))


def wrapped(layout, text, width=None, icon='NONE', context=None):
    """Long text as label lines that fit the region (`width` in characters, else from `context`'s region).
    The icon sits on the first line only. Returns the column."""
    width = width or width_chars(context)
    col = layout.column(align=True)
    for i, line in enumerate(textwrap.wrap(text, width) or [""]):
        col.label(text=line, icon=icon if i == 0 else 'NONE')
    return col


def hints(layout, texts, context=None):
    """Why buttons are disabled etc.: small greyed info lines, wrapped to fit (empty texts skipped)."""
    texts = [t for t in dict.fromkeys(texts) if t]
    if texts:
        col = layout.column(align=True)
        col.active = False
        col.scale_y = 0.8
        for t in texts:
            wrapped(col, t, icon='INFO', context=context)


def progress(layout, done, total, text=None):
    """A progress bar, "3 of 6" by default."""
    layout.progress(factor=done / total if total else 0.0, type='BAR', text=text or f"{done} of {total}")


def step_row(layout, number, text, state, operator, rebuild_operator=None, stale=False, rebuild_props=None, **props):
    """One numbered step of a real sequence. `state` is 'done' (tick, plus an icon-only rebuild button when
    `rebuild_operator` is given, with `rebuild_props` set; red when `stale`), 'next' (big button) or 'later'
    (greyed). Returns the operator properties of the step button."""
    row = layout.row(align=True)
    row.active = state != 'later'
    row.scale_y = 1.3 if state == 'next' else 1.0
    row.label(text="", icon='CHECKMARK' if state == 'done' else 'NONE')
    op = row.operator(operator, text=f"{number}  {text}", **props)
    if state == 'done' and rebuild_operator:
        rebuild = row.row(align=True)
        rebuild.alert = stale
        rebuild_op = rebuild.operator(rebuild_operator, text="", icon='FILE_REFRESH')
        for name, value in (rebuild_props or {}).items():
            setattr(rebuild_op, name, value)
    return op


DIFF_INLINE_CHARS = 24   # longest "old → new" that fits right of its label; longer ones go on their own two lines
LINE_CHARS = 34


def poll_message(cls, why):
    """For an operator poll: show `why` (the reason it can't run) as the greyed-out button's tooltip.
    True when there is no reason."""
    if why:
        cls.poll_message_set(why)
    return not why


def shorten(text, chars=LINE_CHARS):
    """`text` cut to `chars` with an ellipsis at the front (the end of a path or name is the telling part)."""
    return text if len(text) <= chars else "…" + text[-(chars - 1):]


def draw_grey(layout, text):
    """One greyed-out line of text (shortened to fit)."""
    grey = layout.column()
    grey.active = False
    grey.label(text=shorten(text))


def diff_row(layout, label, old, new):
    """A changed setting: its name on the left, "old → new" on the right; values too long for that go under the
    name, old on one line and → new on the next."""
    change = f"{old} → {new}"
    if len(change) <= DIFF_INLINE_CHARS:
        split = layout.split(factor=0.55)
        split.label(text=label)
        cell = split.row()
        cell.alignment = 'RIGHT'
        cell.label(text=change)
        return
    col = layout.column(align=True)
    col.label(text=label)
    col.label(text=shorten(f"   {old}"))
    col.label(text=shorten(f"→ {new}"))


def count_on(owner, names):
    """"2 of 5 on": how many of the boolean properties `names` of `owner` are on (for folded option headers)."""
    on = sum(1 for name in names if getattr(owner, name))
    return f"{on} of {len(names)} on"


def setting_label(owner, name):
    """A setting as Blender itself names it (`bl_rna.properties[name].name`), else the plain-words property
    name."""
    try:
        return owner.bl_rna.properties[name].name
    except (AttributeError, KeyError):
        return friendly_name(name).title()


def enum_label(owner, name):
    """The shown name of an enum property's current value ("Fit Box (move)"), for header summaries."""
    value = getattr(owner, name, "")
    try:
        return owner.bl_rna.properties[name].enum_items[value].name
    except (AttributeError, KeyError, TypeError):
        return value if isinstance(value, str) else ""


def setting_value(owner, name, value):
    """A setting's value as plain words: On / Off for a checkbox, the shown name of an enum item, else a short number."""
    if isinstance(value, bool):
        return "On" if value else "Off"
    try:
        info = owner.bl_rna.properties[name]
        if info.type == 'ENUM':
            return info.enum_items[value].name
    except (AttributeError, KeyError):
        pass
    return f"{value:.4g}" if isinstance(value, float) else str(value)
