"""A well log's gaps: the samples its channel holds no value at.

The plugin writes such a sample as a NEGATIVE zero (a NaN cannot stay in the
array that sets the radius of the tube drawn from it) and counts them in the
field array `<array>_nanCount`. One rule reads them (engine/ranges.no_value):
a counted negative zero is no value, as a NaN; a zero of a log without gaps,
or a positive zero beside the gaps, is a value. The Statistics matrix counts
them as undefined and leaves them out of every figure and of the histogram.
"""
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("vtkmodules.vtkCommonCore")

from vtkmodules.util.numpy_support import numpy_to_vtk  # noqa: E402
from vtkmodules.vtkCommonCore import vtkIdTypeArray, vtkPoints  # noqa: E402
from vtkmodules.vtkCommonDataModel import vtkPolyData  # noqa: E402

from tests.unit.fake_assembly import FakeDataAssembly  # noqa: E402
from fespp_on_trame.engine import cell_weights  # noqa: E402
from fespp_on_trame.engine import compare_dispatch as cd  # noqa: E402
from fespp_on_trame.engine import ranges  # noqa: E402
from fespp_on_trame.engine import welllog_dispatch as wd  # noqa: E402
from fespp_on_trame.engine.tree import Tree  # noqa: E402


def _channel(name, values, gaps=None):
    """A log channel's block as the plugin makes it: one point per frame node
    down the hole, the values on the points and, unless `gaps` is None, how
    many samples it wrote without a value."""
    block = vtkPolyData()
    points = vtkPoints()
    for i in range(len(values)):
        points.InsertNextPoint(0.0, 0.0, -1000.0 - 10.0 * i)
    block.SetPoints(points)
    arr = numpy_to_vtk(np.array(values, dtype=float), deep=True)
    arr.SetName(name)
    block.GetPointData().AddArray(arr)
    if gaps is not None:
        count = vtkIdTypeArray()
        count.SetName(name + "_nanCount")
        count.InsertNextValue(gaps)
        block.GetFieldData().AddArray(count)
    return block


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def test_a_counted_negative_zero_is_no_value_and_any_other_zero_is_one():
    values = np.array([-0.0, 0.0, 2.0, np.nan, np.inf])
    assert ranges.no_value(values, gaps=1).tolist() == [True, False, False, True, True]
    # a block that counted none: its negative zero is a value
    assert ranges.no_value(values, gaps=0).tolist() == [False, False, False, True, True]
    # an integer array holds a value everywhere
    assert not ranges.no_value(np.array([0, -1, 3])).any()


def test_the_count_is_read_on_the_block():
    assert ranges.gap_count(_channel("Facies", [-0.0, 1.0], gaps=1), "Facies") == 1
    assert ranges.gap_count(_channel("Facies", [-0.0, 1.0], gaps=0), "Facies") == 0
    # a block that says nothing (a grid's array), or no block at all
    assert ranges.gap_count(_channel("Facies", [-0.0, 1.0]), "Facies") == 0
    assert ranges.gap_count(None, "Facies") == 0


def test_the_log_samples_follow_the_rule():
    got = wd._ring_samples(_channel("GR", [-0.0, 0.0, 30.0, -0.0], gaps=2), "GR")
    assert [v for v, _tvd, _md in got] == [None, 0.0, 30.0, None]
    assert [tvd for _v, tvd, _md in got] == [1000.0, 1010.0, 1020.0, 1030.0]
    # without a count, a negative zero is a value like any zero
    got = wd._ring_samples(_channel("GR", [-0.0, 30.0], gaps=0), "GR")
    assert [v for v, _tvd, _md in got] == [0.0, 30.0]


# ---------------------------------------------------------------------------
# The Statistics matrix
# ---------------------------------------------------------------------------

def _log_tree():
    """A wellbore, its log frame, a discrete log "Facies" on it."""
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_w", 0, label="55/33-1", title="55/33-1",
                                   type="Wellbore", typeCode="2")
    frame = asm.add_node_with_attrs("_frame", well, label="Frame", title="Well Log Frame",
                                    type="Frame", typeCode="2")
    leaf = asm.add_node_with_attrs("_facies", frame, label="Properties_Facies", title="Facies",
                                   type="DiscreteProperty", typeCode="4", propertyKind="facies")
    return Tree(asm), asm.GetNodePath(leaf)


@pytest.fixture
def log_read(monkeypatch):
    """The log's block, as the shared source hands it over; `block[0]` is the
    block the next read gets."""
    block = [None]
    monkeypatch.setattr(wd, "_fetch_block", lambda _source, _path: block[0])
    monkeypatch.setattr(cell_weights, "weights_for", lambda *a: {"note": ""})
    monkeypatch.setattr(cd, "_category_names", lambda *a: {})
    return block


_STATE = SimpleNamespace(ui_vector_component={}, ui_active_realization_by_array_by_view={},
                         fespp_render_panels=[])
_SOURCES = SimpleNamespace(shared_source=lambda: object())


def _matrix_row(tree, path):
    return cd._row(_STATE, tree, _SOURCES, cd._norm_item({"path": path}))


def test_the_gaps_of_a_log_are_undefined_in_the_statistics(log_read):
    """The negative zeros the plugin counted are no values: the undefined
    count holds them, no figure is computed on them — a facies log whose
    codes run from 1 does not start at 0."""
    tree, path = _log_tree()
    log_read[0] = _channel("Facies", [-0.0, 1.0, 2.0, -0.0, 3.0, 2.0, -0.0], gaps=3)
    m = _matrix_row(tree, path)["metrics"]
    assert (m["Cardinality"], m["NaN_count"]) == (4.0, 3.0)
    assert (m["Minimum"], m["Maximum"]) == (1.0, 3.0)
    assert m["Mean"] == pytest.approx(2.0)


def test_a_zero_of_a_log_is_a_value(log_read):
    """A positive zero beside the gaps is a code, and so is every zero of a
    block that counted no gap."""
    tree, path = _log_tree()
    log_read[0] = _channel("Facies", [-0.0, 0.0, 2.0], gaps=1)
    m = _matrix_row(tree, path)["metrics"]
    assert (m["Cardinality"], m["NaN_count"], m["Minimum"]) == (2.0, 1.0, 0.0)
    log_read[0] = _channel("Facies", [-0.0, 1.0, 2.0], gaps=0)
    m = _matrix_row(tree, path)["metrics"]
    assert (m["Cardinality"], m["NaN_count"], m["Minimum"]) == (3.0, 0.0, 0.0)


def test_the_gaps_of_a_log_are_no_bar_of_its_distribution(log_read):
    tree, path = _log_tree()
    log_read[0] = _channel("Facies", [-0.0, 1.0, 2.0, -0.0, 2.0], gaps=2)
    it = cd._norm_item({"path": path})
    read = cd._row_trace(_STATE, tree, _SOURCES, it, cd._rep_path(tree, path), cd._dist_opts({}))
    assert read["discrete"] and read["codes"] == [1.0, 2.0]
    assert (read["total"], read["kept"]) == (5, 3)
