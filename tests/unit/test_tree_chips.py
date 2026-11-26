"""The tree's colour chips (the PO, 20/10: which row is which object in 3D):
a loaded representation's solid colour, its grid folder wearing its
geometry's; an unloaded one keeps its reserved colour but no chip."""
from fespp_on_trame.app.views.widgets.data_tree import chip_colours

GEOM = "/data/_gridfolder_g/_propsfolder_g/_g"
SURF = "/data/_s"


def test_a_loaded_representation_wears_its_colour_and_its_grid_folder_too():
    chips = chip_colours({GEOM: "#112233ff", SURF: "#abcdef80"}, [GEOM, SURF])
    assert chips == {GEOM: "#112233", "/data/_gridfolder_g": "#112233", SURF: "#abcdef"}


def test_an_unloaded_one_has_no_chip_and_a_bad_colour_is_skipped():
    assert chip_colours({GEOM: "#112233ff", SURF: "#abcdef80"}, [SURF]) == {SURF: "#abcdef"}
    assert chip_colours({SURF: "nope", "": "#000000"}, None) == {}
    # no loaded list given: every colour
    assert chip_colours({SURF: "#abcdef"}) == {SURF: "#abcdef"}
