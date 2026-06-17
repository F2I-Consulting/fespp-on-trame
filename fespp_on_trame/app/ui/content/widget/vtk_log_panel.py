"""Collapsible panel at the bottom of the content area that surfaces
VTK / ParaView stderr messages captured by the engine's stderr tee.

Visible only when `state.vtk_log_messages` is non-empty. The Clear
button is rendered as an absolute child of the panel container so it
sits on top of the VExpansionPanelTitle without intercepting its
click — the `$event.stopPropagation()` in the click handler keeps the
title from collapsing when the user clicks Clear."""
from trame.widgets import html, vuetify3


class VtkLogPanel:
    """Bottom VTK log panel."""

    def render(self):
        with html.Div(
            v_show="vtk_log_messages && vtk_log_messages.length > 0",
            style=(
                "flex-shrink: 0; position: relative;"
                " background: rgba(18,18,18,0.97);"
                " border-top: 2px solid #444;"
            ),
        ):
            self._render_clear_button()
            self._render_expansion_panel()

    def _render_clear_button(self):
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

    def _render_expansion_panel(self):
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
                self._render_title()
                self._render_body()

    def _render_title(self):
        """Title shows error / warning counts. Numbers are computed
        client-side via filter() so we don't pay a round-trip for
        every new message."""
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

    def _render_body(self):
        """Scrollable list of messages. Auto-scrolls to bottom via
        shared/scripts.py (MutationObserver on #vtk-log-container)."""
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
