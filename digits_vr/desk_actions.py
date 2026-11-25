# SPDX-License-Identifier: GPL-3.0-or-later
"""What the desk's buttons do (bpy side): the screen model read from Blender, and one function per widget action.
Undo / Redo run from a modal operator's first TIMER event (ed.undo run straight from a timer breaks later timer
contexts: README gotchas)."""
import bpy

from . import display_state, annotate, asset_page, gpencil, hide, scale_math, user_scale, desk_layout as layout, modifier_state, perf_stats, rig_tab, router, settings
from .context_helper import run_in_view3d, view3d_override
from . import desk_state as ds
from .desk_state import DESK
from .size_state import SIZE

NEW_OBJECT_DISTANCE = 0.9      # m in front of the headset for a New Grease Pencil


def build_model(context):
    """A DeskModel of what Blender shows right now."""
    ob = context.active_object
    xr_settings = context.window_manager.xr_session_settings
    modifiers, object_name = (), ""
    if ob is not None:
        object_name = ob.name
        if DESK.tab == 'modifiers':
            scene = context.scene
            scene_choices = modifier_state.choices(scene)
            modifiers = tuple((mod.name, mod.type.replace('_', ' ').title(),
                               modifier_state.is_shown(scene, ob, mod, scene_choices)) for mod in ob.modifiers)
    mode = router.mode_kind(context.mode)
    hidden = hide.view(context) if DESK.tab == 'tools' and mode == router.OBJECT else ((), 0, 1, 0, False)
    gp = gpencil.view(context) if DESK.tab == 'tools' and mode == router.GP_DRAW else ((), 0, "", 0, 0, 0)
    assets = asset_page.build_view(context) if DESK.tab == 'assets' else layout.AssetsView()
    return layout.DeskModel(
        mode=mode, tab=DESK.tab, grab_mode=settings.get("grab_mode"),
        touch_distance_cm=round(settings.get("touch_distance") * 100, 1),
        rotation_mode=settings.get("rotation_mode"), swap_linked=settings.get("swap_linked"),
        swap_distance_cm=round(settings.get("swap_distance") * 100, 1), fine_control=settings.get("fine_control"), name_tag=settings.get("name_tag"), push_speed=round(settings.get("push_speed"), 2), always_laser=settings.get("always_laser"),
        hide_heavy=settings.get("hide_heavy_modifiers"),
        perf=perf_stats.view(context) if DESK.tab == 'performance' else layout.PerfView(),
        compositor_off=settings.get("compositor_off_in_vr"), raytracing_off=settings.get("raytracing_off_in_vr"),
        lower_shadows=settings.get("lower_shadows_in_vr"),
        hide_transparent=settings.get("hide_transparent_in_vr"), draw_distance=settings.get("draw_distance"),
        shading=xr_settings.shading.type, show_floor=xr_settings.show_floor, object_name=object_name,
        modifiers=modifiers, assets=assets, move_mode=settings.get("move_mode"), move_heading=settings.get("move_heading"),
        fly_pitch=settings.get("fly_pitch"), teleport_land=settings.get("teleport_land"), turn_style=settings.get("turn_style"),
        walk_speed=round(settings.get("walk_speed"), 2), fly_speed=round(settings.get("fly_speed"), 2),
        snap_angle=round(settings.get("snap_angle")), turn_speed=round(settings.get("turn_speed")),
        plane_height_cm=round(settings.get("plane_height") * 100), geo_slide_speed=round(settings.get("geo_slide_speed"), 2),
        geo_step_height_cm=round(settings.get("geo_step_height") * 100), size_preset=scale_math.active_preset(SIZE.factor) or 0.0, size_gesture=settings.get("size_gesture"),
        annotate_on=annotate.STATE.on,
        annotate_color=settings.get("annotate_color"), annotate_thickness=int(round(settings.get("annotate_thickness"))),
        annotate_strokes=annotate.stroke_count(context.scene) if DESK.tab == 'tools' else 0,
        hidden_shown=hidden[0], hidden_page=hidden[1], hidden_pages=hidden[2], hidden_total=hidden[3],
        can_hide=hidden[4], gp_materials=gp[0], gp_material=gp[1], gp_layer=gp[2], gp_layer_index=gp[3],
        gp_layer_count=gp[4], gp_strokes=gp[5], gp_radius_cm=round(settings.get("gp_radius") * 100, 1),
        disabled_modes=_disabled_modes(ob),
        display_hidden=tuple(settings.get("display_hidden")), display_more=DESK.display_more,
        rig=rig_tab.build_view(context) if DESK.tab == 'selected' else None)


def _disabled_modes(ob):
    """Modes the active object can't enter: Pose needs an armature, Draw a Grease Pencil object."""
    return tuple(mode for mode, allowed in (('POSE', 'ARMATURE'), (router.GP_DRAW, 'GREASEPENCIL'))
                 if ob is None or ob.type != allowed)


class DIGITSVR_OT_history(bpy.types.Operator):
    """Undo or redo one step, like Ctrl+Z on the desktop (runs on its first timer event, in the window's own event
    loop)."""
    bl_idname = "digits_vr.history"
    bl_label = "VR Undo / Redo"
    bl_options = {'INTERNAL'}
    redo: bpy.props.BoolProperty()

    def invoke(self, context, _event):
        self.timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        context.window_manager.event_timer_remove(self.timer)
        step = bpy.ops.ed.redo if self.redo else bpy.ops.ed.undo
        if not step.poll():      # nothing to redo / undo (poll fails): do nothing instead of raising an error
            return {'CANCELLED'}
        try:
            step()
        except RuntimeError as error:
            print(f"digits_vr: {'redo' if self.redo else 'undo'} skipped: {error}")
            return {'CANCELLED'}
        return {'FINISHED'}


def history(context, redo):
    return run_in_view3d(context, lambda: bpy.ops.digits_vr.history('INVOKE_DEFAULT', redo=redo))


def _set_mode(context, mode):
    ob = context.active_object
    if router.mode_kind(context.mode) == mode or mode in _disabled_modes(ob):
        return False
    return run_in_view3d(context, lambda: bpy.ops.object.mode_set(mode=mode))


def _toggle_modifier(context, index):
    ob = context.active_object
    if ob is None or index >= len(ob.modifiers):
        return False
    mod = ob.modifiers[index]
    scene = context.scene
    modifier_state.set_shown(scene, ob, mod, not modifier_state.is_shown(scene, ob, mod))
    return True


def _set_shading(context, shading):
    context.window_manager.xr_session_settings.shading.type = shading
    return True


def _toggle_floor(context):
    display_state.toggle("floor")
    return True


def _pose_tool(context, name):
    """Clear transforms / Mirror pose on the selected bones (Pose mode, through the 3D View override)."""
    if router.mode_kind(context.mode) != router.POSE:
        return False

    def run():
        if name == "pose_clear":
            bpy.ops.pose.transforms_clear()
        else:                       # copy, then paste onto the opposite side's bones
            bpy.ops.pose.copy()
            bpy.ops.pose.paste(flipped=True)
    return run_in_view3d(context, run)


def _new_grease_pencil(context):
    """An empty Grease Pencil object about arm's length in front of the headset (behind the desk), at the origin
    when no session runs."""
    from mathutils import Quaternion, Vector
    from .hands import session_state
    state = session_state(context)
    location = Vector((0.0, 0.0, 0.0))
    if state is not None:
        forward = Quaternion(state.viewer_pose_rotation) @ Vector((0.0, 0.0, -1.0))
        location = ds.place_in_front(state.viewer_pose_location, forward, distance=NEW_OBJECT_DISTANCE, drop=0.1)[0]
    gpencil.new_object(context, location)
    return True


def _set_tab(_context, tab):
    if DESK.tab == 'assets' and tab != 'assets':
        asset_page.close()          # textures released when the page closes
    DESK.tab = tab
    settings.put("desk_tab", tab)
    return True


def perform(context, widget, pixel_x):
    """Do what `widget` says (a press, or a slider drag at screen pixel `pixel_x`). Returns True when it did."""
    if not widget.action or not widget.enabled:
        return False
    kind, *arguments = widget.action
    if kind == "undo" or kind == "redo":
        return history(context, kind == "redo")
    if kind == "mode":
        return _set_mode(context, arguments[0])
    if kind == "tab":
        return _set_tab(context, arguments[0])
    if kind == "grab_mode":
        settings.put("grab_mode", arguments[0])
        return True
    if kind in ("rotation_mode", "move_mode", "turn_style", "move_heading", "fly_pitch", "teleport_land"):
        settings.put(kind, arguments[0])
        return True
    if kind == "annotate_toggle":
        return annotate.toggle()
    if kind == "annotate_color":
        settings.put("annotate_color", arguments[0])
        return True
    if kind == "annotate_erase":
        return annotate.erase_last(context)
    if kind == "annotate_clear":
        return annotate.clear_all(context)
    if kind == "gp_new":
        return _new_grease_pencil(context)
    if kind == "gp_material":
        return gpencil.set_material(context, arguments[0])
    if kind == "gp_layer":
        return gpencil.step_layer(context, arguments[0])
    if kind == "gp_erase":
        return gpencil.erase_last(context)
    if kind == "gp_clear":
        return gpencil.clear_layer(context)
    if kind == "hide_selected":
        return hide.hide_selected(context)
    if kind == "unhide_all":
        return hide.unhide_all(context)
    if kind == "unhide_one":
        return hide.unhide_one(context, arguments[0])
    if kind == "hide_page":
        return hide.turn_page(arguments[0])
    if kind in ("pose_clear", "pose_mirror"):
        return _pose_tool(context, kind)
    if kind == "draw_distance_reset":
        settings.put("draw_distance", 0.0)
        return True
    if kind == "size_preset":
        return user_scale.preset(context, context.window_manager.xr_session_state, arguments[0])
    if kind == "plane_reset":
        settings.put("plane_height", 0.0)
        return True
    if kind == "slider":
        value = layout.slider_value(widget, pixel_x)
        if abs(value - widget.value) < 1e-6:
            return False
        settings.put(arguments[0], value * (arguments[1] if len(arguments) > 1 else 0.01))
        return True
    if kind == "toggle":
        settings.put(arguments[0], not settings.get(arguments[0]))
        return True
    if kind == "modifier":
        return _toggle_modifier(context, arguments[0])
    if kind == "perf_recount":
        perf_stats.recount()
        return True
    if kind == "shading":
        return _set_shading(context, arguments[0])
    if kind == "floor":
        return _toggle_floor(context)
    if kind == "display":
        display_state.toggle(arguments[0])
        return True
    if kind == "display_all":
        display_state.show_all()
        return True
    if kind == "display_more":
        DESK.display_more = not DESK.display_more
        return True
    if kind.startswith("asset"):
        return asset_page.perform(context, widget.action)
    if kind.startswith("rig_"):
        return rig_tab.perform(context, widget, pixel_x)
    return False


classes = (DIGITSVR_OT_history,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
