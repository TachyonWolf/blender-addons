# SPDX-License-Identifier: GPL-3.0-or-later
"""A copy of the mesh in Edit mode, to put it back EXACTLY while a tool drag runs (a cancel, or a setting that changed
mid-drag): coordinates, shape keys, weights, UVs, selection and hidden parts, with the same indices (measured headless
2026-11-25). One temporary mesh data-block without users, removed by close()."""
import bmesh
import bpy


class MeshSnapshot:
    def __init__(self, ob, bm):
        self.ob_name = ob.name_full
        copy = ob.data.copy()
        copy.name = "VR edit snapshot"
        self.mesh_name = copy.name
        self.key_index = ob.active_shape_key_index
        self.has_keys = ob.data.shape_keys is not None
        self.select_mode = set(bm.select_mode)
        self.active_face = bm.faces.active.index if bm.faces.active is not None else -1
        self.history = [(type(element), element.index) for element in bm.select_history]
        bm.to_mesh(copy)

    def restore(self, ob, bm):
        """Put the mesh back into the live edit bmesh. The caller drops its bmesh elements. False: the copy is gone (undo)."""
        copy = bpy.data.meshes.get(self.mesh_name)
        if copy is None:
            return False
        bm.clear()
        if self.has_keys:
            bm.from_mesh(copy, use_shape_key=True, shape_key_index=self.key_index)
        else:
            bm.from_mesh(copy)
        bm.select_mode = self.select_mode
        sequences = {bmesh.types.BMVert: bm.verts, bmesh.types.BMEdge: bm.edges, bmesh.types.BMFace: bm.faces}
        for sequence in sequences.values():
            sequence.ensure_lookup_table()
        if self.active_face >= 0:
            bm.faces.active = bm.faces[self.active_face]
        for element_type, index in self.history:
            bm.select_history.add(sequences[element_type][index])
        bmesh.update_edit_mesh(ob.data, loop_triangles=True, destructive=True)
        return True

    def close(self):
        copy = bpy.data.meshes.get(self.mesh_name)
        if copy is not None and copy.users == 0:
            bpy.data.meshes.remove(copy)
