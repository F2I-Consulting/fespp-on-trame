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
        self._timeseries = None

        state.setdefault("first_selection", True)

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

    def select_node_surface(self):
        """Push the surface tab's checked nodes into
        fespp_data_selectors. Re-creates a TimeSeries companion when a
        TimeSeries node is in the selection."""
        if self._timeseries is not None:
            self._timeseries.delete()
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_surface,
        )

        list_selected = optimized_selection
        path_selectors = []

        for node_id in list_selected:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

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
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_well.copy()
        for wellhead in self._wellheads:
            wellhead.delete()
        self._wellheads = []

        for node_id in list_selected:
            if self._tree.find_type(node_id) == "Trajectory":
                self._wellheads.append(Wellhead(self._tree, node_id))

            elif self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

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
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_reservoir.copy()
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

        path_selectors = []
        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)
        self._selection_path_reservoir = path_selectors

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
