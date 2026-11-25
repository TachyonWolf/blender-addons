# SPDX-License-Identifier: GPL-3.0-or-later
"""HDRI World: the one place for its names, defaults and teaching tooltips. Plain data (no bpy), used by the
HDRI World card (hdri_world.py) and the tests. Every description is a hover tooltip and a short lighting lesson."""

WORLD_NAME = "HDRI World"
TAG = "digit_hdri"          # custom property on every node the tool builds (value = the node's role)
IMAGE_EXTENSIONS = (".hdr", ".exr")
# Folders looked at (first that exists wins) for the default "HDRI Folder", relative to the home folder.
FOLDER_CANDIDATES = ("Downloads/HDRIs", "Downloads/hdri")

NO_HDRI = "NONE"
NO_HDRI_LABEL = "None picked"
BLUR_SCALE = 0.2            # lookup jitter (in direction units) at Background Blur = 1.0

HDRI_HELP = ("An HDRI is a photo of a real place that records how bright every direction is, so it lights "
             "your scene the way that place would: the sky, sun and surroundings become the lights and reflections")
PATH_HELP = ("An .hdr or .exr file to use. When set it wins over the list. Leave it empty to use the list")
PICK_HELP = ("HDRIs found in Blender's bundled studio lights and in the HDRI Folder. Choosing one clears the file path")
FOLDER_HELP = "A folder holding .hdr / .exr files; they appear in the list (subfolders one level down too)"
STRENGTH_HELP = ("How bright the world light is. 1 is the picture as shot; 2 doubles the light (one stop brighter). "
                 "Raise it if the subject looks dull, lower it if highlights burn out")
ROTATION_HELP = ("Turn the HDRI around the vertical axis. The sun or the brightest window in the picture is your "
                 "key light, so spin it until the light hits the subject from the side you want "
                 "(front-side for flat, from the side for shape and shadow, from behind for a rim)")
BACKGROUND_HELP = ("Show: the HDRI is the picture behind the subject. Hide: the render has a transparent "
                   "background (Film > Transparent), but the HDRI still lights and reflects in the subject")
BG_STRENGTH_HELP = ("How bright the HDRI looks to the camera, separate from how much light it gives. "
                    "Lower it for a dim, moody backdrop that still lights the subject brightly (0 = black)")
BLUR_HELP = ("Softens the HDRI only where the camera sees it, so a sharp location photo becomes an out-of-focus "
             "backdrop like a wide-aperture lens would give. Lighting and reflections stay sharp. Cheap trick: "
             "the picture is looked up at slightly jittered directions, so Cycles averages it smooth over many "
             "samples (use the denoiser); EEVEE shows a fine frosted grain instead of a true blur")
APPLY_HELP = ("Build the HDRI lighting in the scene's world, or update it if already built. A custom world with "
              "your own nodes is never touched: a new world named HDRI World is made and used instead")
