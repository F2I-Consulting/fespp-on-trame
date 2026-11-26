"""The rows of the Statistics matrix: an item, then the rows that follow it.

A part's row reads the property on a part of its grid, a 3D view's row on what
the view draws of it. They are expanded from the selection at each refresh,
sorted, read against the baseline, drawn and exported like the items, and they
are never the baseline, never cached, with no picker. The value reads are
monkeypatched: what is pinned here is what the matrix does with them.
"""
from contextlib import contextmanager
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine import cell_weights
from fespp_on_trame.engine import compare_dispatch as cd
from fespp_on_trame.engine import compare_tree as ct
from fespp_on_trame.engine import compare_matrix
from fespp_on_trame.engine import compare_rows
from fespp_on_trame.engine import derived_props
from fespp_on_trame.engine import drawn_cells
from fespp_on_trame.engine import property_values
from fespp_on_trame.engine import stats_dispatch as sd
from fespp_on_trame.engine import stats_supports
from fespp_on_trame.engine.tree import Tree


def _tree():
    """A grid in the container layout, with its properties, a blocked wellbore
    and a sub-representation, and a partial stub of one; a second grid."""
    asm = FakeDataAssembly()

    def add(name, parent, **attrs):
        return asm.add_node_with_attrs(name, parent, label=attrs.get("title", name),
                                       typeCode="2", **attrs)

    grid = add("_gridfolder_g", 0, title="Geogrid", type="GridContainer")
    props = add("_props_g", grid, title="properties", type="PropertiesFolder")
    add("_g", props, title="SolidColor", type="IjkGrid")
    other = add("_gridfolder_h", 0, title="Other", type="GridContainer")
    props_h = add("_props_h", other, title="properties", type="PropertiesFolder")
    add("_h", props_h, title="SolidColor", type="IjkGrid")
    nodes = {
        "poro": add("_poro", props, title="PORO", type="ContinuousProperty",
                    propertyKind="porosity", uom="m3/m3"),
        "perm": add("_perm", props, title="PERM", type="ContinuousProperty",
                    propertyKind="permeability", uom="mD"),
        "facies": add("_facies", props, title="FACIES", type="CategoricalProperty",
                      propertyKind="facies"),
        "code": add("_code", props, title="CODE", type="DiscreteProperty"),
        "poro_mr": add("_poro_mr", props, title="PORO_MR", type="MultiRealization",
                       propertyKind="porosity", realization_indices="1,2,3"),
        "soil": add("_soil", props, title="SOIL", type="TimeSeries", propertyKind="saturation"),
        "sgas": add("_sgas", props, title="SGAS", type="MultiRealizationTimeSeries",
                    realization_indices="1,2"),
        "poro_h": add("_poro_h", props_h, title="PORO_H", type="ContinuousProperty",
                      propertyKind="porosity"),
    }
    blocked = add("_bw", grid, title="blocked wellbores", type="BlockedWellboreFolder")
    subs = add("_sub", grid, title="sub-representations", type="SubRepresentationFolder")
    nodes["w1"] = add("_w1", blocked, title="W1", type="BlockedWellbore")
    nodes["north"] = add("_north", subs, title="North", type="Sub")
    nodes["stub"] = add("_stub", subs, title="!!!PARTIAL!!!Far", type="Sub")
    return Tree(asm), {k: asm.GetNodePath(n) for k, n in nodes.items()}


def _state(*views, **shown):
    """A session with these 3D views (`vid`, title), `shown` their eyes."""
    state = SimpleNamespace(ui_vector_component={}, ui_active_realization_by_array_by_view={},
                            fespp_render_panels=[{"id": v, "title": t} for v, t in views])
    for vid, paths in shown.items():
        setattr(state, f"visible_paths__{vid}", paths)
    return state


def _item(path, uid, real=None, ts=None, pinned=False):
    return {"path": path, "real": real, "ts": ts, "uid": uid, "pinned": pinned}


def _on(path, support, real=None, ts=None):
    """The following row of an item of `path`, read on `support`."""
    item = cd._norm_item(_item(path, "i1", real, ts))
    return cd._norm_item(compare_rows._following(item, support, real, ts))


@pytest.fixture
def no_weights(monkeypatch):
    monkeypatch.setattr(cell_weights, "weights_for", lambda *a: {"note": ""})


@pytest.fixture
def item_values(monkeypatch):
    def read(state, tree, source_registry, path, rep, real_idx=None, ts_idx=None):
        return np.linspace(0.1, 0.3, 11)
    monkeypatch.setattr(cd, "_values_for", read)


@pytest.fixture
def part_values(monkeypatch):
    """The reads on a part; `calls` says at which realization and time."""
    calls = []

    def read(state, tree, source_registry, part, path, rep, real_idx=None, ts_idx=None,
             weights=None):
        calls.append((part, path, real_idx, ts_idx))
        blocked = part.endswith("_w1")
        return {"values": np.array([1.0, 2.0, 3.0, 4.0, np.nan]),
                "volume": None if blocked else np.ones(5),
                "pore": None,
                "length": np.array([1.0, 1.0, 1.0, 7.0, 1.0]) if blocked else None,
                "missing": 1}
    monkeypatch.setattr(stats_supports, "part_values", read)
    return calls


@pytest.fixture
def view_stats(monkeypatch):
    """What a 3D view draws of a property, the batch and the chain around it."""
    trail = []

    def build(state, source_registry, tree, path, rep, vid, title):
        trail.append(f"view {vid}")
        row = sd._row_stats_from_values(np.array([0.2, 0.25, 0.3, 0.35, 0.4]), "x")
        row.update(kind="view", id=vid, view_title=title, real_idx=2,
                   ts_idx=4, ts_label="2020-01-01")
        return row

    @contextmanager
    def chain():
        trail.append("chain in")
        yield
        trail.append("chain out")

    @contextmanager
    def batch():
        trail.append("batch in")
        yield
        trail.append("batch out")

    monkeypatch.setattr(sd, "_build_view_row", build)
    monkeypatch.setattr(sd, "transient_chain", chain)
    monkeypatch.setattr(property_values, "time_batch", batch)
    monkeypatch.setattr(sd, "_resolve_rendered_inputs",
                        lambda rep, vid: ([object()], None))
    return trail


# ---- the expansion ----------------------------------------------------------

def test_a_part_follows_each_unpinned_item_of_its_grid():
    tree, p = _tree()
    items = [_item(p["poro"], "i1", real=None), _item(p["poro"], "i2", ts=3),
             _item(p["poro"], "i3", pinned=True), _item(p["poro_h"], "i4")]
    rows = compare_rows.with_following(_state(), tree, items, [p["w1"]])
    assert [r["uid"] for r in rows] == ["i1", f"i1@{p['w1']}", "i2", f"i2@{p['w1']}", "i3", "i4"]
    follower = rows[3]
    assert follower == {"path": p["poro"], "real": None, "ts": 3, "uid": f"i2@{p['w1']}",
                        "pinned": False, "xplot": False, "support": p["w1"], "follows": "i2"}


def test_a_part_named_twice_is_one_row():
    tree, p = _tree()
    rows = compare_rows.with_following(_state(), tree, [_item(p["poro"], "i1")], [p["w1"], p["w1"]])
    assert [r["uid"] for r in rows] == ["i1", f"i1@{p['w1']}"]


def test_without_a_part_or_a_cut_the_rows_are_the_selection(monkeypatch):
    tree, p = _tree()
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: ([], None))
    items = [_item(p["poro"], "i1"), _item(p["perm"], "i2")]
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    rows = compare_rows.with_following(state, tree, items, [])
    assert [r["uid"] for r in rows] == ["i1", "i2"]
    assert compare_rows.with_following(None, tree, [], []) == []
    assert compare_rows.with_following(None, tree, None, None) == []


def test_a_view_that_cuts_the_grid_follows_the_first_unpinned_item_of_the_path(monkeypatch):
    tree, p = _tree()
    monkeypatch.setattr(sd, "_resolve_rendered_inputs",
                        lambda rep, vid: ([object()] if vid in ("v1", "v2") else [], None))
    state = _state(("v1", "3D view 1"), ("v2", "3D view 2"), ("v3", "3D view 3"), ("v4", "3D view 4"),
                   v1=[p["poro"]], v2=[p["perm"]], v3=[p["poro"]])
    items = [_item(p["poro"], "i0", real=1, pinned=True), _item(p["poro"], "i1", ts=7),
             _item(p["poro"], "i2"), _item(p["perm"], "i3")]
    rows = compare_rows.with_following(state, tree, items, [])
    # v1 cuts and shows PORO, v2 cuts and shows PERM, v3 shows the whole grid,
    # v4 shows neither
    assert [r["uid"] for r in rows] == ["i0", "i1", "i1@view:v1", "i2", "i3", "i3@view:v2"]
    # it reads the view's realization and time, whatever its item names
    assert (rows[2]["real"], rows[2]["ts"], rows[2]["support"], rows[2]["follows"]) == \
        (None, None, "view:v1", "i1")
    assert rows[2]["xplot"] is False and rows[2]["pinned"] is False


def test_an_expanded_list_expands_to_itself():
    tree, p = _tree()
    rows = compare_rows.with_following(_state(), tree, [_item(p["poro"], "i1")], [p["w1"]])
    assert compare_rows.with_following(_state(), tree, rows, [p["w1"]]) == rows


def test_an_entry_with_no_uid_names_its_rows_by_its_key():
    tree, p = _tree()
    rows = compare_rows.with_following(_state(), tree, [_item(p["poro"], "", real=2)], [p["north"]])
    key = cd.item_key(p["poro"], 2, None)
    assert rows[1]["uid"] == f"{key}@{p['north']}" and rows[1]["follows"] == key


# ---- the identity -----------------------------------------------------------

def test_the_support_joins_the_key():
    assert cd.item_key("/d/x", 3, 0) == "/d/x|3|0"
    assert cd.item_key("/d/x", 3, 0, "") == "/d/x|3|0"
    assert cd.item_key("/d/x", 3, 0, "view:v1") == "/d/x|3|0@view:v1"
    assert cd.item_key("/d/x", None, None, "session://v1/e1") == "/d/x||@session://v1/e1"


def test_norm_item_keeps_what_a_following_row_says():
    got = cd._norm_item({"path": "/p", "support": "view:v1", "follows": "i1"})
    assert (got["support"], got["follows"]) == ("view:v1", "i1")
    plain = cd._norm_item({"path": "/p"})
    assert (plain["support"], plain["follows"]) == ("", "")
    assert cd.item_id(cd._norm_item({"path": "/p", "support": "view:v1"})) == "/p||@view:v1"


# ---- the part's row ---------------------------------------------------------

@pytest.fixture
def tree_parts(no_weights, part_values, item_values):
    """An item at a realization and a time step, followed by a blocked wellbore."""
    tree, p = _tree()
    items = compare_rows.with_following(_state(), tree, [_item(p["poro_mr"], "i1", real=2, ts=5)],
                                        [p["w1"]])
    return tree, p, cd.rows_for(_state(), tree, None, items), items


def test_a_blocked_wellbore_row_reads_at_its_items_axis_and_has_its_mean_along_the_hole(
        tree_parts, part_values):
    tree, p, rows, items = tree_parts
    row = rows[items[1]["uid"]]
    assert part_values == [(p["w1"], p["poro_mr"], 2, 5)]
    assert row["metrics"]["Cardinality"] == 4.0 and row["metrics"]["NaN_count"] == 1.0
    assert row["metrics"]["Mean"] == pytest.approx(2.5)
    # (1 + 2 + 3 + 7 * 4) / 10: the last interval is the longest
    assert row["metrics"]["Mean (L)"] == pytest.approx(3.4)
    assert "Mean (V)" not in row["metrics"]
    assert row["support"] == p["w1"] and row["follows"] == "i1"
    assert row["support_label"] == "Blocked wellbore · W1"
    assert row["label"].startswith("PORO_MR on W1 · real 2")
    assert row["title"] == "PORO_MR" and row["rep"] == "Geogrid"
    assert row["reals"] == [] and row["ts_opts"] == []
    assert row["pinned"] is False and "xplot" not in row
    assert row["key"] == cd.item_key(p["poro_mr"], 2, 5, p["w1"])
    assert "1 of its cells lie in no cell of the grid" in row["note"]
    # its item keeps its pickers
    assert [o["value"] for o in rows["i1"]["reals"]] == [1, 2, 3]


def test_a_sub_representation_row_takes_the_grids_weights_on_its_cells(monkeypatch, part_values):
    """The note is what the weights say of THIS row: how many of its cells a
    weighted mean rests on, where the blocked wellbore's says nothing of them."""
    tree, p = _tree()
    monkeypatch.setattr(cell_weights, "weights_for",
                        lambda *a: {"note": "Net-to-gross taken as 1 on Geogrid."})
    state = _state()
    it = _on(p["poro"], p["north"])
    row = cd._row(state, tree, None, it)
    assert row["metrics"]["Mean"] == pytest.approx(2.5)
    assert "Mean (L)" not in row["metrics"]
    assert "Net-to-gross taken as 1 on Geogrid." in row["note"]
    assert row["support_label"] == "Sub-representation · North"
    it = _on(p["poro"], p["w1"])
    assert "Net-to-gross" not in cd._row(state, tree, None, it)["note"]


def test_a_part_that_cannot_be_read_says_why(monkeypatch, no_weights):
    tree, p = _tree()
    monkeypatch.setattr(stats_supports, "part_values", lambda *a, **k: None)
    monkeypatch.setitem(stats_supports._LAST_ERROR, "msg", "not loaded — tick it in the tree")
    it = _on(p["poro"], p["w1"])
    row = cd._row(_state(), tree, None, it)
    assert row["metrics"] == {}
    assert row["note"] == "Blocked wellbore · W1: not loaded — tick it in the tree."
    assert row["support_label"] == "Blocked wellbore · W1"

    def boom(*a, **k):
        raise RuntimeError("the reader fell over")
    monkeypatch.setattr(stats_supports, "part_values", boom)
    row = cd._row(_state(), tree, None, it)
    assert row["metrics"] == {} and "could not be read (the reader fell over)" in row["note"]


def test_a_following_row_of_a_property_being_read_waits_with_it(no_weights, monkeypatch):
    tree, p = _tree()
    monkeypatch.setattr(stats_supports, "part_values", lambda *a, **k: pytest.fail("read"))
    items = compare_rows.with_following(_state(), tree, [_item(p["poro"], "i1")], [p["w1"]])
    rows = cd.rows_for(_state(), tree, None, items, pending={p["poro"]: cd.LOADING})
    row = rows[items[1]["uid"]]
    assert row["load"] == cd.LOADING and row["metrics"] == {}
    assert row["label"] == "PORO on W1 · loading"


# ---- the view's row ---------------------------------------------------------

def test_a_view_row_is_read_after_the_batch_inside_one_chain(view_stats, no_weights, item_values):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), ("v2", "3D view 2"), v1=[p["poro"]], v2=[p["poro"]])
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1", ts=3)], [])
    rows = cd.rows_for(state, tree, None, items)
    assert view_stats == ["batch in", "batch out", "chain in", "view v1", "view v2", "chain out"]
    row = rows["i1@view:v1"]
    assert row["label"] == "PORO On 3D view 1" and row["support_label"] == "3D view 1"
    assert row["title"] == "PORO"
    assert row["support"] == "view:v1" and row["follows"] == "i1"
    # it names neither; what it reads is the view's
    assert row["real"] is None and row["ts"] is None
    assert row["real_read"] == 2
    assert row["ts_label"] == "2020-01-01" and row["ts_text"] == "2020-01-01"
    assert row["reals"] == [] and row["ts_opts"] == []
    assert row["metrics"]["Mean"] == pytest.approx(0.3)
    assert row["note"] == ("A view row shows the filtered display, whose cells are not the"
                           " grid's: the weighted means are reported on the rows of the"
                           " whole grid only.")


def test_no_view_row_no_chain(view_stats, no_weights, item_values):
    tree, p = _tree()
    cd.rows_for(_state(), tree, None, [_item(p["poro"], "i1")])
    assert view_stats == ["batch in", "batch out"]


def test_a_view_that_stopped_drawing_says_so(monkeypatch, view_stats, no_weights, item_values):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1")], [])
    monkeypatch.setattr(sd, "_build_view_row", lambda *a: None)
    row = cd.rows_for(state, tree, None, items)["i1@view:v1"]
    assert row["metrics"] == {} and row["note"].startswith("3D view 1: ")


def test_a_view_rows_nan_moment_is_a_metric_it_does_not_have(monkeypatch, view_stats, no_weights,
                                                             item_values):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1")], [])
    monkeypatch.setattr(sd, "_build_view_row",
                        lambda *a: {"kind": "view", "Mean": 0.2, "Skewness": float("nan")})
    metrics = cd.rows_for(state, tree, None, items)["i1@view:v1"]["metrics"]
    assert metrics == {"Mean": 0.2}


def test_a_view_row_is_never_cached_and_a_part_row_is(view_stats, part_values, no_weights, item_values):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1")], [p["w1"]])
    cache, loaded = {}, {p["poro"]}
    cd.rows_for(state, tree, None, items, cache=cache, loaded=loaded)
    assert set(cache) - {"_hits", "_reads"} == {cd.item_key(p["poro"], None, None),
                                                cd.item_key(p["poro"], None, None, p["w1"])}
    assert cache["_reads"] == 3
    cd.rows_for(state, tree, None, items, cache=cache, loaded=loaded)
    assert cache["_hits"] == 2 and cache["_reads"] == 1
    assert len(part_values) == 1 and view_stats.count("view v1") == 2


# ---- what a row says of itself ----------------------------------------------

def test_the_value_type_of_a_row():
    tree, p = _tree()
    facts = lambda k: compare_rows.row_facts(_state(), tree, p[k], None, None)  # noqa: E731
    assert facts("poro")["value_type"] == "Continuous property"
    assert facts("facies")["value_type"] == "Categorical property"
    assert facts("code")["value_type"] == "Discrete property"


def test_a_recipe_is_derived_and_reads_its_first_realization():
    tree, p = _tree()

    class Store:
        def get(self, path):
            return {"prop_kind": "ContinuousProperty", "uom": ""}

        def title(self, path):
            return "PHIE"

        def axis_caps(self, tree, path):
            return {"is_mr": True, "is_ts": False, "reals": [4, 5]}

    derived_props.set_store(Store())
    try:
        path = derived_props.path_for("/data/_gridfolder_g/_props_g/_g", "PHIE")
        facts = compare_rows.row_facts(_state(), tree, path, None, None)
        assert facts["value_type"] == "Derived"
        assert facts["real_read"] == 4 and facts["ts_text"] == ""
        assert compare_rows.row_facts(_state(), tree, path, 5, None)["real_read"] == 5
    finally:
        derived_props.set_store(None)


def test_the_realization_a_row_reads():
    tree, p = _tree()
    facts = lambda k, real=None: compare_rows.row_facts(_state(), tree, p[k], real, None)  # noqa: E731
    assert facts("poro_mr")["real_read"] == 1, "the first available when it names none"
    assert facts("poro_mr", 3)["real_read"] == 3
    assert facts("poro")["real_read"] is None


def test_the_time_step_a_row_reads_in_words(monkeypatch):
    from fespp_on_trame.engine import view_axes
    tree, p = _tree()
    facts = lambda k, ts=None: compare_rows.row_facts(_state(), tree, p[k], None, ts)  # noqa: E731
    monkeypatch.setattr(view_axes, "session_time", lambda: 5.0)
    tree._data_assembly.SetAttribute(0, "time5.000000", "2021-03-01T00:00:00")
    assert facts("soil")["ts_text"] == "2021-03-01", "the session's on a time series"
    assert facts("sgas")["ts_text"] == "2021-03-01"
    assert facts("poro")["ts_text"] == "", "nothing to say with no time step"
    monkeypatch.setattr(sd, "_ts_label_for_idx", lambda tree, ts: "2022-06-01" if ts == 1 else "")
    assert facts("soil", 1)["ts_text"] == "2022-06-01"
    assert facts("soil", 2)["ts_text"] == "t2"


def test_the_row_uses_the_richer_weights_note(monkeypatch, item_values):
    """What the row says of its weights, each sentence once."""
    tree, p = _tree()
    weights = {"volume": np.where(np.arange(11) < 8, 1.0, np.nan), "pore": None, "real_idx": 1,
               "poro_path": p["poro_mr"], "poro_title": "PORO_MR", "ntg_path": "",
               "note": "Net-to-gross taken as 1 on Geogrid: no net-to-gross property."}
    monkeypatch.setattr(cell_weights, "weights_for", lambda *a: weights)
    item = cd._norm_item(_item(p["poro_mr"], "i1", real=2))
    note = cd._row(_state(), tree, None, item)["note"]
    assert "Net-to-gross taken as 1 on Geogrid" in note
    assert "computed on 8 of the 11 valued cells" in note
    assert "read once, at realization 1: a row at realization 2" in note
    assert note.count("weighted by itself") == 1 and "always above the plain mean" in note
    # the row at the weight's realization has nothing to say of it
    item = cd._norm_item(_item(p["poro_mr"], "i1", real=1))
    assert "read once" not in cd._row(_state(), tree, None, item)["note"]


# ---- the blocks -------------------------------------------------------------

def _rows_of(tree, p, *items, parts=(), state=None):
    state = state or _state()
    expanded = compare_rows.with_following(state, tree, list(items), list(parts))
    return expanded, cd.rows_for(state, tree, None, expanded)


def test_a_sum_goes_only_when_no_row_of_the_block_has_one(no_weights, item_values):
    tree, p = _tree()
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), _item(p["perm"], "i2"),
                           _item(p["facies"], "i3"))
    assert rows["i1"]["sum_meaningful"] is False, "a fraction, by its unit"
    assert rows["i2"]["sum_meaningful"] is True
    assert rows["i3"]["sum_meaningful"] is False, "codes"
    by_kind = {b["kind"]: b for b in cd.blocks_from_rows(items, rows, "", "", True)[0]}
    assert by_kind["porosity"]["sum_meaningful"] is False
    assert by_kind["permeability"]["sum_meaningful"] is True
    items = [{"path": "/p", "uid": k} for k in "ab"]
    mixed = {"a": {"kind": "k", "sum_meaningful": False}, "b": {"kind": "k", "sum_meaningful": True}}
    assert cd.blocks_from_rows(items, mixed, "", "", True)[0][0]["sum_meaningful"] is True
    unsaid = {"a": {"kind": "k", "sum_meaningful": False}, "b": {"kind": "k"}}
    assert cd.blocks_from_rows(items, unsaid, "", "", True)[0][0]["sum_meaningful"] is True


def test_a_block_has_length_with_a_row_read_along_the_hole(no_weights, part_values, item_values):
    tree, p = _tree()
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), parts=[p["w1"]])
    assert cd.blocks_from_rows(items, rows, "", "", True)[0][0]["has_length"] is True
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), parts=[p["north"]])
    assert cd.blocks_from_rows(items, rows, "", "", True)[0][0]["has_length"] is False


def test_a_following_row_is_sorted_and_read_against_the_baseline(no_weights, part_values, item_values):
    tree, p = _tree()
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), _item(p["poro_h"], "i2"), parts=[p["w1"]])
    follower = f"i1@{p['w1']}"
    assert [it["uid"] for it in items] == ["i1", follower, "i2"]
    blocks, ann = cd.blocks_from_rows(items, rows, "i2", "", True)
    assert blocks[0]["keys"] == ["i2", "i1", follower], "right under its item, sort aside"
    assert ann[follower]["Mean"] == "pos"
    deltas = cd.deltas_from_rows(items, rows, "i2")
    assert deltas[follower]["Mean"]["abs"] == pytest.approx(2.5 - 0.2)
    blocks, _ = cd.blocks_from_rows(items, rows, "i2", "Mean", False)
    assert blocks[0]["keys"] == ["i2", follower, "i1"], "the largest Mean first"
    blocks, _ = cd.blocks_from_rows(items, rows, "i2", "Mean", True)
    assert blocks[0]["keys"] == ["i2", "i1", follower]


def test_what_follows_the_baseline_stays_right_under_it(no_weights, part_values, item_values):
    tree, p = _tree()
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), _item(p["poro_mr"], "i2"), parts=[p["w1"]])
    w1 = f"@{p['w1']}"
    blocks, _ = cd.blocks_from_rows(items, rows, "i2", "", True)
    assert blocks[0]["keys"] == ["i2", "i2" + w1, "i1", "i1" + w1]
    # a sort puts every row but the baseline in its place
    blocks, _ = cd.blocks_from_rows(items, rows, "i2", "Mean", False)
    assert blocks[0]["keys"][0] == "i2" and blocks[0]["keys"][-1] == "i1"


def test_a_following_row_is_never_the_baseline(no_weights, part_values, item_values):
    tree, p = _tree()
    items, rows = _rows_of(tree, p, _item(p["poro"], "i1"), _item(p["poro_h"], "i2"), parts=[p["w1"]])
    follower = f"i1@{p['w1']}"
    for key in (follower, cd.item_key(p["poro"], None, None, p["w1"])):
        blocks, ann = cd.blocks_from_rows(items, rows, key, "", True)
        assert blocks[0]["keys"][0] == "i1", "selection order, as with no baseline"
        assert ann["i1"].get("Mean") != "eq", "no row is read against it"
        assert cd.deltas_from_rows(items, rows, key) == {}
    # the rows of an expansion start with an item whatever its order
    only = [{"path": "/p", "uid": "x", "support": "view:v1"}]
    assert cd._baseline_index([cd._norm_item(it) for it in only], "x") is None


# ---- the distribution -------------------------------------------------------

def _dist(tree, state, items, **opts):
    fig, meta = cd.dist_figure(state, tree, None, items, dict({"nbins": 10}, **opts))
    return (fig.to_plotly_json() if fig is not None else None), meta


def test_the_distribution_draws_the_following_rows(monkeypatch, part_values, view_stats, item_values):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    monkeypatch.setattr(sd, "_resolve_rendered_inputs",
                        lambda rep, vid: ([drawn_cells.Drawn(object())], None))
    monkeypatch.setattr(property_values, "named_values", lambda *a: np.array([0.2, 0.4, np.nan]))
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1", real=2, ts=5)], [p["w1"]])
    js, meta = _dist(tree, state, items)
    assert [t["name"] for t in js["data"]] == ["PORO · real 2 · t5", "PORO on W1 · real 2 · t5",
                                               "PORO On 3D view 1"]
    assert meta["traces"] == 3 and meta["note"] == ""
    assert meta["kept"] == 11 + 4 + 2 and meta["total"] == 11 + 5 + 3
    assert part_values == [(p["w1"], p["poro"], 2, 5)], "at its item's realization and time"


def test_an_unreadable_following_row_is_noted_beside_the_drawn_ones(monkeypatch, item_values):
    pytest.importorskip("plotly")
    tree, p = _tree()
    monkeypatch.setattr(stats_supports, "part_values", lambda *a, **k: None)
    monkeypatch.setitem(stats_supports._LAST_ERROR, "msg", "its grid has no cells loaded")
    items = compare_rows.with_following(_state(), tree, [_item(p["poro"], "i1")], [p["w1"]])
    js, meta = _dist(tree, _state(), items)
    assert [t["name"] for t in js["data"]] == ["PORO"]
    assert meta["note"] == "not drawn: PORO on W1 (its grid has no cells loaded)"


def test_a_following_row_moves_neither_a_colour_nor_the_zoom(part_values, item_values):
    pytest.importorskip("plotly")
    tree, p = _tree()
    selection = [_item(p["poro"], "i1"), _item(p["poro_h"], "i2")]
    alone, _ = _dist(tree, _state(), compare_rows.with_following(_state(), tree, selection, []))
    with_part, _ = _dist(tree, _state(), compare_rows.with_following(_state(), tree, selection, [p["w1"]]))
    colour = {t["name"]: t["marker"]["color"] for t in with_part["data"]}
    assert [t["marker"]["color"] for t in alone["data"]] == [colour["PORO"], colour["PORO_H"]]
    assert colour["PORO on W1"] not in (colour["PORO"], colour["PORO_H"])
    assert alone["layout"]["uirevision"] == with_part["layout"]["uirevision"]


# ---- the values of a following row ------------------------------------------

def test_the_values_of_a_part(part_values):
    tree, p = _tree()
    it = _on(p["poro"], p["north"], 1, 2)
    vals = compare_rows.support_values(_state(), tree, None, it)
    assert list(vals[:4]) == [1.0, 2.0, 3.0, 4.0]
    assert part_values == [(p["north"], p["poro"], 1, 2)]
    assert compare_rows.last_error() == ""


def test_the_values_of_a_part_that_cannot_be_read_say_why(monkeypatch):
    tree, p = _tree()
    it = _on(p["poro"], p["north"])
    monkeypatch.setattr(stats_supports, "part_values", lambda *a, **k: None)
    monkeypatch.setitem(stats_supports._LAST_ERROR, "msg", "not loaded — tick it in the tree")
    assert compare_rows.support_values(_state(), tree, None, it) is None
    assert compare_rows.last_error() == "not loaded — tick it in the tree"

    def boom(*a, **k):
        raise RuntimeError("the reader fell over")
    monkeypatch.setattr(stats_supports, "part_values", boom)
    assert compare_rows.support_values(_state(), tree, None, it) is None
    assert compare_rows.last_error() == "the reader fell over"


def test_the_values_of_a_view_come_off_what_it_draws(monkeypatch):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"))
    state.ui_active_realization_by_array_by_view = {"v1": {p["poro_mr"]: 3}}
    state.ui_vector_component = {p["poro_mr"]: 1}
    display, seen = object(), []

    def read(source, name, component):
        seen.append((source, name, component))
        return np.array([0.5])

    drawn = [drawn_cells.Drawn(display)]
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: (drawn, None))
    monkeypatch.setattr(property_values, "named_values", read)
    it = _on(p["poro_mr"], "view:v1")
    vals = compare_rows.support_values(state, tree, None, it)
    assert list(vals) == [0.5]
    assert seen == [(display, "PORO_MR_real_3", 1)]
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: ([], None))
    assert compare_rows.support_values(state, tree, None, it) is None
    assert compare_rows.last_error() == "the view draws nothing of it"
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: (drawn, None))
    monkeypatch.setattr(property_values, "named_values", lambda *a: None)
    assert compare_rows.support_values(state, tree, None, it) is None
    assert compare_rows.last_error() == "what the view draws does not carry it"


def test_named_values_are_one_per_element_and_blank_the_ghosts(monkeypatch):
    from vtkmodules.util.numpy_support import numpy_to_vtk
    vector = numpy_to_vtk(np.array([[3.0, 4.0], [6.0, 8.0], [0.0, 1.0]]))
    ghost = numpy_to_vtk(np.array([0, 32, 0], dtype=np.uint8))
    monkeypatch.setattr(property_values, "_named_and_ghost", lambda source, name: (vector, ghost))
    got = property_values.named_values(object(), "v", None)
    assert list(got[[0, 2]]) == [5.0, 1.0] and np.isnan(got[1])
    assert list(property_values.named_values(object(), "v", 0)[[0, 2]]) == [3.0, 0.0]
    monkeypatch.setattr(property_values, "_named_and_ghost", lambda source, name: (None, None))
    assert property_values.named_values(object(), "v", None) is None


# ---- the file ---------------------------------------------------------------

def test_the_csv_says_where_a_following_row_was_read(view_stats, part_values, no_weights, item_values):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1")], [p["w1"]])
    rows = cd.rows_for(state, tree, None, items)
    header = cd.csv_payload(items, rows, "", kind="porosity")["header"]
    assert "# items: 1" in header, "the selection: a following row is not an entry of it"
    assert any(line.startswith("# item: PORO (Geogrid)") for line in header)
    assert any(line.startswith("# following row: PORO on W1 (Blocked wellbore · W1 of Geogrid)"
                               " - Blocked wellbore · W1: 1 of its cells") for line in header)
    assert any(line.startswith("# following row: PORO On 3D view 1 (the filtered display of"
                               " 3D view 1, real 2, 2020-01-01) - A view row") for line in header)
    assert header[0].endswith(" - statistics")


def test_the_csv_says_what_weighs_the_mean_pv_once_per_grid(monkeypatch, item_values):
    tree, p = _tree()
    monkeypatch.setattr(cell_weights, "weights_for", lambda *a: {
        "volume": np.ones(11), "pore": np.ones(11), "note": "", "ntg_title": "NTG",
        "poro_title": "PHI", "real_idx": 2})
    items = [_item(p["poro"], "i1"), _item(p["perm"], "i2")]
    header = cd.csv_payload(items, cd.rows_for(_state(), tree, None, items), "")["header"]
    assert header.count("# pore volume: Geogrid: volume x net-to-gross x porosity"
                        " (NTG, PHI, both read at realization 2)") == 1


def test_the_csv_names_no_pore_volume_a_grid_has_none_of(no_weights, item_values):
    tree, p = _tree()
    items = [_item(p["poro"], "i1")]
    header = cd.csv_payload(items, cd.rows_for(_state(), tree, None, items), "")["header"]
    assert not any(line.startswith("# pore volume") for line in header)


# ---- Mean (L), a metric like the others -------------------------------------

def test_mean_l_sits_after_mean_pv():
    keys = list(compare_matrix._METRIC_KEYS)
    assert keys[keys.index("Mean (PV)") + 1] == "Mean (L)"


# ---- transient_chain --------------------------------------------------------

class _Active:
    """The active source and view pvsimple holds."""

    def __init__(self):
        self.source, self.view = "the source", "the view"

    def GetActiveSource(self):
        return self.source

    def GetActiveView(self):
        return self.view

    def SetActiveSource(self, source):
        self.source = source

    def SetActiveView(self, view):
        self.view = view


def test_the_chain_clears_the_view_then_puts_everything_back(monkeypatch):
    from vtkmodules.vtkCommonCore import vtkObject
    active = _Active()
    monkeypatch.setattr(sd, "pvsimple", active)
    before = vtkObject.GetGlobalWarningDisplay()
    with sd.transient_chain():
        assert active.view is None
        assert vtkObject.GetGlobalWarningDisplay() == 0
        active.source = "a transient filter"
    assert (active.source, active.view) == ("the source", "the view")
    assert vtkObject.GetGlobalWarningDisplay() == before


def test_the_chain_puts_everything_back_on_a_failure(monkeypatch):
    active = _Active()
    monkeypatch.setattr(sd, "pvsimple", active)
    with pytest.raises(RuntimeError):
        with sd.transient_chain():
            active.source = "a transient filter"
            raise RuntimeError("no")
    assert (active.source, active.view) == ("the source", "the view")


# ---- the parts the file holds, in the tree ----------------------------------

def test_every_part_of_the_file_and_no_stub():
    tree, p = _tree()
    assert stats_supports.assembly_parts(tree) == [p["w1"], p["north"]]
    assert stats_supports.assembly_parts(None) == []
    assert stats_supports.assembly_parts(Tree(FakeDataAssembly())) == []


def test_a_file_with_no_part_has_no_folder():
    tree, p = _tree()
    xml, path_map = ct.kind_tree_xml(tree, [p["poro"]], parts=[])
    assert [k.get("title") for k in ET.fromstring(xml)] == ["porosity"]
    assert (xml, path_map) == ct.kind_tree_xml(tree, [p["poro"]])


def test_the_parts_come_after_the_kinds_filed_by_what_they_are():
    tree, p = _tree()
    xml, path_map = ct.kind_tree_xml(tree, [p["poro"], p["perm"]],
                                     parts=stats_supports.assembly_parts(tree))
    root = ET.fromstring(xml)
    assert [k.get("title") for k in root] == ["porosity", "permeability", ct.PARTS_KIND]
    parts = root[-1]
    assert parts.get("type") == "KindFolder" and parts.get("title") == "Parts of a grid"
    assert [(r.get("type"), r.get("title"), r.get("family")) for r in parts] == \
        [("RepFolder", "Blocked wellbore", "Reservoir"), ("RepFolder", "Sub-representation", "Reservoir")]
    w1 = parts[0][0]
    assert (w1.get("type"), w1.get("title"), w1.get("eye")) == ("ComparePart", "W1", "array")
    assert w1.get("propType") == "BlockedWellbore", "the leaf wears what it is"
    assert parts[1][0].get("propType") == "Sub"
    assert parts.get("sortLast"), "and the widget, which sorts by title, keeps them there"
    # the widget's rule: "/<root>/<tag>/<tag>/<tag>"
    assert ct.PARTS_FOLDER == f"/compare/{parts.tag}"
    assert {s: q for s, q in path_map.items() if q in (p["w1"], p["north"])} == {
        f"{ct.PARTS_FOLDER}/{parts[0].tag}/{parts[0][0].tag}": p["w1"],
        f"{ct.PARTS_FOLDER}/{parts[1].tag}/{parts[1][0].tag}": p["north"]}
    assert len(path_map) == 4, "and the properties' own"
    # tags stay unique per level, the widget builds its paths from them
    tags = [el.tag for el in root.iter()]
    assert len(tags) == len(set(tags))


def test_one_rep_folder_per_kind_of_part_and_family():
    """A tab keeps what its family says: a part of a surface is no Reservoir's."""
    asm = FakeDataAssembly()
    add = asm.add_node_with_attrs
    grid = add("_gridfolder_g", 0, title="Geogrid", type="GridContainer", typeCode="2")
    props = add("_props_g", grid, title="properties", type="PropertiesFolder", typeCode="2")
    add("_g", props, title="SolidColor", type="IjkGrid", typeCode="2")
    surf = add("_top", 0, title="Top", type="TriangulatedSet", typeCode="2")
    a = asm.GetNodePath(add("_a", grid, title="A", type="Sub", typeCode="2"))
    b = asm.GetNodePath(add("_b", surf, title="B", type="SubRepresentation", typeCode="2"))
    xml, _ = ct.kind_tree_xml(Tree(asm), [], parts=[a, b])
    folder = ET.fromstring(xml)[0]
    assert [(r.get("title"), r.get("family"), [leaf.get("title") for leaf in r]) for r in folder] == \
        [("Sub-representation", "Reservoir", ["A"]), ("Sub-representation", "Surface", ["B"])]


def test_a_part_leaf_says_whether_it_is_read():
    tree, p = _tree()
    xml, _ = ct.kind_tree_xml(tree, [], loaded={p["w1"]}, pending={p["north"]: cd.LOADING},
                              parts=[p["w1"], p["north"]])
    w1, north = ET.fromstring(xml)[0]
    assert w1[0].get("loadState") is None and w1[0].get("info") is None
    assert north[0].get("loadState") == cd.LOADING


def test_a_blocked_wellbores_lengths_are_the_plugins_array():
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from vtkmodules.vtkCommonCore import vtkDoubleArray
    from vtkmodules.vtkCommonDataModel import vtkUnstructuredGrid
    grid = vtkUnstructuredGrid()
    lengths = vtkDoubleArray()
    lengths.SetName(stats_supports.LENGTH_ARRAY)
    lengths.SetNumberOfTuples(2)
    lengths.SetValue(0, 3.0)
    lengths.SetValue(1, 5.0)
    grid.GetCellData().AddArray(lengths)
    assert list(stats_supports._lengths(np, vtk_to_numpy, [grid])) == [3.0, 5.0]


def test_two_reads_of_the_same_values_are_equal_to_the_baseline():
    """A 3D view's row and its property's are read by two chains that do not
    sum in the same order: their noise is no difference."""
    base = {"Mean": 0.165, "Sum": 3.96, "Skewness": 0.0, "M2": 0.115, "M3": 0.0,
            "Standard Deviation": 0.07071, "Cardinality": 24.0}
    read = dict(base, Mean=0.165 + 5.551e-17, Skewness=-1.782e-18, M3=-1e-19, Sum=3.96 + 4e-16)
    rows = [base, read]
    tags = compare_matrix.highlight_annotations(rows, "baseline", 0)
    deltas = compare_matrix.baseline_deltas(rows, 0)
    for metric in ("Mean", "Sum", "Skewness", "M3"):
        assert tags[metric][1] == "eq", metric
        assert deltas[metric][1]["abs"] == 0.0, metric
    other = dict(base, Mean=0.17)
    assert compare_matrix.highlight_annotations([base, other], "baseline", 0)["Mean"][1] == "pos"


def test_the_tabs_list_the_family_of_a_part():
    asm = FakeDataAssembly()
    odd = asm.GetNodePath(asm.add_node_with_attrs("_odd", 0, title="Odd", type="Sub", typeCode="2"))
    xml, _ = ct.kind_tree_xml(Tree(asm), [], parts=[odd])
    assert [t["name"] for t in ct.tree_tabs(xml)] == ["Reservoir", "Surface", "Well", "Seismic", "Other"]


# ---- what a 3D view draws, cell by cell --------------------------------------

def _cells(values, ids=None, ghost=None, xs=None):
    """A grid of one hexahedron per value, along X, its cell array `a`, and the
    cells' ids when it carries them."""
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import VTK_HEXAHEDRON, vtkUnstructuredGrid
    grid = vtkUnstructuredGrid()
    points = vtkPoints()
    xs = list(range(len(values))) if xs is None else xs
    for n, x in enumerate(xs):
        for corner in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)):
            points.InsertNextPoint(x + corner[0], corner[1], corner[2])
    grid.SetPoints(points)
    for n in range(len(values)):
        grid.InsertNextCell(VTK_HEXAHEDRON, 8, [8 * n + c for c in range(8)])

    def add(name, array, kind):
        arr = numpy_to_vtk(np.asarray(array, dtype=kind), deep=1)
        arr.SetName(name)
        grid.GetCellData().AddArray(arr)

    add("a", values, float)
    if ids is not None:
        add("vtkOriginalCellIds", ids, np.int64)
    if ghost is not None:
        add("vtkGhostType", ghost, np.uint8)
    return grid


class _Proxy:
    """What holds a dataset, as a filter's proxy does."""

    def __init__(self, data):
        self.data = data

    def UpdatePipeline(self):
        pass

    def GetClientSideObject(self):
        return SimpleNamespace(GetOutputDataObject=lambda port: self.data)


def _read(*parts, name="a", component=None):
    got = drawn_cells.values(list(parts), name, component)
    return None if got is None else sorted(got.tolist())


def test_a_cell_two_cuts_hold_counts_once():
    i_cut = _Proxy(_cells([1.0, 2.0, 3.0], ids=[0, 4, 8]))
    j_cut = _Proxy(_cells([2.0, 5.0], ids=[4, 5]))
    assert _read(drawn_cells.Drawn(i_cut), drawn_cells.Drawn(j_cut)) == [1.0, 2.0, 3.0, 5.0]


def test_the_grid_drawn_whole_beside_a_cut_is_indexed_by_its_own_cells():
    whole = _Proxy(_cells([1.0, 2.0, 3.0]))
    crop = _Proxy(_cells([3.0, 9.0], ids=[2, 7]))
    assert _read(drawn_cells.Drawn(whole), drawn_cells.Drawn(crop)) == [1.0, 2.0, 3.0, 9.0]


def test_two_thresholds_on_the_grid_itself_count_a_cell_both_keep_once():
    """They carry no ids: the cells of each come from its ranges."""
    grid = _Proxy(_cells([0.1, 0.2, 0.25, 0.3, 0.5], ghost=[0, 32, 0, 0, 0]))
    low = _Proxy(_cells([0.1, 0.25]))
    high = _Proxy(_cells([0.25, 0.3, 0.5]))
    parts = (drawn_cells.Drawn(low, branch=[("a", "CELLS", 0.1, 0.25)], root=grid),
             drawn_cells.Drawn(high, branch=[("a", "CELLS", 0.25, 0.5)], root=grid))
    assert _read(*parts) == [0.1, 0.25, 0.3, 0.5]
    assert drawn_cells.last_error() == ""


def test_a_threshold_s_bound_is_compared_in_doubles_as_the_filter_does():
    from vtkmodules.util.numpy_support import numpy_to_vtk
    grid = _cells([0.1, 0.2])
    single = numpy_to_vtk(np.array([0.1, 0.2], dtype=np.float32), deep=1)
    single.SetName("f")
    grid.GetCellData().AddArray(single)
    part = drawn_cells.Drawn(_Proxy(_cells([0.2])), branch=[("f", "CELLS", 0.0, 0.1)], root=_Proxy(grid))
    # the float 0.1 is a little above the double 0.1: below that bound lies nothing
    assert list(drawn_cells._branch_cells(part)) == []
    part = part._replace(branch=[("f", "CELLS", 0.1, 0.2)])
    assert list(drawn_cells._branch_cells(part)) == [0], "the float 0.2 is a little above too"


def test_thresholds_that_cannot_be_told_apart_are_not_counted_twice_in_silence():
    grid = _Proxy(_cells([0.1, 0.2]))
    a, b = _Proxy(_cells([0.1])), _Proxy(_cells([0.1]))
    on_nodes = drawn_cells.Drawn(a, branch=[("a", "POINTS", 0.0, 0.2)], root=grid)
    assert _read(on_nodes, drawn_cells.Drawn(b, branch=[("a", "CELLS", 0.0, 0.1)], root=grid)) is None
    assert "could not be told apart" in drawn_cells.last_error()
    other_count = drawn_cells.Drawn(a, branch=[("a", "CELLS", 0.0, 0.2)], root=grid)
    assert _read(other_count, drawn_cells.Drawn(b, branch=[("a", "CELLS", 0.0, 0.1)], root=grid)) is None
    assert "could not be told apart" in drawn_cells.last_error()


def test_a_threshold_alone_needs_no_ids():
    grid = _Proxy(_cells([0.1, 0.2]))
    tip = drawn_cells.Drawn(_Proxy(_cells([0.1])), boxes=[[[-1.0, 9.0], [-1.0, 9.0], [-1.0, 9.0]]],
                            branch=[("a", "POINTS", 0.0, 0.2)], root=grid)
    # read through a cut scene's preparation, which gives every cell its extent
    from fespp_on_trame.engine.blockscope import scene_crop
    tip = tip._replace(proxy=_Proxy(scene_crop._prep_leaf(tip.proxy.data, {}, {})))
    assert _read(tip) == [0.1]


def test_a_cut_scene_is_read_on_every_cell_a_box_meets_not_on_the_faces_it_draws():
    from fespp_on_trame.engine.blockscope import scene_crop
    prep = scene_crop._prep_leaf(_cells([1.0, 2.0, 3.0, 4.0], xs=[0, 10, 20, 30]), {}, {})
    boxes = [[[5.0, 25.0], [0.0, 1.0], [0.0, 1.0]]]
    assert _read(drawn_cells.Drawn(_Proxy(prep), boxes=boxes)) == [2.0, 3.0]
    two = [[[5.0, 25.0], [0.0, 1.0], [0.0, 1.0]], [[15.0, 35.0], [0.0, 1.0], [0.0, 1.0]]]
    assert _read(drawn_cells.Drawn(_Proxy(prep), boxes=two)) == [2.0, 3.0, 4.0]


def test_a_cut_scene_read_on_several_displays_counts_a_cell_once():
    from fespp_on_trame.engine.blockscope import scene_crop
    boxes = [[[-1.0, 15.0], [0.0, 1.0], [0.0, 1.0]]]
    a = scene_crop._prep_leaf(_cells([1.0, 2.0, 3.0], ids=[7, 8, 9], xs=[0, 10, 20]), {}, {})
    b = scene_crop._prep_leaf(_cells([2.0, 5.0], ids=[8, 3], xs=[10, 40]), {}, {})
    assert _read(drawn_cells.Drawn(_Proxy(a), boxes=boxes), drawn_cells.Drawn(_Proxy(b), boxes=boxes)) == [1.0, 2.0]


def test_a_composite_on_a_cut_scene_reads_the_leaves_of_its_grid():
    from vtkmodules.vtkCommonDataModel import vtkPartitionedDataSet, vtkPartitionedDataSetCollection
    from fespp_on_trame.engine.blockscope import scene_crop
    leaf = scene_crop._prep_leaf(_cells([1.0, 2.0, 3.0], xs=[0, 10, 20]), {}, {})
    other = scene_crop._prep_leaf(_cells([7.0], xs=[0]), {}, {})
    scene = vtkPartitionedDataSetCollection()
    for n, ds in enumerate((other, leaf)):
        pds = vtkPartitionedDataSet()
        pds.SetPartition(0, ds)
        scene.SetPartitionedDataSet(n, pds)
    boxes = [[[5.0, 25.0], [0.0, 1.0], [0.0, 1.0]]]
    # flat: 0 the collection, 1 the first dataset, 2 its leaf, 3 the second, 4 its leaf
    assert _read(drawn_cells.Drawn(_Proxy(scene), boxes=boxes, flats=(4,))) == [2.0, 3.0]
    assert _read(drawn_cells.Drawn(_Proxy(scene), boxes=boxes, flats=(99,))) is None


def test_a_hidden_cell_is_no_value_and_a_vector_is_one_value_per_cell():
    from vtkmodules.util.numpy_support import numpy_to_vtk
    grid = _cells([1.0, 2.0], ids=[0, 1], ghost=[0, 32])
    vector = numpy_to_vtk(np.array([[3.0, 4.0], [6.0, 8.0]]), deep=1)
    vector.SetName("v")
    grid.GetCellData().AddArray(vector)
    part = drawn_cells.Drawn(_Proxy(grid))
    got = drawn_cells.values([part, drawn_cells.Drawn(_Proxy(_cells([1.0], ids=[0])))], "a", None)
    assert got[0] == 1.0 and np.isnan(got[1]) and got.size == 2
    other = _cells([1.0], ids=[9])
    other.GetCellData().AddArray(vector)
    got = drawn_cells.values([part, drawn_cells.Drawn(_Proxy(other))], "v", None)
    assert got[0] == 5.0 and np.isnan(got[1]), "the magnitude, as everywhere"


def test_a_property_on_the_nodes_says_why_it_has_no_figures():
    from vtkmodules.util.numpy_support import numpy_to_vtk
    grid = _cells([1.0], ids=[0])
    nodes = numpy_to_vtk(np.zeros(grid.GetNumberOfPoints()), deep=1)
    nodes.SetName("n")
    grid.GetPointData().AddArray(nodes)
    part = drawn_cells.Drawn(_Proxy(grid))
    assert _read(part, part, name="n") is None
    assert drawn_cells.last_error() == drawn_cells._ON_NODES
    assert _read(part, part, name="nothing") is None
    assert drawn_cells.last_error() == "what the view draws does not carry it"


def test_nothing_drawn_says_so():
    assert drawn_cells.values([], "a", None) is None
    assert drawn_cells.last_error() == "the view draws nothing of it"


def test_a_view_row_on_several_displays_counts_each_cell_once(monkeypatch):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    parts = [drawn_cells.Drawn(_Proxy(_cells([0.1, 0.2], ids=[0, 1]))),
             drawn_cells.Drawn(_Proxy(_cells([0.2, 0.4], ids=[1, 2])))]
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: (parts, None))
    monkeypatch.setattr(sd, "_compute_one_variable", lambda *a, **k: pytest.fail("the filter chain"))
    # the view's array is named as the title makes it
    for part in parts:
        array = part.proxy.data.GetCellData().GetArray("a")
        array.SetName("PORO")
    row = sd._build_view_row(state, None, tree, p["poro"], cd._rep_path(tree, p["poro"]), "v1", "3D view 1")
    assert row["Cardinality"] == 3.0 and row["Mean"] == pytest.approx(0.7 / 3)
    assert row["kind"] == "view" and row["label"].startswith("PORO")


def test_a_view_row_on_one_display_keeps_the_filter_chain(monkeypatch):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    display = object()
    monkeypatch.setattr(sd, "_resolve_rendered_inputs", lambda rep, vid: ([drawn_cells.Drawn(display)], None))
    asked = []

    def chain(source, name, component=None):
        asked.append((source, name))
        return {"Cardinality": 3.0, "Mean": 0.5}

    monkeypatch.setattr(sd, "_compute_one_variable", chain)
    row = sd._build_view_row(state, None, tree, p["poro"], cd._rep_path(tree, p["poro"]), "v1", "3D view 1")
    assert asked == [(display, "PORO")] and row["Cardinality"] == 3.0


def test_a_view_row_that_cannot_count_a_cell_once_says_why(monkeypatch, view_stats):
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    it = _on(p["poro"], "view:v1")

    def refuses(*a):
        drawn_cells._LAST_ERROR["msg"] = drawn_cells._ON_NODES
        return None

    monkeypatch.setattr(sd, "_build_view_row", refuses)
    assert cd._row(state, tree, None, it)["note"] == f"3D view 1: {drawn_cells._ON_NODES}."
    # a reason from an earlier read is not this one's
    monkeypatch.setattr(sd, "_build_view_row", lambda *a: None)
    assert cd._row(state, tree, None, it)["note"] == "3D view 1: what it draws of this property could not be read."


# ---- what an isolate draws in its view --------------------------------------

def _isolate(mask=None, tips=(), volumes=(), scene_crops=None):
    """An isolate over what it needs of itself: its root, its chain."""
    from fespp_on_trame.engine.sources.ijkgrid import IjkGrid, _IjkChainEntry
    iso = IjkGrid.__new__(IjkGrid)
    iso._src_extract_init = "extractor"
    iso._nan_mask = mask
    iso._src_slicers_i, iso._src_slicers_j, iso._src_slicers_k = [], [], []
    iso._src_volumes = list(volumes)
    iso._chain = []
    iso._scene_crops = scene_crops
    iso._node_id = None
    for name, parent, low, high, proxies in tips:
        entry = _IjkChainEntry(name, parent, "a", "CELLS", True, low, high, (0.0, 1.0))
        entry.pv_proxies = {id(k): v for k, v in proxies.items()}
        iso._chain.append(entry)
    return iso


class _Key(str):
    """A proxy hashable by itself, with a global id."""

    @property
    def SMProxy(self):
        return SimpleNamespace(GetGlobalIDAsString=lambda: str(self))


@pytest.fixture
def displays(monkeypatch):
    """Which proxies a view shows."""
    shown = set()
    monkeypatch.setattr(drawn_cells, "pvsimple", SimpleNamespace(
        GetDisplayProperties=lambda proxy, view=None: SimpleNamespace(Visibility=1 if proxy in shown else 0)))
    return shown


def test_an_isolate_draws_its_mask_when_it_is_on(displays):
    """The extractor hidden under it never stood for what the view draws."""
    iso = _isolate(mask="the mask")
    displays.add("the mask")
    assert [d.proxy for d in drawn_cells.of_isolate(iso, "view")] == ["the mask"]
    assert drawn_cells.is_plain(drawn_cells.of_isolate(iso, "view"))
    displays.clear()
    assert drawn_cells.of_isolate(iso, "view") == []


def test_the_tips_on_the_mask_are_what_is_drawn_and_they_say_their_branch(displays):
    mask = "the mask"
    iso = _isolate(mask=mask, tips=[("a", None, 0.1, 0.3, {}), ("b", "a", 0.2, 0.4, {})])
    iso._chain[0].pv_proxies = {id(iso._render_root()): "under"}
    iso._chain[1].pv_proxies = {id(iso._render_root()): "tip"}
    displays.add("tip")
    drawn = drawn_cells.of_isolate(iso, "view")
    assert [d.proxy for d in drawn] == ["tip"]
    assert drawn[0].root == mask
    assert drawn[0].branch == [("a", "CELLS", 0.2, 0.4), ("a", "CELLS", 0.1, 0.3)]
    assert iso.root_branch("the mask") == []


def test_a_threshold_on_a_crop_says_no_branch_its_cells_say_which_they_are(displays):
    crop = _Key("crop")
    iso = _isolate(volumes=[crop], tips=[("a", None, 0.1, 0.3, {crop: "tip"})])
    displays.add("tip")
    drawn = drawn_cells.of_isolate(iso, "view")
    assert [d.proxy for d in drawn] == ["tip"] and not drawn[0].branch


def test_what_the_scene_cuts_is_read_at_the_cut_s_preparation(displays):
    """The proxy is hidden, its cut shown: the row stays, on the cells a box meets."""
    from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop
    root = _Key("extractor")
    crop = SceneCrop("v1")
    crop._boxes = [[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]]
    crop._stages = ["prep", "the cut"]
    iso = _isolate()
    iso._src_extract_init = root
    iso._scene_crops = {str(root): (root, crop)}
    displays.add("the cut")
    drawn = drawn_cells.of_isolate(iso, "view")
    assert [(d.proxy, d.boxes) for d in drawn] == [("prep", crop.boxes)]
    assert not drawn_cells.is_plain(drawn)
    crop._boxes = []
    displays.clear()
    assert drawn_cells.of_isolate(iso, "view") == []
    assert iso.scene_cut_of(root) is None


class _Scene:
    def __init__(self, crop, shown=("/g",)):
        self.crop, self.isolated, self.shown = crop, set(), set(shown)

    def shown_selectors(self):
        return self.shown


def test_a_composite_draws_what_the_scene_keeps_of_its_grid():
    from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop
    index = SimpleNamespace(flat_indices=lambda rep, subtree=False: [4] if rep == "/g" else [])
    crop = SceneCrop("v1")
    crop._boxes, crop._stages = [[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]], ["prep", "cut"]
    scene = _Scene(crop)
    drawn = drawn_cells.of_scene(scene, "/g", index)
    assert [(d.proxy, d.boxes, d.flats) for d in drawn] == [("prep", crop.boxes, (4,))]
    assert not drawn_cells.is_plain(drawn), "a view's row is a read of its own"
    assert drawn_cells.scene_boxes(scene) == crop.boxes
    assert drawn_cells.of_scene(scene, "/not-loaded", index) == []
    scene.isolated.add("/g")
    assert drawn_cells.of_scene(scene, "/g", index) == [], "something else draws it"
    scene.isolated.clear()
    scene.shown.clear()
    assert drawn_cells.of_scene(scene, "/g", index) == [], "its eye is closed"
    scene.shown.add("/g")
    crop._boxes = []
    assert drawn_cells.of_scene(scene, "/g", index) == [], "the scene is whole"
    assert drawn_cells.scene_boxes(scene) == []
    assert drawn_cells.scene_boxes(None) == []
    assert drawn_cells.of_scene(SimpleNamespace(), "/g", index) == [], "a Globe view cuts nothing"


def test_a_view_shows_the_row_of_a_cut_scene_when_its_isolate_draws_nothing(monkeypatch):
    from trame.app import get_server
    from fespp_on_trame.engine import view_resources
    from fespp_on_trame.engine.blockscope.scene_crop import SceneCrop
    crop = SceneCrop("v1")
    crop._boxes, crop._stages = [[[0.0, 1.0], [0.0, 1.0], [0.0, 1.0]]], ["prep", "cut"]
    context = get_server().context
    monkeypatch.setattr(context, "grid_isolates", {("v1", "/g"): "the isolate"}, raising=False)
    monkeypatch.setattr(context, "blockscope_scenes", {"v1": _Scene(crop)}, raising=False)
    monkeypatch.setattr(context, "assembly_index",
                        SimpleNamespace(flat_indices=lambda rep, subtree=False: [2]), raising=False)
    monkeypatch.setattr(view_resources, "pv_view_of", lambda vid: "the view")
    monkeypatch.setattr(drawn_cells, "of_isolate", lambda iso, view: [])
    assert [d.flats for d in sd._resolve_rendered_inputs("/g", "v1")[0]] == [(2,)]
    monkeypatch.setattr(drawn_cells, "of_isolate", lambda iso, view: ["what it draws"])
    assert sd._resolve_rendered_inputs("/g", "v1")[0] == ["what it draws"]
    monkeypatch.setattr(view_resources, "pv_view_of", lambda vid: None)
    assert sd._resolve_rendered_inputs("/g", "v1") == ([], None)


def test_a_view_s_title_is_one_rule():
    from fespp_on_trame.engine import view_axes
    state = _state(("v1", "3D view 1"), ("v2", ""))
    assert view_axes.view_title(state, "v1") == "3D view 1"
    assert view_axes.view_title(state, "v2") == "v2", "no title: its id"
    assert view_axes.view_title(state, "gone") == "gone"
    assert view_axes.view_title(SimpleNamespace(), "v1") == "v1"


# ---- the overlay: only what moved is read ------------------------------------

@pytest.fixture
def counted(monkeypatch, no_weights):
    """How many times each item's values were read."""
    reads = []

    def read(state, tree, source_registry, path, rep, real_idx=None, ts_idx=None):
        reads.append((path, ts_idx))
        return np.linspace(0.1, 0.3, 11) + (ts_idx or 0)

    monkeypatch.setattr(cd, "_values_for", read)
    return reads


def _pinned_steps(p):
    return [_item(p["soil"], "i0")] + [_item(p["soil"], f"i{t + 1}", ts=t, pinned=True) for t in range(3)]


def test_an_item_read_for_the_overlay_is_not_read_again_while_it_cannot_have_changed(counted):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state, cache, loaded = _state(), {}, {p["soil"]}
    first, _meta = cd.dist_figure(state, tree, None, _pinned_steps(p), {"nbins": 10}, cache=cache, loaded=loaded)
    assert len(counted) == 4
    again, meta = cd.dist_figure(state, tree, None, _pinned_steps(p), {"nbins": 10}, cache=cache, loaded=loaded)
    assert len(counted) == 4, "no pinned step is read again"
    assert again.to_plotly_json()["data"] == first.to_plotly_json()["data"]
    assert meta["traces"] == 4 and meta["kept"] == 44
    # another binning is another trace
    cd.dist_figure(state, tree, None, _pinned_steps(p), {"nbins": 20}, cache=cache, loaded=loaded)
    assert len(counted) == 8
    # a row of a property not read holds nothing yet
    cd.dist_figure(state, tree, None, _pinned_steps(p), {"nbins": 20}, cache=cache, loaded=set())
    assert len(counted) == 12


def test_the_traces_of_the_overlay_keep_nothing_of_the_row_that_read_them(counted):
    """A row removed moves the colours of the next: what is kept is neither
    painted nor named."""
    pytest.importorskip("plotly")
    tree, p = _tree()
    state, cache, loaded = _state(), {}, {p["poro"], p["perm"]}
    both = [_item(p["poro"], "i1"), _item(p["perm"], "i2")]
    fig, _m = cd.dist_figure(state, tree, None, both, {"nbins": 5}, cache=cache, loaded=loaded)
    colour = {t["name"]: t["marker"]["color"] for t in fig.to_plotly_json()["data"]}
    fig, _m = cd.dist_figure(state, tree, None, both[1:], {"nbins": 5}, cache=cache, loaded=loaded)
    assert len(counted) == 2, "the kept trace"
    moved = fig.to_plotly_json()["data"][0]
    assert moved["marker"]["color"] == colour["PORO"] != colour["PERM"]
    fig, _m = cd.dist_figure(state, tree, None, both, {"nbins": 5, "mode": "line"}, cache=cache, loaded=loaded)
    lines = fig.to_plotly_json()["data"]
    assert [t["line"]["color"] for t in lines] == [colour["PORO"], colour["PERM"]]
    assert lines[0]["line"]["color"] == lines[0]["marker"]["color"]


def test_a_pinned_copy_shares_its_source_s_read_and_keeps_its_own_colour(counted):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state, cache, loaded = _state(), {}, {p["poro"]}
    both = [_item(p["poro"], "i1"), _item(p["poro"], "i2", pinned=True)]
    fig, _m = cd.dist_figure(state, tree, None, both, {"nbins": 5}, cache=cache, loaded=loaded)
    assert len(counted) == 1, "one read for the two"
    first, second = fig.to_plotly_json()["data"]
    assert first["marker"]["color"] != second["marker"]["color"]


def test_the_row_that_follows_is_read_each_time_its_item_is_not(counted, monkeypatch, view_stats):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["poro"]])
    drawn = []

    def view_read(*a):
        drawn.append("read")
        return np.array([0.2, 0.4])

    monkeypatch.setattr(compare_rows, "_view_values", view_read)
    items = compare_rows.with_following(state, tree, [_item(p["poro"], "i1")], [])
    assert [it["uid"] for it in items] == ["i1", "i1@view:v1"]
    cache, loaded = {}, {p["poro"]}
    cd.dist_figure(state, tree, None, items, {"nbins": 5}, cache=cache, loaded=loaded)
    cd.dist_figure(state, tree, None, items, {"nbins": 5}, cache=cache, loaded=loaded)
    assert len(counted) == 1 and len(drawn) == 2
    assert set(cache) == {cd.item_key(p["poro"], None, None)}


def test_the_overlay_moves_the_pipeline_once_and_reads_a_view_after(counted, monkeypatch, view_stats):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state = _state(("v1", "3D view 1"), v1=[p["soil"]])
    monkeypatch.setattr(compare_rows, "_view_values", lambda *a: view_stats.append("view") or np.array([0.2]))
    real_read = cd._values_for

    def read(state_, tree_, reg, path, rep, real_idx=None, ts_idx=None):
        view_stats.append(f"item {ts_idx}")
        return real_read(state_, tree_, reg, path, rep, real_idx, ts_idx)

    monkeypatch.setattr(cd, "_values_for", read)
    items = [_item(p["soil"], "i1", ts=2, pinned=True), _item(p["soil"], "i2"),
             _item(p["soil"], "i3", ts=1, pinned=True)]
    expanded = compare_rows.with_following(state, tree, items, [])
    fig, meta = cd.dist_figure(state, tree, None, expanded, {"nbins": 5})
    assert view_stats == ["batch in", "item None", "item 1", "item 2", "batch out", "chain in", "view", "chain out"]
    assert meta["note"] == "", "what the view read is drawn with the rest"
    assert [t["name"] for t in fig.to_plotly_json()["data"]] == [
        "SOIL · t2", "SOIL", "SOIL On 3D view 1", "SOIL · t1"], "drawn in the matrix's order"


def test_what_could_not_be_drawn_is_said_whatever_order_it_was_read_in(counted, monkeypatch):
    pytest.importorskip("plotly")
    tree, p = _tree()
    state = _state()
    monkeypatch.setattr(cd, "_values_for", lambda *a, **k: None)
    monkeypatch.setattr(cd, "_read_error", lambda: "the reader fell over")
    _fig, meta = cd.dist_figure(state, tree, None, [_item(p["poro"], "i1"), _item("/not/there", "i2")], {"nbins": 5},
                                pending={p["perm"]: cd.LOADING})
    assert meta["note"].startswith("not drawn: PORO (the reader fell over)")
    assert "(not loaded)" in meta["note"]
    _fig, meta = cd.dist_figure(state, tree, None, [_item(p["poro"], "i1")], {"nbins": 5},
                                pending={p["poro"]: cd.FAILED})
    assert meta["note"] == "not drawn: PORO (read failed)"


# ---- the parts of a grid ------------------------------------------------------

def test_a_dataset_is_its_object_not_the_wrapper_of_this_read():
    class Wrapper:
        def GetAddressAsString(self, _):
            return "Addr=0x1"

        def GetMTime(self):
            return 7

        def GetNumberOfCells(self):
            return 3

    first = Wrapper()
    assert stats_supports._stamp([first]) == stats_supports._stamp([Wrapper()])


def test_a_locator_goes_with_its_grid():
    stats_supports._LOCATORS.clear()
    stats_supports._LOCATORS.update({"kept": (0, None), "gone": (0, None)})
    stats_supports.keep_locators(["kept"])
    assert list(stats_supports._LOCATORS) == ["kept"]
    stats_supports.clear_caches()
    assert not stats_supports._LOCATORS


def test_a_part_row_is_read_once_until_its_cells_move(monkeypatch):
    tree, p = _tree()
    part = _cells([1.0], xs=[1])
    monkeypatch.setattr(stats_supports, "_part_datasets", lambda path: [part])
    read = []
    monkeypatch.setattr(compare_rows, "support_row", lambda state, tree, reg, it: (
        read.append(it["support"]) or ({"Mean": 1.0}, "", {})))
    item = {"path": p["poro"], "real": None, "ts": None, "uid": "i1@w", "support": p["w1"], "follows": "i1"}
    loaded = {p["poro"]}
    cache = {}

    def rows():
        return cd.rows_for(None, tree, None, [item], cache=cache, loaded=loaded)

    rows()
    rows()
    assert read == [p["w1"]]
    part.Modified()
    rows()
    assert read == [p["w1"], p["w1"]]


def test_every_part_of_a_grid_shares_its_one_locator(monkeypatch):
    from vtkmodules import vtkCommonDataModel
    tree, p = _tree()
    stats_supports._CACHE.clear()
    stats_supports._LOCATORS.clear()
    grid = _cells([1.0, 2.0, 3.0])
    parts = {p["w1"]: _cells([1.0], xs=[1]), p["north"]: _cells([2.0], xs=[2])}
    monkeypatch.setattr(stats_supports, "_part_datasets", lambda path: [parts[path]])
    monkeypatch.setattr(stats_supports, "_grid_dataset", lambda reg, rep: grid)
    built = []
    real = vtkCommonDataModel.vtkStaticCellLocator

    def count():
        built.append(1)
        return real()

    monkeypatch.setattr(vtkCommonDataModel, "vtkStaticCellLocator", count)
    rep = cd._rep_path(tree, p["poro"])
    a = stats_supports.cell_map(None, p["w1"], rep, tree)
    b = stats_supports.cell_map(None, p["north"], rep, tree)
    assert list(a[0]) == [1] and list(b[0]) == [2]
    assert len(built) == 1
    # the grid changed: a new locator
    grid.Modified()
    stats_supports.cell_map(None, p["w1"], rep, tree)
    assert len(built) == 2


def test_a_part_that_cannot_read_its_values_gives_a_reason(monkeypatch, no_weights):
    tree, p = _tree()
    monkeypatch.setattr(stats_supports, "cell_map",
                        lambda *a: (np.array([0, 1]), None, 2))
    monkeypatch.setattr(property_values, "values_for", lambda *a, **k: None)
    monkeypatch.setitem(property_values._LAST_ERROR, "msg", "")
    it = _on(p["poro"], p["w1"])
    assert cd._row(_state(), tree, None, it)["note"] == "Blocked wellbore · W1: its values could not be read."
    assert compare_rows.support_values(_state(), tree, None, it) is None
    assert compare_rows.last_error() == "its values could not be read"
    # what the seam says, it says
    monkeypatch.setitem(property_values._LAST_ERROR, "msg", "the recipe's grid is gone")
    assert "the recipe's grid is gone" in cd._row(_state(), tree, None, it)["note"]


def _two_grids():
    """A well blocked on each of two grids."""
    asm = FakeDataAssembly()

    def add(name, parent, **attrs):
        return asm.add_node_with_attrs(name, parent, label=attrs.get("title", name), typeCode="2", **attrs)

    paths = []
    for g, title in (("g", "Geogrid"), ("h", "Other")):
        grid = add(f"_gridfolder_{g}", 0, title=title, type="GridContainer")
        folder = add(f"_bw_{g}", grid, title="blocked wellbores", type="BlockedWellboreFolder")
        paths.append(asm.GetNodePath(add(f"_w1_{g}", folder, title="W1", type="BlockedWellbore")))
    return Tree(asm), paths


def test_the_leaves_of_parts_on_several_grids_say_their_grid():
    tree, parts = _two_grids()
    xml, path_map = ct.kind_tree_xml(tree, [], parts=parts)
    leaves = ET.fromstring(xml)[0][0]
    assert [leaf.get("title") for leaf in leaves] == ["W1 — Geogrid", "W1 — Other"]
    assert sorted(path_map.values()) == sorted(parts)
    # the row's own label says nothing of it: the row is under its grid's item
    assert stats_supports.title_of(tree, parts[0]) == "W1"


def test_the_leaves_of_parts_on_one_grid_stay_as_they_are():
    tree, parts = _two_grids()
    xml, _map = ct.kind_tree_xml(tree, [], parts=parts[:1])
    assert [leaf.get("title") for leaf in ET.fromstring(xml)[0][0]] == ["W1"]
    tree, p = _tree()
    xml, _map = ct.kind_tree_xml(tree, [], parts=[p["w1"], p["north"]])
    assert [r[0].get("title") for r in ET.fromstring(xml)[0]] == ["W1", "North"]


def test_a_part_with_no_grid_keeps_its_title_beside_those_of_two_grids():
    asm = FakeDataAssembly()
    add = asm.add_node_with_attrs
    paths = []
    for g, title in (("g", "Geogrid"), ("h", "Other")):
        grid = add(f"_gridfolder_{g}", 0, title=title, type="GridContainer", typeCode="2")
        paths.append(asm.GetNodePath(add(f"_s_{g}", grid, title="S", type="Sub", typeCode="2")))
    surf = add("_top", 0, title="Top", type="TriangulatedSet", typeCode="2")
    paths.append(asm.GetNodePath(add("_b", surf, title="B", type="SubRepresentation", typeCode="2")))
    titles = stats_supports.leaf_titles(Tree(asm), paths)
    assert list(titles.values()) == ["S — Geogrid", "S — Other", "B"]
