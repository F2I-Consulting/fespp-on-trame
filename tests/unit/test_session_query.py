"""engine/session_query: the page's query as a session document — an EPC
under the open directory, an ETP store with its dataspaces, uuids read and
shown; nothing else leaves the directory."""
import pytest

from fespp_on_trame.engine import session_query as sq


def test_an_epc_and_uuids_make_a_document_that_reads_and_shows_them():
    doc = sq.document_from_query("?epc=private/drogon.epc&uuid=aaa&uuid=bbb", root="/deploy/data")
    assert doc["sources"]["files"] == [{"name": "drogon.epc", "path": "/deploy/data/private/drogon.epc"}]
    assert doc["session"]["selected_paths"] == ["uuid:aaa", "uuid:bbb"]
    assert doc["views"] == [{"kind": "render", "eyes": ["uuid:aaa", "uuid:bbb"]}]


def test_an_etp_store_names_its_dataspaces_and_never_a_token():
    doc = sq.document_from_query("etp=wss%3A%2F%2Fhost%2Fetp%2F&dataspace=demo%2FVolve&dataspace=x%2Fy")
    assert doc["sources"]["etp"] == {"url": "wss://host/etp/", "partition": "",
                                     "dataspaces": ["demo/Volve", "x/y"]}
    assert "session" not in doc
    # the store's data partition (the PO's link of 22/10 left it to type)
    doc = sq.document_from_query("etp=wss://host/etp/&dataspace=demo/Volve&partition=opendes")
    assert doc["sources"]["etp"]["partition"] == "opendes"
    with pytest.raises(sq.QueryError, match="dataspace"):
        sq.document_from_query("?etp=wss://host/etp/")


@pytest.mark.parametrize("name, path", [
    ("private/drogon.epc", "/deploy/data/private/drogon.epc"),
    ("/deploy/data/private/drogon.epc", "/deploy/data/private/drogon.epc"),
    ("/deploy/data/x/../drogon.epc", "/deploy/data/drogon.epc"),
])
def test_a_document_s_file_is_a_server_path_under_the_open_directory(name, path):
    assert sq.server_path(name, "/deploy/data") == path


@pytest.mark.parametrize("name", ["/etc/passwd", "/deploy/data2/x.epc", "/deploy/data/../x.epc", "../x.epc", "C:/x.epc"])
def test_a_document_s_file_outside_the_open_directory_is_refused(name):
    with pytest.raises(sq.QueryError, match="open directory"):
        sq.server_path(name, "/deploy/data")


def test_a_plain_page_asks_for_nothing_and_a_state_url_is_handed_back():
    assert sq.document_from_query("") is None
    assert sq.document_from_query("?foo=1") is None
    assert sq.document_from_query("?state=https://x/y.json") == {"state_url": "https://x/y.json"}


@pytest.mark.parametrize("name", ["../etc/passwd", "/etc/passwd", "C:/x.epc", "a/../../b.epc", ""])
def test_a_name_that_leaves_the_open_directory_is_refused(name):
    with pytest.raises(sq.QueryError, match="open directory"):
        sq.epc_path(name, root="/deploy/data")


def test_the_open_directory_is_the_environment_s(monkeypatch):
    monkeypatch.setenv(sq.OPEN_DIR_VAR, "/tmp/testdata")
    assert sq.epc_path("drogon.epc") == "/tmp/testdata/drogon.epc"
    monkeypatch.delenv(sq.OPEN_DIR_VAR)
    assert sq.epc_path("x/y.epc") == "/deploy/data/x/y.epc"
