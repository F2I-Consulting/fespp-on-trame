"""Per-zone statistics, pay cutoffs and absent-log reasons on the well-log payload.

Covers the statistics per stratigraphic zone
(fespp_on_trame.engine.welllog_dispatch.zone_stats / zone_intervals), the
cutoffs that flag the pay (pay_intervals / with_cutoffs), and why a rule's
log is absent from a well (absent_why, fed by build_payload's `absent`).

These are pure functions over the payload shape, with no ParaView involved,
so they run under the conftest stubs; `build_payload` runs on a fake
assembly with the block reads stubbed.
"""
import pytest

from fespp_on_trame.engine import welllog_dispatch
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine.welllog_dispatch import (
    _percentile, absent_why, build_payload, missing_rule_curves,
    pay_intervals, summation_curves, with_cutoffs, zone_intervals,
    zone_stats,
)
from tests.unit.fake_assembly import FakeDataAssembly


def _curve(name, points, unit=None):
    return {"name": name, "unit": unit,
            "samples": [[v, d] for v, d in points]}


@pytest.fixture
def well():
    return {
        "name": "W1",
        "tops": [{"name": "TopA", "depth": 100.0},
                 {"name": "TopB", "depth": 200.0},
                 {"name": "TopC", "depth": 300.0}],
        "strati": {"rock": [
            {"name": "Fm A", "color": "#aaa", "top": 100.0, "bottom": 200.0},
            {"name": "Fm B", "color": "#bbb", "top": 200.0, "bottom": 300.0},
        ]},
        "tracks": [{"curves": [_curve("PHI", [
            (0.10, 150), (0.20, 199.9),      # Fm A
            (0.30, 200.0), (0.40, 250), (None, 260), (0.50, 299),  # Fm B
        ], "v/v")]}],
    }


class TestZoneIntervals:
    def test_column_wins_when_present(self, well):
        zones, source = zone_intervals(well)
        assert source == "frame"
        assert [z["name"] for z in zones] == ["Fm A", "Fm B"]

    def test_markers_when_no_column(self, well):
        well["strati"] = {}
        zones, source = zone_intervals(well)
        assert source == "markers"
        # Named after both picks, consecutive pairs only.
        assert [(z["name"], z["top"], z["bottom"]) for z in zones] == [
            ("TopA → TopB", 100.0, 200.0), ("TopB → TopC", 200.0, 300.0)]

    def test_inverted_or_flat_pair_is_skipped(self):
        w = {"tops": [{"name": "A", "depth": 50.0}, {"name": "B", "depth": 50.0}],
             "strati": {}}
        assert zone_intervals(w)[0] == []


class TestZoneStats:
    def test_bottom_bound_is_exclusive(self, well):
        z = zone_stats(well)
        a = z[0]["curves"][0]
        assert a["name"] == "PHI" and a["unit"] == "v/v"
        assert a["n"] == 2                       # 199.9 in, 200.0 out
        assert a["mean"] == pytest.approx(0.15)
        assert (a["min"], a["max"]) == (0.10, 0.20)

    def test_missing_samples_are_ignored(self, well):
        b = zone_stats(well)[1]["curves"][0]
        assert b["n"] == 3                       # the None is not a value
        assert b["mean"] == pytest.approx(0.40)

    def test_zone_without_curve_keeps_its_thickness(self, well):
        well["tracks"] = []
        z = zone_stats(well)
        assert [(x["name"], x["thickness"], x["curves"]) for x in z] == [
            ("Fm A", 100.0, []), ("Fm B", 100.0, [])]

    def test_source_is_carried_on_every_zone(self, well):
        assert {x["source"] for x in zone_stats(well)} == {"frame"}

    def test_no_cutoffs_means_no_summation_fields(self, well):
        z = zone_stats(well)[0]
        assert "net" not in z and "n_pay" not in z["curves"][0]


class _FakeArray:
    def __init__(self, values, components=1):
        self._v = list(values)
        self._c = components

    def GetNumberOfComponents(self):
        return self._c

    def GetNumberOfTuples(self):
        return len(self._v)

    def GetTuple1(self, i):
        return self._v[i]


class _FakeData:
    """The one lookup `_ring_samples` does on a point-data / field-data."""

    def __init__(self, arrays):
        self._a = arrays

    def GetArray(self, name):
        return self._a.get(name)


class _FakeTube:
    """A tube of `rings` rings of `sides` points, shaped like a VTK tube.

    Ring i is centred on ``z = -(100 + 10*i)`` with its points at
    ``centre ± radius``, the shape the VTK tube filter produces: the points
    sit on the surface, at a radius the log value drives."""

    def __init__(self, rings=3, sides=4, radius=25.0, zs=None, points=None):
        self.rings, self.sides = rings, sides
        # `points` is a real vtkPoints when the array read is under test;
        # without one the reader falls back to GetPoint, as on a dataset
        # whose points cannot be handed over as an array.
        self._points = points
        self._z = []
        if zs is not None:
            self._z = list(zs)
            self.rings = len(self._z) // sides
            return
        for i in range(rings):
            centre = -(100.0 + 10.0 * i)
            for k in range(sides):
                self._z.append(centre + (radius if k % 2 == 0 else -radius))

    def GetNumberOfPoints(self):
        return self.rings * self.sides

    def GetNumberOfCells(self):
        return self.sides

    def GetPoints(self):
        if self._points is None:
            raise AttributeError("this stub hands over no point array")
        return self._points

    def GetPoint(self, i):
        return (0.0, 0.0, self._z[i])

    def GetPointData(self):
        return _FakeData({"GR": _FakeArray([1.0] * (self.rings * self.sides))})

    def GetFieldData(self):
        return _FakeData({})


class TestRingCentreline:
    def test_the_ring_mean_is_the_centreline(self):
        # The mean of a closed ring is its centre, so the depths are the
        # ring centres 100, 110, 120; the first point of each ring sits a
        # radius above it and would read 75, 85, 95.
        got = welllog_dispatch._ring_samples(_FakeTube(), "GR")
        assert [d for _v, d, _m in got] == [100.0, 110.0, 120.0]

    def test_the_array_read_and_the_point_read_give_the_same_bits(self):
        """The array read and the per-point read of ring depths agree bit for bit.

        The Z column is read once as an array and summed ring by ring;
        without an array (a stub, a dataset that cannot hand one over) each
        point is read on its own. The two must agree to the last bit, not
        merely closely: the depth check refuses a single up-step along a
        log, and a 1e-16 difference on a flat stretch would be one.

        The ring here is a real circle, so the four offsets are
        0, r, 1.2e-16·r, −r and the sum is a residue rather than an exact
        zero, a sum that a different order would round differently."""
        import math
        zs = [-(100.0 + 10.0 * i) + 37.5 * math.sin(math.pi * k / 2.0)
              for i in range(3) for k in range(4)]
        vtk_core = pytest.importorskip("vtkmodules.vtkCommonCore")
        pts = vtk_core.vtkPoints()
        for z in zs:
            pts.InsertNextPoint(0.0, 0.0, z)
        by_array = welllog_dispatch._ring_samples(_FakeTube(zs=zs, points=pts), "GR")
        by_point = welllog_dispatch._ring_samples(_FakeTube(zs=zs), "GR")
        assert [d for _v, d, _m in by_array] == [d for _v, d, _m in by_point]

    def test_a_radius_larger_than_the_step_cannot_invert_the_depths(self):
        # Radius 25 against a 10 m step: the first-point depth of ring 0
        # (75) is shallower than that of ring 2 read the same way (95), and
        # both are wrong; the centreline is monotonic by construction.
        got = welllog_dispatch._ring_samples(_FakeTube(radius=25.0), "GR")
        depths = [d for _v, d, _m in got]
        assert depths == sorted(depths)


class TestPercentile:
    def test_nearest_rank_ties_go_up(self):
        v = list(range(1, 11))
        # A rank of 4.5 takes index 5, not Python's round-half-even 4.
        assert (_percentile(v, 10), _percentile(v, 50), _percentile(v, 90)) == (2, 6, 9)

    def test_exact_median_on_odd_count(self):
        assert _percentile(list(range(1, 10)), 50) == 5

    def test_edges_and_empty(self):
        v = list(range(1, 11))
        assert (_percentile(v, 0), _percentile(v, 100)) == (1, 10)
        assert _percentile([], 50) is None


def _two_logs():
    """PHI and SW on the same depths (one frame); one zone A = [100, 200)."""
    depths = [100, 120, 140, 160, 180]
    phi = [0.05, 0.12, 0.20, 0.08, 0.15]
    sw = [0.9, 0.4, 0.3, 0.5, 0.2]
    return {
        "name": "W", "tops": [],
        "strati": {"rock": [{"name": "A", "color": None,
                             "top": 100.0, "bottom": 200.0}]},
        "tracks": [
            {"kind": "effective porosity",
             "curves": [_curve("PHI", list(zip(phi, depths)), "v/v")]},
            {"kind": "water saturation",
             "curves": [_curve("SW", list(zip(sw, depths)), "v/v")]},
        ],
    }


PHI_10 = {"curve": "PHI", "op": ">=", "value": 0.10}
SW_50 = {"curve": "SW", "op": "<=", "value": 0.5}


class TestCutoffs:
    def test_pay_is_where_every_rule_holds(self):
        # 120 (0.12 / 0.4) and 140 (0.20 / 0.3) pass, 160 fails on PHI, and
        # 180 passes but, being the last sample, bounds nothing.
        assert pay_intervals(_two_logs(), [PHI_10, SW_50]) == [[120.0, 160.0]]

    def test_net_ntg_and_mean_over_the_pay(self):
        z = zone_stats(_two_logs(), [PHI_10])[0]
        assert z["net"] == pytest.approx(40.0)
        assert z["ntg"] == pytest.approx(0.4)
        phi = next(c for c in z["curves"] if c["name"] == "PHI")
        assert phi["n_pay"] == 2                 # 120 and 140; 160 is the bound
        assert phi["mean_pay"] == pytest.approx(0.16)

    def test_pore_thickness_from_the_kinds(self):
        z = zone_stats(_two_logs(), [PHI_10])[0]
        # phi·h over [120,140) + [140,160): 0.12·20 + 0.20·20.
        assert z["phih"] == pytest.approx(6.4)
        # phi(1−Sw)·h: 0.12·0.6·20 + 0.20·0.7·20.
        assert z["hcph"] == pytest.approx(4.24)

    def test_percent_curves_are_scaled_to_fractions(self):
        w = _two_logs()
        w["tracks"][0]["curves"][0]["unit"] = "%"
        w["tracks"][0]["curves"][0]["samples"] = [
            [v * 100 if v is not None else None, d]
            for v, d in w["tracks"][0]["curves"][0]["samples"]]
        z = zone_stats(w, [{"curve": "PHI", "op": ">=", "value": 10}])[0]
        assert z["phih"] == pytest.approx(6.4)

    def test_no_saturation_curve_leaves_hcph_unset(self):
        w = _two_logs()
        w["tracks"] = w["tracks"][:1]
        z = zone_stats(w, [PHI_10])[0]
        assert z["phih"] == pytest.approx(6.4) and z["hcph"] is None

    def test_rule_on_a_missing_curve_is_not_evaluable(self):
        # The well has no GR: nothing to shade, yet not a sterile well.
        # Every figure that rests on the pay is None, and the zone says why.
        gr = {"curve": "GR", "op": "<", "value": 60}
        assert pay_intervals(_two_logs(), [gr]) == []
        assert missing_rule_curves(_two_logs(), [gr]) == ["GR"]
        z = zone_stats(_two_logs(), [gr])[0]
        assert z["pay_na"] == ["GR"]
        assert (z["net"], z["ntg"], z["phih"], z["hcph"]) == (None,) * 4
        assert all(c["n_pay"] is None and c["mean_pay"] is None
                   for c in z["curves"])

    def test_one_missing_rule_among_two_names_only_the_missing_one(self):
        gr = {"curve": "GR", "op": "<", "value": 60}
        assert missing_rule_curves(_two_logs(), [PHI_10, gr, gr]) == ["GR"]
        assert zone_stats(_two_logs(), [PHI_10, gr])[0]["net"] is None

    def test_no_pay_is_an_honest_zero(self):
        # The curve is there and nothing passes: zero net, zero N/G, no dash.
        z = zone_stats(_two_logs(), [{"curve": "PHI", "op": ">=", "value": 0.99}])[0]
        assert z["pay_na"] == []
        assert (z["net"], z["ntg"], z["phih"]) == (0.0, 0.0, 0.0)
        phi = next(c for c in z["curves"] if c["name"] == "PHI")
        assert phi["n_pay"] == 0 and phi["mean_pay"] is None

    def test_with_cutoffs_carries_the_missing_curves_on_the_well(self):
        gr = {"curve": "GR", "op": "<", "value": 60}
        out = with_cutoffs({"wells": [_two_logs()], "markers": []}, [gr])
        w = out["wells"][0]
        assert w["pay"] == [] and w["pay_na"] == ["GR"]
        assert w["pay_na_why"] == {"GR": "unlogged"}
        ok = with_cutoffs({"wells": [_two_logs()], "markers": []}, [PHI_10])
        assert ok["wells"][0]["pay_na"] == []
        assert ok["wells"][0]["pay_na_why"] == {}

    def test_half_typed_rule_is_ignored(self):
        assert pay_intervals(_two_logs(), [{"curve": "PHI", "op": ">=",
                                            "value": ""}]) == []

    def test_sample_and_hold_across_two_depth_grids(self):
        w = _two_logs()
        # SW logged coarser: at 140 it holds the 0.4 of 120, at 150 it is 0.6.
        w["tracks"][1]["curves"][0]["samples"] = [[0.9, 100], [0.4, 120], [0.6, 150]]
        assert pay_intervals(w, [PHI_10, SW_50]) == [[120.0, 150.0]]

    def test_with_cutoffs_returns_a_new_payload_and_keeps_the_input(self):
        w = _two_logs()
        base = {"wells": [w], "markers": [], "flattenOn": None}
        out = with_cutoffs(base, [PHI_10])
        assert out is not base
        assert out["wells"][0]["pay"] == [[120.0, 160.0]]
        assert out["wells"][0]["zones"][0]["ntg"] == pytest.approx(0.4)
        assert "pay" not in w and "zones" not in w


def _with_neutron(first):
    """`_two_logs` plus a neutron porosity, placed before or after PHI.

    The neutron porosity kind also says "porosity", so it competes with PHI
    for the porosity pick in track order."""
    w = _two_logs()
    nphi = {"kind": "neutron porosity",
            "curves": [_curve("NPHI", [(0.3, 100), (0.3, 180)], "v/v")]}
    w["tracks"].insert(0 if first else 1, nphi)
    return w


class TestSummationDisclosure:
    def test_names_the_curves_it_reads(self):
        assert summation_curves(_two_logs()) == {
            "phi": "PHI", "phi_candidates": ["PHI"], "phi_absent": {},
            "sw": "SW", "sw_candidates": ["SW"], "sw_absent": {}}

    def test_first_of_the_kind_is_picked_and_the_others_are_listed(self):
        # The pick is the first porosity in track order (PHI or NPHI), and
        # the report lists the other, so the reader can tell which was used.
        s = summation_curves(_with_neutron(first=False))
        assert (s["phi"], s["phi_candidates"]) == ("PHI", ["PHI", "NPHI"])
        s = summation_curves(_with_neutron(first=True))
        assert (s["phi"], s["phi_candidates"]) == ("NPHI", ["NPHI", "PHI"])

    def test_disclosure_matches_the_figure(self):
        # Φ·h is read from the curve the disclosure names.
        z = zone_stats(_with_neutron(first=True), [PHI_10])[0]
        assert z["phih"] == pytest.approx(0.3 * 40.0)      # NPHI, not PHI

    def test_no_curve_of_the_kind(self):
        w = _two_logs()
        w["tracks"] = w["tracks"][1:]                      # SW only
        assert summation_curves(w) == {
            "phi": None, "phi_candidates": [], "phi_absent": {},
            "sw": "SW", "sw_candidates": ["SW"], "sw_absent": {}}

    def test_an_absent_porosity_is_named_with_why(self):
        # The well logs a porosity that is unticked: "no porosity" would be
        # false, so the report names it and says it is unticked.
        w = _two_logs()
        w["tracks"] = w["tracks"][1:]                      # SW only
        w["absent"] = {"PHIE": {"kind": "effective porosity", "why": "unticked"},
                       "GR": {"kind": "gamma ray", "why": "unticked"}}
        s = summation_curves(w)
        assert s["phi"] is None
        assert s["phi_absent"] == {"PHIE": "unticked"}
        assert s["sw_absent"] == {}

    def test_with_cutoffs_carries_the_disclosure_on_the_well(self):
        out = with_cutoffs({"wells": [_two_logs()], "markers": []}, [PHI_10])
        assert out["wells"][0]["summation"]["phi"] == "PHI"
        base = {"wells": [_two_logs()], "markers": []}
        assert "summation" not in with_cutoffs(base, [])["wells"][0]


class TestAbsentWhy:
    """The reason given for an absent log is the true one.

    Ticked, logged and readable are three different things, and the panel
    must show which one failed."""

    def test_unticked_is_told_from_unlogged(self):
        w = _two_logs()
        w["absent"] = {"GR": {"kind": "gamma ray", "why": "unticked"}}
        assert absent_why(w, "GR") == "unticked"
        assert absent_why(w, "RHOB") == "unlogged"

    def test_unreadable_is_told_from_both(self):
        w = _two_logs()
        w["absent"] = {"GR": {"kind": "gamma ray", "why": "unreadable"}}
        assert absent_why(w, "GR") == "unreadable"

    def test_a_payload_without_the_record_says_unlogged(self):
        assert absent_why(_two_logs(), "GR") == "unlogged"

    def test_with_cutoffs_gives_every_missing_rule_curve_its_reason(self):
        w = _two_logs()
        w["absent"] = {"GR": {"kind": "gamma ray", "why": "unticked"}}
        rules = [{"curve": "GR", "op": "<", "value": 60},
                 {"curve": "RHOB", "op": "<", "value": 2.5}, PHI_10]
        out = with_cutoffs({"wells": [w], "markers": []}, rules)["wells"][0]
        assert out["pay_na"] == ["GR", "RHOB"]
        assert out["pay_na_why"] == {"GR": "unticked", "RHOB": "unlogged"}
        assert out["zones"][0]["net"] is None


def _two_wells_tree():
    """Two wellbores logging the same suite, as the assembly presents them.

    Each well holds GR and PHIE under one frame; there is no enum table, so
    the class names route the walk. Returns the tree and
    ``{(well, channel): path}``."""
    asm = FakeDataAssembly()
    paths = {}
    for wname in ("W1", "W2"):
        wid = asm.add_node_with_attrs(f"_{wname}", 0, title=wname,
                                      type="Wellbore")
        fid = asm.add_node_with_attrs(f"_{wname}_frame", wid, title="frame",
                                      type="Frame")
        for cname, kind in (("GR", "gamma ray"), ("PHIE", "effective porosity")):
            cid = asm.add_node_with_attrs(
                f"_{wname}_{cname}", fid, title=cname,
                type="ContinuousProperty", propertyKind=kind, uom="u")
            paths[(wname, cname)] = asm.GetNodePath(cid)
    return Tree(asm), paths


class _Registry:
    def shared_source(self):
        return object()


class TestBuildPayloadAbsent:
    """`build_payload` records, per well, the channels left out and why.

    These are the channels it did not turn into a curve; the panel's
    reasons rest on this record."""

    @pytest.fixture
    def reads(self, monkeypatch):
        # The block of a channel is the channel's own path; the samples read
        # off it come from this table (a path absent here reads nothing).
        table = {}
        monkeypatch.setattr(welllog_dispatch, "_fetch_block",
                            lambda shared, path: path)
        monkeypatch.setattr(welllog_dispatch, "_ring_samples",
                            lambda path, name: table.get(path, []))
        return table

    def _payload(self, tree, paths, reads, checked):
        wells = ["/data/_W1", "/data/_W2"]
        for path in paths.values():
            reads.setdefault(path, [(1.0, 10.0, None), (2.0, 20.0, None)])
        out = build_payload(tree, _Registry(), wells, checked)
        return {w["name"]: w for w in out["wells"]}

    def test_unticked_on_one_well_is_recorded_as_such(self, reads):
        tree, paths = _two_wells_tree()
        checked = [p for (w, c), p in paths.items()
                   if not (w == "W2" and c == "GR")]
        wells = self._payload(tree, paths, reads, checked)
        assert wells["W1"]["absent"] == {}
        assert wells["W2"]["absent"] == {"GR": {"kind": "gamma ray",
                                                "why": "unticked"}}
        # The slot stays in the track, empty.
        gr2 = next(c for t in wells["W2"]["tracks"] for c in t["curves"]
                   if c["name"] == "GR")
        assert gr2["missing"] and gr2["samples"] == []

    def test_a_cutoff_on_it_says_unticked_never_unlogged(self, reads):
        tree, paths = _two_wells_tree()
        checked = [p for (w, c), p in paths.items()
                   if not (w == "W2" and c == "GR")]
        wells = self._payload(tree, paths, reads, checked)
        cut = with_cutoffs({"wells": list(wells.values()), "markers": []},
                           [{"curve": "GR", "op": ">=", "value": 0.5}])
        by = {w["name"]: w for w in cut["wells"]}
        assert by["W1"]["pay_na"] == [] and by["W1"]["pay"] == [[10.0, 20.0]]
        assert by["W2"]["pay_na"] == ["GR"]
        assert by["W2"]["pay_na_why"] == {"GR": "unticked"}

    def test_ticked_but_unreadable_is_recorded_as_such(self, reads):
        # Two ways a ticked channel yields no curve: nothing comes back off
        # its block, or nothing but gaps does.
        tree, paths = _two_wells_tree()
        reads[paths[("W2", "PHIE")]] = []
        reads[paths[("W1", "GR")]] = [(None, 10.0, None), (None, 20.0, None)]
        wells = self._payload(tree, paths, reads, list(paths.values()))
        assert wells["W1"]["absent"] == {
            "GR": {"kind": "gamma ray", "why": "unreadable"}}
        assert wells["W2"]["absent"] == {
            "PHIE": {"kind": "effective porosity", "why": "unreadable"}}
        assert summation_curves(wells["W2"])["phi_absent"] == {
            "PHIE": "unreadable"}

    def test_a_channel_read_from_another_frame_is_not_absent(self, reads):
        tree, paths = _two_wells_tree()
        asm = tree._data_assembly
        w1 = asm.GetFirstNodeByPath("/data/_W1")
        f2 = asm.add_node_with_attrs("_W1_frame2", w1, title="frame 2",
                                     type="Frame")
        c2 = asm.add_node_with_attrs("_W1_GR2", f2, title="GR",
                                     type="ContinuousProperty",
                                     propertyKind="gamma ray")
        assert asm.GetNodePath(c2) not in paths.values()
        wells = self._payload(tree, paths, reads, list(paths.values()))
        assert wells["W1"]["absent"] == {}


class TestFullResolution:
    def test_statistics_read_the_undecimated_samples(self, well):
        # What is drawn may be decimated; `_full` carries every sample.
        well["_full"] = {"PHI": [[0.1, 110], [0.1, 120], [0.1, 130], [0.1, 140],
                                 [0.9, 210], [0.9, 220]]}
        z = zone_stats(well)
        assert z[0]["curves"][0]["n"] == 4 and z[0]["curves"][0]["mean"] == pytest.approx(0.1)
        assert z[1]["curves"][0]["n"] == 2 and z[1]["curves"][0]["mean"] == pytest.approx(0.9)

    def test_pay_uses_the_full_samples(self, well):
        well["_full"] = {"PHI": [[0.05, 110], [0.30, 120], [0.30, 130], [0.05, 140]]}
        assert pay_intervals(well, [{"curve": "PHI", "op": ">=", "value": 0.2}]) == [[120.0, 140.0]]


def test_zones_csv_payload_names_wells_source_cutoffs_and_reads():
    import re
    from fespp_on_trame.engine import welllog_dispatch as wd
    payload = {"wells": [
        {"name": "W1", "depthRef": "MD",
         "zones": [{"name": "A", "source": "frame"}],
         "summation": {"phi": "PHIT", "sw": None}},
        {"name": "W2", "depthRef": "TVD", "zones": []},
    ]}
    pl = wd.zones_csv_payload(payload, [{"curve": "PHIT", "op": ">=", "value": 0.1},
                                        {"curve": "", "op": ">=", "value": 1}])
    assert re.fullmatch(r"zones_W1_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    h = pl["header"]
    assert "# wells: W1" in h
    assert "# zones source: frame" in h
    assert "# cutoffs: PHIT >= 0.1" in h
    assert "# summation logs: W1: porosity PHIT, water saturation none" in h
    assert any(line.startswith("# depths: top and base in each well's own"
                               " drawing axis") for line in h)
    # The file says which axis every thickness was summed on...
    assert any(line.startswith("# thicknesses: gross_tvd, net_tvd, phih_tvd and"
                               " hcph_tvd are integrated on TRUE VERTICAL DEPTH")
               for line in h)
    # ...and that the along-hole gross beside them is an interval, not rock.
    assert any("gross (depth_axis) is the along-hole interval the zone band"
               " is drawn over, not a thickness of rock" in line for line in h)
    two = {"wells": [dict(payload["wells"][0]), dict(payload["wells"][0], name="W3")]}
    pl = wd.zones_csv_payload(two, [])
    assert re.fullmatch(r"zones_2_wells_\d{4}-\d{2}-\d{2}\.csv", pl["name"])
    assert "# cutoffs: none" in pl["header"]
    assert wd.zones_csv_payload({"wells": [{"name": "W", "zones": []}]}) == {
        "name": "", "header": []}


# ---- the two axes: drawn along the hole, integrated on the vertical -------
# An analytic well: a constant 60 degrees from vertical, so cos 60 = 0.5
# exactly and TVD = MD / 2 over the whole logged interval. Every figure
# asserted below is derived by hand from these numbers, never read off a run.
_MD60 = [1000.0 + 20.0 * i for i in range(11)]     # 1000 … 1200, TVD 500 … 600
_PHI60 = [0.20, 0.20, 0.05, 0.05, 0.20, 0.10, 0.10, 0.02, 0.02, 0.02, 0.02]
_SW60 = [0.30, 0.30, 0.90, 0.90, 0.30, 0.50, 0.50, 0.95, 0.95, 0.95, 0.95]
_PAY_RULE = {"curve": "PHI", "op": ">=", "value": 0.10}


def _sixty_degree_well(monkeypatch, synthetic=False):
    """The 60° well, built through `build_payload` and cut on `_PAY_RULE`.

    Three marker picks at MD 1000 / 1100 / 1200 (TVD 500 / 550 / 600) and
    the two curves above, read off stubbed blocks. With `synthetic`, one
    grid-sampled curve carrying no measured depth is admitted: the whole
    well then falls back to TVD for drawing, which is exactly the change
    that must move no figure."""
    asm = FakeDataAssembly()
    wid = asm.add_node_with_attrs("_W60", 0, title="W60", type="Wellbore")
    fid = asm.add_node_with_attrs("_W60_frame", wid, title="frame", type="Frame")
    reads, marks = {}, {}
    for name, kind, values in (("PHI", "porosity", _PHI60),
                               ("SW", "water saturation", _SW60)):
        cid = asm.add_node_with_attrs(f"_W60_{name}", fid, title=name,
                                      type="ContinuousProperty",
                                      propertyKind=kind, uom="v/v")
        reads[asm.GetNodePath(cid)] = [(v, md / 2.0, md)
                                       for v, md in zip(values, _MD60)]
    for nm, md in (("TopA", 1000.0), ("TopB", 1100.0), ("TopC", 1200.0)):
        mid = asm.add_node_with_attrs(f"_W60_{nm}", wid, title=nm, type="Marker")
        marks[asm.GetNodePath(mid)] = (md / 2.0, md)
    monkeypatch.setattr(welllog_dispatch, "_fetch_block",
                        lambda shared, path: path)
    monkeypatch.setattr(welllog_dispatch, "_ring_samples",
                        lambda path, name: reads.get(path, []))
    monkeypatch.setattr(welllog_dispatch, "_marker_depth",
                        lambda path: marks.get(path))
    wpath = asm.GetNodePath(wid)
    synth = None
    if synthetic:
        synth = {wpath: [{"name": "PORO (grid)", "unit": "v/v",
                          "kind": "porosity",
                          "samples": [[0.11, md / 2.0, None] for md in _MD60]}]}
    payload = build_payload(Tree(asm), _Registry(), [wpath],
                            list(reads) + list(marks), synthetics=synth)
    return with_cutoffs(payload, [_PAY_RULE])["wells"][0]


@pytest.fixture
def well60(monkeypatch):
    return _sixty_degree_well(monkeypatch)


def _zone(well, name):
    return next(z for z in well["zones"] if z["name"] == name)


def _curve_of(zone, name):
    return next(c for c in zone["curves"] if c["name"] == name)


class TestTvdIntegration:
    """Thicknesses integrate on the vertical, hand-derived on the 60° well.

    The pay is walked on the vertical sample depths, sample-and-hold, each
    stretch carrying the flag of its top:

        500 .20 ok -> open    520 .05 no -> close [500, 520]
        540 .20 ok -> open    570 .02 no -> close [540, 570]

    so pay(TVD) = [[500, 520], [540, 570]]."""

    def test_the_drawn_axis_is_the_hole_and_the_integration_the_vertical(self, well60):
        assert well60["depthRef"] == "MD"
        assert well60["integrationRef"] == "TVD"
        assert well60["depth"] == {"min": 1000.0, "max": 1200.0}
        assert well60["tvd_up_hole"] == 0.0

    def test_gross_and_net_are_vertical_thicknesses(self, well60):
        # Zone A = MD [1000, 1100) = TVD [500, 550): gross = 550 - 500 = 50,
        # net = (520 - 500) + (550 - 540) = 20 + 10 = 30.
        # Zone B = TVD [550, 600): gross = 50, net = 570 - 550 = 20.
        # Along the hole both would be doubled (100 / 60 and 100 / 40).
        a, b = _zone(well60, "TopA → TopB"), _zone(well60, "TopB → TopC")
        assert (a["top_tvd"], a["bottom_tvd"], a["thickness_tvd"]) == (500.0, 550.0, 50.0)
        assert (a["top"], a["bottom"], a["thickness"]) == (1000.0, 1100.0, 100.0)
        assert a["net"] == pytest.approx(30.0)
        assert b["net"] == pytest.approx(20.0)
        assert a["tvd_na"] is None and b["tvd_na"] is None

    def test_ntg_is_the_ratio_of_two_vertical_thicknesses(self, well60):
        # 30 / 50 and 20 / 50: a ratio is the same along the hole and on the
        # vertical.
        assert _zone(well60, "TopA → TopB")["ntg"] == pytest.approx(0.60)
        assert _zone(well60, "TopB → TopC")["ntg"] == pytest.approx(0.40)

    def test_phih_and_hcph_integrate_on_the_vertical(self, well60):
        # A: 0.20*10 (500->510) + 0.20*10 (510->520) + 0.20*10 (540->550) = 6.00
        #    each stretch * (1 - 0.30)                                    = 4.20
        # B: 0.10*10 (550->560) + 0.10*10 (560->570)                      = 2.00
        #    * (1 - 0.50)                                                 = 1.00
        a, b = _zone(well60, "TopA → TopB"), _zone(well60, "TopB → TopC")
        assert a["phih"] == pytest.approx(6.00)
        assert a["hcph"] == pytest.approx(4.20)
        assert b["phih"] == pytest.approx(2.00)
        assert b["hcph"] == pytest.approx(1.00)

    def test_the_pay_band_is_published_on_the_axis_it_is_drawn_against(self, well60):
        """`pay` is published on the drawn axis, `pay_tvd` on the vertical.

        The band is shaded with the drawing scale (the renderer builds it
        from `depth.min` / `depth.max`), so what is published as `pay` is the
        vertical pay read back on the hole: TVD [500, 520] and [540, 570] are
        MD [1000, 1040] and [1080, 1140] on a well inclined at 60°, both
        inside the 1000–1200 m track. Published on the vertical instead, the
        two bands would sit 500 m above the top of the track and shade
        nothing at all, while Net still reported 30 m of pay."""
        assert well60["pay_tvd"] == [[500.0, 520.0], [540.0, 570.0]]
        assert well60["pay"] == [[1000.0, 1040.0], [1080.0, 1140.0]]
        lo, hi = well60["depth"]["min"], well60["depth"]["max"]
        assert all(lo <= a <= hi and lo <= b <= hi for a, b in well60["pay"])

    def test_the_curve_statistics_do_not_move(self, well60):
        # The vertical bound selects exactly the samples the measured-depth
        # bound does: A holds TVD 500…540 (PHI .20 .20 .05 .05 .20), of which
        # 500, 510 and 540 are pay; B holds 550…590 (.10 .10 .02 .02 .02).
        a = _curve_of(_zone(well60, "TopA → TopB"), "PHI")
        assert (a["n"], a["mean"]) == (5, pytest.approx(0.140))
        assert (a["n_pay"], a["mean_pay"]) == (3, pytest.approx(0.20))
        b = _curve_of(_zone(well60, "TopB → TopC"), "PHI")
        assert (b["n"], b["mean"]) == (5, pytest.approx(0.052))
        assert (b["n_pay"], b["mean_pay"]) == (2, pytest.approx(0.10))


def test_a_synthetic_log_leaves_every_figure_alone(monkeypatch):
    """A grid-sampled curve changes the drawing axis and no figure.

    The synthetic curve carries no measured depth, so it flips the drawing
    axis to TVD, and it must move nothing else: the same zone bounds on the
    vertical, the same net, N/G, phi*h, phi(1-Sw)*h, and the same per-curve
    statistics."""
    plain = _sixty_degree_well(monkeypatch, synthetic=False)
    withgrid = _sixty_degree_well(monkeypatch, synthetic=True)
    assert (plain["depthRef"], withgrid["depthRef"]) == ("MD", "TVD")
    keys = ("name", "source", "top_tvd", "bottom_tvd", "thickness_tvd",
            "tvd_na", "net", "ntg", "phih", "hcph")

    def figures(well):
        return [dict({k: z.get(k) for k in keys},
                     curves={c["name"]: c for c in z["curves"]
                             if c["name"] in ("PHI", "SW")})
                for z in well["zones"]]
    assert figures(plain) == figures(withgrid)
    # The drawn axis does move, so the comparison above is not vacuous.
    assert [z["top"] for z in plain["zones"]] == [1000.0, 1100.0]
    assert [z["top"] for z in withgrid["zones"]] == [500.0, 550.0]
    # The pay follows the drawing axis: the same rock, shaded against
    # whichever axis the track is scaled on. On a well drawn vertically the
    # two published lists coincide.
    assert plain["pay_tvd"] == withgrid["pay_tvd"]
    assert withgrid["pay"] == withgrid["pay_tvd"]
    assert plain["pay"] == [[2 * a, 2 * b] for a, b in plain["pay_tvd"]]


def test_build_payload_emits_triplets(monkeypatch):
    for synthetic in (False, True):
        well = _sixty_degree_well(monkeypatch, synthetic=synthetic)
        for name, pts in well["_full"].items():
            assert all(len(p) == 3 for p in pts), name
            assert all(isinstance(p[2], float) for p in pts), name
        # Slot 1 is the drawn axis, slot 2 is always the vertical.
        assert well["_full"]["PHI"][0][1:] == (
            [500.0, 500.0] if synthetic else [1000.0, 500.0])


def test_zone_bounds_carry_both_depths(monkeypatch, well60):
    # From the marker source: the picks' own two depths.
    a = _zone(well60, "TopA → TopB")
    assert (a["top"], a["top_tvd"]) == (1000.0, 500.0)
    assert (a["bottom"], a["bottom_tvd"]) == (1100.0, 550.0)
    assert all(tp["tvd"] == tp["depth"] / 2.0 for tp in well60["tops"])
    # From the column source: the band is laid onto the drawn axis, and each
    # bound is mapped back to the vertical through the well's own samples.
    from fespp_on_trame.engine import stratigraphy
    monkeypatch.setattr(stratigraphy, "intervals_for_tops",
                        lambda columns, tops: {"rock": [
                            {"name": "Fm", "kind": "f", "parent": None,
                             "color": "#aaa", "top": 1020.0, "bottom": 1100.0}]})
    lanes = welllog_dispatch._strati_intervals(
        ["a column"], well60["tops"], welllog_dispatch._tvd_of_draw(well60))
    band = lanes["rock"][0]
    # 1100 is a pick (exact), 1020 sits between two samples (interpolated).
    assert (band["top_tvd"], band["bottom_tvd"]) == (510.0, 550.0)
    zones, source = zone_intervals(dict(well60, strati=lanes))
    assert source == "frame"
    assert (zones[0]["top"], zones[0]["top_tvd"]) == (1020.0, 510.0)


def test_a_zone_of_zero_vertical_thickness_is_kept_and_says_why():
    # Two picks 100 m apart along the hole at the same true vertical depth:
    # a horizontal section. There is no rock thickness to sum, and reporting
    # 100 m would be false, but the samples are still worth reporting.
    w = {"name": "H1", "strati": {},
         "tops": [{"name": "A", "depth": 1000.0, "tvd": 500.0},
                  {"name": "B", "depth": 1100.0, "tvd": 500.0}],
         "tracks": [{"kind": "porosity", "curves": [{"name": "PHI", "unit": "v/v"}]}],
         "_full": {"PHI": [[0.20, 1010.0, 500.0], [0.30, 1050.0, 500.0]]}}
    z = zone_stats(w, [_PAY_RULE])[0]
    assert z["tvd_na"] == ("the zone's two bounds sit at the same or an"
                           " inverted true vertical depth (a horizontal or"
                           " re-entrant section): no vertical thickness to sum")
    assert (z["thickness_tvd"], z["net"], z["ntg"], z["phih"], z["hcph"]) == (None,) * 5
    assert z["thickness"] == 100.0          # the drawn bounds are kept
    phi = _curve_of(z, "PHI")
    assert (phi["n"], phi["mean"]) == (2, pytest.approx(0.25))
    # The other reason: a bound the column cannot map to a vertical depth.
    w2 = dict(w, tops=[], strati={"rock": [
        {"name": "Fm", "color": None, "top": 1000.0, "bottom": 1100.0,
         "top_tvd": None, "bottom_tvd": 550.0}]})
    z2 = zone_stats(w2, [_PAY_RULE])[0]
    assert z2["tvd_na"] == ("the zone bounds have no true vertical depth on"
                            " this well")
    assert z2["net"] is None and _curve_of(z2, "PHI")["n"] == 2


def test_a_well_that_comes_back_up_is_counted_and_declared():
    # TVD 500, 520, 540, 530, 550: the fourth sample is 10 m higher than the
    # third. The stretch 530-540 is drilled twice and must count once: net is
    # 550 - 500 = 50, never 60, and phi*h is 0.20 * 50 = 10.
    tvds = [500.0, 520.0, 540.0, 530.0, 550.0]
    pts = [[0.20, 1000.0 + 20.0 * i, t] for i, t in enumerate(tvds)]
    assert welllog_dispatch.up_hole_tvd(pts) == pytest.approx(10.0)
    w = {"name": "U1", "strati": {},
         "tops": [{"name": "A", "depth": 1000.0, "tvd": 500.0},
                  {"name": "B", "depth": 1080.0, "tvd": 550.0}],
         "tracks": [{"kind": "porosity", "curves": [{"name": "PHI", "unit": "v/v"}]}],
         "_full": {"PHI": pts}}
    z = zone_stats(w, [_PAY_RULE])[0]
    assert z["thickness_tvd"] == pytest.approx(50.0)
    assert z["net"] == pytest.approx(50.0)
    assert z["ntg"] == pytest.approx(1.0)
    assert z["phih"] == pytest.approx(10.0)


def test_a_pair_shaped_sample_is_read_as_vertical():
    # The fixture form [value, depth]: the one depth is the vertical.
    assert welllog_dispatch._tvd_pairs([[1.0, 5.0], [2.0, 7.0]]) == [(1.0, 5.0), (2.0, 7.0)]
    assert welllog_dispatch._triples([[1.0, 5.0]]) == [(1.0, 5.0, 5.0)]
    # A triplet keeps the two apart, and a sample with no drawn depth is
    # dropped.
    assert welllog_dispatch._triples([[1.0, 9.0, 4.0], [2.0, None, 4.0]]) == [(1.0, 9.0, 4.0)]


def test_a_track_has_one_value_scale_for_the_measured_and_the_synthetic(monkeypatch):
    """A measured log and a synthetic log in one track share one value axis.

    A synthetic log is drawn in the track of its kind to be read against
    the measured log. The track's range is the span of every curve in it;
    each curve keeps its own span for the header. A flat synthetic at 0.11
    against a porosity spanning 0.02-0.20: the track spans 0.02-0.20,
    whereas the synthetic alone would draw a line across the whole track."""
    well = _sixty_degree_well(monkeypatch, synthetic=True)
    track = next(t for t in well["tracks"] if t["kind"] == "porosity")
    names = {c["name"]: c for c in track["curves"]}
    assert set(names) == {"PHI", "PORO (grid)"}
    assert names["PHI"]["range"] == [pytest.approx(0.02), pytest.approx(0.20)]
    assert names["PORO (grid)"]["range"] == [pytest.approx(0.11), pytest.approx(0.11)]
    assert names["PORO (grid)"]["synthetic"] is True
    assert track["range"] == [pytest.approx(0.02), pytest.approx(0.20)]
    # A track whose only curve is flat still spans something to draw on.
    sw = next(t for t in well["tracks"] if t["kind"] != "porosity")
    assert sw["range"][0] < sw["range"][1]


def test_a_cutoff_can_be_an_equality_on_a_discrete_log():
    """A cutoff on a discrete log can test equality with a code.

    For a facies code, pay is where the log equals the code, and ≠ is its
    complement; a rule with an unknown operator is skipped."""
    from fespp_on_trame.engine.welllog_dispatch import _rules
    rules = _rules([{"curve": "FACIES", "op": "=", "value": 3},
                    {"curve": "FACIES", "op": "≠", "value": 3},
                    {"curve": "FACIES", "op": "?", "value": 3}])
    assert len(rules) == 2
    eq, ne = rules[0][1], rules[1][1]
    assert eq(3.0, 3.0) and not eq(2.0, 3.0)
    assert ne(2.0, 3.0) and not ne(3.0, 3.0)


# ---- the band the marker frame STATES (2026-10-10) ------------------------
def test_frame_bands_come_from_the_frame_s_own_assignment_only():
    from fespp_on_trame.engine.welllog_dispatch import frame_bands, _md_to_tvd
    fields = {"title": "Frame", "md": "1000;1100;1200;1300;1400",
              "marker.0": "m0|Top A", "marker.1": "m1|Top B", "marker.2": "m2|Top C",
              "unit.0": "u-a|Fm A", "unit.1": "u-b|Fm B",
              "interval_units": "0;0;null;1"}
    columns = [{"entities": [{"name": "Fm B", "color": "#123456"}]}]
    bands = frame_bands(fields, columns)
    # two intervals of one unit are one band; a null interval is a gap; the
    # colour is the loaded column's for the unit of the same title, else grey
    assert [(b["name"], b["top"], b["bottom"], b["color"]) for b in bands] == [
        ("Fm A", 1000.0, 1200.0, "#c8c8c8"), ("Fm B", 1300.0, 1400.0, "#123456")]
    # the marker titles alone say nothing: no assignment, no band
    assert frame_bands({"md": "1000;1100", "marker.0": "m0|Hugin Fm Top"}) == []
    assert frame_bands({"md": "1000;1100", "interval_units": "3", "unit.0": "u|A"}) == []   # an index the occurrence does not list
    assert frame_bands({"md": "1000", "interval_units": "0", "unit.0": "u|A"}) == []
    # SKUA's "|UNNAMED|" placeholder is no name: the band is named by the
    # unit's uuid rather than by the placeholder (the plugin itself hands the
    # feature's name in that case)
    assert [b["name"] for b in frame_bands(
        {"md": "1000;1100", "interval_units": "0", "unit.0": "u-x||UNNAMED|"})] == ["u-x"]
    # MD -> TVD through the markers' own pairs, clamped at the ends
    pairs = [(1000.0, 500.0), (1200.0, 600.0)]
    assert _md_to_tvd(pairs, 1100.0) == 550.0 and _md_to_tvd(pairs, 900.0) == 500.0 and _md_to_tvd(pairs, 1300.0) == 600.0


def test_marker_frames_found_by_the_type_the_reader_writes():
    # a plugin without the enum table: no role, the tree types the marker
    # frame 'MarkerFrame' (as Data health reads it) — the fallback finds it
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_well", 0, label="Wellbore_W", title="W-1",
                                   type="Wellbore")
    frame = asm.add_node_with_attrs("_mf", well, label="MarkerFrame_M", title="Tops",
                                    type="MarkerFrame")
    asm.add_node_with_attrs("_lf", well, label="Frame_L", title="Logs", type="Frame")
    tree = Tree(asm)
    found = welllog_dispatch._descendants_of_kinds(
        tree, well, welllog_dispatch._MARKER_FRAME_ROLES, welllog_dispatch._MARKER_FRAME_KINDS)
    assert found == [frame]
