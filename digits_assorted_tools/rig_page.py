# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/rig_page.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig panel data (shared: Addons/shared_addon/rig_page.py is the ONE source, synced into Digit's Assorted Tools): what
the rig panel shows, as plain values, read only. Two places draw it: the Selected card's Character Rig box
(rig_switches_ui.py, Blender layouts) and Digit's VR desk (its Selected tab draws its own widgets from these same
functions and presses the same operators).

- `panel_state(rig, context)`: the rig map, the page showing (Follow Selection rule), the changed counts.
- `limb_view(context, info, page)`: a limb page's IK | FK state, Follows parents, Copy To side.
- `row_owners`, `row_enabled`, `blend_row`, `row_groups`, `other_owners`, `page_hint`, `part_tool_hint`: the rows of
  a page and the lines around them.
- `value_range(owner, key)`: a property's slider range (soft limits of its UI data).
The window-manager values (stored part, Follow Selection) are named per add-on copy (PREFIX), as before."""
import json
from collections import namedtuple

from .rig_parts import (FULL_BODY, OTHER, SLIDERS, Entry, Row, changed_counts, owner_of, rig_map,  # generated copy
                        shown_part)

PREFIX = (__package__ or "rig").rsplit(".", 1)[-1]   # one set of window-manager values per add-on copy: no clash
SEARCH_PROP = PREFIX + "_rig_search"
PART_PROP = PREFIX + "_rig_part"            # the part last clicked
PART_BONE_PROP = PREFIX + "_rig_part_bone"  # the bone active at that click (rig_parts.bone_key_text)
FOLLOW_PROP = PREFIX + "_rig_follow"
FULL_BODY_HINT = "Pick a part for its switches. Reset All resets every part."

PanelState = namedtuple("PanelState", "info page counts only_other")
# arm / bone = the limb control; parents = Follows names ((): no Follows row); parent = the IK_Parent index;
# copy_to = the other side's page when the rig has it, else None
LimbView = namedtuple("LimbView", "arm bone is_fk live parents parent copy_to")


def stored(context):
    """(stored part, stored bone text, Follow Selection) of this add-on copy."""
    wm = context.window_manager
    return getattr(wm, PART_PROP, ""), getattr(wm, PART_BONE_PROP, ""), getattr(wm, FOLLOW_PROP, True)


def current_part(rig, context):
    """The page showing for `rig` now (read only)."""
    part, bone, follow = stored(context)
    return shown_part(rig_map(rig), context, part, bone, follow)


def only_other(info):
    """A rig off the bone-name standard: Other is its only page (no Part picker, no Reset Part)."""
    return list(info.parts) in ([], [OTHER])


def panel_state(rig, context):
    info = rig_map(rig)
    return PanelState(info, current_part(rig, context), changed_counts(info), only_other(info))


def part_text(name, counts):
    return f"{name} •" if counts.get(name) else name


def status_text(counts):
    total = sum(counts.values())
    return f"{total} changed: {', '.join(counts)}" if total else "Nothing changed"


def is_slider(owner, key):
    return key in SLIDERS or isinstance(owner[key], float)


def value_range(owner, key):
    """(low, high) a slider runs over: the soft limits of the property's UI data (else its hard limits, else 0-1)."""
    try:
        data = owner.id_properties_ui(key).as_dict()
    except TypeError:
        return 0.0, 1.0
    low = data.get("soft_min", data.get("min", 0.0))
    high = data.get("soft_max", data.get("max", 1.0))
    return (float(low), float(high)) if high > low else (0.0, 1.0)


def row_owners(row):
    """The owner of each entry of a row, or None when one is gone or lost its key (the row is not drawn)."""
    owners = [owner_of(entry) for entry in row.entries]
    if any(owner is None or entry.key not in owner for owner, entry in zip(owners, row.entries)):
        return None
    return owners


def row_groups(rows):
    """The sub-group names of a page's rows, in order (several = a folding group each on the desktop)."""
    return list(dict.fromkeys(row.group for row in rows))


def other_side(page):
    """"Arm R" for "Arm L" and back; None for a limb without a side."""
    if not page.endswith((" L", " R")):
        return None
    return page[:-1] + ("R" if page.endswith("L") else "L")


def limb_view(context, info, page):
    """The limb page's state, or None when its control is gone."""
    arm_name, bone = info.parts[page].limb
    control = owner_of(Entry(arm_name, bone, "IK_FK"))
    if control is None or "IK_FK" not in control:
        return None
    limb = json.loads(control["Limb"])
    parents = tuple(limb.get("parents") or ()) if "IK_Parent" in control else ()
    side = other_side(page)
    return LimbView(arm_name, bone, control["IK_FK"] < 0.5, context.mode in ('POSE', 'OBJECT'), parents,
                    control["IK_Parent"] if parents else -1, side if side in info.parts else None)


def limb_notes(view):
    notes = [] if view.live else ["Object or Pose Mode to switch"]   # the buttons put the control's armature in Pose Mode
    if view.is_fk:
        notes.append("FK controls are showing. IK options are off.")
    return notes


def follows_entry(view):
    return Entry(view.arm, view.bone, "IK_Parent")


def row_enabled(view, row):
    """A limb row is off while in FK when it sits on the IK control."""
    return not (view.is_fk and row.entries[0].bone == view.bone)


def blend_row(page, view):
    """The IK/FK blend row (under More)."""
    return Row(page, "IK/FK Blend", (Entry(view.arm, view.bone, "IK_FK"),))


def page_hint(info, page):
    return FULL_BODY_HINT if page == FULL_BODY and not info.parts[page].rows else None


def part_tool_hint(part):
    return "No switches: pose its bones directly" if not part.rows and not part.limb and not part.chains else None


def other_owners(info):
    """Other's switches by owner: [((armature, bone), owner, [Entry])], owners that are gone left out."""
    by_owner = {}
    for entry in (entry for row in info.parts[OTHER].rows for entry in row.entries):
        by_owner.setdefault((entry.arm, entry.bone), []).append(entry)
    found = []
    for key, entries in by_owner.items():
        owner = owner_of(entries[0])
        if owner is not None:
            found.append((key, owner, entries))
    return found
