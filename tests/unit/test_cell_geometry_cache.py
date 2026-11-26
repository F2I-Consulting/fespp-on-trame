"""The cells of a grid are read once, not once per tick.

Reading the volume and centre of every cell takes seconds on a million-cell
grid, so the geometry is cached per representation path and outlives the
weights: the weights are cleared at every change of selection, and that must
not make each property ticked into Compare or Statistics read the whole grid
again. A hit is checked against the dataset's cell and point counts, and an
import drops the cache.
"""
from types import SimpleNamespace

import pytest

from fespp_on_trame.engine import cell_weights, volumetrics_dispatch as vd


class _Dataset:
    def __init__(self, cells, points):
        self._c, self._p = cells, points

    def GetNumberOfCells(self):
        return self._c

    def GetNumberOfPoints(self):
        return self._p


@pytest.fixture
def reads(monkeypatch):
    """`cell_geometry` replaced by a counter that returns a recognisable
    pair; the count is what the test asserts."""
    cell_weights.clear_geometry()
    cell_weights.clear()
    n = SimpleNamespace(calls=0)

    def fake(dataset):
        n.calls += 1
        return ([1.0] * dataset.GetNumberOfCells(), [0.0] * dataset.GetNumberOfCells())

    monkeypatch.setattr(vd, "cell_geometry", fake)
    yield n
    cell_weights.clear_geometry()


def test_the_same_grid_is_read_once(reads):
    ds = _Dataset(926_808, 1_000_000)
    a = cell_weights.geometry_for("/data/grid", ds)
    b = cell_weights.geometry_for("/data/grid", ds)
    assert reads.calls == 1
    assert a == b


def test_clearing_the_weights_keeps_the_geometry(reads):
    ds = _Dataset(8, 27)
    cell_weights.geometry_for("/data/grid", ds)
    cell_weights.clear()  # what every tick does
    cell_weights.geometry_for("/data/grid", ds)
    assert reads.calls == 1


def test_a_new_assembly_drops_the_geometry(reads):
    ds = _Dataset(8, 27)
    cell_weights.geometry_for("/data/grid", ds)
    cell_weights.clear_geometry()  # what an import does
    cell_weights.geometry_for("/data/grid", ds)
    assert reads.calls == 2


def test_a_dataset_with_other_counts_is_read_again(reads):
    cell_weights.geometry_for("/data/grid", _Dataset(8, 27))
    cell_weights.geometry_for("/data/grid", _Dataset(9, 27))
    cell_weights.geometry_for("/data/grid", _Dataset(9, 27))
    assert reads.calls == 2


def test_two_representations_do_not_share_a_read(reads):
    ds = _Dataset(8, 27)
    cell_weights.geometry_for("/data/grid_a", ds)
    cell_weights.geometry_for("/data/grid_b", ds)
    assert reads.calls == 2


def test_without_a_path_nothing_is_cached(reads):
    ds = _Dataset(8, 27)
    cell_weights.geometry_for("", ds)
    cell_weights.geometry_for("", ds)
    assert reads.calls == 2
