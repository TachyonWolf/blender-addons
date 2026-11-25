# SPDX-License-Identifier: GPL-3.0-or-later
"""The ring of edges a loop cut runs through (bmesh reads only; the cut itself is edit_tools.loop_cut, the preview
edit_loop_preview)."""
import numpy as np


class Ring:
    """The ring of one edge: across every visible quad, in both directions. Edges all point the same way, so a slide
    moves the whole loop to one side. `pairs`: rows of two edges that share a face; `crosses`: a quad is met twice."""

    def __init__(self, edge):
        start = edge.verts[0], edge.verts[1]
        self.edges, self.ends, self.pairs, self.crosses = [edge], [start], [], False
        rows, faces, queue = {edge: 0}, {}, [0]
        while queue:
            row = queue.pop()
            for face in self.edges[row].link_faces:
                if len(face.verts) != 4 or face.hide:
                    continue
                if face in faces:
                    self.crosses = self.crosses or row not in faces[face]
                    continue
                other, ends = _opposite(face, self.edges[row], self.ends[row])
                if other not in rows:
                    rows[other] = len(self.edges)
                    self.edges.append(other)
                    self.ends.append(ends)
                    queue.append(rows[other])
                faces[face] = (row, rows[other])
                self.pairs.append(faces[face])

    def points(self):
        """(heads, tails): (rows, 3) arrays, local coordinates."""
        return (np.array([head.co[:] for head, _tail in self.ends], np.float64),
                np.array([tail.co[:] for _head, tail in self.ends], np.float64))

    def refusal(self, cuts, max_points):
        if not self.pairs:
            return "No loop to cut here"
        if self.crosses:
            return "This loop crosses itself"
        if len(self.edges) * cuts > max_points:
            return "Too many cuts for this loop"
        return ""


def _opposite(face, edge, ends):
    """(the edge across `face` from `edge`, its ends in the same direction)."""
    loop = next(loop for loop in face.loops if loop.edge == edge)
    across = loop.link_loop_next.link_loop_next
    beside_loop, beside_next = loop.link_loop_prev.vert, across.vert      # joined to loop.vert, to the loop's end
    return across.edge, (beside_loop, beside_next) if loop.vert == ends[0] else (beside_next, beside_loop)
