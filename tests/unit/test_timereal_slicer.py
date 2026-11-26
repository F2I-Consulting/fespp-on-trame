"""The Time & Realizations card as the shared slicer card
(app/features/timereal_slicer; the PO, 29/10): its helpers on the card
model, no view."""
from fespp_on_trame.app.features import timereal_slicer as ts
from fespp_on_trame.engine import slicer_card as sc


def test_a_value_snaps_to_the_nearest_one_the_view_can_show():
    assert ts.nearest([23, 24, 30], 27.4) == 30
    assert ts.nearest([23, 24, 30], 26.9) == 24
    assert ts.nearest([], 5) == 5


def test_a_vector_names_its_components_and_its_magnitude():
    assert ts.component_labels(3) == {-1: "|v|", 0: "X", 1: "Y", 2: "Z"}
    assert ts.component_labels(2) == {-1: "|v|", 0: "1", 1: "2"}


def test_a_series_of_one_step_goes_by_unique_time_step():
    # the card draws `single_label` on a subject of one value, its date alone beside it
    one = ts.time_info([3], {3: "1995-01-01"})
    assert one["single_label"] == "Unique time step" and one["label"] == "Time step"
    assert one["extent"] == [3, 3] and one["values"] == [3] and one["labels"] == {3: "1995-01-01"}
    many = ts.time_info([0, 4, 9], {0: "a", 4: "b", 9: "c"})
    assert many["extent"] == [0, 9] and many["values"] == [0, 4, 9]
    assert many["extent"][0] != many["extent"][1], "several steps: the Time step row and its slider"


def test_the_time_card_bundle_reads_the_single_label():
    # the bundle the browser runs, built from the shared slicer card that draws it
    from pathlib import Path
    bundle = (Path(__file__).resolve().parents[2] / "widgets" / "timereal" / "trame_fespp_timereal"
              / "module" / "serve" / "trame_fespp_timereal.umd.js").read_text(encoding="utf-8")
    assert "single_label" in bundle


def test_the_first_cut_of_the_first_slice_box_is_what_the_view_shows():
    subjects = ("time", "real:/p")
    exts = {"time": [0, 9], "real:/p": [23, 30]}
    values = {"time": list(range(10)), "real:/p": [23, 24, 30]}
    card = sc.empty(subjects)
    box = sc.new_box(card, exts, mode=sc.SLICE, values=values, whole=subjects)
    for s in subjects:
        sc.new_cut(card, box, s, exts[s], values[s], whole=True)
    ts.point_cuts(card, box, {"time": 4, "real:/p": 24})
    assert ts.cut_values(card) == {"time": 4.0, "real:/p": 24.0}
    # a second Slice box says nothing: the first is in force
    other = sc.new_box(card, exts, mode=sc.SLICE, values=values, whole=subjects)
    sc.new_cut(card, other, "time", exts["time"], values["time"], whole=True)["at"] = 9.0
    assert ts.cut_values(card)["time"] == 4.0
    # a Range box has no cut to read
    assert ts.cut_values(sc.empty(subjects)) == {}
