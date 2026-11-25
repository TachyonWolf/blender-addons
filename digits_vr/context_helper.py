# SPDX-License-Identifier: GPL-3.0-or-later
"""The one way our code runs bpy.ops that need a 3D View: an override of window + area + WINDOW region (an override
with an area but no region can segfault Blender, spike C Q2). None when no 3D View is open anywhere (A22)."""


def view3d_override(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                region = next((region for region in area.regions if region.type == 'WINDOW'), None)
                if region:
                    return {"window": window, "area": area, "region": region}
    return None


def run_in_view3d(context, call):
    """Run `call()` inside the 3D View override. False when no 3D View is open (nothing ran)."""
    override = view3d_override(context)
    if override is None:
        return False
    with context.temp_override(**override):
        call()
    return True


def view3d_override_showing(context, ob):
    """The same override for the largest 3D View that shows `ob` (local view and hiding count). None when none does."""
    best = None
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D' or not ob.visible_in_viewport_get(area.spaces.active):
                continue
            region = next((region for region in area.regions if region.type == 'WINDOW'), None)
            if region and region.width * region.height > 1 and (best is None or region.width * region.height >
                                                                best["region"].width * best["region"].height):
                best = {"window": window, "area": area, "region": region}
    return best
