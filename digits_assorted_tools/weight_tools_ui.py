# SPDX-License-Identifier: GPL-3.0-or-later
"""Weights tools (Digit's Tools > Weights): Remove Disconnected Islands (click a vertex on the part to keep; the rest of
the active vertex group is removed or moved) and Merge Vertex Groups (other groups join the active one). All logic is in
weight_cleanup (generated copy of Addons/shared_addon/weight_cleanup.py); this file is the settings, operators and cards.
Nothing runs in the background and the cards do no mesh work: counts come from the click, not from drawing."""
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import weight_cleanup as wc  # generated copy
from .rig_placement import PickOperator
from .ui_cards import action_row, choice_row, hints, prop_group, section, status  # generated copy

ISLAND_NAME = "Remove Disconnected Islands"
MERGE_NAME = "Merge Vertex Groups"
THRESHOLD_HELP = ("Weight at or above which a vertex counts as part of the part you click. The part is every vertex "
                  "connected to your click through such vertices. Raise it to cut at a thin, faint bridge; lower it to "
                  "keep faint weight")
PICK_TEXT = "Click a vertex on the part to keep  ·  Esc / Right-click: cancel"
ACTIONS = (("NORMALIZE", "Remove and Normalize", "Take the rest out of the group; its weight goes to the vertex's other "
            "deform groups so it still sums to 1"),
           ("MOVE", "Move to New Group", "Move the rest into a new group named '<group> Spill'"))


def weight_mesh(context, need_mode=True):
    """The active mesh object if it is in Weight Paint mode (or any non-Edit mode when need_mode is False), else None."""
    ob = context.active_object
    if ob is None or ob.type != 'MESH':
        return None
    ok = context.mode == 'PAINT_WEIGHT' if need_mode else not context.mode.startswith('EDIT')
    return ob if ok else None


def active_group(ob):
    return ob.vertex_groups.active if ob is not None else None


def why_not(context, need_mode=True):
    """The hint for a disabled button, or "" when the tool can run."""
    ob = weight_mesh(context, need_mode)
    if ob is None:
        return "Select a mesh and go to Weight Paint Mode" if need_mode else "Select a mesh (not in Edit Mode)"
    if active_group(ob) is None:
        return "Make a vertex group active first"
    return ""


class MergeEntry(bpy.types.PropertyGroup):
    name: StringProperty(name="Group", description="A vertex group to merge into the active one")


class WeightToolsSettings(bpy.types.PropertyGroup):
    threshold: FloatProperty(name="Threshold", default=wc.DEFAULT_THRESHOLD, min=0.0, max=1.0, precision=2,
                             description=THRESHOLD_HELP)
    result: StringProperty(options={'HIDDEN'})       # last island result, for the status line
    result_for: StringProperty(options={'HIDDEN'})   # "object/group" it belongs to
    merge_mode: EnumProperty(name="Combine", items=(("ADD", "Add", "Add the weights, at most 1"),
                                                    ("MAX", "Max", "Keep the larger weight of each pair")), default="ADD")
    remove_merged: BoolProperty(name="Remove Merged Groups", default=True,
                                description="Delete the merged groups afterwards")
    normalise: BoolProperty(name="Normalize Result", default=False,
                            description="Scale each changed vertex's deform weights to sum to 1")
    merge_list: CollectionProperty(type=MergeEntry)


def settings(context):
    return context.scene.weight_tools


def result_key(ob, group):
    return f"{ob.name}/{group.name}"


# ---------------------------------------------------------------- the work
def run_island(context, ob, seed, action, threshold):
    """Split the active group around vertex `seed` and apply `action`. Returns (message, ok)."""
    group = active_group(ob)
    keep, spill = wc.split_island(ob, group.name, seed, threshold)
    if not keep:
        return f"That vertex has less than {threshold:.2f} weight in '{group.name}': click a stronger one", False
    note = ""
    if not spill:
        done = 0
    elif action == 'MOVE':
        done, name = wc.move_to_new_group(ob, group.name, spill)
        note = f" · moved to '{name}'"
    else:
        done, left = wc.remove_and_normalize(ob, group.name, spill)
        note = f" · {left} left (no other deform group)" if left else ""
    ob.data.update()
    text = wc.status_text(len(keep), len(spill) if action == 'MOVE' else done) + note
    s = settings(context)
    s.result, s.result_for = text, result_key(ob, group)
    return (text if spill else text + " · nothing to remove"), True


class WEIGHTS_OT_remove_islands(PickOperator, bpy.types.Operator):
    """Click a vertex on the part of the active vertex group to keep; weight not connected to it (through vertices at or
    above the Threshold) is removed"""
    bl_idname = "chartools.remove_islands"
    bl_label = ISLAND_NAME
    bl_options = {'REGISTER', 'UNDO'}
    pick_help = PICK_TEXT

    action: EnumProperty(items=ACTIONS, default='NORMALIZE', options={'SKIP_SAVE'})
    vertex: IntProperty(default=-1, options={'SKIP_SAVE'}, description="Script use: skip the click and use this vertex")

    @classmethod
    def poll(cls, context):
        return not why_not(context)

    @classmethod
    def description(cls, context, properties):
        text = {a[0]: a[2] for a in ACTIONS}[properties.action]
        return f"Click a vertex on the part to keep. {text}"

    def execute(self, context):
        if self.vertex >= 0:
            return self.finish(context, self.vertex)
        return super().execute(context)

    def picked(self, context, view):
        ob = weight_mesh(context)
        if ob is None:
            return {'CANCELLED'}
        seed = self.vertex_under(context, ob, view)
        if seed is None:
            self.report({'WARNING'}, "No vertex under the mouse: click on the mesh")
            return {'CANCELLED'}
        return self.finish(context, seed)

    def vertex_under(self, context, ob, view):
        """Original vertex index nearest to the mesh point under the click ray (None: the ray missed `ob`)."""
        depsgraph = context.evaluated_depsgraph_get()
        hit, location, _n, face, hit_ob, _m = context.scene.ray_cast(depsgraph, view.eye, view.forward)
        if not hit or hit_ob.original != ob:
            return None
        evaluated = hit_ob.evaluated_get(depsgraph)   # ray_cast's object is evaluated; its to_mesh() carries the modifiers
        mesh = evaluated.to_mesh()
        try:
            if wc.topology_changed(ob, mesh):
                self.report({'INFO'}, "Modifiers change the mesh shape: using the nearest base-mesh vertex")
            return wc.vertex_from_hit(ob, mesh, face, ob.matrix_world.inverted() @ location)
        finally:
            evaluated.to_mesh_clear()

    def finish(self, context, seed):
        ob = weight_mesh(context)
        if ob is None or not 0 <= seed < len(ob.data.vertices):
            return {'CANCELLED'}
        message, ok = run_island(context, ob, seed, self.action, settings(context).threshold)
        self.report({'INFO' if ok else 'WARNING'}, message)
        return {'FINISHED' if ok else 'CANCELLED'}


class WEIGHTS_OT_merge_groups(bpy.types.Operator):
    """Add the listed vertex groups' weights to the active group"""
    bl_idname = "chartools.merge_vertex_groups"
    bl_label = MERGE_NAME
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return not why_not(context, need_mode=False) and any(e.name for e in settings(context).merge_list)

    def execute(self, context):
        ob, s = weight_mesh(context, need_mode=False), settings(context)
        target = active_group(ob).name
        names = [e.name for e in s.merge_list if e.name in ob.vertex_groups and e.name != target]
        if not names:
            self.report({'WARNING'}, "Pick at least one other group to merge")
            return {'CANCELLED'}
        moved = wc.merge_groups(ob, target, names, s.merge_mode, s.remove_merged, s.normalise)
        ob.data.update()
        if s.remove_merged:
            s.merge_list.clear()
        self.report({'INFO'}, f"Merged {len(names)} group{'' if len(names) == 1 else 's'} into '{target}': {moved} vertices changed")
        return {'FINISHED'}


class WEIGHTS_OT_merge_list(bpy.types.Operator):
    """Change the list of groups to merge"""
    bl_idname = "chartools.merge_list"
    bl_label = "Groups to Merge"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(("ADD", "Add", "Add a row"), ("CLEAR", "Clear", "Empty the list"),
                                ("REMOVE", "Remove", "Take this row off")), options={'HIDDEN'})
    index: IntProperty(options={'HIDDEN'})

    def execute(self, context):
        rows = settings(context).merge_list
        if self.action == 'CLEAR':
            rows.clear()
        elif self.action == 'REMOVE':
            rows.remove(self.index)
        else:
            rows.add()
        return {'FINISHED'}


# ---------------------------------------------------------------- cards
def draw_island_card(layout, context):
    """Status first, the two action buttons, then the Threshold section."""
    s, hint = settings(context), why_not(context)
    ob = weight_mesh(context)
    group = active_group(ob) if ob else None
    if hint:
        status(layout, "Needs a mesh in Weight Paint Mode", icon='INFO')
    elif s.result and s.result_for == result_key(ob, group):
        status(layout, s.result, icon='CHECKMARK')
    else:
        status(layout, f"Group: {group.name}", icon='GROUP_VERTEX')
    for key, label, _tip in ACTIONS:
        op = action_row(layout).operator(WEIGHTS_OT_remove_islands.bl_idname, text=label, icon='GROUP_VERTEX' if key == 'MOVE' else 'X')
        op.action = key
    hints(layout, [hint] if hint else ["Click a vertex on the part to keep"], context)
    box = section(layout, "weights_island_options", "Island", icon='MOD_MASK', right=f"at {s.threshold:.2f}")
    if box:
        prop_group(box, s, ["threshold"])
        hints(box, ["Weight needed to count as connected"], context)


def draw_merge_card(layout, context):
    """Status first, the merge button, the Groups to Merge section and the Options section."""
    s, hint = settings(context), why_not(context, need_mode=False)
    ob = weight_mesh(context, need_mode=False)
    target = active_group(ob) if ob else None
    status(layout, f"Into: {target.name}" if target else "Needs a mesh with a vertex group",
           icon='GROUP_VERTEX' if target else 'INFO')
    action_row(layout).operator(WEIGHTS_OT_merge_groups.bl_idname, text="Merge Into Active Group", icon='AUTOMERGE_ON')
    hints(layout, [hint] if hint else (["Add the groups to merge below"] if not s.merge_list else []), context)
    count = len([e for e in s.merge_list if e.name])
    rows = section(layout, "weights_merge_list", "Groups to Merge", icon='GROUP_VERTEX',
                   right=f"{count} group{'' if count == 1 else 's'}" if count else "none")
    if rows:
        for index, entry in enumerate(s.merge_list):
            row = rows.row(align=True)
            if ob is not None:
                row.prop_search(entry, "name", ob, "vertex_groups", text="")
            else:
                row.label(text=entry.name)
            op = row.operator(WEIGHTS_OT_merge_list.bl_idname, text="", icon='X')
            op.action, op.index = 'REMOVE', index
        buttons = rows.row(align=True)
        buttons.operator(WEIGHTS_OT_merge_list.bl_idname, text="Add", icon='ADD').action = 'ADD'
        buttons.operator(WEIGHTS_OT_merge_list.bl_idname, text="Clear").action = 'CLEAR'
    opts = section(layout, "weights_merge_options", "Options", icon='PREFERENCES',
                   right=f"{s.merge_mode.title()}{', keep' if not s.remove_merged else ''}")
    if opts:
        choice_row(opts, s, "merge_mode", label="Combine")
        prop_group(opts, s, ["remove_merged", "normalise"], split=False)


classes = (MergeEntry, WeightToolsSettings, WEIGHTS_OT_remove_islands, WEIGHTS_OT_merge_groups, WEIGHTS_OT_merge_list)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.weight_tools = PointerProperty(type=WeightToolsSettings)


def unregister():
    del bpy.types.Scene.weight_tools
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
