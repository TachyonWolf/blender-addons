# Digit's Assorted Tools

(Was "Assorted Character Tools", module `assorted_character_tools`; renamed 2026-11-03.) Sidebar tab **Digit's Tools**,
tools in two categories, **Export** (Combine Into One Model, Game Rig) and **Character Rigs**, among them **Rename Bones** (any rig to `docs/BONE_NAMES.md`), **Combine Bones** and these cards: **Combine Into One Model** (Combine Multi Part Model), **Face Rig** (Eyes & Anthro Snout), **Bendy Span Bone** (span bones +
Reset of every Stretch To). Each card: a status line, its main buttons in one big row, greyed hints for disabled
buttons, settings in collapsible sub-cards (Options / Eyes / Anthro Snout / Shared / Advanced, closed or remembered). (Make Vert Group From Sum of
Bone Chain, Add Stretch To Curve and Add Stretchy Limb moved to Digit's Modifiers.)

## Face Rig

Digit's eye rig and maw (mouth) rig on any character. Logic: `face_rig_core.py` (generated copy of
`Addons/shared_addon/face_rig_core.py`); design and goals: `notes/wip/face-rig-tool.md`.

1. Select the character (its armature or a mesh it deforms). **Add Eye Rig** / **Add Anthro Mouth Rig** append the guide
   assets ("Eye Rig" / "Anthro Mouth Rig" from `FaceRigs.blend` in your asset libraries; built in code if missing) onto the
   character and place them: eye centre from the eye bone or eyeball mesh, lid ring / lips from the old face bones
   or the skin, mouth corners guessed. The settings fill in (skin meshes, size from the eye width, old bones).
2. **Edit Guides**: drag the guide bones' heads in Edit Mode onto the lid edge (8 points round the eye), the brow
   (4), the lip lines (centre, middle, corner) and the jaw hinge (only used without a jaw bone). Left side only
   unless Mirror is off.
3. Check the settings: meshes (first = weight source; others with an identical head get its head weights, e.g.
   two copies of a body), skin parts, Build Weights, Mirror, Size, colours; eye: eye bone, Lid Pivots, Lid Deformation
   (Pivots = smoothest closed lid, recommended; Ring, experimental = a B-bone ring through the pivots' tips deforms
   the lids, with Ring Reach (mm; smaller = only the lid edge follows the ring) and Sharp Corners), Look Follow, Brow Push, Brows, Lashes + lash mesh, swing; maw: jaw and
   lip parents, Corner Jaw Follow, Corner Pull; **Replace** lists the old face bones the build removes (their
   weights go to their parent; the magnifier detects them).
4. **Build**. **Rebuild** after changing guides or settings keeps your control poses. **Remove** takes the rig out
   (the old bones it replaced come back only with Undo). The guides stay, hidden, for rebuilds.

Weights need the skin's lid edge and lip lines as edge loops (quad loops, or poles traced) and meshes without an
extra transform against the armature (left half + Mirror modifier, as many characters).

## Bendy Span Bone

**Add Span Bone**: in Pose or Edit Mode select two bones (active = end): a deforming B-bone from the first to the
active one (head on it, parented to it, Stretch To the active bone), named `Span_<A>_<B>`, in the Deform collection,
marked `span_bone`. **Handles**: Smart (Tangent to a neighbouring span where one meets that end, else Automatic) or
Blender's Automatic / Absolute / Relative / Tangent, stored per span. **Mirror** makes the mirrored span too;
**Turn Off Deform Under Spans** (+ **Move Weights to Span** onto the nearest span) turns the two bones' Deform off.
**Flip Span** swaps the selected spans' direction (renamed, weights follow). **Reset Spans** (only needs the armature active, any
mode, no selection) resets every Stretch To of the armature (rest length measured in the rest pose, volume variation
1), lid rings and hand-made stretch bones included; span bones are also realigned to their bones with segments,
handles (Each Span's Handles, or the dropdown's), ease and pose reset. Disabled buttons say why under the card.
Logic: `span_bones.py` (generated copy of `Addons/shared_addon/span_bones.py`).

## Combine Multi Part Model

One click combines a multi-part rigged character (parts and nested rigs) into one rig + one mesh, for deform
work (Geometry Nodes etc.). Click, then open the `-Whole` file.

## Use

1. Select the armature or any part of the character (the **Digit's Tools** tab always shows; without a character it asks you to select one).
2. 3D view sidebar (N) > **Digit's Tools** tab > **Combine Multi Part Model** (or F3 > "Combine Multi Part Model"). Confirm.
3. The session becomes `<file>-Whole.blend` in the same folder (`-Whole-2`, ... if taken). The original
   file on disk is never touched. An unsaved file is changed in place (nothing is saved), unless an Output Folder is set (then `<rig>-Whole.blend` goes there).
4. The info bar reports parts merged, parts deleted and warnings.

**Remove hidden child items** (default OFF): OFF merges everything, hidden parts included. ON leaves hidden
parts out of the merge and deletes them (swap parts: hide the spares, tick it, Combine).

**Clear custom normals** (default OFF): ON removes the custom split normals from the combined mesh
(`has_custom_normals` ends False), because Geometry Nodes modifiers work badly on meshes with them. OFF keeps them.
Both options are scene settings in the panel's own "Combine Multi Part Model" box; Clear custom normals is also an operator property (shows in the confirm dialog).

**Output** (sub-card, Scene settings): **Output Name** and **Output Folder**. Both empty = the automatic file above (shown greyed in the empty field; the card says "Saves as ..."). A typed name needs no `.blend`, path separators are dropped; a file that exists is never overwritten (`-2`, `-3` ...). The folder may be `//` relative to this file and is created if missing.

Optional **Keep** field: comma separated collection names (e.g. `Jester, PowerArmor`) whose objects are
never merged or deleted. Digit's WIP collections are in `charfix/configs/digit.json`.

## What it does

- Character = meshes/curves/text deformed by, or parented (recursively) to, the armature.
- All parts are merged, or with **Remove hidden child items** only the visible ones (`visible_get`); hidden ones are
  then spares and are deleted with the merged originals.
  Other characters, cameras, lights and the rig stay. Children of deleted parts move to the rig, world position kept.
- Modifiers other than Armature and Subdivision Surface are applied in stack order, **in rest pose**
  (Armature is switched off while evaluating, rig pose is restored afterwards). Modifiers after Armature
  are therefore applied to the rest mesh too, as if they came before it. Modifiers switched off in the viewport are dropped.
- Shape keys: rebuilt after the modifiers (each key evaluated alone) when they are relative to the basis,
  have no vertex group, and the modifiers keep the vertex count per key. Otherwise they are baked at their
  current values and reported as lost.
- Curves/text/surfaces become meshes; ones with an Armature modifier are skipped with a warning.
- Mesh parented to a bone without Armature modifier gets a full-weight vertex group of that bone.
- Result `<Armature>_Whole`: vertex groups, UVs, materials kept; one Armature modifier (main rig) then one
  Subdivision Surface using the highest viewport/render levels found (warns when parts differ, or adds 1/2 if none).

## Bone Workshop

Character Rigs card (`bone_workshop*.py`, `bone_setups.py`, `rig_check.py`; tests `tests/test_bone_workshop.py`,
`tests/test_bone_setups.py`, `tests/test_widget_shapes.py`). Pose Mode. Every button changes the active bone or all
selected bones (several armatures too) and, with **Also Change the Mirror Side**, their mirror bones; one undo step per
click, the report names what it skipped (no mirror bone, a linked or override rig). Sliders show the active bone and
write every target (Scene get/set properties; `bone_workshop_props.LIVE_SLIDERS = False` falls back to the bone's own
values plus a copy button per row).
- **Style Presets**: FK Control, IK Control, Tweak, Pole, Face Control, Root (shape, size, colour, collection by name),
  your own presets (Save Current as Preset, stored in the extension's user folder), and a "Looks like ...: Apply"
  button from the active bone's name.
- **Shape**: 15 tiles with icons drawn from the widget meshes (`icons/make_shape_icons.py`), shared widgets from
  `face_rig_core.ensure_widget`; N-gon / Star, Gear and Capsule are made from their numbers (`WGT-Ngon6Flat`,
  `WGT-Gear10-25-50Hole`...: one mesh per setting, unused ones removed); Use Mesh, Edit Shape (a copy for these bones,
  Done Editing Shape), Clear.
- **Size & Placement**: scale (uniform lock), offset, rotation, wire width, wireframe, scale to bone length, Shape
  Follows; Fit to Mesh (once, on the click), Match Active, Reset.
- **Colour**: theme colours, Show In Pose / Edit / Both, From Collection, By Side (left blue, right red, middle yellow).
- **Bone Collections**: the rig's tree; a click makes the home (deform bones also go in Body / Face Deform, FK switch
  collections stay), Also Add, Remove, Auto-Sort by Name, Make Collection.
- **Bone Settings**: Deform, Connected, Inherit Rotation, Local Location, Hide, Bones In Front (the preference),
  Inherit Scale, Rotation Mode (keeps the turn), B-Bone Segments, locks.
- **Constraint Setups**: a dropdown grouped Limbs / Hands & Feet / Chains / Helpers (`bone_setups.SETUPS`, one entry
  per setup): IK Limb (IK Bone Add New / Use Existing; Place It Inline = along the hand with Copy Rotation, the Full
  Rig's way, or At End; pole, IK_FK, Limb Rig's stretch / parent switch / snap data, pole line), Twist Share, Spine IK,
  Finger Curl (+ Fan on Z), Foot Roll (+ Foot Bank), Chain Curl, Stretch To, Aim at Target, Parent Switch, Deform
  Follows (the DEF- copy takes the weights). Setups the Full Character Rig has run its code (`body_rig`, `limb_rig`).
  Each shows what it does, what to select (or why not yet), its options and what it adds; Add Setup (the other side
  too), Try It (a demo pose; move the mouse for more or less, a click puts the pose back, no undo step). "On <bone> now"
  lists the bone's constraints with where they came from, mute and remove, Mute All, Copy to Mirror Side.
- **Name & Role**: Control / IK- / DEF- / MCH- (renames, clashes skipped), the standard check with Rename, Select Mirror.
- **Rig Check** (closed; runs on its button): Controls With No Shape, Names Off the Standard, DEF Bones in Controls,
  Left / Right Differ, Unused Shape Meshes, each with a Fix; its own list and cache, not in the Oops Debugger.
- Bottom: Copy Active to Selected, an eyedropper (click a bone in the viewport: its look goes onto your bones), Mirror
  to Other Side.

## Combine Bones

Pose or Edit Mode: select bones, make one the active (main) bone, click **Combine Bones**. The others are removed and:
their vertex group weights are added to the main bone's (on every mesh the rig deforms, clamped at 1; the main bone's
Deform is turned on if it was off and weights moved); their children go to the main bone, keeping their rest
position (a child that is itself an ancestor of the main bone goes to the removed bone's parent instead, so no cycle);
if the main bone hangs under removed bones it goes to its nearest surviving ancestor; constraints (any rig, any
object) and driver variables aimed at a removed bone aim at the main bone; objects bone-parented to a removed bone are
parented to the main bone keeping their world position; drivers on the removed bones' own properties are removed.
Left as they were, and counted in the report: a constraint on the main bone that aimed at a removed bone, driver
variables reading a custom property of a removed bone, action curves of the removed bones. Undo works. Logic: `combine_bones.py`
(generated copy of `Addons/shared_addon/combine_bones.py`).

## Game Rig chains

A B-Bone Chain Builder chain or loop (such as wings) becomes just two game bones a side, `<Name>1` root -> mid and
`<Name>2` mid -> tip, under the chain's parent bone; the full B-bone chain stays on the source rig. Root = the point
nearest the parent bone, tip = the top-level point farthest from it, mid = a web point near the chain's middle, else
the middle itself (a loop's outline centre). The chain's B-bone weights split between the two by place along
root -> mid -> tip, blended wide across the mid joint (`CHAIN_BLEND`: 0.8 of the shorter bone). Near the chain's base
(its points nearest the body) the chain vertices fade to the spine's weights there (the nearest body vertices'
weights on the chain's ancestor bones, e.g. Chest / Spine / Hips; `CHAIN_HOLD`: 13% of the root -> tip span), so the
base stays on the back when the spine bends; then the chain vertices are smoothed in space (`CHAIN_SMOOTH`), body
vertices untouched, at most 4 weights, normalised. `make_game_rig(...,
follow=True)` (code only, for baking an animation) makes the game rig follow the source: Copy Transforms per bone,
the chain bones from the root control over a helper `MCH-<Name>Mid` to the tip control. Logic: `game_rig.py`.

## Game Rig output

Besides **This File** (the `<rig> Game` collection in this file, as always) the card's **Output** sub-card can also
export just the game rig and its meshes: **FBX**, **glTF Binary (.glb)** or **Blend File** (a temporary scene holds the
collection, so the file opens showing it; paths are remapped to the new place). The rig is always made in this file and
the source is untouched. File names: `<rig>-Game.<ext>` next to this file, or **Output Name** / **Output Folder**
(a typed name also names the collection `<name> Game` and the rig `<name>_Game`). These are repeat exports, so the
same path is REPLACED each run (the card says "Replaces X" when it exists). An unsaved file needs an Output Folder; a
switched-off FBX or glTF add-on is reported. Logic of the exports: `game_rig_ui.py`; the name / folder fields and
path rules shared with Combine Into One Model: `output_file.py`.

## Swap rigs

Result is one rig + one mesh. Every other armature that deforms a merged part is joined into the main rig
(bones keep their world rest position):

- Bones whose names clash with the main rig are renamed `<bone>.<RigName>`; the matching vertex groups of
  that rig's parts are renamed the same way before the mesh join.
- A swap rig carried by a main bone (bone parent or Child Of) gets its root bones parented to that bone, so it follows.
- Constraints and driver variables that pointed at the old rig object now point at the main rig.
- Rigs used only by deleted spare parts (Remove hidden child items ON) are deleted too (unless something that stays still uses them).
- Animation on a swap rig object is not carried over (warning). Only the first Armature modifier of a part counts.

## Oops Debugger and Drivers

**Oops Debugger** (under **Check**) lists things you MAY have left on or changed by mistake on the active object, its rig and that rig's meshes, only when present: a row each with the plain-words name, a count, a grey detail, **Select** (where it names objects or bones) and **Clear** (its tooltip says what is removed and that Ctrl+Z brings it back). Posed Bones and Shape Key Above Zero are risk 3 (Risky). Every risk 3 Clear opens a warning popup saying what is lost (risk 0-2 stay one click). **Clear All** has a level select above it (Clear up to risk 0 / 1 / 2 / 3, default 1, saved in the preferences) and clears every listed leftover up to that level; at 3 a red line warns that Risky ones are included. It asks first and says how many items per level (a warning popup at level 3). Tests: `tests/test_oops_risk.py`. Sections: Animation & Pose (action on object / rig data / shape keys; posed bones; rig in Rest Position; hidden bones; **Rest Shape Changers** = enabled bone constraints that pin a bone in place (Limit Location / Rotation / Scale / Distance, Floor, Shrinkwrap, Child Of, Pivot, Transform) and deforming modifiers (Shrinkwrap, Lattice, Curve, Cast, Simple Deform, Warp, Wave, Displace, Hook, Mesh / Surface / Laplacian Deform, Smooth, Corrective Smooth, Volume Displace), which can change the rest shape without any posing; Clear mutes them), Mesh (sculpt mask, face sets, Dyntopo, custom split normals, shape key above 0 that nothing drives, Shape Key Lock, hidden objects, modifier viewport vs render), Transforms (negative scale, unapplied scale / rotation: Clear applies them; delta transforms), Tool Settings (Affect Only Origins / Locations / Parents, X-Axis Mirror, Auto Keying, Proportional Editing, Snapping, Lock Camera to View), Weights (vertices not adding up to 1: normalize via `weight_cleanup`; locked groups; empty groups), Drivers (drivers with errors: Clear mutes them). The checks are a registry in `scene_checks.py` (shared, no UI: `Check(id, area, label, help, find, clear)`; add one `register(...)` line for a new one; `run_all(scope, areas)` / `clear_all`), so Pre-Render Check can move onto it by making its checks `Check`s in its own area. **Looking for** (a dropdown at the top: **Object** / **Scene** / **Render**, saved in the add-on preferences) picks which checks are shown AND scanned: Object = the character (bones, meshes, weights, transforms, baked data, the Checks card), Scene = editor state (tool settings, hidden objects / bones, locked vertex groups), Render = the Pre-Render Check problems plus Render Differences (and the render settings lines); Clear All Leftovers acts only on the kind shown. **Scans** card: a switch per heavy scan (Baked Data, Weights, Mesh Checks, UV Overlap; off by default, saved in the preferences): on = runs now and on every selection change, off = never runs and its checks are hidden (the Checks card says "off (turn on in Scans)"). Cheap checks always run. Turning one on runs only its checks. A check that raises shows as "<name> · failed" with the error, the others still run. Pre-Render Check has no Scans and always runs all of its checks. A red warning at the top of the card says to read before clearing. **Showcase file**: `tests/make_oops_showcase.py` builds a scene where every check finds something (objects named after their check; writes `Practice/OopsDebuggerShowcase.blend`, or the path after `--`); `tests/test_oops_showcase.py` fails naming any check it misses, so add a cause for a new check in `tests/oops_problems.py` (shared with `test_oops_drivers.py`) or list it in `UNTRIGGERABLE`. Tests: `tests/test_oops_scans.py`. **Drivers** (under **Character Rigs**) lists the selected rig's drivers (and, with Include Meshes, its meshes' shape key and modifier drivers) per bone / owner, each with the driven property in words, the expression or how the variables combine, a red line for errors (typo in the expression, no target, property or bone gone, Blender could not run it), a Select Bone button and a mute switch; Search, Only Problems, summary "n drivers · m with errors". The reading is `driver_scan.py` (shared; Oops Debugger uses it too). Both do nothing in the background: they scan only while their card is open, cache the result per selection, and have a Rescan button. Tests: `tests/test_oops_drivers.py`.

## Known limits

- Joined UV maps merge by position; a warning appears if parts name them differently.

## UV Rebake

Tool "UV Rebake" (category Texture). Move seams and islands without losing the paint: select the meshes, make a new UV map, pick Source and Target, press Rebake Images. Each image on the material gets a new file (never overwrites); nodes stay the same, so what's derived from an image follows it. Every part on an image is baked with it, selected or not; a part lacking the target UV stops the job (or Copy to Missing Parts gives it the source UV). Tiling patterns (images in a `Hexes` group or read through their own coordinates) start off in the Images list and just read the new UV. Options: Margin, Sharp (Closest sampling: an island moved by whole pixels copies exactly), Use New Images. Output is 8-bit PNG. Core: `uv_rebake.py`, generated from `shared_addon/`.

## Texture Studio

Photographs a character into texture maps (beauty, matte, albedo, normal, roughness...) for posters and standees: one Cycles
render per shot. Glass (a visor) reads as glass in beauty and matte: the world is a grey glass backdrop for glossy and
transmission rays only (`scene_setup.GLASS_BACKDROP`), and matte adds the light seen through glass. Code in `texture_studio/` (studio.py, compositor.py, aov_inject.py, scene_setup.py, panel.py); usage and
goals in the project note `notes/wip/texture-studio.md`. Ways to start: **File > New > Texture Studio** (the studio file from the
preferences opens as a new untitled file, so a save never overwrites it), **Add > Camera > Texture Studio in This File** or
the Scene > Texture Studio card (a studio scene in the open file; optional Subject = a collection of this file, linked, not
copied). The sidebar panel (Digit's Tools tab) shows only while the scene is a studio (`scene.texture_studio.is_studio`);
its Add Character section links a character's master .blend as a library override (never edited) and sets it as the subject.
Headless: `Scripts/texture_studio/capture.py`, `build_studio.py`. Test: `tests/test_texture_studio_entries.py`,
`Scripts/texture_studio/test_texture_studio.py`.

## Install and test

`blender --command extension build --source-dir "<this folder>"`, then Install from Disk. Installed for
this machine as a copy in `~/.config/blender/5.3/extensions/user_default/digits_assorted_tools` by
`Addons/install_dev.sh digits_assorted_tools` (run again after edits). Self-contained: it does not import charfix (an installed copy can't reach it).

`character_link.py`, `compositor_common.py`, `ui_cards.py`, `combine_bones.py`, `face_rig_core.py`, `lid_bbone_ring.py`, `span_bones.py`, `chain_weights.py`, `bone_collections.py`, `modifier_setup.py` and
`bone_chain.py` here are generated copies of the files in `Addons/shared_addon/`: edit the source, run
`Addons/shared_addon/sync_shared.py`.

## The panel layout

Three levels, three looks (`ui_cards.py`): a **card** (header strip, `card`), a framed **section** inside a card (`section`: box + panel header) and a plain arrow **group** inside a frame (`group`; `section` turns into one while a Selected box is drawn, `inside_frame`). Never a frame in a frame. Section headers can show a grey state summary on the right (`right=`) and an icon-only header button (`button=(operator, icon)`, the Deploy +).

Digit's Tools has two top-level sidebar panels (own collapsible headers, drag to reorder). **Selected** (first, open by default; header right = `nothing` / `n objects`) holds the live controls of the deployed things with properties that are selected, one framed box per thing headed by its plain-words name ("Camera Rig · Aim"; the first box open, the rest closed), each part a plain group. Modules register providers in `selected_ui.py` (shared with Digit's Modifiers; `add(name, poll, title, draw)`): **Camera Rig** (Lens & Focus, Framing, Focus Pull, Composition, Select Part row), **Three Point Light** (Look, Brightness, Position with Key / Fill / Rim headings, Softness & Shadow, Colour, Rig with a Select Part row), **Bounce Card**, **Photo Backdrop**, **Shadow Catcher** and **Catchlight**. With anything else selected the card shows one grey hint. Generic helpers (Make Modifier Helper, Combine Bones, Bendy Span Bone) are dropdown tools, and so is **Combined Weight From Bones** under the **Weights** heading (`bone_chain_ui.py`, the same tool as Digit's Modifiers' card: a vertex group from a bone chain's summed weights, minus Excluded Bones), **Remove Disconnected Islands** and **Merge Vertex Groups** (`weight_tools_ui.py`, logic in `weight_cleanup.py`). Remove Disconnected Islands (mesh in Weight Paint Mode, active vertex group): **Remove and Normalize** or **Move to New Group** starts a crosshair pick; click a vertex on the part to keep. It floods through mesh edges over vertices whose weight is at or above the **Threshold** (default 0.05); the rest of the group is the spill. Remove and Normalize drops the spill and gives each vertex's weight to its other deform groups so it sums to 1 (a vertex with no other deform group stays and is counted); Move to New Group puts it in `<group> Spill`. Status: "Keeps n · removes m". With topology-changing modifiers (Subdivision, Mirror...) the nearest base-mesh vertex to the hit is used. Merge Vertex Groups: list groups (Add / Clear, a search row each); Merge Into Active Group adds their weights to the active group (Add, clamped to 1, or Max), **Remove Merged Groups** (on) deletes them, **Normalize Result** (off) scales changed vertices to 1; it reuses `combine_bones.merge_weights`. Both are one undo step; nothing runs in the background and the cards do no mesh work. The second panel is **Tools**: a one-row badge legend, the tool dropdown, then the chosen tool's card. The dropdown is a menu (`tool_menu.py` adds the badges to the shared `tool_picker.py`, also used by Digit's Processes; type to search): category headings, tools A-Z, each row = tool icon + name with its skill mark after it (★ / ◆); the row tooltip adds what the mark means. Marks: ★ = beginner friendly, ◆ = expert, none = neither (text marks, because a menu row holds only one icon: the tool's). Icon and skill of each tool are in `TOOL_LOOKS` next to `TOOLS` (`__init__.py`), the marks and their tooltips are defined once in `tool_menu.py`; each row is one internal pick operator; the legend items are an internal operator that only shows the badge tooltip, and the stored choice is still `WindowManager.digit_tool`. **Poses to Shape Keys** (Character Rigs, `pose_shape_keys.py`, test `tests/test_pose_shape_keys.py`): Current Pose (typed name) or Each Pose Marker of the rig's active action (one key per marker); targets = selected meshes, or with the rig selected every visible mesh with an Armature modifier on it (status line counts them); keys are relative to Basis (made if missing), evaluated up to the Armature modifier only with other shape keys muted, same name replaces, meshes whose vertex count changes are skipped and reported, pose / frame / modifier states restored. A Setups tool card holds its status, a grey hint that the controls are in Selected, and the Deploy section (folded once a rig exists, options summary on the right, icon-only + button in the header).

Every tool card: status line, the main action row, then titled sections. Common sections open, Advanced / rare ones closed.

Test: `tests/run_tests.sh` (headless, niced, silent): every card on a fake layout (`test_draw_cards.py`), Combine, Combine Bones, the Face Rig card, Span Bones, Limbs, Game Rig, Rename Bones, `test_rig_names.py` (plain Python), Face Rig Rebuild on scratch copies of the real rigs.

## Moved tools

**Make Vert Group From Sum of Bone Chain**, Add Stretch To Curve and Add Stretchy Limb are now in the **Digit's Modifiers** extension (`Addons/digits_modifiers/`), sidebar tab **Modifiers**.

**Add Rig Component** (Character Rigs card, `rig_component_ui.py`; logic in `rig_component.py`): adds ONE rig part on its own: Tail, Ears, Hair, Breasts, Butt, Membrane Wings, Ray Fin or Face. Pick the part and its few settings, the Rig (empty = a new armature `<Part> Rig`), the Bone (empty = Pelvis, Chest or Head by name) and the Mesh. Steps: **Add Guides** (on the mesh, else the usual place), drag them, **Build**, **Weights**; each can be done again; **Remove Part** takes only that part off. The Full Character Rig uses the same builders, leaves these parts alone and weighs them again after its body weights. Wings come only from this tool.

**Add Mirrored Mesh** (`mirrored_mesh.py` geometry, `mirrored_mesh_add.py` plan / add / redo, `mirrored_mesh_options.py` the options, `mirrored_mesh_ui.py` operator + card; Object card): adds a primitive as only the half (or quarter, eighth) that a Mirror modifier turns back into the exact whole. The card: the mirror axes (X/Y/Z toggles in Object Mode; read only from the active object's enabled Mirror modifiers in Edit Mode, read by `mirror_pivot.applicable_mirrors` / `mirror_planes_of`), a **primitive dropdown** (shapes that fit no turn on these axes are marked "(no fit)"), that primitive's options (size, segment / ring counts) and **Orientation**, then **Add Mirrored Object** (Object Mode: a new object at the 3D cursor, world aligned, with a Mirror modifier, Clipping and Merge on) or **Add to Mesh** (Edit Mode: into the active mesh at the cursor with its coordinate on each mirrored axis snapped onto the plane, in the object's or the Mirror Object's space; the new geometry is the only selection). A red line and a greyed button say why an add is impossible (e.g. "Cylinder with 31 vertices is not the same mirrored on XYZ; use an even count", "Add a Mirror modifier first"). **One definition of the options**: `OptionsMixin` is inherited by both the card's scene settings group (`scene.mirrored_mesh_card`) and the operator; the operator takes the card's value for every option not passed to it, and writes its values back (so the Adjust Last Operation panel and the card stay in sync). **Before or after placing**: options set on the card are used by the next Add. While the latest thing done is still our add (our operator is the last operator, and the new object is active / the new geometry is still the whole selection), changing an option on the card redoes that add in place: it swaps the object's mesh and modifier axes, or deletes the selected geometry and adds the new one, and updates the operator's stored values. No undo is used, since we know what the add made. After any other action a change applies to the next Add only. **Orientation**: a primitive may be turned in 90 degree steps so it mirrors exactly (Monkey on Z lies down, Cone on Z lies along X or Y, Plane/Circle/Grid on Z stand up, Ico Sphere turns onto X or Z). `mirrored_mesh.analyse` finds the distinct turns that pass an exact vertex check (KD-tree, 1e-4) and are not flat on a chosen plane (cached per primitive and counts, size ignored, so drawing never rebuilds a mesh it has seen). A cut may add a centre loop. No handlers or timers. Test: `tests/test_mirrored_mesh.py` (background Blender keeps no operator stack, so the last-operator check is stubbed there).

**Mirror Pivot** (`mirror_pivot.py`, no panel card): "Median Point with Mirror" for Scale and Rotate in mesh Edit Mode. The pivot is the middle of the selection plus the copies of every Mirror modifier (enabled in viewport and Edit Mode, stack order, plane in the object's or the Mirror Object's space, verts within the merge distance of a plane are not copied), as if the copy were real and selected. Blender 5.3's pivot dropdown is drawn by `VIEW3D_HT_header.draw_xform_template`, so the add-on wraps it (restored on unregister): in mesh Edit Mode the dropdown opens our popover with the five built-in pivots (as buttons that also clear the flag), then **Median Point with Mirror** (sets the real pivot to Median Point plus a scene flag), **Only when On Cage** (default off; when on, a Mirror counts only with its On Cage button on) and a status line ("MIR X" / "MIR XY", "MIR off" when no mirror applies); the dropdown button reads "MIR" while on. The S and R keys of the Edit Mesh keymap call `mirror_pivot.transform`, which starts `transform.resize` / `transform.rotate` with `center_override`; with no applicable mirror it falls back to plain Median Point and says why in the status bar; if the real pivot was changed, it clears the flag. **Cursor to Mirrored Selection** (`mirror_pivot.cursor_to_selected`) is in Snap (Mesh Edit Mode) and the Shift+S snap pie. **Mirror Transform** (`mirror_pivot_tools.py`): one Edit Mesh toolbar tool right after Transform (own icon `icons/mirror_transform.dat`, made by `icons/make_mirror_icon.py`). Its gizmo (move arrows, rotate dials X / Y / Z + view, scale boxes + uniform dial; Global or Local) sits on the mirrored centre and Rotate / Scale pivot there; the group's `poll` shows it only while this tool is the active one. Click selects, drag box-selects. It ignores Median Point with Mirror and Only when On Cage (any Mirror enabled in viewport and Edit Mode counts; none = plain median): `applicable_mirrors(obj, only_on_cage)` is the one rule, `tool_center` the one centre. `refresh` recomputes the centre (selected verts only). One pure function (`mirrored_center`) and one modifier rule (`applicable_mirrors`) serve all of it. No handlers or timers. Tests: `tests/test_mirror_pivot.py`, `tests/test_mirror_pivot_tools.py` (gizmo drawing is checked live only).

## Path Generators

**Path Generators** (Object card, `path_generators.py`; the one table is `path_generators_spec.py`) and the 3D View Add
menu: **Add > Curve > Spiral Curve / Knot Curve** and **Add > Mesh > Maze** (Object Mode) add an object at the 3D cursor
whose own data stays empty: a Geometry Nodes generator modifier makes the geometry, so every input stays live (Apply it
for normal geometry). The card has the same three Add buttons and, for a selected generator object, its main inputs
(shared `toony_ui.draw_modifier`, the rest under More). Spiral Curve and Curve to Knot (moved here from Digit's
Modifiers) make one poly spline for Stretch To Curve, Traveling Bulge and Stretchy Limb to follow; **Maze** makes points
and edges only, no faces: its passages (Output Paths) or walls (Output Walls), Width x Height cells, Seed, Braid
(dead ends opened into loops), Cell Size, Shape Rectangle / Circle, Openings. It is a perfect maze (a random spanning
tree, every cell reachable) built fully in Geometry Nodes. Stack Screw (Angle 0) to raise the walls, or Geometry
Nodes; Skin needs the Maze applied first. The node groups ship in this extension's `assets/` folder (`SpiralCurve.blend`,
`CurveToKnot.blend`, `Maze.blend`; no asset library is registered for them, `assets/Previews/` is not shipped), built
by `Scripts/spiral_curve/`, `Scripts/curve_to_knot/`, `Scripts/maze/`. Test: `tests/test_path_generators.py`.

**Placement: General** (`placement_tool.py`, `placement_math.py`): a left-toolbar tool in its own group Placement, in Object, Pose, Edit Mesh and Edit Armature (one WorkSpaceTool per mode, settings on the scene). It only chains Blender's own operators, so nothing runs in Python per mouse move. Click: Object Mode selects ONE object (Grab: Parent Rig = its armature, None = the clicked object, Root Parent = the top of its hierarchy; children follow by parenting), Pose Mode the clicked bone, edit modes keep the selection. Drop: Live Follow on (default) = Blender's Move with snapping (Place On = Face, Middle of Depth = Volume, Set Depth = Face then Depth further along the view); a click drops it. Live Follow off = the next click casts one ray (two for Middle of Depth) and the selection jumps there. Aim After Place: in Object / Pose Mode the Front Axis (default -Y) is first turned to face the mouse on the Spin Axis dial, then Blender's Rotate around the Spin Axis takes over (its own keys; right-click / Esc ends it and keeps the move). The scene's snap settings and 3D cursor are put back. Icon `icons/placement_general.dat` (made by `icons/make_placement_icon.py`). Test: `tests/test_placement.py` (the operator chain is checked live).
