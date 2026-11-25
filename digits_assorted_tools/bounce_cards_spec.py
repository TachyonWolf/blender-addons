# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounce Cards: the one place for names, sliders, defaults, presets and which fields each slider
drives. Plain data (no bpy), used by the builder (Scripts/bounce_cards/build_bounce_cards.py), the
sidebar panel (bounce_cards.py) and the tests. Same pattern as light_rig_spec.py."""

from .light_rig_spec import prop_def

ASSET_NAME = "Bounce Cards"
LIBRARY_FILE = "BounceCards.blend"
ROOT_TAG = "bc_rig"        # on BC_Rig; pointers to the parts are "bc_<part>"
PART_TAG = "bc_part"       # on every rig object: its part name
PARTS = ("card", "light", "focus")
AIM_CONSTRAINT = "Aim at Focus"
SHAPE_KEY = "Curve"       # shape key on the card mesh: edges lifted toward the front
MATERIAL = "Bounce Card"
FOCUS_HEIGHT = 1.0          # BC_Focus height above the ground at the Deploy point (m), like the asset's own
DEPLOY_SIDE, DEPLOY_TOWARD = 1.2, 0.5  # Deploy puts the card this far to the viewer's right and closer to them (m)
WATTS_PER_STRENGTH = 100.0  # Fake light power at Strength 1 (Normalize on: independent of size)

DESCRIPTION = ("Photographer-style bounce card / reflector / flag. Bounce mode: the card really "
               "reflects the scene's light. Fake mode: a soft area light in front of the card (cheap, "
               "works in Eevee and Cycles). Edit it on BC_Rig (Custom Properties or the Bounce Cards "
               "card in Digit's Tools > Setups). Aims at BC_Focus, or at the Lighting Rig's Focus.")
TAGS = ("Light", "Lighting", "Reflector", "Bounce", "Rig")

PROPS = [
    prop_def("Colour", (1.0, 1.0, 1.0), 0.0, 1.0, subtype="COLOR",
             description="Card colour: white, warm gold, cool silver, any colour (a gel)"),
    prop_def("Strength", 1.0, 0.0, 1000.0, (0.0, 10.0),
             description="Fake mode brightness: 1 = a 100 W soft light (size-independent). Bounce mode: "
                         "also how much the card glows when shown to the camera. 0 = a flag (blocks light)"),
    prop_def("Width", 1.0, 0.05, 50.0, (0.1, 4.0), "DISTANCE", "Card width (m)"),
    prop_def("Height", 1.0, 0.05, 50.0, (0.1, 4.0), "DISTANCE", "Card height (m)"),
    prop_def("Curve", 0.0, 0.0, 1.0, description="0 = flat panel, 1 = strongly curved like a reflector disc"),
    prop_def("Softness", 0.5, 0.0, 1.0,
             description="Soft light: how widely the card spreads light (Fake) / how rough its surface "
                         "is (Bounce): 0 = tight and mirror-like, 1 = wide and matte"),
    prop_def("Fake Mode", True, False, True,
             description="On: a soft light in front of the card (cheap). Off: the card really bounces the "
                         "scene's light (physically right, costs render time)"),
    prop_def("Visible To Camera", False, False, True,
             description="Show the card in the render; off = only its light shows"),
    prop_def("Aim At Focus", True, False, True,
             description="Turn the card to face BC_Focus (or the target set by Aim at Light Rig)"),
]
PROP_NAMES = [p["name"] for p in PROPS]
PROP_BY_NAME = {p["name"]: p for p in PROPS}

PRESET_KEYS = ("Colour", "Strength", "Softness", "Curve", "Fake Mode")
PRESETS = {
    "White Card": {"Colour": (1.0, 1.0, 1.0), "Strength": 1.0, "Softness": 0.5, "Curve": 0.0, "Fake Mode": True},
    "Gold Reflector": {"Colour": (1.0, 0.72, 0.32), "Strength": 1.3, "Softness": 0.6, "Curve": 0.25,
                       "Fake Mode": True},
    "Silver Reflector": {"Colour": (0.85, 0.91, 1.0), "Strength": 1.8, "Softness": 0.25, "Curve": 0.35,
                         "Fake Mode": True},
    "Black Flag": {"Colour": (0.01, 0.01, 0.01), "Strength": 0.0, "Softness": 0.5, "Curve": 0.0,
                   "Fake Mode": False},
    "Colour Gel": {"Colour": (0.15, 0.45, 1.0), "Strength": 1.5, "Softness": 0.7, "Curve": 0.0, "Fake Mode": True},
}

PRESET_INFO = {  # hover tooltips
    "White Card": "A plain white card: soft, neutral fill light bounced into shadows. The everyday choice.",
    "Gold Reflector": "A warm gold bounce: adds a sunny glow to skin. Use for warm portraits and sunset looks.",
    "Silver Reflector": "A bright, slightly cool bounce, stronger than white and more focused. Use when you need "
                        "extra punch in the shadows.",
    "Black Flag": "A flag blocks light instead of adding it, making shadows deeper. Use to add contrast or "
                  "to shade the subject from a light.",
    "Colour Gel": "A coloured bounce (blue here) for a tinted accent. Use for mood or a colour contrast.",
}


def preset_items():
    """EnumProperty items for the presets, with tooltips."""
    return [(n, n, PRESET_INFO[n]) for n in PRESETS]


def stored(name, value):
    """A PROPS-unit value as stored in the custom property."""
    return list(value) if isinstance(value, tuple) else value


def driven_fields():
    """[(target, data_path, index, expression, {var: prop name | (prop name, index)})].

    target: "card" (card mesh object), "shape" (its shape keys), "light" (area light data), "material" (the card's node tree),
    "rig" (BC_Rig itself). index -1 = not an array field."""
    principled = 'nodes["Principled BSDF"].inputs'
    colour = [("material", f'{principled}["Base Color"].default_value', i, "c", {"c": ("Colour", i)})
              for i in range(3)]
    emission = [("material", f'{principled}["Emission Color"].default_value', i, "c", {"c": ("Colour", i)})
                for i in range(3)]
    light_colour = [("light", "color", i, "c", {"c": ("Colour", i)}) for i in range(3)]
    return [
        ("card", "scale", 0, "w", {"w": "Width"}),
        ("card", "scale", 1, "h", {"h": "Height"}),
        ("card", "scale", 2, "w", {"w": "Width"}),  # curve depth grows with the width
        ("shape", f'key_blocks["{SHAPE_KEY}"].value', -1, "c", {"c": "Curve"}),
        ("card", "visible_camera", -1, "v", {"v": "Visible To Camera"}),
        ("card", "visible_diffuse", -1, "not fake", {"fake": "Fake Mode"}),   # Fake: no real bounce
        ("card", "visible_glossy", -1, "not fake", {"fake": "Fake Mode"}),
        *colour, *emission,
        ("material", f'{principled}["Roughness"].default_value', -1, "0.08 + 0.92 * soft", {"soft": "Softness"}),
        ("material", f'{principled}["Emission Strength"].default_value', -1, "s * fake * 2.0 if v else 0.0",
         {"s": "Strength", "fake": "Fake Mode", "v": "Visible To Camera"}),
        ("light", "energy", -1, f"s * fake * {WATTS_PER_STRENGTH}", {"s": "Strength", "fake": "Fake Mode"}),
        ("light", "size", -1, "w", {"w": "Width"}),
        ("light", "size_y", -1, "h", {"h": "Height"}),
        ("light", "spread", -1, "(60 + 120 * soft) * pi / 180", {"soft": "Softness"}),
        *light_colour,
        ("rig", f'constraints["{AIM_CONSTRAINT}"].influence', -1, "a", {"a": "Aim At Focus"}),
    ]
