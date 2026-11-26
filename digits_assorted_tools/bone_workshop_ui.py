# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop card (Digit's Tools > Character Rigs): shape, size, colour, collections, settings and name of the
active or selected bones (and their mirror bones), in the approved mock-up's order (notes/wip/bone-workshop/).
Drawing reads only the active bone, the target count and the active rig's collection list; Rig Check shows its
last scan (it runs on its button). Logic: bone_workshop.py; settings: bone_workshop_props.py; buttons:
bone_workshop_ops.py; Rig Check: rig_check.py."""
import os

import bpy
import bpy.utils.previews

from . import bone_collections as bc, rig_names as rn  # generated copies
from . import bone_setups as setups, bone_workshop as bw, bone_workshop_ops as ops, bone_workshop_props as props, bone_workshop_spec as spec, \
    oops_ui, rig_check
from .bones_in_front import DIGITOOLS_OT_toggle_bones_in_front
from .ui_cards import action_row, hints, section, shorten, status, wrapped

PREFIX = "digitools_bone_workshop_"
ICON_FOLDER = os.path.join(os.path.dirname(__file__), "icons", "shapes")   # made by icons/make_shape_icons.py
ICONS = {}            # "previews": the shape-tile icons, loaded at register


def tile_icon(tile):
    """(icon, icon_value) keyword of a shape tile: its own picture, else Blender's built-in stand-in."""
    previews = ICONS.get("previews")
    if previews is not None and tile.id in previews:
        return dict(icon_value=previews[tile.id].icon_id)
    return dict(icon=tile.icon)


def open_section(layout, idname, title, **kwargs):
    """A card section with plain (not split) rows: number fields show their name inside, checkboxes their label."""
    body = section(layout, PREFIX + idname, title, **kwargs)
    if body is not None:
        body.use_property_split = False
    return body


def hint(layout, context, key):
    if props.settings_of(context).show_hints:
        hints(layout, [spec.HINTS[key]], context)


def slider(layout, s, prop, pb, text=None):
    """A bone value: the live virtual property, or (fallback) the active bone's own property + copy button."""
    if props.LIVE_SLIDERS:
        layout.prop(s, prop, text=text) if text is not None else layout.prop(s, prop)
        return
    value = props.VALUE_BY_PROP[prop]
    row = layout.row(align=True)
    row.prop(props.owner_of(pb, value), value.attr, text=text if text is not None else "")
    row.operator(ops.DIGITOOLS_OT_bw_copy_setting.bl_idname, text="", icon='PASTEDOWN').prop = prop


def labelled(layout, label, factor=0.35):
    split = layout.split(factor=factor, align=True)
    split.label(text=label)
    return split.row(align=True)


def draw_target(layout, context, s, found):
    box = layout.box().column(align=True)
    row = box.row()
    row.label(text="Active")
    cell = row.row()
    cell.alignment = 'RIGHT'
    cell.label(text=shorten(context.active_pose_bone.name, 24), icon='BONE_DATA')
    box.row(align=True).prop(s, "target", expand=True)
    box.prop(s, "mirror")
    box.label(text="Changes go to " + found.summary())
    hint(box, context, 'target')


def draw_presets(layout, context, s, pb):
    body = open_section(layout, "presets", "Style Presets")
    if not body:
        return
    suggested = spec.suggest(pb.name)
    if suggested and not bw.matches(pb, bw.preset_look(suggested)):
        op = body.operator(ops.DIGITOOLS_OT_bw_preset.bl_idname, icon='LIGHT',
                           text=f"Looks like {spec.PRESET_BY_ID[suggested].label}: Apply")
        op.preset, op.action = suggested, 'APPLY'
    grid = body.grid_flow(columns=2, even_columns=True, align=True)
    for preset in spec.PRESETS:
        look = bw.preset_look(preset.id)
        op = grid.operator(ops.DIGITOOLS_OT_bw_preset.bl_idname, text=preset.label, icon=spec.palette_icon(preset.colour),
                           depress=bw.matches(pb, look))
        op.preset, op.action = preset.id, 'APPLY'
    saved = bw.saved_presets()
    if saved is None:
        body.label(text="Presets file unreadable", icon='ERROR')
        saved = {}
    for name, entry in sorted(saved.items()):
        row = body.row(align=True)
        op = row.operator(ops.DIGITOOLS_OT_bw_preset.bl_idname, text=name, icon=spec.palette_icon(entry['colour']))
        op.preset, op.action = name, 'APPLY'
        op = row.operator(ops.DIGITOOLS_OT_bw_preset.bl_idname, text="", icon='X')
        op.preset, op.action = name, 'REMOVE'
    body.operator(ops.DIGITOOLS_OT_bw_preset.bl_idname, text="Save Current as Preset…", icon='ADD').action = 'SAVE'
    if s.show_hints:
        hints(body, [spec.PRESET_HINT], context)


def draw_shape(layout, context, s, pb):
    widget = bw.widget_name(pb)
    body = open_section(layout, "shape", "Shape", right=widget or "none")
    if not body:
        return
    tile_now = spec.options_of(widget)[0]
    grid = body.grid_flow(columns=spec.TILE_COLUMNS, even_columns=True, align=True)
    for tile in spec.SHAPES:
        grid.operator(ops.DIGITOOLS_OT_bw_shape.bl_idname, text=tile.label, depress=tile.id == tile_now,
                      **tile_icon(tile)).shape = tile.id
    draw_shape_options(body, context, s, tile_now)
    row = body.row(align=True)
    row.prop(s, "use_mesh", text="")
    row.operator(ops.DIGITOOLS_OT_bw_shape.bl_idname, text="Use Mesh", icon='EYEDROPPER').shape = 'MESH'
    row = body.row(align=True)
    row.operator(ops.DIGITOOLS_OT_bw_edit_shape.bl_idname, text="Edit Shape", icon='EDITMODE_HLT').action = 'START'
    row.operator(ops.DIGITOOLS_OT_bw_shape.bl_idname, text="Clear", icon='X').shape = 'NONE'
    hint(body, context, 'shape')


def draw_shape_options(layout, context, s, tile):
    if tile not in ('ngon', 'gear', 'capsule'):
        return
    box = layout.column(align=True)
    box.separator(type='LINE')
    if tile == 'ngon':
        box.prop(s, "sides")
        box.row(align=True).prop(s, "flat", text="Flat Side" if s.flat else "Point First", toggle=True,
                                 icon='MESH_PLANE' if s.flat else 'TRIA_UP')
        box.prop(s, "star")
        if s.star:
            box.prop(s, "inner")
    elif tile == 'gear':
        for name in ("teeth", "depth", "tooth_width"):
            box.prop(s, name)
        box.prop(s, "hole")
    else:
        box.prop(s, "thickness")
    hint(box, context, tile)


def draw_size(layout, context, s, pb):
    body = open_section(layout, "size", "Size & Placement")
    if not body:
        return
    col = body.column(align=True)
    row = col.row(align=True)
    if s.uniform:
        slider(row, s, "scale", pb) if props.LIVE_SLIDERS else slider(row, s, "scale_xyz", pb)
    else:
        slider(row, s, "scale_xyz", pb, text="")
    row.prop(s, "uniform", text="", icon='LOCKED' if s.uniform else 'UNLOCKED')
    col.separator()
    for prop in ("offset", "rotation"):
        body.label(text=prop.title())
        slider(body.row(align=True), s, prop, pb, text="")
    slider(body, s, "wire_width", pb)
    toggles = body.column(align=True)
    slider(toggles, s, "wireframe", pb)
    slider(toggles, s, "bone_length", pb)
    body.label(text="Shape Follows (another bone)")
    body.prop_search(s, "follow", pb.id_data.pose, "bones", text="", icon='BONE_DATA')
    row = body.row(align=True)
    for action, text in (('FIT', "Fit to Mesh"), ('MATCH', "Match Active"), ('RESET', "Reset")):
        row.operator(ops.DIGITOOLS_OT_bw_size.bl_idname, text=text).action = action
    hint(body, context, 'size')


def draw_colour(layout, context, s, pb):
    palette = bw.shown_colour(pb)[0]
    body = open_section(layout, "colour", "Colour", right=spec.COLOUR_NAMES.get(palette, "Custom"))
    if not body:
        return
    row = body.row(align=True)
    for colour in spec.COLOURS:
        op = row.operator(ops.DIGITOOLS_OT_bw_colour.bl_idname, text="", icon=colour.icon, depress=colour.palette == palette)
        op.mode, op.palette = 'PALETTE', colour.palette
    labelled(body, "Show In").prop(s, "colour_where", expand=True)
    row = body.row(align=True)
    row.operator(ops.DIGITOOLS_OT_bw_colour.bl_idname, text="From Collection").mode = 'COLLECTION'
    row.operator(ops.DIGITOOLS_OT_bw_colour.bl_idname, text="By Side (L / R / Mid)").mode = 'SIDE'
    hint(body, context, 'colour')


def ordered_collections(rig):
    """The rig's collections as a tree: (collection, depth), roots in LAYOUT order then A-Z, children likewise."""
    order = {name: k for k, (_p, name, _c) in enumerate(bc.LAYOUT)}
    key = lambda c: (order.get(c.name, len(order)), c.name)
    out = []

    def walk(colls, level):
        for coll in sorted(colls, key=key):
            out.append((coll, level))
            walk(coll.children, level + 1)
    walk(rig.data.collections, 0)
    return out


def draw_collections(layout, context, s, pb):
    home = bw.home_of(pb)
    body = open_section(layout, "collections", "Bone Collections", right=home or "none")
    if not body:
        return
    rig = pb.id_data
    members = {c.name for c in pb.bone.collections}
    col = body.column(align=True)
    for coll, level in ordered_collections(rig):
        row = col.row(align=True)
        if level:
            row.separator(factor=1.6 * level)
        cell = row.row(align=True)
        cell.alignment = 'LEFT'
        cell.enabled = not bw.is_parent(coll)
        colour = bc.COLOR.get(coll.name)
        op = cell.operator(ops.DIGITOOLS_OT_bw_collection.bl_idname, text=coll.name, depress=coll.name == s.picked,
                           icon=spec.palette_icon(colour) if colour else 'OUTLINER_COLLECTION', emboss=coll.name == s.picked)
        op.action, op.name = 'HOME', coll.name
        tag = "Home" if coll.name == home else ("+ Deform" if coll.name.lower() in bc.DEFORM_SETS and coll.name in members
                                                else ("In" if coll.name in members else ""))
        if tag:
            row.label(text="")
            label = row.row()
            label.alignment = 'RIGHT'
            label.label(text=tag)
    row = body.row(align=True)
    for action, text in (('HOME', "Move Here"), ('ADD', "Also Add"), ('REMOVE', "Remove")):
        op = row.operator(ops.DIGITOOLS_OT_bw_collection.bl_idname, text=text)
        op.action, op.name = action, s.picked
    row = body.row(align=True)
    row.operator(ops.DIGITOOLS_OT_bw_collection.bl_idname, text="Auto-Sort by Name").action = 'SORT'
    row.operator(ops.DIGITOOLS_OT_bw_collection.bl_idname, text="Make Collection…").action = 'MAKE'
    hint(body, context, 'collections')


def draw_settings(layout, context, s, pb):
    body = open_section(layout, "settings", "Bone Settings")
    if not body:
        return
    toggle_op(body.row(), pb.bone.use_deform, "Deform", 'DEFORM', pb.bone.use_connect, "Connected", 'CONNECTED')
    col = body.column(align=True)
    for prop in ("inherit_rotation", "local_location", "hide"):
        slider(col, s, prop, pb)
    col.operator(DIGITOOLS_OT_toggle_bones_in_front.bl_idname, text="Bones In Front", icon='XRAY', emboss=False)
    hint(body, context, 'deform')
    for prop, label in (("inherit_scale", "Inherit Scale"), ("rotation_mode", "Rotation")):
        slider(labelled(body, label), s, prop, pb, text="")
    slider(body, s, "bbone_segments", pb)
    body.label(text="Lock (stop on an axis)")
    for prop, label in (("lock_location", "Move"), ("lock_rotation", "Turn"), ("lock_scale", "Scale")):
        row = labelled(body, label)
        if props.LIVE_SLIDERS:
            for index, axis in enumerate("XYZ"):
                row.prop(s, prop, index=index, text=axis, toggle=True)
        else:
            slider(row, s, prop, pb, text="")


def toggle_op(row, first_on, first_text, first_setting, second_on, second_text, second_setting):
    """Two operator buttons drawn like checkboxes (Deform and Connected change collections or need Edit Mode)."""
    for on, text, setting in ((first_on, first_text, first_setting), (second_on, second_text, second_setting)):
        row.operator(ops.DIGITOOLS_OT_bw_toggle.bl_idname, text=text, emboss=False,
                     icon='CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT').setting = setting


class DIGITOOLS_MT_bw_setups(bpy.types.Menu):
    """The constraint setups, grouped (bone_setups.SETUPS)"""
    bl_idname = "DIGITOOLS_MT_bw_setups"
    bl_label = "Constraint Setups"

    def draw(self, context):
        layout = self.layout
        for k, group in enumerate(setups.GROUPS):
            if k:
                layout.separator()
            layout.label(text=group)
            for setup in (x for x in setups.SETUPS if x.group == group):
                op = layout.operator(ops.DIGITOOLS_OT_bw_setup.bl_idname, text=setup.label)
                op.action, op.setup = 'PICK', setup.id


IK_EXPLAIN = {'INLINE': "Inline: the IK bone lies along the hand. The hand turns with it.",
              'END': "At End: a small IK bone at the tip. The hand keeps its own turn."}


def draw_setups(layout, context, s, pb):
    setup = setups.BY_ID.get(s.setup, setups.SETUPS[0])
    body = open_section(layout, "setups", "Constraint Setups", right=setup.label)
    if not body:
        return
    labelled(body, "Setup").menu(DIGITOOLS_MT_bw_setups.bl_idname, text=f"{setup.group} › {setup.label}")
    box = body.column()
    box.separator(type='LINE')
    box.label(text=setup.label)
    wrapped(box, setup.desc, context=context)
    sel = setups.Selection.of(context)
    why = setups.why_not(setup, sel, s)
    need = box.column()
    need.alert = bool(why)
    wrapped(need, why or "Ready: " + setup.needs, icon='ERROR' if why else 'CHECKMARK', context=context)
    for prop in setup.options:
        if prop in ("ik_new", "ik_place"):
            labelled(box, props.DIGITOOLS_PG_bone_workshop.bl_rna.properties[prop].name).prop(s, prop, expand=True)
            if prop == "ik_new" and s.ik_new == 'EXISTING':
                box.prop_search(s, "ik_bone", pb.id_data.pose, "bones", text="", icon='BONE_DATA')
            if prop == "ik_place":
                hints(box, [IK_EXPLAIN[s.ik_place]], context)
        elif prop == "curl_axes":
            row = labelled(box, "Axes")
            for index, axis in enumerate("XYZ"):
                row.prop(s, prop, index=index, text=axis, toggle=True)
        else:
            box.prop(s, prop)
    hints(box, ["Adds: " + setup.adds], context)
    row = action_row(box, 1.2)
    row.enabled = not why
    row.operator(ops.DIGITOOLS_OT_bw_setup.bl_idname, text="Add Setup", icon='CONSTRAINT_BONE').action = 'ADD'
    action_row(box, 1.0).operator(ops.DIGITOOLS_OT_bw_try_setup.bl_idname, text="Try It", icon='PLAY')
    hint(box, context, 'try_it')
    draw_on_bone(body, context, pb)


def draw_on_bone(layout, context, pb):
    col = layout.column(align=True)
    col.label(text=f"On {shorten(pb.name, 22)} now")
    if not len(pb.constraints):
        hints(col, ["No constraints"], context)
        return
    for c in pb.constraints:
        row = col.row(align=True)
        row.prop(c, "mute", text="", invert_checkbox=True, emboss=False)
        row.label(text=shorten(c.name, 16))
        grey = row.row()
        grey.active = False
        grey.label(text=setups.made_by(c.name))
        op = row.operator(ops.DIGITOOLS_OT_bw_constraint.bl_idname, text="", icon='X', emboss=False)
        op.action, op.name = 'REMOVE', c.name
    row = layout.row(align=True)
    row.operator(ops.DIGITOOLS_OT_bw_constraint.bl_idname, text="Mute All").action = 'MUTE'
    row.operator(ops.DIGITOOLS_OT_bw_constraint.bl_idname, text="Copy to Mirror Side").action = 'MIRROR'


def draw_name(layout, context, s, pb):
    body = open_section(layout, "name", "Name & Role")
    if not body:
        return
    role = spec.role_of(pb.name)
    body.label(text="Role")
    row = body.row(align=True)
    for ident, label, _tip in spec.ROLES:
        op = row.operator(ops.DIGITOOLS_OT_bw_name.bl_idname, text=label, depress=ident == role)
        op.action, op.role = 'ROLE', ident
    if role == 'OTHER':
        hints(body, [f"Prefix {rn.split_role(pb.name)[0]}-: pick a role to change it"], context)
    labelled(body, "Name").prop(pb, "name", text="")
    if rn.is_standard(pb.name):
        body.label(text="Fits the bone-name standard", icon='CHECKMARK')
    else:
        standard = rn.standard(pb.name, bw.home_of(pb), pb.bone.use_deform)
        body.operator(ops.DIGITOOLS_OT_bw_name.bl_idname, text=f"Rename to {shorten(standard, 22)}",
                      icon='SORTALPHA').action = 'STANDARD'
    other = rn.flip(pb.name)
    if other != pb.name:
        body.operator(ops.DIGITOOLS_OT_bw_name.bl_idname, text=f"Select Mirror ({shorten(other, 18)})",
                      icon='MOD_MIRROR').action = 'MIRROR'
    hint(body, context, 'name')


def draw_rig_check(layout, context):
    found = rig_check.results(context)
    right = "" if found is None else (f"{len(found)} found" if found else "all good")
    body = open_section(layout, "rig_check", "Rig Check", default_closed=True, right=right)
    if not body:
        return
    action_row(body, 1.1).operator(rig_check.DIGITOOLS_OT_bw_rig_check.bl_idname,
                                   text="Check Rig" if found is None else "Rescan", icon='VIEWZOOM')
    if found is None:
        hint(body, context, 'rig_check')
        return
    if not found:
        body.label(text="Nothing to fix", icon='CHECKMARK')
    for check, finding in found:
        oops_ui.draw_finding(body, check, finding, rig_check.DIGITOOLS_OT_bw_rig_fix.bl_idname)
    hints(body, ["Changed the rig? Press Rescan."], context)


def draw_bottom(layout):
    row = action_row(layout)
    row.operator(ops.DIGITOOLS_OT_bw_copy.bl_idname, text="Copy Active to Selected", icon='PASTEDOWN').action = 'SELECTED'
    row.operator(ops.DIGITOOLS_OT_bw_pick_look.bl_idname, text="", icon='EYEDROPPER')
    action_row(layout).operator(ops.DIGITOOLS_OT_bw_copy.bl_idname, text="Mirror to Other Side",
                                icon='MOD_MIRROR').action = 'MIRROR'


def draw_editing(layout, s):
    status(layout, f"Editing {s.editing_shape}", icon='EDITMODE_HLT')
    action_row(layout).operator(ops.DIGITOOLS_OT_bw_edit_shape.bl_idname, text="Done Editing Shape",
                                icon='CHECKMARK').action = 'DONE'
    hints(layout, [spec.HINTS['edit_shape']])


def draw_card(layout, context):
    s = props.settings_of(context)
    if s.editing_shape:
        draw_editing(layout, s)
        return
    why = ops.pose_why(context)
    if why:
        status(layout, why, icon='INFO')
        if context.mode != 'POSE':
            action_row(layout).operator(ops.DIGITOOLS_OT_bw_pose_mode.bl_idname, icon='POSE_HLT')
        draw_rig_check(layout, context)
        return
    pb = context.active_pose_bone
    head = layout.row()
    head.label(text=f"{shorten(pb.id_data.name, 20)} · Pose Mode", icon='ARMATURE_DATA')
    head.prop(s, "show_hints", text="", icon='INFO')
    found = bw.targets(context)
    reason = bw.why_not(pb.id_data, 'pose')
    if reason:
        hints(layout, [reason], context)
        return
    draw_target(layout, context, s, found)
    for draw in (draw_presets, draw_shape, draw_size, draw_colour, draw_collections, draw_settings, draw_setups,
                 draw_name):
        draw(layout, context, s, pb)
    draw_rig_check(layout, context)
    draw_bottom(layout)
    data_why = bw.why_not(pb.id_data, 'data')
    if data_why:
        hints(layout, [data_why], context)


classes = ops.classes + rig_check.classes + (DIGITOOLS_MT_bw_setups,)


def load_icons():
    previews = bpy.utils.previews.new()
    for tile in spec.SHAPES:
        path = os.path.join(ICON_FOLDER, f"{tile.id}.png")
        if os.path.exists(path):
            previews.load(tile.id, path, 'IMAGE')
    ICONS["previews"] = previews


def register():
    load_icons()
    props.register()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    props.unregister()
    previews = ICONS.pop("previews", None)
    if previews is not None:
        bpy.utils.previews.remove(previews)
