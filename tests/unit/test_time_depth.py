"""The time-depth law (engine/time_depth): points, velocities, the
conversion both ways, what keeps a law from converting."""
import pytest

from fespp_on_trame.engine.time_depth import DEFAULT_CELLS, DEFAULT_LAYERS, DEPTH, TIME, ZERO, Column, Law, Model


def test_a_new_law_has_no_point_and_says_so():
    law = Law()
    assert law.rows() == [ZERO]
    assert law.problems() == ["no point beyond the start: enter a depth and its two-way time"]
    assert not law.valid()
    assert law.table() == ([], [])
    with pytest.raises(ValueError):
        law.to_time(100.0)


def test_one_point_is_one_velocity_from_the_zero():
    law = Law([(2000.0, 2000.0)])          # 2 000 m in 2 000 ms two-way: 2 000 m/s
    assert law.valid()
    assert law.velocities() == [2000.0]
    assert law.to_time(1000.0) == 1000.0
    assert law.to_depth(500.0) == 500.0
    # the line carries on beyond the point
    assert law.to_time(3000.0) == 3000.0
    assert law.to_depth(4000.0) == 4000.0


def test_two_intervals_each_their_own_velocity():
    law = Law([(1000.0, 1000.0), (3000.0, 2000.0)])   # 2 000 m/s, then 4 000 m/s
    assert law.velocities() == [2000.0, 4000.0]
    assert law.to_time(500.0) == 500.0
    assert law.to_time(2000.0) == 1500.0
    assert law.to_depth(1500.0) == 2000.0
    # beyond the last point: the last interval's velocity
    assert law.to_time(4000.0) == 2500.0
    assert law.to_depth(2500.0) == 4000.0
    assert law.convert([500.0, 2000.0], TIME) == [500.0, 1500.0]
    assert law.convert([500.0, 1500.0], DEPTH) == [500.0, 2000.0]


def test_points_are_read_in_depth_order_whatever_the_entry_order():
    law = Law([(3000.0, 2000.0), (1000.0, 1000.0)])
    assert law.rows() == [ZERO, (1000.0, 1000.0), (3000.0, 2000.0)]
    assert law.valid()


def test_a_point_not_below_and_later_than_the_previous_is_a_problem():
    law = Law([(1000.0, 1000.0), (1500.0, 900.0)])
    assert law.velocities() == [2000.0, None]
    assert law.problems() == [
        "point 2 (1500 m, 900 ms) is not below and later than the one before (1000 m, 1000 ms)"]
    assert law.table() == ([], [])


def test_edit_add_and_delete_points():
    law = Law([(1000.0, 1000.0)])
    i = law.add_point()                     # 500 m further at the same velocity
    assert i == 1 and law.points[1] == (1500.0, 1500.0)
    law.set_point(1, twt=1200.0)
    assert law.points[1] == (1500.0, 1200.0)
    assert law.velocities() == [2000.0, 5000.0]
    law.del_point(0)
    assert law.rows() == [ZERO, (1500.0, 1200.0)]
    assert Law().add_point() == 0 and Law().add_point.__self__ is not None
    # a start other than the zero: a datum, 120 m at 0 ms
    datum = Law([(1000.0, 880.0)], start=(120.0, 0.0))
    assert datum.rows() == [(120.0, 0.0), (1000.0, 880.0)] and datum.velocities() == [2000.0]
    assert datum.to_time(120.0) == 0.0 and datum.to_time(20.0) == -100.0
    assert Law.from_dict(datum.to_dict()).rows() == datum.rows()
    datum.add_point(60.0, -60.0)          # above the start: the new start
    assert datum.rows()[:2] == [(60.0, -60.0), (120.0, 0.0)]


def test_a_column_is_a_law_at_a_position():
    col = Column(Law([(1000.0, 1000.0)]), 10, 20)
    assert col.placed() and col.to_dict() == {"x": 10.0, "y": 20.0, "points": [{"depth": 1000.0, "twt": 1000.0}]}
    assert not Column().placed()
    assert Column.from_dict({"x": 1, "points": [{"depth": 500, "twt": 400}]}).law.velocities() == [2500.0]


def test_the_model_converts_with_one_column_or_the_placed_ones_and_with_none_does_not():
    model = Model()
    # no column to start with: nothing converts, no law stands in
    assert model.columns == [] and not model.has_law() and model.valid()
    assert model.laws() == [] and model.columns_of() == [] and model.cube() is None
    # a column added by hand starts on a line to edit, 0 to 5 000 m at 2 000 m/s: its law everywhere
    model.add_column()
    assert model.columns[0].law.points == [(5000.0, 5000.0)] and model.has_law()
    assert model.columns_of() == [{"x": None, "y": None, "depths": [0.0, 5000.0], "times": [0.0, 5000.0]}]
    # a column that cannot convert: nothing does, no law stands in for it
    model.columns[0].law.points.clear()
    assert not model.has_law() and model.why_left_out(model.columns[0]) == "no point"
    assert model.columns_of() == [] and model.cube() is None
    # one column: its law everywhere, wherever it stands
    model.columns[0].law.points[:] = [(1000.0, 1000.0)]
    assert model.has_law() and model.why_left_out(model.columns[0]) == ""
    assert model.columns_of() == [{"x": None, "y": None, "depths": [0.0, 1000.0], "times": [0.0, 1000.0]}]
    assert model.extent_in_use() is None
    model.columns[0].x, model.columns[0].y = 5.0, 6.0
    # no extent set: a square around the columns, 1 km around a lone one
    assert model.extent_in_use() == (-495.0, 505.0, -494.0, 506.0)
    model.extent = (0.0, 10.0, 0.0, 0.0)
    assert model.problems() == ["the extent is empty: x1 above x0 and y1 above y0"]
    model.extent = (0.0, 10.0, 0.0, 10.0)
    assert model.valid()
    model.add_column(7.0, 8.0)             # the first column's law to start from
    assert model.columns[1].law.points == [(1000.0, 1000.0)]
    model.columns[1].law.set_point(0, twt=500.0)
    assert [c["times"][1] for c in model.columns_of()] == [1000.0, 500.0]
    # a column without a point, or with a point out of order, is left
    # out: the velocity model reads the others
    model.columns[1].law.points.clear()
    assert model.why_left_out(model.columns[1]) == "no point" and model.valid()
    assert [c["x"] for c in model.columns_of()] == [5.0]
    model.columns[1].law.points[:] = [(1000.0, 1000.0), (1200.0, 900.0)]
    assert model.why_left_out(model.columns[1]) == "a point out of order"
    # among several, an unplaced column is left out
    model.add_column()
    assert model.why_left_out(model.columns[2]) == "not placed"
    model.columns[2].law.points.clear()
    assert model.why_left_out(model.columns[2]) == "not placed, no point"


def test_the_model_round_trips_and_reads_an_older_document():
    model = Model()
    model.columns.clear()
    model.add_column(1.0, 2.0)
    model.columns[0].law.points[:] = [(2000.0, 1800.0)]
    model.columns[0].law.start = (120.0, 0.0)
    model.extent, model.nx, model.ny, model.nz = (0.0, 10.0, 0.0, 20.0), 4, 2, 6
    doc = model.to_dict()
    assert doc == {"columns": [{"x": 1.0, "y": 2.0, "points": [{"depth": 2000.0, "twt": 1800.0}],
                                "start": {"depth": 120.0, "twt": 0.0}}],
                   "extent": [0.0, 10.0, 0.0, 20.0, 0.0, 5000.0], "nx": 4, "ny": 2, "nz": 6}
    again = Model.from_dict(doc)
    assert again.to_dict() == doc and again.columns_of()[0]["x"] == 1.0
    # a document before 02/11: its 1D law comes back as the first column
    old = Model.from_dict({"points": [{"depth": 1000, "twt": 1000}]})
    assert [(c.name, c.law.points) for c in old.columns] == [(None, [(1000.0, 1000.0)])]
    assert old.extent is None and (old.nx, old.ny, old.nz) == (DEFAULT_CELLS, DEFAULT_CELLS, DEFAULT_LAYERS)
    assert old.trange == (0.0, 5000.0) and Model.from_dict({"trange": [100, 3000]}).trange == (100.0, 3000.0)
    assert Model.from_dict({"extent": [0, 1, 0, 1], "trange": [100, 3000]}).extent == (0.0, 1.0, 0.0, 1.0)
    # no zone set: its times are kept all the same
    bare = Model.from_dict({"extent": [None, None, None, None, 100, 3000]})
    assert bare.extent is None and bare.trange == (100.0, 3000.0)
    assert bare.to_dict()["extent"] == [None, None, None, None, 100.0, 3000.0]
    both = {"points": [{"depth": 5, "twt": 5}], "columns": [{"x": 1, "y": 2, "points": [{"depth": 9, "twt": 9}]}]}
    assert [c.name for c in Model.from_dict(dict(both, mode="1d")).columns] == ["1D", None]
    assert [c.law.points for c in Model.from_dict(dict(both, mode="cube")).columns] == [[(9.0, 9.0)]]
    assert Model.from_dict({"extent": "wide", "nx": "many"}).extent is None


def test_the_model_says_how_deep_what_was_entered_goes():
    model = Model()
    assert model.deepest() == (0.0, 0.0)
    model.add_column(1.0, 2.0)
    model.columns[0].law.points[:] = [(1000.0, 900.0), (2500.0, 1800.0)]
    assert model.deepest() == (2500.0, 1800.0)


def test_the_model_makes_its_cube():
    pytest.importorskip("numpy")
    model = Model()
    assert model.cube() is None                        # no column: no velocity model
    model.add_column()
    model.columns[0].law.points[:] = [(5000.0, 5000.0)]
    cube = model.cube()                               # the one column, unplaced: one cell by layer
    assert (cube.nx, cube.ny, cube.layers) == (1, 1, DEFAULT_LAYERS) and (cube.v == 2000.0).all()
    model.nz = None                                    # the engine keeps the layers at the times entered
    model.columns.clear()
    model.add_column(0.0, 0.0)
    model.columns[0].law.points[:] = [(1000.0, 1000.0)]
    model.add_column(100.0, 0.0)
    model.columns[1].law.set_point(0, twt=500.0)
    cube = model.cube()                               # no extent set: around the columns
    assert (cube.x0, cube.x1, cube.y0, cube.y1) == (-450.0, 550.0, -500.0, 500.0)
    model.extent, model.nx, model.ny = (0.0, 100.0, -50.0, 50.0), 2, 1
    cube = model.cube()
    assert (cube.nx, cube.ny, cube.layers) == (2, 1, 2) and cube.t.tolist() == [0.0, 500.0, 1000.0]
    assert 2000.0 < cube.v[0, 0, 0] < cube.v[0, 0, 1] < 4000.0
    # K even layers in two-way time over the time range, the laws' depths kept at their boundaries
    model.nz = 4
    cube = model.cube()
    assert cube.layers == 4 and cube.t.tolist() == [0.0, 1250.0, 2500.0, 3750.0, 5000.0]
    assert abs(float(cube.to_depth([0.0], [0.0], [5000.0])[0]) - float(cube.z[-1, 0, 0])) < 1e-6
    model.trange = (5000.0, 100.0)
    assert model.cube() is None and model.problems() == ["the time range is empty: its end later than its start"]


def test_dict_round_trip_drops_the_zero_and_the_unreadable():
    law = Law.from_dict({"points": [{"depth": 0, "twt": 0}, {"depth": "1000", "twt": 1000},
                                    {"depth": None, "twt": 1}]})
    assert law.points == [(1000.0, 1000.0)]
    assert law.to_dict() == {"points": [{"depth": 1000.0, "twt": 1000.0}]}
    assert Law.from_dict(None).points == []


def test_a_column_beyond_the_extent_set_grows_the_cube_and_is_named():
    # two fields side by side (the PO, 01/11): the neighbour's wells count
    model = Model()
    model.columns.clear()
    model.extent = (0.0, 1000.0, 0.0, 500.0)
    model.add_column(500.0, 250.0)
    assert model.outside_extent() == [] and model.extent_in_use() == (0.0, 1000.0, 0.0, 500.0)
    model.add_column(1500.0, 250.0)        # east of the zone: only x1 grows, with its margin
    assert model.outside_extent() == [1]
    assert model.extent_in_use() == (0.0, 1530.0, 0.0, 500.0)
    model.add_column(-100.0, 700.0)        # north-west: x0 and y1 grow
    assert model.outside_extent() == [1, 2]
    assert model.extent_in_use() == (-132.0, 1532.0, 0.0, 732.0)
    model.add_column()                     # not placed: grows nothing
    assert model.outside_extent() == [1, 2]
    model.extent = None                    # no extent set: nothing is outside
    assert model.outside_extent() == []
