"""The Tools panel's dropdown: a menu with the tool icon on every row and the skill badge (★ / ◆) after the name, plus the badge legend.
The menu and pick operator come from the shared `tool_picker.py` (also used by Digit's Processes); this module adds the badges.
The tool table itself (`TOOLS`, `TOOL_LOOKS`) lives in the package `__init__`; this module reads it when drawing."""
import importlib

import bpy
from bpy.props import StringProperty

from .tool_picker import MENU_COLUMNS, ToolPicker, split_into_columns, tool_id  # generated copy  # noqa: F401

BEGINNER, EXPERT = 'BEGINNER', 'EXPERT'
SKILL_MARKS = {BEGINNER: "★", EXPERT: "◆"}   # text marks: a menu row holds one icon, the tool's own
SKILL_NAMES = {BEGINNER: "Beginner friendly", EXPERT: "Expert"}
SKILL_TOOLTIPS = {
    BEGINNER: "Beginner friendly: one click gives a good result. Safe to try.",
    EXPERT: "Expert tool: needs rigging, driver or export know-how. Read the tooltips before you use it.",
}


def package():
    return importlib.import_module(__package__)   # lazy: the package imports this module


def tool_icon(label):
    return package().TOOL_LOOKS[label][0]


def tool_skill(label):
    return package().TOOL_LOOKS[label][1]


def tool_text(label):
    """The tool's name with its skill mark after it ("Camera Rig  ★"), or just the name."""
    skill = tool_skill(label)
    return f"{label}  {SKILL_MARKS[skill]}" if skill else label


class CHARTOOLS_OT_skill_badge(bpy.types.Operator):
    """Legend item: shows what a skill badge means (does nothing when clicked)"""
    bl_idname = "chartools.skill_badge"
    bl_label = "Skill Badge"
    bl_options = {'INTERNAL'}

    skill: StringProperty(options={'SKIP_SAVE'})
    tool: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return SKILL_TOOLTIPS.get(properties.skill, "")

    def execute(self, context):
        if PICKER.label_of(self.tool):
            context.window_manager.digit_tool = self.tool
        return {'FINISHED'}


# Each category heading's icon, so the headings stand out from the tool rows.
CATEGORY_ICONS = {"Character Rigs": 'ARMATURE_DATA', "Check": 'CHECKMARK', "Convert": 'FILE_REFRESH', "Export": 'EXPORT',
                  "Object": 'OBJECT_DATA', "Scene": 'SCENE_DATA', "Setups": 'LIGHT', "Texture": 'TEXTURE', "Weights": 'MOD_VERTEX_WEIGHT'}


def draw_legend(layout):
    """One compact row saying what the badges mean; hovering an item shows the badge's tooltip."""
    row = layout.row()
    row.alignment = 'LEFT'
    for skill in (BEGINNER, EXPERT):
        legend_item = row.operator(CHARTOOLS_OT_skill_badge.bl_idname, text=f"{SKILL_MARKS[skill]} {SKILL_NAMES[skill]}",
                                   emboss=False)
        legend_item.skill = skill
        row.separator(factor=2)


def tool_description(tool):
    """The row tooltip: the tool and its category, then what its skill badge means."""
    for category, label, _ in package().TOOLS:
        if tool_id(label) == tool:
            skill_line = SKILL_TOOLTIPS.get(tool_skill(label))
            return f"{label} ({category})" + (f"\n{skill_line}" if skill_line else "")
    return ""


PICKER = ToolPicker(
    operator_idname="chartools.pick_tool", menu_idname="CHARTOOLS_MT_tools", menu_label="Tools", property_name="digit_tool",
    entries=lambda: [(category, label) for category, label, _ in package().sorted_tools()],
    icon=tool_icon, text=tool_text, description=tool_description, category_icons=CATEGORY_ICONS,
    operator_doc="Show this tool in the Tools panel")
tool_label = PICKER.label_of
tools_by_category = PICKER.by_category
draw_dropdown = PICKER.draw_dropdown
CHARTOOLS_OT_pick_tool, CHARTOOLS_MT_tools = PICKER.classes

classes = (*PICKER.classes, CHARTOOLS_OT_skill_badge)
