"""app/scene/panel_trees: the one grammar (the PO, 18/10) — checkbox = the
session's load, eye = in THIS view — and the question an untick asks."""
from fespp_on_trame.app.scene.panel_trees import PanelTrees
from fespp_on_trame.engine import tick_confirm


def _panel(pt, held):
    calls = []

    def hold(vid, paths):
        calls.append((vid, list(paths)))
        held[:] = list(paths)
    pt.add("log", vids=lambda: ["s1"], held=lambda vid: list(held), hold=hold,
           title=lambda vid: "Well log")
    return calls


def test_an_eye_takes_a_row_in_and_lets_it_go():
    pt, held = PanelTrees(), []
    calls = _panel(pt, held)
    pt.eye("log", "s1", ["/g/prop1"])                        # a leaf: toggles on
    assert held == ["/g/prop1"]
    pt.eye("log", "s1", ["/g/prop1"])                        # and off
    assert held == []
    pt.eye("log", "s1", ["/g/prop1", "/g/prop2"], on=True)   # a folder's leaves
    assert held == ["/g/prop1", "/g/prop2"]
    pt.eye("log", "s1", ["/g/prop1"], on=True)               # already held: nothing to do
    assert len(calls) == 3


def test_a_panel_says_what_an_eye_opened_makes_it_hold():
    pt, held = PanelTrees(), ["/g/prop1"]
    pt.add("kinds", vids=lambda: ["s1"], held=lambda vid: list(held),
           hold=lambda vid, paths: held.__setitem__(slice(None), list(paths)),
           opens=lambda vid, paths: [p for p in paths if "/prop" in p])
    pt.eye("kinds", "s1", ["/g", "/h/prop2"], on=True)
    assert held == ["/h/prop2"]


def test_a_tick_in_the_panel_takes_what_it_read():
    pt, held = PanelTrees(), []
    _panel(pt, held)
    pt.take("log", "s1", ["/g/prop3"])
    assert held == ["/g/prop3"]


def test_the_users_of_an_object_are_named_the_origin_left_out():
    pt, held = PanelTrees(), ["/g/prop1"]
    _panel(pt, held)
    shown = {"v1": {"/g", "/g/prop1"}, "v2": {"/w"}}
    pt.add_views(lambda paths: [v for v, s in shown.items() if s & paths])
    assert pt.users(["/g/prop1"]) == ["v1", "s1"]
    assert pt.users(["/g/prop1"], exclude="v1") == ["s1"]
    assert pt.users(["/g"], exclude="v1") == ["s1"]          # a row under an unloaded grid
    assert pt.users(["/x"]) == []
    assert pt.kind_of("s1") == "log" and pt.title("log", "s1") == "Well log"


def test_what_is_unloaded_leaves_every_panel():
    pt, held = PanelTrees(), ["/g/prop1", "/h/prop2"]
    _panel(pt, held)
    pt.prune(["/g"])
    assert held == ["/h/prop2"]


def test_a_panel_with_its_own_paths_converts_both_ways():
    pt, held = PanelTrees(), ["k/r/p1"]
    pmap = {"k/r/p1": "/g/prop1", "k/r/p2": "/g/prop2"}
    pt.add("compare", vids=lambda: ["c1"], held=lambda vid: list(held),
           hold=lambda vid, paths: held.__setitem__(slice(None), list(paths)),
           to_real=lambda syn: [pmap[s] for s in syn if s in pmap],
           from_real=lambda real: [s for s, p in pmap.items() if p in set(real)])
    assert pt.users(["/g/prop1"]) == ["c1"]
    pt.take("compare", "c1", ["/g/prop2"])
    assert held == ["k/r/p1", "k/r/p2"]
    pt.prune(["/g/prop1"])
    assert held == ["k/r/p2"]


def test_the_unload_question_names_what_and_where():
    q = tick_confirm.unload_question(["Porosity"], ["3D view 2", "Statistics"])
    assert q["title"] == "Unload Porosity?" and q["ok"] == "Unload"
    assert "used in 3D view 2 and Statistics" in q["body"]
    assert "removed from 3D view 2 and Statistics" in q["body"]
    many = tick_confirm.unload_question(["A", "B"], ["V1", "V2", "V3", "V4"])
    assert many["title"] == "Unload A and B?" and "They are used in V1, V2 and 2 others" in many["body"]
