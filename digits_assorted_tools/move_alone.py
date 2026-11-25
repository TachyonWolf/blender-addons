"""Move Alone (Selected card, Character Rig box): move a control without moving the bones that follow it, then turn it
off and they follow again, from where they are now.

A follower is a bone with children whose constraint takes a share of the control's move: an Armature constraint
with the control as a weighted target (B-Bone Chain Builder's MCH-<Name>Follow<k> / MCH-<Name>WebFollow<k>, or any
hand-made rig), or a Copy Transforms / Child Of on the control. The follower's children are the controls you see.

On: the control's weight on each direct follower goes to 0 (Copy Transforms / Child Of: influence 0); the other
targets are scaled up so their sum stays the same (only one target: the follower stays where it is). Off: the
original weights come back. Both ways the followers' children get a new local transform, so nothing moves on
screen. The original weights live on the follower as JSON (STATE_KEY, also the "on" state), so undo and saving
keep them; several controls can be on at once (each listed there).

Cheap draw: the followers of every control are cached per armature (bone count + RECHECK_SECONDS); nothing runs in
the background.
"""
import json
import time

import bpy

from .rig_parts import RECHECK_SECONDS  # generated copy
from .ui_cards import hints  # generated copy

STATE_KEY = "move_alone"   # on a follower: {"controls": [names on], "constraints": {name: {"weights": {...}} | {"influence": x}}}
INFLUENCE_TYPES = {'COPY_TRANSFORMS', 'CHILD_OF'}
SETTLE_PASSES = 6          # compensation passes (one per level of followers that follow followers)
TOL = 1e-6

_cache = {}      # armature name -> (bone count, time of the scan, {control: [follower names]})
scan_count = 0   # how many bone scans happened (tests: a redraw must not add to it)

# ---------------------------------------------------------------- finding followers


def targets_of(con):
    """{bone name: share} the constraint takes from bones of its own armature (Armature: weights; others: influence)."""
    arm = con.id_data
    if con.type == 'ARMATURE':
        return {t.subtarget: t.weight for t in con.targets if t.target == arm and t.subtarget}
    if con.type in INFLUENCE_TYPES and con.target == arm and con.subtarget:
        return {con.subtarget: con.influence}
    return {}


def scan(arm):
    """{control name: [follower names]}: every bone with children whose constraint follows the control."""
    found = {}
    for pb in arm.pose.bones:
        if not pb.bone.children:
            continue
        stored = state(pb)
        for con in pb.constraints:
            for control, share in targets_of(con).items():
                if share > 0 or control in stored.get("controls", ()):
                    found.setdefault(control, [])
                    if pb.name not in found[control]:
                        found[control].append(pb.name)
    return found


def follower_map(arm):
    """scan(arm), cached per armature (scanned again when the bone count changes or after RECHECK_SECONDS)."""
    global scan_count
    count, now = len(arm.pose.bones), time.monotonic()
    cached = _cache.get(arm.name)
    if cached and cached[0] == count and now - cached[1] < RECHECK_SECONDS:
        return cached[2]
    scan_count += 1
    found = scan(arm)
    _cache[arm.name] = (count, now, found)
    return found


def forget_cache():
    _cache.clear()


def followers(control):
    """The pose bones that follow `control` directly."""
    bones = control.id_data.pose.bones
    return [bones[name] for name in follower_map(control.id_data).get(control.name, ()) if name in bones]


def active_control(context):
    """The active pose bone when other bones follow it (Pose Mode), else None."""
    pb = context.active_pose_bone if context.mode == 'POSE' else None
    return pb if pb is not None and followers(pb) else None


def selected_controls(context):
    """The selected pose bones (the active one first) that other bones follow."""
    active = active_control(context)
    rest = [pb for pb in (context.selected_pose_bones or []) if pb != active and followers(pb)]
    return ([active] if active else []) + rest

# ---------------------------------------------------------------- state


def state(follower):
    try:
        return json.loads(follower.get(STATE_KEY, "{}"))
    except (TypeError, ValueError):
        return {}


def is_on(control):
    """True while Move Alone is on for `control` (a follower lists it)."""
    return any(control.name in state(pb).get("controls", ()) for pb in followers(control))


def originals(follower):
    """{constraint name: {"weights": {bone: w}} or {"influence": x}} as they are now."""
    out = {}
    for con in follower.constraints:
        if con.type == 'ARMATURE':
            out[con.name] = {"weights": {t.subtarget: t.weight for t in con.targets}}
        elif con.type in INFLUENCE_TYPES:
            out[con.name] = {"influence": con.influence}
    return out


def alone_weights(weights, alone):
    """The weights with the `alone` bones at 0 and the others scaled so the sum stays the same."""
    total = sum(weights.values())
    kept = sum(w for bone, w in weights.items() if bone not in alone)
    scale = total / kept if kept > 0 else 0.0
    return {bone: 0.0 if bone in alone else w * scale for bone, w in weights.items()}


def apply_state(follower, controls, saved):
    """Set the follower's constraints from the `saved` originals with the `controls` alone; store or clear the state."""
    alone = set(controls)
    for con in follower.constraints:
        original = saved.get(con.name)
        if original is None:
            continue
        if "weights" in original:
            weights = alone_weights(original["weights"], alone)
            for target in con.targets:
                if target.subtarget in weights:
                    target.weight = weights[target.subtarget]
        else:
            con.influence = 0.0 if con.subtarget in alone else original["influence"]
    if alone:
        follower[STATE_KEY] = json.dumps({"controls": sorted(alone), "constraints": saved})
    elif STATE_KEY in follower:
        del follower[STATE_KEY]

# ---------------------------------------------------------------- toggling without a jump


def settle(context, wanted):
    """Give each bone of `wanted` {pose bone: pose-space matrix} that matrix again (local transforms solved, parents
    first: a pass per level, until nothing is off)."""
    for _ in range(SETTLE_PASSES):
        context.view_layer.update()
        off = [pb for pb, matrix in wanted.items()
               if any(abs(a - b) > TOL for row_a, row_b in zip(pb.matrix, matrix) for a, b in zip(row_a, row_b))]
        if not off:
            return
        for pb in off:
            correct_basis(pb, wanted[pb])


def correct_basis(pb, wanted):
    """Nudge the pose bone's own transform so its evaluated pose-space matrix moves to `wanted`. Unlike `pb.matrix = `,
    this holds with constraints that act before the transform (an Action constraint on Before Split, say): the
    setter solves as if there were none."""
    try:
        pb.matrix_basis = pb.matrix_basis @ (pb.matrix.inverted() @ wanted)
    except ValueError:   # a degenerate (scale 0) matrix: fall back on the plain setter
        pb.matrix = wanted


def set_alone(context, controls, on):
    """Turn Move Alone on or off for each pose bone of `controls`; nothing moves on screen. Returns the followers changed."""
    changes = {}   # follower -> (controls alone after, saved originals)
    for control in controls:
        for follower in followers(control):
            current = state(follower)
            alone, saved = changes.get(follower, (set(current.get("controls", ())), current.get("constraints")))
            alone = alone | {control.name} if on else alone - {control.name}
            changes[follower] = (alone, saved or originals(follower))
    children = [child for follower in changes for child in follower.id_data.pose.bones if child.parent == follower]
    wanted = {child: child.matrix.copy() for child in children}
    for follower, (alone, saved) in changes.items():
        apply_state(follower, alone, saved)
    settle(context, wanted)
    return list(changes)


class POSE_OT_move_alone(bpy.types.Operator):
    """Move this control without moving the bones that follow it. Click again: they follow again, from where they are"""
    bl_idname = "pose.move_alone"
    bl_label = "Move Alone"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return active_control(context) is not None

    def execute(self, context):
        controls = selected_controls(context)
        on = not is_on(controls[0])
        changed = set_alone(context, controls, on)
        self.report({'INFO'}, f"Move Alone {'on' if on else 'off'}: {len(changed)} follower"
                              f"{'' if len(changed) == 1 else 's'} {'stay put' if on else 'follow again'}")
        return {'FINISHED'}


def draw_toggle(layout, context):
    """The Move Alone row for the active control (nothing when no bone follows it)."""
    control = active_control(context)
    if control is None:
        return
    on = is_on(control)
    layout.operator(POSE_OT_move_alone.bl_idname, icon='UNLINKED' if on else 'LINKED', depress=on)
    if on:
        hints(layout, ["Its followers stay put"])


classes = (POSE_OT_move_alone,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
