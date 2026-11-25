#!/usr/bin/env python3
"""Copy the shared add-on source files into every extension folder that uses them.

Run (also done by Addons/package.sh) after editing a file in this folder:
  python3 sync_shared.py
Each copy gets a "generated copy" header; never edit the copies.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ADDONS = os.path.dirname(HERE)
SCRIPTS = os.path.join(os.path.dirname(ADDONS), "Scripts")
# extension folder -> its parent folder (default Addons/; batch_tools is a script folder)
FOLDERS = {"batch_tools": SCRIPTS, "Scripts": os.path.dirname(SCRIPTS)}   # "Scripts" = the Scripts folder itself
TARGETS = {"local_defaults.py": ("batch_tools", "digits_assorted_tools", "render_presets", "digits_vr"),
           "asset_libraries.py": ("digits_modifiers", "digits_assorted_tools"),
           "character_link.py": ("Scripts", "digits_assorted_tools", "digits_vr"),
           "compositor_common.py": ("Scripts", "digits_assorted_tools"),
           "bone_chain.py": ("digits_modifiers", "digits_assorted_tools", "render_presets"),
           "modifier_setup.py": ("digits_modifiers", "digits_assorted_tools", "render_presets"),
           "bone_chain_ui.py": ("digits_modifiers", "digits_assorted_tools"),
           "selected_ui.py": ("digits_assorted_tools", "digits_modifiers"),
           "tool_picker.py": ("digits_assorted_tools", "digits_processes"),
           "ui_cards.py": ("digits_assorted_tools", "digits_modifiers", "render_presets", "digits_processes", "digits_vr"),
           "viewport_modifiers.py": ("digits_assorted_tools", "digits_vr"),
           "scene_record.py": ("digits_vr",),
           "render_settings.py": ("render_presets", "batch_tools", "digits_assorted_tools"),
           "chain_weights.py": ("batch_tools", "digits_assorted_tools"),
           "bone_collections.py": ("batch_tools", "digits_assorted_tools"),
           "face_rig_core.py": ("batch_tools", "digits_assorted_tools"),
           "widget_meshes.py": ("batch_tools", "digits_assorted_tools"),
           "look_rig.py": ("batch_tools", "digits_assorted_tools"),
           "span_bones.py": ("batch_tools", "digits_assorted_tools"),
           "lid_bbone_ring.py": ("batch_tools", "digits_assorted_tools"),
           "limb_rig.py": ("batch_tools", "digits_assorted_tools"),
           "rig_names.py": ("batch_tools", "digits_assorted_tools"),
           "rig_rename.py": ("batch_tools", "digits_assorted_tools"),
           "game_rig.py": ("batch_tools", "digits_assorted_tools"),
           "mesh_reduce.py": ("digits_assorted_tools",),
           "combine_bones.py": ("digits_assorted_tools",),
           "weight_cleanup.py": ("digits_assorted_tools",),
           "full_rig_spec.py": ("batch_tools", "digits_assorted_tools"),
           "body_rig.py": ("batch_tools", "digits_assorted_tools"),
           "bendy_limbs.py": ("batch_tools", "digits_assorted_tools"),
           "part_chains.py": ("batch_tools", "digits_assorted_tools"),
           "wing_rig.py": ("batch_tools", "digits_assorted_tools"),
           "wing_membrane.py": ("batch_tools", "digits_assorted_tools"),
           "fin_rig.py": ("batch_tools", "digits_assorted_tools"),
           "bbone_builder.py": ("batch_tools", "digits_assorted_tools"),   # game_rig needs it
           "rig_component.py": ("batch_tools", "digits_assorted_tools"),
           "full_rig.py": ("batch_tools", "digits_assorted_tools"),
           "rig_weights.py": ("batch_tools", "digits_assorted_tools"),
           "mesh_review.py": ("digits_assorted_tools",),
           "deform_metrics.py": ("batch_tools", "digits_assorted_tools"),
           "scene_checks.py": ("digits_assorted_tools",),
           "modifier_order.py": ("digits_assorted_tools",),
           "texture_space_fix.py": ("digits_assorted_tools",),
           "linked_modifiers.py": ("digits_assorted_tools",),
           "instance_array.py": ("digits_assorted_tools",),
           "driver_scan.py": ("digits_assorted_tools",),
           "rig_parts.py": ("digits_assorted_tools",),
           "rig_page.py": ("digits_assorted_tools",),
           "rig_switches_ui.py": ("digits_assorted_tools",),
           "view_ray.py": ("digits_assorted_tools", "render_presets"),
           "uv_rebake.py": ("digits_assorted_tools",),
           "toony_ui.py": ("digits_assorted_tools", "digits_modifiers")}  # file -> extension folders


def header(name):
    return (f"# GENERATED COPY, do not edit. Edit the source at Addons/shared_addon/{name} and run\n"
            "# Addons/shared_addon/sync_shared.py (the extension is installed as a copy, so it can't\n"
            "# import the shared folder).\n")


def main():
    for name, folders in TARGETS.items():
        with open(os.path.join(HERE, name)) as f:
            source = f.read()
        for folder in folders:
            if not os.path.isdir(os.path.join(FOLDERS.get(folder, ADDONS), folder)):
                # a git worktree has no Scripts/ (it is outside the repo): skip, don't crash
                print("skipped", folder + "/" + name, "(folder missing, e.g. in a worktree)")
                continue
            with open(os.path.join(FOLDERS.get(folder, ADDONS), folder, name), "w") as f:
                f.write(header(name) + source)
            print("synced", folder + "/" + name)


if __name__ == "__main__":
    main()
