# Widget: Analysis panels (statistics / distribution)

Quantitative panels driven by the **selected properties**, dockview panels.

## Scope
Per-property, not per-view. Opened as dockview panels.

## Input
- The selection of the Statistics view (`ui_compare_items`), the parts of a grid
  whose eye is open (`ui_compare_parts`), the loaded sources.
- Per-kind and per-panel options (bins, mode, log-y, normalisation, baseline row, …).

## Behaviour
- **Statistics** (kind `compare`, `widgets/compare`) — one tab per property kind,
  each at once: the matrix (min/max/mean/std/var/percentiles/skew/kurtosis/
  count/NaN, read against a baseline row), the overlaid distributions, the
  cross-plot of two of its rows. Under an item, the rows that follow it: the
  property on a part of its grid, or on what a 3D view draws of it.
- **Distribution** — Plotly histogram of ONE row (bars/line/curve, cumulative,
  normalised), at the realization or the time step the row reads; it follows that
  row unless pinned, and what a 3D view draws when opened from the view's row.
- CSV export on each.

## Reads
- The property arrays from the **shared** loaded sources, `ui_compare_items`,
  `ui_compare_parts`, `ui_distribution_contexts`, the per-kind and per-panel option
  vars.

## Writes (back-end / global)
- Their own figure / table / option state. CSV export (client download). No
  per-view writes.

## Notes / open
- These read **shared** loaded data, so a property's row is view-independent —
  they are not per-view widgets. A 3D view's row is the exception, and the
  reason it follows the view: it reads what that view draws (post cut, post
  threshold), at that view's realization and time.
