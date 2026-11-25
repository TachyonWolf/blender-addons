# SPDX-License-Identifier: GPL-3.0-or-later
"""The Look sub-sections (Polish / Fog / Lens / Film): On (needs Apply), Start With, and live sliders
that draw the applied chain's node inputs straight (so a change re-composites at once, and saved
presets get them too). Inputs a Fog Mark drives show "from mark" and can't be typed into."""

from . import builtin_presets as bp, fog_marks, look_nodes, setup_props
from .ui_cards import group, hints, section, smart_prop

CYCLES_HINT = "Cycles viewport has no depth pass. Render once (F12), then tweaks re-composite the result."
SAMPLE_WORLD_OPERATOR = "render_presets.sample_world"
LOOK_OPTIONS = bp.options_in_group(bp.LOOK)


def on_labels(setup):
    return [option.label for option in LOOK_OPTIONS if getattr(setup, option.id)]


def draw_setup_look(layout, context, setup):
    """Setup > Look: every Look group, with On and Start With."""
    body = section(layout, "render_presets_setup_look", "Look", right=", ".join(on_labels(setup)) or "None")
    if body:
        draw_look_groups(body, context, setup, LOOK_OPTIONS)


def draw_saved_look(layout, context):
    """For a saved preset: the live sliders of the groups the scene's compositor has."""
    present = [option for option in LOOK_OPTIONS if look_nodes.chain_node(context.scene, option.chain_group)]
    if not present:
        return
    body = section(layout, "render_presets_look", "Look", icon='SHADING_RENDERED',
                   right=", ".join(option.label for option in present))
    if body:
        draw_look_groups(body, context, None, present)


def draw_look_groups(layout, context, setup, options):
    for option in options:
        draw_look_group(layout, context, setup, option)
    if context.scene.render.engine == 'CYCLES' and _fog_wanted(context.scene, setup):
        hints(layout, [CYCLES_HINT], context)


def _fog_wanted(scene, setup):
    return (setup is not None and setup.fog) or look_nodes.chain_node(scene, look_nodes.FOG_GROUP) is not None


def draw_look_group(layout, context, setup, option):
    node = look_nodes.chain_node(context.scene, option.chain_group)
    is_on = getattr(setup, option.id) if setup else node is not None
    extra = (lambda header: header_toggle(header, setup, option)) if setup else None
    body = group(layout, f"render_presets_look_{option.id}", option.label, default_closed=not is_on, extra=extra)
    if body is None:
        return
    if setup:
        body.prop(setup, setup_props.start_picker_attr(option), text="Start With")
    hints(body, [apply_hint(option, is_on, node, setup)], context)
    if option.chain_group == look_nodes.FOG_GROUP:
        fog_marks.draw_rows(body, context)
    if node is not None:
        draw_inputs(body, node)


def header_toggle(header, setup, option):
    """The group's On checkbox in its header (never split, or it gets pushed right)."""
    header.use_property_split = False
    header.prop(setup, option.id, text="")


def apply_hint(option, is_on, node, setup):
    """Turning a group on or off takes an Apply (it adds or removes a compositor node)."""
    if setup is None:
        return ""
    if is_on and node is None:
        return f"Apply to add {option.label}"
    if not is_on and node is not None:
        return f"Apply to remove {option.label}"
    return ""


def look_rows(names):
    """The input names as rows: ("effect", on name, amount name, label) for "<X> On" + "<X> Amount",
    else ("input", name)."""
    rows, i = [], 0
    while i < len(names):
        name = names[i]
        amount = name[:-3] + " Amount" if name.endswith(" On") else ""
        if amount and i + 1 < len(names) and names[i + 1] == amount:
            rows.append(("effect", name, amount, name[:-3]))
            i += 2
        else:
            rows.append(("input", name))
            i += 1
    return rows


def draw_inputs(layout, node):
    driven = look_nodes.driven_inputs(node)
    col = layout.column(align=True)
    for row in look_rows(bp.LOOK_INPUTS.get(node.label, ())):
        if row[0] == "effect":
            _, on_name, amount_name, label = row
            if on_name in node.inputs and amount_name in node.inputs:
                draw_effect_row(col, node.inputs[on_name], node.inputs[amount_name], label)
            continue
        socket = node.inputs.get(row[1])
        if socket is None:
            continue
        if socket.name in driven:
            draw_driven_row(col, socket)
        elif socket.name == look_nodes.FOG_COLOUR:
            draw_fog_colour_row(col, socket)
        else:
            smart_prop(col, socket, "default_value", text=socket.name)


def draw_effect_row(layout, on_socket, amount_socket, label):
    """One effect: its On checkbox and its Amount slider on one line."""
    row = layout.row(align=True)
    row.use_property_split = False
    row.prop(on_socket, "default_value", text="")
    amount = row.row(align=True)
    amount.active = bool(on_socket.default_value)
    amount.prop(amount_socket, "default_value", text=label)


def draw_driven_row(layout, socket):
    """A driven input: its value greyed and locked, with where it comes from."""
    row = layout.row(align=True)
    value = row.row(align=True)
    value.enabled = False
    value.prop(socket, "default_value", text=socket.name)
    row.label(text="from mark")


def draw_fog_colour_row(layout, socket):
    layout.prop(socket, "default_value", text=socket.name)
    layout.operator(SAMPLE_WORLD_OPERATOR, text="Sample World", icon='WORLD')
