# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/full_rig.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig: the one entry point the card calls. It only orchestrates: body_rig (guides, fit, body bones),
part_chains (tail / ears / hair / breasts / butt, through rig_component's per-part functions), face_rig_core (face guides,
face rig) and rig_weights (skin weights, Keep Weights). Bone-only: no shape keys, no corrective bones. Wings are not
built here (2026-11-17): they are added with Add Rig Component (rig_component), and so can any other part. Parts a
component owns are left to it: their bones count as the user's, the part of that kind is not built here, and their
weights are put back after the body weights (rig_component.weigh_components).

Steps (each callable alone, so the card can rebuild one step):
    guides = add_guides(meshes, values)           body guides + part guides (tail / ear Base, Mid, Tip on the figure)
    fit(guides, meshes, values=values)            guides fitted to the mesh; tail / ear handles snapped, breast / butt guides
    rig, log = generate_body(guides, meshes, values)   new armature <Name> (from a rough skeleton: a COPY; accept() later)
    place_face_guides(rig, meshes)                face guides auto-placed on the Head, for the user to check
    generate_parts(rig, values)                   part chains from the part guides
    generate_face(rig)                            face rig from the face guides (weigh() runs it as its face step)
    weigh(rig)                                    body weights -> face rig -> part chains -> Keep Weights
    generate(meshes, values)                      all of the above in order
    regenerate(rig, values)                       safe rebuild: pose, collection homes, user bones, painted weights kept
    remove(rig)                                   rig gone, meshes back as they were (modifiers, groups, parenting)

Card support (the Full Character Rig card draws and runs these): STEP_IDS / STEP_TITLES, step_states(), step_blocker(),
run_step() (one card step), set_meshes() (also: a bare character takes a mesh) and the per-step marks (`steps` in
the record, `full_rig_steps` on the guides) that say which steps are done and with which option values, so the card
can show a step as stale without scanning anything. A bare character (no mesh) skips Fit and Weights.

One record (JSON `full_rig` on the armature data): option values, meshes, guide joints, parts, the rough skeleton it
came from, the bones it built. Face and limb state stay in their own records (face_rig_core's face_rig_*, body_rig's
full_rig_body, limb data on the controls) and are read from there. Each mesh keeps how it was before
(`full_rig_before` JSON on the object) for Remove. Steps return log lines; generate / regenerate a report with them.
"""
import json
import re
import time

import bpy
from mathutils import Matrix, Vector

try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, face_rig_core as fr, full_rig_spec as spec, limb_rig as lr, \
        object_tools as ot, part_chains as pc, rig_component as rc, rig_names as rn, rig_weights as rw
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import face_rig_core as fr
    import full_rig_spec as spec
    import limb_rig as lr
    import object_tools as ot
    import part_chains as pc
    import rig_component as rc
    import rig_names as rn
    import rig_weights as rw

VERSION = 1
RECORD = 'full_rig'                      # JSON on the armature data
EXTRAS = 'full_rig_extras'               # JSON list on the armature data: the keep list of a rig with no record yet (a rough skeleton)
BEFORE = 'full_rig_before'               # JSON on each mesh: how it was before the rig touched it
PART_TAG = 'parts'                       # body_rig.TAG value of the part guide armature
SEGMENTS, CURVED, EAR_BONES, DROOPY = rc.SEGMENTS, rc.CURVED, rc.EAR_BONES, rc.DROOPY   # per-part data: rig_component
PART_TOGGLES = {'tail': 'tail', 'hair': 'hair', 'breast': 'breasts', 'butt': 'butt'}   # parts that are options of their own
PART_MESHES = 'full_rig_part_meshes'     # JSON on the body guides: {part kind: mesh name} of a part on a chosen mesh
HAIR_NOTE = 'hair: default guide placed behind the head; drag its Base, Mid and Tip onto the hair'
TWEAKS = {'tail': 'tail_tweaks', 'ear': 'ear_tweaks', 'hair': 'hair_tweaks'}
PARENTS = {c.kind: c.parent for c in rc.COMPONENTS if c.kind in SEGMENTS}   # the bone each part hangs on
STEP_IDS = ('guides', 'fit', 'body', 'face_guides', 'face_parts', 'weights')
STEP_TITLES = ("Add Guides", "Fit Guides", "Generate Body", "Check Face Guides", "Generate Face & Parts", "Weights")
STEP_SHORT = ("Guides", "Fit", "Body", "Face Guides", "Face & Parts", "Weights")       # for "Rebuild <short>"
STEP_TIPS = ("Place guide bones you drag onto the character",
             "Snap the guides to the mesh",
             "Build the body controls from the guides",
             "Look over the eye, brow and mouth guides before the face is built",
             "Build the face and the tail, ears and hair",
             "Skin the mesh to the new bones")
GUIDE_IDS = ('face', 'leg_type', 'fingers', 'toes')               # options that shape the guides
STEP_OPTION_IDS = {                                               # options each step's mark remembers
    'guides': GUIDE_IDS,
    'body': tuple(o.id for o in spec.options('Body') if o.id not in GUIDE_IDS),
    'face_parts': tuple(o.id for o in spec.options('Face') + spec.options('Parts')),
}
GUIDE_STEPS = ('guides', 'fit')                                   # steps that only make sense before the body exists
RIG_OF = 'full_rig_rig_of'                                        # on a mesh: the name of the rig built for it (the card finds it)
GUIDES_OF = 'full_rig_guides_of'                                  # on a mesh / part guide object: its body guides' name
STEPS_PROP = 'full_rig_steps'                                     # JSON on the guides: {step: option values}
NO_MESH_FIT = "No mesh: nothing to fit"
NO_MESH_WEIGHTS = "No mesh: nothing to weigh"
FACE_NOTE = re.compile(r'WARNING|no edge loop|not found|skipp', re.I)    # face_rig_core log lines the user should see


# ---------------------------------------------------------------- progress + log
class Steps:
    """Per-step log lines (returned to the caller) and the window manager's progress bar when there is a window."""

    def __init__(self, total, log=None):
        self.lines, self.total, self.done, self.log = [], total, 0, log
        wm = getattr(bpy.context, 'window_manager', None)
        self.wm = wm if wm is not None and getattr(bpy.context, 'window', None) is not None else None
        self.t = time.time()
        if self.wm:
            self.wm.progress_begin(0, total)

    def say(self, line):
        self.lines.append(line)
        if self.log:
            self.log(line)

    def step(self, name, fn, *args, **kw):
        start = time.time()
        out = fn(*args, **kw)
        self.done += 1
        self.say(f'{name}: {time.time() - start:.1f} s')
        if self.wm:
            self.wm.progress_update(self.done)
        return out

    def end(self):
        if self.wm:
            self.wm.progress_end()
        self.say(f'total {time.time() - self.t:.1f} s')
        return self.lines


def settle(rig, mode='OBJECT'):
    """After a step: the rig in `mode` (Object, or Pose when it was posed before), nothing else left in Edit Mode,
    its Mechanism and Deform collections hidden."""
    bc.hide_rigging(rig)
    view = bpy.context.view_layer
    if rig.name not in view.objects:
        return
    if view.objects.active is not None:
        ot.set_mode(view.objects.active, 'OBJECT')
    ot.set_mode(rig, mode)


def start_mode(rig):
    """The mode settle() puts the rig back in: Pose when it is posed now, else Object."""
    return 'POSE' if rig is not None and rig.mode == 'POSE' else 'OBJECT'


# ---------------------------------------------------------------- the record
def read_record(rig):
    """The stored record of the rig this module built (dict), or None."""
    text = rig.data.get(RECORD) if rig is not None and rig.type == 'ARMATURE' else None
    return json.loads(text) if text else None


def write_record(rig, rec):
    rec['version'] = VERSION
    rig.data[RECORD] = json.dumps(rec)


# ---------------------------------------------------------------- extras (the bones of the rig the tool does not make)
def extras_list(rig):
    """The names on the rig's Keep These Extras list: in its record, else (a rough skeleton not rigged yet) on the data."""
    rec = read_record(rig)
    if rec is not None:
        return list(rec.get('extras', []))
    text = rig.data.get(EXTRAS)
    return list(json.loads(text)) if text else []


def set_extras(rig, names):
    """Store the Keep These Extras list (sorted, no repeats) in the rig's record, else on its data."""
    names = sorted(set(names))
    rec = read_record(rig)
    if rec is None:
        rig.data[EXTRAS] = json.dumps(names)
        return names
    rec['extras'] = names
    write_record(rig, rec)
    return names


def tool_bones(rig):
    """The bones the tool made (or took over by name): the record's built list, the body's and parts' bones, and the
    Add Rig Component parts'."""
    rec = read_record(rig) or {}
    names = set(rec.get('built', [])) | set(br.read_record(rig).get('bones', [])) | rc.owned_bones(rig)
    return names | {n for p in rec.get('parts', []) for n in p['bones']}


def extras_report(rig):
    """Where the bones the tool did not make stand: {'kept': on the Keep list and present, 'unlisted': not on it (they
    stay on the rig, but are reported until the user lists them), 'missing': listed but gone}."""
    others = [b.name for b in rig.data.bones if b.name not in tool_bones(rig)]
    listed = set(extras_list(rig))
    return dict(kept=sorted(n for n in others if n in listed), unlisted=[n for n in others if n not in listed],
                missing=sorted(n for n in listed if n not in rig.data.bones))


def extras_lines(report, shown=8):
    """The report as plain log lines: what is kept, what is not on the list (never dropped silently), what went."""
    def names(group):
        return ', '.join(group[:shown]) + (f' and {len(group) - shown} more' if len(group) > shown else '')
    lines = []
    if report['kept']:
        lines.append(f"extras: {len(report['kept'])} kept from the Keep list ({names(report['kept'])})")
    if report['unlisted']:
        lines.append(f"extras: {len(report['unlisted'])} bones are not on the Keep list ({names(report['unlisted'])}); "
                     "they stay on the rig; add the ones you want in the Keep These Extras list")
    if report['missing']:
        lines.append(f"extras: listed but not on the rig: {names(report['missing'])}")
    return lines


def record_values(rec):
    """The option values a record was built with. One from before the Hair option (2026-11-16) that built hair chains
    (from hand-made hair guides) keeps Hair on; any other missing option takes its default in full_values."""
    values = dict(rec.get('values') or {})
    if 'hair' not in values and any(p['kind'] == 'hair' for p in rec.get('parts', [])):
        values['hair'] = True
    return values


def full_values(values):
    """Every option of the spec: the given values over the Face choice's defaults over the Lean preset."""
    return spec.full_values(values)


def body_config(values):
    """body_rig guide options from the option values (face, leg type, finger / toe / spine counts)."""
    values = full_values(values)
    cfg = spec.config_for(values)['body_rig']
    return dict({k: cfg[k] for k in ('face', 'leg_type', 'fingers', 'toes', 'spine_bones')},
                tail=values['tail'], ears=values['ear_type'] != 'NONE')      # their markers: where Fit looks


def vec(v):
    return [round(x, 6) for x in v]


def meshes_of(rec):
    return [bpy.data.objects[n] for n in rec['meshes'] if n in bpy.data.objects]


# ---------------------------------------------------------------- step marks (what the card reads)
def snapshot(step, values, ids=None):
    """The option values a step was built with ({} for a step no option shapes)."""
    values = full_values(values)
    return {i: values[i] for i in (STEP_OPTION_IDS.get(step, ()) if ids is None else ids)}


def steps_of(rec):
    """{step: option values} of the steps a rig has done. A record from before the card has none: every rig step
    counts as done with the record's values."""
    if 'steps' in rec:
        return rec['steps']
    return {s: snapshot(s, record_values(rec)) for s in STEP_IDS[2:]}


def mark_step(rig, step, values, ids=None):
    """Remember that `step` was built with these option values (`ids` of them: a part of the step, merged in)."""
    rec = read_record(rig)
    steps = steps_of(rec)
    steps[step] = dict(steps.get(step, {}) if ids is not None else {}, **snapshot(step, values, ids))
    rec['steps'] = steps
    write_record(rig, rec)


def clear_steps(rig, names):
    """Steps that must be done again (their marks go)."""
    rec = read_record(rig)
    steps = steps_of(rec)
    rec['steps'] = {s: v for s, v in steps.items() if s not in names}
    write_record(rig, rec)


def guide_marks(guides):
    return json.loads(guides.get(STEPS_PROP, '{}')) if guides is not None else {}


def mark_guides(guides, step, values=None):
    marks = guide_marks(guides)
    marks[step] = snapshot(step, values)
    guides[STEPS_PROP] = json.dumps(marks)


def refresh_built(rig):
    """The bones the tool made: everything that was not there before it started (user bones stay out)."""
    rec = read_record(rig)
    rec['built'] = sorted({b.name for b in rig.data.bones} - set(rec['user_before']) - rc.owned_bones(rig))
    write_record(rig, rec)


def is_bare(guides, rig):
    """Whether a started character has no mesh (a bare rig: Fit and Weights have nothing to work on)."""
    rec = read_record(rig) if rig is not None else None
    if rec:
        return not rec.get('meshes')
    return guides is not None and not json.loads(guides.get('full_rig_meshes', '[]'))


def step_states(guides, rig, values, face=True):
    """[(step id, state, stale)] for the card, no scans: state is 'done', 'next', 'later' or 'off' (Check Face Guides
    when the card's Face toggle is off; Fit and Weights on a bare rig); stale = done with other option values than now.
    Read from the marks on the rig or the guides."""
    current = full_values(values)
    rec = read_record(rig) if rig is not None else None
    marks = steps_of(rec) if rec else guide_marks(guides)
    done = {s: s in marks for s in STEP_IDS}
    if rec:
        done['guides'] = done['fit'] = True
    elif guides is not None:
        done['guides'] = True
    bare = is_bare(guides, rig)
    off = {'face_guides': not face, 'fit': bare, 'weights': bare}
    out, nxt = [], False
    for s in STEP_IDS:
        if off.get(s):
            out.append((s, 'off', False))
        elif done[s]:
            mark = spec.upgrade(marks.get(s))             # a retired option (Tail IK) never makes a step stale
            out.append((s, 'done', any(current.get(i) != v for i, v in mark.items())))
        else:
            out.append((s, 'later' if nxt else 'next', False))
            nxt = True
    return out


def step_blocker(step, guides, rig, meshes):
    """Why a step can't run now, or ''."""
    if step == 'guides':
        return "The body is built: Remove the rig to place new guides" if rig else ""
    if step == 'fit':
        return "Add Guides first" if guides is None else "The body is built: Remove the rig to fit the guides again" if rig \
            else "" if meshes else NO_MESH_FIT
    if step == 'body':
        return "" if rig is not None or guides is not None else "Add Guides first"
    if rig is None:
        return "Generate Body first"
    return NO_MESH_WEIGHTS if step == 'weights' and not meshes else ""


# ---------------------------------------------------------------- guides
def part_guides_of(guides):
    """The part guide armature that belongs to these body guides, or None."""
    ob = bpy.data.objects.get(guides.get('full_rig_part_guides', '')) if guides is not None else None
    return ob if ob is not None and ob.get(br.TAG) == PART_TAG else None


def default_name(meshes):
    return f'{max(meshes, key=lambda o: len(o.data.vertices)).name} Rig' if meshes else 'Character Rig'


def add_guides(meshes, values, name=None, rig=None, matrix=None):
    """Body guides `<Name> Guides` (the template's figure, or read from the rough skeleton `rig`) plus an empty part
    guide armature `<Name> Part Guides` beside them (fit() lays the parts). `matrix`: where the guide object goes
    (a bare rig: the 3D cursor; Add Guides again: where the old guides were). Returns the body guide object."""
    name = name or default_name(meshes)
    opts = body_config(values)
    if rig is not None:
        guides = br.guides_from_rig(rig, opts, name)
    else:
        coll = meshes[0].users_collection[0] if meshes and meshes[0].users_collection else None
        guides = br.make_guides(name, opts, coll)
    if matrix is not None:
        guides.matrix_world = matrix
    parts = bpy.data.objects.new(f'{name} Part Guides', bpy.data.armatures.new(f'{name} Part Guides'))
    for c in guides.users_collection:
        c.objects.link(parts)
    parts[br.TAG] = PART_TAG
    parts.show_in_front = True
    parts.matrix_world = guides.matrix_world.copy()
    guides['full_rig_part_guides'] = parts.name
    parts[GUIDES_OF] = guides.name
    set_meshes(guides, None, meshes)
    for kind in laid_parts(values):       # a bare rig keeps these; Fit snaps the tail and ears to the mesh
        pc.write_handles(parts, kind, default_handles(kind, br.guide_joints(guides), values))
    mark_guides(guides, 'guides', values)
    return guides


def place_guides(guides, matrix):
    """Move the body guides and their part guides together (the part handles stay where they are on the figure)."""
    for ob in (guides, part_guides_of(guides)):
        if ob is not None:
            ob.matrix_world = matrix


def remove_guides(guides):
    """The body guides and their part guides gone (and the meshes' pointer to them)."""
    for n in json.loads(guides.get('full_rig_meshes', '[]')):
        if n in bpy.data.objects and GUIDES_OF in bpy.data.objects[n]:
            del bpy.data.objects[n][GUIDES_OF]
    for ob in (part_guides_of(guides), guides):
        if ob is not None:
            ot.remove_object(ob)


def laid_parts(values):
    """The curved parts whose guide Add Guides and Fit lay: the tail and ears always (their options can be switched on
    later), the hair only while Hair is on (no hair guide behind every bald head)."""
    return [kind for kind in CURVED if kind != 'hair' or full_values(values)['hair']]


def default_handles(kind, joints, values=None):
    """Base, Mid, Tip of a curved part (guide space) on the body guides' figure (rig_component.default_handles, the
    ears in the shape of the Ears option)."""
    return rc.default_handles(kind, joints, full_values(values)['ear_type'])


def lay_hair_guide(parts, guides, values):
    """The hair's default guide on the part guides while Hair is on and it has none yet (Fit cleared it, or Hair was
    switched on after Add Guides). The hair is not looked for on the mesh: the user drags the guide. Log lines."""
    if parts is None or not full_values(values)['hair'] or part_guide(parts, 'hair'):
        return []
    pc.write_handles(parts, 'hair', default_handles('hair', br.guide_joints(guides)))
    return [HAIR_NOTE]


def part_meshes_of(guides, rec=None):
    """{part kind: mesh name} of the parts on a chosen mesh (the record's, else the guides')."""
    if rec and 'part_meshes' in rec:
        return rec['part_meshes']
    return json.loads(guides.get(PART_MESHES, '{}')) if guides is not None else {}


def set_meshes(guides, rig, meshes):
    """The character's meshes from now on: the guides' list and the rig's record, each mesh pointing back (the card
    finds the character from the mesh). They are fitted, skinned and put back on Remove. The card's Use This Mesh
    gives a bare character its mesh this way: before Generate Body, Fit Guides then fits the guides to it; after it,
    Weights skins it (the bones stay where they are)."""
    names = [o.name for o in meshes]
    if guides is not None:
        guides['full_rig_meshes'] = json.dumps(names)
        for o in meshes:
            o[GUIDES_OF] = guides.name
    if rig is not None:
        rec = read_record(rig)
        rec['meshes'] = names
        write_record(rig, rec)
        for o in meshes:
            o[RIG_OF] = rig.name


def choose_part_meshes(guides, rig, meshes, chosen):
    """Remember the mesh each part is on ({kind: mesh name}; '' = the mesh nearest the part, the body on a one-mesh
    character). A chosen mesh joins the character's meshes (it is fitted, skinned and put back on Remove). Returns
    the meshes."""
    chosen = {k: n for k, n in chosen.items() if n in bpy.data.objects}
    extra = [bpy.data.objects[n] for n in sorted(set(chosen.values())) if bpy.data.objects[n] not in meshes]
    meshes = list(meshes) + extra
    if guides is not None:
        guides[PART_MESHES] = json.dumps(chosen)
    if rig is not None:
        rec = read_record(rig)
        rec['part_meshes'] = chosen
        write_record(rig, rec)
    set_meshes(guides, rig, meshes)
    return meshes


def snap_handles(guides, meshes, kind, base, tip, side=''):
    """Base, Mid, Tip of a curved part (guide space) on the mesh between the body guides' root and tip marker
    (rig_component.snap_handles), or None when no part is under the marker. The mesh: the one chosen for the part
    (choose_part_meshes), else the one nearest the tip marker."""
    chosen = part_meshes_of(guides).get(kind)
    mesh = next((o for o in meshes if o.name == chosen), None) or rw.nearest_mesh(meshes, guides.matrix_world @ tip)
    return rc.snap_handles(guides, mesh, base, tip, side)


def fit(guides, meshes, body=True, values=None):
    """Fit the body guides to the meshes (body_rig.fit_guides; `body` False keeps them, e.g. read from a rough
    skeleton), then lay the part guides: the tail's and ears' Base, Mid, Tip snapped to the mesh from the body guides'
    Tail / Ear markers (default handles on the fitted figure where no part is found: the user drags them), the hair's
    default guide while Hair is on, breast and butt guides from the body's surface (built only when their option is
    on; left out without a surface). Wings: Add Rig Component.
    Returns log lines. A bare rig (no meshes) keeps the default figure and the default handles add_guides wrote."""
    mark_guides(guides, 'fit')
    if not meshes:
        return ['fit: no mesh, the default figure kept']
    if body:
        br.fit_guides(guides, meshes)
    parts = part_guides_of(guides)
    if parts is None:
        return []
    lines = []
    with pc.sb.Kept(parts) as k:         # start clean
        E = k.edit()
        for eb in list(E):
            E.remove(eb)
        k.done()
    B, joints = guides.data.bones, br.guide_joints(guides)
    for kind, marker, side in (('tail', 'Tail', ''), ('ear', rn.left('Ear'), 'L')):
        pts = None
        if marker in B and meshes:
            pts = snap_handles(guides, meshes, kind, B[marker].head_local.copy(), B[marker].tail_local.copy(), side)
            lines.append(f'{kind}: Base, Mid, Tip snapped to the mesh' if pts else f'{kind}: none found on the mesh, '
                         'default guide placed')
        pc.write_handles(parts, kind, pts or default_handles(kind, joints, values))
    lines += lay_hair_guide(parts, guides, values)
    probe, joints = br.Probe.from_objects(meshes, guides), br.guide_joints(guides)
    bones = rc.chain_bones('breast', breast_bones=full_values(values)['breast_bones'])
    for kind in ('breast', 'butt'):
        pts = rc.soft_part_points(probe, joints, kind, bones if kind == 'breast' else 1)
        if pts:
            (pc.write_handles if rc.is_curved(kind, bones) else pc.write_guides)(parts, kind, pts)
    return lines


def part_guide(parts, kind):
    """(points, handles?) of a part's guide: a curved part's Base, Mid, Tip (or the chain joints of an older guide),
    a chain's joints; None when it has no guide."""
    handles = pc.handle_points(parts, kind) if kind in CURVED or kind == 'breast' else None
    joints = None if handles else pc.guide_points(parts, kind)
    return (handles, True) if handles else (joints, False) if joints else None


def bone_count(kind, values):
    """Bones per chain a curved part gets from the options (0 = not built): the tail / hair when on, the ears by type."""
    if kind == 'ear':
        return rc.chain_bones(kind, values['ear_type'])
    if kind == 'breast':
        return rc.chain_bones(kind, breast_bones=values['breast_bones']) if values.get('breasts') else 0
    return rc.chain_bones(kind) if values.get(PART_TOGGLES.get(kind), True) else 0


def part_plan(rig, values, rec):
    """([(kind, word, guide points, handles?)] of every part with a guide, [(kind, word, joints in rig space)] of the
    parts to build). From the part guides when they exist, else the record. A curved part's joints follow the curve
    through its handles (part_chains.curve_joints), as many as bone_count says; a part with an option of its own is
    built only when it is on."""
    parts = part_guides_of(bpy.data.objects.get(rec.get('guides', '')))
    if parts is not None:
        to_rig = rig.matrix_world.inverted() @ parts.matrix_world
        every = [(kind, '', [to_rig @ p for p in g[0]], g[1]) for kind in SEGMENTS for g in [part_guide(parts, kind)] if g]
    else:
        every = [(p['kind'], p.get('word', ''), [Vector(x) for x in p['points']], p.get('handles', False))
                 for p in rec.get('all_parts', [])]
    plan = []
    for kind, word, pts, handles in every:
        if kind == 'breast' and bone_count(kind, values) >= 2:       # a one-bone guide grows to a Base, Mid, Tip one
            pts, handles = rc.three_points(pts), True
        count = bone_count(kind, values) if handles or kind == 'ear' else len(pts) - 1
        if handles and count:
            plan.append((kind, word, pc.curve_joints(pts, count)))
        elif count and values.get(PART_TOGGLES.get(kind), True):
            plan.append((kind, word, pts))
    return every, plan


# ---------------------------------------------------------------- body
def generate_body(guides, meshes, values, rig=None, source=None, extras=None):
    """Build the body (body_rig.build_body) on `rig`, else on a new armature `<Name>`; with a rough skeleton
    `source`, on a COPY of it: the original stays hidden and untouched until accept(). Writes the record, with the
    Keep list (`extras`, else the source's own) of the source's bones to keep.
    Returns (rig, log lines)."""
    values = full_values(values)
    rec = read_record(rig) if rig is not None else None
    if rig is None:
        name = guides.name[:-len(' Guides')] if guides.name.endswith(' Guides') else guides.name
        if source is not None:
            rig = source.copy()
            rig.data = source.data.copy()
            rig.name = rig.data.name = f'{source.name} Full Rig'
            rig.animation_data_clear()
            source.hide_set(True)
            source.hide_viewport = True
        else:
            rig = bpy.data.objects.new(name, bc.new_armature(name))
            rig.matrix_world = guides.matrix_world.copy()
        for c in guides.users_collection or [bpy.context.scene.collection]:
            c.objects.link(rig)
    pre = {b.name for b in rig.data.bones}
    widgets_before = sorted(o.name for o in bpy.data.objects if is_widget(o))
    report = br.build_body(rig, guides, spec.config_for(values))
    rec = rec or dict(source=source.name if source is not None else '', accepted=source is None, parts=[],
                      user_before=sorted(pre), steps={}, widgets_before=widgets_before,
                      extras=sorted(set(extras_list(rig) if extras is None else extras)))
    rec.update(values=values, meshes=[o.name for o in meshes], guides=guides.name, part_meshes=part_meshes_of(guides),
               joints={k: vec(v) for k, v in br.guide_joints(guides).items()}, opts=br.guide_options(guides))
    write_record(rig, rec)
    for o in meshes:
        o[RIG_OF] = rig.name
    mark_step(rig, 'body', values)
    return rig, [f"body: {report['bones']} bones" + (f", {len(report['removed'])} removed" if report['removed'] else '')]


def guides_for(rig, rec):
    """(body guide object, temporary?): the record's guides, or temporary ones made from the stored joints."""
    guides = bpy.data.objects.get(rec.get('guides', ''))
    if guides is not None and br.is_guides(guides):
        return guides, False
    temp = br.make_guides(rig.name + ' Temp', rec['opts'], joints={k: Vector(v) for k, v in rec['joints'].items()})
    temp.matrix_world = rig.matrix_world.copy()
    return temp, True


def rebuild_body(rig, values=None):
    """The body again on a generated rig, from its guides (or the stored joints when the guides are gone): the
    'body' step of Regenerate. Returns log lines."""
    rec = read_record(rig)
    guides, temp = guides_for(rig, rec)
    try:
        _, lines = generate_body(guides, meshes_of(rec), values or record_values(rec), rig=rig)
    finally:
        if temp:
            data = temp.data
            bpy.data.objects.remove(temp)
            bpy.data.armatures.remove(data)
            rec = read_record(rig)
            rec['guides'] = ''
            write_record(rig, rec)
    return lines


def face_off(rig, log=None):
    """Take the face rig off (face_rig_core.remove: its weights go to their heirs). The face claims the body's Snout
    as its own control, so body bones it took along are built again."""
    if not fr.has_built(rig):
        return
    fr.remove(rig, log=log or (lambda *a: None))
    if any(n not in rig.data.bones for n in br.read_record(rig).get('bones', [])):
        rebuild_body(rig)


# ---------------------------------------------------------------- parts
def part_opts(kind, values):
    return rc.chain_opts(kind, PARENTS[kind], values.get(TWEAKS.get(kind), False), values['ear_type'],
                         values['breast_bones'])


def generate_parts(rig, values=None):
    """Build (or rebuild) the part chains from the part guides (or the record); a part no longer wanted loses its
    bones (weights merged into the parent). A part of a kind an Add Rig Component part owns is left to it. Returns log
    lines."""
    lines = rc.adopt_legacy_wings(rig)
    rec = read_record(rig)
    values = full_values(values or record_values(rec))
    guides = bpy.data.objects.get(rec.get('guides', ''))
    lines += lay_hair_guide(part_guides_of(guides), guides, values)
    every, plan = part_plan(rig, values, rec)
    owned = rc.owned_kinds(rig)
    made, parts = set(), []
    for kind, word, pts in plan:
        if kind in owned:
            lines.append(f'{kind}: added with Add Rig Component, left as it is')
            continue
        rep = pc.build_chain(rig, kind, pts, part_opts(kind, values))
        made |= set(rep['bones'])
        parts.append(dict(kind=kind, word=word, bones=rep['bones'], chains=list(rep['chains'].values())))
        lines.append(f"{kind}: {len(rep['bones'])} bones")
    old = {n for p in rec.get('parts', []) for n in p['bones']}
    drop_bones(rig, sorted(n for n in old - made if n in rig.data.bones))
    rec = read_record(rig)
    rec.update(parts=parts, values=values,
               all_parts=[dict(kind=k, word=w, points=[vec(p) for p in pts], handles=h) for k, w, pts, h in every])
    write_record(rig, rec)
    mark_step(rig, 'face_parts', values, [o.id for o in spec.options('Parts')])
    return lines


drop_bones = rc.drop_bones               # one way to take bones off (rig_component)


def chain_lists(rig):
    """The part chains to weigh (rig_weights.weigh_all): bone lists, or {bones, mesh} for a part on a chosen mesh."""
    rec = read_record(rig) or {}
    on = rec.get('part_meshes', {})
    return [dict(bones=c, mesh=on[p['kind']]) if p['kind'] in on else c
            for p in rec.get('parts', []) for c in p['chains'] if all(n in rig.data.bones for n in c)]


# ---------------------------------------------------------------- face
def face_flags(values):
    """(eye settings, maw settings) for face_rig_core from the option values (rig_component.face_flags)."""
    return rc.face_flags(full_values(values))


def face_meshes(rig, meshes):
    """The meshes, the face skin first: the one with the most vertices round the Head (none for a bare rig)."""
    head = rig.data.bones['Head']
    h, reach = rig.matrix_world @ head.head_local, 2.5 * head.length * max(rig.matrix_world.to_scale())
    near = lambda o: sum(1 for v in o.data.vertices if (o.matrix_world @ v.co - h).length < reach)
    return sorted(meshes, key=near, reverse=True)


def face_skin(rig, meshes):
    """[name of the face skin], or [] for a bare rig (the face guides then come from the default head)."""
    return [o.name for o in face_meshes(rig, meshes)[:1]]


def face_guide_objects(rig_name):
    """{'eye' / 'maw': face guide object} placed for the rig of this name."""
    return {o['face_rig_kind']: o for o in bpy.data.objects
            if o.get('face_rig_kind') in ('eye', 'maw') and o.get('full_rig') == rig_name}


def place_face_guides(rig, meshes, kinds=('eye', 'maw')):
    """Face guides (face_rig_core's guide objects, one per kind) auto-placed on the generated Head (auto_guides), for
    the user to check before the face is built. Mouth Rig guides only when the body has a Jaw. The meshes go on the
    rig first (take_meshes), as face_rig_core looks for eyeballs among the rig's meshes. Returns log lines."""
    take_meshes(rig, meshes)             # face_rig_core finds eyeball meshes among the rig's own
    skin = face_skin(rig, meshes)
    have, lines = face_guide_objects(rig.name), []
    for kind in kinds:
        if kind == 'maw' and 'Jaw' not in rig.data.bones:
            continue
        ob = have.get(kind)
        if ob is None:
            ob = rc.make_face_guide(rig, kind, skin, f'{rig.name} {fr.TITLES[kind]}')
        else:
            fr.set_guides(ob, rig, fr.auto_guides(rig, kind, skin))
        ob['full_rig'] = rig.name
        lines.append(f"face: {fr.TITLES[kind]} guides placed on {skin[0] if skin else 'the default head'}")
    mark_step(rig, 'face_guides', {})
    return lines


def face_configs(rig, meshes, values, stored):
    """(eye, maw) face_rig_core configs: guides from the face guide objects (else the `stored` configs of the last
    build), the face flags of the option values, the skin found round the Head. None for a kind without guides.
    The face rig must be off already (face_rig_core guesses the jaw and snout bones by name)."""
    flags = dict(zip(('eye', 'maw'), face_flags(values)))
    skin = face_skin(rig, meshes)
    guide_obs = face_guide_objects(rig.name)
    snout = 'Snout' if 'Snout' in br.read_record(rig).get('bones', []) else ''
    out = []
    for kind in ('eye', 'maw'):
        old = stored.get(kind)
        guides = fr.guides_from_object(guide_obs[kind], rig) if kind in guide_obs else old and old['guides']
        if not guides:
            out.append(None)
            continue
        out.append(rc.face_config(rig, kind, guides, skin, flags[kind], snout=snout))
    return tuple(out)


def generate_face(rig, meshes=None, values=None):
    """Build the face rig (face_rig_core.build) on the generated Head from the face guides, with the face flags of the
    option values. An earlier face rig comes off first (face_rig_core.remove: its weights go to their heirs), so this
    rebuilds it too. Needs the body weights (the face takes its weights from the Head's): weigh() runs it as its face
    step. Returns log lines."""
    if rc.entry(rig, 'face'):            # the face was added with Add Rig Component: it rebuilds its own
        return rc.build('face', rig, None, rc.entry(rig, 'face')['settings'], rc.entry(rig, 'face')['parent_choice'])[1]
    rec = read_record(rig)
    meshes = meshes or meshes_of(rec)
    stored = {kind: fr.stored(rig, kind) for kind in ('eye', 'maw')}
    notes = []
    keep = lambda *a: notes.append(' '.join(str(x) for x in a)) if FACE_NOTE.search(str(a[0])) else None
    face_off(rig, keep)
    eye, maw = face_configs(rig, meshes, full_values(values or record_values(rec)), stored)
    if not (eye or maw):
        return ['face: no face guides, skipped']
    fr.build(rig, eye, maw, log=keep)
    mark_step(rig, 'face_parts', values or record_values(rec), [o.id for o in spec.options('Face')])
    kinds = ' + '.join(fr.TITLES[c['kind']] for c in (eye, maw) if c)
    return [f"face: {kinds}, {len(fr.built_info(rig).get('made', []))} bones"] + \
        [f"face: {n.replace('M# ', '')}" for n in notes]


# ---------------------------------------------------------------- weights
def before_state(o, rig):
    """How a mesh is before the rig touches it: parent, modifiers, vertex groups and weights."""
    return dict(rig=rig.name, parent=o.parent.name if o.parent else '', parent_type=o.parent_type,
                parent_bone=o.parent_bone, parent_inverse=[list(r) for r in o.matrix_parent_inverse],
                modifiers=[m.name for m in o.modifiers],
                armature={m.name: m.object.name for m in o.modifiers if m.type == 'ARMATURE' and m.object},
                groups=[g.name for g in o.vertex_groups], weights=fr.snapshot(o))


def take_meshes(rig, meshes):
    """The meshes go on the rig (rig_weights.attach: parented, Armature modifier), each one's before-state stored the
    first time for Remove; a rough skeleton's Armature modifiers deform with the copy instead (no double deform)."""
    rec = read_record(rig)
    for o in meshes:
        if not o.get(BEFORE):
            o[BEFORE] = json.dumps(before_state(o, rig))
        if rec.get('source') and not rec.get('accepted'):
            for m in o.modifiers:
                if m.type == 'ARMATURE' and m.object is not None and m.object.name == rec['source']:
                    m.object = rig
        rw.attach(o, rig)


def weigh(rig, meshes=None, keep=True, face=True, values=None):
    """Skin weights in Generate's order (rig_weights.weigh_all): body automatic weights, the face rig (generate_face:
    it takes its weights from the Head), the part chains, then Keep Weights. `keep`: True = painted weights on bones
    that still deform come back (remembered now), a rig_weights.remember_weights dict = those, False = fresh weights.
    The first weigh stores each mesh's before-state for Remove. Returns log lines."""
    rec = read_record(rig)
    meshes = meshes or meshes_of(rec)
    if keep is True:
        keep = rw.remember_weights(rig, meshes) if all(o.get(BEFORE) for o in meshes) else None
    take_meshes(rig, meshes)
    face_lines = []
    face = face or rc.entry(rig, 'face') is not None      # an Add Rig Component face comes back with the weights
    face_step = (lambda r, m: face_lines.extend(generate_face(r, m, values or record_values(rec)))) if face else None
    report = rw.weigh_all(rig, meshes, dict(face=face_step, chains=chain_lists(rig), parts=[rc.weigh_components],
                                            keep=keep or None))
    filled = sum(r['filled'] for r in report['body'].values())
    mark_step(rig, 'weights', values or record_values(rec))
    return [f"weights: {len(meshes)} meshes, {filled} vertices filled, {len(report['chains'])} part chains"
            + (', your weights kept' if keep else '')] + face_lines


# ---------------------------------------------------------------- the whole thing
def generate(meshes, values, name=None, source=None, guides=None, face=True, log=None, extras=None):
    """The whole rig in order: guides (unless given) + fit, body, parts, face guides auto-placed, weights with the face
    rig. `source`: a rough skeleton to start from (worked on a copy; accept() makes it final). Returns (rig, report)
    with the log lines in report['log'] and the extras report (extras_report) in report['extras']. `extras`: names of the
    source's bones to keep (else its own Keep list); the other bones the tool does not make stay too, but are reported."""
    values = full_values(values)
    steps = Steps(6 if guides is None else 4, log)
    if guides is None:
        guides = steps.step('guides', add_guides, meshes, values, name, source)
        for line in steps.step('fit', fit, guides, meshes, source is None, values):
            steps.say(line)
    rig, lines = steps.step('body', generate_body, guides, meshes, values, source=source, extras=extras)
    for line in lines + steps.step('parts', generate_parts, rig, values):
        steps.say(line)
    if face:
        for line in steps.step('face guides', place_face_guides, rig, meshes):
            steps.say(line)
    for line in steps.step('weights + face', weigh, rig, meshes, False, face, values):
        steps.say(line)
    fr.finish_rig(rig)
    refresh_built(rig)
    settle(rig)
    report = extras_report(rig)
    for line in extras_lines(report) if source is not None else ():
        steps.say(line)
    steps.say(f'{rig.name}: {len(rig.data.bones)} bones')
    return rig, dict(bones=len(rig.data.bones), log=steps.end(), extras=report)


def user_bones(rig, rec):
    """Bones that are not the tool's: the user's own (added after the build) and a rough skeleton's left-overs."""
    built = set(rec.get('built', []))
    return [b.name for b in rig.data.bones if b.name not in built]


def pose_props(rig):
    """Number custom properties on the pose bones (switches, sliders), to restore after a rebuild."""
    out = {}
    for pb in rig.pose.bones:
        vals = {k: pb[k] for k in pb.keys() if isinstance(pb[k], (int, float))}
        if vals:
            out[pb.name] = vals
    return out


def restore_props(rig, saved):
    for name, vals in saved.items():
        pb = rig.pose.bones.get(name)
        for k, v in (vals.items() if pb else ()):
            if k in pb.keys():
                pb[k] = v


def keep_user_parents(rig, names, parent_of, ancestors):
    """The user's bones hang where they did, or on their nearest old ancestor that still exists."""
    B, fix = rig.data.bones, {}
    for n in [n for n in names if n in B]:
        want = parent_of[n]
        if want and want not in B:
            want = next((p for p in ancestors[n] if p in B), '')
        if want != (B[n].parent.name if B[n].parent else ''):
            fix[n] = want
    if fix:
        with pc.sb.Kept(rig) as k:
            E = k.edit()
            for n, p in fix.items():
                E[n].use_connect = False
                E[n].parent = E.get(p) if p else None
            k.done()


def regenerate(rig, values=None, keep_weights=True, log=None):
    """Rebuild from the record and the guides (or the stored joints when the guides are gone): body, parts, face and
    weights, keeping the pose (transforms and switches), the bones' collection homes, the user's own bones (re-parented
    to the nearest bone that stays if theirs went) and, with Keep Weights, the painted weights. A changed option adds
    or removes only its feature (body_rig / limb_rig.remove_features, part toggles, face flags). Returns a report."""
    rec = read_record(rig)
    if rec is None:
        raise ValueError(f'{rig.name} was not made by Full Character Rig')
    rc.adopt_legacy_wings(rig)
    rec = read_record(rig)
    values = full_values(values or record_values(rec))
    mode = start_mode(rig)
    steps = Steps(3, log)
    meshes = meshes_of(rec)
    fr.standardise_face(rig)             # old face names first, so the kept pose, homes and weights use the new ones
    pose, props = fr.control_pose(rig, rig.pose.bones.keys()), pose_props(rig)
    homes = fr.bone_homes(rig, [b.name for b in rig.data.bones])
    mine = user_bones(rig, rec)
    ancestors = {b.name: [p.name for p in b.parent_recursive] for b in rig.data.bones}
    parent_of = {n: rig.data.bones[n].parent.name if rig.data.bones[n].parent else '' for n in mine}
    saved = rw.remember_weights(rig, meshes) if keep_weights else False
    lr.set_mode(rig, 'OBJECT')
    fr.reset_pose(rig)
    if fr.has_built(rig):                # the face off first: it hangs on the body and claims its Snout
        fr.remove(rig, log=lambda *a: None)
    lines = steps.step('body', rebuild_body, rig, values)
    lines += generate_parts(rig, values)
    keep_user_parents(rig, mine, parent_of, ancestors)
    lines += steps.step('weights + face', weigh, rig, meshes, saved, True, values)
    keep_user_parents(rig, mine, parent_of, ancestors)
    for line in lines:
        steps.say(line)
    rec = read_record(rig)
    rec['built'] = sorted({b.name for b in rig.data.bones} - set(mine) - rc.owned_bones(rig))
    write_record(rig, rec)
    fr.restore_homes(rig, {n: h for n, h in homes.items() if n in rig.data.bones})
    fr.restore_pose(rig, pose)
    restore_props(rig, props)
    fr.finish_rig(rig)
    settle(rig, mode)
    report = extras_report(rig)
    for line in extras_lines(report):
        steps.say(line)
    steps.say(f'{rig.name}: {len(rig.data.bones)} bones, {len([n for n in mine if n in rig.data.bones])} of yours kept')
    return dict(bones=len(rig.data.bones), log=steps.end(), extras=report)


def run_step(step, meshes, values, guides=None, rig=None, face=True, log=None, part_meshes=None):
    """One step of the card (`STEP_IDS`), done now or again (the card's rebuild button). Returns (guides, rig, log
    lines). The face is built together with the weights (it takes its weights from the Head), so Generate Face &
    Parts builds the parts and, once the weights exist, the face too; `face` False (the card's Face toggle) leaves the
    face out. `part_meshes` ({kind: mesh name}, the card's
    part mesh pickers) is remembered first (choose_part_meshes)."""
    values = full_values(values)
    why = step_blocker(step, guides, rig, meshes)
    if why:
        raise ValueError(why)
    mode = start_mode(rig)
    if rig is not None:
        rc.adopt_legacy_wings(rig)
    if part_meshes is not None and (guides is not None or rig is not None):
        meshes = choose_part_meshes(guides, rig, meshes, part_meshes)
    steps = Steps(1, log)
    lines = []
    if step == 'guides':
        name = matrix = None
        if guides is not None:           # again: the same name and place (a bare rig's guides are its only anchor)
            name, matrix = guides.name.removesuffix(' Guides'), guides.matrix_world.copy()
            remove_guides(guides)
        guides = steps.step(step, add_guides, meshes, values, name, matrix=matrix)
        if part_meshes is not None:
            choose_part_meshes(guides, None, meshes, part_meshes)
    elif step == 'fit':
        lines = steps.step(step, fit, guides, meshes, True, values)
    elif step == 'body':
        if rig is None:
            rig, lines = steps.step(step, generate_body, guides, meshes, values)
        else:                            # again: the face off first, the later steps are done again after it
            face_off(rig)
            lines = steps.step(step, rebuild_body, rig, values)
            clear_steps(rig, ('face_parts', 'weights'))
        refresh_built(rig)
    elif step == 'face_guides':
        lines = steps.step(step, place_face_guides, rig, meshes)
    elif step == 'face_parts':
        lines = steps.step(step, generate_parts, rig, values)
        mark_step(rig, step, values, [])
        if face and ('weights' in steps_of(read_record(rig)) or not meshes):   # bare: no weights to wait for
            lines += steps.step('face', generate_face, rig, meshes, values)
        elif face:
            lines.append('face: built with the weights')
        if not meshes:                   # bare: there is no Weights step to finish the rig
            fr.finish_rig(rig)
        refresh_built(rig)
    elif step == 'weights':
        again = 'weights' in steps_of(read_record(rig))
        lines = steps.step(step, weigh, rig, meshes, again, face, values)
        fr.finish_rig(rig)
        refresh_built(rig)
    else:
        raise ValueError(f'unknown step {step!r}')
    if rig is not None:
        settle(rig, mode)
    return guides, rig, lines + steps.end()


def accept(rig):
    """From a rough skeleton: the copy replaces the original (deleted) and takes its name. Returns log lines."""
    rec = read_record(rig)
    if rec is None or rec.get('accepted'):
        return []
    name, old = rec['source'], rig.name
    src = bpy.data.objects.get(name)
    if src is not None:
        ot.remove_object(src)
    rig.name = name
    for o in bpy.data.objects:              # the meshes' before-state belongs to the renamed rig now
        if o.type == 'MESH' and o.get(BEFORE):
            before = json.loads(o[BEFORE])
            if before.get('rig') == old:
                before['rig'] = name
                o[BEFORE] = json.dumps(before)
    for o in meshes_of(rec):
        o[RIG_OF] = name
    for ob in face_guide_objects(old).values():
        ob['full_rig'] = name
    rec.update(accepted=True, source='')
    write_record(rig, rec)
    return [f'{name}: the new rig replaced the rough skeleton']


def restore_mesh(o, before, rig):
    """A mesh back to its before-state: our Armature modifier off, the rough rig's back, groups and weights as they
    were, the old parent (the world transform stays)."""
    world = o.matrix_world.copy()
    for m in list(o.modifiers):
        if m.name not in before['modifiers'] and m.type == 'ARMATURE' and m.object in (rig, None):
            o.modifiers.remove(m)
    for name, target in before['armature'].items():
        if name in o.modifiers:
            o.modifiers[name].object = bpy.data.objects.get(target)
    names = list(o.modifiers.keys())
    for i, name in enumerate(n for n in before['modifiers'] if n in names):     # the old order
        o.modifiers.move(list(o.modifiers.keys()).index(name), i)
    for g in list(o.vertex_groups):
        o.vertex_groups.remove(g)
    for name in before['groups']:
        o.vertex_groups.new(name=name)
    fr.restore_weights({o.name: before['weights']})
    parent = bpy.data.objects.get(before['parent'])
    o.parent = parent
    if parent is not None:
        o.parent_type, o.parent_bone = before['parent_type'], before['parent_bone']
        o.matrix_parent_inverse = Matrix(before['parent_inverse'])
    else:
        o.matrix_world = world
    del o[BEFORE]


def is_widget(ob):
    """A control shape object of ours (face_rig_core.ensure_widget names)."""
    return ob.type == 'MESH' and (ob.name.startswith('WGT-') or ob.name.startswith('SelectionSphere'))


def rig_leftovers(rig, rec, guide_objects):
    """(widget objects, collections) the rig and its face guides brought: the rig's control shapes and the widgets in
    the face guides' collections, and the unlinked ones (control shapes sit in no collection), minus what the file had before the build; the face guides' collections."""
    colls = {c for ob in guide_objects for c in ob.users_collection if c != bpy.context.scene.collection}
    colls |= {child for c in colls for child in c.children_recursive}
    widgets = {pb.custom_shape for pb in rig.pose.bones if pb.custom_shape} | {o for c in colls for o in c.objects if is_widget(o)}
    widgets |= {o for o in bpy.data.objects if is_widget(o) and not o.users_collection}   # unlinked ones (the face guides')
    before = set(rec.get('widgets_before', ()))
    return [w for w in widgets if w.name not in before], colls


def drop_leftovers(widgets, colls):
    """Widgets no armature uses any more go, the others leave the rig's collections; then the collections left empty go
    (children first)."""
    used = {pb.custom_shape for o in bpy.data.objects if o.type == 'ARMATURE' for pb in o.pose.bones if pb.custom_shape}
    for w in widgets:
        if w not in used:
            mesh = w.data
            bpy.data.objects.remove(w)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    for c in sorted(colls, key=lambda c: len(c.children_recursive)):
        for w in [o for o in c.objects if is_widget(o)]:      # still used elsewhere: kept by its fake user only
            w.use_fake_user = True
            c.objects.unlink(w)
        if not c.objects and not c.children:
            bpy.data.collections.remove(c)


def remove(rig):
    """Remove the generated rig and put the meshes back as they were (modifiers, vertex groups, parenting); its guide
    objects go too. A rough skeleton that was not accepted comes back. Returns log lines."""
    rec = read_record(rig)
    if rec is None:
        raise ValueError(f'{rig.name} was not made by Full Character Rig')
    lines = []
    if rig.mode != 'OBJECT':
        lr.set_mode(rig, 'OBJECT')
    for o in meshes_of(rec):
        o.pop(RIG_OF, None)
    for o in bpy.data.objects:
        if o.type == 'MESH' and o.get(BEFORE):
            before = json.loads(o[BEFORE])
            if before.get('rig') == rig.name:
                restore_mesh(o, before, rig)
                lines.append(f'{o.name}: back as it was')
    guides = bpy.data.objects.get(rec.get('guides', ''))
    extra = [o for o in (guides, part_guides_of(guides)) if o is not None] + list(face_guide_objects(rig.name).values())
    src = bpy.data.objects.get(rec.get('source', ''))
    if src is not None and not rec.get('accepted'):
        src.hide_viewport = False
        src.hide_set(False)
    rc.remove_all_guides(rig.name)
    widgets, colls = rig_leftovers(rig, rec, list(face_guide_objects(rig.name).values()))
    for ob in extra + [rig]:
        ot.remove_object(ob)
    drop_leftovers(widgets, colls)
    lines.append('rig removed')
    return lines
