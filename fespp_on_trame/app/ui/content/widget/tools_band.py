"""Top tools band rendered above the multi-view.

Holds the **global** view-wide widgets only — per-view camera and
linking controls live on each panel directly (see
`PerViewCameraToolbar` + `ViewLinkMenu`).

Two slots, separated by a flexible spacer:
  - **Center**: optional global TimeControl. Writes TimeKeeper.Time so
    every view linked to the keeper follows. Only rendered when a
    TimeSeries property is in play (`ptc_show_vcr` is True).
  - **Right**: global settings cog (Z-scale, background, orientation
    — all applied globally). Per-view variants of these settings live
    in the per-panel ⚙ button."""
from trame.app import get_server
from trame.widgets import html, vuetify3

from .time_control import FesppTimeControl
from .realization_control import RealizationControl


server = get_server()
controller = server.controller


class ToolsBand:
    """Top tools band above the multi-view area."""

    def render(self):
        with html.Div(
            classes="d-flex align-center px-2 py-1",
            style=(
                "flex-shrink: 0; gap: 8px; min-height: 44px;"
                " border-bottom: 1px solid rgba(0,0,0,0.12);"
                " background: #f5f5f5;"
            ),
        ):
            # Left-of-center spacer (keeps the center group centered).
            html.Div(style="flex: 1;")
            self._render_global_time_control()
            self._render_realization_control()
            html.Div(style="flex: 1;")
            self._render_settings_cog()

    def _render_global_time_control(self):
        """Centered global TC. namespace="" keeps the legacy state
        names (time_index / time_value) that changeTimeLabel and
        TimeSeries still read. Outer v_if collapses the slot entirely
        when no TS is in play, so the surrounding spacers collapse
        the right group against the left edge with no leftover gap."""
        with html.Div(
            v_if=("ptc_show_vcr", False),
            classes="d-flex align-center",
            style="min-width: 380px; max-width: 720px; flex: 0 0 auto;",
        ):
            FesppTimeControl(
                scope="global",
                namespace="",
                time_expression="ui_time_label",
            )

    def _render_realization_control(self):
        """Scene-wide realization slider, shown only when at least one
        multi-realization property is loaded. Same justification as the
        global TC: realization swaps property values across every rep
        in the collector, so it doesn't belong in the per-rep attributes
        drawer."""
        with html.Div(
            v_if="realization_labels && realization_labels.length > 0",
            classes="d-flex align-center ml-2",
            style="flex: 0 0 auto;",
        ):
            RealizationControl().render()

    def _render_settings_cog(self):
        """Right-side cog opening the global settings modal.

        Right margin is reactive: when the top AppBar is hidden, the
        floating show-toolbar chevron sits at viewport `right: 8px`
        and would overlap this cog — shift the cog ~48px to the left
        in that case."""
        with vuetify3.VTooltip(location="bottom"):
            with vuetify3.Template(v_slot_activator="{ props }"):
                vuetify3.VBtn(
                    icon="mdi-cog",
                    v_bind="props",
                    variant="text",
                    color="blue",
                    size="small",
                    style=(
                        "`margin-right: ${toolbar_visible ? '0px' : '48px'};`",
                    ),
                    click=controller.global_settings_open,
                )
            html.Span("Global settings (Z scale, background, orientation)")
