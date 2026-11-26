"""Sampling a grid property along a trajectory
(fespp_on_trame.engine.trajectory_sampling).

The geometry is pure Python; the cell lookup needs VTK (pvpython ships it),
and those tests skip where it is missing.
"""
import math

import pytest

from fespp_on_trame.engine.trajectory_sampling import (
    chord_md, resample, sample_grid,
)


class TestChordMd:
    def test_cumulative_chord_length(self):
        st = chord_md([(0, 0, 0), (3, 4, 0), (3, 4, -10)])
        assert [s[3] for s in st] == [0.0, 5.0, 15.0]

    def test_single_point(self):
        assert chord_md([(1, 2, 3)]) == [(1.0, 2.0, 3.0, 0.0)]


class TestResample:
    def test_regular_step_and_last_station(self):
        st = chord_md([(0, 0, 0), (0, 0, -10)])
        pts = resample(st, 4.0)
        assert [p[3] for p in pts] == [0.0, 4.0, 8.0, 10.0]
        assert pts[1][2] == pytest.approx(-4.0)      # linear along the leg

    def test_bend_is_followed(self):
        # a horizontal leg after a vertical one: x moves only past md 10
        st = chord_md([(0, 0, 0), (0, 0, -10), (5, 0, -10)])
        pts = resample(st, 5.0)
        assert [(round(p[0], 6), round(p[2], 6), p[3]) for p in pts] == [
            (0.0, 0.0, 0.0), (0.0, -5.0, 5.0), (0.0, -10.0, 10.0),
            (5.0, -10.0, 15.0)]

    def test_step_larger_than_the_hole(self):
        st = chord_md([(0, 0, 0), (0, 0, -3)])
        assert [p[3] for p in resample(st, 100.0)] == [0.0, 3.0]

    def test_degenerate_input(self):
        assert resample([], 1.0) == []
        st = chord_md([(0, 0, 0), (0, 0, -3)])
        assert resample(st, 0) == st


def _two_hexes():
    """Two unit cubes stacked along -Z: cell 0 spans z ∈ [-1, 0], cell 1
    z ∈ [-2, -1]; both over x, y ∈ [0, 1]."""
    vtk_dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    vtk_core = pytest.importorskip("vtkmodules.vtkCommonCore")
    pts = vtk_core.vtkPoints()
    for z in (0.0, -1.0, -2.0):
        for y in (0.0, 1.0):
            for x in (0.0, 1.0):
                pts.InsertNextPoint(x, y, z)
    grid = vtk_dm.vtkUnstructuredGrid()
    grid.SetPoints(pts)
    for layer in (0, 1):
        b = layer * 4
        ids = [b + 0, b + 1, b + 3, b + 2, b + 4, b + 5, b + 7, b + 6]
        grid.InsertNextCell(vtk_dm.VTK_HEXAHEDRON, 8, ids)
    return grid


class TestSampleGrid:
    def test_value_of_the_containing_cell(self):
        grid = _two_hexes()
        pts = [(0.5, 0.5, -0.5, 0.5), (0.5, 0.5, -1.5, 1.5)]
        # no md: the panel keeps a well with a synthetic log on TVD
        assert sample_grid(grid, [10.0, 20.0], pts) == [
            [10.0, 0.5, None], [20.0, 1.5, None]]

    def test_outside_and_blanked_are_none(self):
        grid = _two_hexes()
        pts = [(5.0, 5.0, -0.5, 0.0), (0.5, 0.5, -1.5, 1.5)]
        out = sample_grid(grid, [10.0, math.nan], pts)
        assert out == [[None, 0.5, None], [None, 1.5, None]]


class TestStoredMd:
    """The trajectory block carries the file's measured depth as the "MD"
    point array when the file stores one: the stations then ride on it and
    the samples carry it, so the well stays drawn on MD beside its logs;
    without it the chord length paces the sampling and the md slot stays
    None."""

    def _polyline(self, with_md, n_md=None, nan=False):
        vtk_core = pytest.importorskip("vtkmodules.vtkCommonCore")
        vtk_dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
        pts = vtk_core.vtkPoints()
        # three stations, the polyline walking them in reverse id order
        for p in ((0, 0, -20), (0, 0, -10), (0, 0, 0)):
            pts.InsertNextPoint(*p)
        pd = vtk_dm.vtkPolyData()
        pd.SetPoints(pts)
        lines = vtk_dm.vtkCellArray()
        lines.InsertNextCell(3, [2, 1, 0])
        pd.SetLines(lines)
        if with_md:
            arr = vtk_core.vtkDoubleArray()
            arr.SetName("MD")
            vals = [1030.0, 1015.0, 1000.0][: (n_md or 3)]
            if nan:
                vals[1] = float("nan")
            for v in vals:
                arr.InsertNextValue(v)
            pd.GetPointData().AddArray(arr)
        return pd

    def _stations(self, monkeypatch, pd):
        from fespp_on_trame.engine import trajectory_sampling as ts
        monkeypatch.setattr(ts.welllog_dispatch, "_fetch_block",
                            lambda shared, path: pd)
        return ts.stations_and_md(object(), "traj")

    def test_the_stored_md_rides_on_the_stations(self, monkeypatch):
        stations, true_md = self._stations(monkeypatch, self._polyline(True))
        assert true_md is True
        assert [s[3] for s in stations] == [1000.0, 1015.0, 1030.0]
        assert [s[2] for s in stations] == [0.0, -10.0, -20.0]

    def test_without_stored_md_the_chord_paces(self, monkeypatch):
        stations, true_md = self._stations(monkeypatch, self._polyline(False))
        assert true_md is False
        assert [s[3] for s in stations] == [0.0, 10.0, 20.0]

    def test_an_md_array_that_does_not_pair_or_has_a_gap_is_ignored(self, monkeypatch):
        _s, true_md = self._stations(monkeypatch, self._polyline(True, n_md=2))
        assert true_md is False
        _s, true_md = self._stations(monkeypatch, self._polyline(True, nan=True))
        assert true_md is False

    def test_the_samples_carry_the_md_only_when_it_is_stored(self):
        grid = _two_hexes()
        pts = [(0.5, 0.5, -0.5, 1000.5), (0.5, 0.5, -1.5, 1001.5)]
        assert sample_grid(grid, [10.0, 20.0], pts, with_md=True) == [
            [10.0, 0.5, 1000.5], [20.0, 1.5, 1001.5]]
        assert sample_grid(grid, [10.0, 20.0], pts) == [
            [10.0, 0.5, None], [20.0, 1.5, None]]
