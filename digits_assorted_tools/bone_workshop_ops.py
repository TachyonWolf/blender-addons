# SPDX-License-Identifier: GPL-3.0-or-later
"""Bone Workshop operators. Each click is one operator with UNDO that changes every target (the active or the
selected bones, plus their mirror bones) inside one execute: one undo step however many bones it changes. Mode
switches use plain mode_set inside that execute; bones are fetched again by name after a switch."""
import bpy
from bpy.props import EnumProperty, StringProperty

from . import bone_setups as setups, bone_workshop as bw, bone_workshop_props as props, bone_workshop_spec as spec
from . import bone_collections as bc, limb_rig as lr, rig_names as rn, view_ray  # generated copies
from .save_pose import apply_exact_pose, read_exact_pose

UNDO = {'REGISTER', 'UNDO'}


def pose_why(context):
    """Why the Bone Workshop buttons can't run now, or ""."""
    ob = context.active_object
    if ob is None or ob.type != 'ARMATURE':
        return "Select an armature"
    if context.mode != 'POSE':
        return "Go to Pose Mode"
    if context.active_pose_bone is None:
        return "Click a bone to make it active"
    return ""


class BoneOperator:
    """Base: runs in Pose Mode with an active bone; reports what it did and what it skipped."""
    bl_options = UNDO

    @classmethod
    def poll(cls, context):
        why = pose_why(context)
        if why:
            cls.poll_message_set(why)
        return not why

    def done(self, line, skipped=()):
        for why in dict.fromkeys(s for s in skipped if s):
            self.report({'WARNING'}, why)
        self.report({'INFO'}, line)
        return {'FINISHED'}

    def refused(self, why):
        self.report({'WARNING'}, why)
        return {'CANCELLED'}


def settings(context):
    return props.settings_of(context)


class DIGITOOLS_OT_bw_shape(BoneOperator, bpy.types.Operator):
    """Give the bones this shape. Shapes are shared: every bone with the same shape and settings uses one mesh"""
    bl_idname = "digits_assorted_tools.bw_shape"
    bl_label = "Shape"
    shape: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})   # a tile id, 'MESH' (the picked mesh) or 'NONE' (clear)

    @classmethod
    def description(cls, context, properties):
        if properties.shape == 'NONE':
            return "Take the shape off: the bone is drawn as a plain bone again"
        if properties.shape == 'MESH':
            return "Use the picked mesh object as the shape"
        tile = spec.SHAPE_BY_ID.get(properties.shape)
        return tile.tip if tile else ""

    def execute(self, context):
        found = bw.targets(context)
        bones, why = found.usable()
        if self.shape == 'NONE':
            bw.set_shape(bones, None)
            return self.done(bw.report_line(len(bones), "Shape cleared", found), why)
        if self.shape == 'MESH':
            mesh = settings(context).use_mesh
            if mesh is None:
                return self.refused("Pick a mesh first")
            for pb in bones:
                pb.custom_shape = mesh
            return self.done(bw.report_line(len(bones), mesh.name, found), why)
        widget = spec.widget_of(self.shape, bw.last_options(settings(context)))
        bw.set_shape(bones, widget)
        return self.done(bw.report_line(len(bones), widget, found), why)


class DIGITOOLS_OT_bw_edit_shape(BoneOperator, bpy.types.Operator):
    """Edit the shape's vertices on a copy: only these bones get the edited shape, others keep the shared one"""
    bl_idname = "digits_assorted_tools.bw_edit_shape"
    bl_label = "Edit Shape"
    action: EnumProperty(items=(('START', "Edit Shape", ""), ('DONE', "Done Editing Shape", "")),
                         options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.action == 'DONE':
            return "Finish editing the shape and go back to the rig in Pose Mode"
        return cls.__doc__

    @classmethod
    def poll(cls, context):
        return True if settings(context).editing_shape else super().poll(context)

    def execute(self, context):
        return self.finish(context) if self.action == 'DONE' else self.start(context)

    def start(self, context):
        pb = context.active_pose_bone
        if pb.custom_shape is None or pb.custom_shape.type != 'MESH':
            return self.refused("Pick a shape first: Edit Shape edits a copy of the bone's shape")
        found = bw.targets(context)
        bones, why = found.usable()
        if pb not in bones:
            return self.refused(why[0] if why else "This bone can't be changed")
        rig, matrix = pb.id_data, bw.edit_shape_matrix(pb)
        copy = bw.own_copy(pb)
        for bone in bones:
            if bone.custom_shape == pb.custom_shape:
                bone.custom_shape = copy
        bpy.ops.object.mode_set(mode='OBJECT')
        context.scene.collection.objects.link(copy)
        copy.matrix_world = matrix
        for ob in context.selected_objects:
            ob.select_set(False)
        copy.select_set(True)
        context.view_layer.objects.active = copy
        bpy.ops.object.mode_set(mode='EDIT')
        s = settings(context)
        s.editing_shape, s.editing_rig = copy.name, rig.name
        return self.done(f"Editing {copy.name}: press Done Editing Shape when you are done")

    def finish(self, context):
        s = settings(context)
        copy, rig = bpy.data.objects.get(s.editing_shape), bpy.data.objects.get(s.editing_rig)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if copy is not None:
            copy.matrix_world.identity()
            for coll in list(copy.users_collection):
                coll.objects.unlink(copy)
        s.editing_shape = s.editing_rig = ""
        if rig is not None and rig.name in context.view_layer.objects:
            for ob in context.selected_objects:
                ob.select_set(False)
            rig.select_set(True)
            context.view_layer.objects.active = rig
            bpy.ops.object.mode_set(mode='POSE')
        return self.done("Shape edited")


class DIGITOOLS_OT_bw_preset(BoneOperator, bpy.types.Operator):
    """Apply a style preset: shape, size and colour in one click (built-in ones also sort the bones into their
    standard collections by name)"""
    bl_idname = "digits_assorted_tools.bw_preset"
    bl_label = "Style Preset"
    preset: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    action: EnumProperty(items=(('APPLY', "Apply", ""), ('SAVE', "Save Current as Preset", ""),
                                ('REMOVE', "Remove", "")), options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.action == 'SAVE':
            return "Save the active bone's shape, size and colour as a preset you can use in every file"
        if properties.action == 'REMOVE':
            return f"Remove the saved preset {properties.preset}"
        built = spec.PRESET_BY_ID.get(properties.preset)
        return built.tip + ". Also sorts the bones into their collections by name" if built else \
            f"Apply your preset {properties.preset}: shape, size and colour"

    def invoke(self, context, event):
        if self.action == 'SAVE':
            return context.window_manager.invoke_props_dialog(self, title="Save Preset", confirm_text="Save")
        return self.execute(context)

    def draw(self, context):
        self.layout.prop(settings(context), "preset_name")

    def execute(self, context):
        saved = bw.saved_presets()
        if self.action == 'SAVE':
            name = settings(context).preset_name.strip() or "My Preset"
            saved[name] = bw.look_of(context.active_pose_bone)
            bw.store_presets(saved)
            return self.done(f"Preset {name} saved")
        if self.action == 'REMOVE':
            saved.pop(self.preset, None)
            bw.store_presets(saved)
            return self.done(f"Preset {self.preset} removed")
        look = bw.preset_look(self.preset, saved)
        if look is None:
            return self.refused(f"No preset {self.preset}")
        found = bw.targets(context)
        done, why = bw.apply_preset(found, look, settings(context).colour_where, sort=self.preset in spec.PRESET_BY_ID)
        label = spec.PRESET_BY_ID[self.preset].label if self.preset in spec.PRESET_BY_ID else self.preset
        return self.done(bw.report_line(done, label, found), why)


class DIGITOOLS_OT_bw_colour(BoneOperator, bpy.types.Operator):
    """Colour the bones"""
    bl_idname = "digits_assorted_tools.bw_colour"
    bl_label = "Bone Colour"
    mode: EnumProperty(items=(('PALETTE', "Colour", ""), ('COLLECTION', "From Collection", ""),
                              ('SIDE', "By Side", "")), options={'HIDDEN', 'SKIP_SAVE'})
    palette: StringProperty(default='DEFAULT', options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.mode == 'COLLECTION':
            return "Each bone takes the standard colour of its home collection (bones in your own collections keep theirs)"
        if properties.mode == 'SIDE':
            return "Left bones blue, right bones red, middle bones yellow"
        return f"Colour the bones {spec.COLOUR_NAMES.get(properties.palette, properties.palette)}"

    def execute(self, context):
        found = bw.targets(context)
        bones, why = found.usable('data')
        where, skipped = settings(context).colour_where, 0
        for pb in bones:
            if self.mode == 'COLLECTION':
                palette = bc.COLOR.get(bw.home_of(pb) or "")
                if palette is None:
                    skipped += 1
                    continue
            elif self.mode == 'SIDE':
                palette = spec.BY_SIDE[rn.side_of(pb.name)]
            else:
                palette = self.palette
            bw.set_colour(pb, palette, where)
        if skipped:
            why.append(f"{skipped} bones are in collections with no standard colour")
        return self.done(bw.report_line(len(bones) - skipped, "Colour", found), why)


class DIGITOOLS_OT_bw_size(BoneOperator, bpy.types.Operator):
    """Size the shapes"""
    bl_idname = "digits_assorted_tools.bw_size"
    bl_label = "Shape Size"
    action: EnumProperty(items=(('FIT', "Fit to Mesh", ""), ('MATCH', "Match Active", ""), ('RESET', "Reset", "")),
                         options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return {'FIT': "Size each shape to the body around its bone (once, now)",
                'MATCH': "Give the other bones the active bone's size and placement",
                'RESET': "Size 1, no offset, no turn, normal line width, drawn at the bone itself"}[properties.action]

    def execute(self, context):
        found = bw.targets(context)
        bones, why = found.usable()
        if self.action == 'FIT':
            fitted, missed = bw.fit_to_mesh(bones)
            if missed:
                why.append(f"{missed} bones are not inside the body: they keep their size")
            return self.done(bw.report_line(fitted, "Fitted", found), why)
        active = context.active_pose_bone
        for pb in bones:
            if self.action == 'RESET':
                bw.reset_placement(pb)
            elif pb != active:
                bw.copy_placement(active, pb)
        return self.done(bw.report_line(len(bones), "Size", found), why)


class DIGITOOLS_OT_bw_collection(BoneOperator, bpy.types.Operator):
    """Bone collections"""
    bl_idname = "digits_assorted_tools.bw_collection"
    bl_label = "Bone Collection"
    action: EnumProperty(items=(('HOME', "Make Home", ""), ('ADD', "Also Add", ""), ('REMOVE', "Remove", ""),
                                ('SORT', "Auto-Sort by Name", ""), ('MAKE', "Make Collection", "")),
                         options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        name = properties.name or "the picked collection"
        return {'HOME': f"Make {name} the bones' home: they move there (deform bones also go in Body or Face Deform)",
                'ADD': f"Also put the bones in {name}, keeping their home",
                'REMOVE': f"Take the bones out of {name}",
                'SORT': "Put each bone in its standard collection by its name (DEF- to Deform, MCH- to Mechanism...)",
                'MAKE': "Make a new bone collection and move the bones there"}[properties.action]

    def invoke(self, context, event):
        if self.action == 'MAKE':
            return context.window_manager.invoke_props_dialog(self, title="Make Collection", confirm_text="Make")
        return self.execute(context)

    def draw(self, context):
        s = settings(context)
        col = self.layout.column()
        col.prop(s, "new_collection")
        col.prop_search(s, "new_parent", context.active_object.data, "collections_all")

    def execute(self, context):
        found = bw.targets(context)
        s = settings(context)
        if self.action == 'SORT':
            bones, why = found.usable('data')
            return self.done(bw.report_line(bw.auto_sort(bones), "Sorted", found), why)
        if self.action == 'MAKE':
            return self.make(context, found, s)
        name = self.name or s.picked
        if not name:
            return self.refused("Click a collection first")
        if self.action == 'HOME':
            s.picked = name
            done, why = bw.move_home(found, name)
            return self.done(bw.report_line(done, f"Home {name}", found), why)
        done, why = bw.also_add(found, name, add=self.action == 'ADD')
        return self.done(bw.report_line(done, ("Added to " if self.action == 'ADD' else "Removed from ") + name, found), why)

    def make(self, context, found, s):
        rig = context.active_object
        why = bw.why_not(rig, 'data')
        if why:
            return self.refused(why)
        name = s.new_collection.strip()
        if not name:
            return self.refused("Type a name for the new collection")
        colls = rig.data.collections_all
        if name not in colls:
            if name in bc.PARENT:
                bc.ensure_home(rig, name)
            else:
                rig.data.collections.new(name, parent=colls.get(s.new_parent))
        s.picked = name
        done, skipped = bw.move_home(found, name)
        if name not in bc.PARENT:
            skipped.append(f"{name} is not one of the standard collections (docs/BONE_NAMES.md)")
        return self.done(bw.report_line(done, f"Home {name}", found), skipped)


class DIGITOOLS_OT_bw_toggle(BoneOperator, bpy.types.Operator):
    """Turn a bone setting on or off for every bone"""
    bl_idname = "digits_assorted_tools.bw_toggle"
    bl_label = "Bone Setting"
    setting: EnumProperty(items=(('DEFORM', "Deform", ""), ('CONNECTED', "Connected", "")),
                          options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.setting == 'DEFORM':
            return "Deform bones bend the mesh. On also puts the bone in Body or Face Deform; off takes it out"
        return "The bone's start sticks to its parent's end, so it can only turn, not move. Only bones that touch " \
               "their parent can connect"

    def execute(self, context):
        found = bw.targets(context)
        active = context.active_pose_bone
        if self.setting == 'DEFORM':
            bones, why = found.usable('data')
            on = not active.bone.use_deform
            homeless = sum(not bw.set_deform(pb, on) for pb in bones)
            if homeless:
                why.append(f"{homeless} bones have no collection yet: give them a home to add Body / Face Deform")
            return self.done(bw.report_line(len(bones), "Deform " + ("on" if on else "off"), found), why)
        return self.connect(context, found, not active.bone.use_connect)

    def connect(self, context, found, on):
        bones, why = found.usable('edit')
        if not bones:
            return self.refused(why[0] if why else "Nothing to change")
        names = {(pb.id_data.name, pb.name) for pb in bones}
        bpy.ops.object.mode_set(mode='EDIT')
        done = far = 0
        for rig_name, name in names:
            eb = bpy.data.objects[rig_name].data.edit_bones.get(name)
            if eb is None or eb.parent is None:
                continue
            if on and (eb.head - eb.parent.tail).length > 1e-4:
                far += 1
                continue
            eb.use_connect = on
            done += 1
        bpy.ops.object.mode_set(mode='POSE')
        if far:
            why.append(f"{far} bones don't touch their parent's end, so they can't connect")
        return self.done(bw.report_line(done, "Connected " + ("on" if on else "off"), found), why)


class DIGITOOLS_OT_bw_name(BoneOperator, bpy.types.Operator):
    """Bone names"""
    bl_idname = "digits_assorted_tools.bw_name"
    bl_label = "Bone Name"
    action: EnumProperty(items=(('ROLE', "Role", ""), ('STANDARD', "Rename to Standard", ""),
                                ('MIRROR', "Select Mirror", "")), options={'HIDDEN', 'SKIP_SAVE'})
    role: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.action == 'ROLE':
            return next((tip for ident, _l, tip in spec.ROLES if ident == properties.role), "") + \
                ". Renames the bones: animation, constraints and vertex groups follow"
        if properties.action == 'STANDARD':
            return "Rename the bones to their standard names (docs/BONE_NAMES.md). Animation and constraints follow"
        return "Select the bone on the other side"

    def execute(self, context):
        if self.action == 'MIRROR':
            pb = context.active_pose_bone
            other = bw.mirror_of(pb)
            if other is None:
                return self.refused(f"{pb.name} has no mirror bone" if rn.has_side(pb.name) else f"{pb.name} is a middle bone")
            bw.select_only(context, [(other.id_data, other.name)])
            return self.done(f"Selected {other.name}")
        found = bw.targets(context)
        bones, why = found.usable('data')
        done = 0
        for rig in {pb.id_data for pb in bones}:
            names = [pb.name for pb in bones if pb.id_data == rig]
            table = ({n: spec.with_role(n, self.role) for n in names} if self.action == 'ROLE'
                     else bw.standard_table(rig, names))
            count, clashes = bw.rename(rig, table)
            done += count
            why += clashes
            if self.action == 'ROLE' and self.role == 'DEF':
                for name in (table.get(n, n) for n in names):
                    if name in rig.pose.bones and not rig.data.bones[name].use_deform:
                        bw.set_deform(rig.pose.bones[name], True)
        return self.done(bw.report_line(done, "Renamed", found), why)


class DIGITOOLS_OT_bw_copy(BoneOperator, bpy.types.Operator):
    """Copy looks between bones"""
    bl_idname = "digits_assorted_tools.bw_copy"
    bl_label = "Copy Look"
    action: EnumProperty(items=(('SELECTED', "Copy Active to Selected", ""), ('MIRROR', "Mirror to Other Side", "")),
                         options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.action == 'MIRROR':
            return "Give each bone's mirror bone the same shape, size, colour, settings and collection (other side)"
        return "Give the selected bones the active bone's shape, size and colour"

    def execute(self, context):
        if self.action == 'MIRROR':
            found = bw.Targets(context, settings(context).target == 'SELECTED', False)
            done, why = bw.mirror_to_side(found)
            return self.done(bw.report_line(done, "Mirrored", found), why)
        found = bw.Targets(context, True, settings(context).mirror)
        bones, why = found.usable('data')
        active = context.active_pose_bone
        for pb in bones:
            if pb != active:
                bw.copy_look(active, pb)
        return self.done(bw.report_line(len(bones) - (active in bones), "Look copied", found), why)


class DIGITOOLS_OT_bw_pick_look(BoneOperator, bpy.types.Operator):
    """Click a bone in the viewport: its shape, size and colour go onto your bones"""
    bl_idname = "digits_assorted_tools.bw_pick_look"
    bl_label = "Copy Look From a Bone"

    def invoke(self, context, event):
        return view_ray.begin_click(context, self, 'EYEDROPPER',
                                    "Click a bone to copy its look  ·  Esc / Right-click: cancel")

    def modal(self, context, event):
        kind = view_ray.click_kind(event)
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind == 'cancel':
            view_ray.end_click(context)
            return {'CANCELLED'}
        if kind != 'click':
            return {'RUNNING_MODAL'}
        rigs = [ob for ob in context.visible_objects if ob.type == 'ARMATURE']
        hit = view_ray.bone_under_mouse(context, event, rigs)
        if hit is None:
            context.workspace.status_text_set("No bone there: click closer to a bone  ·  Esc / Right-click: cancel")
            return {'RUNNING_MODAL'}
        view_ray.end_click(context)
        return self.copy_from(context, hit[0].pose.bones[hit[1]])

    def copy_from(self, context, source):
        found = bw.targets(context)
        bones, why = found.usable('data')
        bones = [pb for pb in bones if pb != source]
        for pb in bones:
            bw.copy_look(source, pb)
        return self.done(bw.report_line(len(bones), f"Look of {source.name}", found), why)


class DIGITOOLS_OT_bw_pose_mode(bpy.types.Operator):
    """Go to Pose Mode on the active armature (or the armature of the active mesh)"""
    bl_idname = "digits_assorted_tools.bw_pose_mode"
    bl_label = "Go to Pose Mode"
    bl_options = UNDO

    @classmethod
    def poll(cls, context):
        return rig_for_pose(context) is not None

    def execute(self, context):
        rig = rig_for_pose(context)
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = rig
        rig.select_set(True)
        bpy.ops.object.mode_set(mode='POSE')
        return {'FINISHED'}


def rig_for_pose(context):
    ob = context.active_object
    if ob is None:
        return None
    rig = ob if ob.type == 'ARMATURE' else ob.find_armature()
    return rig if rig is not None and rig.name in context.view_layer.objects and not rig.library else None


class DIGITOOLS_OT_bw_copy_setting(BoneOperator, bpy.types.Operator):
    """Copy this value of the active bone to the other bones (and their mirror bones)"""
    bl_idname = "digits_assorted_tools.bw_copy_setting"
    bl_label = "Copy to Bones"
    prop: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        value = props.VALUE_BY_PROP[self.prop]
        active = context.active_pose_bone
        new = getattr(props.owner_of(active, value), value.attr)
        new = tuple(new) if hasattr(new, "__len__") and not isinstance(new, str) else new
        done = bw.write_targets(context, lambda pb: props.write_value(pb, value, new), props.need_of(value))
        return self.done(f"{value.attr} on {done} bones")


class DIGITOOLS_OT_bw_setup(BoneOperator, bpy.types.Operator):
    """Constraint setups"""
    bl_idname = "digits_assorted_tools.bw_setup"
    bl_label = "Add Setup"
    action: EnumProperty(items=(('PICK', "Pick", ""), ('ADD', "Add Setup", "")), options={'HIDDEN', 'SKIP_SAVE'})
    setup: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        setup = setups.BY_ID.get(properties.setup or settings(context).setup)
        if setup is None:
            return ""
        if properties.action == 'PICK':
            return setup.desc
        return f"Add {setup.label} to the selected bones (and their mirror bones): {setup.adds}"

    @classmethod
    def poll(cls, context):
        return True if context.active_object is not None else super().poll(context)

    def execute(self, context):
        s = settings(context)
        if self.action == 'PICK':
            s.setup = self.setup
            return {'FINISHED'}
        why = pose_why(context)
        if why:
            return self.refused(why)
        setup = setups.BY_ID[s.setup]
        sel = setups.Selection.of(context)
        why = setups.why_not(setup, sel, s)
        if why:
            return self.refused(why)
        lines = setups.add(setup, sel, s, s.mirror)
        for line in lines[1:]:
            self.report({'INFO'}, line)
        return self.done(f"{setup.label}: {lines[0]}")


class DIGITOOLS_OT_bw_try_setup(BoneOperator, bpy.types.Operator):
    """Pose the rig to show the setup working (move the mouse for more or less); a click puts the pose back"""
    bl_idname = "digits_assorted_tools.bw_try_setup"
    bl_label = "Try It"
    bl_options = {'REGISTER'}
    SCRUB = 300.0     # pixels of mouse move from none to the full demo pose

    def invoke(self, context, event):
        s = settings(context)
        sel = setups.Selection.of(context)
        setup = setups.BY_ID[s.setup]
        try:
            self.items = setup.demo(sel, s)
        except (IndexError, KeyError, TypeError, AttributeError):
            return self.refused(setup.needs)
        if not self.items or any(bone not in sel.rig.pose.bones for bone, *_ in self.items):
            return self.refused("Add the setup first: Try It shows it working")
        self.rig, self.start = sel.rig, event.mouse_x
        self.pose = read_exact_pose(self.rig)
        setups.apply_demo(self.rig, self.items, 1.0)
        return view_ray.begin_click(context, self, 'SCROLL_X', "Move the mouse left / right: less / more  ·  "
                                                               "Click, Esc or Right-click: put the pose back")

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            amount = min(1.0, max(0.0, 1.0 + (event.mouse_x - self.start) / self.SCRUB))
            apply_exact_pose(self.rig, self.pose)
            setups.apply_demo(self.rig, self.items, amount)
            return {'RUNNING_MODAL'}
        kind = view_ray.click_kind(event)
        if kind == 'pass':
            return {'PASS_THROUGH'}
        if kind in ('click', 'cancel'):
            apply_exact_pose(self.rig, self.pose)
            view_ray.end_click(context)
            return {'CANCELLED'}     # nothing changed: no undo step
        return {'RUNNING_MODAL'}


class DIGITOOLS_OT_bw_constraint(BoneOperator, bpy.types.Operator):
    """Constraints on the active bone"""
    bl_idname = "digits_assorted_tools.bw_constraint"
    bl_label = "Bone Constraint"
    action: EnumProperty(items=(('REMOVE', "Remove", ""), ('MUTE', "Mute All", ""), ('MIRROR', "Copy to Mirror Side", "")),
                         options={'HIDDEN', 'SKIP_SAVE'})
    name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return {'REMOVE': f"Remove the constraint {properties.name} (and its drivers) from the bone and its mirror bone",
                'MUTE': "Switch all of the bone's constraints off, or back on (they stay on the bone)",
                'MIRROR': "Copy the bone's constraints to its mirror bone, bone names swapped (same names are "
                          "replaced). Check turns that mirror, like Transformation"}[properties.action]

    def execute(self, context):
        pb = context.active_pose_bone
        why = bw.why_not(pb.id_data, 'pose')
        if why:
            return self.refused(why)
        other = bw.mirror_of(pb)
        bones = [pb] + ([other] if other is not None and settings(context).mirror else [])
        if self.action == 'MIRROR':
            count, other = bw.mirror_constraints(pb)
            if other is None:
                return self.refused(f"{pb.name} has no mirror bone")
            return self.done(f"{count} constraints copied to {other.name}")
        if self.action == 'REMOVE':
            done = 0
            for bone in bones:
                if self.name in bone.constraints:
                    lr.remove_constraint(bone.id_data, bone.name, self.name)
                    done += 1
            return self.done(f"{self.name} removed from {done} bones")
        mute = any(not c.mute for c in pb.constraints)
        for bone in bones:
            for c in bone.constraints:
                c.mute = mute
        return self.done(("Muted" if mute else "Unmuted") + f" the constraints of {len(bones)} bones")


classes = (DIGITOOLS_OT_bw_shape, DIGITOOLS_OT_bw_edit_shape, DIGITOOLS_OT_bw_preset, DIGITOOLS_OT_bw_colour,
           DIGITOOLS_OT_bw_size, DIGITOOLS_OT_bw_collection, DIGITOOLS_OT_bw_toggle, DIGITOOLS_OT_bw_name,
           DIGITOOLS_OT_bw_copy, DIGITOOLS_OT_bw_pick_look, DIGITOOLS_OT_bw_pose_mode, DIGITOOLS_OT_bw_copy_setting,
           DIGITOOLS_OT_bw_setup, DIGITOOLS_OT_bw_try_setup, DIGITOOLS_OT_bw_constraint)
