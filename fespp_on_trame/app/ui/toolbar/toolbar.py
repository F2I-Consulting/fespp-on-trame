from trame.widgets import vuetify3 as vuetify3, html
from trame.app import get_server


server = get_server()
state = server.state
controller = server.controller


class Toolbar:
    """Top toolbar: the Import dialog trigger and a top-right chevron
    (double-up) that collapses the whole AppBar. Its matching show
    mirror (a double-down chevron) is pinned to the same corner at the
    layout root so it stays reachable when the AppBar is hidden."""

    def __init__(self, local_file_manager, import_dialog):
        self.local_file_manager = local_file_manager
        self.import_dialog = import_dialog

    def render(self):
        with vuetify3.VContainer(classes="fill-height"):
            vuetify3.VSpacer()

            with html.Div(classes="d-flex align-center", style="gap: 8px;"):
                vuetify3.VBtn(
                    "Import data",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )
                # Hide-the-AppBar chevron — a double-UP arrow at the toolbar's
                # top-right corner. Its show mirror (a double-DOWN arrow at the
                # same corner) lives at the layout root in app_layout.py, so
                # the toggle keeps the button in one place: up = collapse,
                # down = expand.
                with vuetify3.VTooltip(location="bottom", open_delay=300, close_delay=0):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            icon="mdi-chevron-double-up",
                            v_bind="props",
                            variant="tonal",
                            color="blue-grey-darken-2",
                            size="small",
                            click="toolbar_visible = false",
                        )
                    html.Span("Hide top toolbar")

            self.import_dialog.render()
