"""Select Non Manifold (Skip Mirror Seam): Blender's Select Non Manifold, minus the open centre seam
that a Mirror modifier closes. The base selection is the built-in operator; the seam is deselected after.

Seam rule: a BOUNDARY edge (one face) whose both verts lie on the same plane of an enabled Mirror
modifier (axis in use_axis, plane in mirror_object space when set), within the modifier's merge
threshold (SEAM_TOLERANCE when merge is off). Seam verts stay selected when another non-manifold
edge (wire, multi-face or boundary off the plane) touches them."""
import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty

from . import mesh_review


def seam_edges(obj, bm):
    """Boundary edges lying on a mirror plane of the object (the rule lives in mesh_review, shared with the
    Non-Manifold check)."""
    planes = mesh_review.mirror_planes(obj)
    if not planes:
        return []
    bm.verts.index_update()
    bm.edges.ensure_lookup_table()
    co = np.array([v.co for v in bm.verts], dtype=np.float32).reshape(-1, 3)
    edge_verts = np.array([[v.index for v in e.verts] for e in bm.edges], dtype=np.intp).reshape(-1, 2)
    edge_faces = np.array([len(e.link_faces) for e in bm.edges], dtype=np.intp)
    return [bm.edges[i] for i in np.flatnonzero(mesh_review.seam_edge_mask(planes, co, edge_verts, edge_faces))]


def deselect_seam(bm, seam, keep_selected):
    """Deselect seam edges and their verts (unless another selected non-manifold edge touches the vert).
    Elements in keep_selected = (edge indices, vert indices) were selected before; they stay.
    Returns (edges skipped, verts skipped)."""
    seam_set = set(seam)
    kept_edges, kept_verts = keep_selected
    edges = [e for e in seam if e.select and e.index not in kept_edges]
    verts = {v for e in edges for v in e.verts if v.select and v.index not in kept_verts}
    stay = {v for v in verts if any(
        o.select and o not in seam_set and len(o.link_faces) != 2 for o in v.link_edges)}
    for edge in edges:
        edge.select_set(False)
    for vert in verts - stay:
        vert.select_set(False)
    for vert in stay | {v for e in seam for v in e.verts if v.index in kept_verts}:
        vert.select_set(True)
    bm.select_flush_mode()
    return len(edges), len(verts - stay)


class MESH_OT_select_non_manifold_smart(bpy.types.Operator):
    bl_idname = "mesh.select_non_manifold_smart"
    bl_label = "Non Manifold (Skip Mirror Seam)"
    bl_description = ("Select Non Manifold, but not the open centre seam a Mirror modifier closes "
                      "(boundary edges on the mirror plane)")
    bl_options = {'REGISTER', 'UNDO'}

    extend: BoolProperty(name="Extend", default=True, description="Extend the existing selection")
    use_wire: BoolProperty(name="Wire", default=True, description="Wire edges")
    use_boundary: BoolProperty(name="Boundaries", default=True, description="Boundary edges")
    use_multi_face: BoolProperty(name="Multiple Faces", default=True, description="Edges shared by more than two faces")
    use_non_contiguous: BoolProperty(name="Non Contiguous", default=True, description="Edges between faces pointing in alternate directions")
    use_verts: BoolProperty(name="Vertices", default=True, description="Vertices connecting multiple face regions")
    ignore_seam: BoolProperty(name="Ignore Mirror Seam", default=True,
                              description="Skip boundary edges on a Mirror modifier plane (within its merge distance, "
                                          "1e-4 when Merge is off)")

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        objects = list(context.objects_in_mode_unique_data)
        before = {}
        for obj in objects:
            bm = bmesh.from_edit_mesh(obj.data)
            before[obj] = ({e.index for e in bm.edges if e.select}, {v.index for v in bm.verts if v.select})
        try:
            bpy.ops.mesh.select_non_manifold(
                extend=self.extend, use_wire=self.use_wire, use_boundary=self.use_boundary,
                use_multi_face=self.use_multi_face, use_non_contiguous=self.use_non_contiguous,
                use_verts=self.use_verts)
        except RuntimeError as error:
            self.report({'ERROR'}, str(error).strip().splitlines()[-1])
            return {'CANCELLED'}
        if self.ignore_seam:
            skipped_edges = skipped_verts = 0
            for obj in objects:
                bm = bmesh.from_edit_mesh(obj.data)
                seam = seam_edges(obj, bm)
                if not seam:
                    continue
                kept = before[obj] if self.extend else (set(), set())
                edges, verts = deselect_seam(bm, seam, kept)
                skipped_edges += edges
                skipped_verts += verts
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            self.report({'INFO'}, f"Skipped {skipped_edges} mirror seam edges, {skipped_verts} vertices")
        return {'FINISHED'}


def draw_menu(self, context):
    self.layout.operator(MESH_OT_select_non_manifold_smart.bl_idname)


def register():
    bpy.utils.register_class(MESH_OT_select_non_manifold_smart)
    bpy.types.VIEW3D_MT_edit_mesh_select_by_trait.append(draw_menu)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_select_by_trait.remove(draw_menu)
    bpy.utils.unregister_class(MESH_OT_select_non_manifold_smart)
