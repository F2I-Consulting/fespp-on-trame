"""Distribution panel — Plotly histogram rendered inside one floating
dockview overlay instance, plus a per-panel options toolbar.

Multi-instance: every per-row Hist click (and every Compare-histograms
click) spawns a NEW Distribution panel via `multi_view.add_view(kind=
"distribution")`. Each instance owns its own state-var bindings
(figure payload, mode toggle, bin slider, normalisation, etc.) — all
suffixed with `<panel_id>` so two panels never clobber each other.

Toolbar controls (top of the panel, above the Plotly figure):
  - mode toggle (bars / line / curve)
  - bin slider 5 → 500
  - log Y switch
  - mean / median / quartiles overlay switch
  - cumulative switch
  - normalisation toggle (count / density / probability)
  - NaN / total / kept badge
  - CSV export button

When any toolbar control mutates its scoped state var, a
`@state.change` watcher (registered at panel creation time in
`multi_view._add_distribution_panel`) re-runs the compute with the
fresh options and pushes a new figure through the panel's update
controller method.

The Plotly widget must be wrapped in VContainer / VRow / VCol — a raw
html.Div with flex + min-height collapses Plotly to 0×0 in a dockview
floating shell whose layout settles asynchronously.
"""
from trame.app import get_server
from trame.widgets import html, plotly, vuetify3


class DistributionPanel:
    """Renders one Plotly Figure tied to a specific dockview panel id,
    plus a per-panel options toolbar.

    `_add_distribution_panel` passes the panel id in so every state
    binding and the captured `.update` method are scoped per-instance;
    without that scoping all Distribution panels would clobber the same
    vars and only the last-updated one would render.
    """

    def __init__(self, panel_id: str):
        self._panel_id = panel_id

    # --- state var names ----------------------------------------------------

    @property
    def state_var(self) -> str:
        """Name of the trame state key that holds this panel's
        `{"data": [...], "layout": {...}}` figure payload."""
        return f"ui_distribution_figure_{self._panel_id}"

    @property
    def ctrl_method(self) -> str:
        """Name of the controller method that triggers `Plotly.react`
        for this panel's figure. Set on the trame controller during
        render so any server-side code can do
        `getattr(controller, panel.ctrl_method)(go.Figure(...))`."""
        return f"update_distribution_figure_{self._panel_id}"

    @property
    def mode_var(self) -> str:
        return f"ui_distribution_mode_{self._panel_id}"

    @property
    def nbins_var(self) -> str:
        return f"ui_distribution_nbins_{self._panel_id}"

    @property
    def log_y_var(self) -> str:
        return f"ui_distribution_log_y_{self._panel_id}"

    @property
    def show_stats_var(self) -> str:
        return f"ui_distribution_show_stats_{self._panel_id}"

    @property
    def cumulative_var(self) -> str:
        return f"ui_distribution_cumulative_{self._panel_id}"

    @property
    def norm_var(self) -> str:
        return f"ui_distribution_norm_{self._panel_id}"

    @property
    def meta_var(self) -> str:
        """`{kept, total, nan}` payload feeding the NaN badge."""
        return f"ui_distribution_meta_{self._panel_id}"

    @property
    def csv_var(self) -> str:
        """Base64-encoded data URL the export button binds to via
        `<a :href=csv_var download="distribution.csv">`."""
        return f"ui_distribution_csv_{self._panel_id}"

    @property
    def is_compare_var(self) -> str:
        """Compare panels hide controls that don't apply (stats
        overlay, individual bin slider semantics differ slightly).
        Boolean state var set by the spawner at panel creation."""
        return f"ui_distribution_is_compare_{self._panel_id}"

    # --- render -------------------------------------------------------------

    def render(self):
        server = get_server()
        with vuetify3.VContainer(
            fluid=True,
            classes="pa-0 ma-0 d-flex flex-column",
            style="height: 100%; width: 100%;",
        ):
            self._render_toolbar()
            with vuetify3.VRow(
                no_gutters=True,
                classes="ma-0",
                style="flex: 1 1 auto; min-height: 0;",
            ):
                with vuetify3.VCol(classes="pa-0", style="min-height: 0;"):
                    widget = plotly.Figure(
                        state_variable_name=self.state_var,
                        display_mode_bar=True,
                        display_logo=False,
                        responsive=True,
                        style="height: 100%; width: 100%;",
                    )
                    setattr(server.controller, self.ctrl_method, widget.update)

    def _render_toolbar(self):
        """One-row toolbar above the figure. Kept compact so it eats
        as little vertical space as possible (40px tall). Controls
        flow left-to-right grouped by category:

        [ mode toggle | bins slider | log Y | stats | cumulative | norm | badge | export ]
        """
        with vuetify3.VToolbar(
            density="compact",
            flat=True,
            classes="pa-1",
            style="flex: 0 0 auto; min-height: 40px;",
        ):
            # --- shape: bars / line / curve ---
            with vuetify3.VBtnToggle(
                v_model=(self.mode_var, "bars"),
                mandatory=True,
                density="compact",
                divided=True,
                variant="outlined",
                classes="mr-2",
            ):
                vuetify3.VBtn(
                    value="bars", icon="mdi-chart-bar",
                    size="small", title="Bars",
                )
                vuetify3.VBtn(
                    value="line", icon="mdi-chart-line-variant",
                    size="small", title="Line (step)",
                )
                vuetify3.VBtn(
                    value="curve", icon="mdi-chart-bell-curve-cumulative",
                    size="small", title="Smoothed curve",
                )
            # --- bins slider ---
            with html.Div(
                classes="d-flex align-center mr-3",
                style="min-width: 180px;",
            ):
                vuetify3.VIcon(
                    "mdi-format-line-spacing",
                    size="small", classes="mr-1",
                    title="Bins",
                )
                vuetify3.VSlider(
                    v_model=(self.nbins_var, 50),
                    min=5, max=500, step=1,
                    thumb_label=True,
                    hide_details=True,
                    density="compact",
                    style="flex: 1; min-width: 100px;",
                )
            vuetify3.VDivider(vertical=True, classes="mx-1")
            # --- log Y ---
            vuetify3.VSwitch(
                v_model=(self.log_y_var, False),
                label="log Y",
                density="compact",
                hide_details=True,
                color="primary",
                classes="mr-3",
                title="Log-scale Y axis",
            )
            # --- stats overlay (mean / median / quartiles vertical lines) ---
            vuetify3.VSwitch(
                v_model=(self.show_stats_var, False),
                label="stats",
                density="compact",
                hide_details=True,
                color="primary",
                classes="mr-3",
                v_if=f"!{self.is_compare_var}",
                title="Overlay mean / median / quartiles",
            )
            # --- cumulative ---
            vuetify3.VSwitch(
                v_model=(self.cumulative_var, False),
                label="cumul",
                density="compact",
                hide_details=True,
                color="primary",
                classes="mr-3",
                title="Cumulative distribution",
            )
            # --- normalisation ---
            with vuetify3.VBtnToggle(
                v_model=(self.norm_var, "count"),
                mandatory=True,
                density="compact",
                divided=True,
                variant="outlined",
                classes="mr-2",
            ):
                vuetify3.VBtn(
                    "n", value="count", size="small",
                    title="Raw counts",
                )
                vuetify3.VBtn(
                    "dens", value="density", size="small",
                    title="Density (integral = 1)",
                )
                vuetify3.VBtn(
                    "p", value="probability", size="small",
                    title="Probability (sum = 1)",
                )
            vuetify3.VSpacer()
            # --- NaN / kept badge ---
            # Single VChip whose text is computed Vue-side. Title
            # carries the same info as a tooltip; amber when NaN > 0,
            # grey when the dropped count is 0.
            m = self.meta_var
            text_expr = (
                f"(({m} && {m}.kept) || 0) + ' / ' + (({m} && {m}.total) || 0)"
                f" + (({m} && {m}.nan > 0) ? '  (' + {m}.nan + ' NaN)' : '')"
            )
            vuetify3.VChip(
                "{{ "
                + text_expr
                + " }}",
                v_if=f"{m} && {m}.total",
                size="small",
                color=(f"{m}.nan > 0 ? 'amber-darken-2' : 'grey'",),
                variant="tonal",
                classes="mr-2",
                title="Cells kept / total (NaN dropped)",
            )
            # --- export CSV ---
            # VBtn renders as <a> when `href` is set, so download +
            # the data URL kept in `ui_distribution_csv_<panel_id>`
            # together produce a native browser save dialog with no
            # server round-trip on click. The expression form of
            # `disabled` greys the button out while the CSV var is
            # empty (between panel spawn and first compute push).
            vuetify3.VBtn(
                icon="mdi-download",
                size="small",
                variant="text",
                href=(self.csv_var,),
                download="distribution.csv",
                # target=_blank so the data: URL can never navigate (and
                # drop the websocket) the main SPA window — the download
                # attribute still saves the file.
                target="_blank",
                disabled=(f"!{self.csv_var}",),
                title="Download bins as CSV",
            )
