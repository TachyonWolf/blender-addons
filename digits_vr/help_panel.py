# SPDX-License-Identifier: GPL-3.0-or-later
"""The Help panel (bpy side; DESIGN "Help panel"): its own floating panel with the Tooltips toggle (`help_on`) and the
Controls pictures. Opened by the desk's Help button; opens itself once on the first VR start, with Tooltips on. Handles,
Pin and the belt (belt_items.HELP_ITEM) are the shared panel / held-item code; the tips themselves are help_draw's and the
labels come from router.help_labels (one source)."""
from . import help_art, help_draw, help_layout as layout, settings
from .panel import Panel


def build_model(context):
    return layout.HelpModel(rows=help_draw.rows(context), tooltips=settings.get("help_on"))


def perform(widget):
    if not widget.enabled or widget.action != ("toggle", "help_on"):
        return False
    settings.put("help_on", not settings.get("help_on"))
    return True


def first_start():
    """The first VR start of a new user: the Help panel opens, with Tooltips on. After that it stays as it was left."""
    if settings.get("help_seen"):
        return False
    settings.put_many({"help_seen": True, "help_on": True, "help_open": True})
    return True


class HelpPanel(Panel):
    name = "help"
    spec = layout.SPEC
    open_side = 0.5             # first opens to the right and a bit farther off, clear of the desk in front (tool options: right too)
    open_distance = 0.7
    open_drop = 0.1

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(widget)

    def load(self):
        first_start()

    def open(self, context, state, remember=True):
        help_art.load()             # the controller pictures are read when the panel opens, never in a draw callback
        super().open(context, state, remember)

    def closed(self):
        help_art.free()


PANEL = HelpPanel()
