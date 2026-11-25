# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/rig_names.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""All bone name logic (docs/BONE_NAMES.md is the standard; this file is the ONE source, sync_shared.py copies it into
each add-on / script folder; no bpy here). Two parts:

Rig bone names: parse a name of any style into role, part, number and side, build a standard name, flip sides, turn an
old name (`LeftForearm1`, `foot_ik_l`, `Master`) into the standard one, find a bone by name whatever style the rig uses.
Tools never hard-code `Left`, `.L` or a prefix: they call this.

Game rig names: the one table of logical part > the name each engine expects. game_rig.py decides WHICH logical part a
bone is; this file is the only place that knows what it is called.

Logical parts: root, pelvis, spine (1..n, the last one is the chest), neck (1..), head, jaw, eye, clavicle, upperarm,
lowerarm, lowerarm2, hand, thumb / index / middle / ring / pinky (1..3), thigh, calf, hock, foot, toes, brow (1..), lipcorner,
tail, ear, hair, wing (1..). A side is 'L', 'R' or '' (centre); her left is +X.

Engines (EngineProperty items): Unreal = Mannequin names (`lowerarm_l`); Godot = SkeletonProfileHumanoid names
(`LeftLowerArm`, checked against the Godot docs); Unity = HumanBodyBones names (`LeftLowerArm`; Unity's Humanoid
Avatar has no fixed names, it maps by hierarchy and body-part words, and these are the names its auto-mapping
recognises best); Generic = no table, the source rig's own names stay.
"""
import re
from collections import Counter, namedtuple

ENGINES = (("UNREAL", "Unreal", "Unreal Mannequin bone names (upperarm_l, calf_l)"),
           ("UNITY", "Unity", "Unity Humanoid names (LeftUpperArm, LeftLowerLeg)"),
           ("GODOT", "Godot", "Godot SkeletonProfileHumanoid names (LeftUpperArm, LeftLowerLeg)"),
           ("GENERIC", "Generic", "Keep the source rig's own bone names"))
DEFAULT_ENGINE = "UNREAL"
COLUMN = {"UNREAL": 0, "UNITY": 1, "GODOT": 2}
# (prefix, suffix) a side adds to a name: '{pre}' and '{sfx}' in the templates
SIDE_TOKENS = {"UNREAL": {"L": ("", "_l"), "R": ("", "_r"), "": ("", "")},
               "UNITY": {"L": ("Left", ""), "R": ("Right", ""), "": ("", "")},
               "GODOT": {"L": ("Left", ""), "R": ("Right", ""), "": ("", "")}}

# part -> (Unreal, Unity, Godot); a tuple is picked by the part's number (1, 2, ...), '{i}' / '{i:02d}' = the number
PARTS = {
    "root": ("root", "Root", "Root"),
    "pelvis": ("pelvis", "Hips", "Hips"),
    "spine": ("spine_{i:02d}", ("Spine", "Chest", "UpperChest"), ("Spine", "Chest", "UpperChest")),
    "neck": ("neck_{i:02d}", ("Neck",), ("Neck",)),
    "head": ("head", "Head", "Head"),
    "jaw": ("jaw", "Jaw", "Jaw"),
    "eye": ("eye{sfx}", "{pre}Eye", "{pre}Eye"),
    "clavicle": ("clavicle{sfx}", "{pre}Shoulder", "{pre}Shoulder"),
    "upperarm": ("upperarm{sfx}", "{pre}UpperArm", "{pre}UpperArm"),
    "lowerarm": ("lowerarm{sfx}", "{pre}LowerArm", "{pre}LowerArm"),
    "lowerarm2": ("lowerarm2{sfx}", "{pre}LowerArm2", "{pre}LowerArm2"),   # no engine standard: the elbow-side split
    "hand": ("hand{sfx}", "{pre}Hand", "{pre}Hand"),
    "thigh": ("thigh{sfx}", "{pre}UpperLeg", "{pre}UpperLeg"),
    "calf": ("calf{sfx}", "{pre}LowerLeg", "{pre}LowerLeg"),
    "hock": ("hock{sfx}", "{pre}Hock", "{pre}Hock"),
    "foot": ("foot{sfx}", "{pre}Foot", "{pre}Foot"),
    "toes": ("ball{sfx}", "{pre}Toes", "{pre}Toes"),
    "brow": ("brow_{i:02d}{sfx}", "{pre}Brow{i}", "{pre}Brow{i}"),
    "lipcorner": ("lip_corner{sfx}", "{pre}LipCorner", "{pre}LipCorner"),
    # no engine standard: the engine's own pattern
    "tail": ("tail_{i:02d}", "Tail{i}", "Tail{i}"),
    "ear": ("ear_{i:02d}{sfx}", "{pre}Ear{i}", "{pre}Ear{i}"),
    "hair": ("hair_{i:02d}", "Hair{i}", "Hair{i}"),
    "wing": ("wing_{i:02d}{sfx}", "{pre}Wing{i}", "{pre}Wing{i}"),
}
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
UNITY_SEGMENTS = ("Proximal", "Intermediate", "Distal")
GODOT_SEGMENTS = {"thumb": ("Metacarpal", "Proximal", "Distal")}
for _finger in FINGERS:
    _word = "Little" if _finger == "pinky" else _finger.title()
    PARTS[_finger] = (_finger + "_{i:02d}{sfx}",
                      tuple("{pre}" + _word + s for s in UNITY_SEGMENTS),
                      tuple("{pre}" + _word + s for s in GODOT_SEGMENTS.get(_finger, UNITY_SEGMENTS)))
# the parts every humanoid game rig has: each (part, side, number) must give a different name in every engine
CORE_PARTS = ("root", "pelvis", "spine", "neck", "head", "clavicle", "upperarm", "lowerarm", "hand", "thigh", "calf",
              "foot", "toes") + FINGERS


def game_name(engine, part, side="", index=1):
    """The engine's name for logical `part` (side 'L' / 'R' / '', number from 1), or None when the engine keeps the
    source name (Generic) or the part is unknown."""
    template = PARTS.get(part, (None,) * 3)[COLUMN[engine]] if engine in COLUMN else None
    if template is None:
        return None
    pre, sfx = SIDE_TOKENS[engine][side]
    if isinstance(template, tuple):         # more bones than the engine has names: Spine4, Neck2
        template = template[index - 1] if index <= len(template) else "{pre}" + part.title() + "{i}{sfx}"
    return template.format(i=index, pre=pre, sfx=sfx)


# ---------------------------------------------------------------- rig bone names (docs/BONE_NAMES.md)
SIDES = ('L', 'R')
SIDE_WORDS = {'L': 'Left', 'R': 'Right'}    # for people (collection titles); bones never use them
ROOT = 'Root'
Parsed = namedtuple('Parsed', 'role part number side')

ROLE_PREFIX = re.compile(r'^(?:(MCH|ORG|DEF)[-_.]|(IK|FK|TWK|WGT)-)')
SIDE_WORD = re.compile(r'Left|Right')
SIDE_TAG = re.compile(r'[._\-]([LlRr])(?=[._\-\d]|$)')     # .L  _l  -r  and .L.001
DOTTED = re.compile(r'(.*?)(\d*)\.(\d+)$')                 # Blender's Hair.005, Ear1.002
TRAILING_NUMBER = re.compile(r'(.*?\D)(\d+)$')

# Old name (side and role off) -> standard name, first the exact ones
OLD_WORDS = {
    'Main': 'Root', 'Master': 'Root', 'root': 'Root', 'Hips': 'Pelvis', 'pelvis': 'Pelvis', 'torso_pelvis': 'Pelvis',
    'Spine': 'Spine1', 'torso_1': 'Spine1', 'torso_2': 'Spine2', 'torso_3': 'Chest', 'torso_chest_lower': 'Spine2',
    'torso_chest_upper': 'Chest', 'neck': 'Neck',
    'Arm': 'Upperarm', 'UpperArm': 'Upperarm', 'arm_1': 'Upperarm', 'arm_upper_arm': 'Upperarm', 'arm_2': 'Forearm1',
    'arm_forarm_1': 'Forearm1', 'arm_3': 'Forearm2', 'arm_forarm_2': 'Forearm2',
    'Leg1': 'Shin', 'Leg2': 'Hock', 'LowerLeg': 'Shin', 'LowerLeg1': 'Shin', 'LowerLeg2': 'Hock', 'leg_1': 'Thigh',
    'leg_2': 'Shin', 'heel': 'Hock', 'leg_thigh': 'Thigh', 'leg_shin': 'Shin', 'leg_heal': 'Hock',
    'eye_iris': 'Iris', 'eye_pupil': 'Pupil', 'eye_puipl': 'Pupil', 'foot_toes': 'Toes',
    'HandIK': 'IK-Hand', 'FootIK': 'IK-Foot', 'HockIK': 'IK-Hock', 'HeadIK': 'IK-Head', 'ChestIK': 'IK-Chest',
    'LegIK': 'IK-Pole-Knee', 'KneeIK': 'IK-Pole-Knee', 'ElbowIk': 'IK-Pole-Elbow', 'ElbowIK': 'IK-Pole-Elbow',
    'Tongue_Master': 'TongueBase', 'TongueMaster': 'TongueBase', 'Tongue_Tip': 'TongueTip', 'MouthJawZip': 'DEF-MouthJawZip',
}
OLD_PATTERNS = [        # (old, standard), in order, on the name with side and role off
    (r'_+ik(?=[A-Z\d_]|$)', 'IK'),                           # foot_ik, foot_ikTarget, leg_ik2_1
    (r'(?:(?:pointer|index)_finger_|finger_pointer|IndexFinger)_?(\d)', r'Index\1'),
    (r'(?:middle_finger_|finger_middle|MiddleFinger)_?(\d)', r'Middle\1'),
    (r'(?:ring_finger_|finger_ring|RingFinger)_?(\d)', r'Ring\1'),
    (r'(?:pinky_finger_|finger_small|LittleFinger)_?(\d)', r'Pinky\1'),
    (r'toe_big', 'BigToe'), (r'toe_index', 'SecondToe'), (r'toe_middle', 'MiddleToe'), (r'toe_little', 'LittleToe'),
    (r'Brest', 'Breast'), (r'EyebrowB(?=\d)', 'EyebrowSeg'), (r'IKRoll', 'Roll'),
    (r'IK(\d)_(\d)$', r'IK\1Seg\2'),
]
# Bones the face and limb tools make: (pattern on the Pascal name, role). The part keeps its name.
OLD_ROLES = [(r'.*Seg\d+', 'DEF'), (r'LidRing\d+', 'DEF'), (r'SnarlLift|PuffSwell', 'DEF'),
             (r'.*Roll(Heel|Tip|Ball|Counter)|.*IKTarget', 'MCH')]
PLAIN_PARTS = re.compile(r'(Upperarm|Forearm|Thigh|Shin|Hock|Hand|Foot|Toes|Eye)\d*')
STANDARD_TEXT = re.compile(r'[A-Za-z0-9-]+(\.[LR])?')
LID_TIP = re.compile(r'Lid((?:Inner|Outer)|(?:Upper|Lower)\d+)$')
# Deforming face helpers that were MCH- until 2026-11-16 and are DEF- now (part with side off): old rigs read as the new name
NOW_DEFORM = re.compile(r'MouthJawZip')
# Lid tips: DEF- with Pivots lids (they deform), MCH- with Ring lids (the ring deforms). An MCH- tip that deforms is an
# old Pivots one: only the Deform flag tells (text alone keeps it)
LID_TIP_NAME = re.compile(r'LidTip(?:Inner|Outer|(?:Upper|Lower)\d+)')


def split_role(name):
    """('MCH', 'LeftLidUpper1') from 'MCH-LeftLidUpper1'; ('', name) without a prefix."""
    m = ROLE_PREFIX.match(name)
    return (m.group(1) or m.group(2), name[m.end():]) if m else ('', name)


def side_of(name):
    """'L', 'R' or '' for a name of any style."""
    m = SIDE_WORD.search(name)
    if m:
        return m.group(0)[0]
    m = SIDE_TAG.search(name)
    return m.group(1).upper() if m else ''


def strip_side(name):
    """The name without its side, any style: 'LeftArm', 'arm.L', 'arm_l' -> 'Arm', 'arm', 'arm'."""
    return SIDE_TAG.sub('', SIDE_WORD.sub('', name), 1)


def flip(name):
    """The other side's name, same style: 'Hand.L' <-> 'Hand.R', 'LeftArm' <-> 'RightArm', 'arm_l' <-> 'arm_r'."""
    if SIDE_WORD.search(name):
        return SIDE_WORD.sub(lambda m: 'Right' if m.group(0) == 'Left' else 'Left', name)
    m = SIDE_TAG.search(name)
    if not m:
        return name
    swap = {'L': 'R', 'R': 'L', 'l': 'r', 'r': 'l'}
    return name[:m.start(1)] + swap[m.group(1)] + name[m.end(1):]


def with_side(name, side):
    """`name` on `side` ('L' / 'R'), same style. A centre name stays as it is."""
    return flip(name) if side_of(name) not in ('', side) else name


def build(part, side='', number=None, role=''):
    """A standard name: build('Forearm', 'L', 1) -> 'Forearm1.L', build('Hand', 'L', role='IK') -> 'IK-Hand.L'."""
    return (f'{role}-' if role else '') + part + ('' if number is None else str(number)) + (f'.{side}' if side else '')


def left(part, role=''):
    return build(part, 'L', role=role)


def pascal(text):
    """'hock_target' -> 'HockTarget'. Letters inside a word stay: 'legIK2' -> 'LegIK2'."""
    return ''.join(w[:1].upper() + w[1:] for w in re.split(r'[_\s]+', text) if w)


def chain_number(stem, own, dot):
    """Chain index of a dotted old name: Hair.005 -> 5, Ear1.002 -> 3, Brest.001 -> 2 (Brest itself is the first)."""
    if own:
        return int(own) + int(dot)
    return int(dot) if stem.lower().startswith('hair') else 1 + int(dot)


def standard_core(rest):
    """(role, Pascal part + number) of an old name with side and role off."""
    if rest in OLD_WORDS:
        role, core = split_role(OLD_WORDS[rest])
        return role, core
    number = ''
    rest = rest.replace('.IK', '_IK')
    m = DOTTED.fullmatch(rest)
    if m:
        rest, number = m.group(1), str(chain_number(m.group(1), m.group(2), m.group(3)))
        if rest in OLD_WORDS:
            rest = OLD_WORDS[rest]
    for old, new in OLD_PATTERNS:
        rest = re.sub(old, new, rest)
    tweak = re.fullmatch(r'(.*?)_?Tweak(\d+)', rest)
    if tweak:
        shift = 1 if tweak.group(1) == 'Tongue' else 0       # Tongue_Tweak0 is the first tongue tweak
        return 'TWK', f'{pascal(tweak.group(1))}{int(tweak.group(2)) + shift}'
    pole = re.fullmatch(r'(.*?)_?(?:[Pp]oll|[Pp]ole)', rest)
    if pole:
        return 'IK', f'Pole-{pascal(pole.group(1))}{number}'
    ik = re.fullmatch(r'(.+?)_?IK', rest)
    if ik:
        word = pascal(ik.group(1))
        return 'IK', ('Pole-' if word in ('Knee', 'Elbow') else '') + word + number
    core = pascal(rest.replace('-', '_').replace('.', '_')) + number
    role = next((r for pattern, r in OLD_ROLES if re.fullmatch(pattern, core)), '')
    return role, core


def standard(name, home=None, deform=False):
    """The docs/BONE_NAMES.md name of a bone of any style; a standard name comes back as it is. Pure text, plus what
    only the rig knows when given: `home` = its bone collection, `deform` = its Deform flag (a hidden bone gets `MCH-`,
    a deform-only one `DEF-`, a deforming `MCH-` lid tip `DEF-`)."""
    role, rest = split_role(name)
    side = side_of(rest)
    if role == 'MCH' and (NOW_DEFORM.fullmatch(strip_side(rest)) or deform and LID_TIP_NAME.fullmatch(strip_side(rest))):
        return 'DEF-' + rest
    if is_standard_text(role, rest):
        return name
    role = '' if role == 'ORG' else role
    word_role, core = standard_core(strip_side(rest))
    if not role and not word_role and LID_TIP.fullmatch(core):      # the tip of a lid pivot (MCH-LidUpper1.L): deforms, or
        word_role = 'MCH' if home == 'Mechanism' and not deform else 'DEF'     # Ring lids' mechanism
        core = 'LidTip' + LID_TIP.fullmatch(core).group(1)
    role = role or word_role
    if not role:
        role = hidden_role(core, home, deform)
    return build(core, side, role=role)


def hidden_role(core, home, deform):
    """The role a hidden bone gets from the rig. A limb or eye bone stays plain: it is the FK control too."""
    if home == 'Mechanism':
        return 'MCH'
    return 'DEF' if deform and home is None and not PLAIN_PARTS.fullmatch(core) else ''


def is_standard_text(role, rest):
    """A role prefix on a name already in the standard's form: nothing to convert."""
    if not role or role == 'ORG' or not STANDARD_TEXT.fullmatch(rest) or SIDE_WORD.search(rest):
        return False
    return role != 'MCH' or rest[0].isupper()


def is_standard(name):
    """The name is already what the standard says (text only; the rig can still want a role on it)."""
    return standard(name) == name


def parse(name):
    """Parsed(role, part, number, side) of a name of any style, read as its standard name:
    parse('LeftForearm1') == parse('Forearm1.L') == Parsed('', 'Forearm', 1, 'L')."""
    role, rest = split_role(standard(name))
    side = side_of(rest)
    rest = strip_side(rest)
    m = TRAILING_NUMBER.fullmatch(rest)
    return Parsed(role, m.group(1), int(m.group(2)), side) if m else Parsed(role, rest, None, side)


def with_role(name, role):
    """The same part with another role: with_role('UpperLipMid.L', 'MCH') -> 'MCH-UpperLipMid.L'."""
    b = parse(name)
    return build(b.part, b.side, b.number, role)


def mch(name):
    """The mechanism bone of a bone. A lid tip's is its pivot in the eye centre: 'DEF-LidTipUpper1.L' -> 'MCH-LidUpper1.L'."""
    return with_role(name, 'MCH').replace('LidTip', 'Lid')


def helper(control, job):
    """Mechanism bone of an IK control, any style of control: helper('IK-Foot.L', 'Parent') -> 'MCH-FootIKParent.L',
    helper('IK-Foot.L', 'RollHeel') -> 'MCH-FootRollHeel.L'."""
    b = parse(control)
    ik = 'IK' if b.role == 'IK' and not job.startswith('Roll') else ''
    return build(b.part + ('' if b.number is None else str(b.number)) + ik + job, b.side, role='MCH')


def find(names, name):
    """The name in `names` of the bone called `name` in any style, or None: 'IK-Foot.L' finds 'foot_ik_l'."""
    if name in names:
        return name
    want = standard(name).lower()
    return next((n for n in names if standard(n).lower() == want), None)


def plain(name):
    """Lower-case name without role prefix, side or separators: 'MCH-upper_arm.L.001' -> 'upperarm001'."""
    return re.sub(r'[^a-z0-9]', '', strip_side(ROLE_STRIP.sub('', name)).lower())


ROLE_STRIP = re.compile(r'^(?:(?:MCH|ORG|DEF)[-_.]|(?:FK|TWK|WGT)-)')


def bare_stem(name):
    """Plain name without digits: 'Index1' and 'Index2' share the stem 'index'."""
    return re.sub(r'\d', '', plain(name))


def has_side(name):
    return side_of(name) != ''


def is_helper(name):
    """A bone nobody poses by its role: mechanism or deform."""
    return split_role(name)[0] in ('MCH', 'ORG', 'DEF')


def rename_plan(bones):
    """Old name -> standard name for a rig, and the clashes. `bones`: {name: (home collection or None, deform flag)}.
    Returns (renames, clashes): renames holds only names that change, clashes {new name: [old names]}.
    A lone first bone of a chain gets its number (Neck + Neck2 -> Neck1)."""
    new = {n: standard(n, *info) for n, info in bones.items()}
    taken = set(new.values())
    for old, name in new.items():
        b = parse(name)
        second = build(b.part, b.side, 2, b.role)
        if old != name and b.number is None and second in taken and build(b.part, b.side, 1, b.role) not in taken:
            new[old] = build(b.part, b.side, 1, b.role)
    counts = Counter(new.values())
    clashes = {n: sorted(o for o, x in new.items() if x == n) for n, c in counts.items() if c > 1}
    return {o: n for o, n in new.items() if o != n}, clashes


def replace_names(text, table):
    """Bone names in a text (a Limb JSON, a data path) replaced by `table`, whole names only."""
    if not table:
        return text
    keys = sorted(table, key=len, reverse=True)
    rx = re.compile(r'(?<![\w.\-])(' + '|'.join(map(re.escape, keys)) + r')(?![\w.\-])')
    return rx.sub(lambda m: table[m.group(1)], text)


def guide_name(name, side):
    """Guide bones of the face rigs (Library/FaceRigs.blend) keep their own style: `LidUpper1`, `RightLidUpper1`."""
    return ('Right' + name) if side == 'R' else name


def guide_base(name):
    """(base name, side) of a guide bone."""
    return (name[5:], 'R') if name.startswith('Right') else (name, 'L')


# ---------------------------------------------------------------- a whole rig's L/R style (charfix audits any rig: `L_arm`, `arm left`)
# (left token, right token, where)  where: start / end / any
CONVENTIONS = [
    ('Left', 'Right', 'any'), ('left', 'right', 'any'), ('LEFT', 'RIGHT', 'any'),
    ('.L', '.R', 'end'), ('_L', '_R', 'end'), ('.l', '.r', 'end'), ('_l', '_r', 'end'),
    ('-L', '-R', 'end'), (' L', ' R', 'end'),
    ('.L.', '.R.', 'any'), ('_L_', '_R_', 'any'), ('_L.', '_R.', 'any'), ('.L_', '.R_', 'any'),
    ('L_', 'R_', 'start'), ('l_', 'r_', 'start'), ('L.', 'R.', 'start'), ('Left_', 'Right_', 'start'),
]


def _swap(name, a, b, where):
    if where == 'start':
        return b + name[len(a):] if name.startswith(a) else None
    if where == 'end':
        return name[:-len(a)] + b if name.endswith(a) else None
    # only the first side token counts: LeftEyeRightB <-> RightEyeRightB
    m = re.search(re.escape(a) + '|' + re.escape(b), name)
    if not m or m.group(0) != a:
        return None
    return name[:m.start()] + b + name[m.end():]


def _convs(conv):
    """A naming is a list of conventions (rigs can mix Left/Right and _l/_r)."""
    if not conv:
        return []
    return [conv] if isinstance(conv[0], str) else list(conv)


def _side1(name, conv):
    left, right, where = conv
    if _swap(name, left, right, where):
        return 'L'
    if _swap(name, right, left, where):
        return 'R'
    return None


def matching_convention(name, conv):
    return next((c for c in _convs(conv) if _side1(name, c)), None)


def side_under(name, conv):
    """'L', 'R' or None for a bone name under the naming conv."""
    c = matching_convention(name, conv)
    return c and _side1(name, c)


def mirror_under(name, conv):
    """The other side's name under the naming conv, or None."""
    c = matching_convention(name, conv)
    if not c:
        return None
    left, right, where = c
    if _side1(name, c) == 'R':
        left, right = right, left
    return _swap(name, left, right, where)


def detect_convention(names, cfg=None, min_pairs=2):
    """Naming = every convention with at least min_pairs L/R pairs in names, most
    pairs first (or the configured list)."""
    if cfg and cfg.get('naming'):
        return [tuple(n) for n in cfg['naming']]
    names = set(names)
    found = []
    for conv in CONVENTIONS:
        n = sum(1 for x in names if _side1(x, conv) == 'L' and _swap(x, conv[0], conv[1], conv[2]) in names)
        if n >= min_pairs:
            found.append((n, conv))
    found.sort(key=lambda x: -x[0])
    return [c for _, c in found]


def convention_label(conv):
    labels = []
    for left, right, where in _convs(conv):
        labels.append({'start': f'{left}x/{right}x prefix', 'end': f'x{left}/x{right} suffix'}.get(where, f'{left}/{right} anywhere'))
    return ' + '.join(labels) or None


def lr_pairs(names, conv):
    names = set(names)
    return [(n, mirror_under(n, conv)) for n in sorted(names)
            if conv and side_under(n, conv) == 'L' and mirror_under(n, conv) in names]
