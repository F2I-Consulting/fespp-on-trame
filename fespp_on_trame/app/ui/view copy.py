from trame.app import get_server
from paraview import simple as pvsimple
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal
import ptc

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

import fespp_on_trame.app.core.fespp_engine as fespp_engine
import fespp_on_trame.app.ui.panel.slicers as panel_slicers
#import fespp_on_trame.app.core.fespp_ijkgrid as fespp_ijkgrid

import contextlib
from fespp_on_trame.app.io.http import download_file_from_url
from fespp_on_trame.app.io.drop_files import save_uploaded_files
from tempfile import mkdtemp


server = get_server()
state = server.state
controller = server.controller

state.dialog_visible = False
state.execute_action = False
state.ptc_show_vcr = False
state.ui_time_label = ""

class Representation:
    Points = 0
    Wireframe = 1
    Surface = 2
    SurfaceWithEdges = 3

# Fonction pour exécuter une action spécifique
@state.change("execute_action")
def run_action(execute_action, **kwargs):
    if execute_action and state.remote_files_location:
        list_url = state.remote_files_location.split('|')
        temp_dir = mkdtemp()
        epc_paths = []
        
        for url in list_url:
            file_name = download_file_from_url(url, temp_dir)
        
            if file_name.lower().endswith('.epc'):
                epc_paths.append(file_name)
                
        for epc_path in epc_paths:
            controller.load_epc_file(epc_path)
        
        state.execute_action = False
        state.remote_epc_file_location = None
        state.remote_h5_file_location = None
        
    elif execute_action and state.files:
        epc_paths = save_uploaded_files(state.files)
        for epc_path in epc_paths:
            controller.load_epc_file(epc_path)
        state.files = None
    state.execute_action = False

                
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

    with SinglePageWithDrawerLayout(server, width=450) as layout:
        layout.title.set_text(TRAME_APP_TITLE)

        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        with layout.toolbar:
            with vuetify3.VContainer(
                classes="fill-height",
            ):
                vuetify3.VSpacer()
                
#                with vuetify3.VBtn(icon=True, click=server.controller.view_reset_camera):
#                    vuetify3.VIcon("mdi-image-filter-center-focus", color="blue")

                with html.Div(style="width: 15%;"):
                    ptc.RepresentBy(
                        color = "blue",
                        base_color="blue", 
                        item_color="blue"
                    )
                #with html.Div(style="width: 15%;"):
                #    vuetify3.VSelect(
                #        # Representation
                #        v_model=("ui_representation", "Surface"),
                #        items=(
                #            "representations",
                #            [
                #                "Points","Wireframe","Surface","Surface With Edges",
                #            ],
                #        ),
                #        label="Representation",
                #        hide_details=True,
                #        dense=True,
                #        outlined=True,
                #        color="blue",
                #        base_color="blue",
                #    )
                with html.Div(style="width: 5%;"):
                    vuetify3.VTextField(
                        v_model=("ui_scale_z", 1.0),
                        label="z scale",
                        hide_details=True,
                        dense=True,
                        outlined=True,
                        color="blue",
                        base_color="blue",
                        bg_color="white",
                        reverse=True,
                        type="number",
                    )
                
                vuetify3.VSpacer()
                
                with html.Div(style="width: 15%;"):
                    vuetify3.VSpacer()
                    
                vuetify3.VBtn(
                    "Import files",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true",
                )
    
                with vuetify3.VDialog(
                    v_model=("dialog_visible", False),
                    max_width="500"
                ):
                    with vuetify3.VCard():
                        vuetify3.VCardTitle("Import files")

                        with vuetify3.VCardText():
                            with vuetify3.VRow(classes="my-3 mx-0"):
                                with vuetify3.VCol(cols="9", classes="pa-0 pr-2"):
                                    vuetify3.VTextField(
                                        variant="outlined",
                                        prepend_icon="mdi-server",
                                        label="Import from URLs",
                                        v_model=("remote_files_location", None),
                                        density="comfortable",
                                        placeholder="url separated with '&' character",
                                        hide_details="auto",
                                    )
                                vuetify3.VDivider(classes="my-5")
                                vuetify3.VFileUpload(
                                    v_model=("files", None),
                                    density="comfortable",
                                    clearable=True,
                                    multiple=True,
                                )
            
                        with vuetify3.VCardActions():
                            vuetify3.VSpacer()
                            vuetify3.VBtn(
                                "Close",
                                color="red",
                                click="dialog_visible = false"
                            )
                            vuetify3.VBtn(
                                "Import...",
                                color="green",
                                click="dialog_visible = false; execute_action = true"
                            )
                ptc.PalettePicker(flat=True)

        with layout.drawer as drawer:
            drawer.width=450
            with vuetify3.VContainer(fluid=True):
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
                                open_all=True,
                                item_props=True,
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
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            with vuetify3.VExpansionPanels(style="display: initial;"):
                                with html.Div(v_if=("ui_active_node_reservoir_type_rep === 'IjkGrid'",)):
                                    panel_slicers.SlicerControls()
                            with html.Div(v_if=("ui_active_node_reservoir_type.includes('Property')")):
                                vuetify3.VTextField("{{ ui_active_node_reservoir }} => {{ ui_active_node_reservoir_type }}")
                                #ptc.ColorBy()
                    
                    with vuetify3.VWindowItem(value="surface"):
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
                                open_all=True,
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
                                select_strategy="classic",
                                update_selected="ui_select_node_surface = $event",
                            )
                        # Attribut Node CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            vuetify3.VTextField("{{ ui_active_node_surface }} => {{ ui_active_node_surface_type }}")
                            #ptc.proxy_editor.PlaneEditorPanel()

                    with vuetify3.VWindowItem(value="well"):
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
                                open_all=True,
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
                                indent_lines="default",
                                update_selected="ui_select_node_well = $event",
                            )
                        # Attribut Node CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            vuetify3.VTextField("{{ ui_active_node_well }} => {{ ui_active_node_well_type }}")
                            #ptc.proxy_editor.PlaneEditorPanel()
             
        with layout.content:
            with vuetify3.VContainer(
                fluid=True, classes="pa-0 fill-height position-relative"
            ):
                view = paraview.VtkRemoteView(
                    pvsimple.GetActiveViewOrCreate("RenderView") if pvsimple else None,
                    interactive_ratio=1,
                    interactive_quality=70,
                    namespace="time_view",
                    style="width: 100%; height: 100%;",
                )
                
                ptc.ResetCameraButtons(
                    classes = "position-absolute top-0 left-0 ma-2",
                    variant = "text",
                    color = "blue",
                    direction = "vertical",
                )
                                
                # 3. Contrôles du temps (Haut au Centre) - Utilisation de VRow pour le centrage
                with vuetify3.VRow(
                    justify="center", # Centre la VRow horizontalement (le bandeau)
                    classes="position-absolute top-0 w-100 pa-0 ma-0", 
                ):
                    # Conteneur flexible pour le Label et le TimeControl
                    with ptc.Div(
                        v_show=("ptc_show_vcr", False),
                        # Limite la largeur du bloc pour qu'il soit bien centré
                        style="width: 60%; min-width: 300px; max-width: 600px;",
                        # d-flex pour aligner les enfants horizontalement
                        # align-center pour aligner les enfants verticalement (important pour le label)
                        classes="ma-2 d-flex align-center", # ⬅️ CLÉS
                    ):
                        # Le Label (Texte simple)
                        ptc.VLabel(
                            "{{ ui_time_label }}",
                            v_if=("ptc_show_vcr"),
                            classes="mr-2 text-subtitle-1 font-weight-bold flex-shrink-0",
                            style="overflow: visible; white-space: nowrap; width: 100px;",
                        )
                
                        # Le TimeControl (prendra le reste de l'espace dans ce Div)
                        ptc.TimeControl(namespace="time_view",)
                
                with vuetify3.VRow(
                    justify="center", # Centre la VRow horizontalement (le bandeau)
                    classes="position-absolute top-50 w-100 pa-0 ma-0", 
                ):
                    ptc.VProgressLinear(
                        indeterminate=True,
                        absolute=True,
                        bottom=True,
                        color="blue",
                        active=("trame__busy",),
                    )
                
                # Link view callbacks
                server.controller.view_replace = view.replace_view
                server.controller.view_update = view.update
                server.controller.view_reset_camera = view.reset_camera
                server.controller.on_server_ready.add(server.controller.view_update)

        layout.footer.hide()

        return layout


