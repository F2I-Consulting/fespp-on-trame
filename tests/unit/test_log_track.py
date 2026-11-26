"""engine/log_track: a well log as the plugin's block holds it — its hole, its
values and its gaps, read as a table of samples — and a first width for its
graph. The graph itself is the plugin's (vtkEnergisticsWellSymbols, tested in
FESPP's Plugin/Testing/Python/TestWellSymbols.py)."""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("vtkmodules.vtkCommonDataModel")
from vtkmodules.util.numpy_support import numpy_to_vtk  # noqa: E402
from vtkmodules.vtkCommonCore import vtkIdTypeArray, vtkPoints  # noqa: E402
from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData  # noqa: E402

from fespp_on_trame.engine import log_track  # noqa: E402

SIDES = 10


def test_the_marker_chips_skip_a_view_without_the_filter():
    pieces = {"view_1": None,
              "view_2": {"marker_chips": {"/a": "#ff0000", "/b": "#00ff00"}},
              "view_3": {"marker_chips": {"/a": "#0000ff"}},
              "view_4": {}}
    assert log_track.marker_chips(pieces) == {"/a": "#ff0000", "/b": "#00ff00"}
    assert log_track.marker_chips({"view_1": None}) == {}
    assert log_track.marker_chips(None) == {}


def _tube(centres, values, gaps=0, name="AI"):
    """A log channel's block as the plugin makes it: a ring of SIDES points
    per frame node wearing its value, SIDES strips along the hole."""
    ring = np.array([[np.cos(a), np.sin(a), 0.0] for a in np.linspace(0, 2 * np.pi, SIDES, endpoint=False)]) * 5.0
    pts = np.concatenate([c + ring for c in np.asarray(centres, float)])
    tube = vtkPolyData()
    points = vtkPoints()
    points.SetData(numpy_to_vtk(pts, deep=True))
    tube.SetPoints(points)
    strips = vtkCellArray()
    for s in range(SIDES):
        strips.InsertNextCell(len(centres))
        for i in range(len(centres)):
            strips.InsertCellPoint(i * SIDES + s)
    tube.SetStrips(strips)
    worn = numpy_to_vtk(np.repeat(np.asarray(values, float), SIDES), deep=True)
    worn.SetName(name)
    tube.GetPointData().AddArray(worn)
    count = vtkIdTypeArray()
    count.SetName(name + "_nanCount")
    count.InsertNextValue(gaps)
    tube.GetFieldData().AddArray(count)
    return tube


VERTICAL = [(100.0, 200.0, -z) for z in (1000.0, 1010.0, 1020.0, 1030.0)]


def test_the_rings_give_the_hole_the_values_and_the_gaps():
    centres, values, gap = log_track.rings(_tube(VERTICAL, [0.2, -0.0, -0.1, 0.0], gaps=1), "AI")
    assert centres == pytest.approx(np.array(VERTICAL))
    assert list(values) == [0.2, 0.0, -0.1, 0.0]
    # the negative zero is the node without a value; the plain zero is a value
    assert list(gap) == [False, True, False, False]
    assert log_track.rings(_tube(VERTICAL, [1, 2, 3, 4]), "Nope") is None


def test_a_log_read_by_its_samples():
    from vtkmodules.vtkCommonCore import vtkDoubleArray
    tube = _tube(VERTICAL, [0.2, -0.0, -0.1, 0.0], gaps=1)
    md = vtkDoubleArray()
    md.SetName("MD")
    for depth in (1000.0, 1010.0, 1020.0, 1030.0):
        md.InsertNextValue(depth)
    tube.GetFieldData().AddArray(md)
    centres, values, depths = log_track.samples(tube, "AI")
    # one row per node of the frame, not one per point of its tube; no value where the log holds none
    assert centres == pytest.approx(np.array(VERTICAL)) and list(depths) == [1000.0, 1010.0, 1020.0, 1030.0]
    assert values[0] == 0.2 and np.isnan(values[1]) and values[2] == -0.1 and values[3] == 0.0
    # without the plugin's measured depths: none given
    assert log_track.samples(_tube(VERTICAL, [1, 2, 3, 4]), "AI")[2] is None
    assert log_track.samples(_tube(VERTICAL, [1, 2, 3, 4]), "Nope") is None


def test_a_frame_read_by_its_samples_is_one_row_per_node():
    md = np.array([1000.0, 1010.0, 1020.0, 1030.0])
    centres = np.array(VERTICAL)
    ai = (centres, np.array([0.2, np.nan, -0.1, 0.0]), md)
    phi = (centres, np.array([0.1, 0.2, 0.3, np.nan]), md)
    got_centres, got_md, cols = log_track.frame_table([("AI", ai), ("PHI", phi), ("GR", None)])
    assert got_centres == pytest.approx(centres) and list(got_md) == list(md)
    assert [name for name, _v in cols] == ["AI", "PHI", "GR"]
    assert cols[1][1][2] == 0.3 and np.isnan(cols[0][1][1])
    # a log not read: a column with no value, the frame's rows kept
    assert len(cols[2][1]) == 4 and np.isnan(cols[2][1]).all()
    # a log on other nodes than the frame's: no value rather than misplaced ones
    odd = (centres[:2], np.array([1.0, 2.0]), md[:2])
    assert np.isnan(log_track.frame_table([("AI", ai), ("ODD", odd)])[2][1][1]).all()
    # the measured depths from any log that has them
    assert list(log_track.frame_table([("A", (centres, ai[1], None)), ("B", phi)])[1]) == list(md)
    assert log_track.frame_table([("GR", None)]) is None and log_track.frame_table([]) is None


def test_a_log_summed_up_on_its_samples():
    md = [1000.0, 1010.0, 1020.0, 1030.0]
    assert log_track.log_summary([np.nan, 0.2, 0.5, np.nan], md) == [2.0, 1010.0, 1020.0, 0.2, 0.5]
    # no measured depth: its depths unknown, its values still summed up
    got = log_track.log_summary([0.1, 0.4], None)
    assert got[0] == 2.0 and np.isnan(got[1]) and np.isnan(got[2]) and got[3:] == [0.1, 0.4]
    # a log with no value at all
    none = log_track.log_summary([np.nan, np.nan], md[:2])
    assert none[0] == 0.0 and all(np.isnan(x) for x in none[1:])


def test_a_first_width_from_the_holes():
    # the largest hole's bounding box: 300 East, 400 down — a diagonal of 500
    holes = [np.array([(0.0, 0.0, 0.0), (300.0, 0.0, -400.0)]), np.array([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)])]
    assert log_track.first_width(holes) == pytest.approx(log_track.WIDTH_SHARE * 500.0)
    assert log_track.first_width([]) == 1.0


def test_a_station_of_the_trajectory_reads_as_its_nearest_sample():
    # the plugin's filter marks each point with the sample it stands for, -1 for a station (drawing only)
    tube = _tube(VERTICAL, [1.0, 2.0, 3.0, 4.0])
    said = vtkIdTypeArray()
    said.SetName(log_track.LOG_SAMPLE)
    for value in (0, -1, -1, 1, -1, 2):
        said.InsertNextValue(value)
    data = vtkPolyData()
    data.GetPointData().AddArray(said)
    assert log_track.real_point(data, 0) == 0 and log_track.real_point(data, 3) == 3
    assert log_track.real_point(data, 1) == 0 and log_track.real_point(data, 2) == 3
    assert log_track.real_point(data, 4) == 3 or log_track.real_point(data, 4) == 5
    # a block that says nothing of it: the point itself
    assert log_track.real_point(tube, 7) == 7


def test_graphs_face_the_screen_again_at_rest_only():
    from fespp_on_trame.engine.log_track import faces_again
    east, north = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0)), ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
    assert faces_again(True, east, north, False)            # turned, at rest: laid again
    assert not faces_again(True, east, north, True)         # a drag's frame: kept as laid
    assert not faces_again(True, north, north, False)       # not turned
    assert not faces_again(False, east, north, False)       # no graph faces the screen
    assert not faces_again(True, east, None, False)         # a camera with no frame
    assert faces_again(True, None, north, False)            # never laid yet
