"""Tests for the bins of a histogram (fespp_on_trame.engine.distribution_dispatch).

`_apply_norm` must accept `widths` as a plain list: the discrete path
passes one, and an int times a list is list repetition, not a product.
Also covered: diverging bar colours for a difference.
"""
import numpy as np
import pytest

from fespp_on_trame.engine.distribution_dispatch import (
    _NORM_COUNT, _NORM_DENSITY, _NORM_PROBABILITY, _apply_norm,
)


class TestApplyNorm:
    def test_density_with_a_plain_list_of_widths(self):
        out = _apply_norm(np.array([2.0, 3.0]), 5, [1.0, 1.0], _NORM_DENSITY)
        assert list(out) == pytest.approx([0.4, 0.6])

    def test_density_with_bin_widths(self):
        out = _apply_norm(np.array([2.0, 3.0]), 5, np.array([0.5, 0.5]), _NORM_DENSITY)
        assert list(out) == pytest.approx([0.8, 1.2])

    def test_probability_and_count(self):
        c = np.array([2.0, 3.0])
        assert list(_apply_norm(c, 5, [1.0, 1.0], _NORM_PROBABILITY)) == pytest.approx([0.4, 0.6])
        assert list(_apply_norm(c, 5, [1.0, 1.0], _NORM_COUNT)) == [2.0, 3.0]

    def test_empty_total_passes_through(self):
        c = np.array([0.0])
        assert _apply_norm(c, 0, [1.0], _NORM_DENSITY) is c


# ---- a difference reads on a diverging scale --------------------------------

from fespp_on_trame.engine import distribution_dispatch as dd
from fespp_on_trame.engine.utils.color_palette import (
    DIVERGING_NEG, DIVERGING_POS, DIVERGING_ZERO)


def test_diverging_colors_by_bin_side():
    centers = [-1.5, -0.5, 0.0, 0.5, 1.5]
    widths = [1.0] * 5
    assert dd.diverging_colors(centers, widths) == [
        DIVERGING_NEG, DIVERGING_NEG, DIVERGING_ZERO, DIVERGING_POS, DIVERGING_POS]
    # a bin ending exactly at zero is below; one starting there is above
    assert dd.diverging_colors([-0.25, 0.25], [0.5, 0.5]) == [DIVERGING_NEG, DIVERGING_POS]
    assert dd.diverging_colors([], []) == []
    line = dd.zero_line()
    assert line["x0"] == 0 and line["x1"] == 0 and line["yref"] == "paper"
