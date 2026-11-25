# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/scene_checks.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene checks: things you MAY have left on or changed by mistake on a character (Oops Debugger), as a registry
of small find() / clear() pairs. No UI in here, and nothing runs by itself: a check is only called when a tool
that uses the registry is open (its card draws, or a button is pressed).

A check is `Check(id, area, label, help, find, clear)`:
    find(scope)  -> Finding (plain names, no Blender references) or None when the thing is fine
    clear(scope) -> how many things it fixed
Add a check = write the two functions and add one `register(Check(...))` line. Any tool can use the registry:
    scope = scope_of(context); found = run_all(scope)   # [(check, finding), ...]
Two tools share it, each with its own areas (run_all defaults to the Oops Debugger's AREAS): the Oops Debugger
and Pre-Render Check (areas "Render" and "Scene Render Differences", `run_all(scope, areas=RENDER_AREAS)`; its checks live in pre_render_check.py).
A check with `clear=None` is Select only: the tool shows no Clear button for it.
A check with `show(context, object)` (area REVIEW, "Checks") is review only: its Finding rows each get a Show button
that makes the object active and selects the problem elements in Edit Mode; it has no Clear and no risk.
Each check has a `kind` (KINDS: what the user is looking for, Object / Scene / Render; by default the kind of its
area) and, when it is heavy, a `scan` (SCANS): a scan the Oops Debugger only runs while it is turned on.
`run_all(scope, areas, kind, scans)` picks by both; a check that raises becomes a "Check failed" Finding, the rest go on.
"""
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable

import bpy
from mathutils import Matrix, Vector

from . import chain_weights, driver_scan, instance_array, mesh_review, modifier_order, rig_names, texture_space_fix, weight_cleanup
from .instance_array import is_instance_array
from .rig_rename import action_channelbags
from .ui_cards import friendly_name

DIFFERENCES = "Render Differences"              # the Oops Debugger's viewport vs render checks (character only)
SCENE_DIFFERENCES = "Scene Render Differences"  # Pre-Render Check's, for the whole scene
BAKED = "Baked Data"                            # written into the mesh by an import, a bake or an Apply; reviewed on purpose
NAMING = "Naming"                               # objects still called what Blender named them
LINKED = "Linked Data"                          # objects sharing their data (linked duplicates) with something the share cannot hold
REVIEW = "Checks"                               # mesh checks that are often intentional: review only, Show never fixes
RENDER = "Render"                               # render problems (Pre-Render Check, and the Oops Debugger's Render kind: render settings)
AREAS = ("Animation & Pose", "Mesh", "Transforms", LINKED, "Tool Settings", "Weights", "Drivers", NAMING, RENDER, DIFFERENCES, BAKED, REVIEW)   # the Oops Debugger's sections
OBJECT_ROW_AREAS = tuple(area for area in AREAS if area not in (NAMING, LINKED))   # the All kind lists naming and linked data in their own sections, not in each object's row
RIG_SETUP = "Rig Setup"                          # Bone Workshop's Rig Check (rig_check.py, its own list, not CHECKS): never in Oops / Clear All
RENDER_AREAS = (RENDER, SCENE_DIFFERENCES)                                                                        # Pre-Render Check
# What the user is looking for (the Oops Debugger's dropdown): (id, name, tooltip). A check's kind is its area's
# kind unless it says otherwise.
OBJECT, SCENE, RENDER_KIND, ALL_KIND = "OBJECT", "SCENE", "RENDER", "ALL"
KINDS = ((OBJECT, "Object", "The selected character: its bones, meshes, weights, transforms, viewport vs render differences, baked data and mesh checks"),
         (SCENE, "Scene", "Editor state left on: tool settings, hidden objects or bones, locked vertex groups"),
         (RENDER_KIND, "Render", "Render settings left in a bad state: output, resolution, samples, camera, missing images..."),
         (ALL_KIND, "All", "Every object in the scene: runs the Object checks on each one and lists which have issues"))
KIND_OF_AREA = {"Animation & Pose": OBJECT, "Mesh": OBJECT, "Transforms": OBJECT, "Weights": OBJECT, "Drivers": OBJECT, NAMING: OBJECT, LINKED: OBJECT,
                BAKED: OBJECT, REVIEW: OBJECT, DIFFERENCES: OBJECT, "Tool Settings": SCENE,
                RENDER: RENDER_KIND, SCENE_DIFFERENCES: RENDER_KIND, RIG_SETUP: OBJECT}


@dataclass
class Scan:
    """A heavy scan the user turns on (the Oops Debugger's Scans card): its checks have `scan=id`. Off by default."""
    id: str
    label: str
    help: str


SCANS = (Scan("baked", "Baked Data", "Extra UV Maps, Extra Colour Layers and Leftover Attributes (reads every material's nodes)"),
         Scan("weights", "Weights", "Weights Don't Add Up, Empty Vertex Groups, Unweighted Verts and Too Many Influences "
                                    "(reads every vertex's weights)"),
         Scan("mesh_review", "Mesh Checks", "Non-Manifold, Doubled Verts, Loose Geometry and Degenerate (reads every mesh)"),
         Scan("uv_overlap", "UV Overlap", "Flipped / Overlap UVs (the heaviest: compares every UV triangle)"))


@dataclass
class Ignore:
    """An "Ignore ..." setting of a check that is often fine on purpose (objects placed rotated or scaled). Like a Scan,
    but the other way round: the check (`scan=id`) runs only while the setting is OFF (prefs.scans_on adds the id).
    With `filters=check id` it gates nothing: that check always runs and trims its own list while the setting is ON
    (it asks `scope.ignores(id)`; Pre-Render Check builds its scope without ignores, so it keeps listing everything)."""
    id: str
    label: str
    help: str
    default: bool
    filters: str = ""


IGNORES = (Ignore("rotation", "Ignore Rotations", "Don't list Unapplied Rotation: objects placed rotated on purpose are fine", True),
           Ignore("scale", "Ignore Scale", "Don't list Unapplied Scale: objects placed scaled on purpose are fine", False),
           Ignore("subdiv_viewport", "Ignore Subdiv in Viewport",
                  "Don't list a Subdivision Surface (or Multires) modifier that is off in the viewport but on in render: "
                  "a normal speed setup", True, filters="modifier_eyes"))
# Differences and baked data are for review, not leftovers: Clear All never touches these areas, each has its own buttons.
NEVER_CLEAR_ALL = (DIFFERENCES, SCENE_DIFFERENCES, BAKED, REVIEW)
FAST_VIEWPORT_KEY = "digit_fast_viewport"  # scene custom property of Fast Viewport: JSON [[object full name, modifier name, uid], ...]
EPSILON = 1e-4
CLEAR_NOTE = "Ctrl+Z brings it back."


# ---------------------------------------------------------------------------
# Finding the character
# ---------------------------------------------------------------------------

def rig_of_object(ob):
    """The armature a mesh is deformed by or parented to, else None."""
    if ob is None:
        return None
    if ob.type == 'ARMATURE':
        return ob
    for mod in ob.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            return mod.object
    parent = ob.parent
    while parent is not None:
        if parent.type == 'ARMATURE':
            return parent
        parent = parent.parent
    return None


def find_rig(context):
    """Active object's rig, else the rig of the first selected object."""
    for ob in [context.active_object] + list(context.selected_objects):
        rig = rig_of_object(ob)
        if rig is not None:
            return rig
    return None


def belongs_to(ob, rig):
    """True if the object is deformed by the rig or has it as an ancestor."""
    if any(m.type == 'ARMATURE' and m.object == rig for m in ob.modifiers):
        return True
    parent = ob.parent
    while parent is not None:
        if parent == rig:
            return True
        parent = parent.parent
    return False


def rig_meshes(rig, objects):
    return [ob for ob in objects if ob.type == 'MESH' and belongs_to(ob, rig)]


class Scope:
    """What the checks look at: the active object, its rig and that rig's meshes (`objects`, rigs and meshes only),
    plus the scene's tool settings. `include_disabled=False` leaves out objects that are not in the view layer
    (excluded collections), for every check at once."""

    def __init__(self, context, active=None, include_disabled=True, ignored=()):
        self.ignored = frozenset(ignored)   # ids of the Ignores that are ON (see Ignore.filters)
        self.scene = context.scene
        self.view_layer = context.view_layer
        self.tool_settings = context.scene.tool_settings
        active = active or active_of(context)
        self.rig = rig_of_object(active)
        if self.rig is not None:
            found = [self.rig] + rig_meshes(self.rig, context.scene.objects)
        else:
            found = [active] if active is not None else []
        self.objects = [ob for ob in dict.fromkeys(found) if ob.type in ('ARMATURE', 'MESH')
                        and (include_disabled or in_view_layer(ob, self.view_layer))]
        self.meshes = [ob for ob in self.objects if ob.type == 'MESH']
        self.rigs = [ob for ob in self.objects if ob.type == 'ARMATURE']
        self.name = (active.name if active is not None else "")
        self.shared_mode = ""   # what a fix does with objects sharing their data: SHARED_UNLINK / SHARED_ALL, else it skips them
        self.notes = []         # what a fix skipped or could not do, in words; the UI reports them
        self.unpicked = frozenset()   # {(data name, modifier name)} the user unticked for Apply Modifiers (set by the UI)
        self._memo = {}

    def ignores(self, ignore_id):
        return ignore_id in self.ignored

    def memo(self, key, compute):
        """A value several checks share, worked out once per scan."""
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]


def scope_of(context, active=None, include_disabled=True, ignored=()):
    """The scope of the active object, or of `active` (All: each object of the scene in turn)."""
    return Scope(context, active, include_disabled, ignored)


def active_of(context):
    """The object the checks start from: the active object, else the first selected one."""
    return context.active_object or next(iter(context.selected_objects), None)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    count: int
    detail: str = ""
    objects: list = field(default_factory=list)   # object names the Select button selects
    bones: list = field(default_factory=list)     # (rig name, bone name) pairs it selects
    rows: list = field(default_factory=list)      # foldout list under the check: (title, detail, object name, bone name or ""[, enabled]); a click selects the bone (in Pose Mode) or the object; enabled=False draws it greyed
    unavailable: tuple = ()                       # buttons of the check's alternative Actions that have nothing to do now: not drawn
    picks: list = field(default_factory=list)     # (data name, [modifier names]) the user can untick for the main fix (Linked Modifiers)
    error: str = ""                               # the check itself failed (detail says why): drawn as such, never cleared


@dataclass
class Action:
    """A further button of a check, with its own risk: `clear(scope)` returns the number fixed. `confirm` asks first."""
    button: str
    clear: Callable
    help: str
    risk: int = 2
    confirm: bool = False


@dataclass
class Check:
    id: str
    area: str
    label: str            # plain words, at most 22 characters (it sits in a card row)
    help: str             # what Clear does, in a sentence (the button's tooltip, plus the undo note)
    find: Callable
    clear: Callable | None   # None = Select only
    button: str = "Clear"
    risk: int = 2            # 0..3, see RISKS; Clear All clears up to the level chosen in its select
    show: Callable | None = None   # review checks: show(context, object) selects the problem elements; rows get a Show button
    more: tuple = ()         # alternative Actions drawn under the main button (the main `clear` is the default, and what Clear All runs)
    kind: str = ""           # KINDS id; "" = its area's kind
    scan: str = ""           # SCANS id of a heavy check (runs only while that scan is on); "" = always runs
    shared: Callable | None = None   # transform checks: shared(scope) -> SharedData, objects whose fix meets shared data (asks first)
    confirm: bool = False    # the main Clear asks first (a fix that removes information)
    rows_title: str = ""     # title of the Finding rows' foldout; "" = from the row kind (oops_ui.rows_title)
    why: str = ""            # for new artists: what goes wrong if it stays (renders, rigs, exports...)
    keep: str = ""           # when it is fine or done on purpose. Every check writes both (see explanation())

    def __post_init__(self):
        self.kind = self.kind or KIND_OF_AREA[self.area]

    @property
    def actions(self):
        """[Action] in the order drawn: the main one (the default fix), then the alternatives."""
        if self.clear is None:
            return []
        return [Action(self.button, self.clear, self.help, self.risk, self.confirm)] + list(self.more)

    @property
    def tooltip(self):
        return f"{self.help} {CLEAR_NOTE}"

    def risk_tooltip_of(self, risk):
        return f"{risk} {RISKS[risk][0]}: {RISKS[risk][1]}"

    @property
    def risk_tooltip(self):
        return self.risk_tooltip_of(self.risk)


def action_risk_text(action):
    """"Risk 2, Check First." for one fix button (its tooltip ends with it)."""
    return f"Risk {action.risk}, {RISKS[action.risk][0]}."


EXPLANATION_TITLES = ("Why fix it", "Risk of fixing", "Why you might keep it")
NO_FIX_NOTE = "Nothing is changed: this check has no fix button."
SHOW_NOTE = "Nothing is changed: Show selects the problem elements in Edit Mode."


def fixing_text(check):
    """The risk part of explanation(): each fix button with its help and risk level, or that nothing is changed."""
    if check.clear is None:
        return f"{SHOW_NOTE if check.show else NO_FIX_NOTE} {check.help}"
    return "\n".join([action_text(action) for action in check.actions] + [CLEAR_NOTE])


def action_text(action):
    """One fix button with its help and risk level."""
    return f"{action.button}: {action.help} {action_risk_text(action)} {RISKS[action.risk][1]}"


def explanation_of(why, fixing, keep):
    """The tooltip text for new artists: why fix it, the risk of fixing, why you might keep it. The one place it is built."""
    return "\n\n".join(f"{title}: {text}" for title, text in zip(EXPLANATION_TITLES, (why, fixing, keep)))


def explanation(check):
    """The tooltip on a check's name (every tool that draws the registry)."""
    return explanation_of(check.why, fixing_text(check), check.keep)


@dataclass
class BulkFix:
    """A scene-wide fix button that is not a check's action (the All view): the same why / risk / keep tooltip and a confirm."""
    action: Action
    why: str
    keep: str
    confirm_message: str

    @property
    def tooltip(self):
        return explanation_of(self.why, "\n".join([action_text(self.action), CLEAR_NOTE]), self.keep)


# How safe a Clear is, shown by every tool that draws the registry. No check is at 0 yet: nothing we flag is
# always a mistake (a reset pose, a Hide in Render or a muted constraint can all have been wanted).
RISKS = {
    0: ("Mistake", "Always wrong to keep: fixing it can't lose anything you wanted."),
    1: ("Leftover", "A tool left on or editor state: no effect on the shape, render, pose or animation. Clearing only tidies."),
    2: ("Check First", "Changes how something looks, renders or behaves: you may have wanted it."),
    3: ("Risky", "Can break a rig, clothing or a deliberate setup. Check what it is before clearing."),
}
MAX_RISK = max(RISKS)
MAX_CLEAR_ALL_RISK = 1   # the default of the Clear All level select: levels 0 and 1


def needs_warning(risk):
    """The one rule: a Clear at the top risk level asks first, in a warning popup saying what is lost."""
    return risk == MAX_RISK


CHECKS = []
OWN_CHECKS = []   # checks a tool keeps out of the registry (Bone Workshop's Rig Check): only check_by_id finds them


def register(check):
    CHECKS.append(check)
    return check


def check_by_id(check_id):
    return next(c for c in CHECKS + OWN_CHECKS if c.id == check_id)


def checks_of(areas=AREAS, kind=None, scans=None):
    """The checks of these areas, of this kind (None: every kind), heavy ones only when their scan is in `scans`
    (None: every scan runs, as Pre-Render Check and tests do). The All kind runs the Object checks."""
    kind = OBJECT if kind == ALL_KIND else kind
    return [c for c in CHECKS if c.area in areas and (kind is None or c.kind == kind)
            and (not c.scan or scans is None or c.scan in scans)]


def run_check(check, scope):
    """check.find(scope), or a "Check failed" Finding when it raises (so one broken check never hides the others)."""
    try:
        return check.find(scope)
    except Exception as error:   # noqa: BLE001 - any failure is shown, the scan goes on
        import traceback
        traceback.print_exc()
        return Finding(1, f"Check failed: {type(error).__name__}: {error}", error=str(error) or type(error).__name__)


def run_all(scope, areas=AREAS, kind=None, scans=None, skip=()):
    """Every check of checks_of(areas, kind, scans) that finds something, minus the ids in `skip` (already known):
    [(check, finding)], in registry order."""
    found = []
    for check in checks_of(areas, kind, scans):
        if check.id in skip:
            continue
        finding = run_check(check, scope)
        if finding is not None:
            found.append((check, finding))
    return found


def scene_roots(context):
    """The All kind's roots: every character's rig (or a rig-less mesh), in the scene's order. Cheap: no check runs."""
    return list(dict.fromkeys(rig_of_object(ob) or ob for ob in context.scene.objects if ob.type in ('ARMATURE', 'MESH')))


def in_view_layer(ob, view_layer):
    """False for an object in an excluded (unchecked) collection only."""
    return ob.name in view_layer.objects


def disabled_count(context, kind=ALL_KIND):
    """How many objects sit in excluded collections (what 'Scan Disabled Collections' adds): the All kind's roots, else
    the active character's objects. No check runs."""
    objects = scene_roots(context) if kind == ALL_KIND else scope_of(context).objects
    return sum(not in_view_layer(ob, context.view_layer) for ob in objects)


def scan_scene(context, scans=None, include_disabled=False, ignored=()):
    """The All kind: the Object checks on every character (a rig with its meshes) and every loose mesh of the scene
    (those in excluded collections only with `include_disabled`).
    [(root object name, [(check, finding)])], only the ones with something found. Heavy: callers cache it."""
    roots = [ob for ob in scene_roots(context) if include_disabled or in_view_layer(ob, context.view_layer)]
    found = ((root.name, run_all(scope_of(context, root, include_disabled, ignored), OBJECT_ROW_AREAS, ALL_KIND, scans)) for root in roots)
    return [(name, findings) for name, findings in found if findings]


def clearable_all(findings, max_risk=MAX_CLEAR_ALL_RISK):
    """The [(check, finding)] Clear All would clear at this level: has a clear(), a risk of at most `max_risk`, is not
    a Render Differences check and did not fail. The one place the level filter lives (button count and clearing)."""
    return [(c, f) for c, f in findings
            if c.clear is not None and c.risk <= max_risk and c.area not in NEVER_CLEAR_ALL and not f.error]


def risk_counts(findings):
    """{risk level: number of checks} of [(check, finding)] (for the Clear All confirm text)."""
    return {level: sum(c.risk == level for c, _f in findings) for level in RISKS}


def clear_all(scope, areas=AREAS, kind=None, scans=None, max_risk=MAX_CLEAR_ALL_RISK):
    """Run the clear() of every check Clear All may clear (risk up to `max_risk`) whose find() reports something, of
    this kind and these scans (see checks_of). Returns the number of checks cleared."""
    cleared = 0
    areas = [a for a in areas if a not in NEVER_CLEAR_ALL]   # review areas aren't even scanned
    for check, _finding in clearable_all(run_all(scope, areas, kind, scans), max_risk):
        check.clear(scope)
        cleared += 1
    return cleared


def select_finding(context, finding):
    """Select what a finding names (objects, or bones of their rig)."""
    names = list(finding.objects) + [rig for rig, _bone in finding.bones]
    objects = [bpy.data.objects[n] for n in dict.fromkeys(names) if n in bpy.data.objects]
    if not objects:
        return
    for ob in context.view_layer.objects:
        ob.select_set(False)
    for ob in objects:
        if ob.name in context.view_layer.objects:
            ob.select_set(True)
    context.view_layer.objects.active = objects[0]
    for rig_name, bone_name in finding.bones:
        select_bone(bpy.data.objects[rig_name], bone_name, keep_others=True)


def inspect(context, ob, bone=""):
    """Make `ob` the only selected and active object; with `bone`, in Pose Mode with that bone selected and active."""
    if ob is None or ob.name not in context.view_layer.objects or (bone and bone not in ob.data.bones):
        return False
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for other in context.view_layer.objects:
        other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if not bone:
        return True
    bpy.ops.object.mode_set(mode='POSE')
    return select_bone(ob, bone)


def select_bone(rig, name, keep_others=False):
    """Select (and make active) the bone `name` of `rig`. Selection lives on the pose bones in 5.x."""
    if name not in rig.data.bones:
        return False
    if not keep_others:
        for pb in rig.pose.bones:
            pb.select = False
    rig.pose.bones[name].select = True
    rig.data.bones.active = rig.data.bones[name]
    return True


class ScanCache:
    """Keeps the last scan so redraws reuse it: `get(key, compute)` recomputes only when the key changes or after
    clear() (Rescan button, any Clear). Also remembers file checks by path (`exists`), until clear(): a path on a
    sleeping disk or a network share can take half a second to look up."""

    def __init__(self):
        self.key, self.value, self.paths = None, None, {}

    def get(self, key, compute):
        if self.key != key or self.value is None:
            self.value, self.key = compute(), key
        return self.value

    def exists(self, path, folder=False):
        """os.path.isdir (folder) or os.path.exists of `path`, looked up once per path until clear()."""
        if (path, folder) not in self.paths:
            self.paths[(path, folder)] = os.path.isdir(path) if folder else os.path.exists(path)
        return self.paths[(path, folder)]

    def clear(self):
        self.key, self.value, self.paths = None, None, {}


CACHE = ScanCache()


def context_key(context):
    """Cheap key of what the user is looking at: active object, selection, mode, frame."""
    return (context.active_object.name if context.active_object else "",
            tuple(sorted(ob.name for ob in context.selected_objects)), context.mode, context.scene.frame_current)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def names_text(names, limit=3):
    """"A, B, C" or "A, B, C +2"."""
    names = [friendly_name(str(n)) for n in names]
    text = ", ".join(names[:limit])
    return f"{text} +{len(names) - limit}" if len(names) > limit else text


def found(items, detail_items=None, **kwargs):
    """A Finding from a list of things (None when empty); the detail lists their names."""
    if not items:
        return None
    names = detail_items if detail_items is not None else [getattr(i, "name", i) for i in items]
    return Finding(len(items), names_text(names), **kwargs)


def datablocks(owners):
    """Unique data blocks of objects (a mesh shared by two objects is one)."""
    return list(dict.fromkeys(ob.data for ob in owners))


def all_pose_bones(scope):
    return [(rig, pb) for rig in scope.rigs for pb in rig.pose.bones]


def flag_check(check_id, area, label, help_text, flags, detail_names=None, button="Turn Off", risk=2, why="", keep=""):
    """A check for boolean settings left on: `flags(scope)` gives [(owner, attribute, shown name)]."""
    def find(scope):
        on = [name for owner, attr, name in flags(scope) if getattr(owner, attr)]
        return Finding(len(on), names_text(on)) if on else None

    def clear(scope):
        count = 0
        for owner, attr, _name in flags(scope):
            if getattr(owner, attr):
                setattr(owner, attr, False)
                count += 1
        return count
    return register(Check(check_id, area, label, help_text, find, clear, button, risk, why=why, keep=keep))


# ---------------------------------------------------------------------------
# Animation & Pose
# ---------------------------------------------------------------------------

def animated_ids(scope):
    """[(label, anim data)] of the object, the rig data and the shape keys that have an action."""
    owners = []
    for ob in scope.objects:
        owners.append((ob.name, ob.animation_data))
        owners.append((f"{ob.name} data", ob.data.animation_data))
        keys = getattr(ob.data, "shape_keys", None)
        if keys is not None:
            owners.append((f"{ob.name} shape keys", keys.animation_data))
    return [(label, ad) for label, ad in owners if ad is not None and ad.action is not None]


def find_animation(scope):
    items = animated_ids(scope)
    if not items:
        return None
    return Finding(len(items), names_text(ad.action.name for _l, ad in items),
                   objects=[ob.name for ob in scope.objects if ob.animation_data and ob.animation_data.action])


def clear_animation(scope):
    items = animated_ids(scope)
    for _label, ad in items:
        ad.action = None
    return len(items)


register(Check("animation", "Animation & Pose", "Animation",
               "Removes the animation (the action) from the object, rig and shape keys. Drivers stay.",
               find_animation, clear_animation, risk=3,
               why="An action left on the rig, mesh or shape keys plays on every frame. It can undo the pose you set, "
                   "and it goes out with exports.",
               keep="Keep it when the animation is real work you want to render or export."))


CHANNEL_REST = (("location", (0.0, 0.0, 0.0)), ("scale", (1.0, 1.0, 1.0)), ("rotation_euler", (0.0, 0.0, 0.0)),
                ("rotation_quaternion", (1.0, 0.0, 0.0, 0.0)), ("rotation_axis_angle", (0.0,)))   # axis angle: the angle only


def posed(pb, driven=()):
    """True when the pose bone is away from rest (location, rotation, scale). Channels in `driven`, a set of
    (property, index), are ignored: a driver set them, not the user."""
    return any(abs(value - rest) > EPSILON
               for prop, rests in CHANNEL_REST for index, (value, rest) in enumerate(zip(getattr(pb, prop), rests))
               if (prop, index) not in driven)


def posed_by_user(scope, rig, pb):
    """Posed on a channel no driver sets (see driven_channels)."""
    driven = driven_channels(scope, rig).get(pb.name, [])
    return posed(pb, {(prop, index) for prop, index, _info in driven})


def find_posed(scope):
    bones = [(rig.name, pb.name) for rig, pb in all_pose_bones(scope) if posed_by_user(scope, rig, pb)]
    return found(bones, [b for _r, b in bones], bones=bones) if bones else None


def clear_posed(scope):
    count = 0
    for rig, pb in all_pose_bones(scope):
        if posed_by_user(scope, rig, pb):
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
            count += 1
    return count


register(Check("posed", "Animation & Pose", "Posed Bones",
               "Removes the pose: sets every bone that is away from rest back to its rest location, rotation and scale.",
               find_posed, clear_posed, risk=3,
               why="A pose you forgot about bends the character. Exports, shape keys and weight painting then start "
                   "from that bent shape.",
               keep="Keep it when you posed the character on purpose, for example for a render."))


def find_rest_position(scope):
    rigs = [rig.name for rig in scope.rigs if rig.data.pose_position == 'REST']
    return found(rigs, objects=rigs)


def clear_rest_position(scope):
    count = 0
    for rig in scope.rigs:
        if rig.data.pose_position == 'REST':
            rig.data.pose_position = 'POSE'
            count += 1
    return count


register(Check("rest_position", "Animation & Pose", "Rig in Rest Position",
               "Sets the rig from Rest Position back to Pose Position, so poses and animation show again.",
               find_rest_position, clear_rest_position, "Set to Pose", risk=2,
               why="In Rest Position the rig ignores every pose and animation. Renders then show the character in its "
                   "rest pose.",
               keep="Keep it while you edit the rig or check the weights against the rest pose."))

# Bones that something other than the user moves: measured, not guessed by type. A bone whose own pose values are at
# rest (a channel a driver sets counts as unposed) but whose evaluated place differs from where its rest place puts it (relative to its parent, so a posed parent
# is no cause) is being moved by its active constraints or drivers. A Limit that does nothing at rest is not reported.
# Select-only: the Oops Debugger lists the bones, a click opens one in Pose Mode.
# Mesh modifiers are left out: clothing Shrinkwraps, Lattices and Displace decals are deliberate shape tools.
MOVE_DISTANCE = 0.001           # metres: a bone moved more than 1 mm counts as moved
MOVE_ANGLE = math.radians(1.0)  # turned more than 1 degree
MOVE_SCALE = 0.01               # scaled more than 1 %


def active_constraints(pb):
    return [c for c in pb.constraints if not c.mute and c.influence > 0.0]


def driven_channels(scope, rig):
    """{bone name: [(property, index, DriverInfo)]} of the live drivers on each bone's pose channels. Once per scan."""
    def compute():
        channels = {}
        for info in rig_drivers(scope, rig):
            match = driver_scan.BONE_PATH.match(info.data_path)
            if (info.id_kind != "objects" or info.id_name != rig.name or info.muted or not info.bone or not match
                    or match.group(2) not in dict(CHANNEL_REST)):
                continue
            channels.setdefault(info.bone, []).append((match.group(2), info.index, info))
        return channels
    return scope.memo(("driven_channels", rig.name), compute)


def rest_matrix(pb):
    """Where the bone sits in armature space when nothing is posed and nothing constrains it, given its parent's
    current place."""
    local = pb.bone.matrix_local
    if pb.parent is None:
        return local
    return pb.parent.matrix @ (pb.parent.bone.matrix_local.inverted() @ local)


@dataclass
class MovedBone:
    rig: object
    pb: object
    constraints: list
    drivers: list        # [(property, index, DriverInfo)]
    distance: float      # how far the bone sits from where its rest place puts it (metres)
    angle: float = 0.0   # how far it is turned from there (radians)
    scale: float = 0.0   # how far its size is from there (0.05 = 5 %)

    @property
    def amount(self):
        """What moved, in plain words: "2.1 cm", "0.4°", "2.1 cm · 5°", "scale 8%"."""
        parts = []
        if self.distance > MOVE_DISTANCE:
            parts.append(f"{self.distance * 100:.1f} cm")
        if self.angle > MOVE_ANGLE:
            parts.append(f"{math.degrees(self.angle):.1f}°")
        if self.scale > MOVE_SCALE:
            parts.append(f"scale {self.scale * 100:.0f}%")
        return " · ".join(parts)

    @property
    def causes(self):
        return [c.name for c in self.constraints] + [f"Driver: {info.title} = {info.what}" for _p, _i, info in self.drivers]


def moved_without_posing(scope):
    """[MovedBone] of bones nobody posed (channels a driver sets count as unposed) whose active constraints or
    drivers put them away from rest."""
    moved = []
    for rig in scope.rigs:
        if rig.data.pose_position == 'REST':
            continue
        driven = driven_channels(scope, rig)
        for pb in rig.pose.bones:
            constraints, drivers = active_constraints(pb), driven.get(pb.name, [])
            if not constraints and not drivers:
                continue
            if posed_by_user(scope, rig, pb):
                continue
            expected = rest_matrix(pb)
            _loc, turn, size = (expected.inverted_safe() @ pb.matrix).decompose()
            bone = MovedBone(rig, pb, constraints, drivers, (pb.matrix.translation - expected.translation).length,
                             turn.angle, max(abs(v - 1.0) for v in size))
            if bone.amount:
                moved.append(bone)
    return moved


def bone_rows(items):
    """Foldout rows (title, detail, rig name, bone name) from [(rig, bone name, cause text, extra)]."""
    return [(bone, f"{cause}{extra}", rig.name, bone) for rig, bone, cause, extra in items]


def find_rest_changers(scope):
    """The finding lists each moved bone with its constraints / drivers and how far it sits from rest."""
    moved = moved_without_posing(scope)
    return found(moved, [m.pb.name for m in moved],
                 rows=bone_rows((m.rig, m.pb.name, ", ".join(m.causes), f" · {m.amount}") for m in moved),
                 bones=[(m.rig.name, m.pb.name) for m in moved])


def clear_rest_changers(scope):
    """Mutes the constraints and drivers that move these bones (nothing is removed). A muted driver leaves its
    channel where it last put it, so those channels go back to rest."""
    moved = moved_without_posing(scope)
    for m in moved:
        for constraint in m.constraints:
            constraint.mute = True
        for prop, index, info in m.drivers:
            driver_scan.set_muted(info, True)
            getattr(m.pb, prop)[index] = dict(CHANNEL_REST)[prop][index]
    return len(moved)


register(Check("rest_changers", "Animation & Pose", "Bones Moved Unposed",
               "Bones that sit away from their rest place although nobody posed them: a constraint or driver moves "
               "them. Rig mechanisms do this on purpose, so muting can break the rig. Open the list and click a bone "
               "to inspect it. Mute switches the constraints and drivers off (they stay in the file) and sets their "
               "channels back to rest; Muted Bone Constraints lists them after.",
               find_rest_changers, clear_rest_changers, "Mute", risk=3,
               why="A constraint or driver (a rule that moves a bone for you) moves these bones. If you did not set "
                   "that up, it can bend the mesh in odd ways.",
               keep="Most rigs do this on purpose: IK chains, Copy Rotation and corrective drivers all move bones. "
                    "Keep it when the rig was made that way."))


def muted_bone_things(scope):
    """[(rig, bone name, label, thing)] of muted bone constraints and muted bone drivers (thing = constraint or DriverInfo)."""
    things = []
    for rig in scope.rigs:
        for pb in rig.pose.bones:
            things += [(rig, pb.name, c.name, c) for c in pb.constraints if c.mute]
        things += [(rig, d.bone, f"Driver: {d.title}", d) for d in rig_drivers(scope, rig)
                   if d.muted and d.bone and d.id_kind == "objects" and d.id_name == rig.name]
    return things


def find_muted_bone_things(scope):
    things = muted_bone_things(scope)
    return found(things, [bone for _r, bone, _l, _t in things],
                 rows=bone_rows((rig, bone, label, "") for rig, bone, label, _t in things),
                 bones=[(rig.name, bone) for rig, bone, _l, _t in things])


def clear_muted_bone_things(scope):
    things = muted_bone_things(scope)
    for _rig, _bone, _label, thing in things:
        if isinstance(thing, driver_scan.DriverInfo):
            driver_scan.set_muted(thing, False)
        else:
            thing.mute = False
    return len(things)


register(Check("muted_constraints", "Animation & Pose", "Muted Bone Constraints",
               "Bone constraints and bone drivers that are switched off. Some rigs mute them on purpose (an IK / FK "
               "switch): Unmute turns them all back on, which can change how the rig moves.",
               find_muted_bone_things, clear_muted_bone_things, "Unmute", risk=3,
               why="A muted constraint or driver does nothing. A part of the rig can then stop following, like a hand "
                   "that ignores its IK control.",
               keep="Rigs often mute some on purpose, for example for an IK / FK switch. Keep them when the rig turns "
                    "them on and off itself."))

# ---------------------------------------------------------------------------
# Mesh
# ---------------------------------------------------------------------------

MASK = ".sculpt_mask"
FACE_SETS = ".sculpt_face_set"


def has_mask(me):
    attr = me.attributes.get(MASK)
    return attr is not None and any(abs(d.value) > EPSILON for d in attr.data)


def has_face_sets(me):
    attr = me.attributes.get(FACE_SETS)
    return attr is not None and len({d.value for d in attr.data}) > 1


def muted_modifiers(scope):
    """[(object, modifier)] switched off in both the viewport and the render (Fast Viewport only turns off the viewport)."""
    return [(ob, m) for ob in scope.meshes for m in ob.modifiers if not m.show_viewport and not m.show_render]


def find_muted_modifiers(scope):
    mods = muted_modifiers(scope)
    return found(mods, [f"{ob.name}: {m.name}" for ob, m in mods],
                 rows=[(ob.name, m.name, ob.name, "") for ob, m in mods], objects=[ob.name for ob, _m in mods])


def set_muted_modifiers(scope, viewport):
    """Turns the muted modifiers back on in the render (and in the viewport when `viewport`)."""
    mods = muted_modifiers(scope)
    for _ob, m in mods:
        m.show_render = True
        m.show_viewport = viewport or m.show_viewport
    return len(mods)


def remove_muted_modifiers(scope):
    mods = muted_modifiers(scope)
    for ob, m in mods:
        ob.modifiers.remove(m)
    return len(mods)


register(Check("muted_modifiers", "Mesh", "Muted Modifiers",
               "Turns them back on in the render only; the viewport stays off. They then show in Render Differences. "
               "This changes your renders.",
               find_muted_modifiers, lambda scope: set_muted_modifiers(scope, False), "Unmute in Render", risk=2,
               more=(Action("Unmute Both", lambda scope: set_muted_modifiers(scope, True),
                            "Turns them back on in the viewport and the render, which can change the shape of the mesh.", 2),
                     Action("Remove", remove_muted_modifiers,
                            "Deletes the muted modifiers from the meshes. Only these ones.", 3, confirm=True)),
               rows_title="Modifiers",
               why="A modifier that is off in the viewport and in the render does nothing. It may be a step you "
                   "forgot to turn back on.",
               keep="Keep it when you turned it off on purpose, to compare the look or to save it for later."))


def wrong_order_stacks(scope, plan):
    """[(object, wanted modifier names)] for the meshes whose modifier stack `plan(modifiers)` wants in another order."""
    stacks = [(ob, plan(ob.modifiers)) for ob in scope.meshes]
    return [(ob, wanted) for ob, wanted in stacks if wanted]


def order_check(check_id, label, help_text, plan, why, keep):
    """A Mesh check for a modifier stack in the wrong order: `plan(modifiers)` gives the wanted order (names) or None.
    The fix only moves modifiers (modifier_order.apply_order), so no setting changes."""
    def find(scope):
        stacks = wrong_order_stacks(scope, plan)
        rows = [(ob.name, " > ".join(m.name for m in ob.modifiers), ob.name, "") for ob, _wanted in stacks]
        return found(stacks, [ob.name for ob, _wanted in stacks], rows=rows, objects=[ob.name for ob, _wanted in stacks])

    def clear(scope):
        stacks = wrong_order_stacks(scope, plan)
        for ob, wanted in stacks:
            modifier_order.apply_order(ob, wanted)
        return len(stacks)
    return register(Check(check_id, "Mesh", label, help_text, find, clear, "Fix Order", risk=2, rows_title="Modifiers", why=why, keep=keep))


order_check("armature_not_first", "Armature Not First",
            "Moves the Armature modifier up to just before the first modifier that needs the posed shape. Nothing else moves.",
            lambda modifiers: modifier_order.armature_first_plan(modifiers, modifier_order.wants_armature_first),
            why="Subdivision, Bevel, Lattice, Shrinkwrap and the like work on the shape they get. Before the Armature they work on "
                "the rest shape, so the mesh deforms the wrong way, or slowly.",
            keep="Keep it when the order is deliberate. A Mirror, Mask, Solidify or Array before the Armature is normal and not flagged.")

order_check("toony_before_armature", "Toony Before Armature",
            "Moves the Armature modifier up to just before the first Toony modifier. Nothing else moves.",
            lambda modifiers: modifier_order.armature_first_plan(modifiers, modifier_order.toony_before_armature),
            why="Toony modifiers bend and stretch the posed mesh. Before the Armature they act on the rest shape, "
                "and the pose then moves their result.",
            keep="Keep it when you want the effect built in the rest pose. Bubbles Rest is made to sit before the Armature and is not flagged.")

order_check("finishers_not_last", "Subdiv & Weld Not Last",
            "Moves Subdivision, then Weld Normals, after the other modifiers. Nothing else moves.",
            modifier_order.finishers_last_plan,
            why="Subdivision smooths the shape it gets, and Weld Normals blends the normals of the final shape. A modifier "
                "after them works on the subdivided mesh: slow, and the shading seam can come back.",
            keep="Keep it when the order is deliberate. Normal editing, Triangulate, Shrinkwrap, Instance Array and Bubbles may follow, and are not flagged.")


def attribute_check(check_id, label, help_text, attribute, test, risk=2, why="", keep=""):
    def meshes(scope):
        return [ob for ob in scope.meshes if test(ob.data)]

    def find(scope):
        return found(meshes(scope), objects=[ob.name for ob in meshes(scope)])

    def clear(scope):
        todo = meshes(scope)
        for me in datablocks(todo):
            me.attributes.remove(me.attributes[attribute])
        return len(todo)
    return register(Check(check_id, "Mesh", label, help_text, find, clear, risk=risk, why=why, keep=keep))


attribute_check("sculpt_mask", "Sculpt Mask",
                "Removes the sculpt mask (the painted mask from sculpt mode) from the mesh.", MASK, has_mask, risk=1,
                why="A sculpt mask stops brushes on the masked parts. Your next sculpt strokes then seem to do "
                    "nothing there.",
                keep="Keep it while you still use it to protect parts of the mesh as you sculpt.")
attribute_check("face_sets", "Face Sets",
                "Removes the sculpt face sets (the coloured face groups of sculpt mode) from the mesh.", FACE_SETS,
                has_face_sets, risk=1,
                why="Face sets only help in Sculpt Mode. Old ones add to the file size and can get in the way of the "
                    "next sculpt session.",
                keep="Keep them while you still use them to hide or mask parts in Sculpt Mode.")


def dyntopo_meshes(scope):
    return [ob for ob in scope.meshes if ob.use_dynamic_topology_sculpting]


def find_dyntopo(scope):
    return found(dyntopo_meshes(scope), objects=[ob.name for ob in dyntopo_meshes(scope)])


def clear_dyntopo(scope):
    count = 0
    for ob in dyntopo_meshes(scope):
        with bpy.context.temp_override(object=ob, active_object=ob):
            try:
                bpy.ops.sculpt.dynamic_topology_toggle()
                count += 1
            except RuntimeError:
                pass   # not in sculpt mode: nothing to toggle there
    return count


register(Check("dyntopo", "Mesh", "Dyntopo Left On",
               "Turns Dynamic Topology off (it rebuilds the mesh while you sculpt).", find_dyntopo, clear_dyntopo,
               "Turn Off", risk=1,
               why="Dynamic Topology rebuilds the mesh as you sculpt. Left on, the next stroke can ruin UV maps, "
                   "colour attributes and other mesh data.",
               keep="Keep it on while you still sculpt a rough shape that has no UV maps yet."))


def normals_meshes(scope):
    return [ob for ob in scope.meshes if ob.data.has_custom_normals]


def find_normals(scope):
    meshes = normals_meshes(scope)
    return found(meshes, rows=[(ob.name, "custom split normals", ob.name, "") for ob in meshes],
                 objects=[ob.name for ob in meshes])


def clear_normals(scope):
    done = 0
    for ob in normals_meshes(scope):
        with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        done += 1
    return done


register(Check("custom_normals", BAKED, "Custom Split Normals",
               "Removes the custom split normals (hand-edited shading directions) from the mesh.",
               find_normals, clear_normals, risk=2,
               why="Custom split normals lock the shading directions. After you edit the mesh, the shading can look "
                   "dented and won't update.",
               keep="Keep them when you set them on purpose, for example for toon shading or normals copied from "
                    "another mesh."))


# Extra UV maps, colour attributes and leftover attributes: data written into the mesh that nothing may use. "Used" is
# decided in one place, data_users(): names referenced by the object's materials, modifiers and bake settings.

NODE_TEXT_SKIP = ("name", "label")   # a node's own name is not a reference


def node_texts(tree, seen=None):
    """Every text a node tree holds that could name data: node settings (UV Map, Attribute, Color Attribute, Normal
    Map...) and text socket values (Named Attribute names, Geometry Nodes inputs), inside node groups too."""
    seen = set() if seen is None else seen
    if tree is None or tree.name_full in seen:
        return
    seen.add(tree.name_full)
    for node in tree.nodes:
        for prop in node.bl_rna.properties:
            if prop.type == 'STRING' and prop.identifier not in NODE_TEXT_SKIP:
                yield getattr(node, prop.identifier)
        for socket in node.inputs:
            if socket.type == 'STRING' and hasattr(socket, "default_value"):
                yield socket.default_value
        if node.type == 'GROUP':
            yield from node_texts(node.node_tree, seen)


def tree_texts(scope, tree):
    """node_texts(tree) as a list, read once per scan (materials and node groups are shared by many meshes)."""
    if tree is None:
        return []
    return scope.memo(("node_texts", tree.as_pointer()), lambda: list(node_texts(tree)))


def geometry_nodes_texts(mod):
    """The text inputs set on a Geometry Nodes modifier."""
    if mod.type != 'NODES' or mod.node_group is None:
        return
    for item in mod.node_group.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.socket_type == 'NodeSocketString':
            yield getattr(mod.properties.inputs, item.identifier).value


def data_users(scope, ob):
    """{name: [what refers to it]} for a mesh object: its materials' nodes, its modifiers (text settings, Geometry Nodes
    inputs and node groups), the active UV map (the bake target) and the bake settings. Read once per scan."""
    def compute():
        users = {}

        def add(text, who):
            if text:
                users.setdefault(text, [])
                if who not in users[text]:
                    users[text].append(who)
        for slot in ob.material_slots:
            if slot.material and slot.material.node_tree:
                for text in tree_texts(scope, slot.material.node_tree):
                    add(text, f"material {slot.material.name}")
        for mod in ob.modifiers:
            who = f"modifier {mod.name}"
            for prop in mod.bl_rna.properties:
                if prop.type == 'STRING' and prop.identifier not in NODE_TEXT_SKIP:
                    add(getattr(mod, prop.identifier), who)
            for text in geometry_nodes_texts(mod):
                add(text, who)
            for text in tree_texts(scope, getattr(mod, "node_group", None)):
                add(text, who)
        if ob.data.uv_layers.active:
            add(ob.data.uv_layers.active.name, "the active UV map (bake)")
        add(getattr(scene_bake(scope), "uv_layer", ""), "the bake settings")
        return users
    return scope.memo(("data_users", ob.name), compute)


def scene_bake(scope):
    return getattr(scope.scene.render, "bake", None)


def extra_uv_maps(me):
    return [l.name for l in list(me.uv_layers)[1:] if not l.active_render]


def extra_colours(me):
    """Colour attributes after the first, except the render one."""
    return [a.name for i, a in enumerate(me.color_attributes) if i > 0 and i != me.color_attributes.render_color_index]


BLENDER_ATTRIBUTES = {"position", "sharp_face", "sharp_edge", "material_index", "crease_vert", "crease_edge", "bevel_weight_vert",
                      "bevel_weight_edge", "id", "radius", "normal", "custom_normal"}   # custom_normal: the Custom Split Normals check's


def leftover_attributes(me):
    covered = {l.name for l in me.uv_layers} | {a.name for a in me.color_attributes}
    return [a.name for a in me.attributes
            if not a.name.startswith(".") and a.name not in BLENDER_ATTRIBUTES and a.name not in covered
            and not a.is_internal and not a.is_required]


def baked_candidates(scope, names_of):
    """[(object, name, [users])] for the first object of each mesh in scope: its names from `names_of(mesh)`, with who uses them."""
    items = []
    for ob in dict.fromkeys(next(o for o in scope.meshes if o.data is me) for me in datablocks(scope.meshes)):
        users = {}
        for other in (o for o in bpy.data.objects if o.type == 'MESH' and o.data is ob.data):
            for name, who in data_users(scope, other).items():
                users.setdefault(name, []).extend(w for w in who if w not in users.get(name, []))
        items += [(ob, name, users.get(name, [])) for name in names_of(ob.data)]
    return items


def baked_check(check_id, label, help_text, names_of, remove, rows_title, why="", keep=""):   # all in the "baked" scan (they share data_users)
    """A Baked Data check for extra data in the mesh: lists every candidate (used ones greyed, with who uses them);
    its button removes the unused ones only. `remove(mesh, name)` deletes one."""
    def find(scope):
        items = baked_candidates(scope, names_of)
        unused = [i for i in items if not i[2]]
        if not unused:
            return None
        rows = [(ob.name, f"{name} · " + (f"used by {', '.join(users)}" if users else "unused"), ob.name, "", not users)
                for ob, name, users in items]
        return Finding(len(unused), names_text(f"{ob.name}: {name}" for ob, name, _u in unused), rows=rows,
                       objects=list(dict.fromkeys(ob.name for ob, _n, _u in unused)))

    def clear(scope):
        unused = [i for i in baked_candidates(scope, names_of) if not i[2]]
        for ob, name, _users in unused:
            remove(ob.data, name)
        return len(unused)
    return register(Check(check_id, BAKED, label, help_text, find, clear, "Remove Unused", risk=2, scan="baked",
                          rows_title=rows_title, why=why, keep=keep))


baked_check("extra_uv_maps", "Extra UV Maps",
            "Removes the UV maps after the first that nothing uses (no material, modifier or bake refers to them, "
            "and they are not the render one). Used ones stay.",
            extra_uv_maps, lambda me, name: me.uv_layers.remove(me.uv_layers[name]), "UV Maps",
            why="UV maps that nothing uses make the file and exports larger. A game engine may also pick the wrong UV "
                "map.",
            keep="Keep one when you plan to use it later, for example a second UV map for a light map bake.")
baked_check("extra_colours", "Extra Colour Layers",
            "Removes the colour attributes after the first that nothing uses (and that are not the render one). Used ones stay.",
            extra_colours, lambda me, name: me.color_attributes.remove(me.color_attributes[name]), "Colour Layers",
            why="Colour attributes that nothing uses make the file and exports larger. They are often left over from "
                "a bake or an import.",
            keep="Keep one when you still need it, for example for a game engine that reads vertex colours.")
baked_check("leftover_attributes", "Leftover Attributes",
            "Removes attributes Blender did not make itself (often import leftovers) that nothing uses. Used ones stay.",
            leftover_attributes, lambda me, name: me.attributes.remove(me.attributes[name]), "Attributes",
            why="Attributes that nothing uses add to the file size and the export size. They often come from imports "
                "or old Geometry Nodes.",
            keep="Keep one when an exporter, a game engine or another file reads it, even if this file does not.")

# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------


def negative_scale(ob):
    return any(v < 0 for v in ob.scale)


def unapplied_scale(ob):
    return not negative_scale(ob) and any(abs(v - 1.0) > EPSILON for v in ob.scale)


def unapplied_rotation(ob):
    if ob.rotation_mode == 'QUATERNION':
        return any(abs(a - b) > EPSILON for a, b in zip(ob.rotation_quaternion, (1.0, 0.0, 0.0, 0.0)))
    if ob.rotation_mode == 'AXIS_ANGLE':
        return abs(ob.rotation_axis_angle[0]) > EPSILON
    return any(abs(v) > EPSILON for v in ob.rotation_euler)


SHARED_UNLINK, SHARED_SAME, SHARED_ALL, SHARED_MINIMIZE = "UNLINK", "SAME", "ALL", "MINIMIZE"   # Scope.shared_mode: copy the data first / new shared copy for the users of the same size / apply to the shared data once, adjusting every user / bake only the most common scale, every user keeps its look
SAME_SIZE = 1e-4


@dataclass
class SharedData:
    """The listed objects whose data other objects use too: [(object, number of others)], and whether Apply to All
    is possible for them (scale: no axis of this object's scale at 0, every user takes its size; rotation: every user has a uniform
    scale, so the turn can be undone per user).
    `same_size` = how many objects Apply to Same Size would change (None: not offered, also when every user matches: Apply to All
    then does the same in place). `can_minimize`: Minimize is possible (a scale, and every user may be applied)."""
    objects: list
    can_apply_all: bool
    same_size: int | None = None
    can_minimize: bool = False


def users_by_data():
    """{data: [objects using it]}, over the whole file."""
    users = {}
    for ob in bpy.data.objects:
        if ob.data is not None:
            users.setdefault(ob.data, []).append(ob)
    return users


def with_data_sharers(objects):
    """`objects` plus every other user of their shared data, each once: work on shared data needs all its users."""
    users = users_by_data()
    grouped = {}
    for ob in objects:
        for user in (users[ob.data] if ob.data is not None else [ob]):
            grouped[user] = None
    return list(grouped)


def uniform_scale(ob):
    return max(ob.scale) - min(ob.scale) < EPSILON


def can_apply_shared(ob, users, rotation, only_same):
    """Can this object's transform go into the shared mesh? A mesh, no scale axis at 0 (negative is fine: the normals
    are flipped after, like Blender's Apply Scale; rotation: any). For a rotation
    every user needs a uniform scale (the turn is undone per user); the Same size users just reset. A scale is simply
    given to every user, so the others' scales don't matter."""
    return (ob.type == 'MESH' and (rotation or min(abs(v) for v in ob.scale) > EPSILON)
            and (only_same or not rotation or all(uniform_scale(u) for u in users[ob.data])))


def same_transform(a, b, rotation):
    """True when two objects have the same scale (or, for rotation, the same turn) within SAME_SIZE."""
    if rotation:
        return abs(a.matrix_basis.to_quaternion().dot(b.matrix_basis.to_quaternion())) > 1 - SAME_SIZE
    return all(abs(x - y) < SAME_SIZE for x, y in zip(a.scale, b.scale))


def shared_data(objects, rotation=False):
    users = users_by_data()
    shared = [ob for ob in objects if ob.data is not None and len(users[ob.data]) > 1]
    everyone = {u for ob in shared for u in users[ob.data]}
    same = {u for ob in shared for u in users[ob.data] if same_transform(u, ob, rotation)}
    same_ok = all(can_apply_shared(ob, users, rotation, True) for ob in shared) and len(same) < len(everyone)
    can_minimize = not rotation and all(group_skip_reason(ob, users[ob.data]) is None for ob in shared)
    return SharedData([(ob, len(users[ob.data]) - 1) for ob in shared],
                      all(can_apply_shared(ob, users, rotation, False) for ob in shared), len(same) if same_ok else None, can_minimize)


def shared_rows(shared):
    """The finding's list rows: a note on each object whose data is shared (none when nothing is)."""
    return [(ob.name, f"shared {data_word(ob)} ({others + 1} users)", ob.name, "") for ob, others in shared.objects]


def data_word(ob):
    return "mesh" if ob.type == 'MESH' else "data"


def keeping_children(ob, change):
    """change() moves `ob`'s own transform; its children keep their world matrices (their parent inverse takes it up)."""
    old = ob.matrix_world.copy()
    change()
    bpy.context.view_layer.update()
    if abs(ob.matrix_world.determinant()) > 1e-12:
        for child in ob.children:
            child.matrix_parent_inverse = ob.matrix_world.inverted() @ old @ child.matrix_parent_inverse


def set_rotation(ob, matrix):
    if ob.rotation_mode == 'QUATERNION':
        ob.rotation_quaternion = matrix.to_quaternion()
    elif ob.rotation_mode == 'AXIS_ANGLE':
        axis, angle = matrix.to_quaternion().to_axis_angle()
        ob.rotation_axis_angle = (angle, *axis)
    else:
        ob.rotation_euler = matrix.to_euler(ob.rotation_mode, ob.rotation_euler)


def bake_scale(data, factor):
    """Scale the mesh (its shape keys too) by `factor` per axis; a mirror (odd number of negative axes) turns the faces
    inside out, so the normals are flipped back like Blender's Apply Scale."""
    data.transform(Matrix.Diagonal((*factor, 1.0)), shape_keys=True)
    if factor[0] * factor[1] * factor[2] < 0:
        data.flip_normals()


def set_scale(ob, scale):
    keeping_children(ob, lambda: setattr(ob, "scale", scale))


def apply_to_shared_data(ob, users, scale, rotation, only_same):
    """Apply `ob`'s scale (or rotation) to its shared mesh. Needs can_apply_shared. Returns the new data (or the old
    one, applied in place).
    Scale, All (only_same False): `ob`'s scale goes into the shared mesh once and EVERY user, bigger or smaller, ends at
    scale 1: they all take `ob`'s size (the others' shape changes on purpose).
    Rotation, All: once, on the shared mesh; every user's own turn is undone by `ob`'s, so each keeps its world shape
    (a uniform scale lets each turn be undone).
    Same size: the users with this object's scale (rotation) get a new shared copy at scale 1 (rotation 0); the others
    keep the old mesh and their shape."""
    group = [u for u in users if not only_same or same_transform(u, ob, rotation)]
    data = ob.data if len(group) == len(users) else ob.data.copy()
    factor, turn = ob.scale.copy(), ob.matrix_basis.to_quaternion().to_matrix()
    if rotation:
        data.transform(turn.to_4x4(), shape_keys=True)
    else:
        bake_scale(data, factor)
    for u in group:
        u.data = data
        if rotation:
            new_turn = Matrix.Identity(3) if only_same else u.matrix_basis.to_quaternion().to_matrix() @ turn.inverted()
            keeping_children(u, lambda u=u, m=new_turn: set_rotation(u, m))
        else:
            set_scale(u, (1.0, 1.0, 1.0))
    return data


def apply_transform(objects, scale=False, rotation=False, shared_mode="", notes=None):
    """Apply scale / rotation (Object-coordinate materials keep their pattern: texture_space_fix), see below."""
    notes = [] if notes is None else notes
    with texture_space_fix.compensating_scale(objects, notes):
        return apply_transform_plain(objects, scale, rotation, shared_mode, notes)


def apply_transform_plain(objects, scale, rotation, shared_mode, notes):
    """Apply scale / rotation, parents first. An object sharing its data with others is skipped with a note in `notes`,
    unless shared_mode is SHARED_UNLINK (it gets its own copy first: Blender's isolate_users) or SHARED_ALL (applied to
    the shared data once, see apply_to_shared_data). Returns how many were applied."""
    def depth(ob):
        return len([p for p in iter_parents(ob)])
    done, applied_data = 0, set()
    for ob in sorted(objects, key=depth):
        users = users_by_data()
        others = len(users[ob.data]) - 1 if ob.data is not None else 0
        if shared_mode in (SHARED_SAME, SHARED_MINIMIZE) and ob.data in applied_data:
            continue   # already in the group a former object made
        if others and shared_mode == SHARED_ALL and ob.data in applied_data:
            notes.append(f"Skipped: {ob.name} shares its {data_word(ob)} with {others} others and it was just applied; press again")
        elif others and shared_mode in (SHARED_ALL, SHARED_SAME) and can_apply_shared(ob, users, rotation, shared_mode == SHARED_SAME):
            applied_data.add(apply_to_shared_data(ob, users[ob.data], scale, rotation, shared_mode == SHARED_SAME))
            done += 1
        elif others and shared_mode == SHARED_MINIMIZE and not rotation:
            applied_data.add(ob.data)
            done += minimize_shared_group(ob, users[ob.data], notes)
        elif others and shared_mode != SHARED_UNLINK:
            notes.append(f"Skipped: {ob.name} shares its {data_word(ob)} with {others} others")
        else:
            with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob],
                                           selected_editable_objects=[ob]):
                try:
                    bpy.ops.object.transform_apply(location=False, rotation=rotation, scale=scale, isolate_users=bool(others))
                    done += 1
                except RuntimeError as error:
                    notes.append(f"Skipped: {ob.name}: {error}")
    return done


# Minimize Unapplied Scales: apply every scale that can be applied without changing how anything looks.
SKIP_ZERO_AXIS, SKIP_LINKED, SKIP_RIG, SKIP_ANIMATED = "a scale axis at 0", "linked from a library", "armature", "animated scale"
SKIP_SHARED_DATA = "shared data that is not a mesh"
SKIP_MODIFIER = "a modifier that works in the object's own size"
SKIP_UNKNOWN_MODIFIER = "a modifier whose sizes can't be adjusted"   # reported as "<type> modifier whose sizes ..." (see modifier_blocker)
# Modifiers whose result does not depend on the object's scale. Any other (Array offset, Solidify thickness, Bevel width,
# Displace, Ocean, Geometry Nodes...) uses sizes in object space, so applying the scale would move or reshape its result.
SCALE_SAFE_MODIFIERS = {'SUBSURF', 'MIRROR', 'TRIANGULATE', 'EDGE_SPLIT', 'WEIGHTED_NORMAL', 'SMOOTH', 'ARMATURE', 'BOOLEAN'}
# How a modifier setting changes when the object's uniform scale s moves into its mesh (the setting stays in world size):
# LENGTH x |s|; PER_LENGTH / |s|; AXIS_X / AXIS_Y / AXIS_Z / AXIS_VECTOR x the signed scale of that axis (a position, an
# offset or a push along an axis, so a negative axis flips it).
LENGTH, PER_LENGTH, AXIS_X, AXIS_Y, AXIS_Z, AXIS_VECTOR = "length", "per length", "x", "y", "z", "vector"
# Modifier type > {setting: how it changes}. Only for an object whose data has one user and a scale equal in size on every
# axis; a type not in here (Geometry Nodes, Ocean...) has sizes we don't know, so the object is skipped.
MODIFIER_SIZE_SETTINGS = {
    'BEVEL': {'width': LENGTH, 'spread': LENGTH},   # width_pct (Percent) is a ratio
    'SOLIDIFY': {'thickness': LENGTH, 'nonmanifold_merge_threshold': LENGTH},
    'WIREFRAME': {'thickness': LENGTH},
    'ARRAY': {'constant_offset_displace': AXIS_VECTOR, 'merge_threshold': LENGTH, 'fit_length': LENGTH},
    'DISPLACE': {'strength': LENGTH},
    'WAVE': {'height': AXIS_Z, 'width': LENGTH, 'narrowness': PER_LENGTH, 'falloff_radius': LENGTH, 'speed': LENGTH,
             'start_position_x': AXIS_X, 'start_position_y': AXIS_Y},
    'MIRROR': {'merge_threshold': LENGTH, 'bisect_threshold': LENGTH},
    'WELD': {'merge_threshold': LENGTH},
}
APPLY_SCALE_TYPES = ('MESH', 'CURVE')   # unshared data of these types is applied; shared data only for meshes (Mesh.transform)


def animates_scale(ob):
    animation = ob.animation_data
    if animation is None:
        return False
    curves = list(animation.drivers) + ([curve for bag in action_channelbags(animation.action) for curve in bag.fcurves] if animation.action else [])
    return any(curve.data_path.split(".")[-1].split("[")[0] == "scale" for curve in curves)


def uniform_in_size(scale):
    """True when every axis of `scale` has the same size (signs may differ)."""
    sizes = [abs(v) for v in scale]
    return max(sizes) - min(sizes) <= EPSILON * max(sizes)


def modifier_blocker(ob, shared):
    """Why the modifiers of `ob` stop its scale from being applied (None: they don't). A scale-dependent modifier is fine
    when the object's data has one user (`shared` False), its scale is uniform in size and every such modifier is in
    MODIFIER_SIZE_SETTINGS: apply_scale_to_modifiers then keeps its result."""
    dependent = [modifier for modifier in ob.modifiers if modifier.type not in SCALE_SAFE_MODIFIERS]
    unknown = next((modifier for modifier in dependent if modifier.type not in MODIFIER_SIZE_SETTINGS), None)
    if unknown and not shared:
        return f"{unknown.type.lower()} {SKIP_UNKNOWN_MODIFIER.removeprefix('a ')}"
    if dependent and (shared or not uniform_in_size(ob.scale)):
        return SKIP_MODIFIER
    return None


def scaled_setting(value, how, scale):
    """`value` of a modifier setting after the object's `scale` moved into the mesh (see MODIFIER_SIZE_SETTINGS)."""
    size = abs(scale[0])
    return {LENGTH: lambda: value * size, PER_LENGTH: lambda: value / size, AXIS_X: lambda: value * scale[0],
            AXIS_Y: lambda: value * scale[1], AXIS_Z: lambda: value * scale[2],
            AXIS_VECTOR: lambda: tuple(v * axis for v, axis in zip(value, scale))}[how]()


def apply_scale_to_modifiers(ob, scale):
    """Change the size settings of `ob`'s modifiers so they give the same world result after its `scale` was applied."""
    for modifier in ob.modifiers:
        for name, how in MODIFIER_SIZE_SETTINGS.get(modifier.type, {}).items():
            setattr(modifier, name, scaled_setting(getattr(modifier, name), how, scale))


def minimize_skip_reason(ob, shared=False):
    """Why this object's scale must stay as it is (None: it may be applied). `shared`: its data has other users."""
    if ob.library or ob.override_library or (ob.data is not None and ob.data.library):
        return SKIP_LINKED
    if ob.type == 'ARMATURE':
        return SKIP_RIG
    if min(abs(v) for v in ob.scale) <= EPSILON:
        return SKIP_ZERO_AXIS
    if animates_scale(ob):
        return SKIP_ANIMATED
    return modifier_blocker(ob, shared)


def most_common_scale(users):
    """The scale most users have (same_transform); a tie goes to the one closest to (1, 1, 1), then to the first name."""
    groups = []
    for user in sorted(users, key=lambda u: u.name):
        for group in groups:
            if same_transform(group[0], user, False):
                group.append(user)
                break
        else:
            groups.append([user])
    best = min(groups, key=lambda group: (-len(group), (Vector(group[0].scale) - Vector((1, 1, 1))).length))
    return best[0].scale.copy()


def bake_common_scale(data, users):
    """Put the most common scale of `users` into their shared mesh once; every user's scale is divided by it, so every
    user looks exactly as before (scales are diagonal, so this holds even with rotation). Returns False (nothing to do)
    when that scale is 1. No texture space fix: the caller wraps it (texture_space_fix.compensating_scale)."""
    common = most_common_scale(users)
    if all(abs(v - 1.0) <= EPSILON for v in common):
        return False
    bake_scale(data, common)
    for user in users:
        set_scale(user, tuple(own / shared for own, shared in zip(user.scale, common)))
    return True


def minimize_shared_scale(data, users):
    """bake_common_scale, with Object-coordinate textures keeping their pattern."""
    with texture_space_fix.compensating_scale(users):
        return bake_common_scale(data, users)


def scale_changes(group):
    """True when Minimize would change the scale of the objects in `group` (users of one data): the scale most users have
    is not 1 (a single object is its own most common scale)."""
    return any(abs(v - 1.0) > EPSILON for v in most_common_scale(group))


def group_skip_reason(ob, group):
    """Why the scale of `ob` and the other users of its data (`group`, `ob` included) must stay (None: it may be applied)."""
    reason = next((why for why in (minimize_skip_reason(user, len(group) > 1) for user in [ob] + group) if why), None)
    if reason is None and len(group) > 1 and ob.type != 'MESH':
        reason = SKIP_SHARED_DATA
    return reason


def minimize_shared_group(ob, group, notes):
    """Minimize for the Unapplied Scale popup, inside apply_transform (which keeps the textures): returns 1 when the
    group's shared mesh took its most common scale, else 0 with a note saying why."""
    reason = group_skip_reason(ob, group)
    if reason:
        notes.append(f"Skipped: {ob.name} and the {len(group) - 1} others sharing its data: {reason}")
        return 0
    if not bake_common_scale(ob.data, group):
        notes.append(f"Nothing to minimize: the most common scale of {ob.name}'s group is 1")
        return 0
    return 1


def minimize_unapplied_scales(objects):
    """Apply the scale of every object it is safe for. Unshared data: apply_transform. Shared data (meshes): see
    minimize_shared_scale. Returns (how many objects changed, {reason: how many objects were skipped}); a group
    that is skipped for one object is skipped whole."""
    users, skipped, done, alone, handled = users_by_data(), Counter(), 0, [], set()
    for ob in objects:
        group = users[ob.data] if ob.data is not None else [ob]
        if ob.data in handled or (ob.type not in APPLY_SCALE_TYPES and ob.type != 'ARMATURE') or not scale_changes(group):
            continue
        reason = group_skip_reason(ob, group)
        if reason:
            skipped[reason] += len(group)
        elif len(group) == 1:
            alone.append(ob)
        else:
            done += len(group) if minimize_shared_scale(ob.data, group) else 0
        handled.add(ob.data)
    return done + apply_alone_scales(alone), dict(skipped)


def apply_alone_scales(objects):
    """apply_transform for objects with unshared data, their modifier sizes adjusted to keep the result. Returns how many."""
    scales = {ob: ob.scale.copy() for ob in objects}
    done = apply_transform(objects, scale=True)
    for ob, scale in scales.items():
        if all(abs(v - 1.0) <= EPSILON for v in ob.scale):
            apply_scale_to_modifiers(ob, scale)
    return done


def minimizable_scale_names(objects):
    """The names of `objects` whose scale Minimize Unapplied Scales would change (the All view shows its button only when
    there is one): a mesh or curve whose data group has a scale to bake (scale_changes) and nothing that forbids it. The
    same test minimize_unapplied_scales makes, so the count is what a click changes."""
    users = users_by_data()
    groups = {ob: users[ob.data] if ob.data is not None else [ob] for ob in objects if ob.type in APPLY_SCALE_TYPES}
    return [ob.name for ob, group in groups.items() if scale_changes(group) and not group_skip_reason(ob, group)]


def skipped_text(skipped):
    """", "-joined "count reason" pairs of a {reason: count} skip dict."""
    return ", ".join(f"{count} {reason}" for reason, count in skipped.items())


def minimized_text(done, skipped):
    return f"Minimized {done} objects" + (f"; skipped {skipped_text(skipped)}" if skipped else "")


MINIMIZE_SCALES = BulkFix(
    Action("Minimize Unapplied Scales",
           None,
           "Applies the scale of every object in the scan where that is safe, so each looks exactly as before. Linked "
           "duplicates: the most common scale goes into the shared mesh once, the others keep a smaller scale. Single "
           "objects with Bevel, Solidify, Array, Wave... modifiers get the modifier sizes adjusted to match. Skipped "
           "and counted: a scale axis at 0, library links, armatures, animated scales, linked duplicates or non-uniform scales "
           "with modifiers that work in the object's own size, and modifiers like Geometry Nodes or Ocean.",
           risk=2, confirm=True),
    why="An unapplied scale makes tools, modifiers, physics and exports see a different size than the mesh has, and "
        "tiling and bevels come out uneven.",
    keep="Keep a scale when the object is animated or driven, when it is an instance you scale on purpose, or when "
         "the file is in a pipeline that expects it.",
    confirm_message="Applies the scale of every object in the scan (and of every user of their shared meshes). Linked duplicates get their "
                    "most common scale baked into the shared mesh; the rest keep their size. A single object with a uniform scale "
                    "and Bevel, Solidify, Wireframe, Array, Displace, Wave, Mirror or Weld modifiers has their sizes multiplied to match. "
                    "Skipped: a scale axis at 0, library links, armatures, animated scales, modifiers that work in the object's own size on "
                    "linked duplicates or non-uniform scales, and modifiers whose sizes are unknown (Geometry Nodes, Ocean...).")


def iter_parents(ob):
    while ob.parent is not None:
        ob = ob.parent
        yield ob


def transform_check(check_id, label, help_text, test, button, scale, rotation, risk=2, scan="", why="", keep=""):
    def things(scope):
        return [ob for ob in scope.objects if test(ob)]

    def shared(scope):
        return shared_data(things(scope), rotation)

    def find(scope):
        obs = things(scope)
        return found([ob.name for ob in obs], objects=[ob.name for ob in obs], rows=shared_rows(shared_data(obs, rotation)))

    def clear(scope):
        return apply_transform(things(scope), scale, rotation, scope.shared_mode, scope.notes)
    return register(Check(check_id, "Transforms", label, help_text, find, clear, button, risk, scan=scan, shared=shared,
                          why=why, keep=keep))


transform_check("negative_scale", "Negative Scale",
                "Applies the scale, which turns a mirrored (negative) scale into real geometry with the right normals.",
                negative_scale, "Apply Scale", True, False, risk=2,
                why="A negative scale mirrors the object, which flips its normals. Shading, modifiers like Solidify "
                    "and Bevel, and exports can then look inside out.",
                keep="Keep it for a mirrored linked duplicate (a copy that shares its mesh) that must keep sharing "
                     "the mesh.")
transform_check("unapplied_scale", "Unapplied Scale",
                "Applies the scale: the size is baked into the geometry and the object's scale becomes 1.",
                unapplied_scale, "Apply Scale", True, False, risk=2, scan="scale",
                why="An unapplied scale stretches what modifiers, physics and textures in Object coordinates do. "
                    "Bevels, cloth and textures then come out the wrong size.",
                keep="An object placed at its size with no modifiers, physics or rig is fine scaled. Linked "
                     "duplicates also need their own scale to share one mesh.")
transform_check("unapplied_rotation", "Unapplied Rotation",
                "Applies the rotation: the turn is baked into the geometry and the object's rotation becomes 0.",
                unapplied_rotation, "Apply Rotation", False, True, risk=2, scan="rotation",
                why="An unapplied rotation turns the object's own axes. Modifiers like Mirror and Array, and some "
                    "exports, then work along the wrong axis.",
                keep="Keep it when you placed or turned the object on purpose, like a prop on a table. A rotation you "
                     "animate must stay too.")


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

PRIMITIVE_NAMES = ("Cube", "Plane", "Circle", "UV Sphere", "Sphere", "Ico Sphere", "Icosphere", "Cylinder", "Cone", "Torus",
                   "Grid", "Suzanne", "Monkey", "Empty", "Camera", "Light", "Armature", "BezierCurve", "BezierCircle",
                   "NurbsCurve", "NurbsCircle", "NurbsPath")   # what Blender calls a new object; ".001" style suffixes count too
PRIMITIVE_NAME = re.compile(r"(?:%s)(?:\.\d+)?" % "|".join(re.escape(n) for n in PRIMITIVE_NAMES))
NUMBER_SUFFIX = re.compile(r".*\.\d+")


def is_primitive_name(name):
    return PRIMITIVE_NAME.fullmatch(name) is not None


def primitive_named(objects):
    return [ob for ob in objects if is_primitive_name(ob.name)]


def scanned_objects(context, include_disabled=False):
    """The All kind's scope: the scene's objects, leaving out those in excluded collections unless `include_disabled`."""
    return [ob for ob in context.scene.objects if include_disabled or in_view_layer(ob, context.view_layer)]


def scan_naming(context, include_disabled=False):
    """The All kind's Naming list: the names of the scene's objects (any type) still called like a primitive."""
    return [ob.name for ob in primitive_named(scanned_objects(context, include_disabled))]


def non_array_modifier_names(ob):
    """The names of the modifiers on `ob` other than Instance Array (whose copies share the mesh)."""
    return [modifier.name for modifier in ob.modifiers if not is_instance_array(modifier)]


def linked_modifier_groups(objects):
    """[(data, user count, [(object, modifier names)])] for data used by more than one object, listing those of `objects`
    that have modifiers other than Instance Array. Each such object evaluates its stack on its own, so the shared data
    saves no work. Sorted by data name."""
    wanted, groups = set(objects), []
    for data, users in users_by_data().items():
        listed = [(ob, non_array_modifier_names(ob)) for ob in users if ob in wanted]
        listed = [(ob, names) for ob, names in listed if names]
        if len(users) > 1 and listed:
            groups.append((data, len(users), listed))
    return sorted(groups, key=lambda group: group[0].name)


def scan_linked_modifiers(context, include_disabled=False):
    """The All kind's Modifiers on Linked Data list: [(data name, user count, [(object name, [modifier names])])] over the
    scene's objects (names, so the scan cache survives undo)."""
    return sorted((data.name, count, sorted((ob.name, names) for ob, names in listed))
                  for data, count, listed in linked_modifier_groups(scanned_objects(context, include_disabled)))


def find_primitive_names(scope):
    names = [ob.name for ob in primitive_named(scope.objects)]
    return found(names, objects=names)


register(Check("primitive_name", NAMING, "Primitive Name",
               "Select only: rename the object yourself (Primitive Data Name then renames default-named data to match).",
               find_primitive_names, None,
               why="Names like Cube.003 say nothing about the object. In big files, exports and game engines it gets "
                   "hard to find the right part.",
               keep="Fine for a quick test or a helper you will delete soon."))


def has_own_data(ob):
    """True when `ob` has data (mesh, curve, armature...) that only it uses and that is not linked from a library or a
    library override: the only data with one right name, its object's. Linked duplicates and linked data have none."""
    data = ob.data
    return data is not None and data.users == 1 and data.library is None and data.override_library is None


def data_renames(objects):
    """[(object, the name its data should have)] for objects whose own data (has_own_data) is still named like a
    Blender primitive (is_primitive_name: "Cube.003", "Plane") and not like the object. A data name that simply differs
    (often on purpose) is left alone; shared and linked data are never renamed."""
    return [(ob, ob.name) for ob in objects
            if has_own_data(ob) and ob.data.name != ob.name and is_primitive_name(ob.data.name)]


def match_data_names(objects):
    """Rename each object's own data (see data_renames) to the object's name. Returns how many were renamed."""
    renames = data_renames(objects)
    for ob, name in renames:
        ob.data.name = name
    return len(renames)


def data_rename_names(objects):
    """The names of the objects whose data Match All Data Names would rename (the All view shows its button only when
    there is one): the same test match_data_names makes, so the count is what a click renames."""
    return [ob.name for ob, _name in data_renames(objects)]


def find_primitive_data_names(scope):
    renames = data_renames(scope.objects)
    rows = [(ob.name, f"{friendly_name(ob.data.name)} > {friendly_name(name)}", ob.name, "") for ob, name in renames]
    return found([ob.data.name for ob, _name in renames], objects=[ob.name for ob, _name in renames], rows=rows)


MATCH_DATA_NAMES = BulkFix(
    Action("Match All Data Names",
           None,
           "Renames the data (mesh, curve, armature...) still named like a primitive, such as Cube.002, to its object's "
           "name, for every object in the scan. Skipped: data shared by several objects (linked duplicates) and data "
           "linked from a library or library override.",
           risk=1, confirm=True),
    why="Data still named like Cube.002 says nothing about what it is. In the Outliner, Append and exports, the "
        "right mesh is then hard to find.",
    keep="Fine for a quick test or a helper you will delete soon. A data name that differs but means something is "
         "never touched.",
    confirm_message="Renames the data of every object in the scan that is still named like a primitive (Cube.002, "
                    "Plane...) to its object's name. Linked duplicates and library data are skipped.")


register(Check("primitive_data_name", NAMING, "Primitive Data Name",
               "Renames the data (mesh, curve...) still named like a primitive, such as Cube.002, to its object's name. "
               "Data shared by several objects or linked from a library is not flagged.",
               find_primitive_data_names, lambda scope: match_data_names(scope.objects), "Match Names", risk=1,
               why="Data still named like Cube.002 says nothing about what it is. In the Outliner, Append and "
                   "exports, the right mesh is then hard to find.",
               keep="Fine for a quick test or a helper you will delete soon. A data name that differs but means "
                    "something is never flagged."))


def has_delta(ob):
    return (any(abs(v) > EPSILON for v in ob.delta_location) or any(abs(v) > EPSILON for v in ob.delta_rotation_euler)
            or any(abs(v - 1.0) > EPSILON for v in ob.delta_scale)
            or any(abs(a - b) > EPSILON for a, b in zip(ob.delta_rotation_quaternion, (1.0, 0.0, 0.0, 0.0))))


def find_deltas(scope):
    obs = [ob.name for ob in scope.objects if has_delta(ob)]
    return found(obs, objects=obs)


def clear_deltas(scope):
    count = 0
    for ob in scope.objects:
        if has_delta(ob):
            ob.delta_location, ob.delta_rotation_euler = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
            ob.delta_rotation_quaternion, ob.delta_scale = (1.0, 0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
            count += 1
    return count


register(Check("deltas", "Transforms", "Delta Transforms",
               "Removes the delta transforms (a hidden extra offset, rotation and scale on the object).",
               find_deltas, clear_deltas, risk=2,
               why="Delta transforms are a hidden extra offset on top of the normal transform. The object then sits "
                   "away from where its Location, Rotation and Scale say.",
               keep="Keep them when an animation or a tool uses them on purpose, like offsets on copies of one "
                    "animated object."))

# ---------------------------------------------------------------------------
# Linked data
# ---------------------------------------------------------------------------

CONVERT_ARRAYS = "Convert Arrays"


def groups_of_scope(scope):
    return linked_modifier_groups(scope.objects)


def users_of_groups(groups):
    """Every user of the data of `groups`: a fix on linked data takes its whole group, all users must stay consistent."""
    users = users_by_data()
    return [ob for data, _count, _listed in groups for ob in users[data]]


def scanned_mesh_objects(context, include_disabled=False):
    """The meshes of the All kind's scope: what Convert Arrays (All view) looks at, linked or single user."""
    return [ob for ob in scanned_objects(context, include_disabled) if ob.type == 'MESH']


def converted_text(converted, skipped):
    text = f"Converted {converted} Arrays to Instance Array"
    if skipped:
        text += ". Skipped: " + ", ".join(f"{count} ({reason})" for reason, count in sorted(skipped.items()))
    return text


CONVERT_ARRAYS_HELP = ("Replaces the built-in Arrays with Instance Array (Digit's Modifiers), so the copies stay instances of the shared mesh. "
                       "Only exact ones: Arrays in a run at the end of the stack (stacked Arrays convert together), Fixed Count, no Merge, no Caps, no UV offsets.")
CONVERT_ALL_ARRAYS = BulkFix(
    Action(CONVERT_ARRAYS, None, CONVERT_ARRAYS_HELP, risk=2, confirm=True),
    why="The built-in Array makes real copies of the mesh. Instance Array keeps the copies as instances of one mesh, so "
        "they use less memory and the scene evaluates faster.",
    keep="Keep the built-in Array when you need its Merge, Caps, Fit Length or UV offsets, or when a later modifier "
         "must see the copies as real geometry.",
    confirm_message="Converts the exact built-in Arrays on every mesh object in the scan, linked or not. The copies become "
                    "instances, which is a risk when a later modifier needs real geometry.")


def modifier_picks(groups):
    """Finding.picks of Linked Modifiers: (data name, offered modifier names of all its users) per shared mesh."""
    from . import linked_modifiers   # it imports this module
    users = users_by_data()
    picks = [(data.name, linked_modifiers.offered_names(users[data])) for data, _count, _listed in groups]
    return [(name, names) for name, names in picks if names]


def find_linked_modifiers(scope):
    groups = groups_of_scope(scope)
    listed = [(ob, names) for _data, _count, users in groups for ob, names in users]
    rows = [(ob.name, ", ".join(names), ob.name, "") for ob, names in listed]
    convertible = instance_array.arrays_of(users_of_groups(groups))[0]
    return found([ob.name for ob, _names in listed], objects=[ob.name for ob, _names in listed], rows=rows,
                 unavailable=() if convertible else (CONVERT_ARRAYS,), picks=modifier_picks(groups))


def skipped_notes(skipped, prefix="Skipped"):
    return [f"{prefix}: {count} ({reason})" for reason, count in sorted(skipped.items())]


def apply_linked_modifiers(scope):
    from . import linked_modifiers   # it imports this module
    names = [data.name for data, _count, _listed in groups_of_scope(scope)]
    result = linked_modifiers.apply_linked_modifiers(names, scope.view_layer, scope.unpicked)
    scope.notes += skipped_notes(result.skipped)
    return result.applied


def convert_linked_arrays(scope):
    if not instance_array.available():
        scope.notes.append("Convert Arrays needs the Digit's Modifiers add-on (its Instance Array asset)")
        return 0
    converted, skipped = instance_array.convert_arrays(users_of_groups(groups_of_scope(scope)))
    scope.notes += skipped_notes(skipped, "Not converted")
    return converted


register(Check("linked_modifiers", LINKED, "Linked Modifiers",
               "Applies the modifiers of the linked duplicates (Blender won't): every user of the shared data takes part, "
               "users with the same result share one new mesh. Instance Array and what follows an Armature modifier stay. "
               "Only the ticked modifiers are applied, the others stay. Applying one below a kept one gives what "
               "Blender's own Apply gives (onto the base mesh), which can differ from the viewport.",
               find_linked_modifiers, apply_linked_modifiers, "Apply Modifiers", risk=3, confirm=True,
               more=(Action(CONVERT_ARRAYS, convert_linked_arrays,
                            CONVERT_ARRAYS_HELP, risk=2, confirm=True),),
               why="Blender can't apply modifiers to a mesh that linked duplicates share. You then can't make the "
                   "final shape real, for example before Join or sculpting.",
               keep="Linked duplicates with live modifiers keep the file small and easy to change. Keep them while "
                    "you still change the shape or the modifiers."))


# ---------------------------------------------------------------------------
# Tool settings
# ---------------------------------------------------------------------------


def view3d_spaces():
    return [space for screen in bpy.data.screens for area in screen.areas if area.type == 'VIEW_3D'
            for space in area.spaces if space.type == 'VIEW_3D']


flag_check("affect_origins", "Tool Settings", "Affect Only Origins",
           "Turns off Affect Only Origins (moving would shift only the origins, not the objects).",
           lambda s: [(s.tool_settings, "use_transform_data_origin", "Origins")], risk=1,
           why="With Affect Only Origins on, moving an object moves only its origin. The object stays put, so Move "
               "seems broken.",
           keep="Keep it on while you place origins on purpose.")
flag_check("affect_locations", "Tool Settings", "Affect Only Locations",
           "Turns off Affect Only Locations (rotate and scale would do nothing).",
           lambda s: [(s.tool_settings, "use_transform_pivot_point_align", "Locations")], risk=1,
           why="With Affect Only Locations on, rotate and scale only move the objects' positions. The objects "
               "themselves don't turn or grow.",
           keep="Keep it on while you spread objects around a pivot point on purpose.")
flag_check("affect_parents", "Tool Settings", "Affect Only Parents",
           "Turns off Affect Only Parents (moving a parent would leave its children behind).",
           lambda s: [(s.tool_settings, "use_transform_skip_children", "Parents")], risk=1,
           why="With Affect Only Parents on, moving a parent leaves its children behind. The parts then end up in odd "
               "places.",
           keep="Keep it on while you move a parent without its children on purpose.")
flag_check("mirror_x", "Tool Settings", "X-Axis Mirror",
           "Turns off X-Axis Mirror on the meshes and the rig (edits would also change the other side).",
           lambda s: ([(me, "use_mirror_x", f"Mesh {me.name}") for me in datablocks(s.meshes)]
                      + [(rig.data, "use_mirror_x", f"Rig {rig.name}") for rig in s.rigs]), risk=1,
           why="X-Axis Mirror copies every edit to the other side. A one-sided change, like a scar, then shows up on "
               "both sides.",
           keep="Keep it on while you model, weight paint or pose a character that is the same on both sides.")
flag_check("auto_key", "Tool Settings", "Auto Keying",
           "Turns off Auto Keying (every move would add a keyframe).",
           lambda s: [(s.tool_settings, "use_keyframe_insert_auto", "Auto Keying")], risk=1,
           why="Auto Keying adds a keyframe each time you move something. Poses you only tried out then end up in the "
               "animation.",
           keep="Keep it on while you animate and want every change keyed.")
flag_check("proportional", "Tool Settings", "Proportional Editing",
           "Turns off Proportional Editing (moving one point would drag the ones around it).",
           lambda s: [(s.tool_settings, "use_proportional_edit", "Edit mode"),
                      (s.tool_settings, "use_proportional_edit_objects", "Object mode")], risk=1,
           why="Proportional Editing drags nearby points along when you move one. Small fixes can then bend parts you "
               "did not want to touch.",
           keep="Keep it on while you shape soft, smooth forms on purpose.")
flag_check("snapping", "Tool Settings", "Snapping",
           "Turns off Snapping (moves would jump to snap targets).",
           lambda s: [(s.tool_settings, "use_snap", "Snapping")], risk=1,
           why="Snapping makes moves jump to the grid, vertices or faces. Small moves then jump to the wrong place.",
           keep="Keep it on while you line up parts exactly.")
flag_check("lock_camera", "Tool Settings", "Lock Camera to View",
           "Turns off Lock Camera to View (moving the 3D view would also move the camera).",
           lambda s: [(space, "lock_camera", "3D view") for space in view3d_spaces()], risk=1,
           why="With Lock Camera to View on, every view change moves the camera. You can lose a camera framing you "
               "set up.",
           keep="Keep it on while you frame the shot by moving the view.")

# ---------------------------------------------------------------------------
# Shape keys, visibility, modifiers
# ---------------------------------------------------------------------------


def driven_key_names(keys):
    ad = keys.animation_data
    if ad is None:
        return set()
    return {fc.data_path.split('"')[1] for fc in ad.drivers if fc.data_path.startswith("key_blocks[")}


def raised_keys(scope):
    """[(object, key)] shape keys above 0 that nothing drives (a driven one is meant to move). The first key is the
    basis and is skipped."""
    keys = []
    for ob in scope.meshes:
        shape_keys = ob.data.shape_keys
        if shape_keys is None:
            continue
        driven = driven_key_names(shape_keys)
        keys += [(ob, kb) for kb in list(shape_keys.key_blocks)[1:] if kb.value > EPSILON and kb.name not in driven]
    return keys


def find_raised_keys(scope):
    keys = raised_keys(scope)
    return found(keys, [f"{kb.name} {kb.value:.2f}" for _ob, kb in keys], objects=[ob.name for ob, _kb in keys])


def clear_raised_keys(scope):
    keys = raised_keys(scope)
    for _ob, kb in keys:
        kb.value = 0.0
    return len(keys)


register(Check("key_values", "Mesh", "Shape Key Above Zero",
               "Sets the shape key values that are above 0 back to 0 (not the driven ones).",
               find_raised_keys, clear_raised_keys, "Set to 0", risk=3,
               why="A shape key above 0 changes the shape of the mesh. If you forgot it, renders and exports show "
                   "that change, like a smile you did not want.",
               keep="Keep it when the value is part of the look, for example a body shape you chose."))

flag_check("key_pin", "Mesh", "Shape Key Pinned",
           "Unpins Shape Key Lock (only the active shape key shows, at full value).",
           lambda s: [(ob, "show_only_shape_key", ob.name) for ob in s.meshes], button="Unpin", risk=2,
           why="Shape Key Lock shows only the active shape key, at full value. The mesh then ignores the values of "
               "all the other shape keys.",
           keep="Keep it on while you sculpt or check one shape key on its own.")


def hidden_objects(scope):
    def is_hidden(ob):
        try:
            return ob.hide_viewport or ob.hide_get()
        except RuntimeError:   # not in this view layer
            return ob.hide_viewport
    return [ob for ob in scope.objects if is_hidden(ob)]


def find_hidden_objects(scope):
    obs = hidden_objects(scope)
    return found([ob.name for ob in obs], objects=[ob.name for ob in obs])


def show_object(ob):
    ob.hide_viewport = False
    try:
        ob.hide_set(False)
    except RuntimeError:   # not in this view layer
        pass


def clear_hidden_objects(scope):
    obs = hidden_objects(scope)
    for ob in obs:
        show_object(ob)
    return len(obs)


def is_unseen(ob, view_layer):
    """Hidden itself, or in a hidden or excluded collection (what the All kind's Unhide fixes)."""
    return not in_view_layer(ob, view_layer) or not ob.visible_get(view_layer=view_layer)


def collections_holding(ob, layer_collection):
    """The layer collections that hold `ob` directly or through a child collection, outermost first."""
    below = [c for child in layer_collection.children for c in collections_holding(ob, child)]
    return ([layer_collection] if below or ob.name in layer_collection.collection.objects else []) + below


def off_collections_of(ob, layer_collection):
    """Those of collections_holding that are excluded or hidden."""
    return [lc for lc in collections_holding(ob, layer_collection)
            if lc.exclude or lc.hide_viewport or lc.collection.hide_viewport]


def unhide(context, ob):
    """Make `ob` visible, one step: if it sits in an excluded or hidden collection, turn those collections on and leave
    the object's own hide state alone; else unhide the object. Returns True when something was turned on."""
    off = off_collections_of(ob, context.view_layer.layer_collection)
    for layer_collection in off:
        layer_collection.exclude = False
        layer_collection.hide_viewport = False
        layer_collection.collection.hide_viewport = False
    if not off:
        show_object(ob)
    return True


register(Check("hidden_objects", "Mesh", "Hidden Objects",
               "Shows the hidden parts of this character again (the rig and its meshes).",
               find_hidden_objects, clear_hidden_objects, "Unhide", risk=2, kind=SCENE,
               why="Hidden objects are easy to forget. They still render and export unless they are also hidden from "
                   "render, and you can't check them.",
               keep="Helpers like modifier targets, cages and bone shapes are often hidden on purpose. Keep them "
                    "hidden when you don't need to see them."))


def hidden_bones(scope):
    return [(rig.name, bone.name) for rig in scope.rigs for bone in rig.data.bones if bone.hide]


def find_hidden_bones(scope):
    bones = hidden_bones(scope)
    return found(bones, [b for _r, b in bones], bones=bones)


def clear_hidden_bones(scope):
    bones = hidden_bones(scope)
    for rig_name, bone_name in bones:
        bpy.data.objects[rig_name].data.bones[bone_name].hide = False
    return len(bones)


register(Check("hidden_bones", "Animation & Pose", "Hidden Bones",
               "Shows the bones that were hidden one by one (hidden bone collections stay as they are).",
               find_hidden_bones, clear_hidden_bones, "Unhide", risk=2, kind=SCENE,
               why="Hidden bones are easy to forget. You can't see or select them, so you can't check their pose.",
               keep="Riggers often hide helper bones (bones that only drive other bones) to keep the rig clean. Keep "
                    "them hidden when you don't need them."))


def fast_viewport_off(scene):
    """{(object full name, modifier name)} that Fast Viewport turned off on purpose (it records them on the scene)."""
    return {tuple(entry[:2]) for entry in json.loads(scene.get(FAST_VIEWPORT_KEY, "[]"))}


def is_subdiv_speed_setup(modifier):
    """A Subdivision Surface or Multires modifier hidden in the viewport but on in render (a normal speed setup)."""
    return modifier.type in ('SUBSURF', 'MULTIRES') and modifier.show_render and not modifier.show_viewport


def mismatched_modifiers(objects, scene, ignore_subdiv=False):
    """[(object, modifier)] set differently in the viewport and in render, except the ones Fast Viewport turned off
    (and, with `ignore_subdiv`, the subdivision speed setups)."""
    on_purpose = fast_viewport_off(scene)
    return [(ob, m) for ob in objects for m in ob.modifiers
            if m.show_viewport != m.show_render and (ob.name_full, m.name) not in on_purpose
            and not (ignore_subdiv and is_subdiv_speed_setup(m))]


def find_mismatched_in(objects, scene, ignore_subdiv=False):
    mods = mismatched_modifiers(objects, scene, ignore_subdiv)
    rows = [(ob.name, f"{m.name} · {'on' if m.show_viewport else 'off'} in the viewport, {'on' if m.show_render else 'off'} in render",
             ob.name, "") for ob, m in mods]
    return found(mods, [f"{ob.name}: {m.name}" for ob, m in mods], rows=rows,
                 objects=list(dict.fromkeys(ob.name for ob, _m in mods)))


def find_mismatched(scope):
    return find_mismatched_in(scope.meshes, scope.scene, scope.ignores("subdiv_viewport"))


def clear_mismatched(scope):
    mods = mismatched_modifiers(scope.meshes, scope.scene, scope.ignores("subdiv_viewport"))
    for _ob, m in mods:
        m.show_render = m.show_viewport
    return len(mods)


register(Check("modifier_eyes", DIFFERENCES, "Viewport vs Render",
               "Makes the render setting of each modifier match its viewport setting (on or off in both).",
               find_mismatched, clear_mismatched, "Match", risk=2, rows_title="Modifiers",
               why="A modifier set differently in the viewport and the render makes the render look different from "
                   "what you see. You may only find out after a long render.",
               keep="Subdivision Surface off in the viewport and on in the render is a normal way to keep the "
                    "viewport fast. Fast Viewport's own changes are already skipped."))

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

SUM_TOLERANCE = 0.01


def deform_group_indices(ob):
    return {ob.vertex_groups[name].index for name in weight_cleanup.deform_group_names(ob)}


def weight_scan(scope, ob):
    """(vertices whose deform weights don't sum to 1, indices of groups in use) for a mesh. One pass, shared."""
    def compute():
        deform = deform_group_indices(ob)
        bad, used = [], set()
        for v in ob.data.vertices:
            total = 0.0
            for g in v.groups:
                used.add(g.group)
                if g.group in deform:
                    total += g.weight
            if total > EPSILON and abs(total - 1.0) > SUM_TOLERANCE:
                bad.append(v.index)
        return bad, used
    return scope.memo(("weights", ob.name), compute)


def weighted_meshes(scope):
    return [ob for ob in scope.meshes if len(ob.vertex_groups)]


def find_unnormalized(scope):
    bad = {ob.name: len(weight_scan(scope, ob)[0]) for ob in weighted_meshes(scope)}
    bad = {n: c for n, c in bad.items() if c}
    if not bad:
        return None
    return Finding(sum(bad.values()), f"in {names_text(bad)}", objects=list(bad))


def clear_unnormalized(scope):
    return sum(weight_cleanup.normalise_vertices(ob, weight_scan(scope, ob)[0], weight_cleanup.deform_group_names(ob))
               for ob in weighted_meshes(scope))


register(Check("unnormalized", "Weights", "Weights Don't Add Up",
               "Normalizes the weights: on each vertex the deform groups are scaled so they add up to 1.",
               find_unnormalized, clear_unnormalized, "Normalize", risk=2, scan="weights",
               why="The deform weights of these vertices add up to more or less than 1. Blender evens them out as it "
                   "deforms, but game engines may not, so exports can bend differently.",
               keep="Inside Blender it often looks fine, because Blender evens them out. Keep them if you don't "
                    "export and the rig bends well."))


def locked_groups(scope):
    return [(ob, vg) for ob in weighted_meshes(scope) for vg in ob.vertex_groups if vg.lock_weight]


def find_locked(scope):
    locked = locked_groups(scope)
    return found(locked, [vg.name for _ob, vg in locked], objects=[ob.name for ob, _vg in locked])


def clear_locked(scope):
    locked = locked_groups(scope)
    for _ob, vg in locked:
        vg.lock_weight = False
    return len(locked)


register(Check("locked_groups", "Weights", "Locked Vertex Groups",
               "Unlocks the locked vertex groups (they can be painted again).", find_locked, clear_locked, "Unlock", risk=1,
               kind=SCENE,
               why="A locked vertex group can't be painted. Weight painting on it then seems to do nothing.",
               keep="Keep it locked while you paint the groups next to it and want this one safe."))


def is_mirror_partner_group(ob, vg):
    """A Mirror modifier that mirrors vertex groups needs the other side's group: it moves the copied half's
    weights there. So an empty group whose Left/Right counterpart exists on the mesh must stay."""
    other_side = rig_names.flip(vg.name)
    return chain_weights.mirrors_groups(ob) and other_side != vg.name and other_side in ob.vertex_groups


def empty_groups(scope):
    return [(ob, vg) for ob in weighted_meshes(scope) for vg in ob.vertex_groups
            if vg.index not in weight_scan(scope, ob)[1] and not is_mirror_partner_group(ob, vg)]


def find_empty_groups(scope):
    empty = empty_groups(scope)
    return found(empty, [vg.name for _ob, vg in empty], objects=[ob.name for ob, _vg in empty])


def clear_empty_groups(scope):
    empty = empty_groups(scope)
    for ob, vg in sorted(empty, key=lambda p: -p[1].index):   # last first: removing shifts the later indices
        ob.vertex_groups.remove(vg)
    return len(empty)


register(Check("empty_groups", "Weights", "Empty Vertex Groups",
               "Removes the vertex groups that no vertex uses (a group is a bone's weights: it has nothing in it).",
               find_empty_groups, clear_empty_groups, "Remove", risk=2, scan="weights",
               why="An empty vertex group holds no weights, so its bone moves nothing. Empty groups also clutter the "
                   "list and hide the ones that matter.",
               keep="Keep one when you will paint it soon, or when a modifier or tool needs that group name. An empty Left/Right "
                    "group next to its filled partner on a mesh with a Mirror modifier is kept on its own."))


def mirror_group_gaps(scope):
    return [(ob, chain_weights.missing_mirror_groups(ob)) for ob in weighted_meshes(scope)
            if chain_weights.mirrors_groups(ob) and chain_weights.missing_mirror_groups(ob)]


def find_missing_mirror_groups(scope):
    gaps = mirror_group_gaps(scope)
    return found(gaps, [n for _ob, names in gaps for n in names], objects=[ob.name for ob, _names in gaps])


def add_missing_mirror_groups(scope):
    return sum(len(chain_weights.ensure_mirror_groups(ob)) for ob, _names in mirror_group_gaps(scope))


register(Check("missing_mirror_groups", "Weights", "Missing Mirror Groups",
               "Adds the empty Left/Right counterpart of every sided vertex group on a mesh whose Mirror modifier mirrors vertex groups.",
               find_missing_mirror_groups, add_missing_mirror_groups, "Add", risk=1,
               why="The Mirror modifier moves the copied half's weights into the other side's vertex group, but only when "
                   "that group exists. Without it the mirrored half stays on the original side's bone, so the right side "
                   "follows the left bones.",
               keep="Keep it when the mesh is not meant to be mirrored with its weights."))

def wrong_side_gaps(scope):
    return [(ob, wrong) for ob in weighted_meshes(scope) for wrong in [chain_weights.wrong_side_weights(ob)] if wrong]


def find_mirrored_side_weights(scope):
    wrong = wrong_side_gaps(scope)
    detail = [f"{ob.name}: " + ", ".join(f"{name} ({len(verts)})" for name, verts in groups.items()) for ob, groups in wrong]
    return found(wrong, detail, objects=[ob.name for ob, _groups in wrong])


def clear_mirrored_side_weights(scope):
    return sum(chain_weights.clear_wrong_side_weights(ob) for ob, _groups in wrong_side_gaps(scope))


register(Check("mirrored_side_weights", "Weights", "Mirrored Side Weights",
               "Clears the weights in the other side's vertex groups on the real half of a mesh whose Mirror modifier mirrors "
               "vertex groups (vertices on the mirror plane are kept).",
               find_mirrored_side_weights, clear_mirrored_side_weights, "Clear", risk=3,
               why="The Mirror modifier fills the other side's groups for its copy. Weight painted there on the real half "
                   "makes those vertices follow the wrong side's bone, and the copy then follows the real side's bone.",
               keep="Keep it when the mesh is not really mirrored that way, for example both halves are real geometry."))

# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------


def rig_drivers(scope, rig):
    """Every driver of `rig` (the main rig also with its meshes), read once per scan: DriverInfo list."""
    return scope.memo(("drivers", rig.name),
                      lambda: driver_scan.scan(rig, scope.meshes if rig is scope.rig else ()))


def driver_problems(scope):
    if scope.rig is None:
        return []
    return [d for d in rig_drivers(scope, scope.rig) if d.error and not d.muted]


def find_driver_errors(scope):
    problems = driver_problems(scope)
    return found(problems, [d.title for d in problems],
                 bones=[(scope.rig.name, d.bone) for d in problems if d.bone])


def clear_driver_errors(scope):
    problems = driver_problems(scope)
    for d in problems:
        driver_scan.set_muted(d, True)
    return len(problems)


register(Check("driver_errors", "Drivers", "Drivers With Errors",
               "Mutes the drivers that have errors (they stay in the file, switched off).",
               find_driver_errors, clear_driver_errors, "Mute", risk=2,
               why="A driver with an error stops working. The thing it controls, like a shape key or a bone, then "
                   "stays still.",
               keep="Keep it while you still fix the driver. Also keep it when what it needs, like a rig script, is "
                    "only off for now."))


# ---------------------------------------------------------------------------
# Checks (review only: often intentional, Show selects them in Edit Mode, nothing here fixes anything)
# ---------------------------------------------------------------------------

def review_meshes(scope):
    """Mesh objects to review, one per mesh data (linked duplicates show the same problem)."""
    first = {}
    for ob in scope.meshes:
        first.setdefault(ob.data, ob)
    return list(first.values())


def show_review(review, context, ob):
    """Show button of a review check: the object becomes active and its problem elements are selected in Edit Mode."""
    if not inspect(context, ob):
        return False
    if ob.type != 'MESH':
        return False
    hit = review(ob, scope_of(context))
    if hit is not None:
        mesh_review.show_hit(context, ob, hit)
    return hit is not None


def review_check(check_id, label, help_text, review, scan, show=None, why="", keep=""):
    """A review Check from a mesh_review function `review(ob, scope) -> Hit or None`. Finding rows: object, counts."""
    def find(scope):
        rows = []
        for ob in review_meshes(scope):
            if ob.mode == 'EDIT':
                ob.update_from_editmode()
            hit = review(ob, scope)
            if hit is not None:
                rows.append((ob.name, hit.detail, ob.name, "", hit.count))
        if not rows:
            return None
        return Finding(sum(r[4] for r in rows), names_text(r[0] for r in rows), rows=[r[:4] for r in rows])
    return register(Check(check_id, REVIEW, label, help_text, find, None, scan=scan,
                          show=show or (lambda context, ob: show_review(review, context, ob)), why=why, keep=keep))


def show_non_manifold(context, ob):
    """Show for Non-Manifold: the Select Non Manifold (Skip Mirror Seam) operator, so the selection is what Blender would show."""
    if not inspect(context, ob):
        return False
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='EDGE')   # the seam stays deselected (vertex mode would re-select it from its end points)
    bpy.ops.mesh.select_all(action='DESELECT')
    return bpy.ops.mesh.select_non_manifold_smart(extend=False) == {'FINISHED'}


review_check("review_non_manifold", "Non-Manifold",
             "Edges that are not shared by exactly two faces (open borders, wire edges, three or more faces) or join faces "
             "pointing opposite ways. The open centre seam of a Mirror modifier is skipped. Often intentional (open meshes).",
             mesh_review.non_manifold, "mesh_review", show_non_manifold,
             why="Non-manifold edges (edges not shared by exactly two faces) break 3D printing, booleans and some "
                 "modifiers. They can also shade badly.",
             keep="Open meshes like a plane, cloth or a hair card are non-manifold by design. That is fine for most "
                  "renders.")
review_check("review_mirror_seam", "Mirror Seam Gaps",
             "On a mesh with an X Mirror modifier: open-border vertices close to the mirror plane but not on it (a crack "
             "after mirroring), vertices across the plane (overlapping halves) and faces lying on the plane (doubled faces inside).",
             mesh_review.mirror_seam_gaps, "mesh_review",
             why="A Mirror modifier only joins vertices within its merge distance of the plane, so vertices just off it "
                 "leave a crack down the middle. Vertices across the plane overlap the copy, and a face on it is doubled.",
             keep="Keep it when the gap is on purpose, like a mesh that is not meant to close in the middle.")
review_check("review_unweighted", "Unweighted Verts",
             "Vertices of a mesh with an Armature modifier that have no weight above 0 in any deform-bone group: the rig can't move them.",
             mesh_review.unweighted, "weights",
             why="These vertices have no weight for any deform bone. When the rig moves, they stay behind and stretch "
                 "the mesh.",
             keep="Keep it when those parts should never move with the rig, or when another modifier moves them.")
review_check("review_influences", "Too Many Influences",
             f"Vertices with weights above 0 in more than {mesh_review.MAX_INFLUENCES} deform-bone groups (game engines keep only 4).",
             mesh_review.too_many_influences, "weights",
             why="Most game engines keep only the 4 largest weights on each vertex. They drop the rest, so the model "
                 "bends differently after export.",
             keep="Fine for renders inside Blender, which uses all of the weights.")
review_check("review_doubled", "Doubled Verts",
             f"Vertices closer than {mesh_review.DOUBLE_DISTANCE} m to another vertex (Merge by Distance would join them).",
             mesh_review.doubled, "mesh_review",
             why="Doubled vertices sit on top of each other but are not joined. They cause shading seams and cracks, "
                 "for example with Subdivision Surface.",
             keep="Keep them when the parts must stay separate, like the edge of a pocket or two pieces that only "
                  "touch.")
review_check("review_loose", "Loose Geometry",
             "Vertices with no edges and edges with no faces.",
             mesh_review.loose, "mesh_review",
             why="Loose vertices and edges don't render, but they clutter the mesh. They can break exports, 3D "
                 "printing and modifiers like Solidify.",
             keep="Keep them when a modifier or Geometry Nodes uses them, for example edges for a Skin modifier.")
review_check("review_degenerate", "Degenerate",
             f"Faces with an area under {mesh_review.MIN_FACE_AREA} m2 and edges shorter than {mesh_review.MIN_EDGE_LENGTH} m.",
             mesh_review.degenerate, "mesh_review",
             why="Faces with almost no area and very short edges cause shading spots. They also break tools like "
                 "Bevel and booleans.",
             keep="Rarely wanted. Keep them only when nothing looks wrong and a tool made them on purpose.")
review_check("review_uvs", "Flipped / Overlap UVs",
             "On the active UV map: faces whose UV winding is flipped against the rest of their island, and faces that "
             "overlap another face in UV space. Mirrored or stacked UVs are often intentional.",
             mesh_review.uv_problems, "uv_overlap",
             why="Flipped or overlapping UVs make a texture show mirrored or twice. Bakes then write two faces onto "
                 "the same pixels.",
             keep="Mirrored or stacked UVs save texture space on purpose, for example two sides of a face sharing one "
                  "texture.")
