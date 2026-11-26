"""Tests for the OSDU dataspace explorer (engine/osdu_explorer).

Covers the REST facade found beside the ETP endpoint, the rows merged from
the facade and the ETP list, the facts summed from the type counts, the
EPSG codes read off a CRS and the catalogue search, all on recorded
answers with no network."""
import io
import json
import urllib.error

import pytest

from fespp_on_trame.engine import osdu_explorer as ex


def test_the_rest_facade_and_the_search_sit_beside_the_etp_endpoint():
    assert ex.rest_base("wss://admeinterop.energy.azure.com/api/reservoir-ddms-etp/v2/") == \
        "https://admeinterop.energy.azure.com/api/reservoir-ddms/v2"
    assert ex.rest_base("wss://host:443/api/reservoir-ddms-etp/v2") == "https://host:443/api/reservoir-ddms/v2"
    assert ex.search_url("wss://host/api/reservoir-ddms-etp/v2/") == "https://host/api/search/v2/query"
    # a bare open-etp-server, or an /oetp/ path: no facade known
    assert ex.rest_base("wss://osdu-ship.msft-osdu-test.org:443/oetp/reservoir-ddms/") is None
    assert ex.rest_base("ws://localhost:9002") is None
    assert ex.rest_base("") is None


def test_a_dataspace_uri_and_its_path_go_both_ways():
    assert ex.dataspace_path("eml:///dataspace('demo/Volve')") == "demo/Volve"
    assert ex.dataspace_path("demo/Volve") == "demo/Volve"
    assert ex.dataspace_uri("demo/Volve") == "eml:///dataspace('demo/Volve')"
    assert ex.dataspace_path(ex.dataspace_uri("o'neil/x")) == "o'neil/x"


class _Opener:
    """urlopen on a table of answers: {(method, url without query): payload}."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, req, timeout=None):
        url = req.full_url.split("?")[0]
        self.calls.append((req.get_method(), req.full_url, req.headers.get("Authorization")))
        if (req.get_method(), url) not in self.answers:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"no such route"))
        body = json.dumps(self.answers[(req.get_method(), url)]).encode("utf-8")
        return _Response(body)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


BASE = "https://h/api/reservoir-ddms/v2"
FACADE_LIST = [
    {"uri": "eml:///dataspace('demo/Volve')", "path": "demo/Volve", "storeLastWrite": "2026-09-23T14:04:58.431Z",
     "customData": {"size": {"values": ["12345678"]}, "locked": {"values": ["false"]}, "read-only": {"values": ["true"]}}},
    {"uri": "eml:///dataspace('carl/teapot')", "path": "carl/teapot", "storeLastWrite": "2026-09-17T20:00:49.289Z",
     "customData": {"size": "42", "locked": "true"}},
]


def test_the_rows_merge_the_facade_s_dates_and_sizes_with_the_etp_list():
    rest = ex.Rest(BASE, "https://h/api/search/v2/query", "opendes", "tok", opener=_Opener({("GET", BASE + "/dataspaces"): FACADE_LIST}))
    rows = ex.list_dataspaces(rest, ["eml:///dataspace('carl/teapot')", "eml:///dataspace('new/one')"])
    assert [r["path"] for r in rows] == ["carl/teapot", "new/one", "demo/Volve"]   # the ETP order first
    teapot, new, volve = rows
    assert teapot["project"] == "carl" and teapot["name"] == "teapot" and teapot["size"] == 42 and teapot["locked"]
    assert volve["size"] == 12345678 and volve["read_only"] and not volve["locked"] and volve["last_write"].startswith("2026-09-23")
    assert new["last_write"] is None and new["size"] is None and new["uri"] == "eml:///dataspace('new/one')"
    assert all(r["facts"] is None for r in rows)
    assert rest.headers["Authorization"] == "Bearer tok" and rest.headers["data-partition-id"] == "opendes"


def test_the_size_is_read_as_bytes_from_a_number_or_the_facade_s_words():
    assert ex.size_bytes("514 MB") == 514_000_000 and ex.size_bytes("232 kB") == 232_000
    assert ex.size_bytes("13 MB") == 13_000_000 and ex.size_bytes("1.5 GB") == 1_500_000_000
    assert ex.size_bytes(42) == 42 and ex.size_bytes("42") == 42 and ex.size_bytes("") is None
    assert ex.size_bytes("big") is None and ex.size_bytes(None) is None


def test_without_the_facade_the_rows_are_the_names_etp_listed():
    rows = ex.names_only(["eml:///dataspace('demo/Volve')", "eml:///", "eml:///dataspace('demo/Volve')"])
    assert [r["path"] for r in rows] == ["demo/Volve"] and rows[0]["project"] == "demo"


def test_the_facts_are_summed_from_the_type_counts():
    types = [{"name": "resqml20.obj_IjkGridRepresentation", "count": 2}, {"name": "resqml22.UnstructuredGridRepresentation", "count": 1},
             {"name": "resqml20.obj_DeviationSurveyRepresentation", "count": 31}, {"name": "resqml20.obj_ContinuousProperty", "count": 1668},
             {"name": "resqml20.obj_CategoricalProperty", "count": 39}, {"name": "resqml20.obj_Grid2dRepresentation", "count": 12},
             {"name": "resqml20.obj_HorizonInterpretation", "count": 399}, {"name": "resqml20.obj_FaultInterpretation", "count": 168},
             {"name": "resqml20.obj_LocalDepth3dCrs", "count": 2}]
    f = ex.summarise(types)
    assert (f["grids"], f["wells"], f["properties"], f["surfaces"], f["horizons"], f["faults"]) == (3, 31, 1707, 12, 399, 168)
    assert f["objects"] == 2322
    assert ex.summarise(None) == {"objects": 0, "grids": 0, "wells": 0, "properties": 0, "surfaces": 0, "horizons": 0, "faults": 0}


def test_the_epsg_codes_are_read_off_the_crs_json():
    crs = {"$type": "resqml20.obj_LocalDepth3dCrs", "ProjectedCrs": {"$type": "eml20.ProjectedCrsEpsgCode", "EpsgCode": 23031},
           "VerticalCrs": {"$type": "eml20.VerticalCrsEpsgCode", "EpsgCode": "5714"}, "ExtraMetadata": [{"Name": "EpsgCode", "Value": "x"}]}
    assert ex.epsg_codes(crs) == [23031, 5714]
    assert ex.epsg_codes({"ProjectedCrs": {"$type": "eml20.ProjectedUnknownCrs", "Unknown": "local"}}) == []


def test_the_facts_of_a_dataspace_take_the_counts_then_the_crs():
    ds = BASE + "/dataspaces/demo%2FVolve"
    answers = {("GET", ds + "/resources"): [{"name": "resqml20.obj_IjkGridRepresentation", "count": 2},
                                            {"name": "resqml20.obj_LocalDepth3dCrs", "count": 1}],
               ("GET", ds + "/resources/resqml20.obj_LocalDepth3dCrs"): [{"uri": "eml:///dataspace('demo/Volve')/resqml20.obj_LocalDepth3dCrs(9cfa891b-1)"}],
               ("GET", ds + "/resources/resqml20.obj_LocalDepth3dCrs/9cfa891b-1"): {"ProjectedCrs": {"EpsgCode": 23031}}}
    opener = _Opener(answers)
    facts = ex.dataspace_facts(ex.Rest(BASE, None, "p", "t", opener=opener), "demo/Volve")
    assert facts["grids"] == 2 and facts["epsg"] == [23031] and facts["error"] is None
    # only the CRS types the counts name are asked: three calls, not five
    assert len(opener.calls) == 3
    # a dataspace without a CRS costs the one call
    opener2 = _Opener({("GET", ds + "/resources"): [{"name": "resqml20.obj_IjkGridRepresentation", "count": 2}]})
    facts = ex.dataspace_facts(ex.Rest(BASE, None, "p", "t", opener=opener2), "demo/Volve")
    assert facts["epsg"] == [] and len(opener2.calls) == 1


def test_a_refused_call_is_an_error_with_the_server_s_words():
    rest = ex.Rest(BASE, None, "p", "t", opener=_Opener({}))
    with pytest.raises(ex.OsduError, match="404 .*no such route"):
        rest.get("/dataspaces")


def test_the_catalogue_search_names_dataspaces_and_components():
    q = "https://h/api/search/v2/query"
    seen = []

    def opener(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        seen.append(body)
        if "ETPDataspace" in body["kind"]:
            out = {"totalCount": 1, "results": [{"data": {"Name": "carl/teapot", "DatasetProperties.URI": "eml:///dataspace('carl/teapot')"}}]}
        else:
            out = {"totalCount": 3, "results": [
                {"kind": "osdu:wks:work-product-component--IjkGridRepresentation:1.0.0", "data": {"Name": "Drogon DG2 - Geogrid",
                 "Datasets": ["opendes:dataset--ETPDataspace:carl-teapot:"]}},
                {"kind": "osdu:wks:work-product-component--Activity:1.0.0", "data": {"Name": "Drogon run"}},
                {"kind": "osdu:wks:work-product-component--HorizonInterpretation:1.0.0", "data": {"Name": "Hugin top",
                 "DDMSDatasets": ["eml://reservoir-ddms1/dataspace('carl/volve_horizons')/resqml20.obj_HorizonInterpretation(9f75)"]}}]}
        return _Response(json.dumps(out).encode("utf-8"))
    rest = ex.Rest(BASE, q, "p", "t", opener=opener)
    out = ex.catalogue_search(rest, "Drogon DG2")
    assert out["total"] == 4
    # the named dataspace first (with what the components say of it), then
    # the dataspaces the components live in, each summarised
    assert out["dataspaces"] == [
        {"name": "carl/teapot", "uri": "eml:///dataspace('carl/teapot')", "components": 1,
         "kinds": [{"kind": "IjkGridRepresentation", "count": 1}], "names": ["Drogon DG2 - Geogrid"]},
        {"name": "carl/volve_horizons", "uri": "eml:///dataspace('carl/volve_horizons')", "components": 1,
         "kinds": [{"kind": "HorizonInterpretation", "count": 1}], "names": ["Hugin top"]}]
    assert out["components"][0] == {"name": "Drogon DG2 - Geogrid", "kind": "IjkGridRepresentation", "dataspace": "carl/teapot", "count": 1}
    assert out["components"][1]["dataspace"] is None
    # the manifest's DDMSDatasets uri names the dataspace exactly
    assert out["components"][2] == {"name": "Hugin top", "kind": "HorizonInterpretation", "dataspace": "carl/volve_horizons", "count": 1}
    assert seen[0]["query"] == "data.Name:Drogon* AND data.Name:DG2*"
    assert ex.lucene_text("") == "" and ex.catalogue_search(rest, "  ") == {"total": 0, "dataspaces": [], "components": []}
    assert ex.lucene_text("a-b (c)") == r"data.Name:a\-b* AND data.Name:\(c\)*"
    # a code of digits is also an EPSG code, matched exactly on the CRS id
    q = ex.lucene_text("23031", "opendes")
    assert q.startswith("(data.Name:23031* OR data.SpatialPoint.AsIngestedCoordinates.CoordinateReferenceSystemID:"
                        '"opendes:reference-data--CoordinateReferenceSystem:Projected:EPSG::23031:"')
    assert "Vertical:EPSG::23031:" in q and q.endswith(")")


# ---- the ETP inventory of a dataspace (the plugin's channel, 2026-10-10) ----
def test_the_inventory_lines_are_parsed_and_the_kinds_summed():
    ds = "eml:///dataspace('demo/Volve')"
    lines = ["#info|objects=4|fetched=4|from_cache=0|names_only=0|unreadable=0|seconds=1.20|store_last_write=5",
             f"{ds}/resqml20.obj_ContinuousProperty(a1)|resqml20.obj_ContinuousProperty|a1|porosity|PORO",
             f"{ds}/resqml20.obj_ContinuousProperty(a2)|resqml20.obj_ContinuousProperty|a2|porosity|PHIE|eff",
             f"{ds}/resqml22.DiscreteProperty(a3)|resqml22.DiscreteProperty|a3||ZONES",
             f"{ds}/resqml20.obj_PropertyKind(k1)|resqml20.obj_PropertyKind|k1||porosity"]
    got = ex.parse_inventory(lines)
    assert got["error"] is None and got["info"]["objects"] == "4" and got["info"]["seconds"] == "1.20"
    # the title comes last: it keeps its "|"
    assert [o["title"] for o in got["objects"]] == ["PORO", "PHIE|eff", "ZONES", "porosity"]
    assert ex.short_type("resqml20.obj_ContinuousProperty") == ex.short_type("resqml22.ContinuousProperty") == "ContinuousProperty"
    # the summary counts the PROPERTIES: the PropertyKind object is not one
    assert ex.kinds_summary(got["objects"]) == {"total": 3, "kinds": [{"kind": "porosity", "count": 2}], "unknown": 1}
    assert ex.kind_rows(got["objects"]) == [("ContinuousProperty", "PORO", "porosity"),
                                            ("ContinuousProperty", "PHIE|eff", "porosity")]
    assert ex.parse_inventory(["#error|no open ETP session"])["error"] == "no open ETP session"
    assert ex.parse_inventory([])["error"]


def test_the_search_finds_a_property_by_its_kind_once_read():
    rows = [{"uri": "eml:///dataspace('demo/Volve')", "path": "demo/Volve", "project": "demo", "name": "Volve",
             "last_write": "2026-09-23"}]
    rest = [("ContinuousProperty", "PORO"), ("ContinuousProperty", "PHIE"), ("IjkGridRepresentation", "Volve_SGrid")]
    kinds = [("ContinuousProperty", "PORO", "porosity"), ("ContinuousProperty", "PHIE", "porosity")]
    # the facade's property rows give way to the plugin's: a property once
    merged = ex.merge_inventories(rest, kinds)
    assert merged == [("IjkGridRepresentation", "Volve_SGrid")] + kinds
    assert ex.merge_inventories(rest, []) == rest
    found = ex.find("porosity", rows, {"demo/Volve": merged})
    assert found["total"] == 1 and found["results"][0]["why"] == ["2 properties of kind porosity"]
    assert found["results"][0]["objects"][0] == {"type": "ContinuousProperty", "name": "PORO"}
    # without the kinds the word finds nothing: PORO is not spelled porosity
    assert ex.find("porosity", rows, {"demo/Volve": rest})["total"] == 0
    # the kind: filter
    assert ex.find("kind:poro", rows, {"demo/Volve": merged})["results"][0]["why"] == ["2 properties of kind porosity"]
    assert ex.find("kind:perm", rows, {"demo/Volve": merged})["total"] == 0
    # the PropertyKind objects the facade lists are searchable by name: the
    # kinds a dataspace defines, before any inventory
    assert ex.find("porosity", rows, {"demo/Volve": [("PropertyKind", "porosity")]})["results"][0]["why"] == ["kind porosity"]


def test_the_search_finds_the_dataspaces_changed_since_the_last_visit():
    """"modified", "nouveau": the rows boot marked `changed` from its memory
    of the server (written since this process last listed it, or new);
    nothing without the mark, whatever the name."""
    rows = [{"uri": "eml:///dataspace('demo/Volve')", "path": "demo/Volve", "project": "demo", "name": "Volve",
             "last_write": "2026-10-12", "changed": True},
            {"uri": "eml:///dataspace('demo/Drogon')", "path": "demo/Drogon", "project": "demo", "name": "Drogon",
             "last_write": "2026-09-23", "changed": False},
            {"uri": "eml:///dataspace('demo/New')", "path": "demo/New", "project": "demo", "name": "New"}]
    for text in ("modified", "modifié", "nouveau", "changed"):
        found = ex.find(text, rows, {})
        assert [r["path"] for r in found["results"]] == ["demo/Volve"], text
        assert found["results"][0]["why"] == ["changed since the last visit"]
