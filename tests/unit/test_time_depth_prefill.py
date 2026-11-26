"""The pre-fill of the time-depth model (engine/time_depth_prefill): the
extent out of the representations' fields, the columns out of the wells'
time logs, both pure over what the query channel answers."""
import math

from fespp_on_trame.engine import time_depth_prefill as pf


def test_the_extent_is_the_union_of_what_answered_a_little_wider():
    got = pf.numbers("1;2.5;nan;x")
    assert got[:2] == [1.0, 2.5] and math.isnan(got[2]) and math.isnan(got[3])
    assert pf.extent_of({"extent_xy": "10;20;30;40"}) == (10.0, 20.0, 30.0, 40.0)
    assert pf.extent_of({"extent_xy": "10;nan;30;40"}) is None
    assert pf.extent_of({"extent_xy": "20;10;30;40"}) is None       # inside out
    assert pf.extent_of({}) is None
    assert pf.union([None, (0, 10, 0, 5), (-5, 3, 2, 9)]) == (-5, 10, 0, 9)
    assert pf.union([None]) is None
    assert pf.padded((0.0, 1000.0, 0.0, 500.0)) == (-20.0, 1020.0, -10.0, 510.0)
    assert pf.padded((5.0, 5.0, 7.0, 7.0)) == (-495.0, 505.0, -493.0, 507.0)


def test_the_index_names_what_is_read_and_how():
    index = [
        {"uuid": "a", "type": "Grid2dRepresentation", "title": "HOD", "partial": False},
        {"uuid": "b", "type": "Grid2dRepresentation", "title": "stub", "partial": True},
        {"uuid": "c", "type": "IjkGridRepresentation", "title": "grid", "partial": False},
        {"uuid": "d", "type": "WellboreTrajectoryRepresentation", "title": "w", "partial": False},
        {"uuid": "e", "type": "HorizonInterpretation", "title": "no extent", "partial": False},
        {"uuid": "f", "type": "SubRepresentation", "title": "its support's", "partial": False},
    ]
    entries = pf.extent_entries(index)
    assert [u for u, *_ in entries] == ["a", "b", "c", "d"]
    assert pf.describe_extent_read(entries) == ("2 from their lattice (no data read), "
                                                "1 from their top and base interfaces, 1 from their points")


def test_a_time_log_is_known_by_its_unit_and_one_per_well_makes_the_column():
    assert pf.is_time_log("TWTIME", "s") and pf.is_time_log("anything", "ms")
    assert not pf.is_time_log("TIME", "us/ft") and not pf.is_time_log("DT", "")
    channels = [("W1", "u1", "DT", "us/ft"), ("W1", "u2", "TIME", "s"), ("W1", "u3", "TWTIME", "s"),
                ("W2", "u4", "VELOCITY", "m/s"), ("W3", "u5", "owt", "ms")]
    assert pf.pick_time_logs(channels) == [("W1", "u3", "TWTIME", "s"), ("W3", "u5", "owt", "ms")]


def test_samples_read_the_fields_in_the_crs_orientation_and_the_unit():
    fields = {"uom": "s", "depth_oriented": "true",
              "xyz": "1;2;100;1;2;200;1;2;nan;1;2;300", "values": "0.1;0.2;0.25;nan"}
    assert pf.log_samples(fields) == [(1.0, 2.0, 100.0, 100.0), (1.0, 2.0, 200.0, 200.0)]
    up = {"uom": "ms", "depth_oriented": "false", "xyz": "1;2;-300;1;2;-100", "values": "300;100"}
    assert pf.log_samples(up) == [(1.0, 2.0, 100.0, 100.0), (1.0, 2.0, 300.0, 300.0)]
    assert pf.log_samples({"uom": "us/ft", "xyz": "1;2;3", "values": "1"}) == []
    assert pf.log_samples({"uom": "s", "xyz": "1;2", "values": "1"}) == []


def test_a_column_is_sampled_on_the_shared_step_along_its_own_curve():
    assert pf.nice_step(3000.0) == 250.0 and pf.nice_step(3100.0) == 250.0 and pf.nice_step(600.0) == 50.0
    assert pf.nice_step(0) == 200.0 and pf.nice_step(1e6) == 5000.0
    # a well drifting east, 2000 m/s above 500 m, 4000 m/s below
    samples = [(0.0, 0.0, 0.0, 0.0), (10.0, 0.0, 500.0, 500.0), (30.0, 0.0, 1500.0, 1000.0)]
    (x, y), points = pf.column_points(samples, 250.0)
    assert (x, y) == (40.0 / 3.0, 0.0)
    assert points == [(250.0, 250.0), (500.0, 500.0), (750.0, 625.0), (1000.0, 750.0),
                      (1250.0, 875.0), (1500.0, 1000.0)]
    # a sample going back in time is dropped, under two usable samples no column
    assert pf.column_points([(0, 0, 100.0, 100.0), (0, 0, 200.0, 90.0)], 50.0) == ((None, None), [])
    assert pf.column_points([(0, 0, 100.0, 100.0), (0, 0, 200.0, 90.0), (0, 0, 300.0, 300.0)], 100.0)[1] == [
        (100.0, 100.0), (200.0, 200.0), (300.0, 300.0)]


def test_the_wells_share_one_step_chosen_from_the_deepest():
    logs = [("A", "TWTIME", [(0, 0, 100.0, 100.0), (0, 0, 3000.0, 2000.0)]),
            ("B", "TWTIME", [(5, 5, 200.0, 150.0), (5, 5, 1100.0, 700.0)]),
            ("C", "TWTIME", [(9, 9, 100.0, 100.0)])]
    columns, step = pf.wells_columns(logs)
    assert step == 250.0 and [c[0] for c in columns] == ["A", "B"]
    assert columns[0][1] == (0.0, 0.0) and columns[0][2][0] == (250.0, 100.0 + 150.0 * 1900.0 / 2900.0)
    assert columns[1][2] == [(250.0, 150.0 + 50.0 * 550.0 / 900.0), (500.0, 150.0 + 300.0 * 550.0 / 900.0),
                             (750.0, 150.0 + 550.0 * 550.0 / 900.0), (1000.0, 150.0 + 800.0 * 550.0 / 900.0)]
    assert columns[0][3] == "TWTIME, 2 samples"
    assert pf.wells_columns([("C", "TWTIME", [(9, 9, 100.0, 100.0)])]) == ([], 200.0)
    # the step reads the deepest usable depth: a sample out of order below it is no depth
    deep = [("D", "TWTIME", [(0, 0, 100.0, 100.0), (0, 0, 3000.0, 2000.0), (0, 0, 9000.0, 1500.0)])]
    assert pf.wells_columns(deep)[1] == 250.0
    assert pf.column_name("  NO 15/9-F-5 ") == "NO 15/9-F-5" and pf.column_name("") is None
    assert pf.column_name("well_feature_NO_15_9-F-5_B75BED") == "NO_15_9-F-5_B75BED"
    assert pf.column_name("Wellbore_Feature_X") == "X" and pf.column_name("well_feature_") is None


US_FT_2000 = 1e6 * 0.3048 / 2000.0      # the slowness of 2 000 m/s, in us/ft


def _close(a, b):
    return abs(a - b) < 1e-6


def test_a_sonic_log_is_integrated_down_from_its_top():
    assert pf.sonic_kind("DT", "us/ft") == "slowness" and pf.sonic_kind("P_VELOCITY", "ft/s") == "velocity"
    assert pf.sonic_kind("DTS", "us/ft") is None and pf.sonic_kind("GR", "gAPI") is None
    picked = pf.pick_sonic_logs([("W1", "a", "DT", "us/ft"), ("W1", "b", "DT_CKS", "us/ft"),
                                 ("W1", "s", "DTS", "us/ft"), ("W2", "v", "VELOCITY", "m/s")])
    assert [(w, u) for w, u, _t, _m in picked] == [("W1", "b"), ("W2", "v")]
    # 2 000 m/s from 1 000 m down, a spike (5 us/ft) dropped
    fields = {"uom": "us/ft", "depth_oriented": "true",
              "xyz": "0;0;1000;0;0;1500;0;0;1700;0;0;2000",
              "values": f"{US_FT_2000};{US_FT_2000};5;{US_FT_2000}"}
    got = pf.sonic_samples(fields, lambda x, y, z: 2000.0 * z / 2500.0)
    assert [s[2] for s in got] == [1000.0, 1500.0, 2000.0]
    assert _close(got[0][3], 800.0) and _close(got[-1][3], 1800.0)
    assert pf.sonic_samples({"uom": "us/ft", "xyz": "0;0;1", "values": "100"}, lambda *a: 0.0) == []


def test_horizons_pair_by_feature_then_by_name():
    assert pf.pair_key("Hugin_Fm_Top") == pf.pair_key("Hugin Fm_ Top") == "hugin"
    assert pf.pair_key("Hugin_Fm_Base") == "hugin base" and pf.pair_key("TY") == pf.pair_key("Ty_Fm_Top")
    left = [("f1", "BCU", "a"), ("", "Hugin_Fm_Top", "b"), ("", "Tor", "c")]
    right = [("x", "Hugin Fm_ Top", 1), ("f1", "Base Cretaceous", 2), ("", "Hod", 3)]
    assert [(a[2], b[2]) for a, b in pf.pairs_of(left, right)] == [("a", 2), ("b", 1)]


def test_a_surface_is_read_between_its_nodes():
    fields = {"lattice": "0;0;100;0;0;50", "nodes": "3;2", "stride": "1",
              "z": "1000;1100;1200;1000;1100;nan", "depth_oriented": "true"}
    at, extent = pf.surface_reader(fields)
    assert extent == (0.0, 200.0, 0.0, 50.0)
    assert at(50, 0) == 1050.0 and at(50, 25) == 1050.0
    assert at(150, 25) is None and at(250, 0) is None      # a hole, then outside
    assert pf.oriented(at, {"depth_oriented": "false"}, 1000.0)(0, 0) == -1000000.0
    # one node in two kept: the lattice's offsets doubled
    kept = {"lattice": "0;0;50;0;0;50", "nodes": "5;3", "stride": "2", "z": "1;2;3;4;5;6"}
    at2, extent2 = pf.surface_reader(kept)
    assert extent2 == (0.0, 200.0, 0.0, 100.0) and at2(200, 100) == 6.0
    assert pf.surface_reader({"lattice": "0;0;1;0;0;1", "nodes": "2;2", "z": "1;2;3"}) is None
    assert pf.overlap((0, 10, 0, 10), (5, 20, -5, 5)) == (5, 10, 0, 5) and pf.overlap((0, 1, 0, 1), (2, 3, 0, 1)) is None


def test_markers_are_read_on_their_time_horizon():
    fields = {"xyz": "10;20;1000;10;20;2000;10;20;2500", "depth_oriented": "true",
              "marker_feature.0": "F1|BCU", "marker_feature.2": "F3|Tor"}
    marks = pf.marker_points(fields)
    assert marks == [("f1", "BCU", 10.0, 20.0, 1000.0), ("f3", "Tor", 10.0, 20.0, 2500.0)]
    samples = pf.marker_samples(marks, lambda f, t, x, y: 900.0 if f == "f1" else None)
    assert samples == [(10.0, 20.0, 1000.0, 900.0)]


def test_surface_pairs_make_columns_where_they_answer():
    def flat(value):
        return lambda x, y: value
    pairs = [(flat(1000.0), flat(1200.0), (0.0, 100.0, 0.0, 100.0)),
             (flat(1800.0), flat(2500.0), (0.0, 50.0, 0.0, 100.0))]
    cols = pf.pair_samples(pairs, n=2)
    assert [name for name, _s in cols] == ["S1", "S2", "S3", "S4"]
    assert cols[0][1] == [(25.0, 25.0, 1200.0, 1000.0), (25.0, 25.0, 2500.0, 1800.0)]
    # one pair is a column: a point beyond the zero is a law
    got, step = pf.wells_columns([("S1", "surfaces", cols[0][1][:1])], least=1,
                                 describe=lambda _t, s: f"{len(s)} pair")
    assert got[0][3] == "1 pair" and got[0][1] == (25.0, 25.0) and got[0][2][-1][0] <= 1200.0
    assert pf.wells_columns([("S1", "surfaces", cols[0][1][:1])])[0] == []


def test_surface_pair_columns_are_numbered_in_a_row_where_a_pair_answers():
    def east_half(value):
        return lambda x, y: value if x > 50 else None
    cols = pf.pair_samples([(east_half(1000.0), east_half(1200.0), (0.0, 100.0, 0.0, 100.0))], n=2)
    assert [(name, s[0][0], s[0][1]) for name, s in cols] == [("S1", 75.0, 25.0), ("S2", 75.0, 75.0)]
