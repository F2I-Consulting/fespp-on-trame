"""The Geometry slicer in X/Y/Z (engine/sources/xyz_crop, engine/slicer_card):
boxes in the scene's coordinates, never rounded, a cut at one value a box
flat on its axis; a crop chains a Threshold for each axis its box narrows
(29/10)."""
import pytest

from fespp_on_trame.engine import slicer_card as sc
from fespp_on_trame.engine.sources import xyz_crop

EXT = {"x": [0.0, 1000.0], "y": [5000.0, 7000.0], "z": [-3000.0, -2500.0]}
XYZ = ("x", "y", "z")
BOUNDS = [0.0, 1000.0, 5000.0, 7000.0, -3000.0, -2500.0]


def test_coordinate_boxes_keep_the_values_and_a_cut_is_flat_on_its_axis():
    card = sc.empty(XYZ)
    box = sc.new_box(card, EXT, mode=sc.SLICE)
    assert sc.new_cut(card, box, "x", EXT["x"])["at"] == 500.0
    assert sc.boxes(card, EXT, XYZ, whole=False) == [[[500.0, 500.0], [5000.0, 7000.0], [-3000.0, -2500.0]]]
    box["cuts"]["x"][0]["cmp"] = sc.BELOW
    assert sc.boxes(card, EXT, XYZ, whole=False) == [[[0.0, 500.0], [5000.0, 7000.0], [-3000.0, -2500.0]]]


def test_the_scene_is_cut_by_the_boxes_that_narrow_it():
    # the Geometry slicer on the whole scene (29/10): one mark for all the
    # boxes; a box holding the whole scene holds it for the union
    from fespp_on_trame.engine.blockscope import scene_crop as cut
    whole = [[0.0, 1000.0], [5000.0, 7000.0], [-3000.0, -2500.0]]
    box = [[200.0, 1000.0], [6000.0, 6000.0], [-3000.0, -2600.0]]
    assert cut.cutting_boxes([box], BOUNDS) == [box]
    assert cut.cutting_boxes([box, [[0.0, 500.0], *whole[1:]]], BOUNDS) == [box, [[0.0, 500.0], *whole[1:]]]
    assert cut.cutting_boxes([box, whole], BOUNDS) == []
    assert cut.cutting_boxes([], BOUNDS) == []
    assert cut.holds_whole(whole, BOUNDS) and not cut.holds_whole(box, BOUNDS)


def test_the_scene_cut_keeps_the_cells_a_box_meets():
    # the cut's rule (scene_crop.mask_of), on cells given by their extents
    # (field data, axis-major)
    import numpy as np
    from fespp_on_trame.engine.blockscope import scene_crop as cut

    class _Arr:
        def __init__(self, a):
            self.a = a

        def GetNumberOfTuples(self):
            return len(self.a)

    cells = np.array([[0, 10, 0, 10, 0, 10],       # meets the box
                      [20, 30, 0, 10, 0, 10],      # beside it in X
                      [5, 6, 0, 10, 50, 60]])      # above it in Z
    boxes = [[[8.0, 25.0], [0.0, 1.0], [0.0, 1.0]]]

    class _FieldData:
        def GetArray(self, name):
            return _Arr(cells.T.ravel()) if name == cut.CELLBOX else None

    class _Ds:
        def GetNumberOfCells(self):
            return len(cells)

        def GetFieldData(self):
            return _FieldData()

    import types
    from unittest import mock
    fake_np_support = types.SimpleNamespace(vtk_to_numpy=lambda arr: arr.a)
    with mock.patch.dict("sys.modules", {"vtkmodules.util.numpy_support": fake_np_support,
                                         "vtkmodules": types.ModuleType("vtkmodules"),
                                         "vtkmodules.util": types.ModuleType("vtkmodules.util")}):
        keep = cut.mask_of(_Ds(), boxes)
    assert keep.tolist() == [True, True, False]


def test_a_horizon_and_an_ijk_grid_are_cut_by_the_scene():
    # a 2D grid (a horizon, vtkStructuredGrid) has no cell array to read:
    # its cells' extents come off its point grid (the PO, 29/10 evening: a
    # horizon ticked on a cut scene showed whole); an IJK grid is drawn as
    # the polydata of its exposed faces, read off its face table
    np = pytest.importorskip("numpy")
    dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    from vtkmodules.vtkCommonCore import vtkPoints
    from fespp_on_trame.engine.blockscope import scene_crop as cut
    # the horizon: 3 x 2 points at z 0, two quads, x 0..1 and 1..2
    sg = dm.vtkStructuredGrid()
    sg.SetDimensions(3, 2, 1)
    pts = vtkPoints()
    for y in (0.0, 1.0):
        for x in (0.0, 1.0, 2.0):
            pts.InsertNextPoint(x, y, 0.0)
    sg.SetPoints(pts)
    box = cut._extents_of_grid(sg)
    assert box.shape == (6, 2) and box[0].tolist() == [0.0, 1.0] and box[1].tolist() == [1.0, 2.0]
    right = [[[1.5, 3.0], [-1.0, 2.0], [-1.0, 1.0]]]
    horizon = cut._prep_leaf(sg, {}, {})
    assert cut.mask_of(horizon, right).tolist() == [False, True]
    kept = cut._cut_leaf(horizon, right)
    assert kept.IsA("vtkPolyData") and kept.GetNumberOfCells() == 1
    assert kept.GetCellData().GetArray(cut.ORIGINAL_IDS).GetValue(0) == 1
    # on the points it uses, the right quad's four
    assert kept.GetNumberOfPoints() == 4 and [kept.GetCell(0).GetPointId(k) for k in range(4)] == [0, 1, 3, 2]
    # a well: a poly-line split into segments, the ones the box meets kept
    well = dm.vtkPolyData()
    wpts = vtkPoints()
    for x in (0.0, 1.0, 2.0, 3.0):
        wpts.InsertNextPoint(x, 0.0, 0.0)
    well.SetPoints(wpts)
    lines = dm.vtkCellArray()
    lines.InsertNextCell(4, [0, 1, 2, 3])
    well.SetLines(lines)
    segments = cut._prep_leaf(well, {}, {})
    assert segments.GetNumberOfCells() == 3
    kept = cut._cut_leaf(segments, right)
    assert kept.GetNumberOfLines() == 2 and kept.GetNumberOfCells() == 2
    assert kept.GetNumberOfPoints() == 3 and [kept.GetCell(1).GetPointId(k) for k in range(2)] == [1, 2]
    assert kept.GetCellData().GetArray(cut.ORIGINAL_IDS).GetValue(1) == 0
    # the grid: two hexahedra side by side in I, one face shared
    pts = vtkPoints()
    for z in (0.0, 1.0):
        for y in (0.0, 1.0):
            for x in (0.0, 1.0, 2.0):
                pts.InsertNextPoint(x, y, z)
    hexes = np.array([[0, 1, 4, 3, 6, 7, 10, 9], [1, 2, 5, 4, 7, 8, 11, 10]])
    meta, match, lone, cell_map = cut._face_table(hexes, (2, 1, 1))
    assert meta.tolist()[:5] == [2, 1, 1, 1, 0] and match.tolist() == [1]
    assert len(lone) == 2 * 10 and cell_map.tolist() == [0, 1]
    # the same two, the cells of a 3 x 1 x 1 grid whose middle cell is
    # hidden: no face shared, every face lone
    holed = cut._face_table(hexes, (3, 1, 1), np.array([0, 2]))
    assert holed[1].tolist() == [0, 0] and len(holed[2]) == 2 * 12 and holed[3].tolist() == [0, -1, 1]
    ug = dm.vtkUnstructuredGrid()
    ug.SetPoints(pts)
    ug.Allocate(2)
    for h in hexes:
        ug.InsertNextCell(cut.VTK_HEXAHEDRON, 8, [int(i) for i in h])
    grid = cut._prep_leaf(ug, {}, {})
    assert grid.GetFieldData().GetArray(cut.CELLBOX) is not None
    for name, values in ((cut.FACE_META, meta), (cut.FACE_MATCH, match), (cut.FACE_LONE, lone),
                         (cut.FACE_CELLS, cell_map)):
        cut._add_field(grid, name, values)
    left = [[[-1.0, 0.5], [-1.0, 2.0], [-1.0, 2.0]]]
    faces = cut._cut_leaf(grid, left)
    assert faces.IsA("vtkPolyData") and faces.GetNumberOfCells() == 6
    ids = faces.GetCellData().GetArray(cut.ORIGINAL_IDS)
    assert {int(ids.GetValue(i)) for i in range(6)} == {0}
    whole = cut._cut_leaf(grid, [[[-1.0, 3.0], [-1.0, 2.0], [-1.0, 2.0]]])
    assert whole.GetNumberOfCells() == 10
    # on the points the faces use only: the kept cell's eight
    assert faces.GetNumberOfPoints() == 8 and whole.GetNumberOfPoints() == 12


def test_a_scene_card_follows_the_scene_as_it_grows():
    # the wells read after the grid: the card keeping everything keeps it
    card = sc.empty(XYZ)
    sc.defaults(card, EXT)
    card["boxes"][0]["ranges"]["x"][0]["high"] = 600.0
    grown = dict(EXT, z=[-3000.0, 35.0], x=[-50.0, 1000.0])
    sc.follow_extents(card, EXT, grown)
    ranges = card["boxes"][0]["ranges"]
    assert [ranges["x"][0]["low"], ranges["x"][0]["high"]] == [-50.0, 600.0]
    assert [ranges["z"][0]["low"], ranges["z"][0]["high"]] == [-3000.0, 35.0]
    assert sc.boxes(card, grown, XYZ, whole=False)[0][2] == [-3000.0, 35.0]


def test_a_crop_says_the_axes_its_box_narrows():
    whole = [[0.0, 1000.0], [5000.0, 7000.0], [-3000.0, -2500.0]]
    assert xyz_crop.narrows(whole, BOUNDS) == ()
    assert xyz_crop.narrows([[500.0, 500.0], [5000.0, 7000.0], [-2800.0, -2500.0]], BOUNDS) == (0, 2)


def test_an_object_crop_hands_its_box_to_the_cut_as_it_is():
    # the scene cut's filters on the object (30/10): the box in the scene's
    # coordinates, negative elevations as they are (VTK's continuous cell
    # range ignored the lower bound on them — the PO: "the min does not
    # work"), written only when it changes
    class _Cut:
        Boxes = "[]"

    crop = xyz_crop.CoordCrop.__new__(xyz_crop.CoordCrop)
    crop._cut, crop._text, crop.axes, crop._subset = _Cut(), None, (), None
    box = [[0.0, 1000.0], [5000.0, 7000.0], [-2800.0, -2600.0]]
    crop.set_box(box, BOUNDS)
    assert crop._cut.Boxes == xyz_crop.boxes_text(box)
    assert '-2800.0' in crop._cut.Boxes and crop.axes == (2,)
    crop._cut.Boxes = "untouched"
    crop.set_box(box, BOUNDS)
    assert crop._cut.Boxes == "untouched"


def test_a_surface_crop_cuts_its_i_and_j_before_its_x_y_z():
    # a surface on a 2D grid: [i, j, x, y, z] boxes, I and J on the subset
    # (a cut at one index the row of cells after it, K left flat), X, Y and
    # Z on the cut
    class _Proxy:
        def __init__(self, **props):
            self.__dict__.update(props)

    class _SMProxy:
        def GetProperty(self, name):
            return object() if name == "VOI" else None

    crop = xyz_crop.CoordCrop.__new__(xyz_crop.CoordCrop)
    crop._cut, crop._text, crop.axes = _Proxy(Boxes="[]"), None, ()
    crop._subset, crop._ij, crop._voi = _Proxy(VOI=[0, 99, 0, 49, 0, 0], SMProxy=_SMProxy()), [0, 99, 0, 49, 0, 0], None
    xyz = [[0.0, 1000.0], [5000.0, 7000.0], [-2800.0, -2600.0]]
    crop.set_box([[10, 20], [0, 49]] + xyz, BOUNDS)
    assert crop._subset.VOI == [10, 20, 0, 49, 0, 0]
    assert crop._cut.Boxes == xyz_crop.boxes_text(xyz) and crop.axes == (2,)
    crop.set_box([[30, 30], [49, 49]] + xyz, BOUNDS)
    assert crop._subset.VOI == [30, 31, 48, 49, 0, 0]


def test_one_object_cut_alone_takes_the_class_of_what_the_cut_makes():
    # the cut of HOD (a horizon, cut alone by the object slicer) kept the
    # whole horizon: its quads could not go into a structured grid output
    # (30/10); the output class follows the stage, the result is converted
    pytest.importorskip("numpy")
    dm = pytest.importorskip("vtkmodules.vtkCommonDataModel")
    from vtkmodules.vtkCommonCore import vtkPoints
    from fespp_on_trame.engine.blockscope import scene_crop as cut
    assert cut.output_class("cut", "vtkStructuredGrid") == "vtkPolyData"
    assert cut.output_class("prep", "vtkExplicitStructuredGrid") == "vtkUnstructuredGrid"
    assert cut.output_class("cut", "vtkUnstructuredGrid") == "vtkUnstructuredGrid"
    sg = dm.vtkStructuredGrid()
    sg.SetDimensions(3, 2, 1)
    pts = vtkPoints()
    for y in (0.0, 1.0):
        for x in (0.0, 1.0, 2.0):
            pts.InsertNextPoint(x, y, -10.0)
    sg.SetPoints(pts)
    prepared = dm.vtkStructuredGrid()
    cut.prep_into(sg, prepared)
    out = dm.vtkPolyData()
    cut.cut_into(prepared, out, [[[1.5, 3.0], [-1.0, 2.0], [-11.0, -9.0]]])
    assert out.GetNumberOfCells() == 1 and out.GetNumberOfPoints() == 4
    # an unstructured grid cut into an unstructured grid output, a polydata
    # result converted
    assert cut._as_class(out, "vtkUnstructuredGrid").IsA("vtkUnstructuredGrid")
