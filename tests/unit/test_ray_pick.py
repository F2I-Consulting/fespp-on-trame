"""engine/ray_pick: picking a line or point set, which has no width.

A ray from the pointer meets a trajectory when it passes within PICK_PX
pixels of one of its segments, measured at the segment's depth; the nearest
to the eye wins; the cell id is the polydata's own (vertices first, then
lines). A cell locator's sub-millimetre tolerance would almost never meet a
zero-width line, hence a reach measured in pixels."""
import pytest

vtk = pytest.importorskip("vtkmodules.vtkCommonDataModel")
from vtkmodules.vtkCommonCore import vtkPoints  # noqa: E402

from fespp_on_trame.engine import ray_pick  # noqa: E402


def _polyline(*pts, verts=()):
    """A polydata: one polyline through `pts`, then each of `verts` as a
    vertex cell of its own."""
    points = vtkPoints()
    for p in list(pts) + list(verts):
        points.InsertNextPoint(*p)
    pd = vtk.vtkPolyData()
    pd.SetPoints(points)
    if verts:
        va = vtk.vtkCellArray()
        for k in range(len(verts)):
            va.InsertNextCell(1)
            va.InsertCellPoint(len(pts) + k)
        pd.SetVerts(va)
    if pts:
        la = vtk.vtkCellArray()
        la.InsertNextCell(len(pts))
        for k in range(len(pts)):
            la.InsertCellPoint(k)
        pd.SetLines(la)
    return pd


# a vertical well at x = y = 0, from 0 down to -1000
WELL = ((0.0, 0.0, 0.0), (0.0, 0.0, -500.0), (0.0, 0.0, -1000.0))
# a horizontal ray along +y at depth -700, from y = -1000 to y = +1000,
# passing `gap` metres from the well; a pixel is 1 m wide all along
def _ray(gap):
    return [gap, -1000.0, -700.0], [0.0, 2000.0, 0.0], ([1.0, 0.0, 0.0], [0.0, 0.0, 0.0])


def test_a_ray_three_pixels_from_the_well_names_it():
    p1, u, px = _ray(3.0)
    hit = ray_pick.near_lines(_polyline(*WELL), p1, u, px)
    assert hit is not None
    s, point, cell = hit
    assert s == pytest.approx(0.5)
    assert point == pytest.approx([0.0, 0.0, -700.0])
    assert cell == 0


def test_ten_pixels_away_is_not_on_it():
    p1, u, px = _ray(10.0)
    assert ray_pick.near_lines(_polyline(*WELL), p1, u, px) is None


def test_a_pixel_is_wider_far_away():
    # the same 10 m gap is within reach when a pixel there is 3 m wide
    p1, u, _ = _ray(10.0)
    assert ray_pick.near_lines(_polyline(*WELL), p1, u, ([3.0, 0.0, 0.0], [0.0, 0.0, 0.0])) is not None


def test_the_nearest_to_the_eye_wins():
    # a second well behind the first along the ray (y = +400)
    behind = ((0.0, 400.0, 0.0), (0.0, 400.0, -1000.0))
    from vtkmodules.vtkFiltersCore import vtkAppendPolyData
    app = vtkAppendPolyData()
    app.AddInputData(_polyline(*behind))
    app.AddInputData(_polyline(*WELL))
    app.Update()
    p1, u, px = _ray(2.0)
    s, point, _cell = ray_pick.near_lines(app.GetOutput(), p1, u, px)
    assert point[1] == pytest.approx(0.0)        # the well at y = 0, not 400
    assert s == pytest.approx(0.5)


def test_points_are_met_too_and_cells_count_vertices_first():
    pd = _polyline(*WELL, verts=((0.0, 200.0, -700.0),))
    p1, u, px = _ray(0.5)
    s, point, cell = ray_pick.near_lines(pd, p1, u, px)
    # the ray starts at y = -1000 and runs along +y: the well (y = 0) is met
    # before the vertex (y = 200)
    assert point == pytest.approx([0.0, 0.0, -700.0])
    assert cell == 1                               # the line, after the vertex
    # a ray that only passes the vertex
    s, point, cell = ray_pick.near_lines(pd, [0.0, 200.0, 0.0], [0.0, 0.0, -1400.0],
                                         ([1.0, 0.0, 0.0], [0.0, 0.0, 0.0]))
    assert cell == 0 and point == pytest.approx([0.0, 200.0, -700.0])


def test_surfaces_and_empty_sets_are_left_to_the_locator():
    assert ray_pick.near_lines(None, [0, 0, 0], [1, 0, 0], ([1, 0, 0], [0, 0, 0])) is None
    assert ray_pick.near_lines(vtk.vtkPolyData(), [0, 0, 0], [1, 0, 0], ([1, 0, 0], [0, 0, 0])) is None
    assert ray_pick.near_lines(vtk.vtkUnstructuredGrid(), [0, 0, 0], [1, 0, 0],
                               ([1, 0, 0], [0, 0, 0])) is None


def test_the_reach_is_measured_as_drawn_under_a_z_exaggeration():
    # the well drawn with Z x 25: a ray, in the data's space, passing 2.4 m
    # under a horizontal line is 60 pixels under it on screen
    line = ((-500.0, 0.0, -697.6), (500.0, 0.0, -697.6))
    p1, u, px = _ray(0.0)
    assert ray_pick.near_lines(_polyline(*line), p1, u, px, scale=(1.0, 1.0, 25.0)) is None
    # 0.12 m under it: 3 pixels, on it — the point handed back is the data's
    p1[2] = -697.72
    s, point, _cell = ray_pick.near_lines(_polyline(*line), p1, u, px, scale=(1.0, 1.0, 25.0))
    assert s == pytest.approx(0.5) and point == pytest.approx([0.0, 0.0, -697.6])
