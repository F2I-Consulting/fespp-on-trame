# Engine — Lifecycle & State

> **19/10/2026 — the per-representation model is gone (overhaul, decision Q2 bis).** `RepInScene`, `ViewScene`, `SceneRegistry`, the activator, the legacy visibility and active-array dispatch, the slice / clip planes and the `FESPP_BLOCKSCOPE` flag were removed: each view draws through its composite scene (`engine/blockscope`), a cut or filtered grid through its `GridIsolate`. A passage below that still names them describes removed code.

## Overview

The `fespp_on_trame/engine/` package is the **server-side brain** of the app. It sits between the Vue/Trame UI (state variables, controller methods, server triggers) and the data layer (`SourceRegistry`, `SceneRegistry`, the FESPP C++ collector via `paraview.simple`). `boot.py` is the single entry point: `initialize_fespp_engine(server, *, fespp_plugin_path)` loads the FESPP ParaView plugin, constructs all long-lived objects (`Tree`, `Collector`, `ETPConnector`, `SourceRegistry`, `SceneRegistry`, `Selector`, `Activator`), seeds every Trame state variable, and registers ~50 `@state.change` / `@controller.set` / `@server.trigger` handlers. Each handler is a thin shim that captures the constructed objects in its closure and forwards to a focused **dispatch module** (`data_load`, `visibility`, `active_array`, `hierarchy`, `selection_dispatch`, `view_ops`, plus threshold/slice/clip/marker/realization/stats/distribution dispatchers documented elsewhere).

The package is mid-migration from a **legacy single-view model** (one shared `SourceRegistry`, flat state vars like `ui_active_array_by_rep` / `ui_hidden_rep_paths`) to a **per-view scene model** (`SceneRegistry` of `ViewScene`s, each owning per-`(view, rep)` `RepInScene` pipelines, with `*_by_view` maps as the source of truth). The two coexist: the flat vars are kept as live mirrors of the *active panel*'s bucket so legacy consumers keep working. Understanding this duality is the single most important thing for a forker — most "why are there two of these?" questions trace back to it. The files in this page cover lifecycle/wiring (`boot`, `state_defaults`), the load pipeline (`data_load`), input dispatch (`selection_dispatch`, `hierarchy`), output mutation (`visibility`, `active_array`), and the per-view resolution helpers (`source_resolver`, `panel_resolver`, `view_ops`).

---

### `fespp_on_trame/engine/boot.py`
**GONE (2026-09-16).** The former wiring hub (`initialize_fespp_engine`, 1743 lines) had not been executed since the per-view architecture: the application boots through `app/boot.py` (`boot_engine`), which constructs the engine objects, seeds `state_defaults` and registers every handler. The one helper still in use, the ExplicitStructuredGrid plugin locator, lives in `engine/plugins.py` (`resolve_esg_plugin`). Deleted with it, for the same reason: `engine/clip_dispatch.py`, `engine/slice_dispatch.py`, `engine/selection_dispatch.py`, `engine/slicer_dispatch.py` (their live counterparts are the per-view `sources/slice_plane.py`, `sources/clip_plane.py`, the selection invariant of `app/boot.py` and `sources/ijkgrid.py` driven by the Slicers card), `app/ui/tree_views.py` (its one live function, the selection cascade, is now `app/ui/selection_deps.py`), the never-instantiated `widgets/stats`, and twenty state defaults nothing read any more (`animation_delay`, `load_mode`, `ui_slicers_tab`, `fespp_stats_panel_id`, `ui_stats_panel_minimized/maximized`, `ui_slice_enabled`, `ui_clip_enabled`, `ui_slices_*_active`, `ui_threshold_local_ranges`, `vtk_log_visible`…). `tests/unit/test_engine_package_imports.py` now walks every module of the package.

---

### `fespp_on_trame/engine/state_defaults.py`

**Responsibility.** Seed (via `state.setdefault`) every Trame state variable the engine and UI assume to exist, in one declarative place so `boot.py` stays focused on lifecycle. Grouped roughly by data-flow stage (selection → loaded → visible → coloured → threshold → diff → stats).

**Key classes / functions.**
- `init_state_defaults(state) -> None` — called once near the start of `initialize_fespp_engine`. Pure sequence of `state.setdefault(name, default)` calls. It is the **authoritative catalogue of state-var shapes** — the inline comments document the exact dict/list structure of every non-trivial var (read this file to learn the data model). Key buckets and their documented shapes:
  - Selection: `ui_select_node_reservoir/surface/well` (lists), `fespp_data_selectors` (list).
  - Per-tab active-property sets: `ui_active_node_<tab>_{array_name, rep_path, property_kind, array_path, rep_has_props}` for the three tabs, plus `ui_active_node_reservoir_pending` (selected-but-not-loaded gate); a refused uncheck (trajectory veto, threshold guard, a trajectory a blocked wellbore pulls back) speaks through the amber snackbar (`empty_color_snackbar_text` / `_visible`) and keeps no state of its own. The legacy shared vars (`active_color_array_name`, `active_property_kind`, `active_representation_path`, `active_color_array_path`, `active_representation_has_properties`) are **projections of the visible tab's set** — see `activator.project_shared_from_tab`.
  - Visibility: `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view` (`{panel_id: [rep_path,...]}`).
  - Coloring: `ui_loaded_array_paths`, `ui_active_array_by_rep` (`{rep_path: array_path}`, mirror of active panel), `ui_active_array_by_rep_by_view` (`{panel_id: {rep_path: array_path}}`, source of truth), `ui_loaded_marker_paths`, `ui_visible_marker_paths_by_view`, `panel_has_ts_by_id`.
  - Realizations: `ui_active_realization_by_array_by_view` (`{panel_id: {array_path: idx}}`), `ui_panel_active_mr_specs_by_id`, `panel_has_mr_by_id`, `ui_global_mr_specs`, `ui_global_mr_selected_path`, `ui_global_mr_selected_spec`.
  - Diff / ETP / view-status / VTK-log / upload-progress blocks.
  - Slice plane (`ui_slice_enabled/axis/offset/bounds` + server-resolved `ui_slice_offset_min/max/step`), Clip plane (parallel `ui_clip_*` incl. `ui_clip_inside_out`), `ui_plane_edit_mode` (`"slice"|"clip"|None`).
  - IJK slicer (`ui_range_i/j/k`, `ui_slices_*_list`, `ui_volumes_list`, `ui_volumes_visible_list`, `ui_slices_*_visible_list`, `ui_threshold_chain`, etc.).
  - The Statistics view: `ui_compare_parts` (the parts of a grid whose eye is open), `ui_compare_session_rows` (the extracts' rows of its tree), `ui_per_view_time_pulse`. (Its `ui_compare_*` payload is seeded by boot, not here.)
  - The heavy recomputes. The matrix of the Statistics view reads every cell of a grid, so `app/features/heavy._defer` runs the bar of their views (`ui_view_busy__<id>`, `view_wait`), flushes, yields the event loop one turn (the flag reaches the browser) and computes on the next turn; requests made in the same turn coalesce into one compute. The view keeps its content meanwhile. `controller.heavy_pending()` says whether one is still running — the headless runner waits on it after each step.
  - Drawer target: `drawer_target_view_id` (`""`), `drawer_target_view_pinned` (`False`).
  - Panel ids / overlay flags: `ui_distribution_contexts` (per panel, what it reads: `{array_path, row_kind, row_id, real, ts, item}`, `item` the uid of the Statistics row it follows), `ui_slicers_tab` (`"ijk"`).
  - Misc: `load_mode` (`"auto"`).

**State.** Writes (defaults-only) every var listed above. Reads none.

**Collaborators.** No imports. Called exactly once by `boot.initialize_fespp_engine`. Every other engine module assumes these defaults are present.

**Gotchas.**
- Uses `state.setdefault` not `state[...] = ` — re-running it (or a later `setdefault` in boot) won't clobber a value already set.
- The flat vars (`ui_active_array_by_rep`, `ui_hidden_rep_paths`) are documented here as **mirrors of the active panel's per-view bucket**, not independent state — do not write them as if they're authoritative.
- `ui_per_view_time_pulse` is a **monotonic counter used as a change pulse**, not real data — it funnels dynamic `time_value_<panel_id>` changes into the static `@state.change` declaration.
- `ui_compare_visible_metrics` (seeded in boot, not here) is a **whitelist**, filtered through `compare_matrix._METRIC_KEYS` on every write, so the metrics the Statistics view shows are always canonical keys in canonical order.

---

### `fespp_on_trame/engine/data_load.py`

**Responsibility.** The load-time pipeline driver. `run(...)` fires on every `fespp_data_selectors` change and performs the full sequence: push selectors to the active source, hide the parent multiblock, reserve chip colors, sync the registries, bump pipeline info, notify the activator, maintain all visibility/array/marker/active-array tracking state, refresh threshold + IJK UI, and do a single final Render. The order of operations is load-bearing and heavily commented.

**Key classes / functions.**
- `run(state, controller, server, view, tree, collector, etp_connector, source_registry, activator, refresh_threshold_ui, push_active_ijk_state)` — the driver. Steps, in order: (1) pick `active_source = etp_connector if etp_connector.is_connected else collector`; (2) `SetPropertyWithName('Selectors', ...)` + a single `UpdatePipeline()` + `show()` (the C++ `ClearSelectors`/`AddSelector` are Modified()-only, so one explicit RequestData here materialises the multiblock once); (3) hide the parent rep (`Assembly='Assembly'`, `BlockSelectors=['/data']`, `Visibility=0`) BEFORE any render to avoid O(N) per-block painting; (4) reserve a `color_for_index` chip color per newly-loaded rep into `solid_color_by_rep` (cached via `_selector_rep_cache`), BEFORE `sync` so new sources tint immediately; (5) `source_registry.sync(selectors, ui_select_node_reservoir)` + `ijk.update_block_visibility()` per grid; (6) `Modified()` + `UpdatePipelineInformation()` on every source, plus full `UpdatePipeline()` on IjkGrid `_src_extract_init` and its slicers/volume; (7) `activator.notify_active_reps(present_paths)`; (8) the four tracking helpers below; (9) **synchronous eager teardown** of deselected reps' per-view pipelines via `scene_reg.all_scenes()` → `scene.remove_rep`; (10) `SetActiveSource` + `on_data_loaded` / `on_active_proxy_change`; (11) camera reset on the first load that MATERIALISES geometry (`GetNumberOfCells() > 0` — an H5-less EPC selection must not consume the one-shot flag, else the post-H5 retry renders off-centre): a SYNCHRONOUS server-side `pvsimple.ResetCamera(view)` + `CenterOfRotation=focal` so the final frame push already carries the framed camera (the `view_reset_camera` sentinel resolves in a LATER flush through an async html-widget reset — relying on it alone left the client on the empty-scene default camera until the next manual interaction), then the sentinel is still set for block-visibility refresh + client resync; (12) `activator.refresh_active()`, then **re-apply the grid's active colouring when blocked wellbores appeared in this run** — a wellbore checked while its grid already colours by a property would otherwise arrive SolidColor (the active-array map didn't change, so nothing else re-applies; threads the active panel's MR realization index, without which an MR property resolves to nothing), and the same block seeds each fresh wellbore's mirrored THRESHOLD chain from its grid's `snapshot_threshold_chain()` (the dispatch mirror `sync_blocked_wellbore_chains` only fires on threshold ops, so a BW checked after the filter was set would render unfiltered without this); (13) `refresh_threshold_ui()`, `push_active_ijk_state()`; (14) final `pvsimple.Render(view=view)` only when selection is non-empty. Note the loading path **never re-opens a hidden rep's eye** (the old "select a property = load + eye" force-unhide is gone — visibility and colouring are orthogonal).
- `_update_visibility_tracking(state, present_paths)` — maintains `ui_loaded_rep_paths`, prunes `ui_hidden_rep_paths` to present reps, and for each non-active per-view bucket appends newly-loaded reps as hidden (PV only adds the new display to the active view, so other panels' chips should read "closed").
- `_update_data_array_tracking(state, tree, present_paths) -> (last_array_for_rep, prev_loaded_set)` — recomputes `ui_loaded_array_paths` (selectors whose `element_type.for_kind(type).tracking_bucket() == BUCKET_ARRAY` and whose rep is present), and returns the "last added array per rep" map (the default active eye).
- `_update_marker_tracking(state, tree, present_paths)` — recomputes `ui_loaded_marker_paths` (`BUCKET_MARKER`) and prunes `ui_visible_marker_paths_by_view`.
- `_update_active_array_maps(state, tree, present_paths, last_array_for_rep, prev_loaded_set)` — recomputes `ui_active_array_by_rep` (global) and `ui_active_array_by_rep_by_view` (per-panel). Rule: a newly-loaded array auto-becomes the rep's active one **only in the currently-active panel**; otherwise keep the prior choice if still loaded; otherwise SolidColor. For MR auto-activations it seeds `ui_active_realization_by_array_by_view` with the smallest index.

**State.** Reads: `fespp_data_selectors`, `ui_select_node_reservoir`, `solid_color_by_rep`, `solid_color_next_idx`, `_selector_rep_cache`, `has_data_loaded_once`, `fespp_active_panel_id`, the prior values of every tracking var. Writes: `solid_color_by_rep`, `solid_color_next_idx`, `_selector_rep_cache`, `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view`, `ui_loaded_array_paths`, `ui_loaded_marker_paths`, `ui_visible_marker_paths_by_view`, `ui_active_array_by_rep`, `ui_active_array_by_rep_by_view`, `ui_active_realization_by_array_by_view`, `view_update`, `view_reset_camera`, `has_data_loaded_once`.

**Collaborators.** Imports `color_for_index` (`utils.color_palette`) and `element_type`; lazily imports `realization_dispatch` inside `_update_active_array_maps`. Calls `source_registry.sync/.ijk_grids/.all_sources/.items`, `activator.notify_active_reps/.refresh_active`, `server.context.scene_registry`, `controller.on_data_loaded/on_active_proxy_change`. Sole caller: boot's `@state.change("fespp_data_selectors")`.

**Gotchas.**
- **Ordering is critical and documented per-step.** Notably: the IjkGrid slicers need a full `UpdatePipeline()` (data pass), not just `UpdatePipelineInformation()` — otherwise the slicer keeps a structurally-valid grid with NO CellData arrays and the activator's `_find_array_in_store` misses the property. This surfaced after the per-view scene refactor (commit `3fb95016`) because per-view IjkGrid creation invalidates the collector MTime.
- **The MR realization bucket MUST be written BEFORE the active-array buckets** in `_update_active_array_maps`, because the active-array `@state.change` handlers read the realization bucket to resolve the suffixed VTK array name. Wrong order ⇒ rep stays SolidColor on first MR load.
- **Synchronous teardown of deselected reps (step 9)** is a segfault avoidance: the deferred teardown (`@state.change("ui_loaded_rep_paths")`) runs AFTER this function's activator render, and rendering a stale still-visible source against a clone whose upstream partition is gone crashes natively ("Connection Closed", no traceback). REMOVE-only here; the add half stays deferred.
- **`controller.view_replace` on line 240 is a bare expression** (no call) — effectively dead; don't assume it replaces anything.
- The final `Render` is **skipped on empty selection** as belt-and-braces against an empty-pipeline crash inside `vtkPVRenderView`.
- `active_source.show()` is called early but `run` deliberately does NOT call it again before the final render (it would re-set the parent rep's `Visibility=1` and undo the early hide).

---

### `fespp_on_trame/engine/selection_dispatch.py`
**GONE (2026-09-16)** — see `engine/boot.py` above. The per-tab checkbox arrays reach the reader through the selection invariant of `app/boot.py` (`_on_selectors`, `selection_deps._expand_selection_with_deps`); there is no manual load mode any more.

---

---

### `fespp_on_trame/engine/source_resolver.py`

**Responsibility.** Free-function helpers (extracted from boot closures) that resolve a rep path to its rendered/colorable PV sources, displays, and VTK array names, and that apply ColorBy / SolidColor with the PV6 workarounds and per-view scoped LUTs. Each takes its dependencies explicitly — no module-level state.

**Key classes / functions.**
- `sources_for_rep_path(source_registry, rep_path, view=None) -> (sources, view)` — *rendered* source proxies for a rep. Per-view first: `RepInScene.element_type.rendered_sources(...)`. Falls back to the legacy shared IjkGrid (slicers + volume + rep_data, substituting the deepest visible threshold leaf) then ExtractBlock (deepest visible threshold or the source) then name-matched `rep<path>` sources.
- `color_sources_for_rep_path(source_registry, rep_path, view=None) -> (sources, view)` — like above but returns EVERY chain proxy (visible or not) plus the per-`(rep,view)` clip output (`_scene_clip_output_for_view`); slice's display is intentionally excluded (tinted red). Per-view first via `element_type.color_sources(...)`.
- `displays_for_rep_path(source_registry, rep_path, view=None) -> [display]` — `GetDisplayProperties` for every source from `color_sources_for_rep_path`.
- `resolve_array_for_path(source_registry, tree, rep_path, array_path, realization_idx=None, view=None) -> (assoc, vtk_array_name)` — resolves the VTK array name. Consults the per-view source first (channel's own extractor for frames via `element_type.array_candidate_source(...)`), tries the MR-suffixed name `<sanitized_title>_real_<idx>` when `realization_idx` is set, then falls back to raw title / `make_valid_vtk_name(title)`. Returns `(None, None)` on miss.
- `apply_color_array(source_registry, tree, rep_path, array_path, view=None, realization_idx=None, clear_on_empty=False) -> bool` — the workhorse. Clears to SolidColor when `array_path` falsy; otherwise resolves the array, ColorBy's each display, swaps to per-view scoped TFs (`swap_to_scene_tfs`), force-rescales the LUT from the fresh client-side array range (`_vtk_array_range_from_clientside`) — **unless the range is user-pinned** (`leaf_rep.range_is_pinned`: the COE Min/Max Apply sets `AutomaticRescaleRangeMode='Never'` on the LUT) — shows the scalar bar via `SetScalarBarVisibility`, and sweeps orphan bars. Returns `False` when `array_path` resolves to nothing (caller surfaces a "no data" alert); `clear_on_empty=True` (eye toggles only) additionally clears the stale ColorBy.
- `blocked_wellbore_rep_paths_for(tree, rep_path) -> [path]` — the BlockedWellbore rep paths grouped under the same GridContainer as a grid geometry rep (empty for non-grids).
- `_mirror_color_to_blocked_wellbores(source_registry, tree, rep_path, assoc, name, view)` — FESPP mirrors a grid's CELL arrays onto its blocked wellbores (same names, restricted to the crossed cells); this mirrors the **ColorBy** too, so the wells follow the grid's active property — including while the grid is hidden. Hooked into `apply_color_array` on all three outcomes (apply / deselect-clear / empty-clear), BEFORE the orphan-bar sweep: the wellbore displays reference the same scoped LUT, which is what keeps the shared colour bar alive when the grid itself is hidden. Skips unchecked wellbores (no displays → no load).
- `hide_unused_scalar_bars(view=None)` — `vtkSMTransferFunctionManager.UpdateScalarBars(view.SMProxy, 1)` sweep.
- `layout_visible_scalar_bars(view=None)` — spreads the visible colour bars over a fixed 4-corner rotation (lower-right, upper-right, upper-center, lower-center — left column reserved for the orientation axes and in-view toolbar), in stable representation-list order. Bars past the 4th re-stack on the last spot: accepted limitation (`PlaceInView` delegation was tried and had no visible effect in this remote-render setup); a real layout manager is future work. Called at the end of `apply_color_array` (after the sweep) and of `reassert_active_scalar_bars`.
- `reassert_active_scalar_bars(state, source_registry, view=None)` — end-of-load-batch invariant "the active array's bar is visible": for every `(rep → array)` in `ui_active_array_by_rep`, re-shows the bar of the first visible bound display. Exists because an unidentified writer raw-hides freshly shown bars mid-batch (bypasses every helper here; two probe rounds could not name it). Ends with `layout_visible_scalar_bars`.
- `swap_to_scene_tfs(displays, target_view, array_name) -> (scene_lut, scene_pwf)` — rebinds each display's `LookupTable`/`ScalarOpacityFunction` to the per-`(scene, array)` proxies so a COE edit doesn't bleed across views. Returns `(None, None)` for legacy/pre-scene views.
- `resolve_target_scoped_lut(array_name) -> (base, scene_lut)` — for COE-style edit panels: resolves the UI title into the per-(drawer-target scene, MR-suffixed base) LUT.
- `target_view_and_panel() -> (pv_view, panel_id)` — drawer target resolution (falls back to active panel).
- `render_and_push_target(controller)` — render the drawer target's view + push its frame via `controller.view_update_for(panel_id)` (falls back to `view_update`). **Coalesced** (trailing-edge debounce, 50 ms per panel): one user gesture fans out to several COE state handlers and each used to render + push its own identical ~370 ms frame — six per property switch, measured. Only the last call in a burst renders (`_render_and_push_target_now`). Immediate fallback when no event loop runs.
- `blocked_wellbore_rep_paths_for` fans out **only from a grid geometry rep** (`IjkGrid`/`UnstructuredGrid` type check): a BlockedWellbore sits under the SAME GridContainer, so without the guard each wellbore's own apply/clear walked every sibling — the active-map sweep went O(N²) (~6 700 display resolutions ≈ 9 s measured with 82 wells) and a wellbore's None-apply mass-cleared its siblings' colouring, surviving on iteration-order luck.
- `scene_lut_for_view(view, array_name)` — per-view LUT if it exists else PV global singleton.
- `channel_source_for(channel_path)` — per-`(channel, view)` extractor for a wellbore channel in the drawer-target view, materialised (hidden) if absent.
- `real_base_name(array_name, rep_path, view)` — the ACTUAL VTK base name: raw (unsanitized) title for channels (whose POINT array is named verbatim), sanitized for grids/surfaces.
- `nondegenerate_range(lo, hi)` — widens a zero/non-finite-width range so the COE CanvasGradient doesn't divide by zero.
- Private helpers: `_scene_rep_for_view(rep_path, view)`, `_scene_clip_output_for_view(rep_path, view)`, `_vtk_array_range_from_clientside(pv_src, name, assoc)`, `_src_has_named_array(src, name)`, `_clear_coloring(displays, view)`.

**State.** Reads (via lazy `get_server()`): `drawer_target_view_id`, `fespp_active_panel_id`, `active_representation_path`, `ui_active_node_reservoir`. No writes.

**Collaborators.** Imports `make_valid_vtk_name` (`utils.naming`); lazily imports `get_server`, the `engine` package (`_tree`), `realization_dispatch`. Reaches `server.context.scene_registry` and the mirrored `engine._tree`. Called extensively by `active_array.py`, `visibility.py`, boot's realization trigger, and edit panels.

**Gotchas.**
- **IjkGrid is checked FIRST in both source resolvers** specifically to avoid the rep_data extractor lazily creating a default display (`Visibility=1, Representation='Outline'`) in a new view and rendering a phantom outline overlay on top of the slicers.
- **Channel array names are NOT sanitized** (`ResqmlWellboreChannelToVtkPolyData` uses `getTitle()` verbatim) while grid/surface properties are. `real_base_name` / `resolve_array_for_path` probe the actual source so the COE keys the same per-view LUT — blindly sanitizing keys a different, never-rendered LUT and blanks the COE.
- **PV6 quirk:** `pvsimple.ColorBy(display, None)` raises "invalid association string NONE", so SolidColor is cleared via `SMProxy.SetScalarColoring("", 0)` in `_clear_coloring`.
- **LUT rescale workaround:** `ColorBy`'s internal `RescaleTransferFunctionToDataRange` reads a stale proxy info cache after an in-place re-extraction (channel/marker retarget), leaving the LUT at `[0,1]` (tube paints flat). `apply_color_array` reads the fresh client-side range via `_vtk_array_range_from_clientside` and rescales — skipped for `IndexedLookup` (categorical) LUTs.
- **Scalar-bar visibility must go through `SetScalarBarVisibility`** (drives the TransferFunctionManager to re-attach the bar) — a raw `bar.Visibility = 1` is a no-op after a `hide_unused_scalar_bars` sweep unbound it.
- `_clear_coloring` hides the bar via `SetScalarBarVisibility(view, False)` BEFORE severing the LUT wire — the manager only reaps bars whose LUT it still tracks as wired.

---

### `fespp_on_trame/engine/panel_resolver.py`

**Responsibility.** Tiny per-panel resolution helpers shared by `visibility` and `active_array` dispatch: translate a panel id into the right PV view / HTML view, with a legacy active-view fallback.

**Key classes / functions.**
- `resolve_view_and_html_view(server, panel_id) -> (pv_view, html_view)` — asks `server.context.multi_view.get_pv_view(panel_id)` / `get_html_view(panel_id)`. Returns `(pvsimple.GetActiveView(), None)` when `panel_id` is empty/unknown or no multi_view is mounted; if only the pv_view lookup misses, falls back to the active view but keeps any html_view.
- `active_panel_id(server) -> str | None` — `multi_view._active_panel_id` coerced through `view_routing.resolve_active_render_panel`: the focused dockview panel can be a statistics or distribution tab, and every caller here writes a colour or visibility bucket keyed by view — a non-render id would strand the write in a bucket no tree annotation or render path ever reads. None when no multi-view is mounted yet.

**State.** None.

**Collaborators.** Imports `pvsimple`. Reads `server.context.multi_view`. Called by `visibility.py`, `active_array.py`, boot's `set_view_realization` trigger.

**Gotchas.**
- `active_panel_id` reaches into a **private attribute** `multi_view._active_panel_id` — coupling to the multi_view's internals. A forker changing the multi_view must keep that attribute.
- The `(active_view, None)` fallback is what keeps every legacy single-view code path alive when callers don't supply a `panel_id`; the `html_view` being None is the signal downstream to fall back to `controller.view_update()`.

---

---

## The selection invariant (`app/boot.py`, 2026-09-13)

`selected_paths` is the ONE channel that loads: the data tree writes it, `_on_selected` watches it, `_apply_selection` expands it (cascades, the property → representation pull, the blocked-well trajectory pull, the vetoes) and hands the effective set to `fespp_data_selectors`. The expansion is a **delta machine**: it compares what it is given against `_prev_selected["paths"]`, its own baseline, and reads what left the set as an untick to cascade. The invariant that makes that safe is

> after every call, `state.selected_paths == _prev_selected["paths"]`.

A tick made in a **panel's** tree does not come through that variable — it calls `_apply_selection` directly, through `_panel_tick_read` — so it passes **`push=True`**, and the write at the end of `_apply_selection` is then unconditional (`state.selected_paths = eff_paths`, plus `state.dirty`, since trame drops a write equal to the value it holds). Without it the write was skipped whenever the expansion added nothing to what the caller already listed — the common case, since the property's representation was already selected — and the baseline advanced alone: the session's selection stayed one property behind, and the NEXT tick in the data tree (whose widget sends its own list, which never held that property) read it as newly unticked and unloaded it, taking the figures of its row in the Statistics view with it.

Two per-view baselines sit beside it, for the same reason in the opposite direction — a two-way tree's ticks are rewritten by the server, and that rewrite fires the tree's own watcher straight back:

- `_compare_published[vid]` — the paths last published to `compare_tree_selected__<vid>`. `compare_tree_paths` returns early on an incoming set equal to it. Without that, a folder tick re-synced the tree to its 27 leaves, re-entered, and posed a SECOND question over the first: the single `_tick_ask` slot then held the second gesture's callbacks, so `Cancel` restored the 27 already taken in and left the reader with 27 ticked boxes and 27 empty rows blaming the file.
- `_welllog_published[vid]` — the tick set last published to `welllog_tree_selected__<vid>` (the wells AND what the panel draws under them, `_welllog_ticks`). `welllog_tree_wells` reads an untick against **that**, never against `selected_paths`: a node the tree never showed ticked was never the reader's to untick. The tree seeds itself through `controller.welllog_tree_ticks(vid)` for the same reason — seeded with the wellbores alone, the very first watcher call on a panel opened over a full log read as "the reader has just unticked all 176 read nodes", `welllog_dropped__<vid>` swallowed the trajectory, every frame and every channel, and the panel drew nothing under an empty state saying no curve had been read.

`_ask_tick` refuses a second question while one stands: the standing box keeps its answers and the newcomer steps back at once through its own `on_no`, which is what a cancel does anyway. Both baselines are pruned to the open panels by the `_sync_*_trees` that write them, so a closed view leaves nothing behind.

`_apply_selection` also takes **`on_go`**, the third hook: what puts the ticked object in the panel, run only when the read goes ahead. Filling the panel first — taking the well into the log — showed the reader a panel already holding what the box behind it was still asking about, each row saying its dataset could not be read. With `on_go` the refusal has nothing to undo: `on_no` puts the tree's checkboxes back and that is all.

The log's `on_go` (`_hold`) re-syncs its own tree ONLY when the wells did not move. When they did, `_on_welllog_inputs` — which watches `ui_welllog_wells` and `selected_paths` — does it after the read; writing the boxes in the same flush as the read instead sent a stale echo (the wells alone) back through the tree's watcher, against a baseline the read had already advanced to the full tick set, and the log dropped all 176 nodes the tick had just brought in. `welllog_tree_wells` returns early on a tick set equal to what the server last published, for the same reason.
