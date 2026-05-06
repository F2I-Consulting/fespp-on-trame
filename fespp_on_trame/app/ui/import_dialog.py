from trame.widgets import vuetify3 as vuetify3, html
from tempfile import mkdtemp

from fespp_on_trame.app.io.http import download_file_from_url


# Inline JS run on Import-button click.
#   "files" tab: streams a multipart POST to /upload (or
#     /api/<sid>/upload behind the proxy). Reaches `window` via
#     ownerDocument.defaultView so it bypasses Vue 3's template
#     whitelist; filters the FileList against upload_file_names so
#     per-file removals stick; sends raw binary, no base64.
#   "osdu" tab: just toggles execute_action so the Python handler
#     downloads via download_file_from_url.
_IMPORT_CLICK_JS = (
    "upload_debug='start';"
    "if (import_tab === 'files') {"
    "  try {"
    "    var _doc=($event&&$event.target)?$event.target.ownerDocument:document;"
    "    var _inp=_doc&&_doc.getElementById('fesppFileInput');"
    "    var _f=_inp&&_inp.files;"
    "    upload_debug='files:'+((_f&&_f.length)||0);"
    "    if (_f&&_f.length) {"
    "      var _win=_doc.defaultView;"
    "      var _keep=upload_file_names&&upload_file_names.length?Array.from(upload_file_names):null;"
    "      var _fd=new _win.FormData();"
    "      var _sz=0;"
    "      Array.from(_f).forEach(function(f){"
    "        if(!_keep||_keep.indexOf(f.name)>=0){_fd.append('files',f);_sz+=f.size;}"
    "      });"
    "      if (_sz>0) {"
    "        var _url=upload_session_id?'/api/'+upload_session_id+'/upload':'/upload';"
    "        upload_debug='url:'+_url;"
    "        var _xhr=new _win.XMLHttpRequest();"
    "        _xhr.open('POST',_url);"
    "        _xhr.setRequestHeader('X-File-Size',_sz);"
    "        _xhr.onload=function(){ upload_debug='xhr:'+_xhr.status; if(_xhr.status<300){upload_uploading=false;upload_progress=100;} };"
    "        _xhr.onerror=function(){ upload_debug='xhr_error'; upload_uploading=false; };"
    "        _xhr.send(_fd);"
    "        upload_debug='sent:'+_url;"
    "        upload_uploading=true; upload_progress=0;"
    "        upload_file_names=[]; upload_file_count=0;"
    "      }"
    "    }"
    "  } catch(e) { upload_debug='err:'+e.message; }"
    "  dialog_visible=false;"
    "} else {"
    "  dialog_visible=false; execute_action=true;"
    "}"
)


class ImportDialog:
    """Owns both the import dialog UI and the execute_action handler.
    Three import paths are supported:
    - remote URL list (HTTP download into a temp dir);
    - local file upload (handled outside this class — the inline JS
      above POSTs to /upload directly);
    - OSDU / ETP connection."""

    def __init__(self, state, controller):
        self.state = state
        self.controller = controller
        self.state.change("execute_action")(self._on_execute_action)
        if not hasattr(self.state, "osdu_token_type"):
            self.state.osdu_token_type = "Bearer"
        if not hasattr(self.state, "osdu_proxy_token_type"):
            self.state.osdu_proxy_token_type = "Bearer"
        if not hasattr(self.state, "import_tab"):
            self.state.import_tab = "files"
        self.state.import_button_disabled = False
        self.state.change("import_tab", "etp_selected_dataspace")(self._update_import_button_state)
        self.state.change("etp_selected_dataspace")(self._on_dataspace_selected)

    def _update_import_button_state(self, **kwargs):
        """Disable the Import button on the OSDU tab as long as no
        dataspace is selected; always enabled on the Files tab."""
        if self.state.import_tab == "osdu":
            self.state.import_button_disabled = not bool(self.state.etp_selected_dataspace)
        else:
            self.state.import_button_disabled = False

    def _on_dataspace_selected(self, etp_selected_dataspace, **kwargs):
        if etp_selected_dataspace:
            self.controller.select_etp_dataspace(etp_selected_dataspace)

    def _on_execute_action(self, execute_action, **kwargs):
        """Run the right import path when execute_action flips to True.
        Local-file uploads are NOT handled here — the inline JS above
        sends a multipart POST to /upload directly. We only handle
        remote URLs and OSDU here."""
        if not execute_action:
            return

        current_tab = self.state.import_tab

        if current_tab == "osdu":
            self._handle_osdu_import()
        elif self.state.remote_files_location:
            list_url = self.state.remote_files_location.split('|')
            temp_dir = mkdtemp()
            epc_paths = []

            for url in list_url:
                file_name = download_file_from_url(url, temp_dir)
                if file_name.lower().endswith('.epc'):
                    epc_paths.append(file_name)

            for epc_path in epc_paths:
                self.controller.load_epc_file(epc_path)

            self.state.remote_files_location = None

        self.state.execute_action = False

    def _handle_osdu_connect(self):
        """Connect to the configured OSDU/ETP server. The dialog stays
        open so the user can pick a dataspace once the connection is
        up."""
        if not self.state.osdu_etp_url:
            print("Error: ETP URL is required")
            return

        if not self.state.osdu_data_partition:
            print("Error: OSDU Data Partition is required")
            return

        if not self.state.osdu_token:
            print("Error: OSDU Token is required")
            return

        etp_url = self.state.osdu_etp_url
        data_partition = self.state.osdu_data_partition
        token = self.state.osdu_token
        token_type = self.state.osdu_token_type

        proxy_url = self.state.osdu_proxy_url if hasattr(self.state, 'osdu_proxy_url') else None
        proxy_token = self.state.osdu_proxy_token if hasattr(self.state, 'osdu_proxy_token') else None
        proxy_token_type = self.state.osdu_proxy_token_type if hasattr(self.state, 'osdu_proxy_token_type') else "Bearer"

        self.controller.connect_to_etp(
            etp_url=etp_url,
            data_partition=data_partition,
            token=token,
            token_type=token_type,
            proxy_url=proxy_url,
            proxy_token=proxy_token,
            proxy_token_type=proxy_token_type
        )

    def _handle_osdu_import(self):
        """Trigger a forced refresh of the ETP source to pull in the
        currently-selected dataspace."""
        self.controller.force_etp_refresh()
        self.state.has_data_loaded_once = True

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
                        with vuetify3.VWindowItem(value="files"):
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

                            # Local file upload via HTTP multipart (no
                            # base64-over-WebSocket).
                            with vuetify3.VRow(classes="ma-0"):
                                with vuetify3.VCol(cols="12", classes="pa-0"):
                                    with html.Div(classes="d-flex align-center mb-3"):
                                        vuetify3.VIcon(icon="mdi-folder-upload", class_="mr-0", color="blue-grey-darken-2")
                                        html.Span("Upload Local Files", classes="text-h6 font-weight-regular pl-4")

                                    # Drag & drop zone: an invisible
                                    # <input type="file"> covers the
                                    # whole div so click and drop both
                                    # work natively (no custom JS).
                                    with html.Div(
                                        style="position: relative; border: 2px dashed #90a4ae; border-radius: 8px; padding: 32px 16px; text-align: center;",
                                    ):
                                        vuetify3.VIcon(icon="mdi-upload-multiple", size="48", color="blue-grey-lighten-1")
                                        html.P(
                                            "Drop files or click to pick (.epc, .h5)",
                                            style="margin: 8px 0 0; color: #607d8b; font-size: 0.9rem; pointer-events: none;",
                                        )

                                        html.Input(
                                            id="fesppFileInput",
                                            type="file",
                                            multiple=True,
                                            accept=".epc,.h5",
                                            title="",
                                            style=(
                                                "position: absolute; inset: 0; width: 100%; height: 100%;"
                                                " opacity: 0; cursor: pointer; z-index: 1;"
                                            ),
                                            change=(
                                                "upload_file_names=Array.from($event.target.files)"
                                                ".map(function(f){return f.name;});"
                                                " upload_file_count=upload_file_names.length;"
                                            ),
                                        )

                                    # Selected-files list (one per row,
                                    # individual remove).
                                    with html.Div(
                                        v_show="upload_file_count > 0 && !upload_uploading",
                                        style="margin-top: 8px; border-radius: 4px; overflow: hidden;",
                                    ):
                                        with html.Div(
                                            style="padding: 6px 10px; background: #e8f5e9; border-bottom: 1px solid #c8e6c9;",
                                        ):
                                            html.Span(
                                                "{{ upload_file_count }} file(s) selected",
                                                style="color: #2e7d32; font-size: 0.82rem; font-weight: 600;",
                                            )
                                        with html.Div(
                                            style="background: #f1f8e9; max-height: 160px; overflow-y: auto;",
                                        ):
                                            with html.Div(
                                                v_for="(name, idx) in upload_file_names",
                                                key=("idx",),
                                                style=(
                                                    "display: flex; align-items: center; justify-content: space-between;"
                                                    " padding: 4px 10px; border-bottom: 1px solid #dcedc8;"
                                                ),
                                            ):
                                                html.Span(
                                                    "{{ name }}",
                                                    style="font-size: 0.83rem; color: #33691e; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;",
                                                )
                                                vuetify3.VBtn(
                                                    icon="mdi-close",
                                                    variant="text",
                                                    size="x-small",
                                                    color="red-lighten-2",
                                                    click=(
                                                        "upload_file_names = upload_file_names.filter(function(_, i){ return i !== idx; });"
                                                        " upload_file_count = upload_file_names.length;"
                                                    ),
                                                    style="flex-shrink: 0; margin-left: 4px;",
                                                )

                                    # Progress bar — visible during upload.
                                    with html.Div(
                                        v_show="upload_uploading",
                                        style="margin-top: 16px;",
                                    ):
                                        vuetify3.VProgressLinear(
                                            model_value=("upload_progress", 0),
                                            color="blue",
                                            height=8,
                                            rounded=True,
                                            indeterminate=("upload_progress === 0",),
                                        )
                                        html.P(
                                            "{{ upload_progress > 0 ? 'Upload en cours… ' + upload_progress + '%' : 'Transfert en cours…' }}",
                                            style="text-align: center; color: #607d8b; font-size: 0.85rem; margin-top: 4px;",
                                        )

                        with vuetify3.VWindowItem(value="osdu"):
                            with vuetify3.VContainer(fluid=True, classes="pa-0"):
                                vuetify3.VTextField(
                                    v_model=("osdu_etp_url", None),
                                    label="RDDMS ETP URL",
                                    variant="outlined",
                                    density="comfortable",
                                    clearable=True,
                                    color="blue",
                                )

                                vuetify3.VTextField(
                                    v_model=("osdu_data_partition", None),
                                    label="OSDU Data Partition",
                                    variant="outlined",
                                    density="comfortable",
                                    clearable=True,
                                    color="blue",
                                )

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

                                with vuetify3.VRow(classes="ma-0 mt-4"):
                                    with vuetify3.VCol(cols="12", classes="pa-0"):
                                        vuetify3.VBtn(
                                            "Connect to Server",
                                            color="blue",
                                            variant="tonal",
                                            block=True,
                                            prepend_icon="mdi-connection",
                                            click=(self._handle_osdu_connect,),
                                        )

                                # Dataspace selector — only shown
                                # once the ETP connection is up.
                                with vuetify3.VCard(
                                    v_show="etp_dataspaces && etp_dataspaces.length > 0",
                                    classes="mt-4",
                                    outlined=True,
                                    elevation=1,
                                    style="border-color: #2196F3;"
                                ):
                                    with vuetify3.VCardText(classes="pa-3"):
                                        vuetify3.VSelect(
                                            v_model=("etp_selected_dataspace", None),
                                            items=("etp_dataspaces", []),
                                            label="Select Dataspace",
                                            variant="outlined",
                                            density="comfortable",
                                            color="blue",
                                            base_color="blue",
                                            messages="Choose a dataspace to explore",
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
                        click=_IMPORT_CLICK_JS,
                        prepend_icon="mdi-check-circle",
                        disabled=("import_button_disabled",),
                    )
