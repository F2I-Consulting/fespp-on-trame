from trame.app import get_server

from fespp_on_trame.app.core.wellhead import Wellhead
from fespp_on_trame.app.core.timeseries import TimeSeries
from fespp_on_trame.app.core.tree import Tree

server = get_server()
state = server.state


class Selector:
    """Translates the per-tab `ui_select_node_*` checkbox lists into
    assembly paths and writes the concatenated result into
    `state.fespp_data_selectors`. Also creates / destroys companion
    objects (Wellhead, TimeSeries) tied to specific node kinds."""

    def __init__(self, tree: Tree):
        self._tree = tree

        self._selection_path_reservoir = []
        self._selection_path_surface = []
        self._selection_path_well = []

        self._wellheads = []
        # Per-tab TimeSeries companions (audit case 20): one slot per
        # tree tab so a selection change on one tab never destroys the
        # companion (LUT lock + time label) another tab still relies on.
        self._timeseries = {}

        state.setdefault("first_selection", True)

    def apply_z_scale(self, zscale):
        """Re-anchor every wellhead on the Z exaggeration.

        Wellheads are Text reps (flagpole + billboard): they carry no
        `Scale`, so the z-scale fan-out silently skips them and they would
        stay at the unscaled datum while their trajectory stretches away.
        See `Wellhead.apply_z_scale`."""
        for wellhead in self._wellheads:
            try:
                wellhead.apply_z_scale(zscale)
            except Exception:
                continue

    def optimize_tree_selection(self, selected_items):
        """Identity in explicit-selection mode.

        With ExplicitSelection=1 (set at boot in engine.py) the C++ side
        does not auto-load descendants of a parent path, so each checked
        node must be forwarded verbatim — collapsing to a parent path
        would silently drop the user's checked properties.

        UI-side dependency expansion (auto-check Trajectory when a
        Channel/Marker is checked, auto-check descendants of a
        grouping) happens in tree_views.py before this function runs,
        so `selected_items` is already the complete set."""
        return list(selected_items) if selected_items else []

    def _reset_timeseries(self, tab, node_ids):
        """Re-create THIS tab's TimeSeries companion from its selection;
        the other tabs keep theirs (audit case 20). When this tab ends up
        without one, the time label deleted alongside it is restored from
        any surviving companion."""
        old = self._timeseries.get(tab)
        if old is not None:
            old.delete()
            self._timeseries[tab] = None
        for node_id in node_ids:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries[tab] = TimeSeries(self._tree, node_id)
        if self._timeseries.get(tab) is None:
            for other in self._timeseries.values():
                if other is not None:
                    other.refresh_label()
                    break

    def select_node_surface(self):
        """Push the surface tab's checked nodes into
        fespp_data_selectors. Re-creates the surface TimeSeries companion
        when a TimeSeries node is in the selection."""
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_surface,
        )

        list_selected = optimized_selection
        self._reset_timeseries("surface", list_selected)
        path_selectors = []

        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_surface = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True

    def select_node_well(self):
        """Push the well tab's checked nodes into fespp_data_selectors.
        Re-creates Wellhead companions for every checked Trajectory and
        a TimeSeries companion when one is in the selection."""
        list_selected = state.ui_select_node_well.copy()
        self._reset_timeseries("well", list_selected)
        for wellhead in self._wellheads:
            wellhead.delete()
        self._wellheads = []

        for node_id in list_selected:
            if self._tree.find_type(node_id) == "Trajectory":
                self._wellheads.append(Wellhead(self._tree, node_id))

        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_well,
        )

        list_selected = optimized_selection
        path_selectors = []

        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_well = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True

    def select_node_reservoir(self):
        """Push the reservoir tab's checked nodes into
        fespp_data_selectors. Every checked path is forwarded
        explicitly — with ExplicitSelection=1, the C++ side does NOT
        auto-load descendants of a non-grouping path, so each property
        the user wants must appear in the list."""
        list_selected = state.ui_select_node_reservoir.copy()
        self._reset_timeseries("reservoir", list_selected)

        path_selectors = []
        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)
        # An IjkGrid property checked on its own (parent grid node NOT checked)
        # must still pull the grid GEOMETRY. The C++ collector loads cells
        # from the grid path; a property path alone yields only the array, so
        # the rep_data extractor comes back empty and the grid is discarded
        # (source is None → ensure_ijk_grid drops it). Prepend each selected
        # property's IjkGrid ancestor path so the geometry is always loaded.
        grid_paths = []
        for node_id in list_selected:
            ijk_id = self._tree.find_parent_node_id_with_type(node_id, "IjkGrid")
            if ijk_id is None or ijk_id == node_id:
                continue
            ijk_path = self._tree.find_path(ijk_id)
            if ijk_path and ijk_path not in path_selectors and ijk_path not in grid_paths:
                grid_paths.append(ijk_path)
        self._selection_path_reservoir = grid_paths + path_selectors

        # IjkGrid teardown on empty selection is handled implicitly by
        # the fespp_data_selectors change handler — when the reservoir
        # selection drops a grid, _on_change_fespp_data_selectors_impl
        # tears down its IjkGrid instance.

        state.fespp_data_selectors = (
            self._selection_path_reservoir
            + self._selection_path_surface
            + self._selection_path_well
        )
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True
