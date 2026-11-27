#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exports every VR panel's screens, drawn by the add-on's own layout and draw code, into one web page (a clickable copy
of the headset UI for design work outside VR). Plain python3 (numpy, Pillow, fontTools); no Blender, no GPU.

    python3 export_ui.py                 the page: build/digits_vr_ui.html
    python3 export_ui.py --check         coverage check only (the fast tests run it)
    python3 export_ui.py --overflow      list every text wider than its widget
    python3 export_ui.py --font PATH     Blender's UI font (default: found next to the `blender` on PATH)

Which panels exist comes from panels.PANELS (read from the source); each needs a scene here (SCENES). Screens are found by
pressing every widget of every screen found so far: page / pop-up / mode switches first, then one changed value
(a toggle, a choice) at a time, up to MAX_SCREENS per panel. The page draws the recorded shapes, text and icons only."""
import argparse
import ast
import base64
import dataclasses
import datetime
import glob
import gzip
import heapq
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import record                                       # noqa: E402  (after the path)
import fake_scene as scene                          # noqa: E402
from addon_import import ADDON, load                # noqa: E402

panel_layout, desk_layout, help_text = load("panel_layout"), load("desk_layout"), load("help_text")
keyboard_layout = load("keyboard_layout")
BUILD = os.path.join(HERE, "build")
PAGE = os.path.join(HERE, "page.html")
MAX_SCREENS = 3000              # per panel, at most
MAX_VALUE_STEPS = 1             # values changed away from the panel's first models: a press that would change a second
                                # one shows that change alone (from the screen's base, its pages and pop-ups only)


# ---- the panels, read from the add-on's source --------------------------------------------------------------------------

def _source(name):
    with open(os.path.join(ADDON, name + ".py"), encoding="utf-8") as handle:
        return ast.parse(handle.read())


def panel_modules():
    """Module names of panels.PANELS, in its order."""
    for node in _source("panels").body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "PANELS" for target in node.targets):
            return [element.value.id for element in node.value.elts]
    raise SystemExit("panels.PANELS not found")


def panel_facts(module):
    """(name, layout module, pinnable, own body_rects) of the Panel subclass in `module`."""
    tree = _source(module)
    layout = next(alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                  for alias in node.names if alias.asname == "layout")
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(getattr(base, "id", "") == "Panel" for base in node.bases):
            values = {target.id: statement.value for statement in node.body if isinstance(statement, ast.Assign)
                      for target in statement.targets if isinstance(target, ast.Name)}
            pinnable = values.get("pinnable")
            methods = {statement.name for statement in node.body if isinstance(statement, ast.FunctionDef)}
            return (values["name"].value, layout, pinnable.value if pinnable is not None else True, "body_rects" in methods)
    raise SystemExit(f"no Panel class in {module}.py")


# ---- pressing a widget: what the page shows next -------------------------------------------------------------------------

NAV_KINDS = {"tab", "popup", "mode", "selected_sub", "rig_picker", "pda_tab_step", "pda_edit", "gun_tool",
             "gun_edit", "page", "paste", "dd_close", "spot_page"}


def is_nav(action):
    return action[0] in NAV_KINDS


def _fields(model):
    return {field.name for field in dataclasses.fields(model)}


def _set_value(model, kind, arguments):
    """A press that sets or flips one plain field of the model (a toggle, a choice card), else None."""
    if kind == "toggle" and arguments and arguments[0] in _fields(model) and isinstance(getattr(model, arguments[0]), bool):
        return replace(model, **{arguments[0]: not getattr(model, arguments[0])})
    if kind in _fields(model):
        current = getattr(model, kind)
        if not arguments and isinstance(current, bool):
            return replace(model, **{kind: not current})
        if len(arguments) == 1 and type(arguments[0]) is type(current):
            return replace(model, **{kind: arguments[0]})
    return None


def _flip_axis(axes, axis):
    return tuple((name, not on if name == axis and works else on, works) for name, on, works in axes)


def tools_step(model, kind, arguments):
    """The tool rows' presses (desk Tools page and Tool options panel)."""
    if kind == "popup":
        return replace(model, popup="" if model.popup == arguments[0] else arguments[0])
    if kind == "mode":
        return replace(model, mode=arguments[0], popup="")
    if kind in ("edit_tool", "edit_select"):
        return replace(model, edit=replace(model.edit, **{kind[5:] if kind == "edit_select" else "tool": arguments[0]}))
    if kind == "grab_order":
        how, index, *step = arguments
        order = grab_order.toggled(model.grab_order, index) if how == "toggle" else grab_order.moved(model.grab_order, index, *step)
        return replace(model, grab_order=order)
    if kind == "grab_mode":        # each grab mode has its own order (settings per mode)
        return replace(model, grab_mode=arguments[0], grab_order=grab_order.DEFAULTS[arguments[0]])
    if kind == "sculpt_brush":
        return replace(model, sculpt=replace(model.sculpt, brush=arguments[0]))
    if kind == "sculpt_mirror":
        index = tool_rows.AXES.index(arguments[0])
        return replace(model, sculpt=replace(model.sculpt, mirror=tuple(
            not on if number == index else on for number, on in enumerate(model.sculpt.mirror))))
    if kind == "mirror":
        return replace(model, mirror=_flip_axis(model.mirror, arguments[0]))
    if kind == "gp_layer_set":
        return replace(model, gp_layer_index=arguments[0], gp_layer=model.gp_layers[arguments[0]])
    if kind == "color_mode":
        return replace(model, picker=replace(model.picker, mode=arguments[0]))
    return _set_value(model, kind, arguments)


tool_rows, grab_order = load("tool_rows"), load("grab_order")


def _closes_list(model, kind, changed):
    """A pick in an open dropdown list closes it (desk_actions.perform)."""
    if changed is not None and model.popup in desk_layout.LIST_POPUPS and kind not in ("popup", *tool_rows.KEEP_OPEN):
        return replace(changed, popup="")
    return changed


def desk_step(model, kind, arguments):
    changed = None
    if kind == "tab":
        tab = arguments[0]
        if tab == 'options':            # the Options tab opens its first section (later: the one used last)
            tab = model.tab if model.tab in desk_layout.OPTION_IDS else desk_layout.OPTION_IDS[0]
        changed = replace(model, tab=tab, popup="")
    elif kind == "selected_sub":
        changed = replace(model, selected_sub=arguments[0], popup="")
    elif kind == "rig_picker" and model.rig is not None:
        changed = replace(model, rig=replace(model.rig, picker_open=not model.rig.picker_open))
    elif kind == "modifier":
        changed = replace(model, modifiers=tuple((name, label, not shown if index == arguments[0] else shown)
                                                 for index, (name, label, shown) in enumerate(model.modifiers)))
    elif kind == "asset_library":
        changed = replace(model, assets=replace(model.assets, library=arguments[0]))
    elif kind == "asset_catalog":
        label = next(text for key, text in model.assets.chips if key == arguments[0])
        changed = replace(model, assets=replace(model.assets, catalog=arguments[0], catalog_label=label), popup="")
    else:
        changed = tools_step(model, kind, arguments)
    return _closes_list(model, kind, changed)


def tool_options_step(model, kind, arguments):
    return _closes_list(model, kind, tools_step(model, kind, arguments))


def pda_step(model, kind, arguments):
    if kind == "pda_edit":
        return replace(model, edit=not model.edit, selected=-1, armed=False)
    if kind == "pda_tab_step" and model.tabs:
        return replace(model, current=(model.current + arguments[0]) % len(model.tabs), selected=-1)
    if kind == "pda_slot" and model.edit:
        return replace(model, selected=-1 if model.selected == arguments[0] else arguments[0])
    if kind == "pda_delete":
        return replace(model, armed=not model.armed)
    return None


KEYBOARD_KEYS = ("shift", "caps", "ctrl", "page")


def keyboard_step(model, kind, arguments):
    """Shift, Caps, Ctrl and the page key through keyboard_layout.apply; Paste held = the history list."""
    if kind in KEYBOARD_KEYS:
        edit = keyboard_layout.Edit(model.text, len(model.text), None, model.page, model.shift, model.ctrl)
        if kind == "page":
            edit = replace(edit, page=keyboard_layout.SYMBOLS if model.page == keyboard_layout.LETTERS else keyboard_layout.LETTERS)
        else:
            edit = keyboard_layout.apply(edit, (kind, *arguments))[0]
        return replace(model, page=edit.page, shift=edit.shift, ctrl=edit.ctrl)
    if kind == "paste":
        return replace(model, dropdown=("Wooden chair", "Table top", "Lamp shade"))
    if kind == "dd_close":
        return replace(model, dropdown=None)
    return None


def viewpoints_step(model, kind, arguments):
    if kind == "spot_page":
        names = ("Front", "Close-up", "Top", "Desk", "Doorway", "Overview", "Behind")
        first, page = load("viewpoint_layout").page_slice(model.page + arguments[0], model.total)
        return replace(model, names=names[first:first + load("viewpoint_layout").ROWS], first=first, page=page)
    return None


def gun_step(model, kind, arguments):
    if kind == "gun_tool":
        base = scene.gun_variants(scene.gun_model()).get(arguments[0], scene.gun_model())
        return replace(base, tool=arguments[0], editing=model.editing)
    if kind == "gun_reset":
        lit = set(model.channels) ^ {arguments[0]}
        return replace(model, channels=tuple(sorted(lit)))
    if kind in ("gun_edit", "gun_eyedrop"):
        field = "editing" if kind == "gun_edit" else "eyedrop"
        return replace(model, **{field: not getattr(model, field)})
    return None


def help_step(model, kind, arguments):
    if (kind, *arguments) == ("toggle", "help_on"):
        return replace(model, tooltips=not model.tooltips)
    return None


def _camera_seeds():
    return [scene.camera_model(), replace(scene.camera_model(), camera="", note="No scene camera")]


def _desk_seeds():
    return [scene.desk_model()]


def _tool_options_seeds():
    """One per mode: the panel shows Blender's mode (it has no mode buttons)."""
    first = scene.tool_options_model(scene.desk_model())
    return [replace(first, mode=mode) for mode, _label in desk_layout.MODES]


def _pda_seeds():
    return [scene.pda_model(desk_layout.build(scene.desk_model()))]


@dataclasses.dataclass(frozen=True)
class Scene:
    title: str
    seeds: object               # () -> [first models]
    step: object = None         # (model, kind, arguments) -> next model or None


SCENES = {"desk": Scene("Desk", _desk_seeds, desk_step),
          "tool_options": Scene("Tool options", _tool_options_seeds, tool_options_step),
          "viewpoints": Scene("Viewpoints", lambda: [scene.viewpoints_model()], viewpoints_step),
          "find": Scene("Find", lambda: [scene.find_model()]),
          "pda": Scene("PDA", _pda_seeds, pda_step),
          "keyboard": Scene("Keyboard", lambda: [scene.keyboard_model()], keyboard_step),
          "tool_gun": Scene("Tool gun menu", lambda: [scene.gun_model()], gun_step),
          "camera_view": Scene("Cam view", _camera_seeds),
          "help": Scene("Help", lambda: [scene.help_model()], help_step)}
SHORTCUTS = (("Colour picker", "desk", dict(tab='tools', mode='PAINT_GREASE_PENCIL', popup='gp_color')),)


# ---- finding the screens ------------------------------------------------------------------------------------------------

class Panel:
    """One panel: how to build its widgets for a model, and its screens."""

    def __init__(self, module):
        self.name, layout_name, self.pinnable, own_body = panel_facts(module)
        self.layout = load(layout_name)
        self.scene = SCENES.get(self.name)
        self.own_body = own_body
        self._built, self.found, self.order = {}, {}, []

    def spec(self, model):
        return self.layout.spec_for(model.extra) if hasattr(self.layout, "spec_for") else self.layout.SPEC

    def body(self, model):
        spec = self.spec(model)
        if self.own_body:
            return lambda: self.layout.body_rects(model.extra)
        return lambda: panel_layout.frame_rects(spec.width, spec.height)

    def widgets(self, model):
        """The panel's widgets for `model` (cached: the search asks for the same models often)."""
        if model not in self._built:
            widgets = list(self.layout.build(model))
            if self.pinnable:
                widgets.append(panel_layout.pin_widget(self.spec(model).width, False))
            self._built[model] = widgets
        return self._built[model]

    def press(self, model, action):
        if not action or self.scene.step is None:
            return None
        return self.scene.step(model, action[0], tuple(action[1:]))

    def screen_of(self, model):
        """Index of the exported screen that shows `model`, or None. Models that look the same share one screen (a
        state the page cannot see, like the Grab tab's More fold on another tab, makes no new screen)."""
        return self.found.get(tuple(self.widgets(model)))

    def explore(self, limit, value_limit):
        """Screens (model, widgets, value steps, base) in the order found: fewer changed values first, then fewer presses.
        `base` = the same pages and pop-ups with no value changed (where a press that changes one more value starts)."""
        self.found, self.order, queue, counter = {}, [], [], 0
        for seed in self.scene.seeds():
            heapq.heappush(queue, (0, 0, counter, seed, seed))
            counter += 1
        seen = set()
        while queue and len(self.order) < limit:
            values, steps, _number, model, base = heapq.heappop(queue)
            widgets = self.widgets(model)
            key = tuple(widgets)
            if key in self.found:
                continue
            self.found[key] = len(self.order)
            self.order.append((model, widgets, values, base))
            for widget in widgets:
                target = self.press(model, widget.action) if widget.enabled else None
                if target is None or target in seen:
                    continue
                seen.add(target)
                nav = is_nav(widget.action)
                more = values + (0 if nav else 1)
                if more <= value_limit:
                    target_base = (self.press(base, widget.action) or base) if nav else base
                    heapq.heappush(queue, (more, steps + 1, counter, target, target if more == 0 else target_base))
                    counter += 1
        return self.order

    def target(self, model, base, widget):
        """(screen index or None, True when it is the press from `base` instead: the export has no screen for it)."""
        target = self.press(model, widget.action) if widget.enabled else None
        if target is None:
            return None, False
        index = self.screen_of(target)
        if index is None and base is not model:
            alone = self.press(base, widget.action)
            index = self.screen_of(alone) if alone is not None else None
            return index, index is not None
        return index, False


def describe(model, first):
    """A short name of a screen: what differs from the panel's first model."""
    parts = []
    for field in dataclasses.fields(model):
        value, base = getattr(model, field.name), getattr(first, field.name, None)
        if value == base or field.name in ("help_rows", "linked", "names"):
            continue
        if dataclasses.is_dataclass(value) and dataclasses.is_dataclass(base):
            parts += [f"{field.name}.{inner.name}={getattr(value, inner.name)!r}" for inner in dataclasses.fields(value)
                      if getattr(value, inner.name) != getattr(base, inner.name) and inner.name not in ("items", "picker")]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            parts.append(f"{field.name}={value!r}")
        else:
            parts.append(f"{field.name} changed")
    return ", ".join(parts) or "as it opens"


# ---- the data the page draws --------------------------------------------------------------------------------------------

class Tables:
    """Shared, de-duplicated tables: screens refer to entries by index."""

    def __init__(self):
        self.colours, self.shapes, self.texts, self.widgets, self.lists, self.rings = ({} for _ in range(6))

    @staticmethod
    def add(table, key, value=None):
        if key not in table:
            table[key] = (len(table), value if value is not None else key)
        return table[key][0]

    @staticmethod
    def listed(table):
        return [value for _index, value in sorted(table.values(), key=lambda entry: entry[0])]

    def colour(self, colour):
        colour = tuple(round(float(channel), 4) for channel in colour)
        return self.add(self.colours, colour)

    def fan(self, key, positions, colours):
        """A rounded rect as panel_draw tessellated it: centre, rim points, colours (triangles centre, rim i, rim i + 1)."""
        if key in self.shapes:
            return self.shapes[key][0]
        count = len(positions) // 3
        rim = [positions[3 * index + 1] for index in range(count)]
        centre = positions[0]
        assert all(positions[3 * index] == centre and positions[3 * index + 2] == rim[(index + 1) % count]
                   for index in range(count)), "panel_draw._fan changed its triangle order: update Tables.fan"
        flat = [round(centre[0], 2), round(centre[1], 2), self.colour(colours[0])]
        for index, point in enumerate(rim):
            flat += [round(point[0], 2), round(point[1], 2), self.colour(colours[3 * index + 1])]
        return self.add(self.shapes, key, flat)

    def events(self, events):
        """Recorded events -> the page's compact list (consecutive shapes / texts merged)."""
        out = []
        for event in events:
            kind = event[0]
            if kind == "shapes":
                item = ["S", [self.fan(*fan) for fan in event[1]]]
            elif kind == "text":
                _kind, text, x, y, size, colour = event
                optical = record.FACE.optical(size) if record.FACE.path else 0
                item = ["T", [self.add(self.texts, (text, round(x, 2), round(y, 2), size, self.colour(colour), optical))]]
            elif kind == "image":
                item = self._image(event)
            elif kind == "lines":
                item = ["L", _flat(event[1]), self.colour(event[2]), event[3]]
            elif kind == "tris":
                item = ["F", _flat(event[1]), self.colour(event[2])]
            else:
                item = ["M", _flat(event[1]), [self.colour(colour) for colour in event[2]]]
            if out and out[-1][0] == item[0] and item[0] in "ST":
                out[-1][1] += item[1]
            else:
                out.append(item)
        return out

    def _image(self, event):
        _kind, texture, primitive, points, uvs, colour = event
        if texture == "body":
            return ["B"]
        per_quad = 6 if primitive == 'TRIS' else 4
        quads = []
        for start in range(0, len(points), per_quad):
            xs, ys = [point[0] for point in points[start:start + per_quad]], [point[1] for point in points[start:start + per_quad]]
            us, vs = [uv[0] for uv in uvs[start:start + per_quad]], [uv[1] for uv in uvs[start:start + per_quad]]
            top_left = points.index((min(xs), min(ys)), start)
            assert uvs[top_left] == (min(us), max(vs)), "an image quad is mirrored: the page cannot draw it"
            quads.append([round(min(xs), 2), round(min(ys), 2), round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2),
                          round(min(us), 5), round(min(vs), 5), round(max(us), 5), round(max(vs), 5), self.colour(colour)])
        return ["I", texture, quads]

    def widget(self, widget, paused, rings_by_key, panel_draw):
        key = record.ring_key(panel_draw, widget)
        if key in self.rings:
            ring_index = self.rings[key][0]
        else:
            ring = rings_by_key.get(key)
            ring_index = self.add(self.rings, key, [_flat(part) for part in ring]) if ring else -1
        tip = help_text.line(widget.id, widget.enabled, paused)
        entry = (widget.id, widget.kind, round(widget.x, 2), round(widget.y, 2), round(widget.w, 2), round(widget.h, 2),
                 widget.label, widget.detail, " ".join(str(part) for part in widget.action), widget.enabled, widget.active,
                 tip, ring_index, widget.style)
        return self.add(self.widgets, entry, list(entry))


def _flat(points):
    return [round(value, 2) for point in points for value in point[:2]]


def _png(pixels):
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray(pixels[::-1]).save(buffer, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def export(panels, value_limit, panel_draw, capture_all=True):
    """(data for the page, coverage report). `capture_all` False (the check): only each panel's first screen is drawn."""
    tables, rings = Tables(), {}
    screens, page_panels, report = [], [], {}
    for panel in panels:
        order = panel.explore(MAX_SCREENS, value_limit)
        first = order[0][0]
        start = len(screens)
        paused_of = lambda model: getattr(model, "paused", False)       # noqa: E731
        for model, widgets, values, base in order if capture_all else order[:1]:
            spec = panel.spec(model)
            inside, outside, hovered = record.capture(panel_draw, spec, panel.body(model), widgets, rings)
            outside_index = tables.add(tables.lists, json.dumps(tables.events(outside)))
            handles = {key: tables.add(tables.lists, json.dumps(tables.events(events))) for key, events in hovered.items()}
            goes, alone = [], []
            for number, widget in enumerate(widgets):
                index, from_base = panel.target(model, base, widget)
                goes.append(start + index if index is not None else -1)
                if from_base:
                    alone.append(number)
            screens.append([len(page_panels), describe(model, first), tables.events(inside), outside_index, handles,
                            [tables.widget(widget, paused_of(model), rings, panel_draw) for widget in widgets], goes,
                            values, spec.width, spec.height, alone])
        page_panels.append({"id": panel.name, "title": panel.scene.title, "start": start, "count": len(order)})
        report[panel.name] = panel
    shortcuts = []
    for title, name, fields in SHORTCUTS:
        panel, start = report[name], next(page["start"] for page in page_panels if page["id"] == name)
        index = next(index for index, (model, _widgets, values, _base) in enumerate(panel.order) if values == 0
                     and all(getattr(model, field) == value for field, value in fields.items()))
        shortcuts.append({"title": title, "screen": start + index})
    data = {"panels": page_panels, "shortcuts": shortcuts, "screens": screens,
            "colours": tables.listed(tables.colours), "shapes": tables.listed(tables.shapes),
            "texts": tables.listed(tables.texts), "widgets": tables.listed(tables.widgets),
            "lists": [json.loads(text) for text in tables.listed(tables.lists)], "rings": tables.listed(tables.rings),
            "textures": {name: _png(pixels) for name, pixels in record.REC.textures.items()},
            "meta": {"notHit": list(panel_layout.NOT_HIT), "noHighlight": list(panel_layout.NO_HIGHLIGHT),
                     "hover": list(panel_draw.HOVER_COLOUR), "press": list(panel_draw.PRESS_COLOUR),
                     "metersPerPixel": panel_layout.METERS_PER_PIXEL, **_version()}}
    return data, report


def _version():
    def git(*arguments):
        try:
            return subprocess.run(["git", "-C", ADDON, *arguments], capture_output=True, text=True, timeout=10).stdout.strip()
        except OSError:
            return ""
    return {"commit": git("rev-parse", "--short", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--", ".")), "date": datetime.date.today().isoformat()}


# ---- the coverage check -------------------------------------------------------------------------------------------------

def check(panels, data, report):
    """Problems: a panel without a scene, a tab / pop-up / mode the layouts can show that no exported screen shows, a
    navigation press with no screen, widget counts that differ from the layout functions."""
    problems = []
    desk = report["desk"].order
    desk = [screen for screen in desk if screen[2] == 0]
    tabs = {model.tab for model, *_rest in desk}
    problems += [f"desk tab {tab} has no screen" for tab in desk_layout.TAB_IDS if tab not in tabs]
    for tab in desk_layout.TAB_IDS:
        model = next(model for model, *_rest in desk if model.tab == tab) if tab in tabs else None
        if model is not None and not desk_layout.page_widgets(model, desk_layout.PAGE_TOP):
            problems.append(f"desk tab {tab}: page_widgets draws nothing")
    modes = {model.mode for model, *_rest in desk if model.tab == 'tools'}
    problems += [f"desk Tools page in mode {mode} has no screen" for mode, _label in desk_layout.MODES if mode not in modes]
    options = {model.mode for model, *_rest in report["tool_options"].order}
    problems += [f"Tool options in mode {mode} has no screen" for mode, _label in desk_layout.MODES if mode not in options]
    for panel in panels:
        if panel.scene is None:
            problems.append(f"panel {panel.name} (panels.PANELS) has no scene in export_ui.SCENES")
            continue
        for model, widgets, values, _base in panel.order:
            if values:                  # a screen with a changed value: its presses may lead past the export (by design)
                continue
            if len(widgets) != len(panel.layout.build(model)) + panel.pinnable:
                problems.append(f"{panel.name}: widget count differs from {panel.layout.__name__}.build")
            for widget in widgets:
                if not widget.enabled or not widget.action or not is_nav(widget.action):
                    continue
                target = panel.press(model, widget.action)
                if target is None:
                    problems.append(f"{panel.name}: the press {widget.action} ({widget.id}) has no screen rule")
                elif panel.screen_of(target) is None:
                    problems.append(f"{panel.name}: the press {widget.action} ({widget.id}) leads to no exported screen")
                elif widget.action[0] == "popup" and target.popup and not any(
                        other.kind == panel_layout.BACKDROP for other in panel.widgets(target)):
                    problems.append(f"{panel.name}: pop-up {target.popup!r} opens nothing with the fake scene")
    return sorted(set(problems))


# ---- text that does not fit its widget ----------------------------------------------------------------------------------

OVERFLOW_TOLERANCE = 2.0        # px: the text widths follow blf within about 2 px


def overflows(panels, panel_draw):
    """[(panel, widget id, text, px over, screen description)] for every text a widget draws wider than itself, over all
    explored screens (the real `panel_draw._draw_text` runs on each widget; only its text events are read)."""
    found, seen = [], set()
    record.REC.height = None
    for panel in panels:
        for model, widgets, _values, _base in panel.order:
            height = panel.spec(model).height
            for widget in widgets:
                record.REC.events = []
                panel_draw._draw_text(widget, height)
                right = panel_draw._switch(widget)[0] if widget.kind == panel_layout.TOGGLE else widget.x + widget.w
                for _kind, text, x, _y, size, _colour in record.REC.events:
                    over = max(widget.x - x, x + record.FACE.width(text, size) - right) - OVERFLOW_TOLERANCE
                    key = (panel.name, widget.id, text)
                    if over > 0 and key not in seen:
                        seen.add(key)
                        found.append((panel.name, widget.id, text, round(over + OVERFLOW_TOLERANCE), describe(model, panel.order[0][0])))
    return found


# ---- the page -----------------------------------------------------------------------------------------------------------

def blender_font():
    """Blender's UI font (blf's default face), found next to the `blender` on PATH."""
    binary = shutil.which("blender")
    if binary:
        for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.realpath(binary)), "*", "datafiles", "fonts",
                                                  "Inter.woff2")), reverse=True):
            return path
    return None


def page_fonts(texts):
    """{optical size: woff2 data URI}: blf's face at each optical size the texts use, cut down to their characters."""
    from fontTools import subset
    from fontTools.ttLib import TTFont
    characters = {}
    for text, _x, _y, _size, _colour, optical in texts:
        characters.setdefault(optical, set()).update(text)
    fonts = {}
    for optical, used in characters.items():
        buffer = io.BytesIO()
        record.FACE.instance(optical)[0].save(buffer)
        font = TTFont(io.BytesIO(buffer.getvalue()))
        subsetter = subset.Subsetter(subset.Options(layout_features=["*"], notdef_outline=True))
        subsetter.populate(text="".join(sorted(used)) + " ")
        subsetter.subset(font)
        font.flavor, buffer = "woff2", io.BytesIO()
        font.save(buffer)
        fonts[str(optical)] = "data:font/woff2;base64," + base64.b64encode(buffer.getvalue()).decode()
    return fonts


def write_page(data, path):
    packed = base64.b64encode(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), 9)).decode()
    with open(PAGE, encoding="utf-8") as handle:
        page = handle.read()
    page = page.replace("__UI_DATA__", packed)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return len(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="coverage and text overflow check only (no page)")
    parser.add_argument("--overflow", action="store_true", help="list every text wider than its widget, then exit")
    parser.add_argument("--font", default=os.environ.get("DIGITS_VR_UI_FONT") or blender_font())
    parser.add_argument("--out", default=os.path.join(BUILD, "digits_vr_ui.html"))
    options = parser.parse_args()
    quick = options.check or options.overflow       # no page
    if options.font:
        record.use_font(options.font)
    elif not quick:
        raise SystemExit("Blender's Inter.woff2 not found: pass --font")
    panel_draw = record.install()
    panels = [Panel(module) for module in panel_modules()]
    missing = [panel.name for panel in panels if panel.scene is None]
    if missing:
        print("RESULT FAIL\n" + "\n".join(f"FAIL panel {name} has no scene in export_ui.SCENES" for name in missing))
        return 1
    data, report = export(panels, MAX_VALUE_STEPS, panel_draw, capture_all=not quick)
    problems = check(panels, data, report)
    if options.font or not quick:
        problems += [f"text overflow: {panel} {widget} {text!r} is {over} px too wide ({where})"
                     for panel, widget, text, over, where in overflows(panels, panel_draw)]
    elif options.check:
        print("overflow check skipped: no Blender font found (pass --font)")
    for problem in problems:
        print("FAIL " + problem)
    screens = sum(len(panel.order) for panel in panels)
    if quick:
        print(f"RESULT {'FAIL' if problems else 'OK'}: {screens} screens")
        return 1 if problems else 0
    data["fonts"] = page_fonts(data["texts"])
    size = write_page(data, options.out)
    print(f"{screens} screens, {size / 1e6:.1f} MB -> {options.out}" + ("  (with coverage problems)" if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
