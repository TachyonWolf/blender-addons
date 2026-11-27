# SPDX-License-Identifier: GPL-3.0-or-later
"""A made-up scene for the UI export: the first model of every panel, filled the way the tests fill them (the layouts'
own dataclasses with plain values). Generic names only. Change the values here to see other content on the page."""
from dataclasses import replace

from addon_import import load

desk_layout = load("desk_layout")
rig_layout = load("rig_layout")
outliner_layout = load("outliner_layout")
router = load("router")
sculpt_page = load("sculpt_page")
subdiv_math = load("subdiv_math")
blender_icons = load("blender_icons")

COLLECTION, OBJECT = outliner_layout.COLLECTION, outliner_layout.OBJECT


def _rig_view():
    cells = (("L", rig_layout.CELL_SLIDER, 0.25, 0.0, 1.0), ("R", rig_layout.CELL_SLIDER, 0.5, 0.0, 1.0))
    items = (("ikfk", False, True), ("follows", ("Root", "Torso"), 0, True, False)) + tuple(
        ("row", index, label, cells, index == 0, True) for index, label in enumerate(
            ("Finger curl", "Fist", "Spread", "Thumb", "Wrist bend", "Elbow pole", "Stretch", "Twist", "Roll", "Bend")))
    return rig_layout.RigView(groups=(("Body", True), ("Face", False), ("Deform", False), ("Fingers & Toes", False)),
                              title="Character_Rig", page="Arm L", page_label="Arm L •", reset_part=True, pose_mode=True,
                              status="Arm L: 1 change", items=items,
                              picker=tuple((section, tuple((f"{section} {n}", n == 0) for n in range(4)))
                                           for section in ("Full Body", "Head", "Torso", "Arms", "Legs", "Other")))


def _outliner_rows():
    row = outliner_layout.OutlinerRow
    icon = blender_icons.TYPE_ICONS.get
    return (row(COLLECTION, "Scene Collection", "Scene Collection", 0, True, True, icon=blender_icons.COLLECTION_ICON),
            row(COLLECTION, "Character", "Character", 1, True, True, icon=blender_icons.COLLECTION_ICON),
            row(OBJECT, "Character_Rig", "Character_Rig", 2, icon=icon('ARMATURE'), selected=True),
            row(OBJECT, "Body", "Body", 2, icon=icon('MESH')),
            row(COLLECTION, "Props", "Props", 1, True, False, icon=blender_icons.COLLECTION_ICON),
            row(COLLECTION, "Lights", "Lights", 1, True, True, False, icon=blender_icons.COLLECTION_ICON),
            row(OBJECT, "Camera", "Camera", 1, icon=icon('CAMERA', blender_icons.OTHER), locked=True))


def desk_model():
    assets = desk_layout.AssetsView(
        libraries=("Essentials", "Props library"), chips=((None, "All"), ("furniture", "Furniture"), ("plants", "Plants"),
                                                          ("lights", "Lights"), ("rocks", "Rocks")),
        tiles=tuple((f"key{index}", name, "Object") for index, name in enumerate(
            ("Wooden chair", "Table", "Lamp", "Potted plant", "Rock", "Crate", "Barrel", "Bench", "Shelf", "Stool"))),
        pages=3, total=26, chip_pages=1)
    perf = desk_layout.PerfView(fps=90, python_p95=1.4, triangles=184000, heavy_off=2, heavy_on=0, taa_samples=8,
                                objects_hidden=1, draw_distance=120.0)
    sculpt = load("tool_rows").SculptView(brush='Draw', brushes=sculpt_page.menu({}), size_cm=5.0, strength=0.5)
    edit = load("tool_rows").EditView(usable=True, hidden=True)
    return desk_layout.DeskModel(
        tab='tools', object_name="Body", disabled_modes=(),
        modifiers=(("Armature", "Armature", True), ("Subdivision", "Subdivision Surface", False),
                   ("Smooth Corrective", "Corrective Smooth", False)),
        subdiv=subdiv_math.SubdivView(level=1, minus=True, plus=True, dimmed=False),
        rig=_rig_view(), assets=assets, perf=perf, sculpt=sculpt, edit=edit,
        workspace_rows=_outliner_rows(),
        gp_materials=(("Black", "#1a1a1a"), ("Red", "#d83a3a"), ("Blue", "#3a6ed8"), ("Green", "#3ab05a")),
        gp_layer="Lines", gp_layer_count=2, gp_layers=("Lines", "Fill"), gp_strokes=3,
        hidden_shown=("Old chair", "Backdrop"), hidden_total=2, can_hide=True,
        mirror=(('X', True, True), ('Y', False, True), ('Z', False, False)), mirror_note="Z: this object has no Z mirror.",
        annotate_strokes=2, file_name="scene.blend", file_status="Saved")


def help_rows(mode, grab_mode):
    """The Help panel's rows, from router.help_labels (what help_draw.rows asks in Blender)."""
    labels = router.help_labels(router.mode_kind(mode), grab_mode)
    return tuple((hand, button, *text) for hand, buttons in labels.items() for button, text in buttons.items())


def help_model():
    return load("help_layout").HelpModel(rows=help_rows('OBJECT', 'FREE'))


def tool_options_model(desk):
    """The Tool options panel shows the desk's tool rows (the same ToolsModel fields)."""
    layout = load("tool_options_layout")
    fields = {name: getattr(desk, name) for name in layout.ToolOptionsModel.__dataclass_fields__ if hasattr(desk, name)}
    return layout.ToolOptionsModel(**{**fields, "popup": "", "attached": True})


def pda_model(desk_widgets):
    """Two tabs; the first links three desk controls (their live widgets, as pda.py passes them)."""
    links = ("fine_control", "always_laser", "undo", "", "", "")
    by_id = {widget.id: widget for widget in desk_widgets}
    return load("pda_layout").PdaModel(tabs=(("Posing", links), ("Scene", ("", "", "", "", "", ""))),
                                       linked=tuple(by_id.get(link) for link in links))


def viewpoints_model():
    names = ("Front", "Close-up", "Top", "Desk", "Doorway", "Overview", "Behind")
    layout = load("viewpoint_layout")
    return layout.ViewpointsModel(names=names[:layout.ROWS], page=0, pages=layout.pages(len(names)), total=len(names))


def find_model():
    layout = load("find_layout")
    rows = (("H", "O", "Objects", "", "", False),
            ("O", "Chair", "Chair", "OUTLINER_OB_MESH", "", True), ("O", "Chair.001", "Chair.001", "OUTLINER_OB_MESH", "", False),
            ("H", "C", "Collections", "", "", False), ("C", "Chairs", "Chairs", "OUTLINER_COLLECTION", "", False))
    return layout.FindModel(query="chair", rows=rows, total=3, workspace="Stage")


def keyboard_model():
    return load("keyboard_layout").KeyboardModel(prompt="Rename object", text="Wooden chair")


def camera_model():
    return load("camera_layout").CameraModel(camera="Camera")


def gun_model():
    return load("gun_layout").GunModel(tool='PLACE', note="Shoot a thing.")


def gun_variants(model):
    """The gun's per-tool content (a hidden list, a material list) the menu shows for that tool."""
    return {'HIDE': replace(model, names=("Old chair", "Backdrop"), total=2),
            'MATERIAL': replace(model, names=("Wood", "Metal", "Glass"), total=3, material="Wood")}
