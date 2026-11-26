# Core — Sources (ParaView pipeline)

> **19/10/2026 — the per-representation model is gone (overhaul, decision Q2 bis).** `RepInScene`, `ViewScene`, `SceneRegistry`, the activator, the legacy visibility and active-array dispatch, the slice / clip planes and the `FESPP_BLOCKSCOPE` flag were removed: each view draws through its composite scene (`engine/blockscope`), a cut or filtered grid through its `GridIsolate`. A passage below that still names them describes removed code.

> **Read this first (2026-09-16).** The package is `fespp_on_trame/engine/sources/` today. The per-view model below (`ViewScene`, `RepInScene`, the clone, slice / clip planes) is the **legacy path**, live only with `FESPP_BLOCKSCOPE` unset; the production image runs the BlockScope scene of `engine/blockscope` (one composite representation per view — [[Architecture]] §2). What this page says of `Collector`, `ActiveSource`, the ETP connector, `IjkGrid` (the per-view isolates of the Slicers and Thresholds cards) and `threshold_chain` still holds on both paths.

This subsystem (`fespp_on_trame/engine/sources/`) is the architectural heart of the app: it owns every ParaView ServerManager (SM) proxy that turns a loaded RESQML/EPC dataset into visible geometry, and it does so through **two coexisting generations of pipeline** that you must understand before touching anything.

**The legacy generation** is keyed by `rep_path` only — one source per representation, shared across all render views. It lives in `SourceRegistry` (the dict-of-instances manager), `ExtractBlockRepresentation` (non-IjkGrid reps), and `IjkGrid` (the modal I/J/K-slicer pipeline). **The per-view generation** is keyed by `(rep_path, view_id)` — one source *per render panel* — and lives in `SceneRegistry` → `ViewScene` → `RepInScene`. The migration from legacy to per-view happens in numbered "Phases" referenced all over the docstrings (1.b, 2, 3a, 3b, 3c, 4, 5); at the current state of the branch, non-IjkGrid reps are fully per-view (Phase 3a), IjkGrid reps run a per-view pipeline that *mirrors* a still-authoritative legacy `IjkGrid` (Phase 3b), and the legacy `ExtractBlockRepresentation` / `SourceRegistry` slice/clip/threshold methods are deprecated fallbacks (Phase 4) that only fire when the `vtkEPCCollectorClone` plugin proxy is unavailable.

The data flow is: a C++ `EPCCollector` source (wrapped by `Collector`) reads the EPC/RESQML file into a single multiblock assembly. Each `ViewScene` chains a `vtkEPCCollectorClone` (a zero-copy ShallowCopy passthrough) on the collector as its per-view structural anchor. `RepInScene` then chains a per-(rep, view) `EnergisticsExtractor` (set `ExtractPath = rep_path`) on that clone, and slice/clip/threshold filters chain on the extractor. The per-kind *behaviour* (which extractor to build, what to show/hide, how children render) has been factored OUT of `RepInScene` into the `fespp_on_trame.app.core.element_type` hierarchy (`Representation`, `IjkGridRep`, `ChannelFrameRep`, `MarkerFrameRep`, …) via a strategy pattern: `RepInScene` keeps the per-(rep, view) *state*, the `ElementType` subclass supplies the *policy*, receiving `RepInScene` as `ris`.

> Note on read scope: this page documents the files under `core/sources/`. To describe `rep_in_scene.py` accurately I also read its delegation target `core/element_type/{representation,frames}.py`; those are documented in their own pages but referenced here where the real logic lives.

> **⚠️ Refactor update (`refactoring` branch).** A behaviour-preserving dedup pass moved several formerly-duplicated helpers into shared modules. Where the per-file notes below say a helper is "duplicated 3×" / "mirrors the same helper", that is the *pre-refactor* description — it now reads:
> - `representation.inherit_display(upstream, target, view)` — threshold-output display inheritance (was 3 copies).
> - `representation.arrays_from_source` / `array_range_from_source` / `resolve_assoc` — array introspection (was 3 copies).
> - **`threshold_chain.py`** (new, dependency-free; in `engine/legacy/` since the overhaul's slice 7, imported lazily by the legacy-only chain methods of `ExtractBlockRepresentation`) — the single-upstream threshold-chain graph walk + `refresh_chain_visibility` rewiring, shared by `RepInScene` and `ExtractBlockRepresentation` (each passes its own root/view/rep-hidden policy). `IjkGrid`'s MULTI-upstream chain is separate.

---

---

### `fespp_on_trame/engine/sources/ijkgrid.py`

**Responsibility.** The modal I/J/K slicer + volume-crop + threshold pipeline for ONE IJK reservoir grid. Used in two modes from a single class: **legacy shared-instance** (no view args; `Show/Hide` track the active view) and **per-view** (Phase 3b: pass `view_id`/`clone`/`pv_view`; rep_data is an `EnergisticsExtractor` on the clone and all rendering targets the captured `pv_view`).

**Key classes / functions.**

`class _IjkChainEntry` — one threshold-chain node, the only one since the per-representation model went (Q2 bis). It holds `pv_proxies: dict` keyed by `id(upstream_source)` → a Threshold proxy, because an IJK threshold must attach to EVERY active upstream (rep_data + each slicer in slice mode; rep_data + each volume crop in range mode). Carries `kind`/`unique_values`/`labels` for the threshold-panel slider variant; `to_dict()`.

`class IjkGrid`
- `__init__(collector, tree, *, view_id=None, clone=None, pv_view=None)` — `view_id`/`clone`/`pv_view` are all-or-none. When set → per-view mode. State includes `_node_id`, `_property_path`, `_current_extent`, `_rep_token` (PV name suffix, includes `view_id` in per-view mode), `_src_extract_init` (rep_data), `_src_slicers_{i,j,k}` lists, `_src_volumes` (range-mode volume crops, one per UI volume), `_chain`, `_slice`/`_clip` (DEPRECATED, normally None), and per-instance slicer UI state (`_slices_*_list`, `_slices_*_visible_list`, `_volumes` + `_volumes_visible` (per-volume `[[i],[j],[k]]` ranges + eyes), `_range_*`, `_range_mode='full'`).
- `source` (property) — `_src_extract_init`; symmetric with `ExtractBlockRepresentation.source`, the ColorBy anchor.
- `_target_view()` — per-view `pv_view` else `GetActiveView()`. Every Show/Hide/GetRepresentation flows through this so the per-view variant doesn't leak into other panels.
- `rep_path` (property) — `tree.find_path(self._node_id)`.
- `set_node_id(node_id)` — **The core lifecycle method.** `None` → tear down everything. A node id resolves its `IjkGrid` ancestor: if it's a *different* grid → `_delete_all_sources()` and rebuild (create rep_data, three axis slicers + one volume crop, set Representation/Scale/tint, compute extent, init slicer state); if the *same* grid → treat as a property change (re-`update_colors` every slicer). In per-view mode rep_data is built via `_create_plugin_filter_proxy("EnergisticsExtractor")` + `ExtractPath`; in legacy mode via the collector's `ExtractRepPath`/`ExtractedRepProducerName` C++ properties.
- `show(view=None)` — **The visibility brain.** Slice/clip active → hide all sources. Else re-assert Representation+tint+Scale on every source (needed for views created later than `set_node_id`), then: slice mode shows the per-axis crops; range mode shows each visible volume's crop, a visible FULL-EXTENT volume rendering through rep_data instead (see `_is_volume_full_extent`). NO parent fallback: every eye closed (slicers or volumes) renders nothing — an all-hidden set must read as empty, not as the full grid sneaking back. When a chain is visible, each would-be-visible source is replaced by ALL of its visible-tip Threshold proxies (union branches each render) via `_show_source_or_chain`. The scene cut (`set_scene_cut`, 29/10): each display the isolate shows draws through a `SceneCrop` of its own, keyed by the proxy's global id (`_gid`; `id()` is given again to a new proxy once the old one is freed), hidden with its proxy — a source replaced by its chain hides its cut too, or the cut grid stays painted under the tip (30/10) — and pruned when the proxy is gone.
- `_is_range_full_extent()` — PV6's `ExplicitStructuredGridCrop` produces a degenerate 1-cell output at full extent, so range mode falls back to rep_data until the user actually crops.
- `_primary_range_source()`, `_active_upstreams()`, `_visible_leaf_tips()` (every visible chain tip — single for a linear/intersection chain, one per sibling for a union), `_ancestors_all_visible()`, `_show_source_or_chain()`, `_hide_chain_for()`.
- Array introspection: `color_array_type(name)`, `available_arrays()`, `array_data_range(array_name)`, `_resolve_assoc()`.
- Chain public API: `get_chain()`, `chain_entries()`, `add_threshold(parent_name, array)`, `delete_threshold(name)` (re-parents children), `set_range(name, low, high)`, `set_visible(name, visible)`, `all_visible_threshold_proxies()`, `all_render_sources()`, `all_threshold_sources()`.
- Chain plumbing: `_refresh_chain_pipeline()` (syncs the per-entry per-upstream proxy set with the active upstreams, rewires Inputs visibility-aware), `_effective_upstream_for(entry, src)`, `_inherit_display(thr_proxy, src)`, `refresh_threshold_pipeline()`.
- Colors: `update_colors(src, array_type, property_title, property_type)` (sets LUT, scalar bar, `NanOpacity` from `state.nan_color`), `_nan_opacity_from_state()`, `update_block_visibility()` (drops this grid's property path from the parent multiblock's `BlockSelectors` so it renders through the slicers, not the parent rep).
- Slicer state apply (used by snapshot/replicate): `apply_slice_positions`, `apply_slice_visibility`, `apply_volumes` (syncs crop count + per-volume ranges + eyes), `apply_mode`, `to_ui_state()`.
- DEPRECATED slice/clip legacy path: `_ensure_slice`/`slice_state`/`slice_set`/`_ensure_clip`/`clip_state`/`clip_set`/`clip_output`/`refresh_planes_after_property_change` — `_slice`/`_clip` stay None in normal use (per-(rep, view) slice/clip lives on `RepInScene`).

**State.** Reads `state.representation_active`, `state.solid_color_by_rep`, `state.nan_color`, `ui_scale_z__<view>`, `state.fespp_data_selectors`. Writes `rep.BlockSelectors` (via `update_block_visibility`). Module-level `server`/`state`/`ctrl` are captured at import.

**Collaborators.** `Collector`, `Tree`, `pvsimple`, `vtkSMPropertyHelper`, `representation._{apply_default_tint, find_registered_proxy, sanitize, create_plugin_filter_proxy}`, `chain_domain.resolve_chain_kind`, `SlicePlane`/`ClipPlane` (deprecated path). Legacy instances created by `SourceRegistry.ensure_ijk_grid`; per-view instances created by `IjkGridRep.ensure_per_view_ijk`.

**Gotchas.**
- The slicers are `ExplicitStructuredGridCrop`, NOT `Slice`/`Clip` — they crop the structured grid extent (`OutputWholeExtent = [i0,i1,j0,j1,k0,k1]`), giving an I/J/K planar/box subset of the cells.
- A range-mode volume at full extent renders rep_data (not its crop) because the crop output degenerates on PV6.
- Per-view IjkGrid peeks at the clone's output assembly to choose the output VTK type; `IjkGridRep.ensure_per_view_ijk` forces `clone.UpdatePipeline()` FIRST or every slicer rejects the placeholder `vtkPolyData` input.
- `update_block_visibility` is cumulative-safe across multiple grids: it rehydrates from `['/data']` (the engine reset marker) only on first call, otherwise pops just its own path.
- Multiple thresholds on the same array under the same parent are valid (UNION of ranges) → entry names get numeric suffixes to avoid registration collisions.

---

### `fespp_on_trame/engine/sources/xyz_crop.py`

**Responsibility.** The X / Y / Z crop of an isolated representation that has no I/J/K — a surface, a polyline or point set, an unstructured grid, a sub-representation (the Geometry slicer in coordinates). Since 30/10 it is the scene cut's two filters on the object alone (`engine/blockscope/scene_cut_filters`): `FesppScenePrep` once (each cell's extent in numpy, a polyline's segments and a point set's points made cells), `FesppSceneCut` at each step (the cells whose extent meets the box) — one code for the scene and the object. It replaced a chain of ParaView Thresholds (a `Calculator` of the coordinates, one Threshold per narrowed axis with *Use Continuous Cell Range*): VTK starts a cell's maximum at DBL_MIN, the smallest positive double, so on negative values (every elevation of ALK) the lower bound was never applied (the PO, 30/10: "the min does not work"; a column at −30..0 cut at [−5, −5] kept its three cells), and the chain was 4–5 times slower — on ALK's 75 460 cells a step 33–40 ms against 6–8 ms (scenario `xyz_bench`, the same cells kept both ways), for 24–32 ms of preparation once. Extract Cells By Region and the crinkle Clip keep a cell when one of its points is in the box: a range thinner than a cell keeps almost nothing.

**Key pieces.** `narrows(box, bounds)` (the axes a box narrows, what the scenarios read); `boxes_text(box)` (the cut's Boxes property); `CoordCrop(upstream, name)` with `set_box(box, bounds)` (written only when it changes: the cut runs again, not the preparation), `set_input(upstream)`, `tip`, `axes`, `delete(view)`. A lone dataset's output takes the class of what the stage makes of it (`scene_crop.output_class`: a horizon's cut is the polydata of its quads; `_as_class` converts) — the cut of HOD kept the whole horizon until 30/10, its quads unable to go into a structured grid.

**In the isolate (`ijkgrid.py`).** A non-IJK isolate keeps its bounds (`snapshot()["bounds"]`, `"ijk": False`) and one `CoordCrop` per volume (`_xyz_crops`, their tips are `_src_volumes`); `apply_volumes` takes boxes in the scene's coordinates and moves each cut, its tip kept whatever axes the box narrows (the threshold chain made again on a new axis left the view empty while the hand was down). A point set is cropped on its points made vertex cells (`_point_cells`). A cut "=" is a box flat on its axis: the cells the plane crosses.

---

### `fespp_on_trame/engine/blockscope/scene_crop.py`

**Responsibility.** The X / Y / Z cut of a whole 3D view — the Geometry slicer on the scene (29/10), the object slicer's rule (a cell kept when it meets a box). ONE pipeline per view whatever the number of boxes, on the shared display source, keeping its structure (its blocks, their flat indices, its assembly): `FesppScenePrep` (`prep_into`, run again when the source changes, each grid's geometry prepared once — a cache by its cells' and points' address and mtime, so a property loaded or a log ticked costs its own leaf: each cell's id `vtkOriginalCellIds` for picking, an IJK grid made unstructured, lines and points made cells of their own, each cell's extent as the field array `__fespp_cellbox` (axis-major), a 2D grid's — a horizon, `vtkStructuredGrid` — read off its point grid, and an IJK grid's FACE TABLE: which faces between I, J, K neighbours are one face, which are lone — the outside, the faults' split nodes, a hidden neighbour; a leaf with cells and no points passed untouched), `FesppSceneCut` (`cut_into`, the boxes as its `Boxes` property: the cells a box meets, `mask_of`, numpy; an IJK grid drawn as the POLYDATA OF ITS EXPOSED FACES straight from the table, on the points they use; a polydata's and a horizon's kept cells in numpy; a Threshold inside the filter for any other leaf). The two filters are Python VTK algorithms loaded once as a ParaView plugin (`scene_cut_filters.py`). Measured on drogon (930 000 cells, 270 000 hidden): an explicit structured grid's shallow copy 30–45 ms (an unstructured grid's 0.1 ms), a ProgrammableFilter run 33 ms of `gc.collect` over the app's heap, a `TrivialProducer` fed by hand forced `UpdatePipeline` in the middle of a read, a face table hashed over every face 2 s to build and 60 ms a step to read (the IJK structure gives the neighbours for nothing), ParaView's Threshold then the representation's surface filter 40–80 ms a step, the mapper's upload of the grid's million shared points 20 ms more than the faces' own — hence what is there; a step 66–86 ms in all (the cut itself 13–25 ms), against 98–179 ms with the Threshold. No `ExtractBlock` of the drawn blocks: it renumbers them, and a log ticked while the scene was cut (ADME) shifted the flat indices under the representation — the render after crashed the session (SIGSEGV, 29/10; scenario `etp_scene_cut_logs`, traced by the file named in `FESPP_SCENE_CUT_TRACE`).

**Key pieces.** `SCENE = "@scene"`; `holds_whole(box, bounds)`, `cutting_boxes(boxes, bounds)` (`[]` when a box holds the whole scene: the union then holds everything); `mark(data, boxes)`; `SceneCrop(view_id)` with `set_boxes(base, boxes, bounds, selectors)` (True when what the view draws changed: the representation must move), `tips(base, selectors)` (the cut made again when the prep output changed), `tip_ids()`, `source_flat(flat, source_index)` (the identity: the cut keeps the source's flat indices), `drop_stale()`, `release()`.

**In the scene (`pdc_scene.py`).** `set_crop(boxes, bounds, live)` reconciles only when what is drawn changes (a step moves the mark only); `ensure_main_rep` shows `main_rep` on the cut's tip, the blocks drawn being `_cut_blocks()` (shown, not isolated: the representation's block selectors, the cut itself keeps every block); the extra representations (`_sync_extras`, `_copy_to_extras`) stay for a cut of several tips, unused since one mark serves every box; `crop_tip_ids()` for picking; `release()` drops the reps and the cut. **The convert stage** (`domain_convert.py`, 30/10): `FesppDomainConvert` (`Flats`, `Cube` — the key of the velocity model in `domain_convert.CUBES`, the stage running in the server's own process —, `To`) between the shared source and the cut when the view draws an object of the other vertical domain converted with the time-depth law — the named leaves get new points, z converted by the cube (`engine/velocity_model.Cube.convert`: integration down the cell's vertical) with the data's sign kept, the structure untouched; `DomainConvert.tip(base, flats, cube_key, to)` / `park()` / `drop_stale()`; `PdcScene.converted`, `convert_cube`, `flats_of` (set by `view_domain.attach`), `_converted_base` in `ensure_main_rep`, `_drop_stale_stages` at the next call (a stage still drawn is never deleted).

---

### `fespp_on_trame/engine/sources/extract_block.py`

**Responsibility.** The per-rep DATA source for NON-IjkGrid representations (UnstructuredGrid, Trajectory, Grid2d, PointSet, Polyline(Set), TriangulatedSet, …): one `EnergisticsExtractor` proxy chained on the collector source, whose `ExtractPath` selects the rep's block, read for array introspection and the values the statistics read. It is never shown: each view's composite is the one visible representation (engine/blockscope). Its threshold chain and display helpers went with the per-representation model (Q2 bis); a view's thresholds live in its grid isolate (`_IjkChainEntry`).

**Key classes / functions.**

`class ExtractBlockRepresentation` — `__init__(collector, tree, rep_path)` (the caller discards the instance if `source is None`), `rep_path`, `source`, `_create_source()`, `delete()`, `available_arrays()`. Held by `SourceRegistry`.

**The chain's domain (`chain_domain.py`).** `resolve_chain_kind(tree, rep_path, array_name, source_proxy, assoc, reader=None)` → `(kind, unique_values, labels)`. Derives `kind` from the tree's `propKind`; scans the VTK array for distinct values (capped at `_MAX_DISCRETE_UNIQUES = 64`, demote to Continuous beyond); for Categorical the labels come from `engine/utils/categories.labels_for` (the LUT `Annotations`, else the fesapi StringTableLookup through `reader`). Helpers: `_kind_from_tree` (matches a property node by sanitized title, strips the MR `_real_<idx>` suffix; walks the rep subtree first, then falls back to the enclosing `GridContainer` — see Gotchas), `_kind_in_subtree` (the shared walk, returns None when absent), `_normalise_kind`, `_scan_unique_values` (reads the inner dataset through `assembly_index.inner`).

`chain_domain(kind, unique_values, labels, fallback_range)` → `(range, unique_values, labels)`. Applied right after `resolve_chain_kind` when a threshold is added. RESQML integer properties cannot carry NaN, so writers declare `<NullValue>` = INT32_MAX (or int64/MIN variants — `INT_NULL_SENTINELS`, tested via `is_null_sentinel`) for inactive cells, and FESPP delivers them verbatim: `GetRange()` on such an array spans billions and the categorical threshold slider collapsed every real category into the first pixels of the track (measured on Petrel OLYMPUS FIPBLOCK: range (1, 2147483647) for categories 1–5). For Discrete/Categorical the sentinels are dropped from the uniques and the label map, and a Categorical entry's domain additionally spans ALL annotated keys (every lookup category gets a tick, present in the data or not); a degenerate single-value domain is widened by 1 for `VRangeSlider`. Continuous passes through untouched. Side effect: the initial threshold bounds exclude the sentinel, so adding a categorical threshold immediately filters out inactive cells.

**Collaborators.** `representation.arrays_from_source`, `pvsimple`, `vtkSMPropertyHelper`. Created/managed by `SourceRegistry`.

**Gotchas.**
- **A grid's properties are SIBLINGS of its geometry rep, not descendants** — both sit under the `GridContainer`'s `PropertiesFolder`, and the geometry rep (title `SolidColor`) has **zero children**. Any "walk the rep's subtree to find its property" code silently finds nothing. `_kind_from_tree` did exactly that and fell back to `"Continuous"`, so EVERY grid Discrete/Categorical property rendered a continuous threshold slider (and `resolve_chain_kind` short-circuited before scanning `unique_values`, leaving them empty). It now retries from the enclosing `GridContainer` when the rep's own subtree misses; non-grid reps have no `GridContainer` ancestor so they are untouched. Note the widened search also lets a `BlockedWellbore` rep (0 property children, same container) resolve the grid's same-titled property — arguably correct, since BW arrays *are* the supporting grid's properties. **This subtree assumption was invalidated by the C++ assembly restructure, not by any Python commit** — `extract_block.py` was byte-identical to v1.1.0 while broken. The same trap lives in `threshold_dispatch._find_property_path_by_title` and `Tree.has_property_descendant` (used by `activator` for `active_representation_has_properties`, now always False for grids): audit every caller before trusting a subtree walk here.
- **A wellbore is laid out like a grid** (FESPP, 2026-09-18): `searchWellboreFrame` puts the log frames under `_logsfolder_<feature uuid>` (`WellboreLogsFolder`, title `logs`), the marker frames under `_markersfolder_` (`markers`), `searchWellboreCompletion` the completions under `_completionsfolder_` (`completions`); the trajectory stays a direct child. All three are grouping types (`isGroupingType`) and `MapperType::Folder`; the app lists them in `node_kinds.GROUPING_KINDS` and `element_type.Grouping`. Walks that go UP to the Wellbore (`find_parent_node_id_with_type`) and DOWN through descendants are unchanged; only a direct-child assumption on a frame would break — none was found (`selection_deps` reads the trajectory, still direct). Fixed in passing: a second trajectory of the same well, and the frames of a companion EPC, now hang under the well node (they went beside it / at the root). Headless: `well_layout_probe` in `well_layout.json`.
- **A grid met first as a PARTIAL reference gets the same layout** (FESPP, 2026-09-18). When the EPC of a grid's properties is read before the grid's own EPC (the Olympus split: OnlyProp, Well, GridAndProp), the grid is a partial stub on the first traversal. The plugin used to add a flat `Partial` node there and, when the real grid came, retype it in place — no `GridContainer`, no `PropertiesFolder`, no `SolidColor` leaf: the tree showed the grid with its property set straight under it and no geometry row. `searchRepresentations` now builds the container + properties folder for a partial IjkGrid / UnstructuredGrid and puts the stub INSIDE the folder (typed `Partial`, `supporttype` set, greyed in the tree); the properties and completions read meanwhile hang where they belong, and the real grid only retypes the leaf (title `SolidColor`) and refreshes the container's metadata. Headless: `grid_layout_probe` in `olympus_partial_first.json` / `olympus_grid_first.json` (the PO's Olympus files, `data/private/olympus/`).
- Despite the class name "ExtractBlock", the proxy it builds is an `EnergisticsExtractor` (the C++ ExtractBlock path was abandoned — see `_create_source` docstring).

---

### `fespp_on_trame/engine/sources/source_registry.py`

**Responsibility.** The legacy unified per-`rep_path` registry: one entry per loaded rep regardless of type, holding two internal dicts (`_extract_blocks`, `_ijk_grids`) keyed differently (rep path vs property node id lifecycle) but presenting a single compat surface to the engine. Drives data-load sync (selector → rep mapping), and remains the authority for IjkGrid property selection (`ensure_ijk_grid`) which fans out to per-view IjkGrids.

**Key classes / functions.**

`class SourceRegistry`
- `__init__(collector, tree)` — the two dicts plus `_selector_cache`.
- Selector resolution: `_rep_path_for(selector_path)` (cached selector→rep mapping; returns IjkGrid selectors too), `_rep_type_for(rep_path)`.
- Instance accessors: `get_extract_block`, `get_ijk_grid`, `get_instance` (either), `is_ijk_grid`.
- Compat surface: `get(rep_path)` (canonical upstream source — EB source or IjkGrid rep_data), `all_sources()`, `items()`.
- Array introspection: `available_arrays`, `array_data_range`.
- Chain compat (DEPRECATED, `_warn_deprecated`): `get_chain`, `add_threshold`, `delete_threshold`, `set_range`, `set_visible`; read-side `all_visible_thresholds` (EB only), `all_chain_proxies`, `get_threshold` (deepest visible, EB only), `all_thresholds()`.
- Slice/clip compat (DEPRECATED, no remaining callers): `slice_state`/`slice_set`/`clip_state`/`clip_set`.
- Cross-rep display: `apply_z_scale(zscale)` (EB only — IjkGrid z-scale is engine-driven), `apply_representation(representation_type)` (EB only — same reason).
- Lifecycle: `get_or_create_extract_block(rep_path)`, `ensure_ijk_grid(rep_path, prop_node_id)` (creates/retargets the legacy IjkGrid AND fans the property change to every per-view IjkGrid via `scene_registry.refresh_per_view_ijk_for_rep`), `release(rep_path)`, `release_all()`.
- `sync(selectors, reservoir_select_node_ids)` — reconciles both dicts with the current selection. ExtractBlock side from `state.fespp_data_selectors`; IjkGrid side from `state.ui_select_node_reservoir` (per-tab checked nodes), with a fallback that derives IjkGrid targets directly from `selectors` when the reservoir state var hasn't flushed yet (the reselect-after-deselect-all race).
- Path/instance enumerators: `ijk_paths`, `extract_block_paths`, `all_paths`, `ijk_grids`, `extract_blocks`.

**State.** Reads `state.fespp_data_selectors` and `state.ui_select_node_reservoir` (passed into `sync`); reaches `server.context.scene_registry` in `ensure_ijk_grid`.

**Collaborators.** `ExtractBlockRepresentation`, `IjkGrid`, `Tree`, `Collector`, and (best-effort) `SceneRegistry`. Stored on `server.context.source_registry`; called by the engine's data-load / dispatch layers and used as the per-view pipeline's legacy fallback.

**Gotchas.**
- Asymmetric lifecycle: an `IjkGrid` lives by *property node id* (`set_node_id`), an `ExtractBlockRepresentation` by *rep path*. This is why there are two dicts and why `ensure_ijk_grid` takes a `prop_node_id` while `get_or_create_extract_block` takes only a path.
- Most of the surface is deprecated and exists as a fallback; `get`, `get_ijk_grid`, `get_extract_block`, `apply_z_scale`, `apply_representation`, `sync`, `release` remain in active use (per the header).
- `sync`'s reservoir-vs-selectors fallback is load-bearing: without it, an IjkGrid reselected after deselect-all sees empty input and silently no-ops (rep stays unbuilt).

---

---

---

### `fespp_on_trame/engine/sources/merged_source.py` and `ActiveSource`

**Responsibility.** A session reads files (the `EPCCollector`) and a store (the `ETP12Store`) TOGETHER, each reader with its own repository: a working file may hold the very objects of the dataspace it is compared with. What displays, picks, lists or extracts still wants ONE collection and ONE assembly: `merged_source` is the ProgrammableFilter `fespp_sources` that joins the readers holding data, and `source_registry.ActiveSource` is the session's source in front of it (`server.context.active_data_source`).

**Key classes / functions.**

- `merged_source.apply(algorithm)` — the filter's body. One input: a `ShallowCopy` pass-through (the session reads as it did with that reader alone). Several: the partitioned datasets one after the other, the assemblies' top rows under one root, the dataset indices of every reader after the first moved on by the datasets standing before it, every node numbered again (`merged_source.joined`, written on the trees' XML: `vtkDataAssembly.AddSubtree` moves the dataset indices by a count of its own — the largest index the assembly already names plus one, at each call — and returns no node id).
- `MergedSource.proxy(readers)` / `set_inputs(readers)` — the filter, made at first use; its inputs follow the readers.
- `MergedSource.keep_readers_time(*others)` — a filter registered over a source makes ParaView's time keeper suppress that source and listen to the filter, whose steps are only known once it has run: the readers are un-suppressed, this filter and the ones chained on it are suppressed.
- `ActiveSource.readers()` — the readers that HOLD data (their assembly has rows), the file reader first. A store counts from its first dataspace on and past its disconnection: the plugin's `disconnect` closes the session and keeps the repository.
- `ActiveSource.sync()` — joins the readers that hold data now and tells `repo_query.stands_for(proxy, readers)`; called from `etp.update_data_information` (a file read, a dataspace loaded).
- `ActiveSource.get_source()` — the collection as read (the merge); `get_display_source()` — the derived-arrays filter over it.
- `ActiveSource.reader_of(path)` — the reader whose assembly holds the row: what an extractor of one object anchors on (`IjkGrid`, `ExtractBlockRepresentation`).
- `ActiveSource.push_selectors(selectors)` — what to read, said to each reader in the paths its own assembly holds.
- `ActiveSource.store_paths(paths)` — those of the rows the store holds: what tells a download from a read at hand (`tick_question`, `stepped_read`). Never ask "is the store connected" to decide how a row is read.
- A closed store reads nothing more: `ctx.store_closed()` (`app/features/osdu_etp`) says why — the reader disconnected, the token ended, the session was lost — and `tick_question._apply_selection` refuses, with that sentence, a selection that adds a row of the store; an untick and the files' rows go through. Without it the reader waits on a session that is gone.

**Collaborators.** `engine/repo_query` routes a question asked of the merged source to the reader that holds the object (`_readers`, `_owners`, `store_uuids`); `engine/derived_arrays`; `engine/etp.update_data_information`.

**Gotchas.**
- A node's name is its object's uuid: two readers hold the same path only when they hold the very same object (two exports of one model carry different uuids, hence two rows of one title, each read from its own reader). The very same object in both is not folded into one row: the joined tree then has two rows of that path, a selector reaches both and both readers read it.
- A reader-level question (selectors, the query channel, the lazy fetch) never goes to the merged proxy itself.

---

### `fespp_on_trame/engine/sources/collector.py`

**Responsibility.** Thin wrapper around the FESPP `EPCCollector` ParaView source — the single root that parses an EPC/RESQML file into the multiblock assembly every downstream filter chains on.

**Key classes / functions.**

`class Collector`
- `__init__()` — creates `pvsimple.EPCCollector(registrationName="EPCCollector")`, shows it.
- `representationType` / `scale_z` properties (set-if-changed).
- `get_source()` — the `EPCCollector` proxy.
- `get_representation()` — its display in the active view.
- `add_file(epc_file_path) -> bool` — pushes the path into the `Files` property, `UpdatePipelineInformation`, `controller.update_data_information()`, prints `[DIAG load]` diagnostics. On exception, sets `state.load_error` and `state.flush()`, returns False.
- `show()`.

**State.** Writes `state.load_error` on load failure.

**Collaborators.** `pvsimple`, `server.controller`. Instantiated at engine boot; its source is the input to every `ViewScene._clone` and to legacy `ExtractBlockRepresentation`/`IjkGrid`.

**Gotchas.**
- `add_file`'s try/except is the Python net for FESAPI errors the C++ now *surfaces* (after its own guards) instead of dying — it CANNOT catch a hard C++ SIGABRT/SIGSEGV (the process would already be gone); the C++ `vtkEPCCollector::GetAllFiles` guards are what prevent that.
- `EPC_COLLECTOR_GUI_NAME = "EPCCollector"` is the fixed registration name — `IjkGrid`/`ExtractBlockRepresentation` reach the collector through this wrapper, never by name.

---

### `fespp_on_trame/engine/sources/etp_connector.py`

**Responsibility.** Wrapper around the FESPP `ETP12Store` ParaView reader for OSDU RDDMS (RESQML over ETP 1.2). Handles authentication, optional proxy, dataspace selection — an alternative data root to `Collector` exposing the same `get_source()` contract so the rest of the engine drives it identically.

**Key classes / functions.**

`class ETPConnector`
- `__init__()` — creates `pvsimple.ETP12Store(registrationName="ETP12Store")`, shows it; `_is_connected=False`.
- `representationType` / `is_connected` properties; `get_source()`, `get_representation()`.
- `connect(etp_url, data_partition, token, token_type="Bearer", proxy_url=None, proxy_token=None, proxy_token_type="Bearer") -> bool` — sets `ETPUrl`/`OSDUDataPartition`/`ETPTokenType`(0 Bearer / 1 Basic)/`ETPToken`, optional proxy props, calls `Connect()`, then polls `ConnectionTag` (1=not connected, 0=connected) for up to 30 s (0.5 s sleep) because the C++ connect is async.
- `disconnect()` — invokes the C++ `disconnectionClicked` command.
- `set_dataspace(dataspace)` — sets `Dataspaces` (and calls the client-side `SetDataspaces` if present), then polls the data assembly until it gains a child or 10 s elapse (the C++ `SetDataspaces` runs in a detached thread); finally `controller.update_data_information()`.
- `get_dataspaces()` — reads the `AllDataspaceNames` property into a list (1 s settle sleep first).
- `show()`.

**State.** None.

**Collaborators.** `pvsimple`, `server.controller`. Parallel to `Collector` as a data root.

**Gotchas.**
- Both `connect`, `set_dataspace`, and `get_dataspaces` use blocking `time.sleep` polling loops (the C++ ETP operations are async/threaded). These run on the server thread — they will block the Trame server for up to 30 s on connect / 10 s on dataspace selection.
- `ETPTokenType` / `ProxyTokenType` are integers (0/1), not strings — the string `token_type` arg is mapped before the `Set`.

---

---

---

---

### `fespp_on_trame/engine/sources/__init__.py`

Empty package marker (skipped per the documentation rules).
