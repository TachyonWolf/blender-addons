# SPDX-License-Identifier: GPL-3.0-or-later
"""Rig parts (shared: Addons/shared_addon/rig_parts.py is the ONE source, synced into Digit's Assorted Tools): what the
Rig panel shows, read off the rig. rig_switches_ui.py draws it; the operators live in Digit's Assorted Tools
(pose_ops.py, rig_panel_ops.py).

Switches: a bone "has switches" when it carries any number / toggle custom property (any rig: ours, Rigify,
hand-made), except internal MCH- / DEF- / ORG- bones and hidden "_" keys. SWITCHES only gives the known ones their
order and label. `switch_names(rig)` is cached per rig (bone count + RECHECK_SECONDS).

Parts: `rig_map(rig)` sorts every switch of the rig AND of its part armatures (ears, tails, hair, wings: armatures
parented to it, at any depth, that are in the view layer) into parts, from the rig itself (no character list): a limb
control (it has `Limb` data) gives Arm L / Arm R / Leg L / Leg R (a part chain's: Tail, Ear L / Ear R, its data names
the part); every part armature gives a page, also without switches (bone_collections.rig_region: Wings, Ears, Tail,
Hair...; when several share a region, its own name: "Hair Pony", "Tail Lotus"), which lists its tip IKs that have no
IK/FK switch yet (`TipChain`: part_chains.add_tip_switch adds one); a bone in the Ears / Hair / Tail / Wings
collections gives that part; one in the Face collections gives Face, in Torso gives Torso; the main rig's own
switches (on the rig object or its data) give Full Body; anything else goes to Other, so no switch is lost. Left /
right switches that match by name share one row. The pages come sorted into SECTIONS (Full Body, Head, Torso, Arms,
Legs, Other) by `part_section`: a word of the page's name (or the part armature's region), else the bone the part
armature hangs on. The map also knows the part of every bone (limb chains included), for Follow Selection. Cached
like switch_names.

`character_rig(obj)` finds the character's main rig from any object of it, cheaply (no scene scan).
"""
import json
import re
import time
from collections import namedtuple

import bpy

from . import bone_collections as bc, limb_rig as lr, rig_names as rn  # generated copies
from .ui_cards import friendly_name as friendly  # generated copy

# bone property -> label, in display order
SWITCHES = (("IK_FK", "IK"), ("IK_Stretch", "Stretch"), ("PoleFollow", "Pole Follow"), ("KneeFollow", "Knee Follow"), ("RubberHose", "Rubber Hose"),
            ("SpineIK", "Spine IK"), ("HeadAim", "Head Aim"), ("LookFollow", "Look Follow"), ("Focus", "Focus"), ("PupilSize", "Pupil Size"), ("IrisSize", "Iris Size"), ("HeadFollow", "Head Follow"), ("NeckFollow", "Neck Follow"),
            ("FootRoll", "Foot Roll"), ("RollBreak", "Roll Break"), ("FootBank", "Foot Bank"), ("HeelSwivel", "Heel Swivel"),
            ("curl", "Curl"), ("droop", "Droop"), ("maw_stretch", "Maw Stretch"),
            ("lip_roll_upper", "Upper Lip Roll"), ("lip_roll_lower", "Lower Lip Roll"),
            ("zip", "Zip"), ("corner_slide", "Corner Slide"), ("corner_pin", "Pin To Jaw"),
            ("scrunch", "Scrunch"), ("snarl_scrunch", "Snarl Scrunch"), ("flare", "Flare"), ("puff", "Puff"), ("cloak", "Cloak"),
            ("follow_tip", "Follow Tip"), ("fold", "Fold"), ("spread", "Spread"), ("auto_fan", "Auto Fan"), ("billow", "Billow"), ("auto_turn", "Auto Turn"),
            ("WaveHeight", "Wave Height"), ("WaveSpeed", "Wave Speed"), ("Wavelength", "Wavelength"),
            ("WaveDirection", "Wave Direction"))
SLIDERS = ("IK_FK", "IK_Stretch", "PoleFollow", "KneeFollow", "RubberHose", "SpineIK", "HeadAim", "Focus", "PupilSize", "IrisSize", "HeadFollow", "NeckFollow", "curl", "droop", "maw_stretch", "lip_roll_upper", "lip_roll_lower",
           "zip", "corner_slide", "corner_pin", "scrunch", "snarl_scrunch", "flare", "puff", "cloak", "follow_tip", "fold", "spread", "auto_fan", "billow", "auto_turn",
           "WaveHeight", "WaveSpeed", "Wavelength", "WaveDirection")
LABELS = dict(SWITCHES)
LEG_WORDS = ("foot", "toe", "ankle", "leg", "thigh", "shin", "calf", "knee", "hock")
INTERNAL_BONE = re.compile(r"^(MCH|DEF|ORG)[-_.]")   # mechanism bones: their properties are driven, not posed
LIMB_KEYS = {"Limb", "IK_Parent"}                    # limb data, drawn by the limb buttons
TUNING = {"cheek_follow", "cheek_swing"}             # model settings (face_rig_core CHEEK_TUNING), not a pose: shown, never reset or counted as changed

RECHECK_SECONDS = 3.0   # a cached answer is also scanned again after this long (props added to existing bones keep the count)
_cache = {}      # rig name -> (bone count, time of the scan, [names of the bones with switches])
_maps = {}       # rig name -> (key, time of the scan, RigMap)
scan_count = 0   # how many full bone scans happened (tests: a redraw must not add to it)

# ---------------------------------------------------------------- which properties are switches

def is_number(value):
    """A number, a toggle or a short number array (a vector): what can be drawn as a property field."""
    if isinstance(value, (bool, int, float)):
        return True
    items = value.to_list() if hasattr(value, "to_list") else None
    return bool(items) and len(items) <= 4 and all(isinstance(v, (bool, int, float)) for v in items)


def shown_keys(owner, internal=False):
    """The custom properties a rig card shows for `owner` (a pose bone or the rig itself): the known SWITCHES first in
    their order, then every other number property A-Z. Limb data (`Limb`, `IK_Parent`) is drawn by the limb buttons."""
    if internal or (hasattr(owner, "bone") and INTERNAL_BONE.match(owner.name)):
        return []
    known = [key for key, _ in SWITCHES if key in owner]
    skip = set(known) | (LIMB_KEYS if "Limb" in owner else set())
    extra = sorted(key for key in owner.keys() if key not in skip and not key.startswith("_") and is_number(owner[key]))
    return known + extra


def prop_label(key):
    """Known keys keep their label ("IK"); others read as words: follow_tip -> "Follow Tip", FK_limb_follow -> "FK Limb Follow"."""
    return LABELS.get(key) or " ".join(w[:1].upper() + w[1:] for w in key.replace("-", "_").split("_") if w)


def property_default(owner, key):
    """The default set in the property's UI data (what Reset puts back), or None (no UI data, strings, groups)."""
    try:
        return owner.id_properties_ui(key).as_dict().get("default")
    except TypeError:
        return None


def plain_value(value):
    return list(value) if hasattr(value, "__len__") and not isinstance(value, str) else value


def is_changed(owner, key):
    """True when the property is away from its default (numbers compared with a small tolerance)."""
    if key in TUNING:
        return False
    default = property_default(owner, key)
    if default is None or key not in owner:
        return False
    current = plain_value(owner[key])
    try:
        if isinstance(current, list):
            return len(current) != len(default) or any(abs(a - b) > 1e-6 for a, b in zip(current, default))
        return abs(current - default) > 1e-6
    except TypeError:   # text, or a list against a single value
        return current != default


def reset_property(owner, key):
    """Put one property back to its default; True when it changed (Reset Pose and the panel's resets)."""
    if not is_changed(owner, key):
        return False
    owner[key] = property_default(owner, key)
    return True


def switch_names(rig):
    """Names of the rig's bones that carry switch properties; scanned again only when the bone count changes or the
    answer is RECHECK_SECONDS old (no timers: checked when a panel asks)."""
    global scan_count
    count = len(rig.pose.bones)
    cached = _cache.get(rig.name)
    now = time.monotonic()
    if cached and cached[0] == count and now - cached[1] < RECHECK_SECONDS:
        return cached[2]
    scan_count += 1
    names = [pb.name for pb in rig.pose.bones if shown_keys(pb)]
    _cache[rig.name] = (count, now, names)
    return names


def forget_cache():
    _cache.clear()
    _maps.clear()


def switch_bones(rig):
    if rig is None or rig.type != 'ARMATURE':
        return []
    return [rig.pose.bones[name] for name in switch_names(rig) if name in rig.pose.bones]


def rig_owners(rig):
    """(title, owner) for every place on the rig with shown properties: the rig object and its armature data first
    ("Rig"), then each switch bone."""
    owners = [("Rig", owner) for owner in (rig, rig.data) if shown_keys(owner)]
    return owners + [(switch_title(pb), pb) for pb in switch_bones(rig)]


def character_rig(obj):
    """The main rig (has switches) of the character `obj` belongs to, else None. Armature: the topmost armature at or
    above it that has switches (so Wings and Ears give the body rig). Mesh and others: the rig of its Armature
    modifier, else of its parents, then the same climb."""
    if obj is None:
        return None
    start = obj if obj.type == 'ARMATURE' else None
    if start is None:
        start = next((m.object for m in getattr(obj, "modifiers", ()) if m.type == 'ARMATURE' and m.object), None)
    if start is None:
        start = obj.parent
        while start is not None and start.type != 'ARMATURE':
            start = start.parent
    found, rig = None, start
    while rig is not None:
        if rig.type == 'ARMATURE' and switch_names(rig):
            found = rig
        rig = rig.parent
    return found

# ---------------------------------------------------------------- titles

LIMB_NAME_FIELDS = ("tip", "target", "pole", "hock", "hock_target", "turns")
LIMB_LIST_FIELDS = ("chain", "fk")


def limb_data(control):
    """The control's Limb data with its bone names read in any style: data written before Rename Bones still names
    'LeftHand', which is now 'Hand.L' (rig_names.standard). Names that exist are kept as they are."""
    limb = json.loads(control["Limb"])
    bones = control.id_data.pose.bones
    names = [limb.get(field) for field in LIMB_NAME_FIELDS] + [n for field in LIMB_LIST_FIELDS for n in limb.get(field) or ()]
    if all(not name or name in bones for name in names):
        return limb
    by_standard = {}
    for name in bones.keys():
        by_standard.setdefault(rn.standard(name).lower(), name)

    def resolve(name):
        return name if not name or name in bones else by_standard.get(rn.standard(name).lower(), name)
    for field in LIMB_NAME_FIELDS:
        limb[field] = resolve(limb.get(field))
    for field in LIMB_LIST_FIELDS:
        limb[field] = [resolve(name) for name in limb.get(field) or ()]
    return limb


def limb_kind(pose_bone):
    """("Arm", "Leg" or "Wing", "L" / "R" / "") of a control with Limb data: side from the bone name, arm or leg from
    the bones it moves; a wing arm's control (bone_collections.is_wing_limb) is a Wing. A part chain's data names its
    own word ("Tail", "Ear": limb_rig.store_limb_data)."""
    limb = json.loads(pose_bone["Limb"])
    names = [pose_bone.name, limb.get("tip") or ""] + list(limb.get("chain") or [])
    side = re.search(r"(?:[._ -]|^)([LR])(?:[._ -]|$)|(left|right)", pose_bone.name, re.IGNORECASE)
    side = (side.group(1) or side.group(2)[0]).upper() if side else ""
    if limb.get("part"):
        return limb["part"], side
    if bc.is_wing_limb(pose_bone.name):
        return "Wing", side
    leg = bool(limb.get("hock")) or any(word in name.lower() for name in names for word in LEG_WORDS)
    return ("Leg" if leg else "Arm"), side


def limb_title(pose_bone):
    """"Left Arm" / "Right Leg" for a control with Limb data, "Arm" without a side."""
    kind, side = limb_kind(pose_bone)
    return f"{rn.SIDE_WORDS[side] + ' ' if side else ''}{kind}"


PART_BASE = re.compile(r"^([A-Z][A-Za-z]*?)Base\.([LR])$")   # a part rig's per-side base control: WingBase.L


def switch_title(pose_bone):
    """"Left Arm" for a limb, "Left Wing" for a part's per-side base control (WingBase.L), else the plain name."""
    if "Limb" in pose_bone:
        return limb_title(pose_bone)
    base = PART_BASE.match(pose_bone.name)
    if base:
        return f"{'Left' if base.group(2) == 'L' else 'Right'} {base.group(1)}"
    return friendly(pose_bone.name)


def switch_summary(pose_bone):
    """What the folded box shows: IK / FK (and the roll) for a limb, else how many sliders it holds."""
    if "IK_FK" in pose_bone:
        text = "IK" if pose_bone["IK_FK"] > 0.5 else "FK"
        return f"{text} · roll {pose_bone['FootRoll']:g}" if "FootRoll" in pose_bone else text
    if "SpineIK" in pose_bone:
        return "Spine IK on" if pose_bone["SpineIK"] > 0.5 else "Spine IK off"
    n = len(shown_keys(pose_bone))
    return f"{n} slider{'' if n == 1 else 's'}"


def rig_summary(rig):
    """Header text of the rig's box: "4 limbs · 2 IK" (or "N controls" when no bone has Limb data). Tail and ear
    controls count too: they switch IK / FK like a limb."""
    pbs = switch_bones(rig)
    limbs = [pb for pb in pbs if "Limb" in pb]
    if not limbs:
        return f"{len(pbs)} controls"
    in_ik = sum(1 for pb in limbs if pb.get("IK_FK", 0) > 0.5)
    return f"{len(limbs)} limb{'' if len(limbs) == 1 else 's'} · {in_ik} IK"

# ---------------------------------------------------------------- parts

OTHER = "Other"
FULL_BODY = "Full Body"   # the main rig's own switches (rig object, armature data): the whole rig
PART_COLLECTIONS = ("Ears", "Hair", "Tail", "Wings", "Breasts", "Groin")   # collections (tweak children included) that make a part of their own
# The part drop-down's sections, in order, with the words that put a page there (a word of the page's name or the
# part armature's region, matched left to right; the word's place sorts the pages inside a section, then A-Z, so L
# comes before R). Full Body holds only the Full Body page.
SECTIONS = ((FULL_BODY, ()),
            ("Head", ("face", "head", "neck", "eyes", "eye", "look", "brows", "mouth", "jaw", "snout", "ears", "ear", "hair")),
            ("Torso", ("torso", "spine", "chest", "hips", "pelvis", "breasts", "butt", "groin", "wings", "wing")),
            ("Arms", ("arm", "arms", "hand", "hands", "fingers")),
            ("Legs", ("leg", "legs", "foot", "feet", "toes")),
            (OTHER, ("tail", "tails")))
# A part armature no word places: the bone it hangs on (rig_names.plain name). Nothing matches: Other.
HANG_SECTIONS = (("Head", r"head|neck|jaw|skull"), ("Torso", r"chest|spine|torso|pelvis|hip|breast"),
                 ("Arms", r"arm|hand|shoulder|clavicle"), ("Legs", r"thigh|shin|leg|foot"))
# Sub-groups of a page (the Face page's Mouth / Nose / Cheeks / Tongue): by anatomy words on the bone's plain name,
# else the bone's home collection.
SUB_GROUPS = (("Nose", r"nose|nostril|snout"), ("Tongue", r"tongue|tounge"), ("Eyes", r"eye|lid|lash|pupil"),
              ("Brows", r"brow"), ("Cheeks", r"cheek|puff"))

Entry = namedtuple("Entry", "arm bone key")       # one switch: armature object name, bone name ("" = the rig object, "#data" = its armature data), key
Row = namedtuple("Row", "group label entries")    # one panel row: sub-group heading, label, 1 entry or 2 (left, right)
# limb = (armature name, control bone name) for an Arm / Leg page, else None; arm = the part armature of the page (Select
# Controls), else None; chains = its TipChains without a switch
Part = namedtuple("Part", "rows limb arm chains", defaults=(None, ()))
TipChain = namedtuple("TipChain", "arm control part")   # a tip IK with no IK/FK switch: armature, IK control, the part its switch will make
RigMap = namedtuple("RigMap", "parts bone_parts groups sections")   # parts: {name: Part} in display order; bone_parts: {(arm, bone): part}; groups: Show Bones groups the rig has; sections: ((section, (part names...)), ...) for the drop-down


def rig_armatures(rig):
    """The rig and its part armatures (armatures parented to it, at any depth)."""
    return [rig] + [ob for ob in rig.children_recursive if ob.type == 'ARMATURE']


def shown_armatures(rig):
    """rig_armatures that are in the view layer (a character's spare tails sit in excluded collections)."""
    view_layer = getattr(bpy.context, "view_layer", None)
    return [arm for arm in rig_armatures(rig) if arm == rig or view_layer is None or arm.name in view_layer.objects]


def page_names(rig, parts):
    """{part armature: its page}: its region (Tail, Hair...) when it is the only one there, else its own name in words
    without the character's name ("DigitTailLotus" -> "Tail Lotus")."""
    regions = {arm: bc.rig_region(arm) for arm in parts}
    names = {}
    for arm, region in regions.items():
        if region and list(regions.values()).count(region) == 1:
            names[arm] = region
        else:
            own = arm.name[len(rig.name):] if arm.name.startswith(rig.name) and arm.name != rig.name else arm.name
            names[arm] = friendly(own)
    return names


def chain_label(control):
    """"Hair Pony" for IK-HairPony, "Orca Tail Fluke" for IK-OrcaTailFluke.L: a tip IK's name in words, no side."""
    parsed = rn.parse(control)
    return friendly(parsed.part + ("" if parsed.number is None else str(parsed.number)))


def tip_chains(arm, page):
    """[(control, part, switched)] of the armature's tip IKs: part = `page` when its chains all share one name (one
    ponytail, or an ear pair: the side comes from the control), else the chain's own name. Switched: the control
    has Limb data or the IK's influence is driven already."""
    drivers = arm.animation_data.drivers if arm.animation_data else None
    found = []
    for pb, con in lr.tip_iks(arm):
        driven = drivers is not None and drivers.find(f'pose.bones["{pb.name}"].constraints["{con.name}"].influence')
        found.append((con.subtarget, "Limb" in arm.pose.bones[con.subtarget] or bool(driven)))
    labels = {chain_label(control) for control, _ in found}
    return [(control, page if len(labels) == 1 else chain_label(control), switched) for control, switched in found]


def owner_of(entry):
    """The pose bone (or rig object / armature data) an Entry points at, or None when it is gone."""
    ob = bpy.data.objects.get(entry.arm)
    if ob is None or ob.type != 'ARMATURE':
        return None
    if entry.bone == "":
        return ob
    if entry.bone == "#data":
        return ob.data
    return ob.pose.bones.get(entry.bone)


def limb_part(pose_bone):
    """"Arm L" for a limb control on the left, plain "Arm" without a side."""
    kind, side = limb_kind(pose_bone)
    return f"{kind} {side}" if side else kind


def limb_bone_names(pose_bone):
    """The control and every bone its Limb data names (chain, FK, tip, target, pole, hock)."""
    limb = limb_data(pose_bone)
    names = {pose_bone.name}
    for key in ("chain", "fk"):
        names.update(limb.get(key) or ())
    names.update(limb.get(key) for key in LIMB_NAME_FIELDS if limb.get(key))
    return names


def collection_homes(bone):
    """The standard collections a bone is in, with their parents ("Mouth" -> Face, Mouth)."""
    return {name for c in bone.collections if c.name in bc.PARENT for name in bc.chain(c.name)}


LIMB_COLLECTION = re.compile(r"^(?:IK|FK) (Left|Right) (?:\w+ )?(Arm|Leg)$")   # "FK Left Arm", "IK Right Second Leg"


HEAD_BONE = re.compile(r"(?:head|neck)(?:ik\w*|follow|aim|look\w*)?|look\w*")   # bare_stem of Head, Neck1, HeadLookFocus, MCH-HeadIKParent
HEAD_PAGE = "Head"


def collection_part(bone):
    """Part from the bone's collections: a limb's IK / FK collection gives "Arm L"; then Ears / Hair / Tail / Wings /
    Breasts / Groin, else Face, else Torso, else None. A head / neck / look-at bone that would land on Torso, Face
    (HeadLookFocus is in the Face collection on a fresh build) or nowhere goes to the Head page, the one IK-Head's Limb data makes, so the head's switches sit with the head."""
    found = collection_part_by_collection(bone)
    if found in ("Torso", "Face", None) and HEAD_BONE.fullmatch(rn.bare_stem(bone.name)):
        return HEAD_PAGE
    return found


def collection_part_by_collection(bone):
    """collection_part without the head rule."""
    for coll in bone.collections:
        limb = LIMB_COLLECTION.match(coll.name)
        if limb:
            return f"{limb.group(2)} {limb.group(1)[0]}"
    homes = collection_homes(bone)
    found = next((name for name in PART_COLLECTIONS if name in homes), None)
    return found or next((name for name in ("Face", "Torso") if name in homes), None)


def sub_group(bone):
    """The heading of a bone's sub-group on its page: an anatomy word, else its home collection, else its plain name."""
    plain = rn.plain(bone.name)
    found = next((title for title, words in SUB_GROUPS if re.search(words, plain)), None)
    if found:
        return found
    homes = [c.name for c in bone.collections if bc.PARENT.get(c.name) and c.name not in bc.HIDDEN_HOMES
             and "Deform" not in c.name]
    return homes[0] if homes else friendly(rn.strip_side(bone.name)).strip()


def rows_for(found):
    """Rows of one part from [(Entry, sub-group)]: a .L entry and the .R entry of the same bone and key share a row."""
    by_entry = {entry: group for entry, group in found}
    rows, used = [], set()
    for entry, group in found:
        if entry in used:
            continue
        side = rn.side_of(entry.bone) if entry.bone not in ("", "#data") else ""
        twin = Entry(entry.arm, rn.flip(entry.bone), entry.key) if side else None
        if twin in by_entry and twin not in used:
            pair = (entry, twin) if side == "L" else (twin, entry)
            used.update(pair)
            rows.append(Row(group, prop_label(entry.key), pair))
        else:
            used.add(entry)
            rows.append(Row(group, prop_label(entry.key), (entry,)))
    return unique_labels(rows)


def unique_labels(rows):
    """Two rows of one sub-group with the same label get the bone's name in front ("Tongue Curl")."""
    seen = {}
    for row in rows:
        seen.setdefault((row.group, row.label), []).append(row)
    out = []
    for row in rows:
        if len(seen[(row.group, row.label)]) > 1 and row.entries[0].bone not in ("", "#data"):
            stem = friendly(rn.strip_side(row.entries[0].bone)).strip()
            row = row._replace(label=f"{stem} {row.label}")
        out.append(row)
    return out


SECTION_NAMES = [name for name, _words in SECTIONS]


def part_section(name, arm=None):
    """(section, rank) of a page: the first word of its name, or of the part armature's region, found in SECTIONS
    (rank = the word's place there); else the bone the part armature hangs on (HANG_SECTIONS); else Other."""
    if name == FULL_BODY:
        return FULL_BODY, 0
    region = bc.rig_region(arm) if arm is not None else None
    for word in name.lower().split() + ([region.lower()] if region else []):
        for section, words in SECTIONS:
            if word in words:
                return section, words.index(word)
    hang = rn.plain(arm.parent_bone) if arm is not None and arm.parent_bone else ""
    found = next((section for section, pattern in HANG_SECTIONS if hang and re.search(pattern, hang)), OTHER)
    return found, len(SECTIONS[SECTION_NAMES.index(found)][1])


def sort_sections(names, arms):
    """((section, (page names...)), ...) in SECTIONS order, only sections with pages: by word rank, then A-Z (L before
    R); Other's own page last. `arms`: {page: its part armature object}."""
    placed = {}
    for name in names:
        section, rank = part_section(name, arms.get(name))
        placed.setdefault(section, []).append((name == OTHER, rank, name))
    return tuple((section, tuple(name for *_key, name in sorted(placed[section])))
                 for section in SECTION_NAMES if section in placed)


def scan_map(rig):
    """Build the RigMap of `rig` (the whole scan; rig_map caches it)."""
    found = {}           # part -> [(Entry, sub-group)]
    limbs = {}           # part -> (arm, control)
    part_arms = {}       # part -> part armature name
    chains = {}          # part -> [TipChain] without a switch
    bone_parts = {}
    arms = shown_armatures(rig)
    pages = page_names(rig, arms[1:])
    for arm in arms:
        region = pages.get(arm)
        if region:
            found.setdefault(region, [])
            part_arms.setdefault(region, arm.name)
            for control, part, switched in tip_chains(arm, region):
                if not switched:
                    chains.setdefault(region, []).append(TipChain(arm.name, control, part))
        for owner, bone in ((arm, ""), (arm.data, "#data")):   # rig-level switches first, as before
            for key in shown_keys(owner):
                found.setdefault(region or FULL_BODY, []).append((Entry(arm.name, bone, key), "Rig"))
        limb_of = {}
        for pb in arm.pose.bones:
            if "Limb" in pb and "IK_FK" in pb:
                try:
                    part, names = limb_part(pb), limb_bone_names(pb)
                except (TypeError, ValueError) as exc:   # broken Limb data: its switches go to Other
                    print(f"rig_parts: {arm.name}:{pb.name} Limb data unreadable ({exc})")
                    continue
                limbs.setdefault(part, (arm.name, pb.name))
                limb_of.update(dict.fromkeys(names, part))
        for pb in arm.pose.bones:
            part = limb_of.get(pb.name) or region or collection_part(pb.bone)
            if part:
                bone_parts[(arm.name, pb.name)] = part
            keys = [key for key in shown_keys(pb) if not (key == "IK_FK" and limbs.get(part) == (arm.name, pb.name))]
            group = part if limb_of.get(pb.name) else sub_group(pb.bone)
            for key in keys:
                found.setdefault(part or OTHER, []).append((Entry(arm.name, pb.name, key), group))
    for part in limbs:
        found.setdefault(part, [])
        part_arms.setdefault(part, limbs[part][0] if limbs[part][0] != rig.name else None)
    rig_wide = found.pop(FULL_BODY, [])
    if set(found) - {OTHER}:
        found[FULL_BODY] = rig_wide
    elif rig_wide:    # a rig off the standard: everything stays on Other, rig-wide first
        found[OTHER] = rig_wide + found.get(OTHER, [])
    sections = sort_sections(found, {name: bpy.data.objects.get(arm) for name, arm in part_arms.items() if arm})
    parts = {name: Part(rows_for(found[name]), limbs.get(name), part_arms.get(name), tuple(chains.get(name, ())))
             for _section, names in sections for name in names}
    present = {c.name for arm in arms for c in arm.data.collections_all}
    groups = tuple(name for name, colls in bc.BONE_GROUPS if present & set(colls))
    bone_parts = {key: part for key, part in bone_parts.items() if part in parts}
    return RigMap(parts, bone_parts, groups, sections)


def rig_map(rig):
    """The cached RigMap of `rig`: scanned again when the rig's bone count or the file's object count changes (a part
    armature added or removed), or after RECHECK_SECONDS."""
    global scan_count
    key = (len(rig.pose.bones), len(bpy.data.objects))
    cached = _maps.get(rig.name)
    now = time.monotonic()
    if cached and cached[0] == key and now - cached[1] < RECHECK_SECONDS:
        return cached[2]
    scan_count += 1
    found = scan_map(rig)
    _maps[rig.name] = (key, now, found)
    return found


def part_entries(part):
    return [entry for row in part.rows for entry in row.entries]


def changed_entries(entries):
    found = []
    for entry in entries:
        owner = owner_of(entry)
        if owner is not None and is_changed(owner, entry.key):
            found.append(entry)
    return found


def part_switches(rig_info, name):
    """Every Entry of a part, the limb control's IK/FK and parent switches included (what Reset Part resets)."""
    part = rig_info.parts[name]
    entries = part_entries(part)
    if part.limb:
        arm, bone = part.limb
        entries = [Entry(arm, bone, "IK_FK"), Entry(arm, bone, "IK_Parent")] + entries
    return [entry for entry in entries if (owner_of(entry) is not None and entry.key in owner_of(entry))]


def changed_counts(rig_info):
    """{part: how many of its switches are away from their default}, parts with changes only."""
    counts = {name: len(changed_entries(part_switches(rig_info, name))) for name in rig_info.parts}
    return {name: count for name, count in counts.items() if count}

# ---------------------------------------------------------------- which page shows (Follow Selection, no handlers)

def active_bone_key(context):
    """(armature name, bone name) of the active bone of the active armature, else None."""
    ob = context.active_object
    if ob is None or ob.type != 'ARMATURE' or ob.data.bones.active is None:
        return None
    return (ob.name, ob.data.bones.active.name)


def bone_key_text(key):
    return f"{key[0]}\t{key[1]}" if key else ""


def shown_part(rig_info, context, stored_part, stored_bone, follow):
    """The page to show. A part click stores the part and the bone active at that moment (`stored_bone`, as
    bone_key_text). While Follow Selection is on and the active bone is a different one, the active bone's part
    shows; otherwise the stored part. Pure: reads only, so draw() can call it."""
    names = list(rig_info.parts)
    if not names:
        return None
    active = active_bone_key(context)
    if follow and active and bone_key_text(active) != stored_bone and active in rig_info.bone_parts:
        return rig_info.bone_parts[active]
    return stored_part if stored_part in rig_info.parts else names[0]
