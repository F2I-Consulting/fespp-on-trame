"""The layout a window filling the dock covers, without the panels closed meanwhile."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "fespp_on_trame", "app", "views", "dock_fill.py")
_SPEC = importlib.util.spec_from_file_location("dock_fill", _PATH)
dock_fill = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dock_fill)


def _leaf(*views):
    return {"type": "leaf", "data": {"views": list(views), "activeView": views[0], "id": views[0]}, "size": 100}


def _layout():
    return {
        "grid": {"root": {"type": "branch", "data": [_leaf("a", "b"), _leaf("c")], "size": 200}},
        "panels": {p: {"id": p} for p in "abcd"},
        "floatingGroups": [{"data": {"views": ["d"], "activeView": "d", "id": "d"}, "position": {"top": 1}}],
    }


def test_a_tab_goes_and_its_group_stays():
    out = dock_fill.layout_without(_layout(), {"a"})
    first = out["grid"]["root"]["data"][0]["data"]
    assert first["views"] == ["b"]
    assert first["activeView"] == "b"
    assert sorted(out["panels"]) == ["b", "c", "d"]


def test_a_group_left_empty_goes():
    out = dock_fill.layout_without(_layout(), {"c"})
    assert [n["data"]["views"] for n in out["grid"]["root"]["data"]] == [["a", "b"]]


def test_a_floating_window_left_empty_goes():
    assert dock_fill.layout_without(_layout(), {"d"})["floatingGroups"] == []


def test_the_root_stays_when_all_its_groups_go():
    out = dock_fill.layout_without(_layout(), {"a", "b", "c"})
    assert out["grid"]["root"]["data"] == []
    assert out["floatingGroups"][0]["data"]["views"] == ["d"]


def test_nested_branches_left_empty_go():
    layout = _layout()
    layout["grid"]["root"]["data"].append({"type": "branch", "data": [_leaf("e")], "size": 50})
    out = dock_fill.layout_without(layout, {"e"})
    assert len(out["grid"]["root"]["data"]) == 2


def test_the_layout_given_is_left_alone():
    layout = _layout()
    dock_fill.layout_without(layout, {"a", "d"})
    assert layout == _layout()


def test_nothing_gone_is_a_copy():
    layout = _layout()
    out = dock_fill.layout_without(layout, set())
    assert out == layout
    assert out is not layout
