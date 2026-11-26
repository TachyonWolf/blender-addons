# SPDX-License-Identifier: GPL-3.0-or-later
"""Add Rig Component: ONE rig part on its own, as its own armature (`<Component> Rig`) or into an existing rig, on the
right bone (found by its standard name, docs/BONE_NAMES.md: tail / butt -> Pelvis, wings / ray fin / breasts ->
Chest, ears / hair / face -> Head; the user can pick another). The Full Character Rig builds its parts with the same
per-part functions (full_rig imports this module), so a part is built one way only.

Components (COMPONENTS): Tail, Ears, Hair, Breasts, Butt (part_chains), Membrane Wings (wing_rig + wing_membrane),
Ray Fin (fin_rig), Face (face_rig_core: Eye Rig + Anthro Mouth Rig; it needs a rig with a Head bone). Wings are only
added with this tool (the Full Character Rig no longer builds them, 2026-11-17). The look rig is not a component of
its own: the Eye Rig builds it (face_rig_core's `look` extra) and it needs the Eye Rig's eye bones and sizes.

Steps (each alone; the card calls them):
    guides, lines = add_guides(cid, rig, mesh, options)       guide bones you drag: on the mesh, else near the parent
    rig, lines = build(cid, rig, guides, options, parent)     into `rig`, or (rig None) a new armature
    lines = weigh(cid, rig, mesh)                             skin weights for this part only (not the Face: it takes
                                                              its weights from the Head when it is built)
    rig_left, lines = remove(cid, rig)                        this part only; a standalone armature goes with its last

One record (JSON `rig_components` on the armature data): {component id: entry}, entry = options, parent bone, bones,
chains / spars, the guide shape it was built from (rig space; Rebuild uses it when the guides are gone), the weights
mesh. The Full Character Rig reads it: it leaves component bones alone (they count as the user's), skips its own part
of a kind a component owns, and weighs the components again after its body weights (weigh_components). Wings a Full
Rig built before 2026-11-17 read as components here (legacy_wings) and are moved over on the next write.
Nothing here runs in the background: every function runs from a button.
"""
import json
from collections import namedtuple

import bpy
from mathutils import Matrix, Vector

try:                                     # inside the add-on package
    from . import body_rig as br, bone_collections as bc, face_rig_core as fr, fin_rig as fnr, full_rig_spec as spec, \
        limb_rig as lr, object_tools as ot, part_chains as pc, rig_names as rn, rig_weights as rw, wing_rig as wr
except ImportError:                      # Scripts/batch_tools copy
    import body_rig as br
    import bone_collections as bc
    import face_rig_core as fr
    import fin_rig as fnr
    import full_rig_spec as spec
    import limb_rig as lr
    import object_tools as ot
    import part_chains as pc
    import rig_names as rn
    import rig_weights as rw
    import wing_rig as wr

RECORD = 'rig_components'                # JSON on the armature data: {component id: entry}
GUIDE_OF = 'rig_component'               # on a guide object: the component it guides
GUIDE_RIG = 'rig_component_rig'          # ... and the rig it belongs to ('' = a new armature)
MORE_GUIDES = 'rig_component_more'       # ... and (the Face's eye guides) the names of its other guide objects
FACE_SKIN = 'rig_component_skin'         # ... and (the Face's eye guides) the skin mesh the guides were placed on
FULL_RIG = 'full_rig'                    # full_rig.RECORD: read here only to take over the wings it built before
TEMP = 'Rig Component Temp'

# ---------------------------------------------------------------- per-part data (the Full Character Rig uses it too)
SEGMENTS = {'tail': 6, 'ear': 3, 'hair': 4, 'breast': 1, 'butt': 1}
BREAST_BONES = (1, 4)                    # bones per breast (limits); 2+ makes the breast a curved part: a Base, Mid, Tip guide
CURVED = ('tail', 'ear', 'hair')         # parts guided by three handles (Base, Mid, Tip); the chain follows their curve
EAR_BONES = {'NONE': 0, 'HUMAN': 1, 'SHORT': 2, 'LONG': 3, 'EXTREME': 5}   # bones per ear, by the Ears type
DROOPY = ('LONG', 'EXTREME')             # ear types with a Droop slider
# Default handles (Base, Mid, Tip) where no mesh is under a part: the tail in body heights from the pelvis, the ears
# in Head bone lengths from the head top (x out, y back, z up; left ear). A gentle tail droop that lifts at the tip.
TAIL_HANDLES = ((0, 0.06, 0.0), (0, 0.18, -0.06), (0, 0.31, -0.03))
EAR_HANDLES = {
    'HUMAN': ((0.4, 0.05, -0.45), (0.46, 0.12, -0.4), (0.5, 0.2, -0.35)),
    'SHORT': ((0.38, 0.0, -0.12), (0.5, 0.02, 0.2), (0.6, 0.05, 0.5)),
    'LONG': ((0.48, 0.0, -0.2), (0.85, 0.05, -0.25), (0.95, 0.1, -0.95)),
    'EXTREME': ((0.3, 0.05, -0.08), (0.42, 0.12, 0.75), (0.5, 0.35, 1.5)),
}
HAIR_HANDLES = ((0, 0.45, -0.3), (0, 0.6, -0.75), (0, 0.65, -1.25))   # Head lengths from the head top: down the back
WHOLE_SHARE = 0.6                        # a part found on more than this share of a mesh: the mesh is just the part
SOFT_REACH = 0.08                        # a breast / butt with no mesh: the body surface is this share of the figure height out
MIN_PART_VERTS = 8                       # a part guide that finds fewer vertices than this has no part under it

# ---------------------------------------------------------------- the components and their few settings
Setting = namedtuple('Setting', 'id label kind default choices limits tip')
EAR_CHOICES = tuple(c for c in spec.EAR_TYPES if c[0] != 'NONE')
SETTINGS = {
    'ear_type': Setting('ear_type', "Ear Type", 'enum', 'SHORT', EAR_CHOICES, None, "How many bones each ear gets"),
    'tweaks': Setting('tweaks', "Tweaks", 'bool', False, None, None,
                      "Extra small controls along the chain, for hand-shaping its curve"),
    'spokes': Setting('spokes', "Spokes", 'int', fnr.SPOKES, None, (1, fnr.MAX_SPOKES),
                      "How many stiff rays each fin has. More rays: a smoother wave, more bones"),
    'face': Setting('face', "Face", 'enum', 'SNOUT', spec.FACE_CHOICES, None, "A snout face or a flat human face"),
    'breast_bones': Setting('breast_bones', "Bones", 'int', 1, None, BREAST_BONES,
                            "Bones per breast. 2 or more follow a curved guide (Base, Mid, Tip) and get a Droop slider"),
    'mouth': Setting('mouth', "Mouth", 'bool', True, None, None, "Also build the Anthro Mouth Rig: jaw, lips, tongue"),
}
# id, label, part kind, standard parent bone, settings, weights step?, tooltip
Component = namedtuple('Component', 'id label kind parent settings weights tip')
COMPONENTS = (
    Component('tail', "Tail", 'tail', 'Pelvis', ('tweaks',), True, "A bendy tail with IK and FK"),
    Component('ears', "Ears", 'ear', 'Head', ('ear_type', 'tweaks'), True, "A pair of ears with IK and FK"),
    Component('hair', "Hair", 'hair', 'Head', ('tweaks',), True, "A bendy hair chain (a ponytail or a long lock)"),
    Component('breasts', "Breasts", 'breast', 'Chest', ('breast_bones',), True, "A bone for each breast, to pose or jiggle"),
    Component('butt', "Butt", 'butt', 'Pelvis', (), True, "A bone for each butt cheek, to pose or jiggle"),
    Component('membrane_wings', "Membrane Wings", 'wing', 'Chest', ('tweaks',), True,
              "Bat or dragon wings: skin between long fingers, with a Fold slider"),
    Component('ray_fin', "Ray Fin", 'fin', 'Chest', ('spokes',), True,
              "Manta or stingray fins: stiff rays that ripple in a wave"),
    Component('face', "Face", 'face', 'Head', ('face', 'mouth'), False,
              "The Eye Rig and the Anthro Mouth Rig. Needs a rig with a Head bone"),
)
BY_ID = {c.id: c for c in COMPONENTS}
WING_IDS = {'MEMBRANE': 'membrane_wings', 'FIN': 'ray_fin'}   # the Full Rig's old Wing Type -> its component
STEP_IDS = ('guides', 'build', 'weights')
STEP_TITLES = ("Add Guides", "Build", "Weights")
STEP_TIPS = ("Place guide bones you drag onto the part", "Build the part's bones from the guides",
             "Skin the mesh to the part's bones")


def settings_of(cid, given=None):
    """The component's settings: the given values over the defaults (others ignored)."""
    given = given or {}
    return {i: given.get(i, SETTINGS[i].default) for i in BY_ID[cid].settings}


# ---------------------------------------------------------------- per-part helpers (shared with full_rig)
def chain_bones(kind, ear_type='SHORT', breast_bones=1):
    """Bones per chain of a chain part: the ears by their type, the breasts by their count."""
    if kind == 'breast':
        return min(max(int(breast_bones), BREAST_BONES[0]), BREAST_BONES[1])
    return EAR_BONES[ear_type] if kind == 'ear' else SEGMENTS[kind]


def is_curved(kind, breast_bones=1):
    """A part guided by three handles (Base, Mid, Tip): the CURVED kinds, and a breast of 2+ bones."""
    return kind in CURVED or (kind == 'breast' and chain_bones(kind, breast_bones=breast_bones) >= 2)


def chain_opts(kind, parent, tweaks=False, ear_type='NONE', breast_bones=1):
    """part_chains.build_chain options of a part (a breast of 2+ bones gets a Droop slider that tips it down)."""
    droop = ear_type in DROOPY if kind == 'ear' else kind == 'breast' and chain_bones(kind, breast_bones=breast_bones) >= 2
    return dict(parent=parent, tweaks=tweaks, droop=droop)


def three_points(points):
    """A part's guide as Base, Mid, Tip: three points stay, two get the midpoint between (a one-bone breast guide
    that grew to 2+ bones)."""
    return list(points) if len(points) >= 3 else [points[0], points[0].lerp(points[-1], 0.5), points[-1]]


def default_handles(kind, joints, ear_type='SHORT'):
    """Base, Mid, Tip of a curved part (guide space) on a figure (body guide joints): the tail behind the pelvis, the
    ears on the head in the shape of the Ears type (Short when None), the hair down the back of the head."""
    if kind == 'tail':
        height = joints['top'].z - joints['heel'].z
        return [joints['pelvis'] + Vector(h) * height for h in TAIL_HANDLES]
    head = (joints['top'] - joints['skull']).length
    shape = HAIR_HANDLES if kind == 'hair' else EAR_HANDLES.get(ear_type, EAR_HANDLES['SHORT'])
    return [joints['top'] + Vector(h) * head for h in shape]


def snap_handles(space, mesh, base, tip, side='', picked=None):
    """Base, Mid, Tip of a curved part (`space`'s coordinates) on `mesh` between `base` and `tip`, or None when no
    part is under that line. Mid: halfway along the part's vertices (part_chains.select_part, unless `picked`) by
    distance along the mesh."""
    picked = picked if picked is not None else line_part(space, mesh, base, tip, side)
    if len(picked) < MIN_PART_VERTS:
        return None
    to_space = space.matrix_world.inverted() @ mesh.matrix_world
    return [base.copy(), pc.middle_point(mesh, {i: to_space @ mesh.data.vertices[i].co for i in picked}, base, tip),
            tip.copy()]


def line_part(space, mesh, base, tip, side=''):
    """The mesh's vertices of the part along the line base -> tip (part_chains.select_part)."""
    return pc.select_part(space, mesh, [base.lerp(tip, k / 4) for k in range(5)], side)


def lay_handles(space, mesh, kind, near_root):
    """Base, Mid, Tip along the whole mesh (a mesh that is only this part, e.g. a separate tail), its root end the one
    nearest `near_root`; None for a mesh too small."""
    sided = pc.KINDS[kind]['sided']
    verts = pc.part_vertices(space, mesh, sided=sided)
    if len(verts) < MIN_PART_VERTS:
        return None
    return pc.lay_points(mesh, verts, 2, root=near_root)


def soft_part_points(probe, joints, kind, bones=1):
    """A breast or butt guide (left side, guide space): from inside the body out to its surface, in front of the
    chest (breast) or behind the hip (butt). Without a body `probe` it sticks out SOFT_REACH of the figure height;
    None when the probe's ray finds no surface. A breast of 2+ bones gets three points (Base, Mid, Tip) hanging a
    little, for the user to drag onto the breast's profile."""
    if kind == 'breast':
        chest, neck, shoulder = joints['chest'], joints['neck'], joints['shoulder']
        base, out = Vector((0.45 * shoulder.x, chest.y, chest.z + 0.45 * (neck.z - chest.z))), Vector((0, -1, 0))
    else:
        hip, pelvis = joints['hip'], joints['pelvis']
        base, out = Vector((hip.x, pelvis.y, hip.z - 0.25 * (joints['waist'].z - pelvis.z))), Vector((0, 1, 0))
    if probe is None:
        reach = SOFT_REACH * wr.figure_height(joints)
    else:
        reach = probe.exit_distance(base, out, 1.0) if probe.inside(base) else None
    if not reach:
        return None
    if kind == 'breast' and bones >= 2:
        hang = Vector((0, 0, -1))
        return [base + out * 0.4 * reach, base + out * 0.7 * reach + hang * 0.05 * reach,
                base + out * 0.92 * reach + hang * 0.2 * reach]
    return [base + out * 0.4 * reach, base + out * 0.92 * reach]


def freeze(shape):
    """A wing ({key: points}) or points as plain lists for a record; None stays None."""
    if shape is None:
        return None
    return {s: [vec(p) for p in pts] for s, pts in shape.items()} if isinstance(shape, dict) else [vec(p) for p in shape]


def thaw(data):
    return {s: [Vector(p) for p in pts] for s, pts in data.items()} if isinstance(data, dict) else [Vector(p) for p in data]


def vec(v):
    return [round(x, 6) for x in v]


def moved(shape, matrix):
    """A shape (points, or {key: points}) through a matrix."""
    return {s: [matrix @ p for p in pts] for s, pts in shape.items()} if isinstance(shape, dict) \
        else [matrix @ p for p in shape]


def drop_bones(rig, names):
    """Remove bones the rig no longer wants: deform weights to the first parent that stays, children re-parented."""
    if not names:
        return
    gone, heir = set(names), {}
    for n in names:
        p = rig.data.bones[n].parent
        while p is not None and p.name in gone:
            p = p.parent
        heir[n] = p.name if p is not None else rn.ROOT
    fr.merge_away({n: h for n, h in heir.items() if rig.data.bones[n].use_deform})
    for n in names:
        lr.remove_drivers(rig, lr.bone_path(n))
    with pc.sb.Kept(rig) as k:
        E = k.edit()
        for eb in E:
            if eb.name not in gone and eb.parent is not None and eb.parent.name in gone:
                eb.parent = E.get(heir[eb.parent.name])
        pc.drop_bones(E, names)
        k.done()


# ---------------------------------------------------------------- wings (shared with full_rig's old records)
def wing_weights(rig, meshes, kind, spars):
    """The wing or fin weights of built `spars` on the meshes: {mesh name: {side: vertices}}; {} when bones are gone."""
    if not spars or any(n not in rig.data.bones for chains in spars.values() for c in chains.values() for n in c):
        return {}
    if kind == 'fin':
        fan = fnr.built_fan(rig, spars['L'])
        found = lambda o: {side: list(wr.wing_vertices(rig, [o], fan, side)[1]) for side in spars}
        return {o.name: fnr.fin_weights(rig, o, dict(spars=spars), found(o)) for o in meshes}
    return {o.name: wr.wing_weights(rig, o, dict(spars=spars)) for o in meshes}


def fit_wing(kind, space, meshes, joints, probe):
    """(shape, line) of a wing type in `space`: fitted to the wing on the meshes (a 'Wings' vertex group, or grown
    from the default wing), else the default on the figure's back."""
    fin = kind == 'fin'
    default = fnr.default_fin(joints, probe) if fin else wr.default_fan(joints, probe)
    mesh, verts = wr.wing_vertices(space, meshes, fnr.outline_fan(default) if fin else default) if meshes else (None, {})
    if mesh is not None:
        shape = fnr.fit_fin(verts) if fin else wr.fit_fan(verts, wr.wing_pivot(default), wr.fan_plane(default))
        if shape is not None:
            return shape, f'wings: fitted to {mesh.name}'
    return default, 'wings: default place on the back; drag the guides onto the wing'


def write_wing_guides(kind, guides, shape):
    (fnr.write_fin_guides if kind == 'fin' else wr.write_wing_guides)(guides, shape)


def read_wing_guides(kind, guides):
    return (fnr.fin_guide_outline if kind == 'fin' else wr.wing_guide_fan)(guides)


# ---------------------------------------------------------------- face (shared with full_rig)
def face_flags(values):
    """(eye settings, maw settings) for face_rig_core from full option values (full_rig_spec.full_values); the Face
    choice says if the mouth gets the snout part."""
    cfg = spec.config_for(values)['face_rig_core']
    eye_keys, maw_keys = set(fr.FLAGS['eye']) | {'lid_mode', 'pivots', 'lid_push'}, set(fr.FLAGS['maw'])
    eye = {k: v for k, v in cfg.items() if k in eye_keys}
    eye['lid_push'] = fr.EYE['lid_push'] if eye.get('lid_push') else (0.0, 0.0)
    return eye, dict({k: v for k, v in cfg.items() if k in maw_keys}, snout=values['face'] == 'SNOUT')


def face_config(rig, kind, guides, skin, flags, head='Head', snout=''):
    """A face_rig_core config of one kind from guide points (rig space) on the skin mesh names."""
    own = dict(jaw='Jaw', upper_parent=snout) if kind == 'maw' else {}
    return fr.auto_config(rig, kind, meshes=skin, guides=guides, replace=[], head=head, **own, **flags)


def make_face_guide(rig, kind, skin, name):
    """A face_rig_core guide object of one kind, auto-placed on the rig's head (face_rig_core.auto_guides), in a fresh
    collection of its own (face_rig_core links a collection that isn't in the scene yet for its edit)."""
    coll = bpy.data.collections.new(name)
    ob = fr.make_guides(kind, collection=coll, name=name)
    next(iter(rig.users_collection), bpy.context.scene.collection).children.link(coll)
    fr.set_guides(ob, rig, fr.auto_guides(rig, kind, skin))
    return ob


# ---------------------------------------------------------------- the record
def read(rig):
    """{component id: entry} of the components on the rig (old Full Rig wings included, see legacy_wings)."""
    if rig is None or rig.type != 'ARMATURE':
        return {}
    text = rig.data.get(RECORD)
    comps = json.loads(text) if text else {}
    for cid, e in legacy_wings(rig).items():
        comps.setdefault(cid, e)
    return comps


def write(rig, comps):
    """Store the components; old Full Rig wings move out of the Full Rig's record for good."""
    rig.data[RECORD] = json.dumps(comps)
    strip_legacy_wings(rig)


def entry(rig, cid):
    return read(rig).get(cid)


def owned_bones(rig):
    """Every bone a component made."""
    return {n for e in read(rig).values() for n in e.get('bones', [])}


def owned_kinds(rig):
    """The part kinds a component owns (the Full Rig leaves those parts to the component)."""
    return {BY_ID[cid].kind for cid in read(rig) if cid in BY_ID}


def full_record(rig):
    text = rig.data.get(FULL_RIG) if rig is not None else None
    return json.loads(text) if text else None


def legacy_wings(rig):
    """Wings the Full Character Rig built before it left them to this tool, as component entries (not stored)."""
    rec = full_record(rig)
    out = {}
    for part in (rec or {}).get('parts', []):
        if part['kind'] != 'wing':
            continue
        wing_type = part.get('wing_type', 'MEMBRANE')
        fin = wing_type == 'FIN'
        values = rec.get('values', {})
        out[WING_IDS.get(wing_type, 'membrane_wings')] = dict(
            settings=dict(spokes=int(values.get('fin_spokes', fnr.SPOKES))) if fin else dict(tweaks=False),
            parent='Chest', parent_choice='', bones=part['bones'], chains=[], spars=part.get('spars'),
            shape=rec.get('fin_outline' if fin else 'wing_fan'), mesh=rec.get('part_meshes', {}).get('wing', ''),
            weighted=True, standalone=False)
    return out


def strip_legacy_wings(rig):
    rec = full_record(rig)
    if rec is None or not any(p['kind'] == 'wing' for p in rec.get('parts', [])):
        return
    rec['parts'] = [p for p in rec['parts'] if p['kind'] != 'wing']
    for key in ('wing_fan', 'fin_outline'):
        rec.pop(key, None)
    rec.get('part_meshes', {}).pop('wing', None)
    rec['values'] = spec.upgrade(rec.get('values'))
    rig.data[FULL_RIG] = json.dumps(rec)


def adopt_legacy_wings(rig):
    """Move old Full Rig wings into this record now (the Full Rig calls this before it rebuilds). Log lines."""
    found = legacy_wings(rig)
    if not found:
        return []
    write(rig, read(rig))
    return [f'{BY_ID[cid].label}: now an Add Rig Component part' for cid in found]


# ---------------------------------------------------------------- guides
def guide_objects(cid, rig_name):
    """The guide objects of a component on a rig (by tag; runs on a button, not on redraw)."""
    return [o for o in bpy.data.objects if o.get(GUIDE_OF) == cid and o.get(GUIDE_RIG, '') == rig_name]


def remove_guides(guides):
    """A guide object and its other guide objects (the Face's mouth guides) gone."""
    if guides is None:
        return
    obs = [guides] + [bpy.data.objects[n] for n in guides.get(MORE_GUIDES, []) if n in bpy.data.objects]
    for ob in obs:
        colls = [c for c in ob.users_collection if c != bpy.context.scene.collection and ob.get('face_rig_kind')]
        ot.remove_object(ob)
        for c in colls:                  # a face guide's own collection, once nothing is left in it
            if not c.objects and not c.children:
                bpy.data.collections.remove(c)


def figure_joints(space, rig=None):
    """Body landmarks in `space`'s coordinates for default places: read off the rig's bones (any names:
    body_rig.rig_joints), else the template figure."""
    if rig is not None:
        try:
            opts = br.resolve(dict(br.rig_options(rig), tail=True, ears=True))
            joints = br.rig_joints(rig, opts)
            to_space = space.matrix_world.inverted() @ rig.matrix_world
            return {k: to_space @ v if isinstance(v, Vector) else v for k, v in joints.items()}
        except (KeyError, IndexError, ValueError, AttributeError, TypeError, StopIteration, ZeroDivisionError) as err:
            print(f'rig_component: could not read the figure of {rig.name} ({err}); using the template figure')
    temp = br.make_guides(TEMP, dict(tail=True, ears=True))
    try:
        joints = br.guide_joints(temp)
    finally:
        data = temp.data
        bpy.data.objects.remove(temp)
        bpy.data.armatures.remove(data)
    return joints


def thick_end(verts):
    """The centre of the thicker end of a part's vertices ({index: co}), along its longest axis: a tail, ear or lock
    of hair is thickest at its root."""
    axis = pc.principal_axis(list(verts.values()))
    proj = {i: co.dot(axis) for i, co in verts.items()}
    lo, hi = min(proj.values()), max(proj.values())
    band = 0.15 * ((hi - lo) or 1.0)

    def end(near):
        cos = [verts[i] for i, p in proj.items() if abs(p - near) <= band]
        centre = sum(cos, Vector()) / len(cos)
        return centre, sum((c - centre - axis * (c - centre).dot(axis)).length for c in cos) / len(cos)
    (a, thick_a), (b, thick_b) = end(lo), end(hi)
    return a if thick_a >= thick_b else b


def new_guide_object(cid, rig, mesh):
    comp = BY_ID[cid]
    name = f'{rig.name} {comp.label} Guides' if rig is not None else f'{comp.label} Guides'
    ob = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    home = rig or mesh
    coll = home.users_collection[0] if home is not None and home.users_collection else bpy.context.scene.collection
    coll.objects.link(ob)
    ob.matrix_world = rig.matrix_world.copy() if rig is not None else Matrix.Identity(4)
    ob.show_in_front = True
    ob[GUIDE_OF], ob[GUIDE_RIG] = cid, rig.name if rig is not None else ''
    return ob


def place_curved(guides, kind, joints, mesh, ear_type, on_rig):
    """A tail / ear / hair guide. On a rig's mesh: snapped to the part under the default Base -> Tip line, or along
    the whole mesh when the part is most of it (root end toward the default Base). With no rig the mesh is just the
    part: along it, the root at its thicker end. Else the default handles. Log line."""
    handles = default_handles(kind, joints, ear_type)
    pts, where = None, 'default place'
    if mesh is not None:
        side = 'L' if pc.KINDS[kind]['sided'] else ''
        if on_rig:
            base, tip = handles[0], handles[-1]
            picked = line_part(guides, mesh, base, tip, side)
            share = len(picked) / max(1, len(pc.part_vertices(guides, mesh, sided=bool(side))))
            pts = snap_handles(guides, mesh, base, tip, side, picked) if share < WHOLE_SHARE else None
            root = base
        else:
            verts = pc.part_vertices(guides, mesh, sided=bool(side))
            root = thick_end(verts) if len(verts) >= MIN_PART_VERTS else None
        if pts is None and (on_rig or root is not None):   # the part is the whole mesh
            pts = lay_handles(guides, mesh, kind, root)
        where = f'on {mesh.name}' if pts else where
    pc.write_handles(guides, kind, pts or handles)
    return f'{kind}: guide placed ({where}); drag Base, Mid and Tip onto the part'


def add_guides(cid, rig=None, mesh=None, settings=None):
    """Guide bones for one component, for the user to drag: on the mesh when one is given, else at the default place
    near its parent bone (the rig's figure, or the template figure for a new armature). Returns (guide object, log
    lines). The Face's guides are face_rig_core's eye and mouth guide objects (the eye one returned)."""
    comp, o = BY_ID[cid], settings_of(cid, settings)
    if comp.kind == 'face':
        return add_face_guides(rig, mesh, o)
    guides = new_guide_object(cid, rig, mesh)
    joints = figure_joints(guides, rig)
    if comp.kind in CURVED:
        lines = [place_curved(guides, comp.kind, joints, mesh, o.get('ear_type', 'SHORT'), rig is not None)]
    elif comp.kind in ('breast', 'butt'):
        probe = br.Probe.from_objects([mesh], guides) if mesh is not None else None
        bones = chain_bones(comp.kind, breast_bones=o.get('breast_bones', 1)) if comp.kind == 'breast' else 1
        pts = soft_part_points(probe, joints, comp.kind, bones) or soft_part_points(None, joints, comp.kind, bones)
        (pc.write_handles if is_curved(comp.kind, bones) else pc.write_guides)(guides, comp.kind, pts)
        lines = [f'{comp.label.lower()}: guide placed; drag it into place']
    else:
        probe = br.Probe.from_objects([mesh], guides) if mesh is not None else None
        shape, line = fit_wing(comp.kind, guides, [mesh] if mesh is not None else [], joints, probe)
        write_wing_guides(comp.kind, guides, shape)
        lines = [line]
    return guides, lines


def add_face_guides(rig, mesh, o):
    if rig is None or rn.find(rig.data.bones.keys(), 'Head') is None:
        raise ValueError("The Face needs a rig with a Head bone: pick the rig first")
    skin = [mesh.name] if mesh is not None else []
    kinds = ('eye', 'maw') if o['mouth'] else ('eye',)
    obs = [make_face_guide(rig, kind, skin, f'{rig.name} {fr.TITLES[kind]}') for kind in kinds]
    for ob in obs:
        ob[GUIDE_OF], ob[GUIDE_RIG] = 'face', rig.name
    obs[0][MORE_GUIDES] = [ob.name for ob in obs[1:]]
    obs[0][FACE_SKIN] = skin[0] if skin else ''
    return obs[0], [f"face: {fr.TITLES[k]} guides placed on {skin[0] if skin else 'the head'}" for k in kinds]


# ---------------------------------------------------------------- build
def new_rig(cid, guides):
    """A new armature `<Component> Rig` where the guides are (standalone)."""
    name = f'{BY_ID[cid].label} Rig'
    rig = bpy.data.objects.new(name, bc.new_armature(name))
    for c in (guides.users_collection if guides is not None else None) or [bpy.context.scene.collection]:
        c.objects.link(rig)
    if guides is not None:
        rig.matrix_world = guides.matrix_world.copy()
    if guides is not None:
        guides[GUIDE_RIG] = rig.name
    return rig


def parent_of(rig, cid, choice=''):
    """The bone a component hangs on: the user's choice when the rig has it, else the standard bone by name."""
    names = rig.data.bones.keys()
    if choice and choice in names:
        return choice
    return rn.find(names, BY_ID[cid].parent)


def clash(rig, cid, comp):
    """Why the component can't go on this rig ('' = it can): the rig has the part already, not from this tool."""
    rec = full_record(rig)                # (its old wings are this tool's now: legacy_wings)
    if rec and comp.kind in {p['kind'] for p in rec.get('parts', []) if p['kind'] != 'wing'}:
        return f"{rig.name} has {comp.label.lower()} from the Full Character Rig already"
    if comp.kind == 'face':
        return f"{rig.name} has a face rig already" if fr.has_built(rig) and cid not in read(rig) else ''
    first = {'wing': wr.base_name('L'), 'fin': fnr.base_name('L')}.get(comp.kind) or \
        pc.chain_names(comp.kind, 1, 'L' if pc.KINDS[comp.kind]['sided'] else '')[0]
    mine = set((read(rig).get(cid) or {}).get('bones', []))
    return f"{rig.name} has a {first} bone already" if first in rig.data.bones and first not in mine else ''


def guide_shape(comp, guides, rig, old):
    """The shape to build in rig space: read from the guides, else the last build's."""
    shape = None
    if guides is not None:
        if comp.kind in CURVED:
            shape = pc.handle_points(guides, comp.kind)
        elif comp.kind in ('breast', 'butt'):
            shape = pc.handle_points(guides, comp.kind) or pc.guide_points(guides, comp.kind)
        else:
            shape = read_wing_guides(comp.kind, guides)
        if shape is not None:
            shape = moved(shape, rig.matrix_world.inverted() @ guides.matrix_world)
    if shape is None and old and old.get('shape'):
        shape = thaw(old['shape'])
    if shape is None:
        raise ValueError("Add Guides first")
    return shape


def build_part(rig, comp, shape, parent, o):
    """Build one non-face part from its shape. Returns the builder's report ('bones', 'chains' / 'spars')."""
    if comp.kind == 'wing':
        return wr.build_wings(rig, shape, dict(parent=parent, tweaks=o.get('tweaks', False)))
    if comp.kind == 'fin':
        return fnr.build_fin(rig, shape, dict(parent=parent, spokes=o['spokes']))
    ear_type = o.get('ear_type', 'SHORT')
    count = chain_bones(comp.kind, ear_type, o.get('breast_bones', 1))
    if comp.kind == 'breast' and count >= 2:                 # a guide of the one-bone days has two points
        shape = three_points(shape)
    pts = pc.curve_joints(shape, count) if comp.kind in CURVED or (comp.kind == 'breast' and len(shape) == 3) else shape
    return pc.build_chain(rig, comp.kind, pts, chain_opts(comp.kind, parent, o.get('tweaks', False), ear_type, count))


def build(cid, rig=None, guides=None, settings=None, parent_choice=''):
    """Build (or rebuild) one component: into `rig` on its parent bone, or (rig None) into a new armature
    `<Component> Rig`. From the guides (else the last build's guides, else the shape it was built from). Bones it no longer makes go; a part that
    had weights is weighed again. Returns (rig, log lines)."""
    comp, o = BY_ID[cid], settings_of(cid, settings)
    if rig is None and comp.kind == 'face':
        raise ValueError("The Face needs a rig with a Head bone: pick the rig first")
    if rig is not None:
        why = clash(rig, cid, comp)
        if why:
            raise ValueError(why)
    standalone = rig is None
    rig = rig or new_rig(cid, guides)
    old = read(rig).get(cid) or {}
    guides = guides or bpy.data.objects.get(old.get('guides', ''))     # a rebuild (the Full Rig's) finds its guides
    if rig.mode != 'OBJECT':
        lr.set_mode(rig, 'OBJECT')
    parent = parent_of(rig, cid, parent_choice)
    if comp.kind == 'face':
        rep, lines = build_face(rig, guides, o, old, parent)
        shape = None
    else:
        shape = guide_shape(comp, guides, rig, old)
        rep = build_part(rig, comp, shape, parent, o)
        lines = [f"{cid}: {len(rep['bones'])} bones" + (f' on {parent}' if parent else '')]
    made = set(rep['bones'])
    drop_bones(rig, sorted(n for n in old.get('bones', []) if n not in made and n in rig.data.bones))
    if comp.kind == 'wing':
        wr.remove_leftovers(rig)
    comps = read(rig)
    comps[cid] = dict(settings=o, parent=parent or '', parent_choice=parent_choice, bones=sorted(made),
                      chains=[c for c in rep.get('chains', {}).values()], spars=rep.get('spars'), shape=freeze(shape),
                      guides=guides.name if guides is not None else '', mesh=old.get('mesh') or rep.get('mesh', ''), weighted=old.get('weighted', False) and comp.weights,
                      standalone=old.get('standalone', standalone))
    write(rig, comps)
    mesh = bpy.data.objects.get(comps[cid]['mesh'])
    if comps[cid]['weighted'] and mesh is not None:
        lines += weigh(cid, rig, mesh)
    fr.finish_rig(rig)
    bc.hide_rigging(rig)
    return rig, lines


def build_face(rig, guides, o, old, head):
    """The Eye Rig (+ the Anthro Mouth Rig) on the rig's Head from the face guides (else the last build's stored
    configs). Its weights come from the Head's on the skin (face_rig_core). Returns (report, log lines)."""
    if head is None:
        raise ValueError("The Face needs a rig with a Head bone")
    obs = [guides] + [bpy.data.objects[n] for n in guides.get(MORE_GUIDES, []) if n in bpy.data.objects] \
        if guides is not None else []
    from_obs = {ob['face_rig_kind']: fr.guides_from_object(ob, rig) for ob in obs if ob.get('face_rig_kind')}
    stored = {kind: fr.stored(rig, kind) for kind in ('eye', 'maw')}
    if fr.has_built(rig):
        fr.remove(rig, log=lambda *a: None)
    eye_flags, maw_flags = face_flags(spec.full_values(dict(face=o['face'])))
    skin = [n for n in [old.get('mesh') or (guides.get(FACE_SKIN, '') if guides is not None else '')]
            if n in bpy.data.objects]
    snout = 'Snout' if o['face'] == 'SNOUT' and 'Snout' in rig.data.bones else ''
    configs = []
    for kind, flags in (('eye', eye_flags), ('maw', maw_flags)):
        points = from_obs.get(kind) or (stored[kind] or {}).get('guides') if (kind == 'eye' or o['mouth']) else None
        configs.append(face_config(rig, kind, points, skin, flags, head, snout) if points else None)
    if not any(configs):
        raise ValueError("Add Guides first")
    notes = []
    keep = lambda *a: notes.append(' '.join(str(x) for x in a)) if 'WARNING' in str(a[0]) else None
    fr.build(rig, *configs, log=keep)
    made = fr.built_info(rig).get('made', [])
    kinds = ' + '.join(fr.TITLES[c['kind']] for c in configs if c)
    return dict(bones=made, mesh=skin[0] if skin else ''), [f'face: {kinds}, {len(made)} bones'] + \
        [f"face: {n.replace('M# ', '')}" for n in notes]


# ---------------------------------------------------------------- weights
def weigh(cid, rig, mesh):
    """Skin weights for one component on `mesh` (blended over the weights it has, e.g. the body's); the mesh goes on
    the rig (parented, Armature modifier) when it isn't yet. Returns log lines."""
    comps = read(rig)
    e, comp = comps.get(cid), BY_ID[cid]
    if e is None:
        raise ValueError("Build first")
    if not comp.weights:
        return [f'{comp.label}: its weights come with Build']
    if full_record(rig):                 # on a Full Rig: the mesh's before-state is kept, so its Remove puts it back
        full_rig_module().take_meshes(rig, [mesh])
    else:
        rw.attach(mesh, rig)
    if comp.kind in ('wing', 'fin'):
        done = wing_weights(rig, [mesh], comp.kind, e.get('spars')).get(mesh.name, {})
        count = sum(v if isinstance(v, int) else len(v) for v in done.values())
    else:
        whole = e.get('standalone')      # a part's own rig: its mesh is just the part, every vertex goes on it
        done = rw.weigh_chains(rig, [mesh], [dict(bones=c, mesh=mesh.name, vertices=whole_side(rig, mesh, c) if whole else None)
                                             for c in e['chains'] if all(n in rig.data.bones for n in c)])
        count = sum(done.values())
    e.update(mesh=mesh.name, weighted=True)
    write(rig, comps)
    return [f'{cid}: {count} vertices weighted on {mesh.name}']


def whole_side(rig, mesh, chain):
    """Every vertex of the mesh on the chain's side (all of them for a centre chain)."""
    side = rn.side_of(chain[0])
    if not side:
        return list(range(len(mesh.data.vertices)))
    to_rig = rig.matrix_world.inverted() @ mesh.matrix_world
    return [v.index for v in mesh.data.vertices if ((to_rig @ v.co).x > 0) == (side == 'L')]


def weigh_components(rig, meshes):
    """The Full Rig's weigh step (rig_weights.weigh_all `parts`): every weighed component again on its mesh, after the
    body weights cleared the rig's groups. Returns {component id: log lines}."""
    out = {}
    for cid, e in read(rig).items():
        mesh = bpy.data.objects.get(e.get('mesh', ''))
        if cid in BY_ID and BY_ID[cid].weights and e.get('weighted') and mesh is not None:
            out[cid] = weigh(cid, rig, mesh)
    return out


# ---------------------------------------------------------------- remove
def homes_of(rig, names):
    """The bone collections the bones are in (to tidy the ones left empty)."""
    return {c.name for n in names if n in rig.data.bones for c in rig.data.bones[n].collections}


def drop_empty_collections(rig, names):
    """The collections of `names` that hold no bones and no children any more go, then their parents the same way."""
    todo = list(names)
    while todo:
        coll = rig.data.collections_all.get(todo.pop())
        if coll is None or coll.bones or coll.children:
            continue
        parent = coll.parent
        rig.data.collections.remove(coll)
        if parent is not None:
            todo.append(parent.name)


def release_mesh(mesh, rig):
    """A mesh off a standalone component rig: its Armature modifier and the rig's bone groups go, unparented where it
    stands."""
    for m in [m for m in mesh.modifiers if m.type == 'ARMATURE' and m.object == rig]:
        mesh.modifiers.remove(m)
    for g in [g for g in mesh.vertex_groups if g.name in rig.data.bones]:
        mesh.vertex_groups.remove(g)
    if mesh.parent == rig:
        world = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = world


def remove(cid, rig):
    """Take one component off the rig; nothing else on the rig changes. Its deform weights go to the bone it hung on,
    its guides go. A standalone component rig goes with its last component (its meshes let go). Returns (the rig, or
    None when it went, log lines)."""
    comps = read(rig)
    e = comps.get(cid)
    if e is None:
        raise ValueError(f'{rig.name} has no {BY_ID[cid].label.lower()} from Add Rig Component')
    if rig.mode != 'OBJECT':
        lr.set_mode(rig, 'OBJECT')
    for guides in guide_objects(cid, rig.name):
        if guides.name in bpy.data.objects:
            remove_guides(guides)
    del comps[cid]
    if e.get('standalone') and not comps:
        for mesh in [o for o in bpy.data.objects if o.type == 'MESH' and (o.parent == rig or any(
                m.type == 'ARMATURE' and m.object == rig for m in o.modifiers))]:
            release_mesh(mesh, rig)
        ot.remove_object(rig)
        return None, [f'{BY_ID[cid].label}: removed with its rig']
    if BY_ID[cid].kind == 'face':
        remove_face(rig)
    else:
        names = [n for n in e.get('bones', []) if n in rig.data.bones]
        homes = homes_of(rig, names)
        drop_bones(rig, names)
        if BY_ID[cid].kind == 'wing':
            wr.remove_leftovers(rig)
        drop_empty_collections(rig, homes)
    write(rig, comps)
    bc.hide_rigging(rig)
    return rig, [f'{BY_ID[cid].label}: removed, the rest of {rig.name} kept']


def remove_face(rig):
    """The face rig off; on a Full Rig body the body bones the face took over (its Snout) come back (full_rig.face_off)."""
    if full_record(rig):
        full_rig_module().face_off(rig)
    else:
        fr.remove(rig, log=lambda *a: None)


def full_rig_module():
    """full_rig, imported when needed (it imports this module)."""
    try:
        from . import full_rig as full
    except ImportError:
        import full_rig as full
    return full


def remove_all_guides(rig_name):
    """Every component guide object of a rig (the Full Rig's Remove takes them along)."""
    for ob in [o for o in bpy.data.objects if o.get(GUIDE_OF) and o.get(GUIDE_RIG) == rig_name]:
        if ob.name in bpy.data.objects:
            remove_guides(ob)


# ---------------------------------------------------------------- card support
def step_states(cid, guides, rig, settings=None):
    """[(step id, state, stale)] for the card, no scans: state 'done', 'next', 'later' or 'off' (Weights of the Face);
    stale = built with other settings than now."""
    e = read(rig).get(cid) if rig is not None else None
    done = dict(guides=guides is not None or e is not None, build=e is not None, weights=bool(e and e.get('weighted')))
    out, nxt = [], False
    for step in STEP_IDS:
        if step == 'weights' and not BY_ID[cid].weights:
            out.append((step, 'off', False))
        elif done[step]:
            stale = step == 'build' and settings is not None and e.get('settings') != settings_of(cid, settings)
            out.append((step, 'done', stale))
        else:
            out.append((step, 'later' if nxt else 'next', False))
            nxt = True
    return out
