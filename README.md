# Digit's Blender add-ons

Add-ons (extensions) for Blender 5.3 and later.

| Add-on | What it does |
| --- | --- |
| Digit's Assorted Tools | Character rigging, scene setups, checks and other tools |
| Digit's Modifiers | Geometry Nodes modifiers, with setup helpers |
| Digit's Processes | Multi-step jobs built from other tools, such as baking a game asset |
| Digit's VR | Pose characters and move objects in VR (in development) |
| Render Presets | Built-in and saved render settings |

## Install

1. Download or clone this repo.
2. Run `./package.sh` (needs `blender` on your PATH). It copies the zips to `~/Downloads`.
3. In Blender, open Edit > Preferences > Get Extensions, and choose Install from Disk.
4. Pick a zip.

Some features look for optional files (asset libraries, compositor groups) that are not in this repo.

## Code

Shared code lives in `shared_addon/`. `shared_addon/sync_shared.py` copies it into each add-on, so edit it there.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
