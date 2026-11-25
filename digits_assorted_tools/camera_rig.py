# SPDX-License-Identifier: GPL-3.0-or-later
"""Camera Rig (Digit's Tools > Setups): Deploy button, lens / depth-of-field presets and controls for
the Camera Rig asset (Library/CameraRig.blend), plus Focus Pull, Frame Subject and Composition Guides.
Placement and framing maths is in rig_placement, presets / guide tables in camera_rig_spec."""

import bpy
from bpy_extras import view3d_utils
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from mathutils import Matrix, Vector

from . import camera_rig_spec as spec
from . import rig_common, rig_placement as placement
from .rig_common import find_root, pointer, select_only, set_constant_interpolation, set_key_interpolation
from . import composition_overlay, selected_ui
from .ui_cards import action_row, enum_label, hints, prop_group, section, status, sub_heading  # generated copy

FOLLOW_PROP = "Aim Follows Dolly"
FOLLOW_PATH = f'["{FOLLOW_PROP}"]'
TAG = "camrig_dolly"
PARTS = ("camera", "aim", "focus")
FOCUS_POINT_PROPS = {"A": "Focus Pull A", "B": "Focus Pull B"}   # picked world points, stored on the Dolly
FOCUS_FRAMES_PROP = "Focus Pull Frames"                          # [frame A, frame B] of the keys, on the Focus
GEOMETRY_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META', 'VOLUME', 'CURVES', 'POINTCLOUD'}


# ---------------------------------------------------------------------------
# Finding the rig
# ---------------------------------------------------------------------------

def is_dolly(ob):
    return ob is not None and ob.get(TAG) is not None


def part(dolly, name):
    """Rig part from the Dolly's pointer properties ('dolly', 'camera', 'aim' or 'focus')."""
    if name == "dolly":
        return dolly
    return pointer(dolly, "camrig_" + name)


def find_dolly(context):
    """The Dolly of the rig the active object belongs to, or None."""
    return find_root(context, TAG, "camrig_part", lambda dolly: [part(dolly, p) for p in PARTS])


# ---------------------------------------------------------------------------
# Follow switch
# ---------------------------------------------------------------------------

def aim_basis_for_mode(dolly, aim_world, follow):
    """Aim matrix_basis that keeps aim_world in the given mode (Child Of with identity inverse)."""
    if follow:
        return dolly.matrix_world.inverted_safe() @ aim_world
    return aim_world.copy()


def set_follow(context, dolly, follow):
    """Switch the Aim between following the Dolly and staying put, without it jumping."""
    aim = part(dolly, "aim")
    aim_world = aim.matrix_world.copy()
    dolly[FOLLOW_PROP] = follow
    dolly.update_tag()  # ID property writes from Python don't re-run drivers by themselves
    aim.matrix_basis = aim_basis_for_mode(dolly, aim_world, follow)

    if context.scene.tool_settings.use_keyframe_insert_auto:
        frame = context.scene.frame_current
        dolly.keyframe_insert(FOLLOW_PATH, frame=frame)
        set_constant_interpolation(dolly, FOLLOW_PATH, frame)
        aim.keyframe_insert("location", frame=frame)
        rot_path = {"QUATERNION": "rotation_quaternion", "AXIS_ANGLE": "rotation_axis_angle"}
        aim.keyframe_insert(rot_path.get(aim.rotation_mode, "rotation_euler"), frame=frame)
    context.view_layer.update()


class CAMERARIG_OT_toggle_follow(bpy.types.Operator):
    """Switch between the Aim following the Dolly and staying put, keeping it where it is"""
    bl_idname = "camera_rig.toggle_follow"
    bl_label = "Toggle Aim Follow"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "aim") is not None

    def execute(self, context):
        dolly = find_dolly(context)
        set_follow(context, dolly, not bool(dolly.get(FOLLOW_PROP, True)))
        return {'FINISHED'}


class CAMERARIG_OT_select_part(bpy.types.Operator):
    """Select this part of the camera rig"""
    bl_idname = "camera_rig.select_part"
    bl_label = "Select Rig Part"
    bl_options = {'REGISTER', 'UNDO'}

    part: EnumProperty(items=[(p.upper(), p.title(), "") for p in ("dolly",) + PARTS])

    @classmethod
    def poll(cls, context):
        return find_dolly(context) is not None

    def execute(self, context):
        if not select_only(context, part(find_dolly(context), self.part.lower())):
            self.report({'WARNING'}, "Rig part is missing or hidden")
            return {'CANCELLED'}
        return {'FINISHED'}


class CAMERARIG_OT_snap_focus(bpy.types.Operator):
    """Move the Focus back onto the Aim"""
    bl_idname = "camera_rig.snap_focus"
    bl_label = "Snap Focus"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "aim") and part(dolly, "focus")

    def execute(self, context):
        dolly = find_dolly(context)
        set_focus_at(context, dolly, part(dolly, "aim").matrix_world.translation, dof_on=False)
        return {'FINISHED'}


def set_focus_at(context, dolly, point, dof_on=True):
    """Put the rig's Focus (the DoF target) at a world-space point; keys it at the current frame when auto-keying
    is on; turns Depth of Field on when `dof_on` (so the pick shows)."""
    focus = part(dolly, "focus")
    matrix = focus.matrix_world.copy()
    matrix.translation = point
    focus.matrix_world = matrix
    if dof_on:
        part(dolly, "camera").data.dof.use_dof = True
    if context.scene.tool_settings.use_keyframe_insert_auto:
        focus.keyframe_insert("location", frame=context.scene.frame_current)
    context.view_layer.update()


class CAMERARIG_OT_focus_here(placement.PickOperator, bpy.types.Operator):
    """Click a surface to focus there. Wide apertures (f/1.4-2.8) show the effect most"""
    bl_idname = "camera_rig.focus_here"
    bl_label = "Pick Focus"
    bl_options = {'REGISTER', 'UNDO'}
    pick_help = "Click what to focus on  ·  Esc / Right-click: cancel"

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "focus") is not None and part(dolly, "camera") is not None

    def picked(self, context, view):
        point = placement.cast(context.scene, context.evaluated_depsgraph_get(), view.eye, view.forward)
        if point is None:
            self.report({'WARNING'}, "No surface there: click on something in the scene")
            return {'CANCELLED'}
        set_focus_at(context, find_dolly(context), point)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Look through the camera
# ---------------------------------------------------------------------------

def look_through(context, camera):
    """Make `camera` the scene camera and switch the current 3D view to it."""
    context.scene.camera = camera
    if context.space_data and context.space_data.type == 'VIEW_3D':
        context.space_data.region_3d.view_perspective = 'CAMERA'


class CAMERARIG_OT_look_through(bpy.types.Operator):
    """Make the rig's camera the scene camera and look through it in this 3D view, to judge the real framing"""
    bl_idname = "camera_rig.look_through"
    bl_label = "Look Through Camera"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "camera") is not None and context.space_data is not None \
            and context.space_data.type == 'VIEW_3D'

    def execute(self, context):
        look_through(context, part(find_dolly(context), "camera"))
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Composition guides (the camera's own overlays)
# ---------------------------------------------------------------------------

def toggle_guide(camera_data, prop):
    """Flip one composition guide (a camera property named in spec.GUIDES); returns its new state."""
    if prop not in {g[0] for g in spec.GUIDES}:
        raise ValueError(f"not a composition guide: {prop}")
    setattr(camera_data, prop, not getattr(camera_data, prop))
    return getattr(camera_data, prop)


def set_passepartout(camera_data, alpha):
    """Darken outside the frame by `alpha` (0 = off)."""
    camera_data.show_passepartout = alpha > 0
    camera_data.passepartout_alpha = alpha


class CAMERARIG_OT_toggle_guide(bpy.types.Operator):
    """Show or hide a composition guide in the camera view"""
    bl_idname = "camera_rig.toggle_guide"
    bl_label = "Composition Guide"
    bl_options = {'REGISTER', 'UNDO'}

    guide: StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return spec.guide_tip(properties.guide) if properties.guide else cls.__doc__

    @classmethod
    def poll(cls, context):
        return _live_camera_data(context) is not None

    def execute(self, context):
        toggle_guide(_live_camera_data(context), self.guide)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Focus pull: key the Focus between two picked points
# ---------------------------------------------------------------------------

def focus_points(dolly):
    """(world point A, world point B) picked for the focus pull; None for one not picked yet."""
    return tuple(Vector(dolly[p]) if p in dolly.keys() else None for p in FOCUS_POINT_PROPS.values())


def apply_focus_pull(context, dolly, frame_a, frame_b, interpolation):
    """Key the Focus's location so it sits on world point A at frame_a and B at frame_b. The Focus is a
    child of the Aim, so each key is the local location that lands on the world point as the rig stands
    at that frame (the Aim is evaluated there, whether it follows the Dolly or not): the pull is exact if
    the Aim stands still, and keeps its offset from the Aim if the Aim moves."""
    focus = part(dolly, "focus")
    scene, keep = context.scene, context.scene.frame_current
    for point, frame in zip(focus_points(dolly), (frame_a, frame_b)):
        scene.frame_set(frame)
        parent = focus.parent.matrix_world if focus.parent else Matrix()
        focus.location = placement.local_point(parent, focus.matrix_parent_inverse, point)
        focus.keyframe_insert("location", frame=frame)
        set_key_interpolation(focus, "location", frame, interpolation)
    scene.frame_set(keep)
    focus[FOCUS_FRAMES_PROP] = [frame_a, frame_b]
    context.view_layer.update()


def clear_focus_pull(dolly):
    """Remove the keys apply_focus_pull made (only those frames); True if there were any."""
    focus = part(dolly, "focus")
    if FOCUS_FRAMES_PROP not in focus.keys():
        return False
    for frame in focus[FOCUS_FRAMES_PROP]:
        focus.keyframe_delete("location", frame=frame)
    del focus[FOCUS_FRAMES_PROP]
    return True


class CAMERARIG_OT_pick_focus(placement.PickOperator, bpy.types.Operator):
    """Click in the 3D view on what the focus should land on"""
    bl_idname = "camera_rig.pick_focus"
    bl_label = "Pick Focus"
    bl_options = {'REGISTER', 'UNDO'}
    pick_help = "Click what to focus on  ·  Enter: screen centre  ·  Esc / Right-click: cancel"

    which: EnumProperty(items=[("A", "A", ""), ("B", "B", "")], options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        which = properties.which or "A"
        return (f"Click on the subject the focus starts on (A)" if which == "A" else
                f"Click on the subject the focus moves to (B)") + ". " + spec.FOCUS_PULL_TIP

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "focus") is not None

    def picked(self, context, view):
        dolly, wm = find_dolly(context), context.window_manager
        point, _ = placement.view_target(context, view)
        dolly[FOCUS_POINT_PROPS[self.which]] = tuple(point)
        if self.which == "A":
            wm.setups_cam_pull_a = context.scene.frame_current
            if FOCUS_POINT_PROPS["B"] not in dolly.keys():
                wm.setups_cam_pull_b = context.scene.frame_current + spec.FOCUS_PULL_FRAMES
        return {'FINISHED'}


class CAMERARIG_OT_apply_focus_pull(bpy.types.Operator):
    """Key the Focus onto point A at frame A and onto point B at frame B, so focus moves from one subject to
    the other. A focus pull (rack focus) moves the viewer's attention; it works best at wide apertures (f/1.4 to f/2.8)"""
    bl_idname = "camera_rig.apply_focus_pull"
    bl_label = "Apply Focus Pull"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "focus") is not None and None not in focus_points(dolly)

    def execute(self, context):
        wm = context.window_manager
        if wm.setups_cam_pull_a == wm.setups_cam_pull_b:
            self.report({'WARNING'}, "Frame A and frame B are the same")
            return {'CANCELLED'}
        apply_focus_pull(context, find_dolly(context), wm.setups_cam_pull_a, wm.setups_cam_pull_b,
                         spec.FOCUS_EASE_BY_ID[wm.setups_cam_pull_ease][2])
        return {'FINISHED'}


class CAMERARIG_OT_clear_focus_pull(bpy.types.Operator):
    """Remove the focus pull's two keys (the picked points stay, so you can apply it again)"""
    bl_idname = "camera_rig.clear_focus_pull"
    bl_label = "Clear Focus Pull"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and part(dolly, "focus") is not None

    def execute(self, context):
        if not clear_focus_pull(find_dolly(context)):
            self.report({'INFO'}, "No focus pull keys to clear")
            return {'CANCELLED'}
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Frame Subject: move the camera along its line of sight until the subject fills the frame
# ---------------------------------------------------------------------------

def framing_objects(scene, target):
    """The objects whose geometry the subject is: a character's meshes, the object itself, or for an
    empty / group parent the geometry under it."""
    if target.type in GEOMETRY_TYPES or placement.armature_of(target) is not None:
        return placement.subject_objects(target, scene.objects)
    return [o for o in target.children_recursive if o.type in GEOMETRY_TYPES] or [target]


def subject_points(context, targets):
    """The 8 world corners of the box around the evaluated geometry of the targets (modifiers, shape keys
    and pose included), or [] when they have none."""
    objects = [o for t in targets for o in framing_objects(context.scene, t)]
    bounds = placement.world_bounds(objects, context.evaluated_depsgraph_get())
    if bounds is None:
        return []
    low, high = bounds
    return [Vector((x, y, z)) for x in (low.x, high.x) for y in (low.y, high.y) for z in (low.z, high.z)]


def frame_subject(context, dolly, points, margin):
    """Aim and Focus go to the middle of the points, and the camera moves along the line from there to
    where it stands now (its direction kept) until the points fill the frame with the camera's lens,
    sensor fit and the render aspect, leaving `margin` (0-1) empty. Returns the new distance."""
    camera, aim, focus = (part(dolly, p) for p in PARTS)
    centre = placement.box_centre(points)
    back = camera.matrix_world.translation - centre
    if back.length < 1e-6:
        back = camera.matrix_world.to_3x3() @ Vector((0, 0, 1))
    back.normalize()

    aim_world = aim.matrix_world.copy()
    aim_world.translation = centre
    aim.matrix_basis = aim_basis_for_mode(dolly, aim_world, bool(dolly.get(FOLLOW_PROP, True)))
    context.view_layer.update()
    focus_world = focus.matrix_world.copy()
    focus_world.translation = centre
    focus.matrix_world = focus_world

    data = camera.data
    half_tans = placement.frame_half_tans(data.lens, data.sensor_width, data.sensor_height, data.sensor_fit,
                                          placement.render_aspect(context.scene))
    parent = camera.parent.matrix_world if camera.parent else Matrix()
    for _ in range(2):   # the second pass uses the camera's up after it turned toward the new Aim
        context.view_layer.update()
        right, up = placement.camera_axes(back, camera.matrix_world.to_3x3() @ Vector((0, 1, 0)))
        distance = placement.frame_distance(points, centre, back, right, up, half_tans, margin)
        camera.location = placement.local_point(parent, camera.matrix_parent_inverse, centre + back * distance)
    context.view_layer.update()
    if context.scene.tool_settings.use_keyframe_insert_auto:
        frame = context.scene.frame_current
        for ob in (camera, focus):
            ob.keyframe_insert("location", frame=frame)
        aim.keyframe_insert("location", frame=frame)
    return distance


def selected_targets(context, dolly):
    """Selected objects that are not part of the rig: what Frame Subject frames."""
    rig = {dolly, *(part(dolly, p) for p in PARTS)}
    return [o for o in context.selected_objects if o not in rig and o.get("camrig_part") is None]


class CAMERARIG_OT_frame_subject(placement.PickOperator, bpy.types.Operator):
    """Move the camera along its line of sight until the subject fills the frame, with the margin below.
    Select the rig and the subject, or click the subject. For a character it frames all the rig's meshes"""
    bl_idname = "camera_rig.frame_subject"
    bl_label = "Frame Subject"
    bl_options = {'REGISTER', 'UNDO'}
    pick_help = "Click the subject  ·  Enter: screen centre  ·  Esc / Right-click: cancel"

    @classmethod
    def poll(cls, context):
        dolly = find_dolly(context)
        return dolly is not None and all(part(dolly, p) for p in PARTS) and part(dolly, "camera").type == 'CAMERA'

    def _frame(self, context, targets):
        points = subject_points(context, targets)
        if not points:
            self.report({'WARNING'}, "The subject has no geometry to frame")
            return {'CANCELLED'}
        frame_subject(context, find_dolly(context), points, context.window_manager.setups_cam_margin / 100)
        return {'FINISHED'}

    def execute(self, context):
        targets = selected_targets(context, find_dolly(context))
        return self._frame(context, targets) if targets else super().execute(context)

    def invoke(self, context, event):
        if selected_targets(context, find_dolly(context)):
            return self.execute(context)
        return super().invoke(context, event)

    def picked(self, context, view):
        _, ob = placement.cast_hit(context.scene, context.evaluated_depsgraph_get(), view.eye, view.forward)
        if ob is None:
            self.report({'WARNING'}, "Nothing under the click: click on the subject")
            return {'CANCELLED'}
        return self._frame(context, [ob])


# ---------------------------------------------------------------------------
# Presets (lens and depth of field), also applied live to a rig in the scene
# ---------------------------------------------------------------------------

def apply_lens(camera_data, lens_id):
    _, _, lens, sensor, _ = spec.LENS_BY_ID[lens_id]
    camera_data.lens, camera_data.sensor_width = lens, sensor


def apply_dof(camera_data, dof_id):
    _, _, fstop, _ = spec.DOF_BY_ID[dof_id]
    camera_data.dof.use_dof = fstop is not None
    if fstop is not None:
        camera_data.dof.aperture_fstop = fstop


def _live_camera_data(context):
    dolly = find_dolly(context)
    camera = part(dolly, "camera") if dolly else None
    return camera.data if camera is not None and camera.type == 'CAMERA' else None


def _lens_changed(self, context):
    data = _live_camera_data(context)
    if data is not None:
        apply_lens(data, self.setups_cam_lens)


def _dof_changed(self, context):
    data = _live_camera_data(context)
    if data is not None:
        apply_dof(data, self.setups_cam_dof)


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def lens_frame(lens, camera=None):
    """(focal length, sensor width, sensor height, sensor fit) the framing maths uses: the lens preset
    `lens`, or `camera` (an existing rig's camera object) as it is now."""
    if camera is not None:
        data = camera.data
        return data.lens, data.sensor_width, data.sensor_height, data.sensor_fit
    _, _, mm, sensor, _ = spec.LENS_BY_ID[lens]
    return mm, sensor, 24.0, 'AUTO'


def apply_resolution(scene, resolution):
    """Set the render resolution (percentage untouched) from a spec.RESOLUTIONS id or a (width, height);
    Keep Scene / None leave it. Returns True when it changed."""
    if resolution is None:
        return False
    size = resolution if isinstance(resolution, tuple) else spec.RESOLUTION_BY_ID[resolution][2:4]
    if not size[0]:
        return False
    scene.render.resolution_x, scene.render.resolution_y = size
    return True


def framed_eye(scene, view, target, match_view, frame, box_tans, aspect=None):
    """The eye the camera goes to for a Match View mode (`frame` = lens_frame): FIT_LENS keeps the viewport's
    picture (rig_placement.matched_eye), MOVE_BOX backs the camera along the line to the target until the
    drawn box fills the frame at this lens (rig_placement.eye_for_box); the others keep the eye."""
    mm, sensor_w, sensor_h, fit = frame
    aspect = aspect or placement.render_aspect(scene)
    if match_view == "FIT_LENS":
        return placement.matched_eye(view, target, mm, sensor_w, aspect)
    if match_view == "MOVE_BOX" and box_tans is not None:
        return placement.eye_for_box(view.eye, target, box_tans, placement.frame_half_tans(mm, sensor_w, sensor_h, fit, aspect))
    return view.eye


def deploy(context, view, path, follow=False, lens=spec.DEFAULT_LENS, dof=spec.DEFAULT_DOF, set_active=True,
           match_view="OFF", box_tans=None, existing=None, resolution=spec.DEFAULT_RESOLUTION):
    """Append the Camera Rig from `path` as real objects with the camera at the view's eye, looking
    along the view. match_view (spec.MATCH_VIEWS): FIT_LENS moves the camera along that line so the lens
    frames the subject like the viewport does (see rig_placement.matched_eye); FIT_BOX keeps the camera
    at the eye and sets the focal length so the frame holds `box_tans` = (tan across, tan up) of the
    field of view the user drew; MOVE_BOX keeps the lens and moves the camera so that box fills the frame;
    OFF keeps the eye and the chosen lens. The Aim and Focus go where the view points (first ray hit, else
    a close point ahead), so depth of field focuses on it. Returns the Dolly.
    `existing` (a Dolly): Redeploy, move that rig instead of appending one: only its placement changes
    (dolly, camera height, Aim, an unkeyed Focus), the camera keeps its lens (unless FIT_BOX), DoF,
    Aim Follows Dolly and active-camera state; `path`, follow, lens, dof and set_active are ignored.
    `resolution` (spec.RESOLUTIONS id or (width, height)) is set on the scene first, so the framing uses its aspect."""
    apply_resolution(context.scene, resolution)
    target, depsgraph = placement.view_target(context, view)
    old_camera = part(existing, "camera") if existing is not None else None
    frame = lens_frame(lens, old_camera)
    view = view._replace(eye=framed_eye(context.scene, view, target, match_view, frame, box_tans))
    floor_z = placement.floor_below(context.scene, depsgraph, view.eye)
    dolly = existing if existing is not None else rig_common.append_rig(context, path, spec.ASSET_NAME, TAG)[1]
    camera, aim, focus = (part(dolly, p) for p in PARTS)

    dolly.location, dolly.rotation_euler.z, camera.location = placement.camera_placement(view, floor_z)
    context.view_layer.update()
    if existing is None:
        dolly[FOLLOW_PROP] = follow
        dolly.update_tag()
    aim.matrix_basis = aim_basis_for_mode(dolly, Matrix.Translation(target), bool(dolly.get(FOLLOW_PROP, False)))
    if existing is None or focus.animation_data is None or focus.animation_data.action is None:
        focus.location = (0, 0, 0)
    if existing is None:
        apply_lens(camera.data, lens)
    if match_view == "FIT_BOX" and box_tans is not None:
        data = camera.data
        data.lens = placement.lens_for_tans(box_tans, data.sensor_width, data.sensor_height, data.sensor_fit,
                                            placement.render_aspect(context.scene), spec.LENS_RANGE)
    if existing is None:
        apply_dof(camera.data, dof)
        if set_active:
            context.scene.camera = camera
    context.view_layer.update()
    select_only(context, dolly)
    return dolly


class CAMERARIG_OT_deploy(placement.PickDeployOperator, bpy.types.Operator):
    """Add a Camera Rig as real, editable objects: click what to film (Enter: the screen centre). The camera
    sits at your viewport's eye aimed at that point, and focus lands on it"""
    bl_idname = "camera_rig.deploy"
    bl_label = "Deploy Camera Rig"
    bl_options = {'REGISTER', 'UNDO'}
    library_name = spec.LIBRARY_FILE
    root_tag = TAG
    rig_label = "Camera Rig"
    refine_help = spec.BOX_PICK_HELP
    _box = None

    def _match(self, context):
        return context.window_manager.setups_cam_match_view

    def _frame(self, context):
        """lens_frame of what Deploy would use: the chosen preset, or the rig's own camera when redeploying."""
        rigs = self.existing_rigs(context) if self.redeploy else []
        return lens_frame(context.window_manager.setups_cam_lens, part(rigs[0], "camera") if rigs else None)

    def readout(self, context, view):
        """Move Camera to Fit Lens: how far from the target the camera would stand."""
        if self._match(context) != "FIT_LENS":
            return None
        target, _ = placement.view_target(context, view)
        eye = framed_eye(context.scene, view, target, "FIT_LENS", self._frame(context), None)
        return self._distance_text(target, eye)

    @staticmethod
    def _distance_text(target, eye):
        return iface_("Camera {distance:.1f} m from the target").format(distance=(target - eye).length)

    def refine_start(self, context, view, region, rv3d):
        """Pick Lens / Move Camera to Fit Box: after the target click, draw the frame around the target."""
        if self._match(context) not in spec.BOX_MODES or region is None or view.half_tans is None:
            return False
        self._target, _ = placement.view_target(context, view)
        self._eye = view.eye
        centre = view3d_utils.location_3d_to_region_2d(region, rv3d, self._target)
        if centre is None:
            return False
        self._centre = centre
        self._res, self._ratio_name = None, None   # set once Shift has changed the ratio
        self._start = self._start_size(context)
        return True

    def _start_size(self, context):
        """(width, height) the box starts from: the chosen Resolution preset, or the scene's."""
        wm = context.window_manager
        preset = spec.RESOLUTION_BY_ID[wm.setups_cam_resolution]
        render = context.scene.render
        return (preset[2], preset[3]) if preset[2] else (render.resolution_x, render.resolution_y)

    def _box_aspect(self, context):
        """Width / height the box and lens use now: the Shift-drawn ratio, else the Resolution preset's, else the scene's."""
        size = self._res or (self._start if context.window_manager.setups_cam_resolution != spec.DEFAULT_RESOLUTION else None)
        return size[0] / size[1] if size else placement.render_aspect(context.scene)

    def _shift_resolution(self, context, mouse):
        """Shift held: the ratio follows the mouse (both axes), the pixel count stays about the start's."""
        free = placement.free_box_around(self._centre, mouse, spec.BOX_MIN_PIXELS)
        width, height, self._ratio_name = placement.resolution_for_aspect(
            self._start[0] * self._start[1], placement.aspect_from_box(free),
            context.window_manager.setups_cam_snap_ratio, spec.PRESET_SIZES)
        self._res = (width, height)

    def refine_move(self, context, mouse):
        if self._shift:
            self._shift_resolution(context, mouse)
        aspect = self._box_aspect(context)
        self._box = placement.box_around(self._centre, mouse, aspect, spec.BOX_MIN_PIXELS)
        self._box_tans(context)
        if self._match(context) == "MOVE_BOX":
            eye = framed_eye(context.scene, self._view, self._target, "MOVE_BOX", self._frame(context), self._tans, aspect)
            text = self._distance_text(self._target, eye)
        else:
            text = f"{self._box_lens(context, aspect):.0f} mm"
        if self._res:
            text = f"{placement.ratio_text(*self._res, self._ratio_name)} · {text}"
        self._overlay.update(self._region, mouse, text, self._box)

    def _box_tans(self, context):
        """Set self._tans: the field of view (tan across, tan up) of the drawn box as seen from the eye."""
        forward = (self._target - self._eye).normalized()
        right, up = placement.camera_axes(-forward, placement.UP)
        rays = [view3d_utils.region_2d_to_vector_3d(self._region, self._rv3d, corner)
                for corner in placement.box_corners_2d(self._box)]
        self._tans = placement.ray_tans(rays, forward, right, up)

    def _box_lens(self, context, aspect):
        """Focal length whose frame holds the drawn box as seen from the eye."""
        _, sensor_w, sensor_h, fit = self._frame(context)
        return placement.lens_for_tans(self._tans, sensor_w, sensor_h, fit, aspect, spec.LENS_RANGE)

    def place(self, context, view, path, existing=None):
        wm = context.window_manager
        box_tans = self._tans if self._box is not None else None
        resolution = self._res if box_tans is not None and self._res else wm.setups_cam_resolution
        dolly = deploy(context, view, path, wm.setups_cam_follow, wm.setups_cam_lens, wm.setups_cam_dof,
                       wm.setups_cam_set_active, wm.setups_cam_match_view, box_tans, existing, resolution)
        camera = part(dolly, "camera")
        if box_tans is not None and wm.setups_cam_match_view == "FIT_BOX":
            self.report({'INFO'}, f"Lens set to {camera.data.lens:.0f} mm")
        if wm.setups_cam_look_through:
            look_through(context, camera if existing is not None else context.scene.camera)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

def draw_card(layout, context):
    """The Camera Rig tool: Deploy only; the rig's own controls are in the Selected card."""
    body = layout   # the tool dropdown is the title
    placement.draw_scene_status(body, context.scene, TAG, "camera rig", 'OUTLINER_OB_CAMERA',
                                selected=find_dolly(context) is not None)
    draw_deploy(body, context.window_manager, context)


def draw_selected(box, context):
    """The Selected card's part: the live controls of the rig the selected object belongs to."""
    dolly = find_dolly(context)
    wm = context.window_manager
    status(box, rig_summary(dolly), icon='OUTLINER_OB_CAMERA')
    draw_lens_focus(box, dolly, wm)
    draw_framing(box, dolly, wm)
    draw_focus_pull(box, dolly, wm)
    draw_guides(box, dolly, wm)
    draw_parts(box, dolly, context)


def selected_title(context):
    return rig_common.part_title("Camera Rig", context.active_object, "camrig_part", root_name="Dolly")


selected_ui.add("Camera Rig", lambda context: find_dolly(context) is not None, selected_title, draw_selected)


def rig_summary(dolly):
    """The status line: the rig's lens and f-stop, or what to do first."""
    camera = part(dolly, "camera") if dolly is not None else None
    if dolly is None:
        return "No rig yet: Deploy one"
    if camera is None or camera.type != 'CAMERA':
        return "Camera Rig"
    return f"Camera Rig · {lens_summary(camera)}"


def draw_deploy(body, wm, context):
    def options(sec):
        col = prop_group(sec, wm, [("setups_cam_match_view", "Match View")])
        lens_col = col.column()
        lens_col.active = wm.setups_cam_match_view != "FIT_BOX"   # greyed: that mode picks the lens by a drawn box
        lens_col.prop(wm, "setups_cam_lens", text="Lens")
        col.prop(wm, "setups_cam_dof", text="Depth of Field")
        prop_group(sec, wm, [None, ("setups_cam_resolution", "Resolution"), ("setups_cam_snap_ratio", "Snap Ratio"),
                             ("setups_cam_follow", "Aim Follows Dolly"),
                             ("setups_cam_set_active", "Set Active Camera"),
                             ("setups_cam_look_through", "Look Through It")])
    placement.draw_deploy(body, "setups_camera_rig_options", CAMERARIG_OT_deploy.bl_idname,
                          len(placement.rig_roots(context.scene.objects, TAG)), options,
                          summary=enum_label(wm, "setups_cam_match_view"))


def lens_summary(camera):
    """"50 mm · f/2.8" (or "50 mm · no blur"): the camera's lens and aperture."""
    dof = camera.data.dof
    return f"{camera.data.lens:g} mm · " + (f"f/{dof.aperture_fstop:g}" if dof.use_dof else "no blur")


def draw_lens_focus(body, dolly, wm):
    camera = part(dolly, "camera")
    if camera is None or camera.type != 'CAMERA':
        return
    sec = section(body, "setups_camera_rig_lens", "Lens & Focus", icon='CAMERA_DATA', right=lens_summary(camera))
    if sec:
        prop_group(sec, wm, [("setups_cam_lens", "Lens"), ("setups_cam_dof", "Blur")])
        sec.separator(type='LINE')
        prop_group(sec, camera.data, [("lens", "Focal Length")])
        prop_group(sec, camera.data.dof, [("aperture_fstop", "F-Stop"), ("use_dof", "Depth of Field")])
        action_row(sec).operator(CAMERARIG_OT_focus_here.bl_idname, icon='EYEDROPPER')


def draw_framing(body, dolly, wm):
    sec = section(body, "setups_camera_rig_framing", "Framing", icon='FULLSCREEN_ENTER',
                  right=f"{wm.setups_cam_margin:g} % margin")
    if not sec:
        return
    follow = bool(dolly.get(FOLLOW_PROP, True))
    sec.operator(CAMERARIG_OT_toggle_follow.bl_idname, text=iface_("Aim Follows Dolly"), emboss=False,
                 icon='CHECKBOX_HLT' if follow else 'CHECKBOX_DEHLT')
    prop_group(sec, wm, [("setups_cam_margin", "Margin")])
    row = sec.row(align=True)
    row.operator(CAMERARIG_OT_frame_subject.bl_idname, icon='FULLSCREEN_ENTER')
    row.operator(CAMERARIG_OT_snap_focus.bl_idname, icon='PIVOT_CURSOR')


def draw_parts(body, dolly, context):
    """Select Part: one row of buttons, the active part pressed."""
    sub_heading(body, "Select Part")
    row = body.row(align=True)
    for name in ("dolly",) + PARTS:
        row.operator(CAMERARIG_OT_select_part.bl_idname, text=name.title(),
                     depress=rig_common.is_active_part(context, "camrig_part", name, TAG, "dolly")).part = name.upper()


def draw_focus_pull(body, dolly, wm):
    point_a, point_b = focus_points(dolly)
    pull = section(body, "setups_camera_rig_focus_pull", "Focus Pull", icon='KEYFRAME', default_closed=True,
                   right="A to B" if point_a is not None and point_b is not None else "off")
    if not pull:
        return
    for which, point, frame in (("A", point_a, "setups_cam_pull_a"), ("B", point_b, "setups_cam_pull_b")):
        row = pull.row(align=True)
        op = row.operator(CAMERARIG_OT_pick_focus.bl_idname, text=iface_(f"Pick {which}"),
                          icon='CHECKMARK' if point is not None else 'EYEDROPPER')
        op.which = which
        row.prop(wm, frame, text=iface_("Frame"))
    prop_group(pull, wm, [("setups_cam_pull_ease", "Ease")])
    row = action_row(pull)
    row.operator(CAMERARIG_OT_apply_focus_pull.bl_idname, icon='KEYFRAME')
    row.operator(CAMERARIG_OT_clear_focus_pull.bl_idname, icon='X')


def draw_guides(body, dolly, wm):
    camera = part(dolly, "camera")
    if camera is None or camera.type != 'CAMERA':
        return
    on = [label for prop, label, _ in spec.GUIDES if getattr(camera.data, prop)]
    guides = section(body, "setups_camera_rig_guides", "Composition", icon='MOD_LATTICE', default_closed=True,
                     right=on[0] if len(on) == 1 else f"{len(on)} guides" if on else "off")
    if not guides:
        return
    guides.operator(CAMERARIG_OT_look_through.bl_idname, icon='VIEW_CAMERA')
    grid = guides.grid_flow(columns=2, align=True)
    for prop, label, _ in spec.GUIDES:
        op = grid.operator(CAMERARIG_OT_toggle_guide.bl_idname, text=iface_(label), depress=getattr(camera.data, prop))
        op.guide = prop
    prop_group(guides, wm, []).prop(wm, "setups_cam_passepartout", text="Darken Outside", slider=True)
    scene = bpy.context.scene
    composition_overlay.sync()   # a loaded file keeps the Show Guides flag but not the draw handler
    prop_group(guides, scene, [("comp_guides_show", "Outlined Lines")])
    if getattr(camera.data, spec.SPIRAL_PROP):
        composition_overlay.draw_spiral_settings(guides, scene)
    composition_overlay.draw_line_settings(guides, scene)
    hints(guides, ["Lines also show outside camera view with the Composition Guides tool"])


classes = (
    CAMERARIG_OT_look_through,
    CAMERARIG_OT_toggle_guide,
    CAMERARIG_OT_pick_focus,
    CAMERARIG_OT_focus_here,
    CAMERARIG_OT_apply_focus_pull,
    CAMERARIG_OT_clear_focus_pull,
    CAMERARIG_OT_frame_subject,
    CAMERARIG_OT_toggle_follow,
    CAMERARIG_OT_select_part,
    CAMERARIG_OT_snap_focus,
    CAMERARIG_OT_deploy,
)


def _passepartout_get(self):
    data = _live_camera_data(bpy.context)
    return data.passepartout_alpha if data is not None and data.show_passepartout else 0.0


def _passepartout_set(self, value):
    data = _live_camera_data(bpy.context)
    if data is not None:
        set_passepartout(data, value)


def register():
    wm = bpy.types.WindowManager
    wm.setups_cam_lens = EnumProperty(
        name="Lens", items=spec.enum_items(spec.LENSES), default=spec.DEFAULT_LENS, update=_lens_changed,
        description="Focal length (and sensor) of the camera: sets the rig's camera now, and the next Deploy's")
    wm.setups_cam_dof = EnumProperty(
        name="Depth of Field", items=spec.enum_items(spec.DOFS), default=spec.DEFAULT_DOF, update=_dof_changed,
        description="Aperture (f-stop) for background blur: sets the rig's camera now, and the next Deploy's")
    wm.setups_cam_resolution = EnumProperty(
        name="Resolution", items=spec.enum_items(spec.RESOLUTIONS), default=spec.DEFAULT_RESOLUTION,
        description="Render size Deploy sets on the scene (the percentage stays). The frame you draw with a Fit Box "
                    "mode and the lens follow its aspect ratio. Keep Scene leaves it alone")
    wm.setups_cam_snap_ratio = BoolProperty(name="Snap Ratio", default=True, description=spec.SNAP_RATIO_TIP)
    wm.setups_cam_follow = BoolProperty(
        name="Aim Follows Dolly", default=False,
        description="On: the camera's target moves with the dolly, like a camera on a track (dolly tracking). "
                    "Off: the target stays put and the camera keeps looking at it while the dolly moves")
    wm.setups_cam_match_view = EnumProperty(
        name="Match View", items=spec.enum_items(spec.MATCH_VIEWS), default=spec.DEFAULT_MATCH_VIEW,
        description="How Deploy keeps the framing you see in the viewport")
    wm.setups_cam_set_active = BoolProperty(
        name="Set as Active Camera", default=True, description="Make the new camera the scene's camera")
    wm.setups_cam_look_through = BoolProperty(
        name="Look Through It", default=False, description="Switch this 3D view to the new camera")
    wm.setups_cam_pull_a = IntProperty(
        name="Frame A", default=1, description="Frame where the focus sits on point A (set to the current frame "
        "when you pick A). Pulls feel best over 1 to 3 seconds: 24 to 72 frames at 24 fps")
    wm.setups_cam_pull_b = IntProperty(
        name="Frame B", default=1 + spec.FOCUS_PULL_FRAMES, description="Frame where the focus has arrived on "
        "point B. The further from frame A, the slower and gentler the pull")
    wm.setups_cam_pull_ease = EnumProperty(
        name="Ease", items=spec.enum_items(spec.FOCUS_EASES), default="SMOOTH",
        description="How the focus accelerates between A and B")
    wm.setups_cam_margin = FloatProperty(
        name="Margin", default=spec.DEFAULT_MARGIN, min=0.0, max=90.0, subtype='PERCENTAGE',
        description="Empty border Frame Subject leaves, as a percent of the frame. 10 keeps the subject at 90% "
                    "of the frame (a comfortable fit); 0 touches the edges; more adds breathing room, "
                    "good for a subject that will move")
    wm.setups_cam_passepartout = FloatProperty(
        name="Darken Outside", min=0.0, max=1.0, get=_passepartout_get, set=_passepartout_set,
        description=spec.PASSEPARTOUT_TIP)
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    for name in ("lens", "dof", "follow", "match_view", "set_active", "look_through", "resolution", "snap_ratio", "pull_a", "pull_b",
                 "pull_ease", "margin", "passepartout"):
        delattr(bpy.types.WindowManager, "setups_cam_" + name)
