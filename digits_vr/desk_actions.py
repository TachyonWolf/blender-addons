# SPDX-License-Identifier: GPL-3.0-or-later
"""What the desk's buttons do (bpy side): the screen model read from Blender, and one function per widget action.
Undo / Redo run from a modal operator's first TIMER event (ed.undo run straight from a timer breaks later timer
contexts: README gotchas)."""
import time

import bpy

from . import haptics_test, help_art, help_draw, display_state, annotate, asset_page, gpencil, hide, scale_math, user_scale, desk_layout as layout, modifier_state, perf_stats, rig_tab, pose_mirror, router, tool_actions, sculpt_stroke, select_bubble, settings, subdiv
from . import camera_preview, perf_state, desk_qol_math, edit_grab, edit_mode, file_tab, panel, screenshot
from .picking import is_linked
from .context_helper import run_in_view3d, view3d_override
from . import desk_state as ds
from .desk_state import DESK
from .size_state import SIZE

NEW_OBJECT_DISTANCE = 0.9      # m in front of the headset for a New Grease Pencil


REBUILD_AFTER = 5.0     # s: the kept model is built again at least this often (a change no key covers)
LIVE_TABS = {'speed': 2.0, 'assets': 1.0, 'file': 1.0}     # tabs showing values that change by themselves (stats every 2 s:
                                                            # each new number is a texture render, ~1-2 ms)
_kept = {"key": None, "model": None, "time": 0.0}


def forget_model():
    """A press: the next model check builds the model again."""
    _kept["key"] = None
    tool_actions.forget()


def build_model(context):
    """The DeskModel, reused during a session while nothing it shows can have changed (the full read cost ~0.1 ms in
    VR, the slow frame of each model check): no setting written, depsgraph update, undo, mode / object / tab / pop-up
    / shading / size / panel change and no note since, rebuilt at least every REBUILD_AFTER s (LIVE_TABS: more often:
    a forced rebuild every second was the slow frame of the three-panel Q1 check). Outside a session
    (tests, the sidebar) it is always built fresh."""
    from .runtime import RUNTIME
    if not RUNTIME.active:
        return _build_model(context)
    ob = context.active_object
    key = (settings.revision, RUNTIME.scene_updates, RUNTIME.generation, context.mode, ob.name_full if ob else None,
           DESK.tab, DESK.popup, DESK.selected_sub, DESK.grab_more, annotate.STATE.on, SIZE.factor,
           context.window_manager.xr_session_settings.shading.type, _panel_open("viewpoints"), _panel_open("tool_options"), _panel_open("pda"), _panel_open("tool_gun"),
           desk_qol_math.NOTICE.current(time.perf_counter()),
           subdiv.key(ob) if ob and DESK.tab == 'selected' and DESK.selected_sub == 'mods' else None,
           help_draw.rows(context) if DESK.popup == 'help' else None,
           tool_actions.key(context) if DESK.tab == 'tools' else None)
    now = time.perf_counter()
    if key != _kept["key"] or now - _kept["time"] > LIVE_TABS.get(DESK.tab, REBUILD_AFTER):
        _kept.update(key=key, model=_build_model(context), time=now)
    return _kept["model"]


def _build_model(context):
    """A DeskModel of what Blender shows right now."""
    ob = context.active_object
    xr_settings = context.window_manager.xr_session_settings
    modifiers, object_name, subdiv_view = (), "", layout.SubdivView()
    if ob is not None:
        object_name = ob.name
        if DESK.tab == 'selected' and DESK.selected_sub == 'mods':
            scene = context.scene
            scene_choices = modifier_state.choices(scene)
            modifiers = tuple((mod.name, mod.type.replace('_', ' ').title(),
                               modifier_state.is_shown(scene, ob, mod, scene_choices)) for mod in ob.modifiers)
            subdiv_view = subdiv.view(ob)
    mode = router.mode_kind(context.mode)
    tool_fields = tool_actions.fields(context) if DESK.tab == 'tools' else {"mode": mode}
    assets = asset_page.build_view(context) if DESK.tab == 'assets' else layout.AssetsView()
    return layout.DeskModel(
        tab=DESK.tab, grab_mode=settings.get("grab_mode"),
        touch_distance_cm=round(settings.get("touch_distance") * 100, 1),
        fine_control=settings.get("fine_control"), name_tag=settings.get("name_tag"), show_hands=settings.get("show_hands"), hand_marker=settings.get("hand_marker"), finger_poke=settings.get("finger_poke"), push_speed=round(settings.get("push_speed"), 2), always_laser=settings.get("always_laser"), paused=settings.get("paused"), help_on=settings.get("help_on"),
        help_rows=help_draw.rows(context) if DESK.popup == 'help' else (),
        hide_heavy=settings.get("hide_heavy_modifiers"),
        perf=perf_stats.view(context) if DESK.tab == 'speed' else layout.PerfView(),
        compositor_off=settings.get("compositor_off_in_vr"), raytracing_off=settings.get("raytracing_off_in_vr"),
        lower_shadows=settings.get("lower_shadows_in_vr"),
        hide_transparent=settings.get("hide_transparent_in_vr"), draw_distance=settings.get("draw_distance"),
        shading=xr_settings.shading.type, show_floor=xr_settings.show_floor, object_name=object_name,
        modifiers=modifiers, subdiv=subdiv_view, assets=assets, move_mode=settings.get("move_mode"), move_heading=settings.get("move_heading"),
        fly_pitch=settings.get("fly_pitch"), teleport_land=settings.get("teleport_land"), turn_style=settings.get("turn_style"),
        walk_speed=round(settings.get("walk_speed"), 2), fly_speed=round(settings.get("fly_speed"), 2),
        snap_angle=round(settings.get("snap_angle")), turn_speed=round(settings.get("turn_speed")),
        plane_height_cm=round(settings.get("plane_height") * 100), geo_slide_speed=round(settings.get("geo_slide_speed"), 2),
        geo_step_height_cm=round(settings.get("geo_step_height") * 100), size_preset=scale_math.active_preset(SIZE.factor) or 0.0, size_gesture=settings.get("size_gesture"), size_invert=settings.get("size_invert"),
        disabled_modes=_disabled_modes(ob),
        display_hidden=tuple(settings.get("display_hidden")), popup=DESK.popup, selected_sub=DESK.selected_sub,
        grab_more=DESK.grab_more, eye_height_cm=round(settings.get("eye_height") * 100),
        laser_length=round(settings.get("laser_length"), 1), belt_on=settings.get("belt_on"),
        belt_height=round(settings.get("belt_height"), 2), belt_size=round(settings.get("belt_size"), 2),
        belt_snap_back=round(settings.get("belt_snap_back"), 1), belt_take_fingertip=settings.get("belt_take_fingertip"),
        rig=rig_tab.view(context) if DESK.tab == 'selected' and DESK.selected_sub == 'rig' else None,
        viewpoints_open=_panel_open("viewpoints"), tool_options_open=_panel_open("tool_options"), pda_open=_panel_open("pda"), tool_gun_open=_panel_open("tool_gun"),
        camera_preview=settings.get("camera_preview"),
        haptics=settings.get("haptics"), haptics_strength=round(settings.get("haptics_strength"), 1),
        haptics_point=settings.get("haptics_point"), haptics_grab=settings.get("haptics_grab"),
        haptics_other=settings.get("haptics_other"), scale_meter=settings.get("scale_meter"),
        note=desk_qol_math.NOTICE.current(time.perf_counter()) or camera_preview.note(context), **tool_fields, **_file_fields())


def _panel_open(name):
    other = panel.REGISTRY.get(name)
    return other.is_open() if other is not None else False


def _file_fields():
    if DESK.tab != 'file':
        return {}
    name, status, message = file_tab.view()
    return {"file_name": name, "file_status": status, "file_message": message}


def _disabled_modes(ob):
    """Modes the active object can't enter: Pose needs an armature, Draw a Grease Pencil object, Sculpt and Edit a mesh
    that can be changed (the other Edit refusals are shown when you press it)."""
    wrong = tuple(mode for mode, allowed in (('POSE', 'ARMATURE'), (router.GP_DRAW, 'GREASEPENCIL'), (router.SCULPT, 'MESH'),
                                              (router.EDIT, 'MESH')) if ob is None or ob.type != allowed)
    linked = ob is not None and ob.type == 'MESH' and (not ob.data.is_editable or is_linked(ob))
    return wrong + ((router.SCULPT, router.EDIT) if linked else ())


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
    sculpt_stroke.end(context)        # a running stroke is kept first: this undo then takes it back as one step
    select_bubble.end(context)
    if edit_grab.cancel_all(context.blend_data):
        return True        # a running Edit grab: Undo / Redo cancels it (vertices back), the last finished action stays
    return run_in_view3d(context, lambda: bpy.ops.digits_vr.history('INVOKE_DEFAULT', redo=redo))


def _set_mode(context, mode):
    ob = context.active_object
    if router.mode_kind(context.mode) == mode or mode in _disabled_modes(ob):
        return False
    sculpt_stroke.end(context)
    select_bubble.end(context)
    if router.EDIT in (mode, router.mode_kind(context.mode)):
        return edit_mode.switch(context, mode)
    # entering / leaving Sculpt is an undo step, like on the desktop: else undoing the first stroke throws you out of it
    with_undo = router.SCULPT in (mode, router.mode_kind(context.mode))
    return run_in_view3d(context, lambda: bpy.ops.object.mode_set('EXEC_DEFAULT', with_undo, mode=mode))


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
    perf_state.apply_window_manager()           # the desktop 3D Views follow the headset's shading
    return True


def _toggle_floor(context):
    display_state.toggle("floor")
    return True


def _pose_tool(context, name):
    """Clear transforms / Mirror pose on the selected bones (Pose mode, through the 3D View override)."""
    if router.mode_kind(context.mode) != router.POSE:
        return False

    if name != "pose_clear":
        return pose_mirror.mirror_selected(context)
    return run_in_view3d(context, lambda: bpy.ops.pose.transforms_clear())


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
    DESK.tab, DESK.popup = tab, ""
    settings.put("desk_tab", tab)
    return True


def _show_help(is_on):
    """Help turned on: the Controls pop-up opens too (Close leaves the tips on); off: both go."""
    DESK.popup, DESK.grab_more = ("help" if is_on else ""), False
    if is_on:
        help_art.load()


def _session_state(context):
    return context.window_manager.xr_session_state


def perform(context, widget, pixel_x):
    """Do what `widget` says (a press, or a slider drag at screen pixel `pixel_x`). Returns True when it did.
    A pick in a dropdown list closes the list."""
    if not widget.action or not widget.enabled:
        return False
    done = _perform(context, widget, pixel_x)
    if (DESK.popup in layout.LIST_POPUPS and widget.action[0] != "popup") or (
            DESK.popup == 'cat' and widget.action[0] == "asset_catalog"):
        DESK.popup = ""
        return True
    return done


def _perform(context, widget, pixel_x):
    kind, *arguments = widget.action
    if kind == "popup":         # open a pop-up / dropdown list; its opener again or "" closes it
        DESK.popup = "" if DESK.popup == arguments[0] else arguments[0]
        return True
    if kind == "selected_sub":
        DESK.selected_sub, DESK.popup = arguments[0], ""
        return True
    if kind == "grab_more":
        DESK.grab_more, DESK.popup = not DESK.grab_more, ""
        return True
    if kind in ("recenter", "safe_settings"):      # same as holding both stick clicks 2 s / 6 s
        from . import recenter        # here: recenter imports the desk
        state = _session_state(context)
        if state is None:
            return False
        if kind == "recenter":
            return recenter.recenter(context, state)
        recenter.failsafe(context, state)
        return True
    if kind == "gp_layer_set":
        return gpencil.set_layer(context, arguments[0])
    if kind == "panel":         # Tool options / Viewpoints: open, call to you, or close (like the stick click)
        other = panel.REGISTRY.get(arguments[0])
        state = context.window_manager.xr_session_state
        if other is None or state is None:
            return False
        other.toggle(context, state)
        return True
    if kind == "undo" or kind == "redo":
        return history(context, kind == "redo")
    if kind == "mode":
        DESK.popup = ""
        return _set_mode(context, arguments[0])
    if kind == "tab":
        return _set_tab(context, arguments[0])
    if kind == "grab_mode":
        settings.put("grab_mode", arguments[0])
        return True
    if kind in ("move_mode", "turn_style", "move_heading", "fly_pitch", "teleport_land", "finger_poke"):
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
    if kind == "haptics_test":
        return haptics_test.run(context, arguments[0])
    if kind == "hand_marker_default":
        settings.put("hand_marker", 0.0)
        return True
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
        if arguments[0] == "help_on":
            _show_help(settings.get("help_on"))
        return True
    if kind == "modifier":
        return _toggle_modifier(context, arguments[0])
    tool_done = tool_actions.perform(context, widget, pixel_x)
    if tool_done is not None:
        return tool_done
    if kind == "subdiv":
        return subdiv.step(context, arguments[0])
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
    if kind == "snapshot":
        return camera_preview.snapshot(context)
    if kind == "screenshot":
        return screenshot.request()
    if kind == "file_save":
        return file_tab.save(context)
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
