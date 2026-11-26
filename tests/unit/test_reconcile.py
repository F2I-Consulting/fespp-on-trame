"""Tests for the pure half of engine/reconcile_dispatch: pairing logs with
grid properties, unit scaling, and the per-zone comparison rows."""
import pytest

from fespp_on_trame.engine import pwls_kinds as pk
from fespp_on_trame.engine import reconcile_dispatch as rd


@pytest.fixture
def hierarchy():
    pk.use_table({
        "property": [None, ""],
        "porosity": ["property", "volume per volume"],
        "neutron porosity": ["porosity", "volume per volume"],
        "saturation": ["property", "volume per volume"],
        "water saturation": ["saturation", "volume per volume"],
        "gas saturation": ["saturation", "volume per volume"],
    })
    yield
    pk.use_table(None)


def test_match_basis_kinds_win_over_names(hierarchy):
    assert rd.match_basis("porosity", "PHIE", "porosity", "PORO") == "kind"
    # a specialisation IS the kind: the hierarchy says so, approximately
    assert rd.match_basis("neutron porosity", "NPHI", "porosity", "PORO") == "kind~"
    assert rd.match_basis("water saturation", "SW", "saturation", "SWAT") == "kind~"
    # siblings in the hierarchy never pair, whatever word they share
    assert rd.match_basis("water saturation", "SW", "gas saturation", "SGAS") is None
    # kinds the hierarchy does not know: a shared word is the approximation
    assert rd.match_basis("Interp Facies", "F", "Interp Lithology", "L") == "kind~"
    # two declared kinds that disagree are not a pair, whatever the names say
    assert rd.match_basis("saturation", "PORO", "porosity", "PORO") is None
    # no kind on a side: the names decide
    assert rd.match_basis("", "PORO", "porosity", "PORO") == "name"
    assert rd.match_basis("", "Porosity log", "", "porosity model") == "name~"
    assert rd.match_basis("", "GR", "", "PORO") is None


def test_short_mnemonics_pair_as_whole_words_only(hierarchy):
    # a short mnemonic pairs with the words naming its quantity...
    assert rd.match_basis("", "SW", "", "WatSat") == "name~"
    assert rd.match_basis("", "SW", "", "SWAT_2019") == "name~"
    assert rd.match_basis("", "PHI", "", "Porosity") == "name~"
    assert rd.match_basis("", "GR", "", "GammaRay") == "name~"
    # ...as a whole word: a prefix is not the mnemonic
    assert rd.match_basis("", "SW", "", "Swept zone") is None
    # a two-letter word that is no mnemonic pairs nothing
    assert rd.match_basis("", "Zone A1", "", "Layer A1") is None
    assert rd.match_basis("", "GR", "", "Gross volume") is None
    # the mnemonics do not cross: water against gas stays apart
    assert rd.match_basis("", "SW", "", "SGAS") is None


def test_pair_reason_names_the_specialisation(hierarchy):
    assert rd.pair_reason("water saturation", "saturation", "kind~") == "water saturation ⊂ saturation"
    assert rd.pair_reason("saturation", "water saturation", "kind~") == "water saturation ⊂ saturation"
    assert rd.pair_reason("a b", "b c", "kind~").startswith("kinds share a word")


def test_auto_pairs_keeps_the_best_basis_per_log(hierarchy):
    logs = {"PHIE": {"kind": "porosity", "unit": "v/v"},
            "SW": {"kind": "water saturation", "unit": ""}}
    props = [{"path": "/a", "title": "PORO", "kind": "porosity", "unit": "v/v"},
             {"path": "/b", "title": "NPHI model", "kind": "neutron porosity", "unit": "v/v"},
             {"path": "/c", "title": "Lithology", "kind": "", "unit": ""},
             {"path": "/d", "title": "SWAT", "kind": "saturation", "unit": ""}]
    pairs = rd.auto_pairs(logs, props)
    # every pair also carries the two quantity classes and whether they
    # disagree — disclosed on every row, not only when it rejects something
    assert pairs == [
        {"log": "PHIE", "prop": "/a", "basis": "kind", "why": None,
         "class_log": "volume per volume", "class_prop": "volume per volume",
         "class_mismatch": False},
        {"log": "SW", "prop": "/d", "basis": "kind~",
         "why": "water saturation ⊂ saturation",
         "class_log": "volume per volume", "class_prop": "volume per volume",
         "class_mismatch": False},
    ]


def test_unit_factor_scales_percent_and_flags_the_rest():
    assert rd.unit_factor("%", "v/v") == (0.01, "log % → v/v")
    assert rd.unit_factor("v/v", "%") == (100.0, "log v/v → %")
    assert rd.unit_factor("m3/m3", "") == (1.0, None)
    assert rd.unit_factor("mD", "mD") == (1.0, None)
    factor, flag = rd.unit_factor("ohm.m", "mD")
    assert factor == 1.0 and flag == "units differ: ohm.m vs md"


def _well(tops=True):
    depths = range(0, 100)
    return {
        "name": "W1", "depth": {"min": 0.0, "max": 100.0},
        "tops": ([{"name": "A", "depth": 0.0}, {"name": "B", "depth": 50.0},
                  {"name": "C", "depth": 100.0}] if tops else []),
        "_full": {
            "PHI": [[20.0 if d < 50 else 10.0 + (d % 2), float(d)] for d in depths],
            "PORO (grid)": [[0.25 if d < 50 else 0.1, float(d)] for d in depths],
        },
    }


_PROPS = {"/p": {"path": "/p", "title": "PORO", "kind": "porosity", "unit": "v/v"}}


def test_rows_for_well_one_row_per_zone_with_the_log_scaled():
    rows = rd.rows_for_well(
        _well(), [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "%"}}, _PROPS)
    assert [r["zone"] for r in rows] == ["A → B", "B → C"]
    a, b = rows
    assert a["n_log"] == 50 and a["n_grid"] == 50
    assert abs(a["mean_log"] - 0.20) < 1e-9 and a["mean_grid"] == 0.25
    assert a["z"] is None                      # a constant log has no σ
    assert "log % → v/v" in a["flags"]
    # the compared values are in the grid property's unit once scaled
    assert a["log_unit"] == "%" and a["prop_unit"] == "v/v" and a["unit"] == "v/v"
    assert abs(b["mean_log"] - 0.105) < 1e-9 and b["mean_grid"] == 0.1
    assert b["z"] is not None and b["z"] > 0


def test_rows_for_well_falls_back_to_the_whole_well():
    rows = rd.rows_for_well(
        _well(tops=False), [{"log": "PHI", "prop": "/p", "basis": "name~"}],
        {"PHI": {"kind": "", "unit": "v/v"}}, _PROPS)
    assert len(rows) == 1 and rows[0]["zone"] == "(whole well)"
    # the flag says what the pairing actually rests on — the two titles share
    # a word — and, since the log declares no kind, that no class was checked
    assert rows[0]["n_log"] == 100
    assert rows[0]["flags"] == ["titles share a word", "quantity class not checked"]


def test_sort_rows_puts_the_largest_contradiction_first():
    rows = [{"z": 0.5, "gap": 1}, {"z": None, "gap": 9}, {"z": -3.0, "gap": 2}]
    assert [r["z"] for r in rd.sort_rows(rows)] == [-3.0, 0.5, None]


def test_sort_rows_ranks_a_zone_of_few_samples_last_whatever_its_z():
    rows = [{"z": 40.0, "gap": 1, "n_log": 2}, {"z": 0.5, "gap": 1, "n_log": 50},
            {"z": None, "gap": 9, "n_log": 80}, {"z": -3.0, "gap": 2, "n_log": 5}]
    assert [r["z"] for r in rd.sort_rows(rows)] == [-3.0, 0.5, None, 40.0]


def test_rows_for_well_flags_a_zone_of_few_samples_and_keeps_it():
    well = _well(tops=False)
    well["tops"] = [{"name": "thin", "depth": 0.0}, {"name": "thick", "depth": 3.0},
                    {"name": "end", "depth": 100.0}]
    rows = rd.rows_for_well(
        well, [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "v/v"}}, _PROPS)
    thin, thick = rows
    assert thin["n_log"] == 3 and f"n<{rd.MIN_SAMPLES}" in thin["flags"]
    assert thick["n_log"] == 97 and not any(f.startswith("n<") for f in thick["flags"])
    assert rd.MIN_SAMPLES == 5


def test_csv_payload_explains_the_columns():
    import re
    from fespp_on_trame.engine import reconcile_dispatch as rd
    res = {"rows": [{"well": "W1"}], "pairs": [{"log": "PHI", "prop": "/p", "basis": "kind"}],
           "auto": True, "step": 0.5, "min_samples": rd.MIN_SAMPLES}
    pl = rd.csv_payload(res)
    assert re.fullmatch(r"log_grid_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    h = pl["header"]
    assert h[0].endswith(" - log_grid")
    assert any(line.startswith("# sampling step: 0.5") for line in h)
    assert "# pairs: 1 (automatic)" in h
    assert any(line.startswith("# basis: kind = the same property kind") for line in h)
    assert any("delta_rel is a fraction of the log mean" in line for line in h)
    assert any("in the unit column of each row" in line for line in h)
    assert rd.csv_payload({"rows": []}) == {"name": "", "header": []}


# ---- the zone is bounded on the vertical, as in the log view -------------

def _deviated_well():
    """A well whose true vertical depth is HALF its drawn (measured) depth.

    Its three picks give their two depths independently: MD 0 / 50 / 100
    against TVD 0 / 20 / 50, so selecting on one axis or the other puts a
    different number of samples in each zone."""
    depths = range(0, 100)
    return {
        "name": "W1", "depth": {"min": 0.0, "max": 100.0},
        "tops": [{"name": "A", "depth": 0.0, "tvd": 0.0},
                 {"name": "B", "depth": 50.0, "tvd": 20.0},
                 {"name": "C", "depth": 100.0, "tvd": 50.0}],
        "_full": {
            "PHI": [[20.0, float(d), d / 2.0] for d in depths],
            "PORO (grid)": [[0.25, float(d), d / 2.0] for d in depths],
        },
    }


def test_rows_for_well_selects_on_the_vertical():
    # zone A is TVD [0, 20): the samples with d/2 < 20, i.e. MD 0…39 — forty
    # of them, not the fifty the measured-depth bound would have taken.
    # Zone B is TVD [20, 50): MD 40…99, sixty samples.
    rows = rd.rows_for_well(
        _deviated_well(), [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "%"}}, _PROPS)
    assert [(r["zone"], r["n_log"], r["n_grid"]) for r in rows] == [
        ("A → B", 40, 40), ("B → C", 60, 60)]
    # the drawn bounds are still what the table shows in its depth columns
    assert (rows[0]["top"], rows[0]["bottom"]) == (0.0, 50.0)


# ---- the grid mean weighted by the length of hole traversed --------------

def test_the_traversed_length_of_each_sample_is_hand_derived():
    """Samples every 2 m at TVD 1, 3, 5, 7, 9, 11; each owns the half-step to
    each neighbour, the first and last mirroring their single one:

        midpoints 0 | 2 | 4 | 6 | 8 | 10 | 12

    clipped to the zone and floored at 0."""
    assert rd.traversed_lengths([1, 3, 5, 7, 9, 11], 0, 10) == [2, 2, 2, 2, 2, 0]
    # with the base at 11, the last sample keeps half its stretch: 11 − 10 = 1
    assert rd.traversed_lengths([1, 3, 5, 7, 9, 11], 0, 11) == [2, 2, 2, 2, 2, 1]
    # a lone sample bounds no stretch — no length, and no weighted mean
    assert rd.traversed_lengths([5.0], 0, 10) == [0.0]
    assert rd.traversed_lengths([], 0, 10) == []


def test_the_grid_mean_weighted_by_the_traversed_length():
    """Six grid samples at TVD 1, 3, 5, 7, 9, 10 valued 1, 1, 1, 1, 1, 100 in
    a zone [0, 10.5). By hand:

        lengths  2 + 2 + 2 + 2 + 1.5 (9: 8 → 9.5) + 1.0 (10: 9.5 → 10.5) = 10.5
        weighted (2+2+2+2+1.5)·1 + 1.0·100 = 9.5 + 100 = 109.5, ÷ 10.5 = 73/7
                                                              = 10.428571428571429
        unweighted (1+1+1+1+1+100) / 6 = 105 / 6            = 17.5

    The 100 stands for one metre of hole, not for a sixth of the zone."""
    tvds = [1.0, 3.0, 5.0, 7.0, 9.0, 10.0]
    well = {
        "name": "W", "depth": {"min": 0.0, "max": 11.0},
        "tops": [{"name": "Z", "depth": 0.0, "tvd": 0.0},
                 {"name": "end", "depth": 10.5, "tvd": 10.5}],
        "_full": {
            "PHI": [[1.0, t, t] for t in tvds],
            "PORO (grid)": [[1.0 if t < 10.0 else 100.0, t, t] for t in tvds],
        },
    }
    row = rd.rows_for_well(
        well, [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "v/v"}}, _PROPS)[0]
    assert row["n_grid"] == 6
    assert row["mean_grid"] == pytest.approx(17.5)
    assert row["len_grid"] == pytest.approx(10.5)
    assert row["mean_grid_len"] == pytest.approx(73.0 / 7.0)


def test_a_sample_astride_the_zone_base_keeps_the_hole_it_owns_inside():
    """Six grid samples at TVD 1, 3, 5, 7, 9, 11 valued 1, 1, 1, 1, 1, 100 in
    a zone [0, 11). The last STATION sits on the base, outside the half-open
    zone, but the metre of hole from 10 to 11 belongs to it. By hand:

        lengths   2 + 2 + 2 + 2 + 2 + 1 (the 11 clipped at the base) = 11
        weighted  (5 × 2 × 1) + (1 × 100) = 10 + 100 = 110, ÷ 11     = 10.0
        unweighted, the five stations inside [0, 11)                 = 1.0

    `len_grid` is then the 11 m the zone actually spans, which is what the
    column claims; dropping the astride sample would weigh 11 m of zone with
    10 m of hole and lose the metre that holds the 100."""
    tvds = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0]
    well = {
        "name": "W", "depth": {"min": 0.0, "max": 12.0},
        "tops": [{"name": "Z", "depth": 0.0, "tvd": 0.0},
                 {"name": "end", "depth": 11.0, "tvd": 11.0}],
        "_full": {
            "PHI": [[1.0, t, t] for t in tvds],
            "PORO (grid)": [[1.0 if t < 11.0 else 100.0, t, t] for t in tvds],
        },
    }
    row = rd.rows_for_well(
        well, [{"log": "PHI", "prop": "/p", "basis": "kind"}],
        {"PHI": {"kind": "porosity", "unit": "v/v"}}, _PROPS)[0]
    assert row["n_grid"] == 5
    assert row["mean_grid"] == pytest.approx(1.0)
    assert row["len_grid"] == pytest.approx(11.0)
    assert row["mean_grid_len"] == pytest.approx(10.0)


# ---- the PWLS quantity class as a guard ---------------------------------

def test_a_true_pair_is_untouched(hierarchy):
    pairs = rd.auto_pairs(
        {"PHIE": {"kind": "porosity", "unit": "v/v"}},
        [{"path": "/a", "title": "NPHI", "kind": "neutron porosity", "unit": "v/v"}])
    assert pairs[0]["basis"] == "kind~"
    assert pairs[0]["class_mismatch"] is False
    rows = rd.rows_for_well(
        _well(), [dict(pairs[0], log="PHI", prop="/p")],
        {"PHI": {"kind": "porosity", "unit": "v/v"}}, _PROPS)
    assert rows[0]["class_checked"] is True and rows[0]["class_mismatch"] is False
    assert not any(f.startswith("different quantity classes") for f in rows[0]["flags"])
    assert "quantity class not checked" not in rows[0]["flags"]


def test_a_word_sharing_pair_of_different_classes_is_demoted():
    # Neither side declares a kind, so the titles decide — and the shipped
    # table knows both of them: "pore volume" is a volume, "volume fraction"
    # a volume per volume. They share the word "volume" and nothing else.
    logs = {"pore volume": {"kind": "", "unit": "m3"}}
    props = [{"path": "/v", "title": "Volume fraction", "kind": "", "unit": ""}]
    pair = rd.auto_pairs(logs, props)[0]
    assert pair["basis"] == "name~"          # the pair SURVIVES, demoted
    assert (pair["class_log"], pair["class_prop"]) == ("volume", "volume per volume")
    assert pair["class_mismatch"] is True
    assert pair["why"].endswith("different quantity classes: volume vs volume per volume")
    well = {"name": "W", "depth": {"min": 0.0, "max": 10.0}, "tops": [],
            "_full": {"pore volume": [[1.0, float(d)] for d in range(10)],
                      "Volume fraction (grid)": [[0.2, float(d)] for d in range(10)]}}
    props_by_path = {"/v": props[0]}
    row = rd.rows_for_well(well, [pair], logs, props_by_path)[0]
    assert "different quantity classes: volume vs volume per volume" in row["flags"]
    # and it ranks after everything, below even a row of too few samples
    ranked = rd.sort_rows([row, {"z": 0.1, "gap": 0.0, "n_log": 2, "zone": "thin"},
                           {"z": 5.0, "gap": 9.0, "n_log": 50, "zone": "loud"}])
    assert [r["zone"] for r in ranked] == ["loud", "thin", "(whole well)"]


def test_a_pair_with_an_unknown_class_is_kept_and_says_so():
    # a pair found in the Volve data: two property kinds PWLS does not know,
    # paired on the shared word "wilfried". No class guard can catch that, so
    # the row says the class was not checked instead of implying it was.
    logs = {"Facies_Wilfried": {"kind": "Facies_Wilfried 5", "unit": ""}}
    props = [{"path": "/l", "title": "Lithology1",
              "kind": "Well_Log_Interp_Wilfried Lithology1", "unit": ""}]
    pair = rd.auto_pairs(logs, props)[0]
    assert pair["basis"] == "kind~" and pair["class_mismatch"] is False
    assert (pair["class_log"], pair["class_prop"]) == ("", "")
    assert pair["why"].endswith("quantity class unknown on both sides:"
                                " the pairing is not checked against one")
    well = {"name": "W", "depth": {"min": 0.0, "max": 10.0}, "tops": [],
            "_full": {"Facies_Wilfried": [[1.0, float(d)] for d in range(10)],
                      "Lithology1 (grid)": [[2.0, float(d)] for d in range(10)]}}
    row = rd.rows_for_well(well, [pair], logs, {"/l": props[0]})[0]
    assert row["class_checked"] is False and row["class_mismatch"] is False
    assert "quantity class not checked" in row["flags"]
    assert rd.sort_rows([row])[0] is row     # the ranking does not move


def test_porosity_and_water_saturation_are_the_same_class_for_pairing():
    # PWLS spells the same thing two ways; a porosity and a saturation ARE
    # comparable quantities and must never be refused for that
    assert rd._norm_class("volume per volume") == "fraction"
    assert rd._norm_class("dimensionless") == "fraction"
    # the root class carries no information: a large share of the kinds
    # inherit "unitless"
    assert rd._norm_class("unitless") == "" and rd._norm_class("") == ""
    assert rd.class_mismatch("volume per volume", "dimensionless") is False
    assert rd.class_mismatch("length", "volume") is True
    assert rd.class_mismatch("", "volume") is False        # unknown: no verdict


def test_the_shipped_hierarchy_has_no_conflicting_ancestor_class():
    """A kind and any of its ancestors normalise to the same quantity class.

    The class guard must never break a pairing the hierarchy already allows.
    Run on the SHIPPED table, every kind, not on a fixture."""
    pk.use_table(None)
    table = pk._load()
    assert len(table) > 3000
    conflicts = []
    for title in table:
        own = rd._norm_class(pk.quantity_class(title))
        for parent in pk.ancestors(title)[1:]:
            up = rd._norm_class(pk.quantity_class(parent))
            if own and up and own != up:
                conflicts.append((title, parent))
    assert conflicts == []


def test_unit_factor_reads_porosity_units_as_a_percentage():
    """A log in p.u. (porosity units, a percentage) against a grid in v/v is
    the same quantity a hundred apart: scaled, not read as a disagreement."""
    assert rd.unit_factor("p.u.", "v/v") == (0.01, "log p.u. → v/v")
    assert rd.unit_factor("v/v", "p.u.") == (100.0, "log v/v → p.u.")
    assert rd.unit_factor("p.u.", "%") == (1.0, None)
    assert rd.unit_factor("%", "P.U.") == (1.0, None)
    factor, flag = rd.unit_factor("p.u.", "mD")
    assert factor == 1.0 and flag == "units differ: p.u. vs md"


# ---- the panel's two doors: the log view's wells and its own tree ---------

_CHANNELS = {"/w1": ["/w1/f/GR", "/w1/f/RHOB", "/w1/f/SW"],
             "/w2": ["/w2/f/GR", "/w2/f/SW"]}


def _well_of(path):
    return "/" + path.split("/")[1]


def _inputs(welllog_wells=(), own=(), dropped=(), selected=()):
    return rd.session_inputs(list(welllog_wells), list(own), list(dropped),
                             list(selected), _well_of,
                             lambda w: _CHANNELS.get(w, []))


def test_the_log_views_wells_bring_every_read_channel():
    wells, sel = _inputs(welllog_wells=["/w1"],
                         selected=["/w1", "/w1/f/GR", "/w1/f/SW", "/w1/traj"])
    assert wells == ["/w1"]
    assert sel == ["/w1", "/w1/f/GR", "/w1/f/SW", "/w1/traj"]


def test_the_panels_own_log_brings_its_well_and_that_log_only():
    # the data tree has read RHOB and SW under /w2 too: only GR is the
    # panel's — a well taken in for one log brings no other curve
    wells, sel = _inputs(own=["/w2/f/GR"],
                         selected=["/w2/traj", "/w2/f/GR", "/w2/f/SW"])
    assert wells == ["/w2"]
    assert sel == ["/w2/traj", "/w2/f/GR"]


def test_both_doors_merge_in_order_without_repeat():
    wells, sel = _inputs(welllog_wells=["/w1"], own=["/w2/f/SW", "/w1/f/GR"],
                         selected=["/w1/f/GR", "/w1/f/RHOB", "/w2/f/SW"])
    assert wells == ["/w1", "/w2"]
    assert sel == ["/w1/f/GR", "/w1/f/RHOB", "/w2/f/SW"]


def test_dropped_leaves_the_table_and_stays_loaded():
    wells, sel = _inputs(welllog_wells=["/w1"], dropped=["/w1/f/RHOB", "/g/poro"],
                         selected=["/w1/f/GR", "/w1/f/RHOB", "/g/poro", "/g/perm"])
    assert sel == ["/w1/f/GR", "/g/perm"]


def test_an_own_log_not_read_yet_is_not_held():
    wells, sel = _inputs(own=["/w1/f/GR"], selected=["/w1/traj"])
    assert wells == ["/w1"]
    assert sel == ["/w1/traj"]
