# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/bone_collections.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
"""Bone Collections: sorts every armature in a character file into one shared bone collection layout.

The main rig and its part rigs (ears, hair, beards, tails, wings: armatures parented to the main rig)
use the same collection names, so joining parts into the main rig (Combine Multi Part Model) merges
them into its collections instead of leaving a mess. A collection holds the bones you actually pose.
Bones that constraints drive fully (IK chains, copy-rotation followers) live only in Deform, or in
Mechanism when they don't deform.

Works on docs/BONE_NAMES.md names and the old styles (rig_names reads them all), and reads the rig's old collections ("Main controls", "IK", "Face", "Helpers", "Layer 4"...)
as hints. Safe to re-run: it reads both the original and the already-converted collection names.

Run: blender -b <file> --python bone_collections.py            (dry run, prints the plan)
     blender -b <file> --python bone_collections.py -- --apply (rebuilds collections, saves)
"""
import json
import re
import sys

import bpy

try:                                     # inside the add-on package
    from . import rig_names as rn
except ImportError:                      # Scripts/batch_tools copy
    import rig_names as rn

# (parent collection, collection, bone color), the layout in docs/BONE_NAMES.md. Created in this order, only when bones
# land in them or under them.
LAYOUT = [
    (None, "Body", None), ("Body", "Torso", "THEME09"),
    ("Body", "IK Left Arm", "THEME01"), ("Body", "IK Right Arm", "THEME01"),
    ("Body", "IK Left Leg", "THEME01"), ("Body", "IK Right Leg", "THEME01"),
    ("Body", "Limb Tweak", "THEME04"), ("Body", "Fingers & Toes", "THEME08"), ("Fingers & Toes", "Finger Tweak", "THEME04"),
    ("Body", "Tail", "THEME01"), ("Tail", "Tail Tweak", "THEME04"), ("Body", "Body Non-Standard", "THEME04"),
    (None, "Face", None), ("Face", "Look", "THEME11"), ("Face", "Eyes", "THEME06"), ("Face", "Brows", "THEME06"),
    ("Face", "Mouth", "THEME06"), ("Face", "Cheeks", "THEME06"),
    ("Face", "Ears", "THEME06"), ("Ears", "Ear Tweak", "THEME04"),
    ("Face", "Hair", "THEME06"), ("Hair", "Hair Tweak", "THEME04"),
    ("Face", "Face Tweak", "THEME04"), ("Face", "Face Non-Standard", "THEME04"),
    (None, "Extras", None), ("Extras", "Wings", "THEME02"), ("Wings", "Wing Tweak", "THEME04"),
    ("Extras", "Extras Tweak", "THEME04"), ("Extras", "Breasts", "THEME02"), ("Extras", "Groin", "THEME02"), ("Extras", "Extras Non-Standard", "THEME04"),
    (None, "Adjustment", "THEME04"),
    (None, "Rigging", None), ("Rigging", "Deform", None), ("Deform", "Body Deform", None),
    ("Deform", "Face Deform", None), ("Rigging", "Mechanism", None),
    (None, "Unsorted", None),
]
PARENT = {name: parent for parent, name, _ in LAYOUT}
NON_STANDARD = ("Body Non-Standard", "Face Non-Standard", "Extras Non-Standard")   # never made by default: rigs that add such bones
HIDDEN = {name for name in PARENT if name.endswith("Tweak")} | set(NON_STANDARD) | {"Adjustment", "Rigging"}
# Upper vs lower face parts get two face shades (custom pose bone colours), so the upper jaw / lip / lid / lashes
# and the lower ones are easy to tell apart. Matched on rn.plain() names; anything else keeps its collection colour.
FACE_SPLIT = [
    (r"^muzzle\d*$|upperlip|upperteeth|upperlid|upperlash", (0.95, 0.50, 0.90)),            # upper: light pink-purple
    (r"jaw|lowerlip|lowerteeth|tongue|tounge|lowerlid|lowerlash", (0.25, 0.80, 0.85)),  # lower: teal
]
COLOR = {name: color for _, name, color in LAYOUT}
FK_COLOR = "THEME03"
LIMB_TWEAK = r"(upperarm|forearm|thigh|shin|hock)"   # bendy limb tweaks (bendy_limbs), on rn.plain names
TWEAK_OF = {"Ears": "Ear Tweak", "Hair": "Hair Tweak", "Tail": "Tail Tweak", "Wings": "Wing Tweak"}

# Old or converted collection names (lower case) and what they say about a bone
DEFORM_SETS = {"deform", "body deform", "face deform"}
MECHANISM_SETS = {"mechanism", "wingmechanism"}
HELPER_SETS = {"helpers", "bending", "face tweak", "ear tweak", "hair tweak", "tail tweak"}
FINGER_SETS = {"fingers & toes", "finger tweak"}
WING_TWEAK_SETS = {"wingtweak", "wing tweak"}
FULL_DRIVE = {"IK", "COPY_ROTATION", "COPY_TRANSFORMS", "DAMPED_TRACK", "TRACK_TO", "STRETCH_TO", "LOCKED_TRACK"}

# Rules on a bone's plain name (see rig_names.plain), first match wins:
# (pattern, home, stays a control even when a constraint drives it).
# Arms/Legs/Adjustment rules only apply to bones with a side (L/R); center bones are Torso.
BODY_RULES = [
    (r"brest|breast|boob", "Breasts", True),
    (r"focus|look", "Look", True),
    (r"brow", "Brows", False),
    (r"eye|pupil|puipl|puipil|iris|lash", "Eyes", True),
    (r"cheek", "Cheeks", False),
    (r"lip|jaw|muzzle|nose|teeth|tooth|tongue|tounge|mouth|snout|beak", "Mouth", False),
    (r"shaft|sheath|groin|knot|sac\d*$", "Groin", False),
    (r"thigh2", "Adjustment", True),            # toony adjustment, even inside an IK chain
    (r"heel|heal", "Adjustment", False),
    (r"(hand|arm|elbow|wrist).*(ik|pole|poll)|(ik|pole|poll).*(hand|arm|elbow)", "Arms", True),
    (r"(foot|leg|knee|hock|ankle).*(ik|pole|poll)|(ik|pole|poll).*(foot|leg|knee)", "Legs", True),
    (r"shoulder(?!s)|clavicle|forearm|forarm", "Arms", True),  # hand-adjusted (forearm = wrist twist)
    (r"hip(?!s)|thigh", "Legs", True),
    (r"arm|hand|elbow|wrist", "Arms", False),
    (r"leg|foot|knee|hock|ankle|shin|calf", "Legs", False),
    (r"main|master|root|pelvis|hips|spine|torso|chest|neck|head|shoulder|belly|waist|body|back|cog",
     "Torso", True),
]
LIMB_HOMES = {"Arms", "Legs", "Adjustment"}   # Arms and Legs become the side's IK collection
# Face set-up bones (upper snout): Adjustment only, sided or not. Extras one character adds: its Non-Standard collection.
FACE_ADJUSTMENT = r"^muzzle\d*$|snout"
FACE_NON_STANDARD = r"teeth|tooth|^jaw2$|muzzlecheek|cheekglow"
FACE_HOMES = {"Look", "Eyes", "Brows", "Mouth", "Cheeks"}


def chain(name):
    """The collection and its parents, top one first (a collection not in LAYOUT, made by hand or by place_fk: itself)."""
    parent = PARENT.get(name)
    return (chain(parent) if parent else []) + [name]


FACE_SORTED = ("Eyes", "Brows", "Mouth", "Cheeks", "Face Tweak")
HIDDEN_HOMES = {name for name in PARENT if HIDDEN & set(chain(name))}
FINGER_WORDS = r"finger|thumb|toe|index|pinky|pinkie|pointer|^palm$"
HAND_DIGIT = r"^(middle|ring)\d*$"   # fingers only under a hand or foot: old tails are Ring1, Ring2, ...
HAND_WORD = re.compile(r"hand|palm|paw|wrist|foot|hoof")
LEG_WORD = re.compile(r"foot|hoof|leg|thigh|shin|calf|heel|heal|hock|knee")
FK_STAYS = r"(?<!wing)(forearm|forarm)|^thigh1?$"   # limb bones an animator also poses in IK: they stay out of the FK
                                                     # collections (a wing's forearm is FK only)

def driven_bones(ob):
    """Bones a constraint drives at full influence: an IK's whole chain, or the constrained bone itself."""
    driven = set()
    for pb in ob.pose.bones:
        for c in pb.constraints:
            if not c.enabled or c.influence < 0.999 or c.type not in FULL_DRIVE:
                continue
            if c.type == "IK":
                bone, left = pb, c.chain_count or 1000
                while bone and left:
                    driven.add(bone.name)
                    bone, left = bone.parent, left - 1
            else:
                driven.add(pb.name)
    return driven


def driven_home(deform):
    """Where a fully driven bone goes: Deform only, or Mechanism if it doesn't deform."""
    return None if deform else "Mechanism"


def under_hand(b):
    """The bone hangs under a hand or foot (a finger or toe)."""
    return any(HAND_WORD.search(rn.plain(p.name)) for p in b.parent_recursive)


def part_region(name, bone=None):
    """Which part a bone belongs to by name (ears, hair, tail or wings on a main or merged rig). With the `bone`, a Ring
    finger under a hand is not an old tail bone."""
    n = rn.plain(name)
    if re.search(r"hair|mane|beard|hawk|bang", n):
        return "Hair"
    if n.startswith("ear"):
        return "Ears"
    if re.search(r"tail|fluke|peddel", n) or name == "Bone" or (re.search(r"^ring\d", n) and not (bone and under_hand(bone))):
        return "Tail"
    if "wing" in n:
        return "Wings"
    return None


def is_finger(b, old):
    n = rn.plain(b.name)
    return bool(old & FINGER_SETS or re.search(FINGER_WORDS, n) or (re.search(HAND_DIGIT, n) and under_hand(b)))


def is_b_bone_helper(name):
    """Bendy helper bones named after their control plus B: 'LeftEyeB1', 'LipBSide', 'EyeLeftB'."""
    return bool(re.search(r"[a-z]B(\d+|Side)?(\.\d+)?$", name))


def finger_home(b, deform, driven):
    """Base bone of a finger or toe is the control; later segments of the same finger are tweaks. Thumb2 is a control
    too when nothing drives it (body_rig's thumb rule: Thumb1 aims, Thumb2 curls)."""
    if b.parent and rn.bare_stem(b.parent.name) == rn.bare_stem(b.name):
        if driven or rn.plain(b.name) != 'thumb2':
            return "Finger Tweak"
    return driven_home(deform) if driven else "Fingers & Toes"


def part_home(region, deform, driven):
    """Ears, hair, tail, wings: posable unless a constraint drives them."""
    return driven_home(deform) if driven else region


def limb_home(home, name):
    """The IK collection of the bone's side for the Arms and Legs rules, other homes as they are."""
    if home not in ("Arms", "Legs"):
        return home
    return f"IK {rn.SIDE_WORDS[rn.side_of(name)]} {home[:-1]}"


def rule_home(b, deform, driven):
    """First BODY_RULES match on the bone's plain name (or its parent's, for Look)."""
    n = rn.plain(b.name)
    parent = rn.plain(b.parent.name) if b.parent else ""
    sided = rn.has_side(b.name)
    if re.search(FACE_NON_STANDARD, n):
        return "Face Non-Standard"
    if re.search(FACE_ADJUSTMENT, n):
        return "Adjustment"
    for pattern, home, stays in BODY_RULES:
        if home in LIMB_HOMES and not sided:
            continue
        if re.search(pattern, n) or (home == "Look" and re.search(pattern, parent)):
            return driven_home(deform) if driven and not stays else limb_home(home, b.name)
    return "Unsorted"


def rig_region(ob):
    """Part rigs are sorted by their name or where they hang; None for main rigs (and unknown parts)."""
    if not ob.parent or ob.parent.type != "ARMATURE":
        return None
    name = ob.name.lower()
    for words, region in ((r"wing", "Wings"), (r"hair|beard|mane", "Hair"), (r"ear", "Ears"),
                          (r"tail", "Tail"), (r"shaft|sheath|groin", "Groin")):
        if re.search(words, name):
            return region
    hang = rn.plain(ob.parent_bone)
    if "head" in hang:
        return "Hair"
    if re.search(r"pelvis|hip|root|tail", hang):
        return "Tail"
    return None


def plan_rig(ob):
    """{bone: (home collection or None, is deform)}"""
    driven = driven_bones(ob)
    rig_part = rig_region(ob)
    bones = ob.data.bones
    olds = {b.name: {c.name.lower() for c in b.collections} for b in bones}
    regions = {b.name: rig_part or part_region(b.name, b) for b in bones}
    plan = {}

    def home_of(b):
        n, old, deform = b.name, olds[b.name], b.use_deform
        is_driven = n in driven
        if old & MECHANISM_SETS or rn.split_role(n)[0] in ("MCH", "ORG") or re.search(r"roll|iktarget", rn.plain(n)):
            return "Mechanism"
        if rn.split_role(n)[0] == "DEF":
            return None
        if rn.split_role(n)[0] == "TWK" and not rig_part and re.fullmatch(LIMB_TWEAK, rn.plain(n)):
            return "Limb Tweak"
        if old & WING_TWEAK_SETS:
            return "Wing Tweak"
        if not rig_part and is_finger(b, old):
            return finger_home(b, deform, is_driven)
        if re.search(FACE_NON_STANDARD, rn.plain(n)):
            return "Face Non-Standard"
        for coll in NON_STANDARD + FACE_SORTED:   # already sorted: stays where the user or a tool put it
            if coll.lower() in old:
                return coll
        if old - DEFORM_SETS == {"adjustment"}:  # already converted: Adjustment only
            return "Adjustment"
        if old & HELPER_SETS or (is_driven and is_b_bone_helper(n)):  # tweak of their region, face or body
            if is_driven and deform:      # a deforming segment a constraint fully drives (brow / tongue B-bones)
                return None               # Deform only, nothing to pose
            if regions[n]:
                return TWEAK_OF.get(regions[n], "Adjustment")
            return "Face Tweak" if rule_home(b, deform, False) in FACE_HOMES else "Adjustment"
        if regions[n]:
            return part_home(regions[n], deform, is_driven)
        if "wings" in old:
            return "Wings"
        home = rule_home(b, deform, is_driven)
        if home == "Unsorted" and is_driven:
            return driven_home(deform)
        if home == "Unsorted":
            return posable_parent_home(b) or home
        return home

    def place(b):
        if b.name not in plan:
            plan[b.name] = (home_of(b), b.use_deform)
        return plan[b.name][0]

    def posable_parent_home(b):
        """Home of the nearest ancestor in a visible collection: a bone goes where it hangs."""
        parent = b.parent
        while parent:
            home = place(parent)
            if home and home not in HIDDEN_HOMES and home != "Unsorted":
                return home
            parent = parent.parent
        return None

    for b in bones:
        place(b)
    return plan


def extra_adjustment(ob, plan):
    """Bones kept in the old Adjustment collection as a second collection (face sizing: Jaw, Muzzle)."""
    return {b.name for b in ob.data.bones if "Adjustment" in {c.name for c in b.collections}
            and plan[b.name][0] not in ("Adjustment", "Breasts", *NON_STANDARD)}


def deform_home(ob, b, home):
    """Body Deform or Face Deform: the bone's home says, or for a bone with no face home its name."""
    region = rig_region(ob) or part_region(b.name, b)
    n = rn.plain(b.name)
    face = (home and chain(home)[0] == "Face") or region in ("Ears", "Hair") \
        or re.search(f"{FACE_NON_STANDARD}|{FACE_ADJUSTMENT}", n) or rule_home(b, True, False) in FACE_HOMES
    return "Face Deform" if face else "Body Deform"


def build(ob, plan, extra):
    a = ob.data
    stay_hidden = {c.name for c in a.collections_all if not c.is_visible and c.name in PARENT}
    for c in list(a.collections_all):
        a.collections.remove(c)
    deforms = {b.name: deform_home(ob, b, plan[b.name][0]) for b in a.bones if plan[b.name][1]}
    needed = {h for h, _ in plan.values() if h} | set(deforms.values())
    if extra:
        needed.add("Adjustment")
    needed = {name for home in needed for name in chain(home)}
    made = {}
    for parent, name, _ in LAYOUT:
        if name in needed:
            made[name] = a.collections.new(name, parent=made.get(parent))
            made[name].is_visible = name not in HIDDEN | stay_hidden
    for b in a.bones:
        home, deform = plan[b.name]
        if home:
            made[home].assign(b)
        if deform:
            made[deforms[b.name]].assign(b)
        if b.name in extra:
            made["Adjustment"].assign(b)
        if COLOR.get(home):
            b.color.palette = COLOR[home]
            pb = ob.pose.bones.get(b.name)
            if pb:
                pb.color.palette = "DEFAULT"
    apply_face_split_colors(ob)
    place_fk(ob)
    set_bbone_display(ob)


def face_split_color(name):
    """Custom colour for an upper or lower face part, or None."""
    n = rn.plain(name)
    return next((col for pattern, col in FACE_SPLIT if re.search(pattern, n)), None)


def apply_face_split_colors(ob, colors=None, only=None):
    """Upper / lower face parts: their own pose bone colour (normal, select and active shades).
    colors: optional (upper, lower) instead of FACE_SPLIT's; only: optional set of bone names to touch."""
    n = 0
    split = [(pat, col) for (pat, _), col in zip(FACE_SPLIT, colors)] if colors else FACE_SPLIT
    for pb in ob.pose.bones:
        if only is not None and pb.name not in only:
            continue
        col = next((c for pattern, c in split if re.search(pattern, rn.plain(pb.name))), None)
        if col:
            pb.color.palette = "CUSTOM"
            pb.color.custom.normal = col
            pb.color.custom.select = tuple(min(1.0, c * 0.5 + 0.5) for c in col)
            pb.color.custom.active = (1.0, 1.0, 1.0)
            n += 1
        elif pb.color.palette == "CUSTOM" and any(
                all(abs(a - b) < 1e-3 for a, b in zip(pb.color.custom.normal, c)) for _, c in split):
            pb.color.palette = "DEFAULT"      # no longer an upper / lower part (re-runs, renamed rules)
    return n


def ensure_home(ob, name):
    """The LAYOUT collection `name` on ob (its parents too), created if missing, without touching the rest of the
    layout (for tools that add a few bones to an already sorted rig). A name not in LAYOUT: the rig's collection of
    that name, else a new top-level one."""
    a = ob.data
    coll = None
    for step in chain(name):
        if step not in a.collections_all:
            a.collections.new(step, parent=coll).is_visible = step not in HIDDEN
        coll = a.collections_all[step]
    return coll


def ensure_deform(ob, bone_name, home=None):
    """The Body Deform or Face Deform collection for a bone."""
    return ensure_home(ob, deform_home(ob, ob.data.bones[bone_name], home))


DEF_THICKNESS = 0.03     # drawn B-Bone width (bbone_x / z) as a share of the bone's length: DEF bones
CONTROL_THICKNESS = 0.05   # ... other bones (the default 0.1 m looks fat)
MIN_THICKNESS = 0.001      # metres


LINE_PART = re.compile(r'Line(?:$|[-\d])')   # the part of a line bone: PoleLine-Elbow, LookLine ... (widget WGT-Line)


def is_line_bone(b):
    """The bone is drawn as a line (custom shape WGT-Line: pole lines, look line). Edit Mode ignores custom shapes, so
    these get the minimum B-bone width and show as thin lines there too."""
    return bool(LINE_PART.search(rn.parse(b.name).part))


def bbone_width(b, deform=None):
    """The drawn B-bone width for one bone (a Bone or an EditBone): a share of its length, min 1 mm. Line bones
    (`is_line_bone`) always get the minimum."""
    if is_line_bone(b):
        return MIN_THICKNESS
    deform = b.use_deform if deform is None else deform
    return max(MIN_THICKNESS, b.length * (DEF_THICKNESS if deform else CONTROL_THICKNESS))


def thin_bbone(b, deform=None):
    """Draw one bone's B-bone thin (a Bone or an EditBone): width a share of its length (DEF bones 3%, others 5%, min
    1 mm). Only the size is set: no per-bone BBONE display (it blocks Edit Mode on small rigs such as eyes; rigs are
    drawn STICK, see `new_armature`). deform None = the bone's use_deform."""
    deform = b.use_deform if deform is None else deform
    b.bbone_x = b.bbone_z = bbone_width(b, deform)


def new_armature(name):
    """A new armature datablock drawn STICK (like Digit): no big octahedral or B-bone shapes hiding small rigs in Edit
    Mode."""
    data = bpy.data.armatures.new(name)
    data.display_type = 'STICK'
    return data


def clear_bbone_overrides(rig):
    """Set every bone of `rig` (an armature object) that has the per-bone BBONE display back to the armature's own
    display (ARMATURE_DEFINED). Object / Pose Mode (Bone data). Safe to repeat. Returns how many bones changed."""
    changed = 0
    for b in rig.data.bones:
        if b.display_type == 'BBONE':
            b.display_type = 'ARMATURE_DEFINED'
            changed += 1
    return changed


def set_bbone_display(rig, bones=None):
    """Draw every bone of `rig` (an armature object; `bones` = names, default all) with a B-bone width that fits its
    length (bbone_x / z, `thin_bbone`'s rule: DEF bones 3%, others 5%, min 1 mm). Blender's default 0.1 m is fat on a
    1.4 m character. Needs Object / Pose Mode (Bone data). Changes no bone's display type. Safe to repeat. Returns how many bones changed."""
    changed = 0
    for b in rig.data.bones:
        if bones is not None and b.name not in bones:
            continue
        before = (b.bbone_x, b.bbone_z)
        if b.bbone_segments > 1:
            thin_bbone(b)
        else:
            b.bbone_x = b.bbone_z = bbone_width(b)
        changed += (b.bbone_x, b.bbone_z) != before
    return changed


def thin_bbones(bones):
    """thin_bbone for every bone of `bones` (Bones or EditBones) that is a B-bone (bbone_segments > 1)."""
    for b in bones:
        if b.bbone_segments > 1:
            thin_bbone(b)


def move_to(ob, bone_name, home, deform, keep_driven=False):
    """Put one bone in its home collection only (plus its deform collection when it deforms). `home` may be any
    collection of the rig, also one made by hand (it is used as it is) or a LAYOUT one still to be made. With
    keep_driven the bone stays in the collections a driver shows and hides (the FK limb collections). Nothing else
    changes (colour, B-Bone display)."""
    b = ob.data.bones[bone_name]
    for c in list(b.collections):
        if not (keep_driven and is_driven(ob, c)):
            c.unassign(b)
    if home:
        ensure_home(ob, home).assign(b)
    if deform:
        ensure_deform(ob, bone_name, home).assign(b)


def place_bone(ob, bone_name, home, deform):
    """Put one bone in its home collection only (plus its deform collection when it deforms), with the home's colour."""
    move_to(ob, bone_name, home, deform)
    ob.data.bones[bone_name].color.palette = COLOR.get(home) or "DEFAULT"
    set_bbone_display(ob, {bone_name})


def is_wing_limb(ctrl):
    """The IK control of a wing arm (wing_rig: IK-WingHand.L)."""
    return rn.parse(ctrl).part.lower().startswith("wing")


def fk_title(ctrl, leg):
    """The FK collection of the limb with IK control `ctrl`: 'FK Left Arm', 'FK Right Second Arm' on a second pair,
    'FK Left Wing' for a wing arm."""
    if is_wing_limb(ctrl):
        return " ".join(w for w in ("FK", rn.SIDE_WORDS.get(rn.side_of(ctrl), ""), "Wing") if w)
    extra = re.sub(r"Hand|Foot|Paw|Hoof", "", rn.parse(ctrl).part)
    return " ".join(w for w in ("FK", rn.SIDE_WORDS.get(rn.side_of(ctrl), ""), extra, "Leg" if leg else "Arm") if w)


def show_when_fk(ob, coll, ctrl):
    """The collection shows only while the limb is out of IK (IK_FK on its control below 1)."""
    drv = coll.driver_add("is_visible").driver
    drv.type = "SCRIPTED"
    v = drv.variables[0] if len(drv.variables) else drv.variables.new()
    v.name, v.type = "ik", "SINGLE_PROP"
    v.targets[0].id_type, v.targets[0].id = "OBJECT", ob
    v.targets[0].data_path = f'pose.bones["{ctrl}"]["IK_FK"]'
    drv.expression = "ik < 0.999"


def place_fk(ob):
    """FK limbs get their own collections under Body (a wing arm's under Wings), shown when the limb leaves IK: the limb
    bones the IK drives. On top of
    their home, which keeps a driven bone in Deform only while the limb is in IK. Reads the `Limb` data of each IK
    control. Safe to re-run. A part chain's data (tail, ears: `part` set) gets none: its bones are the FK controls and
    the IK's start shape at once, so they stay in their part's collection in IK and FK."""
    a = ob.data
    for pb in ob.pose.bones:
        if "Limb" not in pb or "IK_FK" not in pb:
            continue
        limb = json.loads(pb["Limb"])
        if limb.get("part"):
            continue
        fk = limb["fk"]
        title = fk_title(pb.name, any(LEG_WORD.search(rn.plain(n)) for n in fk))
        home = ensure_home(ob, "Wings" if is_wing_limb(pb.name) else "Body")
        coll = a.collections_all.get(title) or a.collections.new(title, parent=home)
        for name in fk:
            if name in a.bones and not re.search(FK_STAYS, rn.plain(name)):
                coll.assign(a.bones[name])
                if a.bones[name].color.palette == "DEFAULT":
                    a.bones[name].color.palette = FK_COLOR
        show_when_fk(ob, coll, pb.name)


def is_rigging(coll):
    """A Rigging collection (Deform, Mechanism...) or one inside it."""
    while coll is not None:
        if coll.name == "Rigging":
            return True
        coll = coll.parent
    return False


def show_chain_in_fk(ob, ctrl, names, title):
    """A part chain whose bones live only in Rigging collections (a ponytail of DEF bones): those bones also go in
    collection `title` (under the control's home collection), shown while the chain is in FK so they can be posed."""
    a = ob.data
    hidden = [n for n in names if not any(not is_rigging(c) for c in a.bones[n].collections)]
    if not hidden:
        return None
    home = next((c for c in a.bones[ctrl].collections if not is_rigging(c)), None)
    coll = a.collections_all.get(title) or a.collections.new(title, parent=home)
    for name in hidden:
        coll.assign(a.bones[name])
    show_when_fk(ob, coll, ctrl)
    return coll


# Show Bones groups of the rig panel: separate sets of LAYOUT collections that never overlap. A click shows one group,
# Shift-click adds or removes one. Mechanism is never shown; the FK limb collections keep their IK/FK driver.
BONE_GROUPS = (
    ("Deform", ("Body Deform", "Face Deform")),
    ("Body", ("Torso", "IK Left Arm", "IK Right Arm", "IK Left Leg", "IK Right Leg")),
    ("Face", ("Look", "Eyes", "Brows", "Mouth", "Cheeks", "Ears", "Hair")),
    ("Fingers & Toes", ("Fingers & Toes",)),
    ("Additional Parts", ("Extras", "Tail", "Wings", "Breasts", "Butt", "Groin")),   # Extras too: custom chains (B-Bone Chain Builder) hide with it
    ("Tweaks", ("Limb Tweak", "Finger Tweak", "Tail Tweak", "Face Tweak", "Ear Tweak", "Hair Tweak", "Wing Tweak", "Extras Tweak", "Adjustment")
     + NON_STANDARD),
)
GROUP_MEMBERS = {member for _, members in BONE_GROUPS for member in members}


def is_driven(ob, coll):
    """True when a driver sets the collection's visibility (the FK limb collections)."""
    anim = ob.data.animation_data
    return bool(anim and anim.drivers.find(f'collections_all["{coll.name}"].is_visible'))


def shown_groups(ob):
    """Names of the BONE_GROUPS that show on armature `ob` now (any of their collections visible, parents included)."""
    colls = ob.data.collections_all
    return {name for name, members in BONE_GROUPS
            if any(colls.get(m) is not None and colls[m].is_visible_effectively for m in members)}


def show_groups(ob, names):
    """Show exactly the BONE_GROUPS in `names` on armature `ob`, the other groups' collections hidden. Plain parents
    (Body, Face, Extras; Rigging and Deform only with the Deform group) show when a wanted collection needs them. A
    collection inside another group's collection (Ear Tweak in Ears) shows only when both groups do. Mechanism stays
    hidden; driven collections (FK limbs) are left to their driver."""
    colls = ob.data.collections_all
    wanted = {m for name, members in BONE_GROUPS if name in names for m in members}
    for m in GROUP_MEMBERS:
        coll = colls.get(m)
        if coll is not None and not is_driven(ob, coll):
            coll.is_visible = m in wanted
    for name in ("Rigging", "Deform"):
        if colls.get(name) is not None:
            colls[name].is_visible = "Deform" in names
    for m in wanted:
        parent = colls[m].parent if colls.get(m) is not None else None
        while parent is not None and parent.name not in GROUP_MEMBERS:
            parent.is_visible = True
            parent = parent.parent
    if colls.get("Mechanism") is not None:
        colls["Mechanism"].is_visible = False


def hide_rigging(ob):
    """Mechanism and Deform hidden on armature `ob`, whatever a build step did to them (the Show Bones Deform group
    shows Deform again)."""
    for name in ("Mechanism", "Deform"):
        coll = ob.data.collections_all.get(name)
        if coll is not None:
            coll.is_visible = False


def report(ob, plan):
    groups = {}
    for n, (h, _) in plan.items():
        groups.setdefault(h or "(Deform only)", []).append(n)
    kind = f"part: {rig_region(ob)}" if rig_region(ob) else "main"
    print(f"## {ob.name} ({kind}): " + "  ".join(f"{h} {len(v)}" for h, v in sorted(groups.items())))
    if "Unsorted" in groups:
        print(f"   UNSORTED: {groups['Unsorted']}")


def main():
    apply = "--apply" in sys.argv
    for ob in bpy.data.objects:
        if ob.type != "ARMATURE":
            continue
        plan = plan_rig(ob)
        report(ob, plan)
        if apply:
            build(ob, plan, extra_adjustment(ob, plan))
    if apply:
        bpy.ops.wm.save_mainfile()
        print("SAVED")


if __name__ == "__main__":
    main()
