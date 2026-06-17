# FESPP-on-Trame — Developer Guide

This document is for developers contributing to FESPP-on-Trame. It
covers the architecture, the data flow between layers, and the key
state variables and conventions to understand before editing the code.

For end-user documentation, see [`user-guide.md`](user-guide.md).

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [Repository Layout](#repository-layout)
- [The C++ Side: FESPP Plugin](#the-c-side-fespp-plugin)
  - [Data Repository → vtkDataAssembly](#data-repository--vtkdataassembly)
  - [Selection Modes](#selection-modes)
  - [Tree Hierarchy Modes](#tree-hierarchy-modes)
  - [Per-Rep Extract: ExtractRepWithoutCopy](#per-rep-extract-extractrepwithoutcopy)
  - [Per-View Clone: vtkEPCCollectorClone](#per-view-clone-vtkepccollectorclone)
  - [Live Assembly Rebuild](#live-assembly-rebuild)
- [The Python Side: Trame App](#the-python-side-trame-app)
  - [Module Map](#module-map)
  - [Lifecycle Overview](#lifecycle-overview)
  - [Engine Orchestrator (`engine/boot.py`)](#engine-orchestrator-enginebootpy)
  - [Tree Parser (`tree.py`)](#tree-parser-treepy)
  - [Selector (`selector.py`)](#selector-selectorpy)
  - [Activator (`activator.py`)](#activator-activatorpy)
  - [Sources Layer](#sources-layer)
  - [View-Scenes Layer](#view-scenes-layer)
  - [UI Layer](#ui-layer)
- [State Variables (Trame)](#state-variables-trame)
- [Selection / Visibility / Coloring Model](#selection--visibility--coloring-model)
- [Critical Data Flows](#critical-data-flows)
  - [File Load](#file-load)
  - [Checkbox Click](#checkbox-click)
  - [Eye Click (Visibility)](#eye-click-visibility)
  - [Eye Click (DataArray)](#eye-click-dataarray)
  - [Add View / Split / Empty View](#add-view--split--empty-view)
  - [Copy From View](#copy-from-view)
  - [Tree Hierarchy Mode Change](#tree-hierarchy-mode-change)
- [Common Pitfalls](#common-pitfalls)
- [Adding a Feature: Cookbook](#adding-a-feature-cookbook)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Browser                          │
│   Vue 3 + Vuetify 3 (rendered by Trame templates)    │
└──────────────────────┬──────────────────────────────┘
                       │  (websocket, JSON state)
┌──────────────────────┴──────────────────────────────┐
│                Python (Trame server)                 │
│ ┌──────────────────────────────────────────────────┐ │
│ │ Engine (orchestration), Selector, Activator,     │ │
│ │ Tree (assembly→state), RepSources, IjkGrid,      │ │
│ │ panels (color, slicers, …)                       │ │
│ └────────────────────────┬─────────────────────────┘ │
│                          │  pvsimple, vtkSMPropertyHelper
│ ┌────────────────────────┴─────────────────────────┐ │
│ │ ParaView server-side proxy (vtkEPCCollector)     │ │
│ └────────────────────────┬─────────────────────────┘ │
└──────────────────────────┴──────────────────────────┘
                           │
┌──────────────────────────┴──────────────────────────┐
│              C++ FESPP plugin                        │
│  vtkEPCCollector ─→ ResqmlDataRepository…Collection  │
│  uses fesapi to parse EPC + drive vtkDataAssembly    │
└─────────────────────────────────────────────────────┘
```

Data path:

1. fesapi parses the `.epc` / `.h5` file into an in-memory
   `DataObjectRepository`.
2. `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` walks the
   repository and builds a `vtkDataAssembly` (the tree visible to the
   user). Each node carries `kind`, `title`, `path`, plus per-type
   metadata (`propKind`, `realization_count`, …).
3. The Python `Tree` parser reads the assembly and writes it as nested
   dicts into Trame state (`ui_subtree_reservoir`, `_surface`, `_well`).
4. Vuetify templates render the trees from those dicts.
5. Selecting / activating / toggling eyes in the UI mutates Trame
   state, which fires `@state.change` handlers that drive the
   ParaView pipeline (selectors, ColorBy, Visibility, …).

---

## Repository Layout

```
.
├── fespp_on_trame/              # Python Trame application
│   ├── __main__.py              # entry point, CLI args, wires the engine
│   ├── constants.py
│   └── app/
│       ├── core/                # backend: engine, selectors, sources
│       │   ├── tree.py                # vtkDataAssembly → Trame dicts
│       │   ├── selector.py            # checkbox → fespp_data_selectors
│       │   ├── activator.py           # active node → ColorBy + LUT
│       │   ├── wellhead.py            # wellbore trajectory helpers
│       │   ├── timeseries.py
│       │   ├── color_palette.py       # default per-rep colors
│       │   ├── engine/                # orchestration sub-package
│       │   │   ├── boot.py                  # initialize_fespp_engine (main wiring)
│       │   │   ├── state_defaults.py        # state.setdefault(...) seeds
│       │   │   ├── data_load.py             # fespp_data_selectors handler
│       │   │   ├── active_array.py          # ColorBy fan-out (rep / view buckets)
│       │   │   ├── slice_dispatch.py        # per-view slice plane writes
│       │   │   ├── clip_dispatch.py         # per-view clip plane writes
│       │   │   ├── slicer_dispatch.py       # per-view IJK slicer writes
│       │   │   ├── threshold_dispatch.py    # per-view threshold chain writes
│       │   │   ├── realization_dispatch.py  # per-view MR realization picks
│       │   │   ├── source_resolver.py       # rep_path → PV proxies / displays
│       │   │   ├── panel_resolver.py        # panel_id → pv_view / html_view
│       │   │   ├── visibility.py            # rep eye click flow
│       │   │   ├── view_ops.py              # camera reset / view update
│       │   │   ├── selection_dispatch.py    # checkbox → selectors plumbing
│       │   │   ├── hierarchy.py             # tree-hierarchy-mode flow
│       │   │   ├── diff.py                  # A − B diff scene
│       │   │   ├── etp.py                   # ETP/OSDU connect
│       │   │   ├── time_realization.py      # per-view TC labels
│       │   │   └── vtk_log.py               # stderr tee + log panel
│       │   ├── sources/                # PV proxy wrappers
│       │   │   ├── collector.py             # wraps vtkEPCCollector
│       │   │   ├── etp_connector.py
│       │   │   ├── extract_block.py         # legacy non-IJK per-rep wrapper
│       │   │   ├── ijkgrid.py               # IJK pipeline (legacy + per-view)
│       │   │   ├── slice_plane.py           # SlicePlane (per (rep, view))
│       │   │   ├── clip_plane.py            # ClipPlane (per (rep, view))
│       │   │   ├── plane_widget.py          # 3D widget channel
│       │   │   ├── representation.py        # ExtractBlock helpers
│       │   │   ├── source_registry.py       # legacy per-rep registry
│       │   │   ├── view_scene.py            # one ViewScene per render panel
│       │   │   ├── rep_in_scene.py          # per-(rep, view) wrapper
│       │   │   └── scene_registry.py        # view → ViewScene map
│       │   └── common/
│       ├── ui/                  # Vue/Vuetify templates
│       │   ├── view.py                # main layout
│       │   ├── tree_views.py          # the 3 VTreeviews + eye slots
│       │   ├── toolbar.py
│       │   ├── import_dialog.py
│       │   ├── helpers.py
│       │   ├── content/                # multi-view content area
│       │   │   ├── content.py
│       │   │   ├── view/
│       │   │   │   └── multi_view.py        # FesppMultiView (ptc.MultiView)
│       │   │   ├── dialog/
│       │   │   │   └── new_view_content_dialog.py  # split: Copy / Empty / Diff
│       │   │   └── widget/
│       │   │       ├── time_control.py
│       │   │       ├── realization_picker.py
│       │   │       ├── view_link_menu.py        # per-view camera-link menu
│       │   │       └── per_view_camera_toolbar.py
│       │   ├── drawer/
│       │   │   └── panel/                   # per-feature panels
│       │   │       ├── solid_color_panel.py
│       │   │       ├── color_editor.py
│       │   │       ├── categorical_color_editor.py
│       │   │       ├── representation_type_panel.py
│       │   │       ├── slicers.py                  # IJK tab body
│       │   │       ├── slicers_panel.py            # Slicers card (IJK / Slice / Clip tabs)
│       │   │       ├── slice_plane_panel.py
│       │   │       ├── clip_plane_panel.py
│       │   │       ├── threshold_panel.py
│       │   │       └── copy_from_view_menu.py      # "Copy from view X" helper
│       │   ├── config/
│       │   │   ├── tree_icons.py
│       │   │   └── tree_selection.py
│       │   └── widget/
│       └── io/
│           ├── upload_endpoint.py     # /upload HTTP route (multipart)
│           ├── drop_files.py
│           └── http.py
└── doc/                         # docs (this file lives here)
```

The **C++ FESPP plugin** sources live in a separate repository (under
`e:\Dev\fespp\work\src\Plugin\Energistics\` in the development setup).
A build step copies those sources to the deploy tree
(`/work/ttl/fespp/Plugin/Energistics/...`) before invoking CMake.

---

## The C++ Side: FESPP Plugin

The plugin exposes `vtkEPCCollector`, a `vtkPartitionedDataSetCollectionAlgorithm`
backed by `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` (the
"repository wrapper") which itself wraps a fesapi `DataObjectRepository`.

### Data Repository → vtkDataAssembly

`buildDataAssemblyFromDataObjectRepo(fileName)` traverses every
representation in the repo (grids, surfaces, polylines, points,
unstructured grids) and calls `searchRepresentations(rep)` for each.
Specialised walkers handle wellbores (`searchWellboreTrajectory`),
property sets (`searchPropertySet`), time series (`searchTimeSeries`)
and realizations (`searchRealization`).

Every node is added via `addNodeToDataAssembly(object, type, parent)`
which sets:

- `type` (int) — `TreeViewNodeType` enum value (see `Tools/enum.h`).
- `kind` (string) — human/Python-friendly name (`"IjkGrid"`,
  `"ContinuousProperty"`, …).
- `title` (string) — original RESQML object title.
- `label` (string) — VTK-valid name for legacy display.
- Plus optional metadata: `propKind`, `realization_count`,
  `realization_indices`, `minvalue`, `maxvalue`, `colorRGB`, …

**Synthetic node types** (`MultiRealization`, `MultiRealizationTimeSeries`,
`Feature`, `Interpretation`) have no fesapi object behind them; they
are pure tree-shaping helpers.

### Selection Modes

Two selection semantics, chosen at runtime by the
`ExplicitSelection` proxy property:

- `ExplicitSelection = 0` *(default, ParaView GUI compatibility)* —
  selecting a path implicitly includes all descendants. This matches
  ParaView's `data_assembly_editor` widget which collapses fully-checked
  subtrees to the parent path.
- `ExplicitSelection = 1` *(set at boot by fespp_on_trame)* — selectors
  are taken literally for non-grouping nodes. Selecting a grid does
  NOT auto-load its properties; selecting a wellbore frame does NOT
  auto-load its channels. Grouping nodes (`Collection`, `Wellbore`,
  `Partial`, `Feature`, `Interpretation`) still propagate.

The split is implemented in `selectNodeId` / `selectNodeIdChildren`:
descendant propagation only happens when `!_explicitSelection ||
isGroupingType(node_type)`. See `isGroupingType` in `Tools/enum.h`.

### Tree Hierarchy Modes

`SetTreeHierarchyMode(value)` switches the tree layout between three
modes (enum `TreeHierarchyMode` in `enum.h`):

| Value | Name | Layout |
|-------|------|--------|
| 0 | `Flat` | Reps directly under root (legacy). |
| 1 | `ByInterpretation` | Reps grouped under their Interpretation parent. |
| 2 | `ByFeatureAndInterpretation` | Extra Feature grouping above Interpretation. |

`resolveGroupingParent(rep, parent)` is the helper that, in non-Flat
modes, looks up or creates the matching `Feature` / `Interpretation`
nodes (idempotent — keyed by uuid) and returns the effective parent
node id. It's called from `buildDataAssemblyFromDataObjectRepo` for
every top-level rep.

### Per-Rep Extract: EnergisticsExtractor (chained on collector)

Each loaded rep gets its own single-output ParaView source via an
`EnergisticsExtractor` filter chained on top of the collector. The
Python side (`ExtractBlockRepresentation._create_source` in
`extract_block.py`) builds the extractor via
`_create_plugin_filter_proxy("EnergisticsExtractor", …)` and registers
it under a deterministic `rep_<rep_path-with-_>` name. The Python side
diffuse-color default tint and ColorBy operate on this individual
source.

The "WithoutCopy" semantics shallow-copy the partition data in
`RequestData`, so the sub-source automatically tracks upstream changes
(selector add/remove, realization swap, property in-place addition).

**Why Python and not the C++ `SetExtractRepPath` proxy command:** the
collector's C++ side does have a `SetExtractRepPath(path)` property
command that internally calls
`controller->RegisterPipelineProxy(extract, regName)` — but that path
silently fails to re-publish the proxy when called a second time
under the same `regName` after a Python `pvsimple.Delete` cycle
(deselect-all + reselect on the same rep). See PARAVIEW.md
"`controller->RegisterPipelineProxy` silently fails the second time
under the same name" for the documented workaround pattern. The
Python-direct path bypasses the controller entirely
(`spm->NewProxy + spm->RegisterProxy("sources", …)`), which is
re-callable N times in a row.

### Per-View Clone: vtkEPCCollectorClone

`vtkEPCCollectorClone` is a pure-passthrough filter chained on the
top-level `vtkEPCCollector` source. It ShallowCopy's the upstream
output in `RequestData` (zero data duplication) and exists for one
reason: give each Python `ViewScene` its own root proxy in the PV
ServerManager graph. The per-view pipelines
(`EnergisticsExtractor` + slicers + threshold) anchor on the clone,
so two views can hold divergent downstream proxies without sharing
state. The clone itself is never `Show()`n in any view (it's a
structural node, not a renderable one).

When the FESPP plugin DLL ships without `vtkEPCCollectorClone`
(out-of-date build), the Python side falls back to anchoring on the
shared collector source instead. This is logged at view creation
as `clone=shared` and disables per-view divergence for that
scene (every "per-view" proxy collides on `id()` across views).

### Live Assembly Rebuild

`rebuildAssembly()` (added with the TreeHierarchyMode feature):

1. Drops every per-node-id cache (`_nodeIdToMapper`,
   `_nodeIdToMapperSet`, `_selection`, `_currentSelection`,
   `_oldSelection`, `_blocksColors`, `_blockColorsMap`).
2. Calls `vtkDataAssembly::Initialize()` on the existing assembly,
   then re-applies `SetRootNodeName("data")` (Initialize resets the
   root name to the VTK default which would break path matching).
3. Re-traverses every previously-loaded file via
   `buildDataAssemblyFromDataObjectRepo` — this re-hits fesapi but
   doesn't re-read the file from disk because the repository is
   already in memory.

`SetTreeHierarchyMode` calls `rebuildAssembly()` automatically after
flipping the mode, also clearing `selectorNotLoaded` / `selectors`
(the previous-layout paths would otherwise raise
`vtkDataAssembly: Invalid parameters` warnings on the next
`RequestData`).

### Notable Public API Used from Python

| Method | Purpose |
|--------|---------|
| `Set/GetExplicitSelection(bool)` | Switch selection semantics. |
| `Set/GetTreeHierarchyMode(int)` | Switch tree layout (rebuilds in place). |
| `GetAssembly()` / `GetLiveAssembly()` | Direct access to the live `vtkDataAssembly` (bypasses the pipeline DeepCopy in `GetOutput`). `GetLiveAssembly` exists under a unique name to dodge wrapping issues with the parent class's `GetAssembly`. |
| `SetExtractRepPath(path)` + `GetExtractedRepProducerName()` | Per-rep extracted source pair (set + readback). |
| `SetRealizationIndex(int)` / `SetRealizationIndexAsString(str)` | Multi-realization scrubbing. |

---

## The Python Side: Trame App

The app uses Trame in single-page-with-drawer mode. State is shared
between server (Python) and client (Vue) via Trame's reactive
mechanism: writing to `state.foo` propagates to the browser, and
`@state.change("foo")` fires a Python handler on every mutation.

### Module Map

| Module | Responsibility |
|--------|----------------|
| `__main__.py` | CLI parsing, instantiates `App`, wires `initialize_fespp_engine`, calls `ui(server)`. |
| `app/core/engine/boot.py` | `initialize_fespp_engine(server, ...)` — the big orchestrator. Loads plugins, creates the initial render view, instantiates `Tree` / `Collector` / `SourceRegistry` / `SceneRegistry` / `Selector` / `Activator`, registers every `@state.change` and `@controller.set`. |
| `app/core/engine/state_defaults.py` | `state.setdefault(...)` for every variable the engine / UI rely on. Grouped declaratively so adding a flag doesn't require scrolling through `boot.py`. |
| `app/core/engine/data_load.py` | `run(state, ...)` — the body of the `fespp_data_selectors` handler: push selectors, hide multiblock parent, sync registries, refresh active, render. |
| `app/core/engine/{slice,clip,slicer,threshold,realization}_dispatch.py` | Per-concern dispatchers routing UI events through `scene_registry → RepInScene → per-view proxies` (legacy fallback when scene_registry isn't ready). |
| `app/core/engine/active_array.py` | ColorBy fan-out: `toggle_dataarray_color` (eye click) + `on_active_array_change` + `apply_panel_coloring` (per-panel re-color). |
| `app/core/engine/source_resolver.py` | `(rep_path, view) → list[PV proxy]` resolution for visibility / ColorBy fan-out. Per-view-aware. |
| `app/core/engine/panel_resolver.py` | `panel_id → pv_view / html_view` resolution via `server.context.multi_view`. |
| `app/core/engine/visibility.py`, `view_ops.py`, `time_realization.py` | Rep visibility eye, camera reset / view update broadcast, per-view TimeControl labels. |
| `app/core/engine/diff.py` | A − B diff scene compute + LUT setup. |
| `app/core/engine/stats_dispatch.py` | `publish_descriptive_stats(...)` — builds a transient `Threshold(no-NaN) → DescriptiveStatistics` chain on the active view's rendered source, reads the output, populates `state.ui_descriptive_stats`. Triggered by active property / rep / panel / realization / threshold chain edits + time-step changes. |
| `app/core/engine/vtk_log.py` | stderr tee → `state.vtk_log_messages`. |
| `app/core/tree.py` | `Tree` class — wraps `vtkDataAssembly`. `set_tree(assembly)` re-parses into `state.ui_subtree_*` and exposes `find_*` helpers. |
| `app/core/selector.py` | `Selector` — converts UI checkbox lists (`ui_select_node_*`) to assembly paths and writes them to `state.fespp_data_selectors`. |
| `app/core/activator.py` | `Activator` — listens on `ui_active_node_*`, resolves the active rep, conditionally applies `ColorBy`, refreshes the LUT/PWF panel. |
| `app/core/sources/collector.py` | Wraps `vtkEPCCollector` proxy: `add_file`, `show`, `set_realization_index`. |
| `app/core/sources/source_registry.py` | Legacy per-rep registry — kept as fallback. New code targets `SceneRegistry`. |
| `app/core/sources/extract_block.py` | Legacy non-IJK per-rep wrapper (`ExtractBlockRepresentation`). Most methods deprecated; the per-view extractor lives on `RepInScene` now. |
| `app/core/sources/ijkgrid.py` | IJK slicer / volume / chain pipeline. Each `RepInScene` for an IJK rep instantiates its OWN `IjkGrid` per view (anchored on the scene's clone). The legacy shared `IjkGrid` survives as a metadata holder. |
| `app/core/sources/slice_plane.py`, `clip_plane.py` | Per-(rep, view) `SlicePlane` and `ClipPlane` filters, owned by `RepInScene`. |
| `app/core/sources/scene_registry.py` | **`SceneRegistry`** — `{panel_id: ViewScene}` lifecycle, view → reps mirroring, `replicate_view` (snapshot/apply across views). |
| `app/core/sources/view_scene.py` | **`ViewScene`** — one per render panel. Owns the `vtkEPCCollectorClone` proxy + the panel's `{rep_path: RepInScene}` map. |
| `app/core/sources/rep_in_scene.py` | **`RepInScene`** — per-(rep, view) wrapper. Owns the per-view `EnergisticsExtractor` (non-IjkGrid), per-view `IjkGrid` pipeline (IjkGrid), per-view `SlicePlane` / `ClipPlane`, per-view threshold chain. Exposes `snapshot_*` / `apply_*` per concern for view replication. |
| `app/core/sources/etp_connector.py` | ETP/OSDU client (alternate data source). |
| `app/ui/view.py` | Main layout: drawer, tabs, attribute cards, general-display section, render area, log panel. |
| `app/ui/tree_views.py` | The three `VTreeview`s + per-view eye chips row + dependency-expansion handlers. |
| `app/ui/content/view/multi_view.py` | `FesppMultiView` (ptc.MultiView subclass) — owns the dockview panels, per-panel `pv_view` map, view-add / view-close lifecycle, camera-link sync, replicate-visibility on split. |
| `app/ui/content/dialog/new_view_content_dialog.py` | Split-action modal: Copy scene / Empty scene / Diff scene. |
| `app/ui/content/widget/{time_control,realization_picker,view_link_menu,per_view_camera_toolbar}.py` | Per-view overlays in the 3D area. |
| `app/ui/toolbar.py` | Title bar, **Import**, **Load** buttons, global Realization picker. |
| `app/ui/import_dialog.py` | File upload + ETP/OSDU connection dialog. |
| `app/ui/drawer/panel/solid_color_panel.py` | Active-node color/LUT panel. |
| `app/ui/drawer/panel/{slice,clip}_plane_panel.py`, `threshold_panel.py`, `slicers.py`, `slicers_panel.py` | Slice / Clip / Threshold / IJK slicers UI. Each panel header carries a `render_copy_menu(concern)` dropdown ("Copy from view X"). |
| `app/ui/content/panel/descriptive_stats_panel.py` | `DescriptiveStatsPanel` — VExpansionPanel rendering `state.ui_descriptive_stats` as a compact HTML table (Variable / Cardinality / Min / Max / Mean / Std Dev / Variance / Sum / Skewness / Kurtosis / M2-M4). Hidden when the state list is empty. |
| `app/ui/drawer/panel/copy_from_view_menu.py` | Reusable copy-from-view dropdown helper, registers the `copy_<concern>_from_view` triggers. |
| `app/ui/drawer/panel/color_editor.py`, `categorical_color_editor.py` | LUT / PWF widgets. |
| `app/ui/drawer/panel/representation_type_panel.py` | Per-rep ParaView display type (Surface / Wireframe / …). |
| `app/ui/config/tree_icons.py` | `kind` → mdi-icon map. |
| `app/ui/config/tree_selection.py` | Per-tab selectable types (used by the VTreeview `item_props` selector). |
| `app/io/upload_endpoint.py` | Patched HTTP upload route, calls `controller.load_epc_file` after each upload. |

### Lifecycle Overview

`__main__.py` builds an `App` which:

1. Creates the Trame `server` (`get_server(client_type="vue3")`).
2. Calls `initialize_fespp_engine(server, fespp_plugin_path=...)`.
3. Calls `ui(server)`.
4. Runs `server.start()`.

`initialize_fespp_engine` does most of the wiring:

- Loads the FESPP `.so` plus the `ExplicitStructuredGrid` plugin.
- Creates the ParaView render view.
- Builds the core objects: `Tree`, `Collector`, `ETPConnector`,
  `IjkGrid`, `RepSources`, `Selector`, `Activator`.
- Sets `ExplicitSelection=1` on the collector proxy.
- Pushes the initial `tree_hierarchy_mode` value.
- Calls `state.setdefault(...)` for every state variable (see below).
- Registers `@state.change` handlers and `@controller.set` actions.

### Engine Orchestrator (`engine/boot.py`)

This is the largest module. Responsibilities, by section:

- **VTK log capture** — installs a stderr tee so VTK-formatted messages
  end up both in docker logs and in `state.vtk_log_messages`.
- **Pipeline init** — collector / view / extract.
- **State defaults** — every state var the rest of the app relies on.
- **`controller.load_epc_file(path)`** — calls `_collector.add_file`,
  which sets `Files`, calls `UpdatePipelineInformation`, and triggers
  `controller.update_data_information`.
- **`controller.update_data_information`** — reads the live
  `vtkDataAssembly` (preferring `GetLiveAssembly` over the pipeline's
  deep-copied output) and calls `_tree.set_tree(assembly)`.
- **`@state.change("fespp_data_selectors")`** — the load handler:
  pushes selectors to the collector, hides the parent multiblock,
  syncs `RepSources`, bumps every producer's MTime to invalidate
  proxy info caches, updates `ui_loaded_rep_paths` and
  `ui_active_array_by_rep`, calls `notify_active_reps` on the
  activator, sets the active source, runs `refresh_active`, renders.
- **`controller.toggle_rep_visibility(rep_path)`** — rep eye click:
  flips `ui_hidden_rep_paths` and applies `pvsimple.Show` / `Hide`
  + `display.Visibility` on every source rendering the rep.
- **`controller.toggle_dataarray_color(array_path)`** — data-array
  eye click: writes to `ui_active_array_by_rep` (one entry per rep).
- **`@state.change("ui_active_array_by_rep")`** — applies the
  `ColorBy` (or clears it for SolidColor) on each loaded rep.
- **`@state.change("tree_hierarchy_mode")`** — pushes the mode to the
  collector (which triggers the C++ rebuild), clears every selection
  state var, calls `UpdatePipeline` so the pipeline output deep-copy
  catches up with the new live assembly, then `update_data_information`
  to re-parse, and pops the warning snackbar if a selection had been
  wiped.
- **`@state.change("load_mode")`** — auto / manual.
- **`controller.apply_pending_selection`** — manual mode's `Load`
  button entry point.
- **`@state.change("ui_scale_z")`** — broadcasts Z-scale to every rep
  source.
- **Slicer handlers**, **realization handlers**, **time controls**,
  **camera reset**, **session lifecycle** (drop temp dirs on last
  client exit).

### Tree Parser (`tree.py`)

`Tree.set_tree(data_assembly)` walks the live assembly with two
recursive helpers (`set_tree` for top-level + `add_subtreeview_data`
for subtrees) and writes three nested-dict lists:
`state.ui_subtree_{reservoir,surface,well}`.

Each dict has: `id`, `parent_id`, `title`, `path`, `type`, `icon`,
`is_ts`, `is_mr`, optional `disabled`, optional `children`.

**Sibling order.** The C++ assembly emits children in its own order; the
emitted `ui_subtree_*` dicts are then sorted **alphabetically at every
level** (the hierarchy is kept; only siblings are reordered) via
`_sibling_sort_key` — case-insensitive, accent-folded (`Éclair` sorts
with `E`), natural-numeric (`Grid2` before `Grid10`), with the
`!!!PARTIAL!!!` marker stripped so a partial sorts by its real name. This
is **presentational only**: it reorders the three emitted lists and each
node's `children`; node identity everywhere else is by `id`/`path`, never
list position (the assembly walk, `find_*`, dataset/partition indexing,
MR/timeseries, selection are all order-independent).

Dispatching to the right tab handles the tree-hierarchy modes:
top-level `Feature` / `Interpretation` nodes recurse via
`_resolve_dispatch_kind` until the first non-grouping descendant is
found, and *that* kind decides the destination tab.

The class also exposes a bunch of read-only helpers used by the rest
of the codebase: `find_node_id(path)`, `find_path(node_id)`,
`find_type(node_id)`, `find_title(node_id)`,
`find_attribute_value(node_id, attr)`,
`find_representation_node(node_id)`,
`find_parent_node_id_with_type(node_id, kind)`,
`find_first_child_of_type(node_id, kind)`,
`find_all_descendant_ids(node_id)` (used by the UI dependency
expansion), `has_property_descendant(node_id)`.

### Selector (`selector.py`)

The `Selector` holds the per-tab path lists
(`_selection_path_{reservoir,surface,well}`) and the active
`TimeSeries` / `Wellhead` instances. Every `select_node_*` method
reads `state.ui_select_node_*`, walks the ids to paths, sets one of
the three local lists, and writes the concatenation into
`state.fespp_data_selectors`.

Reservoir / surface / well are symmetric: they emit the full list of
checked paths (with `ExplicitSelection=1`, every property must be
listed explicitly).

### Activator (`activator.py`)

Listens on `ui_active_node_{reservoir,surface,well}`. The reservoir
handler is the most complex because of IJK grids:

1. Validates the active node is "active-able" (its subtree is
   checked) — otherwise resets `ui_active_node_*` to `[]`.
2. Resolves rep type, title, propKind.
3. For property activations, sets `active_color_array_name` and
   resolves the right ParaView source (rep_data filter, slicers,
   volume — multiple sources may render the same IJK grid).
4. **Conditionally applies ColorBy** — only when the active array's
   eye is open in `ui_active_array_by_rep`. The eye is the source of
   truth; the activation is just refresh.
5. Refreshes the panel LUT via `controller.update_color_editor`.
6. Forces the LUT range from the underlying VTK array (the proxy
   info cache is unreliable when arrays are added in-place by the
   C++ pipeline).

`refresh_active()` re-runs the three handlers without going through
state mutations — used by the manual-load path and by the load
handler to catch up activations that fired before the data was
loaded.

`notify_active_reps(present_paths)` is called by the engine after
each load to hide stale color bars for reps no longer in the
selection.

### Sources Layer

- **`Collector`** wraps a `pvsimple.FESPP` proxy. `add_file(path)`
  pushes the file, calls `UpdatePipelineInformation`, and runs
  `controller.update_data_information`.
- **`SourceRegistry`** is the legacy per-rep registry: maintains
  `{rep_path: ExtractBlockRepresentation | IjkGrid}` and exposes a
  thin compat surface (`get`, `get_ijk_grid`, `get_extract_block`,
  `add_threshold`, `slice_set`, …). Most of the per-rep methods are
  deprecated and only reachable as a fallback when `SceneRegistry`
  can't service the request (early boot, missing
  `vtkEPCCollectorClone`); first call emits a single-fire
  `[DEPRECATED]` print. New code targets `SceneRegistry`.
- **`ExtractBlockRepresentation`** is the legacy non-IJK wrapper.
  Its slice / clip / threshold methods are now also deprecated —
  the per-(rep, view) `RepInScene` owns those concerns.
- **`IjkGrid`** is dual-use: it still exists as a metadata-holder
  legacy instance (one per rep, keyed by property node id), AND each
  `RepInScene` for an IJK rep instantiates its OWN `IjkGrid` per
  view, parameterised with `view_id` / `clone` / `pv_view`. The
  per-view instance has its own rep_data + slicers + volume + chain,
  anchored on the scene's clone. `set_node_id` switches the active
  property; `apply_slice_positions` / `apply_range` / `apply_mode` /
  `apply_volume_visible` patch the slicer state.

### View-Scenes Layer

The view-scenes layer sits between the engine and the legacy sources
layer. Every render panel owns one `ViewScene` which in turn owns one
`RepInScene` per loaded rep. All per-(rep, view) state lives here.

```
SceneRegistry              ← single instance, on server.context.scene_registry
└── ViewScene (per panel)  ← created on FesppMultiView.add_view
    ├── _clone: vtkEPCCollectorClone        # the structural anchor
    └── _reps: { rep_path: RepInScene }
         └── RepInScene
              ├── _extractor       # per-(rep, view) EnergisticsExtractor (non-IJK)
              ├── _chain           # per-view threshold chain (non-IJK)
              ├── _per_view_ijk    # per-(rep, view) IjkGrid pipeline (IJK)
              ├── _slice_plane     # per-(rep, view) SlicePlane
              └── _clip_plane      # per-(rep, view) ClipPlane
```

#### `SceneRegistry`

- `add_view(panel_id, pv_view)` — called from `FesppMultiView.add_view`.
  Creates a `ViewScene` for the panel, which lazily instantiates a
  `vtkEPCCollectorClone` proxy on the collector. Logs
  `[SCENE_REG] add_view(...) clone=...` so the per-view bookkeeping
  is visible without UI instrumentation.
- `remove_view(panel_id)` — destroys the `ViewScene` (which destroys
  every `RepInScene` it owned).
- `sync_loaded_reps(loaded_rep_paths)` — fired on every
  `state.change("ui_loaded_rep_paths")`. For each scene, adds any
  loaded rep that isn't there yet and removes any rep that's no
  longer loaded. After each rep add, `_eager_setup_rep_in_scene`
  force-builds the per-view extractor (Hides the legacy in scene
  view) and mirrors the active panel's ColorBy onto the new scene.
- `replicate_view(src_view_id, dst_view_id, *, concerns=(...))` —
  snapshot/apply iteration: for each rep in src, applies every
  concern's `snapshot_X()` → `apply_X(snap)` onto dst. Concerns
  default to `("threshold", "slice", "clip", "ijk_slicers")`,
  applied in dependency order (ijk_slicers before threshold so the
  chain attaches to the correct upstream set).
- `get_rep(view_id, rep_path)` — the main facade for dispatchers.
- `mirror_legacy_ijk_state(rep_path, legacy_ijk)` — defined but no
  longer auto-fired; reserved for one-shot snapshot/apply use.

#### `ViewScene`

Thin owner of the per-view clone proxy + the rep map. `add_rep` /
`remove_rep` lifecycle, `reps()` iterator, `destroy()` tears
everything down.

`_create_clone()` uses `representation._create_plugin_filter_proxy`
which transparently falls back from `pvsimple` to
`vtkSMSessionProxyManager.NewProxy` when the pvsimple namespace
hasn't refreshed after `LoadPlugin`. If the plugin doesn't ship
`vtkEPCCollectorClone` at all the scene anchors on the shared
collector source instead (logged `clone=shared`).

#### `RepInScene`

> **ElementType refactor (Option A).** `RepInScene` still owns the
> per-(rep, view) STATE described below (`_extractor`, `_per_view_ijk`,
> `_channel_extractors` / `_marker_extractors`, `_slice_plane` /
> `_clip_plane`, `_chain`), but the per-type BEHAVIOUR (source construction,
> visibility, channel/marker child management, rendered / colorable source
> sets) is delegated to `self.element_type` — the `app/core/element_type/`
> hierarchy, resolved via `for_path` — to which `RepInScene` passes itself as
> `ris`. The methods below (`source()`, `_ensure_extractor`,
> `_ensure_per_view_ijk`, `set_channel_visible`,
> `_refresh_parent_rep_visibility`, …) are **thin delegators**. Details:
> [REFACTOR_ELEMENT_TYPE_HIERARCHY.md](REFACTOR_ELEMENT_TYPE_HIERARCHY.md) +
> [TYPES_PARTICULARITES.md](TYPES_PARTICULARITES.md).

The heart of the per-(rep, view) refactor. Three responsibilities:

1. **Source resolution.** `source()` returns the proxy that
   represents this rep in this view — the per-view extractor for
   non-IJK, the per-view IjkGrid's rep_data for IJK, falling back
   to the legacy shared source when the per-view path can't be
   built (Phase 2 fallback / no property picked yet on IJK).

2. **Slice / clip / threshold ownership.** `slice_set` / `clip_set`
   create lazy `SlicePlane` / `ClipPlane` filters chained on the
   per-view source. `_chain` (non-IJK) or `_per_view_ijk._chain`
   (IJK) hold the per-view threshold chain. Visibility is managed
   by `_refresh_chain_visibility` (the primary source is hidden
   when a chain tip is shown).

3. **Snapshot / apply primitives** per concern:
   `snapshot_threshold_chain / apply_threshold_chain`,
   `snapshot_slice / apply_slice`,
   `snapshot_clip / apply_clip`,
   `snapshot_ijk_slicers / apply_ijk_slicers`.
   All four are strictly per-view — never touch the legacy shared
   instances. Used by `replicate_view` (view split inheritance) and
   by the `copy_<concern>_from_view` controllers (per-concern Copy
   UI).

The `_v<view_id>` suffix on registration names is the convention
that lets `multi_view._is_per_view_source(name)` detect per-view
proxies and skip them when mirroring visibility from a ref view to
a new view (otherwise `GetDisplayProperties` would lazily create
phantom Vis=1 displays in the wrong view).

#### Per-view IjkGrid pipeline gotchas

A cluster of subtle ordering bugs lives in the per-view IjkGrid path
(`RepInScene._ensure_per_view_ijk` → `IjkGrid.set_node_id`). All four
were needed for a TimeSeries IjkGrid (`dynamicDiscreteProp.epc`) to
render and recolor correctly:

1. **Clone must execute before the per-view extractor is built.**
   `_ensure_per_view_ijk` calls `clone.UpdatePipeline()` *before*
   constructing the per-view `EnergisticsExtractor`. The extractor's
   `RequestDataObject` peeks at the clone's assembly to decide its
   output type; an un-executed clone has an empty assembly → the
   extractor falls back to a `vtkPolyData` placeholder → every
   downstream `ExplicitStructuredGridCrop` rejects it with
   "Input ... is of type vtkPolyData, but a vtkExplicitStructuredGrid
   is required".
2. **rep_data needs a full `UpdatePipeline()` (data pass) before the
   slicers chain on it** — `UpdatePipelineInformation()` alone doesn't
   settle the concrete output type. The engine's `data_load.run` also
   forces a data pass on the rep_data extractor + each slicer (not
   just an info pass) so the property arrays propagate downstream.
3. **`_refresh_parent_rep_visibility` defers to `ijk.show()` for IJK
   reps.** For non-IJK the "rep source" is the rendered geometry; for
   IJK the `_src_extract_init` extractor is NOT — `ijk.show()` hides
   it whenever any slicer is visible. A blind `Show(self.source())`
   here repainted the un-cropped grid as a SolidColor block over the
   slicers (the red overlay seen after a 2nd property selector
   flipped the active array via `on_active_array_change`).
4. **The activator's `ijk_lookup` is per-view-aware**
   (`boot._ijkgrid_by_rep_path` resolves the drawer-target view's
   per-view IjkGrid, legacy fallback). The legacy IjkGrid's sources
   are Hidden in the panel, so a legacy-only lookup made
   `_resolve_color_target_source` find no visible target and bail
   before `update_color_editor` — leaving the Colors panel stuck on
   SolidColor when the active node differed from the eye-coloured one.

#### Per-view scoped LUT / PWF naming

`source_resolver.resolve_target_scoped_lut` and the rendering path
(`apply_color_array` → `swap_to_scene_tfs`) MUST key the per-(scene,
array) LUT on the **sanitized VTK array name**
(`utils.naming.make_valid_vtk_name`), not the raw RESQML title. A
title like `"Pressure (PRESSURE)"` materializes as the VTK array
`"PressurePRESSURE"`; keying the COE's scoped LUT on the raw title
made the editor look up a non-existent array (empty range) and edit a
different LUT proxy than the displays rendered through.

> **C++ invariant (array naming).** As of the array-naming consistency
> fix, **every** colorable VTK array name is produced by C++
> `MakeValidNodeName` — grid/UG properties (both the multi-proc AND the
> single-proc/default ctor) and wellbore-log channels alike. Before the
> fix the single-proc grid ctor and the channel mapper named arrays with
> the **raw** title, so Python had to probe the source to discover which
> name a given array actually carried (`source_resolver.real_base_name`).
> `make_valid_vtk_name` is now a **byte-for-byte mirror** of C++
> `MakeValidNodeName`, including the leading-`_` prepend it applies when
> the stripped result is empty or starts with a digit / `-` / `.` (e.g.
> `"123abc"` → `"_123abc"`). The Python source-probe helpers
> (`real_base_name`, the title-then-sanitized fallbacks in
> `resolve_array_for_path` / stats `_original_source_and_name`) are kept
> as a **defensive layer** that tolerates an out-of-date plugin build
> (raw-named arrays); they can be trimmed once every deployed plugin
> carries the fix.

New per-scene PWFs default to **flat opacity 1**
(`ViewScene.get_or_create_pwf` flattens ParaView's seeded 0→1 ramp
when it's still the untouched two-stop default, preserving the
X-extent). NaN opacity is a separate `NanOpacity` on the LUT (default
0 — transparent), so a flat-1 valid-value curve and transparent NaN
cells coexist, and a user's later opacity edits are never re-flattened
(cached PWFs return early).

### UI Layer

The UI is described declaratively with Trame's vuetify3 widgets
inside Python. Key conventions:

- **Tuple binding** `prop=("state_name", default)` exposes the state
  to Vue with two-way reactivity.
- **`click=(callable, "[args_js]")`** auto-registers a trigger and
  evaluates the second string as a JS expression returning the args
  list.
- **`v_if=`, `v_else_if=`, `v_for=`** map directly to Vue directives.
- **`v_slot_prepend="{ item }"`** etc. expose tree node data inside
  custom templates.

`_eye_slot(controller)` (in `tree_views.py`) renders the visibility
eye on representation nodes and the active-array eye on data-array
nodes. The two are mutually exclusive (`v_if` / `v_else_if`).

`_wire_dependency_expansion(...)` (also in `tree_views.py`) is a
`@state.change` handler that intercepts every change of
`ui_select_node_*` and expands the selection to include implicit
dependencies (`Channel/Marker → parent Wellbore's Trajectory`,
`grouping → all descendants`).

`_wire_select_to_active(...)` automatically activates the most
recently checked node so the user sees its panel right away.

---

## State Variables (Trame)

The most important state variables — there are more, but these are
the ones you need to know to wire a new feature.

### Trees / Selection

- `ui_subtree_{reservoir,surface,well}` — list of nested dicts
  rendered by the three `VTreeview`s.
- `ui_opened_{reservoir,surface,well}` — set of expanded node ids.
- `ui_select_node_{reservoir,surface,well}` — list of checked node
  ids per tab.
- `ui_active_node_{reservoir,surface,well}` — list of active node
  ids per tab (single-element when active, empty otherwise).
- `_prev_select_{reservoir,surface,well}` — internal previous-state
  cache used by the dependency-expansion + select-to-active wirings.

### FESPP Pipeline

- `fespp_data_selectors` — the concatenated path list pushed to the
  collector proxy. Driven by the `Selector`.
- `file_loaded` — True once the first `add_file` succeeded.

### Visibility / Coloring

Flat (legacy) and per-view buckets coexist: the flat vars mirror the
**active panel's** bucket so consumers that don't know about views
still work. The bucket-of-buckets vars are the source of truth.

- `ui_loaded_rep_paths` — paths of representations currently
  materialised in ParaView (across every view). The eye icon is
  rendered next to those rows.
- `ui_loaded_array_paths` — paths of data-array nodes (Property,
  TimeSeries, MultiRealization, …) whose data is loaded.
- `ui_hidden_rep_paths_by_view` — `{panel_id: [rep_path, …]}`, the
  per-view "hidden" set (eye closed on that view's chip). Source of
  truth for the per-view eye chips in the tree.
- `ui_hidden_rep_paths` — flat mirror of the **active** panel's
  bucket. Kept in sync by `multi_view._mirror_active_hidden_state`
  on panel-activation events.
- `ui_active_array_by_rep_by_view` — `{panel_id: {rep_path:
  array_path}}`, per-view ColorBy choices.
- `ui_active_array_by_rep` — flat mirror of the **active** panel's
  bucket; also written directly by the load handler on first activation.
- `ui_active_realization_by_array_by_view` — `{panel_id: {array_path:
  idx}}`, the per-view realization pick for each MR array. Drives
  the per-view RealizationPicker overlay; consumed by
  `source_resolver.apply_color_array(realization_idx=…)` and by
  `threshold_dispatch._resolve_vtk_array_name`.
- `solid_color_by_rep` — `{rep_path: "#RRGGBBAA"}`, picker value
  per rep (not per view — solid color is a property of the rep).
- `tree_chip_color_by_path` — derived: `{rep_path: "PROPERTY" |
  hex_color}`, drives the per-row color chip in the trees.
- `active_representation_path`, `active_color_array_name`,
  `active_property_kind` — set by the activator from the active
  node, drives the Attributes panel.

### Multi-View

- `fespp_render_panels` — `[{id, title}, …]`, the list of render
  (non-diff) panels currently open. Drives the per-view eye chips
  in the tree and the "Copy from view X" dropdowns.
- `fespp_active_panel_id`, `fespp_active_panel_title` — the
  currently-focused render panel. The dispatchers read this only
  as a boot-window fallback now; the Attributes drawer's edit
  panels resolve their target via `drawer_target_view_id` (which
  itself follows `fespp_active_panel_id` unless pinned).
- `drawer_target_view_id`, `drawer_target_view_pinned` — the
  Attributes card's target view picker. `drawer_target_view_id` is
  the panel id the edit dispatchers (`slice_dispatch`,
  `clip_dispatch`, `threshold_dispatch`, `slicer_dispatch`) operate
  on. In follow mode (`drawer_target_view_pinned=False`) it
  auto-syncs to `fespp_active_panel_id`; in pinned mode the user
  picked it via the VSelect rendered at the top of the Attributes
  card body (NOT in the card toolbar — the picker was moved into
  the body so narrow drawer widths don't squash it). Auto-depin
  fires when the pinned view is closed (handled in
  `boot._on_render_panels_change`).
- `fespp_stats_panel_id` — non-empty string when the singleton
  "Stats" dockview tab is currently open. Set by
  `multi_view._add_stats_panel`, cleared on its `_on_view_closed`.
  Read by `controller.toggle_stats_display` to decide whether to
  create a new stats tab when the user pins their first property
  (avoiding duplicate tabs / a fresh one on every pin).
- `ui_stats_compare` — `{array_path: [item_key, …]}`, the
  **unified** per-property cart that drives BOTH the floating
  Compare-stats panel (numeric matrix) AND the singleton
  Compare-distribution panel (overlay traces). One cart per
  property — separate `_num` / `_dist` carts collapsed into this
  single var per the 2026-06 refactor (mixing properties is
  structurally impossible since the dict is keyed by array_path).
  Item keys are `f"{array_path}|{row_kind}|{row_id}"`. Mutated by
  `stats_dispatch.toggle_compare` (server trigger
  `stats_compare_toggle`); fully cleared for a property by
  `stats_compare_clear`. Carts persist across `ui_stats_tables`
  recomputes — stale keys whose row no longer exists are filtered
  out of `ui_stats_compare_items` rather than the panel templates.
- `ui_stats_compare_panel` — `{array_path: panel_id}`, singleton
  tracker for the floating Compare-stats panels (replaced the
  old `VDialog` per the 2026-06 refactor — see
  `_add_stats_compare_panel` in `multi_view.py`). The per-card
  **Compare** button in `descriptive_stats_panel` fires the
  `open_compare_stats(array_path)` trigger; `boot._open_compare_stats`
  spawns a fresh dockview panel via
  `mv.add_view(kind="stats_compare")` if no entry exists, else
  re-pushes the latest items into the existing panel. Entries
  are cleared by `multi_view._on_view_closed` when the panel
  tab is closed. The presence of an entry is what gates the
  `_refresh_compare_stats(array_path)` live-update on toggle /
  clear.
- `ui_stats_compare_dist_panel` — `{array_path: panel_id}`,
  singleton tracker for the Compare-distribution floating
  panels. Populated by the `open_compare_distributions` trigger
  (fired from the Compare-stats panel's **Show distributions**
  toolbar button — no longer from a separate card-header
  button); entries are removed by `multi_view._on_view_closed`
  when the panel's dockview tab is closed (so the next click on
  *Show distributions* spawns a new panel rather than orphaning
  the cart). The presence of an entry is what gates
  `_refresh_compare_dist` and the toggle / clear live-updates.
- **Per-panel option vars (Compare-stats)** —
  `_open_compare_stats` seeds and reads the following
  `panel_id`-suffixed vars (one set per active stats_compare
  panel), bound by `StatsComparePanel(panel_id)`:
  `ui_stats_compare_array_path_<panel_id>` (the property the
  panel binds to),
  `ui_stats_compare_visible_metrics_<panel_id>` (list of metric
  keys SHOWN in the matrix — inverted semantics vs the old
  `hidden_metrics` flag; default = every metric, toolbar menu
  drops individual keys),
  `ui_stats_compare_baseline_<panel_id>` (item_key used as the
  reference row in Δ-comparison mode; empty string `""` means
  `(no baseline)` → fall back to extrema shading),
  `ui_stats_compare_order_<panel_id>` (list of item_keys
  capturing the user's drag-to-reorder layout; applied in
  `_refresh_compare_stats` BEFORE baseline pinning so the
  baseline stays anchored on the left of whatever order the
  user picked),
  `ui_stats_compare_transposed_<panel_id>` (bool),
  `ui_stats_compare_sort_key_<panel_id>` (metric key for sort),
  `ui_stats_compare_sort_asc_<panel_id>` (bool),
  `ui_stats_compare_items_<panel_id>` (resolved item list pushed
  by `_refresh_compare_stats`),
  `ui_stats_compare_csv_<panel_id>` (base64 data URL for the
  download button),
  `ui_stats_compare_annotations_<panel_id>`
  (`{metric_key: {item_idx: tag}}` dict pushed by
  `compare_matrix.highlight_annotations_for_items`; the table
  template reads it for the `:class="{cmp-cell-min/max/pos/
  neg/eq}"` cell bindings AND the `it.row[mk]`-driven Δ chip
  in baseline mode via the auxiliary
  `annotations._deltas[metric_key][item_idx]` entries — see
  the `compare_matrix` module section below). All of them are
  cleared on `multi_view._on_view_closed` when the panel tab
  is closed (the cleanup loop in multi_view.py iterates the
  full list including `order` / `annotations` so no stale
  state leaks across panel respawns).
  The old `ui_stats_compare_highlight_<panel_id>` /
  `ui_stats_compare_normalize_<panel_id>` /
  `ui_stats_compare_topN_<panel_id>` /
  `ui_stats_compare_hidden_metrics_<panel_id>` /
  `ui_stats_compare_pinned_<panel_id>` vars were dropped in
  the 2026-06 feedback round — highlight mode now derives
  from `baseline_key` (empty → extrema, set → baseline) and
  the heatmap / Top-N / pin features were taken out wholesale.
- The Stats dockview panel opens as a **floating overlay** —
  `_add_stats_panel` calls
  `self.add_panel(panel_id, title, template, floating={"width":
  1400, "height": 450, "position": {"left": 100, "top": 100}})`.
  Dockview routes the `floating` kwarg straight to its
  `addFloatingGroup` internal API (verified in the JS bundle's
  panel-routing block: `typeof e.floating === "object" ?
  this.addFloatingGroup(group, e.floating) : ...`). The
  floating frame brings its own chrome — 1px border + drop
  shadow + 8 resize handles + drag-to-move on the tabstrip
  empty area — so the stats template no longer paints its own
  blue "active panel" inset (it visually fought the floating
  border for no semantic value; Stats is a singleton so the
  active-for-editing cue isn't needed).

  Entry points + lifecycle:
  * Toolbar `mdi-chart-box-outline` button →
    `controller.open_stats_panel` — pure open/close toggle. If
    the panel exists, calls `mv.remove_panel(existing)`; else
    `mv.add_view(kind="stats")`. To raise an obscured floating
    window the user clicks twice (close + reopen) and the
    freshly-added group lands at the top of dockview's z-index
    singleton (`be.push(el)` in the bundle). Earlier iterations
    tried close+reopen on every click to "raise to front"
    automatically, but that meant a click on a visible Stats
    window destroyed and recreated it (visible flash, no
    semantic value) — the toggle is simpler and matches the
    "click to dismiss" mental model users have for floating
    panels.
  * Tree chart-icon per Property row →
    `controller.toggle_stats_display` →
    `_open_stats_if_closed()` (helper renamed from the previous
    `_ensure_stats_panel`). First-time pin on a property opens
    the floating window; subsequent pins are no-ops (the user is
    just adding more cards, not asking for focus or raise).
  * Close = the tab's `×` (dockview fires `remove_panel` event
    identically for floating panels, so `_on_view_closed`
    handles cleanup the same way as it did for docked tabs).
  * Re-dock = `Shift+drag` the tab title into a grid drop zone
    — native dockview gesture, no custom code needed.

  The same `Shift+drag` gesture promotes any DOCKED panel
  (render, diff) to a floating window with no code on our side:
  dockview's tab pointer handler dispatches on the
  `shiftKey` modifier and calls `addFloatingGroup` on the
  source panel directly (`if (r && !h && o.shiftKey) ...
  addFloatingGroup(...)` in the bundle). The panel instance is
  reused (`skipDispose: true` inside the moving lock), so the
  pv_view, VtkRemoteView mount, per-view scene_registry entry,
  view_links and per-panel state vars all survive the
  transition — same preservation guarantee as the Stats overlay
  open path. We deliberately do NOT add a dedicated "float
  this panel" button on the per-panel chrome: the gesture
  exists, exposing it as a button would require vendoring a
  patched `trame_dockview.umd.js` (the wrapper only exports
  addPanel / removePanel / activePanel from setup), and the
  Shift modifier is a discoverable enough convention for power
  users.

  Per-property state (`ui_stats_panel_state[array_path]` —
  Originals list, Custom-row snapshots, etc.) is decoupled
  from the tab's existence: closing the tab does NOT clear the
  dict, so reopening via the toolbar button restores every
  card with its previous Custom rows in place. Removal of a
  property from `ui_stats_pinned_paths` (via the tree's chart-
  icon or the card's ×) drops just that key from the state.
- `ui_stats_panel_minimized` — boolean toggled by the minimize
  button in the Stats panel template (multi_view._add_stats_panel
  renders it via the negative-top overflow trick into the
  floating window's tabstrip area). When True, the JS watcher in
  ui/shared/scripts.py (setupStatsMinimize) mirrors the flag to
  a `fespp-stats-minimized` class on `<body>`; CSS in
  ui/shared/styles.py then collapses the floating shell to a
  single tabstrip row via
  `body.fespp-stats-minimized .dv-resize-container:has(.fespp-stats-panel)`.
  Same `:has()` rule also pins the
  `.dv-render-overlay-float` mirror element (dockview's resize
  observer copies the shell's bounding rect onto it on every
  change). `!important` beats dockview's inline style.height. The
  rule also disables `[class*='dv-resize-handle']` pointer events
  while minimized so the user can't drag-resize to a value that
  becomes the "restored" height. Restore is automatic — clearing
  the body class lets the original inline height (whatever the
  user resized to before minimizing) take effect again.
- `ui_stats_panel_maximized` — mutex companion of
  `ui_stats_panel_minimized`. Toggled by the
  `mdi-window-maximize` button next to the minimize button in
  the Stats tab chrome; the Vue click handlers in
  `_add_stats_panel` clear the opposite flag on every toggle so
  the two states stay exclusive (no enforcement at the JS or
  CSS layer — purely a UX convention).
  `setupStatsMinimize` in `ui/shared/scripts.py` mirrors BOTH
  flags to body classes in one pass (`fespp-stats-minimized` /
  `fespp-stats-maximized`) and polls both in the watcher.
  The CSS rule in `ui/shared/styles.py` for maximize pins
  `top:0; left:0; right:auto; bottom:auto; width:100%;
  height:100%` on the `.dv-resize-container:has(.fespp-stats-
  panel)` shell — `right:auto` and `bottom:auto` are explicit
  because dockview's `setBounds` can write `bottom`/`right`
  instead of `top`/`left` when the user resized via the
  bottom-right corner; without the explicit auto, the residual
  `right` value would push the maximized shell off-screen. Same
  `pointer-events: none` on `[class*='dv-resize-handle']` so a
  drag-resize while maximized doesn't bleed bad bounds into the
  inline style.
- `ui_distribution_figure` — single `{"data": [...], "layout":
  {...}}` dict bound to the floating Distribution overlay's
  Plotly Figure widget. trame-plotly's `Figure(state_variable_
  name="ui_distribution_figure", ...)` owns the state binding
  internally — it writes `data=(f"{var}.data",)` and
  `layout=(f"{var}.layout",)` to its super, so passing those
  kwargs from our side would crash with "got multiple values
  for keyword argument 'data'". Server-side updates assign the
  whole dict at once (e.g. `state.ui_distribution_figure =
  {"data": [trace], "layout": layout}`). Traces are pre-binned
  via `numpy.histogram` (for continuous) or `Counter` (for
  discrete) and pushed as `type:"bar"` — NEVER `type:
  "histogram"` (which would re-bin client-side from raw values
  and choke on million-cell arrays). WS payload stays ~few KB
  regardless of source array size.
- `distribution_dispatch.compute_histogram_figure(state, tree,
  scene_registry, source_registry, array_path, row_kind, row_id,
  *, display_mode, nbins, log_y, show_stats, cumulative, norm,
  return_meta)` — builds a `plotly.graph_objects.Figure` from one
  Stats row. Every option kwarg may be left None to take the
  default in `_DEFAULTS` (`bars`, 50 bins, linear Y, no stats
  overlay, raw counts). When `return_meta=True` the function
  returns `(fig, meta)` where meta is `{kept, total, nan,
  bin_centers, bin_heights, bin_widths, chart_title, xaxis_title,
  yaxis_title}` — the binned data is surfaced so CSV export
  doesn't re-run the compute. Display-mode logic lives in
  `_shape_trace_for_mode`: `bars` → `go.Bar`; `line` →
  `go.Scatter(mode="lines+markers", line.shape="hv")` (step);
  `curve` → `go.Scatter(mode="lines", line.shape="spline",
  fill="tozeroy")` (smoothed area under the curve). Source
  resolution mirrors `stats_dispatch`: Original rows ride
  `source_registry.get(rep_path)` (unfiltered), View rows ride
  `_resolve_rendered_inputs(scene_registry, source_registry,
  rep_path, view_id)` (post-clip/slice/threshold output). NaN
  values dropped pre-binning so kurtosis / skewness peers in the
  Stats table stay meaningful for the same subset. The X-axis
  title is built as `<Property name> (<unit>)` via
  `stats_dispatch._unit_for_array_path(tree, array_path)` —
  when the helper returns `""` (current FESPP build, see the
  RESQML accumulator), it degrades cleanly to `<Property name>`
  alone with no trailing parenthesis. Discrete / categorical
  rows force the X-axis label to `"Category"` regardless. The
  meta dict now carries an extra key `legend_label` —
  `", ".join(label_parts)` where `label_parts` is the same
  `[real N, ts <label>]` sequence the chart title already
  pulls in for its `(real, ts)` suffix. Empty when neither MR
  nor TS applies, in which case downstream consumers fall back
  to `chart_title` or the row key.
- `distribution_dispatch.compute_compare_figure(..., selection_keys,
  *, return_meta=...)` — same option surface as the single-row
  compute, propagated to every per-row trace so the compare panel
  renders all rows in one consistent shape (mode, log, norm). The
  `show_stats` toggle is intentionally suppressed for compare
  panels (per-row mean / median lines pile up and obscure the
  trace shapes); the panel UI hides the switch via the
  `ui_distribution_is_compare_<panel_id>` flag. Per-trace
  legend names come from the per-row meta's `legend_label`
  (not the longer `chart_title`) — the cart guarantees every
  selected row shares the same `array_path`, so the property
  name is redundant in the legend; only the real / TS axes
  vary across traces. The compare X-axis title reuses
  `_unit_for_array_path` against that first shared
  `array_path` so both single-row and compare panels label the
  axis consistently.
- `distribution_dispatch.build_csv_from_meta(meta)` — renders a CSV
  string from the meta dict. Single-row → 3 cols (center, height,
  width). Compare → one column triplet per trace, padded by index.
  Header `height` label tracks the `yaxis_title` (lowercased) so
  density / probability renders carry the right column name.
- `@server.trigger("open_row_histogram")(array_path, row_kind,
  row_id)` — fired by the per-row `mdi-eye-outline` icon next to
  the Source label in the Stats panel (no separate `Distr.`
  column). Calls `_spawn_distribution_panel(kind="single",
  context={array_path, row_kind, row_id})`.
- `@server.trigger("open_compare_distributions")(array_path)` —
  singleton multi-trace overlay variant. Reads the property's
  unified `state.ui_stats_compare[array_path]` cart, calls
  `_spawn_distribution_panel(kind="compare",
  context={"array_path": array_path, "kind": "compare"})` on
  first invocation, then registers the resulting `panel_id` in
  `state.ui_stats_compare_dist_panel[array_path]` so subsequent
  calls reuse the same panel (see `_refresh_compare_dist` for
  the live-update / unregister flow). Wired to the
  **Show distributions** button on the Compare-stats panel's
  toolbar (no card-header button anymore).
- `boot._spawn_distribution_panel(kind, context)` —
  multi-instance panel factory. Does
  `mv.add_view(kind="distribution")` (returns the new panel id),
  stores `context` under
  `state.ui_distribution_contexts[panel_id]`, seeds per-panel
  option vars with their defaults so the toolbar's `v_model`
  bindings bind to known values, registers a per-panel
  `state.change` watcher on every option var (runtime form:
  `state.change(*var_names)(callback)`), and triggers the initial
  `_refresh_distribution(panel_id)` push. The watcher calls
  `_refresh_distribution(panel_id)` which reads the stored context
  + the option vars, re-runs either `compute_histogram_figure` or
  `compute_compare_figure` with `return_meta=True`, pushes the
  figure through
  `controller.update_distribution_figure_<panel_id>(fig)`, and
  writes the meta (`{kept, total, nan}`) + the CSV data URL
  (`data:text/csv;base64,...`) to their per-panel state vars so
  the toolbar badge + download link update in lockstep.
- Distribution panels are MULTI-INSTANCE: no singleton tracker,
  no toolbar entry-point, no minimize/maximize chrome. Every
  per-row Hist click and every Compare-histograms click spawns a
  fresh floating dockview panel via
  `multi_view.add_view(kind="distribution")`. The user closes
  with the dockview tab's `×`; drag/resize are native dockview
  handles. Per-panel state bindings:
  `ui_distribution_figure_<panel_id>` (Plotly figure payload, set
  by trame-plotly's Figure widget),
  `ui_distribution_mode_<panel_id>` (`"bars"|"line"|"curve"`),
  `ui_distribution_nbins_<panel_id>` (int 5..500),
  `ui_distribution_log_y_<panel_id>` (bool),
  `ui_distribution_show_stats_<panel_id>` (bool),
  `ui_distribution_cumulative_<panel_id>` (bool),
  `ui_distribution_norm_<panel_id>` (`"count"|"density"|"probability"`),
  `ui_distribution_meta_<panel_id>` (badge payload),
  `ui_distribution_csv_<panel_id>` (export data URL),
  `ui_distribution_is_compare_<panel_id>` (UI gating flag).
  Controller method `controller.update_distribution_figure_<panel_id>`
  is registered by `DistributionPanel(panel_id).render()`.
  `_on_view_closed` clears all per-panel state vars + drops the
  panel entry from `ui_distribution_contexts` + delattr's the
  controller method.

Entry points:
- `fespp_settings_scopes` — `[{value, title}, …]`, drives the
  Scope select in `GlobalSettingsDialog` ("Global" + every panel
  including diff).
- `fespp_diff_panel_id`, `fespp_diff_ready`, `fespp_diff_computing` —
  the singleton diff panel lifecycle.
- `view_links` — `{panel_id: [panel_id, …]}`, per-panel
  camera-broadcast group. Symmetrical (membership is mirrored on
  both sides). Read by `_sync_camera_from` on `EndAnimation`.
- `new_view_dialog_*` — open / pre-fill state for
  `NewViewContentDialog`.

### Threshold / Slice / Clip / IJK Slicers (UI flat vars)

The Attributes drawer panels bind to flat vars; the
`fespp_active_panel_id` change handler republishes the active view's
state into them via `slice_dispatch.publish_slice_state` /
`clip_dispatch.publish_clip_state` /
`threshold_dispatch.refresh_threshold_ui_for_active_grid` /
`_push_active_ijk_state_to_ui`.

- `ui_slice_enabled`, `ui_slice_axis`, `ui_slice_offset`,
  `ui_slice_offset_{min,max,step}`, `ui_slice_bounds`.
- `ui_clip_enabled`, `ui_clip_axis`, `ui_clip_offset`,
  `ui_clip_inside_out`, `ui_clip_offset_{min,max,step}`.
- `ui_threshold_chain`, `ui_threshold_arrays_available`,
  `ui_threshold_pending_action` (sentinel for add / delete /
  set_range / set_visible events). Each chain entry now carries
  `kind` (`"Continuous"` / `"Discrete"` / `"Categorical"`) plus
  `unique_values` (sorted distinct values for Discrete /
  Categorical ticks) and `labels` (`{value: name}` map for
  Categorical entries, read from the LUT's `Annotations` at
  threshold creation). The threshold panel dispatches the slider
  variant on `entry.kind`. Resolution lives in
  `extract_block.resolve_chain_kind(tree, rep_path, array,
  source_proxy, assoc)`; entries exceeding 64 unique values are
  demoted to `"Continuous"` so the UI stays usable.
- `ui_stats_pinned_paths` — `[array_path, …]`, the tree-driven set
  of properties whose stats are shown in the singleton Stats
  dockview tab (`multi_view._add_stats_panel`). Toggled by
  `controller.toggle_stats_display(array_path)` fired by the
  tree's `mdi-chart-box-outline` button (see `_stats_slot` in
  `tree_views.py`). The chart icon only renders on property
  nodes whose `id` is in the tree's selection list (per-tree:
  `ui_select_node_reservoir` / `_surface` / `_well`) — pinning
  stats on an unchecked property has no use case and would just
  clutter the row. On first pin (no `fespp_stats_panel_id`),
  `toggle_stats_display` opens the Stats tab itself; subsequent
  pins reuse the existing tab.
- `ui_stats_panel_state` — `{array_path: {"originals":
  [{"id", "pinned", "real_idx", "ts_idx"}, …]}}`, per-pinned-
  property panel state. The first `originals` entry is always
  `{"id": "default", "pinned": False, "real_idx": None, "ts_idx":
  None}` and the **default row** carries inline real / TS
  selectors that the user can edit (wired through
  `controller.stats_set_original_real_idx` /
  `controller.stats_set_original_ts_idx`). The pin icon snapshots
  the default's current selectors into a new `custom-<n>` row
  (frozen — custom rows are read-only). Custom rows can be
  removed via `controller.stats_unpin_original`. The default row
  is never removable.
- `ui_stats_tables` — `{array_path: {"title": str,
  "rep_title": str, "kind": str,
  "rows": [{"kind": "original"|"view", "id", "label", "real_idx",
  "ts_idx", "ts_label": str, "pinned"?: bool,
  …vtkDescriptiveStatistics output}, …],
  "available_realizations": [int, …],
  "available_timesteps": [float, …]}}`. Computed by
  `stats_dispatch.publish_descriptive_stats` from the pinned set
  + per-property panel state + every render view's current state.
  `rep_title` carries the enclosing representation's human title
  (resolved via `_rep_title_for_array_path`); used by the stats
  card header as a dimmed `<RepTitle> /` prefix so two reps that
  share an identically-named property can still be told apart.
  Original rows anchor on `source_registry.get(rep_path)`
  (unfiltered); View rows anchor on
  `_resolve_rendered_inputs(scene_registry, source_registry,
  rep_path, view_id)` which calls `sources_for_rep_path` AND
  augments with the rep's per-view `clip_output` /
  `slice_output`, then filters by Visibility=1. Without the
  augmentation, enabling clip / slice on a non-IJK rep would hide
  the upstream source and the per-view row would disappear — the
  resolver only sees the canonical source list. `kind`,
  `available_realizations` and `available_timesteps` drive the
  default Original row's inline real / TS VSelects.

  Row `label` carries the Source-column text — property title for
  Original rows, `f"{title} On {view_title}"` for View rows.
  Realization Index and Time Step now live in their own
  kind-gated columns rather than the label suffix; `real_idx` /
  `ts_idx` are the raw values, `ts_label` is the human-readable
  date (`YYYY-MM-DD`, time-of-day stripped by
  `time_realization._shorten_time_label`).
- `ui_stats_compare_items` — `[{"key", "row", "propertyTitle",
  "column_label", "extrema": {metric_key: "min"|"max"}}, …]`.
  `extrema` is populated server-side in `publish_compare_items`
  whenever ≥ 2 items are selected: for every numeric metric we
  find the min / max value across the cart and tag the carrying
  items. `StatsComparePanel` reads `item.extrema[metric_key]`
  and paints the cell green (max) / amber (min). Done
  server-side so Vue `:style` bindings don't have to aggregate
  across v-for peers on every render. The traversed key list
  (`_COMPARE_METRIC_KEYS` in `stats_dispatch.publish_compare_items`)
  now includes `"Q1"`, `"Median"`, `"Q3"` alongside the
  vtkDescriptiveStatistics keys, so the IQR cells in the dialog
  carry the same extrema highlight as Min / Max / Mean.
  `column_label` is the per-item header text rendered in the
  Compare-stats matrix; for non-View rows it carries a
  `<rep_title> / <real N, ts label>` prefix sourced from the
  parent table's `rep_title` (see `ui_stats_tables` above) so
  two reps that ship the same property name stay tellable apart
  at the column-header level. View rows reuse their own label
  unchanged (it already encodes the view's identity).

Stats-row contract additions worth calling out (lockstep with
`stats_dispatch._compute_one_variable`, around line 235 of that
module):

- **`Q1` / `Median` / `Q3`** — three new numeric keys on every
  row dict, computed via `numpy.percentile(arr, [25, 50, 75])` on
  the same NaN-stripped array `_compute_one_variable` already
  builds for the vtk filter (the threshold output, fetched via
  `dsa.WrapDataObject(...).PointData / CellData`). `Median` is
  the IQR centre — it differs from vtk's `Mean` by definition, so
  both are exposed. Failures (zero-length array, all-NaN slab)
  fall through silently — the keys are simply absent on the row
  and the UI renders the same em-dash as for any missing metric.
- **`stats_dispatch._unit_for_array_path(tree, array_path)`** —
  helper that walks the `vtkDataAssembly` from the array_path,
  inspects `find_attribute_value(node_id, "uom")`, and returns
  the trimmed unit string (or `""` when absent). Currently
  always returns `""` because FESPP's
  `ResqmlDataRepositoryToVtkPartitionedDataSetCollection` does
  not yet write `uom` (nor `resqmlKind`) as
  `vtkDataAssembly` node attributes — see the RESQML accumulator
  for the C++-side fix that lights this up. Once the C++ side
  ships, the Distribution panel X-axis label
  (`<Property> (<unit>)`) and any future unit-aware widget pick
  up the value with zero Python-side change.
- **`stats_dispatch.{toggle,clear}_compare`** — the unified
  per-property cart primitives (the 2026-06 refactor collapsed
  the separate `_num` / `_dist` carts into a single one).
  `toggle_compare(state, array_path, item_key)` flips `item_key`
  in `state.ui_stats_compare[array_path]`; `clear_compare(state,
  array_path)` drops the whole cart for one property. Wired via
  the `stats_compare_toggle` / `stats_compare_clear` server
  triggers (registered in `boot.py`); both triggers additionally
  call `_refresh_compare_stats(array_path)` and
  `_refresh_compare_dist(array_path)` for any panel currently
  registered on that property so the live updates keep matrix +
  overlay in lockstep. Because each property's cart is a
  separate list, no cross-property gating /
  rejection-snackbar is needed — mixing apples with kg is
  structurally impossible. The UI gates the **Cmp** column +
  **Compare** button to MR / TS cards only: cells render under
  `ui_stats_tables[array_path].is_mr || .is_ts` and the
  `Compare` button sits under the same gate (`_can_cmp` in
  `descriptive_stats_panel._render_card_header`). Plain
  Continuous cards therefore never expose the cart UI at all.
- **Compare-stats floating panel lifecycle** — replaced the
  former `VDialog`. Three pieces:
    * **`multi_view._add_stats_compare_panel(panel_id,
      template_name, panel_title)`** — builds the floating
      dockview panel body via
      `StatsComparePanel(panel_id).render()` (pure HTML — no
      pv_view, no scene_registry entry), then calls
      `self.add_panel(..., floating={"width": 1100, "height":
      600, "position": {"left": 180, "top": 100}})`. Registered
      via `add_view(kind="stats_compare")` from
      `_open_compare_stats`.
    * **`boot._open_compare_stats(array_path)`** (trigger
      `open_compare_stats`) — singleton-per-property: looks up
      `state.ui_stats_compare_panel[array_path]`. If present,
      just calls `_refresh_compare_stats(array_path)` to push
      the latest items into the existing panel. If absent,
      calls `mv.add_view(kind="stats_compare")` to spawn a fresh
      panel, registers the new `panel_id` in
      `ui_stats_compare_panel[array_path]`, seeds the per-panel
      option vars (`ui_stats_compare_*_<panel_id>`) with their
      defaults, then runs the initial refresh.
    * **`boot._refresh_compare_stats(array_path)`** — re-runs
      `stats_dispatch.publish_compare_items(...)` against the
      current `ui_stats_compare[array_path]` cart, applies the
      per-panel **sort key + direction** server-side (so the
      cell-class annotation indices line up with the rendered
      row order), applies the user's drag-to-reorder layout
      from `ui_stats_compare_order_<panel_id>` (keys not
      present in the list trail at the end so new cart
      additions land last), pins the baseline row first when
      one is set so it stays anchored on the left of the
      scroll area, tags every surviving row with `it["profile"]
      = compare_matrix.profile_tag(row.Skewness,
      row.Kurtosis)`, derives the highlight **mode** from
      `baseline_key` (empty → `"extrema"`, set → `"baseline"`
      — no more `"heatmap"`, no separate toggle var), computes
      the cell-highlight dict via
      `compare_matrix.highlight_annotations_for_items(items,
      mode, baseline_key=...)`, then writes the result into
      `ui_stats_compare_items_<panel_id>` (the table's data
      source) and `ui_stats_compare_annotations_<panel_id>`
      (the cell-class lookup), and rebuilds the CSV data URL
      via `compare_matrix.items_to_csv(items,
      hidden_metrics=...)` → writes
      `ui_stats_compare_csv_<panel_id>` for the Download
      button's `<a :href download>`. No `Top N` slice — the
      slider was dropped in the 2026-06 round.
    * **`state.change` watcher in `_open_compare_stats`** —
      after the per-panel option vars are seeded, the spawn
      path registers a single watcher (runtime form
      `state.change(*watched)(_on_compare_stats_options_changed)`)
      on the option vars that mutate the matrix shape /
      content: `ui_stats_compare_baseline_<panel_id>`,
      `ui_stats_compare_sort_key_<panel_id>`,
      `ui_stats_compare_sort_asc_<panel_id>`,
      `ui_stats_compare_order_<panel_id>`. The handler
      simply calls `_refresh_compare_stats(array_path)` —
      every toolbar interaction that flips sort, baseline or
      drag-reorder therefore triggers a single re-publish
      round. Visible-metrics + transpose are NOT in the
      watcher list: they only mutate the visible-column
      projection (a pure Vue-template computed), so a
      re-publish would just duplicate work.
    * **Unregister** — `multi_view._on_view_closed(panel_id)`
      iterates `ui_stats_compare_panel` and pops the entry
      whose value matches the closed `panel_id` (mirrors the
      stats_compare_dist_panel cleanup pass); per-panel option
      vars are also cleared in the same handler.
- **`boot._refresh_compare_dist(array_path)`** — singleton
  Compare-distribution panel lifecycle helper. Lifecycle:
    * **Spawn** — `open_compare_distributions(array_path)`
      trigger calls `_spawn_distribution_panel(kind="compare",
      context={"array_path": array_path, "kind": "compare"})`,
      which returns a fresh `panel_id`.
    * **Register** — `state.ui_stats_compare_dist_panel[array_path]
      = panel_id` so subsequent
      `open_compare_distributions(array_path)` calls find the
      existing panel and refresh in place (singleton per
      property).
    * **Live-update** — every `stats_compare_toggle` /
      `stats_compare_clear` checks whether the property has
      a registered panel and calls `_refresh_compare_dist` to
      re-run `compute_compare_figure` from the current
      `ui_stats_compare[array_path]` selection and push the
      figure through the panel's
      `controller.update_distribution_figure_<panel_id>`. When
      the cart drops below 2 items a placeholder Plotly figure
      with the "Add 2 or more rows…" annotation is pushed instead
      (panel stays mounted with valid figure).
    * **Unregister** — `multi_view._on_view_closed(panel_id)`
      iterates `ui_stats_compare_dist_panel` and pops the entry
      whose value matches the closed `panel_id`; the next
      `open_compare_distributions(array_path)` then spawns a
      fresh panel rather than reattaching to the dead id.
- **`@server.trigger("open_compare_distributions")(array_path)`**
  — opens or focuses the singleton Compare-distribution panel
  for `array_path`. Wired to the **Show distributions** toolbar
  button on the Compare-stats panel (no longer a card-header
  button — the entry-point moved into the Compare-stats panel
  in the 2026-06 refactor). Implementation lives in `boot.py`;
  see `_refresh_compare_dist` above for the singleton lifecycle.
- **`compare_matrix.py` module** — pure-Python primitives for
  the Compare-stats panel (no PV / state access; takes a list
  of item dicts as produced by
  `stats_dispatch.publish_compare_items`). Five public
  functions:
    * `visible_metric_keys(hidden_metrics)` — returns metric
      keys in canonical order minus the ones the user hid via
      the toolbar multi-select. Backs both the table render
      and the CSV export so they stay in sync.
    * `sort_items(items, sort_key, sort_asc)` — stable sort by
      a metric key. None / non-numeric values sink to the
      bottom. (Currently used server-side as the basis for the
      panel's transposed-mode header-click sort; the table
      template also sorts client-side off the same key.)
    * `highlight_annotations(items, mode, baseline_key=None)`
      — returns `{metric_key: {item_idx: tag}}` where the tag
      depends on `mode`: `extrema` → `'min' | 'max'`,
      `baseline` → `'pos' | 'neg' | 'eq'` (delta sign vs
      baseline row), `heatmap` → float in `[0, 1]` (relative
      position in min..max). The panel applies the tag as a
      CSS class on the matching cell.
    * `items_to_csv(items, hidden_metrics=None)` — renders the
      comparison matrix as CSV (rows × visible metrics).
      `_csv_escape` / `_csv_num` (module-private helpers)
      handle the quoting + numeric formatting. Used by
      `boot._refresh_compare_stats` to produce the data URL
      bound to the Download button.
    * `profile_tag(skewness, kurtosis)` — distribution-shape
      classifier driving the per-row chip in the Compare-stats
      panel. Thresholds (conventional; tunable in the module
      head if a project ever wants stricter cuts):
      `|excess kurtosis| > 3` → `"heavy_tail"` (wins regardless
      of skew); `skew >= 0.5` → `"skewed_right"`;
      `skew <= -0.5` → `"skewed_left"`;
      `|skew| < 0.5 AND |excess kurtosis| < 1` → `"symmetric"`.
      Anything else (e.g. moderate skew + moderate kurtosis)
      returns `""`. Empty / non-numeric inputs also return
      `""` so the panel template can hide the chip cleanly
      via `v_if="it.profile"`. vtkDescriptiveStatistics emits
      Pearson kurtosis (already excess); the helper treats
      the input as excess (centered on 0).
    * `highlight_annotations_for_items(items, mode,
      baseline_key=None)` — wrapper over
      `highlight_annotations` that drills into `item['row']`
      (the dict where `_compute_one_variable` stores Mean /
      Std Dev / …) so the panel can keep its richer item
      shape (`{key, label, row, profile, …}`) without
      flattening. Returns the same `{metric_key: {item_idx:
      tag}}` shape; in `baseline` mode it ALSO populates an
      auxiliary `out["_deltas"][metric_key][item_idx] =
      {abs, rel}` dict so the template can render the inline
      `↑ / ↓ + value + %` Δ chip without re-deriving the
      arithmetic client-side. Baseline lookup matches
      `it['key'] == baseline_key` on the wrapper level (the
      `row` dict doesn't carry the cart key). Called from
      `boot._refresh_compare_stats` once per refresh; the
      template reads
      `((annotations || {})[metric_key] || {})[row_index]`
      as a pure Vue expression for both the `:class` binding
      and the Δ chip's `v_if`.
- `ui_descriptive_stats` — Brique A legacy single-row list, kept
  defaulted to `[]` for the boot-fallback path. Brique B writes it
  to `[]` on every recompute so any leftover panel binding doesn't
  show stale rows.
- `ui_slices_{i,j,k}_list`, `ui_slices_{i,j,k}_visible_list`,
  `ui_slices_range_{i,j,k}`, `ui_slices_range_mode`,
  `ui_slices_volume_visible`, `ui_range_{i,j,k}` (the IJK extent
  bounds).
- `ui_plane_edit_mode` (`"slice" | "clip" | null`) — which 3D plane
  widget is being edited. Shared between slice and clip — only one
  widget visible at a time.

### General Display

- `tree_hierarchy_mode` — `"flat"` / `"by_interpretation"` /
  `"by_feature_and_interpretation"`.
- `tree_hierarchy_snackbar_visible` — pops the warning snackbar
  when a non-empty selection is wiped.
- `load_mode` — `"auto"` / `"manual"`.
- `show_mode` *(deprecated alias)* — kept for compat.
- `ui_scale_z` — global Z-axis exaggeration.
- `representation_active` — Surface / Wireframe / Points …

### Realization / Time

- `ui_panel_active_mr_specs_by_id` — `{panel_id: [{array_path,
  title, available_indices, current_idx}, …]}`, drives the per-view
  RealizationPicker overlay.
- `panel_has_mr_by_id`, `panel_has_ts_by_id` — `{panel_id: bool}`,
  derived from the specs map; gate per-view RealizationPicker /
  TimeControl visibility.
- `ui_global_mr_specs`, `ui_global_mr_selected_path`,
  `ui_global_mr_selected_spec` — the toolbar's "set this realization
  everywhere" picker.
- `time_value_<panel_id>`, `ui_time_label_<panel_id>` — per-panel
  TimeControl values.

### VTK Logging / Upload

- `vtk_log_messages`, `log_panel_open`.
- `upload_uploading`, `upload_progress`, `upload_file_count`,
  `upload_file_names`, `upload_session_id`.

---

## Selection / Visibility / Coloring Model

Three orthogonal concepts:

| Concept | State source | Effect |
|---------|--------------|--------|
| **Loading** | `ui_select_node_*` (UI) → `fespp_data_selectors` (Selector) → C++ collector | Data is materialised in ParaView. |
| **Visibility** | `ui_hidden_rep_paths` (eye on rep) | `display.Visibility` on every source rendering the rep. Independent of loading — a hidden rep is still loaded. |
| **Active coloring** | `ui_active_array_by_rep` (eye on data-array) | `ColorBy(array)` on the rep when present, `ColorArrayName=""` (→ DiffuseColor) when absent. |

The **active node** (`ui_active_node_*`) is yet another, purely-UI
concept: it tells the Attributes panel what to render. It has no
bearing on what's loaded or visible.

The **default tint** is recorded in `solid_color_by_rep` at first
load (one color per rep, picked from `color_palette.color_for_index`)
and stays in `display.DiffuseColor` regardless of what ColorBy is
doing — so when the user closes all data-array eyes on a rep, the
diffuse color takes over instantly.

---

## Critical Data Flows

### File Load

1. User picks a file in the import dialog → POST `/upload`.
2. `upload_endpoint.py` saves the file to a temp dir, calls
   `controller.load_epc_file(path)`.
3. `Collector.add_file` sets the `Files` proxy property and runs
   `UpdatePipelineInformation`. `RequestData` triggers a build of
   the C++ data assembly via `addFile`.
4. `controller.update_data_information` reads the live assembly
   (`GetLiveAssembly` if available, else the pipeline output's
   `GetDataAssembly`) and calls `_tree.set_tree(assembly)` →
   `state.ui_subtree_*` populated.
5. Vuetify renders the trees.

### Checkbox Click

1. User clicks a checkbox → `update_selected` event mutates
   `ui_select_node_*`.
2. `_wire_dependency_expansion` runs first: adds groupings'
   descendants and `Channel/Marker → Trajectory` deps. Writes the
   expanded list back to `ui_select_node_*`.
3. `_wire_select_to_active` runs next: activates the newly checked
   node by writing to `ui_active_node_*`.
4. `Selector.select_node_*` runs: walks ids → paths, writes
   `state.fespp_data_selectors`.
5. The load handler (`@state.change("fespp_data_selectors")`)
   pushes the selectors to the collector, syncs `RepSources`,
   updates loaded/visibility tracking, runs `refresh_active`,
   renders.

### Eye Click (Visibility)

1. User clicks the rep eye → `controller.toggle_rep_visibility(item.path)`.
2. Handler flips `ui_hidden_rep_paths` membership.
3. Resolves all sources rendering the rep via `_sources_for_rep_path`
   (single ExtractBlock for non-IJK; rep_data filter + slicers for
   the active IJK grid).
4. Calls `pvsimple.Show` / `Hide` *and* sets `display.Visibility` —
   belt-and-braces because either alone has been observed to fail
   on Grid2D.
5. Renders.

### Eye Click (DataArray)

1. User clicks an array eye → `controller.toggle_dataarray_color(item.path)`.
2. Handler resolves the parent rep_path via
   `_tree.find_representation_node(node_id)`.
3. Updates `ui_active_array_by_rep[rep_path]`: removes if it was the
   currently active one, sets it otherwise (closing any previous
   active for the same rep).
4. `@state.change("ui_active_array_by_rep")` fires:
   `_apply_color_array(rep_path, array_path)` runs `pvsimple.ColorBy`
   for every display, or clears `ColorArrayName` for SolidColor.

### Add View / Split / Empty View

1. User clicks **Split right / below** on a panel's tab row →
   `controller.open_new_view_dialog(direction, reference_panel_id)`.
2. `NewViewContentDialog.open_for(...)` pre-fills the modal state
   and shows it. The user picks one of three actions:
   - **Copy "<source>" scene** → `mv.add_view(kind="render",
     replicate=True, direction=..., reference_panel_id=...)`.
   - **Empty scene** → same but with `replicate=False`.
   - **Diff scene** → `mv.get_or_create_diff_view(...)` (singleton).
3. `FesppMultiView.add_view`:
   - Creates a new `pvsimple.RenderView`, registers it in
     `self._pv_internal[panel_id]`.
   - `scene_registry.add_view(panel_id, pv_view)` — instantiates
     the `ViewScene` (which creates its own
     `vtkEPCCollectorClone`).
   - `scene_registry.sync_loaded_reps(loaded_rep_paths)` — adds a
     `RepInScene` for every currently-loaded rep, with eager
     setup (per-view extractor build + ColorBy mirror).
   - When `replicate=True` and `ref_view` exists:
     - `_replicate_visibility(ref_view, pv_view)` — mirrors shared
       (non-per-view) source visibility from ref onto new. Filters
       per-view proxies via `_is_per_view_source` so they don't
       leak between scenes.
     - `scene_registry.replicate_view(ref_panel_id, panel_id)` —
       snapshot/apply each concern (ijk_slicers → threshold →
       slice → clip) from ref's `RepInScene` onto new's.
   - When `replicate=False` and `kind="render"`:
     - `_force_hide_all_sources(pv_view)` — pre-hides every shared
       source so lazy `GetDisplayProperties` calls don't paint
       phantom outlines.
   - `_seed_per_view_hidden_state(panel_id, ref_panel_id, kind,
     replicate)` — initialises the panel's `ui_hidden_rep_paths_by_view`
     and `ui_active_array_by_rep_by_view` buckets (copy from ref or
     start empty).
   - Builds the panel's DivLayout (vtk.js view + ACTIVE pill +
     TimeControl + RealizationPicker + camera chrome + actions).
   - `add_panel(panel_id, title, template, position=...)` —
     dockview adds the panel in the chosen direction.
   - If `replicate=True`: `apply_panel_coloring(panel_id)` re-runs
     ColorBy on the new view's displays (mirrored from ref's
     active-array bucket), then `_enforce_view_visibility_from_ref`
     does a final visibility pass.

### Copy From View

The header of each per-view drawer panel (Slice / Clip / Threshold /
IJK slicers) carries a `copy_from_view_menu.render_copy_menu(concern)`
dropdown.

1. User clicks the icon → menu opens listing
   `(fespp_render_panels || []).filter(p => p.id !==
   fespp_active_panel_id)`.
2. User selects a peer view → fires
   `trigger('copy_<concern>_from_view', [src_view_id])`.
3. `_wire_triggers_once()` (in `copy_from_view_menu.py`) routes the
   trigger to `controller.copy_<concern>_from(src_view=...)`.
4. `boot.py` `_copy_concern(src_view, dst_view, concern,
   rep_path=None)`:
   - If `rep_path` is given, snapshots from src's `RepInScene` and
     applies to dst's directly (single-rep variant).
   - Otherwise calls `scene_registry.replicate_view(src, dst,
     concerns=(concern,))` (all reps in src).
   - Renders dst's pv_view, republishes the matching flat UI state
     vars (`publish_slice_state` / `publish_clip_state` /
     `refresh_threshold_ui_for_active_grid` /
     `_push_active_ijk_state_to_ui`) when dst is the active panel.

### Tree Hierarchy Mode Change

1. User clicks a different mode → `tree_hierarchy_mode` mutates.
2. `@state.change("tree_hierarchy_mode")`:
   - Pushes the new value to the collector via `vtkSMPropertyHelper`.
     The C++ `SetTreeHierarchyMode` calls `repository.rebuildAssembly()`
     which clears mapper caches, re-`Initialize`s the assembly,
     re-traverses every loaded file, and bumps `AssemblyTag`.
     `selectorNotLoaded` and `selectors` are cleared too.
   - Detects whether a non-empty selection was about to be wiped →
     pops the warning snackbar.
   - Clears every selection / visibility / coloring state var.
   - `UpdatePipeline()` so `RequestData` re-deep-copies the freshly
     rebuilt assembly into the pipeline output (the Python
     `update_data_information` falls back to that output when
     `GetLiveAssembly` isn't bound).
   - Calls `update_data_information` → `_tree.set_tree(assembly)` →
     trees re-render with the new layout.

---

## Common Pitfalls

- **Proxy info cache is stale** when the C++ pipeline mutates partition
  data in place (`addDataArray`, realization swap). Bump the
  TrivialProducer's MTime via `src.GetClientSideObject().Modified()`
  + `src.UpdatePipelineInformation()` before reading
  `GetCellDataInformation` / `GetPointDataInformation`. Better: query
  the underlying VTK object directly via
  `src.GetClientSideObject().GetOutputDataObject(0)`.
- **`vtkDataAssembly::Initialize()` resets the root node name** to
  the VTK default. Always re-`SetRootNodeName("data")` after
  `Initialize` — every Python path matching is hard-coded against
  `/data/...`.
- **`GetAssembly()` is not always wrapped to Python.** Use
  `GetLiveAssembly()` (added under a unique name to dodge the
  parent-class collision) or fall back to
  `GetOutput().GetDataAssembly()` after an `UpdatePipeline`.
- **Load mode "manual" + active node racing the load handler.**
  Activation can fire before the rep exists on the C++ side;
  `Activator.refresh_active()` is the catch-up path used after
  `apply_pending_selection`.
- **Multi-realization / TimeSeries property names live in `propTitle`,
  not `title`** for synthetic nodes. The latter is the VTK-sanitised
  variant; check both when looking up arrays in cell/point data.
- **Trame state mutations are batched.** A
  clear-then-restore on the same flush collapses to no-op, so
  `@state.change` callbacks don't fire. Call the handler functions
  directly (as `Activator.refresh_active` does) when you need a
  re-run.
- **`pvsimple.ColorBy(display, None)` is broken in PV6**; use
  `display.SMProxy.SetScalarColoring("", 0)` instead (see
  `_apply_color_array` in the engine).
- **Trame `click_stop=` is not a valid binding form.** Use the tuple
  pattern `click=(callable, "[args]")` and accept that the click
  may bubble (or wrap the icon in a div with an explicit
  `@click.stop`).
- **`GetDisplayProperties(src, view=v)` is not read-only.** It
  lazily creates a default display proxy (Visibility=1,
  Representation='Outline') if one doesn't exist. When iterating
  every PV source in a context where some sources are per-view
  (anything created by `RepInScene` / `ViewScene`), filter them
  via `multi_view._is_per_view_source(name)` first — otherwise
  view A ends up rendering view B's per-view extractor + chain
  as phantom outlines.
- **Per-view ownership is name-tagged via `_v<panel_id>` suffix.**
  Every per-view registration name MUST embed `self.scene.view_id`
  (or the equivalent) somewhere, otherwise `_is_per_view_source`
  can't filter it. Same convention for IjkGrid sub-proxies
  (`{base}_v<view_id>`). Diverging from the convention silently
  leaks visibility across views.
- **The legacy `ExtractBlockRepresentation` / `SourceRegistry`
  threshold/slice/clip methods are deprecated** but kept as a
  safety-net fallback. They log a single-fire `[DEPRECATED]` on
  first call — if you see one in production logs, something
  routed through legacy when it should have gone through the
  per-view path; investigate (typically: per-view extractor not
  built yet because no property was picked, or `vtkEPCCollectorClone`
  is missing from the plugin DLL).
- **MR property titles are not VTK array names.** When the user
  thresholds on an MR property, `state.active_color_array_name`
  holds the title (`"VOIL"`) but the actual cell-data array is
  `VOIL_real_<idx>` per the per-view realization pick.
  `threshold_dispatch._resolve_vtk_array_name` walks the rep
  subtree by title + suffixes the active realization; auto-picks
  the first available index when the view has none. Don't bypass
  this resolver if you add new dispatchers that take an "array
  name" from a UI string.

  The COE panel applies the same convention: `solid_color_panel`'s
  `_resolve_coe_lut` resolves title → suffixed + scopes to the
  drawer target view (see "Per-view LUT / PWF" below).

- **Per-view LUT / PWF.** ParaView's default
  `GetColorTransferFunction(name)` returns a singleton keyed by
  array name — every display ColorBy'd with the same name shares
  the same LUT, so a COE edit in one view bleeds into every other
  view rendering the same array. FESPP overrides this by giving
  every `ViewScene` its own per-(scene, array) LUT registered
  under `f"{array_name}__{view_id}"`, then re-binding each
  display's `LookupTable` / `ScalarOpacityFunction` to that
  scoped pair right after `pvsimple.ColorBy`. The override lives
  in two helpers:

    - `source_resolver.swap_to_scene_tfs(displays, view, name)` —
      called from `apply_color_array` AND directly from
      `activator._apply_color_for_active_property` (which does its
      own ColorBy fan-out). Returns the scoped LUT so callers can
      bind their scalar bar to it.

    - `ViewScene.get_or_create_lut(base)` / `get_or_create_pwf` —
      lazy creation; seeds from the global singleton on first call
      so the new scene starts with whatever PV's auto-pick was for
      that array.

  COE panels (`solid_color_panel`, `categorical_color_editor`)
  resolve to the drawer target view's scoped LUT via
  `source_resolver.resolve_target_scoped_lut(name)` for both
  reads and writes — symmetry stays the gating rule.

  On `MultiView.add_view(replicate=True)`, the new scene's LUTs
  are seeded from the global singleton by `swap_to_scene_tfs`;
  we then call `new_scene.replicate_tfs_from(ref_scene)` to copy
  the ref scene's RGBPoints / Points / NanColor / IndexedColors
  / Annotations onto the new scene's scoped proxies so the new
  view's first frame shows the user's edits, not a fresh default.

  Cleanup: `ViewScene.destroy()` deletes every scoped LUT / PWF
  proxy. The global singletons keyed by the raw array name are
  NOT ours — leave them alone.

  Stale-bar reap: `activator._apply_color_for_active_property`
  mirrors `source_resolver.hide_unused_scalar_bars` after each
  ColorBy by calling `vtkSMTransferFunctionManager().UpdateScalarBars(active_view.SMProxy, 1)`.
  Without this sweep, switching scoped LUTs for the same array
  between activations strands the prior bar in
  `view.Representations` (the manager keys bars by `(lut, view)`
  and won't reap one whose LUT lost its visible-display reference).
  This matters because the tree stats VIcon click bubbles to the
  VTreeview row — there is no working `click.stop` binding form in
  trame (see the explicit note above) — so every pin/unpin re-fires
  `active.reservoir`, and only the UpdateScalarBars sweep keeps
  bars from accumulating one-per-array-touched.

  Render path: COE / categorical edit handlers must push to the
  drawer target, not the focused panel. `source_resolver`
  provides `render_and_push_target(controller)` which `Render`s on
  the target scene's `pv_view` and then calls
  `view_update_for(target_panel_id)` (falling back to
  `view_update`). All COE override handlers
  (`_FesppColorOpacityEditor.on_colors_changed` / `on_opacities_changed`
  / `on_preset_name_changed` / `on_nan_color_changed`,
  `CategoricalColorEditor.on_color_change`, `_apply_solid`) call
  it. Without this the LUT is mutated server-side but the wrong
  panel's vtk.js client gets the refresh in pinned mode.

  Rescale guard: `solid_color_panel._update_color_editor` forces a
  `RescaleTransferFunction(data_min, data_max)` on the scope LUT
  ONLY when it's still at PV's default `[0, 1]` range (a fresh
  `GetColorTransferFunction(name)` carries the Cool-to-Warm preset
  over [0, 1] regardless of what `name` refers to). Once the scope
  LUT carries data values (after the first ColorBy auto-rescale or
  any user COE edit), we leave its `RGBPoints` alone — rescaling a
  user-edited LUT would wipe their custom stops. The matching
  scope PWF is rescaled in lockstep when it's also at default `[0, 1]`
  positions — otherwise the COE component's `background_shape="opacity"`
  samples out-of-range and renders the gradient as a single solid
  colour (the leftmost LUT stop).

  Array info lookup: `update_scalar_range` and
  `_data_range_for_active_array` query the **target scene's**
  `RepInScene.source()` (per-view EnergisticsExtractor) — NOT
  ptc's `self.source_proxy` (= `GetActiveSource`). The legacy
  shared `ExtractBlock` returned by `GetActiveSource` doesn't
  carry the MR `_real_<idx>` arrays the per-view extractor
  emits, so the lookup would silently fall through to
  `scalar_range = [0, 0]` and the gradient would render solid.

- **`representation_active` (Surface / Wireframe / …) fans out
  across per-view scenes.** `ptc.RepresentBy` only writes
  `Representation` on a single display (active source × active
  view). Phase 3a per-view pipelines mean that display is the
  legacy shared source, which is HIDDEN in scenes whose per-view
  EnergisticsExtractor is rendering. To make the change visible,
  `slicer_dispatch.propagate_representation` iterates every
  `scene_registry.all_scenes()` and applies `Representation` to
  each scene's per-view proxies (extractor + chain + slice / clip
  outputs + per-view IjkGrid pipeline) in that scene's `pv_view`,
  plus the legacy proxies as a backstop. It then pushes a fresh
  vtk.js frame to every panel via `controller.view_update_all()`
  because ptc's own `on_data_change` push fires BEFORE this
  state.change handler, so the client would otherwise show the
  pre-fan-out frame.

---

## Adding a Feature: Cookbook

A typical "add a new toggle that affects the C++ side" change:

1. **C++ enum / property** — declare in `Tools/enum.h` if it's a
   typed value, add `Set/Get` macros in `vtkEPCCollector.h`,
   implement the setter in `vtkEPCCollector.cxx`. Forward to the
   repository via `repository.setMyProp(...)`.
2. **C++ XML binding** — add an `<IntVectorProperty>` /
   `<StringVectorProperty>` block in `Energistics.xml`. Use
   `panel_visibility="never"` to hide from ParaView's GUI.
3. **Python state var** — `state.setdefault("my_prop", default)` in
   `fespp_engine.initialize_fespp_engine`.
4. **Python push helper** — function that resolves the proxy and
   calls `vtkSMPropertyHelper(proxy, "MyProp").Set(value)` +
   `proxy.UpdateVTKObjects()`.
5. **Python `@state.change`** — listens on the state var, calls
   the push helper, and any side-effects (rebuild, reset).
6. **UI** — add a `VBtnToggle` / `VSwitch` / etc. bound to the
   state var via `v_model=("my_prop", default)`.
7. **Test from a fresh session.** Do not assume a stale state var
   defaults the C++ side: the engine's `state.setdefault` only
   runs the first time, so different code paths must agree on the
   default.

For a UI-only feature (e.g. a new tooltip):

1. Edit the relevant template in `app/ui/`.
2. Add any new state vars in `fespp_engine.py` (consistency).
3. Avoid `@state.change` cycles — write to a state var only when
   the value actually changed (`if new != prev: state.x = new`).

For a load-flow feature:

1. Find the right hook in
   `_on_change_fespp_data_selectors_impl` — most pipeline
   side-effects belong here.
2. Update `ui_loaded_*` / `ui_active_array_by_rep` if your feature
   affects what shows up in the trees' eye state.
3. Don't forget `notify_active_reps` if you change which reps are
   displayed.

---

When in doubt, grep for an existing similar feature and follow the
same shape — `ExplicitSelection` (a boolean proxy property) and
`TreeHierarchyMode` (an enum proxy property + live rebuild) are the
two cleanest references for cross-layer changes.
