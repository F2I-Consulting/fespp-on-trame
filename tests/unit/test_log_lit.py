"""engine/log_lit: the samples highlighted of the logs a 3D view draws, as one
geometry — on a graph a line from the hole to the curve and a dot on the
curve, on a tube the sample's ring a little wider."""
import numpy as np
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from vtkmodules.vtkCommonCore import vtkIdTypeArray, vtkPoints
from vtkmodules.vtkCommonDataModel import vtkPolyData

from fespp_on_trame.engine import log_lit
from fespp_on_trame.engine.log_track import LOG_SAMPLE


def _samples(values):
    a = vtkIdTypeArray()
    a.SetName(LOG_SAMPLE)
    for v in values:
        a.InsertNextValue(int(v))
    return a


def _strip(n=5, off=10.0):
    """A graph's strip as the plugin makes it: the hole's n points down Z,
    then the curve's n, `off` east of them; a trajectory station (-1) between
    samples 1 and 2."""
    hole = [(0.0, 0.0, -10.0 * k) for k in range(n)]
    pts = vtkPoints()
    for p in hole + [(off, 0.0, z) for _x, _y, z in hole]:
        pts.InsertNextPoint(*p)
    said = [0, 1, -1, 2, 3][:n]
    data = vtkPolyData()
    data.SetPoints(pts)
    data.GetPointData().AddArray(_samples(said + said))
    return data


def _tube(rings=3, sides=6, radius=2.0):
    """A tube's rings, `sides` points around each sample."""
    pts, said = [], []
    for s in range(rings):
        for k in range(sides):
            a = 2 * np.pi * k / sides
            pts.append((radius * np.cos(a), radius * np.sin(a), -10.0 * s))
            said.append(s)
    data = vtkPolyData()
    p = vtkPoints()
    p.SetData(numpy_to_vtk(np.asarray(pts, dtype=float), deep=True))
    data.SetPoints(p)
    data.GetPointData().AddArray(_samples(said))
    return data


def _lines(data):
    """Each line cell's points."""
    out = []
    for c in range(data.GetNumberOfCells()):
        cell = data.GetCell(c)
        if cell.GetCellDimension() == 1:
            ids = cell.GetPointIds()
            out.append([data.GetPoint(ids.GetId(i)) for i in range(ids.GetNumberOfIds())])
    return out


def test_a_graph_s_sample_lit_runs_from_the_hole_to_the_curve():
    data, counted = log_lit.geometry({"/log": [2]}, {"/log": _strip()}, {})
    assert counted == {"lines": 1, "rings": 0}
    (line,) = _lines(data)
    # sample 2 is the strip's fourth node (a station stands before it)
    assert line == [(0.0, 0.0, -30.0), (10.0, 0.0, -30.0)]
    assert data.GetNumberOfVerts() == 1, "a dot on the curve"


def test_a_station_is_never_lit():
    data, counted = log_lit.geometry({"/log": [-1, 7]}, {"/log": _strip()}, {})
    assert counted["lines"] == 0 and data.GetNumberOfPoints() == 0


def test_several_rows_light_as_many_lines_in_one_geometry():
    data, counted = log_lit.geometry({"/log": [0, 1, 3]}, {"/log": _strip()}, {})
    assert counted["lines"] == 3
    assert data.GetNumberOfLines() == 3 and data.GetNumberOfVerts() == 3


def test_the_vertical_exaggeration_is_drawn():
    data, _c = log_lit.geometry({"/log": [3]}, {"/log": _strip()}, {}, zs=2.0)
    assert _lines(data)[0][0][2] == -80.0


def test_a_tube_s_sample_lit_is_its_ring_a_little_wider():
    data, counted = log_lit.geometry({"/log": [1]}, {}, {"/log": [_tube()]})
    assert counted == {"lines": 0, "rings": 1}
    (ring,) = _lines(data)
    assert len(ring) == 7 and ring[0] == ring[-1], "closed"
    radius = [np.hypot(x, y) for x, y, _z in ring]
    assert np.allclose(radius, 2.0 * log_lit.RING)
    assert all(z == -10.0 for _x, _y, z in ring)


def test_a_graph_wins_over_a_tube_of_the_same_log():
    _d, counted = log_lit.geometry({"/log": [1]}, {"/log": _strip()}, {"/log": [_tube()]})
    assert counted == {"lines": 1, "rings": 0}


def test_a_graph_not_made_yet_lights_nothing():
    _d, counted = log_lit.geometry({"/log": [1]}, {"/log": None}, {"/log": [_tube()]})
    assert counted == {"lines": 0, "rings": 0}


def test_most_samples_a_log():
    lit = {"/log": list(range(10))}
    _d, counted = log_lit.geometry(lit, {}, {"/log": [_tube(rings=10)]}, most=4)
    assert counted["rings"] == 4




def test_nothing_lit_is_an_empty_geometry():
    data, counted = log_lit.geometry({}, {}, {})
    assert counted == {"lines": 0, "rings": 0} and data.GetNumberOfPoints() == 0
    assert vtk_to_numpy(data.GetPoints().GetData()).size == 0 if data.GetPoints() is not None else True
