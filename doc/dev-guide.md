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
  - [Live Assembly Rebuild](#live-assembly-rebuild)
- [The Python Side: Trame App](#the-python-side-trame-app)
  - [Module Map](#module-map)
  - [Lifecycle Overview](#lifecycle-overview)
  - [Engine Orchestrator (`fespp_engine.py`)](#engine-orchestrator-fespp_enginepy)
  - [Tree Parser (`fespp_tree.py`)](#tree-parser-fespp_treepy)
  - [Selector (`fespp_selection.py`)](#selector-fespp_selectionpy)
  - [Activator (`fespp_active.py`)](#activator-fespp_activepy)
  - [Sources Layer](#sources-layer)
  - [UI Layer](#ui-layer)
- [State Variables (Trame)](#state-variables-trame)
- [Selection / Visibility / Coloring Model](#selection--visibility--coloring-model)
- [Critical Data Flows](#critical-data-flows)
  - [File Load](#file-load)
  - [Checkbox Click](#checkbox-click)
  - [Eye Click (Visibility)](#eye-click-visibility)
  - [Eye Click (DataArray)](#eye-click-dataarray)
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
│       │   ├── fespp_engine.py        # orchestration
│       │   ├── fespp_tree.py          # vtkDataAssembly → Trame dicts
│       │   ├── fespp_selection.py     # checkbox → fespp_data_selectors
│       │   ├── fespp_active.py        # active node → ColorBy + LUT
│       │   ├── color_palette.py       # default per-rep colors
│       │   ├── sources/
│       │   │   ├── collector.py       # wraps vtkEPCCollector proxy
│       │   │   ├── etp_connector.py
│       │   │   ├── ijkgrid.py         # IJK slicers + volume mode
│       │   │   └── rep_sources.py     # one ExtractBlock per non-Ijk rep
│       │   └── common/
│       │       └── timeseries.py
│       ├── ui/                  # Vue/Vuetify templates
│       │   ├── view.py                # main layout
│       │   ├── tree_views.py          # the 3 VTreeviews + eye slots
│       │   ├── toolbar.py
│       │   ├── import_dialog.py
│       │   ├── helpers.py
│       │   ├── panel/                 # per-feature panels
│       │   │   ├── solid_color_panel.py
│       │   │   ├── color_editor.py
│       │   │   ├── categorical_color_editor.py
│       │   │   ├── representation_type_panel.py
│       │   │   └── slicers.py
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

### Per-Rep Extract: ExtractRepWithoutCopy

`SetExtractRepPath(path)` chains an `EnergisticsExtractor` filter on
top of the collector for that one rep, so each rep gets its own
single-output ParaView source. The Python side (`RepSources.get_or_create`)
uses this to obtain a stable proxy per rep_path; the diffuse-color
default tint and ColorBy operate on those individual sources.

The "WithoutCopy" semantics shallow-copy the partition data in
`RequestData`, so the sub-source automatically tracks upstream changes
(selector add/remove, realization swap, property in-place addition).

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
| `app/core/fespp_engine.py` | Initialises the ParaView source / collector / view; registers most controller actions and `@state.change` handlers. The big orchestrator. |
| `app/core/fespp_tree.py` | `Tree` class — wraps the C++ `vtkDataAssembly`. Exposes `set_tree(assembly)` that re-parses into `state.ui_subtree_*` and a bunch of `find_*` helpers. |
| `app/core/fespp_selection.py` | `Selector` — converts UI checkbox lists (`ui_select_node_*`) to assembly paths and writes them to `state.fespp_data_selectors`. |
| `app/core/fespp_active.py` | `Activator` — listens on `ui_active_node_*`, resolves the active rep, conditionally applies `ColorBy` (gated by the eye state), refreshes the LUT/PWF panel via `controller.update_color_editor`. |
| `app/core/sources/collector.py` | Wraps `vtkEPCCollector` proxy: `add_file`, `show`, `set_realization_index`. |
| `app/core/sources/rep_sources.py` | Maintains a `{rep_path: ExtractBlock}` registry; `sync(selectors)` adds / removes proxies to match the current load set. |
| `app/core/sources/ijkgrid.py` | IJK-specific slicer / volume sources. |
| `app/core/sources/etp_connector.py` | ETP/OSDU client (alternate data source). |
| `app/ui/view.py` | Main layout: drawer, tabs, attribute cards, general-display section, render area, log panel. |
| `app/ui/tree_views.py` | The three `VTreeview`s + `_chip_slot` (color chip) + `_eye_slot` (visibility / data-array eyes) + dependency-expansion handlers. |
| `app/ui/toolbar.py` | Title bar, **Import**, **Load** buttons. |
| `app/ui/import_dialog.py` | File upload + ETP/OSDU connection dialog. |
| `app/ui/panel/solid_color_panel.py` | Active-node color/LUT panel — picks between `VColorPicker` (rep) and `_FesppColorOpacityEditor` (continuous array) / `CategoricalColorEditor` (discrete/categorical array) based on `active_color_array_name`. |
| `app/ui/panel/color_editor.py`, `categorical_color_editor.py` | LUT / PWF widgets. |
| `app/ui/panel/representation_type_panel.py` | Per-rep ParaView display type (Surface / Wireframe / …). |
| `app/ui/panel/slicers.py` | IJK slicers UI. |
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

### Engine Orchestrator (`fespp_engine.py`)

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

### Tree Parser (`fespp_tree.py`)

`Tree.set_tree(data_assembly)` walks the live assembly with two
recursive helpers (`set_tree` for top-level + `add_subtreeview_data`
for subtrees) and writes three nested-dict lists:
`state.ui_subtree_{reservoir,surface,well}`.

Each dict has: `id`, `parent_id`, `title`, `path`, `type`, `icon`,
`is_ts`, `is_mr`, optional `disabled`, optional `children`.

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

### Selector (`fespp_selection.py`)

The `Selector` holds the per-tab path lists
(`_selection_path_{reservoir,surface,well}`) and the active
`TimeSeries` / `Wellhead` instances. Every `select_node_*` method
reads `state.ui_select_node_*`, walks the ids to paths, sets one of
the three local lists, and writes the concatenation into
`state.fespp_data_selectors`.

Reservoir / surface / well are symmetric: they emit the full list of
checked paths (with `ExplicitSelection=1`, every property must be
listed explicitly).

### Activator (`fespp_active.py`)

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
- **`RepSources`** maintains a `{rep_path: ExtractBlock}` map for
  non-IJK reps. `sync(selectors)` resolves each selector to a
  rep_path (via `Tree.find_representation_node`), creates an
  `EnergisticsExtractor` filter for new paths via
  `SetExtractRepPath` + `GetExtractedRepProducerName`, and removes
  filters for paths that disappeared. `apply_z_scale` propagates the
  Z scale to every existing extract.
- **`IjkGrid`** owns the IJK-specific filters: a single rep_data
  filter per active IJK grid + slicers + volume crop. `set_node_id`
  switches the active IJK grid; `update_block_visibility` is called
  before camera resets.

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

- `ui_loaded_rep_paths` — paths of representations currently
  materialised in ParaView. The eye icon is rendered next to those
  rows.
- `ui_hidden_rep_paths` — subset whose `display.Visibility` was
  toggled off. Loaded but hidden.
- `ui_loaded_array_paths` — paths of data-array nodes (Property,
  TimeSeries, MultiRealization, …) whose data is loaded. Eye is
  rendered next to those rows.
- `ui_active_array_by_rep` — `{rep_path: array_path}`, at most one
  entry per rep. Drives `ColorBy` via the
  `@state.change("ui_active_array_by_rep")` handler. Absent entry
  → SolidColor.
- `solid_color_by_rep` — `{rep_path: "#RRGGBBAA"}`, picker value
  per rep.
- `tree_chip_color_by_path` — derived: `{rep_path: "PROPERTY" |
  hex_color}`, drives the per-row color chip in the trees.
- `active_representation_path`, `active_color_array_name`,
  `active_property_kind` — set by the activator from the active
  node, drives the Attributes panel.

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

- `realization_selected_index`, `realization_labels`,
  `realization_parent_node_id`, `realization_ts_node_id`.
- `ui_slices_real`, `ui_slices_real_locked`,
  `ui_slices_real_locked_value`.
- `ui_time_label`, `ptc_show_vcr`.

### Slicers

- `ui_slices_{i,j,k}_list`, `ui_slices_{i,j,k}_visible_list`,
  per-axis position arrays.

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
