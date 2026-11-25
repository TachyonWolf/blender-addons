# SPDX-License-Identifier: GPL-3.0-or-later
"""Full Character Rig: the one place for its options. Plain data (no bpy), used by the Full Character Rig card
(full_rig_ui.py), full_rig.py and the tests. Each tooltip teaches what the option does for posing or animating.

Every option has a `target`: the module and config key it sets. config_for() splits a values dict into one config
dict per module, so the builders never read the card's settings directly.
"""
from collections import namedtuple

PRESETS = ('LEAN', 'EVERYTHING')
PRESET_LABELS = {'LEAN': "Lean", 'EVERYTHING': "Everything"}
GROUPS = ('Body', 'Face', 'Parts')
KINDS = ('bool', 'enum', 'int')

# module -> the config keys it accepts from this table (face keys are face_rig_core's own; the new ones land in P3)
TARGET_KEYS = {
    'body_rig': {'face', 'leg_type', 'fingers', 'toes', 'spine_bones', 'neck_bones', 'spine_ik', 'neck_ik', 'head_aim',
                 'lock_movement', 'hand_spread', 'hand_fist', 'fist_thumb', 'bendy_limbs'},
    'limb_rig': {'stretch', 'parent_switch'},
    'face_rig_core': {'brows', 'brow_tweaks', 'lashes', 'lid_mode', 'pivots', 'lid_tweaks', 'lid_twist', 'lid_push',
                      'zipper', 'mouth_sliders', 'tongue_rig', 'snarl', 'smile_cheeks', 'puff'},
    'part_chains': {'tail', 'ear_type', 'tail_tweaks', 'ear_tweaks', 'hair', 'hair_tweaks', 'breasts', 'breast_bones', 'butt'},
}

# Face choices: the face rig each one builds and the defaults it sets (the user can change each afterwards). `guides`:
# body guide defaults (snout = the body's Snout bone; tail and ears are their own choices). `ears`: the Ears type the
# card's Ears toggle switches on when no type was chosen yet.
FACES = {
    'SNOUT': dict(label="Snout", guides=dict(snout=True), ears='SHORT',
                  options=dict(pivots='12', tongue_rig=True),
                  tip="An animal face: the mouth sits on a snout with its own bend, nose, snarl and puff controls."),
    'HUMAN': dict(label="Human", guides=dict(snout=False), ears='HUMAN',
                  options=dict(pivots='8', tongue_rig=False, snarl=False, puff=False),
                  tip="A flat human face: eyes, lids, brows, jaw and lips, no snout. Lighter lids, no tongue by default."),
}
LEGACY_BENDY = {True: 'BOTH', False: 'OFF'}         # the old on / off Bendy Limbs -> the limbs it meant
LEGACY_TEMPLATES = {'ANTHRO': 'SNOUT', 'HUMAN': 'HUMAN'}       # the old Template option -> the Face it meant

# (value, label, tooltip) choices of the enum options
LEG_TYPES = (('PLANTIGRADE', "Plantigrade", "Walks on the whole foot, like a person. Simple to pose: heel, ball and toes roll."),
             ('DIGITIGRADE', "Digitigrade", "Walks on the toes with the heel raised (a dog or cat leg). Adds a hock joint with its own control."))
DIGIT_COUNTS = (('1', "1", "1 Basic: one bone for the whole hand or foot, like a mitten. Fastest to pose and animate."),
                ('4', "4", "4 Fursuit: four fingers or toes (thumb included), the cartoon and fursuit hand."),
                ('5', "5", "5 Normal: five fingers or toes, as on a human."))
TOE_COUNTS = (('1', "1", DIGIT_COUNTS[0][2]),
              ('3', "3", "3 Digit: Big, Second and Little toe, two bones each."),
              DIGIT_COUNTS[1], DIGIT_COUNTS[2])
TOE_COUNT_VALUES = tuple(int(c[0]) for c in TOE_COUNTS)
SPINE_COUNTS = (('1', "1", "One spine bone between pelvis and chest: stiff, good for simple or chibi characters."),
                ('2', "2", "Two spine bones: a natural bend. The usual choice."),
                ('3', "3", "Three spine bones: a longer, more flexible back."))
FIST_THUMBS = (('CURLS', "Curls", "The thumb closes with the fist: it drops across the palm and curls over the fingers."),
               ('SEPARATE', "Separate", "The fist curls only the fingers; you pose the thumb on its own."))
NECK_COUNTS = (('1', "1", "One neck bone: a short, stiff neck."),
               ('2', "2", "Two neck bones: a natural bend. The usual choice."),
               ('3', "3", "Three neck bones: a long, bendy neck, for giraffes and dragons."))
LID_MODES = (('PIVOTS', "Pivots", "The lid pivot bones deform the lids directly."),
             ('RING', "Ring", "A ring of stretchy bones deforms the lids: smoother, but heavier. Experimental."))
PIVOT_COUNTS = (('8', "8", "Fewer lid pivots: lighter, fine for small eyes."),
                ('12', "12", "The default; enough for most eyes."),
                ('16', "16", "More pivots for big eyes, so blinks stay smooth."))
EAR_TYPES = (('NONE', "None", "No ear bones: the ears move with the head."),
             ('HUMAN', "Human", "One small bone per ear, for a little wiggle. Fine for people and elves."),
             ('SHORT', "Short", "Two bones per ear: upright ears that turn and bend, like a cat's or a wolf's."),
             ('LONG', "Long", "Three bones per ear and a Droop slider: floppy ears that fold, like a dog's."),
             ('EXTREME', "Extreme", "Five bones per ear and a Droop slider: very long ears that bend and flop, like a bunny's."))
BENDY_LIMBS = (('OFF', "Off", "No bendy limbs: crisp elbows and knees."),
               ('LEGS', "Legs", "Bendy thighs and shins only."),
               ('ARMS', "Arms", "Bendy upper arms and forearms only."),
               ('BOTH', "Both", "Bendy arms and legs."))


def bendy_mode(value):
    """A Bendy Limbs value as its choice: the old True / False become Both / Off."""
    return LEGACY_BENDY.get(value, str(value)) if isinstance(value, bool) else str(value)


FACE_CHOICES = tuple((k, v['label'], v['tip']) for k, v in FACES.items())

Option = namedtuple('Option', 'id label tooltip group kind target default choices cast limits', defaults=(None,))


def _o(id, label, group, target, lean, everything, tooltip, choices=None, cast=str, limits=None):
    """One option; `limits` (min, max) makes it a whole number."""
    module, key = target
    kind = 'enum' if choices else 'int' if limits else 'bool'
    return Option(id, label, tooltip, group, kind, (module, key), {'LEAN': lean, 'EVERYTHING': everything}, choices,
                  cast if choices else int if limits else bool, limits)


OPTIONS = (
    # ---- Body
    _o('face', "Face", 'Body', ('body_rig', 'face'), 'SNOUT', 'SNOUT',
       "Snout builds an animal face with a muzzle; Human builds a flat face without one. Both get eyes, lids, brows, jaw "
       "and lips.", FACE_CHOICES),
    _o('leg_type', "Leg Type", 'Body', ('body_rig', 'leg_type'), 'DIGITIGRADE', 'DIGITIGRADE',
       "Plantigrade legs rest on the whole foot; digitigrade legs stand on the toes with a hock. Pick what your "
       "character's legs look like.", LEG_TYPES),
    _o('fingers', "Fingers", 'Body', ('body_rig', 'fingers'), '4', '4',
       "How many fingers each hand gets. Fewer bones mean less to pose; 1 is a mitten you open and close with one control.",
       DIGIT_COUNTS, int),
    _o('toes', "Toes", 'Body', ('body_rig', 'toes'), '1', '4',
       "How many toes each foot gets. With 1 the foot has a single Toes bone, which is all foot roll needs.",
       TOE_COUNTS, int),
    _o('spine_bones', "Spine Bones", 'Body', ('body_rig', 'spine_bones'), '2', '2',
       "How many bones the back has between pelvis and chest. More bones bend in a smoother curve but take more posing.",
       SPINE_COUNTS, int),
    _o('neck_bones', "Neck Bones", 'Body', ('body_rig', 'neck_bones'), '2', '2',
       "How many bones the neck has between chest and head. More bones bend in a smoother curve.", NECK_COUNTS, int),
    _o('spine_ik', "Spine IK", 'Body', ('body_rig', 'spine_ik'), True, True,
       "Drag one chest control and the whole spine bends in a curve to follow it. Quick for big poses and leaning."),
    _o('neck_ik', "Neck IK", 'Body', ('body_rig', 'neck_ik'), True, True,
       "Move one head control and the neck bends to follow it; turn it to turn the head. IK | FK on the Head page "
       "switches to posing the neck bones one by one."),
    _o('head_aim', "Head Aim", 'Body', ('body_rig', 'head_aim'), True, True,
       "The head turns to look at a target you move (Head Aim slider, starts at 1). Animate where the character looks "
       "instead of rotating the neck."),
    _o('stretch_limbs', "Stretchy Limbs", 'Body', ('limb_rig', 'stretch'), False, True,
       "Arms and legs stretch past their full length to reach the IK control (Stretch slider on the hand and foot controls, starts at 1; 0 = off)."),
    _o('parent_switch', "Parent Switch", 'Body', ('limb_rig', 'parent_switch'), False, True,
       "A hand or foot control can follow the Root, Pelvis, Chest or Head. Use it to pin a hand to a wall or make it ride the body."),
    _o('lock_movement', "Lock Movement", 'Body', ('body_rig', 'lock_movement'), True, True,
       "Controls that only turn (spine, neck, head, FK arms and legs, fingers, toes) can't be moved by accident. Root, "
       "Pelvis, Shoulder, Hip and the IK controls still move; unlock a bone's padlock in the N panel to adjust it."),
    _o('hand_spread', "Hand Spread", 'Body', ('body_rig', 'hand_spread'), False, True,
       "One control at the knuckles fans all fingers open or closed. Each finger keeps its own curl on top."),
    _o('hand_fist', "Fist Control", 'Body', ('body_rig', 'hand_fist'), False, True,
       "Turn the knuckle control down to curl every finger into a fist, up to open the hand. Each finger keeps its own curl on top."),
    _o('fist_thumb', "Fist Thumb", 'Body', ('body_rig', 'fist_thumb'), 'CURLS', 'CURLS',
       "Whether the thumb closes with the fist or stays for you to pose. Needs Fist Control.", FIST_THUMBS),
    _o('bendy_limbs', "Bendy Limbs", 'Body', ('body_rig', 'bendy_limbs'), 'OFF', 'BOTH',
       "Rubber-hose limbs: a tweak in the middle of each limb part bows it in a smooth curve, and the Rubber Hose "
       "slider rounds the elbow and knee. Pick which limbs get it.", BENDY_LIMBS, bendy_mode),
    # ---- Face
    _o('brows', "Brows", 'Face', ('face_rig_core', 'brows'), True, True,
       "Eyebrow controls (inner, middle, outer) for angry, sad and surprised looks."),
    _o('brow_tweaks', "Brow Tweaks", 'Face', ('face_rig_core', 'brow_tweaks'), False, True,
       "Small extra controls along each eyebrow to shape its curve. Use for fine acting; skip for simple characters."),
    _o('lashes', "Lashes", 'Face', ('face_rig_core', 'lashes'), True, True,
       "Eyelashes swing and tilt with the lids. Switches itself off when the character has no lash mesh."),
    _o('lid_mode', "Lid Deformation", 'Face', ('face_rig_core', 'lid_mode'), 'PIVOTS', 'PIVOTS',
       "How the eyelids deform: Pivots (reliable) or Ring (a stretchy bone ring, smoother but experimental).", LID_MODES),
    _o('pivots', "Lid Pivots", 'Face', ('face_rig_core', 'pivots'), '12', '12',
       "How many pivot bones each eye's lids have. More pivots keep big eyes smooth while blinking.", PIVOT_COUNTS, int),
    _o('lid_tweaks', "Lid Tweaks", 'Face', ('face_rig_core', 'lid_tweaks'), False, True,
       "Small controls along each lid to shape its line, for squints and sleepy eyes."),
    _o('lid_twist', "Lid Twist", 'Face', ('face_rig_core', 'lid_twist'), False, True,
       "Twisting a lid control turns that part of the lid around it, to tilt a lid edge for expressions."),
    _o('lid_push', "Lid Push", 'Face', ('face_rig_core', 'lid_push'), False, True,
       "The lids stretch forward a little as the upper lid closes, so a blink wraps over the eyeball instead of cutting through it."),
    _o('zipper', "Lip Zipper", 'Face', ('face_rig_core', 'zipper'), False, True,
       "A zip slider seals the lips shut from the corners inward. Handy for closed or smiling mouths that must stay sealed."),
    _o('mouth_sliders', "Mouth Sliders", 'Face', ('face_rig_core', 'mouth_sliders'), False, True,
       "Sliders for lip roll, sliding the mouth corners and stretching a wide maw. Extra control for big expressions."),
    _o('tongue_rig', "Tongue", 'Face', ('face_rig_core', 'tongue_rig'), True, True,
       "A bendy tongue you can curl and stick out. Switches itself off when the character has no tongue mesh."),
    _o('snarl', "Nostrils & Snarl", 'Face', ('face_rig_core', 'snarl'), False, True,
       "Nostril flare and a snarl slider that lifts the upper lip and wrinkles the nose. Needs snout guides."),
    _o('smile_cheeks', "Cheeks", 'Face', ('face_rig_core', 'smile_cheeks'), False, True,
       "The cheeks lift and bunch when the mouth corners smile, so smiles look natural without extra posing."),
    _o('puff', "Cheek Puff", 'Face', ('face_rig_core', 'puff'), False, True,
       "A slider that puffs the cheeks out, for blowing, holding breath or stuffing the mouth."),
    # ---- Parts
    _o('tail', "Tail", 'Parts', ('part_chains', 'tail'), True, True,
       "A bendy tail. Its guide is three points (Base, Mid, Tip) you drag, so curled tails work too."),
    _o('ear_type', "Ears", 'Parts', ('part_chains', 'ear_type'), 'SHORT', 'SHORT',
       "What kind of ears to rig: more bones for longer ears. Long and Extreme ears get a Droop slider.", EAR_TYPES),
    _o('tail_tweaks', "Tail Tweaks", 'Parts', ('part_chains', 'tail_tweaks'), False, True,
       "Extra controls along the tail for hand-shaping its curve. Without them you pose the main controls only."),
    _o('ear_tweaks', "Ear Tweaks", 'Parts', ('part_chains', 'ear_tweaks'), False, True,
       "Extra controls along each ear for bends and flops. Useful for expressive ears."),
    _o('hair', "Hair", 'Parts', ('part_chains', 'hair'), False, True,
       "A bendy hair chain (a ponytail or a long lock) from the back of the head. Its guide is three points (Base, Mid, "
       "Tip) that start behind the head: drag them onto the hair."),
    _o('hair_tweaks', "Hair Tweaks", 'Parts', ('part_chains', 'hair_tweaks'), False, True,
       "Extra controls along the hair chain for hand-shaping its curve."),
    _o('breasts', "Breasts", 'Parts', ('part_chains', 'breasts'), False, True,
       "Bones for each breast, so they can be posed and given jiggle."),
    _o('breast_bones', "Breast Bones", 'Parts', ('part_chains', 'breast_bones'), 1, 1,
       "Bones per breast, 1 to 4. With 2 or more the breast follows a curved guide (Base, Mid, Tip) and gets a Droop slider "
       "that tips it down.", limits=(1, 4)),
    _o('butt', "Butt", 'Parts', ('part_chains', 'butt'), False, True,
       "Bones for each cheek of the butt, so they can be posed and given jiggle."),
)
BY_ID = {o.id: o for o in OPTIONS}


def options(group=None):
    """All options (table order), or one group's."""
    return [o for o in OPTIONS if group in (None, o.group)]


def preset(name):
    """{option id: value} for 'LEAN' or 'EVERYTHING'."""
    if name not in PRESETS:
        raise KeyError(f'unknown preset {name!r}')
    return {o.id: o.default[name] for o in OPTIONS}


def face_guides(name):
    """The body guide defaults of a Face choice: snout."""
    return dict(FACES[name]['guides'])


def face_options(name):
    """The option values a Face choice sets (lid pivots, tongue ...)."""
    return dict(FACES[name]['options'])


def face_ears(name):
    """The Ears type a Face choice starts with (Short for Snout, Human for Human)."""
    return FACES[name]['ears']


def upgrade(values):
    """Option values stored by an older version: the old Template becomes the Face, ids no longer in the table go
    (Tail IK, 2026-11-16: the tail and ears always have an IK/FK switch now; Wings, Wing Type, Fin Spokes, 2026-11-17:
    wings are added with Add Rig Component); Bendy Limbs True / False becomes Both / Off."""
    values = dict(values or {})
    if 'template' in values:
        values.setdefault('face', LEGACY_TEMPLATES.get(values['template'], 'SNOUT'))
    if 'bendy_limbs' in values:                          # Bendy Limbs was on / off before it chose limbs
        values['bendy_limbs'] = bendy_mode(values['bendy_limbs'])
    return {k: v for k, v in values.items() if k in BY_ID}


def full_values(values):
    """Every option: the given values (upgraded) over the Face choice's defaults over the Lean preset."""
    values = upgrade(values)
    face = values.get('face', preset('LEAN')['face'])
    return {**preset('LEAN'), **face_options(face), **values}


def config_for(values):
    """Split {option id: value} into {module: {config key: value}} (enum values cast to what the builder wants)."""
    out = {}
    for id, value in values.items():
        o = BY_ID.get(id)
        if o is None:                    # an option an older version had (Knee Follow): the builders ignore it
            continue
        module, key = o.target
        out.setdefault(module, {})[key] = o.cast(value)
    return out


def validate():
    """A list of problems with the table (empty = fine)."""
    problems, seen = [], set()
    for o in OPTIONS:
        if o.id in seen:
            problems.append(f'{o.id}: duplicate id')
        seen.add(o.id)
        if not o.label.strip():
            problems.append(f'{o.id}: no label')
        if not o.tooltip.strip() or not o.tooltip.rstrip().endswith('.') or o.tooltip.count('. ') > 1:
            problems.append(f'{o.id}: tooltip must be one or two sentences ending in a full stop')
        if o.group not in GROUPS:
            problems.append(f'{o.id}: bad group {o.group}')
        if o.kind not in KINDS:
            problems.append(f'{o.id}: bad kind {o.kind}')
        module, key = o.target
        if key not in TARGET_KEYS.get(module, ()):
            problems.append(f'{o.id}: target {module}.{key} is not a known config key')
        if set(o.default) != set(PRESETS):
            problems.append(f'{o.id}: needs a default for every preset')
        for p, value in o.default.items():
            if o.kind == 'bool' and not isinstance(value, bool):
                problems.append(f'{o.id}: {p} default must be True or False')
            if o.kind == 'enum' and value not in [c[0] for c in o.choices or ()]:
                problems.append(f'{o.id}: {p} default {value!r} is not a choice')
        if o.kind == 'int' and not (o.limits and o.limits[0] <= min(o.default.values()) <= max(o.default.values()) <= o.limits[1]):
            problems.append(f'{o.id}: a whole-number option needs limits that hold its defaults')
        if o.kind == 'enum' and not o.choices:
            problems.append(f'{o.id}: enum without choices')
        if o.kind == 'enum' and any(not c[1] or not c[2] for c in o.choices):
            problems.append(f'{o.id}: every choice needs a label and tooltip')
    targets = [o.target for o in OPTIONS]
    for module, keys in TARGET_KEYS.items():
        for key in keys - {k for m, k in targets if m == module}:
            problems.append(f'{module}.{key}: no option sets it')
    for name, face in FACES.items():
        if face['ears'] not in [c[0] for c in EAR_TYPES if c[0] != 'NONE']:
            problems.append(f'face {name}: bad ears {face["ears"]!r}')
        for id, value in face['options'].items():
            o = BY_ID.get(id)
            if o is None or (o.kind == 'enum' and value not in [c[0] for c in o.choices]):
                problems.append(f'face {name}: bad option default {id}={value!r}')
    return problems
