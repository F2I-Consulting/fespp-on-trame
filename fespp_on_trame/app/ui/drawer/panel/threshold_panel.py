"""Threshold chain panel — per-rep value-based filter.

A threshold filters cells by a property value range. Unlike Slice /
Clip (geometric cuts) and IJK slicer (axis-aligned crop), threshold
is a *value-based* filter — it lives in its own panel because:
  - per-rep (each rep keeps its own chain, even across reps sharing
    the same property name)
  - non-geometric (no plane / no widget — just sliders + add/delete)
  - reservoir-scoped (IjkGrid + UnstructuredGrid only)

Driven by `state.ui_threshold_chain` (per-rep snapshot pushed by the
engine on activation) and `state.ui_threshold_pending_action` (sentinel
the engine consumes + resets to flow add/delete/set_range/set_visible
events through a single state var)."""
from trame.widgets import html, vuetify3


# Show the threshold panel only for rep types that actually support it.
THRESHOLD_PANEL_VISIBLE = (
    "ui_active_node_reservoir_type_rep === 'IjkGrid'"
    " || ui_active_node_reservoir_type_rep === 'UnstructuredGrid'"
)


class ThresholdPanel:
    """Standalone VExpansionPanel hosting the threshold chain editor."""

    def render(self):
        with vuetify3.VExpansionPanel(v_if=THRESHOLD_PANEL_VISIBLE):
            with vuetify3.VExpansionPanelTitle(classes="pa-2"):
                html.Span(
                    "Thresholds",
                    classes="text-body-2 font-weight-medium",
                )
                vuetify3.VSpacer()
                # Count chip — quick at-a-glance of how many filters
                # are active on this rep.
                vuetify3.VChip(
                    "{{ ui_threshold_chain.length }} active",
                    v_if="ui_threshold_chain && ui_threshold_chain.length > 0",
                    size="x-small",
                    variant="tonal",
                    color="green",
                    classes="mr-2",
                )
            with vuetify3.VExpansionPanelText(classes="pa-2"):
                self._render_body()

    def _render_body(self):
        # Header + root-add button.
        with html.Div(
            style="display: flex; align-items: center; gap: 4px; margin-bottom: 4px;",
        ):
            html.Div(
                "Chain",
                classes="text-caption font-weight-bold",
                style="font-size: 0.75rem;",
            )
            with vuetify3.VTooltip(location="bottom"):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        icon="mdi-set-all",
                        v_bind="props",
                        disabled=("!active_color_array_name",),
                        click=(
                            "ui_threshold_pending_action = "
                            "{ action: 'add', parent: null }"
                        ),
                        variant="text", density="compact", size="small",
                        color="primary",
                        style="margin: 0; padding: 0; min-width: 36px; width: 36px; height: 36px;",
                    )
                html.Span(
                    "Add union — show cells matching this range OR any existing root range"
                )
            html.Span(
                "(activate a property first)",
                v_if="!active_color_array_name && (!ui_threshold_chain || ui_threshold_chain.length === 0)",
                classes="text-caption text-medium-emphasis ml-1",
                style="font-size: 0.7rem;",
            )

        html.Div(
            "No thresholds.",
            v_if="!ui_threshold_chain || ui_threshold_chain.length === 0",
            classes="text-caption text-medium-emphasis",
            style="font-size: 0.7rem;",
        )

        # Per-entry rows. Indentation tracks chain depth.
        with html.Div(
            v_for="(entry, idx) in (ui_threshold_chain || [])",
            key="entry.name",
            classes="mb-2",
        ):
            with html.Div(
                style=(
                    "{ display: 'flex', alignItems: 'center', gap: '4px',"
                    " paddingLeft: ((entry._depth || 0) * 12) + 'px' }",
                ),
            ):
                vuetify3.VBtn(
                    icon=("entry.visible ? 'mdi-eye' : 'mdi-eye-off'",),
                    click=(
                        "ui_threshold_pending_action = "
                        "{ action: 'set_visible', name: entry.name, visible: !entry.visible }"
                    ),
                    variant="text", density="compact", size="x-small",
                    color=("entry.visible ? 'primary' : 'grey'",),
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px;",
                )
                html.Span(
                    "{{ entry.array }}",
                    classes="text-caption font-weight-medium",
                    style="font-size: 0.75rem;",
                )
                html.Span(
                    "[{{ entry.low.toFixed(3) }} .. {{ entry.high.toFixed(3) }}]",
                    classes="text-caption text-medium-emphasis",
                    style="font-size: 0.7rem;",
                )
                vuetify3.VSpacer()
                with vuetify3.VTooltip(location="bottom"):
                    with vuetify3.Template(v_slot_activator="{ props }"):
                        vuetify3.VBtn(
                            icon="mdi-set-center",
                            v_bind="props",
                            disabled=("!active_color_array_name",),
                            click=(
                                "ui_threshold_pending_action = "
                                "{ action: 'add', parent: entry.name }"
                            ),
                            variant="text", density="compact", size="small",
                            color="primary",
                            style="margin: 0; padding: 0; min-width: 32px; width: 32px; height: 32px;",
                        )
                    html.Span(
                        "Add intersection — narrow this entry's cells further with a chained range"
                    )
                vuetify3.VBtn(
                    icon="mdi-delete",
                    click=(
                        "ui_threshold_pending_action = "
                        "{ action: 'delete', name: entry.name }"
                    ),
                    variant="text", density="compact", size="x-small",
                    color="grey",
                    style="margin: 0; padding: 0; min-width: 24px; width: 24px; height: 24px;",
                )

            with html.Div(
                style=(
                    "{ paddingLeft: ((entry._depth || 0) * 12 + 4) + 'px',"
                    " paddingRight: '4px' }",
                ),
            ):
                vuetify3.VRangeSlider(
                    model_value=("[entry.low, entry.high]",),
                    min=("entry.data_range[0]",),
                    max=("entry.data_range[1]",),
                    step=(
                        "(entry.data_range[1] - entry.data_range[0]) / 1000 || 1",
                    ),
                    strict=True,
                    thumb_label=False,
                    hide_details=True,
                    end=(
                        "ui_threshold_pending_action = "
                        "{ action: 'set_range', name: entry.name,"
                        " low: $event[0], high: $event[1] }"
                    ),
                )
