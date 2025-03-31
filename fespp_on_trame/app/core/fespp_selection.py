from trame.app import get_server

from fespp_on_trame.app.core.reservoir.fespp_ijkgrid import IjkGrid

server = get_server()
state = server.state

class Selector:
    def __init__(self):
        state.setdefault("ui_select_node_reservoir", [])
        state.setdefault("ui_select_node_surface", [])
        state.setdefault("ui_select_node_well", [])
        state.setdefault("selection_path_reservoir", [])
        state.setdefault("selection_path_surface", [])
        state.setdefault("selection_path_well", [])
        state.setdefault("block_selector_reservoir", []) # all selector except IjkGrid
        state.setdefault("block_selector_surface", []) # all selector
        state.setdefault("block_selector_well", []) # all selector


@state.change("ui_select_node_surface")
def on_change_ui_select_node_surface(**kwargs) -> None:
    list_selected = state.ui_select_node_surface.copy()
    path_selectors = []

    list_selected = state.ui_select_node_surface.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = state.tree.find_path(node_id)
        if path:
            path_selectors.append(path)

    state.selection_path_well = path_selectors.copy()
    state.fespp_data_selectors = state.selection_path_reservoir + state.selection_path_surface + state.selection_path_well


@state.change("ui_select_node_well")
def on_change_ui_select_node_well(**kwargs) -> None:
    list_selected = state.ui_select_node_well.copy()
    path_selectors = []

    # switch node_id to path
    for node_id in list_selected:
        path = state.tree.find_path(node_id)
        if path:
            path_selectors.append(path)

    state.selection_path_well = path_selectors.copy()
    state.fespp_data_selectors = state.selection_path_reservoir + state.selection_path_surface + state.selection_path_well

@state.change("ui_select_node_reservoir")
def on_change_ui_select_node_reservoir(**kwargs) -> None:
    if state.ijk_grid is not None:
        if len(state.ui_select_node_reservoir) < 1:
            if state.selection_path_reservoir != []:
                state.selection_path_reservoir = []
                state.fespp_data_selectors = state.selection_path_surface + state.selection_path_well
        else:
            state.selection_path_reservoir = [state.tree.find_path(state.ui_select_node_reservoir[0])]
            state.fespp_data_selectors = state.selection_path_reservoir + state.selection_path_surface + state.selection_path_well


