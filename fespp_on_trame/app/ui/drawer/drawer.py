"""Left-side drawer builder.

Lays out two stacked cards taking equal vertical halves:

  - **Data Explorer** — card whose toolbar hosts the three Reservoir
    / Surface / Well tabs on the left, then the contextual Load
    button (manual mode only), the drawer widen-toggle, and the
    Display Options cog on the right. Body renders the matching
    tree for the active tab.

  - **Attributes** — card whose body shows the per-tab attribute
    panels (slicers / representation / solid color) for the active
    node. Title is a simple "Attributes" label.

All three tree tabs / attribute blocks are mounted simultaneously
and toggled via `v_show` so per-tab UI state (expansion, selection,
scroll position) survives a tab switch.

Public API: `Drawer(tv).render()` — call inside a `with layout.drawer:`
context."""
from trame.app import get_server
from trame.widgets import html, vuetify3

from fespp_on_trame.app.ui.drawer.panel.solid_color_panel import SolidColorPanel
from fespp_on_trame.app.ui.drawer.panel.representation_type_panel import RepresentationTypePanel
from fespp_on_trame.app.ui.drawer.panel.slicers_panel import SlicersPanel
from fespp_on_trame.app.ui.drawer.panel.threshold_panel import ThresholdPanel
from fespp_on_trame.app.ui.drawer.widget.upload_overlay import UploadOverlay


server = get_server()
state = server.state
controller = server.controller


class Drawer:
    """Renders the full drawer body: upload overlay, resize handle,
    Data Explorer card (with tabbed trees), and Attributes card.

    `tv` is a TreeViews instance — Drawer doesn't own it because it's
    also referenced by the engine for assembly walking."""

    def __init__(self, tv):
        self._tv = tv
        # Default tab so v_show matches on first paint — otherwise the
        # Data Explorer body is empty until the user clicks a tab.
        state.setdefault("tab", "reservoir")

    def render(self):
        UploadOverlay().render()
        self._render_resize_handle()
        with vuetify3.VContainer(
            fluid=True,
            classes="pa-0",
            style="display: flex; flex-direction: column; height: 100%;",
        ):
            self._render_data_explorer_card()
            self._render_attributes_card()

    def _render_resize_handle(self):
        """Thin draggable handle on the right edge of the drawer.
        Drag logic lives in shared/scripts.py (pure JS, no trame
        round-trips per step). 16px wide with an -8px right offset
        gives 8px of grab area on each side of the drawer's right
        edge — wider than a one-pixel border so the user doesn't
        have to be pixel-precise. z-index 2000 keeps it above the
        cards inside the drawer; `pointer-events: auto` is explicit
        so a transparent VSheet still receives mousedown."""
        with vuetify3.VSheet(
            classes="position-absolute h-100 fespp-drawer-resize-handle",
            style=(
                "right: -8px; cursor: ew-resize; z-index: 2000;"
                " width: 16px; background-color: transparent;"
                " pointer-events: auto;"
            ),
        ):
            vuetify3.VDivider(vertical=True, classes="h-100")

    # ------------------------------------------------------------------
    # Data Explorer card

    def _render_data_explorer_card(self):
        with vuetify3.VCard(
            classes="d-flex flex-column",
            elevation=0,
            flat=True,
            tile=True,
            style=(
                "flex: 1; min-height: 0; overflow: hidden;"
                " border-bottom: 1px solid rgba(0,0,0,0.12);"
            ),
        ):
            self._render_data_explorer_title()
            self._render_data_explorer_tabs()
            self._render_data_explorer_body()

    def _render_data_explorer_title(self):
        """Title bar: 'Data Explorer' label on the left, contextual
        Load button + Display Options cog on the right. Drawer
        width is resized via the right-edge drag handle (no extra
        button needed)."""
        with vuetify3.VToolbar(
            density="compact",
            # flex-shrink-0 alongside flex-grow-0 — without it, a long
            # tree below makes flex squeeze the title (default
            # flex-shrink: 1) and push the tabs / title off-screen.
            classes="bg-blue-grey-darken-2 flex-grow-0 flex-shrink-0",
            color="white",
        ):
            vuetify3.VIcon("mdi-file-tree", classes="mr-3", color="white")
            vuetify3.VToolbarTitle(
                "Data Explorer",
                classes="text-subtitle-1 font-weight-medium",
            )

            vuetify3.VSpacer()

            # Load button (manual mode only) — pushes the aggregated
            # checkbox selection to the pipeline in one go.
            vuetify3.VBtn(
                "Load",
                v_if="load_mode === 'manual'",
                variant="flat",
                color="green",
                prepend_icon="mdi-reload",
                density="comfortable",
                size="small",
                click=(controller.apply_pending_selection,),
                classes="mr-2",
            )

            # Display options cog (opens DisplayOptionsDialog with
            # Load Mode + Tree Hierarchy toggles).
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-cog",
                        v_bind="props",
                        variant="text",
                        size="small",
                        color="white",
                        click=controller.drawer_options_open,
                    )
                html.Span("Display options (Load mode, Tree hierarchy)")

    def _render_data_explorer_tabs(self):
        """Tabs row sitting just below the Data Explorer title bar.
        Light grey bg sets it apart from the dark title and from the
        tree body below."""
        with vuetify3.VTabs(
            v_model=("tab", "reservoir"),
            # See _render_data_explorer_title — flex-shrink-0 protects
            # the tabs from being squeezed by a tall tree below.
            classes="bg-grey-lighten-4 flex-grow-0 flex-shrink-0",
            color="blue",
            density="comfortable",
            grow=True,
            selected_class="font-weight-bold text-blue",
        ):
            vuetify3.VTab(
                "Reservoir ({{ ui_subtree_reservoir ? ui_subtree_reservoir.length : 0 }})",
                value="reservoir",
            )
            vuetify3.VTab(
                "Surface ({{ ui_subtree_surface ? ui_subtree_surface.length : 0 }})",
                value="surface",
            )
            vuetify3.VTab(
                "Well ({{ ui_subtree_well ? ui_subtree_well.length : 0 }})",
                value="well",
            )

    def _render_data_explorer_body(self):
        """Three tree subtrees, only the matching one visible at any
        moment (via v_show, which keeps each tree's state — expansion,
        selection — across tab switches).

        `min-height: 0` is mandatory: a flex item's default min-height
        is `auto`, which keeps the item at least as tall as its
        content (so the tree would push the title + tabs off-screen
        instead of scrolling inside the card)."""
        with vuetify3.VCardText(
            classes="pa-2",
            style="flex: 1 1 0; min-height: 0; overflow-y: auto;",
        ):
            with html.Div(v_show="tab === 'reservoir'"):
                self._tv.reservoir_tree()
            with html.Div(v_show="tab === 'surface'"):
                self._tv.surface_tree()
            with html.Div(v_show="tab === 'well'"):
                self._tv.well_tree()

    # ------------------------------------------------------------------
    # Attributes card

    def _render_attributes_card(self):
        with vuetify3.VCard(
            classes="d-flex flex-column",
            elevation=0,
            flat=True,
            tile=True,
            style="flex: 1; min-height: 0; overflow: hidden;",
        ):
            with vuetify3.VToolbar(
                density="compact",
                classes="bg-blue-grey-darken-2 flex-grow-0 flex-shrink-0",
                color="white",
            ):
                vuetify3.VIcon("mdi-information", classes="mr-3", color="white")
                vuetify3.VToolbarTitle(
                    "Attributes",
                    classes="text-subtitle-1 font-weight-medium",
                )

            with vuetify3.VCardText(
                classes="pa-2",
                style="flex: 1 1 0; min-height: 0; overflow-y: auto;",
            ):
                # Reservoir attributes — slicers + representation +
                # solid color. v_if check: any active node (the
                # legacy reservoir behaviour, simpler than the other
                # two tabs).
                with html.Div(v_show="tab === 'reservoir'"):
                    with html.Div(
                        v_if="ui_active_node_reservoir && ui_active_node_reservoir.length > 0"
                    ):
                        with vuetify3.VExpansionPanels(
                            style="display: initial;",
                            classes="mb-2",
                        ):
                            SlicersPanel(with_ijk=True).render()
                            ThresholdPanel().render()
                            RepresentationTypePanel()
                            SolidColorPanel()

                # Surface attributes — no IJK slicer. Active node must
                # also be in the current selection (a node can be
                # active without being checked, e.g. after a tab
                # switch).
                with html.Div(v_show="tab === 'surface'"):
                    with html.Div(
                        v_if=(
                            "ui_active_node_surface.length > 0 &&"
                            " ui_select_node_surface.includes(ui_active_node_surface[0])"
                        )
                    ):
                        with vuetify3.VExpansionPanels(
                            style="display: initial;",
                            classes="mb-2",
                        ):
                            # SLICE/CLIP UI HIDDEN — SlicersPanel with
                            # `with_ijk=False` would render an empty body
                            # once Slice and Clip tabs are commented out.
                            # SlicersPanel(with_ijk=False).render()
                            RepresentationTypePanel()
                            SolidColorPanel()

                # Well attributes — same pattern as surface.
                with html.Div(v_show="tab === 'well'"):
                    with html.Div(
                        v_if=(
                            "ui_active_node_well.length > 0 &&"
                            " ui_select_node_well.includes(ui_active_node_well[0])"
                        )
                    ):
                        with vuetify3.VExpansionPanels(
                            style="display: initial;",
                            classes="mb-2",
                        ):
                            # SLICE/CLIP UI HIDDEN — see surface tab note.
                            # SlicersPanel(with_ijk=False).render()
                            RepresentationTypePanel()
                            SolidColorPanel()
