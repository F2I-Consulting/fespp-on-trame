from trame.app import get_server
from paraview import simple  # type: ignore
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

import fespp_on_trame.app.core.fespp_selection as fespp_selection
import fespp_on_trame.app.core.fespp_active as fespp_active
import fespp_on_trame.app.utils.search_node as search_node
import fespp_on_trame.app.ui.panel.slicers as panel_slicers
#import fespp_on_trame.app.core.fespp_ijkgrid as fespp_ijkgrid

server = get_server()
state = server.state

vuetify3.enable_lab()

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
# General UI
# -----------------------------------------------------------------------------
def ui(server: Server, **kwargs) -> None:
    # Get logo from public folder
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")

    # FESPP engine
    fespp_selection.Selector()
    fespp_active.Activator()

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
                        "Data Explorer",
                        "mdi-file-tree",
                        "60vh"
                    ):
                        vuetify3.VTreeview(
                            # style
                            slim=True,
                            density="compact",
                            # data
                            item_value="id",
                            items=("ui_subtree_reservoir", state.ui_subtree_reservoir),
                            # activation logic
                            activated=("ui_active_node_reservoir", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="ui_active_node_reservoir = $event",
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
                        "Data Apps",
                        "mdi-information",
                        "30vh"
                    ):
                        with vuetify3.VExpansionPanels(style="display: initial;"):
                            with html.Div(v_if=("ui_active_node_reservoir_type === 'IjkGrid'",)):
                                panel_slicers.SlicerControls()
                    
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
                            items=("ui_subtree_surface", state.ui_subtree_surface),
                            # activation logic
                            activated=("ui_active_node_surface", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="ui_active_node_surface = $event",
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
                        "Node panel",
                        "mdi-information",
                        "30vh"
                    ):
                        vuetify3.VTextField("{{ ui_active_node_surface }} => {{ ui_active_node_surface_type }}")
                
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
                            items=("ui_subtree_well", state.ui_subtree_well),
                            # activation logic
                            activated=("ui_active_node_well", []),
                            activatable=True,
                            active_strategy="single-independent",
                            update_activated="ui_active_node_well = $event",
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
                        "Node panel",
                        "mdi-information",
                        "30vh"
                    ):
                        vuetify3.VTextField("{{ ui_active_node_well }} => {{ ui_active_node_well_type }}")

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

