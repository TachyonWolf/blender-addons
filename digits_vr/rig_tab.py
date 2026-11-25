# SPDX-License-Identifier: GPL-3.0-or-later
"""The desk's Selected tab, bpy side: the rig panel of Digit's Assorted Tools (its Selected card's Character Rig box)
in VR. No copy of the panel: the rig, its pages, rows, defaults and changed state come from Assorted Tools' own
modules (shared `rig_page.py` / `rig_parts.py` / `bone_collections.py`, the same caches), and every button presses
the SAME operator the desktop panel does (Show Bones, Part, IK | FK snap, Follows, Reset Part / Selected / All, the
row ↺, Copy To, Select Controls). Only the slider and toggle cells write the property straight away (a slider once
per laser move); a slider drag is one undo step, pushed when the trigger lets go.

`build_view(context)` gives the plain RigView the layout draws (rig_layout.py); desk_actions calls it only while the
Selected tab is open (5 Hz model check). The changed counts of all parts (the costly part: every switch's UI data) are
kept for COUNTS_SECONDS, and dropped at once after a press on this tab."""
import json
import sys
import time

import bpy

from . import desk_layout as layout
from .action_map import RIGHT, value
from .context_helper import run_in_view3d
from .rig_layout import CELL_NUMBER, CELL_SLIDER, CELL_TEXT, CELL_TOGGLE, RigView

TOOLS = "digits_assorted_tools"
NEEDS_TOOLS = "The Selected tab needs Digit's Assorted Tools (its rig panel)."
NOTHING = "Select a character's bone, armature or mesh to see its rig."
COUNTS_SECONDS = 1.0
_tools = {}             # Assorted Tools' modules, found once (its package name differs between installs and tests)
_state = {"scroll": 0, "picker_open": False, "picker_page": 0, "page": None, "rig": None, "rows": [], "limb": None,
          "part_arm": None, "counts": None, "counts_key": None, "dragged": False}
builds = 0              # how many views were built (tests)


def _modules():
    """(rig_page, rig_parts, bone_collections, character_rig) of the enabled Digit's Assorted Tools, else None."""
    package = _tools.get("package")
    if package is None or package + ".rig_page" not in sys.modules:
        package = next((name for name in list(sys.modules) if (name == TOOLS or name.endswith("." + TOOLS))
                        and name + ".rig_page" in sys.modules), None)
        _tools["package"] = package
    if package is None or getattr(bpy.types, "POSE_OT_limb_snap", None) is None:     # not enabled (no operators)
        return None
    return tuple(sys.modules.get(f"{package}.{name}") for name in ("rig_page", "rig_parts", "bone_collections",
                                                                    "character_rig"))


def forget():
    """Drop what the tab keeps (session start / end, undo)."""
    _state.update(scroll=0, picker_open=False, picker_page=0, page=None, rig=None, rows=[], limb=None, part_arm=None,
                  counts=None, counts_key=None, dragged=False)


def _counts(parts, info, rig):
    key = (rig.name, id(info))
    now = time.monotonic()
    cached = _state["counts"]
    if cached is None or _state["counts_key"] != key or now - cached[0] > COUNTS_SECONDS:
        cached = (now, parts.changed_counts(info))
        _state["counts"], _state["counts_key"] = cached, key
    return cached[1]


def _cell(page_data, owner, key, side):
    current = owner[key]
    if hasattr(current, "to_list"):                 # a vector: shown, not edited (the sidebar edits it)
        return side, CELL_TEXT, ", ".join(f"{item:.2f}" for item in current.to_list()), 0.0, 1.0
    low, high = page_data.value_range(owner, key)
    if isinstance(current, bool) or (isinstance(current, int) and (low, high) == (0.0, 1.0)):
        return side, CELL_TOGGLE, bool(current), 0.0, 1.0
    if isinstance(current, int):
        return side, CELL_NUMBER, float(current), low, high
    return side, CELL_SLIDER, round(float(current), 3), low, high


class _Items:
    """Collects a page's items and, per row, what its cells point at."""

    def __init__(self, page_data, parts):
        self.page_data, self.parts, self.items, self.rows = page_data, parts, [], []

    def add(self, *item):
        self.items.append(item)

    def row(self, row, enabled=True):
        owners = self.page_data.row_owners(row)
        if owners is None:
            return
        pair = len(row.entries) == 2
        cells = tuple(_cell(self.page_data, owner, entry.key, side if pair else "")
                      for side, owner, entry in zip("LR", owners, row.entries))
        self.add("row", len(self.rows), row.label, cells, bool(self.parts.changed_entries(row.entries)), enabled)
        self.rows.append(row.entries)


def _page_items(context, page_data, parts, info, page):
    found = _Items(page_data, parts)
    part = info.parts[page]
    _state["limb"], _state["part_arm"] = None, part.arm
    if page_data.page_hint(info, page):
        found.add("hint", page_data.page_hint(info, page))
    if page == parts.OTHER:
        for _key, owner, entries in page_data.other_owners(info):
            title = parts.switch_title(owner) if hasattr(owner, "bone") else "Rig"
            found.add("heading", title)
            for entry in entries:
                found.row(parts.Row(title, parts.prop_label(entry.key), (entry,)))
    elif part.limb:
        view = page_data.limb_view(context, info, page)
        if view is not None:
            _state["limb"] = view
            found.add("ikfk", view.is_fk, view.live)
            for note in page_data.limb_notes(view):
                found.add("hint", note)
            if view.parents:
                found.add("follows", view.parents, view.parent, view.live and not view.is_fk,
                          bool(parts.changed_entries([page_data.follows_entry(view)])))
            for row in part.rows:
                found.row(row, page_data.row_enabled(view, row))
            found.add("heading", "More")
            found.row(page_data.blend_row(page, view))
            if view.copy_to:
                found.add("button", "rig_copy", f"Copy To {view.copy_to}", view.live)
    else:
        groups = page_data.row_groups(part.rows)
        for group in groups:
            if len(groups) > 1:
                found.add("heading", group)
            for row in part.rows:
                if row.group == group:
                    found.row(row)
    if page != parts.OTHER and part.arm:
        if page_data.part_tool_hint(part):
            found.add("hint", page_data.part_tool_hint(part))
        found.add("button", "rig_select_controls", "Select Controls", True)
    return found


def build_view(context):
    """The RigView of the selected character's rig (or a message)."""
    global builds
    builds += 1
    modules = _modules()
    if modules is None:
        return RigView(message=NEEDS_TOOLS)
    page_data, parts, collections, character = modules
    rig = character.subject_rig(context)
    _state["rig"] = rig.name if rig is not None else None
    if rig is None:
        _state["rows"] = []
        return RigView(message=NOTHING)
    info = parts.rig_map(rig)
    page = page_data.current_part(rig, context)
    counts = _counts(parts, info, rig)
    if page != _state["page"]:
        _state["page"], _state["scroll"] = page, 0
    only_other = page_data.only_other(info)
    shown = collections.shown_groups(rig) if info.groups else set()
    found = _page_items(context, page_data, parts, info, page) if page else None
    _state["rows"] = found.rows if found else []
    picker = ()
    if _state["picker_open"]:
        picker = tuple((section, tuple((name, bool(counts.get(name))) for name in names))
                       for section, names in info.sections)
    return RigView(
        title=rig.name, groups=tuple((name, name in shown) for name in info.groups), page=page or "",
        page_label=page_data.part_text(page, counts) if page else "", reset_part=not only_other,
        pose_mode=context.mode == 'POSE', status=f"{character.friendly_name(rig.name)}:  "
        f"{page_data.status_text(counts)}", items=tuple(found.items) if found else (), scroll=_state["scroll"],
        picker_open=_state["picker_open"] and not only_other, picker=picker, picker_page=_state["picker_page"])

# ---------------------------------------------------------------- presses


def _op(context, call):
    """Run one of Assorted Tools' operators as the desktop panel does (3D View override, its own undo step)."""
    _state["counts"] = None
    return run_in_view3d(context, call)


def _entries_text(entries):
    return json.dumps([list(entry) for entry in entries])


def _push_undo(context, message):
    run_in_view3d(context, lambda: bpy.ops.ed.undo_push(message=message))


def _set_cell(context, widget, pixel_x, row_id, index):
    modules = _modules()
    if modules is None or row_id >= len(_state["rows"]):
        return False
    entry = _state["rows"][row_id][index]
    owner = modules[1].owner_of(entry)
    if owner is None or entry.key not in owner:
        return False
    current = owner[entry.key]
    if widget.kind == layout.TOGGLE:
        owner[entry.key] = (not current) if isinstance(current, bool) else (0 if current else 1)
        owner.id_data.update_tag()
        _state["counts"] = None
        _push_undo(context, f"VR {entry.key}")
        return True
    new_value = layout.slider_value(widget, pixel_x)
    if abs(new_value - widget.value) < 1e-6:
        return False
    owner[entry.key] = int(round(new_value)) if isinstance(current, int) else float(new_value)
    owner.id_data.update_tag()
    _state["dragged"] = True
    return True


def released(context):
    """The trigger let go of a widget on this tab: a slider drag becomes one undo step."""
    if _state["dragged"]:
        _state["dragged"], _state["counts"] = False, None
        _push_undo(context, "VR rig slider")


def _rig_op(context, kind, arguments):
    rig, limb, ops = _state["rig"], _state["limb"], bpy.ops.pose
    if kind == "rig_group":
        state = context.window_manager.xr_session_state
        extend = state is not None and value(context, state, "toggle", RIGHT) > 0.5      # A held = Shift-click
        return _op(context, lambda: ops.rig_show_bones('EXEC_DEFAULT', True, rig=rig, group=arguments[0],
                                                       extend=extend))
    if kind == "rig_part":
        _state.update(picker_open=False, scroll=0)
        return _op(context, lambda: ops.rig_show_part('EXEC_DEFAULT', True, rig=rig, part=arguments[0]))
    if kind == "rig_reset_part":
        return _op(context, lambda: ops.reset_switches('EXEC_DEFAULT', True, rig=rig, part=_state["page"]))
    if kind in ("rig_reset_selected", "rig_reset_all"):
        return _op(context, lambda: ops.reset_pose_and_properties('EXEC_DEFAULT', True,
                                                                  only_selected=kind == "rig_reset_selected"))
    if kind == "rig_reset_row" and arguments[0] < len(_state["rows"]):
        entries = _entries_text(_state["rows"][arguments[0]])
        return _op(context, lambda: ops.reset_switches('EXEC_DEFAULT', True, entries=entries))
    if kind == "rig_select_controls" and _state["part_arm"]:
        return _op(context, lambda: ops.rig_select_part('EXEC_DEFAULT', True, arm=_state["part_arm"]))
    if limb is None:
        return False
    if kind == "rig_snap":
        return _op(context, lambda: ops.limb_snap('EXEC_DEFAULT', True, bone=limb.bone, to_fk=arguments[0],
                                                  arm=limb.arm))
    if kind == "rig_parent":
        return _op(context, lambda: ops.limb_parent('EXEC_DEFAULT', True, bone=limb.bone, parent=arguments[0],
                                                    arm=limb.arm))
    if kind == "rig_reset_follows":
        entries = _entries_text([(limb.arm, limb.bone, "IK_Parent")])
        return _op(context, lambda: ops.reset_switches('EXEC_DEFAULT', True, entries=entries))
    if kind == "rig_copy":
        return _op(context, lambda: ops.copy_limb_side('EXEC_DEFAULT', True, bone=limb.bone, arm=limb.arm))
    return False


def perform(context, widget, pixel_x):
    """One press (or a slider move) on the Selected tab. True when something changed."""
    kind, *arguments = widget.action
    if kind == "rig_picker":
        _state.update(picker_open=not _state["picker_open"], picker_page=0)
        return True
    if kind == "rig_picker_page":
        _state["picker_page"] = max(0, _state["picker_page"] + arguments[0])
        return True
    if kind == "rig_scroll":
        _state["scroll"] = max(0, _state["scroll"] + arguments[0])
        return True
    if kind == "rig_prop":
        return _set_cell(context, widget, pixel_x, *arguments)
    if _state["rig"] is None:
        return False
    try:
        return _rig_op(context, kind, arguments)
    except RuntimeError as error:           # an operator's poll failed (wrong mode, hidden armature)
        print("digits_vr: rig tab:", error)
        return False
