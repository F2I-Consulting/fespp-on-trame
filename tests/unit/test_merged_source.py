"""engine/sources/merged_source — the readers' collections as one: every row of
the joined tree must point at ITS dataset, whichever reader delivered it."""
import pytest

dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
core = pytest.importorskip("vtkmodules.vtkCommonCore")

from fespp_on_trame.engine.sources import merged_source  # noqa: E402


def _collection(names, root="data"):
    """A reader's output: one partitioned dataset per name, holding a poly
    data of as many points as its place plus one, under folder/props/leaf."""
    pdc = dm.vtkPartitionedDataSetCollection()
    asm = dm.vtkDataAssembly()
    asm.SetRootNodeName(root)
    for i, name in enumerate(names):
        points = dm.vtkPolyData()
        pts = core.vtkPoints()
        for _ in range(len(name)):
            pts.InsertNextPoint(0.0, 0.0, 0.0)
        points.SetPoints(pts)
        pds = dm.vtkPartitionedDataSet()
        pds.SetPartition(0, points)
        pdc.SetPartitionedDataSet(i, pds)
        folder = asm.AddNode(f"_gridfolder_{name}", 0)
        asm.SetAttribute(folder, "label", f"{name} & <its> \"title\"")
        leaf = asm.AddNode(f"_{name}", asm.AddNode(f"_propsfolder_{name}", folder))
        asm.AddDataSetIndex(leaf, i)
    pdc.SetDataAssembly(asm)
    return pdc


class _Algorithm:
    def __init__(self, inputs):
        self.inputs = inputs
        self.out = dm.vtkPartitionedDataSetCollection()

    def GetOutputDataObject(self, _port):
        return self.out

    def GetNumberOfInputConnections(self, _port):
        return len(self.inputs)

    def GetInputDataObject(self, _port, index):
        return self.inputs[index]


def _path(name):
    return f"/data/_gridfolder_{name}/_propsfolder_{name}/_{name}"


def _points_at(pdc, name):
    """How many points the dataset the row of `name` points at holds."""
    asm = pdc.GetDataAssembly()
    node = asm.GetFirstNodeByPath(_path(name))
    assert node > 0, f"no row for {name}"
    indices = list(asm.GetDataSetIndices(node, False))
    assert len(indices) == 1, f"{name}: {indices}"
    return pdc.GetPartitionedDataSet(indices[0]).GetPartition(0).GetNumberOfPoints()


def test_one_reader_passes_through():
    reader = _collection(["a", "bb"])
    algorithm = _Algorithm([reader])
    merged_source.apply(algorithm)
    assert algorithm.out.GetNumberOfPartitionedDataSets() == 2
    assert _points_at(algorithm.out, "bb") == 2


def test_every_row_of_two_readers_points_at_its_own_dataset():
    files = _collection(["a", "bb", "ccc"])
    store = _collection(["dddd", "eeeee", "ffffff", "ggggggg"])
    algorithm = _Algorithm([files, store])
    merged_source.apply(algorithm)
    out = algorithm.out
    assert out.GetNumberOfPartitionedDataSets() == 7
    for name in ("a", "bb", "ccc", "dddd", "eeeee", "ffffff", "ggggggg"):
        assert _points_at(out, name) == len(name), name
    asm = out.GetDataAssembly()
    assert asm.GetRootNodeName() == "data"
    tops = [asm.GetNodeName(n) for n in asm.GetChildNodes(0, False)]
    assert tops == [f"_gridfolder_{n}" for n in ("a", "bb", "ccc", "dddd", "eeeee", "ffffff", "ggggggg")]
    nodes = [0] + list(asm.GetChildNodes(0, True))
    assert len(nodes) == len(set(nodes)) == 1 + 3 * 7
    folder = asm.GetFirstNodeByPath("/data/_gridfolder_eeeee")
    assert asm.GetAttributeOrDefault(folder, "label", "") == "eeeee & <its> \"title\""


def test_three_readers_and_a_reader_with_no_data():
    first = _collection(["a"])
    empty = _collection([])
    last = _collection(["bb", "ccc"])
    algorithm = _Algorithm([first, empty, last])
    merged_source.apply(algorithm)
    for name in ("a", "bb", "ccc"):
        assert _points_at(algorithm.out, name) == len(name), name


def test_the_readers_own_trees_are_left_as_they_were():
    files, store = _collection(["a", "bb"]), _collection(["ccc", "dddd"])
    merged_source.apply(_Algorithm([files, store]))
    assert _points_at(store, "ccc") == 3
    assert _points_at(store, "dddd") == 4
