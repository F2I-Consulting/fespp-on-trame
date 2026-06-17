# `fespp_on_trame/app/core/sources/` — ParaView sources architecture

This document describes the architecture of the Python `sources/`
package — the layer that wraps ParaView pipeline proxies (Collector,
IjkGrid, ExtractBlock, slice, clip, …) into per-representation
objects driven by the trame engine.

This is the **wrapping layer between trame state and ParaView's
ServerManager**. Above it sits the engine (`app/core/engine/`) that
orchestrates user actions; below it lives `paraview.simple` and the
SM proxy graph.

For a full app overview, see [`dev-guide.md`](dev-guide.md). For
general ParaView / RESQML background, see the local notes
[`../PARAVIEW.md`](../PARAVIEW.md) and [`../RESQML.md`](../RESQML.md)
(gitignored).

---

## Table of Contents

- [Layer position](#layer-position)
- [Module map](#module-map)
- [The two entry sources: `Collector` and `ETPConnector`](#the-two-entry-sources-collector-and-etpconnector)
- [Per-representation wrappers](#per-representation-wrappers)
  - [`IjkGrid` — sliceable structured grid](#ijkgrid--sliceable-structured-grid)
  - [`ExtractBlockRepresentation` — everything else](#extractblockrepresentation--everything-else)
- [Filter wrappers: `SlicePlane`, `ClipPlane`, `PlaneWidget`](#filter-wrappers-sliceplane-clipplane-planewidget)
- [`SourceRegistry` — single entry point for the engine](#sourceregistry--single-entry-point-for-the-engine)
- [Lifecycle: a load + activate + cut walkthrough](#lifecycle-a-load--activate--cut-walkthrough)
- [Naming conventions](#naming-conventions)
- [Shared helpers (`representation.py`)](#shared-helpers-representationpy)
- [Cross-cutting state](#cross-cutting-state)

---

## Layer position

```
+-----------------------------------------------+
|  UI layer (trame.widgets)                     |
|  panels, tree, render views                   |
+-----------------------------------------------+
|  Engine layer (app/core/engine/)              |
|  dispatch handlers, state.change reactions    |
|  active_array, data_load, slicer_dispatch,    |
|  slice_dispatch, clip_dispatch, threshold,    |
|  realization_dispatch, source_resolver…       |
+-----------------------------------------------+
|  ★ Sources layer (app/core/sources/) ★        |  <— this doc
|  per-rep PV pipeline wrappers                 |
+-----------------------------------------------+
|  paraview.simple + ServerManager              |
|  vtkSMProxy graph (sources, filters, views)   |
+-----------------------------------------------+
|  VTK pipeline (vtkAlgorithm, vtkDataObject)   |
+-----------------------------------------------+
```

The sources layer keeps the engine ignorant of PV/SM idioms: filter
creation, display proxy management, registration-name conventions,
multi-upstream chaining, widget plumbing. Engine code never calls
`pvsimple.*` directly for pipeline edits — it goes through these
wrappers via the registry.

---

## Module map

| File                  | What it owns                                                                                          |
|-----------------------|-------------------------------------------------------------------------------------------------------|
| `collector.py`        | The single `EPCCollector` PV source (one per app).                                                    |
| `etp_connector.py`    | The single `ETP12Store` PV source for OSDU RDDMS connections.                                         |
| `ijkgrid.py`          | `IjkGrid` — per-IJK-grid wrapper: multi-axis slicers + volume crop + threshold chain.                 |
| `extract_block.py`    | `ExtractBlockRepresentation` — per-rep wrapper for every non-IJK type (UnstructuredGrid, Wellbore, …).|
| `slice_plane.py`      | `SlicePlane` — plane slice filter for any rep (used by ExtractBlock today).                           |
| `clip_plane.py`       | `ClipPlane` — plane clip filter, mirrors `SlicePlane` data model.                                     |
| `plane_widget.py`     | `PlaneWidget` — `ImplicitPlaneWidgetRepresentation` wrapper shared by `SlicePlane` and `ClipPlane`.   |
| `representation.py`   | Shared helpers (`_sanitize`, `_find_registered_proxy`, `_apply_default_tint`).                        |
| `source_registry.py`  | `SourceRegistry` — single entry-point dict-of-instances exposed to the engine.                       |

---

## The two entry sources: `Collector` and `ETPConnector`

Two thin wrappers that own the singleton PV source which produces the
RESQML data assembly:

  - **`Collector`** wraps `pvsimple.EPCCollector()` (registered as
    `EPCCollector` in the `sources` group). Loads `.epc/.h5` files
    via `add_file(...)` which pushes the path into the `Files`
    multi-element SM property, then refreshes information so the
    assembly is rebuilt.

  - **`ETPConnector`** wraps `pvsimple.ETP12Store()` (registered as
    `ETP12Store`). Same role for ETP1.2 / OSDU RDDMS connections —
    handles auth, optional proxy, dataspace selection, then exposes
    the source proxy in the same way.

Both classes are thin (~50 lines): they keep the source, expose a
representationType / scale_z holder for the UI, and a `show()`
default-displaying the proxy. They do NOT track representations —
every rendered rep lives in `IjkGrid` or
`ExtractBlockRepresentation` instances downstream.

---

## Per-representation wrappers

A *representation* in RESQML is one geometric object (one grid, one
trajectory, …) that can have many properties / sub-representations.
When the user checks a rep's box in the tree, the engine creates one
of two wrapper types:

### `IjkGrid` — sliceable structured grid

For `IjkGrid` rep type. Owns the **multi-slicer pipeline**:

```
EnergisticsExtractor (rep_data)
        |
        +--> ExtractCellsAlongLine I_0
        +--> ExtractCellsAlongLine I_1
        |    …
        +--> ExtractCellsAlongLine J_…
        +--> ExtractCellsAlongLine K_…
        +--> ExtractSubset (volume crop, range mode)
```

Each *active upstream* (rep_data + slicers in slice mode; rep_data +
volume crop in range mode) can be the input of a *threshold chain*.
The chain is modelled by `_IjkChainEntry`: each entry holds a
`pv_proxies` dict keyed by `id(upstream_source)` so multiple
Threshold proxies (one per upstream) can be chained from the same
logical entry — the IjkGrid's multi-source nature forces this fan-out.

Visibility rules:
  - `_deepest_visible_leaf()` picks the chain tip to render per
    upstream — others stay hidden.
  - `_show_source_or_chain(src, view, visible, leaf)` toggles between
    the slicer output and the chain leaf in a single view.

The pipeline is rebuilt on:
  - axis / slicer position changes (range or per-position slicers)
  - threshold add / delete / set_range / set_visible
  - representation type or Z-scale change

### `ExtractBlockRepresentation` — everything else

For every non-IJK rep type (UnstructuredGrid, Wellbore, Trajectory,
Grid2d, PointSet, Polyline*, TriangulatedSet, …). Owns a single
**`ExtractBlock`** filter chained on the collector:

```
EPCCollector  --> ExtractBlock (rep_<sanitized>)
                       |
                       +--> Threshold (chain entry 1)
                              |
                              +--> Threshold (chain entry 2)
                                     |
                                     …
                       +--> Slice (optional, plane)
                       +--> Clip  (optional, plane)
```

The ExtractBlock is created via the collector's `SetExtractRepPath`
+ `GetExtractedRepProducerName` SM properties — the FESPP C++ side
registers a sub-pipeline `EnergisticsExtractor` filter (ShallowCopy
semantics, no real data duplication) and returns its registration
name to Python.

Chain entries use a simpler `ChainEntry` (one proxy per entry, not a
dict): the input is a single source so no multi-upstream fan-out is
needed.

Both `IjkGrid` and `ExtractBlockRepresentation` expose the same
threshold API: `add_threshold`, `delete_threshold`, `set_range`,
`set_visible`, `get_chain`, `available_arrays`, `array_data_range`.

---

## Filter wrappers: `SlicePlane`, `ClipPlane`, `PlaneWidget`

**Note:** the slice/clip user-facing UI is currently commented out
(see commit `c791598 ui: hide slice/clip from the SlicersPanel`); the
backend wrappers below remain live and re-enabled by uncommenting the
panel.

### `SlicePlane`

Plane slice (Cuts the rep with an infinite plane, output is the 2D
cross-section). Canonical state:

  - `_origin: [3]` — a point on the plane
  - `_normal: [3]` — plane normal (non-zero when enabled)
  - `_axis: 'X'|'Y'|'Z'` — UI affordance (the cardinal axis closest
    to the current normal; snapped within 5° via `_AXIS_SNAP_COS`).

Pipeline: `pvsimple.Slice(SliceType='Plane')`, Input = the rep's
canonical source. When enabled, the rep source is hidden so only the
cross-section shows.

### `ClipPlane`

Plane clip (cuts the volume in half along a plane, keeps one side —
flipped by `InsideOut` / `Invert` in PV6). Same data model + axis
snap as `SlicePlane`, plus an `_inside_out` flag. Output is
volumetric, so the rep's coloring (ColorBy, LUT, opacity) follows
the clip naturally.

Pipeline: `pvsimple.Clip(ClipType='Plane', Crinkleclip=0)`.

### `PlaneWidget`

Shared `ImplicitPlaneWidgetRepresentation` wrapper used by both
`SlicePlane` and `ClipPlane`. Created via the SM ProxyManager
(`pxm.NewProxy('representations', 'ImplicitPlaneWidgetRepresentation')`),
registered in the view's `HiddenRepresentations` list, placed on
current bounds, then enabled. Drives the sphere/arrow on-screen
gestures.

Only one widget is shown at a time: edit mode is gated by
`state.ui_plane_edit_mode` (`'slice'`, `'clip'`, or `None`). The
filter whose name matches `ui_plane_edit_mode` calls
`PlaneWidget.ensure(view)`; the other one calls `destroy()`.

End-of-drag hands the new (origin, normal) back to the filter via
an observer, which snaps to a cardinal axis if close and writes back
to the panel state.

---

## `SourceRegistry` — single entry point for the engine

Everything above is hidden behind one façade. The engine talks to
the registry through a uniform compat surface:

```python
registry.get(rep_path)                # → source proxy (IjkGrid or ExtractBlock)
registry.get_ijk_grid(rep_path)       # → IjkGrid | None
registry.get_extract_block(rep_path)  # → ExtractBlockRepresentation | None

registry.add_threshold(rep_path, parent, array)
registry.delete_threshold(rep_path, name)
registry.set_range(rep_path, name, low, high)
registry.set_visible(rep_path, name, visible)
registry.get_chain(rep_path)
registry.available_arrays(rep_path)
registry.array_data_range(rep_path, array_name)
registry.all_visible_thresholds(rep_path)
registry.all_chain_proxies(rep_path)
registry.get_threshold(rep_path)      # deepest visible

registry.apply_z_scale(zscale)
registry.apply_representation(rep_type)
registry.sync(selectors, reservoir_select_node_ids)
registry.release(rep_path)
registry.release_all()
```

Internally the registry keeps **two dicts** (one per concrete type)
because the IjkGrid lifecycle is keyed on a *property node id*
(passed via `set_node_id`) while the ExtractBlock lifecycle is keyed
on the *rep path*. Both eventually map to a single rep_path the
engine knows, so the asymmetry stays hidden from callers.

`sync(selectors, …)` is the central reconciler — given the current
tree selector set, it creates instances for newly-selected reps and
releases instances for de-selected ones.

---

## Lifecycle: a load + activate + cut walkthrough

A walkthrough that touches every wrapper in order:

1. **App starts.** `Collector()` creates the one `EPCCollector` PV
   source. `SourceRegistry()` is empty.

2. **User uploads `model.epc`.** `collector.add_file(path)` pushes
   the path into the source's `Files` property. The C++ plugin
   parses the EPC and builds a `vtkDataAssembly` — exposed to Python
   via `collector.get_source().Assembly`. The engine's `tree.py`
   re-parses it into the trame state lists `ui_subtree_*`.

3. **User checks an IJK grid in the tree.** The engine's
   `data_load.run(...)` is invoked via the
   `state.change("fespp_data_selectors")` handler. It calls
   `registry.sync(selectors, ...)` which creates an `IjkGrid`
   instance for the rep_path.

4. **User picks a property (eye click).**
   `active_array.toggle_dataarray_color(panel_id, array_path)` writes
   to `state.ui_active_array_by_rep_by_view[panel_id][rep_path] =
   array_path`, then asks the registry for the displays via
   `displays_for_rep_path(...)`. For an IjkGrid these are the slicer
   displays + volume crop + thresholds.

5. **User opens the Slicers panel and toggles a J slicer.** The
   panel writes `ui_slices_j_list`; the engine's `slicer_dispatch`
   forwards to `IjkGrid._sync_slice_sources('j', n)` which creates /
   re-uses Slice proxies through pvsimple.

6. **User adds a threshold.** `threshold_dispatch.threshold_add(...)`
   calls `registry.add_threshold(rep_path, parent, array)` →
   `IjkGrid.add_threshold(...)` which creates one `Threshold` proxy
   per active upstream (slicer + volume crop).

7. **(Slice/Clip flow — UI currently hidden):** if re-enabled, the
   panel writes axis/offset/enabled to `state.ui_slice_*`; the
   dispatch calls `IjkGrid.slice_set(...)` (or the EB equivalent)
   which lazily builds the `Slice` pipeline; `PlaneWidget.ensure(...)`
   is called when `ui_plane_edit_mode == 'slice'`. The widget's
   end-of-drag observer pushes the new (origin, normal) back.

8. **User unchecks the rep.** `registry.sync(...)` notices the
   rep_path is no longer selected, calls `IjkGrid.delete()` which
   tears down every Slice/Threshold/Clip proxy + the rep_data
   extractor.

---

## Naming conventions

Every proxy created by these wrappers carries a deterministic
registration name so subsequent lookups can rebuild references after
a state reload:

| Proxy                              | Registration name pattern             |
|-----------------------------------|----------------------------------------|
| EPC collector                     | `EPCCollector`                         |
| ETP store                         | `ETP12Store`                           |
| Per-rep extractor (C++ side)      | `rep_<sanitized(rep_path)>`            |
| IjkGrid rep_data                  | `rep_data_<sanitized(rep_path)>`       |
| IjkGrid slicer (one per position) | `slice_<axis>_<idx>_<sanitized(rep)>`  |
| IjkGrid volume crop               | `volume_<sanitized(rep_path)>`         |
| Threshold (any chain)             | `th_<chain-entry-uuid>_<upstream-id>`  |
| SlicePlane                        | `slice_plane_<sanitized(rep_path)>`    |
| ClipPlane                         | `clip_plane_<sanitized(rep_path)>`     |
| PlaneWidget                       | `plane_widget_<sanitized(rep_path)>`   |

`_sanitize(name)` (in `representation.py`) replaces every char outside
`[-.0-9A-Z_a-z]` with `_` so RESQML paths translate to valid PV
registration names.

`_find_registered_proxy(reg_name)` widens the SM `ProxyManager` lookup
to both the `filters` and `sources` groups, because the C++ side
registers extract filters under `filters` (RegisterPipelineProxy) but
`pvsimple.FindSource` only scans `sources`.

---

## Shared helpers (`representation.py`)

Minimal today, hosts:

  - `_sanitize(name)` — see the table above.
  - `_find_registered_proxy(reg_name)` — see above.
  - `_apply_default_tint(display)` — applies a deterministic but
    pleasant default `DiffuseColor` to a freshly-created display, so
    reps don't all start as pure white.

The plan in `REFACTOR_PLAN.md` (TODO) is to grow this into a
`Representation` base class shared by `IjkGrid` and
`ExtractBlockRepresentation`, and a base `ChainEntry` dataclass.

---

## Cross-cutting state

Trame state variables the sources layer reads / writes (engine
handlers usually mediate these — the sources themselves only
manipulate their own internal state):

| Variable                                  | Owner / writer            | Read here                          |
|-------------------------------------------|---------------------------|------------------------------------|
| `ui_loaded_rep_paths`                     | engine.data_load          | (none — registry is the truth)      |
| `ui_hidden_rep_paths_by_view`             | engine.visibility / UI    | `IjkGrid.show()`, `EB.show()`       |
| `ui_active_array_by_rep_by_view`          | engine.active_array       | `apply_color_array` resolver        |
| `ui_active_realization_by_array_by_view`  | engine.realization_dispatch| same                               |
| `ui_slices_range_mode`                    | UI (Slicers IJK tab)      | `IjkGrid` (range vs slice pipeline) |
| `ui_slices_range_{i,j,k}`                 | UI                        | `IjkGrid._sync_slice_sources`       |
| `ui_slices_{i,j,k}_list/_visible_list`    | UI                        | same                                |
| `ui_slice_*` / `ui_clip_*`                | UI (panels — currently hidden) | `SlicePlane` / `ClipPlane`     |
| `ui_plane_edit_mode`                      | UI (slice/clip — hidden)  | `PlaneWidget.ensure()` gating       |
| `ui_threshold_chain`                      | engine.threshold_dispatch | (none — published by engine)        |
| `ui_scale_z`                              | UI                        | `apply_z_scale` on every wrapper    |

---

## See also

  - [`dev-guide.md`](dev-guide.md) — full app architecture.
  - [`../PARAVIEW.md`](../PARAVIEW.md), [`../RESQML.md`](../RESQML.md)
    — local reference notes on the underlying tech stacks (gitignored).
  - `REFACTOR_PLAN.md` — pending refactor: collapse IjkGrid + EB into
    a shared `Representation` base, unify the chain entry type.
