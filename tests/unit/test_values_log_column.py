"""The log view and the Values view: only the column holding the log the
Values view reads marks (pointer) or holds (click) one of its rows."""
from fespp_on_trame.engine import values_table


def _hit(well="55/33-A-2", curves=("Facies", "Zone Index"), md=1700.0):
    return {"well": well, "depths": [{"ref": "MD", "value": md}], "curves": list(curves)}


def test_the_column_of_the_log_read_marks_its_rows():
    assert values_table.on_log_column(_hit(), "55/33-A-2", {"Facies"})
    # a frame read by its samples: any of its logs' columns
    assert values_table.on_log_column(_hit(curves=["Total Porosity"]), "55/33-A-2", {"Facies", "Total Porosity"})


def test_another_column_another_well_or_none_marks_nothing():
    assert not values_table.on_log_column(_hit(curves=["P-Wave Velocity"]), "55/33-A-2", {"Facies"})
    assert not values_table.on_log_column(_hit(well="55/33-1"), "55/33-A-2", {"Facies"})
    # off the tracks, or the Values view reading no log
    assert not values_table.on_log_column({}, "55/33-A-2", {"Facies"})
    assert not values_table.on_log_column(None, "55/33-A-2", {"Facies"})
    assert not values_table.on_log_column(_hit(), "", set())


def test_a_click_asks_for_the_row_held():
    assert values_table.query({"cursor_md": 1700.0, "hold": True})["hold"] is True
    assert values_table.query({"cursor_md": 1700.0})["hold"] is False
    assert values_table.query(3)["hold"] is False
