"""engine/blockscope/assembly_index: the assembly of the reader's collection,
asked in one place — datasets of a path, their flat indices, the path owning
a picked flat index (slice 2 of the overhaul)."""
from fespp_on_trame.engine.blockscope.assembly_index import AssemblyIndex


class _DS:
    def __init__(self, name):
        self.name = name


class _PDS:
    def __init__(self, parts):
        self._parts = parts

    def GetNumberOfPartitions(self):
        return len(self._parts)

    def GetPartition(self, j):
        return self._parts[j]


class _Asm:
    """/data
         ├── _gridfolder_g   (owns nothing)
         │    └── _propsfolder_g
         │         └── _g    owns pds 0
         └── _well           owns pds 1
              └── _traj      owns pds 2"""
    def __init__(self):
        self.paths = {0: "/data", 1: "/data/_gridfolder_g",
                      2: "/data/_gridfolder_g/_propsfolder_g",
                      3: "/data/_gridfolder_g/_propsfolder_g/_g",
                      4: "/data/_well", 5: "/data/_well/_traj"}
        self.children = {0: [1, 4], 1: [2], 2: [3], 3: [], 4: [5], 5: []}
        self.own = {3: [0], 4: [1], 5: [2]}

    def GetRootNode(self):
        return 0

    def GetNodePath(self, n):
        return self.paths[n]

    def GetNodeName(self, n):
        return self.paths[n].rsplit("/", 1)[-1]

    def GetChildNodes(self, n, _recursive=False):
        return list(self.children[n])

    def GetDataSetIndices(self, n, _subtree=False):
        return list(self.own.get(n, []))


class _PDC:
    def __init__(self):
        self.mtime = 1
        self.pds = [_PDS([_DS("g0"), _DS("g1")]), _PDS([_DS("well")]), _PDS([_DS("traj")])]
        self.asm = _Asm()

    def GetMTime(self):
        return self.mtime

    def GetNumberOfPartitionedDataSets(self):
        return len(self.pds)

    def GetPartitionedDataSet(self, i):
        return self.pds[i]

    def GetDataAssembly(self):
        return self.asm


GRID = "/data/_gridfolder_g/_propsfolder_g/_g"


def test_the_flat_numbering_is_paraview_s():
    pdc = _PDC()
    idx = AssemblyIndex(lambda: pdc)
    # 0 the collection; pds 0 at 1 (partitions 2, 3); pds 1 at 4 (5); pds 2 at 6 (7)
    assert idx.flat_indices(GRID) == [2, 3]
    assert idx.flat_indices("/data/_well", subtree=False) == [5]
    assert idx.flat_indices("/data/_well") == [5, 7]
    assert idx.flat_indices("/data/_gridfolder_g") == [2, 3]   # a folder: its subtree


def test_datasets_and_the_owner_of_a_picked_flat_index():
    pdc = _PDC()
    idx = AssemblyIndex(lambda: pdc)
    assert [(d.name, f) for d, f in idx.datasets(GRID)] == [("g0", 2), ("g1", 3)]
    assert idx.dataset(7).name == "traj" and idx.dataset(99) is None
    assert idx.selector_for_flat(3) == GRID
    assert idx.selector_for_flat(7) == "/data/_well/_traj"      # the deepest owner
    assert idx.selector_for_flat(99) is None


def test_a_data_path_is_found_where_the_old_index_never_found_one():
    pdc = _PDC()
    idx = AssemblyIndex(lambda: pdc)
    assert idx.selector_for(GRID) == GRID
    assert idx.selector_for("/data/nowhere") is None
    assert GRID in idx and idx.node_name(GRID) == "_g"


def test_the_index_follows_a_new_or_modified_collection():
    box = {"pdc": _PDC()}
    idx = AssemblyIndex(lambda: box["pdc"])
    assert idx.flat_indices(GRID) == [2, 3]
    box["pdc"].pds[0] = _PDS([_DS("g0")])          # one partition now
    box["pdc"].mtime += 1                          # ... and the collection says so
    assert idx.flat_indices(GRID) == [2]
    assert idx.flat_indices("/data/_well") == [4, 6]
    box["pdc"] = None                              # nothing loaded
    assert idx.flat_indices(GRID) == [] and idx.selector_for(GRID) is None


def _vtk_collection():
    """Two partitioned datasets: the first with a grid and an empty slot, the
    second with one grid — flats 1 [2 3] 4 [5]."""
    from vtkmodules.vtkCommonDataModel import (
        vtkPartitionedDataSet, vtkPartitionedDataSetCollection, vtkUnstructuredGrid)
    first, second = vtkPartitionedDataSet(), vtkPartitionedDataSet()
    first.SetNumberOfPartitions(2)
    first.SetPartition(0, vtkUnstructuredGrid())
    second.SetPartition(0, vtkUnstructuredGrid())
    pdc = vtkPartitionedDataSetCollection()
    pdc.SetPartitionedDataSet(0, first)
    pdc.SetPartitionedDataSet(1, second)
    return pdc


def test_the_leaves_of_a_collection_in_the_index_numbering():
    from fespp_on_trame.engine.blockscope.assembly_index import leaves
    pdc = _vtk_collection()
    every = dict(leaves(pdc, skip_empty=False))
    assert sorted(every) == [2, 3, 5]
    assert every[3] is None and every[2] is not None and every[5] is not None
    assert [f for f, _ds in leaves(pdc)] == [2, 5]
    idx = AssemblyIndex(lambda: pdc)
    idx.refresh()
    assert sorted(idx._leaf) == sorted(every)


def test_the_inner_dataset_of_a_collection():
    from vtkmodules.vtkCommonDataModel import (
        vtkPartitionedDataSet, vtkPartitionedDataSetCollection, vtkUnstructuredGrid)
    from fespp_on_trame.engine.blockscope.assembly_index import inner
    pdc = _vtk_collection()
    first = pdc.GetPartitionedDataSet(0).GetPartitionAsDataObject(0)
    assert inner(pdc) is first
    grid = vtkUnstructuredGrid()
    assert inner(grid) is grid
    assert inner(None) is None
    empty = vtkPartitionedDataSetCollection()
    empty.SetPartitionedDataSet(0, vtkPartitionedDataSet())
    assert inner(empty) is empty
