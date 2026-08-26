# Architecture

> **Orientation.** `fespp-on-trame` is a [Trame](https://kitware.github.io/trame/) (Vue3 + websocket) web UI that drives ParaView Server in-process. ParaView loads the **FESPP** C++ plugin, which reads RESQML/EPC geoscience data through FESAPI and emits VTK multiblock datasets plus a `vtkDataAssembly` describing the object tree. The Python side has four cooperating layers: a **Trame UI** (Vue templates bound to `state.*` vars and `controller.*`/`server.trigger` callbacks), an **engine** layer of stateless dispatch handlers wired in [`boot.py`](#1-big-picture), a **source/scene** layer that owns the ParaView proxies (two coexisting models — a legacy per-rep registry and a per-view scene graph), and the **ParaView/FESPP** plugin itself. The defining design tension this page explains is the **per-view scene model**: every render panel owns an independent sub-pipeline so the same RESQML representation can be coloured, sliced, clipped and thresholded differently in each view. See [[Glossary]] for the vocabulary used throughout (rep, rep_path, ViewScene, RepInScene, ElementType, clone, LUT, PWF, EPCCollector, IjkGrid, MR, channel, marker).
>
> **Legend of key terms** (full definitions in [[Glossary]]):
> | Term | One-line meaning |
> |---|---|
> | **rep / representation** | A renderable RESQML object (grid, surface, well tube, frame). Has geometry + an eye + a colour. |
> | **rep_path** | The `vtkDataAssembly` node path of a rep — the global identity key for everything below the UI. |
> | **ViewScene** | One render panel's sub-pipeline root (owns a `vtkEPCCollectorClone` + per-rep state + per-view LUTs). |
> | **RepInScene** | One `(rep, view)` pair — owns that view's extractor, threshold chain, slice/clip, per-view IjkGrid. |
> | **ElementType** | Stateless strategy singleton per RESQML runtime `kind` — encodes "how this kind behaves". |
> | **SourceRegistry** | LEGACY per-rep registry (one `ExtractBlock`/`IjkGrid` per rep, view-agnostic). Phase-2 fallback. |
> | **SceneRegistry** | PER-VIEW registry: one `ViewScene` per panel. The live model for coloring/slice/clip/threshold. |
> | **clone** | A `vtkEPCCollectorClone` proxy per view — a structural (never-rendered) shallow passthrough of the EPCCollector. |
> | **LUT / PWF** | Color lookup table / opacity (piecewise) transfer function, scoped **per `(scene, array)`**. |

---

## 1. Big picture

### 1.1 The layers and how they talk

```
                    ┌──────────────────────────────────────────────────────────┐
   BROWSER (Vue3)   │  TreeViews · Attributes drawer · MultiView panels · COE   │
                    └───────────────┬───────────────────────────┬──────────────┘
                                    │ state.* (2-way bind)       │ trigger('name',…)
                                    │ @click → controller.*      │ (Vue-only callbacks)
   ─────────────────────────────────┼────────────────────────────┼─────────────────────
   TRAME SERVER     ┌───────────────▼───────────────────────────▼──────────────┐
   (websocket)      │  server.state   server.controller   server.context        │
                    └───────────────┬───────────────────────────────────────────┘
                                    │  @state.change / @controller.set / @server.trigger
   ─────────────────────────────────┼──────────────────────────────────────────────────
   ENGINE           ┌───────────────▼───────────────────────────────────────────┐
   (boot.py wires   │ data_load · selection_dispatch · visibility · active_array │
    thin closures   │ slicer_dispatch · slice_dispatch · clip_dispatch           │
    → dispatch      │ threshold_dispatch · marker_dispatch · realization_dispatch│
    modules)        │ source_resolver · panel_resolver · stats/dist/diff/etp     │
                    └───────┬───────────────────────────────────┬───────────────┘
                            │ Selector / Tree / Activator        │
   ─────────────────────────┼────────────────────────────────────┼──────────────────────
   SOURCE / SCENE   ┌────────▼─────────────┐          ┌──────────▼───────────────────────┐
                    │ LEGACY  SourceRegistry│          │ PER-VIEW  SceneRegistry           │
                    │  ExtractBlockRep      │  COEXIST │  ViewScene(view) ─┬─ clone        │
                    │  IjkGrid (shared)     │◄────────►│   per-(rep,view) RepInScene       │
                    │  (view-agnostic)      │ fallback │    ↳ ElementType strategy          │
                    └────────┬─────────────┘          └──────────┬────────────────────────┘
                             │  pvsimple proxies                 │  pvsimple proxies
   ─────────────────────────┼────────────────────────────────────┼──────────────────────
   PARAVIEW/FESPP   ┌────────▼────────────────────────────────────▼───────────────────────┐
                    │ EPCCollector  →  EPCCollectorClone  →  EnergisticsExtractor /         │
                    │                                         Threshold / Clip / Slice      │
                    │ vtkDataAssembly (the tree)   ·   FESAPI → RESQML/EPC/H5 on disk        │
                    └───────────────────────────────────────────────────────────────────────┘
```

**Three communication channels** between the browser and Python:

1. **`state.*` variables** — reactive, 2-way bound. The UI writes a selection list (`ui_select_node_reservoir`) or a flag; a Python `@state.change("var")` handler reacts. Python writes back (e.g. `ui_loaded_rep_paths`) and the Vue template re-renders. Every important var is catalogued in [§4](#4-state-catalog).
2. **`controller.*` methods** — Python callables registered with `@controller.set("name")`, invokable both from Python and from Vue `@click="name(...)"`. Examples: `load_epc_file`, `toggle_rep_visibility`, `slice_set`, `apply_panel_coloring`.
3. **`server.trigger("name")`** — Vue-only callbacks (the runtime resolves these from templates; `controller.*` is Python-only-reachable from a template). Used for the stats/distribution panels and per-view realization picker: `set_view_realization`, `open_row_histogram`, `stats_compare_toggle`, …

**`server.context`** is the side channel between modules that would otherwise hit a circular import. `boot.py` stashes `server.context.source_registry`, `server.context.scene_registry`, and (set by the UI) `server.context.multi_view`. Helper functions across the source layer fetch them lazily via `get_server().context`.

### 1.2 Entry point and boot

[`fespp_on_trame/__main__.py`](fespp_on_trame/__main__.py) — `@TrameApp class App` parses CLI args (`--local-epc-file-path`, `--fespp-plugin-path`, optional base64-encoded remote `--remote-epc/h5-file-location`), then calls `initialize_fespp_engine(server, fespp_plugin_path=...)`. In `remote_file` mode it downloads the EPC+H5 to a temp dir and calls `controller.load_epc_file(...)`; in `local_file` mode loading is deferred to the upload route / UI. Finally `ui(app.server)` builds the Vue layout and `server.start()` runs.

[`app/core/engine/boot.py`](fespp_on_trame/app/core/engine/boot.py) — `initialize_fespp_engine(server, *, fespp_plugin_path)` is the **single wiring point** (~1700 lines). It:
- `pvsimple.LoadPlugin(fespp_plugin_path)` and the `ExplicitStructuredGrid` plugin (needed for IJK volume crop/slice).
- creates the first `RenderView`, the stderr tee (`vtk_log`), and the core singletons: `Tree(None)`, `Collector()`, `ETPConnector()`, `SourceRegistry(collector, tree)`, `SceneRegistry(collector, tree)`, `Selector(tree)`, `activator.Activator(...)`.
- mirrors `_tree` onto the `engine` package (`_engine_pkg._tree = _tree`) so the UI and free functions can reach it without a cycle.
- sets `ExplicitSelection=1` on the EPCCollector proxy (selection is literal — selecting a grid does **not** auto-load its properties; see [§5](#5-key-invariants--conventions)).
- calls `init_state_defaults(state)` ([`state_defaults.py`](fespp_on_trame/app/core/engine/state_defaults.py)) to seed every `state.*` var.
- registers **all** the `@state.change` / `@controller.set` / `@server.trigger` handlers as thin closures delegating to the dispatch modules.

The dispatch modules ([`data_load`](fespp_on_trame/app/core/engine/data_load.py), [`visibility`](fespp_on_trame/app/core/engine/visibility.py), [`active_array`](fespp_on_trame/app/core/engine/active_array.py), [`slicer_dispatch`](fespp_on_trame/app/core/engine/slicer_dispatch.py), [`slice_dispatch`](fespp_on_trame/app/core/engine/slice_dispatch.py), `clip_dispatch`, `threshold_dispatch`, `marker_dispatch`, `realization_dispatch`, [`source_resolver`](fespp_on_trame/app/core/engine/source_resolver.py), [`panel_resolver`](fespp_on_trame/app/core/engine/panel_resolver.py)) are **stateless free functions** that take their dependencies (`state`, `controller`, `source_registry`, `scene_registry`, `tree`, `view`) explicitly. This keeps `boot.py` a registration shell and makes the handlers unit-testable.

---

## 2. The per-view scene model

### 2.1 The duality: LEGACY vs PER-VIEW

Two object models coexist, by design (this is a multi-phase in-progress refactor; see `doc/REFACTOR_VIEW_SCENES.md`, `REFACTOR_PER_VIEW_PHASE_3.md`):

| | LEGACY — `SourceRegistry` | PER-VIEW — `SceneRegistry` |
|---|---|---|
| Granularity | one entry **per rep** (view-agnostic) | one `ViewScene` **per panel**, each with one `RepInScene` **per (rep, view)** |
| Owns | `ExtractBlockRepresentation` + `IjkGrid` (shared) proxies | per-view `EnergisticsExtractor`, threshold chain, `SlicePlane`/`ClipPlane`, per-view `IjkGrid`, per-(child,view) channel/marker extractors, per-`(scene,array)` LUT/PWF |
| Lifecycle driven by | `data_load.run → source_registry.sync(...)` | `@state.change("ui_loaded_rep_paths") → scene_registry.sync_loaded_reps(...)` + `MultiView.add_view/close` |
| Status | Phase-2 **fallback** | the **live** model for coloring / slice / clip / threshold / markers / channels |

[`source_registry.py`](fespp_on_trame/app/core/sources/source_registry.py) is explicitly annotated as deprecated for the mutating ops (`add_threshold`, `slice_set`, …; each warns via `_warn_deprecated`). It is still alive for: **data load** (`sync`, `ensure_ijk_grid`, `get_or_create_extract_block`), **read-side** array introspection, and as the **fallback** when a per-view proxy can't be built yet.

**When is the legacy path actually live (the "Phase-2 fallback")?** A `ViewScene` tries to create a real `vtkEPCCollectorClone`; if the plugin definition is missing (out-of-date dll), `_create_clone()` returns `collector.get_source()` itself as the clone. In that state `Representation.ensure_extractor` / `IjkGridRep.ensure_per_view_ijk` detect `clone is collector.get_source()` and **return None**, so `RepInScene.source()` falls back to `_fallback_legacy_source()` (the `SourceRegistry` proxy) and `source_resolver`'s per-view branch returns `None` → it walks the legacy `get_ijk_grid` / `get_extract_block` branches. Normal operation (real clone present) keeps everything per-view.

### 2.2 ViewScene + RepInScene + ElementType

```
SceneRegistry._scenes : {view_id → ViewScene}
        │
        ▼
ViewScene(view_id, pv_view, collector, tree)
   ├─ _clone : vtkEPCCollectorClone  (hidden everywhere; structural anchor)
   ├─ _reps  : {rep_path → RepInScene}
   ├─ _luts  : {base_array_name → LUT proxy}   scoped  f"{base}__{view_id}"
   └─ _pwfs  : {base_array_name → opacity-TF}  scoped  f"{base}__{view_id}"
        │
        ▼
RepInScene(scene, rep_path)
   ├─ element_type            ← lazy: element_type.for_path(tree, rep_path)
   ├─ _extractor              ← per-(rep,view) EnergisticsExtractor  (None for IJK)
   ├─ _per_view_ijk           ← per-(rep,view) IjkGrid pipeline      (IJK only)
   ├─ _chain    : [ChainEntry]  per-view threshold chain (non-IJK)
   ├─ _slice_plane / _clip_plane
   ├─ _channel_extractors : {channel_path → ext}  (Frame: one shown at a time)
   └─ _marker_extractors  : {marker_path  → ext}  (MarkerFrame: many shown at once)
```

[`view_scene.py`](fespp_on_trame/app/core/sources/view_scene.py) `ViewScene`:
- `_create_clone()` instantiates `EPCCollectorClone` chained on `collector.get_source()`, forces `Visibility=0` in every view. The clone is a ShallowCopy passthrough — zero data duplication; any EPCCollector update invalidates it natively via the PV pipeline.
- **Per-`(scene, array)` LUT/PWF** (`get_or_create_lut` / `get_or_create_pwf`): PV's default `GetColorTransferFunction(name)` is a global singleton keyed by array name, so a color-editor edit in one view would bleed into all views sharing that array. The scene registers a distinct LUT under `f"{base}__{view_id}"`, seeded once from the global template's `RGBPoints`/`NanColor`/… A fresh PWF is flattened to opacity 1 (PV's default 0→1 ramp would hide the lowest scalar). `replicate_tfs_from(ref_scene)` mirrors LUT/PWF property-by-property onto a split view.

[`rep_in_scene.py`](fespp_on_trame/app/core/sources/rep_in_scene.py) `RepInScene` is the per-(rep,view) state holder. The behavioural decisions are **delegated to its `element_type`** (the strategy pattern, "Option A": `RepInScene` keeps the per-(rep,view) *state*, the stateless `ElementType` singleton keeps the *behaviour* and receives `ris=self`):
- `source()` → `element_type.ensure_source(self)`
- `_ensure_extractor()` → `element_type.ensure_extractor(self)` (caches on `self._extractor`)
- `set_channel_visible` / `set_marker_visible` → `element_type.set_child_visible(self, …)`
- `_refresh_parent_rep_visibility()` → `element_type.refresh_primary_visibility(self)`
- threshold ops (`add_threshold`/`set_range`/`set_visible`) branch on `_is_ijk_grid()`: IJK reps forward to the per-view `IjkGrid` via `_ijk_provider()`; non-IJK reps own a local `_chain` of `ChainEntry` (reused from `extract_block.py`).
- snapshot/apply primitives (`snapshot_threshold_chain`/`apply_threshold_chain`, `snapshot_slice`/`apply_slice`, `snapshot_clip`/`apply_clip`, `snapshot_ijk_slicers`/`apply_ijk_slicers`) — JSON-safe dicts used for view replication (§3f).

### 2.3 The ElementType hierarchy

[`element_type/`](fespp_on_trame/app/core/element_type/__init__.py) is the single source of truth for "how does a RESQML element of this runtime `kind` behave", replacing scattered `if kind == "..."` branches. A class is indented **under the file it lives in** (left column = location on disk); the `(BaseClass)` carries the **general → family → unit** inheritance, so a cross-file parent is visible at a glance (e.g. `FrameRep(Representation)` lives in `frames.py`):

```
base.py
    ElementType                          contract + neutral defaults
grouping.py
    Grouping(ElementType)                folder, tri-state, no source
    PartialType(Grouping)                Partial: folder, NOT selectable
representation.py
    Representation(ElementType)          geometry + eye + per-view source
    GridRep(Representation)              UnstructuredGrid, Sub
    IjkGridRep(GridRep)                  IjkGrid — modal (slicers + volume)
    SurfaceRep(Representation)           Grid2d, PointSet, Polyline*, TriangulatedSet
    WellboreGeometryRep(Representation)  Trajectory, Completion, Perfo, Perforation
    SeismicFrameRep(Representation)      SeismicWellboreFrame
frames.py
    FrameRep(Representation)             folder-for-tree, rep-for-source
    ChannelFrameRep(FrameRep)            kind 'Frame' → VisibilityPolicy.ONE_AT_A_TIME (logs)
    MarkerFrameRep(FrameRep)             kind 'MarkerFrame' → VisibilityPolicy.MULTI (markers)
leaf.py
    Leaf(ElementType)                    sub-element, not a rep
    PropertyLeaf(Leaf)                   colours the parent rep
    MarkerLeaf(Leaf)                     toggles ONE marker
```

[`registry.py`](fespp_on_trame/app/core/element_type/registry.py): each concrete class is instantiated **once** (stateless singleton) and registered under each of its `KINDS`; collisions raise at import. `for_kind(kind)` is an O(1) dict lookup (unknown/None → a generic `Representation` `_FALLBACK`); `for_path(tree, path)` resolves via the live assembly. The runtime `kind` strings are FESPP's `SimplifyXmlTag` output ('Frame', 'MarkerFrame', 'Marker', 'Sub', …), **not** the C++ enum names.

Key behaviours the hierarchy decides (all consumed by `source_resolver` and `RepInScene`):
- `rendered_sources(ris)` / `color_sources(ris)` — which per-view proxies a rep renders / ColorBy fans onto. `None` → fall through to legacy. (e.g. `IjkGridRep` returns slicers+volume+rep_data+threshold leaves; `ChannelFrameRep` returns only the visible channel's extractor.)
- `array_candidate_source(ris, array_path)` — which per-view source carries `array_path`'s VTK array (channel frame → the channel's own extractor; others → the primary extractor).
- `primary_hidden()` — True on `FrameRep` (children render via their own extractors, the frame's primary must never Show).
- `visibility_policy()` — STANDARD / IJK_MODAL / ONE_AT_A_TIME / MULTI.

### 2.4 How a rep is materialised per (rep, view)

For a **standard rep** (`Representation.ensure_extractor`, [representation.py:71](fespp_on_trame/app/core/element_type/representation.py)):
1. registration name `rep_{_sanitize(rep_path)}_v{view_id}`.
2. `_create_plugin_filter_proxy("EnergisticsExtractor", inputs={"Input": clone})`.
3. `ExtractPath = rep_path` via `vtkSMPropertyHelper`.
4. Hide in every non-target view; in the target view set `Representation`, `Scale=[1,1,z]`, default tint; **hide the legacy ExtractBlock** in that view (avoid Z-fight); Show unless the rep is a frame primary or flagged hidden in this view's bucket.

For an **IjkGrid rep** (`IjkGridRep.ensure_per_view_ijk`): reads the legacy shared `IjkGrid`'s current `_node_id`/`_property_path` to know which property to colour, forces `clone.UpdatePipeline()` (so the slicers pick the right output type), builds a fresh per-view `IjkGrid(collector, tree, view_id, clone, pv_view)`, then `_hide_legacy_ijk_in_scene_view(legacy)` to stop double-rendering.

For a **frame child** (channel or marker, `FrameRep._create_child_extractor`): an `EnergisticsExtractor` with `ExtractPath = child_path`, registered `chn_…_v{view}` (channels) or `mrk_…_v{view}` (markers). `ChannelFrameRep.set_child_visible` is **exclusive** (Show one log, Hide all siblings); `MarkerFrameRep.set_child_visible` is **independent** (toggle one marker, siblings untouched).

---

## 3. End-to-end flows

### (a) User checks a tree node → load → render

```
Vue checkbox  ──► state.ui_select_node_reservoir (or _surface / _well)
   @state.change("ui_select_node_reservoir")  → selection_dispatch.on_change_ui_select_node_reservoir
       (load_mode=="auto" only) → Selector.select_node_reservoir()
           builds path list via tree.find_path(node_id); creates Wellhead/TimeSeries companions
           writes state.fespp_data_selectors = reservoir + surface + well
   @state.change("fespp_data_selectors") → data_load.run(...)        ← THE load pipeline
```
[`data_load.run`](fespp_on_trame/app/core/engine/data_load.py) (order matters, heavily commented):
1. `active_source.get_source().SetPropertyWithName('Selectors', …)` + a single `UpdatePipeline()` (the C++ side does `ClearSelectors`+`AddSelector×N` Modified-only, so one RequestData here materialises the multiblock once).
2. **Hide the parent multiblock rep** (`representation.Visibility = 0`, `BlockSelectors=['/data']`) — each rep renders via its own extract, so leaving the parent visible would scale O(N) per add.
3. Reserve a distinct chip colour per newly-loaded rep into `state.solid_color_by_rep` (BEFORE the sync, so new sources tint immediately).
4. `source_registry.sync(fespp_data_selectors, ui_select_node_reservoir)` — creates/drops `ExtractBlock`+`IjkGrid` instances; refreshes `BlockSelectors`.
5. Bump every source's pipeline info (`Modified()` + `UpdatePipelineInformation()`), plus a full `UpdatePipeline()` on IjkGrid `rep_data` + slicers (a documented gotcha: without the data pass the slicer caches an array-less output and the activator misses the property).
6. `activator.notify_active_reps(present_paths)` (hide stale color bars).
7. visibility tracking (`_update_visibility_tracking` → `ui_loaded_rep_paths`, prunes `ui_hidden_rep_paths_by_view`, appends new reps to **non-active** panels' hidden buckets so a first selection appears only in the active view).
8. data-array tracking (`_update_data_array_tracking` → `ui_loaded_array_paths`; "last array added per rep" rule).
9. marker tracking (`_update_marker_tracking` → `ui_loaded_marker_paths`).
10. active-array maps (`_update_active_array_maps` → `ui_active_array_by_rep` + per-view map; newly-loaded array auto-activates **in the active panel only**; MR seeds `ui_active_realization_by_array_by_view` BEFORE the active-array write).
11. **synchronous teardown** of deselected reps' per-view pipelines (`scene.remove_rep`) — the deferred `sync_loaded_reps` runs after the render, and rendering a still-visible source whose upstream partition is gone segfaults.
12. `activator.refresh_active()`, `refresh_threshold_ui()`, `push_active_ijk_state()`, single `pvsimple.Render(view)`.

Separately, `@state.change("ui_loaded_rep_paths") → scene_registry.sync_loaded_reps(...)` adds a `RepInScene` per scene per newly-loaded rep and **eagerly** sets it up (`_eager_setup_rep_in_scene`: force per-view extractor, gate Show on `_hidden_in_scene()`, replicate the active panel's ColorBy onto the new scene). It also re-applies the current Z-scale so a freshly-loaded object inherits it.

### (b) Eye toggle = show / hide

Tree rep-eye click → `controller.toggle_rep_visibility(rep_path, panel_id)` → [`visibility.toggle_rep_visibility`](fespp_on_trame/app/core/engine/visibility.py). It is a plain **show / hide** toggle — visibility and colouring are orthogonal, so this eye never touches the colour array: it flips `rep_path` in `ui_hidden_rep_paths_by_view[bucket_key]` (mirrored to global `ui_hidden_rep_paths` iff this is the active panel), resolves sources via `source_resolver.sources_for_rep_path` (IjkGrid → `ijk.show(view)`; ExtractBlock → `pvsimple.Show` + re-assert Representation/tint), then renders the **target panel's** `pv_view` and pushes the frame to `html_view` (per-panel), not just the active view.

> It used to be a 3-state chip whose first click "gave up the colouring" (→ SolidColor) and only hid on the second, with a `_clear_active_array` helper and an `is_frame` exemption. That made hiding a rep necessarily DESTROY its active array, so **"hide the grid, keep its blocked wellbores coloured by PORO" was unexpressible** — and it violated the orthogonality this document opens with. Dropping a colour array is the array eye's job alone. Symmetrically, `active_array.toggle_dataarray_color` no longer implicitly un-hides + Shows a hidden rep: **colouring a hidden rep is a legal, useful state.**

Markers (`toggle_marker_visibility`) and data-array eyes (`active_array.toggle_dataarray_color`) follow the same panel-targeted render+push pattern.

### (c) ColorBy / coloring

Data-array eye → `controller.toggle_dataarray_color(array_path, panel_id)` → [`active_array.toggle_dataarray_color`](fespp_on_trame/app/core/engine/active_array.py):
- resolves `r_path = tree.find_path(tree.find_representation_node(node_id))`.
- toggles `ui_active_array_by_rep_by_view[bucket][r_path]` (and global mirror iff active panel); for MR, seeds/clears the per-view realization in `ui_active_realization_by_array_by_view`.
- if the rep was hidden in this panel, implicitly un-hides + shows it.
- for a **channel** frame, `rep_in_scene.set_channel_visible(array_path, True)` FIRST (exclusive show), then `source_resolver.apply_color_array(...)`.

[`source_resolver.apply_color_array`](fespp_on_trame/app/core/engine/source_resolver.py) is the coloring workhorse:
1. `displays_for_rep_path` → displays of `color_sources_for_rep_path` (which asks `element_type.color_sources(ris)` first, appends the per-view clip output, falls back to legacy).
2. `resolve_array_for_path` → `(assoc, vtk_name)` — tries MR-suffixed `<title>_real_<idx>` first, then raw title, then `make_valid_vtk_name(title)` (FESPP strips chars outside `[-.0-9A-Z_a-z]`); for channels the raw title is preferred (`real_base_name`).
3. `pvsimple.ColorBy(d, (assoc, name))` on each display. SolidColor clear uses `SMProxy.SetScalarColoring("",0)` (PV6's `ColorBy(d, None)` raises "invalid association string NONE").
4. **`swap_to_scene_tfs(displays, view, name)`** — re-binds each display's `LookupTable`/`ScalarOpacityFunction` to the per-`(scene, array)` LUT/PWF (so an edit in one view doesn't bleed). The scope name lives only in `ViewScene._scoped_tf_name`.
5. `RescaleTransferFunction` from the client-side array range (`_vtk_array_range_from_clientside`) — works around PV's stale proxy-info cache after an in-place re-extraction.
6. `SetScalarBarVisibility(view, True)` (canonical path through `vtkSMTransferFunctionManager`) + `hide_unused_scalar_bars(view)`.

`@state.change("ui_active_array_by_rep") → active_array.on_active_array_change` re-applies ColorBy across loaded reps on the active view.

### (d) Z-scale (global vertical exaggeration)

Source of truth: **`state.ui_scale_z`** (a single float, default 1.0, seeded in three places: `state_defaults`, `state.setdefault` in boot, and `@state.change`).

```
slider → state.ui_scale_z
  @state.change("ui_scale_z") → slicer_dispatch.apply_z_scale(state, controller, source_registry, _view, zscale)
```
[`slicer_dispatch.apply_z_scale`](fespp_on_trame/app/core/engine/slicer_dispatch.py):
1. `source_registry.apply_z_scale(zs)` (legacy ExtractBlocks).
2. **Per-scene fan-out** — the visible displays live on per-(rep,view) proxies, not the shared sources. For every scene, for every proxy from `_collect_scene_proxies(scene)` + legacy, write `disp.Scale = [1,1,zs]` via `_set_scale_preserving_color` (saves/restores ColorArrayName+LUT because some PV builds clobber coloring on a Scale write).
3. **Markers are the exception** — they are symbolic geometry (sphere / oriented disk). Scaling Z would turn a sphere into an olive. `marker_dispatch.is_marker_proxy(p)` (name-based: `mrk_` prefix) routes them to `marker_dispatch.apply_marker_z(disp, source, zs)`, which **TRANSLATES** Z by `(zs-1)*z_center` (real geometry **scales**, markers **translate**). It reads the marker's unscaled bounds for `z_center`.
4. **PV5.13+/PV6 rename:** the display "Position" property became "Translation" (reading/writing the old name raises `NotSupportedException`, even `hasattr`). `apply_marker_z` tries `Translation` first, falls back to `Position` for older builds.

The persistence note (recent commit `60e2ced`): `@state.change("ui_loaded_rep_paths")` re-applies `apply_z_scale` so a newly-loaded object — whose per-view extractor was created with z-scale baked at build time — inherits the current global value even when shown in a non-owning / split view or re-shown after hiding. Channel extractors scale; marker extractors translate (`FrameRep._apply_child_z` is overridden by `MarkerFrameRep`).

### (e) Threshold / Slice / Clip

**IJK slicers** (`ui_slices_*`): `@state.change` handlers in boot → `slicer_dispatch.update_slice_positions/range/mode/visibility/volume`. Each resolves `_active_ijk_grid(state, source_registry)` which **prefers the drawer-target view's per-view `IjkGrid`** (via `scene_registry.get_rep(target, rep).{_per_view_ijk}`), falling back to the legacy shared IjkGrid. Then `active.apply_*(...)` + `active.show()` + `_render_and_push` (renders the target's `pv_view` and pushes to both the target panel and the active panel — covers pinned mode). Each view owns its own slicer state; on panel switch `_push_active_ijk_state_to_ui` republishes the active view's snapshot into the flat `ui_slices_*` vars.

**Slice** ([`slice_dispatch`](fespp_on_trame/app/core/engine/slice_dispatch.py)): `controller.slice_set(enabled, axis, offset, panel_id)` → resolves `(panel_id, active_representation_path)` → `RepInScene.slice_set(...)` (which creates/updates a per-(rep,view) `SlicePlane`, and toggles parent-rep visibility: enabling slice/clip Hides the rep's primary in *that scene's* view only). `publish_slice_state` pushes the descriptor into `ui_slice_*` (incl. server-computed `ui_slice_offset_min/max/step`). **Clip** is the symmetric `clip_dispatch` + `ui_clip_*`.

**Threshold** (`threshold_dispatch`): `controller.threshold_add/delete/set_range/set_visible` operate per-view through `RepInScene` (non-IJK reps own a local `_chain`; IJK reps forward to the per-view `IjkGrid._chain`). `_refresh_threshold_ui_for_active_grid` publishes the active panel's chain to `ui_threshold_chain` for the panel to render.

All three concerns re-publish their flat UI vars on `active_representation_path` change, on `fespp_active_panel_id` change (`_on_active_panel_change`), and on `drawer_target_view_id` change — so the panel sliders always reflect the targeted view's actual state.

### (f) Add-view / split + state replication

```
"+View" / split → MultiView.add_view(kind, replicate, direction, reference_panel_id)
```
[`multi_view.py FesppMultiView.add_view`](fespp_on_trame/app/ui/content/view/multi_view.py):
1. New `panel_id = f"ptc_view_{n}"`; first view **adopts** the engine's pre-existing RenderView, later views `CreateRenderView()`.
2. `scene_registry.add_view(panel_id, pv_view)` then `sync_loaded_reps(...)` — the new `ViewScene` gets a `RepInScene` per already-loaded rep.
3. If `replicate` (default for `kind=="render"`): `_replicate_visibility(ref_view, new_view)` copies non-color display props (NOT ColorArrayName/LookupTable — copied field-wise leaves PV6 in a hybrid SolidColor+outline state; skips `fespp_diff*` and per-view proxies of other scenes), then `scene_registry.replicate_view(ref_panel_id, panel_id)` replays per-(rep,view) **threshold/slice/clip/ijk_slicers** via the snapshot/apply primitives.
4. `_seed_per_view_hidden_state` copies the ref panel's hidden / active-array / active-realization / visible-marker buckets (or, for an **empty** render view, seeds the hidden bucket with *every* loaded rep so all chips appear closed).
5. `scene_registry.apply_visible_markers(panel_id)` re-creates the inherited markers' extractors.
6. After wiring: `controller.apply_panel_coloring(panel_id)` re-runs the full `pvsimple.ColorBy` from the per-view active-array bucket, `new_scene.replicate_tfs_from(ref_scene)` mirrors the LUT/PWF gradient, `_enforce_view_visibility_from_ref` removes phantom outlines, then Render + `html_view.update()`.

`_on_view_closed` tears down the `ViewScene` (`scene_registry.remove_view`), drops the panel's per-view buckets and camera-link entries, clears singleton trackers. `_on_view_activated` publishes `fespp_active_panel_id`/`_title` and `_mirror_active_hidden_state()` (active panel's buckets → legacy globals). `fespp_render_panels` is republished on every add/close; `boot`'s `_on_render_panels_change` auto-depins the drawer target when its pinned view closes.

The single-concern **"Copy from View X"** buttons go through `controller.copy_{threshold_chain,slice,clip,ijk_slicers}_from(src,dst,rep_path)` → `boot._copy_concern` → `RepInScene.snapshot_* / apply_*` (single rep) or `scene_registry.replicate_view(src,dst,concerns=(...))` (all reps).

---

## 4. State catalog

Vars seeded in [`state_defaults.init_state_defaults`](fespp_on_trame/app/core/engine/state_defaults.py) unless noted. "Writer" / "Reader" name the engine modules / UI.

### Selection & load
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| `ui_select_node_reservoir / _surface / _well` | per-tab checked node ids | TreeViews (Vue) | `selection_dispatch`, `Selector` |
| `fespp_data_selectors` | flat list of assembly paths to load | `Selector.select_node_*` | `@state.change → data_load.run` |
| `load_mode` | `"auto"` (push on toggle) / `"manual"` (Load button) | toolbar | `selection_dispatch` |
| `tree_hierarchy_mode` | `"flat"` / Feature / Interpretation | toolbar | `hierarchy` |
| `ui_subtree_reservoir / _surface / _well` | nested treeview dicts (sorted) | `Tree.set_tree` | TreeViews |
| `has_data_loaded_once` | reset-camera-once latch | `data_load.run` | `data_load.run` |

### Loaded / visible / coloring (global + per-view)
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| `ui_loaded_rep_paths` | reps materialised in PV (eye rendered) | `data_load._update_visibility_tracking` | tree, `scene_registry.sync_loaded_reps`, `active_array` |
| `ui_hidden_rep_paths` | subset hidden via eye (active-panel mirror) | `visibility`, `multi_view._mirror_active_hidden_state` | legacy consumers, `RepInScene` guards |
| `ui_hidden_rep_paths_by_view` | `{panel_id → [rep_path]}` hidden per view (**source of truth**) | `visibility`, `data_load`, `multi_view` | `RepInScene._hidden_in_scene`, tree chips |
| `ui_loaded_array_paths` | data-array nodes whose data is loaded | `data_load._update_data_array_tracking` | tree, `diff` |
| `ui_active_array_by_rep` | `{rep_path → array_path}` coloring (active-panel mirror) | `data_load`, `active_array`, `multi_view` | `Activator`, `solid_color_panel`, `on_active_array_change` |
| `ui_active_array_by_rep_by_view` | `{panel_id → {rep_path → array_path}}` (**source of truth**) | `data_load`, `active_array`, `multi_view` | tree eye annotation, `apply_panel_coloring`, MR/TS derivations |
| `ui_loaded_marker_paths` | marker leaves carrying an eye | `data_load._update_marker_tracking` | tree |
| `ui_visible_marker_paths_by_view` | `{panel_id → [marker_path]}` shown markers | `visibility.toggle_marker_visibility`, `multi_view` | `scene_registry.apply_visible_markers` |
| `solid_color_by_rep` | `{rep_path → hex}` chip colour (seeded in `solid_color_panel`) | `data_load`, color panels | extractor build, tint |
| `solid_color_by_marker` / `solid_color_next_idx` | per-marker colour / palette cursor | color panels | `MarkerFrameRep._child_tint` |
| `panel_has_ts_by_id` | `{panel_id → bool}` has a TimeSeries active | `active_array.on_active_array_by_view_change` | per-view TimeControl |

### Multi-realization
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| `ui_active_realization_by_array_by_view` | `{panel_id → {array_path → idx}}` | `data_load`, `active_array`, `realization_dispatch` | `source_resolver` (suffix resolution), pickers |
| `ui_panel_active_mr_specs_by_id` / `panel_has_mr_by_id` | per-panel MR specs / has-MR flag | `realization_dispatch.recompute_*` | per-view RealizationPicker |
| `ui_global_mr_specs / _selected_path / _selected_spec` | tools-band global picker | `realization_dispatch` | global RealizationPicker |

### Z-scale / representation / markers
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| **`ui_scale_z`** | **global vertical exaggeration (source of truth)** | slider | `slicer_dispatch.apply_z_scale`, extractor build, `RepInScene._current_z_scale` |
| `representation_active` | Surface/Wireframe/Points/… | drawer | `slicer_dispatch.apply_representation_type` (per-rep, mirrored in `ui_rep_type_by_rep`), extractor build |
| `marker_orientation` (bool) / `marker_size` (int) | global marker disk-vs-sphere / radius (seeded in boot) | toolbar | `marker_dispatch.apply_marker_options` (on EPCCollector) |

### Slicer / threshold / slice / clip
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| `ui_slices_{i,j,k}_list` / `_visible_list` | IJK slice positions / per-slicer visibility | SlicersPanel | `slicer_dispatch`, per-view `IjkGrid` |
| `ui_slices_range_{i,j,k}` / `_range_mode` / `_volume_visible` | IJK crop range / slice-vs-range mode / volume eye | SlicersPanel | `slicer_dispatch` |
| `ui_threshold_chain` / `_arrays_available` / `_pending_action` | published chain / arrays / queued op | `threshold_dispatch` | ThresholdPanel |
| `ui_slice_enabled / _axis / _offset / _bounds / _offset_min/max/step` | active rep's slice descriptor (flat mirror) | `slice_dispatch.publish_slice_state` | SlicePanel |
| `ui_clip_enabled / _axis / _offset / _inside_out / _bounds / …` | clip descriptor | `clip_dispatch.publish_clip_state` | ClipPanel |
| `ui_plane_edit_mode` | which plane widget is editable (`slice`/`clip`/None) | plane panel | plane widget |

### Panels / drawer target / view status
| `state.*` | Meaning | Written by | Read by |
|---|---|---|---|
| `fespp_active_panel_id / _title` | focused render panel | `multi_view._on_view_activated` | engine `_on_active_panel_change`, contextual band |
| `fespp_render_panels` | `[{id,title}]` render-only panels | `multi_view._publish_panels_state` | tree eye row, `_on_render_panels_change` |
| `drawer_target_view_id` / `drawer_target_view_pinned` | which view the edit panels operate on / pinned-vs-follow | drawer picker, engine follow-mode | `slice/clip/slicer_dispatch`, `source_resolver.target_view_and_panel` |
| `fespp_stats_panel_id` / `fespp_diff_panel_id` | singleton dockview ids | `multi_view` | open/close logic |
| `ui_stats_pinned_paths` / `ui_stats_tables` / `ui_stats_panel_state` | stats pinned set / computed tables / per-row selectors | `stats_dispatch` | DescriptiveStatsPanel |
| `ui_stats_compare*` / `ui_distribution_*` | compare carts/panels / per-panel histogram option+figure vars | `boot` + `stats/distribution_dispatch` | Compare/Distribution panels |
| `view_update` / `view_reset_camera` | trigger flags for `view_ops` | many | `view_ops` |
| `vtk_log_messages` / `vtk_log_visible` | stderr tee mirror | `vtk_log` | VTK log panel |
| `upload_*` | upload progress/session | upload route | upload UI |

---

## 5. Key invariants & conventions

- **`rep_path` is the global identity key.** Everything below the UI keys on the `vtkDataAssembly` node path (`tree.find_path`), never on sibling list position. `Tree._sibling_sort_key` reorders the emitted `ui_subtree_*` dicts (natural, accent-stripped, case-insensitive) purely for display — safe because identity is by `id`/`path`.

- **Proxy registration-name prefixes** (used both for creation and for name-based recognition):
  - `rep_{sanitize(rep_path)}_v{view_id}` — per-(rep,view) primary `EnergisticsExtractor` (`Representation.ensure_extractor`).
  - `chn_{sanitize(child_path)}_v{view_id}` — per-(channel,view) extractor (`ChannelFrameRep`, `_reg_prefix="chn"`).
  - `mrk_{sanitize(child_path)}_v{view_id}` — per-(marker,view) extractor (`MarkerFrameRep`, `_reg_prefix="mrk"`). **`marker_dispatch.is_marker_proxy` recognises markers by the `mrk_` prefix** to translate (not scale) their Z.
  - `EPCCollector_View{view_id}` — the per-view `vtkEPCCollectorClone`.
  - `thr_{rep}_{array}_v{view}` (or `{parent}_{array}`) — per-view threshold `ChainEntry` proxies; suffixed `_v{view_id}` so chains from different views never collide on PV's proxy registry.
  - `MultiView._is_per_view_source(name)` recognises a per-view proxy by checking whether **any** tracked `panel_id` appears as a substring of the name — used to *skip* foreign-scene proxies during replication (calling `GetDisplayProperties` on them in the wrong view lazily creates a `Vis=1 Outline` phantom).

- **Per-view LUT/PWF scoping.** Color/opacity transfer functions are registered per `(scene, base_array_name)` under `f"{base}__{view_id}"` (`ViewScene._scoped_tf_name`). Coloring code rebinds displays to these via `source_resolver.swap_to_scene_tfs`; the global singleton LUT is only a seeding template. This is what lets two views colour the same array with different gradients.

- **VTK array-name sanitizer.** FESPP strips characters outside `[-.0-9A-Z_a-z]` from VTK array names. `make_valid_vtk_name(title)` (in `app/utils/naming.py`) reproduces this. Resolution tries, in order: MR-suffixed `<sanitized>_real_<idx>` → raw title → sanitized title. Channels are special: their POINT array carries the **raw, unsanitized** title (`real_base_name` probes the source to decide).

- **`ExplicitSelection=1` on the EPCCollector.** Selecting a non-grouping node is literal — a grid does **not** auto-load its properties. UI-side dependency expansion (auto-check Trajectory when a Channel is checked, expand a grouping's descendants) happens in `tree_views.py` *before* `Selector`, so `optimize_tree_selection` is the identity.

- **Frame primary stays hidden.** A `Frame`/`MarkerFrame` is a folder-for-the-tree but a representation-for-the-source (C++ `MapperSet`). `primary_hidden()` is True for `FrameRep` so the generic visibility refreshers never `Show` the frame's primary extractor (which the C++ side resolves to the frame's first child, re-surfacing a log/marker the user never picked). Channels render exclusively (one log), markers render multiply.

- **Render + push is per-panel.** `controller.view_update()` only refreshes the active panel; edit handlers that target a non-active (pinned) view call `controller.view_update_for(panel_id)` and Render that panel's `pv_view`. Many handlers push to **both** (target + active) to cover follow and pinned modes.

- **Order-sensitive load + teardown.** `data_load.run` hides the parent rep before any Render, writes the MR realization bucket *before* the active-array bucket, and synchronously tears down deselected reps' per-view pipelines *before* the activator render (a stale visible source over a removed partition segfaults natively with no traceback).

- **Defensive `try/except` everywhere in the source layer.** PV proxy operations are wrapped so a single bad proxy can't abort a multi-rep loop — the operation is skipped rather than raising. (The release build is quiet: the verbose `[WARNING]`/`[SCENE_REG]`/`[ViewScene …]` diagnostics that used to narrate this bookkeeping have been removed; re-add targeted logging while debugging if needed.)
