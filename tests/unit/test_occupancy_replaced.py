"""app/scene/occupancy.replaced_rows: the geometries a visible extract stands in for, their eye shown closed in the
tree (the eye says what is drawn: the extract, not the grid)."""
from fespp_on_trame.app.scene.occupancy import replaced_rows


def test_a_visible_extract_closes_the_eye_of_its_geometry():
    extracts = [{"rep_path": "/grid/geo", "visible": True}, {"rep_path": "/grid/geo", "visible": True},
                {"rep_path": "/other/geo", "visible": False}]
    assert replaced_rows(extracts) == ["/grid/geo"]


def test_no_extract_shown_no_geometry_replaced():
    assert replaced_rows([]) == []
    assert replaced_rows(None) == []
    assert replaced_rows([{"rep_path": "/grid/geo", "visible": False}, {"visible": True}]) == []
