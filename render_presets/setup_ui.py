# SPDX-License-Identifier: GPL-3.0-or-later
"""The Setup section of a built-in preset: Quality / Speed / Look / Output rows drawn from
builtin_presets.OPTIONS, then Reset to Defaults and Save as My Preset."""

from . import builtin_presets as bp, look_ui, setup_props
from .ui_cards import action_row, choice_row, hints, inside_frame, section, smart_prop

GROUP_DRAW_ORDER = (bp.QUALITY, bp.SPEED, bp.LOOK, bp.OUTPUT)
SUMMARY_OPTIONS = {bp.QUALITY: ("samples", "noise_threshold"), bp.SPEED: ("texture_limit",)}
RESET_OPERATOR = "render_presets.reset_setup"
SAVE_OPERATOR = "render_presets.save_setup"


def draw_setup(layout, context, setup):
    body = section(layout, "render_presets_setup", "Setup", icon='PREFERENCES', right=setup.builtin_name)
    if not body:
        return
    with inside_frame():
        for group_id in GROUP_DRAW_ORDER:
            if group_id == bp.LOOK:
                look_ui.draw_setup_look(body, context, setup)
            else:
                draw_option_group(body, setup, group_id)
    row = action_row(body, scale=1.0)
    row.operator(RESET_OPERATOR, icon='LOOP_BACK')
    row.operator(SAVE_OPERATOR, icon='FILE_TICK')
    hints(body, ["Tweaks are stored in this scene"], context)


def draw_option_group(layout, setup, group_id):
    body = section(layout, f"render_presets_setup_{group_id}", bp.GROUP_LABELS[group_id], default_closed=True,
                   right=group_summary(setup, group_id))
    if body:
        for option in bp.options_in_group(group_id):
            draw_option(body, setup, option)


def draw_option(layout, setup, option):
    """One option row: Keep / On / Off, a value with a Keep toggle, a checkbox or a value."""
    if option.id in setup.keep_ids and option.type == "bool":
        choice_row(layout, setup, option.id, label=option.label, factor=0.45)
    elif option.id in setup.keep_ids:
        row = layout.row(align=True)
        value = row.row(align=True)
        value.enabled = not getattr(setup, setup_props.keep_attr(option))
        value.prop(setup, option.id, text=option.label)
        row.prop(setup, setup_props.keep_attr(option), text="Keep", toggle=True)
    else:
        smart_prop(layout, setup, option.id, text=option.label)


def option_text(setup, option):
    """An option's value in a few characters, for a folded header."""
    value = setup_props.option_value(setup, option)
    if value is None:
        return "Keep"
    if isinstance(value, bool):
        return "On" if value else "Off"
    if option.type == "choice":
        return setup_props.choice_label(value)
    return f"{value:g}" if isinstance(value, float) else str(value)


def group_summary(setup, group_id):
    """"4096 · 0.02" for Quality, the texture limit for Speed, "2 on" for checkbox groups."""
    names = SUMMARY_OPTIONS.get(group_id)
    if names:
        return " · ".join(option_text(setup, bp.OPTION_BY_ID[name]) for name in names)
    on = sum(1 for option in bp.options_in_group(group_id) if setup_props.option_value(setup, option))
    return f"{on} on"
