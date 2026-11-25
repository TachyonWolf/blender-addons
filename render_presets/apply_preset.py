"""Headless: apply a render preset to every scene of a .blend (what the render queue uses).

  blender -b file.blend -P apply_preset.py -- --preset Fancy [--option look.fog=on ...] [--dir <saved presets folder>] [--save]

--preset takes a built-in (Draft, Preview, Final, Animation, Ref Sheet), an old name (Fancy, Fancy Full,
Final Low VRAM) or a saved preset in --dir. --option (repeatable, built-ins and old names only) sets a
setup option, e.g. look.fog=on, quality.samples=32, speed.texture_limit=2048, output.transparent=keep.

Existing compositors are replaced without asking (Revert-able in the same file).
Prints "DONE <preset> <scenes> [skipped:<paths>]". Without --save the file is left untouched (the
settings only live for this run, e.g. when a render follows in the same process).
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from render_presets import builtin_presets, preset_choice, preset_store as store  # noqa: E402  (this folder, run as a script)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []

    def option(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default

    name = option("--preset")
    option_texts = [argv[i + 1] for i, word in enumerate(argv) if word == "--option" and i + 1 < len(argv)]
    try:
        preset = builtin_presets.resolve_preset(name, builtin_presets.parse_options(option_texts))
    except ValueError as error:
        sys.exit(str(error))
    if preset is None:
        saved = store.list_presets(os.path.expanduser(option("--dir", preset_choice.DEFAULT_PRESETS_DIR)))
        if name not in saved:
            known = builtin_presets.preset_names() + list(builtin_presets.ALIASES) + list(saved)
            sys.exit(f"Unknown preset {name!r}; have: {', '.join(known)}")
        if option_texts:
            sys.exit("--option works on built-in presets only")
        preset = saved[name]
    skipped = []
    for scene in bpy.data.scenes:
        skipped += store.apply_preset(scene, preset)
    if "--save" in argv:
        bpy.ops.wm.save_mainfile()
    print("DONE", name, len(bpy.data.scenes), ("skipped:" + ",".join(skipped)) if skipped else "")


main()
