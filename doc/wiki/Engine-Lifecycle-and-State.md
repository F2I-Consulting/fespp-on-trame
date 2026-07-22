# Engine — Lifecycle & State

## Overview

The `fespp_on_trame/app/core/engine/` package is the **server-side brain** of the app. It sits between the Vue/Trame UI (state variables, controller methods, server triggers) and the data layer (`SourceRegistry`, `SceneRegistry`, the FESPP C++ collector via `paraview.simple`). `boot.py` is the single entry point: `initialize_fespp_engine(server, *, fespp_plugin_path)` loads the FESPP ParaView plugin, constructs all long-lived objects (`Tree`, `Collector`, `ETPConnector`, `SourceRegistry`, `SceneRegistry`, `Selector`, `Activator`), seeds every Trame state variable, and registers ~50 `@state.change` / `@controller.set` / `@server.trigger` handlers. Each handler is a thin shim that captures the constructed objects in its closure and forwards to a focused **dispatch module** (`data_load`, `visibility`, `active_array`, `hierarchy`, `selection_dispatch`, `view_ops`, plus threshold/slice/clip/marker/realization/stats/distribution dispatchers documented elsewhere).

The package is mid-migration from a **legacy single-view model** (one shared `SourceRegistry`, flat state vars like `ui_active_array_by_rep` / `ui_hidden_rep_paths`) to a **per-view scene model** (`SceneRegistry` of `ViewScene`s, each owning per-`(view, rep)` `RepInScene` pipelines, with `*_by_view` maps as the source of truth). The two coexist: the flat vars are kept as live mirrors of the *active panel*'s bucket so legacy consumers keep working. Understanding this duality is the single most important thing for a forker — most "why are there two of these?" questions trace back to it. The files in this page cover lifecycle/wiring (`boot`, `state_defaults`), the load pipeline (`data_load`), input dispatch (`selection_dispatch`, `hierarchy`), output mutation (`visibility`, `active_array`), and the per-view resolution helpers (`source_resolver`, `panel_resolver`, `view_ops`).

---

### `fespp_on_trame/app/core/engine/boot.py`

**Responsibility.** The wiring hub. `initialize_fespp_engine` constructs every long-lived engine object once at server start, seeds state, and registers all UI-facing handlers, each delegating to a dispatch module. It also defines several non-trivial closures (the slicer/IjkGrid bridging helpers, the per-panel stats/distribution recompute machinery) that are too entangled with the captured objects to extract.

**Key classes / functions.**
- `initialize_fespp_engine(server: Server, *, fespp_plugin_path: Path) -> None` — the whole module is this one function plus its inner closures and decorated handlers. Order of work: (1) eagerly `server.enable_module(trame_plotly.module)` so the Distribution panel's lazily-created Figure widget still receives its JS bundle; (2) `pvsimple.LoadPlugin(fespp_plugin_path)` + load the bundled `ExplicitStructuredGrid` plugin (needed for IJK volume crop/slicing); (3) create the `RenderView`; (4) `setup_stderr_tee()` (after PV init, to avoid flooding the VTK-log queue with startup noise); (5) build `Tree`, `Collector`, `ETPConnector`, `SourceRegistry`, `SceneRegistry`, `Selector`, `Activator`; (6) `init_state_defaults(state)`; (7) register handlers.
- Inner closure `_ijkgrid_by_rep_path(rep_path)` — the `Activator`'s `ijk_lookup`. Resolves an `IjkGrid` for a rep path, **preferring the drawer-target view's per-view instance** (`scene_registry.get_rep(target_panel, rep_path)._per_view_ijk`, materialised via `_ensure_per_view_ijk()`), falling back to the legacy shared `source_registry.get_ijk_grid(rep_path)`. Must return the per-view grid because the per-view rendering fix hides every legacy IjkGrid source in the panel's view, so the activator's visible-source walk would otherwise bail and leave `active_color_array_name` stale (Colors & Opacity panel stuck on SolidColor).
- Inner closure `_active_ijkgrid()` — thin wrapper keyed on `state.active_representation_path`.
- Inner closure `_push_active_ijk_state_to_ui()` — mirrors the active IjkGrid's `to_ui_state()` snapshot into the flat `ui_slices_*` / `ui_range_*` vars. Called on active-grid change, after grid creation in the load handler, AND on panel switch (Phase 3b: each view owns its slicer state).
- Inner closures `_refresh_threshold_ui_for_active_grid()`, `_refresh_descriptive_stats()`, `_open_stats_if_closed()` — stats/threshold UI republishers.
- Inner closures `_refresh_distribution(panel_id)`, `_refresh_compare_stats(array_path)`, `_refresh_compare_dist(array_path)`, `_spawn_distribution_panel(*, kind, context)`, `_csv_data_url(csv_text)`, `_distribution_option_vars(panel_id)` — the per-panel Distribution / Compare-stats machinery. `_spawn_distribution_panel` registers a runtime `state.change(*option_vars)(callback)` watcher per spawned panel and stores the row context in `state.ui_distribution_contexts[panel_id]`. Note the documented ordering constraint: `mv.add_view(kind="distribution")` runs the template build synchronously, which is when `controller.update_distribution_figure_<id>` is set — so it exists by the time the helper returns.
- Inner closures `_follow_mode_target_from_active()` / `_sync_pvsimple_active_to_target()` — drawer-target resolution. The latter forces `pvsimple.SetActiveView(scene.pv_view)` so legacy panels (`SolidColorPanel`, `RepresentationTypePanel`) edit the pinned target rather than the focused panel.

**Registered handlers (the wiring map).** State-change handlers:

| Trigger | Handler | Delegates to |
|---|---|---|
| `@state.change("trame__busy")` | `_on_trame_busy` | (inline busy-timer logging) |
| `@state.change("fespp_data_selectors")` | `on_change_fespp_data_selectors` | `data_load.run(...)` |
| `@state.change("ui_scale_z")` | `ui_scale_z_update` | `slicer_dispatch.apply_z_scale` |
| `@state.change("marker_orientation")` | `marker_orientation_update` | `marker_dispatch.apply_marker_options` (via `_apply_marker_options`) |
| `@state.change("ui_loaded_array_paths")` | `_refresh_diff_choices` | `diff.refresh_diff_choices` |
| `@state.change("ui_loaded_rep_paths")` | `_sync_scene_registry_reps` | `scene_registry.sync_loaded_reps` + re-apply `slicer_dispatch.apply_z_scale` |
| `@state.change("diff_array_a_path","diff_array_choices")` | `_refresh_diff_b_choices` | `diff.refresh_diff_b_choices` |
| `@state.change("ui_active_array_by_rep")` | `_on_active_array_change` | `active_array.on_active_array_change` |
| `@state.change("ui_active_array_by_rep_by_view")` | `_on_active_array_by_view_change` | `active_array.on_active_array_by_view_change` (+ `_refresh_panel_mr_specs`) |
| `@state.change("ui_slices_i/j/k_list")` | `update_slice` | `slicer_dispatch.update_slice_positions` |
| `@state.change("ui_slices_range_i/j/k")` | `update_range_slicer` | `slicer_dispatch.update_slice_range` |
| `@state.change("ui_slices_range_mode")` | `update_mode_slicer` | `slicer_dispatch.update_slice_mode` |
| `@state.change("ui_slices_volume_visible")` | `update_volume_visible` | `slicer_dispatch.update_volume_visible` |
| `@state.change("ui_slices_i/j/k_visible_list")` | `update_slices_visibility` | `slicer_dispatch.update_slice_visibility` |
| `@state.change("active_representation_path","ui_active_node_reservoir_type_rep")` | `on_active_grid_change` | threshold UI + `_push_active_ijk_state_to_ui` + `slice_dispatch.publish_slice_state` + `clip_dispatch.publish_clip_state` + stats |
| `@state.change("ui_stats_pinned_paths", …, ui_slices_*)` (big union) | `_on_stats_inputs_change` | `_refresh_descriptive_stats` |
| `@state.change("fespp_active_panel_id")` | `_on_active_panel_change` | slice/clip publishers, threshold, IJK push, stats, drawer-target follow, `_sync_pvsimple_active_to_target` |
| `@state.change("drawer_target_view_pinned")` | `_on_drawer_target_pinned_change` | re-anchor follow target |
| `@state.change("drawer_target_view_id")` | `_on_drawer_target_view_change` | `_sync_pvsimple_active_to_target` + slice/clip/threshold/IJK republish |
| `@state.change("fespp_render_panels")` | `_on_render_panels_change` | auto-depin + follow re-anchor |
| `@state.change("ui_threshold_pending_action")` | `_on_threshold_pending_action` | `threshold_dispatch.on_threshold_pending_action` |
| `@state.change("representation_active")` | `_propagate_representation` | `slicer_dispatch.propagate_representation` |
| `@state.change("time_index")` | `changeTimeLabel` | `time_realization.change_time_label` + stats |
| `@state.change("ui_select_node_surface/well/reservoir")` | per-tab handlers | `selection_dispatch.on_change_ui_select_node_*` |
| `@state.change("load_mode")` | `on_load_mode_change` | `selection_dispatch.on_load_mode_change` |
| `@state.change("tree_hierarchy_mode")` | `on_tree_hierarchy_mode_change` | `hierarchy.on_tree_hierarchy_mode_change` |
| `@state.change("view_reset_camera")` | `view_reset_camera` | `view_ops.on_view_reset_camera` |
| `@state.change("view_update")` | `view_update` | `view_ops.on_view_update` |
| runtime `state.change(...)` (not decorator) | `_refresh_panel_mr_specs` / `_refresh_mr_derived` / `_refresh_global_selected` | `realization_dispatch.recompute_*` / `resolve_global_selected` |

Controller methods (`@controller.set` unless noted): `view_update_for(panel_id)`, `load_epc_file`, `connect_to_etp`, `select_etp_dataspace`, `force_etp_refresh`, `update_data_information`, `set_slider_value`, `get_rep_source`, `compute_diff`, `get_rep_chain_proxies`, `toggle_rep_visibility`, `toggle_dataarray_color`, `toggle_marker_visibility`, `apply_panel_coloring`, `toggle_stats_display`, `open_stats_panel`, `threshold_add`, `threshold_delete`, `threshold_set_range`, `threshold_set_visible`, `slice_set`, `clip_set`, `plane_edit_mode_set`, `copy_threshold_chain_from`, `copy_slice_from`, `copy_clip_from`, `copy_ijk_slicers_from`, `apply_pending_selection`, `register_per_view_time_label`. Plus `@controller.add("on_server_ready")` (upload-session id + upload route), `@controller.add("on_data_change") → view_ops.broadcast_view_update`, and `controller.apply_marker_options` set as a plain attribute.

Server triggers (`@server.trigger`, the path Vue templates resolve — controller-set methods are Python-only): `stats_set_original_real_idx`, `stats_set_original_ts_idx`, `stats_pin_original`, `stats_unpin_original`, `stats_compare_toggle`, `stats_compare_clear`, `open_compare_stats`, `open_row_histogram`, `open_compare_distributions`, `toggle_stats_display` (separate from the controller-set one — see gotcha), `set_view_realization`, `set_global_realization`.

**State.** Reads/writes a very large set. Notable direct writes in `boot`: `file_loaded` (`load_epc_file`), `view_update` / `view_reset_camera` / `has_data_loaded_once` (via load + handlers), `ui_scale_z` / `marker_orientation` / `marker_size` (seeded with `setdefault`), `fespp_stats_panel_id` consumers, `ui_distribution_contexts`, `ui_stats_compare_panel`, `ui_stats_compare_dist_panel`, and all the dynamic per-panel `ui_distribution_*_<panel_id>` / `ui_stats_compare_*_<panel_id>` vars. `drawer_target_view_id` / `drawer_target_view_pinned` are read and written across the panel-follow handlers.

**Collaborators.** Imports nearly every dispatch module (`threshold_dispatch`, `slicer_dispatch`, `marker_dispatch`, `slice_dispatch`, `clip_dispatch`, `time_realization`, `realization_dispatch`, `data_load`, `etp`, `visibility`, `active_array`, `diff`, `hierarchy`, `selection_dispatch`, `view_ops`, `stats_dispatch`, `distribution_dispatch`, `compare_matrix`, `panel_resolver`, `source_resolver`), plus `Tree`, `Collector`, `ETPConnector`, `SourceRegistry`, `SceneRegistry`, `Selector`, `Activator`, session/upload IO hooks, `vtk_log`. Both registries are published on `server.context.source_registry` / `server.context.scene_registry`. Called by the app bootstrap (whoever calls `initialize_fespp_engine`); the `multi_view` it talks to lives on `server.context.multi_view`.

**Gotchas.**
- **Circular-import dance:** `_tree` is mirrored onto the `engine` package object (`import ... as _engine_pkg; _engine_pkg._tree = _tree`) *inside* the function so `app/ui/app_layout.py` and the `source_resolver` helpers can reach the tree without a module-load-time circular import.
- **`ExplicitSelection` mode** is force-set on the collector proxy so selecting a grid does NOT auto-load its properties (pairs with `select_strategy="independent"` in the VTreeview).
- **No-op statement bug-smell:** `controller.view_replace` on its own line in `data_load.run`'s caller path — actually `data_load` has `controller.view_replace` as a bare expression (line 240), it does nothing. (Mentioned here because boot wires the controller; see `data_load` gotchas.)
- **Two `toggle_stats_display` callables** by design: the `@controller.set` one (tree chart icon path) and the `@server.trigger` one (panel × buttons) — the trigger body just calls the controller method so both share the auto-open-stats side effect; kept separate to avoid silent-override gotchas of re-decorating.
- **The legacy slicer lockstep mirror is deliberately REMOVED** (see the long comment ~lines 461-475): under per-view scenes, re-publishing stale legacy slicer state onto every per-view would clobber per-view divergence. `SceneRegistry.mirror_legacy_ijk_state` survives only for one-shot snapshot/apply.
- **`_on_active_panel_change` restores `pvsimple` active view in pinned mode** because `multi_view._on_view_activated` calls `SetActiveView(active_panel.pv_view)`, which clobbers the drawer target.
- **`marker_size` slider applies on RELEASE only** (`@end` → `controller.apply_marker_options`); only `marker_orientation` (a toggle) applies on change. Each apply re-runs the collector over the whole selection, so per-step would be laggy.
- The file is ~1690 lines; most logic lives in the inner closures rather than the handlers.

---

### `fespp_on_trame/app/core/engine/state_defaults.py`

**Responsibility.** Seed (via `state.setdefault`) every Trame state variable the engine and UI assume to exist, in one declarative place so `boot.py` stays focused on lifecycle. Grouped roughly by data-flow stage (selection → loaded → visible → coloured → threshold → diff → stats).

**Key classes / functions.**
- `init_state_defaults(state) -> None` — called once near the start of `initialize_fespp_engine`. Pure sequence of `state.setdefault(name, default)` calls. It is the **authoritative catalogue of state-var shapes** — the inline comments document the exact dict/list structure of every non-trivial var (read this file to learn the data model). Key buckets and their documented shapes:
  - Selection: `ui_select_node_reservoir/surface/well` (lists), `fespp_data_selectors` (list).
  - Visibility: `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view` (`{panel_id: [rep_path,...]}`).
  - Coloring: `ui_loaded_array_paths`, `ui_active_array_by_rep` (`{rep_path: array_path}`, mirror of active panel), `ui_active_array_by_rep_by_view` (`{panel_id: {rep_path: array_path}}`, source of truth), `ui_loaded_marker_paths`, `ui_visible_marker_paths_by_view`, `panel_has_ts_by_id`.
  - Realizations: `ui_active_realization_by_array_by_view` (`{panel_id: {array_path: idx}}`), `ui_panel_active_mr_specs_by_id`, `panel_has_mr_by_id`, `ui_global_mr_specs`, `ui_global_mr_selected_path`, `ui_global_mr_selected_spec`.
  - Diff / ETP / view-status / VTK-log / upload-progress blocks.
  - Slice plane (`ui_slice_enabled/axis/offset/bounds` + server-resolved `ui_slice_offset_min/max/step`), Clip plane (parallel `ui_clip_*` incl. `ui_clip_inside_out`), `ui_plane_edit_mode` (`"slice"|"clip"|None`).
  - IJK slicer (`ui_range_i/j/k`, `ui_slices_*_list`, `ui_slices_range_*`, `ui_slices_*_visible_list`, `ui_threshold_chain`, etc.).
  - Descriptive stats (Brique B): `ui_stats_pinned_paths`, `ui_stats_panel_state`, `ui_stats_tables`, `ui_stats_publish_version`, `ui_per_view_time_pulse`, `ui_stats_compare`, `ui_stats_compare_panel`, `ui_stats_compare_dist_panel`, `ui_stats_compare_items`.
  - Drawer target: `drawer_target_view_id` (`""`), `drawer_target_view_pinned` (`False`).
  - Panel ids / overlay flags: `fespp_stats_panel_id`, `ui_stats_panel_minimized`, `ui_stats_panel_maximized`, `ui_distribution_contexts`, `ui_slicers_tab` (`"ijk"`).
  - Misc: `ui_scale_z` (`1.0`), `load_mode` (`"auto"`).

**State.** Writes (defaults-only) every var listed above. Reads none.

**Collaborators.** No imports. Called exactly once by `boot.initialize_fespp_engine`. Every other engine module assumes these defaults are present.

**Gotchas.**
- Uses `state.setdefault` not `state[...] = ` — re-running it (or a later `setdefault` in boot, e.g. `state.setdefault("ui_scale_z", 1.0)` which appears redundantly in boot) won't clobber a value already set.
- The flat vars (`ui_active_array_by_rep`, `ui_hidden_rep_paths`) are documented here as **mirrors of the active panel's per-view bucket**, not independent state — do not write them as if they're authoritative.
- `ui_descriptive_stats` (`[]`) is legacy Brique-A and kept only so the revert path compiles; Brique B uses `ui_stats_tables`.
- `ui_stats_publish_version` and `ui_per_view_time_pulse` are **monotonic counters used as Vue `:key` tie-breakers / change pulses**, not real data — they exist to force re-renders (stats table) and to funnel dynamic `time_value_<panel_id>` changes into the static `@state.change` declaration.
- `ui_stats_compare_visible_metrics_<panel_id>` (seeded in boot, not here) inverts the old `hidden_metrics` semantics — see boot's `_open_compare_stats`.

---

### `fespp_on_trame/app/core/engine/data_load.py`

**Responsibility.** The load-time pipeline driver. `run(...)` fires on every `fespp_data_selectors` change and performs the full sequence: push selectors to the active source, hide the parent multiblock, reserve chip colors, sync the registries, bump pipeline info, notify the activator, maintain all visibility/array/marker/active-array tracking state, refresh threshold + IJK UI, and do a single final Render. The order of operations is load-bearing and heavily commented.

**Key classes / functions.**
- `run(state, controller, server, view, tree, collector, etp_connector, source_registry, activator, refresh_threshold_ui, push_active_ijk_state)` — the driver. Steps, in order: (1) pick `active_source = etp_connector if etp_connector.is_connected else collector`; (2) `SetPropertyWithName('Selectors', ...)` + a single `UpdatePipeline()` + `show()` (the C++ `ClearSelectors`/`AddSelector` are Modified()-only, so one explicit RequestData here materialises the multiblock once); (3) hide the parent rep (`Assembly='Assembly'`, `BlockSelectors=['/data']`, `Visibility=0`) BEFORE any render to avoid O(N) per-block painting; (4) reserve a `color_for_index` chip color per newly-loaded rep into `solid_color_by_rep` (cached via `_selector_rep_cache`), BEFORE `sync` so new sources tint immediately; (5) `source_registry.sync(selectors, ui_select_node_reservoir)` + `ijk.update_block_visibility()` per grid; (6) `Modified()` + `UpdatePipelineInformation()` on every source, plus full `UpdatePipeline()` on IjkGrid `_src_extract_init` and its slicers/volume; (7) `activator.notify_active_reps(present_paths)`; (8) the four tracking helpers below; (9) **synchronous eager teardown** of deselected reps' per-view pipelines via `scene_reg.all_scenes()` → `scene.remove_rep`; (10) `SetActiveSource` + `on_data_loaded` / `on_active_proxy_change`; (11) camera reset on first load; (12) `activator.refresh_active()`, then **re-apply the grid's active colouring when blocked wellbores appeared in this run** — a wellbore checked while its grid already colours by a property would otherwise arrive SolidColor (the active-array map didn't change, so nothing else re-applies; threads the active panel's MR realization index, without which an MR property resolves to nothing); (13) `refresh_threshold_ui()`, `push_active_ijk_state()`; (14) final `pvsimple.Render(view=view)` only when selection is non-empty. Note the loading path **never re-opens a hidden rep's eye** (the old "select a property = load + eye" force-unhide is gone — visibility and colouring are orthogonal).
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

### `fespp_on_trame/app/core/engine/selection_dispatch.py`

**Responsibility.** Translate the treeview's per-tab checkbox arrays into pipeline loads, honoring the `auto` vs `manual` load mode.

**Key classes / functions.**
- `on_change_ui_select_node_surface(state, selector)` / `on_change_ui_select_node_well(state, selector)` / `on_change_ui_select_node_reservoir(state, selector)` — per-tab change handlers; in `auto` mode each immediately calls the corresponding `selector.select_node_*()`. No-op in `manual` mode (toggles only stage state).
- `apply_pending_selection(selector, activator)` — toolbar Load button entry point (manual mode). Pushes all three tabs (`select_node_reservoir/surface/well`) then calls `activator.refresh_active()`. The refresh is needed because in manual mode the active-node change happened at checkbox time (before the rep existed, so the activator short-circuited); calling state vars directly would be coalesced into a no-op by Trame's flush batching.
- `on_load_mode_change(selector, activator, load_mode)` — when switching back to `auto`, flush any staged manual selection via `apply_pending_selection`.

**State.** Reads `state.load_mode` (and indirectly the per-tab arrays through the `selector`). Writes none directly.

**Collaborators.** No imports. Operates entirely through the passed `Selector` and `Activator`. Called by boot's per-tab `@state.change` handlers, `@controller.set("apply_pending_selection")`, and `@state.change("load_mode")`.

**Gotchas.**
- The `selector is not None` guards exist because boot constructs the `Selector` before the tree is fully populated in some paths; defensive.
- `manual` mode is the only path where `apply_pending_selection` matters — in `auto`, the per-tab handlers already pushed on every toggle, so the Load button is redundant.

---

### `fespp_on_trame/app/core/engine/hierarchy.py`

**Responsibility.** Push the FESPP collector's tree-hierarchy mode (flat / by_interpretation / by_feature_and_interpretation) to the C++ side, which triggers a live assembly rebuild, and reset all engine tracking state because the rebuild invalidates every node id / path.

**Key classes / functions.**
- Module constant `_MODE_NAME_TO_INT = {"flat": 0, "by_interpretation": 1, "by_feature_and_interpretation": 2}`.
- `push_tree_hierarchy_mode(collector, mode_name) -> bool` — sets the collector proxy's `TreeHierarchyMode` property via `vtkSMPropertyHelper` + `UpdateVTKObjects()` (which triggers `repository.rebuildAssembly()` C++-side). Returns False if the property is absent or on exception. Also called once at boot to seed the initial mode.
- `on_tree_hierarchy_mode_change(state, controller, collector, tree_hierarchy_mode)` — pushes the new mode, then (if push succeeded) clears every selection / visibility / coloring / marker state var, sets `tree_hierarchy_snackbar_visible` if there was a prior selection, and — when `state.file_loaded` — calls `collector.get_source().UpdatePipeline()` (re-deep-copies the rebuilt assembly into the output) followed by `controller.update_data_information()` to re-parse the Python `Tree`.

**State.** Reads `ui_select_node_reservoir/surface/well`, `fespp_data_selectors`, `file_loaded`. Writes (clears): `ui_select_node_reservoir/surface/well`, `ui_active_node_reservoir/surface/well`, `fespp_data_selectors`, `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_hidden_rep_paths_by_view`, `ui_loaded_array_paths`, `ui_active_array_by_rep`, `ui_active_array_by_rep_by_view`, `ui_loaded_marker_paths`, `ui_visible_marker_paths_by_view`, and conditionally `tree_hierarchy_snackbar_visible`.

**Collaborators.** Imports `vtkSMPropertyHelper`. `push_tree_hierarchy_mode` is called both at boot (initial seed) and from `on_tree_hierarchy_mode_change`. The latter is wired to `@state.change("tree_hierarchy_mode")` and calls `controller.update_data_information` (which is itself a boot-registered controller method routing through `etp.update_data_information`).

**Gotchas.**
- ParaView is **not** in auto-apply mode here, so the proxy output keeps the previous assembly's deep copy until `RequestData` runs again — hence the explicit `UpdatePipeline()` before refreshing the tree. Omitting it leaves the Python tree parser reading the stale layout.
- It clears `ui_active_node_reservoir/surface/well` even though those aren't seeded in `state_defaults.py` — they're created by the active-node machinery elsewhere; the clear is unconditional.
- A mode switch is a hard reset: all loaded reps disappear and the user must re-select. The snackbar warns them when they had a selection.

---

### `fespp_on_trame/app/core/engine/visibility.py`

**Responsibility.** Handle tree eye-icon clicks on a representation node and on a wellbore-marker leaf. Both are plain show/hide: **this module never touches colouring** (that is `active_array.toggle_dataarray_color`'s job).

**Key classes / functions.**
- `toggle_rep_visibility(state, controller, server, source_registry, rep_path, panel_id=None, tree=None)` — the rep eye handler. Resolves `(view, html_view)` and `bucket_key` (panel_id, else active panel, else `"_active"`), flips the rep in `ui_hidden_rep_paths_by_view[bucket_key]`, mirrors to the legacy global `ui_hidden_rep_paths` iff active panel, resolves sources via `source_resolver.sources_for_rep_path`, and Shows/Hides them. On show: for an IjkGrid it calls `ijk.show(view=view)` (the per-mode logic is intricate); for an ExtractBlock rep it re-asserts `Representation` (`state.representation_active`) and `_apply_default_tint(d, grid_color)` on each source's display because non-original panels start with PV defaults. Finally renders + pushes the html_view (or `controller.view_update()`).
- `toggle_marker_visibility(state, controller, server, source_registry, tree, marker_path, panel_id=None)` — wellbore-marker eye. Markers display multiple at a time; each renders via its OWN per-`(rep, view)` `EnergisticsExtractor`. Resolves the rep path from the marker leaf, flips `marker_path` in `ui_visible_marker_paths_by_view[bucket_key]`, and calls `rep_in_scene.set_marker_visible(marker_path, new_visible)` on the `RepInScene` (`source_resolver._scene_rep_for_view`). Visibility-only — markers carry no color array.

**State.** Reads/writes `ui_hidden_rep_paths_by_view`, `ui_hidden_rep_paths`, `ui_visible_marker_paths_by_view`. Reads `representation_active`, `solid_color_by_rep`. It no longer touches `ui_active_array_by_rep_by_view` at all.

**Collaborators.** Imports `panel_resolver`, `source_resolver`, and `_apply_default_tint` from `sources.representation`. Calls `IjkGrid.show`, `RepInScene.set_marker_visible`, `pvsimple.Show/Hide/GetDisplayProperties`. Wired to `@controller.set("toggle_rep_visibility")` and `@controller.set("toggle_marker_visibility")`.

**Gotchas.**
- **Visibility and colouring are ORTHOGONAL — keep them that way.** This eye was once a 3-state chip: its first click "gave up the colouring" (→ SolidColor) via a `_clear_active_array` helper, and only hid on the second, with an `is_frame` exemption so wellbore frames (no own geometry) could escape the intermediate. Hiding a rep therefore always DESTROYED its active array, which made "hide the grid, keep its blocked wellbores coloured by PORO" unexpressible. Both the helper and the frame special case are gone — once the general rule is correct, the exception has no reason to exist. **Symmetrically**, `active_array.toggle_dataarray_color` must never implicitly un-hide/Show a rep: it used to, and it replayed the show on the LEGACY `eb.source` while this hide path targets `sources_for_rep_path` — the two disagreed, so a rep re-shown from there escaped the next hide and lingered on screen in SolidColor.
- The legacy global `ui_hidden_rep_paths` is only updated when `bucket_key` equals the active panel — it is a mirror, not authoritative.
- Hide path flips Visibility on EVERY source of the rep (slicers, volume crop, rep_data extractor) so the panel goes dark regardless of which one was rendering; show path delegates IjkGrid mode-selection to `ijk.show()`.
- When no `html_view` (legacy single-view / unknown panel), it falls back to `controller.view_update()`.

---

### `fespp_on_trame/app/core/engine/active_array.py`

**Responsibility.** Drive ColorBy from the per-rep / per-view active-array maps, handle the tree data-array eye toggle, derive the per-panel TimeSeries flag, and (re)apply panel coloring after a view is replicated. This is where scalar coloring actually gets applied to PV displays.

**Key classes / functions.**
- `on_active_array_change(state, controller, source_registry, tree, ui_active_array_by_rep, server=None)` — fires on global-map mutation. For each loaded rep, reads its active array, looks up the MR realization from the active panel's `ui_active_realization_by_array_by_view` bucket (only when `server` is provided), shows wellbore channels exclusively via `_show_channel_active_view`, applies `source_resolver.apply_color_array`, re-hides displays of reps in `ui_hidden_rep_paths`, and re-asserts slice/clip via each scene's `rep_in_scene.refresh_planes_after_property_change()`.
- `on_active_array_by_view_change(state, tree, ui_active_array_by_rep_by_view)` — derives `panel_has_ts_by_id` (a panel has TS iff any active array resolves to a `TimeSeries` / `MultiRealizationTimeSeries` node or a descendant of one). Idempotent.
- `toggle_dataarray_color(state, controller, server, source_registry, tree, array_path, panel_id=None)` — the data-array eye click. Resolves the rep path; toggles `array_path` in `ui_active_array_by_rep_by_view[bucket_key][r_path]` (clicking the active array deactivates → SolidColor; clicking another activates it, evicting the previous). Mirrors to the global map iff active panel. Handles MR realization bookkeeping (clear the dropped MR's slot, seed the new MR's default index). Never touches the rep's visibility (the old implicit "show + color" un-hide is gone — visibility and colouring are orthogonal, and colouring a hidden rep is a legal, useful state). For wellbore channels, re-points the frame's per-view extractor via `rep_in_scene.set_channel_visible(...)` BEFORE coloring, and publishes the viewed channel into the COE state vars (`active_color_array_name/path`, `active_property_kind`, `active_representation_path`) + `controller.update_color_editor`. Applies ColorBy via `apply_color_array(..., clear_on_empty=True)`; on a resolve-to-nothing result it raises the prominent `empty_color_snackbar_*` warning AND rolls the activation back (pops the rep from both active-array maps, releases any MR slot, resets channel COE vars) so the eye returns to SolidColor instead of staying lit on an empty property; on deactivation sweeps stale bars.
- `apply_panel_coloring(state, source_registry, tree, panel_id, view)` — re-applies ColorBy on every rep coloured in `ui_active_array_by_rep_by_view[panel_id]` for a freshly-replicated view, and explicitly turns on one scalar bar per array (per-view scoped LUT, so each realization keeps its own bar).
- `_is_channel_rep(element_type_obj) -> bool` — true when the rep's visibility policy is `ONE_AT_A_TIME` (single source of truth via `element_type`, replacing `kind == 'Frame'`).
- `_show_channel_active_view(tree, rep_path, array_path, view)` — exclusively shows a channel in `view` via its `RepInScene` (no-op otherwise).

**State.** Reads `ui_loaded_rep_paths`, `ui_hidden_rep_paths`, `ui_active_realization_by_array_by_view`, `ui_active_array_by_rep_by_view`, `ui_active_array_by_rep`, `ui_hidden_rep_paths_by_view`. Writes `ui_active_array_by_rep_by_view`, `ui_active_array_by_rep`, `ui_hidden_rep_paths_by_view`, `ui_hidden_rep_paths`, `panel_has_ts_by_id`, and the COE/snackbar vars (`active_color_array_name`, `active_color_array_path`, `active_property_kind`, `active_representation_path`, `empty_color_snackbar_text`, `empty_color_snackbar_visible`). Realization writes go through `realization_dispatch`.

**Collaborators.** Imports `panel_resolver`, `source_resolver`, `realization_dispatch`, `element_type`. Reads `server.context.scene_registry` (lazily via `get_server()`). Calls `apply_color_array`, `resolve_array_for_path`, `hide_unused_scalar_bars`, `RepInScene.set_channel_visible/refresh_planes_after_property_change`, `IjkGrid.show`, `ExtractBlock`. Wired to `@state.change("ui_active_array_by_rep")`, `@state.change("ui_active_array_by_rep_by_view")`, `@controller.set("toggle_dataarray_color")`, `@controller.set("apply_panel_coloring")`.

**Gotchas.**
- **`apply_panel_coloring` deliberately does NOT raw-write `bar.Visibility = 1`** — it relies on `apply_color_array`'s `display.SetScalarBarVisibility(view, True)` (via `vtkSMTransferFunctionManager`). Raw writes desync per-view LUT bookkeeping and surface duplicate bars on other views (bug seen when Stats/Distribution panels triggered `apply_panel_coloring`).
- **Channel ordering trap:** for a wellbore frame, the channel `set_channel_visible(...)` SHOW must happen before `apply_color_array` because `resolve_array_for_path` reads the channel's own extractor arrays; coloring first would miss them.
- The MR realization bucket interactions are subtle — `toggle_dataarray_color` clears the previous MR slot and seeds the new one's default index so the resolver can find a suffixed `<title>_real_<idx>` array.
- `on_active_array_change` skips the MR realization lookup entirely when `server is None` (falls back to the legacy unsuffixed array name).

---

### `fespp_on_trame/app/core/engine/source_resolver.py`

**Responsibility.** Free-function helpers (extracted from boot closures) that resolve a rep path to its rendered/colorable PV sources, displays, and VTK array names, and that apply ColorBy / SolidColor with the PV6 workarounds and per-view scoped LUTs. Each takes its dependencies explicitly — no module-level state.

**Key classes / functions.**
- `sources_for_rep_path(source_registry, rep_path, view=None) -> (sources, view)` — *rendered* source proxies for a rep. Per-view first: `RepInScene.element_type.rendered_sources(...)`. Falls back to the legacy shared IjkGrid (slicers + volume + rep_data, substituting the deepest visible threshold leaf) then ExtractBlock (deepest visible threshold or the source) then name-matched `rep<path>` sources.
- `color_sources_for_rep_path(source_registry, rep_path, view=None) -> (sources, view)` — like above but returns EVERY chain proxy (visible or not) plus the per-`(rep,view)` clip output (`_scene_clip_output_for_view`); slice's display is intentionally excluded (tinted red). Per-view first via `element_type.color_sources(...)`.
- `displays_for_rep_path(source_registry, rep_path, view=None) -> [display]` — `GetDisplayProperties` for every source from `color_sources_for_rep_path`.
- `resolve_array_for_path(source_registry, tree, rep_path, array_path, realization_idx=None, view=None) -> (assoc, vtk_array_name)` — resolves the VTK array name. Consults the per-view source first (channel's own extractor for frames via `element_type.array_candidate_source(...)`), tries the MR-suffixed name `<sanitized_title>_real_<idx>` when `realization_idx` is set, then falls back to raw title / `make_valid_vtk_name(title)`. Returns `(None, None)` on miss.
- `apply_color_array(source_registry, tree, rep_path, array_path, view=None, realization_idx=None, clear_on_empty=False) -> bool` — the workhorse. Clears to SolidColor when `array_path` falsy; otherwise resolves the array, ColorBy's each display, swaps to per-view scoped TFs (`swap_to_scene_tfs`), force-rescales the LUT from the fresh client-side array range (`_vtk_array_range_from_clientside`), shows the scalar bar via `SetScalarBarVisibility`, and sweeps orphan bars. Returns `False` when `array_path` resolves to nothing (caller surfaces a "no data" alert); `clear_on_empty=True` (eye toggles only) additionally clears the stale ColorBy.
- `blocked_wellbore_rep_paths_for(tree, rep_path) -> [path]` — the BlockedWellbore rep paths grouped under the same GridContainer as a grid geometry rep (empty for non-grids).
- `_mirror_color_to_blocked_wellbores(source_registry, tree, rep_path, assoc, name, view)` — FESPP mirrors a grid's CELL arrays onto its blocked wellbores (same names, restricted to the crossed cells); this mirrors the **ColorBy** too, so the wells follow the grid's active property — including while the grid is hidden. Hooked into `apply_color_array` on all three outcomes (apply / deselect-clear / empty-clear), BEFORE the orphan-bar sweep: the wellbore displays reference the same scoped LUT, which is what keeps the shared colour bar alive when the grid itself is hidden. Skips unchecked wellbores (no displays → no load).
- `hide_unused_scalar_bars(view=None)` — `vtkSMTransferFunctionManager.UpdateScalarBars(view.SMProxy, 1)` sweep.
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

### `fespp_on_trame/app/core/engine/panel_resolver.py`

**Responsibility.** Tiny per-panel resolution helpers shared by `visibility` and `active_array` dispatch: translate a panel id into the right PV view / HTML view, with a legacy active-view fallback.

**Key classes / functions.**
- `resolve_view_and_html_view(server, panel_id) -> (pv_view, html_view)` — asks `server.context.multi_view.get_pv_view(panel_id)` / `get_html_view(panel_id)`. Returns `(pvsimple.GetActiveView(), None)` when `panel_id` is empty/unknown or no multi_view is mounted; if only the pv_view lookup misses, falls back to the active view but keeps any html_view.
- `active_panel_id(server) -> str | None` — `multi_view._active_panel_id` (the focused render panel), or None when no multi-view is mounted yet.

**State.** None.

**Collaborators.** Imports `pvsimple`. Reads `server.context.multi_view`. Called by `visibility.py`, `active_array.py`, boot's `set_view_realization` trigger.

**Gotchas.**
- `active_panel_id` reaches into a **private attribute** `multi_view._active_panel_id` — coupling to the multi_view's internals. A forker changing the multi_view must keep that attribute.
- The `(active_view, None)` fallback is what keeps every legacy single-view code path alive when callers don't supply a `panel_id`; the `html_view` being None is the signal downstream to fall back to `controller.view_update()`.

---

### `fespp_on_trame/app/core/engine/view_ops.py`

**Responsibility.** Re-arm the `view_reset_camera` / `view_update` sentinel state vars after firing, and broadcast a refresh to every panel on data change.

**Key classes / functions.**
- `on_view_reset_camera(state, controller, source_registry, value)` — no-op unless `value is True`; refreshes per-block visibility on every loaded IjkGrid (`ijk.update_block_visibility()`), calls `controller.view_reset_camera()` + `controller.view_update()`, then resets `state.view_reset_camera = False` and `state.flush()`.
- `on_view_update(state, controller, value)` — no-op unless `value is True`; calls `controller.view_update()`, resets `state.view_update = False`, `state.flush()`.
- `broadcast_view_update(server)` — the `@controller.add('on_data_change')` callback; calls `controller.view_update_all()` (refresh every panel) when present, else falls back to `controller.view_update()`.

**State.** Reads/writes `view_reset_camera` and `view_update` (re-arms them to `False`).

**Collaborators.** No imports. Calls `controller.view_reset_camera/view_update/view_update_all`, `source_registry.ijk_grids() → ijk.update_block_visibility()`. Wired to `@state.change("view_reset_camera")`, `@state.change("view_update")`, `@controller.add("on_data_change")`.

**Gotchas.**
- The sentinel re-arm pattern (`= False` + `state.flush()`) exists because Trame collapses identical writes into no-ops; without re-arming, a second `view_update = True` request after a previous one would never fire.
- Camera reset specifically also refreshes IjkGrid per-block visibility because block visibility is a slicer-side concept the PV camera reset alone wouldn't account for.
- `on_*` use the explicit `value != True` / `value is True` comparison (not just truthiness) — a stray truthy non-`True` value won't trigger the handler.
