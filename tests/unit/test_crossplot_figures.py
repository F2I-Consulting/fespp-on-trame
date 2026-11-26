"""Tests for engine/crossplot_dispatch: the multi-chart figure builder, and
finding the chart a selection was drawn on from its axis ids.

Pure functions over a fake assembly; no ParaView (conftest stubs it).
"""
import pytest

from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.engine import crossplot_dispatch as xd


def _tree():
    """Two grids: PORO, NTG and FACIES on grid A, SW on grid B."""
    asm = FakeDataAssembly()
    grid_a = asm.add_node_with_attrs("_gridA", 0, label="IjkGrid_A", title="A",
                                     type="IjkGrid", typeCode="2")
    grid_b = asm.add_node_with_attrs("_gridB", 0, label="IjkGrid_B", title="B",
                                     type="IjkGrid", typeCode="2")
    poro = asm.add_node_with_attrs("_poro", grid_a, label="Properties_PORO",
                                   title="PORO", type="ContinuousProperty",
                                   typeCode="4")
    ntg = asm.add_node_with_attrs("_ntg", grid_a, label="Properties_NTG",
                                  title="NTG", type="ContinuousProperty",
                                  typeCode="4")
    facies = asm.add_node_with_attrs("_facies", grid_a,
                                     label="Properties_FACIES", title="FACIES",
                                     type="DiscreteProperty", typeCode="4")
    sw = asm.add_node_with_attrs("_sw", grid_b, label="Properties_SW",
                                 title="SW", type="ContinuousProperty",
                                 typeCode="4")
    tree = Tree(asm)
    paths = {k: asm.GetNodePath(n) for k, n in
             (("poro", poro), ("ntg", ntg), ("facies", facies), ("sw", sw))}
    return tree, paths


class TestChartKeyForSelection:
    AXES = {"pin:0": ["x", "y"], "live:0": ["x2", "y2"], "live:1": ["x3", "y3"]}

    def test_second_subplot_range(self):
        sel = {"range": {"x2": [0.1, 0.2], "y2": [0.3, 0.4]}, "lasso": None}
        assert xd.chart_key_for_selection(self.AXES, sel) == "live:0"

    def test_first_subplot_uses_bare_x_y(self):
        sel = {"range": {"x": [0, 1], "y": [0, 1]}}
        assert xd.chart_key_for_selection(self.AXES, sel) == "pin:0"

    def test_lasso_geometry_and_unknown_axes(self):
        sel = {"range": None, "lasso": {"x3": [0, 1, 1], "y3": [0, 0, 1]}}
        assert xd.chart_key_for_selection(self.AXES, sel) == "live:1"
        assert xd.chart_key_for_selection(
            self.AXES, {"range": {"x9": [0, 1], "y9": [0, 1]}}) is None
        assert xd.chart_key_for_selection(self.AXES, None) is None


class TestFigures:
    """The figure builder over fake values: one shared subsample, per-chart
    finite masks, pinned snapshots first, focus = a single subplot."""

    @pytest.fixture
    def values(self, monkeypatch):
        np = pytest.importorskip("numpy")
        pytest.importorskip("plotly")
        n = 50
        data = {
            "poro": np.linspace(0.0, 0.5, n),
            "ntg": np.where(np.arange(n) % 5 == 0, np.nan, 1.0),
            "facies": (np.arange(n) % 3).astype(float),
        }

        def fake_values(state, tree, source_registry, path, rep, real_idx=None,
                        ts_idx=None):
            return data[path.rsplit("_", 1)[-1].lower()]
        monkeypatch.setattr(xd, "_values_for", fake_values)
        monkeypatch.setattr(xd, "MAX_POINTS", 25)
        return data

    def test_grid_of_charts_and_axes_map(self, values):
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": None}, {"path": p["sw"]},
              {"path": p["poro"]}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, None)
        keys = [c["key"] for c in meta["charts"]]
        assert keys == ["live:0", "live:1", "live:2", "live:3"]
        # one drawn chart: the empty row, the other-grid row and the
        # diagonal are listed with their reason, not drawn
        assert meta["axes"] == {"live:0": ["x", "y"]}
        assert meta["drawn"] == ["live:0"] and len(figs) == 1
        fig = figs[0]
        assert meta["charts"][1]["note"] == ""
        assert "same grid" in meta["charts"][2]["note"]
        assert "diagonal" in meta["charts"][3]["note"]
        # stride 2 over 50 cells = 25 candidates, 5 of them NaN in NTG
        assert meta["total"] == 50 and meta["charts"][0]["kept"] == 20
        assert meta["kept"] == 20 and "1 point in 2" in meta["note"]
        trace = fig.to_plotly_json()["data"][0]
        assert trace["customdata"][:3] == [2, 4, 6]

    def test_pins_first_then_focus(self, values):
        tree, p = _tree()
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"]}, p["facies"])
        assert snap["kept"] == 20 and len(snap["traces"]) == 3
        ys = [{"path": p["ntg"]}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["facies"], pins=[snap])
        assert [c["key"] for c in meta["charts"]] == ["pin:0", "live:0"]
        # every chart is a figure of its own: x / y each, in drawn order
        assert meta["charts"][0]["pinned"] and meta["axes"] == {
            "pin:0": ["x", "y"], "live:0": ["x", "y"]}
        assert meta["drawn"] == ["pin:0", "live:0"] and len(figs) == 2
        data = _traces(figs)
        assert len(data) == 6
        # the legend once per category: the pinned chart's traces carry it
        assert [t["showlegend"] for t in data] == [True] * 3 + [False] * 3
        # kept = the candidate cells on screen, not the sum over the charts
        assert meta["kept"] == 20
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["facies"], pins=[snap],
            focus="live:0")
        assert meta["axes"] == {"live:0": ["x", "y"]}
        assert meta["focus"] == "live:0"
        assert len(figs) == 1 and len(_traces(figs)) == 3

    def test_legend_follows_the_categories_not_the_first_chart(self, values):
        tree, p = _tree()
        # an uncoloured pin leads; the categories still get their one entry,
        # on the first LIVE chart that carries them, and the layout shows it
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"]}, None)
        ys = [{"path": p["ntg"]}, {"path": p["facies"]}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["facies"], pins=[snap])
        data = _traces(figs)
        assert [t["showlegend"] for t in data] == [False] + [True] * 3 + [False] * 3
        # the figure that carries the entries shows the legend, the others not
        assert _legends(figs) == [False, True, False]
        # the reverse: a coloured pin, the live colour cleared — the pin's
        # legend is the only one and stays on
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"]}, p["facies"])
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], None,
            pins=[snap])
        assert [t["showlegend"] for t in _traces(figs)] == [True] * 3 + [False]
        assert _legends(figs) == [True, False]

    def test_the_film_gives_every_chart_its_own_legend(self, values):
        """In film mode every chart carries its own legend and colour bar.

        Only one chart is on screen at a time, so the once-per-grid rule would
        leave most charts without a legend or a colour bar."""
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": p["facies"]}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["facies"], film=True)
        assert _legends(figs) == [True, True]
        assert all(t["showlegend"] for t in _traces(figs))
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["poro"], film=True)
        assert [t["marker"]["showscale"] for t in _traces(figs)] == [True, True]

    def test_colorbar_once_on_the_first_coloured_chart(self, values, monkeypatch):
        tree, p = _tree()
        # 3 distinct values read as continuous once the category cap is 0
        monkeypatch.setattr(xd, "MAX_CATEGORIES", 0)
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"]}, None)
        ys = [{"path": p["ntg"]}, {"path": p["facies"]}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, p["facies"], pins=[snap])
        scales = [t["marker"].get("showscale") for t in _traces(figs)
                  if "colorscale" in t["marker"]]
        assert scales == [True, False]

    def test_four_charts_are_four_figures(self, values):
        tree, p = _tree()
        # the same property at another real / time is not the diagonal
        ys = [{"path": p["ntg"]}, {"path": p["facies"]},
              {"path": p["poro"], "real": 1}, {"path": p["poro"], "ts": 1}]
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, None)
        # the widget lays them out (rows of two, square): every figure is
        # a plain x / y chart with no title of its own
        assert meta["drawn"] == ["live:0", "live:1", "live:2", "live:3"]
        assert meta["axes"] == {k: ["x", "y"] for k in meta["drawn"]}
        assert len(figs) == 4
        for f in figs:
            js = f.to_plotly_json()
            assert len(js["data"]) == 1 and "xaxis2" not in js["layout"]
            assert not js["layout"].get("title")
        assert "real 1" in meta["charts"][2]["title"]
        # kept = the candidates, whichever chart: 25 (poro vs poro), not 90
        assert meta["kept"] == 25

    def test_log_y_masks_non_positive_values_per_chart(self, values):
        tree, p = _tree()
        ys = [{"path": p["facies"]}, {"path": p["ntg"]}]
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, None)
        assert [c["kept"] for c in meta["charts"]] == [25, 20]
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, None, log_y=True)
        # facies 0 at every even multiple of 3 = 9 candidates; NTG's NaN
        # mask is its own and unchanged by the log
        assert [c["kept"] for c in meta["charts"]] == [16, 20]

    def test_stale_focus_falls_back_to_the_grid_and_says_so(self, values):
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": p["facies"]}]
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], ys, None, focus="live:7")
        assert list(meta["axes"]) == ["live:0", "live:1"]
        assert meta["focus"] is None

    def test_pin_label_only_when_both_axes_agree(self, values):
        tree, p = _tree()
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["poro"], "real": 4}, None,
                                 x_real=3)
        # real 3 vs real 4: the axis titles say it, the label would lie
        assert snap["label"] == ""
        assert "real 3" in snap["x_title"] and "real 4" in snap["y_title"]
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"], "real": 3}, None, x_real=3)
        assert snap["label"] == "real 3"
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"], "real": 3}, None)
        assert snap["label"] == "real 3"

    def test_nothing_drawn_returns_no_figure_with_the_reason(self, values):
        tree, p = _tree()
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": None}], None)
        assert figs == [] and meta["drawn"] == [] and meta["kept"] == 0
        assert meta["note"] == ""
        # an unset row still has a chip to show: a placeholder, not a blank
        assert meta["charts"] == [{"key": "live:0", "title": "Y1 — no property",
                                   "pinned": False, "kept": 0,
                                   "nan_y": 0, "nonpos_y": 0,
                                   "note": "",
                                   "loading": False,
                                   "group": "live:0",
                                   "group_title": "Y1 — no property",
                                   "step_title": ""}]

    def test_the_plan_lists_the_charts_before_reading_them(self, values,
                                                            monkeypatch):
        """The plan names every chart without reading a single Y value.

        The widget draws every cell at once, each in a loading state, while
        the charts are read one by one; a chart is complete once
        `crossplot_chart` has run for it."""
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": None}]
        reads = []
        real_values = xd._values_for

        def counting(state, tree_, source_registry, path, rep, **kw):
            reads.append(path)
            return real_values(state, tree_, source_registry, path, rep, **kw)
        monkeypatch.setattr(xd, "_values_for", counting)
        plan = xd.crossplot_plan(None, tree, None, p["poro"], ys, None)
        assert reads == [p["poro"]], "the plan reads X and nothing else"
        heads = [xd.chart_public(h) for h in plan["heads"]]
        assert [h["key"] for h in heads] == ["live:0", "live:1"]
        assert heads[0]["loading"] and "NTG" in heads[0]["title"]
        assert not heads[1]["loading"] and heads[1]["note"] == ""
        c = xd.crossplot_chart(plan, 0, None, tree, None)
        assert reads == [p["poro"], p["ntg"]] and c["kept"] == 20
        assert not c["loading"]
        assert xd.crossplot_figure(plan, c) is not None
        assert xd.crossplot_figure(plan, xd.crossplot_chart(plan, 1, None, tree, None)) is None

    def test_past_the_webgl_budget_the_charts_are_svg_and_smaller(self, values):
        """Past GL_CHARTS charts, every trace is an SVG scatter over a smaller cloud.

        A browser holds only about sixteen WebGL contexts. The switch applies
        to every chart at once, so the candidate cells stay the same for all."""
        tree, p = _tree()
        few = xd.crossplot_plan(None, tree, None, p["poro"],
                                [{"path": p["ntg"]}], None)
        assert few["gl"] and few["ctx"]["stride"] == 2
        many = xd.crossplot_plan(None, tree, None, p["poro"],
                                 [{"path": p["ntg"]}] * (xd.GL_CHARTS + 1), None)
        assert not many["gl"]
        c = xd.crossplot_chart(many, 0, None, tree, None)
        fig = xd.crossplot_figure(many, c)
        assert [t["type"] for t in fig.to_plotly_json()["data"]] == ["scatter"]
        c = xd.crossplot_chart(few, 0, None, tree, None)
        fig = xd.crossplot_figure(few, c)
        assert [t["type"] for t in fig.to_plotly_json()["data"]] == ["scattergl"]

    def test_the_charts_of_one_property_are_one_track(self, values):
        """The charts of one Y property share a track in the player.

        The player gives one play button per Y property: the charts of that
        property (its dates, its realizations) form a track named without the
        step, and each chart names the step it shows."""
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": p["poro"], "real": 1},
              {"path": p["poro"], "real": 2}]
        plan = xd.crossplot_plan(None, tree, None, p["poro"], ys, None)
        heads = [xd.chart_public(h) for h in plan["heads"]]
        assert [h["group"] for h in heads] == [p["ntg"], p["poro"], p["poro"]]
        # the track is named without what the step names
        assert "real" not in heads[1]["group_title"]
        assert heads[1]["group_title"] == heads[2]["group_title"]
        assert [h["step_title"] for h in heads[1:]] == ["real 1", "real 2"]
        assert heads[0]["step_title"] == ""
        # and the chart once its values are READ keeps its track (the
        # publish goes through crossplot_chart, not through the head)
        read = [xd.chart_public(xd.crossplot_chart(plan, i, None, tree, None))
                for i in range(len(plan["heads"]))]
        assert [c["group"] for c in read] == [h["group"] for h in heads]
        assert [c["step_title"] for c in read] == [h["step_title"] for h in heads]
        # a pinned snapshot is frozen: its own track
        snap = xd.snapshot_chart(None, tree, None, p["poro"],
                                 {"path": p["ntg"]}, None)
        plan = xd.crossplot_plan(None, tree, None, p["poro"], ys, None, pins=[snap])
        pinned = xd.chart_public(plan["heads"][0])
        assert pinned["group"] == "pin:0" and pinned["group_title"].startswith("📌")

    def test_the_film_keeps_the_full_cloud_whatever_the_count(self, values):
        """Film mode stays on WebGL over the full cloud, however many charts.

        One chart on screen at a time uses a single WebGL context, so the
        film draws every chart as scattergl even past GL_CHARTS."""
        tree, p = _tree()
        plan = xd.crossplot_plan(None, tree, None, p["poro"],
                                 [{"path": p["ntg"]}] * (xd.GL_CHARTS + 1), None,
                                 film=True)
        assert plan["gl"] and plan["ctx"]["stride"] == 2
        c = xd.crossplot_chart(plan, 0, None, tree, None)
        fig = xd.crossplot_figure(plan, c)
        assert [t["type"] for t in fig.to_plotly_json()["data"]] == ["scattergl"]

    def test_the_player_counts_the_tracks_against_the_webgl_budget(self, values):
        """The player draws ONE chart per track at once: what the browser
        holds is the number of tracks, not of charts — twelve dates of one
        property stay WebGL, twelve properties do not."""
        tree, p = _tree()
        dates = [{"path": p["ntg"], "ts": i} for i in range(xd.GL_CHARTS + 4)]
        assert xd.crossplot_plan(None, tree, None, p["poro"], dates, None,
                                 film=True)["gl"]
        # the same rows in the grid: every one is on screen, so SVG
        assert not xd.crossplot_plan(None, tree, None, p["poro"], dates, None)["gl"]
        # three properties at four dates each: three tracks, still WebGL
        three = [{"path": q, "ts": i} for i in range(4)
                 for q in (p["ntg"], p["poro"], p["facies"])]
        assert xd.crossplot_plan(None, tree, None, p["poro"], three, None,
                                 film=True)["gl"]
        # a row with no Y is a track of its own: past the budget, SVG
        blank = [{"path": None}] * (xd.GL_CHARTS + 1)
        assert not xd.crossplot_plan(None, tree, None, p["poro"], blank, None,
                                     film=True)["gl"]

    def test_past_max_charts_the_rest_is_not_drawn_and_the_note_says_so(self, values):
        tree, p = _tree()
        asked = xd.MAX_CHARTS + 3
        plan = xd.crossplot_plan(None, tree, None, p["poro"],
                                 [{"path": p["ntg"]}] * asked, None)
        assert len(plan["heads"]) == xd.MAX_CHARTS
        assert f"{asked} charts asked: the first {xd.MAX_CHARTS} are drawn" in plan["ctx"]["note"]
        # a pinned snapshot takes a place of the budget
        snap = xd.snapshot_chart(None, tree, None, p["poro"], {"path": p["ntg"]}, None)
        plan = xd.crossplot_plan(None, tree, None, p["poro"],
                                 [{"path": p["ntg"]}] * asked, None, pins=[snap])
        assert len(plan["heads"]) == xd.MAX_CHARTS and plan["heads"][0]["pinned"]

    def test_notes_add_up_instead_of_replacing_each_other(self, values):
        tree, p = _tree()
        # a subsample AND a colour on another grid: both are said
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["sw"])
        assert "1 point in 2" in meta["note"]
        assert "color ignored" in meta["note"]
        assert meta["nan"] == 0 and meta["total"] == 50

    def test_uirevision_follows_the_axes_not_the_data(self, values):
        tree, p = _tree()
        ys = [{"path": p["ntg"]}, {"path": p["facies"]}]

        def layouts(**kw):
            figs, _ = xd.compute_crossplot_figures(
                None, tree, None, p["poro"], ys, None, **kw)
            return [f.to_plotly_json()["layout"] for f in figs]

        base = layouts()
        assert base[0]["uirevision"]
        # another realization / time step of X is the same axis: the
        # zoom must survive the refresh
        moved = layouts(x_real=3, x_ts=2)
        for i in range(2):
            assert base[i]["uirevision"] == moved[i]["uirevision"]
            for ax in ("xaxis", "yaxis"):
                assert base[i][ax]["uirevision"] == moved[i][ax]["uirevision"], ax
        # a log toggle re-frames X and only X; the Y keys name their
        # own property, so a changed Y re-frames its chart alone
        logged = layouts(log_x=True)
        assert logged[0]["xaxis"]["uirevision"] != base[0]["xaxis"]["uirevision"]
        assert logged[0]["yaxis"]["uirevision"] == base[0]["yaxis"]["uirevision"]
        assert base[0]["yaxis"]["uirevision"] != base[1]["yaxis"]["uirevision"]
        assert base[0]["xaxis"]["uirevision"] == base[1]["xaxis"]["uirevision"]

    def test_axis_keyed_selection_at_full_resolution(self, values, monkeypatch):
        tree, p = _tree()
        monkeypatch.setattr(xd, "MAX_POINTS", 20000)   # every point drawn
        ids, note = xd.selection_cell_ids(
            None, tree, None, p["poro"], p["ntg"],
            sel={"range": {"x2": [0.0, 0.1], "y2": [0.5, 1.5]}})
        # cells 0..9 have poro <= 0.1; 0 and 5 are NaN in NTG
        assert ids == [1, 2, 3, 4, 6, 7, 8, 9]
        assert note == "8 cells selected"

    def test_the_selection_names_its_chart(self):
        """A selection names its chart; without a known name, the axes decide.

        Every chart is a figure of its own, so all axes are x / y: the widget
        names the chart the box was drawn on, and a missing or unknown name
        falls back to the first chart whose axes match."""
        axes = {"pin:0": ["x", "y"], "live:0": ["x", "y"], "live:1": ["x", "y"]}
        sel = {"chart": "live:1", "range": {"x": [0, 1], "y": [0, 1]}}
        assert xd.chart_key_for_selection(axes, sel) == "live:1"
        assert xd.chart_key_for_selection(axes, {"chart": "live:9", "range": sel["range"]}) == "pin:0"
        assert xd.chart_key_for_selection(axes, {"range": sel["range"]}) == "pin:0"
        assert xd.chart_key_for_selection(axes, {"range": {"x2": [0, 1], "y2": [0, 1]}}) is None
        assert xd.chart_key_for_selection({}, sel) is None

    def test_a_subsampled_cloud_says_the_selection_is_read_in_full(self, values):
        """The chart draws one point in N (the fixture caps the cloud at
        25 of 50); the lasso reads every value, and the badge says so — a
        count larger than the dots would otherwise read as a bug."""
        tree, p = _tree()
        ids, note = xd.selection_cell_ids(
            None, tree, None, p["poro"], p["ntg"],
            sel={"range": {"x": [0.0, 0.1], "y": [0.5, 1.5]}})
        assert ids == [1, 2, 3, 4, 6, 7, 8, 9]
        assert note == ("8 cells selected at full resolution (the chart draws"
                        " 1 point in 2; the region is read over every value)")


class _State:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _traces(figs):
    """The traces of every figure, in drawn order — what the grid shows."""
    return [t for f in figs for t in f.to_plotly_json()["data"]]


def _legends(figs):
    return [f.to_plotly_json()["layout"]["showlegend"] for f in figs]


class TestComponentAndUnit:
    """A vector component is another axis (the zoom must go), and a log's
    samples are not a grid's cells (the badge must say which)."""

    @pytest.fixture
    def values(self, monkeypatch):
        np = pytest.importorskip("numpy")
        pytest.importorskip("plotly")
        n = 50
        data = {
            "poro": np.linspace(0.0, 0.5, n),
            "ntg": np.where(np.arange(n) % 5 == 0, np.nan, 1.0),
            "facies": (np.arange(n) % 3).astype(float),
        }

        def fake_values(state, tree, source_registry, path, rep, real_idx=None,
                        ts_idx=None):
            return data[path.rsplit("_", 1)[-1].lower()]
        monkeypatch.setattr(xd, "_values_for", fake_values)
        monkeypatch.setattr(xd, "MAX_POINTS", 25)
        return data

    def test_uirevision_changes_with_the_component_read(self, values):
        tree, p = _tree()
        ys = [{"path": p["ntg"]}]

        def layout(state):
            figs, _ = xd.compute_crossplot_figures(
                state, tree, None, p["poro"], ys, None)
            return figs[0].to_plotly_json()["layout"]

        base = layout(_State())
        # X read at its Z component: the numbers on X are other numbers,
        # the framing must not survive; Y is untouched
        moved = layout(_State(ui_vector_component={p["poro"]: 2}))
        assert moved["xaxis"]["uirevision"] != base["xaxis"]["uirevision"]
        assert moved["uirevision"] != base["uirevision"]
        assert moved["yaxis"]["uirevision"] == base["yaxis"]["uirevision"]
        # the magnitude spelled out is the default: the same key
        same = layout(_State(ui_vector_component={p["poro"]: "magnitude"}))
        assert same["xaxis"]["uirevision"] == base["xaxis"]["uirevision"]
        # a Y component re-frames that Y alone
        y_moved = layout(_State(ui_vector_component={p["ntg"]: 0}))
        assert y_moved["yaxis"]["uirevision"] != base["yaxis"]["uirevision"]
        assert y_moved["xaxis"]["uirevision"] == base["xaxis"]["uirevision"]

    def test_badge_counts_are_kept_apart(self, values):
        tree, p = _tree()
        # NTG against poro on a log X: poro's zero cannot be placed
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], None,
            log_x=True)
        assert meta["unit"] == "cells"
        assert meta["nan"] == 0 and meta["nonpos"] == 1
        # NTG is NaN at every fifth cell: 9 pairs X could complete and Y could
        # not (cell 0 already fell on X's side), counted over the whole array
        # — the subsample halves what is drawn, not the gaps
        assert meta["nan_y"] == 9 and meta["nonpos_y"] == 0
        assert meta["charts"][0]["nan_y"] == 9
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, p["ntg"], [{"path": p["facies"]}], None,
            log_y=True)
        assert meta["nan"] == 10 and meta["nonpos"] == 0
        # facies 0 where NTG has a value: 40 candidates, one in three is 0
        assert meta["nonpos_y"] == 13 and meta["nan_y"] == 0

    def test_a_log_frame_counts_samples(self, values, monkeypatch):
        asm = FakeDataAssembly()
        frame = asm.add_node_with_attrs("_frame", 0, title="55/33-1 logs",
                                        type="Frame", typeCode="7")
        poro = asm.add_node_with_attrs("_poro", frame, title="PORO",
                                       type="ContinuousProperty", typeCode="4")
        ntg = asm.add_node_with_attrs("_ntg", frame, title="NTG",
                                      type="ContinuousProperty", typeCode="4")
        tree = Tree(asm)
        pp, pn = asm.GetNodePath(poro), asm.GetNodePath(ntg)
        _, meta = xd.compute_crossplot_figures(
            None, tree, None, pp, [{"path": pn}], None)
        assert meta["unit"] == "samples" and meta["total"] == 50
        assert xd.sample_unit(tree, asm.GetNodePath(frame)) == "samples"
        ids, note = xd.selection_cell_ids(
            None, tree, None, pp, pn,
            sel={"range": {"x": [0.0, 0.1], "y": [0.5, 1.5]}})
        assert note.startswith("8 samples selected")


class TestCategoryLabels:
    @pytest.fixture
    def values(self, monkeypatch):
        np = pytest.importorskip("numpy")
        pytest.importorskip("plotly")
        n = 30
        data = {"poro": np.linspace(0.0, 0.5, n), "ntg": np.ones(n),
                "facies": (np.arange(n) % 3).astype(float)}
        monkeypatch.setattr(xd, "_values_for",
                            lambda state, tree, sr, path, rep, real_idx=None, ts_idx=None:
                            data[path.rsplit("_", 1)[-1].lower()])
        return data

    def test_legend_names_the_categories_when_the_file_does(self, values, monkeypatch):
        from fespp_on_trame.engine.utils import categories
        tree, p = _tree()
        monkeypatch.setattr(categories, "labels_for",
                            lambda tree, path, vtk_name=None, reader=None:
                            {0: "Sand", 1: "Shale"} if path == p["facies"] else {})
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["facies"])
        data = _traces(figs)
        assert [t["name"] for t in data] == ["Sand", "Shale", "2"]
        # the legend group stays the code: the key across charts
        assert [t["legendgroup"] for t in data] == ["0", "1", "2"]

    def test_the_traces_wear_the_colours_the_views_paint_the_codes_with(self, values, monkeypatch):
        from fespp_on_trame.engine import categorical_palette as cp
        tree, p = _tree()
        # no view paints the codes yet: the default palette in code order
        monkeypatch.setattr(cp, "preset_colors", lambda name: [1, 0, 0, 0, 1, 0, 0, 0, 1])
        monkeypatch.setattr(cp, "view_scenes", lambda: [])
        figs, _meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["facies"])
        data = _traces(figs)
        assert [t["marker"]["color"] for t in data] == ["#ff0000", "#00ff00", "#0000ff"]
        # a view paints them: its colours, the reader's edits included
        monkeypatch.setattr(cp, "colors_by_code",
                            lambda codes, name, scenes=None: {0.0: "#111111", 1.0: "#222222", 2.0: "#333333"})
        figs, _meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["facies"])
        data = _traces(figs)
        assert [t["marker"]["color"] for t in data] == ["#111111", "#222222", "#333333"]

    def test_legend_falls_back_to_the_codes(self, values, monkeypatch):
        from fespp_on_trame.engine.utils import categories
        tree, p = _tree()
        monkeypatch.setattr(categories, "labels_for",
                            lambda tree, path, vtk_name=None, reader=None: {})
        figs, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["facies"])
        assert [t["name"] for t in _traces(figs)] == ["0", "1", "2"]
        # a discrete property has no names to miss: nothing said
        assert categories.NO_NAMES_NOTE not in (meta.get("note") or "")
        # a categorical one whose names could not be read: the badge says so
        monkeypatch.setattr(categories, "labels_note",
                            lambda tree, path, labels: categories.NO_NAMES_NOTE)
        _fig, meta = xd.compute_crossplot_figures(
            None, tree, None, p["poro"], [{"path": p["ntg"]}], p["facies"])
        assert f"color: {categories.NO_NAMES_NOTE}" in (meta.get("note") or "")
