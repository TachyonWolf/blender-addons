# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit's Modifiers: the Toony Modifiers (Geometry Nodes assets, bundled in `assets/` and offered as
the asset library "Digit's Modifiers") plus the Modifier Setup Helper and the combined weight group tool.

Setup Helper: one click adds a modifier to the active object and creates the helper objects it needs
(empties, lattice, curves, plates, rollers...) at sensible places and sizes from the object's bounds
(and bones), wired into the modifier's inputs, named clearly, and selected so the control can be
grabbed right away. Every recipe is a row of the table in recipes.py (with its options); the sidebar tab
"Modifiers" (a dropdown + the chosen recipe's options + one Add button) and the Add Modifier menu
(Setup Helper; entries with options open a popup) both draw from it. modifier_cards.py is the Selected card.
bone_chain.py, bone_chain_ui.py, modifier_setup.py, selected_ui.py, toony_ui.py and ui_cards.py are generated copies of
Addons/shared_addon/ (run sync_shared.py).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from . import asset_library, bone_chain_ui, modifier_cards  # bone_chain_ui is a generated copy
from .bone_chain import rig_for_chain  # generated copy
from .helpers import SetupError, option_prop
from .recipes import (RECIPES, RECIPES_BY_KEY, SECTIONS, helper_description, option_values, re_rest, recipes_in, run_recipe,
                      taffy_owners)
from .ui_cards import (action_row, choice_row, enum_label, friendly_name, header_right, hints, section, setting_value, smart_prop,  # generated copy
                       status)


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class _Defaults:
    show_sidebar = True
    show_menu = True


def prefs(context):
    """The add-on's preferences (all on when it isn't enabled as an add-on, e.g. in tests)."""
    entry = context.preferences.addons.get(__package__)
    return entry.preferences if entry else _Defaults


class MODHELP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    show_sidebar: BoolProperty(name="Show sidebar tab", default=True,
                               description="Show the Modifiers tab in the 3D Viewport sidebar")
    show_menu: BoolProperty(name="Show in Add Modifier menu", default=True,
                            description="Show Setup Helper in the Add Modifier menu of the Properties editor")

    def draw(self, context):
        self.layout.prop(self, "show_sidebar")
        self.layout.prop(self, "show_menu")


# ---------------------------------------------------------------------------
# Recipe options: Scene properties made from the table, drawn by the sidebar and the popup
# ---------------------------------------------------------------------------

def _option_property(option):
    """The Scene property for one Option row."""
    if option.kind == 'enum':
        return EnumProperty(name=option.label, description=option.tip, items=option.items, default=option.default)
    if option.kind == 'bool':
        return BoolProperty(name=option.label, description=option.tip, default=option.default)
    if option.kind == 'int':
        return IntProperty(name=option.label, description=option.tip, default=option.default, min=option.min, max=option.max)
    return StringProperty(name=option.label, description=option.tip, default=option.default)  # 'bone'


def option_props():
    """{Scene property name: property} for every option of every recipe."""
    return {option_prop(recipe.key, option.key): _option_property(option)
            for recipe in RECIPES for option in recipe.options}


def draw_options(layout, context, recipe):
    """The recipe's options (nothing for a recipe without any)."""
    scene = context.scene
    layout.use_property_split, layout.use_property_decorate = True, False
    rig = rig_for_chain(context) if any(o.kind == 'bone' for o in recipe.options) else None
    if any(o.kind == 'bone' for o in recipe.options) and rig is None:
        layout.label(text="Select a rig or a mesh it deforms", icon='INFO')
    for option in recipe.options:
        prop = option_prop(recipe.key, option.key)
        if option.kind == 'bone':
            if rig is not None:
                layout.prop_search(scene, prop, rig.data, "bones", text=option.label)
        else:
            if option.kind == 'enum' and len(option.items) <= 4:
                choice_row(layout, scene, prop, label=option.label)
            else:
                smart_prop(layout, scene, prop)


# ---------------------------------------------------------------------------
# The one operator
# ---------------------------------------------------------------------------

class MODHELP_OT_add(bpy.types.Operator):
    bl_idname = "digits_modifiers.add"
    bl_label = "Add Modifier With Helpers"
    bl_options = {'REGISTER', 'UNDO'}

    recipe: StringProperty(name="Recipe", description="Key of the recipe in recipes.py")
    ask: BoolProperty(name="Ask", default=False, options={'SKIP_SAVE', 'HIDDEN'},
                      description="Open a popup with the recipe's options first (the Add Modifier menu does)")

    @classmethod
    def description(cls, context, properties):
        recipe = RECIPES_BY_KEY.get(properties.recipe)
        return recipe.tip if recipe else cls.__doc__ or ""

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def wants_popup(self):
        """True when this call should first show the options popup: asked for, and the recipe has options."""
        recipe = RECIPES_BY_KEY.get(self.recipe)
        return bool(self.ask and recipe and recipe.options)

    def invoke(self, context, event):
        if self.wants_popup():
            return context.window_manager.invoke_props_dialog(self, confirm_text="Add")
        return self.execute(context)

    def draw(self, context):
        recipe = RECIPES_BY_KEY[self.recipe]
        self.layout.label(text=recipe.label)
        draw_options(self.layout, context, recipe)

    def execute(self, context):
        recipe = RECIPES_BY_KEY.get(self.recipe)
        if recipe is None:
            self.report({'ERROR'}, f"Unknown recipe '{self.recipe}'")
            return {'CANCELLED'}
        try:
            _active, _selected, message = run_recipe(context, recipe, option_values(context.scene, recipe))
        except SetupError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, message)
        return {'FINISHED'}


class MODHELP_OT_taffy_re_rest(bpy.types.Operator):
    """Make the current pose the new unstretched start: snap each Taffy Pull rest empty to where its grab is now (grabs stay put). Works on the selected Taffy Pull object or its grab / rest empties"""
    bl_idname = "digits_modifiers.taffy_re_rest"
    bl_label = "Re-rest"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(taffy_owners(context))

    def execute(self, context):
        owners = taffy_owners(context)
        count = re_rest(context, owners)
        self.report({'INFO'}, f"Re-rested {count} Taffy Pull grab(s) on {', '.join(o.name for o in owners)}")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Sidebar tab: modifier dropdown, its options, one Add button, the bone chain tool
# ---------------------------------------------------------------------------

def recipe_items():
    """Dropdown items (id, label, tip, icon, number) grouped under a heading per section."""
    items = []
    for section, title in SECTIONS:
        items.append(("", title, ""))
        items.extend((r.key, r.label, r.tip, r.icon, RECIPES.index(r)) for r in recipes_in(section))
    return items


RECIPE_ITEMS = recipe_items()  # kept alive: Blender reads the list lazily
RECIPE_PROP = "modhelp_recipe"
CHAIN_TOOL = bone_chain_ui.BoneChainTool(__package__)   # the combined weight group tool (its operators and settings)


def draw_chain_body(layout, context):
    """The combined weight group tool (the panel header shows the chain it would use)."""
    CHAIN_TOOL.draw_body(layout, context)


def option_summary(scene, recipe):
    """The chosen option values in a few words for the Options header ("Medium · seed 0"); bone picks are left out."""
    parts = []
    for option in recipe.options:
        prop = option_prop(recipe.key, option.key)
        if option.kind == 'enum':
            parts.append(enum_label(scene, prop))
        elif option.kind != 'bone':
            parts.append(f"{option.label.lower()} {setting_value(scene, prop, getattr(scene, prop))}")
    return " · ".join(parts)[:24]


def helper_summary(recipe):
    """"1 empty" / "3 empties" / "2 helpers" for the Helpers It Makes header."""
    count = len(recipe.helpers)
    if {helper.kind for helper in recipe.helpers} == {'empty'}:
        return f"{count} empty" if count == 1 else f"{count} empties"
    return f"{count} helper" if count == 1 else f"{count} helpers"


def setup_status(recipe, active):
    """"Adds to Teapot · makes 1 helper"."""
    if not active:
        return "Select an object first"
    makes = len(recipe.helpers)
    return f"Adds to {friendly_name(active.name)}" + (f" · makes {makes} helper{'' if makes == 1 else 's'}" if makes else "")


def draw_setup_body(layout, context):
    """The Setup Helper panel body: the recipe dropdown, status, the big Add button, the Options section, Helpers It Makes
    (closed) and recipe Tools (closed)."""
    scene = context.scene
    recipe = RECIPES_BY_KEY[getattr(scene, RECIPE_PROP)]
    body = layout
    body.prop(scene, RECIPE_PROP, text="")
    active = context.active_object
    status(body, setup_status(recipe, active), icon=recipe.icon if active else 'INFO')
    op = action_row(body).operator(MODHELP_OT_add.bl_idname, text=f"Add {recipe.label}", icon=recipe.icon)
    op.recipe = recipe.key
    if recipe.options:
        sec = section(body, "modhelp_options", "Options", icon='PREFERENCES', right=option_summary(scene, recipe))
        if sec:
            draw_options(sec, context, recipe)
    if recipe.helpers:
        sec = section(body, "modhelp_helpers", "Helpers It Makes", icon='EMPTY_DATA', default_closed=True, right=helper_summary(recipe))
        if sec:
            for helper in recipe.helpers:
                status(sec, helper_description(helper), icon='DOT')
            hints(sec, [recipe.tip], context)
    if recipe.buttons:
        sec = section(body, "modhelp_buttons", "Tools", icon='TOOL_SETTINGS', default_closed=True)
        if sec:
            for idname, label, icon in recipe.buttons:
                sec.operator(idname, text=label, icon=icon)


class SidebarPanel:
    """What the three sidebar panels of the Modifiers tab share: the tab, and hiding it with the preference."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Modifiers"

    @classmethod
    def poll(cls, context):
        return prefs(context).show_sidebar


class MODHELP_PT_selected(SidebarPanel, bpy.types.Panel):
    bl_label = "Selected"
    bl_order = 0

    def draw_header_preset(self, context):
        header_right(self.layout, modifier_cards.header_summary(context))

    def draw(self, context):
        modifier_cards.draw_selected_body(self.layout, context)


class MODHELP_PT_setup(SidebarPanel, bpy.types.Panel):
    bl_label = "Setup Helper"
    bl_order = 1

    def draw(self, context):
        draw_setup_body(self.layout, context)


class MODHELP_PT_chain(SidebarPanel, bpy.types.Panel):
    bl_label = bone_chain_ui.DISPLAY_NAME
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header_preset(self, context):
        header_right(self.layout, CHAIN_TOOL.summary(context))

    def draw(self, context):
        draw_chain_body(self.layout, context)


PANELS = (MODHELP_PT_selected, MODHELP_PT_setup, MODHELP_PT_chain)


# ---------------------------------------------------------------------------
# Add Modifier menu (Properties editor): Setup Helper > Toony / Blender / Rig
# ---------------------------------------------------------------------------

def _draw_section_menu(self, context):
    for recipe in recipes_in(self.section):
        op = self.layout.operator(MODHELP_OT_add.bl_idname, text=recipe.label, icon=recipe.icon)
        op.recipe = recipe.key
        op.ask = True


def _section_menu(section, title):
    return type(f"MODHELP_MT_{section.lower()}", (bpy.types.Menu,),
                {"bl_label": title, "section": section, "draw": _draw_section_menu})


SECTION_MENUS = tuple(_section_menu(section, title) for section, title in SECTIONS)


class MODHELP_MT_setup(bpy.types.Menu):
    bl_label = "Setup Helper"

    def draw(self, context):
        for menu in SECTION_MENUS:
            self.layout.menu(menu.__name__)


def draw_in_add_modifier(self, context):
    if context.object and prefs(context).show_menu:
        self.layout.separator()
        self.layout.menu(MODHELP_MT_setup.__name__, icon='MODIFIER')


# ---------------------------------------------------------------------------

classes = (MODHELP_Preferences, MODHELP_OT_add, MODHELP_OT_taffy_re_rest, *modifier_cards.classes, *SECTION_MENUS, MODHELP_MT_setup,
           *PANELS)


def scene_props():
    """Every Scene property the extension adds."""
    return {RECIPE_PROP: EnumProperty(name="Modifier", items=RECIPE_ITEMS, default=RECIPES[0].key,
                                      description="The modifier to add, with the helper objects it needs"),
            **option_props()}


def register():
    for name, prop in scene_props().items():
        setattr(bpy.types.Scene, name, prop)
    CHAIN_TOOL.register()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.OBJECT_MT_modifier_add.append(draw_in_add_modifier)
    asset_library.add_library()


def unregister():
    asset_library.remove_library()
    bpy.types.OBJECT_MT_modifier_add.remove(draw_in_add_modifier)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    CHAIN_TOOL.unregister()
    for name in scene_props():
        delattr(bpy.types.Scene, name)
