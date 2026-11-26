# SPDX-License-Identifier: GPL-3.0-or-later
"""All floating panels together (desk, tool options, viewpoints): what the session, controls, hover, overlay and
your size talk to. Panels win over the scene: a laser on an open panel takes the trigger (the nearest panel wins), a
grip near a handle takes the grip. Every panel closed = the desk's button poll and nothing else."""
from . import camera_panel, desk, keyboard, panel_layout as layout, pda, poke, settings, stick_claim, tool_gun, tool_options, viewpoints
from .action_map import HANDS
from .hands import HandPose
from .runtime import RUNTIME

PANELS = (desk.PANEL, tool_options.PANEL, viewpoints.PANEL, pda.PANEL, keyboard.PANEL, tool_gun.PANEL, camera_panel.PANEL)


def _open_panels():
    return [panel for panel in PANELS if panel.state.open]


def any_open():
    return any(panel.state.open for panel in PANELS)


def laser_reach(hand):
    """Distance from a hand's laser to the nearest open panel it points at (panels win over the scene), else None."""
    reaches = [reach for reach in (panel.laser_reach(hand) for panel in PANELS) if reach is not None]
    return min(reaches) if reaches else None


def hovered_button(hand):
    """(panel name, widget id) of the working button, slider or handle under a hand's laser, else None."""
    for panel in _open_panels():
        widget = panel.renderer.by_id.get(panel.state.hover.get(hand))
        if widget is not None and widget.enabled and widget.action and widget.kind != layout.BACKDROP:
            return panel.name, widget.id
    return None


def start(context):
    desk.reset_buttons()
    for panel in PANELS:
        panel.start(context)


def teardown():
    poke.reset()
    stick_claim.reset()
    for panel in PANELS:
        panel.teardown()


def _nearest_hit(open_panels, pose):
    """(panel, hit) of the nearest open panel the laser meets, or (None, None)."""
    best_panel, best_hit = None, None
    for panel in open_panels:
        hit = panel.ray_hit(pose, panel.state.matrix())
        if hit is not None and (best_hit is None or hit[2] < best_hit[2]):
            best_panel, best_hit = panel, hit
    return best_panel, best_hit


def _hover(context, state, open_panels):
    always = settings.get("always_laser")
    for hand in HANDS:
        hand_state = RUNTIME.hands[hand]
        nearest, hit = None, None
        if hand_state.trigger_touched or hand_state.trigger_down or always:
            nearest, hit = _nearest_hit(open_panels, HandPose(context, state, hand, with_grip_rotation=False))
        for panel in open_panels:
            panel.set_hover(context, hand, hit if panel is nearest else None)


def trigger_pressed(context, state, hand):
    """Trigger pull. True when the laser is on an open panel: that panel takes the press."""
    open_panels = _open_panels()
    if not open_panels:
        return False
    panel, hit = _nearest_hit(open_panels, HandPose(context, state, hand, with_grip_rotation=False))
    return panel is not None and panel.press(context, state, hand, hit)


def grip_pressed(context, state, hand):
    """Grip press. True when a panel took it (a handle, or a desk thumbnail). The panel under the laser asks first."""
    open_panels = _open_panels()
    if not open_panels:
        return False
    pose = HandPose(context, state, hand)
    open_panels.sort(key=lambda panel: hand not in panel.state.hover)
    return any(panel.grip(context, state, hand, pose) for panel in open_panels)


def tick(context, state):
    """Once per session tick. Returns True while a handle is held (the timer then runs every frame)."""
    desk.poll_buttons(context, state)
    open_panels = _open_panels()
    if not open_panels:
        stick_claim.update(context, state, open_panels)       # a stick that scrolled a list still waits for the centre
        return False
    for panel in open_panels:
        panel.release_triggers(context, state)
    _hover(context, state, open_panels)
    stick_claim.update(context, state, open_panels)           # a stick on a list scrolls it and does not move you
    poke.update(context, state, open_panels)         # fingertips pressing into buttons
    busy = False
    for panel in open_panels:
        busy = panel.tick(context, state) or busy
    return busy


def draw(new_frame):
    """One eye: every open panel (inside overlay.draw)."""
    for panel in PANELS:
        if panel.state.open:
            panel.draw(new_frame)
