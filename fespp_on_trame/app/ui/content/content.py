"""Main content-area builder.

Lays out the busy overlay over the multi-view, then a flex column:
top tools band (cameras / global TC / settings cog), the multi-view
itself (with content dialogs + a bottom progress bar), and the VTK
log panel at the bottom.

`Content` owns the five content-area dialogs (add view, diff colors,
global settings, view settings, new view content). The toolbar-area
`ImportDialog` is owned by app_layout.

Public API: `Content(server, state, controller).render()` — call
inside a `with layout.content:` context."""
from trame.widgets import html

from .view import FesppMultiView
from .dialog import (
    AddViewDialog,
    DiffColorsDialog,
    GlobalSettingsDialog,
    ViewSettingsDialog,
    NewViewContentDialog,
)
from .widget.tools_band import ToolsBand
from .widget.busy_overlay import BusyOverlay
from .widget.busy_progress_bar import BusyProgressBar
from .widget.vtk_log_panel import VtkLogPanel


class Content:
    """Renders the entire main content area below the toolbar."""

    def __init__(self, server, state, controller):
        self._server = server
        self._add_view_dialog = AddViewDialog()
        self._diff_colors_dialog = DiffColorsDialog()
        self._global_settings_dialog = GlobalSettingsDialog(state, controller)
        self._view_settings_dialog = ViewSettingsDialog()
        self._new_view_content_dialog = NewViewContentDialog()

    def render(self):
        BusyOverlay().render()

        # Flex column: tools band (fixed) + multi-view (grows) + log
        # panel (fixed at bottom). Tools band has flex-shrink:0 so the
        # multi-view always gets the leftover height.
        with html.Div(style="display: flex; flex-direction: column; height: 100%; width: 100%;"):
            ToolsBand().render()
            self._render_view_area()
            VtkLogPanel().render()

    def _render_view_area(self):
        """Multi-view container + the content-area dialogs that
        render on top of it + the bottom progress bar."""
        with html.Div(style="flex: 1; position: relative; overflow: hidden; min-height: 0;"):
            multi_view = FesppMultiView(
                ctx_name="multi_view",
                ready=lambda: self._server.context.multi_view.add_view(),
            )

            self._add_view_dialog.render()
            self._diff_colors_dialog.render()
            self._global_settings_dialog.render()
            self._view_settings_dialog.render()
            self._new_view_content_dialog.render()

            BusyProgressBar().render()

            # Expose the multi-view controller hooks.
            ctrl = self._server.controller
            ctrl.view_replace = multi_view.replace_active
            ctrl.view_update = multi_view.update_active
            ctrl.view_update_all = multi_view.update_all
            ctrl.view_reset_camera = multi_view.reset_camera_active
            ctrl.on_server_ready.add(ctrl.view_update)
