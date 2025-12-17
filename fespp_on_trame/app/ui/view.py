from trame.app import get_server
from paraview import simple as pvsimple
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html
from trame_server import Server
from typing import Literal
import ptc
import time

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

import fespp_on_trame.app.core.fespp_engine as fespp_engine
import fespp_on_trame.app.ui.panel.slicers as panel_slicers
import fespp_on_trame.app.ui.widget.custom_time_control as custom_time_control
import fespp_on_trame.app.ui.widget.custom_transform_editor as custom_transform_editor
from fespp_on_trame.app.ui.config.tree_selection import get_item_props_js

# new modular imports
from fespp_on_trame.app.ui.toolbar import Toolbar
from fespp_on_trame.app.ui.helpers import create_card
from fespp_on_trame.app.ui.import_dialog import ImportDialog
from fespp_on_trame.app.ui.tree_views import TreeViews

# NOTE: This file was partially refactored to improve maintainability.
# - Toolbar UI moved to `fespp_on_trame.app.ui.toolbar.Toolbar`
# - Import dialog moved to `fespp_on_trame.app.ui.import_dialog.ImportDialog`
# - Card helper moved to `fespp_on_trame.app.ui.helpers.create_card`


import contextlib


# -----------------------------------------------------------------------------
# Trame Server Setup and State Initialization
# -----------------------------------------------------------------------------

# Get the Trame server instance
server = get_server()
# Access Trame state (reactive variables shared between server and client)
state = server.state
# Access Trame controller (functions accessible from the client)
controller = server.controller

# Initialize state variables
state.dialog_visible = False     # Controls the visibility of the file import dialog
state.execute_action = False     # Flag to trigger the file processing function (run_action)
state.ptc_show_vcr = False       # Controls the visibility of the ParaView Time Control (VCR)
state.ui_time_label = ""         # Label for displaying current time step in the UI
state.drawer_width = 450         # State variable for the drawer width
state.is_dragging = False        # Flag to track the dragging state

state.init_height_dataexplorer = "600px"      # Initial height for the data explorer card
state.init_height_attribute = "600px"         # Initial height for the attribute card

# NOTE: Tree opened-nodes initialization is now handled by TreeViews class
# See: fespp_on_trame.app.ui.tree_views.TreeViews.__init__

# NOTE: Import action is now handled by ImportDialog class which manages its own state change handler
# See: fespp_on_trame.app.ui.import_dialog.ImportDialog._on_execute_action
        
# -----------------------------------------------------------------------------
# General UI Definition
# -----------------------------------------------------------------------------
def ui(server: Server, **kwargs) -> None:
    """
    Defines the main user interface layout and components using Trame's Vuetify3 bindings.
    """
    # Get logo from public folder using LocalFileManager
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")
    
    # Use the SinglePageWithDrawerLayout for the main structure (with a side panel)
    with SinglePageWithDrawerLayout(
        server, 
        width=("drawer_width", 450), # Initial width
        v_on_mousemove="""
            if(is_dragging) {
                // Calculates the new width
                drawer_width = $event.clientX;
            }
        """,
        v_on_mouseup="is_dragging = false", # Stops dragging
    ) as layout:
        
        # Set application title in the browser tab and toolbar
        layout.title.set_text(TRAME_APP_TITLE)

        # Application icon (logo)
        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        # Initialize import dialog (registers state change handler internally)
        import_dialog = ImportDialog(state, controller)

        # Initialize tree views (registers opened-nodes handler and initializes state)
        tv = TreeViews(controller, state)

        # Main application toolbar -> delegate to Toolbar class
        with layout.toolbar:
            toolbar = Toolbar(localFileManager, import_dialog)
            toolbar.render()
            toolbar = Toolbar(localFileManager, import_dialog)
            toolbar.render()
                            

        # Side Drawer (Navigation/Control Panel)
        with layout.drawer as drawer:
            # Resizing Handle (VDivider or VSheet)
            # Position the handle on the right edge and give it a 'resize' cursor style
            with vuetify3.VSheet(
                classes="position-absolute h-100", 
                style="right: -4px; cursor: ew-resize; z-index: 1000; width: 8px; background-color: transparent;", 
                v_on_mousedown="is_dragging = true", # Start dragging
            ):
                vuetify3.VDivider(vertical=True, classes="h-100") 
                
            with vuetify3.VContainer(fluid=True, classes="pa-0"): # Make the container fluid and remove its default padding
        
                # --- 1. Tabs (VTabs) ---
                with vuetify3.VTabs(v_model=("tab", None), 
                            classes="bg-grey-lighten-4", 
                            color="blue", 
                            density="comfortable",
                            grow=True,
                            selected_class="font-weight-bold text-blue"): 
                    vuetify3.VTab("Reservoir", value="reservoir")
                    vuetify3.VTab("Surface", value="surface")
                    vuetify3.VTab("Well", value="well")
                
                # --- 2. Tab Content (VWindow) ---
                with vuetify3.VWindow(v_model=("tab",), classes="pa-4"): 
            
                    # ------------------------------------
                    # Reservoir Tab Content
                    # ------------------------------------
                    with vuetify3.VWindowItem(value="reservoir"):
                        with html.Div(v_show="tab === 'reservoir'"):
                            # Data Explorer Treeview CARD
                            with create_card(
                                "Data Explorer",
                                "mdi-file-tree",
                                "init_height_dataexplorer",
                            ):
                                # Treeview for displaying reservoir data hierarchy (extracted)
                                with vuetify3.VSheet(classes="pa-3"):
                                    tv.reservoir_tree()
                            # Node Attribute CARD
                            with create_card(
                                "Attributes",
                                "mdi-information",
                                "init_height_attribute",
                            ):
                                with vuetify3.VSheet(classes="pa-3"): 
                                    # Conditional display for IjkGrid slicer controls
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-4"):
                                        with html.Div(v_if=("ui_active_node_reservoir_type_rep === 'IjkGrid'",)):
                                            panel_slicers.SlicerControls()
                                        # Placeholder for property attributes
                                        with html.Div(v_if=("ui_active_node_reservoir_type.includes('Property')")):
                                            vuetify3.VTextField(
                                                "{{ ui_active_node_reservoir }} => {{ ui_active_node_reservoir_type }}",
                                                variant="outlined", 
                                                density="compact",
                                                hide_details=True
                                            )
                            
                    # Surface Tab Content
                    with vuetify3.VWindowItem(value="surface"):
                        with html.Div(v_show="tab === 'surface'"):
                            # Data Explorer Treeview CARD for surface data
                            with create_card(
                                "Data Explorer",
                                "mdi-file-tree",
                                "init_height_dataexplorer"
                            ):
                                # Treeview for surfaces (extracted)
                                tv.surface_tree()
                            # Node Attribute CARD
                            with create_card(
                                "Attributes",
                                "mdi-information",
                                "init_height_attribute"
                            ):
                                vuetify3.VTextField("{{ ui_active_node_surface }} => {{ ui_active_node_surface_type }}")
    
                    # Well Tab Content
                    with vuetify3.VWindowItem(value="well"):
                        with html.Div(v_show="tab === 'well'"):
                            # Data Explorer Treeview CARD for well data
                            with create_card(
                                "Data Explorer",
                                "mdi-file-tree",
                                "init_height_dataexplorer"
                            ):
                                # Treeview for wells (extracted)
                                tv.well_tree()
                            # Node Attribute CARD
                            with create_card(
                                "Attributes",
                                "mdi-information",
                                "init_height_attribute"
                            ):
                                vuetify3.VTextField("{{ ui_active_node_well }} => {{ ui_active_node_well_type }}")
                            
                # General parameters CARD
                # On utilise la fonction d'aide 'create_card' pour avoir le même look and feel
                # que "Data Explorer" et "Attributes".
                with create_card(
                    "General Display Settings",
                    "mdi-cogs", # Icône appropriée pour les paramètres généraux
                    "init_height_attribute"
                ):
                    # Tout le contenu de la carte est placé dans un VSheet avec padding (grâce à create_card),
                    # puis on utilise VExpansionPanels/VExpansionPanel pour le contenu interne.         
                    with vuetify3.VExpansionPanels(classes="mt-0", elevation=10,):
                        with vuetify3.VExpansionPanel(
                            title="Display Options", # Titre du panneau déroulant
                            value="display_options",
                            elevation=0,
                            classes="border-b"
                        ) as expansion_panel:
                            # 💡 VExpansionPanelText est CRUCIAL pour que les composants aient un padding correct
                            with vuetify3.VExpansionPanelText(classes="pa-4"):
                
                                # 1. Représentation (Surface, Wireframe...)
                                html.Div("Representation", classes="text-caption text-uppercase font-weight-bold mb-n1")
                                ptc.RepresentBy(
                                    color = "blue",
                                    base_color="blue", 
                                    item_color="blue",
                                    flat=True,
                                )
                
                                vuetify3.VDivider(classes="my-3")
                
                                # 2. Transformation (Échelle, etc.)
                                html.Div("Transformation", classes="text-caption text-uppercase font-weight-bold mb-n1")
                                custom_transform_editor.GlobalTransformEditor(
                                    show_translation=False,
                                    show_scale=True,
                                    show_origin=False,
                                    show_orientation=False,
                                    classes="text-blue",
                                )
                
                                vuetify3.VDivider(classes="my-3")
                
                                # 3. Couleur de fond (Background Color)
                                with html.Div(classes="d-flex align-center pt-2"): 
                                    html.Span(
                                        "Background Color:", 
                                        classes="text-caption font-weight-medium mr-3" # Label pour le picker
                                    )
                                    ptc.PalettePicker(
                                        color = "blue",
                                        base_color="blue", 
                                        item_color="blue",
                                        flat=True,
                                    )
                        
        # Main Content Area (3D Viewer)
        with layout.content:
            vuetify3.VOverlay(
                v_if=("trame__busy",),
                v_model=("trame__busy",),
                persistent=True,
                # 🚨 Add a visible scrim to ensure the background is not completely transparent
                scrim="rgba(0, 0, 0, 0.7)", 
                class_="d-flex align-center justify-center", 
            )
            
            with vuetify3.VContainer(
                fluid=True, classes="pa-0 fill-height position-relative"
            ):
                # The core ParaView rendering component
                view = paraview.VtkRemoteView(
                    pvsimple.GetActiveViewOrCreate("RenderView") if pvsimple else None,
                    interactive_ratio=1,
                    interactive_quality=70,
                    namespace="time_view",
                    style="width: 100%; height: 100%;",
                )
                
                # Floating buttons for camera reset
                ptc.ResetCameraButtons(
                    classes = "position-absolute top-0 left-0 ma-2",
                    variant = "text",
                    color = "blue",
                    direction = "vertical",
                )
                            
                # Time controls (Top Center) - Uses VRow for horizontal centering
                with vuetify3.VRow(
                    justify="center", 
                    classes="position-absolute top-0 w-100 pa-0 ma-0", 
                ):
                    # Flexible container for the Label and TimeControl
                    with ptc.Div(
                        v_show=("ptc_show_vcr", False), 
                        style="display: inline-block;", 
                        classes="ma-2 d-flex align-center", 
                    ):
                        custom_time_control.custom_time_control_ui(custom_time_control.CustomTimeControl(namespace="time_view",play_delay=0.1))
                
                # Loading Progress Bar 
                with vuetify3.VRow(
                    v_if=("trame__busy",),
                    justify="center", # Centers the VRow horizontally
                    classes="position-absolute top-50 w-100 pa-0 ma-0", 
                ):
                    ptc.VProgressLinear(
                            indeterminate=True,
                            absolute=True,
                            bottom=True,
                            color="green-darken-1",
                    )
                    ptc.VProgressLinear(
                            reverse=True,
                            indeterminate=True,
                            absolute=True,
                            bottom=True,
                            color="blue-darken-4",
                    )
                    ptc.VAlert(children=["{{ view_loading_message }}"], type="info", prominent=True ,color="blue-grey-lighten-4", classes="position-absolute top-50 w-100 pa-0 ma-0")

                # Link view callbacks to the server controller for remote actions
                server.controller.view_replace = view.replace_view
                server.controller.view_update = view.update
                server.controller.view_reset_camera = view.reset_camera
                # Ensure the view updates when the server is fully ready
                server.controller.on_server_ready.add(server.controller.view_update)

        # Hide the default footer
        layout.footer.hide()

        return layout