from trame.app import get_server
from paraview import simple  # type: ignore
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

import fespp_on_trame.app.utils.fespp_selection as fespp_selection
import fespp_on_trame.app.utils.fespp_active as fespp_active

server = get_server()
state = server.state

vuetify3.enable_lab()

# init
state.setdefault("ui_select_node_reservoir", [])
state.setdefault("ui_select_node_surface", [])
state.setdefault("ui_select_node_well", [])

state.setdefault("active_node_reservoir", [])
state.setdefault("active_node_surface", [])
state.setdefault("active_node_well", [])

def attribut_node_reservoir(node_id):
    server.state.active_node_reservoir = node_id
    print("attribut_node_reservoir=>",server.state.active_node_reservoir)
    #return fespp_active.attribut_node_reservoir()
    return vuetify3.VCardText(
            f"Active Node: {node_id}",
            classes="text-center",
        )
    
def attribut_node_surface(node_id):
    server.state.active_node_surface = node_id
    print("attribut_node_surface=>",server.state.active_node_surface)
    #return fespp_active.attribut_node_surface()
    return vuetify3.VCardText(
            f"Active Node: {node_id}",
            classes="text-center",
        )
    
def attribut_node_well(node_id):
    server.state.active_node_well = node_id
    print("attribut_node_well=>",server.state.active_node_well)
    #return fespp_active.attribut_node_well()
    return vuetify3.VCardText(
            f"Active Node: {node_id}",
            classes="text-center",
        )
    
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
# change of state
# -----------------------------------------------------------------------------
@server.state.change("ui_select_node_reservoir")
def on_select_node_reservoir_change(ui_select_node_reservoir, **kwargs):
    print("on_select_node_reservoir_change")
    fespp_selection.load_fespp_selector_reservoir()
    
@server.state.change("ui_select_node_surface")
def on_select_node_surface_change(ui_select_node_surface, **kwargs):
    print("on_select_node_surface_change")
    fespp_selection.load_fespp_selector_surface()
    
@server.state.change("ui_select_node_well")
def on_select_node_well_change(ui_select_node_well, **kwargs):
    print("on_select_node_well_change")
    fespp_selection.load_fespp_selector_well()
    
@server.state.change("active_node_reservoir")
def on_active_node_reservoir_change(active_node_reservoir, **kwargs):
    attribut_node_reservoir(active_node_reservoir)
    
@server.state.change("active_node_surface")
def on_active_node_surface_change(active_node_surface, **kwargs):
    attribut_node_surface(active_node_surface)
    
@server.state.change("active_node_well")
def on_active_node_well_change(active_node_well, **kwargs):
    attribut_node_well(active_node_well)
    
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
                            activated=("active_node_reservoir", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node_reservoir = $event",
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
                        "Node Attribute",
                        "mdi-information",
                        "30vh"
                    ):
                        attribut_node_reservoir("{{ active_node_reservoir }}")
                    
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
                            activated=("active_node_surface", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node_surface = $event",
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
                        attribut_node_surface("{{ active_node_surface }}")
                
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
                            activated=("active_node_well", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="active_node_well = $event",
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
                        attribut_node_well("{{ active_node_well }}")

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
