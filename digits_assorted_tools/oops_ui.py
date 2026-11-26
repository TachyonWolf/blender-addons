# SPDX-License-Identifier: GPL-3.0-or-later
"""Oops Debugger (Digit's Tools > Check): lists things on the active object, its rig and that rig's meshes that you
MAY have left on or changed by mistake, each with a Clear button. The checks live in scene_checks (generated copy
of Addons/shared_addon/scene_checks.py); this file is the buttons and the card.
Nothing runs in the background: the scan runs only while this card is open, is cached, and has a Rescan button.
At the top, "Looking for" (Object / Scene / Render, the checks' `kind`; All = the Object checks on every object of the
scene, one row per object, scanned once when picked) picks which checks are shown and scanned; the
Scans card turns the heavy ones (the registry's SCANS) on or off. Both are saved in the add-on preferences."""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from . import instance_array, position_snapshot, scene_checks as sc
from .prefs import (clear_all_risk, ignore_prop, ignores_on, is_modifier_picked, oops_settings, scan_prop, scans_on, set_modifier_picked,
                    unpicked_modifiers)
from .ui_cards import action_row, draw_grey, group, hints, section, shorten, smart_prop, status, toggles, wrapped  # generated copy

RISK_ICONS = {0: 'CHECKMARK', 1: 'INFO', 2: 'QUESTION', 3: 'ERROR'}   # beside each Clear button; level 3 is drawn in the alert colour

WARNING = "Clear removes information: only use it if it was a mistake."
NOTHING = "Nothing looks off"
READ_FIRST = "Read before you clear: some of these are on purpose. Hover a row first."
REVIEW_NOTE = "Review only: these are often intentional. Show selects them in Edit Mode; nothing is changed."
SCANS_NOTE = "Heavy scans. On: runs now and on every selection change. Off: never runs, its checks are hidden."
REVIEW_OFF = "Checks: off (turn on in Scans)"


def scans_of_kind(kind):
    """The Scans (registry order) that hold a check of this kind."""
    used = {c.scan for c in sc.checks_of(sc.AREAS, kind)}
    return [s for s in sc.SCANS if s.id in used]


def scope(context):
    """The checks' scope, leaving out objects in excluded collections unless Scan Disabled Collections is on."""
    settings = oops_settings(context)
    return sc.scope_of(context, include_disabled=settings.scan_disabled, ignored=ignores_on(settings))


def scan(context):
    """(findings, character name) of the current selection, of the chosen kind and Scans. Cached per check until the
    selection changes or Rescan: turning a Scan on runs only its checks."""
    settings = oops_settings(context)
    kind, on = settings.kind, scans_on(settings)
    results = sc.CACHE.get(sc.context_key(context) + (settings.scan_disabled, tuple(sorted(ignores_on(settings)))), dict)   # {check id: finding or None}
    wanted = sc.checks_of(sc.AREAS, kind, on)
    if any(c.id not in results for c in wanted):
        found = dict((c.id, f) for c, f in sc.run_all(scope(context), sc.AREAS, kind, on, skip=results))
        results.update({c.id: found.get(c.id) for c in wanted if c.id not in results})
    active = sc.active_of(context)
    return [(c, results[c.id]) for c in wanted if results[c.id] is not None], (active.name if active else "")


def all_scan(context):
    """The All kind: (sc.scan_scene rows, sc.scan_naming names, sc.scan_linked_modifiers groups, the object names
    Minimize Unapplied Scales could change, instance_array.arrays_of of every scanned mesh, the object names Match All Data Names would rename), run once and cached until Rescan or another kind's scan (not per selection). One cache entry holds all: the cache
    keeps a single scan."""
    settings = oops_settings(context)
    on, disabled, ignored = scans_on(settings), settings.scan_disabled, ignores_on(settings)

    def run():
        objects = sc.scanned_objects(context, disabled)
        return (sc.scan_scene(context, on, disabled, ignored), sc.scan_naming(context, disabled),
                sc.scan_linked_modifiers(context, disabled), sc.minimizable_scale_names(objects),
                instance_array.arrays_of(sc.scanned_mesh_objects(context, disabled)), sc.data_rename_names(objects))
    return sc.CACHE.get(("all", tuple(sorted(on)), disabled, tuple(sorted(ignored))), run)


def scan_all(context):
    return all_scan(context)[0]


def scan_naming(context):
    return all_scan(context)[1]


def scan_linked_modifiers(context):
    return all_scan(context)[2]


def minimizable_scales(context):
    return all_scan(context)[3]


def linked_arrays(context):
    """(convertible [(object name, Array name)], Counter of skip reasons) of every scanned mesh object."""
    return all_scan(context)[4]


def renamable_data(context):
    return all_scan(context)[5]


def place_name(context, kind):
    """What Back returns to, for its button: the Object view names the active object, the other views name the view
    (All, Scene, Render), since Back returns to that view's list."""
    if kind == sc.OBJECT:
        return context.active_object.name if context.active_object else ""
    return next((name for identifier, name, _tip in sc.KINDS if identifier == kind), kind) + " view"


def remembering(context, action):
    """Run `action()` (a Select that moves the selection, mode or kind) and, when it worked, keep where you were before
    it (the first time only) so Back can return there. Returns what `action` returned."""
    kind = oops_settings(context).kind
    before = position_snapshot.capture(context, {"kind": kind, "place": place_name(context, kind)})
    done = action()
    if done:
        position_snapshot.keep_first(context, before)
    return done


class OOPS_OT_rescan(bpy.types.Operator):
    """Look again for things that may be a mistake"""
    bl_idname = "oops.rescan"
    bl_label = "Rescan"

    def execute(self, context):
        sc.CACHE.clear()
        return {'FINISHED'}


class _CheckOperator:
    bl_options = {'REGISTER', 'UNDO'}
    check_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    action: IntProperty(options={'HIDDEN', 'SKIP_SAVE'})   # which of the check's buttons (Check.actions); the last is the main one

    @classmethod
    def description(cls, context, properties):
        check = sc.check_by_id(properties.check_id)
        action = check.actions[properties.action]
        return f"{action.help} {sc.action_risk_text(action)} {sc.CLEAR_NOTE}"


SHARED_CHOICES = (("CANCEL", "Cancel", "Change nothing"),
                  (sc.SHARED_UNLINK, "Unlink", "Give each object its own copy of the mesh, then apply"),
                  (sc.SHARED_SAME, "Apply to Same Size", "The objects with this size get one new shared copy, applied; the others keep the old mesh"),
                  (sc.SHARED_MINIMIZE, "Minimize", "A scale: bake only the most common scale of the users into the shared mesh once. Every object keeps its look, the others keep a smaller scale"),
                  (sc.SHARED_ALL, "Apply to All", "Apply to the shared mesh once. A scale: every object using it takes this object's size and ends at scale 1. A rotation: the other objects' transforms are adjusted so they look the same"))


def clear_confirm_message(check, action, count):
    """The confirm popup text of one Clear: what is removed, and for a Risky one what is lost (the action's own help)."""
    text = f"{action.button} {count} items from {check.label}? This removes them."
    return f"{text} {action.help} Risky: {sc.RISKS[action.risk][1]}" if sc.needs_warning(action.risk) else text


class OOPS_OT_clear(_CheckOperator, bpy.types.Operator):
    bl_idname = "oops.clear"
    bl_label = "Clear"

    shared_mode: EnumProperty(items=SHARED_CHOICES, default="CANCEL", options={'HIDDEN', 'SKIP_SAVE'})   # for objects sharing their mesh

    def shared_data(self, context):
        """What the fix meets in shared meshes (a transform check's `shared`), or None when nothing is shared."""
        shared = sc.check_by_id(self.check_id).shared
        data = shared(scope(context)) if shared and self.action == 0 else None
        return data if data and data.objects else None

    def invoke(self, context, event):
        action = sc.check_by_id(self.check_id).actions[self.action]
        if self.shared_data(context):
            return context.window_manager.invoke_props_dialog(self, title=f"{action.button}: shared mesh", confirm_text="OK")
        warn = sc.needs_warning(action.risk)
        if not (action.confirm or warn):
            return self.execute(context)
        check = sc.check_by_id(self.check_id)
        finding = check.find(scope(context))
        return context.window_manager.invoke_confirm(
            self, event, title=f"{action.button}?", confirm_text=action.button,
            message=clear_confirm_message(check, action, finding.count if finding else 0), icon='WARNING' if warn else 'NONE')

    def draw(self, context):
        data = self.shared_data(context)
        col = self.layout.column(align=True)
        for ob, others in data.objects[:6]:
            col.label(text=f"{ob.name} shares its {sc.data_word(ob)} with {others} others")
        if len(data.objects) > 6:
            col.label(text=f"... and {len(data.objects) - 6} more")
        offered = {"CANCEL": True, sc.SHARED_UNLINK: True, sc.SHARED_SAME: data.same_size is not None, sc.SHARED_ALL: data.can_apply_all,
                   sc.SHARED_MINIMIZE: data.can_minimize}
        for key, label, _tip in SHARED_CHOICES:
            if offered[key]:
                col.prop_enum(self, "shared_mode", key, text=f"{label} ({data.same_size})" if key == sc.SHARED_SAME else label)
        if not data.can_apply_all:
            col.label(text="Apply to All needs no scale axis at 0 on this object (a rotation: uniform scales on every user)")

    def execute(self, context):
        check = sc.check_by_id(self.check_id)
        the_scope = scope(context)
        the_scope.shared_mode = self.shared_mode
        the_scope.unpicked = unpicked_modifiers(context)
        count = check.actions[self.action].clear(the_scope)
        sc.CACHE.clear()
        for note in the_scope.notes:
            self.report({'WARNING'}, note)
        self.report({'INFO'}, f"{check.label}: fixed {count}")
        return {'FINISHED'}


class OOPS_OT_risk(bpy.types.Operator):
    """How risky this Clear is (hover for the level)"""
    bl_idname = "oops.risk"
    bl_label = "Risk"

    check_id: StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return sc.check_by_id(properties.check_id).risk_tooltip

    def execute(self, context):
        self.report({'INFO'}, sc.check_by_id(self.check_id).risk_tooltip)
        return {'FINISHED'}


class OOPS_OT_explain(bpy.types.Operator):
    """What this check means (hover for why to fix it, the risk of fixing and why you might keep it)"""
    bl_idname = "oops.explain"
    bl_label = "About This Check"

    check_id: StringProperty(options={'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        return sc.explanation(sc.check_by_id(properties.check_id))

    def execute(self, context):
        self.report({'INFO'}, sc.check_by_id(self.check_id).why)
        return {'FINISHED'}


class OOPS_OT_pick_modifier(bpy.types.Operator):
    """Tick or untick this modifier for Apply Modifiers (on every object sharing this mesh). Unticked ones stay"""
    bl_idname = "oops.pick_modifier"
    bl_label = "Pick Modifier"

    data: StringProperty(options={'HIDDEN'})
    modifier: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        set_modifier_picked(context, self.data, self.modifier, not is_modifier_picked(context, self.data, self.modifier))
        return {'FINISHED'}


class OOPS_OT_inspect(bpy.types.Operator):
    """Select this object, or this bone in Pose Mode, so you can look at it. From All, it also switches to Object so
    you can fix its issues"""
    bl_idname = "oops.inspect"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    object: StringProperty(options={'HIDDEN'})
    bone: StringProperty(options={'HIDDEN'})

    def select(self, context):
        if not sc.inspect(context, bpy.data.objects.get(self.object), self.bone):
            return False
        settings = oops_settings(context)
        if settings.kind == sc.ALL_KIND:
            settings.kind = sc.OBJECT
        return True

    def execute(self, context):
        if not remembering(context, lambda: self.select(context)):
            self.report({'WARNING'}, f"Cannot select {self.object}: it is gone or not in this view layer")
            return {'CANCELLED'}
        return {'FINISHED'}


class OOPS_OT_back(bpy.types.Operator):
    """Go back to where you were before the first Select: mode, active and selected objects, posed bones and the Looking for kind"""
    bl_idname = "oops.back"
    bl_label = "Back"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        extra = position_snapshot.restore(context)
        if extra is None:
            self.report({'INFO'}, "Nothing to go back to")
            return {'CANCELLED'}
        if extra.get("kind") in {item.identifier for item in oops_settings(context).bl_rna.properties["kind"].enum_items}:
            oops_settings(context).kind = extra["kind"]
        return {'FINISHED'}


class OOPS_OT_forget_back(bpy.types.Operator):
    """Forget where you were: the Back button goes away"""
    bl_idname = "oops.forget_back"
    bl_label = "Forget Back"

    def execute(self, context):
        position_snapshot.clear(context)
        return {'FINISHED'}


class OOPS_OT_unhide(bpy.types.Operator):
    """Make this object visible: if it is in a hidden or excluded collection, turn that collection on (press again
    if the object itself is hidden too); else unhide the object"""
    bl_idname = "oops.unhide"
    bl_label = "Unhide"
    bl_options = {'REGISTER', 'UNDO'}

    object: StringProperty(options={'HIDDEN'})
    collection: StringProperty(options={'HIDDEN'})   # the collection it turns on, "" = the object itself

    @classmethod
    def description(cls, context, properties):
        return (f"Turn on the hidden or excluded collection {properties.collection}" if properties.collection
                else "Unhide this object")

    def execute(self, context):
        ob = bpy.data.objects.get(self.object)
        if ob is None or not sc.unhide(context, ob):
            self.report({'WARNING'}, f"Cannot unhide {self.object}: it is gone")
            return {'CANCELLED'}
        return {'FINISHED'}


class OOPS_OT_show(bpy.types.Operator):
    """Make this object active and select the problem elements in Edit Mode (review only: nothing is changed)"""
    bl_idname = "oops.show"
    bl_label = "Show"
    bl_options = {'REGISTER', 'UNDO'}

    check_id: StringProperty(options={'HIDDEN'})
    object: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        ob = bpy.data.objects.get(self.object)
        if ob is None or not remembering(context, lambda: sc.check_by_id(self.check_id).show(context, ob)):
            self.report({'WARNING'}, "Nothing to show: the mesh changed, press Rescan")
            return {'CANCELLED'}
        return {'FINISHED'}


class OOPS_OT_select(bpy.types.Operator):
    """Select the objects or bones this is about"""
    bl_idname = "oops.select"
    bl_label = "Select"
    bl_options = {'REGISTER', 'UNDO'}

    check_id: StringProperty(options={'HIDDEN'})

    def execute(self, context):
        finding = sc.check_by_id(self.check_id).find(scope(context))
        if finding is not None:
            remembering(context, lambda: sc.select_finding(context, finding) or True)
        return {'FINISHED'}


def clear_all_confirm_message(findings, level):
    """The Clear All popup text: how many items, per risk level, and (at the top level) that Risky ones are included."""
    things = sum(f.count for _c, f in findings)
    per_level = ", ".join(f"{count} {sc.RISKS[risk][0]}" for risk, count in sc.risk_counts(findings).items() if count)
    text = f"{len(findings)} items ({things} things) will be cleared: {per_level}."
    if sc.needs_warning(level):
        return f"{text} Risky ones are included: they can break a rig, clothing or a deliberate setup."
    return f"{text} Items above risk {level} stay."


class OOPS_OT_clear_all(bpy.types.Operator):
    """Clears every listed leftover with a risk up to the level chosen next to this button (default 1). Ctrl+Z brings it back"""
    bl_idname = "oops.clear_all"
    bl_label = "Clear All"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        level = clear_all_risk(oops_settings(context))
        findings = sc.clearable_all(scan(context)[0], level)
        return context.window_manager.invoke_confirm(
            self, event, title="Clear all leftovers?", confirm_text="Clear All",
            message=clear_all_confirm_message(findings, level), icon='WARNING' if sc.needs_warning(level) else 'NONE')

    def execute(self, context):
        settings = oops_settings(context)   # only what is shown: the chosen kind and the Scans that are on
        cleared = sc.clear_all(scope(context), kind=settings.kind, scans=scans_on(settings), max_risk=clear_all_risk(settings))
        sc.CACHE.clear()
        self.report({'INFO'}, f"Cleared {cleared} items")
        return {'FINISHED'}


class _BulkFixOperator:
    """A scene-wide fix of the All view (sc.BulkFix): tooltip, a confirm, one undo step, then a rescan."""
    bl_options = {'REGISTER', 'UNDO'}
    fix = None   # the sc.BulkFix

    @classmethod
    def description(cls, context, properties):
        return cls.fix.tooltip

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title=f"{self.fix.action.button}?", confirm_text=self.fix.action.button, message=self.fix.confirm_message)

    def finish(self, worked, text):
        sc.CACHE.clear()
        self.report({'INFO'} if worked else {'WARNING'}, text)
        return {'FINISHED'}


class OOPS_OT_minimize_scales(_BulkFixOperator, bpy.types.Operator):
    bl_idname = "oops.minimize_scales"
    bl_label = sc.MINIMIZE_SCALES.action.button
    fix = sc.MINIMIZE_SCALES

    def execute(self, context):
        done, skipped = sc.minimize_unapplied_scales(sc.scanned_objects(context, oops_settings(context).scan_disabled))
        return self.finish(done and not skipped, sc.minimized_text(done, skipped))


class OOPS_OT_match_data_names(_BulkFixOperator, bpy.types.Operator):
    bl_idname = "oops.match_data_names"
    bl_label = sc.MATCH_DATA_NAMES.action.button
    fix = sc.MATCH_DATA_NAMES

    def execute(self, context):
        renamed = sc.match_data_names(sc.scanned_objects(context, oops_settings(context).scan_disabled))
        return self.finish(renamed, f"Renamed the data of {renamed} objects")


class OOPS_OT_convert_arrays(_BulkFixOperator, bpy.types.Operator):
    bl_idname = "oops.convert_arrays"
    bl_label = sc.CONVERT_ARRAYS
    fix = sc.CONVERT_ALL_ARRAYS

    @classmethod
    def poll(cls, context):
        return instance_array.available()

    def execute(self, context):
        converted, skipped = instance_array.convert_arrays(sc.scanned_mesh_objects(context, oops_settings(context).scan_disabled))
        return self.finish(converted, sc.converted_text(converted, skipped))


def slug(area):
    return area.lower().replace(" & ", "_").replace(" ", "_")


def draw_risk(row, check):
    """The check's risk level next to its Clear button: icon + number, Risky in the alert colour, name in the tooltip."""
    cell = row.row(align=True)
    cell.alert = check.risk == sc.MAX_RISK
    cell.operator(OOPS_OT_risk.bl_idname, text=str(check.risk), icon=RISK_ICONS[check.risk],
                  emboss=False).check_id = check.id


def draw_check_name(layout, check, text):
    """The check's name as flat, left aligned text that looks like a label; hovering it shows sc.explanation()."""
    cell = layout.row(align=True)
    cell.alignment = 'LEFT'
    cell.operator(OOPS_OT_explain.bl_idname, text=text, emboss=False).check_id = check.id


def draw_risk_legend(layout, context):
    """A folded section naming the four risk levels (for the tools that show Clear buttons)."""
    body = section(layout, "oops_risk_levels", "Risk levels", default_closed=True)
    if body:
        hints(body, [f"{n} {name}: {text}" for n, (name, text) in sc.RISKS.items()], context)


def rows_title(check, finding):
    """The title of a finding's foldout, by what its rows hold (a check can set its own `rows_title`)."""
    if check.rows_title:
        return check.rows_title
    if check.show is not None:
        return "Meshes"
    bones = {bool(bone) for _title, _detail, _object, bone, *_enabled in finding.rows}
    return "Bones" if bones == {True} else "Objects" if bones == {False} else "Bones and Objects"


def only_active_row(finding):
    """True when the finding's one row is the active object itself: a foldout would show nothing new."""
    active = sc.active_of(bpy.context)
    if len(finding.rows) != 1 or active is None:
        return False
    _title, _detail, object_name, bone, *_enabled = finding.rows[0]
    return object_name == active.name and not bone


def draw_show_button(row, check, object_name):
    op = row.operator(OOPS_OT_show.bl_idname, text="Show", icon='EDITMODE_HLT')
    op.check_id, op.object = check.id, object_name


def draw_rows(col, check, finding):
    """The foldout list of a finding (closed at first): one row per bone or object, a click selects it; its detail under it.
    When the one row is the active object, no foldout: its detail is drawn inline (a review check keeps its Show)."""
    if only_active_row(finding):
        _title, detail, object_name, _bone, *_enabled = finding.rows[0]
        row = col.row(align=True)
        draw_grey(row, detail)
        if check.show is not None:
            draw_show_button(row, check, object_name)
        return
    body = group(col, f"oops_rows_{check.id}", rows_title(check, finding), default_closed=True, right=f"{len(finding.rows)}")
    if not body:
        return
    for title, detail, object_name, bone, *enabled in finding.rows:   # enabled=[False]: greyed (in use)
        row = body.row(align=True)
        row.active = not enabled or enabled[0]
        if check.show is not None:   # review check: the name is a label, Show selects the elements in Edit Mode
            row.label(text=shorten(title, 28), icon='OBJECT_DATA')
            draw_show_button(row, check, object_name)
        else:
            op = row.operator(OOPS_OT_inspect.bl_idname, text=shorten(title, 28), icon='BONE_DATA' if bone else 'OBJECT_DATA')
            op.object, op.bone = object_name, bone
        draw_grey(body, detail)


def draw_picks(col, check, finding):
    """The Modifiers foldout of Linked Modifiers: a tick per modifier name of each shared mesh (unticked ones stay)."""
    context = bpy.context
    total = sum(len(names) for _data, names in finding.picks)
    ticked = sum(is_modifier_picked(context, data, name) for data, names in finding.picks for name in names)
    body = group(col, f"oops_picks_{check.id}", "Modifiers", default_closed=True, right=f"{ticked} of {total}")
    if not body:
        return
    for data, names in finding.picks:
        if len(finding.picks) > 1:
            body.label(text=shorten(data, 28), icon='MESH_DATA')
        for name in names:
            picked = is_modifier_picked(context, data, name)
            op = body.operator(OOPS_OT_pick_modifier.bl_idname, text=shorten(name, 28),
                               icon='CHECKBOX_HLT' if picked else 'CHECKBOX_DEHLT', emboss=False)
            op.data, op.modifier = data, name


def draw_finding(layout, check, finding, clear_op=None):
    """One found problem: label + count, Select (when it names objects or bones), Clear; grey detail under it.
    A review check (check.show) has neither Clear nor risk: its list rows carry a Show button each. `clear_op` = the
    Clear operator of a tool with its own checks and cache (Rig Check), else the Oops Debugger's."""
    clear_op = clear_op or OOPS_OT_clear.bl_idname
    col = layout.column(align=True)
    row = col.row(align=True)
    if finding.error:   # the check itself failed: say so, nothing to select or clear
        row.alert = True
        row.label(text=f"{check.label} · failed", icon='ERROR')
        draw_grey(col, finding.detail)
        return
    draw_check_name(row, check, f"{check.label} · {finding.count}")
    if finding.objects or finding.bones:
        row.operator(OOPS_OT_select.bl_idname, text="", icon='RESTRICT_SELECT_OFF').check_id = check.id
    if check.clear is not None:
        draw_risk(row, check)
        main, *others = check.actions
        op = row.operator(clear_op, text=main.button)
        op.check_id, op.action = check.id, 0
        offered = [(index, action) for index, action in enumerate(others, start=1) if action.button not in finding.unavailable]
        if offered:   # alternatives get a row of their own under it, each with its risk
            alternatives = col.row(align=True)
            for index, action in offered:
                cell = alternatives.row(align=True)
                cell.alert = action.risk == sc.MAX_RISK
                op = cell.operator(clear_op, text=action.button, icon=RISK_ICONS[action.risk])
                op.check_id, op.action = check.id, index
    if finding.picks:
        draw_picks(col, check, finding)
    if finding.rows:
        draw_rows(col, check, finding)
    elif finding.detail:
        draw_grey(col, finding.detail)


def draw_review(layout, findings, context):
    """The Checks card: review-only mesh checks, each with a fold-out list and a Show button per object."""
    settings = oops_settings(context)
    if not any(c.area == sc.REVIEW for c in sc.checks_of(sc.AREAS, settings.kind, scans_on(settings))):
        grey = layout.column()
        grey.active = False
        grey.label(text=REVIEW_OFF)
        return
    rows = [(c, f) for c, f in findings if c.area == sc.REVIEW]
    if not rows:
        layout.label(text="Checks: nothing to review")
        return
    body = section(layout, f"oops_{slug(sc.REVIEW)}", sc.REVIEW, right=f"{len(rows)} found")
    if not body:
        return
    hints(body, [REVIEW_NOTE], context)
    for check, finding in rows:
        draw_finding(body, check, finding)


def draw_scans(layout, context, settings):
    """The Scans card: a switch per heavy scan of the chosen kind (none: no card)."""
    scans = scans_of_kind(settings.kind)
    if not scans:
        return
    on = scans_on(settings)
    body = section(layout, "oops_scans", "Scans", right=f"{sum(s.id in on for s in scans)}/{len(scans)} on")
    if body:
        hints(body, [SCANS_NOTE], context)
        toggles(body, settings, [(scan_prop(s), s.label) for s in scans])


def draw_render_settings(layout, context):
    """Render kind: the engine, samples and resolution lines of Pre-Render Check."""
    from .pre_render_check import summary_lines   # late: pre_render_check imports this module
    body = section(layout, "oops_render_settings", "Render Settings", default_closed=True)
    if body:
        for line in summary_lines(context.scene):
            status(body, line, icon='SCENE')


def draw_object_rows(layout, context):
    """The All kind: one row per object with issues (name, count, worst risk, Select), its issue labels fold out."""
    found = scan_all(context)
    body = section(layout, "oops_all_objects", "Objects", right=f"{len(found)}")
    if body:
        if minimizable_scales(context):
            action_row(body).operator(OOPS_OT_minimize_scales.bl_idname, text=f"{OOPS_OT_minimize_scales.bl_label} ({len(minimizable_scales(context))})", icon='FULLSCREEN_EXIT')
        draw_convert_arrays(body, context)
        for name, findings in found:
            draw_object_row(body, context, name, findings)


def draw_object_row(layout, context, name, findings):
    worst = max(c.risk for c, _f in findings)
    col = layout.column(align=True)
    row = col.row(align=True)
    row.label(text=f"{shorten(name, 24)} · {len(findings)}", icon=RISK_ICONS[worst])
    row.operator(OOPS_OT_inspect.bl_idname, text="Select").object = name
    if sc.is_unseen(bpy.data.objects[name], context.view_layer):
        off = sc.off_collections_of(bpy.data.objects[name], context.view_layer.layer_collection)
        op = row.operator(OOPS_OT_unhide.bl_idname, text="Unhide Collection" if off else "Unhide")
        op.object, op.collection = name, off[0].name if off else ""
    body = group(col, f"oops_all_{name}", "Problems", default_closed=True, right=f"risk {worst}")
    if body:
        for check, finding in findings:
            draw_check_name(body, check, f"{check.label} · {finding.count}")


def draw_naming(layout, context):
    """The All kind's Naming section: the objects still named like a primitive (Select each), and Match Data Names."""
    names = scan_naming(context)
    body = section(layout, "oops_all_naming", "Naming", right=f"{len(names)}")
    if not body:
        return
    if renamable_data(context):
        action_row(body).operator(OOPS_OT_match_data_names.bl_idname, text=f"{OOPS_OT_match_data_names.bl_label} ({len(renamable_data(context))})", icon='OUTLINER_DATA_MESH')
    for name in names:
        row = body.row(align=True)
        row.label(text=shorten(name, 28), icon='OBJECT_DATA')
        row.operator(OOPS_OT_inspect.bl_idname, text="Select").object = name


def draw_convert_arrays(layout, context):
    """Convert Arrays for every scanned mesh, only when some Array is convertible; greyed with a note without the Digit's
    Modifiers add-on; the Arrays that can't convert are counted below it."""
    convertible, skipped = linked_arrays(context)
    if not convertible:
        return
    can_convert = instance_array.available()
    row = action_row(layout)
    row.enabled = can_convert
    row.operator(OOPS_OT_convert_arrays.bl_idname, text=f"{sc.CONVERT_ARRAYS} ({len(convertible)})", icon='MOD_ARRAY')
    notes = [] if can_convert else ["Needs the Digit's Modifiers add-on (its Instance Array asset)"]
    hints(layout, notes + [f"Not convertible: {count} ({reason})" for reason, count in sorted(skipped.items())], context)


def draw_linked_modifiers(layout, context):
    """The All kind's Modifiers on Linked Data section: per shared data, the users that have modifiers (Select each)."""
    groups = scan_linked_modifiers(context)
    body = section(layout, "oops_all_linked_modifiers", "Modifiers on Linked Data", right=f"{len(groups)}")
    if not body:
        return
    for data_name, user_count, users in groups:
        col = body.column(align=True)
        head = col.row(align=True)
        head.label(text=f"{shorten(data_name, 24)} · {user_count} users", icon='LINKED')
        for name, modifier_names in users:
            row = col.row(align=True)
            row.label(text=shorten(name, 28), icon='OBJECT_DATA')
            row.operator(OOPS_OT_inspect.bl_idname, text="Select").object = name
            grey = col.column()
            grey.active = False
            grey.label(text=shorten(", ".join(modifier_names)))


def draw_scope_toggles(layout, context, settings):
    """Scan Disabled Collections (N): one setting for the Object, Scene and All kinds; N = what it would add.
    The Ignore settings beside it, in the kinds that hold their check."""
    count = sc.disabled_count(context, settings.kind)
    items = [("scan_disabled", f"Scan Disabled Collections ({count})")]
    checks = sc.checks_of(sc.AREAS, settings.kind)
    gated, trimmed = {c.scan for c in checks}, {c.id for c in checks}
    items += [(ignore_prop(i), i.label) for i in sc.IGNORES if (i.filters in trimmed if i.filters else i.id in gated)]
    toggles(layout, settings, items, columns=1)


def draw_all_card(layout, context, settings):
    """The All kind: Rescan, the Scans, then the objects with issues. No Clear All: fix them in the Object kind."""
    found = scan_all(context)
    head = layout.row(align=True)
    if found:
        head.label(text=f"{len(found)} objects", icon='ERROR')
    else:
        head.label(text=NOTHING, icon='CHECKMARK')
    head.operator(OOPS_OT_rescan.bl_idname, text="", icon='FILE_REFRESH')
    draw_scans(layout, context, settings)
    draw_scope_toggles(layout, context, settings)
    draw_object_rows(layout, context)
    draw_naming(layout, context)
    draw_linked_modifiers(layout, context)


def draw_back(layout, context):
    """The Back button (and an X to forget it) while a position is kept; nothing otherwise."""
    text = position_snapshot.label(context)
    if text is None:
        return
    row = action_row(layout)
    row.operator(OOPS_OT_back.bl_idname, text=shorten(text, 28), icon='LOOP_BACK')
    row.operator(OOPS_OT_forget_back.bl_idname, text="", icon='X')


def draw_read_first(layout, context):
    """The red warning at the top of the card (alert is set before the labels are added, or they stay white)."""
    warning = layout.column(align=True)
    warning.alert = True
    wrapped(warning, READ_FIRST, icon='ERROR', context=context)


def draw_clear_all(layout, leftovers, settings):
    """The risk level select and the Clear All button (with the count at that level); a red line at the top level."""
    level = clear_all_risk(settings)
    clearable = len(sc.clearable_all(leftovers, level))
    layout.prop(settings, "clear_all_risk", text="")
    if sc.needs_warning(level):
        warning = layout.column(align=True)
        warning.alert = True
        warning.label(text="Risky ones included: they can break a rig or a setup.", icon='ERROR')
    if clearable:
        action_row(layout).operator(OOPS_OT_clear_all.bl_idname, text=f"Clear All Leftovers ({clearable})", icon='TRASH')


def draw_card(layout, context):
    settings = oops_settings(context)
    draw_read_first(layout, context)
    draw_back(layout, context)
    smart_prop(layout, settings, "kind", text="Looking for")
    if settings.kind == sc.ALL_KIND:
        draw_all_card(layout, context, settings)
        return
    findings, name = scan(context)
    leftovers = [(c, f) for c, f in findings if c.area != sc.REVIEW]
    head = layout.row(align=True)
    if leftovers:
        head.label(text=f"{len(leftovers)} found", icon='ERROR')
    else:
        head.label(text=NOTHING, icon='CHECKMARK')
    head.operator(OOPS_OT_rescan.bl_idname, text="", icon='FILE_REFRESH')
    if not name and settings.kind == sc.OBJECT:
        hints(layout, ["Select the character to check its rig and meshes too"], context)
    draw_scans(layout, context, settings)
    if settings.kind != sc.RENDER_KIND:
        draw_scope_toggles(layout, context, settings)
    if settings.kind == sc.RENDER_KIND:
        draw_render_settings(layout, context)
    if leftovers:
        hints(layout, [WARNING], context)
        draw_clear_all(layout, leftovers, settings)
        draw_risk_legend(layout, context)
        for area in sc.AREAS:
            rows = [(c, f) for c, f in leftovers if c.area == area]
            if not rows:
                continue
            body = section(layout, f"oops_{slug(area)}", area, right=f"{len(rows)} found")
            if body:
                for check, finding in rows:
                    draw_finding(body, check, finding)
    if name and settings.kind == sc.OBJECT:
        draw_review(layout, findings, context)


classes = (OOPS_OT_rescan, OOPS_OT_clear, OOPS_OT_risk, OOPS_OT_explain, OOPS_OT_pick_modifier, OOPS_OT_inspect, OOPS_OT_back, OOPS_OT_forget_back, OOPS_OT_minimize_scales, OOPS_OT_match_data_names, OOPS_OT_convert_arrays, OOPS_OT_unhide, OOPS_OT_show, OOPS_OT_select, OOPS_OT_clear_all)


def register():
    position_snapshot.register()
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    position_snapshot.unregister()
