"""app/scene/selection: the per-view selection state and its only writers."""
from fespp_on_trame.app.scene.selection import Selection


def test_a_pick_holds_the_cells_and_the_navigation_target():
    s = Selection()
    by_flat = {3: [1, 2]}
    s.hold("v1", by_flat, pick=True, origin=7)
    by_flat[3].append(9)                       # the caller's dict is copied
    assert s.cells == {"v1": {3: [1, 2]}}
    assert s.last_pick == {"v1": {3: [1, 2]}}
    assert s.origin == {"v1": 7}


def test_highlighted_rows_are_cells_but_no_navigation_target():
    s = Selection()
    s.hold("v1", {0: [4]})
    assert s.cells["v1"] == {0: [4]} and "v1" not in s.last_pick
    assert s.origin["v1"] is None


def test_drop_says_whether_the_view_held_something():
    s = Selection()
    assert s.drop("v1") is False
    s.set_pick("v1", {0: [1]})                 # a right-click: target only
    assert s.cells == {} and s.drop("v1", pick=False) is False
    assert s.last_pick == {"v1": {0: [1]}}
    assert s.drop("v1") is True and s.last_pick == {}


def test_closing_a_view_drops_its_extracts_but_not_another_views():
    s = Selection()
    s.hold("v1", {0: [1]}, pick=True)
    s.hold("v2", {0: [2]}, pick=True)
    s.extracts["v1"] = [{"id": 1}]
    s.close_view("v1")
    assert "v1" not in s.cells and "v1" not in s.last_pick and "v1" not in s.extracts
    assert s.cells["v2"] == {0: [2]}


def test_inputs_are_cleaned_once_and_a_failure_is_said(capsys):
    class _Proxy:
        def __init__(self, fail=False):
            self.fail, self.cleaned = fail, 0

        def CleanSelectionInputs(self, port):
            if self.fail:
                raise RuntimeError("gone")
            self.cleaned += 1

    s = Selection()
    ok, bad = _Proxy(), _Proxy(fail=True)
    s.add_input("v1", ok)
    s.add_input("v1", bad)
    s.drop_inputs("v1")
    s.drop_inputs("v1")
    assert ok.cleaned == 1 and s.inputs == {}
    assert "input not cleared" in capsys.readouterr().out
