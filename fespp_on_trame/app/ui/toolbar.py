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

            with html.Div(style="width: 15%;", classes="d-flex align-center gap-2"):
                vuetify3.VBtn(
                    "Import data",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )

            # Import dialog (renders inside toolbar scope)
            self.import_dialog.render()
