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
        # Vertical split ratio between the Data Explorer card and the
        # Attributes card. Drag the handle between them to change it; the
        # two cards share `flex: ui_explorer_flex` / `2 - ui_explorer_flex`
        # so the sum stays constant (default 1.0 = 50/50).
        state.setdefault("ui_explorer_flex", 1.0)

    def render(self):
        UploadOverlay().render()
        self._render_resize_handle()
        with vuetify3.VContainer(
            fluid=True,
            classes="pa-0",
            id="fespp-drawer-cards",
            style="display: flex; flex-direction: column; height: 100%;",
        ):
            self._render_data_explorer_card()
            self._render_card_resize_handle()
            self._render_attributes_card()

    def _render_card_resize_handle(self):
        """Draggable horizontal splitter between the Data Explorer and
        Attributes cards — drag up/down to change their relative height.
        Pure-JS drag (shared/scripts.py setupCardResize) writes the new
        ratio to `ui_explorer_flex`; no per-step server round-trip."""
        vuetify3.VSheet(
            classes="fespp-card-resize-handle flex-grow-0 flex-shrink-0",
            style=(
                "flex-basis: 7px; cursor: ns-resize; z-index: 5;"
                " background-color: rgba(0,0,0,0.06);"
                " border-top: 1px solid rgba(0,0,0,0.12);"
                " border-bottom: 1px solid rgba(0,0,0,0.12);"
                " pointer-events: auto;"
            ),
        )

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
            # Height driven by the drag handle (see _render_card_resize_handle):
            # `flex` grows/shrinks against the Attributes card's `2 - ratio`.
            style=("{ flex: ui_explorer_flex + ' 1 0', minHeight: '0', overflow: 'hidden' }",),
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
    # Attributes card — slice / clip / threshold / IJK slicers /
    # representation / solid color, scoped to `drawer_target_view_id`.
    #
    # Statistics live in their own dockview tab (the singleton
    # `kind="stats"` panel created by `multi_view._add_stats_panel`,
    # opened on the first chart-icon click in the tree), not here —
    # the drawer focuses purely on per-view edit operations.

    def _render_attributes_card(self):
        with vuetify3.VCard(
            classes="d-flex flex-column",
            elevation=0,
            flat=True,
            tile=True,
            # Complementary flex to the Data Explorer card so the two always
            # fill the column (sum of the flex grow factors stays 2).
            style=("{ flex: (2 - ui_explorer_flex) + ' 1 0', minHeight: '0', overflow: 'hidden' }",),
        ):
            with vuetify3.VToolbar(
                density="compact",
                classes="bg-blue-grey-darken-2 flex-grow-0 flex-shrink-0",
                color="white",
            ):
                vuetify3.VIcon(
                    "mdi-information",
                    classes="mr-3",
                    color="white",
                )
                vuetify3.VToolbarTitle(
                    "Attributes",
                    classes="text-subtitle-1 font-weight-medium",
                )

            with vuetify3.VCardText(
                classes="pa-2",
                style="flex: 1 1 0; min-height: 0; overflow-y: auto;",
            ):
                # Target view picker — sits at the top of the card
                # body so it has full drawer width to render its
                # label / VSelect cleanly.
                self._render_target_view_strip()
                # Reservoir attributes — slicers + representation +
                # solid color. v_if check: any active node.
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

                # Surface attributes — no IJK slicer.
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
                            SlicersPanel(with_ijk=False).render()
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
                            SlicersPanel(with_ijk=False).render()
                            RepresentationTypePanel()
                            SolidColorPanel()

    # ------------------------------------------------------------------
    # Target view strip (top of Attributes tab body)
    #
    # Drives `state.drawer_target_view_id` — the render panel the edit
    # panels (slice / clip / threshold / IJK slicers) operate on. Two
    # modes:
    #
    #   - **Follow active** (default, `drawer_target_view_pinned=False`)
    #     → the target id auto-syncs to `fespp_active_panel_id` on every
    #     panel-activated event. The strip shows a passive label with
    #     the active view's title.
    #
    #   - **Pinned** (`drawer_target_view_pinned=True`) → the target id
    #     stays put across active-panel switches; the strip shows a
    #     `VSelect` for picking another view. Useful for editing a
    #     view's filters without losing focus on the currently-active
    #     one.
    #
    # Lives at the TOP of the Attributes tab body (not in the card
    # toolbar) so the picker has the full drawer width to render and
    # narrow drawers don't squash it against the tabs.
    #
    # The pin toggle is hidden until there are 2+ render panels — with
    # a single view the picker has nothing to choose.

    def _render_target_view_strip(self):
        with html.Div(
            classes="d-flex align-center mb-2 pa-2",
            style=(
                "background: rgba(0,0,0,0.04);"
                " border-radius: 4px; gap: 8px;"
            ),
        ):
            html.Span(
                "Target view:",
                classes="text-caption font-weight-medium text-medium-emphasis",
                style="white-space: nowrap;",
            )
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        v_bind="props",
                        icon=(
                            "drawer_target_view_pinned"
                            " ? 'mdi-pin' : 'mdi-pin-off-outline'",
                        ),
                        variant="text",
                        density="compact",
                        size="small",
                        color=(
                            "drawer_target_view_pinned"
                            " ? 'primary' : 'grey'",
                        ),
                        v_show="(fespp_render_panels || []).length > 1",
                        click=(
                            "drawer_target_view_pinned = !drawer_target_view_pinned"
                        ),
                    )
                html.Span(
                    "{{ drawer_target_view_pinned"
                    " ? 'Unpin (follow active view)'"
                    " : 'Pin to a specific view' }}",
                )
            # Follow mode → passive label showing the active view's
            # title. Empty when no view is active yet — keeps the
            # strip silent during the boot window before the first
            # split.
            html.Span(
                "{{ ((fespp_render_panels || []).find("
                "p => p.id === fespp_active_panel_id) || {}).title"
                " || '—' }}",
                v_if="!drawer_target_view_pinned",
                classes="text-body-2 font-weight-medium",
                style="white-space: nowrap;",
            )
            # Pinned mode → dropdown of all render panels. Takes the
            # remaining flex space so it grows with the drawer.
            vuetify3.VSelect(
                v_if="drawer_target_view_pinned",
                v_model=("drawer_target_view_id", ""),
                items=("fespp_render_panels", []),
                item_title="title",
                item_value="id",
                density="compact",
                hide_details=True,
                variant="outlined",
                style="flex: 1 1 auto; min-width: 100px;",
            )
