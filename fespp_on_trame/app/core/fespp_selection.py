from trame.app import get_server

from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid

server = get_server()
state = server.state

class Selector:
    def __init__(self, ijkgrid: IjkGrid):
        
        self._ijkgrid = ijkgrid
        
        self._selection_path_reservoir = []
        self._selection_path_surface = []
        self._selection_path_well = []

        state.setdefault("first_selection", True)

#@state.change("first_selection")
#def on_change_first_selection(first_selection, **kwargs) -> None:
#    if first_selection:
#        state.view_reset_camera = True
#        state.representation_update = True
#        
#    state.first_selection = False
    
    
    def select_node_surface(self):
        list_selected = state.ui_select_node_surface.copy()
        path_selectors = []

        list_selected = state.ui_select_node_surface.copy()

        # switch node_id to path
        for node_id in list_selected:
            path = state.tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_surface = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True


    def select_node_well(self):
        list_selected = state.ui_select_node_well.copy()
        path_selectors = []

        # switch node_id to path
        for node_id in list_selected:
            path = state.tree.find_path(node_id)
            if path:
                path_selectors.append(path)

        self._selection_path_well = path_selectors.copy()
        state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True

    def select_node_reservoir(self):
        if self._ijkgrid is not None:
            if len(state.ui_select_node_reservoir) < 1:
                self._ijkgrid.set_node_id(None)
                if self._selection_path_reservoir != []:
                    self._selection_path_reservoir = []
                    state.fespp_data_selectors = self._selection_path_surface + self._selection_path_well
            else:
                self._selection_path_reservoir = [state.tree.find_path(state.ui_select_node_reservoir[0])]
                state.fespp_data_selectors = self._selection_path_reservoir + self._selection_path_surface + self._selection_path_well
        if state.first_selection == True:
            state.first_selection = False
        state.view_update = True


