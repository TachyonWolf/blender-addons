# SPDX-License-Identifier: GPL-3.0-or-later
"""Help in the headset (DESIGN "Help button"), only while the setting `help_on` is on (zero cost off): a small tip beside the
panel widget a laser points at (dim widgets say why), and what each controller button does now for the Help panel
(`router.help_labels`: one source). Nothing is drawn at the hands [user, 2026-11-25]."""
from mathutils import Vector

from . import annotate, box_math, help_text, panel, router, settings, shape_math, tool_gun
from .action_map import HANDS
from .runtime import RUNTIME
from .size_state import SIZE

CHAR_WIDTH = 0.32          # tag width in heights per character (name_tag: 36 px text in a 56 px row)
TIP_SIZE = dict(height_per_metre=0.02, min_height=0.016)      # smaller than a name tag [user: small]


def _tag(text, point, head, align):
    """(label, base, right, up, height) for a tag whose centre-left (align 'l') or centre-right ('r') is at `point`."""
    base, right, up, height = shape_math.tag_frame(point, head, **TIP_SIZE, size=SIZE.factor)
    width = (CHAR_WIDTH * len(text) + 0.64) * height
    length = max(1e-6, (right[0] ** 2 + right[1] ** 2) ** 0.5)
    unit = (right[0] / length, right[1] / length, 0.0)
    shift = -width if align == 'r' else 0.0
    return (text, (base[0] + unit[0] * shift, base[1] + unit[1] * shift, base[2] - height * 1.3), right, up, height)


def tips(state):
    """Tags (for name_tag.matrices) beside the pointed-at panel widgets."""
    head, paused = Vector(state.viewer_pose_location), settings.get("paused")
    tags = []
    for each in panel.REGISTRY.values():
        if not each.state.open:
            continue
        for hand, widget_id in list(each.state.hover.items()):
            widget = each.renderer.by_id.get(widget_id)
            if widget is None or widget.kind in ("HANDLE", "LABEL"):
                continue
            text = help_text.line(widget.id, widget.enabled, paused)
            if not text:
                continue
            left = widget.x + widget.w / 2 < each.spec.width / 2
            local_x, local_y = each.spec.pixel_to_local(widget.x + widget.w if left else widget.x, widget.y + widget.h / 2)
            point = each.state.matrix() @ Vector((local_x, local_y, 0.0))
            tags.append(_tag(text, point, head, 'l' if left else 'r'))
    return tags


def rows(context):
    """((hand, button, title, second line), ...) of every button that does something now."""
    boxing = next(((hand, state.gesture) for hand, state in RUNTIME.hands.items()
                   if state.gesture is not None and state.gesture.boxing), None)
    boxing_hand = None if boxing is None else (router.HAND_L if boxing[0] == HANDS[0] else router.HAND_R)
    gun = None
    if tool_gun.GUN.held_by is not None:
        gun = (router.HAND_L if tool_gun.GUN.held_by == HANDS[0] else router.HAND_R, tool_gun.tool_label())
    labels = router.help_labels(router.mode_kind(context.mode), settings.get("grab_mode"), annotate.is_on(context),
                                settings.get("move_mode"), settings.get("paused"),
                                any(state.grab is not None for state in RUNTIME.hands.values()), boxing_hand,
                                settings.get("fine_control"),
                                boxing is not None and boxing[1].shape == box_math.VOLUME,
                                gun=gun, edit_tool=settings.get("edit_tool"),
                                bubble=router.bubble_on(router.mode_kind(context.mode), settings.get("edit_tool"), settings.get("object_tool")))
    return tuple((hand, button, *text) for hand, buttons in labels.items() for button, text in buttons.items())
