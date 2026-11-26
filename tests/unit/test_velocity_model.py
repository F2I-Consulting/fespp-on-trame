"""The velocity model (engine/velocity_model), in two-way time: built from
the one law or from placed columns, the depths integrated down a cell's
vertical, the conversion both ways, the columns drawn in a view."""
import pytest


from fespp_on_trame.engine.time_depth import Law
from fespp_on_trame.engine import velocity_model as vc

LAW = Law([(1000.0, 1000.0), (3000.0, 2000.0)])      # 2 000 m/s, then 4 000 m/s


def test_the_probe_reads_a_cell_and_the_other_vertical():
    cube = vc.Cube(0, 100, 0, 50, 2, 1, [0, 1000, 2000], [[[2000, 2000]], [[2500, 3000]]])
    hit = cube.probe(25, 25, 500)
    assert (hit["i"], hit["j"], hit["k"], hit["v"]) == (0, 0, 0, 2000.0)
    assert hit["twt"] == pytest.approx(500.0)
    # the second layer, 1 000 to 2 000 ms: 1 000 m down at 3 000 m/s from 1 000 m
    hit = cube.probe(75, 25, 1500, vc.TIME)
    assert (hit["i"], hit["k"], hit["v"]) == (1, 1, 3000.0)
    assert hit["depth"] == pytest.approx(1000.0 + 3000.0 * 500.0 / 2000.0)
    back = cube.probe(75, 25, hit["depth"])
    assert back["twt"] == pytest.approx(1500.0) and back["k"] == 1
    # the faces of the drawn cube read their own cells
    assert cube.probe(100, 50, 0)["i"] == 1 and cube.probe(0, 0, 2000, vc.TIME)["k"] == 1
    assert cube.probe(150, 25, 500) is None
    assert cube.probe(25, 25, 2500, vc.TIME) is None and cube.probe(25, 25, -1, vc.TIME) is None


def test_the_one_law_fills_a_cube_of_one_cell_exactly():
    np = pytest.importorskip("numpy")
    cube = vc.Cube.build([(None, None, LAW)])
    assert (cube.nx, cube.ny, cube.layers) == (1, 1, 2)
    # over an extent, the same law in every cell: a velocity model to draw
    over = vc.Cube.build([(None, None, LAW)], extent=(0, 100, 0, 100), nx=5, ny=5)
    assert (over.nx, over.ny) == (5, 5) and (over.v == cube.v[:, :1, :1]).all()
    assert cube.t.tolist() == [0.0, 1000.0, 2000.0] and cube.v[:, 0, 0].tolist() == [2000.0, 4000.0]
    assert cube.z[:, 0, 0].tolist() == [0.0, 1000.0, 3000.0]
    x = y = np.zeros(4)
    assert cube.to_time(x, y, np.array([500.0, 1000.0, 2000.0, 4000.0])).tolist() == [500.0, 1000.0, 1500.0, 2500.0]
    assert cube.to_depth(x, y, np.array([500.0, 1000.0, 1500.0, 2500.0])).tolist() == [500.0, 1000.0, 2000.0, 4000.0]
    # anywhere: the one cell carries on outside its extent
    assert cube.to_time(np.array([1e6]), np.array([-1e6]), np.array([2000.0])).tolist() == [1500.0]
    assert cube.summary()["cells"] == 2 and cube.summary()["vmax"] == 4000.0
    assert (cube.summary()["tmax"], cube.summary()["zmax"]) == (2000.0, 3000.0)


def test_even_layers_over_the_time_range_set():
    cube = vc.Cube.build([(None, None, LAW)], nz=4, trange=(0.0, 4000.0))
    assert cube.t.tolist() == [0.0, 1000.0, 2000.0, 3000.0, 4000.0]
    # below the last point the last interval carries on
    assert cube.v[:, 0, 0].tolist() == [2000.0, 4000.0, 4000.0, 4000.0]
    assert cube.z[:, 0, 0].tolist() == [0.0, 1000.0, 3000.0, 5000.0, 7000.0]


def test_placed_columns_are_control_points_read_by_their_distance():
    np = pytest.importorskip("numpy")
    slow = (0.0, 0.0, Law([(1000.0, 1000.0)]))        # 2 000 m/s
    fast = (1000.0, 0.0, Law([(2000.0, 1000.0)]))     # 4 000 m/s
    cube = vc.Cube.build([slow, fast], extent=(0, 1000, -500, 500), nx=2, ny=1)
    assert (cube.nx, cube.ny, cube.layers) == (2, 1, 1)
    assert cube.t.tolist() == [0.0, 1000.0]
    v_left, v_right = cube.v[0, 0, 0], cube.v[0, 0, 1]
    assert 2000.0 < v_left < v_right < 4000.0
    # the depth at 1 000 ms is v × 1 000 / 2 000 of the cell
    z = cube.to_depth(np.array([250.0, 750.0]), np.array([0.0, 0.0]), np.array([1000.0, 1000.0]))
    assert z.tolist() == pytest.approx([v_left / 2.0, v_right / 2.0])
    back = cube.to_time(np.array([250.0, 750.0]), np.array([0.0, 0.0]), z)
    assert back.tolist() == pytest.approx([1000.0, 1000.0])
    # convert keeps the sign
    t = cube.convert(np.array([[250.0, 0.0, -1000.0], [250.0, 0.0, 0.0]]), vc.TIME)
    assert t.tolist() == pytest.approx([-2000.0 * 1000.0 / v_left, 0.0])


def test_no_valid_law_gives_no_cube_and_an_unplaced_cube_needs_no_extent():
    pytest.importorskip("numpy")
    assert vc.Cube.build([(None, None, Law())]) is None
    assert vc.Cube.build([]) is None
    cube = vc.Cube.build([(1.0, 2.0, LAW)], extent=None, nx=3, ny=3)
    assert (cube.nx, cube.ny) == (1, 1)


def test_the_columns_drawn_in_a_view():
    pytest.importorskip("numpy")
    pytest.importorskip("vtkmodules.vtkCommonDataModel")
    cube = vc.Cube.build([(0.0, 0.0, LAW)], extent=(-100, 100, -100, 100), nx=2, ny=2)
    pins = cube.pins(vc.TIME, [("TDLaw1", 0.0, 0.0, LAW)], active=0)
    assert pins["lines"].GetCellData().GetArray("velocity").GetValue(1) == 4000.0
    assert pins["points"].GetNumberOfPoints() == 3 and pins["halo"].GetNumberOfLines() == 2
    assert pins["points"].GetBounds()[4:] == (-2000.0, 0.0)
    # the name above the zero, so a velocity model's top face does not hide it
    name, x, y, z = pins["labels"][0]
    assert (name, x, y) == ("TDLaw1", 0.0, 0.0) and z > 0
    depth = cube.pins(vc.DEPTH, [("TDLaw1", 0.0, 0.0, LAW)])
    assert depth["points"].GetBounds()[4:] == (-3000.0, 0.0) and depth["halo"] is None


def test_the_outside_of_a_model_as_a_reader_would_draw_its_grid():
    pytest.importorskip("numpy")
    pytest.importorskip("vtkmodules.vtkCommonDataModel")
    cube = vc.Cube.build([(0.0, 0.0, LAW)], extent=(-100, 100, -100, 100), nx=2, ny=2)
    shell = cube.shell(vc.TIME)
    # 2 × 2 columns of 2 layers: their top and bottom faces, and the rim's faces layer by layer
    assert shell.GetNumberOfCells() == 4 + 4 + 8 * 2
    assert shell.GetBounds() == (-100.0, 100.0, -100.0, 100.0, -2000.0, 0.0)
    assert shell.GetCellData().GetArray("velocity").GetRange() == (2000.0, 4000.0)
    assert cube.shell(vc.DEPTH).GetBounds()[4:] == (-3000.0, 0.0)


def test_a_model_in_depth_keeps_its_depths_when_read_in_time():
    np = pytest.importorskip("numpy")
    # two columns, two layers of 1000 m: 2000 then 4000 m/s, and 4000 throughout
    v = np.array([[[2000.0, 4000.0]], [[4000.0, 4000.0]]])
    times, out, surface = vc.depth_model_in_time([0.0, 1000.0, 2000.0], v)
    assert surface == 0.0 and list(times) == [0.0, 750.0, 1500.0]
    depth = np.cumsum(out * np.diff(times)[:, None, None] / 2000.0, axis=0)
    # the first column at 1500 ms is at its bottom, the second carries on at 4000 m/s
    assert depth[-1, 0, 0] == pytest.approx(2000.0) and depth[-1, 0, 1] == pytest.approx(3000.0)
    # 750 ms into the first column: past its first layer (1000 m in 1000 ms)? no, 750 m
    assert depth[0, 0, 0] == pytest.approx(750.0) and depth[0, 0, 1] == pytest.approx(1500.0)


def test_a_model_in_depth_starting_below_the_zero_reaches_the_surface_at_time_zero():
    np = pytest.importorskip("numpy")
    times, out, surface = vc.depth_model_in_time([500.0, 1000.0], np.full((1, 1, 1), 2500.0))
    assert surface == 0.0 and times[0] == 0.0 and times[-1] == pytest.approx(800.0)
    assert out[0, 0, 0] == pytest.approx(2500.0)


def test_a_cell_without_velocity_takes_the_mean_of_the_others():
    np = pytest.importorskip("numpy")
    v = np.array([[[0.0]], [[3000.0]]])
    _times, out, _surface = vc.depth_model_in_time([0.0, 300.0, 600.0], v)
    assert np.allclose(out, 3000.0)
    with pytest.raises(ValueError):
        vc.depth_model_in_time([0.0, 300.0], np.zeros((1, 1, 1)))


def test_a_cell_with_no_velocity_takes_the_nearest_one_of_its_column():
    np = pytest.importorskip("numpy")
    nan = float("nan")
    # four layers, three columns: a hole between two velocities, holes above
    # and below the only one, a column that holds none
    v = np.array([[[2000.0, nan, 0.0]],
                  [[nan, -999.25, nan]],
                  [[3000.0, 2500.0, float("inf")]],
                  [[3200.0, nan, nan]]], dtype=np.float32)
    assert vc.fill_missing(v) == 8
    assert v[:, 0, 0].tolist() == [2000.0, 2000.0, 3000.0, 3200.0]      # the one above
    assert v[:, 0, 1].tolist() == [2500.0, 2500.0, 2500.0, 2500.0]      # else the one below
    assert np.allclose(v[:, 0, 2], 2525.0)                              # none: the mean of the others
    assert v.dtype == np.float32
    assert vc.fill_missing(np.full((2, 1, 1), 2000.0)) == 0
    with pytest.raises(ValueError):
        vc.fill_missing(np.array([[[nan]], [[0.0]]]))


@pytest.mark.parametrize("reading", ["interval", "average", "rms"])
def test_a_grid_read_as_it_is_from_below_time_zero_keeps_its_depths(reading):
    """A grid of the data that starts at 500 ms: at 2 000 m/s its top is
    500 m down, whatever its velocity is read as — an interval velocity's
    top was at depth 0, 500 m above an average velocity's."""
    np = pytest.importorskip("numpy")
    t = np.array([500.0, 1000.0, 1500.0, 2000.0, 2500.0])
    v = np.full((4, 1, 1), 2000.0, np.float32)
    ztop, at, replaced = vc.read_velocities(v, t, reading, 0.0)
    cube = vc.Cube(0, 1, 0, 1, 1, 1, t, v, ztop=ztop, average=reading == "average", at=at)
    assert replaced == 0
    for twt in (0.0, 500.0, 1500.0, 2500.0):
        assert float(cube.to_depth([0.5], [0.5], [twt])[0]) == pytest.approx(twt, abs=1e-3)


def test_a_grid_read_as_it_is_carries_its_first_velocity_up_to_time_zero():
    np = pytest.importorskip("numpy")
    nan = float("nan")
    t = np.array([500.0, 1000.0, 1500.0])
    v = np.array([[[1500.0]], [[nan]]], dtype=np.float32)
    ztop, at, replaced = vc.read_velocities(v, t, "interval", 0.5)
    assert (at, replaced) == (0.5, 1) and float(ztop[0, 0]) == pytest.approx(375.0)
    cube = vc.Cube(0, 1, 0, 1, 1, 1, t, v, ztop=ztop, at=at)
    assert float(cube.to_depth([0.5], [0.5], [1500.0])[0]) == pytest.approx(375.0 + 2 * 375.0)
    # from time 0 on, nothing to carry
    assert vc.read_velocities(np.full((1, 1, 1), 2000.0), [0.0, 500.0], "interval", 0.5)[0] is None
