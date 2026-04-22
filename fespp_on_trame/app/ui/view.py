from trame.app import get_server
from paraview import simple as pvsimple
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as vuetify3, paraview, html, client as trame_client
from trame_server import Server
from typing import Literal
import ptc

from fespp_on_trame.constants import TRAME_APP_TITLE, PUBLIC_PATH

from trame.assets.local import LocalFileManager

import fespp_on_trame.app.core.fespp_engine as fespp_engine
import fespp_on_trame.app.ui.panel.slicers as panel_slicers
from fespp_on_trame.app.ui.panel.solid_color_panel import SolidColorPanel
from fespp_on_trame.app.ui.panel.representation_type_panel import RepresentationTypePanel
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
state.ui_time_label = ""         # Label for displaying current time step in the UI
state.drawer_width = 500         # Initial drawer width (set once; resize is handled via pure JS)

state.init_height_dataexplorer = "50vh"        # Initial height for the data explorer card
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
        width=("drawer_width", 500), # Initial width (JS resize script handles live resizing)
    ) as layout:
        
        # Set application title in the browser tab and toolbar
        layout.title.set_text(TRAME_APP_TITLE)

        # CSS fixes for ptc components (trame_client.Style injects into document head)
        trame_client.Style(".te-align-center .v-row { align-items: center; }")

        # Hide default trame footer bar ("Powered by trame", "?", copyright)
        # trame_client.Style injects a real <style> in the document head (unlike html.Style)
        # --v-layout-bottom reset prevents Vuetify from reserving space for the hidden footer
        trame_client.Style(
            "footer, .v-footer {"
            "  display: none !important;"
            "  height: 0 !important;"
            "  min-height: 0 !important;"
            "  overflow: hidden !important;"
            "}"
            ".v-layout { --v-layout-bottom: 0 !important; }"
        )

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

        # Side Drawer (Navigation/Control Panel)
        with layout.drawer as drawer:
            # Upload progress overlay — covers the full drawer while uploading
            with html.Div(
                v_show="upload_uploading",
                style=(
                    "position: absolute; inset: 0; z-index: 1001;"
                    " background: rgba(0,0,0,0.55);"
                    " display: flex; flex-direction: column;"
                    " align-items: center; justify-content: center; gap: 16px;"
                ),
            ):
                vuetify3.VProgressCircular(
                    indeterminate=("upload_progress === 0",),
                    model_value=("upload_progress", 0),
                    color="blue",
                    size=64,
                    width=6,
                )
                html.P(
                    "{{ upload_progress > 0 ? 'Upload… ' + upload_progress + '%' : 'Transfert en cours…' }}",
                    style="color: white; font-size: 0.95rem; margin: 0;",
                )

            # Resizing Handle (VDivider or VSheet)
            # Position the handle on the right edge and give it a 'resize' cursor style
            with vuetify3.VSheet(
                classes="position-absolute h-100 fespp-drawer-resize-handle",
                style="right: -4px; cursor: ew-resize; z-index: 1000; width: 8px; background-color: transparent;",
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
                    vuetify3.VTab("Reservoir ({{ ui_subtree_reservoir ? ui_subtree_reservoir.length : 0 }})", value="reservoir")
                    vuetify3.VTab("Surface ({{ ui_subtree_surface ? ui_subtree_surface.length : 0 }})", value="surface")
                    vuetify3.VTab("Well ({{ ui_subtree_well ? ui_subtree_well.length : 0 }})", value="well")
                
                # --- 2. Tab Content (always-rendered, visibility via v_show) ---
                with html.Div(classes="pa-4"):

                    # ------------------------------------
                    # Reservoir Tab Content
                    # ------------------------------------
                    with html.Div(v_show="tab === 'reservoir'"):
                        # Data Explorer Treeview CARD
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer",
                        ):
                            # Treeview for displaying reservoir data hierarchy (extracted)
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.reservoir_tree()
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute",
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                # Show attribute controls only when a reservoir node is active
                                with html.Div(v_if="ui_active_node_reservoir && ui_active_node_reservoir.length > 0"):
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        panel_slicers.SlicerControls()

                                        # Display type per representation (Surface / Wireframe / …)
                                        RepresentationTypePanel()

                                        # Merged Colors & Opacity panel — Property/Solid toggle,
                                        # color picker (Solid) and LUT/PWF editor (Property)
                                        SolidColorPanel()

                    # Surface Tab Content
                    with html.Div(v_show="tab === 'surface'"):
                        # Data Explorer Treeview CARD for surface data
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.surface_tree()
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                # Only show attributes if active node is also selected
                                with html.Div(v_if="ui_active_node_surface.length > 0 && ui_select_node_surface.includes(ui_active_node_surface[0])"):
                                    vuetify3.VTextField("{{ ui_active_node_surface }} => {{ ui_active_node_surface_type }}")
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        RepresentationTypePanel()
                                        SolidColorPanel()

                    # Well Tab Content
                    with html.Div(v_show="tab === 'well'"):
                        # Data Explorer Treeview CARD for well data
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.well_tree()
                        # Node Attribute CARD
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                # Only show attributes if active node is also selected
                                with html.Div(v_if="ui_active_node_well.length > 0 && ui_select_node_well.includes(ui_active_node_well[0])"):
                                    vuetify3.VTextField("{{ ui_active_node_well }} => {{ ui_active_node_well_type }}")
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        RepresentationTypePanel()
                                        SolidColorPanel()
                            
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
                            with vuetify3.VExpansionPanelText(classes="pa-2"):

                                # Display type (Surface / Wireframe / …) is now per-representation;
                                # see RepresentationTypePanel inside each rep's attribute panel.

                                # Transformation (Scale Z only) — stays global on purpose:
                                # vertical exaggeration only makes sense across the whole scene.
                                html.Div("Transformation", classes="text-caption text-uppercase font-weight-bold mb-n1")
                                te = ptc.TransformEditor(
                                    show_translation=False,
                                    show_scale=True,
                                    show_origin=False,
                                    show_orientation=False,
                                    show_apply_button=True,
                                    classes="text-blue te-align-center",
                                )
                                te.set_components_visibilities({
                                    te.scale_name.x: False,
                                    te.scale_name.y: False,
                                })

                                def _apply_global_scale():
                                    scale_data = te.typed_state.data.scale
                                    scale = [scale_data.x.value, scale_data.y.value, scale_data.z.value]
                                    view = pvsimple.GetActiveViewOrCreate("RenderView")
                                    for _, source in pvsimple.GetSources().items():
                                        display = pvsimple.GetDisplayProperties(source, view=view)
                                        if display and display.Visibility == 1:
                                            try:
                                                display.Scale = scale
                                                display.DataAxesGrid.Scale = scale
                                                display.PolarAxes.Scale = scale
                                            except AttributeError:
                                                pass
                                    pvsimple.Render()
                                    controller.view_update()

                                te.bind_on_apply_button_clicked(_apply_global_scale)
                
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
                        
        # Main Content Area (3D Viewer + Log panel below)
        with layout.content:
            vuetify3.VOverlay(
                v_if=("trame__busy",),
                v_model=("trame__busy",),
                persistent=True,
                scrim="rgba(0, 0, 0, 0.7)",
                class_="d-flex align-center justify-center",
            )

            # Flex column: 3D view grows, log panel stays at bottom without overlapping
            with html.Div(style="display: flex; flex-direction: column; height: 100%; width: 100%;"):

                # ---- 3D Render area ----
                with html.Div(style="flex: 1; position: relative; overflow: hidden; min-height: 0;"):
                    view = paraview.VtkRemoteView(
                        pvsimple.GetActiveViewOrCreate("RenderView") if pvsimple else None,
                        interactive_ratio=0.5,
                        interactive_quality=60,
                        namespace="time_view",
                        style="width: 100%; height: 100%;",
                    )

                    # Floating buttons for camera reset
                    ptc.ResetCameraButtons(
                        classes="position-absolute top-0 left-0 ma-2",
                        variant="text",
                        color="blue",
                        direction="vertical",
                    )

                    # Time controls (Top Center)
                    with vuetify3.VRow(
                        justify="center",
                        classes="position-absolute top-0 w-100 pa-0 ma-0",
                    ):
                        with ptc.Div(
                            v_if=("ptc_show_vcr", False),
                            style="display: inline-block;",
                            classes="ma-2 d-flex align-center",
                        ):
                            ptc.TimeControl(namespace="time_view", time_expression="ui_time_label")

                    # Loading Progress Bar
                    with html.Div(
                        v_if=("trame__busy",),
                        style="position: absolute; bottom: 0; width: 100%; left: 0;",
                    ):
                        ptc.VProgressLinear(indeterminate=True, color="green-darken-1")
                        ptc.VProgressLinear(reverse=True, indeterminate=True, color="blue-darken-4")
                        ptc.VAlert(
                            children=["{{ view_loading_message }}"],
                            type="info",
                            prominent=True,
                            color="blue-grey-lighten-4",
                            classes="w-100 pa-0 ma-0",
                        )

                    # Link view callbacks
                    server.controller.view_replace = view.replace_view
                    server.controller.view_update = view.update
                    server.controller.view_reset_camera = view.reset_camera
                    server.controller.on_server_ready.add(server.controller.view_update)

                # ---- VTK Log Panel — visible below the 3D view only when messages exist ----
                with html.Div(
                    v_show="vtk_log_messages && vtk_log_messages.length > 0",
                    style=(
                        "flex-shrink: 0; position: relative;"
                        " background: rgba(18,18,18,0.97);"
                        " border-top: 2px solid #444;"
                    ),
                ):
                    # Floating action buttons — top-right, offset left to avoid scrollbar overlap
                    with html.Div(
                        style=(
                            "position: absolute; top: 2px; right: 28px; z-index: 200;"
                            " display: flex; flex-direction: column; gap: 3px; align-items: flex-end;"
                        ),
                    ):
                        vuetify3.VBtn(
                            "Clear",
                            size="x-small",
                            variant="tonal",
                            color="grey-darken-1",
                            prepend_icon="mdi-delete-outline",
                            click="vtk_log_messages = []; $event.stopPropagation()",
                        )

                    # Expandable log zone — collapsed by default, title shows live counts
                    with vuetify3.VExpansionPanels(
                        v_model=("log_panel_open", []),
                        multiple=True,
                        elevation=0,
                    ):
                        with vuetify3.VExpansionPanel(
                            value="logs",
                            elevation=0,
                            bg_color="transparent",
                            rounded=False,
                        ):
                            with vuetify3.VExpansionPanelTitle(
                                style=(
                                    "font-family: monospace; font-size: 11px;"
                                    " min-height: 28px; padding: 2px 130px 2px 12px;"
                                    " background: rgba(18,18,18,0.97);"
                                ),
                            ):
                                # Error count in red, warning count in orange
                                html.Span(
                                    "{{ (vtk_log_messages||[]).filter(function(m){return m.level==='error'}).length }}",
                                    style="color: #ef5350; font-weight: bold;",
                                )
                                html.Span(" error(s)  —  ", style="color: #888;")
                                html.Span(
                                    "{{ (vtk_log_messages||[]).filter(function(m){return m.level==='warning'}).length }}",
                                    style="color: #ffb300; font-weight: bold;",
                                )
                                html.Span(" warning(s)", style="color: #888;")

                            with vuetify3.VExpansionPanelText(classes="pa-0"):
                                # Scroll container — ~8 visible lines, auto-scroll on new entries
                                with html.Div(
                                    id="vtk-log-container",
                                    style=(
                                        "height: 144px; overflow-y: auto;"
                                        " padding: 4px 10px;"
                                        " color: #e0e0e0; font-family: monospace; font-size: 12px;"
                                        " background: rgba(18,18,18,0.97);"
                                    ),
                                ):
                                    html.Div(
                                        "— no messages —",
                                        v_if="!vtk_log_messages || vtk_log_messages.length === 0",
                                        style="color:#555; font-style:italic; padding:2px 0;",
                                    )
                                    with html.Div(
                                        v_for="(msg, idx) in vtk_log_messages",
                                        key="idx",
                                        style=(
                                            "{ padding: '1px 0',"
                                            " whiteSpace: 'pre-wrap',"
                                            " wordBreak: 'break-all',"
                                            " color: msg.level === 'error' ? '#ef5350'"
                                            "      : msg.level === 'warning' ? '#ffb300'"
                                            "      : msg.level === 'debug'   ? '#757575'"
                                            "      : '#e0e0e0' }",
                                        ),
                                    ):
                                        html.Span("{{ msg.text }}")

        # Auto-scroll (trame_client.Script injects a real executable <script> in the document)
        trame_client.Script("""
(function () {
    function hideEl(el) {
        if (el && el.nodeType === 1) {
            var tag = el.tagName && el.tagName.toLowerCase();
            var cls = el.classList;
            if (tag === 'footer' || (cls && cls.contains('v-footer'))) {
                el.style.setProperty('display', 'none', 'important');
                el.style.setProperty('height', '0', 'important');
                el.style.setProperty('overflow', 'hidden', 'important');
            }
        }
    }

    function setupLogScroll() {
        var c = document.getElementById('vtk-log-container');
        if (!c) { setTimeout(setupLogScroll, 600); return; }
        new MutationObserver(function () {
            c.scrollTop = c.scrollHeight;
        }).observe(c, { childList: true, subtree: true });
    }

    function init() {
        // Hide any already-present footer elements
        document.querySelectorAll('footer, .v-footer').forEach(hideEl);

        // Watch the whole DOM for dynamically added footer elements
        new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (node) {
                    hideEl(node);
                    if (node.querySelectorAll) {
                        node.querySelectorAll('footer, .v-footer').forEach(hideEl);
                    }
                });
            });
        }).observe(document.documentElement, { childList: true, subtree: true });

        setupLogScroll();
        setupDrawerResize();
    }

    // ---- Drawer resize handle (pure JS — zero trame/server round-trips) ----
    function setupDrawerResize() {
        var handle = document.querySelector('.fespp-drawer-resize-handle');
        if (!handle) { setTimeout(setupDrawerResize, 300); return; }

        var dragging = false;

        handle.addEventListener('mousedown', function (e) {
            dragging = true;
            document.body.style.cursor = 'ew-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });

        document.addEventListener('mousemove', function (e) {
            if (!dragging) return;
            var drawer = document.querySelector('.v-navigation-drawer');
            if (drawer) {
                var w = Math.max(200, Math.min(900, e.clientX));
                drawer.style.setProperty('--v-navigation-drawer-width', w + 'px');
            }
        });

        document.addEventListener('mouseup', function () {
            if (!dragging) return;
            dragging = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
""")

        return layout