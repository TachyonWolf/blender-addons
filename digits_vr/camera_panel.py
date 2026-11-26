# SPDX-License-Identifier: GPL-3.0-or-later
"""The Cam view panel (bpy side): the scene camera's live picture on its own floating panel, opened by the desk's Cam view
button. Handles, Pin and the belt (belt_items.CAMERA_ITEM) are the shared panel / held-item code; the picture is
camera_preview's, drawn on the panel by `draw_extra`."""
from . import camera_layout as layout, camera_preview
from .panel import Panel


def build_model(context):
    camera = context.scene.camera
    return layout.CameraModel(camera=camera.name if camera else "", note=camera_preview.note(context))


def perform(context, widget):
    if not widget.enabled or widget.action != ("camera_update",):
        return False
    camera_preview.request_update()
    return True


class CameraPanel(Panel):
    name = "camera_view"
    spec = layout.SPEC
    open_side = -0.5            # first opens to the left of the desk, its Pin and handle clear of the desk's (tool options: right)
    open_drop = 0.05

    def build_model(self, context):
        return build_model(context)

    def build_widgets(self, model):
        return layout.build(model)

    def perform(self, context, widget, pixel_x):
        return perform(context, widget)

    def update(self, context, state):
        camera_preview.update(context, self.spec, layout.PICTURE)     # asks for a render when due (nothing while unchanged)

    def draw_extra(self, new_frame):
        camera_preview.draw(self.renderer.frame_matrix or self.state.matrix())

    def closed(self):
        camera_preview.free()


PANEL = CameraPanel()
