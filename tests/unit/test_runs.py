"""engine/utils/runs: cell ids stored as runs in a session file."""
from fespp_on_trame.engine.utils.runs import from_runs, to_runs


def test_runs_round_trip_and_merge_neighbours():
    ids = [7, 3, 4, 5, 9, 10, 4]
    assert to_runs(ids) == [[3, 5], [7, 7], [9, 10]]
    assert from_runs(to_runs(ids)) == [3, 4, 5, 7, 9, 10]


def test_empty():
    assert to_runs([]) == [] and from_runs([]) == []
