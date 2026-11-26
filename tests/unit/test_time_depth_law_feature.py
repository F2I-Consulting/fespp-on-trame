"""The time-depth law feature (app/features/time_depth_law): the state it
publishes, no model to start with, the one generated of the TDLaws entered,
its gestures on the columns' laws, on the columns and on the velocity model
itself (the cells set by hand),
the velocity model it registers for the stages, what the view reads, the session
round trip, its listeners."""
import types

import pytest

from fespp_on_trame.app.features import time_depth_law as feature
from fespp_on_trame.engine.blockscope import domain_convert
from fespp_on_trame.engine.time_depth import DEFAULT_CELLS as N


class _Controller:
    def __init__(self):
        self.fns = {}

    def set(self, name):
        def deco(fn):
            self.fns[name] = fn
            return fn
        return deco


class _State(dict):
    def __getattr__(self, key):
        return self.get(key)


def _core():
    return types.SimpleNamespace(controller=_Controller(), ctx=types.SimpleNamespace(), mv=lambda: None, state=_State())


ZERO = {"depth": 0.0, "twt": 0.0, "velocity": None}
FAR = {"depth": 5000.0, "twt": 5000.0, "velocity": 2000.0}     # the line a TDLaw entered by hand starts on
BOUNDS = [0.0, 1000.0, 0.0, 500.0, -3000.0, 0.0]
NEW = {"value": "new", "label": "New velocity model"}
NO_LAW = "no TDLaw converts: the velocity model is not updated, and nothing is converted, until one does"


def _generated(core):
    """What most of these tests start from: one TDLaw, on the line it starts
    with (0 to 5 000 m at 2 000 m/s), and the velocity model generated of it
    (the feature registered with data bounds: a model stands on a zone). The
    edit gesture."""
    edit = core.controller.fns["time_depth_law_edit"]
    edit({"op": "add_column"})
    edit({"op": "generate"})
    assert core.state["ui_time_depth_law"]["generated"] is True
    return edit


def test_registered_there_is_no_model_and_nothing_converts():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core)
    st = core.state["ui_time_depth_law"]
    assert st["columns"] == [] and st["active"] == 0 and st["axes"] == ["Easting", "Northing"]
    assert st["generated"] is False and st["can_generate"] is False
    assert st["model"] == "new" and st["models"] == [NEW]
    assert st["cube"] == {"extent": [None, None, None, None], "extent_from": None, "extent_used": None,
                          "extent_grown": [], "nx": N, "ny": N, "nz": N, "trange": [0.0, 5000.0],
                          "summary": None, "edited": 0}
    assert st["prefill"] == {"ready": False, "done": [], "wells": 0, "wells_out": 0, "sonic": 0, "sonic_out": 0,
                             "markers": 0, "markers_out": 0,
                             "time_grids": 0, "depth_grids": 0}
    assert st["valid"] is True and st["problems"] == []
    assert not core.ctx.time_depth_law().has_law()
    assert core.ctx.time_depth_cube() is None and core.ctx.time_depth_cube_key() == ""
    assert domain_convert.CUBES == {}
    assert core.ctx.time_depth_columns() == [] and core.ctx.time_depth_active() is None
    assert core.ctx.time_depth_model_id() is None
    # the session keeps the inputs of a model not generated, said so
    assert core.ctx.time_depth_law_doc() == {
        "columns": [], "extent": [None, None, None, None, 0.0, 5000.0], "nx": N, "ny": N, "nz": N,
        "extent_from": None, "active": 0, "touched": False, "generated": False}
    # nothing to generate from: refused, and said
    core.controller.fns["time_depth_law_edit"]({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["generated"] is False
    assert st["problems"] == ["a velocity model needs a TDLaw: enter one by hand, or read the wells'"]
    # the axes as the CRS names them
    named = _core()
    feature.register(named, _axes=lambda: ("Easting (m)", "Northing (m)", "Elevation (m)"))
    assert named.state["ui_time_depth_law"]["axes"] == ["Easting (m)", "Northing (m)"]
    domain_convert.register_cube("", None)


def test_a_tdlaw_entered_the_model_is_generated_named_and_converts():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core, _data_bounds=lambda: BOUNDS)
    edit = core.controller.fns["time_depth_law_edit"]
    # a TDLaw added by hand starts on a line at 2 000 m/s, to edit, at the centre of the data's extent
    edit({"op": "add_column"})
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"]
    assert (st["columns"][0]["x"], st["columns"][0]["y"]) == (500.0, 250.0)
    assert st["columns"][0]["rows"] == [ZERO, FAR] and st["columns"][0]["why"] == ""
    # it converts, and still nothing is converted: the model is not generated
    assert st["can_generate"] is True and st["generated"] is False and st["cube"]["summary"] is None
    assert core.ctx.time_depth_cube() is None and domain_convert.CUBES == {}
    # what the TDLaw would make is there for the 3D view to show, no more
    preview, preview_key = core.ctx.time_depth_preview()
    assert preview_key.startswith("preview:") and preview.summary()["vmin"] == preview.summary()["vmax"] == 2000.0
    edit({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["generated"] is True and st["can_generate"] is False and st["problems"] == []
    assert core.ctx.time_depth_preview() == (None, "")
    assert st["model"] == "m1" and st["models"] == [NEW, {"value": "m1", "label": "Velocity model 1"}]
    summary = st["cube"]["summary"]
    assert summary["nx"] == N and summary["layers"] == N and summary["vmin"] == summary["vmax"] == 2000.0
    key = core.ctx.time_depth_cube_key()
    assert key.startswith("tdl:") and domain_convert.CUBES[key] is core.ctx.time_depth_cube()
    doc = core.ctx.time_depth_law_doc()
    assert doc["name"] == "Velocity model 1" and "generated" not in doc
    # generated, it is updated by itself
    edit({"op": "set", "index": 1, "velocity": 2500})
    assert core.ctx.time_depth_cube_key() != key and core.state["ui_time_depth_law"]["cube"]["summary"]["vmax"] == 2500.0
    # "New velocity model": the first one left for the inputs of the next, numbered 2 — it
    # goes on converting until another is generated or chosen
    first = core.ctx.time_depth_cube_key()
    edit({"op": "model_activate", "value": "new"})
    st = core.state["ui_time_depth_law"]
    assert st["model"] == "new" and st["generated"] is False
    # there is a zone: the inputs start with their one TDLaw, on the starting line
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"] and st["columns"][0]["rows"] == [ZERO, FAR]
    assert core.ctx.time_depth_cube() is None and core.ctx.time_depth_cube_key() == first
    assert list(domain_convert.CUBES) == [first] and core.ctx.time_depth_convert_cube().summary()["vmax"] == 2500.0
    assert core.ctx.time_depth_converting_id() == 1 and core.ctx.time_depth_model_id() is None
    # the session's document says which model converts meanwhile, and puts it back
    saved = core.ctx.time_depth_law_doc()
    assert saved["generated"] is False and [o.get("converting") for o in saved["others"]] == [True]
    core.ctx.time_depth_law_restore(saved)
    assert core.state["ui_time_depth_law"]["model"] == "new" and core.ctx.time_depth_converting_id() == 1
    assert core.ctx.time_depth_convert_cube().summary()["vmax"] == 2500.0
    edit({"op": "add", "depth": 3000, "twt": 2000})
    edit({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["model"] == "m2" and [m["label"] for m in st["models"]] == [
        "New velocity model", "Velocity model 1", "Velocity model 2"]
    assert st["cube"]["summary"]["vmax"] == 3000.0
    # the first one chosen again: its inputs are back, and it converts
    edit({"op": "model_activate", "value": "m1"})
    st = core.state["ui_time_depth_law"]
    assert st["model"] == "m1" and st["columns"][0]["rows"][1] == {"depth": 5000.0, "twt": 4000.0, "velocity": 2500.0}
    assert domain_convert.CUBES[core.ctx.time_depth_cube_key()].summary()["vmax"] == 2500.0
    # the inputs left on the way to another model are gone: "New velocity model" starts blank
    edit({"op": "model_activate", "value": "new"})
    edit({"op": "add_column"})
    assert [c["name"] for c in core.state["ui_time_depth_law"]["columns"]] == ["TDLaw1", "TDLaw2"]
    edit({"op": "model_activate", "value": "m2"})
    edit({"op": "model_activate", "value": "new"})
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"] and st["columns"][0]["rows"] == [ZERO, FAR]
    assert st["generated"] is False and core.ctx.time_depth_law_doc()["touched"] is False
    domain_convert.register_cube("", None)


def test_inputs_with_a_zone_start_with_one_tdlaw_given_once():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core, _data_bounds=lambda: BOUNDS)
    edit = core.controller.fns["time_depth_law_edit"]
    assert core.state["ui_time_depth_law"]["columns"] == [], "no zone yet: nothing to stand a TDLaw on"
    core.ctx.time_depth_ensure_zone()       # the model's view opened: the zone is the data's
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"] and st["columns"][0]["rows"] == [ZERO, FAR]
    assert (st["columns"][0]["x"], st["columns"][0]["y"]) == (500.0, 250.0)
    # shown, offered, and still no model: nothing converts, nobody touched the inputs
    assert st["can_generate"] is True and st["generated"] is False and core.ctx.time_depth_cube() is None
    assert core.ctx.time_depth_preview()[0] is not None and core.ctx.time_depth_law_doc()["touched"] is False
    # removed by its reader, it does not come back
    edit({"op": "del_column", "index": 0})
    edit({"op": "cube_set", "nx": 12})
    assert core.state["ui_time_depth_law"]["columns"] == []
    domain_convert.register_cube("", None)


def test_gestures_edit_the_law_and_publish_its_rows():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core, _data_bounds=lambda: BOUNDS)
    edit = _generated(core)

    def rows():
        return core.state["ui_time_depth_law"]["columns"][0]["rows"]

    # a point placed on TDLaw1's track
    edit({"op": "add", "depth": 1000, "twt": 1000})
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"] and st["valid"] is True
    assert rows() == [ZERO, {"depth": 1000.0, "twt": 1000.0, "velocity": 2000.0}, FAR]
    edit({"op": "del", "index": 2})
    assert rows() == [ZERO, {"depth": 1000.0, "twt": 1000.0, "velocity": 2000.0}]
    # the one column is the velocity model's law in every cell, registered for the stages
    key = core.ctx.time_depth_cube_key()
    assert domain_convert.CUBES[key] is core.ctx.time_depth_cube()
    assert core.state["ui_time_depth_law"]["cube"]["summary"]["cells"] == N ** 3
    edit({"op": "add"})                               # 500 m further at 2 000 m/s
    assert rows()[2] == {"depth": 1500.0, "twt": 1500.0, "velocity": 2000.0}
    assert core.ctx.time_depth_cube_key() == key      # the same cube (2 000 m/s carried on): its key kept
    # the velocity of an interval edited: the time below follows, the depth stays
    edit({"op": "set", "index": 2, "velocity": 2500})
    assert rows()[2] == {"depth": 1500.0, "twt": 1400.0, "velocity": 2500.0}
    assert core.ctx.time_depth_cube_key() != key      # a new key: the stages see the change
    edit({"op": "set", "index": 2, "velocity": 2000})
    assert rows()[2] == {"depth": 1500.0, "twt": 1500.0, "velocity": 2000.0}
    edit({"op": "set", "index": 2, "twt": 1200})
    assert rows()[2]["velocity"] == 5000.0
    edit({"op": "set", "index": 1, "depth": 1600})    # now deeper than row 2: rows re-ordered
    assert [r["depth"] for r in rows()] == [0.0, 1500.0, 1600.0]
    st = core.state["ui_time_depth_law"]
    # 1600 m at 1000 ms, before 1200 ms: TDLaw1 is left out, and nothing converts any more
    assert st["columns"][0]["why"] == "a point out of order" and st["problems"] == [NO_LAW]
    assert st["valid"] is False and core.ctx.time_depth_cube() is None and domain_convert.CUBES == {}
    edit({"op": "del", "index": 2})
    assert [r["depth"] for r in rows()] == [0.0, 1500.0]
    # the start moves (a datum), it is not deleted
    edit({"op": "set", "index": 0, "depth": 100, "twt": 0})
    assert rows()[0] == {"depth": 100.0, "twt": 0.0, "velocity": None}
    edit({"op": "del", "index": 0})
    assert rows()[0]["depth"] == 100.0
    edit({"op": "reset"})
    assert rows() == [{"depth": 100.0, "twt": 0.0, "velocity": None}]
    domain_convert.register_cube("", None)


def test_the_cube_takes_the_data_extent_and_its_columns_are_what_the_views_draw():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core, _data_bounds=lambda: BOUNDS)
    # the model's one column, entered without a place, stands at the centre
    # of the data's extent: in its velocity model
    edit = _generated(core)
    edit({"op": "cube_auto"})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["extent"] == [-20.0, 1020.0, -10.0, 510.0] and st["cube"]["extent_from"] == "data"
    assert len(st["columns"]) == 1 and st["active"] == 0 and st["columns"][0]["name"] == "TDLaw1"
    assert st["columns"][0]["rows"] == [ZERO, FAR] and st["columns"][0]["why"] == ""
    assert (st["columns"][0]["x"], st["columns"][0]["y"]) == (500.0, 250.0)
    assert st["columns"][0]["valid"] is True and st["valid"] is True
    assert st["cube"]["summary"]["nx"] == N and st["cube"]["summary"]["layers"] == N
    drawn = core.ctx.time_depth_columns()
    assert [(n, x, y) for n, x, y, _law in drawn] == [("TDLaw1", 500.0, 250.0)] and core.ctx.time_depth_active() == 0
    edit({"op": "set_column", "index": 0, "x": 100, "y": 200})
    st = core.state["ui_time_depth_law"]
    drawn = core.ctx.time_depth_columns()
    assert [(n, x, y) for n, x, y, _law in drawn] == [("TDLaw1", 100.0, 200.0)]
    # a corner typed: the extent is typed from then on
    edit({"op": "cube_set", "x0": -50, "nx": 4, "ny": 2})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["extent"] == [-50.0, 1020.0, -10.0, 510.0] and st["cube"]["extent_from"] == "typed"
    assert st["cube"]["summary"]["nx"] == 4 and st["cube"]["summary"]["ny"] == 2
    edit({"op": "cube_auto"})
    assert core.state["ui_time_depth_law"]["cube"]["extent"] == [-20.0, 1020.0, -10.0, 510.0]
    assert core.state["ui_time_depth_law"]["cube"]["extent_from"] == "data"
    # the point gestures act on the active column, or on the one a track names;
    # one layer: a column added on the velocity model starts from its one interval
    edit({"op": "cube_set", "nz": 1})
    edit({"op": "add_column", "x": 500, "y": 200})
    assert core.state["ui_time_depth_law"]["active"] == 1
    edit({"op": "set", "index": 1, "twt": 2500})
    st = core.state["ui_time_depth_law"]
    assert st["columns"][1]["rows"][1]["velocity"] == 4000.0
    assert st["columns"][0]["rows"][1]["velocity"] == 2000.0
    assert st["cube"]["summary"]["vmin"] > 2000.0 and st["cube"]["summary"]["vmax"] < 4000.0
    edit({"op": "name_column", "index": 1, "name": "  A-12 "})
    assert core.state["ui_time_depth_law"]["columns"][1]["name"] == "A-12"
    assert [n for n, *_ in core.ctx.time_depth_columns()] == ["TDLaw1", "A-12"]
    edit({"op": "add", "column": 0})
    st = core.state["ui_time_depth_law"]
    assert st["active"] == 0 and len(st["columns"][0]["rows"]) == 3 and len(st["columns"][1]["rows"]) == 2
    assert st["cube"]["summary"]["layers"] == 1
    # the reader's number of layers, never "auto" (an empty one is no number)
    edit({"op": "cube_set", "nz": 5})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["nz"] == 5 and st["cube"]["summary"]["layers"] == 5
    edit({"op": "cube_set", "nz": None})
    assert core.state["ui_time_depth_law"]["cube"]["summary"]["layers"] == 5
    edit({"op": "del_column", "index": 0})
    st = core.state["ui_time_depth_law"]
    assert len(st["columns"]) == 1 and st["active"] == 0 and st["columns"][0]["x"] == 500.0
    # the last column deleted: none takes its place, and nothing converts
    edit({"op": "del_column", "index": 0})
    st = core.state["ui_time_depth_law"]
    assert st["columns"] == [] and st["generated"] is True and st["problems"] == [NO_LAW]
    assert core.ctx.time_depth_cube() is None
    domain_convert.register_cube("", None)


def test_columns_at_the_centre_take_free_places_inside_the_extent():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core, _data_bounds=lambda: BOUNDS)
    edit = _generated(core)
    for _ in range(6):
        edit({"op": "add_column", "at": "centre"})
    spots = [(c["x"], c["y"]) for c in core.state["ui_time_depth_law"]["columns"]]
    # TDLaw1 stands at the centre; the added ones take the 2 x 2 grid's
    # cells, then the 3 x 3's nearest the centre
    assert spots[:2] == [(500.0, 250.0), (240.0, 120.0)]
    assert len(set(spots)) == 7
    assert all(-20.0 <= x <= 1020.0 and -10.0 <= y <= 510.0 for x, y in spots)
    edit({"op": "del_column", "index": 1})
    edit({"op": "add_column", "at": "centre"})
    last = core.state["ui_time_depth_law"]["columns"][-1]
    assert (last["x"], last["y"]) == (240.0, 120.0)
    # a column entered without a position, then "Place it": the same rule
    edit({"op": "add_column"})
    st = core.state["ui_time_depth_law"]
    assert st["columns"][-1]["why"] == "not placed, no point"
    edit({"op": "set_column", "index": len(st["columns"]) - 1, "at": "free"})
    last = core.state["ui_time_depth_law"]["columns"][-1]
    assert last["x"] is not None and (last["x"], last["y"]) not in spots
    assert -20.0 <= last["x"] <= 1020.0 and -10.0 <= last["y"] <= 510.0
    domain_convert.register_cube("", None)


def test_without_data_the_cube_stands_around_its_columns_until_an_extent_is_typed():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core)
    edit = core.controller.fns["time_depth_law_edit"]
    edit({"op": "add_column"})
    # nothing to stand on: no model is generated of a TDLaw without a place
    edit({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["generated"] is False and st["problems"] == [
        "a velocity model needs a zone: enter its corners, place a TDLaw or tick an object"]
    # no extent to find a centre in: a column "at the centre" is not placed
    # (and has no point among others); TDLaw1, unplaced, is the one that converts
    edit({"op": "add_column", "at": "centre"})
    st = core.state["ui_time_depth_law"]
    assert [c["why"] for c in st["columns"]] == ["", "not placed, no point"] and st["valid"] is True
    assert st["cube"]["extent_used"] is None and st["cube"]["extent_from"] is None
    # a third one placed: the velocity model stands around it, the unplaced ones left out
    edit({"op": "add_column", "x": 1, "y": 2})
    st = core.state["ui_time_depth_law"]
    assert st["valid"] is True and st["problems"] == []
    assert st["cube"]["extent"] == [None, None, None, None] and st["cube"]["extent_from"] == "columns"
    assert st["cube"]["extent_used"] == [-499.0, 501.0, -498.0, 502.0]
    assert [c["why"] for c in st["columns"]] == ["not placed", "not placed, no point", ""]
    assert [n for n, *_ in core.ctx.time_depth_columns()] == ["TDLaw3"] and core.ctx.time_depth_active() == 0
    # a zone to stand on now: generated around its column
    edit({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["generated"] is True and st["cube"]["summary"]["extent"] == [-499.0, 501.0, -498.0, 502.0]
    # the four corners, one by one, kept as a draft until complete
    edit({"op": "cube_set", "x0": 0, "x1": 100})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["extent"] == [0.0, 100.0, None, None] and st["cube"]["extent_from"] == "columns"
    edit({"op": "cube_set", "y0": 0, "y1": 50})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["extent"] == [0.0, 100.0, 0.0, 50.0] and st["valid"] is True
    assert st["cube"]["extent_from"] == "typed" and st["cube"]["extent_used"] == [0.0, 100.0, 0.0, 50.0]
    domain_convert.register_cube("", None)


def test_prefill_asks_then_reads_the_wells_time_logs():
    pytest.importorskip("numpy")
    core = _core()
    asked = {}

    def ask(question, on_yes, on_no, on_third=None):
        asked["q"], asked["yes"] = question, on_yes

    index = [{"uuid": "h", "type": "Grid2dRepresentation", "title": "HOD", "partial": False},
             {"uuid": "t", "type": "WellboreTrajectoryRepresentation", "title": "w", "partial": False},
             {"uuid": "i", "type": "HorizonInterpretation", "title": "no extent", "partial": False}]
    fields = {"h": {"extent_xy": "0;1000;0;500", "extent_how": "lattice"},
              "t": {"extent_xy": "nan;1;2;3"},
              "log1": {"uom": "s", "depth_oriented": "true", "xyz": "10;20;500;10;20;1500", "values": "0.5;1.0"},
              "log2": {"uom": "s", "depth_oriented": "true", "xyz": "100;200;1000;100;200;2000", "values": "0.8;1.4"},
              "log3": {"uom": "s", "depth_oriented": "true", "xyz": "0;0;1000;300;0;2000", "values": "0.8;1.4"}}
    query = types.SimpleNamespace(index=lambda: index, fields=lambda u: fields.get(u, {}))
    channels = [("W1", "log1", "TWTIME", "s"), ("W1", "dt", "DT", "us/ft"),
                ("W2", "log2", "TWT", "s"), ("W3", "v", "VELOCITY", "m/s"), ("W4", "log3", "TWT", "s")]
    feature.register(core, _ask=ask, _query=lambda: query, _channels=lambda: channels,
                     _data_bounds=lambda: BOUNDS)
    edit = core.controller.fns["time_depth_law_edit"]
    st = core.state["ui_time_depth_law"]
    assert st["prefill"] == {"ready": False, "done": [], "wells": 3, "wells_out": 0, "sonic": 2, "sonic_out": 0,
                             "markers": 0, "markers_out": 0, "time_grids": 0, "depth_grids": 0} and st["note"] == ""
    edit({"op": "cube_auto"})
    # the wells: one time log per VERTICAL well; the columns replace what there was,
    # here the TDLaw the inputs started with
    assert len(core.state["ui_time_depth_law"]["columns"]) == 1
    assert core.state["ui_time_depth_law"]["note"] == ""
    edit({"op": "prefill", "what": "wells"})
    assert asked["q"]["title"] == "Read the time logs of 3 wells?"
    assert asked["q"]["body"].startswith("W1 (TWTIME), W2 (TWT), W4 (TWT): ")
    assert "The 1 current TDLaw is replaced." in asked["q"]["body"]
    assert "a deviated one is left out" in asked["q"]["body"]
    asked["yes"]()
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["W1", "W2"] and st["active"] == 0 and st["valid"] is True
    assert [(c["x"], c["y"]) for c in st["columns"]] == [(10.0, 20.0), (100.0, 200.0)]
    assert st["note"] == "2 TDLaws from the wells' time logs, every 200 m · 1 deviated well left out"
    assert st["prefill"]["done"] == ["wells"]
    assert len(st["columns"][0]["rows"]) == 8 and len(st["columns"][1]["rows"]) == 11
    assert st["columns"][0]["rows"][1] == {"depth": 200.0, "twt": 200.0, "velocity": 2000.0}
    assert st["columns"][1]["rows"][6]["twt"] == 920.0
    assert st["can_generate"] is True and st["cube"]["summary"] is None
    edit({"op": "generate"})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["summary"]["layers"] == N and st["cube"]["extent_from"] == "data"
    doc = core.ctx.time_depth_law_doc()
    assert doc["columns"][0]["source"] == "TWTIME, 2 samples" and doc["columns"][0]["name"] == "W1"
    assert doc["prefilled"] == "wells"
    # a column added on the velocity model starts from the velocity model's law there, at the columns' times
    times = sorted({r["twt"] for c in st["columns"] for r in c["rows"]})
    edit({"op": "add_column", "at": "centre"})
    st = core.state["ui_time_depth_law"]
    c3 = st["columns"][2]
    assert (c3["x"], c3["y"]) == (500.0, 250.0) and c3["why"] == "" and st["valid"] is True
    assert [r["twt"] for r in c3["rows"]] == pytest.approx(times)
    assert all(r["velocity"] > 0 for r in c3["rows"][1:]) and st["cube"]["summary"]["layers"] == N
    # a column entered without a position takes the velocity model's law once placed
    edit({"op": "add_column"})
    assert core.state["ui_time_depth_law"]["columns"][3]["rows"] == [ZERO]
    edit({"op": "set_column", "index": 3, "x": 50, "y": 100})
    st = core.state["ui_time_depth_law"]
    assert len(st["columns"][3]["rows"]) == len(times) and st["columns"][3]["why"] == ""
    # nothing to read: said next to the summary, no question
    asked.clear()
    bare = _core()
    feature.register(bare, _ask=ask, _query=lambda: types.SimpleNamespace(index=lambda: [], fields=lambda u: {}),
                     _channels=lambda: [])
    bare_edit = bare.controller.fns["time_depth_law_edit"]
    bare_edit({"op": "prefill", "what": "wells"})
    said = bare.state["ui_time_depth_law"]
    assert said["note"] == "no well carries a time log (a channel in s or ms)" and not asked
    assert said["problems"] == [said["note"]] and said["valid"] is True, "a refusal is in sight, the model stays valid"
    bare_edit({"op": "cube_set", "nx": 5})
    assert bare.state["ui_time_depth_law"]["problems"] == [], "the next edit takes it away"
    domain_convert.register_cube("", None)


def test_the_menu_announces_what_a_pick_gives_once_the_card_is_open():
    """All the wells deviated: 12 announced, nothing given, was the Volve wells."""
    pytest.importorskip("numpy")
    core = _core()
    fields = {"t1": {"extent_xy": "10;10.5;20;20.5"}, "t3": {"extent_xy": "0;300;0;0"}}
    read = []

    def field_of(uuid):
        read.append(uuid)
        return fields.get(uuid, {})

    query = types.SimpleNamespace(index=lambda: [], fields=field_of)
    channels = [("W1", "log1", "TWT", "s"), ("W3", "log3", "TWT", "s"), ("W3", "dt3", "DT", "us/ft")]
    deferred = []
    feature.register(core, _ask=lambda *a, **k: None, _query=lambda: query, _channels=lambda: channels,
                     _trajectories=lambda: [("W1", "t1"), ("W3", "t3")],
                     _defer=lambda name, fn, views=None: deferred.append((fn, views)))
    check = core.ctx.time_depth_prefill_check
    check()
    assert not deferred and core.state["ui_time_depth_law"]["prefill"]["wells"] == 2, "the card closed, nothing read"
    core.mv = lambda: type("M", (), {"panel_ids_of_kind": staticmethod(lambda k: ["view_1"])})()
    check()
    assert len(deferred) == 1 and deferred[0][1] == ["view_1"]
    deferred[0][0]()
    st = core.state["ui_time_depth_law"]["prefill"]
    assert (st["wells"], st["wells_out"], st["sonic"], st["sonic_out"]) == (1, 1, 0, 1)
    assert sorted(read) == ["t1", "t3"], "one read per well, its trajectory"
    deferred.clear()
    check()
    assert not deferred and len(read) == 2, "read once each"
    # what is known deviated is neither asked about nor read
    edit = core.controller.fns["time_depth_law_edit"]
    edit({"op": "prefill", "what": "sonic"})
    said = core.state["ui_time_depth_law"]
    assert said["problems"] == ["the wells with a sonic log are all deviated"] and len(read) == 2
    domain_convert.register_cube("", None)


def test_a_store_says_it_at_the_pick_and_a_deviated_well_makes_no_law_even_where_its_log_is_straight():
    pytest.importorskip("numpy")
    core = _core()
    asked = {}
    logs = {"log1": {"uom": "s", "depth_oriented": "true", "xyz": "0;0;500;300;0;1500", "values": "0.5;1.0"}}
    query = types.SimpleNamespace(index=lambda: [], fields=lambda u: logs.get(u, {}), store=lambda: {"t1", "log1"})
    deferred = []

    def ask(question, on_yes, on_no, on_third=None):
        asked["yes"] = on_yes

    feature.register(core, _ask=ask, _query=lambda: query, _channels=lambda: [("W1", "log1", "TWT", "s")],
                     _trajectories=lambda: [("W1", "t1")],
                     _defer=lambda name, fn, views=None: deferred.append(fn))
    core.mv = lambda: type("M", (), {"panel_ids_of_kind": staticmethod(lambda k: ["view_1"])})()
    core.ctx.time_depth_prefill_check()
    st = core.state["ui_time_depth_law"]
    assert not deferred and st["prefill"]["wells"] == 1, "no request for the menu"
    core.controller.fns["time_depth_law_edit"]({"op": "prefill", "what": "wells"})
    asked["yes"]()
    st = core.state["ui_time_depth_law"]
    assert st["prefill"]["wells"] == 0 and st["prefill"]["wells_out"] == 1, "the pick says it"
    assert len(st["problems"]) == 1 and "deviated well left out" in st["problems"][0]
    domain_convert.register_cube("", None)


def test_extent_says_a_well_is_vertical():
    from fespp_on_trame.engine import time_depth_prefill as prefill
    assert prefill.extent_vertical({"extent_xy": "10;11;20;21"}) is True
    assert prefill.extent_vertical({"extent_xy": "10;110;20;20"}) is False
    assert prefill.extent_vertical({}) is True, "nothing says otherwise"



def test_a_refused_gesture_changes_nothing():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core)
    edit = core.controller.fns["time_depth_law_edit"]
    edit({"op": "add", "depth": 1000, "twt": 1000})    # no TDLaw to put a point on
    assert core.state["ui_time_depth_law"]["columns"] == []
    edit({"op": "add_column"})
    edit({"op": "add", "depth": 1000, "twt": 1000})
    before = core.state["ui_time_depth_law"]
    edit({"op": "del", "index": 7})
    edit({"op": "del", "index": 0})                  # the start moves, it is not deleted
    edit({"op": "set", "index": "x"})
    edit({"op": "fly"})
    edit({"op": "mode", "mode": "2d"})               # no mode any more
    edit({"op": "add", "column": 4})
    edit({"op": "active", "index": 3})
    edit({"op": "set_column", "index": 3, "x": 1})
    edit({"op": "cube_auto"})                         # nothing loaded: refused
    edit({"op": "cube_set", "nx": "wide"})
    edit({"op": "cube_set", "t0": 6000})               # past the range's end
    edit({"op": "prefill", "what": "extent"})         # the files' extent is gone: Auto is the zone
    edit({"op": "look", "look": "fence"})            # the velocity model is a grid of the tree: no look
    edit({"op": "opacity", "value": 0.5})
    edit({"op": "show3d", "on": True})
    edit({"op": "export"})                           # Save as EPC is the tree's
    edit({"op": "set", "index": 1, "velocity": -5})  # a velocity is positive
    edit({"op": "cell", "i": 9, "j": 0, "k": 0, "v": 2500})   # no such cell in a velocity model of one by layer
    edit({"op": "prefill", "what": "stars"})         # no box to ask through, no such pre-fill
    assert core.state["ui_time_depth_law"] == before
    domain_convert.register_cube("", None)


def test_session_round_trip_and_listeners():
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core)
    calls = []
    core.ctx.time_depth_law_listeners.append(lambda: calls.append(1))
    edit = core.controller.fns["time_depth_law_edit"]
    edit({"op": "add_column", "x": 10, "y": 20})
    assert calls == [1]
    edit({"op": "add", "depth": 2000, "twt": 1800})
    edit({"op": "del", "index": 2})                   # the starting line's point goes
    edit({"op": "name_column", "index": 0, "name": "A-12"})
    edit({"op": "cube_set", "x0": 0, "x1": 100, "y0": 0, "y1": 50, "nx": 3, "ny": 2, "nz": 4})
    edit({"op": "generate"})
    # a cell set by hand (the Values card's Map on the model's grid): kept with the model
    edit({"op": "cell", "i": 1, "j": 0, "k": 2, "v": 3100})
    st = core.state["ui_time_depth_law"]
    assert st["cube"]["edited"] == 1 and st["cube"]["summary"]["vmax"] == 3100.0
    assert core.ctx.time_depth_cube().v[2, 0, 1] == 3100.0
    doc = core.ctx.time_depth_law_doc()
    assert doc == {"columns": [{"x": 10.0, "y": 20.0, "points": [{"depth": 2000.0, "twt": 1800.0}], "name": "A-12"}],
                   "extent": [0.0, 100.0, 0.0, 50.0, 0.0, 5000.0], "nx": 3, "ny": 2, "nz": 4,
                   "cells": [[2, 0, 1, 3100.0]], "cells_shape": [4, 2, 3],
                   "extent_from": "typed", "active": 0, "name": "Velocity model 1"}

    other = _core()
    feature.register(other)
    # a document of the files' extent (gone): the zone it names stays, as one typed
    other.ctx.time_depth_law_restore(dict(doc, extent_from="files", extent=[0, 100, 0, 50, 0, 4000]))
    assert other.ctx.time_depth_law_doc() == dict(doc, extent=[0.0, 100.0, 0.0, 50.0, 0.0, 4000.0])
    st = other.state["ui_time_depth_law"]
    assert st["columns"][0]["name"] == "A-12" and st["generated"] is True and st["model"] == "m1"
    assert st["cube"]["extent_from"] == "typed" and st["cube"]["edited"] == 1
    assert st["cube"]["summary"]["tmax"] == 4000.0
    assert st["columns"][0]["rows"][1]["velocity"] == 2000.0 * 2000.0 / 1800.0
    assert st["cube"]["summary"]["nx"] == 3 and st["cube"]["summary"]["layers"] == 4 and st["valid"] is True
    # the velocity model's cells change: the cells set by hand no longer apply, and it is said
    other.controller.fns["time_depth_law_edit"]({"op": "cube_set", "nz": 3})
    st = other.state["ui_time_depth_law"]
    assert st["cube"]["edited"] == 0 and st["note"] == "the 1 cell set by hand no longer apply: the velocity model's cells changed"
    assert "cells" not in other.ctx.time_depth_law_doc()
    # an older document, the 1D law's points alone: one column, everywhere
    other.ctx.time_depth_law_restore({"points": [{"depth": 1000, "twt": 1000}]})
    st = other.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["TDLaw1"] and st["cube"]["summary"]["cells"] == N
    assert st["generated"] is True and [m["label"] for m in st["models"]] == ["New velocity model", "Velocity model 1"]
    # a document before the models were generated, its default model untouched: no model
    other.ctx.time_depth_law_restore({"columns": [{"x": None, "y": None, "points": [{"depth": 5000, "twt": 5000}]}],
                                      "extent": [None, None, None, None, 0, 5000], "touched": False})
    st = other.state["ui_time_depth_law"]
    assert st["generated"] is False and st["columns"] == [] and st["models"] == [NEW]
    assert other.ctx.time_depth_cube() is None
    # the inputs of a model not generated come back as they were, still not a model
    draft = _core()
    feature.register(draft)
    draft.controller.fns["time_depth_law_edit"]({"op": "add_column", "x": 1, "y": 2})
    saved = draft.ctx.time_depth_law_doc()
    assert saved["generated"] is False and "name" not in saved
    other.ctx.time_depth_law_restore(saved)
    st = other.state["ui_time_depth_law"]
    assert st["generated"] is False and [(c["x"], c["y"]) for c in st["columns"]] == [(1.0, 2.0)]
    assert other.ctx.time_depth_law_doc() == saved
    domain_convert.register_cube("", None)


def test_prefill_reads_the_sonic_logs_and_the_markers_by_their_interpretation():
    pytest.importorskip("numpy")
    core = _core()
    asked = {}

    def ask(question, on_yes, on_no, on_third=None):
        asked["q"], asked["yes"] = question, on_yes

    us_ft = 1e6 * 0.3048 / 2000.0

    def rep(title, interp, crs):
        return (f"<obj><Citation><Title>{title}</Title></Citation><RepresentedInterpretation><UUID>{interp}</UUID>"
                f"</RepresentedInterpretation><Geometry><LocalCrs><UUID>{crs}</UUID></LocalCrs></Geometry></obj>")

    xml = {"gt": rep("BCU time", "it", "crst"), "gd": rep("BCU depth", "id", "crsd"),
           "it": "<obj><Citation><Title>|UNNAMED|</Title></Citation><InterpretedFeature><UUID>fb</UUID></InterpretedFeature></obj>",
           "id": "<obj><Citation><Title>|UNNAMED|</Title></Citation><InterpretedFeature><UUID>fb</UUID></InterpretedFeature></obj>",
           "fb": "<obj><Citation><Title>BCU</Title></Citation></obj>",
           "mf": "<frame><WellboreMarker><Interpretation><UUID>it</UUID></Interpretation></WellboreMarker></frame>"}

    def surface(z):
        return {"lattice": "0;0;100;0;0;100", "nodes": "2;2", "stride": "1", "z": f"{z};{z};{z};{z}",
                "depth_oriented": "true"}

    fields = {"crst": {"time_crs": "true", "time_unit": "ms"}, "crsd": {"time_crs": "false"},
              "dt": {"uom": "us/ft", "depth_oriented": "true", "xyz": "50;50;1000;50;50;2000",
                     "values": f"{us_ft};{us_ft}"},
              "dt2": {"uom": "us/ft", "depth_oriented": "true", "xyz": "50;50;1000;90;50;2000",
                      "values": f"{us_ft};{us_ft}"},
              "mf": {"xyz": "50;50;2000", "depth_oriented": "true", "marker_feature.0": "fb|BCU"}}
    # a stub left on an ETP store is read too: the query channel fetches it
    index = [{"uuid": "gt", "type": "Grid2dRepresentation", "title": "BCU time", "partial": True},
             {"uuid": "gd", "type": "Grid2dRepresentation", "title": "BCU depth", "partial": False}]
    query = types.SimpleNamespace(index=lambda: index, fields=lambda u: fields.get(u, {}),
                                  xml=lambda uuids: [xml.get(u, "") for u in uuids],
                                  surface=lambda u: surface(1500) if u == "gt" else surface(2000))
    feature.register(core, _ask=ask, _query=lambda: query,
                     _channels=lambda: [("W1", "dt", "DT", "us/ft"), ("W2", "dt2", "DT", "us/ft")],
                     _markers=lambda: [("W1", "mf", "strati", ["BCU"])],
                     _grids=lambda: {"depth": 1, "time": 1})
    edit = core.controller.fns["time_depth_law_edit"]
    assert core.state["ui_time_depth_law"]["prefill"] == {"ready": False, "done": [], "wells": 0, "wells_out": 0, "sonic": 2, "sonic_out": 0,
                                                         "markers": 1, "markers_out": 0, "time_grids": 1, "depth_grids": 1}
    # the sonic: integrated from its top, above it 2 000 m/s while no model converts
    edit({"op": "prefill", "what": "sonic"})
    assert asked["q"]["title"] == "Integrate the sonic logs of 2 wells?"
    assert asked["q"]["body"].startswith("W1 (DT), W2 (DT): ") and "above its top, 2000 m/s from the zero" in asked["q"]["body"]
    asked["yes"]()
    st = core.state["ui_time_depth_law"]
    assert [c["name"] for c in st["columns"]] == ["W1"] and st["can_generate"] is True
    assert st["note"] == "1 TDLaws from the wells' sonic logs, every 200 m · 1 deviated well left out"
    assert all(abs(r["twt"] - r["depth"]) < 1e-6 for r in st["columns"][0]["rows"])
    assert core.ctx.time_depth_law_doc()["columns"][0]["source"] == "DT integrated from 1000 m"
    # the markers: each on the one time surface of its interpretation
    edit({"op": "prefill", "what": "markers"})
    assert asked["q"]["title"] == "Read the markers of 1 well on the time horizons?"
    assert asked["q"]["body"].startswith("1 interpretation has one surface in time.")
    assert "The 1 current TDLaw is replaced." in asked["q"]["body"]
    asked["yes"]()
    st = core.state["ui_time_depth_law"]
    assert st["note"] == "1 TDLaws from the markers on 1 time horizons, every 200 m"
    assert st["columns"][0]["rows"][-1] == {"depth": 2000.0, "twt": 1500.0, "velocity": 2000.0 * 2000.0 / 1500.0}
    assert st["prefill"]["done"] == ["markers"]
    # a second surface in time of the same interpretation: which one? none read
    index.append({"uuid": "gt2", "type": "Grid2dRepresentation", "title": "BCU time 2", "partial": False})
    xml["gt2"] = rep("BCU time 2", "it", "crst")
    edit({"op": "prefill", "what": "markers"})
    assert "0 interpretations have one surface in time, 1 more than one: their markers point at no single time horizon" in asked["q"]["body"]
    asked["yes"]()
    assert core.state["ui_time_depth_law"]["note"] == "no marker's interpretation has one surface in time"
    domain_convert.register_cube("", None)


class _Tree:
    """The few calls crs_reference makes of the data tree."""
    _data_assembly = object()

    def __init__(self, nodes):
        self.nodes = nodes      # {nid: (type, path, vdomain)}

    def iter_nodes(self, start=None):
        return [(nid, []) for nid in self.nodes]

    def find_type(self, nid):
        return self.nodes[nid][0]

    def find_path(self, nid):
        return self.nodes[nid][1]

    def find_attribute_value(self, nid, name):
        return self.nodes[nid][2] if name == "vdomain" else None

    find_parent_attribute_value = find_attribute_value


class _GridTree(_Tree):
    """A tree of grids, each node named by its uuid under a container."""

    def find_node_id_by_uuid(self, uuid):
        return next((nid for nid, (_t, path, _d) in self.nodes.items() if path.endswith("/_" + uuid)), None)

    def find_parent_node_id_with_type(self, nid, kind):
        path = self.nodes[nid][1]
        return next((n for n, (t, p, _d) in self.nodes.items() if t == kind and path.startswith(p + "/")), None)


def test_the_lattice_grids_are_the_rows_use_as_velocity_model_is_offered_on():
    core = _core()
    core.tree = _GridTree({1: ("GridContainer", "/data/_gridfolder_aaa", "depth"),
                           2: ("IjkGrid", "/data/_gridfolder_aaa/_propsfolder_aaa/_aaa", "depth"),
                           3: ("GridContainer", "/data/_gridfolder_bbb", "depth"),
                           4: ("IjkGrid", "/data/_gridfolder_bbb/_propsfolder_bbb/_bbb", "depth")})
    index = [{"uuid": "aaa", "type": "IjkGridRepresentation", "title": "cube", "partial": False},
             {"uuid": "bbb", "type": "IjkGridRepresentation", "title": "field", "partial": False},
             {"uuid": "ccc", "type": "Grid2dRepresentation", "title": "top", "partial": False}]
    xml = {"aaa": '<g><Points xsi:type="resqml20:Point3dLatticeArray"/></g>',
           "bbb": '<g><Points xsi:type="resqml20:Point3dHdf5Array"/></g>'}
    query = types.SimpleNamespace(index=lambda: index, fields=lambda u: {},
                                  xml=lambda uuids: [xml.get(u, "") for u in uuids])
    feature.register(core, _query=lambda: query, _channels=lambda: [])
    assert core.ctx.time_depth_cube_grid_rows() == ["/data/_gridfolder_aaa"]
    # the query failing reads as no lattice, said in the log, not raised
    query.index = lambda: (_ for _ in ()).throw(RuntimeError("no channel"))
    assert core.ctx.time_depth_cube_grid_rows() == []
    domain_convert.register_cube("", None)


def test_the_tree_counts_its_2d_grids_by_domain():
    from fespp_on_trame.engine import crs_reference
    tree = _Tree({1: ("Grid2d", "/a/_g1", "time"), 2: ("Grid2dRepresentation", "/b/_g1", "time"),
                  3: ("Grid2d", "/a/_g2", "depth"), 4: ("Grid2d", "/a/_g3", None),
                  5: ("TriangulatedSet", "/a/_t", "time")})
    assert crs_reference.grids_by_domain(tree) == {"depth": 1, "time": 1}
    assert crs_reference.grids_by_domain(None) == {"depth": 0, "time": 0}


def test_a_session_with_a_velocity_model_of_the_data_asks_for_it_again():
    """A model of the data holds nothing to put back: the document names its
    grid and the velocity it read, the restore reads them again once the
    session's reads are in — and the card says so when the grid is not in
    the loaded data."""
    pytest.importorskip("numpy")
    core = _core()
    feature.register(core)
    core.ctx.time_depth_law_restore({"name": "V cube", "from": "grid:Vint", "data": "/data/grid",
                                     "velocity": "/data/grid/Vint"})
    st = core.state["ui_time_depth_law"]
    # until its grid is read again, no model is active: nothing converts
    assert st["data"] is False and st["note"] == "" and st["generated"] is False
    assert core.ctx.time_depth_cube() is None
    core.ctx.time_depth_law_restore_data()
    st = core.state["ui_time_depth_law"]
    assert st["note"] == ("not taken as the velocity model: the grid of the session's velocity model"
                          " is not in the loaded data")
    domain_convert.register_cube("", None)
