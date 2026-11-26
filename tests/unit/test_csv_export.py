"""Tests for engine/utils/csv_export: raw, round-tripping values under a
provenance header, and the server-rendered export built on it (the
Statistics view)."""
import re

import pytest

from fespp_on_trame.engine.utils import csv_export as ce

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def test_cell_is_raw_and_round_trips():
    assert ce.cell(0.1) == "0.1"
    assert ce.cell(1e-7) == "1e-7"
    assert ce.cell(1e16) == "1e+16"
    assert ce.cell(3143561234.5) == "3143561234.5"
    assert ce.cell(1.2e-14) == "1.2e-14"
    assert ce.cell(926808) == "926808"
    assert ce.cell(None) == "n/a"
    assert ce.cell(float("nan")) == "n/a"
    assert ce.cell(True) == "true" and ce.cell(False) == "false"
    assert ce.cell("") == ""
    assert ce.cell("plain") == "plain"
    assert ce.cell('a "quoted", cell') == '"a ""quoted"", cell"'
    assert ce.cell("two\nlines") == '"two\nlines"'
    for v in (0.1, 1e-7, 1234567.891, 2.5e-300, 1 / 3):
        assert float(ce.cell(v)) == v


def test_cell_reads_numpy_scalars():
    np = pytest.importorskip("numpy")
    assert ce.cell(np.float64(0.25)) == "0.25"
    assert ce.cell(np.int64(7)) == "7"
    assert ce.cell(np.float32(1.5)) == "1.5"


def test_column_names_the_unit_once():
    assert ce.column("min", "m3/m3") == "min (m3/m3)"
    assert ce.column("variance", "m3/m3", 2) == "variance ((m3/m3)^2)"
    assert ce.column("cells", "") == "cells"
    assert ce.column("skewness", "m3/m3", 0) == "skewness"


def test_header_lines_first_and_last():
    lines = ce.header_lines("volumetrics", [("representation", "Geogrid"),
                                            ("skipped", None),
                                            ("note", "two\nlines  here")])
    assert lines[0].startswith("# fespp-on-trame ") and lines[0].endswith(" - volumetrics")
    assert lines[1].startswith("# date: ") and DATE.search(lines[1])
    assert lines[2] == "# representation: Geogrid"
    assert lines[3] == "# note: two lines here"
    assert lines[-1] == "# n/a = not available"
    assert ce.header_lines("x", {"a": 1})[2] == "# a: 1"


def test_render_round_trip():
    text = ce.render(["# h"], ["a", "b (m)", "c"],
                     [[1, 0.5, None], {"a": "x, y", "b (m)": 2.0, "c": ""}])
    assert text == '# h\na,b (m),c\n1,0.5,n/a\n"x, y",2.0,\n'


def test_slug_and_file_name():
    assert ce.slug("Total Porosity") == "Total_Porosity"
    assert ce.slug("  Geogrid (IJK grid) ") == "Geogrid_IJK_grid"
    assert len(ce.slug("x" * 100)) == 60
    name = ce.file_name("volumetrics", "Geogrid", "")
    assert re.fullmatch(r"volumetrics_Geogrid_\d{4}-\d{2}-\d{2}\.csv", name)
    assert re.fullmatch(r"health_\d{4}-\d{2}-\d{2}\.csv", ce.file_name("health"))
    pl = ce.payload("health", [("objects", "3")])
    assert re.fullmatch(r"health_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    assert pl["header"][2] == "# objects: 3"


def test_rep_title_of_a_derived_property_names_the_grid_not_its_geometry_leaf():
    from tests.unit.fake_assembly import FakeDataAssembly
    from fespp_on_trame.engine.tree import Tree
    from fespp_on_trame.engine import derived_props, stats_dispatch
    asm = FakeDataAssembly()
    cont = asm.add_node_with_attrs("_cont", 0, label="Grid", title="Geogrid",
                                   type="GridContainer", typeCode="2")
    folder = asm.add_node_with_attrs("_propsfolder", cont, label="Properties",
                                     title="Properties", type="PropertiesFolder",
                                     typeCode="2")
    geom = asm.add_node_with_attrs("_geom", folder, label="SolidColor",
                                   title="SolidColor", type="IjkGrid", typeCode="2")
    tree = Tree(asm)
    path = derived_props.path_for(asm.GetNodePath(geom), "delta")
    assert stats_dispatch._rep_title_for_array_path(tree, path) == "Geogrid"
