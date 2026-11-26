"""Volume-weighted means: the ground truths, derived by hand.

Every number asserted below is computed on paper, with the arithmetic
written out in each docstring. None of them is a snapshot of what the code
returns.
"""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine import cell_weights, stats_dispatch as sd

np = pytest.importorskip("numpy")

NAN = float("nan")


# --- (a) the 2x1x1 grid -----------------------------------------------------

def test_the_volume_weighted_mean_of_two_unequal_cells():
    """A 2x1x1 grid, cell volumes 1 and 9, porosity 0.10 and 0.30.

        arithmetic      = (0.10 + 0.30) / 2                  = 0.20
        volume-weighted = (1*0.10 + 9*0.30) / (1 + 9)
                        = (0.10 + 2.70) / 10 = 2.80 / 10     = 0.28

    The thin cell counts for a tenth, not for a half.
    """
    row = sd._row_stats_from_values([0.10, 0.30], "PORO", volume=[1.0, 9.0])
    assert row["Mean"] == pytest.approx(0.20, abs=1e-15)
    assert row["Mean (V)"] == pytest.approx(0.28, abs=1e-15)
    assert row["weighted_n"] == 2
    assert row["Cardinality"] == 2.0


# --- (a') the pore-volume weight --------------------------------------------

def test_the_pore_volume_weight_is_a_third_distinct_number():
    """Same grid, ntg = [1.0, 0.5], phi = [0.10, 0.30], values = phi.

        pore weights = [1*1.0*0.10, 9*0.5*0.30]     = [0.10, 1.35]
        Mean (PV)    = (0.10*0.10 + 1.35*0.30) / (0.10 + 1.35)
                     = (0.010 + 0.405) / 1.45
                     = 0.415 / 1.45                 = 0.2862068965517241
        Mean = 0.20, Mean (V) = 0.28 — three distinct numbers.
    """
    vol = [1.0, 9.0]
    ntg = [1.0, 0.5]
    phi = [0.10, 0.30]
    pore = [v * g * p for v, g, p in zip(vol, ntg, phi)]
    assert pore == pytest.approx([0.10, 1.35], abs=1e-15)
    row = sd._row_stats_from_values(phi, "PORO", volume=vol, pore_volume=pore)
    assert row["Mean"] == pytest.approx(0.20, abs=1e-15)
    assert row["Mean (V)"] == pytest.approx(0.28, abs=1e-15)
    assert row["Mean (PV)"] == pytest.approx(0.2862068965517241, abs=1e-15)


# --- (b) the blanked cell ---------------------------------------------------

def test_a_blanked_cell_is_out_of_both_the_mean_and_the_weight():
    """b1: volumes [1, 9, nan], values [0.10, 0.30, nan].

        Cardinality = 2 (the third value is not a value)
        Mean        = 0.20
        Mean (V)    = 0.28, weighted_n = 2
    """
    row = sd._row_stats_from_values([0.10, 0.30, NAN], "PORO",
                                    volume=[1.0, 9.0, NAN])
    assert row["Cardinality"] == 2.0
    assert row["Mean"] == pytest.approx(0.20, abs=1e-15)
    assert row["Mean (V)"] == pytest.approx(0.28, abs=1e-15)
    assert row["weighted_n"] == 2


def test_a_valued_cell_without_a_volume_counts_in_one_mean_only():
    """b2: volumes [1, 9, nan], values [0.10, 0.30, 0.99].

        Cardinality = 3
        Mean        = (0.10 + 0.30 + 0.99) / 3 = 1.39 / 3
                    = 0.4633333333333333
        Mean (V)    = 0.28 (the third cell has no volume to weigh it with)
        weighted_n  = 2  ->  the row must say "2 of the 3"
    """
    row = sd._row_stats_from_values([0.10, 0.30, 0.99], "PORO",
                                    volume=[1.0, 9.0, NAN])
    assert row["Cardinality"] == 3.0
    assert row["Mean"] == pytest.approx(0.4633333333333333, abs=1e-15)
    assert row["Mean (V)"] == pytest.approx(0.28, abs=1e-15)
    assert row["weighted_n"] == 2


def test_a_zero_volume_cell_weighs_nothing():
    """b3: volumes [1, 9, 0], values [0.10, 0.30, 0.99] — same as b2.

    A weight must be strictly positive: a degenerate cell of zero volume
    is no rock, so it drops out of the weighted mean exactly as a blanked
    one does.
    """
    row = sd._row_stats_from_values([0.10, 0.30, 0.99], "PORO",
                                    volume=[1.0, 9.0, 0.0])
    assert row["Cardinality"] == 3.0
    assert row["Mean (V)"] == pytest.approx(0.28, abs=1e-15)
    assert row["weighted_n"] == 2


# --- (c) the weights cannot be obtained -------------------------------------

def test_without_weights_the_row_carries_no_weighted_mean():
    values = [0.10, 0.30]
    assert "Mean (V)" not in sd._row_stats_from_values(values, "PORO")
    assert "Mean (V)" not in sd._row_stats_from_values(values, "PORO", volume=None)
    row = sd._row_stats_from_values(values, "PORO", volume=[NAN, NAN])
    assert "Mean (V)" not in row
    assert row["weighted_n"] == 0
    # a weight array that does not index the values weighs nothing
    row = sd._row_stats_from_values(values, "PORO", volume=[1.0, 2.0, 3.0])
    assert "Mean (V)" not in row and row["weighted_n"] == 0


def _surface_tree():
    asm = FakeDataAssembly()
    surf = asm.add_node_with_attrs("_surf", 0, label="TriangulatedSet_Top",
                                   title="Top Hugin", type="TriangulatedSet",
                                   typeCode="2")
    return Tree(asm), asm.GetNodePath(surf)


def test_a_surface_has_no_cell_volume_and_says_so():
    cell_weights.clear()
    tree, path = _surface_tree()
    w = cell_weights.weights_for(object(), tree, None, path)
    assert w["volume"] is None and w["pore"] is None
    assert w["note"] == ("Top Hugin is a triangulated set: it has no cells"
                         " with a volume, so no weighted mean.")


def _grid_tree():
    """An IJK grid carrying one porosity property."""
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid", 0, label="IjkGrid_G",
                                   title="Geogrid", type="IjkGrid")
    prop = asm.add_node_with_attrs("_phi", grid, label="phi", title="PORO",
                                   type="ContinuousProperty")
    return Tree(asm), asm.GetNodePath(prop)


# --- what the row says of its weights ---------------------------------------

def test_the_note_blames_the_index_not_the_cells():
    """A node-indexed property leaves `weighted_n` at 0 against a full
    cardinality; blaming blanked cells would be false and unactionable."""
    tree, path = _grid_tree()
    note = sd._weights_note(
        tree, path, {"note": ""},
        [{"Cardinality": 12.0, "weighted_n": 0, "weights_index_na": [12, 2]}])
    assert note == ("'PORO' does not index the cells of Geogrid (12 values"
                    " for 2 cells): no weighted mean.")
    # and a genuinely blanked grid keeps the sentence it earned
    note = sd._weights_note(tree, path, {"note": ""},
                            [{"Cardinality": 10.0, "weighted_n": 7}])
    assert "have no volume (blanked or degenerate)" in note


def test_the_note_counts_the_pore_volume_mean_separately():
    tree, path = _grid_tree()
    note = sd._weights_note(
        tree, path, {"note": "", "poro_title": "PORO", "ntg_title": "NTG"},
        [{"Cardinality": 10.0, "weighted_n": 10, "pore_n": 6}])
    assert note == ("The pore-volume-weighted mean is computed on 6 of those"
                    " 10 cells: 4 have no pore volume (a blanked or"
                    " non-positive PORO or NTG).")


def test_the_row_says_when_the_weight_is_the_property_itself():
    """The row warns when the porosity is weighted by itself.

    `pore = volume x ntg x porosity`, so on the porosity row Mean (PV) is the
    porosity weighted by itself and cannot equal the Volumetrics card's
    PV / NRV; the row must say so."""
    tree, path = _grid_tree()
    note = sd._weights_note(tree, path, {"note": "", "poro_path": path},
                            [{"Cardinality": 10.0, "weighted_n": 10}])
    assert "weighted by itself" in note and "PV ÷ NRV" in note
    # another property of the same grid is weighted by the porosity, not by
    # itself, and says nothing of the sort
    note = sd._weights_note(tree, path, {"note": "", "poro_path": "/other"},
                            [{"Cardinality": 10.0, "weighted_n": 10}])
    assert note == ""


def test_the_row_says_which_realization_the_weight_came_from():
    tree, path = _grid_tree()
    note = sd._weights_note(
        tree, path, {"note": "", "real_idx": 0},
        [{"Cardinality": 10.0, "weighted_n": 10, "real_idx": 0},
         {"Cardinality": 10.0, "weighted_n": 10, "real_idx": 3}])
    assert note == ("The pore-volume weight is read once, at realization 0:"
                    " a row at realization 3 is weighted by realization 0's"
                    " porosity, not its own.")


# --- (d) the two invariants -------------------------------------------------

def test_equal_weights_give_back_the_arithmetic_mean():
    values = [2.0, 4.0, 6.0, 8.0]
    row = sd._row_stats_from_values(values, "P", volume=[1.0, 1.0, 1.0, 1.0])
    assert row["Mean (V)"] == row["Mean"] == 5.0


def test_a_constant_property_weighs_to_the_constant():
    row = sd._row_stats_from_values([3.5] * 5, "P",
                                    volume=[0.1, 7.0, 2.5, 1e-3, 400.0])
    assert row["Mean (V)"] == pytest.approx(3.5, abs=1e-15)


def test_weighted_mean_is_computed_before_the_finite_compaction():
    """The value and its weight must stay paired: dropping the NaN values
    first would shift every weight by one place.

        values  [nan, 0.10, 0.30]   weights [100.0, 1.0, 9.0]
        paired  -> (1*0.10 + 9*0.30) / 10                 = 0.28
        shifted -> (100*0.10 + 1*0.30) / 101              = 0.0993...
    """
    mean, n, why = sd.weighted_mean([NAN, 0.10, 0.30], [100.0, 1.0, 9.0])
    assert mean == pytest.approx(0.28, abs=1e-15)
    assert (n, why) == (2, "")


def test_a_property_that_does_not_index_the_cells_says_so_not_blanked():
    """A property read off the NODES of a grid arrives with more values than
    the grid has cells. That is not "every cell is blanked": the two arrays
    do not index the same thing, and only the second sentence tells the
    reader something they can act on.

    An IJK grid of 2x1x1 has 3x2x2 = 12 nodes against 2 cells."""
    assert sd.weighted_mean([0.1] * 12, [1.0, 9.0]) == (None, 0, "length")
    # and no element carrying a usable weight is the OTHER reason
    assert sd.weighted_mean([0.1, 0.3], [NAN, 0.0]) == (None, 0, "none")
    row = sd._row_stats_from_values([0.1] * 12, "PHI", volume=[1.0, 9.0])
    assert "Mean (V)" not in row
    assert row["weighted_n"] == 0
    assert row["weights_index_na"] == [12, 2]
    # a weight that fits but qualifies nowhere records no index mismatch
    row = sd._row_stats_from_values([0.1, 0.3], "PHI", volume=[NAN, 0.0])
    assert row["weighted_n"] == 0 and "weights_index_na" not in row


def test_the_pore_volume_mean_carries_its_own_count():
    """`pore = volume x ntg x porosity` is NaN wherever a term is blanked, so
    the pore-weighted mean can rest on strictly fewer cells than the
    volume-weighted one. Three cells, the third with no porosity:

        volumes [1, 9, 5]   pore [0.1, 1.35, nan]
        Mean (V) over 3 cells, Mean (PV) over 2 — and the row must not
        report the first count for both."""
    row = sd._row_stats_from_values(
        [0.10, 0.30, 0.20], "PHI", volume=[1.0, 9.0, 5.0],
        pore_volume=[0.10, 1.35, NAN])
    assert row["weighted_n"] == 3
    assert row["pore_n"] == 2
    assert row["Mean (PV)"] == pytest.approx((0.10 * 0.10 + 1.35 * 0.30)
                                             / (0.10 + 1.35))


# ---- percentiles, moments and the Sum column ------------------------------
# P10 and P90 are percentiles of the CELL values, the convention of the
# calculator's chips; the central moments come with them so the numpy row
# carries what the ParaView row carries; and a Sum is offered only where
# adding the values means something.

def test_the_row_carries_the_cell_percentiles_and_the_moments():
    values = list(range(1, 101))
    row = sd._row_stats_from_values(values, "P")
    assert row["P10"] == pytest.approx(10.9)
    assert row["Median"] == pytest.approx(50.5)
    assert row["P90"] == pytest.approx(90.1)
    assert row["P10"] < row["Q1"] < row["Median"] < row["Q3"] < row["P90"]
    # the moments are the SUMS of the powered deviations, the convention
    # of vtkDescriptiveStatistics on a view row: M2 = (n - 1) · variance
    m2 = sum((v - 50.5) ** 2 for v in values)
    assert row["M2"] == pytest.approx(m2)
    assert row["M2"] == pytest.approx(99 * row["Variance"])
    assert row["M3"] == pytest.approx(0.0, abs=1e-6)
    assert row["M4"] == pytest.approx(sum((v - 50.5) ** 4 for v in values))
    from fespp_on_trame.engine import compare_matrix
    assert set(compare_matrix._METRIC_KEYS) >= {"P10", "P90", "M2", "M3", "M4"}


@pytest.mark.parametrize("prop_kind, uom, kind_title, title, expected", [
    ("ContinuousProperty", "m3", "rock volume", "BULKVOL", True),
    ("ContinuousProperty", "mD", "", "PERMX", True),
    ("ContinuousProperty", "", "", "AnyName", True),
    ("ContinuousProperty", "%", "", "AnyName", False),
    ("ContinuousProperty", "p.u.", "", "PHIE", False),
    ("ContinuousProperty", "v/v", "", "PHIE", False),
    ("ContinuousProperty", "", "porosity", "PHIE", False),
    ("ContinuousProperty", "", "water saturation", "SW", False),
    ("ContinuousProperty", "", "net to gross ratio", "NTG", False),
    ("ContinuousProperty", "", "", "porosity", False),
    ("CategoricalProperty", "", "", "FACIES", False),
    ("DiscreteProperty", "", "", "LAYER", True),
])
def test_a_sum_is_offered_only_where_adding_means_something(
        prop_kind, uom, kind_title, title, expected):
    assert sd.sum_meaningful(prop_kind, uom, kind_title, title) is expected
