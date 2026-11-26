"""engine/extent: the objects whose points all sit at one place, which a
store can serve (ADME served the Volve grid with zero coordinates, 12/10)
and which load, show as visible, and draw nothing. The load names them;
the camera is not framed on them (app/views/camera.py)."""
from fespp_on_trame.engine import extent


def test_a_box_without_size_is_flat_and_an_empty_dataset_is_not():
    assert extent.is_flat((420000.0, 420000.0, 6470000.0, 6470000.0, 0.0, 0.0), 1454979)
    # a real grid
    assert not extent.is_flat((431199.1, 439420.9, 6475531.0, 6481320.5, -3734.4, -2684.7), 1454979)
    # one zero-size axis is a flat surface, not a point: it draws
    assert not extent.is_flat((431199.1, 439420.9, 6475531.0, 6481320.5, -3000.0, -3000.0), 1216)
    # no points: an unread property or a grid still loading, nothing to say
    assert not extent.is_flat((420000.0, 420000.0, 6470000.0, 6470000.0, 0.0, 0.0), 0)
    assert not extent.is_flat(None, 12)


def test_the_note_names_the_objects_and_says_why_the_camera_stayed():
    assert extent.note([]) == ""
    one = extent.note(["Volve_SGrid"])
    assert one.startswith("“Volve_SGrid” has every point at one place")
    assert "nothing to draw" in one and "camera stays" in one
    many = extent.note(["a", "b", "c", "d"])
    assert "and others" in many and " have " in many


def test_no_extent_paths_reads_the_collection_in_process():
    """A tiny collection built here: one node whose dataset is a single
    repeated point, one whose dataset has an extent, one without points.
    (`vtkmodules`, not `vtk`: the unit tests run with `vtk` and `paraview`
    mocked away, the real modules come from the wheel the harness installs.)"""
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkDataAssembly, vtkPartitionedDataSetCollection, vtkPolyData
    pdc = vtkPartitionedDataSetCollection()
    asm = vtkDataAssembly()
    asm.Initialize()
    pdc.SetDataAssembly(asm)

    def dataset(points):
        pts = vtkPoints()
        for p in points:
            pts.InsertNextPoint(*p)
        poly = vtkPolyData()
        poly.SetPoints(pts)
        return poly

    flat = dataset([(1.0, 2.0, 3.0)] * 4)
    wide = dataset([(0.0, 0.0, 0.0), (10.0, 5.0, -2.0)])
    empty = dataset([])
    paths = {}
    for i, (name, ds) in enumerate((("_flat", flat), ("_wide", wide), ("_empty", empty))):
        pdc.SetPartition(i, 0, ds)
        nid = asm.AddNode(name, 0)
        asm.SetAttribute(nid, "title", name.strip("_").title())
        asm.AddDataSetIndex(nid, i)
        paths[name] = asm.GetNodePath(nid)      # "/<root>/_flat", as the app's paths are
    found = extent.no_extent_paths(pdc, [paths["_flat"], paths["_wide"], paths["_empty"], "/nowhere/_unknown"])
    assert found == [(paths["_flat"], "Flat")]
    assert extent.no_extent_paths(None, [paths["_flat"]]) == []
