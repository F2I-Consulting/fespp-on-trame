from trame_client.widgets.core import AbstractElement, Template

from trame_fespp_session import module

# The `files` slot (where the host mounts its data drop zone) must be
# declared to trame's `Template` before a caller can write
# `v_slot_files=True`: an unregistered name is rendered into the DEFAULT
# slot, and the drop zone never shows where the dialog expects it.
Template.slot_names.add("files")
# The same for the `etp` slot, where the host mounts its prefilled OSDU form.
Template.slot_names.add("etp")


class HtmlElement(AbstractElement):
    def __init__(self, _elem_name, children=None, **kwargs):
        super().__init__(_elem_name, children, **kwargs)
        if self.server:
            self.server.enable_module(module)


__all__ = ["LeaveGuard", "SessionDoor"]


class SessionDoor(HtmlElement):
    """The session door: save the state of the application to a
    ``.fespp.json`` file on the reader's computer, and open one to restore it.

    The file holds the STATE only; the data (EPC + h5, or an OSDU/ETP
    connection) is loaded again, and the dialog guides that. The widget
    draws its own top-bar trigger and its dialog; it knows nothing of the
    application: props in, events out.

    Props:
        has_data    something is loaded — Save is offered only then
        status      {} or {phase, file, saved, note, app, views, files,
                    etp, etp_ready, report, error} — see the README.
                    etp: None or {url, partition, dataspaces: [uri..],
                    connected, loaded: [uri..]} for a session read from
                    OSDU / ETP (never the token); etp_ready: connected and
                    every saved dataspace loaded. "Restore" is enabled only
                    when no file is missing and (no etp or etp_ready);
                    "Restore anyway" goes without what is absent
        download    {} or {name, text, n}: each new ``n`` saves ``text``
                    as the file ``name`` on the reader's computer
        autosave    {} or {text, sig, saved, views, files, n}: each new
                    ``n`` is kept in the browser's local storage, the last
                    state to resume or download should the server be lost
    Events:
        save(note)            the note the reader wrote, may be ""
        open({name, text})    a session file picked or dropped, read as text
        apply()               restore now
        reset()               forget the opened session file
    Slots:
        files       rendered in the "waiting" phase under the expected
                    files: the host's own data drop zone
        etp         rendered in the "waiting" and "ready" phases while
                    ``status.etp_ready`` is false, under the saved
                    dataspaces: the host's OSDU form, prefilled with the
                    URL and partition, where only the token is asked
    """

    def __init__(self, children=None, **kwargs):
        super().__init__("session-door", children, **kwargs)
        self._attr_names += [("has_data", "hasData"), "status", "download", "autosave"]
        self._event_names += ["save", "open", "apply", "reset"]


class LeaveGuard(HtmlElement):
    """The browser's Back caught while something is loaded: a Warning asks
    before the page is left (Stay, or Leave for real). Client-side only.

    Props:
        armed       something is loaded: there is a session to lose
    """

    def __init__(self, **kwargs):
        super().__init__("leave-guard", **kwargs)
        self._attr_names += ["armed"]
