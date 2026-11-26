"""The Values view's row under the pointer, told to the log view (engine/values_table.pointed_sample): the
sample crossed on the curves of the logs the view reads, none once the pointer leaves the table."""
from fespp_on_trame.engine import values_table

LOGS = {"Relative AI Near (Depth, 2018)", "Total Porosity"}


def test_a_row_of_a_log_sample_points_at_its_measured_depth_on_its_logs():
    got = values_table.pointed_sample({"row": 3557, "md": 1778.561}, "55/33-A-4", LOGS)
    assert got == {"well": "55/33-A-4", "md": 1778.561, "curves": sorted(LOGS)}


def test_the_pointer_leaving_the_table_points_at_nothing():
    assert values_table.pointed_sample(None, "55/33-A-4", LOGS) is None


def test_a_row_without_a_depth_points_at_nothing():
    for md in (None, float("nan"), float("inf"), "1778", True):
        assert values_table.pointed_sample({"row": 1, "md": md}, "55/33-A-4", LOGS) is None


def test_a_view_reading_no_log_points_at_nothing():
    assert values_table.pointed_sample({"row": 1, "md": 10.0}, "", LOGS) is None
    assert values_table.pointed_sample({"row": 1, "md": 10.0}, "55/33-A-4", set()) is None


def test_an_integer_depth_is_a_depth():
    assert values_table.pointed_sample({"row": 1, "md": 1800}, "W", {"GR"})["md"] == 1800.0


def test_a_column_of_values_says_its_unit_and_a_place_keeps_its_label():
    got = values_table.unit_labels(["cell id", "X", "GasBulkVolume", "Facies"],
                                   {"GasBulkVolume": "m3", "X": "m", "Facies": ""}, {"X": "Easting (m)"})
    assert got == {"GasBulkVolume": "GasBulkVolume (m3)"}


def test_no_unit_known_no_label():
    assert values_table.unit_labels(["Temperature"], {}) == {}
    assert values_table.unit_labels(["Temperature"], {"Temperature": "  "}) == {}


def test_the_map_of_a_part_holds_its_cells_alone():
    # a grid of 2 layers of 2 x 3 cells; the part holds cells 1 and 4 of layer 0 and cell 6 (layer 1)
    keep0 = values_table.layer_in_part([1, 4, 6, -1, 99], (2, 2, 3), 0)
    assert keep0.tolist() == [[False, True, False], [False, True, False]]
    keep1 = values_table.layer_in_part([1, 4, 6], (2, 2, 3), 1)
    assert keep1.tolist() == [[True, False, False], [False, False, False]]


def test_a_part_with_no_cell_leaves_the_layer_blank():
    assert not values_table.layer_in_part(None, (1, 2, 2), 0).any()
