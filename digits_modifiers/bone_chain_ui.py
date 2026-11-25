# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/bone_chain_ui.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""The combined weight group tool, shared by Digit's Modifiers (its card) and Digit's Tools (a dropdown tool under
Weights): a vertex group = min(1, summed weights of a bone chain), minus the Excluded Bones. This file is the ONE
source (sync_shared.py copies it into each extension folder); the weight logic is in bone_chain.py.

    tool = bone_chain_ui.BoneChainTool(__package__)   # one per extension: its operators, settings and idnames carry the package name
    tool.register() / tool.unregister()
    tool.draw_body(layout, context)                   # the tool's controls (the host supplies the card or dropdown title)
"""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from .bone_chain import chain_bone_names, chain_path, deformed_meshes, rig_for_chain, selected_bones, write_chain_group  # generated copy
from .ui_cards import action_row, friendly_name, hints, prop_group, section, status  # generated copy

DISPLAY_NAME = "Combined Weight From Bones"   # the tool's name everywhere (card title, dropdown entry): change it here only
BUTTON_TEXT = "Make Combined Weight Group"
DEFAULT_GROUP = "InflateExclude"
EXCLUDE_HELP = ("Bones left out of the sum, e.g. the jaw when making a head group. Their children are left out too "
                "while Exclude Children is on")
SUMMARY_CHARS = 24   # a header summary shares the row with the title


class BoneChainTool:
    """One instance per extension (`package` = its folder name): builds the settings, operators and card from it, so two
    extensions that both ship the tool never share a class name, an operator id or a Scene property."""

    def __init__(self, package):
        self.package = package.rsplit(".", 1)[-1]
        self.prop = f"{self.package}_bone_chain"           # the Scene property holding the settings
        self.make_operator_id = f"{self.package}.bone_chain_group"
        self.exclude_operator_id = f"{self.package}.bone_chain_exclude"
        self.classes = self._make_classes()

    # -- classes ------------------------------------------------------------

    def _make_classes(self):
        tool, prefix = self, self.package.upper()
        item = type(f"{prefix}_PG_bone_chain_item", (bpy.types.PropertyGroup,),
                    {"__annotations__": {"name": StringProperty(name="Bone", description=EXCLUDE_HELP)}})
        settings = type(f"{prefix}_PG_bone_chain", (bpy.types.PropertyGroup,), {"__annotations__": {
            "group_name": StringProperty(name="Group", default=DEFAULT_GROUP, description="Name of the vertex group to write"),
            "root_bone": StringProperty(name="Root Bone", default="", description=(
                "Chain root bone. Empty: use the bones selected in Pose Mode / Weight Paint")),
            "exclude_children": BoolProperty(name="Exclude Children", default=True, description=(
                "Also leave out everything below an excluded bone (the jaw's teeth, tongue...)")),
            "excluded": CollectionProperty(type=item, name="Excluded Bones", description=EXCLUDE_HELP)}})

        class MakeGroup(bpy.types.Operator):
            __doc__ = ("Vertex group = min(1, summed weights of the chosen bone (else the selected bones) and all their "
                       "descendants), leaving out the Excluded Bones")
            bl_idname = tool.make_operator_id
            bl_label = BUTTON_TEXT
            bl_options = {'REGISTER', 'UNDO'}

            @classmethod
            def poll(cls, context):
                return rig_for_chain(context) is not None

            def execute(self, context):
                message, ok = tool.make_group(context)
                self.report({'INFO' if ok else 'WARNING'}, message)
                return {'FINISHED' if ok else 'CANCELLED'}

        class Exclude(bpy.types.Operator):
            """Change the Excluded Bones list"""
            bl_idname = tool.exclude_operator_id
            bl_label = "Excluded Bones"
            bl_options = {'REGISTER', 'UNDO'}

            action: EnumProperty(items=(("ADD_SELECTED", "Add Selected", "Leave out the bones selected in Pose Mode (and their children)"),
                                        ("CLEAR", "Clear", "Leave nothing out"),
                                        ("REMOVE", "Remove", "Take this bone off the list")), options={'HIDDEN'})
            index: IntProperty(options={'HIDDEN'})

            @classmethod
            def poll(cls, context):
                return rig_for_chain(context) is not None

            def execute(self, context):
                excluded = tool.settings(context).excluded
                if self.action == 'CLEAR':
                    excluded.clear()
                elif self.action == 'REMOVE':
                    excluded.remove(self.index)
                else:
                    have = {entry.name for entry in excluded}
                    for bone in selected_bones(rig_for_chain(context)):
                        if bone.name not in have:
                            excluded.add().name = bone.name
                return {'FINISHED'}

        return item, settings, MakeGroup, Exclude

    # -- state --------------------------------------------------------------

    def register(self):
        for cls in self.classes:
            bpy.utils.register_class(cls)
        setattr(bpy.types.Scene, self.prop, PointerProperty(type=self.classes[1]))

    def unregister(self):
        delattr(bpy.types.Scene, self.prop)
        for cls in reversed(self.classes):
            bpy.utils.unregister_class(cls)

    def settings(self, context):
        return getattr(context.scene, self.prop)

    def excluded_names(self, context):
        return [entry.name for entry in self.settings(context).excluded]

    # -- the work -----------------------------------------------------------

    def chain_roots(self, context, rig):
        """The root bones: the chosen Root Bone, else the selected bones that are not excluded."""
        settings = self.settings(context)
        if settings.root_bone:
            picked = rig.data.bones.get(settings.root_bone)
            return [picked] if picked else []
        left_out = set(self.excluded_names(context))
        return [bone for bone in selected_bones(rig) if bone.name not in left_out]

    def make_group(self, context):
        """Write the group. Returns (message, done)."""
        settings, rig = self.settings(context), rig_for_chain(context)
        if settings.root_bone and settings.root_bone not in rig.data.bones:
            return f"{rig.name} has no bone '{settings.root_bone}'", False
        roots = self.chain_roots(context, rig)
        if not roots:
            return "Pick a root bone, or select bones in Pose Mode", False
        names = chain_bone_names(rig, roots, self.excluded_names(context), settings.exclude_children)
        meshes = deformed_meshes(context, rig)
        if not meshes:
            return f"No mesh deformed by {rig.name}", False
        parts = []
        for ob in meshes:
            touched, full = write_chain_group(ob, names, settings.group_name)
            parts.append(f"{ob.name}: {touched} verts weighted, {full} at 1")
        return f"'{settings.group_name}' from {len(names)} bones. " + "; ".join(parts), True

    def summary(self, context):
        """"Tail 1 → Tail 5" (the chain the tool would use), "no rig" or "" for a header summary."""
        rig = rig_for_chain(context)
        if rig is None:
            return "no rig"
        roots = self.chain_roots(context, rig)
        if not roots:
            return ""
        path = chain_path(rig, roots[0].name)
        text = f"{friendly_name(path[0])} → {friendly_name(path[-1])}" if len(path) > 1 else friendly_name(path[0])
        return text[:SUMMARY_CHARS]

    # -- drawing ------------------------------------------------------------

    def draw_body(self, layout, context):
        """Status, the big button, the Chain section (group name, root bone) and the Excluded Bones section."""
        settings, rig = self.settings(context), rig_for_chain(context)
        status(layout, "Vertex group from a bone chain" if rig else "No rig found", icon='GROUP_BONE' if rig else 'INFO')
        action_row(layout).operator(self.make_operator_id, text=BUTTON_TEXT, icon='GROUP_VERTEX')
        hints(layout, [] if rig else ["Select a rig or a mesh it deforms"], context)
        chain = section(layout, f"{self.package}_chain_group", "Chain", icon='BONE_DATA')
        if chain:
            col = prop_group(chain, settings, [("group_name", "Group")])
            if rig is not None:
                col.prop_search(settings, "root_bone", rig.data, "bones", text="Root Bone")
        count = len(settings.excluded)
        left_out = section(layout, f"{self.package}_chain_excluded", "Excluded Bones", icon='X', default_closed=not count,
                           right=f"{count} bone{'' if count == 1 else 's'}" if count else "none")
        if left_out and rig is not None:
            self.draw_excluded(left_out, settings, rig)
        elif left_out:
            hints(left_out, ["Select a rig first"], context)

    def draw_excluded(self, layout, settings, rig):
        for index, entry in enumerate(settings.excluded):
            row = layout.row(align=True)
            row.prop_search(entry, "name", rig.data, "bones", text="")
            op = row.operator(self.exclude_operator_id, text="", icon='X')
            op.action, op.index = 'REMOVE', index
        buttons = layout.row(align=True)
        buttons.operator(self.exclude_operator_id, text="Add Selected", icon='ADD').action = 'ADD_SELECTED'
        buttons.operator(self.exclude_operator_id, text="Clear").action = 'CLEAR'
        flags = layout.column(align=True)
        flags.use_property_split = False
        flags.prop(settings, "exclude_children")
        hints(layout, ["Left out of the sum, e.g. the jaw for a head group"])
