"""Tests for engine.nan_mask: the Calculator expression that hides a grid's
NaN cells so their neighbours' faces show.

The face counts are the point: 54 faces is the skin of a 3x3x3 grid; with
its top-centre cell gone the skin gains the five faces the hole shows and
loses the cell's own top, 58 in all."""
import numpy as np
import pytest

from fespp_on_trame.engine import nan_mask

TOP_CENTRE = 1 + 3 * 1 + 9 * 2          # (i, j, k) = (1, 1, 2)
BOTTOM_CORNER = 0                       # (0, 0, 0)


def test_expression_quotes_the_name_and_ors_the_bit_once():
    assert nan_mask.expression("p", False) == '32*("p" != "p")'
    fn = nan_mask.expression("Net-to.gross (v/v)", True)
    assert fn == ('vtkGhostType + 32*("Net-to.gross (v/v)" != "Net-to.gross (v/v)")'
                  '*(1 - (floor(vtkGhostType/32) % 2))')


def test_an_unusable_name_is_refused_not_mangled():
    assert nan_mask.expression('say "hi"', True) is None
    assert nan_mask.expression("", True) is None
    assert nan_mask.calculator_settings('a"b', False) is None


def test_codes_at_opacity_zero_are_hidden_as_nan_cells_are():
    """A property painted by code whose reader put codes at opacity 0: the
    same mask, one term per code, sorted and once each; nothing to hide is
    no mask at all."""
    assert (nan_mask.expression("p", False, nan=False, codes=(2, 0, 2.0))
            == '32*(("p" == 0) + ("p" == 2))')
    assert (nan_mask.expression("p", False, codes=(2.5,))
            == '32*(("p" != "p") + ("p" == 2.5))')
    assert nan_mask.expression("p", True, nan=False, codes=()) is None
    assert nan_mask.calculator_settings("p", True, nan=False) is None


def test_calculator_settings_write_the_ghost_array_on_cells():
    s = nan_mask.calculator_settings("p", True)
    assert s["AttributeType"] == "Cell Data"
    assert s["ResultArrayName"] == "vtkGhostType"
    assert s["ResultArrayType"] == "Unsigned Char"
    assert s["Function"] == nan_mask.expression("p", True)


# --- the expression's effect, through VTK's own calculator -----------------

vtk_dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy  # noqa: E402
from vtkmodules.util.vtkConstants import VTK_UNSIGNED_CHAR  # noqa: E402
from vtkmodules.vtkFiltersCore import (  # noqa: E402
    vtkArrayCalculator,
    vtkImageDataToExplicitStructuredGrid,
)
from vtkmodules.vtkFiltersGeometry import vtkGeometryFilter  # noqa: E402


def _grid(nan_at=(), dead=(), name="p"):
    img = vtk_dm.vtkImageData()
    img.SetDimensions(4, 4, 4)
    conv = vtkImageDataToExplicitStructuredGrid()
    conv.SetInputData(img)
    conv.Update()
    esg = conv.GetOutput()
    esg.ComputeFacesConnectivityFlagsArray()
    v = np.arange(27, dtype=float)
    v[list(nan_at)] = np.nan
    arr = numpy_to_vtk(v, deep=1)
    arr.SetName(name)
    esg.GetCellData().AddArray(arr)
    for c in dead:
        esg.BlankCell(c)                # what FESPP does on dead cells
    return esg


def _mask(grid, name="p", nan=True, codes=()):
    has = grid.GetCellData().GetArray(nan_mask.GHOSTS) is not None
    calc = vtkArrayCalculator()
    calc.SetInputData(grid)
    calc.SetAttributeTypeToCellData()
    # ParaView's Calculator declares every array under its quoted name too;
    # plain VTK needs it said
    calc.AddScalarVariable(f'"{name}"', name, 0)
    if has:
        calc.AddScalarArrayName(nan_mask.GHOSTS)
    calc.SetResultArrayName(nan_mask.GHOSTS)
    calc.SetResultArrayType(VTK_UNSIGNED_CHAR)
    calc.SetFunction(nan_mask.expression(name, has, nan=nan, codes=codes))
    calc.Update()
    return calc.GetOutput()


def _faces(ds):
    g = vtkGeometryFilter()
    g.SetInputData(ds)
    g.Update()
    return g.GetOutput().GetNumberOfCells()


def _hidden(ds):
    a = ds.GetCellData().GetArray(nan_mask.GHOSTS)
    return [] if a is None else np.nonzero(vtk_to_numpy(a) & nan_mask.HIDDEN)[0].tolist()


def test_the_hole_shows_its_neighbours_faces():
    grid = _grid([TOP_CENTRE])
    assert _faces(grid) == 54                          # unmasked: the skin only
    out = _mask(grid)
    assert out.GetClassName() == "vtkExplicitStructuredGrid"
    assert _hidden(out) == [TOP_CENTRE]
    assert _faces(out) == 58


def test_dead_cells_stay_hidden_and_the_input_keeps_its_ghosts():
    grid = _grid([TOP_CENTRE, BOTTOM_CORNER], dead=[BOTTOM_CORNER])
    out = _mask(grid)
    assert _hidden(out) == [BOTTOM_CORNER, TOP_CENTRE]
    assert _hidden(grid) == [BOTTOM_CORNER]            # the shared grid untouched
    # the dead one keeps its bit: 32, not 64
    assert int(vtk_to_numpy(out.GetCellData().GetArray(nan_mask.GHOSTS))[BOTTOM_CORNER]) == 32


def test_no_nan_hides_nothing():
    assert _hidden(_mask(_grid())) == []


def test_a_code_at_opacity_zero_shows_its_neighbours_faces():
    # the values are the cell indices: code 22 is the top-centre cell
    out = _mask(_grid(), nan=False, codes=[float(TOP_CENTRE)])
    assert _hidden(out) == [TOP_CENTRE]
    assert _faces(out) == 58
    # NaN cells and codes together, each hidden once
    out = _mask(_grid([BOTTOM_CORNER]), codes=[float(TOP_CENTRE), 5.0])
    assert _hidden(out) == [BOTTOM_CORNER, 5, TOP_CENTRE]
