"""Tests for trame_fespp_session.controller.

Covers the phases of a saved session (open, wait for the expected files,
restore with a report) and the autosave, which never keeps an empty
session nor a half-restored one."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "session"))
from trame_fespp_session.controller import SessionController  # noqa: E402


class FakeState(dict):
    def __init__(self):
        super().__init__()
        self.watchers = {}

    def __getattr__(self, k):
        return self.get(k)

    def change(self, *names):
        def deco(fn):
            for n in names:
                self.watchers.setdefault(n, []).append(fn)
            return fn
        return deco

    def set(self, k, v):
        self[k] = v
        for fn in self.watchers.get(k, []):
            fn()

    def flush(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeServer:
    def __init__(self):
        self.state = FakeState()


class FakeHost:
    def __init__(self):
        self.files = []
        self.data = True
        self.restored = None

    def app_name(self):
        return "test"

    def has_data(self):
        return self.data

    def loaded_files(self):
        return self.files

    def collect(self):
        return {"sources": {"files": [{"name": "a.epc", "size_mb": 1.0}]},
                "session": {"selected_paths": ["/p"]}, "objects": {},
                "layout": None, "views": [{"id": "view_1", "kind": "render"}]}

    def current_objects(self, paths):
        return {}

    def candidates(self, type_, title):
        return []

    def restore(self, doc, say):
        self.restored = doc
        say("ok", "1 3D view(s) restored.")


def _ctl():
    server, host = FakeServer(), FakeHost()
    return SessionController(server, host), server.state, host


def test_save_gives_a_file_to_download():
    ctl, state, _ = _ctl()
    ctl.save("before the review")
    d = state["ui_session_download"]
    doc = json.loads(d["text"])
    assert d["name"].endswith(".fespp.json") and d["n"] == 1
    assert doc["meta"]["note"] == "before the review" and doc["views"][0]["id"] == "view_1"


def test_an_opened_session_waits_for_its_files_then_is_ready():
    ctl, state, host = _ctl()
    ctl.save()
    ctl.open({"name": "s.fespp.json", "text": state["ui_session_download"]["text"]})
    assert state["ui_session_status"]["phase"] == "waiting"
    assert state["ui_session_status"]["files"][0]["state"] == "missing"
    host.files = [{"name": "a.epc", "size_mb": 1.0}]
    state.set("ui_loaded_files", host.files)          # the expected file is dropped in
    assert state["ui_session_status"]["phase"] == "ready"


def test_restore_ends_with_a_report():
    ctl, state, host = _ctl()
    ctl.save()
    ctl.open({"name": "s.fespp.json", "text": state["ui_session_download"]["text"]})
    ctl.apply()
    st = state["ui_session_status"]
    assert st["phase"] == "done" and host.restored is not None
    assert [r["level"] for r in st["report"]] == ["ok", "ok"]


def test_a_file_that_is_not_a_session_says_why():
    ctl, state, _ = _ctl()
    ctl.open({"name": "x.json", "text": "{}"})
    assert state["ui_session_status"]["phase"] == "error"
    assert "not a fespp-on-trame session" in state["ui_session_status"]["error"]


def test_the_autosave_keeps_a_session_with_data_once_per_change():
    ctl, state, _ = _ctl()
    ctl.autosave_now()
    first = state["ui_session_autosave"]
    assert first["n"] == 1 and first["views"] == 1 and first["files"] == ["a.epc"]
    ctl.autosave_now()                          # nothing changed: nothing pushed
    assert state["ui_session_autosave"]["n"] == 1


def test_an_empty_session_never_overwrites_the_autosave():
    ctl, state, host = _ctl()
    ctl.autosave_now()
    host.data = False
    host.collect = lambda: {"views": []}
    ctl.autosave_now()
    assert state["ui_session_autosave"]["views"] == 1


def test_no_autosave_in_the_middle_of_a_restore():
    ctl, state, _ = _ctl()
    ctl.save()
    ctl.open({"name": "s.fespp.json", "text": state["ui_session_download"]["text"]})
    ctl.autosave_now()
    assert state["ui_session_autosave"] == {}


# a dataspace as the app records it: the URI the store loads (the format
# turns a plain name into it, 867b96a)
DS1 = "eml:///dataspace('ds1')"


class EtpHost(FakeHost):
    etp_watch = ("etp_connected", "ui_etp_loaded_dataspaces")

    def __init__(self):
        super().__init__()
        self.connected, self.loaded, self.asked = False, [], []

    def collect(self):
        doc = super().collect()
        doc["sources"] = {"files": [], "etp": {"url": "wss://osdu", "partition": "p",
                                               "dataspaces": [DS1]}}
        return doc

    def etp_state(self):
        return {"connected": self.connected, "loaded": self.loaded}

    def etp_resume(self, dataspaces):
        self.asked += list(dataspaces)


def test_an_osdu_session_prefills_the_form_never_a_token_and_waits_for_it():
    server, host = FakeServer(), EtpHost()
    ctl = SessionController(server, host)
    state = server.state
    ctl.save()
    text = state["ui_session_download"]["text"]
    assert "token" not in text.lower()
    ctl.open({"name": "s.fespp.json", "text": text})
    assert state["ui_session_etp_prefill"] == {"url": "wss://osdu", "partition": "p"}
    assert state["ui_session_status"]["phase"] == "waiting"
    host.connected = True                        # the token is typed in the form
    state.set("etp_connected", True)
    assert host.asked == [DS1]                   # the dataspace asked for, once
    state.set("etp_connected", True)
    assert host.asked == [DS1]
    host.loaded = [DS1]
    state.set("ui_etp_loaded_dataspaces", [DS1])
    # the data is back: the session restores by itself, nothing is asked
    st = state["ui_session_status"]
    assert st["phase"] == "done" and host.restored is not None


def test_the_autosave_collects_without_the_reader_s_citations_when_the_host_can():
    """The autosave collects without querying the reader for citations.

    A reader query followed by the first read of a time step makes the
    next render crash, and the autosave runs after every render, so it
    never queries: a host whose `collect` takes `citations` gets False, a
    host without that parameter is called as is. A save by hand still
    asks for the citations."""
    ctl, state, host = _ctl()
    seen = []

    def collect(citations=True):
        seen.append(citations)
        return FakeHost.collect(host)
    host.collect = collect
    ctl.autosave_now()
    assert seen == [False]
    ctl.save("by hand")
    assert seen == [False, True]


# ------------------------------------------------- the API's partial document
class FakeHostWithFiles(FakeHost):
    """A host that reads a file named by a server path, as the application's does."""
    def __init__(self):
        super().__init__()
        self.loaded_paths = []

    def load_file(self, path):
        self.loaded_paths.append(path)
        self.files.append({"name": path.rsplit("/", 1)[-1], "size_mb": 1.0})
        return True


def test_a_partial_document_reads_its_file_and_applies_by_itself():
    """The API's document (the PO, 21/10): no reader to click Apply, so it
    applies as soon as its sources are there — a file by server path is
    read by the host first."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "session"))
    from trame_fespp_session import format as sf
    server, host = FakeServer(), FakeHostWithFiles()
    ctl = SessionController(server, host)
    doc = sf.document({"sources": {"files": [{"name": "a.epc", "path": "/deploy/data/a.epc"}]},
                       "session": {"selected_paths": ["/p"]}})
    ctl.open_document(doc, name="document")
    assert host.loaded_paths == ["/deploy/data/a.epc"]
    st = server.state["ui_session_status"]
    assert st["phase"] == "done" and host.restored is doc
    assert any(r["text"] == "Session restored." for r in st["report"])


def test_a_partial_document_waiting_for_a_token_applies_once_connected():
    server, host = FakeServer(), FakeHost()
    ctl = SessionController(server, host)
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "session"))
    from trame_fespp_session import format as sf
    host.etp_state = lambda: {"connected": False, "loaded": []}
    host.etp_resume = lambda ds: None
    doc = sf.document({"sources": {"etp": {"url": "wss://x/", "dataspaces": ["d/s"]}}})
    ctl.open_document(doc, name="document")
    assert server.state["ui_session_status"]["phase"] == "waiting"
    assert server.state["ui_session_etp_prefill"] == {"url": "wss://x/", "partition": ""}
    assert host.restored is None
