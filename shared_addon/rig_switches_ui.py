# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig panel drawing: Reset Pose & Rig Switches (shared: Addons/shared_addon/rig_switches_ui.py is the ONE source,
synced into Digit's Assorted Tools (the Character Rig box of the Selected card)).

`draw_rig_panel(layout, rig, idprefix, context)` draws, top to bottom: Show Bones (one button per bone collection
group the rig has: click = only that group, Shift-click = add or remove it), the Part drop-down (the pages in the
sections Full Body, Head, Torso, Arms, Legs, Other; a dot marks a changed part) with Follow Selection (picking a part
with it on also selects the part's main control: rig_panel_ops), Reset Part / Reset Selected /
Reset All, a "N changed" status line, and the page of one part: its rows (left / right pairs share a row, a reset
arrow on each changed row), sub-groups folded when a page has several, and on a limb page IK | FK buttons that snap
as they switch, the Follows row, More (the IK/FK blend) and Copy To the other side. A part armature's page (ponytail,
tail, ears) also has Select Controls and, for a tip IK without a switch, Add IK/FK Switch. Buttons on a page work on
its armature: they make it the active object in Pose Mode. A rig off the bone-name standard only has Other: today's
per-bone list with the search field.

What shows comes from rig_parts.py (cached per rig) through rig_page.py (the panel's data as plain values, also read
by Digit's VR desk); the page rule (Follow Selection) reads the active bone and
two stored window-manager values, so draw() never writes data and nothing runs in the background. The operators
live in Digit's Assorted Tools (pose_ops.py: reset, snap, parent; rig_panel_ops.py: part, bone groups, row reset,
copy side).
"""
import json

import bpy

from . import bone_collections as bc  # generated copy
from .rig_parts import (FULL_BODY, OTHER, SLIDERS, Entry, Row, active_bone_key, bone_key_text,  # noqa: F401 (re-exported)  generated copy
                        changed_counts, changed_entries, character_rig, forget_cache, owner_of, prop_label, rig_map,
                        rig_owners, rig_summary, shown_keys, shown_part, switch_bones, switch_names, switch_summary,
                        switch_title)
from .rig_page import (FOLLOW_PROP, PART_BONE_PROP, PART_PROP, PREFIX, SEARCH_PROP, blend_row, current_part,  # noqa: F401 (re-exported)  generated copy
                       follows_entry, is_slider, limb_notes, limb_view, other_owners, other_side, page_hint,
                       panel_state, part_text, part_tool_hint, row_enabled, row_groups, row_owners, status_text,
                       stored)
from .ui_cards import action_row, hints, section, sub_heading  # generated copy

RESET_OP, SNAP_OP, PARENT_OP = "pose.reset_pose_and_properties", "pose.limb_snap", "pose.limb_parent"
PART_OP, BONES_OP = "pose.rig_show_part", "pose.rig_show_bones"
RESET_SWITCHES_OP, COPY_OP = "pose.reset_switches", "pose.copy_limb_side"
SELECT_PART_OP, ADD_SWITCH_OP = "pose.rig_select_part", "pose.add_ik_fk_switch"

LABEL_SHARE = 0.36                          # label column of a row
PART_MENU = PREFIX.upper() + "_MT_rig_parts"   # the Part drop-down

# ---------------------------------------------------------------- window-manager values


def panel_rig(context):
    """The character rig of the active (else first selected) object."""
    return character_rig(context.active_object or next(iter(context.selected_objects), None))


def store_part(context, part):
    """A part click: remember the part and the bone active now (an operator calls this, never draw)."""
    wm = context.window_manager
    setattr(wm, PART_PROP, part)
    setattr(wm, PART_BONE_PROP, bone_key_text(active_bone_key(context)))


def follow_changed(wm, context):
    """Unticking pins the page showing now; ticking keeps this page until the selection changes (an update callback,
    not draw)."""
    rig = panel_rig(context)
    if rig is None:
        return
    part, bone, follow = stored(context)
    if follow:
        setattr(wm, PART_BONE_PROP, bone_key_text(active_bone_key(context)))
    else:
        setattr(wm, PART_PROP, shown_part(rig_map(rig), context, part, bone, True) or "")


def register():
    """The panel's window-manager values (not part of the scene) and the Part drop-down."""
    bpy.utils.register_class(PartMenu)
    wm = bpy.types.WindowManager
    setattr(wm, SEARCH_PROP, bpy.props.StringProperty(
        name="Search", options={'TEXTEDIT_UPDATE'},
        description="Show only the controls whose bone or property name contains this text"))
    setattr(wm, PART_PROP, bpy.props.StringProperty(name="Part", options={'SKIP_SAVE'}))
    setattr(wm, PART_BONE_PROP, bpy.props.StringProperty(name="Bone At Part Click", options={'SKIP_SAVE'}))
    setattr(wm, FOLLOW_PROP, bpy.props.BoolProperty(
        name="Follow Selection", default=True, update=follow_changed,
        description="Show the part of the selected bone. A part click shows that part until you select another bone. "
                    "Off: the page stays where it is"))


def unregister():
    for name in (SEARCH_PROP, PART_PROP, PART_BONE_PROP, FOLLOW_PROP):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    bpy.utils.unregister_class(PartMenu)

# ---------------------------------------------------------------- small pieces


def entries_text(entries):
    return json.dumps([list(entry) for entry in entries])


def draw_back(layout, entries):
    """The ↺ reset of one row while any of its switches is changed, else a blank of the same width."""
    if changed_entries(entries):
        layout.operator(RESET_SWITCHES_OP, text="", icon='LOOP_BACK').entries = entries_text(entries)
    else:
        layout.label(text="", icon='BLANK1')


def labelled(layout, text):
    """A row with `text` right aligned in the label column; returns the control cell (aligned row)."""
    split = layout.split(factor=LABEL_SHARE, align=True)
    left = split.row()
    left.alignment = 'RIGHT'
    left.label(text=text)
    return split.row(align=True)


def draw_row(layout, row, enabled=True):
    """One switch row: label, one slider (or L and R), the ↺."""
    owners = row_owners(row)
    if owners is None:
        return
    cell = labelled(layout, row.label)
    sliders = cell.row(align=True)
    sliders.enabled = enabled
    pair = len(row.entries) == 2
    for side, owner, entry in zip("LR", owners, row.entries):
        sliders.prop(owner, f'["{entry.key}"]', text=side if pair else "", slider=is_slider(owner, entry.key))
    draw_back(cell, row.entries)


def draw_reset_buttons(row, rig=None, part=None):
    """Reset Part (when given) / Reset Selected / Reset All, into `row` (a layout row)."""
    if rig is not None and part:
        op = row.operator(RESET_SWITCHES_OP, text="Reset Part")
        op.rig, op.part = rig.name, part
    row.operator(RESET_OP, text="Reset Selected").only_selected = True
    row.operator(RESET_OP, text="Reset All").only_selected = False


def heading(layout, text, extra=None, icon='NONE'):
    """A small heading with a line under it; `extra(row)` draws more at its right."""
    if extra is None:
        return sub_heading(layout, text, icon=icon)
    col = layout.column(align=True)
    row = col.row()
    row.label(text=text, icon=icon)
    extra(row)
    col.separator(type='LINE')
    return col


# ---------------------------------------------------------------- Show Bones and parts


def draw_show_bones(layout, rig, info, extra):
    """One button per bone collection group the rig has (pressed = showing)."""
    heading(layout, "Show Bones", extra)
    shown = bc.shown_groups(rig)
    grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)   # 3 columns cut "Additional Parts" at the default width
    for name in info.groups:
        op = grid.operator(BONES_OP, text=name, depress=name in shown)
        op.rig, op.group = rig.name, name
    hints(layout, ["Shift-click to show more than one"])


def draw_part_menu(layout, context):
    """The Part drop-down's list: a heading per section (Full Body needs none), its pages under it, a tick on the
    page showing."""
    rig = panel_rig(context)
    if rig is None:
        return
    info = rig_map(rig)
    page, counts = current_part(rig, context), changed_counts(info)
    for index, (section, names) in enumerate(info.sections):
        if index:
            layout.separator()
        if section != FULL_BODY:
            layout.label(text=section)
        for name in names:
            op = layout.operator(PART_OP, text=part_text(name, counts), icon='CHECKMARK' if name == page else 'BLANK1')
            op.rig, op.part = rig.name, name


class PartMenu(bpy.types.Menu):
    """Pick the part whose switches show"""
    bl_idname = PART_MENU
    bl_label = "Part"

    def draw(self, context):
        draw_part_menu(self.layout, context)


def draw_part_picker(layout, context, page, counts):
    """"Part" with Follow Selection at its right, then the drop-down showing the page."""
    row = layout.row()
    row.label(text="Part")
    right = row.row()
    right.alignment = 'RIGHT'
    right.prop(context.window_manager, FOLLOW_PROP)
    layout.menu(PART_MENU, text=part_text(page, counts))


# ---------------------------------------------------------------- pages


def draw_rows(layout, rows, idprefix, page):
    """A page's rows; several sub-groups each get a folding group (the first open)."""
    groups = row_groups(rows)
    if len(groups) <= 1:
        for row in rows:
            draw_row(layout, row)
        return
    for index, name in enumerate(groups):
        body = section(layout, f"{idprefix}_{page}_{name}".replace(" ", "_"), name, default_closed=index > 0)
        if body is None:
            continue
        body.use_property_split = False
        for row in rows:
            if row.group == name:
                draw_row(body, row)


def draw_limb_page(layout, context, info, page, idprefix):
    """IK | FK (snap as they switch; keys with auto-key), Follows, the limb's sliders, More (IK/FK blend), Copy To."""
    view = limb_view(context, info, page)
    if view is None:
        return
    row = layout.row(align=True)
    row.enabled = view.live
    for text, to_fk in (("IK", False), ("FK", True)):
        op = row.operator(SNAP_OP, text=text, depress=view.is_fk == to_fk)
        op.bone, op.to_fk, op.arm = view.bone, to_fk, view.arm
    hints(layout, limb_notes(view))
    if view.parents:
        cell = labelled(layout, "Follows")
        buttons = cell.row(align=True)
        buttons.enabled = view.live and not view.is_fk
        for index, name in enumerate(view.parents):
            op = buttons.operator(PARENT_OP, text=name, depress=view.parent == index)
            op.bone, op.parent, op.arm = view.bone, index, view.arm
        draw_back(cell, [follows_entry(view)])
    for row_def in info.parts[page].rows:
        draw_row(layout, row_def, enabled=row_enabled(view, row_def))
    more = section(layout, f"{idprefix}_{page}_more".replace(" ", "_"), "More", default_closed=True)
    if more is not None:
        more.use_property_split = False
        draw_row(more, blend_row(page, view))
    if view.copy_to:
        copy = layout.row()
        copy.enabled = view.live
        op = copy.operator(COPY_OP, text=f"Copy To {view.copy_to}")
        op.bone, op.arm = view.bone, view.arm


def draw_part_tools(layout, part):
    """A part armature's page: Add IK/FK Switch for each tip IK without one, then Select Controls."""
    for chain in part.chains:
        cell = labelled(layout, chain.part) if len(part.chains) > 1 else layout.row()
        op = cell.operator(ADD_SWITCH_OP, icon='CON_KINEMATIC')
        op.arm, op.bone, op.part = chain.arm, chain.control, chain.part
    if part_tool_hint(part):
        hints(layout, [part_tool_hint(part)])
    layout.operator(SELECT_PART_OP, icon='RESTRICT_SELECT_OFF').arm = part.arm


def draw_search_results(layout, info, text):
    """Flat list of the switches (every part) whose bone, part or property name contains `text`."""
    col = layout.column(align=True)
    col.use_property_split, col.use_property_decorate = True, False
    found = 0
    for part_name, part in info.parts.items():
        for entry in (entry for row in part.rows for entry in row.entries):
            owner = owner_of(entry)
            if owner is None or entry.key not in owner:
                continue
            title = switch_title(owner) if hasattr(owner, "bone") else "Rig"
            names = f"{title} {entry.bone} {part_name}".lower()
            if text in names or text in entry.key.lower() or text in prop_label(entry.key).lower():
                col.prop(owner, f'["{entry.key}"]', text=f"{title}: {prop_label(entry.key)}",
                         slider=is_slider(owner, entry.key))
                found += 1
    if not found:
        hints(layout, [f'Nothing matches "{text}"'])


def draw_other_page(layout, context, info, idprefix):
    """Other: the search field and one folding group per bone (the old list), for switches no part claims."""
    wm = context.window_manager
    text = getattr(wm, SEARCH_PROP, "").strip().lower()
    if hasattr(wm, SEARCH_PROP):
        layout.prop(wm, SEARCH_PROP, text="", icon='VIEWZOOM')
    if text:
        draw_search_results(layout, info, text)
        return
    for index, ((arm_name, bone), owner, entries) in enumerate(other_owners(info)):
        is_bone = hasattr(owner, "bone")
        sec = section(layout, f"{idprefix}_{arm_name}_{bone or 'rig'}".replace(" ", "_"),
                      switch_title(owner) if is_bone else "Rig", icon='BONE_DATA' if is_bone else 'ARMATURE_DATA',
                      default_closed=index > 0, right=switch_summary(owner) if is_bone else f"{len(entries)} slider{'' if len(entries) == 1 else 's'}")
        if not sec:
            continue
        col = sec.column(align=True)
        col.use_property_split, col.use_property_decorate = True, False
        for entry in entries:
            if entry.key in owner:
                col.prop(owner, f'["{entry.key}"]', text=prop_label(entry.key), slider=is_slider(owner, entry.key))


def draw_page(layout, context, info, page, idprefix):
    if page_hint(info, page):
        hints(layout, [page_hint(info, page)])
    if page == OTHER:
        draw_other_page(layout, context, info, idprefix)
    elif info.parts[page].limb:
        draw_limb_page(layout, context, info, page, idprefix)
    else:
        draw_rows(layout, info.parts[page].rows, idprefix, page)
    if page != OTHER and info.parts[page].arm:
        draw_part_tools(layout, info.parts[page])


def draw_rig_panel(layout, rig, idprefix, context=None, extra=None):
    """The whole Reset Pose & Rig Switches panel of `rig` (see the module doc). `idprefix` keeps folded states apart
    per place; `extra(row)` draws more at the right of the top heading (Select Rig)."""
    context = context or bpy.context
    info, page, counts, only_other = panel_state(rig, context)
    if info.groups:
        draw_show_bones(layout, rig, info, extra)
    else:
        heading(layout, "Pose", extra, icon='ARMATURE_DATA')
    if not only_other:
        draw_part_picker(layout, context, page, counts)
    draw_reset_buttons(action_row(layout, scale=1.0), rig, None if only_other else page)
    hints(layout, [status_text(counts)])
    if page is None:
        return
    if not only_other:
        sub_heading(layout, page)
    draw_page(layout, context, info, page, idprefix)
