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

from fespp_on_trame.app.ui.toolbar import Toolbar
from fespp_on_trame.app.ui.helpers import create_card
from fespp_on_trame.app.ui.import_dialog import ImportDialog
from fespp_on_trame.app.ui.tree_views import TreeViews


server = get_server()
state = server.state
controller = server.controller

state.dialog_visible = False
state.execute_action = False
state.ui_time_label = ""
# Drawer width is set once; live resize is handled via the JS hook
# below (no Trame round-trip per drag step).
state.drawer_width = 500

state.init_height_dataexplorer = "50vh"
state.init_height_attribute = "600px"


def ui(server: Server, **kwargs) -> None:
    """Build the main UI layout (toolbar, drawer, tabs, render area)."""
    localFileManager = LocalFileManager(PUBLIC_PATH)
    localFileManager.url("logo", "logo.png")

    with SinglePageWithDrawerLayout(
        server,
        width=("drawer_width", 500),
    ) as layout:

        layout.title.set_text(TRAME_APP_TITLE)

        # CSS fix for ptc components — trame_client.Style injects a
        # real <style> in the document head (unlike html.Style).
        trame_client.Style(".te-align-center .v-row { align-items: center; }")

        # Hide the default trame footer ("Powered by trame", "?",
        # copyright). The --v-layout-bottom reset prevents Vuetify
        # from reserving space for the hidden footer.
        trame_client.Style(
            "footer, .v-footer {"
            "  display: none !important;"
            "  height: 0 !important;"
            "  min-height: 0 !important;"
            "  overflow: hidden !important;"
            "}"
            ".v-layout { --v-layout-bottom: 0 !important; }"
        )

        with layout.icon:
            vuetify3.VImg(src=localFileManager["logo"], height="35", width="35")

        import_dialog = ImportDialog(state, controller)

        # Initialize tree views (registers opened-nodes handler and initializes state)
        # Pass the engine's Tree instance so the dependency-expansion
        # handler can walk the assembly (groupings → descendants,
        # Channel/Marker → Trajectory).
        tv = TreeViews(controller, state, fespp_engine._tree)

        with layout.toolbar:
            toolbar = Toolbar(localFileManager, import_dialog)
            toolbar.render()

        with layout.drawer as drawer:
            # Upload progress overlay — covers the full drawer while
            # uploading.
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

            # Resize handle on the right edge of the drawer.
            with vuetify3.VSheet(
                classes="position-absolute h-100 fespp-drawer-resize-handle",
                style="right: -4px; cursor: ew-resize; z-index: 1000; width: 8px; background-color: transparent;",
            ):
                vuetify3.VDivider(vertical=True, classes="h-100")

            with vuetify3.VContainer(fluid=True, classes="pa-0"):

                with vuetify3.VTabs(v_model=("tab", None),
                            classes="bg-grey-lighten-4",
                            color="blue",
                            density="comfortable",
                            grow=True,
                            selected_class="font-weight-bold text-blue"):
                    vuetify3.VTab("Reservoir ({{ ui_subtree_reservoir ? ui_subtree_reservoir.length : 0 }})", value="reservoir")
                    vuetify3.VTab("Surface ({{ ui_subtree_surface ? ui_subtree_surface.length : 0 }})", value="surface")
                    vuetify3.VTab("Well ({{ ui_subtree_well ? ui_subtree_well.length : 0 }})", value="well")

                # All three tabs are mounted at once and their visibility
                # is toggled via v_show — this preserves expansion /
                # active state when the user switches tabs.
                with html.Div(classes="pa-4"):

                    with html.Div(v_show="tab === 'reservoir'"):
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer",
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.reservoir_tree()
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute",
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                with html.Div(v_if="ui_active_node_reservoir && ui_active_node_reservoir.length > 0"):
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        panel_slicers.SlicerControls()
                                        RepresentationTypePanel()
                                        SolidColorPanel()

                    with html.Div(v_show="tab === 'surface'"):
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.surface_tree()
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                # Show the panel only when the active
                                # node is also currently checked.
                                with html.Div(v_if="ui_active_node_surface.length > 0 && ui_select_node_surface.includes(ui_active_node_surface[0])"):
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        RepresentationTypePanel()
                                        SolidColorPanel()

                    with html.Div(v_show="tab === 'well'"):
                        with create_card(
                            "Data Explorer",
                            "mdi-file-tree",
                            "init_height_dataexplorer"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                tv.well_tree()
                        with create_card(
                            "Attributes",
                            "mdi-information",
                            "init_height_attribute"
                        ):
                            with vuetify3.VSheet(classes="pa-2"):
                                with html.Div(v_if="ui_active_node_well.length > 0 && ui_select_node_well.includes(ui_active_node_well[0])"):
                                    with vuetify3.VExpansionPanels(style="display: initial;", classes="mb-2"):
                                        RepresentationTypePanel()
                                        SolidColorPanel()

                with create_card(
                    "General Display Settings",
                    "mdi-cogs",
                    "init_height_attribute"
                ):
                    with vuetify3.VExpansionPanels(classes="mt-0", elevation=10,):
                        with vuetify3.VExpansionPanel(
                            title="Display Options",
                            value="display_options",
                            elevation=0,
                            classes="border-b"
                        ) as expansion_panel:
                            with vuetify3.VExpansionPanelText(classes="pa-2"):

                                # Z-scale stays global on purpose:
                                # vertical exaggeration only makes
                                # sense across the whole scene.
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

                                # Manual mode lets the user check several
                                # nodes across tabs without paying the
                                # load cost on every click; the toolbar
                                # Load button pushes them all at once.
                                # Visibility on/off is independent —
                                # driven by the eye icons in the trees.
                                html.Div("Load Mode", classes="text-caption text-uppercase font-weight-bold mb-2")
                                with vuetify3.VBtnToggle(
                                    v_model=("load_mode", "auto"),
                                    mandatory=True,
                                    density="comfortable",
                                    color="blue",
                                    divided=True,
                                    classes="mb-3 w-100",
                                ):
                                    vuetify3.VBtn("Auto", value="auto", size="small")
                                    vuetify3.VBtn("Manual", value="manual", size="small")

                                vuetify3.VDivider(classes="my-3")

                                # Switching the mode rebuilds the C++
                                # assembly and resets every selection
                                # / visibility / coloring state — see
                                # the snackbar at the bottom of the
                                # layout.
                                html.Div("Tree Hierarchy", classes="text-caption text-uppercase font-weight-bold mb-2")
                                with vuetify3.VBtnToggle(
                                    v_model=("tree_hierarchy_mode", "flat"),
                                    mandatory=True,
                                    density="comfortable",
                                    color="blue",
                                    divided=True,
                                    classes="mb-3 w-100",
                                ):
                                    vuetify3.VBtn("Flat", value="flat", size="small")
                                    vuetify3.VBtn("By Interp.", value="by_interpretation", size="small")
                                    vuetify3.VBtn("By Feat.+Interp.", value="by_feature_and_interpretation", size="small")

                                with html.Div(classes="d-flex align-start mb-3"):
                                    vuetify3.VIcon(
                                        "mdi-alert-circle-outline",
                                        size="x-small",
                                        color="orange-darken-2",
                                        classes="mr-1 mt-1",
                                    )
                                    html.Span(
                                        "Switching mode clears all current selections and"
                                        " visibility/coloring state — you'll need to re-pick"
                                        " what you want under the new layout.",
                                        classes="text-caption text-medium-emphasis",
                                        style="line-height: 1.2;",
                                    )

                                vuetify3.VDivider(classes="my-3")

                                with html.Div(classes="d-flex align-center pt-2"):
                                    html.Span(
                                        "Background Color:",
                                        classes="text-caption font-weight-medium mr-3"
                                    )
                                    ptc.PalettePicker(
                                        color="blue",
                                        base_color="blue",
                                        item_color="blue",
                                        flat=True,
                                    )

        with layout.content:
            vuetify3.VOverlay(
                v_if=("trame__busy",),
                v_model=("trame__busy",),
                persistent=True,
                scrim="rgba(0, 0, 0, 0.7)",
                class_="d-flex align-center justify-center",
            )

            # Flex column: the 3D view grows; the log panel stays at
            # the bottom without overlapping.
            with html.Div(style="display: flex; flex-direction: column; height: 100%; width: 100%;"):

                with html.Div(style="flex: 1; position: relative; overflow: hidden; min-height: 0;"):
                    view = paraview.VtkRemoteView(
                        pvsimple.GetActiveViewOrCreate("RenderView") if pvsimple else None,
                        interactive_ratio=0.5,
                        interactive_quality=60,
                        namespace="time_view",
                        style="width: 100%; height: 100%;",
                    )

                    ptc.ResetCameraButtons(
                        classes="position-absolute top-0 left-0 ma-2",
                        variant="text",
                        color="blue",
                        direction="vertical",
                    )

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

                    server.controller.view_replace = view.replace_view
                    server.controller.view_update = view.update
                    server.controller.view_reset_camera = view.reset_camera
                    server.controller.on_server_ready.add(server.controller.view_update)

                # VTK log panel — visible only when messages exist.
                with html.Div(
                    v_show="vtk_log_messages && vtk_log_messages.length > 0",
                    style=(
                        "flex-shrink: 0; position: relative;"
                        " background: rgba(18,18,18,0.97);"
                        " border-top: 2px solid #444;"
                    ),
                ):
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

        # Hide-footer + log auto-scroll + drawer resize handle. All
        # pure-JS to avoid trame/server round-trips per drag step.
        # trame_client.Script injects a real executable <script>
        # element (unlike html.Script).
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

        # Shown after a tree-hierarchy mode change wipes a non-empty
        # selection — extra confirmation that the user's previous
        # picks have been discarded.
        with vuetify3.VSnackbar(
            v_model=("tree_hierarchy_snackbar_visible", False),
            timeout=4500,
            color="orange-darken-2",
            location="bottom",
        ):
            with html.Div(classes="d-flex align-center"):
                vuetify3.VIcon(
                    "mdi-alert-circle-outline",
                    size="small",
                    classes="mr-2",
                )
                html.Span(
                    "Tree hierarchy changed — your previous selection has"
                    " been cleared. Re-pick what you want to load under the"
                    " new layout."
                )

        return layout