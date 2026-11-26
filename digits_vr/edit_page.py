# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit mode's tool rows, bpy side: the select mode (Vert / Edge / Face), the active tool with its settings, and the tools
done at once (Merge, Delete, Fill, Reveal; Reveal dims when nothing is hidden). The rows: tool_rows.py."""
import bmesh
import bpy

from . import edit_actions, edit_ops, edit_state, edit_tool_settings, settings
from .context_helper import run_in_view3d
from .tool_rows import EditView

SCAN_LIMIT = 100_000            # faces: a bigger mesh is not scanned for hidden parts on every desk rebuild (Reveal stays on)


def _has_hidden(context):
    ob = context.edit_object
    if ob is None or len(ob.data.polygons) > SCAN_LIMIT:
        return True
    bm = bmesh.from_edit_mesh(ob.data)
    return any(element.hide for elements in (bm.verts, bm.edges, bm.faces) for element in elements)


def key(context):
    """What the rows show besides settings (tool_actions.key has those)."""
    ob = context.edit_object
    return (ob.name_full if ob else None, tuple(context.tool_settings.mesh_select_mode), edit_state.STATE.reason)


def view(context):
    tool = settings.get("edit_tool")
    chosen = dict(tool=tool, grip_target=settings.get("grip_target"), values=tuple(edit_tool_settings.values(tool, settings.get).items()))
    if context.edit_object is None or context.edit_object.type != 'MESH':
        return EditView(note="Edit mode needs a mesh", **chosen)
    edit_state.sync(context)
    reason = edit_state.STATE.reason
    return EditView(select=edit_state.select_kind(context), hidden=_has_hidden(context), note=reason, warn=bool(reason),
                    usable=not reason, **chosen)


def set_select(context, kind):
    if edit_actions.busy():
        return False
    return run_in_view3d(context, lambda: bpy.ops.mesh.select_mode(type=kind))


def run_tool(context, name):
    if edit_actions.busy():
        return False
    if name == "reveal":
        return edit_ops.reveal_action(context)
    tool = edit_actions.TOOLS.get(name)
    return bool(tool and tool(context))
