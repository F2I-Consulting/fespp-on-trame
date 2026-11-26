"""engine/derived_arrays: the computed properties attached as arrays of their
grid's blocks by one pass-through filter (slice 4b of the overhaul)."""
import numpy as np
import pytest

dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
from fespp_on_trame.engine import derived_arrays  # noqa: E402
from fespp_on_trame.engine.derived_arrays import DerivedArrays  # noqa: E402


def _image(nx, ny, nz):
    img = dm.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    return img


def _collection():
    """/data/grid owns pds 0 (two partitions: 4 + 2 cells),
    /data/well owns pds 1 (one partition: 1 cell)."""
    pdc = dm.vtkPartitionedDataSetCollection()
    grid = dm.vtkPartitionedDataSet()
    grid.SetPartition(0, _image(3, 3, 2))
    grid.SetPartition(1, _image(3, 2, 2))
    well = dm.vtkPartitionedDataSet()
    well.SetPartition(0, _image(2, 2, 2))
    pdc.SetPartitionedDataSet(0, grid)
    pdc.SetPartitionedDataSet(1, well)
    asm = dm.vtkDataAssembly()
    asm.SetRootNodeName("data")
    g = asm.AddNode("grid")
    w = asm.AddNode("well")
    asm.AddDataSetIndex(g, 0)
    asm.AddDataSetIndex(w, 1)
    pdc.SetDataAssembly(asm)
    return pdc


class _Algo:
    """The two calls the filter's script makes on `self`."""
    def __init__(self, inp):
        self.inp = inp
        self.out = dm.vtkPartitionedDataSetCollection()

    def GetInputDataObject(self, _port, _conn):
        return self.inp

    def GetOutputDataObject(self, _port):
        return self.out


def _run(store, pdc):
    algo = _Algo(pdc)
    derived_arrays.apply(algo, store.key)
    return algo.out


def _part(pdc, i, j):
    return pdc.GetPartitionedDataSet(i).GetPartition(j)


def test_empty_store_passes_the_collection_through():
    pdc = _collection()
    out = _run(DerivedArrays(), pdc)
    assert out.GetNumberOfPartitionedDataSets() == 2
    assert [out.GetPartitionedDataSet(i).GetNumberOfPartitions() for i in (0, 1)] == [2, 1]
    assert _part(out, 0, 1).GetNumberOfCells() == 2
    assert out.GetDataAssembly().GetFirstNodeByPath("/data/grid") >= 0


def test_values_split_over_the_grid_partitions_in_order():
    pdc = _collection()
    store = DerivedArrays()
    store.put("derived__x", "/data/grid", [1, 2, 3, 4, 5, 6])
    out = _run(store, pdc)
    from vtkmodules.util.numpy_support import vtk_to_numpy
    a0 = _part(out, 0, 0).GetCellData().GetArray("derived__x")
    a1 = _part(out, 0, 1).GetCellData().GetArray("derived__x")
    assert list(vtk_to_numpy(a0)) == [1, 2, 3, 4]
    assert list(vtk_to_numpy(a1)) == [5, 6]
    # the reader's blocks never get the array; other grids are untouched
    assert _part(pdc, 0, 0).GetCellData().GetArray("derived__x") is None
    assert _part(out, 1, 0).GetCellData().GetArray("derived__x") is None
    assert store.notes == []


def test_a_size_mismatch_is_skipped_with_a_note():
    pdc = _collection()
    store = DerivedArrays()
    store.put("derived__x", "/data/grid", [1, 2, 3])
    out = _run(store, pdc)
    assert _part(out, 0, 0).GetCellData().GetArray("derived__x") is None
    assert len(store.notes) == 1 and "3 values for 6 cells" in store.notes[0]


def test_two_arrays_of_one_grid_share_one_copy_and_drop_removes():
    pdc = _collection()
    store = DerivedArrays()
    store.put("derived__a", "/data/grid", np.arange(6))
    store.put("derived__b", "/data/grid", np.arange(6) * 2.0)
    out = _run(store, pdc)
    cd = _part(out, 0, 0).GetCellData()
    assert cd.GetArray("derived__a") is not None and cd.GetArray("derived__b") is not None
    store.drop("derived__a")
    out = _run(store, pdc)
    cd = _part(out, 0, 0).GetCellData()
    assert cd.GetArray("derived__a") is None and cd.GetArray("derived__b") is not None
    assert store.names() == ["derived__b"]


def test_a_grid_the_reader_did_not_load_is_ignored():
    pdc = _collection()
    store = DerivedArrays()
    store.put("derived__x", "/data/other", [1.0])
    out = _run(store, pdc)
    assert _part(out, 0, 0).GetCellData().GetArray("derived__x") is None
    assert store.notes == []


def test_a_change_rewrites_every_filter_script():
    class _Filter:
        Script = ""
        runs = 0

        def UpdatePipeline(self):
            self.runs += 1

    store = DerivedArrays()
    f = _Filter()
    store._filters["1"] = f
    store.put("derived__x", "/data/grid", [1.0])
    first = f.Script
    assert store.key in first
    # run at once: the colour range is read off its output right after
    assert f.runs == 1
    store.drop("derived__x")
    assert f.Script != first and f.runs == 2


def test_each_session_store_has_its_own_key():
    a, b = DerivedArrays(), DerivedArrays()
    assert a.key != b.key
    pdc = _collection()
    a.put("derived__x", "/data/grid", np.arange(6))
    out = _run(b, pdc)
    assert _part(out, 0, 0).GetCellData().GetArray("derived__x") is None


def test_display_source_of_a_plain_provider_is_its_source():
    class _Plain:
        def get_source(self):
            return "reader"

    class _Active(_Plain):
        def get_display_source(self):
            return "filter"

    assert derived_arrays.display_source_of(_Plain()) == "reader"
    assert derived_arrays.display_source_of(_Active()) == "filter"
    assert derived_arrays.display_source_of(None) is None


def test_two_grids_may_carry_a_formula_of_the_same_name():
    pdc = _collection()
    store = DerivedArrays()
    store.put("derived__x", "/data/grid", np.arange(6))
    store.put("derived__x", "/data/well", [42.0])
    out = _run(store, pdc)
    from vtkmodules.util.numpy_support import vtk_to_numpy
    assert list(vtk_to_numpy(_part(out, 1, 0).GetCellData().GetArray("derived__x"))) == [42.0]
    assert _part(out, 0, 1).GetCellData().GetArray("derived__x") is not None
    store.drop("derived__x", "/data/well")
    out = _run(store, pdc)
    assert _part(out, 1, 0).GetCellData().GetArray("derived__x") is None
    assert store.has("derived__x", "/data/grid") and not store.has("derived__x", "/data/well")
