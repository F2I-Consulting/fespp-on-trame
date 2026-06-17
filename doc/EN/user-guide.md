# FESPP-on-Trame — User Guide

A web-based viewer for RESQML / Energistics data, built on top of the FESPP
ParaView plugin and the [Trame](https://kitware.github.io/trame/) framework.
Open EPC + H5 files in your browser, browse the data hierarchy, and render
grids, surfaces and wells in 3D.

---

## Table of Contents

- [Getting Started](#getting-started)
- [The Interface at a Glance](#the-interface-at-a-glance)
- [Loading Data](#loading-data)
- [Browsing the Trees](#browsing-the-trees)
  - [Selecting Items](#selecting-items)
  - [The Eye Icons (Visibility & Coloring)](#the-eye-icons-visibility--coloring)
  - [Active Node and Attributes Panel](#active-node-and-attributes-panel)
- [Coloring & Opacity](#coloring--opacity)
  - [Solid Color Mode](#solid-color-mode)
  - [Property (LUT/PWF) Mode](#property-lutpwf-mode)
  - [Categorical / Discrete Properties](#categorical--discrete-properties)
- [Cutting Geometry: IJK Slicers, Slice & Clip Planes](#cutting-geometry-ijk-slicers-slice--clip-planes)
- [Threshold Filter](#threshold-filter)
- [Descriptive Statistics](#descriptive-statistics)
- [Time Series](#time-series)
- [Multi-Realization Properties](#multi-realization-properties)
- [Working with Multiple Views](#working-with-multiple-views)
  - [Adding a View (Split or Empty)](#adding-a-view-split-or-empty)
  - [The Active View](#the-active-view)
  - [Per-View Visibility and Coloring](#per-view-visibility-and-coloring)
  - [Copy From View](#copy-from-view)
  - [Linking Cameras](#linking-cameras)
  - [Diff View](#diff-view)
- [General Display Settings](#general-display-settings)
  - [Vertical Exaggeration (Z scale)](#vertical-exaggeration-z-scale)
  - [Load Mode (Auto / Manual)](#load-mode-auto--manual)
  - [Tree Hierarchy](#tree-hierarchy)
  - [Background Color](#background-color)
- [Camera Controls](#camera-controls)
- [Log Panel](#log-panel)
- [Tips & Limits](#tips--limits)

---

## Getting Started

The application is served as a single-page web app. Open the URL provided
by your administrator (e.g. `http://<server>:9500/`). Each browser tab is
its own session — closing the tab discards your selection and uploaded
files. To deploy your own instance, see [`elba.md`](elba.md) for the
container-based setup.

---

## The Interface at a Glance

| Region | What it does |
|--------|--------------|
| **Top toolbar** | Application title, **Import data** button, **Load** button (manual mode only). |
| **Left drawer** | Three tabs (`Reservoir`, `Surface`, `Well`) each with a **Data Explorer** tree and an **Attributes** panel. Below: **General Display Settings**. |
| **Main view** | The 3D render with floating camera controls (top-left) and time controls (top-center, when applicable). |
| **Bottom panel** | Collapsible VTK log panel (visible only when warnings/errors are emitted). |

Drag the right edge of the drawer to resize it.

---

## Loading Data

1. Click **Import data** in the toolbar.
2. Drop or pick `.epc` and matching `.h5` files (both are required). You
   can also paste an OSDU URL or connect to an ETP/OSDU server from the
   same dialog.
3. Wait for the upload progress bar to complete. The trees in the drawer
   then populate with whatever the file contains.

> **Note:** The session keeps your data in a temporary directory that is
> wiped when the last client disconnects.

---

## Browsing the Trees

Each tab shows a different kind of object:

- **Reservoir** — IJK grids and unstructured grids.
- **Surface** — 2D grids, point sets, polylines, triangulated sets.
- **Well** — wellbore trajectories, frames, channels, markers,
  completions and perforations.

Trees are independent: you can have items selected and visible in
several tabs at once.

Within each tree the items are sorted **alphabetically at every level**
(the hierarchy is preserved — only siblings are ordered). Sorting is
case- and accent-insensitive and number-aware, so `Grid2` comes before
`Grid10`.

### Selecting Items

Each row has a checkbox on the left. Checking a row tells FESPP to
**load** that item.

- Checking a **grouping** node (`Wellbore`, `Collection`, `Partial`, and
  in non-Flat hierarchy modes also `Feature` / `Interpretation`)
  auto-checks every descendant.
- Checking a **representation** (a grid, a surface, a trajectory…) loads
  *only* that geometry — its properties stay un-checked unless you tick
  them yourself.
- Checking a **WellboreChannel** or **WellboreMarker** auto-checks the
  parent wellbore's `WellboreTrajectory` (the geometry the channel /
  marker is anchored to).

A small **colored chip** appears next to a representation row once it's
loaded:
- a **rainbow** chip means the rep is currently colored by a property
  array,
- a **solid colored dot** means the rep is in solid color mode.

### The Eye Icons (Visibility & Coloring)

Two flavors of eye appear on the right of loaded rows:

| Icon | Where | Meaning |
|------|-------|---------|
| Blue **eye** / grey **eye-closed** | Next to each loaded representation | Toggle visibility — open eye = rep is shown in the 3D view, closed eye = hidden but still loaded. |
| Purple **eye** / grey **eye-closed** | Next to each loaded data array (Property, TimeSeries, MultiRealization, …) | Picks which array currently colors the parent representation. At most **one** open eye per rep — opening one closes the others. All closed → the rep falls back to its solid color. |

When you check a new property, its eye automatically opens (and the
previous active eye on the same rep closes). Un-checking the active
property unloads it and the rep falls back to solid color.

### Active Node and Attributes Panel

Click the **label** of a row (not the checkbox or the eye) to make it
the *active* node. The right-hand **Attributes** panel reflects the
active node:

- Active = a representation → solid color picker.
- Active = a data array → that array's LUT / PWF editor (continuous
  arrays) or per-category color list (discrete / categorical).

Active state is purely a UI concept — it does not change what's loaded
or what's currently visible.

> **A property must be checked to become active.** Clicking the label of
> a property whose checkbox is unchecked does nothing — the Attributes
> panel stays on whatever was active before. Check the property first
> (which loads it), then click its label to edit its colours. A
> representation or grouping node still activates when any of its
> children is checked.

---

## Coloring & Opacity

The **Colors & Opacity** panel under each tab's *Attributes* card is
driven by the active node's type.

### Solid Color Mode

If the active node is a representation, the panel shows a color picker
with alpha. Each rep gets a unique default color when first loaded;
pick a new RGBA to change the diffuse color and opacity. The setting is
remembered per rep — reopen the same node later and the color reappears.

The solid color is what you see when no data array is active on the rep
(all dataArray eyes closed).

### Property (LUT/PWF) Mode

If the active node is a continuous data array, the panel shows the
classic LUT/PWF editor with a color gradient and an opacity curve. You
can:

- Drag stops to change colors and opacities.
- Click on the gradient to insert new stops.
- Edit the scalar range by typing values in the min/max fields.
- The NaN color is preserved between activations.

By default a freshly-activated property has **flat opacity 1** across
the whole value range (the grid is fully opaque) and **NaN cells are
fully transparent** — cells with no value (inactive grid cells,
uncovered partial properties, empty time-series steps) simply don't
render. The two are independent: raise the NaN alpha in the NaN-color
picker to make missing data visible again, and reshape the opacity
curve for valid values without affecting the NaN handling.

The LUT applies whenever the eye is open on the array. When the eye is
closed you can still tweak the LUT (e.g. to prepare it before re-opening
the eye).

For a **multi-realization property** the gradient shown matches the
LUT of the **target view's currently-picked realization** (the picker
in the *Attributes* card header). Switching the target view or the
realization re-loads the COE to reflect the LUT actually applied in
that view.

**Per-view colour isolation.** Each render view owns its own
colour / opacity transfer function for every property — editing the
COE in one view never bleeds into another, even on plain
single-realization properties. Duplicating a view (the *Copy view*
button) replicates the source view's gradient onto the new view as a
starting point, after which the two evolve independently.

### Categorical / Discrete Properties

For `DiscreteProperty` and `CategoricalProperty`, the panel switches
to a list of category-specific color/opacity pickers (one row per
distinct value). The list is sorted by value and you can edit each cell
independently.

---

## Cutting Geometry: IJK Slicers, Slice & Clip Planes

The **Slicers** card in the Reservoir attributes panel hosts three
ways to cut the active representation. They can be combined freely.

**IJK tab** *(IJK grids only)*: axis-aligned crop along the grid's
own i/j/k indices.

- Toggle between **Range** (volume crop, single bounding box per axis)
  and **Slice** mode (one or more individual planes per axis).
- In Slice mode each axis can hold several slicers (use **+** / **−**
  to add / remove) with independent positions and visibility eyes.
- An eye next to "Volume" controls whether the cropped volume is
  rendered in Range mode.

**Slice tab** *(every rep type)*: a single arbitrary axis-aligned
plane that replaces the rep with its 2D cross-section. Switch the
normal axis (X / Y / Z), drag the offset slider, or click **Edit 3D**
to grab the plane interactively in the 3D view. Only one widget
(slice or clip) can be in edit mode at a time.

**Clip tab** *(every rep type)*: same axis + offset controls as
Slice, plus an **Invert side** toggle that flips which half is kept.
Clip can be combined with Slice and with the IJK slicers.

All three concerns are per-view (see [Working with Multiple
Views](#working-with-multiple-views)) — editing them in one panel
does not touch any other view.

When you click a property eye, ColorBy is applied to whichever cut
output is currently visible (IJK slicers / volume crop, slice
plane, clip plane, or the full rep when none is enabled).

---

## Threshold Filter

The **Thresholds** card lets you filter a representation's cells by
a property's value. Each threshold appears as a row in the chain
(stacked filters union their kept ranges); the **+** buttons add a
new root threshold (`mdi-set-all`) or chain a child under an
existing one (`mdi-set-center` → intersection); the eye toggles the
threshold's contribution; the trash removes it.

The slider that drives a threshold row adapts to the property's
kind:

- **Continuous property** — a regular range slider with two thumbs
  over the value range. Drag both thumbs to bracket the cells you
  want to keep.
- **Discrete property** (integer values) — same range slider but
  snapped to integer steps. The thumb labels show the current
  integer bound so you can see exactly which values are included.
- **Categorical property** (named categories) — range slider with
  one labeled tick per category (read from the LUT annotations
  populated by the Color Editor). The thumbs snap between
  categories; the cells whose category falls within the picked
  range are kept.

For multi-realization properties, the threshold binds to the
realization currently picked in the active view. Switching
realizations later does **not** retarget existing thresholds —
they keep filtering on the realization they were created with.

---

## Descriptive Statistics

Statistics live in a **floating overlay** above the multi-view —
not docked into the grid, not in the drawer. Open it via the
`mdi-chart-box-outline` button in the top toolbar (left of the
settings cog), or by pinning a property from the tree. The
floating window appears anchored near the top-left of the
content area at 1400×450, and you can:

- **Move** it by dragging the empty area to the right of the
  tab title.
- **Resize** it from any edge / corner (8 handles).
- **Close** it with the `×` on the tab.
- **Re-dock** it into the grid by `Shift+drag` the tab title
  into one of the dock zones (top / bottom / left / right of
  any panel) — same gesture dockview uses everywhere.
- **Minimize** to a tabstrip-sized chip (height + width both
  shrink, just enough for the tab title + the three chrome
  buttons) via the `mdi-window-minimize` button. Useful when you
  want to keep the panel mounted (so reopening is instant) but
  free the screen behind it. Click `mdi-window-restore` to bring
  it back at its prior position and size.
- **Maximize** the floating window to cover the entire
  multi-view content area via the `mdi-window-maximize` button.
  Useful for inspecting the stats across many views at once.
  Click again (`mdi-window-restore`) to fall back to its prior
  floating size. Minimize and Maximize are mutually exclusive —
  clicking one cancels the other automatically.

While minimized OR maximized the resize handles are disabled so
the collapsed/expanded shell can't be dragged by mistake (that
would rewrite the inline bounds and make Restore land at the
wrong size).

Re-clicking the toolbar button while Stats is open **closes**
the floating window — the button is a pure open/close toggle.
To raise an obscured floating window above its peers, click
twice (close, then reopen): the freshly-added window lands at
the top of dockview's z-index stack. Pinned properties + their
per-Original snapshots live in app state independent of the
window, so closing it and reopening later restores every card
unchanged.

### Pinning a property

Each property row in the tree carries a small chart icon
(`mdi-chart-box-outline`) **once you've ticked the property's
checkbox** — until the property is selected for loading, its
stats toggle stays hidden. Click the chart icon to **pin** the
property: the Stats tab opens (if not already open) and a new
card appears for that property. The icon flips to `mdi-chart-box`
while the property is pinned. Click again (or the `×` in the
card header) to unpin.

You can pin several properties side by side to compare them.

### Rows inside each table

Each pinned property's card holds one stats table. Columns:

- **Cmp** *(MR / TS cards only)* — ⊕ icon per row to add the row
  to that property's **comparison cart** (flips to ✓ once added).
  Plain Continuous cards hide the column entirely — a single-row
  card has nothing to compare against.
- **Source** — what the row is computed on. For an Original row
  this is just the property name; for a per-view row it's
  `<property> On <View N>`. An `mdi-eye-outline` icon sits next
  to the label on every row — clicking it opens a floating
  **Distribution panel** for that row (binned histogram for
  continuous arrays, per-category bars for discrete /
  categorical; see [Distribution (Histogram)](#distribution-histogram)).
- **Realization Index** *(MR / MR+TS properties only)* — the
  realization the row uses. Default Original row gets an editable
  dropdown; Custom (pinned) and View rows show the static value.
- **Time Step** *(TS / MR+TS properties only)* — the time-step
  the row was computed at, formatted as `YYYY-MM-DD` (time-of-day
  is dropped — reservoir time-series are dated to the day in
  practice). Same dropdown vs static rule as Realization Index.
- **Value count** — cells with a finite numeric value
  (= what the stats below were computed on; NaN cells are dropped
  upstream).
- **No value count** — cells whose value couldn't be evaluated (NaN).
  `Value count + No value count = total cells`.
- Numeric metrics from `vtkDescriptiveStatistics`: Min, Max, Mean,
  Std Dev, Variance, Sum, Skewness, Kurtosis, M2 / M3 / M4 (raw
  central moments — see the dev guide if you want to re-derive
  Variance / Skewness / Kurtosis under another convention).
- **Q1 / Median / Q3** — the three interquartile-range markers,
  computed server-side via `numpy.percentile([25, 50, 75])` on the
  same NaN-stripped value array the rest of the metrics ride on,
  so the cart-vs-histogram numbers stay coherent.

The rows themselves:

- **1+ Original rows** — stats on the rep's unfiltered VTK array,
  independent of any view's slicer / clip / threshold. The
  **Default** row tracks the property's auto-resolved real / TS;
  click its **pin icon** in the Source column to snapshot the
  current `(real, TS)` into a new editable **Custom** row, then
  the Default resets to auto so you can keep iterating. Each
  Custom row carries the `×` icon to remove it.
- **One row per view** that's currently coloring by this property
  — stats on what each view actually shows (post-slicer /
  post-clip / post-threshold). The row picks up the realization
  currently chosen in that view, the time-step from its per-view
  TimeControl, and recomputes whenever the view's slicer / clip
  / threshold or realization changes.

**Per-property comparison cart (MR / TS only).** Each card whose
property carries a Multi-Realization or Time-Series axis grows
the single **Cmp** column above and a **Compare** button in the
card header — both gated to MR / TS cards. Tick rows in the
`Cmp` column, then click **Compare** in the card header (becomes
enabled at ≥ 2 ticked rows) to open the floating
**Compare-stats panel** (kind `stats_compare`) bound to that
property. Carts are scoped per property: the cart for property
A is physically separate from property B's, so mixing properties
is structurally impossible (no rejection snackbar needed). Plain
Continuous properties without an MR / TS axis hide both the
column and the button — a one-row card has nothing meaningful
to compare.

**Compare-stats panel toolbar.** The floating Compare-stats
panel is a **singleton per property** — the **Compare** button
opens or focuses the same panel for that property; the cart's
tick / untick events live-update the panel in place. Its
toolbar carries, left to right:

1. **Live badge** — `<property title> — N rows` chip showing
   which property is in scope and how big the cart is. Updates
   on every tick / untick without re-render.
2. **Baseline picker (always on).** A VSelect listing every
   cart row, with a `(no baseline)` sentinel at the head of
   the list as the default. Picking a row switches the matrix
   into **Δ comparison mode**: each cell paints green
   (`cmp-cell-pos`) when above the baseline, red
   (`cmp-cell-neg`) when below, with an inline **Δ chip**
   (`↑ / ↓ / =` + absolute delta + relative `%` when the
   baseline isn't zero) right next to the value. Leaving the
   picker at `(no baseline)` falls back to **extrema** shading
   (blue `cmp-cell-min` for the per-metric min, orange
   `cmp-cell-max` for the per-metric max) so the user still
   sees a useful visual cue. No separate highlight-mode
   toggle, no Z-score / heatmap / Top N controls — the
   baseline picker IS the highlight switch.
3. **Visual baseline marker.** The picked baseline row /
   column is tinted indigo with a **BASELINE** chip on its
   header so the reference is unmistakable at a glance. On
   **layout A** (rows = metrics, columns = items) the
   baseline column is **sticky-left** right after the Metric
   label column, so it stays anchored on the left edge of the
   scroll area while the user scrolls horizontally through the
   other rows. CSS classes: `cmp-baseline-chip` (the chip),
   `cmp-baseline-anchor-bg` (the indigo cell tint),
   `cmp-baseline-anchor-bar` (the sticky-left positioning).
4. **Metrics visibility menu** — multi-select dropdown to drop
   noisy metrics (`M2`, `M3`, `M4`, `Variance`, `Sum`,
   `Skewness`, `Kurtosis`, …) from both the visible matrix and
   the CSV export. Defaults to "all visible"; presets at the
   top of the menu (*Central tendency* / *Spread* / *Shape* /
   *All*) prepopulate the list in one click.
5. **Transpose icon** (`mdi-table-pivot`, with a rotate-variant
   fallback when the icon font is missing) — flip rows ↔
   columns so metrics become column headers (clickable to
   sort in layout B).
6. **Show distributions** — opens or focuses the singleton
   **Compare-distribution** floating panel for the SAME cart
   (same `array_path`), showing every cart row as an overlay
   trace. Subsequent clicks on this button re-focus the same
   panel; the cart's tick / untick events live-update the
   overlay in place. When the cart drops below 2 rows the
   distribution panel stays mounted and shows a *"Add 2 or
   more rows..."* placeholder — close via the tab's `×` to
   unregister.
7. **Download CSV** — exports the comparison matrix as CSV
   (rows × visible metrics, projection from the visibility
   menu).

**Drag-to-reorder.** Any column header (layout A) or row
header (layout B) is draggable: pick one up and drop it on
another header to move it before that one. The new order
persists in the panel's `ui_stats_compare_order_<panel_id>`
state var — it survives cart edits (new rows append at the
end) and refreshes from sort / baseline pinning.

**Distribution profile chip next to each item header.** Each
cart row's header still carries a small chip derived from its
Skewness + Kurtosis: `sym` (symmetric), `↦ skew` (right-
skewed), `↤ skew` (left-skewed), or `heavy` (heavy-tailed,
excess kurtosis > 3). Hover the chip for the threshold
reminder; the chip is hidden when Skewness / Kurtosis are
missing.

**Rep parent prefix.** Card headers and the Compare-stats
column labels carry a dimmed `<RepTitle> /` prefix when the
property's enclosing representation has a title — so two reps
sharing the same property name (e.g. `VOIL` on two different
grids) stay tellable apart in the card header AND in the
matrix's per-item column labels.

The Compare-stats panel is a regular dockview floating window:
move it by dragging the tabstrip, resize from any edge, close
via the tab `×`, re-dock with `Shift+drag`. Closing the tab
unregisters the panel — the next click on **Compare** for that
property spawns a fresh one (its toolbar settings reset to
defaults).

What you see exactly:

- **Anchored on what's rendered** — the stats are computed on the
  geometry currently visible in the active view. If a slice / clip
  / IJK slicer or threshold is active, the stats reflect the
  surviving cells only (not the full rep).
- **One row at a time** — for a multi-realization property the row
  shows the realization currently picked in the active view (via
  the per-view RealizationPicker overlay). Switch realizations to
  see another row.
- **NaN values are excluded** before the stats are computed, so
  Std Dev, Skewness, Kurtosis stay meaningful instead of degrading
  to `–` when the array contains a few invalid cells.
- **Time-aware** — scrubbing the timeline updates the stats live
  for the active view, both with the global TimeControl and with
  per-view TimeControls. The Time Step labels (both in the TC
  chip and in the stats Time Step column) show the date only
  (`YYYY-MM-DD`); the time-of-day part of the underlying ISO
  timestamp is hidden because reservoir TS are dated to the day.
- **Discrete / categorical properties** currently surface the
  same numeric metrics as continuous arrays — that's *not* a
  meaningful stat (mean of unordered categories has no semantics).
  A category-histogram view is planned as a follow-up.

The panel is hidden when no property is active or when the active
geometry has nothing to compute on.

**Recent UX tweaks worth knowing:** numeric cells now display to
three decimal places (`toFixed(3)`) so wide-magnitude metrics stay
legible without horizontal scrolling. The **Realization Index**
and **Time Step** VSelects on the Default Original row no longer
carry the clearable `×` — they default to the first available
real / TS instead of being clearable to "nothing", since a
missing index just makes the row uncomputable. Both selects are
rendered **compact** so they fit comfortably even when many
columns share the same row; clicking the dropdown opens a menu
that **widens up to 360 px** so long Time-Step labels stay
readable. The per-row distribution entry-point is the
`mdi-eye-outline` icon next to the Source label (no separate
column), keeping the table narrow when neither MR nor TS axes
demand a Cmp column.

---

## Distribution (Histogram)

Each row in the **Descriptive Statistics** tables carries an
`mdi-eye-outline` icon **next to the Source label** (no
dedicated column — keeps the table narrow on plain Continuous
cards). Click it to open a **floating Distribution panel**
showing that row's value distribution — binned histogram for
continuous properties (50 bins by default), per-category bars
for discrete / categorical. The figure title mirrors the row's
Source cell with the (real, ts) suffix when relevant. The
X-axis is labelled `<Property name> (<unit>)` when the unit of
measure is available on the tree assembly, else just
`<Property name>` alone (today the FESPP-built `vtkDataAssembly`
does not surface UOM yet, so you'll see the bare name — see the
RESQML / FESPP note in the dev guide for what's needed C++-side
to light this up).

**Multi-instance:** every eye-outline click opens a NEW
Distribution panel — your previous histograms aren't replaced,
so you can lay several distributions side by side. Close one
with its `×`, move it by dragging the title bar, resize from
any edge / corner, re-dock into the dockview grid with
`Shift+drag` the tab title. Same chrome as Stats and render
views.

**Multi-trace overlay (singleton).** Tick the rows you want to
overlay in the property card's **Cmp** column, click **Compare**
in the card header to open the Compare-stats floating panel,
then click **Show distributions** in that panel's toolbar. The
toolbar button opens or focuses the singleton
**Compare-distribution** floating panel for the same cart (per
property): subsequent tick / untick of the `Cmp` column
live-updates both the matrix and the distribution overlay in
place. Cart < 2 keeps the distribution panel mounted with the
placeholder *"Add 2 or more rows..."* — useful when you want to
leave the panel open and incrementally build the overlay row by
row. Because the cart is per-property, legend entries are
trimmed to just `real N, ts <label>` (property name is
redundant). For property+TS rows the legend reads `ts <label>`
only; for MR+TS rows you get both axes. Click any legend entry
to toggle that trace's visibility — native Plotly, no server
round-trip.

**Per-panel controls** — each Distribution panel carries a compact
toolbar above the chart:

- **Shape** — three buttons cycle between `bars` (histogram),
  `line` (step plot, easier on dense bin counts) and `curve`
  (smoothed spline through bin centers, visually close to a KDE).
- **Bins** — slider 5 → 500 (continuous properties only; discrete
  / categorical always show one bar per category).
- **log Y** — switch the Y-axis to a logarithmic scale. Useful when
  one bin dominates (porosity zero in clay layers, etc.).
- **stats** — overlay vertical lines for mean (solid teal),
  median (dashed indigo), Q1 / Q3 (dotted grey) with text labels
  on top. Single-row panels only — compare panels hide this
  control since per-row overlays clutter the figure fast.
- **cumul** — switch to cumulative distribution (the heights
  become the running sum). Reads as "fraction of cells below this
  value" when combined with the `p` normalisation.
- **n / dens / p** — heights normalisation. `n` keeps raw counts,
  `dens` rescales so the integral is 1 (compare distributions with
  different sample sizes), `p` rescales so the bins sum to 1 (read
  bin heights as probabilities).
- **Kept / total badge** — top-right amber chip showing how many
  cells contributed to the histogram and how many were dropped as
  NaN. Hides when total is zero.
- **Download** — `mdi-download` button exports the current bins
  as CSV (`center, height, width` columns; one column triplet per
  trace in compare mode).

All toolbar mutations recompute the figure server-side and push
fresh bins + meta + CSV in the same flush, so the chart, the badge
and the download link stay in lockstep.

---

## Time Series

`TimeSeries` and `MultiRealizationTimeSeries` nodes are leaves. The
underlying property kind (Continuous / Discrete / Categorical) is
preserved on the node icon.

Activate one and the **Time controls** appear at the top of the 3D view
(playback bar with play/pause, step-by-step buttons and a timeline).
Time labels follow the time-series metadata.

Not every property has a value at every time step (some carry a single
step, e.g. a static region). Scrubbing onto a step where the active
property has no data shows the grid as **fully transparent** (every
cell is NaN-filled) — a clear "no data at this step" signal — and the
data reappears when you scrub back to a step that has values.

---

## Multi-Realization Properties

`MultiRealization` and `MultiRealizationTimeSeries` collapse a whole
realization stack into a single tree leaf. Loading one activates
every available realization as a distinct array on the source —
each render view then independently picks which realization to
display.

A **Realization picker** appears at the top of every view actively
colored by an MR property (toggleable via the layers icon in the
view's toolbar). The first realization is auto-selected the first
time an MR property is activated in a view; click the slider /
arrows to scrub through the others. Views can show different
realizations of the same property side by side.

A **global Realization picker** in the top toolbar appears when two
or more views render MR properties. Picking an index there fans the
choice out to every view that currently colors by that property —
useful for "set realization N everywhere".

Thresholds added on an MR property bind to a specific realization
(the one currently picked in that view) — switching realizations
later won't move the existing threshold.

The LUT range can be **locked** so the color mapping stays
comparable between realizations.

---

## Working with Multiple Views

FESPP-on-Trame can render several independent views of the same data
side by side. Each view owns its own visibility, coloring, slicers,
slice plane, clip plane, threshold chain, realization choices and
camera. Splitting a view inherits the source's state once; from
then on each view diverges independently.

### Adding a View (Split or Empty)

Each render panel carries three icons in its tab row:

| Icon | Action |
|------|--------|
| Vertical split (▢│▢) | Add a new view to the **right** of this one. |
| Horizontal split (▢／▢) | Add a new view **below** this one. |
| Cog | Rename this view / settings. |

A modal opens with three content choices for the new view:

- **Copy "{this view}" scene** — replicates the source view's full
  state (visibility, coloring, slicers, slice / clip, threshold
  chain, realization picks). The new view starts as a clone, then
  diverges on subsequent edits.
- **Empty scene** — no rep is visible. Every loaded rep appears
  with a closed eye in the tree's per-view chip row; click an eye
  to incrementally fill the empty view.
- **Diff scene (A − B)** — see [Diff View](#diff-view).

**Floating a view.** Any docked view can be promoted to a
**floating window** that overlays the rest of the multi-view:
hold `Shift` and drag the view's tab title into empty space. The
floating window has the same chrome as the Stats overlay (drop
shadow, 8 resize handles, drag-by-tabstrip). Camera, displays,
slicers, threshold chain and color editor are all preserved
across the transition — dockview keeps the panel instance
mounted, so the 3D content doesn't reset. Drag the floating
title back onto another tab's dock zone (without `Shift`) to
re-dock it. The same gesture pair works on the Stats overlay.

### The Active View

The currently-focused view is highlighted with a blue inset border
and an **ACTIVE** pill. Click anywhere in another view's body, or
on its tab, to switch focus.

By default the drawer's **Attributes** card edits the **active
view's** state — slice, clip, threshold chain, IJK slicers and
color editor all target whichever view has focus. A small **pin**
toggle in the Attributes toolbar lets you pin the panels to a
specific view instead: pick that view from the dropdown that
appears next to the pin, and the panels keep editing it even when
you click into another view's 3D area. Click the pin again to
revert to following the active view. If the pinned view is closed
the panels automatically revert to follow-active.

### Per-View Visibility and Coloring

Every loaded representation row in the tree carries a *row of eye
chips* — one per render view. Each chip shows whether the rep is
shown in that specific view; click to toggle. Closing a rep in view
A does not affect view B.

Property eye chips work the same way: clicking a property's chip in
view A applies ColorBy on that property in view A only. Each view
keeps its own ColorBy mapping independently.

### Copy From View

The Threshold panel, Slice panel, Clip panel, and IJK Slicers panel
each have a small **copy** icon in their header. Clicking it opens
a dropdown listing every other render view; picking one snapshots
that view's state for **just this concern** and applies it to the
active view. After the copy both views still own independent state
— a subsequent edit in either won't propagate.

The same mechanism is used when you choose "Copy scene" while
splitting a view (it just snapshots all concerns at once).

### Linking Cameras

Each view's camera toolbar (top-left of the 3D area) carries a
**magnet** icon. Click it to open a menu of other views: tick the
ones whose camera should follow this view. The link is symmetrical
and fires only on mouse release (no per-frame sync, so interactive
rotation stays responsive).

### Diff View

The Diff scene is a singleton view dedicated to showing the
A − B difference between two properties of the same grid. The
view opens with an A/B selection form; pick two properties, click
**Compute**, and the resulting field renders in the same way as a
regular property (LUT, color editor, palette). Editing the LUT or
the inputs uses the small action buttons that appear in the
top-left corner of the diff panel after the first compute.

---

## General Display Settings

The bottom card of the drawer hosts global options.

### Vertical Exaggeration (Z scale)

Drag the Z scale field to apply the same vertical exaggeration to every
representation. Click **Apply** to push the change. Useful for thin
geological layers where a 1:1 scale flattens too much detail.

### Load Mode (Auto / Manual)

- **Auto** *(default)* — every checkbox toggle pushes immediately to
  the ParaView pipeline, so the 3D view updates as you click.
- **Manual** — checkbox toggles only update the selection state; the
  3D view stays put. Click the toolbar **Load** button (visible only
  in manual mode) to push everything in one go. Handy when you want
  to stage a large multi-tab selection without paying a load cost on
  every click.

> **Note:** Load mode controls **loading** (data presence in ParaView).
> It does not control **visibility** — the eye icons on each loaded
> row do that, independently.

### Tree Hierarchy

Three layouts let you re-arrange how representations are grouped in the
trees:

- **Flat** *(default)* — the legacy layout: representations directly
  under root, properties under their rep.
- **By Interpretation** — representations are grouped under their
  Interpretation parent.
- **By Feature & Interpretation** — adds an extra Feature grouping
  above the Interpretation.

This is mostly useful when several representations share the same name
but differ by Interpretation (e.g. variants of the same grid).

> ⚠ **Switching the mode clears all current selections, visibility and
> coloring state.** A snackbar warns you when this actually happens.
> The tree is rebuilt in place — no need to re-import the file.

### Background Color

A palette picker for the 3D view background. Pick from the swatches or
type a hex color.

---

## Camera Controls

Top-left of the 3D view: vertical button strip with reset/look-along
buttons (`+X`, `-X`, `+Y`, `-Y`, `+Z`, `-Z`, fit-camera). Use the mouse
inside the view to pan / rotate / zoom interactively.

---

## Log Panel

When VTK / ParaView emit warnings or errors during a load or a render,
they collect at the bottom of the screen behind a collapsed panel. The
panel header shows the live count of errors and warnings; expand it to
read messages, click **Clear** to empty the queue.

The panel is hidden when the queue is empty — it doesn't take up screen
real estate unless something has been logged.

---

## Tips & Limits

- **Sessions are isolated.** Closing the browser tab loses your data
  and selection state.
- **Per-rep color is remembered**, but only within the current session.
- **Eye states (visibility, active array) are reset on tree-hierarchy
  mode change.** That's by design — node ids and paths change between
  layouts.
- **Heavy property loads** (large IJK grids with many properties)
  benefit from the Manual load mode — pick everything you need first,
  then click **Load** once.
- **Grid2D and other surfaces** render through their own ExtractBlock
  source. Hiding via the eye truly removes the actor from the view.
- The **VTK log panel** is your friend when something looks wrong — it
  surfaces messages that wouldn't otherwise be visible from a browser.
