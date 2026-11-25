# Setups (Digit's Tools > Setups)

Six tools in Digit's Assorted Tools (was the separate Camera & Light Rigs add-on): **Camera Rig**,
**Lighting Rig** (Style dropdown: Single Overhead, Three Point, Clamshell, Rim Pair, Rembrandt, Product), **Photo Backdrop** and **Shadow Catcher Floor** (each a card with a **Deploy** button) and **HDRI World** (builds the scene world, see the end). Code: `camera_rig.py`,
`light_rig.py`, `bounce_cards.py` (+ `*_spec.py` data tables), `photo_backdrop.py`, `shadow_catcher.py`, `catchlight.py` (+ `catchlight_spec.py`), `hdri_world.py`, shared `rig_common.py`, placement maths
`rig_placement.py`. Tests: `tests/test_setups.py`, `tests/test_camera_rig.py`, `tests/test_backdrop.py`, `tests/test_hdri_world.py`.

## Deploy

Deploy appends the rig from `Library/` as real, editable objects (not an instance) and places it from
the 3D view. Deploy is a **click to place** modal (`PickDeployOperator` in `rig_placement.py`, shared by all
three): the cursor becomes a crosshair and the header says "Click the target · Enter: screen centre ·
Esc / Right-click: cancel". A left click in any 3D view (camera view too; the other keys and the mouse
wheel still navigate) casts a ray through the mouse (`scene.ray_cast`) and the hit is the target; no hit =
a point along that ray at the view's orbit distance clamped to 1.5-5 m. Enter uses the ray through the
screen centre instead. From a script (no view to click in) it places from the first 3D view's centre. The
options are on the card (stored on the WindowManager). A Setups tool card holds only its status, the Deploy section (options, Deploy / Redeploy; folded once a rig exists, with an icon-only + in its header); the controls of a deployed rig (lens, presets, sliders, colour, size, Select / Remove, rig parts) are in the **Selected** card at the top of the panel, which shows them when a part of the rig is selected.

- **Camera Rig**: camera at the viewport eye (also works in camera view), aimed at the clicked target;
  Aim and Focus on it, so DoF focuses on it. With **Match View** (a three-way choice, below; default Move Camera to Fit Lens) the camera is moved along
  the line of sight so the lens frames the subject like the viewport does (below). The
  dolly stands on the floor under the eye (if it is 0.1-6 m down; else the camera keeps 1.6 m and the dolly
  floats under it). Options: Match View (Move Camera to Fit Lens / Pick Lens to Fit Box / Move Camera to Fit Box / Off), Aim Follows Dolly, Set as Active Camera, Look Through It; pickers Lens and
  Depth of Field (hover tooltips explain each; they also change the rig you have selected live).
  Lens presets (`camera_rig_spec.py`): 14, 24, 35, 50, 85, 135, 200, 100 macro, 35 Cine (Super 35 sensor), phone.
  DoF presets: f/16, f/8, f/5.6, f/2.8, f/1.4, Off.
  **Match View** (`rig_placement.matched_eye`): new eye = target - (target - eye) * tan(view fov / 2) / tan(camera fov / 2),
  so a longer lens backs up along the same line and a shorter one comes closer; equal fields of view change
  nothing. The viewport's tan(fov / 2) is `1 / window_matrix[0][0]` (across) or `[1][1]` (up), which already
  holds the region's aspect and zoom; the camera's is `sensor_width / 2 / lens`, compared on the axis Blender's
  Auto sensor fit uses (across for a landscape render, up for a portrait one, from the render resolution and
  pixel aspect). Skipped (eye as-is) in orthographic views. The floor / dolly rule is applied at the moved eye.
**Match View modes** (`spec.MATCH_VIEWS`, enum `setups_cam_match_view`, each with a teaching tooltip):

- *Move Camera to Fit Lens* (default): the maths above. While you hover for the click, a label beside the
  cursor shows "Camera 4.2 m from the target" (also in the header); it ray-casts once per mouse move of
  more than 3 px (`PickOperator.READOUT_MOVE`) so it stays cheap.
- *Pick Lens to Fit Box*: the camera stays at the eye and the Lens picker is greyed (still live for a
  selected rig). After the target click a **second modal step** starts (`PickOperator.refine_start`): a
  frame in the render aspect is drawn around the target's screen position with the outside darkened
  (`PickOverlay`, a POST_PIXEL draw handler) and one corner on the mouse, with the lens you would get
  ("85 mm") beside the cursor; click confirms, Esc cancels. Maths (plain, tested): `box_around` (frame from
  centre + mouse), `ray_tans` (the four corner rays -> tan across / up around the line to the target),
  `lens_for_tans` (the sensor-fit axis -> focal length, clamped to 8-1200 mm, `spec.LENS_RANGE`). The lens
  chosen is reported. Not in orthographic views (no field of view): it behaves like Off.
- *Move Camera to Fit Box*: keeps the chosen lens (the Lens picker stays active). Same second step as Pick
  Lens to Fit Box (box in the render aspect around the target, corner on the mouse), but on confirm the
  camera moves along the eye -> target line until the box exactly fills the frame with that lens:
  `rig_placement.box_distance` = eye distance * max(box tan / frame tan) across and up (`frame_half_tans` of the
  lens), `eye_for_box` puts the eye there. A bigger box or a longer lens means further. The label beside the
  cursor reads "Camera 6.3 m from the target". Same floor / dolly rule as the other modes; no field of view
  (orthographic): eye as-is.
- **Shift while drawing the box** (both Fit Box modes): the box aspect is freed, the corner follows the mouse in both axes (box
  stays centred on the target) and the label reads e.g. "1600 × 1350 · 1.19:1 · 85 mm". The resolution keeps about the starting
  pixel count (w = sqrt(P r), h = sqrt(P / r), `resolution_for_aspect`); confirming after Shift sets the scene resolution (percentage
  untouched); releasing Shift locks the ratio. The modal only passes `event.shift` (`PickOperator._shift`; pressing / releasing Shift
  redraws); the maths is plain: `aspect_from_box`, `free_box_around`, `snap_ratio`, `resolution_for_aspect`, `ratio_text`.
  **Snap Ratio** (`setups_cam_snap_ratio`, default on): the ratio goes to the nearest of 1:1, 5:4, 4:3, 3:2, 16:10, 16:9, 2:1, 2.39:1
  and 4:5, 3:4, 2:3, 9:16 within 3%, the size to a multiple of 8, or to a `spec.RESOLUTIONS` preset of that ratio within 15% of the
  pixel count; the label names the ratio ("16:9"). Off: free ratio, even numbers.
- **Resolution** deploy option (`spec.RESOLUTIONS`, `setups_cam_resolution`, default Keep Scene): 1920×1080 HD, 2560×1440, 3840×2160 4K,
  2048×858 Cinema 2.39:1, 1080×1080 / 2048×2048 / 1920×1920 Square, 1080×1350 Portrait 4:5, 1080×1920 Vertical 9:16. Deploy
  (`camera_rig.apply_resolution`) sets the scene resolution first, so the box and lens use its aspect.
- *Off: Camera at My Eye*: exactly the eye and the chosen lens.

The draw handler is removed on every exit (confirm, cancel, operator killed: `PickOperator._end_pick`).

- **Lighting Rig**: Focus on the target (the ground itself: lifted to 1.3 m), rig root on the floor
  under it (ray down; none: 1.3 m below the Focus), turned so Swing 0 (the camera side) faces the viewer. Options:
  Style, Start With (that style's presets; changing Style resets it to the style's first), Face the Viewer. Also
  Add > Light > Lighting Rig > <style>. Below the Deploy section one row of shortcuts, **Add Catchlight** and
  **Add Bounce Card**, then two folded sections, **Catchlight** and **Bounce Cards**: their Deploy options (and Catchlight's
  Remove), drawn by `catchlight.draw_section` / `bounce_cards.draw_section`. They are no longer dropdown tools; the operators,
  F3 / Add menu entries and Selected card parts stay.
- **Bounce Cards**: BC_Focus on the target (the ground: lifted 1 m), the card 1.2 m to the viewer's right
  and 0.5 m closer, aimed at the Lighting Rig's Focus (any style) if the scene has one, else at BC_Focus. Options:
  Start With (preset), Aim at Light Rig. Also Add > Light > Bounce Card.

- **Photo Backdrop** and **Shadow Catcher Floor** are floors, not rigs: they do NOT go at the clicked point
  but just under the clicked object (`rig_placement.ground_under_click`, below).

## Redeploy (Camera Rig, Lighting Rig)

When the scene has **exactly one** rig of a kind (found by its tag property: `camrig_dolly`, `tpl2_rig`;
`rig_placement.rig_roots`), its card shows a **Redeploy** button above Deploy (tooltip "Move this rig to a
new spot with the same click, keeping all its settings"). It runs the same click flow (and the box step of
the camera's box modes) but calls `place(..., existing=rig)`: only placement changes, no new objects. Camera:
dolly, camera height, Aim (and Focus unless it is keyed); keeps lens (unless Pick Lens to Fit Box; Fit Lens /
Move to Fit Box use the rig camera's own lens), DoF, Aim Follows Dolly, active camera. Light: root location /
Z rotation and Focus; keeps style, preset, sliders and scale (all styles share the tag, so "one rig" means one
Lighting Rig of any style).

Pressing **Deploy** with exactly one rig present first opens a popup "A Camera Rig already exists. Deploy a
second one?" with **Yes** (deploy a new one), **No** (cancel, `setups.dismiss`) and **Redeploy Existing**.
With 0 or 2+ rigs there is no Redeploy button and Deploy runs straight away. Written in `PickDeployOperator`:
a setup opts in with `root_tag` + `rig_label` and a `place(..., existing=None)` that handles `existing`;
`draw_deploy_buttons` draws the button row. The pure decisions (`show_redeploy`, `needs_confirm`) are tested;
the popup (`wm.popup_menu`) and modal can't run headless.

## Under the subject (Photo Backdrop, Shadow Catcher Floor)

The click's ray hits an object; its **lowest world-space point** (evaluated geometry: modifiers, shape keys,
armature pose) is the floor height, the floor goes `GROUND_GAP` (2 mm) below it so they never z-fight, centred
on the middle of the geometry's x/y bounds. If the hit object is deformed by or parented to an armature, the
subject is the whole character: every mesh of that rig (`subject_objects`). A click that hits nothing uses the
fallback point ahead (1.5-5 m) and the first surface below it (else the point's own height).

- **Photo Backdrop** (`Library/PhotoBackdrop.blend`, collection appended as real objects; no light of its own): the
  wall is turned to be behind the subject as seen from the viewer (the asset's +Y wall side points away from
  the eye, so the subject faces the viewer). The sheet is tagged `setups_photo_backdrop`. Option **Colour**
  (default 0.92 linear near-white: white / light-grey backdrops bounce soft light and are easy to key; coloured
  ones set a mood) is written to the sheet's material Base Color (each backdrop gets its own material copy);
  the card, with a backdrop or its light active, shows that socket itself so changes are live. The asset's own
  default is light sky blue; the Colour option overrides it on every Deploy (asset file untouched).
  Nested **Lighting Rig** option (`setups_backdrop_light`): **Style** = None or any Lighting Rig style (default
  Single Overhead). Deploy then also appends that style's rig with `light_rig.deploy_on_ground` (the same
  `Ground` the floor used, which carries the subject's height): root under the subject, scaled to its height
  (Focus at chest height), camera side towards the viewer; an empty click with no real height: scale 1. The rig
  is a normal Lighting Rig (own Selected controls, Redeploy). Backdrops deployed before 2026-11-11 have the
  asset's old soft wall light parented to the sheet; `sheet_of` still finds the backdrop from it.
- **Shadow Catcher Floor**: a generated square plane (no asset) with `is_shadow_catcher` on (Cycles only; the card
  warns when the engine is not Cycles) and tag `setups_shadow_catcher`. Options **Size** (m) and **Transparent
  Film** (`scene.render.film_transparent`, so the render composites over a photo). With a catcher active the
  card shows its width / length, the scene's Transparent Film, Select and Remove.
- **Catchlight**: a tiny generated area light (no asset) that puts the sparkle in a character's eyes, tagged
  `setups_catchlight`. Deploy: click the eye (or face). The light goes on the viewer's side, `Distance` m (default
  0.8) from the clicked point, turned 35 degrees off the viewer's line towards the **Clock Position** (10 / 12 / 2
  o'clock as the viewer sees it, `rig_placement.catchlight_location`; the reflection sits about halfway round the
  eyeball, so it lands near that hour), aimed at the click (`aim_euler`). Looking through the scene camera, the
  camera is the viewer. Sparkle only, no skin light: Cycles `visible_diffuse` off / `visible_glossy` on on the light
  object, EEVEE `diffuse_factor` 0 / `specular_factor` 1 (both always set), shadows off. **Light linking**
  (`light_linking.receiver_collection`, a private collection per light): the separate eye meshes of the clicked
  character within 10 cm of the click (names containing "eye", not lash / lid / brow / socket), else the clicked
  object; the card says which ("Linked to the eyes: ..."). Options **Clock Position**, **Distance**, **Size**
  (m; smaller = crisper dot), **Strength**, **Shape** (Round = disk, Square reads like a window), **Colour**, all
  with teaching tooltips (high catchlights look natural, low ones eerie); one light sparkles in both eyes. With
  exactly one catchlight the card offers Redeploy (moves + re-links it, keeps Size / Strength / Shape / Colour);
  Deploy then asks Yes / No / Redeploy Existing. With one active the card shows its live Size / Strength /
  Colour, Select and Remove (also removes the receiver collection). Test `tests/test_catchlight.py`.

## Camera Rig

A camera on a dolly that looks at an Aim empty, with a Focus empty for depth of field.
The rig is the `Camera Rig` collection asset in `Library/CameraRig.blend` (catalog **Tools/Rigs**).
This add-on adds a sidebar tab to drive it.

## The rig

| Object | What it does |
| --- | --- |
| `CamRig_Dolly` | Root (arrows on the ground, Y = facing). Move/rotate it to move the camera. |
| `CamRig_Camera` | Child of the Dolly at 1.6 m. Grab it to move it relative to the dolly; its rotation comes from a Track To on the Aim. f/2.8, DoF on. |
| `CamRig_Aim` | Sphere the camera looks at. Rotate it (around its view axis) to roll the camera. |
| `CamRig_Focus` | Small cube, child of the Aim. DoF focuses on it; offset it to focus in front of or behind the Aim. |

**Aim Follows Dolly** (custom property on the Dolly, off by default):

- On: the Aim and Focus move with the Dolly (Child Of constraint, influence driven by the property).
- Off: the Aim stays put in world space and the camera keeps tracking it while the dolly moves.
- The driver is a simple expression, so it works with Python auto-run disabled.
- Without the add-on you can flip the checkbox in Object Properties > Custom Properties, but the
  Aim jumps if the Dolly isn't at the origin. Use the add-on's toggle to switch without a jump.
- It's off by default because dropping the asset as real objects moves both the Dolly and the
  Aim by the drop offset. With follow on, the Aim would get that offset twice.

## Adding it to a scene

Drag `Camera Rig` from the Asset Browser. Collection assets drop as a **collection instance** by
default, which you can't edit. To get real, editable objects, open the **Adjust Last Operation**
panel (bottom left) right after the drop and untick **Instance**. With the library's Import
Method set to **Append**, each drop is an independent copy (`CamRig_Dolly.001`, ...). Copies
don't share drivers, constraints or focus objects.

Then set it as the active camera (select `CamRig_Camera`, Ctrl+Numpad 0).

## Camera card

In the 3D View sidebar (N) > Digit's Tools > Setups > Camera Rig, the Rig section shows when any rig object is active:

- **Focus Follows Dolly / Focus Stays Put**: flips the property and keeps the Aim where it is.
  With auto-keying on, it keys the property (constant interpolation) and the Aim's transform
  at the current frame.
- Focal length, f-stop and DoF toggle of the rig camera.
- Select Dolly / Camera / Aim / Focus.
- **Snap Focus to Aim**.
- **Frame Subject** (+ Margin, default 10%): with a rig active and another object selected, or after a click
  on the subject (modal pick; Enter: screen centre), Aim and Focus go to the middle of the subject and the
  camera moves along the line from there to where it stands now (direction kept) until the subject fills
  the frame with the camera's current lens, sensor fit and the render aspect. The subject is the box
  around the evaluated geometry (`rig_placement.world_bounds`: modifiers, shape keys, pose), for a
  character all meshes of its rig (`rig_placement.subject_objects`), for an empty its geometry children.
  Maths in `rig_placement.py`: `frame_half_tans`, `camera_axes`, `frame_distance` (each corner needs
  distance >= depth + |across| / usable tan, and likewise up; usable tan = tan * (1 - margin), so
  margin 10% leaves 5% empty each side). Two passes, since the camera's up turns as it re-aims.
  With auto-keying on it keys the camera, Aim and Focus locations.

### Focus Pull (sub-card)

Pick Focus A / Pick Focus B (the shared click-pick; the points are stored on the Dolly as
`Focus Pull A` / `Focus Pull B`), Frame A / Frame B (picking A sets frame A to the current frame and,
if B is not picked yet, frame B to A + 48), Ease (`spec.FOCUS_EASES`: Smooth = Bezier, Linear),
**Apply Focus Pull** and **Clear Focus Pull**. Apply keys the Focus's location at A and B. The Focus is
a child of the Aim, so each key is the *local* location that lands on the world point as the rig stands
at that frame (the scene is stepped to that frame and the Aim's matrix read; `rig_placement.local_point`):
the pull lands exactly on the picked points when the Aim stands still, and keeps its offset from the Aim
if the Aim moves (follow on). The key frames are stored on the Focus (`Focus Pull Frames`); Clear removes
only those keys. The tooltips teach rack focus: it moves the viewer's attention and works best at
f/1.4-f/2.8.

### Composition Guides (sub-card)

**Look Through Camera** (makes the rig camera the scene camera and switches this 3D view to it), one toggle
per built-in camera guide from the table `spec.GUIDES` (thirds, centre, centre diagonal, golden ratio,
golden triangles A / B, harmonic triangles A / B; each tooltip explains the rule), and **Darken Outside**
(passepartout alpha, 0 = off).

The add-on finds the rig through custom properties on the Dolly (`camrig_dolly` tag and the
`camrig_camera`, `camrig_aim` and `camrig_focus` object pointers), not by names, so appended
copies work.

## Camera tests

`tests/test_camera_extras.py` (framing / box-to-lens maths, Frame Subject fit measured with `world_to_camera_view`, Focus Pull keys at A / B world points, guide toggles, Match View modes).

`tests/test_camera_rig.py` (asset structure, follow switch, append) and `tests/test_setups.py` (Deploy, presets); both run from `tests/run_tests.sh`.

# Lighting Rig

Area lights that always aim at a Focus, in one of several **styles**. One asset per style, catalog **Tools/Rigs**:

| Style | Asset (Library file) | Lights | Look |
| --- | --- | --- | --- |
| Single Overhead | `Single Overhead Light` (`SingleOverheadLight.blend`) | Top | One big soft box high above the subject (Height 75) leaning towards the camera: bright head and shoulders falling off downwards, light pooled around the feet. Photo Backdrop's default. |
| Three Point | `Three Point Light` (`ThreePointLight.blend`) | Key, Fill, Rim | Classic portrait: key side-above, fill 3:1, rim behind. |
| Clamshell | `Clamshell Light` (`ClamshellLight.blend`) | Key, Fill | Beauty: key above the camera aimed down, weaker wide strip fill (5:2) below aimed up, clear of the floor. |
| Rim Pair | `Rim Pair Light` (`RimPairLight.blend`) | Left, Right, Fill | Two kickers behind left / right, weak soft front fill. |
| Rembrandt | `Rembrandt Light` (`RembrandtLight.blend`) | Key, Fill | Low key: small strong key 45° side / 40° up, very weak fill. |
| Product | `Product Light` (`ProductLight.blend`) | Top, Left, Right | Turntable: big soft top light, two tall strip lights (rectangles 1:3.5) at the sides. |

**Styles are data** (`light_rig_spec.STYLES`): each is one `style(...)` entry with its lights (`light(...)`: Swing,
Height, Softness, Temperature, Shadow, brightness kind, optional strip aspect) and presets. Every style builds
the same structure with the same code (`build_light_rig.build(style)`), and every tool (`light_rig.py`: sliders,
drivers, presets, Fit, Face Camera, Unlock, Redeploy, Selected card) reads the rig's style (`style_of(rig)`,
from the root's `tpl2_style`; missing = Three Point, so rigs made before styles keep working). Adding a style =
a spec entry + `build_light_rig.py -- <STYLE_ID>`.

**Edit it on `<prefix>_Rig`** (Object Properties > Custom Properties, or the Selected card),
**or press Unlock to edit the lights directly.** The lights' power, size, colour, temperature and
shadow fields are driven by the sliders (they show purple); every one of them has a slider.

| Object | What it does |
| --- | --- |
| `<prefix>_Rig` (`TPL2_Rig`, `Overhead_Rig`, `Clamshell_Rig`, ...) | Root and all the sliders, tag `tpl2_rig` for every style. Move / rotate / scale it to place the whole setup. Its -Y side is the camera side (Swing 0). |
| `<prefix>_Focus` | Sphere the lights aim at; put it on the character's chest / face. The lights orbit around it. |
| `<prefix>_<Light>` | The lights. Grab them freely: they keep aiming at the Focus and keep the same brightness on the subject. |
| `<prefix>_<Light>Orbit` | Pivots turned by the Swing / Height sliders (not selectable). |

Sliders (all keyable, with tooltips): **Exposure** (stops, all lights); the first light's **Strength**
(brightness on the subject, like a Sun strength); each other light follows it as a **Ratio** (main:light,
3 = a third) or a **Strength** multiple (x main); per light **Swing** (around the subject, 0 = camera, + = camera's
left), **Height** (angle above the Focus, 89 = straight overhead, negative = below aimed up), **Softness**
(size / distance: small = crisp shadows; strips also drive their length), **Temperature** (K), **Tint**, **Shadow**.
Three Point keeps its names: Key Strength, Fill Ratio, Rim Strength.

**Same brightness across styles**: the main light's default Strength is not set by hand. `style()` works it out
so every style gives a standing figure the same light on the side the camera sees (`SUBJECT_LIGHT`;
`subject_light` = each light's share times how much it faces the camera, half for a head (sphere), half for a
body (vertical cylinder), so a light from straight above counts for the head only). Switching styles keeps
about the same subject brightness; Exposure and Strength still work as before. Every light also stays fully
above the floor at its defaults (a light poking through the floor draws a hard line on it; tested).

Brightness is power = strength x pi x distance^2 and size = softness x distance, so moving a
light, the Focus or scaling the rig (mouse-sized or giant characters) keeps the look. The drivers
are simple expressions, so they work with Python auto-run off.

## Adding it

- **Deploy** (see above) or **Add > Light > Lighting Rig > <style>**. Fit it to a character afterwards with **Fit to Selected** (stands under the selection, scaled to its height) and **Face Camera**.
- **Drag from the Asset Browser**: untick **Instance** in Adjust Last Operation for editable
  objects. If you left it as an instance, select it and press **Make Rig Editable** in the Selected card.
- With a **Photo Backdrop** (its nested Lighting Rig Style).

## Rig section (Selected card, when a rig object is active)

- Presets of its style. Three Point: **Portrait** (the defaults: soft, 3:1, warm key, cool rim), **Dramatic** (8:1, high hard
  key, strong rim), **Toon Flat** (1.5:1, soft, strong thin rim), **Toon Hard** (crisp small sources). Single Overhead: Soft Top,
  Hero Top, Butterfly. Clamshell: Beauty, Bright Beauty. Rim Pair: Edges, Cool Edges. Rembrandt: Rembrandt, Chiaroscuro.
  Product: Clean, Contrast. The first preset of each style is its defaults.
  Presets set angles, softness, ratios and temperatures; Exposure, the main Strength, tints and shadows stay.
- **Fit to Selected** (select the character and a rig part), **Face Camera**.
- All sliders, grouped per light.
- **Unlock Lights**: removes the drivers, keeping the values; the panel then shows the lights' own
  power / size / colour. **Link to Sliders** drives them again (overwrites direct edits).
- Select Rig / Focus / each light.

## Building and tests

- Build: `nice -n 19 blender -b --factory-startup -noaudio --python Scripts/light_rig/build_light_rig.py -- [STYLE_ID ...]`
  (no ids: every style, one Library file each; backs up an existing file to `~/AI/Backups/blender-library-<date>/`).
  Styles, names, sliders, defaults, presets and which fields they drive: `light_rig_spec.py` (one place for the
  builder, panel and tests).
- Thumbnail: `blender -b --factory-startup -noaudio --python Scripts/asset_previews.py -- "<asset name>"` (every style is
  listed there; only Three Point has a thumbnail so far).
- Tests: `Scripts/light_rig/tests/run_tests.sh [library folder]` (every style; `LIGHT_RIG_RENDERS=1` adds two small
  renders into `~/Downloads/wip/light-rig/`, ask first).

# HDRI World

Card **HDRI World** (`hdri_world.py`, data + tooltips `hdri_world_spec.py`, test `tests/test_hdri_world.py`): builds / updates the scene's World for an HDRI (a photo of a real place that records the light from every direction).

- **HDRI** list: Blender's bundled studio lights (`datafiles/studiolights/world`: city, courtyard, forest, interior, night, studio, sunrise, sunset) plus every .hdr / .exr in **HDRI Folder** (default: the first existing of `Projects/project/Assets/HDRIs`, `.../asset/Assets/HDRIs` (the world-specific ones), `Downloads/HDRIs`; empty if none). **File** takes any .hdr / .exr path and wins over the list.
- **Apply HDRI** builds the node tree (every node tagged with the custom property `digit_hdri` = its role). A world with untagged nodes of your own is never touched: a new World "HDRI World" is assigned (reused next time) and the old one is kept. A fresh default world is used as is.
- Options update the tagged nodes live: **Strength** (light brightness), **Rotation** (turn the sun / key around the vertical axis), **Background** Show / Hide (Film > Transparent off / on), **Background Strength** (brightness the camera sees, via a Light Path *Is Camera Ray* mix, separate from the light), **Background Blur**.
- Blur choice: a second Environment Texture for camera rays only, looked up at directions jittered by a high-frequency Noise Texture (Vector Math subtract 0.5, scale, add). Works in Cycles (sample averaging, use the denoiser smooths it) and EEVEE (fine frosted grain, not a true blur). Lighting and reflections stay sharp. Blur 0 = exact lookup.
- Status line: current HDRI name or "No HDRI world".
