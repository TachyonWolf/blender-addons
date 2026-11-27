# SPDX-License-Identifier: GPL-3.0-or-later
"""Test helper (not shipped): a fake UILayout that records calls, for headless draw smoke tests (`blender -b` has
no real UILayout). Tests import it by path from Addons/shared_addon/.

    from fake_layout import FakeLayout, draw_all
    fake = FakeLayout(); card.draw_card(fake, context)
    assert not fake.duplicate_panels
"""


def check_property(owner, name):
    """A typo'd property name would only show as an error in Blender's UI: catch it here."""
    if isinstance(owner, FakeLayout):
        return
    if name.startswith('["'):
        assert name[2:-2] in owner, f"custom property {name} missing on {owner!r}"
    else:
        assert hasattr(owner, name), f"{owner!r} has no property {name!r}"


LABEL_BUDGET = 22    # longest prop label / button text that fits a split row at the default sidebar width (~280 px)
FULL_BUTTON_BUDGET = 30   # longest full-width button text
RIGHT_BUDGET = 24    # longest grey header summary / diff value (it shares the row with the title)
VAGUE_TITLES = ("List", "Issues", "Items")   # a foldout title must say what it holds ("Objects", "Bones", "Modifiers")
LINE_BUDGET = 36     # longest status / hint line (label lines)


def prop_name(owner, prop):
    """The label Blender draws for a property that has no `text=`."""
    if isinstance(owner, FakeLayout):
        return ""
    if prop.startswith('["'):
        return prop[2:-2]
    return owner.bl_rna.properties[prop].name


def prop_is_checkbox(owner, prop):
    if isinstance(owner, FakeLayout):
        return False
    if prop.startswith('["'):
        return isinstance(owner.get(prop[2:-2]), bool)
    info = owner.bl_rna.properties.get(prop)
    return info is not None and info.type == 'BOOLEAN' and not info.is_array


def operator_label(idname):
    """bl_label of "module.name" (needs bpy; empty when unknown)."""
    try:
        import bpy
        module, name = idname.split(".")
        return getattr(getattr(bpy.ops, module), name).get_rna_type().name
    except Exception:  # noqa: BLE001
        return ""


OPERATOR_KWARGS = {"text", "text_ctxt", "translate", "icon", "emboss", "depress", "icon_value", "search_weight"}
"""The only keyword arguments Blender's UILayout.operator() takes; operator properties are set as attributes."""


class FakeLayout:
    """Accepts any layout call/attribute; remembers panel idnames (shared across children via `root`) and
    every text drawn (`root.texts`: (call, text, in a split row, property is a checkbox)) for lint()."""

    def __init__(self, root=None, collapsed=False, property_split=False, cells=1, in_box=False, header=False, alignment=None, in_row=False):
        self.root = root or self
        self.in_row = in_row
        self.property_split, self.cells, self.in_box, self.header, self.alignment = property_split, cells, in_box, header, alignment
        if root is None:
            self.panels, self.duplicate_panels, self.calls, self.collapsed = [], [], [], collapsed
            self.boxes = 0   # layout.box() calls: every section / object box is framed
            self.nested_boxes = 0   # layout.box() inside a box: a frame in a frame
            self.texts = []
            self.right_texts = []   # labels drawn right aligned (header summaries, diff values)
            self.header_titles = []  # labels drawn in a panel header (card / section / group titles)
            self.header_ops = []    # operators drawn in a panel header (idname, text)
            self.header_props = []  # properties drawn in a panel header (name, text)
            self.expanded = []      # expanded enums: (property name, drawn in a row, grid cells)

    def child(self, **kwargs):
        """A sub-layout that keeps the split / frame state of this one."""
        state = dict(property_split=self.property_split, cells=self.cells, in_box=self.in_box, in_row=self.in_row)
        state.update(kwargs)
        return FakeLayout(self.root, **state)

    def panel(self, idname, default_closed=False):
        root = self.root
        if idname in root.panels:
            root.duplicate_panels.append(idname)
        root.panels.append(idname)
        root.texts.append(("panel", "", False, False, 1))
        return self.child(header=True), (None if root.collapsed else self.child())

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        root = self.root

        def call(*args, **kwargs):
            if name in ("prop", "prop_search") and len(args) >= 2:
                check_property(*args[:2])
            if name == "operator" and set(kwargs) - OPERATOR_KWARGS:
                raise TypeError(f"UILayout.operator(): invalid keyword argument(s) {sorted(set(kwargs) - OPERATOR_KWARGS)}")
            root.calls.append((name, args, kwargs))
            self.record(name, args, kwargs)
            cells = kwargs.get("columns", 2) if name == "grid_flow" else self.cells
            in_row = name == "row" or (self.in_row and name not in ("column", "grid_flow", "box"))
            return self.child(cells=cells, in_box=self.in_box or name == "box", header=self.header and name != "box", in_row=in_row)
        return call

    def record(self, name, args, kwargs):
        if name == "box":
            self.root.boxes += 1
            if self.in_box:
                self.root.nested_boxes += 1
        elif name == "label":
            text = kwargs.get("text", args[0] if args else "")
            if self.alignment == 'RIGHT' and text:
                self.root.right_texts.append(text)
            elif self.header:
                self.root.header_titles.append(text)
            self.root.texts.append(("label", text, False, False, 1))
        elif name in ("prop", "operator", "menu"):
            text = kwargs.get("text")
            if self.header and name == "operator" and args:
                self.root.header_ops.append((args[0], text))
            if self.header and name == "prop" and len(args) >= 2:
                self.root.header_props.append((args[1], text))
            is_checkbox = False
            if name == "prop" and len(args) >= 2:
                owner, prop = args[:2]
                if kwargs.get("expand"):
                    self.root.expanded.append((prop, self.in_row, self.cells))
                if text is None:
                    text = prop_name(owner, prop)
                is_checkbox = (not kwargs.get("toggle") and not kwargs.get("expand")
                               and prop_is_checkbox(owner, prop))
            elif name == "operator" and text is None:
                text = operator_label(args[0]) if args else ""
            self.root.texts.append((name, text or "", self.property_split and name == "prop", is_checkbox, self.cells))

    def __setattr__(self, name, value):
        if name in ("root", "panels", "duplicate_panels", "calls", "collapsed", "boxes", "texts", "property_split", "cells", "in_box",
                    "header", "alignment", "nested_boxes", "in_row", "expanded", "right_texts", "header_ops", "header_props",
                    "header_titles"):
            object.__setattr__(self, name, value)
        elif name == "use_property_split":
            object.__setattr__(self, "property_split", bool(value))

    def __iter__(self):
        return iter(())


def draw_both(draw, *args):
    """Run a draw function open and collapsed; returns the open run's FakeLayout. Raises on duplicate idnames."""
    for collapsed in (True, False):
        fake = FakeLayout(collapsed=collapsed)
        draw(fake, *args)
        assert not fake.duplicate_panels, f"duplicate layout-panel idnames: {fake.duplicate_panels}"
        assert not fake.nested_boxes, f"{fake.nested_boxes} box(es) inside a box (a frame in a frame)"
    return fake


def button_budget(label_budget, cells):
    """Longest button text in a grid of `cells` columns: a full-width button fits ~30 characters, each
    column of a grid is narrower (16, 10)."""
    return FULL_BUTTON_BUDGET if cells <= 1 else 16 if cells == 2 else 10


def lint(fake, label_budget=LABEL_BUDGET, line_budget=LINE_BUDGET):
    """Readability problems of a drawn fake layout at ~280 px: a list of strings (empty = fine).
    Prop labels in split rows and button texts must fit `label_budget` characters, label lines `line_budget`,
    and checkboxes must not be drawn in a split row (they get pushed right and cut off). Header summaries
    (right aligned labels) must stay short, a header button must be icon only, and a title must say what it holds."""
    problems = []
    for text in fake.header_titles:
        if text in VAGUE_TITLES:
            problems.append(f"foldout title says nothing about what it holds: {text!r}")
    for text in fake.right_texts:
        if len(text) > RIGHT_BUDGET:
            problems.append(f"right aligned text too long ({len(text)}): {text!r}")
    for idname, text in fake.header_ops:
        if text != "":
            problems.append(f"header button {idname} must be icon only")
    for kind, text, split, checkbox, cells in fake.texts:
        if kind == "label" and len(text) > line_budget:
            problems.append(f"label too long ({len(text)}): {text!r}")
        elif kind in ("operator", "menu") and len(text) > button_budget(label_budget, cells):
            problems.append(f"button too long for {cells} column(s) ({len(text)}): {text!r}")
        elif kind == "prop" and split and len(text) > label_budget:
            problems.append(f"split label too long ({len(text)}): {text!r}")
        if checkbox and split:
            problems.append(f"checkbox in a split row: {text!r}")
    return problems
