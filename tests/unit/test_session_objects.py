"""engine/session_objects: the native Objects routes' rules — the uuids a
request names, what is read and shown once objects are added, replaced or
taken away, the 3D view spoken of, the rows of the answer."""
import pytest

from fespp_on_trame.engine import session_objects as so

U1 = "0eb751ef-219b-4e1f-8e4e-06187f16e61a"
U2 = "5af3641f-5a55-43a9-bb31-d7f81ab0ba70"


def test_the_uuids_are_read_as_typed_once_each_in_order():
    body = {"uuids": [f"uuid:{U1}", " {%s} " % U2.upper(), U1]}
    assert so.uuids_of(body) == [U1, U2]


@pytest.mark.parametrize("body", [None, [], {"uuid": U1}, {"uuids": U1}, {"uuids": [1]}, {"uuids": ["uuid: "]}])
def test_a_request_without_a_list_of_uuids_is_refused(body):
    with pytest.raises(so.ObjectsError):
        so.uuids_of(body)


def test_show_is_a_boolean_true_by_default():
    assert so.flag_of({}, "show") is True and so.flag_of({"show": False}, "show") is False
    with pytest.raises(so.ObjectsError):
        so.flag_of({"show": "no"}, "show")


def test_added_keeps_what_was_read_and_shown():
    read, shown = so.added(["b", "c"], ["a", "b"], ["a"])
    assert read == ["a", "b", "c"] and shown == ["a", "b", "c"]
    read, shown = so.added(["c"], ["a"], ["a"], show=False)
    assert read == ["a", "c"] and shown == ["a"]


def test_replaced_is_the_whole_of_it():
    assert so.replaced(["c"]) == (["c"], ["c"])
    assert so.replaced(["c"], show=False) == (["c"], [])


def test_removed_leaves_no_eye_on_what_is_not_read():
    read, eyes = so.removed(["b"], ["a", "b"], {"v1": ["a", "b"], "v2": ["b"]})
    assert read == ["a"] and eyes == {"v1": ["a"], "v2": []}


def test_the_view_is_the_one_named_else_the_first_3d_view():
    kinds = {"p1": "compare", "v1": "render", "v2": "render"}.get
    assert so.first_render_view(["p1", "v1", "v2"], kinds) == "v1"
    assert so.first_render_view(["p1", "v1", "v2"], kinds, "v2") == "v2"
    with pytest.raises(so.ObjectsError, match="No 3D view 'p1'"):
        so.first_render_view(["p1", "v1"], kinds, "p1")
    # no browser attached yet: no view, a show opens one
    assert so.first_render_view(["p1"], kinds) is None and so.first_render_view([], kinds) is None


def test_the_row_naming_an_object_is_its_topmost_folder_of_the_same_uuid():
    from fespp_on_trame.engine.row_object import uuid_of
    leaf = f"/data/_gridfolder_{U1}/_propsfolder_{U1}/_{U1}"
    assert so.object_root(leaf, uuid_of) == f"/data/_gridfolder_{U1}"
    # a property under its grid: its own row, not the grid's
    prop = f"/data/_gridfolder_{U1}/_propsfolder_{U1}/_{U2}"
    assert so.object_root(prop, uuid_of) == prop
    assert so.object_root("derived://x", uuid_of) == "derived://x"


def test_rows_say_each_object_read_and_whether_the_view_shows_it():
    describe = {"a": (U1, "Grid2dRepresentation", "Top"), "derived://x": ("", "Property", "x")}.get
    assert so.rows(["a", "derived://x"], ["a"], describe) == [
        {"uuid": U1, "type": "Grid2dRepresentation", "title": "Top", "shown": True},
        {"uuid": None, "type": "Property", "title": "x", "shown": False}]


def test_rows_say_whether_each_object_is_loaded_when_asked():
    describe = {"a": (U1, "Grid2dRepresentation", "Top")}.get
    assert so.rows(["a"], [], describe, lambda p: False)[0]["loaded"] is False
    assert "loaded" not in so.rows(["a"], [], describe)[0]


def test_an_answer_is_settled_once_no_read_runs_and_all_is_loaded():
    assert so.settled({"loading": False, "objects": [{"loaded": True}]})
    assert not so.settled({"loading": True, "objects": [{"loaded": True}]})
    assert not so.settled({"loading": False, "objects": [{"loaded": True}, {"loaded": False}]})
    assert so.settled({"objects": []})


def test_the_catalogue_filters_by_type_and_title():
    objects = [("a", U1, "Grid2dRepresentation", "Top Hugin"), ("b", U2, "ContinuousProperty", "Porosity"),
               ("x", "", "Folder", "nothing")]
    rows, total = so.catalogue(objects, ["b"], ["b"])
    assert total == 2 and [r["uuid"] for r in rows] == [U1, U2] and rows[1]["read"] and rows[1]["shown"]
    assert so.catalogue(objects, [], [], kind="GRID2DREPRESENTATION")[1] == 1
    assert so.catalogue(objects, [], [], text="hug")[0][0]["uuid"] == U1
    rows, total = so.catalogue(objects, [], [], limit=1)
    assert len(rows) == 1 and total == 2


def test_a_count_of_the_query_is_bounded():
    assert so.count_of(None, "wait", 0, 110) == 0 and so.count_of("30", "wait", 0, 110) == 30
    for bad in ("x", "-1", "111"):
        with pytest.raises(so.ObjectsError, match="wait"):
            so.count_of(bad, "wait", 0, 110)
