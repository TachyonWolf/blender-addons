# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera Rig: the one place for its deploy presets. Plain data (no bpy), used by the Camera Rig card
(camera_rig.py) and the tests. Each description is a hover tooltip and a short photography lesson."""

ASSET_NAME = "Camera Rig"
LIBRARY_FILE = "CameraRig.blend"
FULL_FRAME = 36.0   # sensor width (mm) of a full-frame camera: the focal lengths below mean what photographers expect

# (id, label, focal length mm, sensor width mm, description)
LENSES = (
    ("ULTRA_WIDE", "14 mm Ultra Wide", 14.0, FULL_FRAME,
     "Takes in a huge view and stretches things near the edges. Use it for tight rooms, big landscapes "
     "and dramatic low angles; keep faces away from the edges."),
    ("WIDE", "24 mm Wide", 24.0, FULL_FRAME,
     "Wide but natural-looking. Good for scenery, interiors and showing a character in their surroundings."),
    ("STORY", "35 mm Story", 35.0, FULL_FRAME,
     "Close to how we see a scene when we take it in. The classic documentary and storytelling lens, "
     "good for a character and some background."),
    ("NORMAL", "50 mm Normal", 50.0, FULL_FRAME,
     "Looks the way the eye sees things, with no stretching. A safe all-round lens for people and objects."),
    ("PORTRAIT", "85 mm Portrait", 85.0, FULL_FRAME,
     "The classic portrait lens. Flatters faces and blurs the background nicely; stand further back."),
    ("TELE", "135 mm Telephoto", 135.0, FULL_FRAME,
     "Compresses distance so the background looks close behind the subject. Use for tight portraits "
     "with a very soft background."),
    ("LONG_TELE", "200 mm Long Tele", 200.0, FULL_FRAME,
     "Strong zoom: flat, stacked-up distances and a very shallow focus. Use it to isolate a subject "
     "far away or to make a crowd look packed."),
    ("MACRO", "100 mm Macro", 100.0, FULL_FRAME,
     "For very close-ups of small things. Focus gets razor thin, so use a small aperture (f/8 or "
     "higher) to keep more of the object sharp."),
    ("CINE_35", "35 mm Cine", 35.0, 24.9,
     "A 35 mm lens on a movie-camera sensor (Super 35), which is smaller than full frame, so it "
     "looks narrower, like about a 50 mm. The standard film look."),
    ("PHONE", "Phone Camera", 6.9, 9.8,
     "A tiny phone sensor with a lens that frames like about 26 mm. Its sensor is so small that "
     "almost everything stays in focus."),
)

# (id, label, f-stop or None for off, description)
DOFS = (
    ("DEEP", "f/16 Deep", 16.0,
     "Almost everything from near to far is sharp. Use for landscapes and architecture; needs lots of light."),
    ("LANDSCAPE", "f/8 Landscape", 8.0,
     "Sharp across a good depth, the sweet spot for most lenses. Use when you want the whole scene "
     "readable but not razor-flat."),
    ("EVERYDAY", "f/5.6 Everyday", 5.6,
     "A balanced look: the subject is clear, the background softens a little. Good for general shots "
     "and groups of people."),
    ("PORTRAIT", "f/2.8 Portrait", 2.8,
     "Sharp subject, clearly blurred background. A wider opening lets in more light and gives more "
     "blur. Good for portraits and character shots."),
    ("DREAMY", "f/1.4 Dreamy", 1.4,
     "Extremely shallow focus: only a thin slice is sharp, the rest melts into soft blur. Lets in "
     "lots of light; use for mood, but aim carefully (eyes first)."),
    ("OFF", "DoF Off", None,
     "Everything is perfectly sharp, like an ideal pinhole camera. Fastest to render; use for flat "
     "graphics or when you don't want any blur."),
)

# (id, label, keyframe interpolation, description)
FOCUS_EASES = (
    ("SMOOTH", "Smooth", 'BEZIER',
     "The focus eases out of the first subject and settles into the second, like a trained focus puller. "
     "Looks natural; use it for most pulls."),
    ("LINEAR", "Linear", 'LINEAR',
     "The focus slides at a constant speed with no easing. Looks mechanical, but is predictable; "
     "use it for a deliberate, even sweep."),
)
FOCUS_PULL_TIP = (
    "A focus pull (rack focus) moves the viewer's attention from one subject to another by sliding which "
    "distance is sharp. It works best at wide apertures (f/1.4 to f/2.8), where the out-of-focus subject is "
    "clearly blurred, so the change reads.")
FOCUS_PULL_FRAMES = 48   # frames from A to B by default: two seconds at 24 fps
DEFAULT_MARGIN = 10.0    # percent of the frame left empty by Frame Subject

# Blender has no golden spiral, so its "camera property" is ours (registered on Camera by composition_overlay)
SPIRAL_PROP = "show_composition_golden_spiral"
SPIRAL_TIP = ("A golden (Fibonacci) spiral fitted to the frame. The spiral leads the eye inward to its tight end. "
              "Put the subject's eye or the main point of interest there. Choose the end with Spiral Corner.")

# (camera property, label, description) for the composition guides drawn over the camera view
GUIDES = (
    ("show_composition_thirds", "Thirds",
     "Splits the frame in thirds both ways. Put eyes or the horizon on a line and the subject on a crossing: "
     "it feels balanced but alive. The default guide for almost any shot."),
    ("show_composition_center", "Center",
     "Marks the middle of the frame with a cross. Use it for symmetry, a face looking straight at the viewer, "
     "or a formal, calm look."),
    ("show_composition_center_diagonal", "Diagonal",
     "Diagonals from corner to corner through the centre. Lines running along them feel dynamic; use "
     "them to place a road, a sword or a stretch of arms."),
    ("show_composition_golden", "Golden Ratio",
     "Like thirds, but the lines sit at 38% and 62%, a little closer to the middle. The classic painter's "
     "proportion: a slightly more natural-looking balance for the main subject."),
    ("show_composition_golden_tria_a", "Golden Tri. A",
     "A diagonal plus two lines meeting it at right angles. Place the subject's main shapes on the "
     "triangles to lead the eye across the frame; fits scenes that run bottom-left to top-right."),
    ("show_composition_golden_tria_b", "Golden Tri. B",
     "The mirrored Golden Triangle (top-left to bottom-right). Use whichever way matches how the action "
     "moves; people tend to read a frame left to right."),
    ("show_composition_harmony_tri_a", "Harmonic Tri. A",
     "Triangles that split the frame into harmonious areas. A subject on the crossing points feels "
     "naturally anchored; handy for group shots and diagonal poses."),
    ("show_composition_harmony_tri_b", "Harmonic Tri. B",
     "The mirrored Harmonic Triangle. Switch between A and B to see which set of lines your subject "
     "already follows."),
    (SPIRAL_PROP, "Golden Spiral", SPIRAL_TIP),
)
SPIRAL_CORNERS = (
    ("TOP_LEFT", "Top Left", "The spiral's tight end sits in the top left: put the subject's eye there."),
    ("TOP_RIGHT", "Top Right", "The spiral's tight end sits in the top right: put the subject's eye there."),
    ("BOTTOM_LEFT", "Bottom Left", "The spiral's tight end sits in the bottom left: put the subject's eye there."),
    ("BOTTOM_RIGHT", "Bottom Right", "The spiral's tight end sits in the bottom right: put the subject's eye there."),
)
SPIRAL_RECTS_TIP = ("Also draw the golden rectangles the spiral is built from: each step cuts the frame at 0.618 along its "
                    "long side. They show where the curve turns, and are handy lines for placing smaller details.")
PASSEPARTOUT_TIP = (
    "Darkens everything outside the camera frame while you look through it, so you judge the real crop. "
    "0 is off, 1 is solid black. A strong value helps when you compose for a different aspect ratio.")

# (id, label, description): what Deploy does about the framing you see in the viewport
MATCH_VIEWS = (
    ("FIT_LENS", "Fit Lens",
     "Fit Lens: keep the picture you see: with a longer lens the camera backs up along your line of sight (a shorter "
     "lens moves it closer) so the subject fills the frame like it does in the viewport. Photographers do "
     "this to change perspective without changing the framing: a long lens from far away flattens depth."),
    ("FIT_BOX", "Fit Box (lens)",
     "Fit Box (lens): the camera stays at your eye. After you click the target, move the mouse to draw the frame you want "
     "and click: the lens is chosen to show exactly that. This is zooming, which keeps the perspective of "
     "where you stand and changes only how much of it you see. The Lens picker is not used."),
    ("MOVE_BOX", "Fit Box (move)",
     "Fit Box (move): the lens stays as you chose it. After you click the target, move the mouse to draw the frame you want "
     "and click: the camera moves along your line of sight, closer or further, until that frame is exactly "
     "what it sees. This is dollying, which changes perspective and keeps the lens (a long lens from far "
     "away flattens depth; a wide one up close exaggerates it). Compare with Fit Box (lens), which "
     "stays put and zooms."),
    ("OFF", "At My Eye",
     "At My Eye: the camera sits exactly where your eye is and the chosen lens decides the framing. Use it when "
     "you have already placed the view where the camera should stand."),
)
DEFAULT_MATCH_VIEW = "FIT_LENS"
BOX_MODES = ("FIT_BOX", "MOVE_BOX")   # the modes with the second step: draw the frame around the target
LENS_RANGE = (8.0, 1200.0)   # mm: the focal lengths a drawn box may choose (fisheye to super-telephoto)
BOX_PICK_HELP = "This is what the camera will see  ·  Hold Shift: change the ratio  ·  Click to confirm  ·  Esc: cancel"
BOX_MIN_PIXELS = 8           # the drawn box never gets smaller than this half-width, so the lens stays sane

# (id, label, width, height, description): what Deploy sets the scene's render resolution to (percentage untouched)
RESOLUTIONS = (
    ("KEEP", "Keep Scene", 0, 0,
     "Keep Scene: leave the render resolution as it is. The frame you draw and the lens follow its aspect ratio."),
    ("HD", "1920 × 1080 · HD 16:9", 1920, 1080,
     "Full HD, 16:9: the standard widescreen video and web size. Good for most animation and YouTube."),
    ("QHD", "2560 × 1440 · 16:9", 2560, 1440,
     "1440p, 16:9: sharper than Full HD while staying light to render."),
    ("UHD", "3840 × 2160 · 4K 16:9", 3840, 2160,
     "4K UHD, 16:9: four times the pixels of Full HD. Renders take about four times as long."),
    ("CINEMA", "2048 × 858 · Cinema 2.39:1", 2048, 858,
     "Anamorphic cinema widescreen, 2.39:1: the wide, filmic crop. Leaves black bars on a 16:9 screen."),
    ("SQUARE", "1080 × 1080 · Square 1:1", 1080, 1080,
     "Square, 1:1: the classic social media post, and a calm, symmetrical frame."),
    ("SQUARE_2K", "2048 × 2048 · Square 1:1", 2048, 2048,
     "Square, 1:1, at 2K: a big square for prints and detailed work."),
    ("SQUARE_1920", "1920 × 1920 · Square 1:1", 1920, 1920,
     "Square, 1:1, at 1920: as tall as Full HD is wide."),
    ("PORTRAIT", "1080 × 1350 · Portrait 4:5", 1080, 1350,
     "Portrait, 4:5: the tallest feed post on Instagram, and a natural shape for a standing character."),
    ("VERTICAL", "1080 × 1920 · Vertical 9:16", 1080, 1920,
     "Vertical video, 9:16: Shorts, Reels and TikTok, a phone held upright."),
)
DEFAULT_RESOLUTION = "KEEP"
RESOLUTION_BY_ID = {r[0]: r for r in RESOLUTIONS}
PRESET_SIZES = tuple((r[2], r[3]) for r in RESOLUTIONS if r[2])   # (width, height) of the real presets
SNAP_RATIO_TIP = (
    "While you hold Shift to draw the frame in any shape, snap its ratio to a common one (1:1, 5:4, 4:3, 3:2, 16:10, 16:9, 2:1, "
    "2.39:1 and the upright 4:5, 3:4, 2:3, 9:16) when it is close, with a tidy size (a multiple of 8, or a preset "
    "size). Off: any ratio, with even pixel counts.")

DEFAULT_LENS = "NORMAL"
DEFAULT_DOF = "PORTRAIT"   # the asset's own f/2.8

LENS_BY_ID = {l[0]: l for l in LENSES}
DOF_BY_ID = {d[0]: d for d in DOFS}
FOCUS_EASE_BY_ID = {e[0]: e for e in FOCUS_EASES}


def enum_items(table):
    """EnumProperty items from a preset table: (id, label, description) for each row."""
    return [(row[0], row[1], row[-1]) for row in table]


def guide_tip(prop):
    """The teaching tooltip for a composition guide's camera property."""
    return next(g[2] for g in GUIDES if g[0] == prop)
