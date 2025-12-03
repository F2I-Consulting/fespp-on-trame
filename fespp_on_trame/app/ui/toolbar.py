from trame.widgets import vuetify3 as vuetify3, html
import ptc

from fespp_on_trame.app.ui.import_dialog import ImportDialog


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

            with html.Div(style="width: 15%;", classes="d-flex align-center"):
                ptc.RepresentBy(color="blue", base_color="blue", item_color="blue")

            with html.Div(style="width: 5%;", classes="d-flex align-center"):
                vuetify3.VTextField(
                    v_model=("ui_scale_z", 1.0),
                    label="Z scale",
                    hide_details=True,
                    density="compact",
                    variant="outlined",
                    color="blue",
                    base_color="blue",
                    bg_color="white",
                    reverse=True,
                    type="number",
                )

            vuetify3.VSpacer()

            with html.Div(style="width: 15%;", classes="d-flex align-center"):
                vuetify3.VBtn(
                    "Import files",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )

            with html.Div(classes="d-flex align-center"):
                ptc.PalettePicker(flat=True)

            # Import dialog (renders inside toolbar scope)
            self.import_dialog.render()
