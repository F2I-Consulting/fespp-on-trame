from trame.app import get_server

import fespp_on_trame.app.utils.search_node as search_node
import fespp_on_trame.app.core.reservoir.fespp_ijkgrid as fespp_ijkgrid

server = get_server()
state = server.state

class Activator:
    def __init__(self):
        state.setdefault("ui_active_node_reservoir", [])
        state.setdefault("ui_active_node_surface", [])
        state.setdefault("ui_active_node_well", [])

        @state.change("ui_active_node_reservoir")
        def on_ui_active_node_reservoir_change(ui_active_node_reservoir, **kwargs):
            if ui_active_node_reservoir and len(ui_active_node_reservoir) > 0:
                node_id = ui_active_node_reservoir[0]
                type_node = state.tree.find_type(node_id)
                
                #if type_node is not None and type_node == 'IjkGrid':
                #    state.fespp_ijkgrid.ijkGrid(node_id)
                
                state.update({
                    "ui_active_node_reservoir_type": type_node,
                })
            else:
                state.update({
                    "ui_active_node_reservoir_type": "",
                })

        @state.change("ui_active_node_surface")
        def on_ui_active_node_surface_change(ui_active_node_surface, **kwargs):
            if ui_active_node_surface and len(ui_active_node_surface) > 0:
                node_id = ui_active_node_surface[0]
                type_node = state.tree.find_type(node_id)
                
                state.update({
                    "ui_active_node_surface_type": type_node,
                })
            else:
                state.update({
                    "ui_active_node_surface_type": "",
                })
    
        @state.change("ui_active_node_well")
        def on_ui_active_node_well_change(ui_active_node_well, **kwargs):
            if ui_active_node_well and len(ui_active_node_well) > 0:
                node_id = ui_active_node_well[0]
                type_node = state.tree.find_type(node_id)
                
                state.update({
                    "ui_active_node_well_type": type_node,
                })
            else:
                state.update({
                    "ui_active_node_well_type": "",
                })
    