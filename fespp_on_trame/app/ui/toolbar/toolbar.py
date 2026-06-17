from trame.widgets import vuetify3 as vuetify3, html
from trame.app import get_server


server = get_server()
state = server.state
controller = server.controller


class Toolbar:
    """Top toolbar: the Import dialog trigger and a left-side chevron
    that collapses the whole AppBar. The matching show-button lives in
    the layout content area so it stays reachable when the AppBar is
    hidden."""

    def __init__(self, local_file_manager, import_dialog):
        self.local_file_manager = local_file_manager
        self.import_dialog = import_dialog

    def render(self):
        with vuetify3.VContainer(classes="fill-height"):
            # Chevron that hides the AppBar; its re-show mirror lives
            # at the layout root in app_layout.py.
            with vuetify3.VTooltip(location="bottom", open_delay=300, close_delay=0):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-chevron-double-left",
                        v_bind="props",
                        variant="tonal",
                        color="blue-grey-darken-2",
                        size="small",
                        click="toolbar_visible = false",
                    )
                html.Span("Hide top toolbar")

            vuetify3.VSpacer()

            with html.Div(style="width: 15%;", classes="d-flex align-center gap-2"):
                vuetify3.VBtn(
                    "Import data",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )

            self.import_dialog.render()
