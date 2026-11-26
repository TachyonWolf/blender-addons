# SPDX-License-Identifier: GPL-3.0-or-later
"""Face Rig settings and operators: add, place, configure, build, rebuild and remove the Eye Rig and Anthro Mouth Rig on a
character. The card is gone (the Full Character Rig card has Rebuild Face for existing rigs); `character()` is shared.

Settings live on the character's armature object (`Object.digit_face_rig`); the guides are the "Eye Rig" /
"Anthro Mouth Rig" assets (guide armatures, appended from the asset library file FaceRigs.blend, else made by
face_rig_core.make_guides), parented to the character's armature. All rig logic is in face_rig_core.
"""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, PointerProperty, StringProperty)

from . import face_rig_core as core, rig_names as rn  # generated copy
from .character_link import find_layer_collection  # generated copy
from .modifier_setup import library_file  # generated copy
from .object_tools import ensure_object_mode as ensure_object_mode_shared, remove_object  # generated copy

LIBRARY_FILE = "FaceRigs.blend"
TITLES = core.TITLES
KINDS = [(k, t, "") for k, t in TITLES.items()]
E, M = core.EYE, core.MAW


def is_mesh(_self, ob):
    return ob.type == 'MESH'


class DIGITOOLS_PG_mesh(bpy.types.PropertyGroup):
    object: PointerProperty(type=bpy.types.Object, poll=is_mesh)


class DIGITOOLS_PG_face_rig(bpy.types.PropertyGroup):
    # common
    meshes: CollectionProperty(type=DIGITOOLS_PG_mesh, description="Skin meshes: the first is the weight source, "
                               "the others get its head weights (identical heads, like Body / Body Mesh)")
    skin_parts: CollectionProperty(type=DIGITOOLS_PG_mesh, description="Meshes on the skin (face paint, blush, "
                                   "separate brows) that take the skin's new weights")
    head: StringProperty(name="Head", default="Head", description="Head bone")
    weights: BoolProperty(name="Build Weights", default=True,
                          description="Re-weight the lids, lips and socket on the meshes (off: bones and drivers only)")
    mirror: BoolProperty(name="Mirror", default=True,
                         description="The right side mirrors the left guides (off: Right… guides place the right side; "
                                     "Add / Re-place the guides after changing it)")
    size: FloatProperty(name="Size", default=1.0, min=0.05, soft_max=5,
                        description="Scale of weight falloffs, bone and shape sizes (1 = Digit; set from the eye width)")
    upper_color: FloatVectorProperty(name="Upper", subtype='COLOR', min=0, max=1, default=core.UPPER_COLOR)
    lower_color: FloatVectorProperty(name="Lower", subtype='COLOR', min=0, max=1, default=core.LOWER_COLOR)
    # eye
    eye_bone: StringProperty(name="Eye Bone", default=E['eye_bone'], description="Left eye bone (made if missing)")
    pivots: IntProperty(name="Lid Pivots", default=E['pivots'], min=6, max=22, step=2,
                        description="Lid pivots per eye: two corners plus half upper, half lower (even)")
    look_follow: FloatVectorProperty(name="Look Follow", size=3, default=E['look_follow'], min=0, max=1,
                                     description="How much the upper lid, lower lid and corners follow the eye look")
    lid_mode: EnumProperty(name="Lid Deformation", default='PIVOTS', items=[
        ('PIVOTS', "Pivots", "The lid pivots deform the lids: the smoothest closed lid (recommended)"),
        ('RING', "Ring (experimental)", "A closed B-bone ring per eye through the pivots' tips deforms the lids "
                 "(the pivots still drive it, but stop deforming); liners stay rigid on the ring")])
    ring_reach: FloatProperty(name="Ring Reach (mm)", default=E['ring_reach'], min=0.5, soft_max=60,
                              description="Ring: how far from the lid edge the ring still takes half of the lid weight "
                                          "(none from twice that; mm at size 1). Smaller = only the lid edge follows the ring")
    sharp_corners: BoolProperty(name="Sharp Corners", default=E['sharp_corners'],
                                description="Ring: a real corner at the inner / outer eye corner (a ring "
                                            "smooth all the way round bulges there when shut)")
    brow_push: FloatProperty(name="Brow Push", default=E['brow_push'], min=0, max=1,
                             description="The upper lid moves down by this share of the brow's drop")
    lid_twist: BoolProperty(name="Lid Twist", default=E['lid_twist'],
                            description="Twisting a lid tweak (R from the front) turns that part of the lid round it")
    lid_push: FloatVectorProperty(name="Lid Push", size=2, default=E['lid_push'], min=0, soft_max=0.3,
                                  description="The lid pivots stretch forward by this share as the upper lid closes "
                                              "(keeps the shut lid off the eyeball): all pivots, the pair by the inner corner")
    brows: BoolProperty(name="Brows", default=True, description="Brow master + Inner / Mid / Outer controls")
    lashes: BoolProperty(name="Lashes", default=True, description="Lash sets (one control each) on the lash mesh")
    lash_mesh: PointerProperty(type=bpy.types.Object, poll=is_mesh, name="Lash Mesh",
                               description="Liners + lashes mesh (lashes are its small loose parts on the lid)")
    lash_swing: FloatProperty(name="Lash Swing", default=E['lash_swing'], soft_min=-120, soft_max=60,
                              description="Upper lash swing when the eye is shut (degrees)")
    lash_start: FloatProperty(name="Lash Start", default=E['lash_start'], min=0, max=0.95,
                              description="Lashes start swinging once the eye is this far shut")
    eye_replace: StringProperty(name="Replace", description="Old lid bones to remove (name starts, Left/Right "
                                "left out, comma separated); their weights go to their parent")
    # maw
    jaw: StringProperty(name="Jaw", default=M['jaw'], description="Jaw bone (made from the Jaw guide if missing)")
    upper_parent: StringProperty(name="Upper Lip Parent", description="Bone the upper lip hangs on (empty: head)")
    lower_parent: StringProperty(name="Lower Lip Parent", description="Bone the lower lip hangs on (empty: jaw)")
    corner_parent: StringProperty(name="Corner Parent", description="Mouth corner rest parent (empty: upper lip parent)")
    corner_jaw_follow: FloatProperty(name="Corner Jaw Follow", default=M['corner_jaw_follow'], min=0, max=1,
                                     description="How much the mouth corners follow the jaw")
    corner_pull: FloatVectorProperty(name="Corner Pull", size=2, default=M['corner_pull'], min=0, max=1,
                                     description="How much the upper / lower lip middles follow the mouth corner")
    keep_weights: BoolProperty(name="Rebuild Keeps Weights", default=True,
                               description="Rebuild puts every skin weight back as it was, painted ones too; off: fresh weights along the lid and lip loops")
    corner_lower_lift: FloatProperty(name="Lower Lip Lift", default=M['corner_lower_lift'], min=0, max=1,
                                     description="How much of a mouth corner's lift the lower lip follows "
                                                 "(low: smiles raise the corners without pushing the lower lip into the teeth)")
    smile_back: FloatProperty(name="Cheek Lift Back", default=M['smile_back'], min=0, max=2,
                              description="How far the smile cheek slides back along the skin, per unit of corner lift")
    corner_reach: FloatProperty(name="Corner Slide Reach", default=M['corner_reach'], min=0, max=1,
                                description="How far a mouth corner's Corner Slide goes, as a share of the lip length")
    maw_squash: FloatProperty(name="Wide Jaw Squash", default=M['maw_squash'], min=0, max=1,
                              description="How far Maw Stretch draws the corners in on a wide jaw, as a share of the lip length")
    maw_cheek: FloatProperty(name="Wide Jaw Cheek", default=M['maw_cheek'], min=0, max=0.1, unit='LENGTH',
                             description="How far Maw Stretch bunches the cheeks on a wide jaw (x Size)")
    maw_replace: StringProperty(name="Replace", description="Old lip bones to remove (name starts, Left/Right "
                                "left out, comma separated); their weights go to their parent")


# ---------------------------------------------------------------- character, guides, settings <-> config
def character(context):
    """The character's armature: the active armature (or a guide's parent), or the armature of the active mesh."""
    ob = context.active_object
    if ob is None:
        return None
    if ob.get('face_rig_kind') and ob.parent and ob.parent.type == 'ARMATURE':
        return ob.parent
    if ob.type == 'ARMATURE':
        return ob
    mod = next((m for m in ob.modifiers if m.type == 'ARMATURE' and m.object), None) if ob.type == 'MESH' else None
    return mod.object if mod else (ob.parent if ob.parent and ob.parent.type == 'ARMATURE' else None)


def guide_of(arm, kind):
    return next((o for o in arm.children if o.get('face_rig_kind') == kind), None)


def names(items):
    return [i.object.name for i in items if i.object]


def split(text):
    return [t.strip() for t in text.split(",") if t.strip()]


def config_for(arm, kind):
    s = arm.digit_face_rig
    common = dict(head=s.head, meshes=names(s.meshes), skin_parts=names(s.skin_parts), weights=s.weights,
                  mirror=s.mirror, size=s.size, colors=(tuple(s.upper_color), tuple(s.lower_color)))
    g = guide_of(arm, kind)
    guides = core.guides_from_object(g, arm) if g else {}
    if kind == 'eye':
        return core.config('eye', guides=guides, **common, eye_bone=s.eye_bone, pivots=s.pivots,
                           look_follow=tuple(s.look_follow), brow_push=s.brow_push, brows=s.brows, lid_mode=s.lid_mode,
                           ring_reach=s.ring_reach, sharp_corners=s.sharp_corners,
                           lid_twist=s.lid_twist, lid_push=tuple(s.lid_push),
                           lashes=s.lashes and s.lash_mesh is not None, lash_mesh=s.lash_mesh.name if s.lash_mesh else '',
                           lash_swing=s.lash_swing, lash_start=s.lash_start, replace=split(s.eye_replace))
    return core.config('maw', guides=guides, **common, jaw=s.jaw, upper_parent=s.upper_parent,
                       lower_parent=s.lower_parent, corner_parent=s.corner_parent,
                       corner_jaw_follow=s.corner_jaw_follow, corner_pull=tuple(s.corner_pull), corner_lower_lift=s.corner_lower_lift,
                       smile_back=s.smile_back, corner_reach=s.corner_reach,
                       maw_squash=s.maw_squash, maw_cheek=s.maw_cheek, replace=split(s.maw_replace),
                       tongue=(core.stored(arm, 'maw') or {}).get('tongue', []))


def fill_list(items, mesh_names):
    items.clear()
    for n in mesh_names:
        ob = bpy.data.objects.get(n)
        if ob:
            items.add().object = ob


def settings_from(arm, cfg):
    """Auto-guessed config -> the armature's settings (first Add fills the common ones)."""
    s = arm.digit_face_rig
    if not s.meshes:
        fill_list(s.meshes, cfg['meshes'])
        s.head, s.size = cfg['head'], cfg['size']
    if cfg['kind'] == 'eye':
        s.eye_bone = cfg['eye_bone']
        s.eye_replace = ", ".join(cfg['replace'])
        if cfg['lash_mesh'] and s.lash_mesh is None:
            s.lash_mesh = bpy.data.objects.get(cfg['lash_mesh'])
    else:
        s.jaw = cfg['jaw']
        s.maw_replace = ", ".join(cfg['replace'])


def add_guides(context, arm, kind):
    """The kind's guide armature (asset from FaceRigs.blend, else built), parented to the character."""
    title = TITLES[kind]
    mirrored = arm.digit_face_rig.mirror
    path = library_file(LIBRARY_FILE) if mirrored else None      # the asset has left guides only
    coll = None
    if path:
        with bpy.data.libraries.load(path, link=False) as (_src, dst):
            dst.collections = [title]
        coll = dst.collections[0] if dst.collections and dst.collections[0] else None
        if coll is not None:
            coll.asset_clear()     # else the guides show up as an asset of the character's library
    if coll is None:
        coll = bpy.data.collections.new(title)
        core.make_guides(kind, mirrored, collection=coll)
    coll.name = f"{title} Guides ({arm.name})"
    home = arm.users_collection[0] if arm.users_collection else context.scene.collection
    home.children.link(coll)
    for child in coll.children:            # the control shapes stay out of view
        lc = find_layer_collection(context.view_layer.layer_collection, child)
        if lc:
            lc.exclude = True
    guide = next(o for o in coll.objects if o.get('face_rig_kind') == kind)
    guide.parent = arm
    guide.matrix_parent_inverse = arm.matrix_world.inverted()
    return guide


def remove_guides(arm, kind):
    g = guide_of(arm, kind)
    if g is None:
        return
    colls = list(g.users_collection)
    remove_object(g)
    for c in colls:
        if c.name.startswith((TITLES[kind], "Anthro Snout Rig", "Maw Rig")):     # guides added before the renames too
            for child in list(c.children):
                c.children.unlink(child)
            if not c.objects:
                bpy.data.collections.remove(c)


def ensure_object_mode(context, arm):
    ensure_object_mode_shared(context)
    arm.hide_set(False)
    context.view_layer.objects.active = arm


def build_configs(arm):
    return [config_for(arm, k) if guide_of(arm, k) else None for k in ('eye', 'maw')]


# ---------------------------------------------------------------- operators
class DIGITOOLS_OT_face_rig_add(bpy.types.Operator):
    """Append the rig's guides onto the selected character, placed from its bones and meshes as well as
    possible. Then drag the guide bones in Edit Mode, check the settings and Build"""
    bl_idname = "digits_assorted_tools.face_rig_add"
    bl_label = "Add Face Rig Guides"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(items=KINDS)

    @classmethod
    def poll(cls, context):
        return character(context) is not None

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context, arm)
        s = arm.digit_face_rig
        meshes = names(s.meshes) or None
        cfg = core.auto_config(arm, self.kind, meshes)
        settings_from(arm, cfg)
        remove_guides(arm, self.kind)
        guide = add_guides(context, arm, self.kind)
        core.set_guides(guide, arm, cfg['guides'])
        for ob in context.selected_objects:
            ob.select_set(False)
        guide.select_set(True)
        context.view_layer.objects.active = guide
        self.report({'INFO'}, f"{TITLES[self.kind]} guides placed (size {cfg['size']}); drag them in Edit Mode, then Build")
        return {'FINISHED'}


class DIGITOOLS_OT_face_rig_build(bpy.types.Operator):
    """Build the Eye Rig and / or Anthro Mouth Rig from their guides and settings (Rebuild keeps your control poses)"""
    bl_idname = "digits_assorted_tools.face_rig_build"
    bl_label = "Build Face Rig"
    bl_options = {'REGISTER', 'UNDO'}

    rebuild: BoolProperty(name="Rebuild", default=False)

    @classmethod
    def poll(cls, context):
        arm = character(context)
        return arm is not None and ((guide_of(arm, 'eye') or guide_of(arm, 'maw')) is not None or core.has_built(arm))

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context, arm)
        guided = guide_of(arm, 'eye') or guide_of(arm, 'maw')
        eye, maw = build_configs(arm) if guided else (None, None)
        lines = []
        try:
            if not guided or (self.rebuild and arm.data.get('face_rig_built')):
                rep = core.rebuild(arm, eye, maw, log=lambda *a: lines.append(" ".join(map(str, a))),
                                   keep_weights=arm.digit_face_rig.keep_weights)
            else:
                if arm.data.get('face_rig_built'):
                    core.remove(arm, log=lambda *a: None)
                rep = core.build(arm, eye, maw, log=lambda *a: lines.append(" ".join(map(str, a))))
        except (ValueError, KeyError) as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        for kind in ('eye', 'maw'):
            g = guide_of(arm, kind)
            if g:
                g.hide_set(True)
        notes = [l[3:] for l in lines if l.startswith('M# note') or 'no edge loop' in l]
        self.report({'WARNING'} if notes else {'INFO'},
                    f"Face rig built: {len(rep['made'])} bones, {len(rep['removed'])} old ones replaced"
                    + (". " + "; ".join(notes) if notes else ""))
        return {'FINISHED'}


class DIGITOOLS_OT_face_rig_remove(bpy.types.Operator):
    """Take the built face rig out (its weights go back to the bones it hung on); the guides stay"""
    bl_idname = "digits_assorted_tools.face_rig_remove"
    bl_label = "Remove Face Rig"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = character(context)
        return arm is not None and bool(arm.data.get('face_rig_built'))

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context, arm)
        gone = core.remove(arm, log=lambda *a: None)
        for kind in ('eye', 'maw'):
            g = guide_of(arm, kind)
            if g:
                g.hide_set(False)
        self.report({'INFO'}, f"Removed {len(gone)} face rig bones (old bones it replaced are not restored: use Undo)")
        return {'FINISHED'}


class DIGITOOLS_OT_face_rig_lids(bpy.types.Operator):
    """Apply Lid Twist and Lid Push to the built Eye Rig in place: no rebuild, weights and hand fixes stay"""
    bl_idname = "digits_assorted_tools.face_rig_lids"
    bl_label = "Update Lid Twist + Push"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = character(context)
        return arm is not None and core.has_built(arm)

    def execute(self, context):
        arm = character(context)
        s = arm.digit_face_rig
        cfg = dict(core.stored(arm, 'eye') or core.config('eye'), lid_twist=s.lid_twist, lid_push=tuple(s.lid_push))
        out = core.lid_extras(arm, cfg, log=lambda *a: None)
        if arm.data.get('face_rig_eye'):
            arm.data['face_rig_eye'] = core.to_json(cfg)
        self.report({'INFO'}, f"Lid twist on {len(out['twist'])} pivots, push on {len(out['push'])}")
        return {'FINISHED'}


class DIGITOOLS_OT_face_rig_select(bpy.types.Operator):
    """Select this face control (Pose Mode, made active)"""
    bl_idname = "digits_assorted_tools.face_rig_select"
    bl_label = "Select Face Control"
    bl_options = {'REGISTER', 'UNDO'}

    which: StringProperty(name="Control", description="Quick-select entry (face_rig_core.QUICK_SELECT)")

    @classmethod
    def poll(cls, context):
        return character(context) is not None

    def execute(self, context):
        arm = character(context)
        here = arm.data.bones.keys()                   # a rig with old names reads them
        names = [rn.find(here, n) for n in dict(core.QUICK_SELECT).get(self.which, []) if rn.find(here, n)]
        if not names:
            self.report({'WARNING'}, f"No {self.which} control on {arm.name} (build the face rig first)")
            return {'CANCELLED'}
        if context.mode != 'POSE' or context.active_object is not arm:
            ensure_object_mode(context, arm)
            context.view_layer.objects.active = arm
            arm.select_set(True)
            bpy.ops.object.mode_set(mode='POSE')
        for pb in arm.pose.bones:
            pb.select = False
        for n in names:
            arm.pose.bones[n].select = True
            arm.data.bones[n].hide = False
        arm.data.bones.active = arm.data.bones[names[0]]
        return {'FINISHED'}


class DIGITOOLS_OT_face_rig_fix_eyes(bpy.types.Operator):
    """Put the eye controls right on a built face rig, in place: socket, iris and pupil rings centred on the pupil axis, lid controls on the lid edge. The skin does not change"""
    bl_idname = "digits_assorted_tools.face_rig_fix_eyes"
    bl_label = "Fix Eye Controls"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        arm = character(context)
        return arm is not None and core.stored(arm, 'eye') is not None

    def execute(self, context):
        arm = character(context)
        ensure_object_mode(context, arm)
        try:
            done = core.fix_eye_controls(arm, log=lambda *a: None)
        except (ValueError, KeyError) as err:
            self.report({'ERROR'}, str(err))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Eye controls fixed: {len(done)} bones")
        return {'FINISHED'}


classes = (DIGITOOLS_PG_mesh, DIGITOOLS_PG_face_rig, DIGITOOLS_OT_face_rig_add, DIGITOOLS_OT_face_rig_build,
           DIGITOOLS_OT_face_rig_remove, DIGITOOLS_OT_face_rig_select, DIGITOOLS_OT_face_rig_lids,
           DIGITOOLS_OT_face_rig_fix_eyes)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.digit_face_rig = PointerProperty(type=DIGITOOLS_PG_face_rig)


def unregister():
    del bpy.types.Object.digit_face_rig
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
