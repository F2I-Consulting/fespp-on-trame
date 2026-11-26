from trame_client.widgets.core import AbstractElement

from trame_fespp_upload import module


class HtmlElement(AbstractElement):
    """Base element: enables this package's web module on the server the
    element is attached to, so the Vue components are served and
    registered."""

    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["UploadData", "UploadFile", "UploadOsdu"]


class UploadFile(HtmlElement):
    """Fine-grained file-import widget: pick/drop files -> POST multipart
    FormData to the server's /upload endpoint, which writes them into the
    session temp dir and loads each .epc (the companion .h5 lands in the
    same dir).

    Props::

        upload_url : POST target (default "/upload")
        session_id : if set, POST to "api/{session_id}/upload" (proxied),
                     resolved against the page so a URL prefix is kept
        accept     : input accept filter (default ".epc,.h5")
        loaded     : what the session has ALREADY read, listed above the drop
                     zone: [{name, size_mb, objects, failed}]. The dialog is
                     rebuilt on every open, so nothing survives a close: the
                     host's own list is what lets a reopened dialog show the
                     files the session holds (the reader never reads the
                     same name twice).

    Events::

        uploaded(names)    files uploaded OK (server then loads them)
        error(message)
    """

    def __init__(self, **kwargs):
        super().__init__("upload-file", **kwargs)
        self._attr_names += ["upload_url", "session_id", "accept", "loaded"]
        self._event_names += ["uploaded", "error"]


class UploadOsdu(HtmlElement):
    """Fine-grained OSDU import widget: credential form for an OSDU RDDMS /
    ETP 1.2 endpoint. The connection itself is server-side (FESPP
    ETP12Store): the widget emits the etp_* events and mirrors
    server-driven state.

    Props::

        etp_connected  : bool, server says the ETP session is up
        etp_connecting : bool, connect in flight (disables the button)
        etp_step : str, the step of the connection in progress, shown on
            the button in place of "Connecting…" ("" when none)
        etp_dataspaces : list of dataspace names from the server
        etp_status     : free-text status/error line shown under the form
        prefill        : {} or {url, partition} — what a session file read
                         from OSDU keeps (never the token nor the password).
                         Each new value fills the URL and Data partition
                         fields, empties the secret fields and puts the
                         keyboard focus in the first one asked (the token,
                         or the user with Basic); while the secret is empty
                         a muted line says it is never saved in a session file
        osdu_explorer  : the dataspace explorer's state, owned by the server
                         side (engine/osdu_explorer, state `osdu_explorer`)::

                             {status: idle|listing|scanning|done|error,
                              message: "", rest: bool,
                              dataspaces: [{uri, path, project, name,
                                            last_write, size, locked,
                                            read_only, scan: pending|scanning|
                                            done|error (absent without the
                                            facade), progress: 0..1,
                                            facts: None | {objects,
                                            grids, wells, properties, surfaces,
                                            horizons, faults, epsg, error}}],
                              scanned: 0, total: 0,
                              find: {text, status: idle|searching|done,
                                     total, results: [{uri, path, score,
                                     why: [str], objects: [{type, name}],
                                     published: bool}]},
                              search: {…}   not read by the widget}

                         While `dataspaces` is non-empty the connected form
                         shows a searchable, sortable table with a Load
                         button per row instead of the dropdown; while it is
                         empty (a server side without the explorer, or a list
                         not yet mirrored) the dropdown stays. `find` is
                         the server's answer to the search box: the matching
                         dataspaces ranked best first, each with why it
                         matches and up to 5 matched objects; while its
                         `text` is the one typed and its status "done" the
                         table shows those rows in that order. The server
                         merges the OSDU catalogue into it: `published`
                         puts a badge on a row, and a result no listed row
                         holds (only the catalogue knows it) is shown from
                         its path, without facts, and still loads

    Events::

        etp_connect({url, partition, auth: "Bearer", token})
            or etp_connect({url, partition, auth: "Basic", user, password})
        etp_select({dataspace})   `dataspace` is the entry's ETP URI, from
                                  the dropdown or from a row's Load button
        etp_disconnect()
        osdu_scan()               start or refresh the inventory scan
        osdu_find({text})         search everything the server holds (a well,
                                  a property, a horizon, an EPSG code, a
                                  type, since:YYYY-MM); sent on every change
                                  of the search box, debounced 250 ms, at
                                  once on Enter; an empty text clears it
        osdu_search({text})       never emitted (the OSDU catalogue is
                                  merged into `find`); declared so that a
                                  binding naming it stays valid
        osdu_kinds({uri, refresh?})
                                  read the property KINDS of that dataspace
                                  (the Props count of its row, clicked):
                                  the row's `kinds` goes "reading", then
                                  {total, kinds: [{kind, count}], unknown}
                                  or {error}; `refresh` asks the store again
    """

    def __init__(self, **kwargs):
        super().__init__("upload-osdu", **kwargs)
        self._attr_names += [
            "etp_connected",
            "etp_connecting",
            "etp_step",
            "etp_dataspaces",
            "etp_status",
            "prefill",
            "osdu_explorer",
        ]
        self._event_names += [
            "etp_connect",
            "etp_select",
            "etp_disconnect",
            "osdu_scan",
            "osdu_find",
            "osdu_search",
            "osdu_kinds",
        ]


class UploadData(HtmlElement):
    """Import shell: the "Import data" toolbar button and a modal dialog
    holding BOTH import sources at once, side by side: Files
    (`upload-file`) and OSDU (ETP) (`upload-osdu`). The shell owns the
    open/close state and forwards the fine widgets' props and events
    verbatim; see UploadFile / UploadOsdu for the contracts. Both loads are
    server-side and SESSION-shared.

    `loaded_files` is handed straight to `upload-file`: it is `ui_loaded_files`,
    the session's own list of what it has read.

    `has_data` (`ui_has_data`) decides one thing only: a session that holds
    nothing opens the dialog by itself, once, on mount. There is nothing
    else to do on an empty session, and every panel button is disabled
    until something is in.

    `osdu_explorer` (the `osdu_explorer` state) and the `osdu_scan` /
    `osdu_find` / `osdu_search` / `osdu_kinds` events are handed verbatim to `upload-osdu`:
    the dataspace explorer, see UploadOsdu. The dialog widens while the
    explorer's table is on screen.
    """

    def __init__(self, **kwargs):
        super().__init__("upload-data", **kwargs)
        self._attr_names += [
            "upload_url",
            "session_id",
            "accept",
            "loaded_files",
            "has_data",
            "etp_connected",
            "etp_connecting",
            "etp_step",
            "etp_dataspaces",
            "etp_status",
            "osdu_explorer",
        ]
        self._event_names += [
            "uploaded",
            "error",
            "etp_connect",
            "etp_select",
            "etp_disconnect",
            "osdu_scan",
            "osdu_find",
            "osdu_search",
            "osdu_kinds",
        ]
