"""engine.geo.axes_labels: the letters on a 3D view's orientation axes — the
initials of the CRS's own names for the horizontal ordinates, in the file's
order, and Z upwards (FESPP negates a depth CRS on the way in), T for a time
CRS; each with the unit the CRS declares (the PO, 28/10)."""
from fespp_on_trame.engine import geo


def test_the_file_s_axis_order_gives_the_initials_with_their_units():
    info = {"axis_order": "Easting Northing", "projected_unit": "m", "epsg": 23031}
    assert geo.axes_labels(info) == ("E (m)", "N (m)", "Z")
    info["vertical_unit"] = "m"
    assert geo.axes_labels(info) == ("E (m)", "N (m)", "Z (m)")


def test_a_time_crs_is_lettered_t_in_its_time_unit():
    info = {"axis_order": "Easting Northing", "projected_unit": "m", "time": True,
            "vertical_unit": "m", "time_unit": "ms"}
    assert geo.axes_labels(info) == ("E (m)", "N (m)", "T (ms)")
    assert geo.axes_grid_titles(info)[2] == "Time (ms)"


def test_the_file_s_order_is_kept_when_it_starts_with_northing():
    assert geo.axes_labels({"axis_order": "Northing Easting"}) == ("N", "E", "Z")


def test_a_westing_southing_file_says_so():
    assert geo.axes_labels({"axis_order": "Westing Southing"}) == ("W", "S", "Z")


def test_no_crs_keeps_the_reader_s_letters():
    assert geo.axes_labels(None) == ("X", "Y", "Z")
    assert geo.axes_labels({"epsg": None}) == ("X", "Y", "Z")


def test_the_axes_grid_titles_name_the_ordinates_and_their_units():
    """The axes grid's titles in full, with the declared units (the
    manager, 16/10: "X" and "Y" with no unit said nothing)."""
    info = {"axis_order": "Easting Northing", "projected_unit": "m",
            "vertical_unit": "m"}
    assert geo.axes_grid_titles(info) == ("Easting (m)", "Northing (m)",
                                          "Elevation (m)")
    assert geo.axes_grid_titles({"axis_order": "Northing Easting",
                                 "projected_unit": "ft", "time": True,
                                 "vertical_unit": "ms"}) == (
        "Northing (ft)", "Easting (ft)", "Time (ms)")


def test_the_axes_grid_guesses_neither_a_name_nor_a_unit():
    assert geo.axes_grid_titles(None) == ("X", "Y", "Elevation")
    assert geo.axes_grid_titles({"axis_order": "Easting Northing"}) == (
        "Easting", "Northing", "Elevation")
