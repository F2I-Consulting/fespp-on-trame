"""Compare-stats floating panel (kind="stats_compare").

Dockview floating panel, singleton-per-property
(state.ui_stats_compare_panel[array_path] = panel_id); spawn / focus
handled by the boot._open_compare_stats trigger.

Each panel owns per-panel state vars suffixed with '_<panel_id>' so
two compare panels (for different properties) don't clobber each
other's toolbar settings.
"""
from trame.app import get_server
from trame.widgets import html, vuetify3


class StatsComparePanel:
    def __init__(self, panel_id: str):
        self._panel_id = panel_id

    # ---- state var helpers ----
    @property
    def array_path_var(self): return f"ui_stats_compare_array_path_{self._panel_id}"
    @property
    def items_var(self): return f"ui_stats_compare_items_{self._panel_id}"
    @property
    def visible_metrics_var(self): return f"ui_stats_compare_visible_metrics_{self._panel_id}"
    @property
    def baseline_var(self): return f"ui_stats_compare_baseline_{self._panel_id}"
    @property
    def transposed_var(self): return f"ui_stats_compare_transposed_{self._panel_id}"
    @property
    def sort_key_var(self): return f"ui_stats_compare_sort_key_{self._panel_id}"
    @property
    def sort_asc_var(self): return f"ui_stats_compare_sort_asc_{self._panel_id}"
    @property
    def csv_var(self): return f"ui_stats_compare_csv_{self._panel_id}"

    @property
    def order_var(self): return f"ui_stats_compare_order_{self._panel_id}"

    @property
    def annotations_var(self): return f"ui_stats_compare_annotations_{self._panel_id}"

    def render(self):
        with vuetify3.VContainer(
            fluid=True,
            classes="pa-0 ma-0 d-flex flex-column",
            style="height: 100%; width: 100%;",
        ):
            # Per-panel CSS for the highlight-mode cell classes bound
            # dynamically below via raw_attrs=[":class=..."]. html.Style
            # mounts a <style> tag inline; the very-specific class names
            # keep the rules scoped to the compare-table cells.
            html.Style(
                ".cmp-cell-min { background-color: rgba(33, 150, 243, 0.18); }"
                " .cmp-cell-max { background-color: rgba(255, 152, 0, 0.18); }"
                " .cmp-cell-pos { color: #2e7d32; }"
                " .cmp-cell-neg { color: #c62828; }"
                " .cmp-cell-eq  { color: #757575; }"
                " .cmp-delta { font-size: 0.7em; margin-left: 4px;"
                "              opacity: 0.85; }"
                # Sticky-left anchors for layout A (items as columns):
                # the Metric label column stays glued to the left edge
                # of the scroll area, and the baseline column (when set)
                # sticks right after it at x=140px (= Metric col
                # min-width). Both carry an opaque background so
                # scrolled-under content doesn't bleed through, and
                # z-index keeps them above regular cells during scroll.
                " .cmp-col-metric { position: sticky; left: 0;"
                "     background: #fafafa; z-index: 2;"
                "     min-width: 140px; }"
                " .cmp-col-baseline-anchor { position: sticky;"
                "     left: 140px; background: #fff; z-index: 2;"
                "     box-shadow: 4px 0 4px -2px rgba(0,0,0,0.08); }"
            )
            self._render_toolbar()
            # Flex hosting for the table. Both flex levels carry
            # `min-width: 0` so they can shrink below their
            # intrinsic content size — without that, the table's
            # natural `width: max-content` propagates up the flex
            # chain and the inner Div's `overflow-x: auto` never
            # triggers, killing the horizontal scrollbar (and with
            # it the sticky-left baseline anchor that depends on
            # actual scrolling). `overflow: hidden` here makes the
            # outer levels clip silently and defers the visible
            # scrollbar to the inner Div in _render_table.
            with vuetify3.VRow(
                no_gutters=True,
                classes="ma-0",
                style="flex: 1 1 auto; min-height: 0; min-width: 0;"
                " overflow: hidden;",
            ):
                with vuetify3.VCol(
                    classes="pa-2",
                    style="min-height: 0; min-width: 0;"
                    " overflow: hidden;",
                ):
                    self._render_table()

    def _render_toolbar(self):
        ap = self.array_path_var
        with vuetify3.VToolbar(
            density="compact", flat=True, classes="pa-1",
            style="flex: 0 0 auto; min-height: 40px;",
        ):
            # Live badge: "<rep_title> / <property title> - N rows".
            # The rep_title prefix is shown ONCE here (in the chip),
            # not per-item, to avoid repeating it on every cart row.
            vuetify3.VChip(
                "{{ (ui_stats_tables && ui_stats_tables[" + ap + "]"
                " && ui_stats_tables[" + ap + "].rep_title"
                " ? ui_stats_tables[" + ap + "].rep_title + ' / ' : '') }}"
                "{{ (ui_stats_tables && ui_stats_tables[" + ap + "]"
                " ? ui_stats_tables[" + ap + "].title : '') }} -"
                " {{ ((ui_stats_compare && ui_stats_compare[" + ap + "])"
                "    ? ui_stats_compare[" + ap + "].length : 0) }} rows",
                size="small", variant="tonal", color="primary",
                classes="mr-3",
            )
            # Baseline picker — always visible. A "(no baseline)"
            # sentinel entry sits at the head of the items list so
            # the user can opt out without hiding the dropdown.
            vuetify3.VSelect(
                v_model=(self.baseline_var, ""),
                items=("[{ title: '(no baseline)', value: '' }].concat("
                       "(" + self.items_var + " || []).map(it => "
                       "({ title: it.column_label || it.key, value: it.key })))",),
                item_title="title", item_value="value",
                label="Baseline",
                density="compact", hide_details=True,
                variant="outlined",
                style="min-width: 180px; max-width: 260px;",
                classes="mr-2",
                menu_props=("{ maxWidth: 360 }",),
            )
            # Visible-metrics picker. The v-model is the list of
            # metrics to SHOW (default = every metric); the table reads
            # `visible.includes(m.k)`. The trigger button carries no
            # selection text — the visible columns are already apparent
            # in the table — it only opens the menu of toggles.
            _ALL_KEYS = (
                "['Cardinality','NaN_count','Minimum','Maximum',"
                "'Mean','Standard Deviation','Variance','Sum',"
                "'Q1','Median','Q3','Skewness','Kurtosis',"
                "'M2','M3','M4']"
            )
            with vuetify3.VMenu(close_on_content_click=False):
                with vuetify3.Template(v_slot_activator="{ props }"):
                    vuetify3.VBtn(
                        "Metrics visibility",
                        prepend_icon="mdi-eye-settings-outline",
                        variant="outlined", density="compact", size="small",
                        classes="mr-2",
                        v_bind="props",
                    )
                with vuetify3.VList(density="compact", min_width=220):
                    # Preset shortcuts at the top of the menu.
                    # Each preset writes the VISIBLE list directly.
                    _PRESETS = {
                        "Central tendency":
                            "['Mean','Median','Q1','Q3']",
                        "Spread":
                            "['Minimum','Maximum','Standard Deviation','Variance']",
                        "Shape":
                            "['Skewness','Kurtosis','M2','M3','M4']",
                        "All": _ALL_KEYS,
                    }
                    vuetify3.VListSubheader("Presets")
                    for label, value in _PRESETS.items():
                        vuetify3.VListItem(
                            title=label,
                            density="compact",
                            click=(self.visible_metrics_var + " = " + value),
                        )
                    vuetify3.VDivider()
                    vuetify3.VListSubheader("Toggle individual columns")
                    # Per-metric toggle items. Click flips the key
                    # in/out of the visible list. The leading icon
                    # mirrors the current state for at-a-glance scan
                    # without needing v-checkbox machinery.
                    with vuetify3.VListItem(
                        v_for=("k in " + _ALL_KEYS,),
                        key=("k",),
                        density="compact",
                        click=(
                            "(" + self.visible_metrics_var + " || []).includes(k)"
                            "  ? " + self.visible_metrics_var + " = "
                            + "(" + self.visible_metrics_var + " || []).filter(x => x !== k)"
                            "  : " + self.visible_metrics_var + " = "
                            + "[...(" + self.visible_metrics_var + " || []), k]"
                        ),
                    ):
                        with vuetify3.Template(v_slot_prepend=True):
                            vuetify3.VIcon(
                                "((" + self.visible_metrics_var + " || []).includes(k)"
                                " ? 'mdi-checkbox-marked'"
                                " : 'mdi-checkbox-blank-outline')",
                                size="small",
                                color=("((" + self.visible_metrics_var + " || []).includes(k)"
                                       " ? 'primary' : 'grey')",),
                            )
                        with vuetify3.Template(v_slot_title=True):
                            html.Span("{{ k }}")
            # Transpose toggle. Icon flips between rotate-left and
            # rotate-right depending on the current orientation;
            # colour stays constant (primary blue, drawer-tone) so
            # the affordance reads the same in both states.
            vuetify3.VBtn(
                icon=("(" + self.transposed_var + " ? 'mdi-rotate-right-variant'"
                      " : 'mdi-rotate-left-variant')",),
                size="small",
                variant="text",
                title=("(" + self.transposed_var + " ? 'Switch to columns = items'"
                       " : 'Switch to rows = items')",),
                color="primary",
                click=(self.transposed_var + " = !" + self.transposed_var),
            )
            vuetify3.VSpacer()
            # Show distributions
            vuetify3.VBtn(
                "Show distributions",
                prepend_icon="mdi-chart-histogram",
                variant="flat", density="compact", size="small",
                color="indigo-darken-2",
                classes="mr-2",
                click=(
                    "trigger('open_compare_distributions', [" + ap + "])"
                ),
            )
            # CSV download (data URL in csv_var)
            # TODO(release): CSV download is DISABLED for this release — the
            # data-URL download drops the websocket ("Connection closed").
            # RE-ENABLE once the download is reworked (e.g. server-streamed
            # endpoint instead of an in-page data: URL). csv_var is still
            # computed, so just restore the button:
            #
            # vuetify3.VBtn(
            #     icon="mdi-download", size="small", variant="text",
            #     href=(self.csv_var,),
            #     download="compare.csv",
            #     target="_blank",
            #     disabled=("!" + self.csv_var,),
            #     title="Download CSV of the compare matrix",
            # )

    def _render_table(self):
        """Render the comparison matrix as a Vuetify table. The
        items_var holds the full list of cart rows resolved with
        their numeric stats; the panel applies the per-panel
        transpose / hidden_metrics / sort / highlight at template
        time via computed expressions. Highlight uses CSS class
        bindings tied to the highlight mode + baseline.

        Dynamic-class-binding pattern: html.Td's `classes` keyword is
        for STATIC class lists only. For Vue's `:class="{...}"` dynamic
        bindings, `raw_attrs=[':class="EXPR"']` injects the directive
        verbatim into the generated template. The annotations dict is
        read via `(annotations || {})[metric_key] || {})[row_index]`,
        so a missing tag silently yields no class."""
        # The metric row list mirrors _METRIC_LABELS in
        # compare_matrix.py, duplicated here as a JS-side computed.
        # The transpose toggle swaps the table layout client-side.
        METRIC_LIST_JS = (
            "[{k:'Cardinality',l:'Value count'},"
            "{k:'NaN_count',l:'No value count'},"
            "{k:'Minimum',l:'Min'},"
            "{k:'Maximum',l:'Max'},"
            "{k:'Mean',l:'Mean'},"
            "{k:'Standard Deviation',l:'Std Dev'},"
            "{k:'Variance',l:'Variance'},"
            "{k:'Sum',l:'Sum'},"
            "{k:'Q1',l:'Q1'},"
            "{k:'Median',l:'Median'},"
            "{k:'Q3',l:'Q3'},"
            "{k:'Skewness',l:'Skewness'},"
            "{k:'Kurtosis',l:'Kurtosis'},"
            "{k:'M2',l:'M2'},{k:'M3',l:'M3'},{k:'M4',l:'M4'}]"
        )
        items = self.items_var
        visible = self.visible_metrics_var
        transposed = self.transposed_var
        sortk = self.sort_key_var
        sorta = self.sort_asc_var
        # Filter the canonical metric list down to the user's visible
        # set (default = all visible; the Columns menu unticks to drop).
        visible_metrics_expr = (
            "(" + METRIC_LIST_JS + ").filter(m => "
            "(" + visible + " || []).includes(m.k))"
        )
        # Sorted items (client-side numeric sort by sort_key_var).
        # Metric values live under `it.row.<metric_key>`
        # (publish_compare_items returns {key, row, column_label,
        # extrema, propertyTitle}), matching the cell renders below.
        sorted_items_expr = (
            "((" + items + " || []).slice().sort((a,b) => {"
            "if (!" + sortk + ") return 0;"
            "const va = (a.row||{})[" + sortk + "], vb = (b.row||{})[" + sortk + "];"
            "if (va == null) return 1; if (vb == null) return -1;"
            "return (" + sorta + " ? 1 : -1) * (va - vb);"
            "}))"
        )
        with html.Div(
            # Both axes scrollable. `overflow-x: auto` is what makes
            # the sticky-left baseline anchor meaningful — without
            # active horizontal scrolling the sticky positioning is
            # a no-op. `max-width: 100%` clamps the wrapper to its
            # flex parent so the inner table's `width: max-content`
            # actually overflows here rather than pushing the
            # parents wider.
            style="overflow-x: auto; overflow-y: auto;"
            " max-height: 100%; max-width: 100%; width: 100%;"
        ):
            # Layout A: items as columns (metrics in rows). Transpose flips.
            # `width: max-content` lets the table grow horizontally past
            # the wrapper so the parent's overflow-x kicks in instead of
            # squeezing the columns into illegible widths.
            with html.Table(
                v_if=("!" + transposed,),
                # border-collapse: separate is required for
                # position: sticky on table cells. With collapse,
                # sticky breaks on the cmp-col-metric + cmp-col-
                # baseline-anchor cells (known browser limitation).
                style="border-collapse: separate; border-spacing: 0;"
                " width: max-content; min-width: 100%;",
            ):
                with html.Thead():
                    with html.Tr():
                        # Sticky-left applied inline: the cmp-col-metric
                        # class doesn't paint on html.Th under Vuetify's
                        # table reset.
                        html.Th("Metric",
                                style="text-align: start;"
                                " padding: 4px 8px;"
                                " border-bottom: 1px solid rgba(0,0,0,0.12);"
                                " position: sticky; left: 0;"
                                " background: #fafafa; z-index: 2;"
                                " min-width: 140px;")
                        with html.Th(
                            v_for=("(it, idx) in " + sorted_items_expr,),
                            key=("it.key",),
                            style="text-align: end;"
                            " padding: 4px 8px; border-bottom: 1px solid rgba(0,0,0,0.12);"
                            " white-space: nowrap; cursor: move;",
                            raw_attrs=[
                                # Dynamic baseline anchor as inline
                                # style: glue this Th to the left
                                # of the scroll area right after
                                # the Metric column (left:140px).
                                ':style="it.key === '
                                + self.baseline_var
                                + " ? 'position: sticky; left: 140px;"
                                "  background: #fff; z-index: 2;"
                                "  box-shadow: 4px 0 4px -2px rgba(0,0,0,0.08);'"
                                + " : ''" + '"',
                                # Drag-source: stash this item's key on the drag event.
                                ':draggable="true"',
                                '@dragstart="(e) => e.dataTransfer.setData(\'text/plain\', it.key)"',
                                '@dragover.prevent=""',
                                # On drop: build the new order with the dropped item moved
                                # before this Th's item. The order is sourced from the
                                # current display list (sorted_items_expr) and written back
                                # to the order state var.
                                '@drop="(e) => { const src = e.dataTransfer.getData(\'text/plain\');'
                                ' if (!src || src === it.key) return;'
                                ' const keys = (' + sorted_items_expr + ').map(x => x.key);'
                                ' const filtered = keys.filter(k => k !== src);'
                                ' const idx = filtered.indexOf(it.key);'
                                ' filtered.splice(idx, 0, src);'
                                ' ' + self.order_var + ' = filtered; }"',
                            ],
                        ):
                            with html.Div(classes="d-inline-flex align-center"):
                                html.Span(
                                    "{{ it.column_label || it.key }}",
                                    classes="mr-1",
                                )
                                # Distribution-profile chip. Text/colour/title
                                # are pure template expressions driven by
                                # `it.profile` (populated server-side in
                                # publish_compare_items from each row's
                                # skewness/kurtosis). Empty string means
                                # the profile is unknown — v_if hides the
                                # chip in that case so it doesn't render
                                # as a blank pill.
                                vuetify3.VChip(
                                    "{{ it.profile === 'symmetric' ? 'sym'"
                                    "    : it.profile === 'skewed_right' ? '↦ skew'"
                                    "    : it.profile === 'skewed_left' ? '↤ skew'"
                                    "    : it.profile === 'heavy_tail' ? 'heavy'"
                                    "    : '' }}",
                                    v_if=("it.profile",),
                                    size="x-small", variant="tonal",
                                    color=(
                                        "it.profile === 'heavy_tail' ? 'purple'"
                                        "  : it.profile === 'symmetric' ? 'green'"
                                        "  : 'orange'",
                                    ),
                                    title=(
                                        "it.profile === 'symmetric' ? 'Symmetric distribution'"
                                        "  : it.profile === 'heavy_tail' ? 'Heavy-tailed (excess kurtosis > 3)'"
                                        "  : it.profile === 'skewed_right' ? 'Right-skewed (skewness >= 0.5)'"
                                        "  : it.profile === 'skewed_left' ? 'Left-skewed (skewness <= -0.5)'"
                                        "  : ''",
                                    ),
                                )
                with html.Tbody():
                    with html.Tr(v_for=("m in " + visible_metrics_expr,), key=("m.k",)):
                        html.Td(
                            "{{ m.l }}",
                            style="text-align: start; padding: 4px 8px;"
                            " border-bottom: 1px solid rgba(0,0,0,0.06);"
                            " font-weight: 500;"
                            " position: sticky; left: 0;"
                            " background: #fafafa; z-index: 1;"
                            " min-width: 140px;",
                        )
                        # Annotation tag lookup expression — shared
                        # by the :class binding and the ↑↓ chip.
                        ann_tag_a = (
                            "((" + self.annotations_var + " || {})[m.k] || {})[idx]"
                        )
                        delta_a = (
                            "(((" + self.annotations_var + " || {})['_deltas'] || {})[m.k] || {})[idx]"
                        )
                        with html.Td(
                            v_for=("(it, idx) in " + sorted_items_expr,),
                            key=("it.key",),
                            style="text-align: end; padding: 4px 8px;"
                            " border-bottom: 1px solid rgba(0,0,0,0.06);"
                            " font-variant-numeric: tabular-nums;"
                            " white-space: nowrap;",
                            raw_attrs=[
                                ':class="{'
                                " 'cmp-cell-min': " + ann_tag_a + " === 'min',"
                                " 'cmp-cell-max': " + ann_tag_a + " === 'max',"
                                " 'cmp-cell-pos': " + ann_tag_a + " === 'pos',"
                                " 'cmp-cell-neg': " + ann_tag_a + " === 'neg',"
                                " 'cmp-cell-eq': " + ann_tag_a + " === 'eq'"
                                ' }"',
                                # Inline baseline anchor (sticky-left
                                # after the Metric column). Class-
                                # based binding via cmp-col-baseline-
                                # anchor didn't paint on cells either
                                # so we put the rule inline.
                                ':style="it.key === '
                                + self.baseline_var
                                + " ? 'position: sticky; left: 140px;"
                                "  background: #fff; z-index: 1;"
                                "  box-shadow: 4px 0 4px -2px rgba(0,0,0,0.08);'"
                                + " : ''" + '"',
                            ],
                        ):
                            html.Span(
                                "{{ ((it.row||{})[m.k] == null"
                                "    ? '-'"
                                "    : Number.isInteger((it.row||{})[m.k])"
                                "      ? (it.row||{})[m.k].toString()"
                                "      : Number((it.row||{})[m.k]).toFixed(3)) }}",
                            )
                            # Baseline-mode direction arrow in its own
                            # Span so it carries a vivid green / red
                            # colour + bold weight independent of the
                            # cell text. The colour goes through inline
                            # `style=()` (proxied to Vue's :style); a
                            # CSS class via raw_attrs / classes=() is
                            # not honoured by the Span renderer here.
                            html.Span(
                                "{{ " + delta_a + ".abs > 0 ? '↑' : ("
                                + delta_a + ".abs < 0 ? '↓' : '=') }}",
                                v_if=(self.baseline_var + " && "
                                      + delta_a,),
                                style=(
                                    "({ color: " + delta_a + ".abs > 0 ? '#1b5e20'"
                                    " : (" + delta_a + ".abs < 0 ? '#b71c1c' : '#616161'),"
                                    " fontWeight: 700, fontSize: '1.15em',"
                                    " marginLeft: '4px' })",
                                ),
                            )
                            # Numeric delta details next to the
                            # arrow: abs(delta) + optional rel%.
                            # Kept in a separate Span with the
                            # small/faded `cmp-delta` styling.
                            html.Span(
                                "{{ ("
                                + delta_a + " ? "
                                "(" + delta_a + ".abs.toFixed(3) +"
                                " (" + delta_a + ".rel != null"
                                "    ? ' | ' + " + delta_a + ".rel.toFixed(1) + '%'"
                                "    : ''))"
                                " : '') }}",
                                v_if=(self.baseline_var,),
                                classes="cmp-delta",
                            )
            # Layout B: transpose (items as rows, metrics as columns).
            # Same width: max-content trick so wide stat tables scroll
            # horizontally instead of squeezing.
            with html.Table(
                v_if=(transposed,),
                # border-collapse: separate is required for
                # position: sticky on table cells. With collapse,
                # sticky breaks on the cmp-col-metric + cmp-col-
                # baseline-anchor cells (known browser limitation).
                style="border-collapse: separate; border-spacing: 0;"
                " width: max-content; min-width: 100%;",
            ):
                with html.Thead():
                    with html.Tr():
                        html.Th("Row", style="text-align: start;"
                                " padding: 4px 8px; border-bottom: 1px solid rgba(0,0,0,0.12);")
                        with html.Th(
                            v_for=("m in " + visible_metrics_expr,),
                            key=("m.k",),
                            style="text-align: end; cursor: pointer;"
                            " padding: 4px 8px; border-bottom: 1px solid rgba(0,0,0,0.12);",
                            click=(
                                "if (" + sortk + " === m.k) "
                                + sorta + " = !" + sorta + ";"
                                " else { " + sortk + " = m.k; " + sorta + " = true; }"
                            ),
                        ):
                            html.Span("{{ m.l }}")
                            vuetify3.VIcon(
                                "(" + sortk + " === m.k"
                                " ? (" + sorta + " ? 'mdi-arrow-up' : 'mdi-arrow-down')"
                                " : 'mdi-unfold-more-horizontal')",
                                size="x-small", classes="ml-1",
                            )
                with html.Tbody():
                    with html.Tr(
                        v_for=("(it, idx) in " + sorted_items_expr,),
                        key=("it.key",),
                    ):
                        with html.Td(
                            style="text-align: start; padding: 4px 8px;"
                            " border-bottom: 1px solid rgba(0,0,0,0.06); font-weight: 500;"
                            " white-space: nowrap; cursor: move;",
                            raw_attrs=[
                                # Drag-source: stash this item's key on the drag event.
                                ':draggable="true"',
                                '@dragstart="(e) => e.dataTransfer.setData(\'text/plain\', it.key)"',
                                '@dragover.prevent=""',
                                # On drop: build the new order with the dropped item moved
                                # before this Td's item. The order is sourced from the
                                # current display list (sorted_items_expr) and written back
                                # to the order state var.
                                '@drop="(e) => { const src = e.dataTransfer.getData(\'text/plain\');'
                                ' if (!src || src === it.key) return;'
                                ' const keys = (' + sorted_items_expr + ').map(x => x.key);'
                                ' const filtered = keys.filter(k => k !== src);'
                                ' const idx2 = filtered.indexOf(it.key);'
                                ' filtered.splice(idx2, 0, src);'
                                ' ' + self.order_var + ' = filtered; }"',
                            ],
                        ):
                            with html.Div(classes="d-inline-flex align-center"):
                                html.Span(
                                    "{{ it.column_label || it.key }}",
                                    classes="mr-1",
                                )
                                # Same distribution-profile chip as
                                # Layout A; expression duplicated rather
                                # than factored so each VChip sits in
                                # its own v_for scope (`it` differs).
                                vuetify3.VChip(
                                    "{{ it.profile === 'symmetric' ? 'sym'"
                                    "    : it.profile === 'skewed_right' ? '↦ skew'"
                                    "    : it.profile === 'skewed_left' ? '↤ skew'"
                                    "    : it.profile === 'heavy_tail' ? 'heavy'"
                                    "    : '' }}",
                                    v_if=("it.profile",),
                                    size="x-small", variant="tonal",
                                    color=(
                                        "it.profile === 'heavy_tail' ? 'purple'"
                                        "  : it.profile === 'symmetric' ? 'green'"
                                        "  : 'orange'",
                                    ),
                                    title=(
                                        "it.profile === 'symmetric' ? 'Symmetric distribution'"
                                        "  : it.profile === 'heavy_tail' ? 'Heavy-tailed (excess kurtosis > 3)'"
                                        "  : it.profile === 'skewed_right' ? 'Right-skewed (skewness >= 0.5)'"
                                        "  : it.profile === 'skewed_left' ? 'Left-skewed (skewness <= -0.5)'"
                                        "  : ''",
                                    ),
                                )
                        # Same annotation tag + Δ chip pattern as
                        # Layout A. `idx` is the outer-loop row
                        # index (defined on the Tr above), `m.k` is
                        # the inner-loop metric key.
                        ann_tag_b = (
                            "((" + self.annotations_var + " || {})[m.k] || {})[idx]"
                        )
                        delta_b = (
                            "(((" + self.annotations_var + " || {})['_deltas'] || {})[m.k] || {})[idx]"
                        )
                        with html.Td(
                            v_for=("m in " + visible_metrics_expr,),
                            key=("m.k",),
                            style="text-align: end; padding: 4px 8px;"
                            " border-bottom: 1px solid rgba(0,0,0,0.06);"
                            " font-variant-numeric: tabular-nums;"
                            " white-space: nowrap;",
                            raw_attrs=[
                                ':class="{'
                                " 'cmp-cell-min': " + ann_tag_b + " === 'min',"
                                " 'cmp-cell-max': " + ann_tag_b + " === 'max',"
                                " 'cmp-cell-pos': " + ann_tag_b + " === 'pos',"
                                " 'cmp-cell-neg': " + ann_tag_b + " === 'neg',"
                                " 'cmp-cell-eq': " + ann_tag_b + " === 'eq'"
                                ' }"',
                            ],
                        ):
                            html.Span(
                                "{{ ((it.row||{})[m.k] == null"
                                "    ? '-'"
                                "    : Number.isInteger((it.row||{})[m.k])"
                                "      ? (it.row||{})[m.k].toString()"
                                "      : Number((it.row||{})[m.k]).toFixed(3)) }}",
                            )
                            # Arrow span (vivid green/red/grey),
                            # mirrors layout A's pattern.
                            html.Span(
                                "{{ " + delta_b + ".abs > 0 ? '↑' : ("
                                + delta_b + ".abs < 0 ? '↓' : '=') }}",
                                v_if=(self.baseline_var + " && "
                                      + delta_b,),
                                style=(
                                    "({ color: " + delta_b + ".abs > 0 ? '#1b5e20'"
                                    " : (" + delta_b + ".abs < 0 ? '#b71c1c' : '#616161'),"
                                    " fontWeight: 700, fontSize: '1.15em',"
                                    " marginLeft: '4px' })",
                                ),
                            )
                            html.Span(
                                "{{ ("
                                + delta_b + " ? "
                                "(" + delta_b + ".abs.toFixed(3) +"
                                " (" + delta_b + ".rel != null"
                                "    ? ' | ' + " + delta_b + ".rel.toFixed(1) + '%'"
                                "    : ''))"
                                " : '') }}",
                                v_if=(self.baseline_var,),
                                classes="cmp-delta",
                            )
