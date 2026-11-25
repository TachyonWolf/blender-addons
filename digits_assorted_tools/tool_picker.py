# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/tool_picker.py and run
# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't
# import the shared folder).
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sidebar's tool dropdown, shared by Digit's Assorted Tools (Tools panel) and Digit's Processes: one menu button
that opens a multi-column menu (category headings with an icon, rows with their own icon, type to search); a row
click stores the choice in a WindowManager enum property, and the panel draws the chosen card under the button.

    PICKER = ToolPicker(operator_idname="myaddon.pick_tool", menu_idname="MYADDON_MT_tools", menu_label="Tools",
                        property_name="my_tool", entries=lambda: [(category, label), ...] in menu order,
                        icon=lambda label: 'ICON', category_icons={"Category": 'ICON'})
    PICKER.draw_dropdown(layout, context.window_manager.my_tool)       # in the panel's draw
    classes = (*PICKER.classes, ...)                                   # register them
    bpy.types.WindowManager.my_tool = EnumProperty(items=enum_items(entries), ...)

Optional: `text(label)` = the row text (default the label), `description(tool_id)` = the row tooltip. This file is
the ONE source; sync_shared.py copies it into each extension folder."""
import bpy
from bpy.props import StringProperty

MENU_COLUMNS = 4


def tool_id(label):
    """The enum identifier of a tool label ("Camera Rig" -> "CAMERA_RIG")."""
    return label.upper().replace(" ", "_")


def enum_items(entries):
    """Enum items for the property: an empty identifier is a heading, so each category is one, its tools under it.
    `entries` = [(category, label)] in menu order."""
    items, last = [], None
    for category, label in entries:
        if category != last:
            items.append(("", category, ""))
            last = category
        items.append((tool_id(label), label, f"{label} ({category})"))
    return items


def group_by_category(entries):
    """[(category, [labels])] from [(category, label)] in menu order."""
    groups = []
    for category, label in entries:
        if not groups or groups[-1][0] != category:
            groups.append((category, []))
        groups[-1][1].append(label)
    return groups


def split_into_columns(groups, columns=MENU_COLUMNS):
    """Cut the category list (kept in order) into at most `columns` runs, keeping the tallest column as short
    as it can be. A category's height is its tools plus a line for its heading."""
    heights = [len(labels) + 1 for _, labels in groups]

    def runs_needed(limit):
        runs, height = 1, 0
        for group_height in heights:
            if height and height + group_height > limit:
                runs, height = runs + 1, 0
            height += group_height
        return runs

    limit = max(heights)
    while runs_needed(limit) > columns:
        limit += 1
    result, height = [[]], 0
    for group, group_height in zip(groups, heights):
        if height and height + group_height > limit:
            result.append([])
            height = 0
        result[-1].append(group)
        height += group_height
    return result


class ToolPicker:
    """Builds the pick operator and the dropdown menu of one add-on's tool list (see the module docstring)."""

    def __init__(self, operator_idname, menu_idname, menu_label, property_name, entries, icon, category_icons,
                 text=None, description=None, operator_doc="Show this tool in the panel"):
        self.operator_idname = operator_idname
        self.property_name = property_name
        self.entries = entries
        self.icon = icon
        self.category_icons = category_icons
        self.text = text or (lambda label: label)
        self.description = description or (lambda tool: "")
        picker = self

        def execute(operator, context):
            if picker.label_of(operator.tool):
                setattr(context.window_manager, picker.property_name, operator.tool)
            return {'FINISHED'}

        def describe(cls, context, properties):
            return picker.description(properties.tool)

        def draw(menu, context):
            picker.draw_menu(menu.layout)

        self.pick_operator = type(f"{menu_idname.split('_MT_')[0]}_OT_pick_tool", (bpy.types.Operator,), {
            "__doc__": operator_doc, "bl_idname": operator_idname, "bl_label": "Pick Tool",
            "bl_options": {'INTERNAL'}, "__annotations__": {"tool": StringProperty(options={'SKIP_SAVE'})},
            "description": classmethod(describe), "execute": execute})
        self.menu = type(menu_idname, (bpy.types.Menu,), {
            "__doc__": "One column per few categories (like Blender's Add Modifier menu), each under an icon heading.",
            "bl_label": menu_label, "bl_idname": menu_idname, "bl_options": {'SEARCH_ON_KEY_PRESS'}, "draw": draw})
        self.classes = (self.pick_operator, self.menu)

    def label_of(self, tool):
        """The label of the tool with this identifier ('' when unknown)."""
        return next((label for _, label in self.entries() if tool_id(label) == tool), "")

    def by_category(self):
        return group_by_category(self.entries())

    def draw_menu(self, layout):
        row = layout.row()
        for column_groups in split_into_columns(self.by_category()):
            column = row.column()
            for index, (category, labels) in enumerate(column_groups):
                if index:
                    column.separator()
                column.label(text=category, icon=self.category_icons.get(category, 'NONE'))
                column.separator(type='LINE')
                for label in labels:
                    pick = column.operator(self.operator_idname, text=self.text(label), icon=self.icon(label))
                    pick.tool = tool_id(label)

    def draw_dropdown(self, layout, chosen):
        """The dropdown button: the chosen tool's icon and name, opening the menu."""
        label = self.label_of(chosen)
        if label:
            layout.menu(self.menu.bl_idname, text=self.text(label), icon=self.icon(label))
