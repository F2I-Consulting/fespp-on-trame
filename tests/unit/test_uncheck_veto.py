"""A refused uncheck says why.

When the selection rules keep a box the user unticked, the checkbox
re-ticks itself, and the amber snackbar is the only explanation the user
gets. The threshold guard therefore names its reason there: the property
stays checked while a Property slicer entry of a live view still reads it, and
the message names that view by its title.
"""
from tests.unit.fake_assembly import FakeDataAssembly
from fespp_on_trame.engine.tree import Tree
from fespp_on_trame.app.ui import selection_deps


def _grid_with_property():
    asm = FakeDataAssembly()
    grid = asm.add_node_with_attrs("_grid1", 0, title="MyGrid",
                                   label="IjkGrid_MyGrid",
                                   type="IjkGrid", typeCode="2")
    prop = asm.add_node_with_attrs("_prop1", grid, title="Pressure",
                                   label="Properties_Pressure",
                                   type="ContinuousProperty", typeCode="4")
    tree = Tree(None)
    tree.set_tree(asm)
    return tree, grid, prop


class TestThresholdGuard:
    def test_the_property_stays_and_the_snackbar_names_the_reason(
            self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for",
                            lambda _tree, _nid: [("view_1", "thr_a"),
                                                 ("view_1", "thr_b")])
        selection_deps._state.empty_color_snackbar_text = ""
        selection_deps._state.empty_color_snackbar_visible = False

        kept = selection_deps._expand_selection_with_deps(
            [grid], [grid, prop], tree)

        assert set(kept) == {grid, prop}
        text = selection_deps._state.empty_color_snackbar_text
        assert text.startswith("Pressure stays checked: 2 entries of the Property slicer")
        assert "still read it. Delete them there" in text
        assert selection_deps._state.empty_color_snackbar_visible is True

    def test_one_entry_reads_in_the_singular(self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for",
                            lambda _tree, _nid: [("view_1", "thr_a")])
        selection_deps._state.empty_color_snackbar_text = ""

        selection_deps._expand_selection_with_deps([grid], [grid, prop], tree)

        text = selection_deps._state.empty_color_snackbar_text
        assert "1 entry of the Property slicer" in text
        assert "still reads it. Delete it there" in text

    def test_nothing_reads_it_and_the_uncheck_passes_in_silence(
            self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for",
                            lambda _tree, _nid: [])
        selection_deps._state.empty_color_snackbar_text = ""

        kept = selection_deps._expand_selection_with_deps(
            [grid], [grid, prop], tree)

        assert prop not in kept
        assert selection_deps._state.empty_color_snackbar_text == ""


class _Iso:
    def __init__(self, chain):
        self._chain = chain

    def get_chain(self):
        return self._chain


class TestClosedViewIsolates:
    """An isolate of a closed view has no Property slicer left to delete
    its entries in: it must not hold the property."""

    def _wire(self, monkeypatch, tree, rep_path, live):
        from fespp_on_trame.app.views import per_view_state
        from fespp_on_trame.engine import threshold_dispatch
        import fespp_on_trame.app.ui.selection_deps as tv
        ctx = type("Ctx", (), {})()
        ctx.grid_isolates = {
            ("view_2", rep_path): _Iso([{"array": "Pressure", "name": "thr_a"}])}
        ctx.source_registry = None
        server = type("Srv", (), {})()
        server.context = ctx
        import sys
        monkeypatch.setattr(sys.modules["trame.app"], "get_server",
                            lambda: server)
        monkeypatch.setattr(per_view_state, "_LIVE", set(live))
        return tv, threshold_dispatch

    def test_a_dead_views_isolate_no_longer_vetoes(self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        tv, _ = self._wire(monkeypatch, tree, tree.find_path(grid), live=["view_1"])
        assert tv._threshold_refs_for(tree, prop) == []

    def test_a_live_views_isolate_still_does(self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        tv, _ = self._wire(monkeypatch, tree, tree.find_path(grid),
                           live=["view_1", "view_2"])
        assert tv._threshold_refs_for(tree, prop) == [("view_2", "thr_a")]


class TestVetoNamesTheView:
    def test_the_view_holding_the_chain_is_named_by_its_title(self, monkeypatch):
        tree, grid, prop = _grid_with_property()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for",
                            lambda _tree, _nid: [("view_2", "thr_a")])
        selection_deps._state.fespp_render_panels = [
            {"id": "view_1", "title": "3D view 1"},
            {"id": "view_2", "title": "3D view 2"}]
        selection_deps._state.empty_color_snackbar_text = ""

        selection_deps._expand_selection_with_deps([grid], [grid, prop], tree)

        text = selection_deps._state.empty_color_snackbar_text
        assert "1 entry of the Property slicer of 3D view 2 still reads it" in text
        assert "view_2" not in text


def _well_with_a_log():
    asm = FakeDataAssembly()
    well = asm.add_node_with_attrs("_well1", 0, title="W-1", label="Wellbore_W-1", type="Wellbore", typeCode="1")
    traj = asm.add_node_with_attrs("_traj1", well, title="Drilled", label="Trajectory_Drilled",
                                   type="Trajectory", typeCode="3")
    logs = asm.add_node_with_attrs("_logsfolder_well1", well, title="logs", label="logs",
                                   type="WellboreLogsFolder", typeCode="1")
    frame = asm.add_node_with_attrs("_frame1", logs, title="Well Log Frame", label="Frame_Logs",
                                    type="Frame", typeCode="1")
    log = asm.add_node_with_attrs("_log1", frame, title="Porosity", label="Properties_Porosity",
                                  type="ContinuousProperty", typeCode="4")
    tree = Tree(None)
    tree.set_tree(asm)
    return tree, well, traj, logs, frame, log


class TestEmptyShells:
    def test_a_folder_left_with_nothing_ticked_under_it_is_unticked_with_it(self, monkeypatch):
        tree, well, traj, logs, frame, log = _well_with_a_log()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for", lambda _tree, _nid: [])
        kept = selection_deps._expand_selection_with_deps([well, traj, logs], [well, traj, logs, frame, log], tree)
        # the frame unticked takes its log, the "logs" folder holds nothing ticked any more
        assert set(kept) == {well, traj}

    def test_a_grouping_keeps_its_tick_while_one_of_its_rows_is_ticked(self, monkeypatch):
        tree, well, traj, logs, frame, log = _well_with_a_log()
        monkeypatch.setattr(selection_deps, "_threshold_refs_for", lambda _tree, _nid: [])
        kept = selection_deps._expand_selection_with_deps([well, logs, frame, log], [well, traj, logs, frame, log], tree)
        # the trajectory is kept by the log that reads along it, and nothing above is emptied
        assert set(kept) == {well, traj, logs, frame, log}
