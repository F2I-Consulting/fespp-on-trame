"""trame_fespp_session.format: the `.fespp.json` session file — reading it,
the files it expects, what changed in the data since the save, and the
renaming of the views' ids in a new session."""
import sys
from pathlib import Path

import pytest

# Import the widget package from the source tree, not an installed copy that may be older.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "widgets" / "session"))
from trame_fespp_session import format as sf  # noqa: E402


def test_a_saved_document_reads_back():
    doc = {"schema": 1, "views": [{"id": "view_1", "kind": "render"}]}
    back = sf.loads(sf.dumps(doc))
    assert back["views"] == doc["views"] and back["objects"] == {}


@pytest.mark.parametrize("text, words", [
    ("not json", "not JSON"),
    ('{"a": 1}', "not a fespp-on-trame session"),
    ('{"schema": 99, "views": []}', "newer version"),
])
def test_what_cannot_be_read_says_why(text, words):
    with pytest.raises(sf.SessionFileError, match=words):
        sf.loads(text)


def test_expected_files_are_matched_by_name_and_size():
    rows = sf.file_states(
        [{"name": "a.epc", "size_mb": 7.7}, {"name": "b.epc", "size_mb": 1.0},
         {"name": "c.epc", "size_mb": 2.0}],
        [{"name": "a.epc", "size_mb": 7.7}, {"name": "b.epc", "size_mb": 3.0}])
    assert [r["state"] for r in rows] == ["loaded", "different", "missing"]
    assert "not the same size" in rows[1]["why"]


XML = """<resqml2:ContinuousProperty><eml20:Citation>
<eml20:Title>GasSat</eml20:Title><eml20:Originator>carl</eml20:Originator>
<eml20:Creation xsi:type="xsd:dateTime">2024-04-11T16:08:09Z</eml20:Creation>
<eml20:Format>Aspen SKUA V15</eml20:Format></eml20:Citation></resqml2:ContinuousProperty>"""


def test_the_citation_is_read_whatever_the_prefix():
    c = sf.citation_of(XML)
    assert c["creation"] == "2024-04-11T16:08:09Z" and c["title"] == "GasSat"
    assert c["format"] == "Aspen SKUA V15" and c["last_update"] == ""


def _obj(**kw):
    base = {"uuid": "u1", "type": "ContinuousProperty", "title": "GasSat",
            "creation": "2024-04-11T16:08:09Z", "last_update": "", "version": "",
            "format": "SKUA"}
    base.update(kw)
    return base


def test_an_unchanged_object_says_nothing():
    assert sf.compare_objects({"/p": _obj()}, {"/p": _obj()}) == []


def test_an_edited_object_is_reported_with_what_moved():
    out = sf.compare_objects({"/p": _obj()}, {"/p": _obj(last_update="2026-01-02T00:00:00Z")})
    assert out[0]["level"] == "warn" and "last_update" in out[0]["text"]


def test_an_older_object_is_probably_not_the_same_data():
    out = sf.compare_objects({"/p": _obj()}, {"/p": _obj(creation="2020-01-01T00:00:00Z")})
    assert "OLDER" in out[0]["text"]


def test_a_reexported_object_is_offered_as_a_replacement_not_applied():
    out = sf.compare_objects({"/p": _obj()}, {},
                             candidates=lambda t, n: ["/q"] if n == "GasSat" else [])
    assert out[0]["replacement"] == "/q" and out[0]["level"] == "warn"


def test_a_vanished_object_is_skipped():
    out = sf.compare_objects({"/p": _obj()}, {})
    assert out[0]["level"] == "error" and "skipped" in out[0]["text"]


def test_paths_the_data_lost_are_dropped_derived_ones_kept():
    kept, dropped = sf.keep_known(["/a", "/b", "derived:///x#y"], {"/a"})
    assert kept == ["/a", "derived:///x#y"] and dropped == ["/b"]


def test_view_ids_are_renamed_all_at_once():
    layout = {"panels": {"view_1": {"id": "view_1"}, "view_2": {"id": "view_2"}},
              "grid": {"root": {"data": [{"views": ["view_1", "view_2"]}]}}}
    out = sf.remap_ids(layout, {"view_1": "view_3", "view_2": "view_1"})
    assert set(out["panels"]) == {"view_3", "view_1"}
    assert out["panels"]["view_3"]["id"] == "view_3"
    assert out["grid"]["root"]["data"][0]["views"] == ["view_3", "view_1"]
    assert sf.layout_ids(out) == ["view_3", "view_1"]


def test_the_layout_s_template_names_follow_the_ids():
    layout = {"panels": {"view_2": {"id": "view_2", "params": {"templateName": "view_2_template"}}}}
    out = sf.remap_ids(layout, sf.panel_mapping({"view_2": "view_5"}))
    assert out["panels"]["view_5"]["params"]["templateName"] == "view_5_template"


def test_an_etp_session_is_ready_once_connected_and_every_dataspace_loaded():
    saved = {"url": "wss://osdu", "partition": "p", "dataspaces": ["a", "b"]}
    st, ready, missing = sf.etp_state(saved, False, [])
    assert not ready and missing == ["a", "b"] and st["connected"] is False
    st, ready, missing = sf.etp_state(saved, True, ["a"])
    assert not ready and missing == ["b"] and st["loaded"] == ["a"]
    assert sf.etp_state(saved, True, ["b", "a"])[1] is True
    assert sf.etp_state(None, False, []) == (None, True, [])


# ---------------------------------------------------------- the API's document
def test_a_partial_document_keeps_only_the_groups_it_names():
    """The API's document (the PO, 21/10): an absent group is absent — the
    host leaves that part of the session alone — a present one is kept as
    given, `reset` and `schema` take their defaults."""
    doc = sf.document({"session": {"selected_paths": ["/a"]}, "views": []})
    assert doc["partial"] is True and doc["reset"] is False and doc["schema"] == sf.SCHEMA
    assert "sources" not in doc and "layout" not in doc and "objects" not in doc
    assert doc["views"] == [] and doc["session"] == {"selected_paths": ["/a"]}
    assert sf.document({"reset": True})["reset"] is True


@pytest.mark.parametrize("obj, words", [
    ([], "JSON object"),
    ({"views": {}}, "views is not a list"),
    ({"session": []}, "session is not an object"),
    ({"schema": 99}, "newer version"),
    ({"views": [{"kind": "stats", "place": "left"}]}, "right or below"),
])
def test_a_wrong_document_says_what_is_wrong(obj, words):
    with pytest.raises(sf.SessionFileError, match=words):
        sf.document(obj)


def test_a_view_s_place_is_right_or_below():
    """The PO's document of 22/10: the 3D view on the left, Statistics on
    its right — `place` on the paragraph, no dockview layout to write."""
    doc = sf.document({"views": [{"kind": "render"}, {"kind": "stats", "place": "right"}]})
    assert [v.get("place") for v in doc["views"]] == [None, "right"]


def test_a_dataspace_named_plainly_becomes_the_uri_the_store_loads():
    """The ADME test of 21/10: `demo/Volve` is "Invalid URI" for the store,
    which loads `eml:///dataspace('demo/Volve')` — the form the app records."""
    doc = sf.document({"sources": {"etp": {"url": "wss://x/", "dataspaces": ["demo/Volve", "eml:///dataspace('a/b')"]}}})
    assert doc["sources"]["etp"]["dataspaces"] == ["eml:///dataspace('demo/Volve')", "eml:///dataspace('a/b')"]
    assert sf.etp_dataspace_uri(" x/y ") == "eml:///dataspace('x/y')" and sf.etp_dataspace_uri("") == ""


def test_a_file_still_needs_its_schema_and_views():
    with pytest.raises(sf.SessionFileError, match="no schema or views"):
        sf.document({"session": {}}, partial=False)
    doc = sf.document({"schema": 1, "views": []}, partial=False)
    assert doc["partial"] is False and doc["objects"] == {} and doc["layout"] is None


def test_uuids_become_the_paths_the_data_gives_them():
    known = {"aaa": "/data/_gridfolder_aaa", "bbb": "/data/_gridfolder_aaa/_propsfolder_aaa/_bbb"}
    doc = {"session": {"selected_paths": ["uuid:aaa", "uuid:bbb", "/kept"]},
           "views": [{"kind": "render", "eyes": ["uuid:bbb", "uuid:zzz"]}],
           "objects": {"uuid:aaa": {"type": "IjkGrid"}}}
    out, missing = sf.resolve_uuids(doc, known.get)
    assert out["session"]["selected_paths"] == [known["aaa"], known["bbb"], "/kept"]
    assert out["views"][0]["eyes"] == [known["bbb"], "uuid:zzz"]
    assert list(out["objects"]) == [known["aaa"]]
    assert missing == ["zzz"]
    assert doc["session"]["selected_paths"][0] == "uuid:aaa"   # the input is left as it was
    # typed by hand (the PO, 21/10): a space after the prefix, braces, the
    # same unknown uuid twice
    out, missing = sf.resolve_uuids(["uuid: aaa", "UUID:{bbb}", "uuid: zzz", "uuid:zzz "], known.get)
    assert out == [known["aaa"], known["bbb"], "uuid: zzz", "uuid:zzz "] and missing == ["zzz"]
