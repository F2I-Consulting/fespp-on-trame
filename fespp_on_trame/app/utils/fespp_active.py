from trame.app import get_server
from trame.widgets import vuetify3 as vuetify3, paraview, html

import fespp_on_trame.app.utils.fespp_common as fespp_common

server = get_server()
state = server.state

# -----------------------------------------------------------------------------
# Attribut Node Card
# -----------------------------------------------------------------------------
def attribut_node_reservoir()-> None:
    print("*** attribut_node_reservoir ***")
    print("active_node_id", server.state.active_node_reservoir)
    if server.state.active_node_reservoir is not None and len(server.state.active_node_reservoir) > 0:
        node_id = server.state.active_node_reservoir[0]
        treeview = server.state.data_hierarchy_reservoir.copy()
        print("---> treeview", treeview)
        print("---> node_id", node_id)
        type = fespp_common.node_id_to_type(treeview, node_id)
        print("Node type:", type)
        print("Node id:", node_id)
        return vuetify3.VCardText(
            f"Type Node: {type}",
            classes="text-center",
        )
    else:
        return vuetify3.VCardText(
            "No active node",
            classes="text-center",
        )
        
def attribut_node_surface()->None:
    print("*** attribut_node_surface ***")
    print("active_node_id",server.state.active_node_surface)
    if server.state.active_node_surface is not None and len(server.state.active_node_surface) > 0:
        node_id = server.state.active_node_surface[0]
        treeview = server.state.data_hierarchy_surface.copy()
        type = fespp_common.node_id_to_type(treeview, node_id)
        print("Node type:", type)
        print("Node id:", node_id)
        return vuetify3.VCardText(
            f"Type Node: {type}",
            classes="text-center",
        )
    else:
        return vuetify3.VCardText(
            "No active node",
            classes="text-center",
        )
        
def attribut_node_well()->None:
    print("*** attribut_node_well ***")
    print("active_node_id",server.state.active_node_well)
    if server.state.active_node_well is not None and len(server.state.active_node_well) > 0:
        node_id = server.state.active_node_well[0]
        treeview = server.state.data_hierarchy_well.copy()
        type = fespp_common.node_id_to_type(treeview, node_id)
        print("Node type:", type)
        print("Node id:", node_id)
        return vuetify3.VCardText(
            f"Type Node: {type}",
            classes="text-center",
        )
    else:
        return vuetify3.VCardText(
            "No active node",
            classes="text-center",
        )