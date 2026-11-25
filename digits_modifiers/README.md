# Digit's Modifiers

Blender 5.x extension (add-on) with three things in one:

1. **The Toony Modifiers**: the Geometry Nodes modifier assets (Balloon Twist, Black Hole, Bulge, Crumple, Deforming Swirl, Fold,
   Hole Squeeze, Imprint, Inflate, Press, Roll, Roll Up, Slice, Smear, Smoosh, Squash & Stretch,
   Stretch Around, Stretch To Curve, Stretchy Limb, Taffy Pull, Traveling Bulge, Vacuum Pack + Vacuum Squeeze) and the
   **Vacuum Film** material, plus the **Generate** modifiers Bubbles + Bubbles Rest, Instance Array and the **Bubble** material, bundled in the extension's `assets/` folder (one .blend per modifier + `blender_assets.cats.txt`
   with the catalogs Toony Modifiers, Generate and Materials). Nothing else is shipped (no Snug Fit / Snug Smoosh / old
   groups, no other files; the shipped .blend files have no external links or paths). The path generators Spiral Curve and Curve to Knot
   moved to Digit's Assorted Tools (Add > Curve, Digit's Tools > Object > Path Generators); Stretch To Curve,
   Traveling Bulge and Stretchy Limb follow them like any curve.
2. **The Setup Helper**: one dropdown + one button adds a modifier AND the helper objects it needs.
3. **Combined Weight From Bones** (a vertex group from a bone chain's summed weights, minus Excluded Bones; also a tool in Digit's Tools > Weights).

## Install

Edit > Preferences > Get Extensions > the arrow menu (top right) > **Install from Disk...** and pick
`digits_modifiers-1.0.0.zip`, or drag the zip into Blender. Enabling it adds the asset library
**Digit's Modifiers** (Preferences > File Paths > Asset Libraries, Link/Append mode **Append**) pointing at the
extension's `assets/` folder, unless a library already points there; disabling removes the entry it added.
The Toony Modifiers then show in the Asset Browser (Toony Modifiers catalog) and the recipes below work
without any other asset library: they take the node groups / material from the bundled files first, then
from your asset libraries.

## Use

Sidebar (N) > **Modifiers** tab: pick a modifier in the dropdown (grouped Toony / Blender / Rig, with a tooltip
each, type to search), the **Setup Helper** card shows the status, the dropdown, the **Add <Modifier>** button, then an **Options** section (only recipes that have options), **Helpers It Makes** and a **Tools** section (recipe buttons) (all but Options start closed). The **Selected** card above it shows what is selected: one box per object that has Toony Modifiers (or whose helper empty / curve / plate is selected, e.g. `Taffy Body · Grab B`), one group per modifier with its main inputs (the recipe's `controls=` in `recipes.py`), a closed **More** group with the other value inputs, a **Helpers** row of select buttons and the recipe's tools (Re-rest). The same main inputs are the top level of the node group in Properties > Modifiers; the others sit in its closed **More** panel (built by `geonodes_common.add_more_panel`). A card below makes the combined weight group.
The modifier lands on the active object after the Armature modifier, with its helper objects made, named
`<Object> <Helper>`, parented to the object, and left selected (first helper active). Undo undoes the whole click.
Properties > Modifiers > **Add Modifier > Setup Helper** > Toony Modifiers / Blender Modifiers / Rig has the same
list; entries with options open a small popup with the same options first.
Both are drawn from the one table `RECIPES` in `recipes.py`; each recipe lists its own options as data.
Preferences (Edit > Preferences > Add-ons): **Show sidebar tab** and **Show in Add Modifier menu** (both on).
The **Combined Weight From Bones** card (collapsible, `bone_chain_ui.py`, shared with Digit's Tools > Weights): pick the chain's Root Bone (or
select bones in Pose Mode / Weight Paint), name the Group (default `InflateExclude`), click **Make Combined Weight Group**: every mesh
the rig deforms gets `min(1, summed weights of the bone chain)`; re-runs are clean. **Excluded Bones** (a list: Add Selected, Clear, a
bone picker per row; Exclude Children on by default) are left out of the sum, e.g. the jaw when making a head group.

## Recipes

Arrow convention for empties: local +Z (Single Arrow) is the way the effect works, local X the line /
axis where a second axis is needed, point-only empties are Sphere / Plain Axes.

| Recipe | Helpers |
| --- | --- |
| Balloon Twist | none: Along = Axis, set to the longest axis (whole mesh); for a part of a rig use the bone chain one |
| Black Hole | Center: sphere empty beside the mesh (+X side), Radius 1.5 x size, Suck 0.5; follows the rig's active bone |
| Bulge | Center: sphere empty on the front surface; follows the active bone |
| Crumple | Option **Tightness** (Soft / Medium / Tight = How Crumpled 0.2 / 0.5 / 0.9) and **Seed**. Center: sphere empty at the middle (move it onto the face: that spot stays on top of the ball) |
| Deforming Swirl | Center: arrow empty at the middle, Z up (swirl axis), Swirl Amount Z 90 |
| Fold | Option **Start folded**. `<Obj> Fold Lines` collection with Fold 1 / Fold 2 arrow empties a quarter of the length each side of the middle, X = line, arrow over the moving flap |
| Hole Squeeze | Hole: arrow empty beside the mesh, arrow pointing into the hole (+X) |
| Imprint | Inside Object: wire sphere at the middle (swap for the real object) |
| Inflate | none |
| Press | Plate: plane above the mesh, arrow down (rotated X 180), not parented |
| Roll | Option **Mode**: Ground = Roller cylinder (axis X) beside the mesh on the floor, travels +Y, not parented; Wringer = roller just before the mesh at mid height |
| Roll Up | Axis: arrow empty at the front end laid along the sheet (+Y), X across |
| Slice | Axis: arrow empty at the middle, Z along the longest axis, Spacing = length / 3 |
| Smear | none (then run `Scripts/smear/setup_smear.py` for the Ghost) |
| Smoosh | Target: glass plane in front (normal toward -Y, the camera), Factor 0.999 |
| Squash & Stretch | Axis Object: arrow empty at the feet, Z up |
| Stretch Around | Passing Object (sphere) in front + Opening Axis arrow empty (Z into the mouth, follows the active bone) + empty `Opening` vertex group to paint |
| Stretch To Curve | Curve: bezier along the longest axis; Axis set to match |
| Taffy Pull | Per end, 15 % in from it along the longest axis: Rest A/B (Plain Axes, parented to the mesh) with Grab A/B (Sphere) parented to it on the same spot (options **Grab A bone** / **Grab B bone**: on those bones' heads, rests parented to the bones); grabs selected, Grab B active; Grab Radius 5 % of the length. Options card button **Re-rest**: snaps the rests onto their grabs (selected Taffy object or its empties) |
| Traveling Bulge | Path: bezier along the longest axis |
| Vacuum Pack | Option **Target**: Object, or Collection (a new collection holding the mesh). New empty mesh `<Obj> Vacuum Pack` (the Film) carries the modifier, Target = the mesh; its first material slot (linked to Object) = the Vacuum Film asset |
| Bubbles | Section **Generate** (named like Blender's Add Modifier > Generate). Bubbles goes last in the stack; the Bubble material goes in the modifier and in a new slot; Min / Max Radius, Surface Gap and Density scale with the mesh size (the defaults are for 2 m), so a glass gets many tiny bubbles. With an Armature modifier also **Bubbles Rest** right before it (after Mirror) |
| Instance Array | Section **Generate**. Like Array (Count, Relative / Constant / Object Offset) but the copies stay instances of the mesh: almost no extra memory, linked duplicates stay cheap. Goes last in the stack (a later modifier would realize the copies); stacking several works like stacked Arrays. Not in it, as instances can't merge: Fit Length / Fit Curve, Merge, Caps, UV offsets |
| Lattice | Option **Points per side** (3). Lattice fitted to the local bounds |
| Curve | Curve modifier + bezier along the longest axis (sitting on the mesh, through its origin) |
| Simple Deform | Option **Mode**: Bend / Twist / Taper / Stretch. Origin: arrow empty, Z along the longest axis (Bend at one end, the rest at the middle) |
| Cast | Control: sphere empty at the middle |
| Hook | Hook: empty at the centre of the selected vertices (else all), hooks them with no jump |
| Wave | Start Position: plain-axes empty at the middle, height / width / falloff from the size |
| Displace | new Clouds texture + Texture Coordinates empty at the middle, scaled to half the size |
| Stretch To Curve (chain) | Options Root / Tip bone: Selection + Along groups from the chain, modifier after the Armature at Progress 0, curve through the posed bones (moved here from Assorted Character Tools) |
| Balloon Twist (bone chain) | Options Root / Tip bone: Selection + Along groups from the chain (the same code as Stretch To Curve's), Along = Group, modifier after the Armature |
| Stretchy Limb | Options Root / Mid / Tip bone: shared setup with the Stretchy Limb extension |

Modifiers go right after the Armature modifier (after earlier ones of the same kind). Sizes are in the
object's local units, so scaled objects work.

## Code and building

`recipes.py` (the table `RECIPES` with its `Option` rows, placement functions, `run_recipe`), `helpers.py` (`Bounds`, `at`
frames, object makers), `stretch_setup.py` (bone based setups), `asset_library.py` (registers / removes the
asset library), `__init__.py` (operators, panel, menu, preferences, option properties). `bone_chain.py`,
`modifier_setup.py` (`library_file` looks in `assets/` first), `ui_cards.py` are generated copies of
`Addons/shared_addon/` (run `sync_shared.py` after editing the source).

The `assets/` folder is the ONLY home of the Toony Modifiers .blend files: the builders in `Scripts/<modifier>/`
write there (path constant `ASSETS` in `Scripts/geonodes_common.py`, `asset_file(name)`), thumbnails sources are in
`assets/Previews/` (not shipped). Dev install on this machine: `Addons/install_dev.sh digits_modifiers` (plain copy incl. `assets/`
to `~/.config/blender/5.3/extensions/user_default/digits_modifiers`; run again after edits). Shareable zip:
`Addons/package.sh digits_modifiers` (syncs shared code, validates, builds into `dist/` and copies to `~/Downloads`; the manifest's
`[build]` excludes keep tests, previews, backups out).

Tests: `tests/run_tests.sh` (headless, niced: every recipe, options, UI states A/B/C on a fake layout, More panels of every asset, combined weight group tool, asset library) and
`tests/test_package.sh` (builds the zip, installs it into a fresh headless Blender without any asset library,
checks the library is registered, every recipe works from the bundled files, disable removes it).
