"""The scene's domain conversion stage (engine/blockscope/domain_convert):
the velocity model handed by its key, the points of a leaf converted with their
sign kept, a collection converted leaf by leaf."""
import pytest

from fespp_on_trame.engine.blockscope import domain_convert as dc
from fespp_on_trame.engine.time_depth import Law


def _cube(law=None):
    vc = pytest.importorskip("fespp_on_trame.engine.velocity_model")
    return vc.Cube.build([(None, None, law or Law([(1000.0, 1000.0), (3000.0, 2000.0)]))])   # 2 000 then 4 000 m/s


def _polyline(zs):
    dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    core = pytest.importorskip("vtkmodules.vtkCommonCore")
    pts = core.vtkPoints()
    for i, z in enumerate(zs):
        pts.InsertNextPoint(float(i), 0.0, float(z))
    poly = dm.vtkPolyData()
    poly.SetPoints(pts)
    return poly


def test_the_registry_holds_the_latest_cube_only():
    pytest.importorskip("numpy")
    a, b = _cube(), _cube(Law([(500.0, 500.0)]))
    dc.register_cube("tdl:1", a)
    assert dc.CUBES == {"tdl:1": a}
    dc.register_cube("tdl:2", b)
    assert dc.CUBES == {"tdl:2": b}
    dc.register_cube("", None)
    assert dc.CUBES == {}


def test_a_leaf_converted_keeps_its_sign_and_its_cells():
    pytest.importorskip("numpy")
    leaf = _polyline([-1500.0, -2500.0, 0.0])          # two-way times, negative downward
    out = dc.convert_points(leaf, _cube(), dc.DEPTH)
    assert out is not leaf
    zs = [out.GetPoint(i)[2] for i in range(out.GetNumberOfPoints())]
    assert zs == [-2000.0, -4000.0, 0.0]
    # the source is untouched, x and y too
    assert leaf.GetPoint(0)[2] == -1500.0 and out.GetPoint(1)[0] == 1.0
    back = dc.convert_points(out, _cube(), dc.TIME)
    assert [back.GetPoint(i)[2] for i in range(3)] == [-1500.0, -2500.0, 0.0]


def test_no_cube_or_no_points_hands_the_leaf_back():
    pytest.importorskip("numpy")
    leaf = _polyline([-1500.0])
    assert dc.convert_points(leaf, None, dc.DEPTH) is leaf
    dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    assert dc.convert_points(dm.vtkPolyData(), _cube(), dc.DEPTH).GetNumberOfPoints() == 0


def test_a_collection_is_converted_leaf_by_leaf_through_the_key():
    pytest.importorskip("numpy")
    dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    src = dm.vtkPartitionedDataSetCollection()
    src.SetNumberOfPartitionedDataSets(2)
    src.SetPartition(0, 0, _polyline([-1000.0]))
    src.SetPartition(1, 0, _polyline([-1000.0]))
    flats = [it.GetCurrentFlatIndex() for it, _ds in dc.scene_crop._leaves(src)]
    assert len(flats) == 2
    dst = dm.vtkPartitionedDataSetCollection()
    # 1 000 ms two-way at 4 000 m/s is 2 000 m: the second leaf only
    dc.register_cube("tdl:9", _cube(Law([(2000.0, 1000.0)])))
    dc.convert_into(src, dst, [flats[1]], "tdl:9", dc.DEPTH)
    assert dst.GetPartition(0, 0).GetPoint(0)[2] == -1000.0
    assert dst.GetPartition(1, 0).GetPoint(0)[2] == -2000.0
    assert src.GetPartition(1, 0).GetPoint(0)[2] == -1000.0
    # an unknown key converts nothing
    dc.convert_into(src, dst, [flats[1]], "tdl:gone", dc.DEPTH)
    assert dst.GetPartition(1, 0).GetPoint(0)[2] == -1000.0
    dc.register_cube("", None)
