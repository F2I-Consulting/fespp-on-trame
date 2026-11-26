# trame-fespp-compare

The Statistics view (`compare` in the code): the user builds one free selection
of properties (any kind, any grid or well, realization and time step chosen per
row) and reads it, under one tab per PWLS kind, at once:

- **The matrix** — items × metrics, a kind's own block: every cell is annotated
  against the kind's baseline, the yellow row (`pos` / `neg` / `eq`), with its
  difference to it under the cell. Click a column header to sort — a metric,
  a count (Total count included) or the Representation, by its name — choose the
  visible metrics (checkboxes + the Central tendency /
  Percentiles / Spread / Shape / All presets), copy it as CSV (client-side).
- **The distributions**, below at the left — the rows of the kind as overlaid
  histograms; the shape (Bars / Line / Curve), Bins, Log Y, Cumulative and the
  normalisation are its options bar, the kit's `fp-hist-options` in its compact
  form; a chip says why a row could not be drawn. No count over the chart: the
  table above says it.
- **The cross-plot**, below at the right — two items of the kind, X and Y picked
  over the chart; a note says what it leaves out, or that X and Y are the same
  row; the toolbar and the charts are the host's cross-plot, mounted bare under
  this panel's bar.

The rows of the matrix ARE the selection: one row per entry, its title in the
Property column, its representation in the next (`support_label`, else `rep`), a
Realization and a Time step column with a select on the row when
the property has them (its first line says what the row reads while it names
nothing), a pin beside the name that keeps a copy of the row as read now (its
coordinates fixed, an unpin on the copy), and a right-click
menu for the acts of the row — Set as baseline (the row of its
kind, held by the entry's uid), pin / unpin, Pin all time steps, Pin all
realizations, Unpin all, Remove from stats; an act the property cannot take is
greyed with why.

Under an item come the rows that follow it (`row.support`, `row.support_label`,
`row.follows`): the property on a part of its grid, or on what a 3D view draws of
it. A row that follows has its `support_label` in the Representation column, no
picker, no pin, and its menu refuses the rest with why: `remove` on a part's row
("Take this part out"), disabled on a view's row, which goes with what the view
shows. The block's count and the tab's do not count them.

A block's columns: the counts first; `Sum` unless `sum_meaningful` is false, a row
whose own `sum_meaningful` is false writing a dash there, read against no baseline;
`Mean (L)` only with `has_length`; a `Unit` column when `uom_mixed`; each header
carrying its unit at its power (`Variance (m²)`). On the row's hover, its `note`.

Pure display + one `set` event (`["tab", kind]`, `["pin", id]`,
`["pin_all", [id, "ts"]]`, `["sort", [column, asc]]` — a metric key, `"Total"` or
`"Representation"`, as `engine/compare_matrix.SORT_KEYS` lists them —, ...); the Plotly figures and
the cross-plot toolbar are put in the `dist` and `xplot` slots by the host; every
value is computed in `engine/compare_dispatch` and `engine/compare_rows`.

The panel wears the frame (`fp-panel`): the kind tabs are a row of buttons (as many
as kinds, so not a segmented control), Metrics the action, Copy CSV the export
(`statistics_<date>.csv` as the server names it, `statistics.csv` when it names none),
the host's tree button last. What the panel did not do is a band under the bar:
`note` with `noteSeverity` (`warn` | `error`) and, for an error, `noteNext` — the next
step, said apart (R10). Closing the band emits `set(["note", ""])`.

`ComparePanel.vue` holds the bar, the tabs, the notes band and the charts;
`CompareMatrix.vue` the legend, the blocks and the row menu; `rowActs.js` what that
menu offers on a row; `CompareRowTools.vue` a row's pin;
`CompareAxisPick.vue` where a row reads, on one axis; `metrics.js` the metrics'
order, words and CSV columns.
