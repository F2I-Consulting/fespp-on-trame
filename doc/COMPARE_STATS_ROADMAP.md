# Compare-stats / Distribution panels — future-work roadmap

Captured after the Tier 1 feedback round (2026-06). The current
release ships the always-on baseline mode, the per-property unified
compare cart, sticky baseline column, drag-to-reorder, distribution
profile chips, Metrics-visibility menu with presets, rep-parent
prefix in the toolbar chip, and the Compare-distribution singleton
panel with bars/line/curve overlay.

This document records what was deliberately left for later. Pick
items by priority when a follow-up branch lands.

---

## Tier 2 — Visualisations comparatives (next batch)

These features extend the comparison panels with richer chart
shapes. They go primarily on the **Compare-distribution panel** for
boxplots / violins / histograms overlay, and add a heatmap / radar
visualisation on the **Compare-stats panel** as alternative views.

### 1. Boxplots + Violins on Compare-distribution

- **Why** — the current `bars / line / curve` modes give shape but
  not summary stats. Boxplots show quartiles + outliers per item
  at a glance; violins combine both.
- **Where** — extend `compute_compare_figure` in
  `distribution_dispatch.py` with two new display-mode values
  (`box`, `violin`). Plotly supports both natively
  (`go.Box`, `go.Violin`).
- **UI** — add 2 buttons in the Compare-distribution panel toolbar
  (next to the existing bars/line/curve toggle). Each maps to
  `display_mode = "box"` / `"violin"`.
- **Data path** — each cart row feeds its raw `finite_values`
  array (already produced by `_build_continuous_trace`) into one
  trace. For boxplot/violin the bin computation is skipped; Plotly
  handles the quartile / KDE math client-side.
- **Edge case** — discrete / categorical properties: hide the
  boxplot/violin buttons via `v_if=!is_discrete`. Bars + line make
  sense; box doesn't.

### 2. Heatmap visualisation on Compare-stats

- **Why** — the current Compare-stats panel renders a metric ×
  item matrix as a table. A heatmap shows the same matrix with
  colour intensity = relative magnitude, which spots patterns
  faster on bigger carts (10+ items).
- **Where** — new toggle in the Compare-stats toolbar:
  `View: table | heatmap`. When `heatmap` selected, the panel
  swaps the `<table>` for a Plotly `go.Heatmap` figure with
  metrics on Y, items on X, value = z (or z-score normalised).
- **Backend** — already half-done: `compare_matrix.highlight_annotations`
  produces the per-metric normalised intensity used by the old
  cell-level heatmap mode (dropped). Re-use that intensity to
  feed a Plotly heatmap.
- **State** — add `ui_stats_compare_view_<panel_id>` ∈
  `{"table", "heatmap"}` per panel.
- **Why distinct from Tier 1's dropped heatmap mode** — the
  per-cell heatmap painting in Tier 1 was too constrained by table
  cell semantics (text overlay vs background gradient). A dedicated
  Plotly heatmap canvas gives proper colorbar + axis labels + zoom
  + hover tooltips, which the cell-paint approach couldn't.

### 3. Radar chart visualisation on Compare-stats

- **Why** — for fingerprinting an item across N metrics at once.
  Each cart row becomes a polygon on N axes (= visible metrics);
  overlaid polygons make outliers obvious.
- **Where** — new toggle option in the same view-switcher as
  heatmap: `View: table | heatmap | radar`. Uses Plotly
  `go.Scatterpolar` (one trace per item).
- **Edge case** — radar requires comparable axis scales. Z-score
  normalise each metric before plotting (re-use the normalise path
  built for the dropped cell heatmap), else metrics with large
  magnitude dominate the polygon shape.
- **UX** — limit to ≤ 6-8 items in cart to stay readable; on
  larger carts auto-hide some traces with a chip selector.

---

## Tier 3 — Pro-statistical (deferred, doc only)

Recorded as ideas worth revisiting if power users ask for them.
Heavy lift, narrow audience. Don't pull these in without explicit
demand.

### Statistical tests

- **Student's t-test** between any two items: difference of means
  significant or not, with p-value.
- **Levene's test** for equality of variances.
- **Kolmogorov-Smirnov** for distribution shape comparison.
- **UI** — pair-select two items in the cart, click "Test", get
  a small modal showing the test name + p-value + verdict (✓ / ✗).
- **Backend** — scipy.stats imports. Add a
  `compare_matrix.run_pairwise_tests(items, baseline_key)` helper.

### Distance metrics

- **Wasserstein distance** between distributions (1D EMD).
- **KL divergence** with smoothing.
- **UI** — pairwise matrix or a "distance from baseline" column
  added to the Compare-stats table when a baseline is set.
- **Backend** — scipy.stats / scipy.spatial.

### Similarity ranking

- "Row A is 92% similar to row B" — compute via a cart-wide
  embedding (cosine on normalised metric vectors). Display as a
  sorted list under each row.
- Likely overkill but listed for completeness.

### Outlier detection

- Highlight items that are > 2σ from the cart's per-metric mean
  on N or more metrics. Adds a tag chip on the column label.
- Could re-use the distribution-profile-chip slot (currently
  shows symmetric / heavy-tail).

### Auto-suggestions

- "Cette ligne a une variance anormalement élevée" — opinionated
  threshold-driven hints in a side panel.
- High risk of saying dumb things; skip until a real use-case
  demands it.

---

## Tier 1 follow-ups (small fixes to consider)

These were noticed during the Tier 1 work but not implemented in
the same round. Easy to fold into a maintenance branch.

- **Compare-distribution panel: legend label trim** — verify the
  legend reads `real X, ts_label` only (not the property name +
  view title). The work for the Compare-stats column labels
  already did this server-side; double-check Compare-distribution
  picks it up too.

- **Drag-to-reorder visual feedback** — currently only `cursor: move`
  hints at draggability. Add a `:hover` outline or a dotted
  drag-target indicator on `dragover`.

- **Top-N replacement via "more" affordance** — the Top-N filter
  was dropped per user feedback (horizontal scroll handles
  overflow). If a user complains about overwhelming carts, consider
  a "collapse to top 5 by Mean" toggle that hides the rest behind
  an expander.

- **CSV export naming** — currently `compare.csv` for every
  download. Embed `<property_title>` in the filename so the
  browser doesn't overwrite previous downloads.

- **Sticky for Layout B (transposed)** — the sticky-left was only
  wired for Layout A (items as columns). In Layout B (items as
  rows), the metric headers go horizontally and the row labels go
  vertically. A sticky-top header + sticky-left row-label
  combination would mirror the spreadsheet feel.

---

## Out of scope (intentional cuts)

- **Advanced filtering (range / variance / quartile thresholds)** —
  overlap with sort + cart manual selection.
- **Grouping / clustering** — different workflow, deserves its
  own panel.
- **PDF report export** — CSV is enough for now; PDF adds a
  templating dependency.
- **Tooltips with mini-histograms** — every tooltip would trigger
  a compute round-trip. Not worth the latency for a tooltip.
