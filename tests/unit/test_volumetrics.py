"""engine/volumetrics_dispatch: the pure volume arithmetic and the term picks."""
import math

import pytest

from fespp_on_trame.engine import pwls_kinds as pk
from fespp_on_trame.engine import volumetrics_dispatch as vd

np = pytest.importorskip("numpy")


def test_fluid_zones_by_centre_depth():
    d = [10, 20, 30, 40]
    assert list(vd.fluid_zones(d, 15, 35)) == [0, 1, 1, 2]
    assert list(vd.fluid_zones(d, 15, None)) == [0, 2, 2, 2]
    assert list(vd.fluid_zones(d, None, 35)) == [0, 0, 0, 2]
    assert list(vd.fluid_zones(d, None, None)) == [1, 1, 1, 1]
    assert vd.zone_names(15, 35)[1].startswith("oil")


def test_aggregate_grv_nrv_pv_hcpv_per_region_and_zone():
    vol = [1.0, 1.0, 1.0, 1.0]
    depth = [10, 20, 30, 40]
    phi = [0.2, 0.2, 0.2, 0.2]
    ntg = [0.5, 0.5, 0.5, 0.5]
    sw = [0.3, 0.3, 0.3, 0.3]
    region = [1, 1, 2, 2]
    out = vd.aggregate(vol, depth, 15, 35, phi, ntg, sw, region)
    assert out["cells"] == 4 and out["active"] == 4
    oil = [r for r in out["totals"] if r["fluid"].startswith("oil")][0]
    assert oil["cells"] == 2 and oil["grv"] == 2.0 and oil["nrv"] == 1.0
    assert abs(oil["pv"] - 0.2) < 1e-12 and abs(oil["hcpv"] - 0.14) < 1e-12
    by = {(r["region"], r["fluid"][:3]): r for r in out["rows"]}
    assert by[("1", "gas")]["cells"] == 1 and by[("1", "oil")]["cells"] == 1
    assert by[("2", "oil")]["cells"] == 1 and by[("2", "wat")]["cells"] == 1
    total = out["totals"][-1]
    assert total["fluid"] == "total" and total["grv"] == 4.0


def test_aggregate_excludes_inactive_cells_and_reads_missing_terms():
    vol = [2.0, 2.0, float("nan")]
    depth = [10, 10, 10]
    phi = [0.25, float("nan"), 0.25]          # the second cell is inactive
    out = vd.aggregate(vol, depth, None, None, phi)
    total = out["totals"][-1]
    assert out["active"] == 1 and total["grv"] == 2.0 and total["nrv"] == 2.0
    assert abs(total["pv"] - 0.5) < 1e-12 and total["hcpv"] is None
    assert vd.fraction_factor("%") == 0.01 and vd.fraction_factor("v/v") == 1.0


def test_auto_pick_by_kind_then_by_title():
    pk.use_table({"property": [None, ""], "porosity": ["property", ""],
                  "total porosity": ["porosity", ""],
                  "saturation": ["property", ""], "water saturation": ["saturation", ""]})
    try:
        props = [
            {"path": "/a", "title": "PHIT", "kind": "total porosity", "unit": "", "type": "ContinuousProperty"},
            {"path": "/b", "title": "NTG", "kind": "net to gross ratio", "unit": "", "type": "ContinuousProperty"},
            {"path": "/c", "title": "SWAT", "kind": "", "unit": "", "type": "ContinuousProperty"},
            {"path": "/d", "title": "fault_blocks", "kind": "Number", "unit": "", "type": "DiscreteProperty"},
            {"path": "/e", "title": "Facies", "kind": "", "unit": "", "type": "CategoricalProperty"},
        ]
        picks = vd.auto_pick(props)
        assert picks == {"poro": "/a", "ntg": "/b", "sw": "/c", "region": "/d"}
    finally:
        pk.use_table(None)


def test_aggregate_leaves_out_cells_without_volume():
    # A sub-representation of faces and edges: a zero volume is no rock.
    out = vd.aggregate([1.0, 0.0, 0.0, 2.0], [10, 10, 10, 10])
    assert out["no_volume"] == 2 and out["active"] == 2
    assert out["totals"][-1]["grv"] == 3.0


def test_aggregate_handles_no_property_at_all():
    out = vd.aggregate([1.0, 3.0], [5, 50], None, 20)
    assert [r["fluid"] for r in out["totals"]] == ["oil (above OWC)", "water (below OWC)", "total"]
    assert out["totals"][0]["grv"] == 1.0 and out["totals"][1]["grv"] == 3.0
    assert out["totals"][0]["pv"] is None and math.isclose(out["totals"][-1]["nrv"], 4.0)


def test_aggregate_names_the_regions_and_keeps_their_codes():
    vol = [1.0, 1.0, 1.0, 1.0]
    depth = [10, 20, 30, 40]
    region = [1, 1, 2, float("nan")]
    out = vd.aggregate(vol, depth, None, None, region=region,
                       region_labels={1: "Upper", 2: "Lower"})
    rows = {(r["region"], r["region_code"]) for r in out["rows"]}
    assert rows == {("Upper", 1), ("Lower", 2), ("(no region)", None)}
    assert all(r["region_code"] is None and r["region"] == "all" for r in out["totals"])
    # A code the file does not name is written as the code.
    out = vd.aggregate(vol, depth, None, None, region=region, region_labels={1: "Upper"})
    assert {r["region"] for r in out["rows"]} == {"Upper", "2", "(no region)"}
    # Without any label every row is named by its code.
    out = vd.aggregate(vol, depth, None, None, region=region)
    assert {(r["region"], r["region_code"]) for r in out["rows"]} == {
        ("1", 1), ("2", 2), ("(no region)", None)}


def test_csv_payload_states_terms_contacts_and_raw_cubic_metres():
    import re
    res = {"rows": [{"region": "Upper"}], "totals": [], "cells": 926808, "active": 655576,
           "no_volume": 0, "grid_title": "Geogrid", "rep_type": "IJK grid",
           "convention": "depth positive down; a cell belongs to the zone of its centre",
           "terms": {"poro": "PHIF", "ntg": "", "sw": "SW", "region": "Zone"},
           "term_units": {"poro": "m3/m3", "ntg": "", "sw": "m3/m3", "region": ""},
           "term_types": {"poro": "ContinuousProperty", "ntg": "", "sw": "ContinuousProperty",
                          "region": "DiscreteProperty"},
           "goc": 1650.0, "owc": 1700.0}
    pl = vd.csv_payload(res)
    assert re.fullmatch(r"volumetrics_Geogrid_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    h = pl["header"]
    assert h[0].startswith("# fespp-on-trame ") and h[0].endswith(" - volumetrics")
    assert "# representation: Geogrid (IJK grid)" in h
    assert "# porosity: PHIF (m3/m3)" in h
    assert "# net to gross: none = 1" in h
    assert "# water saturation: SW (m3/m3)" in h
    assert "# region: Zone (DiscreteProperty)" in h
    assert ("# contacts: GOC 1650.0, OWC 1700.0 (depth positive down, in the"
            " grid's depth unit)") in h
    assert any(line.startswith("# volumes: cubic meters (m3), raw values") for line in h)
    assert "# cells: 926808 total, 655576 active, 0 without a volume" in h
    assert h[-1] == "# n/a = not available"
    assert vd.csv_payload({"rows": [], "totals": []}) == {"name": "", "header": []}


# --- a percentile term cubed is not a percentile of the volume --------------
#
# The calculator's P10/P50/P90 recipes are per-cell percentiles across the
# realizations. Per-cell percentiles do not add up: cubing one gives a
# number that is not the P10 of the volume. No arithmetic changes for it;
# the card only has to say so.

def _percentile_prop(quantile, title="P10_PORO (derived)", path="derived://g/P10_PORO"):
    return {"path": path, "title": title, "kind": "", "unit": "",
            "type": "ContinuousProperty", "derived_type": "percentile",
            "quantile": quantile}


def test_a_percentile_term_is_warned_with_its_own_label():
    """Quantile 90 is labelled "P10".

    The calculator builds P10 (the reserves exceedance convention) from the
    90th numpy percentile."""
    props = [_percentile_prop(90)]
    out = vd.percentile_warnings({"poro": props[0]["path"]}, props)
    assert len(out) == 1
    w = out[0]
    assert w["term"] == "poro" and w["label"] == "P10"
    assert w["text"] == (
        "P10_PORO (derived) is a per-cell percentile across realizations:"
        " the volume computed from it is not the P10 of the volume — cube"
        " each realization and take the percentile of the volumes.")


def test_the_p90_recipe_says_p90():
    props = [_percentile_prop(10, title="P90_PORO (derived)")]
    out = vd.percentile_warnings({"poro": props[0]["path"]}, props)
    assert [w["label"] for w in out] == ["P90"]
    assert vd._exceedance_label(50) == "P50"


def test_an_expression_recipe_and_a_plain_property_are_not_warned():
    props = [{"path": "/a", "title": "PHIT", "kind": "porosity", "unit": "",
              "type": "ContinuousProperty"},
             {"path": "derived://g/PHIE", "title": "PHIE (derived)", "kind": "",
              "unit": "", "type": "ContinuousProperty", "derived_type": "expr",
              "quantile": None}]
    assert vd.percentile_warnings({"poro": "/a"}, props) == []
    assert vd.percentile_warnings({"poro": "derived://g/PHIE"}, props) == []


def test_a_percentile_region_is_not_warned():
    """A region does not multiply into a volume: it splits the rows."""
    props = [_percentile_prop(90)]
    assert vd.percentile_warnings({"region": props[0]["path"]}, props) == []


def test_the_csv_header_carries_the_warning():
    props = [_percentile_prop(90)]
    warns = vd.percentile_warnings({"poro": props[0]["path"]}, props)
    res = {"rows": [{"region": "all"}], "totals": [], "cells": 4, "active": 4,
           "no_volume": 0, "grid_title": "Geogrid", "rep_type": "IJK grid",
           "terms": {"poro": "P10_PORO (derived)", "ntg": "", "sw": "", "region": ""},
           "term_units": {}, "term_types": {}, "goc": None, "owc": None,
           "percentile_terms": warns}
    h = vd.csv_payload(res)["header"]
    assert ("# percentile terms: P10_PORO (derived) is a per-cell percentile"
            " across realizations: the volume computed from it is not the P10"
            " of the volume - cube each realization and take the percentile"
            " of the volumes") in h
    res.pop("percentile_terms")
    assert not any(line.startswith("# percentile terms") for line in
                   vd.csv_payload(res)["header"])


def test_the_aggregation_is_what_it_is_hand_derived_to_be():
    """Two cells, so every figure can be written out. Volumes 1 and 3 at
    depths 10 and 20, an oil-water contact at 15, net-to-gross 1.0 and 0.5,
    porosity 0.10 and 0.30, water saturation 0.20 and 0.60.

    Cell 0 sits above the contact, cell 1 below it, so each owns one zone:

        oil (above OWC)   GRV = 1      NRV = 1 x 1.0     = 1.00
                    PV  = 1 x 1.0 x 0.10               = 0.10
                    HCPV= 0.10 x (1 - 0.20)            = 0.08
        water (below OWC) GRV = 3      NRV = 3 x 0.5     = 1.50
                    PV  = 3 x 0.5 x 0.30               = 0.45
                    HCPV= 0.45 x (1 - 0.60)            = 0.18
        total       GRV = 4   NRV = 2.50   PV = 0.55   HCPV = 0.26

    Every one of those eight numbers is asserted; nothing here is compared
    with the function's own output."""
    vol, depth = [1.0, 3.0], [10.0, 20.0]
    ntg, phi, sw = [1.0, 0.5], [0.10, 0.30], [0.20, 0.60]
    out = vd.aggregate(vol, depth, None, 15.0, phi, ntg, sw)
    above, below, total = out["totals"]
    assert [t["fluid"] for t in out["totals"]] == ["oil (above OWC)",
                                                   "water (below OWC)", "total"]
    for row, want in ((above, (1.0, 1.00, 0.10, 0.08)),
                      (below, (3.0, 1.50, 0.45, 0.18)),
                      (total, (4.0, 2.50, 0.55, 0.26))):
        got = (row["grv"], row["nrv"], row["pv"], row["hcpv"])
        assert got == pytest.approx(want, abs=1e-15)
    assert (out["cells"], out["active"], out["no_volume"]) == (2, 2, 0)


def test_no_figure_moves_when_a_term_is_a_percentile_recipe():
    """The percentile check is a warning and changes no figure.

    The warning is text (none of its keys is a number the card multiplies),
    and it adds exactly one line to the export's header while every other
    line stays unchanged. `aggregate` itself receives value arrays and no
    recipe at all; the hand-derived case above pins what it does with them."""
    props = [_percentile_prop(90, title="P10_PORO (derived)")]
    warns = vd.percentile_warnings({"poro": props[0]["path"]}, props)
    assert set(warns[0]) == {"term", "path", "title", "quantile", "label",
                             "text"}
    res = {"rows": [{"region": "all", "fluid": "total", "cells": 2,
                     "grv": 4.0, "nrv": 2.5, "pv": 0.55, "hcpv": 0.26,
                     "region_code": None}],
           "totals": [], "cells": 2, "active": 2, "no_volume": 0,
           "grid_title": "Geogrid", "rep_type": "IJK grid",
           "terms": {"poro": "P10_PORO (derived)", "ntg": "", "sw": "",
                     "region": ""},
           "term_units": {}, "term_types": {}, "goc": None, "owc": None}
    plain = vd.csv_payload(res)["header"]
    res["percentile_terms"] = warns
    warned = vd.csv_payload(res)["header"]
    assert len(warned) == len(plain) + 1
    assert [ln for ln in warned if not ln.startswith("# percentile terms")] \
        == plain


# ---- surface conditions: Bo, Bg, the recovery factors ----------------------

def test_one_contact_names_its_fluids():
    """An OWC is the base of the oil, a GOC the top of it: the zones say
    which fluid they hold, so the surface factors know where to apply."""
    assert vd.zone_names(None, 20) == {0: "oil (above OWC)", 2: "water (below OWC)"}
    assert vd.zone_names(10, None) == {0: "gas (above GOC)", 2: "oil (below GOC)"}
    assert vd.zone_fluids(None, 20) == {0: "oil", 2: "water"}
    assert vd.zone_fluids(10, None) == {0: "gas", 2: "oil"}
    assert vd.zone_fluids(10, 20) == {0: "gas", 1: "oil", 2: "water"}
    assert vd.zone_fluids(None, None) == {1: ""}


def test_a_lone_owc_with_bg_alone_is_a_gas_water_contact():
    """A lone OWC with Bg alone makes the upper zone gas.

    The card has no gas-water contact field: a dry-gas field puts its
    contact in OWC and gives Bg alone. The zone above is then gas, named so,
    and takes Bg; with Bo (alone or with Bg) it stays oil."""
    assert vd.upper_fluid(None, 20, {"bg": 0.005}) == "gas"
    assert vd.upper_fluid(None, 20, {"bo": 1.2}) == "oil"
    assert vd.upper_fluid(None, 20, {"bo": 1.2, "bg": 0.005}) == "oil"
    assert vd.upper_fluid(None, 20, None) == "oil"
    assert vd.upper_fluid(10, 20, {"bg": 0.005}) == "oil"
    assert vd.zone_names(None, 20, {"bg": 0.005}) == {0: "gas (above OWC)", 2: "water (below OWC)"}
    out = vd.aggregate([1.0, 3.0], [10.0, 20.0], None, 15.0, [0.2, 0.2], None, [0.5, 0.5],
                       surface={"bg": 0.005, "rf_gas": 0.8})
    gas, water, total = out["totals"]
    assert gas["fluid"] == "gas (above OWC)"
    assert gas["giip"] == pytest.approx(0.1 / 0.005) and gas["rec_gas"] == pytest.approx(16.0)
    assert water["giip"] is None and total["giip"] == pytest.approx(20.0)


def test_surface_volumes_hand_derived():
    """The two cells of the hand-derived test, an OWC at 15, Bo 1.25 and
    RF oil 0.4: the oil zone (cell 0, HCPV 0.08) gives STOIIP 0.064 and
    0.0256 recoverable; the water zone gives none; the total carries the
    oil zone's; nothing is computed for gas (no Bg)."""
    vol, depth = [1.0, 3.0], [10.0, 20.0]
    ntg, phi, sw = [1.0, 0.5], [0.10, 0.30], [0.20, 0.60]
    out = vd.aggregate(vol, depth, None, 15.0, phi, ntg, sw,
                       surface={"bo": 1.25, "rf_oil": 0.4})
    oil, water, total = out["totals"]
    assert oil["stoiip"] == pytest.approx(0.064) and oil["rec_oil"] == pytest.approx(0.0256)
    assert water["stoiip"] is None and water["rec_oil"] is None
    assert total["stoiip"] == pytest.approx(0.064) and total["rec_oil"] == pytest.approx(0.0256)
    assert all(r["giip"] is None and r["rec_gas"] is None for r in out["totals"])


def test_gas_cap_and_oil_leg_take_their_own_factor():
    """Three cells, one per zone: the gas cap divides by Bg, the oil leg by
    Bo, the water leg by nothing; the grand total sums each family."""
    vol, depth = [1.0, 1.0, 1.0], [5.0, 15.0, 25.0]
    phi, sw = [0.2, 0.2, 0.2], [0.5, 0.5, 0.5]
    out = vd.aggregate(vol, depth, 10.0, 20.0, phi, None, sw,
                       surface={"bo": 2.0, "bg": 0.01, "rf_oil": 0.5, "rf_gas": 0.8})
    gas, oil, water, total = out["totals"]
    assert gas["giip"] == pytest.approx(0.1 / 0.01) and gas["stoiip"] is None
    assert oil["stoiip"] == pytest.approx(0.1 / 2.0) and oil["giip"] is None
    assert water["stoiip"] is None and water["giip"] is None
    assert total["giip"] == pytest.approx(10.0) and total["stoiip"] == pytest.approx(0.05)
    assert total["rec_gas"] == pytest.approx(8.0) and total["rec_oil"] == pytest.approx(0.025)


def test_no_contact_takes_the_fluid_the_factor_names():
    """With no contact the grid names no fluid: Bo alone makes it oil, Bg
    alone gas, both together nothing (the card says it cannot choose)."""
    vol, depth, phi, sw = [1.0], [10.0], [0.2], [0.5]
    assert vd.surface_fluid(None, None, {"bo": 1.2}) == "oil"
    assert vd.surface_fluid(None, None, {"bg": 0.005}) == "gas"
    assert vd.surface_fluid(None, None, {"bo": 1.2, "bg": 0.005}) == ""
    assert vd.surface_fluid(None, 20, {"bo": 1.2, "bg": 0.005}) == ""
    out = vd.aggregate(vol, depth, None, None, phi, None, sw, surface={"bo": 1.2})
    assert out["surface_fluid"] == "oil"
    assert out["totals"][0]["stoiip"] == pytest.approx(0.1 / 1.2)
    out = vd.aggregate(vol, depth, None, None, phi, None, sw,
                       surface={"bo": 1.2, "bg": 0.005})
    assert out["surface_fluid"] == "" and out["totals"][0]["stoiip"] is None


def test_surface_terms_are_read_and_refused_out_loud():
    """A factor is a number or nothing; a bad one is dropped with its
    sentence, a recovery above 1 is read as a percentage and says so."""
    sf, notes = vd.surface_terms({"bo": "1.2", "bg": "", "rf_oil": 30, "rf_gas": None})
    assert sf == {"bo": 1.2, "bg": None, "rf_oil": 0.3, "rf_gas": None}
    assert notes == ["RF oil 30 read as a percentage."]
    sf, notes = vd.surface_terms({"bo": -1, "bg": "abc", "rf_oil": -0.1})
    assert sf["bo"] is None and sf["bg"] is None and sf["rf_oil"] is None
    assert "Bo must be positive" in notes[0]
    assert "Bg 'abc' is not a number" in notes[1]
    assert "RF oil must be between" in notes[2]
    # 150 would recover more than is in place: read as 150 %, then refused.
    sf, notes = vd.surface_terms({"rf_gas": 150})
    assert sf["rf_gas"] is None
    assert notes == ["RF gas 150 read as a percentage.",
                     "RF gas must be between 0 and 1 (or 0 and 100 %): 150 ignored."]


def test_the_csv_header_states_the_surface_terms():
    result = {"rows": [{"region": "all", "fluid": "oil", "cells": 1}], "totals": [],
              "grid_title": "G", "terms": {}, "term_units": {}, "term_types": {},
              "goc": None, "owc": 20.0, "convention": "c", "cells": 1, "active": 1,
              "no_volume": 0, "surface": {"bo": 1.2, "bg": None, "rf_oil": 0.3, "rf_gas": None}}
    header = vd.csv_payload(result)["header"]
    text = "\n".join(header)
    assert "# surface: Bo 1.2, RF oil 0.3" in text
    assert "STOIIP = HCPV / Bo" in text and "stb = sm3 x 6.28981" in text
    result["surface"] = {}
    header = vd.csv_payload(result)["header"]
    assert "# surface: none" in "\n".join(header)
    assert not any(line.startswith("# surface volumes") for line in header)
    # An RF alone gives no column: the header states the factor, not the
    # columns.
    result["surface"] = {"bo": None, "bg": None, "rf_oil": 0.3, "rf_gas": None}
    header = vd.csv_payload(result)["header"]
    assert "# surface: RF oil 0.3" in "\n".join(header)
    assert not any(line.startswith("# surface volumes") for line in header)
