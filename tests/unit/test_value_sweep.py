"""The steps of a swept threshold entry (engine/value_sweep): one value at a
time for the integer kinds, a sliding window for a continuous property."""
import pytest

from fespp_on_trame.engine import value_sweep as vs


def test_a_discrete_entry_steps_through_its_values_one_at_a_time():
    # drogon's Facies, as the isolate gives it (bench of 27/10)
    entry = {"kind": "Discrete", "unique_values": [0, 1, 2, 5, 6, 10, 11, 12],
             "labels": {}, "data_range": [0.0, 12.0], "low": 0.0, "high": 12.0}
    s = vs.steps(entry)
    assert [(a, b) for a, b, _ in s] == [(v, v) for v in (0, 1, 2, 5, 6, 10, 11, 12)]
    assert s[3][2] == "5"
    assert vs.start_index(entry, s) == 0
    assert vs.start_index(dict(entry, low=4.0), s) == 3


def test_a_categorical_step_is_named_by_its_category():
    entry = {"kind": "Categorical", "unique_values": [2, 1], "labels": {"1": "Sand", 2: "Shale"},
             "data_range": [1, 2]}
    assert [t for _a, _b, t in vs.steps(entry)] == ["Sand (1)", "Shale (2)"]


def test_a_continuous_entry_slides_a_window_over_its_range():
    entry = {"kind": "Continuous", "data_range": [0.0, 0.4], "low": 0.0}
    s = vs.steps(entry, width=0.1, positions=5)
    assert len(s) == 5
    # clamped at both ends, a window of 0.04 everywhere else
    assert s[0][:2] == (0.0, pytest.approx(0.02))
    assert s[2][:2] == (pytest.approx(0.18), pytest.approx(0.22))
    assert s[-1][:2] == (pytest.approx(0.38), 0.4)
    # by default each window overlaps the next: the cells change by a thin
    # slice, which is what makes the movement fluid
    d = vs.steps(entry)
    assert len(d) == vs.POSITIONS
    assert all(d[i + 1][0] < d[i][1] for i in range(len(d) - 1))


def test_nothing_to_sweep_says_so_with_no_step():
    assert vs.steps({"kind": "Discrete", "unique_values": []}) == []
    assert vs.steps({"kind": "Continuous", "data_range": []}) == []
    assert len(vs.steps({"kind": "Continuous", "data_range": [3, 3]})) == 1
