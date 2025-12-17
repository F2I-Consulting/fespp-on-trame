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
state.drawer_width = 450         # State variable for the drawer width
state.is_dragging = False        # Flag to track the dragging state

state.init_height_dataexplorer = "600px"      # Initial height for the data explorer card
state.init_height_attribute = "600px"         # Initial height for the attribute card

# -----------------------------------------------------------------------------
# State Change Handlers (Server-Side Logic)
# -----------------------------------------------------------------------------

# Initialize opened nodes only once
@controller.set("init_opened_nodes")
def init_opened_nodes(tree_data):
    """Returns only the IDs of the first level nodes"""
    return [node["id"] for node in tree_data if node.get("parent_id") == 0 or "parent_id" not in node]

# Call after building your trees
state.ui_opened_reservoir = controller.init_opened_nodes(state.ui_subtree_reservoir)
state.ui_opened_surface = controller.init_opened_nodes(state.ui_subtree_surface)
state.ui_opened_well = controller.init_opened_nodes(state.ui_subtree_well)


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

def create_card(title, icon, height=None):
    """
    Creates a Vuetify VCard that is vertically resizable (CSS resize: vertical).
    The content (VCardText) adapts to the new height and is scrollable.
    """

    # 1. Base Card Properties (Flat, Bordered + Resizable)
    card_props = {
        "classes": "pa-0 mb-4 border d-flex flex-column", 
        "elevation": 0,
        "flat": True,
        "tile": False,
        "style": "resize: vertical; overflow: hidden; min-height: 250px;" 
    }
    
    # Handling initial height
    if height:
        card_props["style"] = card_props["style"].replace("250px", height)
        card_props["height"] = height 

    with vuetify3.VCard(**card_props):
        
        # 2. Styled Title Section (VToolbar)
        with vuetify3.VToolbar(
            density="compact",
            classes="bg-blue-grey-lighten-5 flex-grow-0", 
            color="blue-grey-darken-2"
        ):
            vuetify3.VIcon(icon, classes="mr-3")
            vuetify3.VToolbarTitle(title, classes="text-subtitle-1 font-weight-medium")
            
        # 3. Adaptive and Scrollable Content Area
        return vuetify3.VCardText(
            classes="pa-3 flex-grow-1 overflow-y-auto", 
        )
        
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

        # Main application toolbar
        with layout.toolbar:
            
            vuetify3.VSpacer()
            with vuetify3.VContainer(
                classes="fill-height",
                ):
                vuetify3.VSpacer() 
                
                # Widget to select representation (e.g., Surface, Wireframe) from ptc library
                #with html.Div(style="width: 15%;", classes="d-flex align-center"):
                #    ptc.RepresentBy(
                #        color = "blue",
                #        base_color="blue", 
                #        item_color="blue"
                #    )
                
                # Input field for Z-axis scaling
                #with html.Div(style="width: 5%;", classes="d-flex align-center"): 
                #    vuetify3.VTextField(
                #        v_model=("ui_scale_z", 1.0), # Bind to state variable 'ui_scale_z'
                #        label="Z scale",
                #        hide_details=True,
                #        density="compact",
                #        variant="outlined",
                #        color="blue",
                #        base_color="blue",
                #        bg_color="white",
                #        reverse=True,
                #        type="number",
                #    )
                
                vuetify3.VSpacer()
                
                with html.Div(style="width: 15%;", classes="d-flex align-center"): 

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
                    max_width="600" # Increased width for better spacing
                ):
                    with vuetify3.VCard():
        
                        # 1. Header (VCardTitle) - Clear and visual
                        with vuetify3.VCardTitle(classes="d-flex align-center bg-blue-grey-lighten-5"): 
                            # Light background color and vertical centering
                            vuetify3.VIcon(icon="mdi-cloud-upload", class_="mr-0", color="blue")
                            html.Span("Import Files", classes="pl-4") # Updated Title
        
                        # 2. Content (VCardText) - Action separation
                        with vuetify3.VCardText(classes="py-5"): # Added vertical padding
            
                            # --- Section 1: Import from URL ---
                            with vuetify3.VRow(classes="ma-0 mb-5"):
                                with vuetify3.VCol(cols="12", classes="pa-0"):
                                    with html.Div(classes="d-flex align-center mb-2"):
                                        vuetify3.VIcon(icon="mdi-link-variant", class_="mr-0", color="blue-grey-darken-2")
                                        html.Span("Import from Remote URL", classes="text-h6 font-weight-regular pl-4")
                            
                                    vuetify3.VTextField(
                                        variant="outlined",
                                        label="Enter URLs (separated with '&' character)", # Label
                                        v_model=("remote_files_location", None),
                                        density="comfortable",
                                        placeholder="Ex: http://example.com/file1.obj&http://example.com/file2.ply",
                                        hide_details="auto",
                                        clearable=True
                                    )
                
                            vuetify3.VDivider(classes="mb-5")
                
                            # --- Section 2: Local File Upload ---
                            with vuetify3.VRow(classes="ma-0"):
                                with vuetify3.VCol(cols="12", classes="pa-0"):
                                    with html.Div(classes="d-flex align-center mb-3"):
                                        vuetify3.VIcon(icon="mdi-folder-upload", class_="mr-0", color="blue-grey-darken-2")
                                        html.Span("Upload Local Files", classes="text-h6 font-weight-regular pl-4")
                            
                                    vuetify3.VFileUpload(
                                        v_model=("files", None), # Bind to state.files for file data
                                        density="comfortable",
                                        clearable=True,
                                        multiple=True,
                                        prepend_icon="mdi-upload-multiple", 
                                        label="Drag and drop or click to select files", # Label
                                        classes="pa-3", 
                                    )

                        # 3. Actions (VCardActions)
                        with vuetify3.VCardActions(classes="pa-4 bg-blue-grey-lighten-5"): # Light background for actions
                            vuetify3.VSpacer()

                            # Cancel Button 
                            vuetify3.VBtn(
                                "Cancel", 
                                variant="text", 
                                color="blue-grey-darken-2",
                                click="dialog_visible = false"
                            )
                
                            # Import Button 
                            vuetify3.VBtn(
                                "Import", 
                                color="blue",
                                variant="elevated", 
                                click="dialog_visible = false; execute_action = true", # Triggers the run_action function
                                prepend_icon="mdi-check-circle" 
                            )
            
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
                                # Treeview for displaying reservoir data hierarchy
                                with vuetify3.VSheet(classes="pa-3"): 
                                    with vuetify3.VTreeview(
                                        slim=True,
                                        density="comfortable", 
                                        opened=("ui_opened_reservoir", []),
                                        line="connected", 
                                        # Data binding
                                        item_value="id",
                                        items=("ui_subtree_reservoir", []), 
                                        # Activation logic
                                        activated=("ui_active_node_reservoir", []),
                                        activatable=True,
                                        active_strategy="single-independent",
                                        update_activated="ui_active_node_reservoir = $event",
                                        color="primary",
                                        open_on_click=False,
                                        # Selection logic
                                        selected=("ui_select_node_reservoir", []),
                                        selectable=True,
                                        select_strategy="single-leaf",
                                        item_props=True,
                                        update_selected="ui_select_node_reservoir = $event",
                                        indent_lines="default",
                                        separate_roots =True,
                                    ):
                                        with vuetify3.Template(v_slot_prepend="{ item }"):
                                            vuetify3.VIcon(
                                                "{{item.icon}}", 
                                                size="small", 
                                                color="green-darken-1"
                                            )
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
                                # Treeview definition for surfaces (similar structure to reservoir)
                                with vuetify3.VTreeview(
                                    slim=True,
                                    density="compact",
                                    opened=("ui_opened_surface", []),
                                    line="connected", 
                                    # data
                                    item_value="id",
                                    items=("ui_subtree_surface", []),
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
                                    indent_lines="default",
                                    separate_roots =True,
                                ):
                                    with vuetify3.Template(v_slot_prepend="{ item }"):
                                        vuetify3.VIcon(
                                            "{{item.icon}}", 
                                            size="small", 
                                            color="green-darken-1"
                                    )
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
                                # Treeview definition for wells
                                with vuetify3.VTreeview(
                                    slim=True,
                                    density="compact",
                                    opened=("ui_opened_well", []),
                                    line="connected", 
                                    # data
                                    item_value="id",
                                    items=("ui_subtree_well", []),
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
                                    separate_roots =True,
                                    update_selected="ui_select_node_well = $event",
                                ):
                                    with vuetify3.Template(v_slot_prepend="{ item }"):
                                        vuetify3.VIcon(
                                            "{{item.icon}}", 
                                            size="small", 
                                            color="green-darken-1"
                                    )
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