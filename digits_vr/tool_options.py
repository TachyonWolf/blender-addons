# SPDX-License-Identifier: GPL-3.0-or-later
"""The tool options panel (bpy side): a floating panel opened / closed by the desk's Tool options button. Its rows are the
current mode's tools and settings (tool_rows.py; what they show and do: tool_actions.py and desk_actions.py, the same as on
the desk's Tools page). Its own: the Attached toggle and which of its pop-ups is open."""
from . import color_picker, desk_actions, settings, tool_actions, tool_options_layout as layout, tool_rows
from .panel import Panel

LIST_POPUPS = ('layer', *color_picker.POPUPS, *tool_rows.LIST_POPUPS)         # dropdown lists: a pick closes them
_open = [""]                      # this panel's open pop-up


def build_model(context):
    return layout.ToolOptionsModel(attached=settings.get("tool_options_attached"), popup=_open[0],
                                   **tool_actions.fields(context))


def perform(context, widget, pixel_x):
    if not widget.enabled or not widget.action:
        return False
    if widget.action[0] == "popup":
        _open[0] = "" if _open[0] == widget.action[1] else widget.action[1]
        tool_actions.popup_opened(context, _open[0])
        return True
    if widget.action[0] == "attached":
        settings.put("tool_options_attached", not settings.get("tool_options_attached"))     # belt.py reads it
        return True
    done = desk_actions.perform(context, widget, pixel_x)
    if _open[0] in LIST_POPUPS and widget.action[0] not in tool_rows.KEEP_OPEN:
        _open[0] = ""
        done = True
    if done:
        desk_actions.forget_model()
    return done


class ToolOptionsPanel(Panel):
    name = "tool_options"
    spec = layout.SPEC
    open_side = 0.45            # first opens to the right of the desk (clear of its handle)
    open_drop = 0.1

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget, pixel_x)

    def closed(self):
        _open[0] = ""


PANEL = ToolOptionsPanel()
