# SPDX-License-Identifier: GPL-3.0-or-later
"""Lighting Rig (Digit's Tools > Setups): Deploy button with a Style dropdown, sliders, drivers and card for the
Lighting Rig assets (one per style: Single Overhead, Three Point, Clamshell, Rim Pair, Rembrandt, Product).

Every style's rig: <prefix>_Rig (root, holds every slider as a custom property, its style in STYLE_PROP)
> <prefix>_Focus (what the lights aim at) > <prefix>_<Light>Orbit (pivot, turned by the Swing / Height sliders)
> <prefix>_<Light> (area light, Track To the Focus, free to grab). Styles, names, sliders and presets live in
light_rig_spec; everything here works on any style through `style_of(rig)`."""

import bpy
from bpy.props import BoolProperty, EnumProperty
from mathutils import Matrix, Vector

from . import light_rig_spec as spec
from . import bounce_cards, catchlight, rig_common, rig_placement as placement
from .rig_common import find_root, pointer, select_only
from . import selected_ui
from .ui_cards import action_row, enum_label, friendly_name, inside_frame, prop_group, section, status, sub_card, sub_heading  # generated copy

LABEL = "Lighting Rig"


# ---------------------------------------------------------------------------
# Finding the rig
# ---------------------------------------------------------------------------

def style_of(rig):
    """The spec style of a rig (rigs made before styles are Three Point)."""
    return spec.STYLE_BY_ID.get(rig.get(spec.STYLE_PROP, spec.DEFAULT_STYLE), spec.STYLE_BY_ID[spec.DEFAULT_STYLE])


def part_names(style):
    """The part names of a style's rig: 'focus', then '<light>' and '<light>_orbit' per light."""
    return ("focus",) + tuple(f"{L.lower()}{kind}" for L in style["lights"] for kind in ("", "_orbit"))


def part(rig, name):
    """Rig part: 'rig', 'focus', '<light>' (e.g. 'key') or '<light>_orbit'."""
    return rig if name == "rig" else pointer(rig, "tpl2_" + name)


def find_rig(context):
    return find_root(context, spec.ROOT_TAG, spec.PART_TAG,
                     lambda rig: [part(rig, p) for p in part_names(style_of(rig))])


def is_unlocked(rig):
    return bool(rig.get(spec.UNLOCKED_PROP, False))


def rig_instance(context):
    """The active object if it's a collection instance of a light rig (can't be edited)."""
    ob = context.active_object
    coll = ob.instance_collection if ob and ob.instance_type == 'COLLECTION' else None
    if coll and any(o.get(spec.ROOT_TAG) is not None for o in coll.all_objects):
        return ob
    return None


# ---------------------------------------------------------------------------
# Sliders and drivers (also used by Scripts/light_rig/build_light_rig.py)
# ---------------------------------------------------------------------------

def define_props(rig, style):
    """(Re)create every slider of the style on the rig with its default, range and tooltip, and record the style."""
    rig[spec.STYLE_PROP] = style["id"]
    rig_common.define_props(rig, style["props"], spec.stored)


def _target_of(rig, light, target):
    return part(rig, light.lower()).data if target == "light" else part(rig, light.lower() + "_orbit")


def add_drivers(rig):
    """Drive every light and orbit field listed in the style's driven fields from the rig's sliders."""
    focus = part(rig, "focus")
    style = style_of(rig)
    for light in style["lights"]:
        light_ob = part(rig, light.lower())
        for target, path, index, expression, variables in style["fields"][light]:
            driver = rig_common.add_scripted_driver(_target_of(rig, light, target), path, index, rig,
                                                    variables, expression)
            if target == "light":
                dist = driver.variables.new()
                dist.name, dist.type = "d", 'LOC_DIFF'
                dist.targets[0].id, dist.targets[1].id = light_ob, focus
                scale = driver.variables.new()
                scale.name, scale.type = "sc", 'TRANSFORMS'
                scale.targets[0].id = rig
                scale.targets[0].transform_type = 'SCALE_AVG'
                scale.targets[0].transform_space = 'WORLD_SPACE'
    rig[spec.UNLOCKED_PROP] = False
    rig.update_tag()


def remove_drivers(rig):
    """Unlock: drop the drivers, keeping the values they gave, so the lights can be edited directly."""
    bpy.context.view_layer.update()
    style = style_of(rig)
    for light in style["lights"]:
        for target, path, index, _, _ in style["fields"][light]:
            id_ = _target_of(rig, light, target)
            value = getattr(id_, path)
            value = value[index] if index >= 0 else value
            id_.driver_remove(path, index)
            if index >= 0:
                getattr(id_, path)[index] = value
            else:
                setattr(id_, path, value)
    rig[spec.UNLOCKED_PROP] = True


def apply_preset(rig, name):
    """Set the rig's sliders to one of its style's presets."""
    for prop, value in style_of(rig)["presets"][name].items():
        rig[prop] = spec.stored(prop, value)
    rig.update_tag()


def fit_to_objects(rig, objects, depsgraph):
    """Stand the rig under the objects' bounding box and scale it to their height."""
    corners = [ob.matrix_world @ Vector(c) for ob in objects for c in ob.evaluated_get(depsgraph).bound_box]
    lo = Vector(min(c[i] for c in corners) for i in range(3))
    hi = Vector(max(c[i] for c in corners) for i in range(3))
    fit_to_box(rig, Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)), hi.z - lo.z)


def fit_to_box(rig, base, height):
    """Stand the rig at `base` (the middle of a subject's bottom) and scale it to the subject's `height` (Focus reset)."""
    scale = max(height, 0.01) / spec.SUBJECT_HEIGHT
    rig.location = base
    rig.scale = (scale, scale, scale)
    part(rig, "focus").location = (0.0, 0.0, spec.FOCUS_HEIGHT)


def face_camera(rig, camera):
    """Turn the rig around Z so its -Y side (where Swing 0 sits) points at the camera."""
    face_point(rig, camera.matrix_world.translation)


def face_point(rig, point):
    rig.rotation_euler.z = placement.yaw_toward(rig.matrix_world.translation, point)


def root_objects(coll):
    return [ob for ob in coll.all_objects if ob.parent is None]


def _subjects(context):
    return [ob for ob in context.selected_objects
            if ob.get(spec.PART_TAG) is None and ob.get(spec.ROOT_TAG) is None
            and ob.type in {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'ARMATURE', 'CURVES', 'POINTCLOUD'}]


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _RigOperator:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return find_rig(context) is not None


class LIGHTRIG_OT_preset(_RigOperator, bpy.types.Operator):
    """Set the light angles, softness, ratios and colours to a preset (Exposure and the main brightness stay)"""
    bl_idname = "light_rig.preset"
    bl_label = "Light Rig Preset"

    preset: EnumProperty(items=spec.all_preset_items())

    def execute(self, context):
        rig = find_rig(context)
        if self.preset not in style_of(rig)["presets"]:
            self.report({'WARNING'}, f"{style_of(rig)['label']} has no preset {self.preset}")
            return {'CANCELLED'}
        apply_preset(rig, self.preset)
        return {'FINISHED'}


class LIGHTRIG_OT_fit(_RigOperator, bpy.types.Operator):
    """Stand the rig under the selected objects and scale it to their height (Focus reset)"""
    bl_idname = "light_rig.fit"
    bl_label = "Fit to Selected"

    def execute(self, context):
        subjects = _subjects(context)
        if not subjects:
            self.report({'WARNING'}, "Select the character too (Ctrl+click it, rig part last)")
            return {'CANCELLED'}
        fit_to_objects(find_rig(context), subjects, context.evaluated_depsgraph_get())
        return {'FINISHED'}


class LIGHTRIG_OT_face_camera(_RigOperator, bpy.types.Operator):
    """Turn the rig so Swing 0 points at the scene camera"""
    bl_idname = "light_rig.face_camera"
    bl_label = "Face Camera"

    def execute(self, context):
        if context.scene.camera is None:
            self.report({'WARNING'}, "The scene has no camera")
            return {'CANCELLED'}
        face_camera(find_rig(context), context.scene.camera)
        return {'FINISHED'}


class LIGHTRIG_OT_unlock(_RigOperator, bpy.types.Operator):
    """Unlock: remove the drivers so you can edit the lights' own power, size and colour directly
    (the sliders stop working until you press Link to Sliders)"""
    bl_idname = "light_rig.unlock"
    bl_label = "Unlock Lights"

    def execute(self, context):
        remove_drivers(find_rig(context))
        return {'FINISHED'}


class LIGHTRIG_OT_lock(_RigOperator, bpy.types.Operator):
    """Drive the lights from the rig's sliders again (overwrites direct edits to the lights)"""
    bl_idname = "light_rig.lock"
    bl_label = "Link to Sliders"

    def execute(self, context):
        add_drivers(find_rig(context))
        return {'FINISHED'}


class LIGHTRIG_OT_select_part(_RigOperator, bpy.types.Operator):
    """Select this part of the light rig"""
    bl_idname = "light_rig.select_part"
    bl_label = "Select Light Rig Part"

    part: EnumProperty(items=[(p.upper(), p.title(), "") for p in ("rig", "focus") + tuple(
        L.lower() for L in spec.ALL_LIGHTS)])

    def execute(self, context):
        rig = find_rig(context)
        name = self.part.lower()
        if name not in ("rig",) + part_names(style_of(rig)) or not select_only(context, part(rig, name)):
            self.report({'WARNING'}, "Rig part is missing or hidden")
            return {'CANCELLED'}
        return {'FINISHED'}


class LIGHTRIG_OT_make_editable(bpy.types.Operator):
    """Turn this dropped instance into real, editable rig objects in the same place"""
    bl_idname = "light_rig.make_editable"
    bl_label = "Make Rig Editable"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return rig_instance(context) is not None

    def execute(self, context):
        inst = rig_instance(context)
        coll = inst.instance_collection
        if coll.library is not None or coll in context.scene.collection.children_recursive:
            self.report({'ERROR'}, "This rig is linked or already in the scene: set the asset "
                                   "library's Import Method to Append, or drop it with Instance unticked")
            return {'CANCELLED'}
        place = inst.matrix_world @ Matrix.Translation(-coll.instance_offset)
        target = inst.users_collection[0] if inst.users_collection else context.scene.collection
        target.children.link(coll)
        for ob in root_objects(coll):
            ob.matrix_world = place @ ob.matrix_world
        bpy.data.objects.remove(inst)
        rig = next(o for o in coll.all_objects if o.get(spec.ROOT_TAG) is not None)
        context.view_layer.update()
        select_only(context, rig)
        return {'FINISHED'}


def new_rig(context, path, style_id, preset=None):
    """Append a style's rig from `path` as real objects at scale 1, set to `preset` (default: the style's first)."""
    style = spec.STYLE_BY_ID[style_id]
    rig = rig_common.append_rig(context, path, style["asset"], spec.ROOT_TAG)[1]
    rig.scale = (1, 1, 1)
    apply_preset(rig, preset or spec.default_preset(style_id))
    return rig


def deploy(context, view, path, preset=None, face_viewer=True, existing=None, style=spec.DEFAULT_STYLE):
    """Append the Lighting Rig of `style` from `path` as real objects: Focus on what the view centre points at
    (first ray hit, else a close point ahead; on the ground itself, lifted to chest height), the rig's
    root on the floor under it, turned so Swing 0 (the camera side) faces the viewer. Returns the rig.
    `existing` (a rig root): Redeploy, move that rig instead of appending one; only its placement changes
    (its style, scale, preset and sliders stay)."""
    target, depsgraph = placement.view_target(context, view)
    floor_z = placement.floor_below(context.scene, depsgraph, target)
    focus_point = placement.subject_point(target, floor_z, spec.FOCUS_HEIGHT)
    rig = existing if existing is not None else new_rig(context, path, style, preset)
    rig.location, yaw = placement.light_placement(focus_point, floor_z, spec.FOCUS_HEIGHT, view.eye)
    rig.rotation_euler.z = yaw if face_viewer else 0.0
    part(rig, "focus").location = (0, 0, (focus_point.z - rig.location.z) / rig.scale.z)   # local: a fitted rig is scaled
    context.view_layer.update()
    select_only(context, rig)
    return rig


def deploy_on_ground(context, path, ground, style, preset=None):
    """Append the Lighting Rig of `style` fitted to the subject a floor tool measured (`ground`, a
    rig_placement.Ground: standing on its bottom, scaled to its height; no real height, e.g. an empty click:
    scale 1), Swing 0 towards the viewer. Photo Backdrop deploys its light this way. Returns the rig."""
    rig = new_rig(context, path, style, preset)
    height = ground.height if ground.height and ground.height > placement.ON_FLOOR else spec.SUBJECT_HEIGHT
    fit_to_box(rig, ground.centre, height)
    context.view_layer.update()
    face_point(rig, ground.eye)
    context.view_layer.update()
    return rig


CARD_STYLE = "CARD"   # the deploy operator's style "use the card's Style"


def library_of(style_id):
    return spec.STYLE_BY_ID[style_id]["library"]


class LIGHTRIG_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a Lighting Rig as real, editable objects: click what to light (Enter: the screen centre).
    The Focus lands on it, the rig stands on the floor under it, camera side towards you"""
    bl_idname = "light_rig.deploy"
    bl_label = "Deploy Lighting Rig"
    bl_options = {'REGISTER', 'UNDO'}
    root_tag = spec.ROOT_TAG
    rig_label = LABEL

    style: EnumProperty(name="Style", options={'SKIP_SAVE'},
                        items=[(CARD_STYLE, "Card's Style", "The Style chosen on the Lighting Rig card")] + spec.style_items())

    def chosen_style(self, context):
        return context.window_manager.setups_light_style if self.style == CARD_STYLE else self.style

    def prepare(self):
        self.library_name = library_of(self.chosen_style(bpy.context))
        return super().prepare()

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        style = self.chosen_style(context)
        preset = wm.setups_light_preset if style == wm.setups_light_style else None
        deploy(context, view, path, preset, wm.setups_light_face_viewer, existing, style)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


def draw_card(layout, context):
    """The Lighting Rig tool: Style and Deploy; the rig's own controls are in the Selected card. Below, shortcuts
    to Catchlight / Bounce Card Deploy, then their folded sections (options, Catchlight Remove)."""
    body = layout   # the tool dropdown is the title
    placement.draw_scene_status(body, context.scene, spec.ROOT_TAG, "lighting rig", 'LIGHT_AREA',
                                selected=find_rig(context) is not None)
    wm = context.window_manager
    count = len(placement.rig_roots(context.scene.objects, spec.ROOT_TAG))
    placement.draw_deploy(body, "setups_light_rig_options", LIGHTRIG_OT_deploy.bl_idname, count,
                          lambda sec: prop_group(sec, wm, [("setups_light_style", "Style"),
                                                           ("setups_light_preset", "Start With"),
                                                           ("setups_light_face_viewer", "Face the Viewer")]),
                          summary=f"{enum_label(wm, 'setups_light_style')} · {enum_label(wm, 'setups_light_preset')}")
    draw_light_shortcuts(body)
    draw_other_light_sections(body, context)


def draw_light_shortcuts(layout):
    """One row: the Catchlight and Bounce Card Deploy operators (the same ones their sections below run)."""
    layout.separator()
    row = action_row(layout, scale=1.0)
    row.operator(catchlight.CATCHLIGHT_OT_deploy.bl_idname, text="Add Catchlight", icon='LIGHT_POINT')
    row.operator(bounce_cards.BOUNCECARD_OT_deploy.bl_idname, text="Add Bounce Card", icon='MESH_PLANE')


def draw_other_light_sections(layout, context):
    """Folded Catchlight and Bounce Cards sections (their Deploy options, Catchlight's Remove): the cards' own
    draw code, so the Lighting Rig card is the one place that deploys and removes them."""
    for idname, title, icon, draw_section in (
            ("setups_light_rig_catchlight", "Catchlight", 'LIGHT_POINT', catchlight.draw_section),
            ("setups_light_rig_bounce_cards", "Bounce Cards", 'MESH_PLANE', bounce_cards.draw_section)):
        body = sub_card(layout, idname, title, icon=icon)
        if body:
            with inside_frame():   # the sections' own Deploy box is a plain group in this frame
                draw_section(body, context)


def draw_selected(box, context):
    """The Selected card's part: presets, sliders and rig parts of the lighting rig the selected object belongs to,
    or Make Editable for a collection instance of one."""
    rig = find_rig(context)
    status(box, rig_summary(rig, rig_instance(context)), icon='LIGHT_AREA' if rig else 'INFO')
    if rig is None:
        box.operator(LIGHTRIG_OT_make_editable.bl_idname, icon='OBJECT_DATA')
        return
    body = box
    draw_presets(body, rig)
    if is_unlocked(rig):
        draw_unlocked_lights(body, rig)
    else:
        draw_locked_lights(body, rig)
    draw_rig_tools(body, rig)


def selected_title(context):
    rig = find_rig(context)
    if rig is None:
        return friendly_name(context.active_object.name)
    return rig_common.part_title(style_of(rig)["asset"], context.active_object, spec.PART_TAG)


selected_ui.add(LABEL, lambda context: find_rig(context) is not None or rig_instance(context) is not None,
                selected_title, draw_selected)


def matching_preset(rig):
    return placement.matching_preset(rig, style_of(rig)["presets"], spec.stored)


def rig_summary(rig, instance):
    """The status line: the style and the look the lights hold now, or what to do first."""
    if rig is None:
        return "Instance (not editable)" if instance else "No rig yet: Deploy one"
    label = style_of(rig)["label"]
    if is_unlocked(rig):
        return f"{label} · unlocked"
    return f"{label} · {matching_preset(rig) or 'custom'}"


def draw_presets(body, rig):
    current = matching_preset(rig)
    sec = section(body, "setups_light_rig_presets", "Look", icon='PRESET', right=current or "custom")
    if sec:
        grid = sec.grid_flow(columns=2, align=True)
        for name in style_of(rig)["presets"]:
            grid.operator(LIGHTRIG_OT_preset.bl_idname, text=name, depress=name == current).preset = name


def per_light_items(suffixes):
    """Items for one light's sliders (named by the suffix alone: the light is the sub-heading above them)."""
    return lambda light: [(f'["{light} {suffix}"]', suffix) for suffix in suffixes]


def light_summary(rig, suffix, fmt):
    """Every light's value of one slider, joined by dots ("5200 · 7000 · 8000 K")."""
    return " · ".join(fmt(rig[f"{light} {suffix}"]) for light in style_of(rig)["lights"])


def shadow_summary(rig):
    lights = style_of(rig)["lights"]
    return f"{sum(bool(rig[f'{light} Shadow']) for light in lights)} of {len(lights)} shadows"


# (section idname suffix, title, icon, per-light slider suffixes, summary of the folded section)
LIGHT_GROUPS = (
    ("position", "Position", 'ORIENTATION_GIMBAL', ("Swing", "Height"), lambda rig: None),
    ("look", "Softness & Shadow", 'LIGHT_AREA', ("Softness", "Shadow"), shadow_summary),
    ("colour", "Colour", 'COLOR', ("Temperature", "Tint"),
     lambda rig: light_summary(rig, "Temperature", lambda k: f"{k:.0f}") + " K"),
)


def draw_locked_lights(body, rig):
    style = style_of(rig)
    bright = section(body, "setups_light_rig_brightness", "Brightness", icon='LIGHT_SUN')
    if bright:
        prop_group(bright, rig, [(f'["{name}"]', name) for name in style["brightness"]])
    for suffix, title, icon, names, summary in LIGHT_GROUPS:
        sec = section(body, f"setups_light_rig_{suffix}", title, icon=icon, default_closed=suffix != "position",
                      right=summary(rig))
        if sec:
            for light in style["lights"]:   # one sub-heading per light, its sliders under it
                sub_heading(sec, light)
                prop_group(sec, rig, per_light_items(names)(light))


def draw_unlocked_lights(body, rig):
    status(body, "Unlocked: edit the lights directly", icon='UNLOCKED')
    for light in style_of(rig)["lights"]:
        sec = section(body, f"setups_light_rig_direct_{light.lower()}", f"{light} Light", icon='LIGHT_AREA')
        if sec:
            data = part(rig, light.lower()).data
            size = ["size", "size_y"] if data.shape in {'RECTANGLE', 'ELLIPSE'} else ["size"]
            prop_group(sec, data, ["energy", *size, "temperature", "color", "use_shadow"])


def draw_rig_tools(body, rig):
    sec = section(body, "setups_light_rig_controls", "Rig", icon='OUTLINER_OB_EMPTY', default_closed=True)
    if not sec:
        return
    row = sec.row(align=True)
    row.operator(LIGHTRIG_OT_fit.bl_idname, icon='SHADING_BBOX')
    row.operator(LIGHTRIG_OT_face_camera.bl_idname, icon='VIEW_CAMERA')
    if is_unlocked(rig):
        sec.operator(LIGHTRIG_OT_lock.bl_idname, icon='DRIVER')
    else:
        sec.operator(LIGHTRIG_OT_unlock.bl_idname, icon='UNLOCKED')
    sub_heading(sec, "Select Part")
    row = sec.row(align=True)
    for name in ("rig", "focus") + tuple(L.lower() for L in style_of(rig)["lights"]):
        row.operator(LIGHTRIG_OT_select_part.bl_idname, text=name.title(),
                     depress=rig_common.is_active_part(bpy.context, spec.PART_TAG, name, spec.ROOT_TAG, 'rig')).part = name.upper()


class VIEW3D_MT_lighting_rig_add(bpy.types.Menu):
    """Add > Light > Lighting Rig: one entry per style"""
    bl_idname = "VIEW3D_MT_lighting_rig_add"
    bl_label = LABEL

    def draw(self, context):
        for style in spec.STYLES:
            self.layout.operator(LIGHTRIG_OT_deploy.bl_idname, text=style["label"]).style = style["id"]


classes = (
    LIGHTRIG_OT_preset,
    LIGHTRIG_OT_fit,
    LIGHTRIG_OT_face_camera,
    LIGHTRIG_OT_unlock,
    LIGHTRIG_OT_lock,
    LIGHTRIG_OT_select_part,
    LIGHTRIG_OT_make_editable,
    LIGHTRIG_OT_deploy,
    VIEW3D_MT_lighting_rig_add,
)

PRESET_ITEMS = {s["id"]: spec.preset_items(s["id"]) for s in spec.STYLES}   # kept: Blender reads enum items lazily


def _start_with_items(wm, _context):
    return PRESET_ITEMS[wm.setups_light_style]


def _style_changed(wm, _context):
    wm.setups_light_preset = spec.default_preset(wm.setups_light_style)


def register():
    wm = bpy.types.WindowManager
    wm.setups_light_style = EnumProperty(
        name="Style", items=spec.style_items(), default=spec.DEFAULT_STYLE, update=_style_changed,
        description="Which lighting setup to deploy")
    wm.setups_light_preset = EnumProperty(
        name="Start With", items=_start_with_items, default=0,
        description="The look the new rig starts with (you can change it any time)")
    wm.setups_light_face_viewer = BoolProperty(
        name="Face the Viewer", default=True,
        description="Turn the rig so its camera side (Swing 0) faces your view: the subject is lit from your side")
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.setups_light_preset
    del bpy.types.WindowManager.setups_light_style
    del bpy.types.WindowManager.setups_light_face_viewer
