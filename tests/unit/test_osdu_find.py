"""The OSDU explorer's search (engine/osdu_explorer): the inventory read off
the facade, the terms of the search box, and the ranking with its reasons."""
from fespp_on_trame.engine import osdu_explorer as ex

ROWS = [
    {"uri": "eml:///dataspace('demo/Volve')", "path": "demo/Volve", "project": "demo", "name": "Volve",
     "last_write": "2026-09-23T14:04:58Z", "facts": {"grids": 2, "wells": 75, "properties": 1710, "epsg": [23031]}},
    {"uri": "eml:///dataspace('carl/teapot')", "path": "carl/teapot", "project": "carl", "name": "teapot",
     "last_write": "2026-09-17T20:00:49Z", "facts": {"grids": 1, "wells": 5, "properties": 72, "epsg": [32056]}},
    {"uri": "eml:///dataspace('geosiris/test')", "path": "geosiris/test", "project": "geosiris", "name": "test",
     "last_write": "2025-09-29T00:00:00Z", "facts": None},
]
INV = {
    "demo/Volve": [("IjkGridRepresentation", "Volve_SGrid"), ("ContinuousProperty", "PORO"), ("ContinuousProperty", "PERMX"),
                   ("WellboreTrajectoryRepresentation", "15/9-F-1"), ("HorizonInterpretation", "Top Hugin")],
    "carl/teapot": [("IjkGridRepresentation", "Teapot grid"), ("ContinuousProperty", "Porosity"), ("FaultInterpretation", "F1")],
}


def test_the_terms_of_the_box_are_words_and_typed_filters():
    assert ex.parse_query("PORO epsg:23031 type:IjkGrid since:2026-06 Éole") == \
        [("word", "poro"), ("epsg", "23031"), ("type", "ijkgrid"), ("since", "2026-06"), ("word", "eole")]
    assert ex.parse_query("") == []


def test_a_property_name_finds_its_dataspaces_and_says_why():
    out = ex.find("PORO", ROWS, INV)
    assert [r["path"] for r in out["results"]] == ["demo/Volve", "carl/teapot"]   # the exact name first
    volve = out["results"][0]
    assert volve["why"] == ["property PORO"] and volve["objects"] == [{"type": "ContinuousProperty", "name": "PORO"}]
    assert out["results"][1]["why"] == ["property Porosity"]
    assert out["total"] == 2 and out["status"] == "done"


def test_every_term_must_hold_and_the_reasons_add_up():
    out = ex.find("volve 23031", ROWS, INV)
    assert [r["path"] for r in out["results"]] == ["demo/Volve"]
    # the word "volve" also names the grid Volve_SGrid: one reason line per term
    assert out["results"][0]["why"][0].startswith("named Volve") and out["results"][0]["why"][1] == "EPSG 23031"
    assert ex.find("volve 32056", ROWS, INV)["total"] == 0


def test_a_type_a_facet_word_and_a_well_name_are_found():
    assert [r["path"] for r in ex.find("type:ijkgrid", ROWS, INV)["results"]] == ["demo/Volve", "carl/teapot"]
    wells = ex.find("puits", ROWS, INV)
    assert [r["path"] for r in wells["results"]] == ["demo/Volve", "carl/teapot"] and wells["results"][0]["why"] == ["75 wells"]
    well = ex.find("15/9-F-1", ROWS, INV)
    assert well["total"] == 1 and well["results"][0]["why"] == ["well 15/9-F-1"]
    assert ex.find("hugin", ROWS, INV)["results"][0]["why"] == ["horizon Top Hugin"]


def test_dates_and_projects_filter():
    assert [r["path"] for r in ex.find("since:2026-09-20", ROWS, INV)["results"]] == ["demo/Volve"]
    assert [r["path"] for r in ex.find("project:carl", ROWS, INV)["results"]] == ["carl/teapot"]
    assert ex.find("nothing-here", ROWS, INV) == {"text": "nothing-here", "status": "done", "total": 0, "results": []}


def test_the_inventory_reads_type_and_name_off_the_flat_list():
    class R:
        def __init__(self):
            self.calls = []

        def get(self, path, **q):
            self.calls.append((path, q))
            return [{"uri": "eml:///dataspace('demo/Volve')/resqml20.obj_ContinuousProperty(a-1)", "name": "PORO"},
                    {"uri": "eml:///dataspace('demo/Volve')/resqml22.IjkGridRepresentation(b-2)", "name": "G"},
                    {"uri": "junk", "name": "?"}]
    r = R()
    assert ex.dataspace_inventory(r, "demo/Volve") == [("ContinuousProperty", "PORO"), ("IjkGridRepresentation", "G"), ("", "?")]
    assert r.calls == [("/dataspaces/demo%2FVolve/resources/all", {"$top": ex.PAGE, "$skip": 0})]


def test_the_plumbing_objects_are_not_reasons():
    inv = {"demo/Volve": [("EpcExternalPartReference", "demo_Volve.h5"), ("Activity", "Volve import")]}
    rows = [dict(ROWS[2], path="demo/Volve", name="x", project="demo", uri="eml:///dataspace('demo/Volve')")]
    assert ex.find("volve", rows, inv)["total"] == 1        # the path still holds the word
    assert ex.find("volve", rows, inv)["results"][0]["why"] == ["in demo/Volve"]


def test_the_catalogue_completes_the_results_and_never_removes_one():
    found = ex.find("23031", ROWS, INV)
    catalogue = {"dataspaces": [{"name": "demo/Volve", "uri": "eml:///dataspace('demo/Volve')", "components": 75},
                                {"name": "old/published", "uri": "eml:///dataspace('old/published')"}]}
    out = ex.merge_catalogue(found, catalogue, ROWS)
    assert [r["path"] for r in out["results"]] == ["demo/Volve", "old/published"]
    assert out["results"][0]["why"] == ["EPSG 23031", "published: 75 components"] and out["results"][0]["published"]
    assert out["results"][1]["why"] == ["published (not listed by the server)"] and out["total"] == 2
    # an empty catalogue leaves the results as they were
    assert ex.merge_catalogue(found, {}, ROWS)["results"] == found["results"]
