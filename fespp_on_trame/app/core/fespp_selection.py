from trame.app import get_server

from fespp_on_trame.app.core.sources.ijkgrid import IjkGrid
from fespp_on_trame.app.core.well.fespp_wellhead import Wellhead
from fespp_on_trame.app.core.common.timeseries import TimeSeries
from fespp_on_trame.app.core.fespp_tree import Tree

server = get_server()
state = server.state

class Selector:
    def __init__(self, ijkgrid: IjkGrid, tree: Tree):
        
        self._ijkgrid = ijkgrid
        self._tree = tree

        self._selection_path_reservoir = []
        self._selection_path_surface = []
        self._selection_path_well = []
        
        self._wellheads = []
        self._timeseries = None

        state.setdefault("first_selection", True)

    def optimize_tree_selection(self, selected_items, tree_data):
        """Identity in explicit-selection mode.

        Historically this collapsed groups of all-children-selected leaves to
        their parent path, on the assumption that the parent path covers all
        descendants on the C++ side. With FESPP's `ExplicitSelection=1` mode
        (set at boot in fespp_engine.py), that assumption no longer holds for
        non-grouping nodes — sending the parent path would only load the
        parent's geometry and silently drop the user's checked properties.

        UI-side dependency expansion (auto-check Trajectory when a
        Channel/Marker is checked, auto-check descendants of a grouping)
        happens in tree_views.py instead, before this function runs. So by
        the time we get here, `selected_items` is the complete set the user
        actually wants. Just return it as-is.
        """
        return list(selected_items) if selected_items else []
    
    def select_node_surface(self):
        if self._timeseries is not None:
            self._timeseries.delete()
        # Optimiser la sélection avant de l'utiliser
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_surface, 
            state.ui_subtree_surface
        )

        # Utiliser la sélection optimisée si fournie, sinon la sélection brute
        list_selected = optimized_selection
        path_selectors = []

        # switch node_id to path
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
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_well.copy()
        for wellhead in self._wellheads:
            wellhead.delete()
        self._wellheads = []

        # switch node_id to path
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "Trajectory":
                self._wellheads.append(Wellhead(self._tree, node_id))
                
            elif self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

        # Optimiser la sélection avant de l'utiliser
        optimized_selection = self.optimize_tree_selection(
            state.ui_select_node_well, 
            state.ui_subtree_well
        )

        # Utiliser la sélection optimisée si fournie, sinon la sélection brute
        list_selected = optimized_selection
        path_selectors = []

        # switch node_id to path
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
        if self._timeseries is not None:
            self._timeseries.delete()
        list_selected = state.ui_select_node_reservoir.copy()
        for node_id in list_selected:
            if self._tree.find_type(node_id) == "TimeSeries":
                self._timeseries = TimeSeries(self._tree, node_id)

        # Build selector paths from EVERY checked reservoir node (grid,
        # property, sub-rep). With ExplicitSelection=1 (set at boot in
        # fespp_engine), the C++ side does not auto-load descendants of
        # a non-grouping path — every property the user wants must be
        # listed explicitly here.
        path_selectors = []
        for node_id in list_selected:
            path = self._tree.find_path(node_id)
            if path:
                path_selectors.append(path)
        self._selection_path_reservoir = path_selectors

        # Slicers attach to a single active IjkGrid. Pick the first
        # IjkGrid id in the selection (or clear if none).
        if self._ijkgrid is not None:
            if not list_selected:
                self._ijkgrid.set_node_id(None)
            # else: handled in fespp_engine on fespp_data_selectors change.

        state.fespp_data_selectors = (
            self._selection_path_reservoir
            + self._selection_path_surface
            + self._selection_path_well
        )
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True
