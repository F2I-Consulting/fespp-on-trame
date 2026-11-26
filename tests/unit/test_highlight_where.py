"""app/boot `highlight_where`: the assistant's "light the cells where PHIT >
0.2".

Its matching and the composite id list it selects are pure numpy helpers
(`highlight_plan`, `composite_id_triplets`), tested here on their own; the
controller itself needs a ParaView pipeline (the headless scenario
assistant_drogon drives it).

Why they matter: a broad condition on a large grid can match hundreds of
thousands of cells, and sending each one through Python as its own ParaView
id costs seconds of work and render and hundreds of megabytes. The matching
must stay numpy on a million cells, and past HIGHLIGHT_MAX_IDS nothing is
selected (the count is said instead)."""
import time

import numpy as np

from fespp_on_trame.app import boot
from fespp_on_trame.engine import values_table


def test_nan_and_ghost_cells_never_match():
    v = np.array([0.1, 0.25, np.nan, 0.3, 0.0, 0.5])
    ghost = np.array([0, 0, 0, 0, 32, 0], dtype=np.uint8)     # an inactive cell's 0.0 fill
    plan = boot.highlight_plan(v, ghost, 0.0, None)
    assert plan["idx"].tolist() == [0, 1, 3, 5]
    assert (plan["count"], plan["total"], plan["valid"], plan["too_many"]) == (4, 6, 4, 0)


def test_both_bounds_are_inclusive_and_a_missing_ghost_array_is_nan():
    v = np.array([0.1, 0.2, 0.3, 0.4])
    ghost = np.array([np.nan, np.nan, 0.0, np.nan])           # a block without vtkGhostType
    assert boot.highlight_plan(v, ghost, 0.2, 0.3)["idx"].tolist() == [1, 2]
    assert boot.highlight_plan(v, None, None, 0.2)["idx"].tolist() == [0, 1]


def test_past_the_cap_nothing_is_selected_and_the_count_is_kept():
    v = np.linspace(0.0, 1.0, 1000)
    plan = boot.highlight_plan(v, None, 0.5, None, limit=100)
    assert plan["idx"] is None and plan["too_many"] == 100 and plan["count"] == 500
    assert boot.highlight_plan(v, None, 0.95, None, limit=100)["idx"].shape[0] == 50
    # the cap still admits a typical broad query: drogon's "porosity > 0.2"
    # matches 309 638 cells
    assert 309_638 < boot.HIGHLIGHT_MAX_IDS <= 1_000_000


def test_triplets_follow_the_blocks_and_skip_a_block_without_flat_index():
    # three blocks of 4, 3, 5 cells; the middle one has no flat index
    trip = boot.composite_id_triplets([4, 3, 5], [7, -1, 9], [0, 3, 4, 6, 7, 11, 3])
    assert trip.tolist() == [7, 0, 0, 7, 0, 3, 9, 0, 0, 9, 0, 4]
    assert boot.composite_id_triplets([4], [1], []).size == 0


def test_a_million_cells_match_in_numpy_time():
    """1 M cells, 5 % NaN, 2 % ghosts: the plan and the triplets of a
    capped highlight well under a second (no Python loop per cell)."""
    rng = np.random.default_rng(7)
    n = 1_000_000
    v = rng.random(n)
    v[rng.random(n) < 0.05] = np.nan
    ghost = (rng.random(n) < 0.02).astype(np.uint8) * 32
    t0 = time.perf_counter()
    plan = boot.highlight_plan(v, ghost, 0.95, None)          # ~4.6 % of the cells
    trip = boot.composite_id_triplets([600_000, 400_000], [3, 4], plan["idx"])
    took = time.perf_counter() - t0
    print(f"[test] highlight plan + triplets on 1 M cells: {took * 1000:.0f} ms,"
          f" {plan['count']} matches")
    expected = np.flatnonzero(~np.isnan(v) & (ghost == 0) & (v >= 0.95))
    assert plan["idx"].tolist() == expected.tolist()
    assert trip.shape[0] == 3 * expected.shape[0]
    local = trip.reshape(-1, 3)
    first = expected < 600_000
    assert (local[first, 0] == 3).all() and (local[~first, 0] == 4).all()
    assert (local[~first, 2] == expected[~first] - 600_000).all()
    assert took < 1.0
    # a broad condition: counted, never listed
    t0 = time.perf_counter()
    broad = boot.highlight_plan(v, ghost, 0.2, None)
    assert broad["idx"] is None and broad["count"] > boot.HIGHLIGHT_MAX_IDS
    assert time.perf_counter() - t0 < 1.0


# ---------------------------------------------------------------- Values card
def _page(cols, **kw):
    args = dict(names=[f"c{i}" for i in range(len(cols))], cols=cols, fcol=0,
                picked=np.array([], dtype=np.int64), only=False, offset=0, limit=200,
                fmin=None, fmax=None, assoc="CELLS", geometry=False)
    args.update(kw)
    return values_table.page(**args)


def test_the_values_page_filters_pages_and_marks_the_picked_rows():
    v = np.array([0.1, np.nan, 0.3, 0.5, 0.7])       # cell 1 inactive (NaN)
    page = _page([v], fmin=0.2, picked=np.array([3, 4], dtype=np.int64), limit=1)
    # an inactive cell is never in range; the page is one row long
    assert page["count"] == 3 and page["total"] == 5
    assert page["rows"] == [[2, 0.3]] and page["picked"] == 2 and page["picked_rows"] == []
    page = _page([v], fmin=0.2, picked=np.array([3, 4], dtype=np.int64), offset=1)
    assert [r[0] for r in page["rows"]] == [3, 4] and page["picked_rows"] == [3, 4]
    # a NaN reads None, never a number
    assert _page([v])["rows"][1] == [1, None]


def test_the_values_page_keeps_only_the_selection_and_a_code_column():
    v = np.array([1.0, 2.0, 3.0])
    codes = np.array([7, 8, 9])                       # an integer column stays integral
    page = _page([v, codes], only=True, picked=np.array([2], dtype=np.int64))
    assert page["count"] == 1 and page["rows"] == [[2, 3.0, 9]]
    assert page["columns"] == ["index", "c0", "c1"] and page["filter_on"] == "c0"
    assert page["only"] is True


def test_the_filter_reads_the_chosen_column_and_says_its_range():
    """The card's min / max fields start at the range of the column the
    filter reads — any column, not only the first (the PO, 20/10: on a
    geometry it could only read X); a NaN is no part of the range."""
    x = np.array([10.0, 20.0, 30.0])
    z = np.array([-5.0, np.nan, -1.0])
    page = _page([x, z], fcol=1)
    assert page["filter_on"] == "c1" and page["filter_columns"] == ["c0", "c1"]
    assert page["filter_range"] == [-5.0, -1.0]
    assert _page([x, z], fcol=1, fmax=-2.0)["rows"] == [[0, 10.0, -5.0]]
    assert _page([np.array([np.nan])])["filter_range"] == [None, None]


def test_the_csv_hands_over_every_kept_row_and_a_bare_geometry_its_ids():
    """The Values card's Copy CSV: every row the filter keeps, not one page,
    under the provenance header, at most `cap`; a geometry with no column
    still lists its cells (the manager, 21/10)."""
    v = np.array([0.1, np.nan, 0.3, 0.5])
    kept, _r = values_table.rows_of([v], 0, np.array([], dtype=np.int64), False, 0.2, None)
    text = values_table.csv_text(["poro"], [v], kept, ["# h"], index="cell id")
    assert text == "# h\ncell id,poro\n2,0.3\n3,0.5\n"
    assert values_table.csv_text(["poro"], [v], np.arange(4), [], cap=2).count("\n") == 3
    assert _page([], total=3)["rows"] == [[0], [1], [2]]


def test_the_csv_writes_each_cells_points_where_the_card_shows_them():
    """A row read by its cell lists the cell's points (the PO, 21/10): in
    the CSV, their ids space-separated in a "points" column after I J K."""
    k = np.array([1, 2])
    v = np.array([0.5, 0.7])
    text = values_table.csv_text(["K", "poro"], [k, v], np.arange(2), [], index="cell id",
                                 points=[[0, 1, 5, 4], [4, 5, 9, 8]], points_at=2)
    assert text.splitlines() == ["cell id,K,points,poro", "0,1,0 1 5 4,0.5", "1,2,4 5 9 8,0.7"]


def test_the_csv_of_named_rows_says_their_names():
    """A marker frame's rows are its markers, a log frame's its logs: the
    CSV says their names where the card does, not the rows' numbers."""
    md = np.array([1200.5, 1850.0])
    text = values_table.csv_text(["MD"], [md], np.arange(2), [], index="marker",
                                 row_names=["Top Hugin", "Base Hugin"])
    assert text.splitlines() == ["marker,MD", "Top Hugin,1200.5", "Base Hugin,1850.0"]


def test_filter_rows_join_like_the_thresholds():
    """Rows of conditions (the PO, 21/10: a filter on J dropped the one on
    I): ∩ binds tighter than ∪, a row with no bound asks nothing."""
    cols = [np.array([1, 2, 3, 4, 5]), np.array([1, 1, 2, 2, 3])]

    def keep(conds):
        return values_table.rows_of(cols, 0, np.array([], dtype=np.int64), False, None, None,
                                    conds=conds)[0].tolist()
    assert keep([(0, 2, 4, "and"), (1, 2, None, "and")]) == [2, 3]
    assert keep([(0, None, 1, "and"), (1, 3, None, "or")]) == [0, 4]
    assert keep([(0, 2, 4, "and"), (1, None, None, "or")]) == [1, 2, 3]
    assert values_table.conditions_text(
        ["I", "J"], [(0, 2, 4, "and"), (1, 2, None, "and"), (0, 5, 5, "or")]
    ) == "(I in [2, 4] and J in [2, ]) or I in [5, 5]"
