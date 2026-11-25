# SPDX-License-Identifier: GPL-3.0-or-later
"""The Selected panel of Digit's Tools and Digit's Modifiers (shared: Addons/shared_addon/selected_ui.py is the ONE source, sync_shared.py
copies it into each extension; each extension has its own registry): the context actions for what is selected now. Every module that has
something deployed in the world with properties to control (Camera Rig, Lighting Rig, Bounce Cards, Photo
Backdrop, Shadow Catcher, Catchlight; later rigs the same way) registers a provider with add(); the panel draws one
framed, collapsible box per selected thing (heading = its plain-words name, like "Camera Rig · Aim"), the provider's
controls under it. TWEAK ONLY, NO BUILDING: the card has sliders, toggles, presets, picks (Pick Focus, Frame Subject), select-part / helper
buttons, Re-rest, Reset Pose, Snap IK/FK, Unlock / Make Editable. Deploy, add, generate / rebuild / upgrade, make, combine
and remove / delete live in the tool cards (tests scan every provider for the BUILDING_OPERATORS deny-list). Generic helpers (Modifier Helper Object, Combine Bones, Stretch Bones) are dropdown tools instead.

    selected_ui.add("Camera Rig", poll, title, draw)   # poll(context) -> bool, title(context) -> str (or (str, grey header summary)),
                                                       # draw(box, context)
    selected_ui.add_each("Toony Modifiers", entries, draw)   # entries(context) -> [(key, title, thing)];
                                                             # draw(box, context, thing): one box per entry
"""
from functools import partial

from .ui_cards import hints, inside_frame, object_box  # generated copy

BUILDING_WORDS = ("deploy", "remove", "delete", "rebuild", "upgrade", "generate", "build", "combine", "make_helper",
                  "add_modifier", "taffy_add")   # operator id endings a Selected card must not use (tests check)
PROVIDERS = {}   # name -> (poll, title, draw); drawn A-Z by name
EACH = {}        # name -> (entries, draw): providers that give one box per thing, e.g. per object


def add(name, poll, title, draw):
    """Register (or replace) the provider `name`."""
    PROVIDERS[name] = (poll, title, draw)


def add_each(name, entries, draw):
    """Register (or replace) a provider `name` with one box per entry: `entries(context)` -> [(key, title, thing)] (the
    key makes the box's folded state unique), `draw(box, context, thing)`."""
    EACH[name] = (entries, draw)


def matching(context):
    """[(name, title, draw)] of the providers that apply to the current selection, A-Z."""
    found = []
    for name in sorted({*PROVIDERS, *EACH}):
        if name in PROVIDERS:
            poll, title, draw = PROVIDERS[name]
            if poll(context):
                found.append((name, title(context), draw))
        else:
            entries, draw = EACH[name]
            found += [(f"{name} {key}", title, partial(draw, thing=thing)) for key, title, thing in entries(context)]
    return found


def selected_names(context, arm=None):
    """Names of the selected bones in Pose / Edit Mode (those of the armature object `arm` only, when given)."""
    if context.mode == 'POSE':
        return [pb.name for pb in (context.selected_pose_bones or []) if arm is None or pb.id_data == arm]
    if context.mode == 'EDIT_ARMATURE':
        return [eb.name for eb in (context.selected_editable_bones or []) if arm is None or eb.id_data == arm.data]
    return []


def bone_mode(context):
    """True while an armature is active in Pose or Edit Mode (its bones are the selection that matters)."""
    ob = context.active_object
    return ob is not None and ob.type == 'ARMATURE' and context.mode in ('POSE', 'EDIT_ARMATURE')


def subject(context):
    """The active object, else the first selected one, else None."""
    return context.active_object or next(iter(context.selected_objects), None)


EMPTY = ("Select a deployed rig to edit it", "nothing")   # (grey hint, header summary) when nothing applies


def header_summary(context, empty=EMPTY):
    """The grey summary for the Selected panel's header: "2 objects", or the `empty` pair's second text."""
    found = matching(context)
    if not found:
        return empty(context)[1] if callable(empty) else empty[1]
    return f"{len(found)} object{'' if len(found) == 1 else 's'}"


def draw_body(layout, context, idname="chartools_selected", empty=EMPTY):
    """The body of the Selected panel (a top-level sidebar panel of its own, first in its tab): the live controls of the
    deployed things that are selected, one framed box per thing, each part inside it a plain arrow group
    (no frame in a frame). Anything else selected: one grey hint. `idname` keeps the folded states apart per add-on;
    `empty` = (hint, header summary) or a function of the context giving that pair."""
    found = matching(context)
    if not found:
        hints(layout, [empty(context)[0] if callable(empty) else empty[0]], context)
        return
    for i, (name, title, draw) in enumerate(found):
        # the first box starts open, the rest closed; the state is remembered per provider
        title, right = title if isinstance(title, tuple) else (title, None)   # a provider may add a header summary
        box = object_box(layout, idname + "_" + name.lower().replace(" ", "_"), title, default_closed=i > 0, right=right)
        if box is not None:
            with inside_frame():
                draw(box, context)
