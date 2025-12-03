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
        # Ensure OSDU-related state keys exist and set sensible defaults
        if not hasattr(self.state, "osdu_token_type"):
            self.state.osdu_token_type = "Bearer"
        if not hasattr(self.state, "osdu_proxy_token_type"):
            self.state.osdu_proxy_token_type = "Bearer"
        # tab default
        if not hasattr(self.state, "import_tab"):
            self.state.import_tab = "files"

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
            max_width="760",
        ):
            with vuetify3.VCard():
                # Title (harmonized)
                with vuetify3.VCardTitle(classes="d-flex align-center bg-blue-grey-lighten-5"):
                    vuetify3.VIcon(icon="mdi-cloud-upload", class_="mr-0", color="blue")
                    html.Span("Import from", classes="pl-4")

                # Tabs for From Files / From OSDU (styled like drawer tabs)
                with vuetify3.VCardText(classes="py-2"):
                    with vuetify3.VTabs(
                        v_model=("import_tab", "files"),
                        classes="bg-grey-lighten-4",
                        color="blue",
                        density="comfortable",
                        grow=True,
                        selected_class="font-weight-bold text-blue",
                    ):
                        vuetify3.VTab("Files", value="files")
                        vuetify3.VTab("OSDU", value="osdu")

                    with vuetify3.VWindow(v_model=("import_tab",), classes="pt-4"):
                        # --- From Files tab (existing content) ---
                        with vuetify3.VWindowItem(value="files"):
                            # Remote URL import
                            with vuetify3.VRow(classes="ma-0 mb-4"):
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

                            vuetify3.VDivider(classes="mb-4")

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

                        # --- From OSDU tab ---
                        with vuetify3.VWindowItem(value="osdu"):
                            with vuetify3.VContainer(fluid=True, classes="pa-0"):
                                # ETP URL
                                vuetify3.VTextField(
                                    v_model=("osdu_etp_url", None),
                                    label="RDDMS ETP URL",
                                    variant="outlined",
                                    density="comfortable",
                                    clearable=True,
                                    color="blue",
                                )

                                # OSDU Data Partition
                                vuetify3.VTextField(
                                    v_model=("osdu_data_partition", None),
                                    label="OSDU Data Partition",
                                    variant="outlined",
                                    density="comfortable",
                                    clearable=True,
                                    color="blue",
                                )

                                # ETP Token Type + Token (VSelect + aligned field)
                                with vuetify3.VRow(classes="ma-0"):
                                    with vuetify3.VCol(cols="6", classes="pa-0 pr-2"):
                                        vuetify3.VSelect(
                                            v_model=("osdu_token_type", "Bearer"),
                                            items=("osdu_token_type_options", ["Bearer", "Basic"]),
                                            label="OSDU Token Type",
                                            hide_details=True,
                                            dense=True,
                                            outlined=True,
                                            color="blue",
                                            base_color="blue",
                                        )

                                    with vuetify3.VCol(cols="6", classes="pa-0 pl-2"):
                                        vuetify3.VTextField(
                                            v_model=("osdu_token", None),
                                            label="OSDU Token",
                                            variant="outlined",
                                            density="comfortable",
                                            clearable=True,
                                            color="blue",
                                        )

                                # Proxy connexion expansion wrapped in a subtle card
                                with vuetify3.VCard(classes="mb-4", outlined=True, elevation=0):
                                    with vuetify3.VCardText(classes="pa-3"):
                                        with vuetify3.VExpansionPanels(style="display: initial;"):
                                            with vuetify3.VExpansionPanel():
                                                with vuetify3.VExpansionPanelTitle():
                                                    html.Span("Proxy Connection")
                                                with vuetify3.VExpansionPanelText():
                                                    vuetify3.VTextField(
                                                        v_model=("osdu_proxy_url", None),
                                                        label="Proxy Url",
                                                        variant="outlined",
                                                        density="comfortable",
                                                        clearable=True,
                                                        color="blue",
                                                    )

                                                    with vuetify3.VRow(classes="ma-0"):
                                                        with vuetify3.VCol(cols="6", classes="pa-0 pr-2"):
                                                            vuetify3.VSelect(
                                                                v_model=("osdu_proxy_token_type", "Bearer"),
                                                                items=("osdu_proxy_token_type_options", ["Bearer", "Basic"]),
                                                                label="Proxy Token Type",
                                                                hide_details=True,
                                                                dense=True,
                                                                outlined=True,
                                                                color="blue",
                                                                base_color="blue",
                                                            )

                                                        with vuetify3.VCol(cols="6", classes="pa-0 pl-2"):
                                                            vuetify3.VTextField(
                                                                v_model=("osdu_proxy_token", None),
                                                                label="Proxy Token",
                                                                variant="outlined",
                                                                density="comfortable",
                                                                clearable=True,
                                                                color="blue",
                                                            )
                                                

                # Actions
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
