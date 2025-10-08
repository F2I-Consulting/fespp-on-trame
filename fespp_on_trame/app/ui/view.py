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
import fespp_on_trame.app.ui.widget.custom_time_control as custom_time_control

import contextlib
from fespp_on_trame.app.io.http import download_file_from_url
from fespp_on_trame.app.io.drop_files import save_uploaded_files
from tempfile import mkdtemp


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

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
class Representation:
    """Defines integer constants for ParaView data representations."""
    Points = 0
    Wireframe = 1
    Surface = 2
    SurfaceWithEdges = 3

# -----------------------------------------------------------------------------
# State Change Handlers (Server-Side Logic)
# -----------------------------------------------------------------------------

# Function to execute a specific action (triggered when state.execute_action changes to True)
@state.change("execute_action")
def run_action(execute_action, **kwargs):
    """
    Handles file import logic, either from remote URLs or local uploads.
    It retrieves EPC file paths and calls the controller to load them.
    """
    if execute_action and state.remote_files_location:
        # Case 1: Import from remote URLs (e.g., from an input field)
        list_url = state.remote_files_location.split('|')
        temp_dir = mkdtemp()
        epc_paths = []
        
        # Download files from URLs
        for url in list_url:
            file_name = download_file_from_url(url, temp_dir)
        
            if file_name.lower().endswith('.epc'):
                epc_paths.append(file_name)
                
        # Load the collected EPC files using a controller function
        for epc_path in epc_paths:
            controller.load_epc_file(epc_path)
        
        # Reset state variables after action completion
        state.execute_action = False
        state.remote_epc_file_location = None
        state.remote_h5_file_location = None
        
    elif execute_action and state.files:
        # Case 2: Import from local file uploads
        # Save uploaded files to a temporary location and get the paths
        epc_paths = save_uploaded_files(state.files)
        # Load the collected EPC files
        for epc_path in epc_paths:
            controller.load_epc_file(epc_path)
        # Clear the file list in the state
        state.files = None
        
    # Ensure the execution flag is reset regardless of the path taken
    state.execute_action = False

# -----------------------------------------------------------------------------
# UI Component Helpers
# -----------------------------------------------------------------------------

# Default Card component definition
def create_card(title, icon, height=None):
    """
    Creates a Vuetify VCard with a styled header and scrollable content area.
    This component is used to structure panels in the application drawer.
    """
    # Base card properties
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
        # Styled title section
        card_title_props = {"classes": "d-flex align-center py-1", "style": "background-color: #b3b6b7;"}
        with vuetify3.VCardTitle(**card_title_props):
            vuetify3.VIcon(icon)
            html.Div(title)
        vuetify3.VDivider()
        
        # Content area with dynamic max-height and overflow-y for scrolling
        if height:
            # Calculate max-height based on card height (vh units) to account for header/footer
            height_value = int(height[:-2])
            max_height_value = height_value - 5
            max_height = f"{max_height_value}vh"
            return vuetify3.VCardText(style=f"overflow-y: auto; max-height: {max_height};")
        else:
            return vuetify3.VCardText(style="overflow-y: auto;")
    
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
    with SinglePageWithDrawerLayout(server, width=450) as layout:
        # Set application title in the browser tab and toolbar
        layout.title.set_text(TRAME_APP_TITLE)

        # Application icon (logo)
        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        # Main application toolbar
        with layout.toolbar:
            with vuetify3.VContainer(
                classes="fill-height",
            ):
                vuetify3.VSpacer()
                
                # Widget to select representation (e.g., Surface, Wireframe) from ptc library
                with html.Div(style="width: 15%;"):
                    ptc.RepresentBy(
                        color = "blue",
                        base_color="blue", 
                        item_color="blue"
                    )
                
                # Input field for Z-axis scaling
                with html.Div(style="width: 5%;"):
                    vuetify3.VTextField(
                        v_model=("ui_scale_z", 1.0), # Bind to state variable 'ui_scale_z'
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
                    
                # Button to open the Import Files dialog
                vuetify3.VBtn(
                    "Import files",
                    variant="tonal",
                    color="blue",
                    click="dialog_visible = true", # Open the dialog
                )
    
                # File Import Dialog (Modal)
                with vuetify3.VDialog(
                    v_model=("dialog_visible", False), # Controlled by state.dialog_visible
                    max_width="500"
                ):
                    with vuetify3.VCard():
                        vuetify3.VCardTitle("Import files")

                        with vuetify3.VCardText():
                            with vuetify3.VRow(classes="my-3 mx-0"):
                                with vuetify3.VCol(cols="9", classes="pa-0 pr-2"):
                                    # Input field for remote file URLs
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
                                # Component for local file upload
                                vuetify3.VFileUpload(
                                    v_model=("files", None), # Bind to state.files for file data
                                    density="comfortable",
                                    clearable=True,
                                    multiple=True,
                                )
                    
                        with vuetify3.VCardActions():
                            vuetify3.VSpacer()
                            # Close button
                            vuetify3.VBtn(
                                "Close",
                                color="red",
                                click="dialog_visible = false"
                            )
                            # Import button (closes dialog and triggers server action)
                            vuetify3.VBtn(
                                "Import...",
                                color="green",
                                click="dialog_visible = false; execute_action = true" # Triggers the run_action function
                            )
                # Widget for color palette selection
                ptc.PalettePicker(flat=True)

        # Side Drawer (Navigation/Control Panel)
        with layout.drawer as drawer:
            drawer.width=450
            with vuetify3.VContainer(fluid=True):
                # Tabs for different data categories (Reservoir, Surface, Well)
                with vuetify3.VTabs(v_model=("tab", None)):
                    with vuetify3.VTab(value="reservoir"):
                        html.Div("Reservoir")
                    with vuetify3.VTab(value="surface"):
                        html.Div("Surface")
                    with vuetify3.VTab(value="well"):
                        html.Div("Well")
                        
                # Tab content windows
                with vuetify3.VCardText(), vuetify3.VWindow(v_model=("tab",)):
                    
                    # Reservoir Tab Content
                    with vuetify3.VWindowItem(value="reservoir"):
                        # Data Explorer Treeview CARD
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "60vh"
                        ):
                            # Treeview for displaying reservoir data hierarchy
                            vuetify3.VTreeview(
                                # Style settings
                                slim=True,
                                density="compact",
                                open_all=True,
                                item_props=True,
                                # Data binding
                                item_value="id",
                                items=("ui_subtree_reservoir", state.ui_subtree_reservoir), # Data source for the tree
                                # Activation logic (single node activation)
                                activated=("ui_active_node_reservoir", []),
                                activatable=True,
                                active_strategy="single-independent",
                                update_activated="ui_active_node_reservoir = $event",
                                color="primary",
                                open_on_click=False,
                                # Selection logic (single leaf selection)
                                selected=("ui_select_node_reservoir", []),
                                selectable=True,
                                select_strategy="single-leaf",
                                update_selected="ui_select_node_reservoir = $event",
                            )
                            
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            # Conditional display for IjkGrid slicer controls
                            with vuetify3.VExpansionPanels(style="display: initial;"):
                                with html.Div(v_if=("ui_active_node_reservoir_type_rep === 'IjkGrid'",)):
                                    panel_slicers.SlicerControls()
                                # Placeholder for property attributes
                                with html.Div(v_if=("ui_active_node_reservoir_type.includes('Property')")):
                                    vuetify3.VTextField("{{ ui_active_node_reservoir }} => {{ ui_active_node_reservoir_type }}")
                                    #ptc.ColorBy() # Would typically be used here for coloring by property
                        
                    # Surface Tab Content
                    with vuetify3.VWindowItem(value="surface"):
                        # Data Explorer Treeview CARD for surface data
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "60vh"
                        ):
                            # Treeview definition for surfaces (similar structure to reservoir)
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
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            vuetify3.VTextField("{{ ui_active_node_surface }} => {{ ui_active_node_surface_type }}")
                            #ptc.proxy_editor.PlaneEditorPanel()

                    # Well Tab Content
                    with vuetify3.VWindowItem(value="well"):
                        # Data Explorer Treeview CARD for well data
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "60vh"
                        ):
                            # Treeview definition for wells
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
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "30vh"
                        ):
                            vuetify3.VTextField("{{ ui_active_node_well }} => {{ ui_active_node_well_type }}")
                            #ptc.proxy_editor.PlaneEditorPanel()
            
        # Main Content Area (3D Viewer)
        with layout.content:
            with vuetify3.VContainer(
                fluid=True, classes="pa-0 fill-height position-relative"
            ):
                # The core ParaView rendering component
                view = paraview.VtkRemoteView(
                    # Get the active ParaView view or create a new one
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
                        
                # 3. Time controls (Top Center) - Uses VRow for horizontal centering
                with vuetify3.VRow(
                    justify="center", # Centers the VRow content horizontally
                    classes="position-absolute top-0 w-100 pa-0 ma-0", 
                ):
                    # Flexible container for the Label and TimeControl
                    with ptc.Div(
                        v_show=("ptc_show_vcr", False), # Conditional display of the time controls
                        # Limits the block width for better centering aesthetics
                        style="width: 60%; min-width: 300px; max-width: 600px;",
                        # d-flex for horizontal alignment, align-center for vertical alignment
                        classes="ma-2 d-flex align-center", 
                    ):
                        # Time Step Label (Text)
                        ptc.VLabel(
                            "{{ ui_time_label }}",
                            v_if=("ptc_show_vcr"),
                            classes="mr-2 text-subtitle-1 font-weight-bold flex-shrink-0",
                            # Fixed width prevents layout shift when content changes
                            style="overflow: visible; white-space: nowrap; width: 100px;",
                        )
                    
                        # The Time Control widget
                        ptc.TimeControl(namespace="time_view",)
                
                # Loading Progress Bar (Center, hidden when Trame is not busy)
                with vuetify3.VRow(
                    justify="center", # Centers the VRow horizontally
                    classes="position-absolute top-50 w-100 pa-0 ma-0", 
                ):
                    ptc.VProgressLinear(
                        indeterminate=True,
                        absolute=True,
                        bottom=True,
                        color="blue",
                        active=("trame__busy",), # Automatically shows when Trame is busy
                    )
                
                # Link view callbacks to the server controller for remote actions
                server.controller.view_replace = view.replace_view
                server.controller.view_update = view.update
                server.controller.view_reset_camera = view.reset_camera
                # Ensure the view updates when the server is fully ready
                server.controller.on_server_ready.add(server.controller.view_update)

        # Hide the default footer
        layout.footer.hide()

        return layout
