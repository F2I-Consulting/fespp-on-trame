"""The Values view's "Hide NaN": the rows with no value in a column the
filter reads are left out, bound or not; a bound alone never keeps a NaN."""
import numpy as np

from fespp_on_trame.engine import values_table

NAN = float("nan")
COLS = [np.array([1.0, NAN, 3.0, NAN, 5.0]), np.array([NAN, 2.0, 2.0, 2.0, NAN]), np.array([7, 8, 9, 10, 11])]
NONE = np.array([], dtype=np.int64)


def _kept(conds=None, hide_nan=False, fcol=0, fmin=None, fmax=None):
    kept, _range = values_table.rows_of(COLS, fcol, NONE, False, fmin, fmax, conds=conds, hide_nan=hide_nan)
    return kept.tolist()


def test_every_row_without_a_filter_nor_hide_nan():
    assert _kept() == [0, 1, 2, 3, 4]


def test_hide_nan_leaves_out_the_rows_with_no_value_in_the_filtered_column():
    assert _kept(hide_nan=True) == [0, 2, 4]
    assert _kept(hide_nan=True, fcol=1) == [1, 2, 3]


def test_hide_nan_reads_every_column_of_the_filter_rows_bound_or_not():
    conds = [(0, None, None, "and"), (1, None, None, "and")]
    assert _kept(conds=conds, hide_nan=True) == [2]


def test_a_column_of_integers_has_no_nan_to_hide():
    assert _kept(conds=[(2, None, None, "and")], hide_nan=True) == [0, 1, 2, 3, 4]


def test_a_bound_never_keeps_a_nan_and_hide_nan_adds_nothing_to_it():
    conds = [(0, 2.0, None, "and")]
    assert _kept(conds=conds) == [2, 4]
    assert _kept(conds=conds, hide_nan=True) == [2, 4]


def test_the_page_says_hide_nan():
    page = values_table.page(["A", "B", "C"], COLS, 0, NONE, False, 0, 10, None, None, "CELLS", False,
                             conds=[(0, None, None, "and")], hide_nan=True)
    assert page["hide_nan"] is True and page["count"] == 3 and page["total"] == 5


# a frame read sample by sample: MD, then its logs, each holding values on a stretch of its own
MD = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
LOG_A = np.array([NAN, 1.0, NAN, NAN, NAN])
LOG_B = np.array([NAN, NAN, 2.0, NAN, 5.0])
FRAME = [MD, LOG_A, LOG_B]


def _frame_kept(hide_nan=True, nan_all=(1, 2), conds=None):
    kept, _range = values_table.rows_of(FRAME, 0, NONE, False, None, None, conds=conds, hide_nan=hide_nan,
                                        nan_all=nan_all)
    return kept.tolist()


def test_a_frame_hides_the_samples_where_none_of_its_logs_holds_a_value():
    assert _frame_kept() == [1, 2, 4]


def test_a_frame_shows_every_sample_with_hide_nan_off():
    assert _frame_kept(hide_nan=False) == [0, 1, 2, 3, 4]


def test_a_frame_sample_with_one_log_valued_stays_whatever_the_others():
    # the filter on one log still hides that log's empty rows: the rule adds to it, never replaces it
    assert _frame_kept(conds=[(2, None, None, "and")]) == [2, 4]


def test_a_column_of_integers_among_the_logs_leaves_no_sample_empty():
    codes = np.array([3, 3, 4, 4, 4])
    kept, _r = values_table.rows_of([MD, LOG_A, codes], 0, NONE, False, None, None, hide_nan=True, nan_all=(1, 2))
    assert kept.tolist() == [0, 1, 2, 3, 4]


def test_the_page_counts_the_samples_hide_nan_leaves():
    got = values_table.page(["MD", "A", "B"], FRAME, 0, NONE, False, 0, 10, None, None, "POINTS", False,
                            index="sample", hide_nan=True, nan_all=(1, 2))
    assert got["count"] == 3 and [r[0] for r in got["rows"]] == [1, 2, 4]


def test_an_export_says_what_hide_nan_leaves_out_of_a_frame():
    said = values_table.nan_said(["MD", "A", "B"], FRAME, 0, None, (1, 2))
    assert said == "hidden in MD; rows with none in A, B hidden"
    assert values_table.nan_said(["MD", "A", "B"], FRAME, 1, None, ()) == "hidden in A"
    codes = np.array([1, 2, 3, 4, 5])
    assert values_table.nan_said(["code"], [codes], 0, None, ()) is None
