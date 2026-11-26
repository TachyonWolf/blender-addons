# SPDX-License-Identifier: GPL-3.0-or-later
"""Selection in Edit mode for the select tool: replace / toggle / clear of one vertex, edge or face (Blender's own
select mode decides which; the desktop can change it too) on the live edit bmesh, fetched fresh and never kept.
Returns whether the selection really changed, so a tap that changes nothing pushes no undo step."""
import bmesh
import numpy as np

from . import edit_math, edit_state, router


def selection_mask(bm, kind=edit_math.VERT):
    """Selected flags of the vertices (default), edges or faces: what `kind` selecting is defined by."""
    elements = bm.verts if kind == edit_math.VERT else bm.edges if kind == edit_math.EDGE else bm.faces
    return np.fromiter((element.select for element in elements), bool, len(elements))


def deselect_all(bm):
    """Every vertex, edge and face unselected (deselecting vertices alone leaves edge and face flags behind)."""
    for elements in (bm.faces, bm.edges, bm.verts):
        for element in elements:
            if element.select:
                element.select_set(False)


def live_bmesh(context, name):
    """The edit bmesh of object `name` if it is the one cached (and Edit mode works for it), else None."""
    state = edit_state.STATE
    ob = context.edit_object
    if ob is None or not state.ready or state.object_name != name or ob.name_full != name:
        return None
    bm = bmesh.from_edit_mesh(ob.data)
    if len(bm.verts) != len(state.coords):
        return None
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return bm


def apply(context, target, outcome, bm=None):
    """router REPLACE / TOGGLE / CLEAR for `target` (None for CLEAR). True when the selection changed. `bm`: a bmesh
    the caller holds (a tool drag, whose caches are not yet those of this mesh)."""
    name = target.object_name if target else edit_state.STATE.object_name
    bm = bm or live_bmesh(context, name)
    if bm is None:
        return False
    kind = target.element if target else edit_state.select_kind(context)
    before = selection_mask(bm, kind)
    if outcome in (router.CLEAR, router.REPLACE):
        deselect_all(bm)
    if target is not None and outcome in (router.REPLACE, router.TOGGLE):
        elements = bm.verts if kind == edit_math.VERT else bm.edges if kind == edit_math.EDGE else bm.faces
        elements[target.index].select_set(not before[target.index] if outcome == router.TOGGLE else True)
    bm.select_flush_mode()
    changed = not np.array_equal(before, selection_mask(bm, kind))
    if changed:
        bmesh.update_edit_mesh(context.edit_object.data, loop_triangles=False, destructive=False)
    return changed
