# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode's active tools and their settings: the ONE list the settings file, the Tool options panel, the desk's Tools
page and the tools themselves use. Pure Python (no bpy)."""

GRAB, SELECT, EXTRUDE, INSET, LOOP_CUT, BEVEL = 'grab', 'select', 'extrude', 'inset', 'loop_cut', 'bevel'
ANNOTATE = 'annotate'      # Object / Pose mode only
TOOLS = ((GRAB, "Grab"), (SELECT, "Select"), (EXTRUDE, "Extrude"), (INSET, "Inset"), (LOOP_CUT, "Loop cut"), (BEVEL, "Bevel"))
TOOL_LABELS = dict(TOOLS)
OBJECT_TOOLS = ((GRAB, "Grab"), (SELECT, "Select"), (ANNOTATE, "Annotate"))      #  Object / Pose mode: what the trigger does (Grab = pick along the laser, as always)
BUBBLE_STARTS = (("ADD", "Add"), ("NEW", "New"))        # Select: a stroke adds to the selection, or clears it first
INSTANT = (("merge", "Merge"), ("delete", "Delete"), ("fill", "Fill"), ("reveal", "Reveal"))
HINTS = {GRAB: "Grip anywhere moves the selection; two grips scale it.",
         SELECT: "Hold the trigger to paint a selection with the bubble. A held removes. B + hand up / down resizes. Start: New clears first.",
         EXTRUDE: "Grip and drag to extrude the selection.",
         INSET: "Grip and move away to inset, back to undo it.",
         LOOP_CUT: "Aim at an edge. Trigger or grip cuts; hold to slide.",
         BEVEL: "Grip and move away to bevel, back to undo it."}

# setting kinds: SLIDER (low, high, step, decimals), CHOICE (value, label) pairs, TOGGLE
SLIDER, CHOICE, TOGGLE = 'SLIDER', 'CHOICE', 'TOGGLE'
# tool -> ((setting name, kind, label, default, detail), ...)
SETTINGS = {
    GRAB: (),
    SELECT: (("select_bubble_start", CHOICE, "Start", 'ADD', BUBBLE_STARTS),),
    EXTRUDE: (("edit_extrude_mode", CHOICE, "Direction", 'FREE',
               (('NORMALS', "Normals"), ('FREE', "Free"), ('FACES', "Each face"))),),
    INSET: (("edit_inset_mode", CHOICE, "Faces", 'REGION', (('REGION', "Region"), ('FACES', "Individual"))),),
    LOOP_CUT: (("edit_loop_cuts", SLIDER, "Cuts", 1, (1, 20, 1, 0)),
               ("edit_loop_even", TOGGLE, "Even", False, ())),
    BEVEL: (("edit_bevel_segments", SLIDER, "Segments", 1, (1, 10, 1, 0)),
            ("edit_bevel_profile", SLIDER, "Profile", 0.5, (0.0, 1.0, 0.05, 2)),
            ("edit_bevel_affect", CHOICE, "Affect", 'EDGES', (('VERTICES', "Vertices"), ('EDGES', "Edges"))))}


def _check(kind, detail):
    if kind == SLIDER:
        return lambda value: (isinstance(value, (int, float)) and not isinstance(value, bool)
                              and detail[0] <= value <= detail[1])
    if kind == CHOICE:
        return lambda value: value in [identifier for identifier, _label in detail]
    return lambda value: isinstance(value, bool)


def fields():
    """{name: (default, check)} for settings_store."""
    found = {"edit_tool": (GRAB, lambda value: value in TOOL_LABELS),
             "object_tool": (GRAB, lambda value: value in dict(OBJECT_TOOLS))}
    for entries in SETTINGS.values():
        for name, kind, _label, default, detail in entries:
            found[name] = (default, _check(kind, detail))
    return found


def values(tool, get):
    """{setting name: value} of `tool`, read with `get(name)`."""
    return {name: get(name) for name, *_rest in SETTINGS[tool]}
