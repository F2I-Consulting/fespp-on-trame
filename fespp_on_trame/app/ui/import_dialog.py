from trame.widgets import vuetify3 as vuetify3, html
from tempfile import mkdtemp

from fespp_on_trame.app.io.http import download_file_from_url
from fespp_on_trame.app.io.drop_files import save_uploaded_files


class ImportDialog:
    """Manages both UI rendering and import action logic.

    This class encapsulates:
    - UI rendering for remote URL import + local file upload
    - State change handler for execute_action (triggering actual imports)

    The state and controller are injected at initialization.
    """

    def __init__(self, state, controller):
        """Initialize with server state and controller.

        Args:
            state: Trame server state (shared reactive variables)
            controller: Trame server controller (callable functions)
        """
        self.state = state
        self.controller = controller
        # Register the import action handler on state change
        self.state.change("execute_action")(self._on_execute_action)

    def _on_execute_action(self, execute_action, **kwargs):
        """Handle file import logic when execute_action changes to True.

        Supports two import modes:
        1. Import from remote URLs (e.g., from an input field)
        2. Import from local file uploads
        """
        if execute_action and self.state.remote_files_location:
            # Case 1: Import from remote URLs
            list_url = self.state.remote_files_location.split('|')
            temp_dir = mkdtemp()
            epc_paths = []

            # Download files from URLs
            for url in list_url:
                file_name = download_file_from_url(url, temp_dir)
                if file_name.lower().endswith('.epc'):
                    epc_paths.append(file_name)

            # Load the collected EPC files
            for epc_path in epc_paths:
                self.controller.load_epc_file(epc_path)

            # Reset state variables after action completion
            self.state.execute_action = False
            self.state.remote_files_location = None

        elif execute_action and self.state.files:
            # Case 2: Import from local file uploads
            epc_paths = save_uploaded_files(self.state.files)
            for epc_path in epc_paths:
                self.controller.load_epc_file(epc_path)
            self.state.files = None

        # Ensure the execution flag is reset regardless of the path taken
        self.state.execute_action = False

    def render(self):
        with vuetify3.VDialog(
            v_model=("dialog_visible", False),
            max_width="600",
        ):
            with vuetify3.VCard():
                with vuetify3.VCardTitle(classes="d-flex align-center bg-blue-grey-lighten-5"):
                    vuetify3.VIcon(icon="mdi-cloud-upload", class_="mr-0", color="blue")
                    html.Span("Import Files", classes="pl-4")

                with vuetify3.VCardText(classes="py-5"):
                    # Remote URL import
                    with vuetify3.VRow(classes="ma-0 mb-5"):
                        with vuetify3.VCol(cols="12", classes="pa-0"):
                            with html.Div(classes="d-flex align-center mb-2"):
                                vuetify3.VIcon(icon="mdi-link-variant", class_="mr-0", color="blue-grey-darken-2")
                                html.Span("Import from Remote URL", classes="text-h6 font-weight-regular pl-4")

                            vuetify3.VTextField(
                                variant="outlined",
                                label="Enter URLs (separated with '&' character)",
                                v_model=("remote_files_location", None),
                                density="comfortable",
                                placeholder="Ex: http://example.com/file1.obj&http://example.com/file2.ply",
                                hide_details="auto",
                                clearable=True,
                            )

                    vuetify3.VDivider(classes="mb-5")

                    # Local file upload
                    with vuetify3.VRow(classes="ma-0"):
                        with vuetify3.VCol(cols="12", classes="pa-0"):
                            with html.Div(classes="d-flex align-center mb-3"):
                                vuetify3.VIcon(icon="mdi-folder-upload", class_="mr-0", color="blue-grey-darken-2")
                                html.Span("Upload Local Files", classes="text-h6 font-weight-regular pl-4")

                            vuetify3.VFileUpload(
                                v_model=("files", None),
                                density="comfortable",
                                clearable=True,
                                multiple=True,
                                prepend_icon="mdi-upload-multiple",
                                label="Drag and drop or click to select files",
                                classes="pa-3",
                            )

                with vuetify3.VCardActions(classes="pa-4 bg-blue-grey-lighten-5"):
                    vuetify3.VSpacer()
                    vuetify3.VBtn(
                        "Cancel",
                        variant="text",
                        color="blue-grey-darken-2",
                        click="dialog_visible = false",
                    )

                    vuetify3.VBtn(
                        "Import",
                        color="blue",
                        variant="elevated",
                        click="dialog_visible = false; execute_action = true",
                        prepend_icon="mdi-check-circle",
                    )
