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
- [Slicing IJK Grids](#slicing-ijk-grids)
- [Time Series](#time-series)
- [Multi-Realization Properties](#multi-realization-properties)
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

The LUT applies whenever the eye is open on the array. When the eye is
closed you can still tweak the LUT (e.g. to prepare it before re-opening
the eye).

### Categorical / Discrete Properties

For `DiscreteProperty` and `CategoricalProperty`, the panel switches
to a list of category-specific color/opacity pickers (one row per
distinct value). The list is sorted by value and you can edit each cell
independently.

---

## Slicing IJK Grids

When an IJK grid is selected, the **Slicers** panel appears in the
Reservoir attributes card:

- Three sliders (i, j, k) with min/max, current position and visibility
  toggles.
- Several slices per axis can coexist — use the **+** / **−** buttons to
  add/remove slices.
- Switch between **Volume** and **Slice** display via the dedicated
  toggle.

When you click a property, ColorBy is applied to whichever IJK rendering
is currently visible (volume or slice).

---

## Time Series

`TimeSeries` and `MultiRealizationTimeSeries` nodes are leaves. The
underlying property kind (Continuous / Discrete / Categorical) is
preserved on the node icon.

Activate one and the **Time controls** appear at the top of the 3D view
(playback bar with play/pause, step-by-step buttons and a timeline).
Time labels follow the time-series metadata.

---

## Multi-Realization Properties

`MultiRealization` and `MultiRealizationTimeSeries` collapse a whole
realization stack into a single tree leaf. When activated, an extra
slider in the attributes card lets you scrub through the available
realization indices (only indices that actually exist in the loaded
data are shown).

The LUT range can be **locked** (key icon next to the slider) so the
color mapping stays comparable between realizations.

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
