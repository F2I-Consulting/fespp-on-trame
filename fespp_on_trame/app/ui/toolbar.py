from trame.widgets import vuetify3 as vuetify3, html
import ptc
from trame.app import get_server

from fespp_on_trame.app.ui.import_dialog import ImportDialog

server = get_server()
state = server.state
controller = server.controller


class Toolbar:
    """Top toolbar of the application. Hosts the Load button (manual
    load mode only) and the Import dialog trigger. Title and logo are
    rendered by the host layout, not here."""

    def __init__(self, local_file_manager, import_dialog):
        self.local_file_manager = local_file_manager
        self.import_dialog = import_dialog

    def render(self):
        with vuetify3.VContainer(classes="fill-height"):
            vuetify3.VSpacer()

            # Visible only in load_mode="manual" — auto mode pushes
            # selections on every checkbox toggle.
            vuetify3.VBtn(
                "Load",
                v_if="load_mode === 'manual'",
                variant="flat",
                color="green",
                prepend_icon="mdi-reload",
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

            self.import_dialog.render()
