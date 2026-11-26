"""The RESQML object behind a row of the tree — every shape of node name
the plugin emits, and what the explorer must say when the row is not the
object it opens."""
from fespp_on_trame.engine import row_object as ro

UUID = "43338d80-4db2-54a6-9a3e-7be39e1310d1"
TS = "b2c4e6f8-1a3b-4c5d-8e9f-0a1b2c3d4e5f"
COMP = "d938f215-09a5-4b1c-9c2d-3e4f5a6b7c8d"


def test_a_row_that_is_its_object_opens_it_with_no_note():
    assert ro.resolve("_" + UUID, "Sector") == (UUID, "")


def test_the_folders_of_a_grid_open_the_grid():
    for prefix in ("gridfolder", "propsfolder", "subrepfolder", "bwfolder"):
        assert ro.resolve(f"_{prefix}_{UUID}", "properties") == (UUID, "")


def test_the_folders_of_a_well_open_the_wellbore():
    for prefix in ("logsfolder", "markersfolder", "completionsfolder"):
        assert ro.resolve(f"_{prefix}_{UUID}", "logs") == (UUID, "")


def test_a_feature_or_interpretation_row_is_an_object_of_its_own():
    """The by-interpretation layouts group the reps under `_feature_` and
    `_interp_` rows: these are real objects and open with no note."""
    assert ro.resolve("_feature_" + UUID, "Horizon A") == (UUID, "")
    assert ro.resolve("_interp_" + UUID, "Horizon A interp") == (UUID, "")


def test_a_series_row_opens_the_time_series_and_says_so():
    for leaf in (f"_{TS}TimeSeries_Porosity", f"_{TS}multirealts_Porosity",
                 f"_{TS}real_3_Porosity"):
        uuid, note = ro.resolve(leaf, "Porosity")
        assert uuid == TS
        assert note.startswith("Porosity is a time series of one property")
        assert "TimeSeries" in note


def test_a_perforation_opens_its_completion_and_names_it():
    uuid, note = ro.resolve(f"_{COMP}_PERF-12", "Perfo_Perfo1", "OP2 wellbore completion")
    assert uuid == COMP
    assert note == ("Perfo_Perfo1 is a perforation of OP2 wellbore completion:"
                    " what opens is the completion that declares it — a"
                    " perforation is no object of its own.")


def test_a_realization_group_has_no_object():
    uuid, note = ro.resolve("_multireal_Porosity", "Porosity")
    assert uuid == ""
    assert "no object of its own" in note and note.startswith("Porosity groups")


def test_an_unknown_synthetic_row_says_so_by_its_name():
    uuid, note = ro.resolve("_whatever", "")
    assert uuid == "" and note.startswith("This row is not a RESQML object")


def test_the_placeholder_uuid_is_no_object():
    zero = "00000000-0000-0000-0000-000000000000"
    assert ro.resolve(f"_{zero}multirealts_Porosity", "Porosity")[0] == ""
    assert ro.uuid_of("_" + zero) == ""


def test_uuid_of_reads_every_shape_the_attributes_card_meets():
    assert ro.uuid_of("_" + UUID) == UUID
    assert ro.uuid_of("_gridfolder_" + UUID) == UUID
    assert ro.uuid_of("_interp_" + UUID) == UUID
    assert ro.uuid_of(f"_{TS}TimeSeries_Porosity") == TS
    assert ro.uuid_of(f"_{COMP}_PERF-12") == COMP
    assert ro.uuid_of("_multireal_Porosity") == ""
    assert ro.uuid_of("") == ""
