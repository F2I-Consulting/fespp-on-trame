"""A session document written with two views for the statistics
(engine/session_older): its `stats` paragraph is read as the one Statistics
view's, and the panel comes back with what the card held."""
from fespp_on_trame.engine import session_older as older


def _state(*rows):
    return {"originals": [dict(zip(("id", "pinned", "real_idx", "ts_idx"), row)) for row in rows]}


def _stats(pinned, panel_state=None, **more):
    return {"id": "view_2", "kind": "stats", "title": "Statistics", "pinned": pinned,
            "panel_state": panel_state or {}, **more}


def _layout(*groups):
    """A dockview layout (`toJSON()`), one group of tabs per argument."""
    return {"grid": {"root": {"type": "branch", "size": 600, "data": [
                {"type": "leaf", "size": 100, "data": {"views": list(g), "activeView": g[0], "id": str(n)}}
                for n, g in enumerate(groups)]}, "width": 800, "height": 600},
            "panels": {i: {"id": i, "contentComponent": f"{i}_template"} for g in groups for i in g},
            "activeGroup": "0"}


# ---- a stats paragraph -----------------------------------------------------------

def test_a_property_pinned_with_no_state_is_a_bare_item():
    assert older.stats_items(_stats(["/a", "/b"])) == [
        {"path": "/a", "real": None, "ts": None, "pinned": False},
        {"path": "/b", "real": None, "ts": None, "pinned": False}]


def test_each_row_of_a_card_is_an_item_at_its_coordinates():
    state = {"/a": _state(("default", False, 1, None), ("custom-1", True, 2, 3), ("custom-2", True, None, 4))}
    assert older.stats_items(_stats(["/a"], state)) == [
        {"path": "/a", "real": 1, "ts": None, "pinned": False},
        {"path": "/a", "real": 2, "ts": 3, "pinned": True},
        {"path": "/a", "real": None, "ts": 4, "pinned": True}]


def test_what_is_not_pinned_any_more_is_no_item():
    assert older.stats_items(_stats(["/a"], {"/gone": _state(("default", False, 1, None))})) == [
        {"path": "/a", "real": None, "ts": None, "pinned": False}]


def test_a_path_a_document_did_not_resolve_is_no_item():
    assert older.stats_items(_stats([{"title": "Facies"}, "", None])) == []


def test_the_paragraph_keeps_its_place_and_its_tree_and_says_no_parts():
    view = older.stats_as_compare(_stats(["/a"], place="right", tree_open=True))
    assert view == {"id": "view_2", "kind": "compare", "title": "Statistics", "place": "right",
                    "tree_open": True, "items": [{"path": "/a", "real": None, "ts": None, "pinned": False}]}
    assert "parts" not in view, "older than the parts: Mean (L) must show"


# ---- a whole document ------------------------------------------------------------

def test_a_document_with_no_statistics_is_read_as_it_is():
    views = [{"id": "view_1", "kind": "render"}, {"id": "view_2", "kind": "health", "title": "Data health"}]
    layout = _layout(["view_1"], ["view_2"])
    assert older.current_views(views, layout) == (views, layout)
    assert older.current_views(None) == ([], None)


def test_a_stats_view_alone_keeps_its_id_in_the_layout():
    layout = _layout(["view_1"], ["view_2"])
    views, kept = older.current_views([{"id": "view_1", "kind": "render"}, _stats(["/a"])], layout)
    assert [(v["id"], v["kind"]) for v in views] == [("view_1", "render"), ("view_2", "compare")]
    assert kept == layout


def test_a_saved_compare_panel_takes_the_view_s_name():
    views, _ = older.current_views([{"id": "v", "kind": "compare", "title": "Compare", "items": []}])
    assert views[0]["title"] == "Statistics"
    views, _ = older.current_views([{"id": "v", "kind": "compare", "title": "Porosity", "items": []}])
    assert views[0]["title"] == "Porosity", "a title the reader gave stays"


def test_the_tab_of_a_saved_compare_panel_takes_the_view_s_name_in_the_layout():
    layout = _layout(["view_1"], ["view_2"])
    layout["panels"]["view_2"]["title"] = "Compare"
    _, kept = older.current_views([{"id": "view_1", "kind": "render"},
                                   {"id": "view_2", "kind": "compare", "title": "Compare", "items": []}], layout)
    assert kept["panels"]["view_2"]["title"] == "Statistics"
    assert layout["panels"]["view_2"]["title"] == "Compare", "the document itself stays as it is"


def test_a_document_holding_both_comes_back_as_one_panel():
    state = {"/a": _state(("default", False, None, None), ("custom-1", True, 2, None))}
    compare = {"id": "view_3", "kind": "compare", "title": "Compare", "tab": "porosity",
               "items": [{"path": "/b", "real": None, "ts": None, "uid": "i4", "pinned": False},
                         {"path": "/a", "real": 2, "ts": None, "uid": "i5", "pinned": False}],
               "kinds": {"porosity": {"baseline": "i5"}}, "parts": ["/w"]}
    views, _ = older.current_views([{"id": "view_1", "kind": "render"},
                                    _stats(["/a"], state, place="right", tree_open=True), compare])
    assert [v["kind"] for v in views] == ["render", "compare"]
    one = views[1]
    assert (one["id"], one["title"], one["place"], one["tree_open"]) == ("view_2", "Statistics", "right", True)
    assert one["tab"] == "porosity" and one["kinds"] == compare["kinds"] and one["parts"] == ["/w"]
    # the saved selection first, its baseline naming its uid; the same
    # coordinates once
    assert [(it["path"], it["real"], it.get("uid")) for it in one["items"]] == [
        ("/b", None, "i4"), ("/a", 2, "i5"), ("/a", None, None)]


def test_the_second_of_the_two_leaves_the_layout():
    views, layout = older.current_views(
        [{"id": "view_1", "kind": "render"}, _stats(["/a"]),
         {"id": "view_3", "kind": "compare", "items": []}],
        _layout(["view_1"], ["view_2", "view_3"]))
    assert [v["id"] for v in views] == ["view_1", "view_2"]
    assert set(layout["panels"]) == {"view_1", "view_2"}
    assert layout["grid"]["root"]["data"][1]["data"]["views"] == ["view_2"]


def test_the_layout_loses_a_group_left_empty_and_keeps_a_tab_active():
    layout = older.layout_without(_layout(["a"], ["b"], ["c", "d"]), "b")
    assert [n["data"]["views"] for n in layout["grid"]["root"]["data"]] == [["a"], ["c", "d"]]
    assert older.layout_without(layout, "c")["grid"]["root"]["data"][1]["data"] == {
        "views": ["d"], "activeView": "d", "id": "2"}


def test_a_layout_is_followed_down_its_branches():
    layout = _layout(["a"])
    layout["grid"]["root"]["data"].append({"type": "branch", "size": 50, "data": [
        {"type": "leaf", "data": {"views": ["b"], "activeView": "b", "id": "1"}},
        {"type": "leaf", "data": {"views": ["c"], "activeView": "c", "id": "2"}}]})
    layout["panels"].update({"b": {}, "c": {}})
    out = older.layout_without(layout, "b")
    assert out["grid"]["root"]["data"][1]["data"][0]["data"]["views"] == ["c"]
    out = older.layout_without(out, "c")
    assert len(out["grid"]["root"]["data"]) == 1, "the branch goes with its last group"


def test_a_layout_not_placing_the_panel_or_placing_it_alone():
    layout = _layout(["a"])
    assert older.layout_without(layout, "z") is layout
    assert older.layout_without(None, "a") is None
    assert older.layout_without(layout, "a") is None, "it places nothing any more"


# ---- a view of a kind that is gone ------------------------------------------------

def test_a_view_of_a_removed_kind_leaves_the_document_and_its_layout():
    views = [{"id": "view_1", "kind": "render"},
             {"id": "view_2", "kind": "distribution", "title": "Distribution · /a"},
             {"id": "view_3", "kind": "crossplot", "x": "/a"},
             {"id": "view_4", "kind": "health"}]
    kept, layout, gone = older.without_removed_kinds(views, _layout(["view_1"], ["view_2", "view_3"], ["view_4"]))
    assert [v["id"] for v in kept] == ["view_1", "view_4"]
    assert set(layout["panels"]) == {"view_1", "view_4"}
    assert [v["title"] for v in gone] == ["Distribution · /a", "Cross-plot"]


def test_a_3d_view_saved_on_the_globe_comes_back_as_the_globe_view():
    layout = _layout(["view_1", "view_2", "view_3"])
    layout["panels"]["view_2"]["title"] = "3D view 2"
    views, kept = older.current_views([
        {"id": "view_1", "kind": "render", "globe": False},
        {"id": "view_2", "kind": "render", "title": "3D view 2", "globe": True, "globe_state": {"epsg": 23031}},
        {"id": "view_3", "kind": "render", "globe": True, "globe_state": {}}], layout)
    assert [(v["id"], v["kind"]) for v in views] == [("view_1", "render"), ("view_2", "globe"), ("view_3", "render")]
    assert views[1]["title"] == "Globe" and views[1]["globe_state"] == {"epsg": 23031}
    assert not any("globe" in v for v in views) and "globe_state" not in views[2], "one Globe per session"
    assert kept["panels"]["view_2"]["title"] == "Globe"


def test_a_document_with_no_removed_kind_is_left_alone():
    views = [{"id": "view_1", "kind": "render"}, {"id": "view_2", "kind": "compare", "items": []}]
    layout = _layout(["view_1"], ["view_2"])
    assert older.without_removed_kinds(views, layout) == (views, layout, [])


# ---- through the session door -----------------------------------------------------

def _restored(doc):
    from tests.unit.test_assistant_wiring import FakeMV, _host
    from tests.unit.test_compare_rows import _tree
    tree, p = _tree()
    mv = FakeMV(kinds=("render",), count=4)
    host, server = _host(mv)
    server.context.tree = tree
    saved = []

    def restore(what):
        saved.append(what)
        mv.add_view(kind="compare")

    server.controller.session_compare_restore = restore
    said = []
    host.restore(doc(p), lambda level, text: said.append((level, text)))
    return mv, server, saved, said


def test_the_door_reopens_a_stats_view_as_the_one_view():
    def doc(p):
        return {"views": [{"id": "view_1", "kind": "render"},
                          {"id": "view_2", "kind": "stats", "title": "Statistics", "pinned": [p["poro"], "/gone"],
                           "tree_open": True,
                           "panel_state": {p["poro"]: _state(("default", False, None, None), ("custom-1", True, 1, None))}}],
                "layout": _layout(["view_1"], ["view_2"]), "schema": 1}
    mv, server, saved, said = _restored(doc)
    (pid,) = mv.panel_ids_of_kind("compare")
    assert [(it["real"], it["pinned"]) for it in saved[0]["items"]] == [(None, False), (1, True)]
    assert "parts" not in saved[0]
    assert server.state[f"compare_tree_open__{pid}"] == ["Reservoir"]
    assert mv._titles[pid] == "Statistics"
    assert set(mv.restored_layout["panels"]) == {mv.view_ids()[0], pid}
    assert [s for s in said if s[0] != "ok"] == [
        ("warn", "1 row(s) of the Statistics view name what is not in the data — skipped.")]


def test_the_door_reopens_a_document_holding_both_with_its_layout():
    def doc(p):
        return {"views": [{"id": "view_1", "kind": "render"},
                          {"id": "view_2", "kind": "stats", "title": "Statistics", "pinned": [p["poro"]]},
                          {"id": "view_3", "kind": "compare", "title": "Compare",
                           "items": [{"path": p["perm"], "uid": "i7"}]}],
                "layout": _layout(["view_1"], ["view_2", "view_3"]), "schema": 1}
    mv, _server, saved, said = _restored(doc)
    assert len(saved) == 1 and len(saved[0]["items"]) == 2
    (pid,) = mv.panel_ids_of_kind("compare")
    assert set(mv.restored_layout["panels"]) == {mv.view_ids()[0], pid}
    assert [s for s in said if s[0] != "ok"] == []


def test_the_door_opens_a_document_naming_a_removed_kind_and_says_so():
    def doc(p):
        return {"views": [{"id": "view_1", "kind": "render"},
                          {"id": "view_2", "kind": "compare", "title": "Statistics",
                           "items": [{"path": p["poro"], "uid": "i7"}]},
                          {"id": "view_3", "kind": "distribution", "title": "Distribution · PORO",
                           "context": {"array_path": p["poro"], "row_kind": "original", "row_id": "default"},
                           "options": {"pinned": True}},
                          {"id": "view_4", "kind": "crossplot", "x": p["poro"], "ys": [{"path": p["perm"]}]}],
                "layout": _layout(["view_1"], ["view_2"], ["view_3", "view_4"]), "schema": 1}
    mv, _server, saved, said = _restored(doc)
    (pid,) = mv.panel_ids_of_kind("compare")
    assert len(saved) == 1
    assert mv.panel_ids_of_kind("distribution") == [] and mv.panel_ids_of_kind("crossplot") == []
    assert set(mv.restored_layout["panels"]) == {mv.view_ids()[0], pid}, "what stays keeps its layout"
    words = "not restored, the Statistics view now draws the histograms and the cross-plots."
    assert [s for s in said if s[0] != "ok"] == [
        ("warn", f"Distribution · PORO: {words}"), ("warn", f"Cross-plot: {words}")]


def test_a_saved_view_says_whether_its_tree_is_open():
    from tests.unit.test_assistant_wiring import FakeMV, _host
    mv = FakeMV(kinds=("render", "compare"))
    host, server = _host(mv)
    server.state["compare_tree_open__view_2"] = ["Surface", "Well"]
    assert host._collect_panels()["view_2"]["tree_open"] == ["Surface", "Well"]
