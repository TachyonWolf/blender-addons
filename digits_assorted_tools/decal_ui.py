# SPDX-License-Identifier: GPL-3.0-or-later
"""Decals: the card (Digit's Tools > Object > Decals), the Import dialog's look and the Selected panel's Decal box.
Layout follows notes/wip/decals-mockups/Main.dc.html and Import.dc.html.

Card vs Selected panel, no logic twice: `draw_state` (state line + Attach / Stick / Unstick / Re-aim / Rebind,
and Detach in the Selected box) is drawn by both; every button is an operator that calls decal_mesh. Place, Look,
Maps and the list stay in the card. The card reads data only while it is open: the list is the Target's children,
one vertex count per draw for the Rebind check; the Selected poll looks at the active object only."""

import bpy

from . import decal_maps, decal_material, decal_mesh, selected_ui
from .decal_import_ops import is_image_empty, thumbnail
from .decal_recipe import FADES, PLACING, STUCK, UNATTACHED
from .ui_cards import action_row, choice_row, hints, prop_group, section, toggles, wrapped  # generated copy

STATE_LOOKS = {UNATTACHED: ("Unattached", "Unattached: ready to attach", 'UNLINKED'),
               PLACING: ("Placing", "Placing: slides on surface", 'UNPINNED'),
               STUCK: ("Stuck", "Stuck: follows the rig", 'PINNED')}
REBIND_LOOK = ("Rebind", "Rebind: the mesh changed", 'ERROR')
LIST_ICON = 'IMAGE_PLANE'
TIP = "Tip: drag images onto an object in the viewport."
MOVED_HINT = "Moved it with G? Re-aim or the handles update the aim"


def state_look(decal, vertex_count=None):
    """(short word, line, icon, alert) of a decal's state."""
    if decal_mesh.needs_rebind(decal, vertex_count):
        return (*REBIND_LOOK, True)
    return (*STATE_LOOKS[decal.digit_decal.state], False)


def active_decal(context):
    ob = context.active_object
    return ob if decal_mesh.is_decal(ob) else None


def effective_target(context):
    """The card's Target, else the active decal's target, else the active mesh."""
    settings = context.scene.digit_decals
    if settings.target is not None:
        return settings.target
    decal = active_decal(context)
    if decal is not None:
        return decal.digit_decal.target
    ob = context.active_object
    return ob if ob is not None and ob.type == 'MESH' else None


# --- shared by the card and the Selected panel ---------------------------------------------------------------

def draw_state(layout, decal, with_detach=False):
    """The decal's state line and its state buttons."""
    _word, line, icon, alert = state_look(decal)
    row = layout.row()
    row.alert = alert
    row.label(text=line, icon=icon)
    state = decal.digit_decal.state
    buttons = action_row(layout, scale=1.2)
    if state == UNATTACHED:
        buttons.operator("decal.aim", text="Attach", icon='SNAP_FACE', depress=True).decal_name = decal.name
        return
    if alert:
        rebind = buttons.row(align=True)
        rebind.alert = True
        rebind.operator("decal.rebind", text="Rebind").decal_name = decal.name
    else:
        stick = buttons.row(align=True)
        stick.enabled = state == PLACING
        stick.operator("decal.stick", text="Stick", depress=state == PLACING).decal_name = decal.name
    unstick = buttons.row(align=True)
    unstick.enabled = state == STUCK
    unstick.operator("decal.unstick", text="Unstick").decal_name = decal.name
    buttons.operator("decal.aim", text="Re-aim").decal_name = decal.name
    if with_detach:
        layout.operator("decal.detach", text="Detach", icon='UNLINKED').decal_name = decal.name


# --- the card ---------------------------------------------------------------------------------------------

def draw_card(layout, context):
    settings = context.scene.digit_decals
    row = action_row(layout)
    row.operator("decal.add_images", text="Add from Images…", depress=True)
    convert = row.row(align=True)
    convert.enabled = is_image_empty(context.active_object)
    convert.operator("decal.convert_reference", text="From Reference")
    tip = layout.column()
    tip.active = False
    wrapped(tip, TIP, context=context)
    draw_viewport_row(layout, settings)
    draw_target_row(layout, settings)
    target = effective_target(context)
    if target is not None:
        draw_list(layout, context, target)
    else:
        hints(layout, ["Pick a target mesh, or add a decal"], context)
    decal = active_decal(context)
    if decal is not None:
        draw_active(layout, context, decal)
    bake = layout.column()
    bake.active = False
    body = section(bake, "decals_bake", "Bake into Texture", default_closed=True, right="later")
    if body:
        hints(body, ["Later: bake decals into the target's own textures"], context)
    body = section(layout, "decals_settings", "Options", default_closed=True)
    if body:
        toggles(body, settings, ["aim_after_place"], columns=1)
        prop_group(body, settings, ["default_lift", "layer_step"])


def draw_viewport_row(layout, settings):
    split = layout.split(factor=0.3, align=True)
    split.label(text="Viewport")
    right = split.row(align=True)
    right.prop(settings, "show_gizmos", text="Gizmos On", icon='GIZMO', toggle=True)
    note = layout.row()
    note.active = False
    note.label(text="Move / size / rotate handles")


def draw_target_row(layout, settings):
    split = layout.split(factor=0.3, align=True)
    split.label(text="Target")
    right = split.row(align=True)
    right.prop(settings, "target", text="")
    right.operator("decal.pick_target", text="", icon='EYEDROPPER')


def draw_list(layout, context, target):
    decals = decal_mesh.decals_of(target)
    active = context.active_object
    vertex_count = len(target.data.vertices)   # one count for the whole list's Rebind check
    split = layout.split(factor=0.88, align=True)
    rows = split.column(align=True)
    if not decals:
        empty = rows.row()
        empty.active = False
        empty.label(text="No decals yet")
    for decal in reversed(decals):      # top layer first, as drawn
        row = rows.row(align=True)
        row.active = not decal.hide_get()
        is_active = decal == active
        row.operator("decal.select", text=decal.name, icon=LIST_ICON, emboss=is_active,
                     depress=is_active).decal_name = decal.name
        word, _line, icon, alert = state_look(decal, vertex_count)
        tag = row.row(align=True)
        tag.alert = alert
        tag.label(text=word, icon=icon)
        row.operator("decal.toggle_hidden", text="", emboss=False,
                     icon='HIDE_ON' if decal.hide_get() else 'HIDE_OFF').decal_name = decal.name
    side = split.column(align=True)
    side.operator("decal.add_images", text="", icon='ADD')
    chosen = active.name if decal_mesh.is_decal(active) and active in decals else ""
    for operator, icon, props in (("decal.remove", 'REMOVE', {}), ("decal.move_layer", 'TRIA_UP', {"direction": 1}),
                                  ("decal.move_layer", 'TRIA_DOWN', {"direction": -1})):
        cell = side.row(align=True)
        cell.enabled = bool(chosen)
        op = cell.operator(operator, text="", icon=icon)
        op.decal_name = chosen
        for name, value in props.items():
            setattr(op, name, value)


def draw_active(layout, context, decal):
    word = state_look(decal)[0]
    body = section(layout, "decals_active", decal.name, right=word)
    if body:
        draw_state(body, decal)
    draw_place(layout, context, decal)
    draw_look(layout, context, decal)
    draw_maps(layout, decal)


def draw_place(layout, context, decal, prefix="decals"):
    """The Place section (card and Selected box; `prefix` keeps the fold ids apart, both live in one region)."""
    body = section(layout, f"{prefix}_place", "Place")
    if not body:
        return
    recipe = decal.digit_decal
    prop_group(body, recipe, [("size", "Size"), ("rotation", "Rotation"), ("lift", "Lift"), ("detail", "Detail")])
    prop_group(body, recipe, [("over_edges", "Over Edges")])
    angle = body.column()
    angle.enabled = recipe.over_edges in FADES
    prop_group(angle, recipe, [("edge_angle", "Edge Angle")])
    toggles(body, recipe, ["mirror_x", "flip"])
    if recipe.state == PLACING:
        hints(body, [MOVED_HINT], context)


def draw_look(layout, context, decal, prefix="decals"):
    """The Look section (card and Selected box): Shading and the Digit Decal node's inputs."""
    node = decal_material.look_node(decal.active_material)
    body = section(layout, f"{prefix}_look", "Look")
    if not body:
        return
    if node is None:
        hints(body, ["This decal's material has no Digit Decal node"], context)
        return
    choice_row(body, decal.digit_decal, "shading", label="Shading")
    column = body.column(align=True)
    column.use_property_split, column.use_property_decorate = True, False
    from_map = decal_material.map_image(decal.active_material, "ROUGHNESS") is not None
    for name, label in decal_material.LOOK_INPUTS:
        if name == "Roughness" and from_map:
            split = column.split(factor=0.4, align=True)
            split.alignment = 'RIGHT'
            split.label(text=label)
            value = split.row()
            value.active = False
            value.label(text="From map")
            continue
        column.prop(node.inputs[name], "default_value", text=label)


def draw_maps(layout, decal):
    body = section(layout, "decals_maps", "Maps")
    if not body:
        return
    material = decal.active_material
    _draw_map_rows(body, decal, material, "")
    if decal_material.has_back(material):
        body.label(text="Back")
        _draw_map_rows(body, decal, material, decal_maps.BACK_PREFIX)


def _draw_map_rows(body, decal, material, prefix):
    """One row per map slot; prefix "" = the front maps, BACK_PREFIX = the maps seen from behind."""
    for front, label in decal_maps.ROLES:
        role = prefix + front
        image = decal_material.map_image(material, role)
        split = body.split(factor=0.3, align=True)
        split.label(text=label)
        right = split.row(align=True)
        name = right.row(align=True)
        name.active = image is not None
        name.label(text=image.name if image else "none")
        op = right.operator("decal.browse_map", text="", icon='FILEBROWSER')
        op.decal_name, op.role = decal.name, role
        if image is not None and role != "COLOR":
            op = right.operator("decal.clear_map", text="", icon='X')
            op.decal_name, op.role = decal.name, role


# --- the Import dialog ---------------------------------------------------------------------------------------

def draw_import_dialog(operator, layout, context):
    """Import.dc.html: files + roles and placement on the left, the preview on the right."""
    split = layout.split(factor=0.58)
    left = split.column()
    header = left.split(factor=0.6)
    for text in ("File", "Used as"):
        cell = header.row()
        cell.active = False
        cell.label(text=text)
    for entry in operator.entries:
        row = left.split(factor=0.6, align=True)
        row.label(text=entry.filename, icon='IMAGE_DATA')
        row.prop(entry, "role", text="")
    help_line = left.column(align=True)
    help_line.active = False
    help_line.scale_y = 0.8
    help_line.label(text="Roles come from name endings: _color _normal _rough _metal _emit _alpha _height.")
    help_line.label(text="One image alone = sticker.")
    left.separator()
    form = left.column()
    form.use_property_split, form.use_property_decorate = True, False
    form.prop_search(operator, "target_name", bpy.data, "objects", text="Target", icon='MESH_DATA')
    choice_row(form, operator, "place_at", label="Place at")
    size = form.row(align=True)
    size.prop(operator, "size")
    long_side = size.row()
    long_side.active = False
    long_side.label(text="(long side)")
    choice_row(form, operator, "start_as", label="Start as")
    right = split.column()
    color = operator.file_of("COLOR")
    icon = thumbnail(color)
    if icon:
        right.template_icon(icon_value=icon, scale=9)
    roles = right.row(align=True)
    for role, label in decal_maps.ROLES:
        if operator.file_of(role):
            roles.label(text=label)
    note = right.row()
    note.active = False
    note.label(text=operator.crop_text)


# --- the Selected panel's Decal box --------------------------------------------------------------------------

def selected_title(context):
    decal = active_decal(context)
    return decal.name, state_look(decal)[0]


def draw_selected(box, context):
    """The Selected panel's Decal box: the state row, then the same Place and Look sections as the card."""
    decal = active_decal(context)
    draw_state(box, decal, with_detach=True)
    draw_place(box, context, decal, prefix="decals_selected")
    draw_look(box, context, decal, prefix="decals_selected")


def draw_convert_entry(self, context):
    """Object context menu: Convert to Decal, only on a Reference / Image empty."""
    if is_image_empty(getattr(context, "active_object", None)):
        self.layout.operator("decal.convert_reference", text="Convert to Decal", icon='IMAGE_PLANE')


selected_ui.add("Decal", lambda context: active_decal(context) is not None, selected_title, draw_selected)
