from trame.app import get_server

import fespp_on_trame.app.utils.fespp_common as fespp_common

server = get_server()
state = server.state

def update_fespp_data_selectors():
    server.state.fespp_data_selectors = server.state.fespp_data_selectors_reservoir + server.state.fespp_data_selectors_surface + server.state.fespp_data_selectors_well
    
# -----------------------------------------------------------------------------
# Fespp Selector management (each tree can have its own management)
# -----------------------------------------------------------------------------
# load fespp selector with reservoir treeview selection
def load_fespp_selector_reservoir(**kwargs) -> None:
    # init
    server.state.fespp_data_selectors=[]
    path_selectors = []

    treeview = server.state.data_hierarchy_reservoir.copy()
    list_selected = server.state.ui_select_node_reservoir.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = fespp_common.node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_reservoir = path_selectors.copy()
    
    update_fespp_data_selectors()

# load fespp selector with surface treeview selection
def load_fespp_selector_surface(**kwargs) -> None:
    # init
    server.state.fespp_data_selectors=[]
    path_selectors = []

    treeview = server.state.data_hierarchy_surface.copy()
    list_selected = server.state.ui_select_node_surface.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = fespp_common.node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_surface = path_selectors.copy()

    update_fespp_data_selectors()

# load fespp selector with well treeview selection
def load_fespp_selector_well(**kwargs) -> None:
    # init
    server.state.fespp_data_selectors=[]
    path_selectors = []

    treeview = server.state.data_hierarchy_well.copy()
    list_selected = server.state.ui_select_node_well.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = fespp_common.node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_well = path_selectors.copy()

    update_fespp_data_selectors()
