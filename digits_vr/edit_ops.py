# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode actions with no UI yet (the desk's Edit tools page waits for a mock-up): each is one function the
page / the PDA can call later, and each is ONE undo step, or none when nothing changed."""
import bmesh

from . import edit_pick, edit_state, tools


def reveal(context):
    """Unhide every hidden vertex, edge and face (Alt+H; not selected, like Blender's `select=False`). True when
    something was hidden."""
    ob = context.edit_object
    if ob is None:
        return False
    bm = bmesh.from_edit_mesh(ob.data)
    hidden = [element for elements in (bm.verts, bm.edges, bm.faces) for element in elements if element.hide]
    if not hidden:
        return False
    for element in hidden:
        element.hide_set(False)
    bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=False)
    edit_state.STATE.stale = True              # hide flags are not in our key: rebuild at the next tick
    return True


def reveal_action(context):
    """Reveal + its undo step. False (nothing pushed) when Edit mode refuses the mesh or nothing was hidden."""
    if edit_pick.refused(context) or not reveal(context):
        return False
    tools.push_undo("VR Reveal")
    return True
