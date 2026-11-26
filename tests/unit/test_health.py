"""Tests for engine/health_dispatch: the log messages, the CRS, the UTM
sanity check, and property values against their kind (over a fake assembly)."""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import health_dispatch as hd
from fespp_on_trame.engine import pwls_kinds as pk
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.utils.numfmt import DASH


class _Tree:
    def __init__(self, by_uuid):
        self.by_uuid = by_uuid

    def find_node_id_by_uuid(self, uuid):
        return self.by_uuid.get(uuid)

    def find_title(self, nid):
        return f"node{nid}"

    def find_path(self, nid):
        return f"/data/_{nid}"


def test_classify_message_keeps_fesapi_wording_and_ranks_it():
    assert hd.classify_message("Error when rendering uuid: 1234", "ERR")[0:2] == ("error", "data")
    assert hd.classify_message("The HDF5 dataset /RESQML/x could not be opened.")[0:2] == ("error", "data")
    assert hd.classify_message("Cannot compute the frame MD 3682.9 because it is out of the trajectory")[0:2] == ("warning", "well")
    assert hd.classify_message("kind cannot be associated ... assumed to be a partial one", "WARN")[0:2] == ("info", "kind")
    assert hd.classify_message("something odd", "ERR")[0:2] == ("warning", "log")
    assert hd.classify_message("just a note", "INFO") is None
    assert hd.classify_message("   ") is None


def test_log_findings_dedupes_and_names_the_object():
    u = "86e5dd99-4f30-4951-812c-6b179a30a779"
    tree = _Tree({u: 7})
    msgs = [{"text": f"FESAPI Error for uuid\n{u} : Cannot compute the frame MD 3682 because it is out of the trajectory", "level": "ERR"},
            {"text": f"FESAPI Error for uuid {u} : Cannot compute the frame MD 3682 because it is out of the trajectory", "level": "ERR"},
            {"text": "noise", "level": "INFO"}]
    out = hd.log_findings(msgs, tree)
    assert len(out) == 1
    assert out[0]["severity"] == "warning" and out[0]["category"] == "well"
    assert out[0]["object"] == "node7" and out[0]["path"] == "/data/_7"


def test_log_findings_counts_the_same_complaint_about_many_objects():
    tree = _Tree({})
    msgs = [{"text": f"vtkEPCCollector (0x{i:x}): The continuous property "
                     f"3099b3c7-2689-4acc-8bba-{i:012d} cannot be associated to a resqml"
                     " property kind \"volume per volume\" which is abstract."
                     " This property will be assumed to be a partial one.", "level": "WARN"}
            for i in range(40)]
    out = hd.log_findings(msgs, tree)
    assert len(out) == 1 and out[0]["count"] == 40 and out[0]["message"].endswith("(×40)")
    assert out[0]["severity"] == "info" and out[0]["category"] == "kind"


def test_log_findings_caps_the_list():
    tree = _Tree({})
    msgs = [{"text": f"odd thing {chr(65 + i % 26)}{'x' * (i // 26)}", "level": "ERR"} for i in range(70)]
    out = hd.log_findings(msgs, tree, limit=60)
    assert len(out) == 61 and out[-1]["message"] == "10 more distinct messages not listed"


def test_utm_sanity_flags_impossible_eastings():
    # 23037 = ED50 / UTM zone 37N
    assert hd.utm_sanity(23037, [450000, 470000, 6400000, 6420000, -3000, 0]) is None
    doubt = hd.utm_sanity(23037, [1200, 5600, 6400000, 6420000, 0, 0])
    assert doubt and "cannot be EPSG:23037" in doubt and "eastings" in doubt
    assert hd.utm_sanity(4326, [1, 2, 3, 4, 5, 6]) is None      # not a UTM code
    assert hd.utm_sanity(None, [1, 2, 3, 4, 5, 6]) is None
    # VTK's empty-geometry bounds (+1e299, -1e299) say nothing about the data
    assert hd.utm_sanity(23037, [1e299, -1e299, 1e299, -1e299, 1e299, -1e299]) is None


def test_crs_findings_each_case():
    assert hd.crs_findings(lambda: (False, None, 0, ""), None)[0]["message"].startswith("no CRS object")
    out = hd.crs_findings(lambda: (False, None, 2, "unknown"), None)
    assert out[0]["severity"] == "warning" and "the CRS says: unknown" in out[0]["message"]
    out = hd.crs_findings(lambda: (True, {"epsg": 23037, "how": "ProjectedCrsEpsgCode", "title": "crs"}, 1, ""),
                          [1200, 5600, 6400000, 6420000, 0, 0])
    assert [f["severity"] for f in out] == ["info", "warning"]
    out = hd.crs_findings(lambda: (False, {"epsg": 23037, "time": True, "title": "t"}, 1, ""), None)
    assert out[0]["severity"] == "warning" and "TIME CRS" in out[0]["message"]


# ---- the values against their kind -----------------------------------------


@pytest.fixture
def kinds():
    pk.use_table({
        "property": [None, ""],
        "volume per volume": ["property", "volume per volume"],
        "volume fraction": ["volume per volume", "volume per volume"],
        "porosity": ["volume fraction", "volume per volume"],
        "total porosity": ["porosity", "volume per volume"],
        "saturation": ["volume fraction", "volume per volume"],
        "water saturation": ["saturation", "volume per volume"],
        "gas oil ratio": ["volume fraction", "volume per volume"],
        "permeability": ["property", "permeability rock"],
        "directional permeability": ["permeability", "permeability rock"],
        "horizontal permeability": ["directional permeability", "permeability rock"],
        "length": ["property", "length"],
        "thickness": ["length", "length"],
        "net thickness": ["thickness", "length"],
        "volume": ["property", "volume"],
        "pore volume": ["volume", "volume"],
        "length per length": ["property", "length per length"],
        "net gross thickness ratio": ["length per length", "length per length"],
        "peak trough delta depth": ["thickness", "length"],
        "facies": ["property", ""],
    })
    yield
    pk.use_table(None)


def test_expected_domain_from_the_ancestry_and_the_aliases(kinds):
    assert hd.expected_domain("Total Porosity") == "fraction"
    assert hd.expected_domain("water saturation") == "fraction"
    assert hd.expected_domain("net gross thickness ratio") == "fraction"
    assert hd.expected_domain("horizontal permeability") == "positive"
    assert hd.expected_domain("net thickness") == "positive"
    assert hd.expected_domain("pore volume") == "positive"
    # a volume fraction that is not a fraction of a whole
    assert hd.expected_domain("gas oil ratio") is None
    assert hd.expected_domain("facies") is None
    assert hd.expected_domain("no such kind") is None
    assert hd.expected_domain("") is None
    # RESQML 2.0.1 names outside PWLS 4.0
    assert hd.expected_domain("net to gross ratio") == "fraction"
    assert hd.expected_domain("rock permeability") == "positive"
    assert hd.expected_domain("Rock Volume") == "positive"
    # filed under thickness by PWLS, but signed by nature
    assert hd.expected_domain("peak trough delta depth") is None


def test_range_findings_four_messages_and_nothing_to_check(kinds):
    f = hd.range_findings("porosity", "m3/m3", 0.0, 25.0, "PHI", "/p")
    assert [x["severity"] for x in f] == ["warning"]
    assert f[0]["category"] == "range" and f[0]["object"] == "PHI"
    assert f[0]["message"].startswith("values up to 25: a percentage declared as a fraction?")
    f = hd.range_findings("porosity", "%", 0.0, 250.0, "PHI", "/p")
    assert f[0]["message"].startswith("values up to 250 %: above 100 %")
    # no unit on the node: the unit is unknown, not "declared as a fraction"
    f = hd.range_findings("porosity", "", 0.0, 25.0, "PHI", "/p")
    assert [x["severity"] for x in f] == ["warning"]
    assert f[0]["message"].startswith("values up to 25, no unit on this node:")
    assert "declared as a fraction" not in f[0]["message"]
    f = hd.range_findings("porosity", "m3/m3", -0.1, 0.3, "PHI", "/p")
    assert [x["severity"] for x in f] == ["error"]
    assert f[0]["message"].startswith("values down to -0.1: a porosity cannot be negative")
    f = hd.range_findings("net thickness", "m", -3.0, 10.0, "H", "/h")
    assert f[0]["severity"] == "error" and "net thickness cannot be negative" in f[0]["message"]
    # both at once; nothing wrong; nothing known
    assert len(hd.range_findings("porosity", "", -1.0, 2.0, "PHI", "/p")) == 2
    assert hd.range_findings("porosity", "m3/m3", 0.0, 0.35, "PHI", "/p") == []
    assert hd.range_findings("porosity", "%", 0.0, 35.0, "PHI", "/p") == []
    assert hd.range_findings("porosity", "m3/m3", None, None, "PHI", "/p") == []
    assert hd.range_findings("facies", "", -1.0, 5.0, "F", "/f") == []
    assert DASH not in f[0]["message"]


def test_range_findings_reads_every_percent_spelling(kinds):
    # p.u., PU, percent, %VOL: a percentage, whatever the case — never "a
    # percentage declared as a fraction"
    for uom in ("p.u.", "PU", "percent", "%VOL", "Pct", " % "):
        assert hd.range_findings("porosity", uom, 0.0, 35.0, "PHI", "/p") == [], uom
        f = hd.range_findings("porosity", uom, 0.0, 250.0, "PHI", "/p")
        assert [x["severity"] for x in f] == ["warning"], uom
        assert f[0]["message"].startswith("values up to 250 %: above 100 %"), uom
    # a fraction unit above 1 still warns
    f = hd.range_findings("porosity", "v/v", 0.0, 25.0, "PHI", "/p")
    assert f[0]["message"].startswith("values up to 25: a percentage declared as a fraction?")


def _well_tree(md):
    """One wellbore with a trajectory, a marker frame and one marker typed
    the way the reader writes it ('Marker'), with or without its MD."""
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_well", 0, label="Wellbore_W", title="W-1",
                                   type="Wellbore")
    asm.add_node_with_attrs("_traj", well, label="Trajectory_T", title="T",
                            type="Trajectory")
    frame = asm.add_node_with_attrs("_mf", well, label="MarkerFrame_M", title="Tops",
                                    type="MarkerFrame")
    attrs = {"md": md} if md else {}
    asm.add_node_with_attrs("_mk", frame, label="Marker_Top", title="Top",
                            type="Marker", **attrs)
    return Tree(asm)


def test_tree_findings_marker_without_md_said_once_and_not_over_etp():
    def well(findings):
        return [f for f in findings if f["category"] == "well"]
    f = well(hd.tree_findings(_well_tree(md=""))[0])
    assert len(f) == 1 and f[0]["message"].startswith("1 marker without a measured depth")
    assert f[0]["object"] == "W-1"
    assert well(hd.tree_findings(_well_tree(md="1520.5"))[0]) == []
    # a well read from a store: its reader writes no MD on the tree, nothing to say
    assert well(hd.tree_findings(_well_tree(md=""), far=set)[0]) == []
    assert len(well(hd.tree_findings(_well_tree(md=""), far=lambda paths: set())[0])) == 1, "a file's well beside it"


def _grid_tree(**props):
    """One grid with the given property nodes: name -> attributes."""
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G", title="Geogrid",
                                   type="IjkGrid", typeCode="2")
    for name, attrs in props.items():
        asm.add_node_with_attrs(f"_{name}", grid, label=f"Properties_{name}",
                                title=name, typeCode="4", **attrs)
    return Tree(asm)


def _range(tree):
    findings, _ = hd.tree_findings(tree)
    return [f for f in findings if f["category"] == "range"]


def test_tree_findings_range_over_a_fake_assembly(kinds):
    # a multi-realization porosity whose bounds the FESPP reader writes,
    # with no uom (the reader writes none on such a node): the warning says
    # the unit is unknown here
    tree = _grid_tree(PORO={"type": "MultiRealization", "propType": "ContinuousProperty",
                            "propertyKind": "porosity",
                            "minvalue": "0", "maxvalue": "25"})
    f = _range(tree)
    assert [x["severity"] for x in f] == ["warning"] and f[0]["object"] == "PORO"
    assert "no unit on this node" in f[0]["message"]
    # a signed kind filed under thickness: nothing said
    tree = _grid_tree(DZ={"type": "TimeSeries", "propType": "ContinuousProperty",
                          "propertyKind": "peak trough delta depth",
                          "minvalue": "-12", "maxvalue": "8"})
    assert _range(tree) == []
    # a negative minimum: an error
    tree = _grid_tree(PORO={"type": "MultiRealization", "propType": "ContinuousProperty",
                            "propertyKind": "porosity",
                            "minvalue": "-0.1", "maxvalue": "0.3"})
    f = _range(tree)
    assert [x["severity"] for x in f] == ["error"]
    # a plain leaf carries no bounds: said, per representation, as an info
    tree = _grid_tree(PORO={"type": "ContinuousProperty", "propertyKind": "porosity",
                            "uom": "m3/m3"},
                      PERM={"type": "ContinuousProperty",
                            "propertyKind": "horizontal permeability", "uom": "mD"},
                      FACIES={"type": "DiscreteProperty", "propertyKind": "facies"})
    f = _range(tree)
    assert len(f) == 1 and f[0]["severity"] == "info" and f[0]["object"] == "Geogrid"
    assert f[0]["message"].startswith("2 properties with a bounded kind"
                                      " (horizontal permeability, porosity)")
    assert "not range-checked" in f[0]["message"] and f[0]["count"] == 2
    # bounds in range: nothing said
    tree = _grid_tree(PORO={"type": "TimeSeries", "propType": "ContinuousProperty",
                            "propertyKind": "porosity",
                            "minvalue": "0.01", "maxvalue": "0.35"})
    assert _range(tree) == []


def test_csv_payload_states_the_counts():
    import re
    res = {"summary": {"objects": 120, "partial": 2, "errors": 1, "warnings": 3, "infos": 4},
           "findings": [{"severity": "error"}]}
    pl = hd.csv_payload(res)
    assert re.fullmatch(r"health_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    assert "# objects: 120 in the tree, 2 partial" in pl["header"]
    assert "# findings: 1 errors, 3 warnings, 4 infos" in pl["header"]
    assert hd.csv_payload({"findings": []}) == {"name": "", "header": []}


def test_csv_payload_names_the_files_the_session_holds():
    """The CSV header is the one list of what was imported.

    Each file is named with the objects it added, a failed read is said as
    such, and the absence of any file is said too."""
    res = {"summary": {"objects": 405, "partial": 41, "errors": 7, "warnings": 0, "infos": 8,
                       "files": [{"name": "drogon.epc", "size_mb": 0.9, "objects": 405, "failed": False},
                                 {"name": "junk.epc", "size_mb": 0.0, "objects": 0, "failed": True}]},
           "findings": [{"severity": "error"}]}
    h = hd.csv_payload(res)["header"]
    assert "# files: drogon.epc (405 objects); junk.epc (failed to read)" in h
    none = dict(res, summary=dict(res["summary"], files=[]))
    assert "# files: none imported (a dataspace, or nothing yet)" in hd.csv_payload(none)["header"]


def test_the_upload_endpoint_records_each_file_once():
    from types import SimpleNamespace
    from fespp_on_trame.engine.io import upload_endpoint as ue
    st = SimpleNamespace(ui_loaded_files=[])
    ue.record_file(st, "a.epc", 1.26, 12, None)
    ue.record_file(st, "b.epc", 0.0, 0, "not an EPC")
    assert st.ui_loaded_files == [
        {"name": "a.epc", "size_mb": 1.3, "objects": 12, "failed": False},
        {"name": "b.epc", "size_mb": 0.0, "objects": 0, "failed": True}]
    # the same name again replaces its line rather than doubling it
    ue.record_file(st, "a.epc", 1.26, 12, None)
    assert [f["name"] for f in st.ui_loaded_files] == ["b.epc", "a.epc"]


def test_empty_geometry_findings_one_error_per_object_named_and_linked():
    from fespp_on_trame.engine import health_dispatch as hd
    found = hd.empty_geometry_findings({"/data/_b/_grid": "Volve_SGrid", "/data/_a/_x": ""})
    assert [f["object"] for f in found] == ["_x", "Volve_SGrid"]
    assert all(f["severity"] == "error" and f["category"] == "data" for f in found)
    assert found[1]["path"] == "/data/_b/_grid"
    assert "empty coordinates" in found[1]["message"]
    assert hd.empty_geometry_findings(None) == []


def test_what_is_under_a_skipped_row_is_neither_counted_nor_reported():
    """The session's own velocity model is no data: its constant velocity is
    not a finding, its grid is not counted."""
    tree = _grid_tree(V={"type": "ContinuousProperty", "propType": "ContinuousProperty",
                         "propertyKind": "velocity", "uom": "m/s",
                         "minvalue": "2000", "maxvalue": "2000"})
    findings, counts = hd.tree_findings(tree)
    assert [f["object"] for f in findings if f["category"] == "grid"] == ["V"]
    grid = next(tree.find_path(n) for n, _c in tree.iter_nodes() if n and tree.find_title(n) == "Geogrid")
    findings, counts = hd.tree_findings(tree, skip=[grid])
    assert findings == [] and counts == {}
