# Core — Sources (ParaView pipeline)

This subsystem (`fespp_on_trame/app/core/sources/`) is the architectural heart of the app: it owns every ParaView ServerManager (SM) proxy that turns a loaded RESQML/EPC dataset into visible geometry, and it does so through **two coexisting generations of pipeline** that you must understand before touching anything.

**The legacy generation** is keyed by `rep_path` only — one source per representation, shared across all render views. It lives in `SourceRegistry` (the dict-of-instances manager), `ExtractBlockRepresentation` (non-IjkGrid reps), and `IjkGrid` (the modal I/J/K-slicer pipeline). **The per-view generation** is keyed by `(rep_path, view_id)` — one source *per render panel* — and lives in `SceneRegistry` → `ViewScene` → `RepInScene`. The migration from legacy to per-view happens in numbered "Phases" referenced all over the docstrings (1.b, 2, 3a, 3b, 3c, 4, 5); at the current state of the branch, non-IjkGrid reps are fully per-view (Phase 3a), IjkGrid reps run a per-view pipeline that *mirrors* a still-authoritative legacy `IjkGrid` (Phase 3b), and the legacy `ExtractBlockRepresentation` / `SourceRegistry` slice/clip/threshold methods are deprecated fallbacks (Phase 4) that only fire when the `vtkEPCCollectorClone` plugin proxy is unavailable.

The data flow is: a C++ `EPCCollector` source (wrapped by `Collector`) reads the EPC/RESQML file into a single multiblock assembly. Each `ViewScene` chains a `vtkEPCCollectorClone` (a zero-copy ShallowCopy passthrough) on the collector as its per-view structural anchor. `RepInScene` then chains a per-(rep, view) `EnergisticsExtractor` (set `ExtractPath = rep_path`) on that clone, and slice/clip/threshold filters chain on the extractor. The per-kind *behaviour* (which extractor to build, what to show/hide, how children render) has been factored OUT of `RepInScene` into the `fespp_on_trame.app.core.element_type` hierarchy (`Representation`, `IjkGridRep`, `ChannelFrameRep`, `MarkerFrameRep`, …) via a strategy pattern: `RepInScene` keeps the per-(rep, view) *state*, the `ElementType` subclass supplies the *policy*, receiving `RepInScene` as `ris`.

> Note on read scope: this page documents the files under `core/sources/`. To describe `rep_in_scene.py` accurately I also read its delegation target `core/element_type/{representation,frames}.py`; those are documented in their own pages but referenced here where the real logic lives.

> **⚠️ Refactor update (`refactoring` branch).** A behaviour-preserving dedup pass moved several formerly-duplicated helpers into shared modules. Where the per-file notes below say a helper is "duplicated 3×" / "mirrors the same helper", that is the *pre-refactor* description — it now reads:
> - `representation.inherit_display(upstream, target, view)` — threshold-output display inheritance (was 3 copies).
> - `representation.arrays_from_source` / `array_range_from_source` / `resolve_assoc` — array introspection (was 3 copies).
> - **`threshold_chain.py`** (new, dependency-free) — the single-upstream threshold-chain graph walk + `refresh_chain_visibility` rewiring, shared by `RepInScene` and `ExtractBlockRepresentation` (each passes its own root/view/rep-hidden policy). `IjkGrid`'s MULTI-upstream chain is separate.

---

### `fespp_on_trame/app/core/sources/rep_in_scene.py`

**Responsibility.** The per-`(rep, view)` wrapper — the central object of the per-view pipeline. Holds *all* per-(rep, view) ParaView state (extractor, per-child extractors, per-view IjkGrid, threshold chain, slice/clip planes) and exposes the full UI-facing surface for one representation as seen from one render panel. It is, deliberately, a god object: it owns source resolution, lifecycle, slice, clip, the threshold chain (with a non-IjkGrid local implementation AND an IjkGrid forwarding implementation), wellbore-frame child management, per-view visibility, and snapshot/apply replication.

**Key classes / functions.**

`class RepInScene`

- `__init__(self, scene, rep_path: str)` — stores the owning `ViewScene` (`self.scene`) and the assembly path (`self.rep_path`). Initializes every state slot to `None`/empty: `_extractor` (per-view `EnergisticsExtractor`, lazy), `_channel_extractors: dict` (one extractor per wellbore log channel, keyed by channel path, EXCLUSIVE display), `_marker_extractors: dict` (one per marker, MULTI display), `_per_view_ijk` (per-view `IjkGrid`, lazy, IJK reps only), `_chain: list` (per-view threshold `ChainEntry` list, non-IJK only), `_slice_plane` / `_clip_plane` (lazy), `_element_type_cache`.

- `element_type` (property) — lazily resolves and caches `element_type.for_path(self.scene.tree, self.rep_path)` → an `ElementType` instance. **Single source of truth** for per-kind behaviour; every per-kind predicate and most public methods delegate to it.

- `_is_ijk_grid()` / `_is_wellbore_frame()` / `_is_marker_frame()` — `isinstance` checks against `IjkGridRep` / `ChannelFrameRep` / `MarkerFrameRep`. These gate the legacy-vs-per-view and per-vs-multi branches throughout the class.

- `source()` — head proxy used by ColorBy and the display layer. **Delegated** to `element_type.ensure_source(self)`: IjkGrid → per-view IjkGrid's `rep_data` extractor; standard rep → per-view `EnergisticsExtractor`; with the legacy shared source as Phase-2 fallback.

- `_ensure_per_view_ijk()` — delegates to `IjkGridRep.ensure_per_view_ijk(self)`; builds + caches `self._per_view_ijk`. Kept as a method because slice/clip/threshold + `refresh_per_view_ijk_property` all call it.

- `_hide_legacy_ijk_in_scene_view(legacy_ijk)` — Hides every visible source of the legacy shared `IjkGrid` (rep_data, slicers, volume crop, thresholds) in THIS scene's `pv_view`, so the per-view pipeline doesn't Z-fight the legacy one.

- `refresh_per_view_ijk_property(prop_node_id)` — Re-targets the per-view IjkGrid at a new property (calls `_per_view_ijk.set_node_id`), then re-hides the legacy IjkGrid and re-hides this rep if the engine flagged it hidden in this view's bucket. No-op when the per-view IjkGrid isn't built. Called by `SceneRegistry.refresh_per_view_ijk_for_rep`.

- `_ensure_extractor()` — delegates to `Representation.ensure_extractor(self)` (builds + caches `self._extractor`); `IjkGridRep` returns `None`.

- Wellbore-frame child API (all delegate to the `ElementType`, state lives here): `set_channel_visible(channel_path, visible)` → `set_child_visible` (EXCLUSIVE); `channel_extractor_for(channel_path, create=False)` → `child_source`; `visible_channel_extractor()` → `visible_child_source`; `set_marker_visible(marker_path, visible)` → `set_child_visible` (MULTI); `set_marker_color(marker_path, color_hex)` → `set_child_color`; `visible_marker_displays()` → `visible_child_displays`.

- `_channelless_frame()` — `element_type.primary_hidden()`; True for any FrameRep (Channel + Marker). The frame's PRIMARY extractor must stay hidden because children render via dedicated per-child extractors.

- `_hidden_in_scene()` — True iff `self.rep_path` is in `state.ui_hidden_rep_paths_by_view[self.scene.view_id]`. Gates the eager per-view Show so a first selection appears only in the active panel while the pipeline is still BUILT everywhere.

- `hide_in_scene_view()` — delegates to `element_type.hide_in_view(self)`. IJK reps hide slicers/volume/rep_data/thresholds; other reps hide the primary extractor.

- `_fallback_legacy_source()` — fetches `server.context.source_registry.get(rep_path)` (the legacy source). Used by IjkGrid reps and as the non-IJK Phase-2 fallback.

- `_current_z_scale()` — reads `state.ui_scale_z` (default 1.0).

- `delete()` — Tears down in dependency order: `_delete_chain()` (children-first) → slice plane → clip plane → `_per_view_ijk` (via `set_node_id(None)`) → `_extractor` (Hide+Delete) → every per-child extractor in `_marker_extractors` then `_channel_extractors`.

- Slice: `_ensure_slice()` (lazily builds a per-(rep, view) `SlicePlane` chained on `source()`, threading `view_id`/`view_pv`), `slice_state()`, `slice_set(enabled, axis, offset)` (on enable-flip, re-runs `_refresh_parent_rep_visibility` + `_refresh_chain_visibility`), `slice_output()`.

- Clip: `_ensure_clip()`, `clip_state()`, `clip_set(enabled, axis, offset, inside_out)`, `clip_output()` — mirror the slice methods with `ClipPlane`.

- `refresh_planes_after_property_change()` — re-applies enabled slice/clip (a fresh ColorBy doesn't auto-track) and re-asserts parent + chain visibility.

- `_refresh_parent_rep_visibility()` — re-asserts the PRIMARY source's visibility in this view. Shared guards (view present, per-view eye chip in `ui_hidden_rep_paths_by_view`) live here; the per-type policy is **delegated** to `element_type.refresh_primary_visibility(self)`.

- Threshold chain — public, dual-dispatch on `_is_ijk_grid()`:
  - `_ijk_provider()` — per-view IjkGrid when available, else `_legacy_instance()`; `None` for non-IJK.
  - `get_chain()`, `add_threshold(parent_name, array)`, `delete_threshold(name)`, `set_range(name, low, high)`, `set_visible(name, visible)`, `available_arrays()`, `array_data_range(array_name)` — IJK reps forward to the IjkGrid provider; non-IJK reps use the local `_chain` implementation.
  - `all_visible_thresholds()` / `all_chain_proxies()` / `deepest_visible_threshold()` — chain proxies (empty for IJK).

- Threshold chain — local (non-IjkGrid) implementation:
  - `_add_threshold_local(parent_name, array)` — Builds a `pvsimple.Threshold` chained on `_effective_input_for_parent(parent_name)`, registration name suffixed `_v{view_token}` so views don't collide on the PV registry. Resolves property kind via `resolve_chain_kind` (from `extract_block`), appends a `ChainEntry`, inherits display props from upstream, then `_refresh_chain_visibility`.
  - `_delete_threshold_local(name)` — re-parents children onto the deleted entry's parent, Hides+Deletes the proxy.
  - `_delete_chain()` — children-first teardown of every chain proxy.
  - `_resolve_assoc`, `_entry_by_name`, `_effective_input_for_parent(parent_name)` (walks up skipping hidden ancestors; `parent_name=None` → extractor/legacy fallback), `_has_visible_descendant`.
  - `_refresh_chain_visibility()` — recomputes Input wiring + Visibility for every entry. An entry is shown iff `entry.visible AND no visible descendant`; the primary is hidden when a chain tip shows OR slice/clip enabled OR the eye chip hides it OR `_channelless_frame()`. Targets `self.scene.pv_view`. No-op for IjkGrid.
  - `_inherit_display(thr_proxy, upstream)` — copies Representation/Scale/ColorArrayName/LookupTable/DiffuseColor/AmbientColor/Opacity from upstream's display onto the threshold's.

- Phase 3c snapshot/apply primitives (used by `SceneRegistry.replicate_view` for view-split inheritance): `snapshot_threshold_chain()` / `apply_threshold_chain(snap)` (maps source-view entry names → dest-view names so parent refs resolve; IjkGrid path reads/writes ONLY the per-view instance), `snapshot_slice()` / `apply_slice(snap)`, `snapshot_clip()` / `apply_clip(snap)`, `snapshot_ijk_slicers()` / `apply_ijk_slicers(snap)` (reuses `IjkGrid.to_ui_state()`; apply order: positions → visibility → range → mode → volume visibility → `show()`).

- `_legacy_instance()` — fetches the legacy per-rep wrapper (`IjkGrid` via `get_ijk_grid`, else `ExtractBlockRepresentation` via `get_extract_block`) from `source_registry`.

Module-level helpers (duplicated from `ExtractBlockRepresentation` to avoid importing the deprecated module): `_arrays_from_source(src)` → `[(assoc, name), …]` from CellData/PointData; `_array_range_from_source(src, array_name)` → `(min, max)`.

**State.** Reads `state.ui_scale_z`, `state.ui_hidden_rep_paths_by_view`. (Most other state — `solid_color_by_rep`, `representation_active`, etc. — is touched in the delegated `element_type` methods, not directly here.)

**Collaborators.** Imports `element_type` (`for_path`, `IjkGridRep`, `ChannelFrameRep`, `MarkerFrameRep`). Builds `SlicePlane` / `ClipPlane`, `pvsimple.Threshold`. Uses `extract_block.ChainEntry` / `resolve_chain_kind` and `representation._sanitize`. Reaches `server.context.source_registry` for legacy fallback. Created by `ViewScene.add_rep`. Driven by the engine dispatchers (slice/clip/threshold/marker) via `SceneRegistry.get_rep` / `ensure_rep`, and by `SceneRegistry._eager_setup_rep_in_scene`.

**Gotchas.**
- This is the documented god object. When adding rep behaviour, the codebase convention is to put per-kind logic in the `element_type` hierarchy, not here — `RepInScene` should only hold state and thin delegating wrappers.
- Legacy-vs-per-view duality: non-IjkGrid reps run a fully local per-view chain (`_chain`); IjkGrid reps forward threshold/range/visible ops to `_ijk_provider()` (per-view IjkGrid preferred, legacy fallback) and keep `_chain` empty. Mixing them up will silently no-op (`get_chain` returns `[]` for IJK).
- Chain proxy registration names are suffixed `_v{view_id}` to avoid PV proxy-registry collisions between views. Snapshot/apply therefore does NOT preserve entry-name equality across views — only parent/child structure.
- `refresh_per_view_ijk_property` must re-hide the legacy IjkGrid on EVERY property swap (not just first creation): the engine's parallel `set_node_id` on the legacy grid fires `show()` which resets every legacy slicer's `Visibility=1` in the active view, causing a visible Z-fight otherwise.
- Frames never render their primary extractor (`_channelless_frame()`); the generic visibility refreshers would otherwise `Show` it and the C++ side would surface the frame's first child partition.

---

### `fespp_on_trame/app/core/sources/ijkgrid.py`

**Responsibility.** The modal I/J/K slicer + volume-crop + threshold pipeline for ONE IJK reservoir grid. Used in two modes from a single class: **legacy shared-instance** (no view args; `Show/Hide` track the active view) and **per-view** (Phase 3b: pass `view_id`/`clone`/`pv_view`; rep_data is an `EnergisticsExtractor` on the clone and all rendering targets the captured `pv_view`).

**Key classes / functions.**

`class _IjkChainEntry` — one threshold-chain node. UNLIKE `ExtractBlockRepresentation`'s `ChainEntry` (single proxy), it holds `pv_proxies: dict` keyed by `id(upstream_source)` → a Threshold proxy, because an IJK threshold must attach to EVERY active upstream (rep_data + each slicer in slice mode; rep_data + slicervolume in range mode). Carries `kind`/`unique_values`/`labels` for the threshold-panel slider variant; `to_dict()`.

`class IjkGrid`
- `__init__(collector, tree, *, view_id=None, clone=None, pv_view=None)` — `view_id`/`clone`/`pv_view` are all-or-none. When set → per-view mode. State includes `_node_id`, `_property_path`, `_current_extent`, `_rep_token` (PV name suffix, includes `view_id` in per-view mode), `_src_extract_init` (rep_data), `_src_slicers_{i,j,k}` lists, `_src_slicer_volume`, `_chain`, `_slice`/`_clip` (DEPRECATED, normally None), and per-instance slicer UI state (`_slices_*_list`, `_slices_*_visible_list`, `_slices_range_*`, `_range_*`, `_range_mode='slice'`, `_volume_visible=True`).
- `source` (property) — `_src_extract_init`; symmetric with `ExtractBlockRepresentation.source`, the ColorBy anchor.
- `_target_view()` — per-view `pv_view` else `GetActiveView()`. Every Show/Hide/GetRepresentation flows through this so the per-view variant doesn't leak into other panels.
- `rep_path` (property) — `tree.find_path(self._node_id)`.
- `set_node_id(node_id)` — **The core lifecycle method.** `None` → tear down everything. A node id resolves its `IjkGrid` ancestor: if it's a *different* grid → `_delete_all_sources()` and rebuild (create rep_data, three axis slicers + one volume crop, set Representation/Scale/tint, compute extent, init slicer state); if the *same* grid → treat as a property change (re-`update_colors` every slicer). In per-view mode rep_data is built via `_create_plugin_filter_proxy("EnergisticsExtractor")` + `ExtractPath`; in legacy mode via the collector's `ExtractRepPath`/`ExtractedRepProducerName` C++ properties.
- `show(view=None)` — **The visibility brain.** Slice/clip active → hide all sources. Else re-assert Representation+tint+Scale on every source (needed for views created later than `set_node_id`), then: slice mode shows the per-axis crops (rep_data as fallback when no slicer visible); range mode shows `slicervolume` on a subset or rep_data at full extent (see `_is_range_full_extent`). When a chain is visible, each would-be-visible source is replaced by ALL of its visible-tip Threshold proxies (union branches each render) via `_show_source_or_chain`.
- `_is_range_full_extent()` — PV6's `ExplicitStructuredGridCrop` produces a degenerate 1-cell output at full extent, so range mode falls back to rep_data until the user actually crops.
- `_primary_range_source()`, `_active_upstreams()`, `_visible_leaf_tips()` (every visible chain tip — single for a linear/intersection chain, one per sibling for a union), `_ancestors_all_visible()`, `_show_source_or_chain()`, `_hide_chain_for()`.
- Array introspection: `color_array_type(name)`, `available_arrays()`, `array_data_range(array_name)`, `_resolve_assoc()`.
- Chain public API: `get_chain()`, `chain_entries()`, `add_threshold(parent_name, array)`, `delete_threshold(name)` (re-parents children), `set_range(name, low, high)`, `set_visible(name, visible)`, `all_visible_threshold_proxies()`, `all_render_sources()`, `all_threshold_sources()`.
- Chain plumbing: `_refresh_chain_pipeline()` (syncs the per-entry per-upstream proxy set with the active upstreams, rewires Inputs visibility-aware), `_effective_upstream_for(entry, src)`, `_inherit_display(thr_proxy, src)`, `refresh_threshold_pipeline()`.
- Colors: `update_colors(src, array_type, property_title, property_type)` (sets LUT, scalar bar, `NanOpacity` from `state.nan_color`), `_nan_opacity_from_state()`, `update_block_visibility()` (drops this grid's property path from the parent multiblock's `BlockSelectors` so it renders through the slicers, not the parent rep).
- Slicer state apply (used by snapshot/replicate): `apply_slice_positions`, `apply_slice_visibility`, `apply_range`, `apply_mode`, `apply_volume_visible`, `to_ui_state()`.
- DEPRECATED slice/clip legacy path: `_ensure_slice`/`slice_state`/`slice_set`/`_ensure_clip`/`clip_state`/`clip_set`/`clip_output`/`refresh_planes_after_property_change` — `_slice`/`_clip` stay None in normal use (per-(rep, view) slice/clip lives on `RepInScene`).

**State.** Reads `state.representation_active`, `state.solid_color_by_rep`, `state.nan_color`, `state.ui_scale_z`, `state.fespp_data_selectors`. Writes `rep.BlockSelectors` (via `update_block_visibility`). Module-level `server`/`state`/`ctrl` are captured at import.

**Collaborators.** `Collector`, `Tree`, `pvsimple`, `vtkSMPropertyHelper`, `representation._{apply_default_tint, find_registered_proxy, sanitize, create_plugin_filter_proxy}`, `extract_block.resolve_chain_kind`, `SlicePlane`/`ClipPlane` (deprecated path). Legacy instances created by `SourceRegistry.ensure_ijk_grid`; per-view instances created by `IjkGridRep.ensure_per_view_ijk`.

**Gotchas.**
- The slicers are `ExplicitStructuredGridCrop`, NOT `Slice`/`Clip` — they crop the structured grid extent (`OutputWholeExtent = [i0,i1,j0,j1,k0,k1]`), giving an I/J/K planar/box subset of the cells.
- Range mode at full extent renders rep_data (not slicervolume) because the crop output degenerates on PV6.
- Per-view IjkGrid peeks at the clone's output assembly to choose the output VTK type; `IjkGridRep.ensure_per_view_ijk` forces `clone.UpdatePipeline()` FIRST or every slicer rejects the placeholder `vtkPolyData` input.
- `update_block_visibility` is cumulative-safe across multiple grids: it rehydrates from `['/data']` (the engine reset marker) only on first call, otherwise pops just its own path.
- Multiple thresholds on the same array under the same parent are valid (UNION of ranges) → entry names get numeric suffixes to avoid registration collisions.

---

### `fespp_on_trame/app/core/sources/extract_block.py`

**Responsibility.** The legacy per-rep data source for NON-IjkGrid representations (UnstructuredGrid, Trajectory, Grid2d, PointSet, Polyline(Set), TriangulatedSet, …). Owns one `EnergisticsExtractor` proxy plus a threshold chain. Also hosts the still-live `ChainEntry` dataclass and the `resolve_chain_kind` property-kind helpers that BOTH the per-view `RepInScene._chain` and `IjkGrid._chain` import.

**Key classes / functions.**

`class ChainEntry` — `__slots__` dataclass for one threshold node: `name`, `parent_name` (None = rep source is parent), `array`, `assoc`, `proxy` (single Threshold), `visible`, `low`/`high`/`data_range`, and property-kind dispatch fields `kind` ∈ {Continuous, Discrete, Categorical}, `unique_values`, `labels` (`{value: label}`). `to_dict()`.

`_warn_deprecated(name)` — single-fire `[DEPRECATED]` print (keeps logs readable when a legacy path is hit in a tight loop).

`resolve_chain_kind(tree, rep_path, array_name, source_proxy, assoc)` → `(kind, unique_values, labels)`. Derives `kind` from the tree's `propKind`; scans the VTK array for distinct values (capped at `_MAX_DISCRETE_UNIQUES = 64`, demote to Continuous beyond); for Categorical reads LUT `Annotations` labels. Helpers: `_kind_from_tree` (matches a property node by sanitized title, strips the MR `_real_<idx>` suffix; walks the rep subtree first, then falls back to the enclosing `GridContainer` — see Gotchas), `_kind_in_subtree` (the shared walk, returns None when absent), `_normalise_kind`, `_scan_unique_values`, `_drill_inner_partition` (drills the partitioned dataset to the inner partition), `_read_lut_annotations`.

`class ExtractBlockRepresentation`
- `__init__(collector, tree, rep_path)` — builds the source; caller discards the instance if `source is None`.
- `rep_path` / `source` / `chain` properties.
- `_create_source()` — builds the `EnergisticsExtractor` via `_create_plugin_filter_proxy` (reg name `rep` + path with `/`→`_`), sets `ExtractPath`, applies Representation/Scale/tint, Shows in the active view. The docstring documents WHY it bypasses the C++ `ExtractRepPath` path (that path silently fails to re-publish the proxy on a second-pass `rep_path` after a `Delete`, causing "deselect-all + reselect renders nothing").
- `delete()` — slice/clip/chain (children-first) then Hide+Delete source. Idempotent.
- Slice/clip (DEPRECATED, `_warn_deprecated`-guarded): `_ensure_slice`/`slice_state`/`slice_set`/`_ensure_clip`/`clip_state`/`clip_set`/`clip_output`/`refresh_planes_after_property_change`.
- Array introspection: `available_arrays()`, `array_data_range(array_name)`, `_resolve_assoc`.
- Threshold chain (DEPRECATED): `get_chain`, `add_threshold(parent_name, array)`, `delete_threshold(name)`, `set_range`, `set_visible`, `all_visible_thresholds`, `all_chain_proxies`, `deepest_visible_threshold`, plus plumbing `_entry_by_name`, `_effective_input_for_parent`, `_has_visible_descendant`, `_refresh_chain_visibility`.
- Display: `_current_z_scale`, `apply_z_scale(zscale)`, `apply_representation(representation_type)` (these two are still in active use via `SourceRegistry`).

**State.** Reads `state.representation_active`, `state.solid_color_by_rep`, `state.ui_scale_z`, `state.ui_hidden_rep_paths` (note: the FLAT legacy list, not the per-view dict).

**Collaborators.** `representation._{sanitize, find_registered_proxy, apply_default_tint, create_plugin_filter_proxy}`, `utils.naming.make_valid_vtk_name`, `pvsimple`, `vtkSMPropertyHelper`, `SlicePlane`/`ClipPlane`. Created/managed by `SourceRegistry.get_or_create_extract_block`.

**Gotchas.**
- **A grid's properties are SIBLINGS of its geometry rep, not descendants** — both sit under the `GridContainer`'s `PropertiesFolder`, and the geometry rep (title `SolidColor`) has **zero children**. Any "walk the rep's subtree to find its property" code silently finds nothing. `_kind_from_tree` did exactly that and fell back to `"Continuous"`, so EVERY grid Discrete/Categorical property rendered a continuous threshold slider (and `resolve_chain_kind` short-circuited before scanning `unique_values`, leaving them empty). It now retries from the enclosing `GridContainer` when the rep's own subtree misses; non-grid reps have no `GridContainer` ancestor so they are untouched. Note the widened search also lets a `BlockedWellbore` rep (0 property children, same container) resolve the grid's same-titled property — arguably correct, since BW arrays *are* the supporting grid's properties. **This subtree assumption was invalidated by the C++ assembly restructure, not by any Python commit** — `extract_block.py` was byte-identical to v1.1.0 while broken. The same trap lives in `threshold_dispatch._find_property_path_by_title` and `Tree.has_property_descendant` (used by `activator` for `active_representation_has_properties`, now always False for grids): audit every caller before trusting a subtree walk here.
- Despite the class name "ExtractBlock", the proxy it builds is an `EnergisticsExtractor` (the C++ ExtractBlock path was abandoned — see `_create_source` docstring).
- The slice/clip/threshold methods are deprecated Phase-2 fallbacks: they only fire when `vtkEPCCollectorClone` is unavailable. `_chain` stays empty in the normal per-view path. A `[DEPRECATED]` line in the server log means a caller is still hitting them.
- `_refresh_chain_visibility` uses the active view and the FLAT `state.ui_hidden_rep_paths` — different from `RepInScene`'s per-view bucket; this is exactly why the per-view rewrite exists.
- `apply_z_scale` / `apply_representation` are NOT deprecated — `SourceRegistry` still calls them for cross-rep display updates on non-IJK reps.

---

### `fespp_on_trame/app/core/sources/source_registry.py`

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

### `fespp_on_trame/app/core/sources/scene_registry.py`

**Responsibility.** The façade the engine talks to for the per-view world: owns one `ViewScene` per render panel, the view→reps bookkeeping, view-split inheritance (eager bootstrap + per-concern replication), and the per-view IjkGrid sync hooks.

**Key classes / functions.**

`class SceneRegistry`
- `__init__(collector, tree)` — `_scenes: dict` (view_id → ViewScene).
- View lifecycle: `add_view(view_id, pv_view)` (idempotent; creates a `ViewScene`), `remove_view(view_id)` (destroys scene + reps), `get_scene`, `scene_for_pv_view(pv_view)` (reverse lookup used by `source_resolver.apply_color_array`), `has_view`, `view_ids`, `all_scenes`.
- Per-(view, rep): `get_rep(view_id, rep_path)`, `ensure_rep(view_id, rep_path)`.
- `sync_loaded_reps(loaded_rep_paths)` — adds/removes `RepInScene`s in every scene to match the loaded set; eagerly sets up each freshly-added one.
- `_eager_setup_rep_in_scene(scene, rep, rep_path)` — (1) forces per-view extractor creation; (1b) hides it if `rep._hidden_in_scene()`; (2) replicates the active panel's ColorBy onto the new scene (mirrors `ui_active_array_by_rep_by_view`, shows the active wellbore channel, calls `source_resolver.apply_color_array`). Best-effort (every exception swallowed).
- `_source_registry()` — lazy fetch of the legacy registry from `server.context`.
- `apply_visible_markers(view_id)` — after a split, shows every marker in `ui_visible_marker_paths_by_view[view_id]` via the rep's `set_marker_visible`.
- Per-view IjkGrid sync: `mirror_legacy_ijk_state(rep_path, legacy_ijk)` (stop-gap: copies legacy slicer/volume/mode/visibility onto every per-view IjkGrid so they don't render stale positions), `refresh_per_view_ijk_for_rep(rep_path, prop_node_id)` (retargets every scene's per-view IjkGrid).
- `replicate_view(src_view_id, dst_view_id, *, concerns=("threshold","slice","clip","ijk_slicers"))` — copies per-concern state src→dst using `RepInScene.snapshot_*`/`apply_*`. Applies `ijk_slicers` FIRST so the threshold chain attaches to the post-replicate upstream set.
- `release_all()`.

**State.** Reads `state.ui_hidden_rep_paths_by_view`, `state.fespp_active_panel_id`, `state.ui_active_array_by_rep_by_view`, `state.ui_active_realization_by_array_by_view`, `state.ui_visible_marker_paths_by_view`. Writes `state.ui_active_array_by_rep_by_view` (mirroring the active binding into a new view's bucket).

**Collaborators.** `ViewScene`, `RepInScene`, `Tree`, `engine.source_resolver.apply_color_array`. Stored on `server.context.scene_registry`; called by the engine data-load layer (`sync_loaded_reps`), by `SourceRegistry.ensure_ijk_grid`, and by the multi-view layer (`add_view`/`remove_view`/`replicate_view`).

**Gotchas.**
- `_eager_setup_rep_in_scene` is the "view-split inherits active state" bootstrap: without it a split view shows a stale legacy display (Z-fighting / phantom outline) until the user clicks a property.
- `mirror_legacy_ijk_state` keeps per-view IjkGrids in *lockstep* with the legacy slicer config — true per-view slicer divergence is a separate epic (needs the `ui_slices_*` vars to become per-view + republish on panel switch).
- `replicate_view`'s concern ORDER matters (`ijk_slicers` before `threshold`); changing it breaks IjkGrid chain attachment.
- The header lists which methods are deprecated vs active; the per-rep compat shims are NOT here — they're on `SourceRegistry`.

---

### `fespp_on_trame/app/core/sources/view_scene.py`

**Responsibility.** One render view's sub-pipeline root: owns the per-view `vtkEPCCollectorClone` structural anchor, the dict of `RepInScene`s rendered in this view, and the per-`(scene, array)` LUT/PWF proxies that keep ColorBy edits from bleeding across views.

**Key classes / functions.**

`class ViewScene`
- `__init__(view_id, pv_view, collector, tree)` — sets `view_id`, `pv_view`, `collector`, `tree`; builds `_clone` via `_create_clone()`; `_reps: dict`; `_luts`/`_pwfs` dicts.
- `_create_clone()` — builds the `EPCCollectorClone` plugin proxy chained on `collector.get_source()` (reg name `EPCCollector_View{view_id}`), forces `Visibility=0` in every view (it's a structural node, not visual). **Falls back to returning `collector.get_source()` itself** when the clone definition is missing (out-of-date plugin DLL) — this is the Phase-2 `clone=shared` state that disables the per-view extractor path.
- Rep lifecycle: `get_rep(rep_path)`, `add_rep(rep_path)` (idempotent; creates `RepInScene`), `remove_rep(rep_path)` (calls `rep.delete()`), `reps()`.
- `destroy()` — deletes every rep, every per-scene LUT/PWF, and the clone (only if it's a real clone we created, never the collector's own source).
- Per-view LUT/PWF: `_scoped_tf_name(base)` → `f"{base}__{view_id}"`; `get_or_create_lut(base)` / `get_or_create_pwf(base)` (lazily create a scoped transfer function, seed from the global singleton template); `replicate_tfs_from(ref_scene)` (mirror LUT/PWF props on view-duplicate, forcing list copies to avoid aliasing); `get_lut`/`get_pwf` (cached, no-create). Class constants `_LUT_REPLICATED_ATTRS` / `_PWF_REPLICATED_ATTRS` list the cloned props.
- `clone` (property) — the view-scoped scene root.

**State.** None directly (state is touched by the reps/element_type it owns).

**Collaborators.** `RepInScene`, `Collector`, `representation._create_plugin_filter_proxy`, `pvsimple`. Created by `SceneRegistry.add_view`; `replicate_tfs_from` called by the multi-view `add_view` after duplicate.

**Gotchas.**
- `clone` is NOT always a real `vtkEPCCollectorClone`: when the plugin DLL is too old, it's the shared collector source. Every `element_type` source-builder explicitly checks `clone is collector.get_source()` and bails to the legacy path in that case. This is the single switch that decides per-view vs legacy at runtime.
- The per-scene LUT trick exists because PV's `GetColorTransferFunction(name)` is a singleton keyed by array name — without scoped names (`base__view_id`), a Color Options edit in one view bleeds into every other view sharing that array.
- A fresh per-scene PWF is flattened to opacity-1 only when it's PV's untouched two-stop 0→1 ramp; user-edited PWFs (cached) are never re-flattened. Done so the COE doesn't render the lowest scalar at opacity 0 and flip `EnableOpacityMapping` (which would suppress NaN opacity).

---

### `fespp_on_trame/app/core/sources/collector.py`

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

### `fespp_on_trame/app/core/sources/etp_connector.py`

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

### `fespp_on_trame/app/core/sources/slice_plane.py`

**Responsibility.** An axis-snapped-but-freely-orientable single plane *slice* (2D cross-section) over a representation source, with an optional interactive implicit-plane widget. Per-(rep, view) aware.

**Key classes / functions.**

Module helpers: `_AXIS_NORMAL`/`_AXIS_INDEX` maps; `_AXIS_SNAP_COS = cos(5°)`; `_normal_to_axis(normal)` → 'X'/'Y'/'Z' when within 5° of a cardinal axis else None.

`class SlicePlane` (`__slots__`)
- `__init__(rep_path, upstream, state, view_id=None, view_pv=None)` — canonical state `_origin`/`_normal`/`_axis`; builds a `PlaneWidget` (suffix includes `view_id`).
- `_resolve_view()` — captured `view_pv` wins, else `GetActiveView()`.
- Properties: `enabled`, `offset` (origin component along `_axis`), `output` (the Slice proxy).
- `to_dict()` → `{enabled, axis, offset, bounds}`.
- `set(enabled, axis, offset, origin, normal)` — patches any subset (axis snaps normal + recenters; offset moves along axis through bbox centre; normal re-derives axis), then `_apply()`.
- `delete()` — destroys widget, Hides+Deletes proxy.
- Geometry: `_ensure_bounds()` (caches upstream `GetDataInformation().GetBounds()`, seeds origin to bbox centre), `_axis_midpoint`, `_bbox_centre_with_offset`.
- `_ensure_proxy()` — `pvsimple.Slice(SliceType="Plane")`, reg name `slice_{view_id}_{sanitized_rep}`, tints the cross-section bright red so it's visible over the rep.
- `_apply()` — disabled → destroy widget + hide proxy; enabled → set Origin/Normal, Show in resolved view, gate the widget on `state.ui_plane_edit_mode == "slice"`.
- `_on_widget_interact(origin, normal)` — end-of-drag: updates origin/normal, re-snaps axis, updates proxy, publishes state vars, renders.
- `_publish_state_vars()` — writes `ui_slice_*`.

**State.** Reads `state.ui_plane_edit_mode`. Writes `ui_slice_axis`, `ui_slice_offset`, `ui_slice_bounds`, `ui_slice_offset_min`/`_max`/`_step`.

**Collaborators.** `pvsimple`, `representation._sanitize`, `PlaneWidget`. Created by `RepInScene._ensure_slice` (and the deprecated `IjkGrid`/`ExtractBlockRepresentation` paths).

**Gotchas.**
- Slice and Clip share ONE widget edit channel (`ui_plane_edit_mode` ∈ {'slice','clip'}) so only one widget is on-screen even when both filters are applied.
- The red tint is mandatory: without an explicit DiffuseColor the slice picks up the rep's grey and Z-fights into invisibility.
- `view_id` in the registration name is what stops two views' slices for the same rep from colliding on the PV proxy registry.

---

### `fespp_on_trame/app/core/sources/clip_plane.py`

**Responsibility.** A single plane *clip* (volumetric "remove one half") over a representation source — the volumetric analog of `SlicePlane`. Output inherits the rep's coloring. Per-(rep, view) aware. Adds `_inside_out`.

**Key classes / functions.** Mirrors `SlicePlane` almost exactly (same `_AXIS_*`/`_normal_to_axis`, geometry helpers, widget gating).

`class ClipPlane` (`__slots__`)
- `__init__(rep_path, upstream, state, view_id=None, view_pv=None)` — adds `_inside_out`.
- `set(..., inside_out=None)` and `to_dict()` carry `inside_out`.
- `_ensure_proxy()` — `pvsimple.Clip(ClipType="Plane")`, sets `Crinkleclip=0` (smooth cut), reg name `clip_{view_id}_{sanitized_rep}`. **Inherits display props** (Representation/Scale/ColorArrayName/LookupTable/DiffuseColor/AmbientColor/Opacity) from the upstream source ONCE at creation so the clipped half looks like the rep.
- `_apply()` — sets Origin/Normal and the inside-out flag, gates the widget on `state.ui_plane_edit_mode == "clip"`.
- `_on_widget_interact`, `_publish_state_vars()` (writes `ui_clip_*`).

**State.** Reads `state.ui_plane_edit_mode`. Writes `ui_clip_axis`, `ui_clip_offset`, `ui_clip_bounds`, `ui_clip_offset_min`/`_max`/`_step`, `ui_clip_inside_out`.

**Collaborators.** `pvsimple`, `representation._sanitize`, `PlaneWidget`. Created by `RepInScene._ensure_clip` (and deprecated legacy paths).

**Gotchas.**
- PV6 renamed the int `InsideOut` property to the bool `Invert` — `_apply` tries `Invert` first then falls back to `InsideOut`, so the same code works across PV builds.
- Clip inherits coloring only ONCE at creation; a later rep ColorBy doesn't auto-track. `RepInScene.refresh_planes_after_property_change` re-applies it (no-op `set()`), and the user can toggle clip off/on.
- The geometry helpers are deliberately duplicated from `SlicePlane` (the file comment notes a mixin was rejected for readability) — fix bugs in both.

---

### `fespp_on_trame/app/core/sources/plane_widget.py`

**Responsibility.** A thin wrapper around ParaView's `ImplicitPlaneWidgetRepresentation`, shared by `SlicePlane` and `ClipPlane` — places an interactive plane handle (drag sphere = move origin, drag arrow = rotate normal) in a view and fires a callback at end-of-drag.

**Key classes / functions.**

Low-level SM-property helpers (the raw `pxm.NewProxy` proxy has no Python attribute access): `_set_prop_scalar(proxy, name, value)`, `_set_prop_vec(proxy, name, values)`, `_get_prop_vec(proxy, name, n)`.

`class PlaneWidget` (`__slots__`)
- `__init__(id_suffix, bounds_provider, on_end_interact)` — `bounds_provider` is a callable `() -> 6-tuple` for placement; `on_end_interact` is `(origin[3], normal[3])`.
- `proxy` / `view` properties.
- `ensure(view)` — creates the widget via `ProxyManager().NewProxy("representations", "ImplicitPlaneWidgetRepresentation")`, registers it under `plane_widget_{sanitized_suffix}`, sets `PlaceFactor=1.05`, calls the client-side `PlaceWidget(bounds)`, adds it to the view's `HiddenRepresentations` (so the interactor sees it), enables/shows it, and installs an `EndInteractionEvent` observer that reads Origin/Normal and calls `on_end_interact`. Tears down a stale instance if attached to a different view first.
- `sync(origin, normal)` — pushes panel-driven edits onto the widget handles.
- `destroy()` — removes the observer, hides/disables, removes from `HiddenRepresentations`, unregisters from the `"widgets"` group.

**State.** None.

**Collaborators.** `paraview.servermanager.ProxyManager`, `representation._sanitize`. Owned by `SlicePlane`/`ClipPlane`.

**Gotchas.**
- The widget is registered into the view's `HiddenRepresentations` (not a normal display) — that's how the 3D interactor picks it up without it being a rendered source.
- `PlaceWidget` is called on the *client-side* VTK object (`GetClientSideObject().PlaceWidget`), not via an SM property.
- Each filter creates its own `PlaneWidget` instance, but the slice/clip edit-mode logic ensures only one calls `ensure(...)` at a time (the `ui_plane_edit_mode` channel).
- If the PV build lacks the `ImplicitPlaneWidgetRepresentation` proxy, `ensure` logs a warning and silently no-ops (interactive editing unavailable, panel sliders still work).

---

### `fespp_on_trame/app/core/sources/__init__.py`

Empty package marker (skipped per the documentation rules).
