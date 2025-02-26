from trame.app import get_server
from paraview import simple  # type: ignore
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

server = get_server()
state = server.state

vuetify3.enable_lab()

# init
state.setdefault("ui_select_node_reservoir", [])
state.setdefault("ui_select_node_surface", [])
state.setdefault("ui_select_node_well", [])

# -----------------------------------------------------------------------------
# common def
# -----------------------------------------------------------------------------
def find_parent_id(tree, node_id) -> None:
    for item in tree:
        if item.get("id") == node_id:
            return item["parent_id"]
        elif item.get("children"):
            return find_parent_id(item["children"], node_id)
    return None

def find_item_node_id(tree, node_id) -> None:
    for item in tree:
        if item.get("id") == node_id:
            return item
    return None

def node_id_to_path(tree, node_id) -> str:
    for node in tree:
        if node.get("id") == node_id:
            return node.get("path")
        elif node.get("children"):
            path = node_id_to_path(node["children"], node_id)
            if path:
                return path
    return None

# -----------------------------------------------------------------------------
# default Card
# -----------------------------------------------------------------------------
def create_card(title, icon, height=None):
    card_props = {"classes": "pa-0",
                  "elevation": 10,
                  "flat": True, 
                  "outlined": False, 
                  "tile": True,
                  "style": "border: solid; border-color: #d0d3d4;"}
    if height:  
        card_props["height"] = height

    with vuetify3.VCard(**card_props):
        vuetify3.VDivider()
        card_title_props = {"classes": "d-flex align-center py-1", "style": "background-color: #b3b6b7;"}
        with vuetify3.VCardTitle(**card_title_props):
            vuetify3.VIcon(icon)
            html.Div(title)
        vuetify3.VDivider()
        if height:
            height_value = int(height[:-2])
            max_height_value = height_value - 5
            max_height = f"{max_height_value}vh"
            return vuetify3.VCardText(style=f"overflow-y: auto; max-height: {max_height};")
        else:
            return vuetify3.VCardText(style="overflow-y: auto;")

# -----------------------------------------------------------------------------
# Attribut Node Card
# -----------------------------------------------------------------------------
def Attribut_Node(active_node):
    """return a VCardText display active node."""
    return vuetify3.VCardText(
        f"Active Node: {active_node}",
        classes="text-center",
    )
    
# -----------------------------------------------------------------------------
# treeview management
# -----------------------------------------------------------------------------
# NOT USE => specific selection => selection-strategy="independent"
'''def treeview_change(treeview_type, **kwargs) -> None:
    treeview = []
    list_selected = []
    if treeview_type == "reservoir":
        treeview = server.state.data_hierarchy_reservoir.copy()
        list_selected = server.state.ui_select_node_reservoir.copy()
    elif treeview_type == "surface":
        treeview = server.state.data_hierarchy_surface.copy()
        list_selected = server.state.ui_select_node_surface.copy()
    else:
        treeview = server.state.data_hierarchy_well.copy()
        list_selected = server.state.ui_select_node_well.copy()
    
    if not isinstance(list_selected, list):
        print("Error: list_selected is not a list:", list_selected)
        return

    select_node = list_selected.copy()
    for node_id in select_node:
        parent_id = find_parent_id(treeview, node_id)
        if parent_id and parent_id not in select_node:
            select_node.append(parent_id)

    select_node.sort(reverse=True)
    if treeview_type == "reservoir":
        server.state.ui_select_node_reservoir = select_node.copy()
    elif treeview_type == "surface":
        server.state.ui_select_node_surface = select_node.copy()
    else:
        server.state.ui_select_node_well = select_node.copy()
        '''

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
        path = node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_reservoir = path_selectors.copy()

    server.state.fespp_data_selectors = server.state.fespp_data_selectors_reservoir
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_surface)
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_well)

# load fespp selector with surface treeview selection
def load_fespp_selector_surface(**kwargs) -> None:
    # init
    server.state.fespp_data_selectors=[]
    path_selectors = []

    treeview = server.state.data_hierarchy_surface.copy()
    list_selected = server.state.ui_select_node_surface.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_surface = path_selectors.copy()

    server.state.fespp_data_selectors = server.state.fespp_data_selectors_surface
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_reservoir)
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_well)

# load fespp selector with well treeview selection
def load_fespp_selector_well(**kwargs) -> None:
    # init
    server.state.fespp_data_selectors=[]
    path_selectors = []

    treeview = server.state.data_hierarchy_well.copy()
    list_selected = server.state.ui_select_node_well.copy()

    # switch node_id to path
    for node_id in list_selected:
        path = node_id_to_path(treeview, node_id)
        if path:
            path_selectors.append(path)

    server.state.fespp_data_selectors_well = path_selectors.copy()

    server.state.fespp_data_selectors = server.state.fespp_data_selectors_well
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_surface)
    server.state.fespp_data_selectors.extend(server.state.fespp_data_selectors_reservoir)

# -----------------------------------------------------------------------------
# change of state
# -----------------------------------------------------------------------------
@server.state.change("ui_select_node_reservoir")
def on_select_node_change(ui_select_node_reservoir, **kwargs):
    print("ui_select_node_reservoir")
    load_fespp_selector_reservoir()
    
@server.state.change("ui_select_node_surface")
def on_select_node_change(ui_select_node_surface, **kwargs):
    print("ui_select_node_surface")
    load_fespp_selector_surface()
    
@server.state.change("ui_select_node_well")
def on_select_node_change(ui_select_node_well, **kwargs):
    print("ui_select_node_well")
    load_fespp_selector_well()
    
# -----------------------------------------------------------------------------
# General UI
# -----------------------------------------------------------------------------
def ui(server: Server, **kwargs) -> None:
    # Get logo from public folder
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")

    with SinglePageWithDrawerLayout(server, width=450) as layout:
        layout.title.set_text(TRAME_APP_TITLE)

        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        with layout.toolbar:
            pass

        with layout.drawer, vuetify3.VCard(style="box-shodow: None;"):
            with vuetify3.VTabs(v_model=("tab", None)):
                with vuetify3.VTab(value="reservoir"):
                    html.Div("Reservoir")
                with vuetify3.VTab(value="surface"):
                    html.Div("Surface")
                with vuetify3.VTab(value="well"):
                    html.Div("Well")
            with vuetify3.VCardText(), vuetify3.VWindow(v_model=("tab",)):
                with vuetify3.VWindowItem(value="reservoir"):
                    # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        vuetify3.VTreeview(
                            # style
                            slim=True,
                            density="compact",
                            # data
                            item_value="id",
                            items=("data_hierarchy_reservoir", server.state.data_hierarchy_reservoir),
                            # activation logic
                            activated=("active_node", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node = $event",
                            color="primary",
                            open_on_click=False,
                            # selection logic
                            selected=("ui_select_node_reservoir", []),
                            selectable=True,
                            select_strategy="single-leaf",
                            update_selected="ui_select_node_reservoir = $event",
                        )
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        Attribut_Node("{{ active_node }}")
                    
                with vuetify3.VWindowItem(value="surface"):
              # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        vuetify3.VTreeview(
                            # style
                            slim=True,
                            density="compact",
                            # data
                            item_value="id",
                            items=("data_hierarchy_surface", server.state.data_hierarchy_surface),
                            # activation logic
                            activated=("active_node", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node = $event",
                            color="primary",
                            open_on_click=False,
                            # selection logic
                            selected=("ui_select_node_surface", []),
                            selectable=True,
                            select_strategy="single-leaf",
                            update_selected="ui_select_node_surface = $event",
                        )
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        Attribut_Node("{{ active_node }}")
                
                with vuetify3.VWindowItem(value="well"):
                    # Treeview CARD
                    with create_card(
                        "Project treeview",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        vuetify3.VTreeview(
                            # style
                            slim=True,
                            density="compact",
                            # data
                            item_value="id",
                            items=("data_hierarchy_well", server.state.data_hierarchy_well),
                            # activation logic
                            activated=("active_node", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node = $event",
                            color="primary",
                            open_on_click=False,
                            # selection logic
                            selected=("ui_select_node_well", []),
                            selectable=True,
                            select_strategy="classic",
                            update_selected="ui_select_node_well = $event",
                        )
                    # Attribut Node CARD
                    with create_card(
                        "Node Attribut",
                        "mdi-information",
                        "30vh"
                    ):
                        Attribut_Node("{{ active_node }}")

        with layout.content:
            with vuetify3.VContainer(
                fluid=True, classes="pa-0 fill-height", v_if="file_loaded"
            ):
                view = paraview.VtkRemoteView(
                    simple.GetActiveViewOrCreate("RenderView") if simple else None,
                    interactive_ratio=1,
                    interactive_quality=70,
                    namespace="view",
                    style="width: 100%; height: 100%;",
                )
                # Link view callbacks
                server.controller.view_replace = view.replace_view
                server.controller.view_update = view.update
                server.controller.view_reset_camera = view.reset_camera
                server.controller.on_server_ready.add(server.controller.view_update)

        layout.footer.hide()

        return layout
