"""A point set is selected by its points (the PO, 20/10: a rectangle on part
of a point set took all of it — FESPP draws one as a single poly-vertex
cell). Covered: which blocks are point clouds, the held selection keeping
point ids for them, and the split into cell and point ids that the
ParaView selection is built from."""
import pytest

from fespp_on_trame.app.scene import selection_sources as ss
from fespp_on_trame.app.scene.selection import Selection

vtk_dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
vtk_core = pytest.importorskip("vtkmodules.vtkCommonCore")


def _points(n):
    pts = vtk_core.vtkPoints()
    for i in range(n):
        pts.InsertNextPoint(float(i), 0.0, 0.0)
    return pts


def _poly_vertex(n):
    """What FESPP makes of a point set: one poly-vertex holding every point."""
    pd = vtk_dm.vtkPolyData()
    pd.SetPoints(_points(n))
    verts = vtk_dm.vtkCellArray()
    verts.InsertNextCell(n, list(range(n)))
    pd.SetVerts(verts)
    return pd


def _vertices(n):
    pd = vtk_dm.vtkPolyData()
    pd.SetPoints(_points(n))
    verts = vtk_dm.vtkCellArray()
    for i in range(n):
        verts.InsertNextCell(1, [i])
    pd.SetVerts(verts)
    return pd


def _polyline(n):
    pd = vtk_dm.vtkPolyData()
    pd.SetPoints(_points(n))
    lines = vtk_dm.vtkCellArray()
    lines.InsertNextCell(n, list(range(n)))
    pd.SetLines(lines)
    return pd


def test_only_a_poly_vertex_point_set_is_a_point_cloud():
    assert ss.is_point_cloud(_poly_vertex(5))
    # one vertex per point: its cells pick points already
    assert not ss.is_point_cloud(_vertices(5))
    # a wellbore's line, a grid: their cells are what is picked
    assert not ss.is_point_cloud(_polyline(5))
    assert not ss.is_point_cloud(vtk_dm.vtkUnstructuredGrid())
    assert not ss.is_point_cloud(None)


def test_a_selection_splits_into_cells_and_points():
    by_flat = {3: [7, 8], 5: [0, 2, 4]}
    cells, points = ss.split(by_flat, {5})
    assert cells == [3, 0, 7, 3, 0, 8]
    assert points == [5, 0, 0, 5, 0, 2, 5, 0, 4]
    assert ss.split(by_flat, set()) == (ss.triplets(by_flat), [])


def test_the_held_selection_knows_its_point_blocks():
    sel = Selection()
    sel.hold("v", {3: [7], 5: [0, 2]}, pick=True, points={5, 9})
    # a flat the selection does not hold is no point block of it
    assert sel.points_of("v") == {5} and sel.points_of("v", pick=True) == {5}
    sel.hold("v", {3: [1]})
    assert sel.points_of("v") == set() and sel.points_of("v", pick=True) == {5}
    sel.set_pick("v", {3: [1]})     # a right-click: cells, no points
    assert sel.points_of("v", pick=True) == set()
    sel.hold("v", {5: [1]}, pick=True, points={5})
    sel.drop("v")
    assert sel.points_of("v") == set() and sel.points_of("v", pick=True) == set()
