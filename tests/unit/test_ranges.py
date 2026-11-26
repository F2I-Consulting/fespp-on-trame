"""engine/ranges: one rule for an array's range and its distinct values."""
import numpy as np
import pytest

pytest.importorskip("vtkmodules.vtkCommonCore")
from vtkmodules.util.numpy_support import numpy_to_vtk  # noqa: E402
from fespp_on_trame.engine import ranges  # noqa: E402


def _arr(values, name="a"):
    a = numpy_to_vtk(np.asarray(values), deep=1)
    a.SetName(name)
    return a


def test_the_range_skips_hidden_and_non_finite_values():
    v = _arr([0.0, 2.0, np.nan, 5.0, 9.0])
    ghost = _arr(np.array([32, 0, 0, 0, 32], dtype=np.uint8), "vtkGhostType")
    assert ranges.finite_range(v, ghost) == (2.0, 5.0)
    assert ranges.finite_range(v) == (0.0, 9.0)


def test_a_vector_s_range_is_its_magnitude():
    v = _arr(np.array([[3.0, 4.0], [0.0, 1.0]]))
    assert ranges.finite_range(v) == (1.0, 5.0)


def test_a_constant_range_is_opened_for_the_bar():
    assert ranges.widen_for_bar(2.0, 5.0) == (2.0, 5.0)
    assert ranges.widen_for_bar(1.0, 1.0) == (0.5, 1.5)
    assert ranges.widen_for_bar(1000.0, 1000.0) == (995.0, 1005.0)


def test_distinct_values_and_the_cap():
    v = _arr([3.0, 1.0, np.nan, 3.0, 7.0])
    assert ranges.distinct(v) == [1.0, 3.0, 7.0]
    assert ranges.distinct(v, cap=2) is None
    assert ranges.distinct(_arr(np.array([4, 4, 2], dtype=np.int32))) == [2.0, 4.0]
