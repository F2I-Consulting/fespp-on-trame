from trame.widgets import vuetify3 as vuetify3, html
import ptc
from trame.app import get_server

from fespp_on_trame.app.ui.import_dialog import ImportDialog

server = get_server()
state = server.state
controller = server.controller


class Toolbar:
    """Encapsulates toolbar rendering.

    Designed to be instantiated in the main `ui` function and called with
    `toolbar.render()` inside the layout.toolbar context manager.
    """

    def __init__(self, local_file_manager, import_dialog):
        self.local_file_manager = local_file_manager
        self.import_dialog = import_dialog

    def render(self):
        # Application icon and title are handled by the layout in view.ui
        with vuetify3.VContainer(classes="fill-height"):
            vuetify3.VSpacer()

            # Apply button — only visible in apply_mode="manual". Pushes the
            # current per-tab selections (reservoir/surface/well) to ParaView
            # in a single shot so the user can stage many checkbox toggles
            # without paying a load on each click.
            vuetify3.VBtn(
                "Apply",
                v_if="apply_mode === 'manual'",
                variant="flat",
                color="green",
                prepend_icon="mdi-play",
                click=(controller.apply_pending_selection,),
                classes="mr-2",
            )

            with html.Div(style="width: 15%;", classes="d-flex align-center gap-2"):
                vuetify3.VBtn(
                    "Import data",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )

            # Import dialog (renders inside toolbar scope)
            self.import_dialog.render()
