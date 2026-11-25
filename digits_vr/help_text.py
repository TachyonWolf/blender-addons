# SPDX-License-Identifier: GPL-3.0-or-later
"""The words of Help (DESIGN "Help button"): one plain sentence per panel widget, why a dim widget is dim, and the names of
what each controller button does. Pure Python (no bpy), tested headless. Tips are looked up by widget id: an exact id, else the
longest matching prefix. A tip is one short sentence (about 44 characters: it is drawn as one name-tag line)."""

TIPS = {
    # top row, ledge, tabs
    "mode_": "Switch Blender's mode.",
    "always_laser": "Always show lasers (else: finger on the trigger).",
    "pause": "Pause: scene tools and sticks stop.",
    "tab_": "Open this tab.",
    "undo": "Undo the last step.", "redo": "Redo the step you undid.",
    "tool_options": "The tools of this mode and their settings.",
    "tool_gun": "Bring the tool gun, or put it away.",
    "viewpoints": "Saved spots to jump back to.",
    "pda": "Your own small panel of desk controls.", "pda_slot_": "A desk control you chose. Edit moves it.",
    "pda_": "Make tabs, then link desk controls to slots.",
    "camera_preview": "A live scene camera view above the desk.",
    "help": "Help: tips, and the controls on the desk.",
    "help_popup_close": "Close; the tips stay on.", "help_popup_": "",
    "handle_": "Grip to move the panel. Two hands scale it.",
    # Selected
    "sub_rig": "The rig controls of the selection.", "sub_mods": "Which modifiers show in VR.",
    "modifier_": "Show this modifier in VR.",
    "subdiv_down": "Subdivision level down.", "subdiv_up": "Subdivision level up (adds one if none).",
    # Tools
    "select_bubble": "The trigger paints a selection with a bubble at your fingertip.",
    "annotate_on": "Draw notes in 3D with the trigger.", "annotate_color_": "Annotation colour.",
    "annotate_thickness": "Annotation line width.", "annotate_erase": "Remove the last note stroke.",
    "annotate_clear": "Remove all note strokes.", "gp_new": "Add a Grease Pencil object.",
    "hide_selected": "Hide the selected objects (VR only).", "unhide_all": "Show every hidden object.",
    "hide_prev": "Previous page of hidden objects.", "hide_next": "Next page of hidden objects.",
    "hidden_list": "Pick one to show it again.",
    "pose_clear": "Reset the selected bones.", "pose_mirror": "Copy the pose to the other side.",
    "gp_material_": "Draw with this material.", "gp_radius": "Stroke thickness.", "gp_layer_name": "Pick the layer.",
    "gp_erase": "Remove the last stroke.", "gp_clear": "Clear this layer at this frame.",
    "edit_select_": "Select this kind of element with the trigger.",
    "edit_grab": "Grip moves the selection.", "edit_select": "Trigger paints a selection with the bubble.", "edit_extrude": "Grip extrudes; drag to pull out.",
    "edit_inset": "Grip insets; move away to grow.", "edit_bevel": "Grip bevels; move away to grow.",
    "edit_loop_cut": "Aim at an edge, pull to cut.", "edit_loop_cuts": "How many cuts.",
    "edit_loop_even": "All edges slide the same distance.", "edit_bevel_segments": "Steps of the bevel.",
    "edit_bevel_profile": "Shape: 0.5 is round.", "edit_bevel_affect_": "Bevel edges or vertices.",
    "edit_inset_mode_": "Faces together, or each alone.", "edit_extrude_mode_": "Where the extrude goes.",
    "edit_merge": "Merge the selected points.", "edit_delete": "Delete the selection.",
    "edit_fill": "Make a face from the selection.", "edit_reveal": "Show the hidden parts.",
    "sculpt_brush": "What the trigger paints.", "sculpt_size": "Brush size in cm.", "sculpt_strength": "How strong a stroke is.",
    "sculpt_mirror_": "Mirror strokes across this axis.", "sculpt_frame": "Show the object in the desktop 3D View.",
    # Grab
    "grab_FREE": "Grip grabs what your hand touches.", "grab_LASER": "Grip grabs what the laser hits.",
    "grab_SELECT_GRAB": "Grip moves the selection.", "grab_more": "More grab settings.",
    "touch_distance": "How close a hand must be to grab.", "push_speed": "Speed of trigger push and pull.",
    "fine_control": "Slow mode: a quarter of your hand's motion.", "name_tag": "Show names above what you point at.",
    "show_hands": "Draw a simple hand on each controller.", "poke": "Press buttons with a fingertip.",
    "poke_": "Which fingers press buttons.", "laser_length": "How far the laser reaches.",
    "hand_marker": "Size of the axis at each fingertip.", "hand_marker_default": "Back to the tiny size.",
    "belt_snap_back": "An Attached item this far away goes back on the belt.",
    "belt_take_fingertip": "Which point takes things off the belt: your fingertip, or the grip.",
    "belt_on": "Tool belt on or off.", "belt_height": "How far below your eyes the belt hangs.", "belt_size": "Size of the belt slots.",
    # Assets
    "asset_": "Browse the asset library.",
    # Move
    "size_gesture": "Two grips on nothing scale you.", "size_invert": "Swap the scale direction.",
    "size_": "Your size: how big the world is.", "recenter": "Face the scene at standing height.",
    "move_": "How the left stick moves you.", "heading_": "Move relative to your head or left hand.",
    "turn_": "How the right stick turns you.", "walk_speed": "Walking speed.", "fly_speed": "Flying speed.",
    "plane_height": "Height of the walking floor.", "plane_reset": "Put the floor back under your feet.",
    "snap_angle": "Degrees per snap turn.",
    # View
    **{"haptics_test_" + route: "A full-strength buzz to test." for route in ("right", "left", "point", "grab")},
    "haptics_more": "Controller buzzes: choose which ones.", "haptics_strength": "How strong the buzzes are.",
    "haptics_point": "A tick when the laser reaches something.", "haptics_grab": "A buzz when you grab or let go.",
    "haptics_other": "Buzzes for refused actions and limits.", "haptics": "Turn the controller buzzes on.",
    "scale_meter": "Show your size and a ruler while you scale.",
    "shading_": "How the VR view is shaded.", "display_all": "Show every object type again.",
    "display_more": "More object types.", "display_": "Show or hide this kind of object in VR.",
    "snapshot": "Save the scene camera's view as a PNG.", "screenshot": "Save what you see in the headset as a PNG.",
    # Speed
    "perf_compositor": "Turn the compositor off in VR.", "perf_raytracing": "Turn raytracing off in VR.",
    "perf_shadows": "Lower shadow quality in VR.", "perf_heavy": "Turn heavy modifiers off in VR.",
    "perf_transparent": "Hide see-through objects in VR.", "perf_stats": "All the speed numbers.",
    "perf_recount": "Count the triangles again.", "draw_distance": "How far the VR view draws.",
    "draw_distance_reset": "Use Blender's own draw distance.", "safe_settings": "Set everything to its safest, fastest value.",
    "eye_height": "Your eye height above the floor.",
    # File
    "file_save": "Save the .blend file.", "restore_settings": "Put back what VR changed (not built yet).",
    # Tool gun menu
    "gun_tool_": "What the gun's trigger does.", "gun_reset_": "What Reset clears. A held: add or remove.",
    "gun_menu": "Move this menu: left, right or behind the gun.", "gun_copy_reset": "Pick another thing to copy.",
    "gun_hidden_row_": "Show this object again.", "gun_hidden_": "More hidden objects.",
    "gun_material_row_": "Shoot with this material.", "gun_material_": "More materials.",
    "gun_eyedrop": "The next shot picks up a material.",
    # Tool options panel
    "box_": "Shape of the box select.", "snap_": "How moved things snap.", "mirror_": "Mirror edits on this axis.",
    "attached": "Goes back on the belt when you move away.",
    "pin": "Keeps this panel at your hips: it follows as you move and turn.",
}

# why a widget is dim (exact id or prefix; the first match wins). Anything else: DEFAULT_REASON.
REASONS = {
    "mode_POSE": "needs an armature", "mode_SCULPT": "needs an editable mesh", "mode_EDIT_MESH": "needs an editable mesh",
    "mode_PAINT_GREASE_PENCIL": "needs a Grease Pencil object",
    "edit_reveal": "nothing is hidden", "edit_": "this mesh can't be edited here",
    "sculpt_brush": "no brush available",
    "subdiv_": "this object can't take it",
    "annotate_erase": "no note strokes", "annotate_clear": "no note strokes", "unhide_all": "nothing is hidden",
    "gp_erase": "no strokes", "gp_clear": "no strokes", "gp_layer_name": "no layers",
    "restore_settings": "not built yet",
    "mirror_Y": "Blender mirrors this mode on X only", "mirror_Z": "Blender mirrors this mode on X only",
    "mirror_X": "mirror works only in Pose and Edit",
}
DEFAULT_REASON = "not available right now"
PAUSED_REASON = "paused"


def _lookup(table, widget_id):
    if widget_id in table:
        return table[widget_id]
    best = max((key for key in table if key.endswith("_") and widget_id.startswith(key)), key=len, default=None)
    return table[best] if best is not None else None


def tip_for(widget_id, enabled=True, paused=False):
    """(tip, why) for a widget: why is "" while it works. Never None: an unknown widget gets an empty tip."""
    tip = _lookup(TIPS, widget_id) or ""
    if paused and widget_id != "pause":
        return tip, PAUSED_REASON
    if enabled:
        return tip, ""
    return tip, _lookup(REASONS, widget_id) or DEFAULT_REASON


def line(widget_id, enabled=True, paused=False):
    """The one line shown beside a pointed-at widget."""
    tip, why = tip_for(widget_id, enabled, paused)
    if not why:
        return tip
    return f"Dim: {why}." if not tip else f"{tip} (dim: {why})"
