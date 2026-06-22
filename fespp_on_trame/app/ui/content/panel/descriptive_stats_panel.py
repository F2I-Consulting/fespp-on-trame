"""Descriptive statistics panel — multi-property tables.

Rendered as the body of the singleton `kind="stats"` dockview tab
(`multi_view._add_stats_panel`) so it has the full main-area width.
One card per property pinned in `state.ui_stats_pinned_paths`
(toggled via the tree's "Display stats" icon), each card holding:

  - A header with the property title, MR/TS kind chip, row count
    chip, and a `×` to unpin the property.

  - A **stats table** with one row per Original + one row per
    render view that's colouring by this property. The Row label
    cell of the **default** Original row embeds the editable
    `Real` / `Timestep` dropdowns + a pin button so the user can
    pick the slice of the property the baseline tracks. Custom
    (pinned) rows show their snapshotted label + a `×`; View
    rows are read-only. The leftmost `Cmp` column carries a `⊕`
    icon per row that adds the row to the comparison selection
    (consumed by `StatsComparePanel`). Cells render via
    `_cell_expr` — NaN / null → `–`, integers intact, floats
    clipped to 4 significant digits.

Recompute is server-side via
`stats_dispatch.publish_descriptive_stats`, triggered by every
relevant state change."""
from trame.widgets import html, vuetify3


# (column-key, display-label, align). Numeric stat columns only —
# the leftmost cells (Cmp / Source / Realization Index / Time Step)
# are rendered by hand because they carry per-row controls or
# kind-conditional v_if's that don't fit a flat loop.
_COLUMNS = [
    ("Cardinality", "Value count", "end"),
    ("NaN_count", "No value count", "end"),
    ("Minimum", "Min", "end"),
    ("Maximum", "Max", "end"),
    ("Mean", "Mean", "end"),
    ("Standard Deviation", "Std Dev", "end"),
    ("Variance", "Variance", "end"),
    ("Sum", "Sum", "end"),
    ("Q1", "Q1", "end"),
    ("Median", "Median", "end"),
    ("Q3", "Q3", "end"),
    ("Skewness", "Skewness", "end"),
    ("Kurtosis", "Kurtosis", "end"),
    ("M2", "M2", "end"),
    ("M3", "M3", "end"),
    ("M4", "M4", "end"),
]

# Vue expressions for the per-card kind gates. Realization Index
# and Time Step columns are always rendered (so every card shares
# the same grid and the columns visually line up across cards);
# the dropdowns / static values inside the cells gate on these.
_HAS_MR_KIND = "ui_stats_tables[array_path] && ui_stats_tables[array_path].is_mr"
_HAS_TS_KIND = "ui_stats_tables[array_path] && ui_stats_tables[array_path].is_ts"

# Fixed column widths in `px`. `table-layout: fixed` makes the
# browser honour these instead of auto-sizing to content, which is
# what keeps every card's columns lining up vertically. Order
# mirrors `_stat_columns_th` exactly.
_COL_WIDTHS = {
    "cmp": 44,
    "dist": 50,
    "source": 220,
    "real": 130,
    "ts": 150,
}
_NUMERIC_COL_WIDTH = 110


def _cell_expr(key):
    """JS expression: NaN/null → '–'. Integers stay integer
    (Cardinality). Floats clipped to `Number.toFixed(3)`."""
    return (
        f"(row['{key}'] == null"
        f" || (typeof row['{key}'] === 'number' && Number.isNaN(row['{key}'])))"
        " ? '–'"
        f" : (Number.isInteger(row['{key}'])"
        f"     ? row['{key}'].toString()"
        f"     : Number(row['{key}']).toFixed(3))"
    )


_TH_STYLE_BASE = (
    "padding: 4px 10px;"
    " border-bottom: 1px solid rgba(0,0,0,0.12);"
    " font-weight: 600;"
    " background: #f5f5f5;"
    " position: sticky; top: 0;"
)


def _stat_columns_th():
    """Header `<th>` for the Cmp + Source + Realization Index +
    Time Step + every numeric stat column. Widths are pinned (in
    px) so every card's table aligns vertically — `table-layout:
    fixed` on the table picks these up from the first row."""
    html.Th(
        "Cmp",
        v_if=(
            "ui_stats_tables && ui_stats_tables[array_path]"
            " && (ui_stats_tables[array_path].is_mr"
            "     || ui_stats_tables[array_path].is_ts)",
        ),
        style=(
            f"{_TH_STYLE_BASE} width: {_COL_WIDTHS['cmp']}px;"
            " text-align: center;"
        ),
        title=(
            "Pick rows to add to the property's compare cart"
            " (Compare button in the card header opens the floating"
            " panel; Show distributions button there opens the"
            " overlay)."
        ),
    )
    html.Th(
        "Dist",
        style=(
            f"{_TH_STYLE_BASE} width: {_COL_WIDTHS['dist']}px;"
            " text-align: center;"
        ),
        title="Open this row's value distribution (histogram)",
    )
    html.Th(
        "Source",
        style=(
            f"{_TH_STYLE_BASE} width: {_COL_WIDTHS['source']}px;"
            " text-align: start;"
        ),
    )
    html.Th(
        "Realization Index",
        style=(
            f"{_TH_STYLE_BASE} width: {_COL_WIDTHS['real']}px;"
            " text-align: start;"
        ),
    )
    html.Th(
        "Time Step",
        style=(
            f"{_TH_STYLE_BASE} width: {_COL_WIDTHS['ts']}px;"
            " text-align: start;"
        ),
    )
    for _key, label, align in _COLUMNS:
        html.Th(
            label,
            style=(
                f"{_TH_STYLE_BASE} width: {_NUMERIC_COL_WIDTH}px;"
                f" text-align: {align};"
            ),
        )


def _stat_columns_td():
    """Numeric stat `<td>` cells for the current `row` iteration."""
    for key, _label, align in _COLUMNS:
        html.Td(
            f"{{{{ {_cell_expr(key)} }}}}",
            style=(
                "padding: 4px 10px;"
                f" text-align: {align};"
                " font-variant-numeric: tabular-nums;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
                " overflow: hidden; text-overflow: ellipsis;"
            ),
        )


class DescriptiveStatsPanel:
    """Renders one card per pinned property — see the module docstring."""

    def render(self):
        self._render_empty_state()
        with html.Div(
            v_if="ui_stats_pinned_paths && ui_stats_pinned_paths.length > 0",
            classes="d-flex flex-column",
            style="gap: 16px;",
        ):
            self._render_property_cards()

    # ------------------------------------------------------------------
    # Render helpers — each builds one independent block of the panel.

    def _render_empty_state(self):
        """Hint shown when nothing is pinned yet (gated on the
        `ui_stats_pinned_paths` length)."""
        with html.Div(
            v_if="!ui_stats_pinned_paths || ui_stats_pinned_paths.length === 0",
            classes="text-medium-emphasis pa-6 text-center",
        ):
            vuetify3.VIcon(
                "mdi-chart-box-outline",
                size="64",
                color="grey-lighten-1",
            )
            html.Div(
                "No property pinned for stats yet.",
                classes="text-body-1 mt-3 font-weight-medium",
            )
            html.Div(
                "Click the chart icon next to a property in the tree to pin it.",
                classes="text-caption mt-1",
            )

    def _render_property_cards(self):
        """One VCard per pinned property. The cards are v-for'd off
        `ui_stats_pinned_paths`; everything inside reads
        `ui_stats_tables[array_path]` directly."""
        with vuetify3.VCard(
            v_for="array_path in ui_stats_pinned_paths",
            key="array_path",
            elevation=1,
            classes="pa-0",
        ):
            self._render_card_header()
            self._render_stats_table()

    def _render_card_header(self):
        """Per-card header strip: title + tree-aligned signage
        (primary property-kind icon + TS clock + MR chip) + row
        count chip + unpin button. The icon / chip set mirrors the
        tree's property row exactly (see `tree_views`) so users
        can map a card to its source node at a glance."""
        with html.Div(
            classes="d-flex align-center pa-3",
            style=(
                "background: #fafafa;"
                " border-bottom: 1px solid rgba(0,0,0,0.08);"
            ),
        ):
            vuetify3.VIcon(
                "{{ (ui_stats_tables && ui_stats_tables[array_path]"
                " && ui_stats_tables[array_path].icon)"
                " || 'mdi-chart-box-outline' }}",
                color="green-darken-1",
                classes="mr-2",
            )
            # Rep parent label as a dimmed prefix — only when the
            # tree resolved a rep title for this property, so two
            # reps that carry an identically-named property (e.g.
            # VOIL) can still be told apart in the card header.
            html.Span(
                "{{ (ui_stats_tables && ui_stats_tables[array_path]"
                " && ui_stats_tables[array_path].rep_title) }} /",
                v_if=("ui_stats_tables && ui_stats_tables[array_path]"
                      " && ui_stats_tables[array_path].rep_title",),
                classes="text-body-2 text-medium-emphasis mr-1",
            )
            html.Span(
                "{{ (ui_stats_tables && ui_stats_tables[array_path]"
                " && ui_stats_tables[array_path].title)"
                " || array_path }}",
                classes="text-subtitle-1 font-weight-medium",
            )
            # TS badge (same icon/colour as the tree).
            vuetify3.VIcon(
                "mdi-timeline-clock",
                v_if=(
                    "ui_stats_tables && ui_stats_tables[array_path]"
                    " && ui_stats_tables[array_path].is_ts",
                ),
                size="x-small",
                color="purple",
                classes="ml-2",
            )
            # MR badge (same chip as the tree).
            vuetify3.VChip(
                "MR",
                v_if=(
                    "ui_stats_tables && ui_stats_tables[array_path]"
                    " && ui_stats_tables[array_path].is_mr",
                ),
                size="x-small",
                variant="tonal",
                color="purple",
                classes="ml-1",
            )
            _can_cmp = (
                "ui_stats_tables && ui_stats_tables[array_path]"
                " && (ui_stats_tables[array_path].is_mr"
                "     || ui_stats_tables[array_path].is_ts)"
            )
            _cmp_count = (
                "(ui_stats_compare && ui_stats_compare[array_path]"
                "  ? ui_stats_compare[array_path].length : 0)"
            )
            vuetify3.VBtn(
                "Compare",
                v_if=(_can_cmp,),
                variant="flat", density="compact", size="small",
                color="primary",
                prepend_icon="mdi-table-eye",
                classes="ml-3",
                disabled=(_cmp_count + " < 2",),
                click=(
                    "trigger('open_compare_stats', [array_path])"
                ),
            )
            vuetify3.VChip(
                "{{ " + _cmp_count + " }} in cart",
                v_if=(_can_cmp + " && " + _cmp_count + " > 0",),
                size="x-small", variant="tonal", color="primary",
                classes="ml-2",
            )
            vuetify3.VSpacer()
            vuetify3.VChip(
                "{{ (ui_stats_tables && ui_stats_tables[array_path]"
                " && ui_stats_tables[array_path].rows)"
                " ? (ui_stats_tables[array_path].rows.length"
                " + ' row' + (ui_stats_tables[array_path].rows.length > 1 ? 's' : ''))"
                " : '0 rows' }}",
                size="x-small",
                variant="tonal",
                color="teal",
                classes="mr-2",
            )
            vuetify3.VBtn(
                icon="mdi-close",
                variant="text",
                density="compact",
                size="small",
                color="grey",
                title=("'Stop showing stats for this property'",),
                click="trigger('toggle_stats_display', [array_path])",
            )

    def _render_stats_table(self):
        """The per-card stats table: header row + one body row per
        entry in `ui_stats_tables[array_path].rows`. Horizontal
        scroll engages only when the table genuinely doesn't fit."""
        with html.Div(
            style="overflow-x: auto; width: 100%; font-size: 0.8rem;",
        ):
            with html.Table(
                style=(
                    "border-collapse: collapse;"
                    " white-space: nowrap;"
                    " table-layout: fixed;"
                ),
            ):
                with html.Thead():
                    with html.Tr():
                        _stat_columns_th()
                with html.Tbody():
                    with html.Tr(
                        v_for=(
                            "row in ((ui_stats_tables"
                            " && ui_stats_tables[array_path])"
                            " ? ui_stats_tables[array_path].rows"
                            " : [])"
                        ),
                        # `ui_stats_publish_version` bumps on every
                        # recompute so Vue diffs see every row as
                        # new — keeps the cell text bindings AND
                        # the VSelect v-models in sync with the
                        # fresh server-side values without forcing
                        # a tab re-focus.
                        key=(
                            "ui_stats_publish_version + '-'"
                            " + row.kind + '-' + row.id"
                        ),
                    ):
                        self._render_row_compare_cell()
                        self._render_row_distribution_cell()
                        self._render_row_source_cell()
                        self._render_row_realization_cell()
                        self._render_row_timestep_cell()
                        _stat_columns_td()

    def _render_row_compare_cell(self):
        """Leftmost `Cmp` column — a single icon button that flips
        between `mdi-plus-circle-outline` (off, grey) and
        `mdi-check-circle` (on, primary). Click toggles the row in /
        out of `ui_stats_compare[array_path]`. Cell only renders on
        MR / TS cards (the per-property cart is meaningless on
        static cards with a single row)."""
        is_selected = (
            "((ui_stats_compare && ui_stats_compare[array_path] || [])"
            ".indexOf(array_path + '|' + row.kind + '|' + row.id) !== -1)"
        )
        with html.Td(
            v_if=(
                "ui_stats_tables && ui_stats_tables[array_path]"
                " && (ui_stats_tables[array_path].is_mr"
                "     || ui_stats_tables[array_path].is_ts)",
            ),
            style=(
                "padding: 0 8px;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
                " text-align: center;"
            ),
        ):
            vuetify3.VBtn(
                icon=(
                    is_selected
                    + " ? 'mdi-check-circle' : 'mdi-plus-circle-outline'",
                ),
                variant="text", density="compact", size="small",
                color=(
                    is_selected + " ? 'primary' : 'grey'",
                ),
                title=(
                    is_selected
                    + " ? 'Remove from compare cart'"
                    + " : 'Add to compare cart'",
                ),
                click=(
                    "trigger('stats_compare_toggle',"
                    " [array_path, array_path + '|' + row.kind + '|' + row.id])"
                ),
            )

    def _render_row_distribution_cell(self):
        """`Dist` column — a single icon button opening this row's value
        distribution (histogram). Always present (every row has a
        distribution), in its own column so it lines up across cards."""
        with html.Td(
            style=(
                "padding: 0 4px;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
                " text-align: center;"
            ),
        ):
            vuetify3.VBtn(
                icon="mdi-chart-histogram",
                variant="text", density="compact", size="x-small",
                color="indigo-darken-2",
                title="Open this row's value distribution",
                click=(
                    "trigger('open_row_histogram',"
                    " [array_path, row.kind, row.id])"
                ),
            )

    def _render_row_source_cell(self):
        """`Source` column — `row.label` (property name for an
        Original row, `<property> On <view title>` for a View row)
        plus the row-scoped pin (default) / unpin (custom) icon.
        The Realization Index and Time Step columns carry the
        per-row dropdowns / static values — Source stays narrow.

        The pin / unpin icons only appear on cards that actually
        have something to pin (MR or TS kind). A static
        ContinuousProperty has a single state — snapshotting it
        would create a row indistinguishable from the default."""
        is_default = (
            "row.kind === 'original' && row.id === 'default'"
        )
        is_custom_original = (
            "row.kind === 'original' && row.id !== 'default'"
        )
        # `is_pinnable` = MR or TS card (= "has more than one
        # (real, ts) combination to snapshot").
        is_pinnable = (
            "ui_stats_tables[array_path]"
            " && (ui_stats_tables[array_path].is_mr"
            " || ui_stats_tables[array_path].is_ts)"
        )
        with html.Td(
            style=(
                "padding: 4px 10px;"
                " text-align: left;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
            ),
        ):
            with html.Div(
                classes="d-flex align-center",
                style="gap: 6px; font-family: monospace;",
            ):
                html.Span("{{ row.label }}")
                vuetify3.VBtn(
                    v_if=(f"({is_default}) && ({is_pinnable})",),
                    icon="mdi-pin-outline",
                    variant="text",
                    density="compact",
                    size="small",
                    color="primary",
                    title=(
                        "'Pin current values as"
                        " a new editable comparison row'",
                    ),
                    click=(
                        "trigger('stats_pin_original',"
                        " [array_path, row.id])"
                    ),
                )
                vuetify3.VBtn(
                    v_if=(f"({is_custom_original}) && ({is_pinnable})",),
                    icon="mdi-pin-off-outline",
                    variant="text",
                    density="compact",
                    size="small",
                    color="grey",
                    title=("'Remove this pinned row'",),
                    click=(
                        "trigger('stats_unpin_original',"
                        " [array_path, row.id])"
                    ),
                )

    def _render_row_realization_cell(self):
        """`Realization Index` cell — always rendered so every card's
        table aligns column-for-column. The dropdown only appears
        on the default Original row of MR cards; everywhere else
        the static `row.real_idx` is shown (or `–` for static
        non-MR cards / view rows without a realization)."""
        is_default_on_mr = (
            f"({_HAS_MR_KIND})"
            " && row.kind === 'original' && row.id === 'default'"
        )
        with html.Td(
            style=(
                "padding: 4px 10px;"
                " text-align: left;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
                " font-variant-numeric: tabular-nums;"
            ),
        ):
            vuetify3.VSelect(
                v_if=(
                    f"{is_default_on_mr}"
                    " && ui_stats_tables[array_path].available_realizations"
                    " && ui_stats_tables[array_path]"
                    ".available_realizations.length > 0",
                ),
                v_model=("row.real_idx",),
                items=(
                    "ui_stats_tables[array_path]"
                    ".available_realizations",
                ),
                density="compact",
                hide_details=True,
                variant="outlined",
                style="min-width: 70px; max-width: 100px;",
                menu_props=("{ maxWidth: 360 }",),
                update_modelValue=(
                    "trigger('stats_set_original_real_idx', "
                    "[array_path, row.id, $event])"
                ),
            )
            html.Span(
                "{{ row.real_idx != null ? row.real_idx : '–' }}",
                v_if=(f"!({is_default_on_mr})",),
            )

    def _render_row_timestep_cell(self):
        """`Time Step` cell — always rendered, same alignment
        rationale as the Realization Index cell. Dropdown only on
        the default Original row of TS cards; static `row.ts_label`
        elsewhere."""
        is_default_on_ts = (
            f"({_HAS_TS_KIND})"
            " && row.kind === 'original' && row.id === 'default'"
        )
        with html.Td(
            style=(
                "padding: 4px 10px;"
                " text-align: left;"
                " border-bottom: 1px solid rgba(0,0,0,0.06);"
            ),
        ):
            vuetify3.VSelect(
                v_if=(
                    f"{is_default_on_ts}"
                    " && ui_stats_tables[array_path].available_timesteps"
                    " && ui_stats_tables[array_path]"
                    ".available_timesteps.length > 0",
                ),
                v_model=("row.ts_idx",),
                items=(
                    "ui_stats_tables[array_path]"
                    ".available_timesteps",
                ),
                item_title="label",
                item_value="value",
                density="compact",
                hide_details=True,
                variant="outlined",
                style="min-width: 130px; max-width: 170px;",
                menu_props=("{ maxWidth: 360 }",),
                update_modelValue=(
                    "trigger('stats_set_original_ts_idx', "
                    "[array_path, row.id, $event])"
                ),
            )
            html.Span(
                "{{ row.ts_label || '–' }}",
                v_if=(f"!({is_default_on_ts})",),
            )
