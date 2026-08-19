# Engine — Feature Dispatchers

## Overview

The `fespp_on_trame/app/core/engine/*_dispatch.py` modules (plus a few non-`_dispatch` siblings: `time_realization.py`, `compare_matrix.py`, `diff.py`, `etp.py`, `vtk_log.py`) are the **logic layer extracted out of `boot.initialize_fespp_engine`**. The pattern is uniform and important to internalize before forking: every function here is a **free function that receives all of its dependencies explicitly** (`state`, `controller`, `scene_registry`, `source_registry`, `view`, `tree`, …). `boot.py` registers thin `@state.change` / `@controller.set` closure wrappers that capture those deps from the engine-init scope and forward into these functions. Consequently, none of these modules import the engine wiring; they are oblivious to how they are invoked. When forking, expect to trace any handler back to a closure in `boot.py` to discover its real call site.

A second cross-cutting theme is the **legacy-vs-per-view duality** introduced across "Phases" (Phase 2 = single shared pipeline; Phase 3a/3b = per-`(rep, view)` pipelines owned by a `SceneRegistry`). Most slicer/slice/clip/threshold dispatchers first try to route an edit through `scene_registry.get_rep(view_id, rep_path)` (a `RepInScene`, which may delegate to a per-view `IjkGrid`), and only fall back to the shared `source_registry` when the scene registry isn't ready (early boot) or the rep hasn't been synced yet. The "target view" for an edit is resolved via a consistent precedence: `state.drawer_target_view_id` (the Attributes-drawer picker, "Brique A") → `state.fespp_active_panel_id` (active focus) → first known scene. Renders are pushed to the browser via `controller.view_update_for(panel_id)` (specific panel, pinned-mode safe) and `controller.view_update()` (legacy active panel) — usually both, because the cost of a no-op push is negligible.

> **⚠️ Refactor update (`refactoring` branch).** That target-view precedence, the `(panel, active rep)` lookup, the panel pv_view resolution, and the render + dual-push were previously copy-pasted across `slicer` / `slice` / `clip` / `threshold` dispatch. They now live in **`engine/view_routing.py`** (`target_panel_id(state, scene_registry=None)` — 3-tier with a registry, 2-tier without; `resolve_rep`; `scene_pv_view`; `render_and_push` / `push_to_clients`). The four dispatchers delegate, keeping only their own pv_view nuance — so the per-file descriptions below that re-explain this resolution reflect the pre-refactor copies. The stats/distribution/compare cluster (`stats_dispatch`, `distribution_dispatch`, `compare_matrix`) is property-driven ("Brique B") rather than view-driven, and builds transient PV filter chains that must snapshot/restore the PV active source + active view so the main render path never sees a transient proxy.

---

### `fespp_on_trame/app/core/engine/slicer_dispatch.py`

**Responsibility.** Dispatch for IjkGrid slicer/range/volume editing and two global fan-outs: `apply_z_scale` (vertical exaggeration broadcast to every rendered proxy) and `apply_representation_type` (Surface/Wireframe/Points, strictly PER-REP — writes only the active rep's displays in the drawer-target view, remembered in `ui_rep_type_by_rep`; every default-Representation site reads `representation.rep_type_for(state, rep_path)`). Extracted from `boot.initialize_fespp_engine`.

**Key classes / functions.**
- `_target_panel_id(state)` — returns `state.drawer_target_view_id or state.fespp_active_panel_id` (drawer picker first, active panel fallback).
- `_target_pv_view(state, fallback_view)` — resolves the `pv_view` of the target panel via `get_server().context.scene_registry.get_scene(target).pv_view`, falling back to the engine-captured legacy `_view`.
- `_active_ijk_grid(state, source_registry)` — resolves the active `IjkGrid` for the target panel. **Prefers** the per-view IjkGrid (`rep._per_view_ijk`, building it on demand via `rep._ensure_per_view_ijk()`); **falls back** to `source_registry.get_ijk_grid(rep_path)` when the scene registry isn't reachable, the `RepInScene` doesn't exist, or no per-view IjkGrid is built yet. Reads `state.active_representation_path`.
- `_render_and_push(state, controller, fallback_view)` — renders the target panel's `pv_view`, then dual-pushes via `view_update_for(panel_id)` + `view_update()` to cover both follow and pinned modes.
- `set_slider_value(state, index, value)` — value-only entry for the slice slider widgets; writes `value` into element `[0]` of `ui_slices_{index}_list` (index is `'i'`/`'j'`/`'k'`). Coerces to `int`; silently returns on bad input.
- `update_slice_positions(state, controller, source_registry, view, i_list, j_list, k_list)` — first **syncs per-axis visibility lists** (`ui_slices_{axis}_visible_list`) to the length of each slice list (new slicers default `True`, extras popped), then calls `active.apply_slice_positions(...)` + `active.show()` and renders.
- `update_volumes(...)` — calls `active.apply_volumes(volumes, visible_list)` (syncs crop count + per-volume ranges + eyes; re-fires the active-array ColorBy when a volume was added).
- `update_slice_mode(...)` — calls `active.apply_mode(mode or 'slice')`; the `slice`↔`range` flip re-attaches the IjkGrid threshold chain (rep_data + volume in range; rep_data + per-axis slicers in slice).
- `update_slice_visibility(...)` — forwards to `apply_slice_visibility`.
- `_set_scale_preserving_color(disp, scale)` — **non-obvious, load-bearing helper.** Saves `disp.ColorArrayName` and `disp.LookupTable`, writes `disp.Scale = scale`, then restores both if the write clobbered them (observed on some PV builds; same guard the TransformationEditor uses). All reads/writes are individually wrapped in `try/except`.
- **`apply_z_scale(state, controller, source_registry, view, zscale)`** — the central function (see Gotchas for the precise sequence). Coerces `zscale` to float (default `1.0`). Calls `source_registry.apply_z_scale(zs)` (legacy ExtractBlocks) **first**, then fans out per-scene.
- `_collect_scene_proxies(scene)` — per-`(rep, view)` proxies that may have a visible display: the rep's `_extractor`, channel (log-tube) extractors from `rep._channel_extractors` (real geometry → scaled), `rep._chain[*].proxy`, `rep._slice_plane._proxy`, `rep._clip_plane._proxy`, and the per-view IjkGrid pipeline (`ijk.source`, `_src_extract_init`, `_src_volumes`, `_all_slice_sources()`, `all_threshold_sources()`). **Deliberately excludes marker extractors** (they are translated, not scaled).
- `_collect_legacy_proxies(source_registry)` — shared fallback proxies: `all_sources()`, all thresholds, and each IjkGrid's `_src_extract_init`/`_src_volumes`/slice sources/threshold sources.
- `apply_representation_type(state, controller, source_registry, rep_path, rep_type)` — sets `Representation` on ONE rep's displays (`displays_for_rep_path`, drawer-target view), renders, `_push_all_panels`. The old broadcast across every proxy made one rep's toggle restyle the whole scene. Boot pairs it with a `ui_rep_type_by_rep` store + a guarded re-seed of `representation_active` on active-rep switch.
- `_push_all_panels(controller)` — prefers `controller.view_update_all()` (multi-view aware), falls back to `controller.view_update()`.

**State.** Writes `ui_slices_{i,j,k}_list` (via `set_slider_value`) and `ui_slices_{i,j,k}_visible_list` (via `update_slice_positions`). Reads `state.active_representation_path`, `state.drawer_target_view_id`, `state.fespp_active_panel_id`.

**Collaborators.** `paraview.simple` (`Render`, `GetRepresentation`); `trame.app.get_server().context.scene_registry`; `marker_dispatch.is_marker_proxy` / `apply_marker_z`; the `IjkGrid` / `RepInScene` / `Scene` APIs (`apply_slice_positions`, `apply_volumes`, `apply_mode`, `apply_slice_visibility`, `show`, `reps()`, `pv_view`, `_marker_extractors`). Entry points are `@state.change`/`@controller.set` closures in `boot.py`.

**Gotchas.**
- **`apply_z_scale` precise behavior.** (1) Coerce `zs`. (2) `source_registry.apply_z_scale(zs)` updates the legacy ExtractBlocks. (3) If any scenes exist, iterate them: for each scene's `pv_view`, iterate `_collect_scene_proxies(scene) + legacy` and, per proxy, get its display and branch — **markers translate, everything else scales** via `_set_scale_preserving_color(disp, [1.0, 1.0, zs])`. The marker test is `marker_dispatch.is_marker_proxy(p)` (name-based, see below), so it works even when the scene registry didn't track the extractor. (4) **Then** a *second*, redundant marker pass iterates `scene.reps()` → `rep._marker_extractors.values()` and calls `apply_marker_z` directly — a belt-and-braces guarantee that symbolic markers translate even if the name check missed them in step 3. (5) `Render` each view; `_push_all_panels`; `return`. The **legacy fallback** (no scenes) scales only IjkGrid slice sources + `_src_volumes` and calls `_render_and_push`.
- The whole point of the per-scene fan-out is that the **visible** displays live on the per-`(rep, view)` proxies, NOT the legacy shared sources — without it a z-scale change never reaches the rendered objects.
- Markers must **translate Z** by `(zs-1)*z_center`, not scale, or a high z-scale turns a sphere into an "olive" ellipsoid. Channel (log-tube) extractors are real geometry and DO scale.
- `_set_scale_preserving_color` exists because writing `Scale` can reset the active coloring on some PV builds.
- `apply_z_scale` needs `state` (for `_render_and_push` target resolution); the docstring warns pre-Brique-A callers without `state` must update their call sites.

---

### `fespp_on_trame/app/core/engine/slice_dispatch.py`

**Responsibility.** Single axis-aligned slice plane per `(rep, view)`. Publishes the active rep's slice descriptor into `ui_slice_*` state and applies `(enabled, axis, offset)` patches to the owning `RepInScene`.

**Key classes / functions.**
- `_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}` — module constant mapping axis label to bounds index.
- `_resolve_active_panel_id(state, scene_registry)` — `drawer_target_view_id` → `fespp_active_panel_id` → `scene_registry.view_ids()[0]`.
- `_resolve_rep(state, scene_registry, panel_id)` — `scene_registry.get_rep(panel_id, state.active_representation_path)` or None.
- `publish_slice_state(state, scene_registry, panel_id=None)` — reads `rep.slice_state()` (or a default descriptor `{enabled:False, axis:"X", offset:0.0, bounds:[0,1,0,1,0,1]}`) and writes the seven `ui_slice_*` vars including a derived `ui_slice_offset_step = (hi-lo)/1000` (or `0.001`). **Idempotent.**
- `slice_set(state, controller, scene_registry, view, enabled=None, axis=None, offset=None, panel_id=None)` — applies `rep.slice_set(enabled=, axis=, offset=)`, republishes, renders the **owning** view (`scene.pv_view` preferred over the passed `view`), then dual-pushes `view_update_for(panel_id)` + `view_update()`. Calling with all three None is a pipeline no-op but still republishes — useful as a forced refresh on rep activation.

**State.** Writes `ui_slice_enabled`, `ui_slice_axis`, `ui_slice_offset`, `ui_slice_bounds`, `ui_slice_offset_min`, `ui_slice_offset_max`, `ui_slice_offset_step`. Reads `state.active_representation_path`, `state.drawer_target_view_id`, `state.fespp_active_panel_id`.

**Collaborators.** `paraview.simple.Render`; `scene_registry.get_rep` / `get_scene`; `RepInScene.slice_state()` / `slice_set()`; controller push methods. Entry points are boot.py closures.

**Gotchas.** Per Phase-1.b.1 the dispatcher routes through `scene_registry` so each `(rep, view)` has its own slice filter, but per-view UI state vars and the UI re-enable were deferred to Phase 1.b.2 — the panel still binds to the single flat `ui_slice_*` vars. The "active rep" is read from `state.active_representation_path` (same as legacy). Rendering prefers the slice's *owning* view, not whatever was globally active.

---

### `fespp_on_trame/app/core/engine/clip_dispatch.py`

**Responsibility.** Clip-plane analog of `slice_dispatch`, plus the shared "which filter the 3D plane widget binds to" toggle. Per-`(rep, view)` clip ownership via `scene_registry`.

**Key classes / functions.**
- `_AXIS_INDEX`, `_resolve_active_panel_id`, `_resolve_rep` — identical shape to `slice_dispatch`.
- `publish_clip_state(state, scene_registry, panel_id=None)` — reads `rep.clip_state()` and writes the `ui_clip_*` vars, including the extra `ui_clip_inside_out` (bool). Default descriptor adds `inside_out: False`.
- `clip_set(state, controller, scene_registry, view, enabled=None, axis=None, offset=None, inside_out=None, panel_id=None)` — applies `rep.clip_set(...)`, republishes, renders the owning view, dual-pushes.
- `set_edit_mode(state, controller, scene_registry, view, mode)` — validates `mode in (None, "slice", "clip")`, writes `state.ui_plane_edit_mode`, then **re-applies both filters** with no-state-change patches (`rep.slice_set()` and `rep.clip_set()`, both all-None) so the 3D widget is created/destroyed/rebound according to the new edit mode. Renders + dual-pushes.

**State.** Writes `ui_clip_enabled`, `ui_clip_axis`, `ui_clip_offset`, `ui_clip_inside_out`, `ui_clip_bounds`, `ui_clip_offset_min/max/step`, and `ui_plane_edit_mode`. Reads the same panel-resolution + `active_representation_path` vars.

**Collaborators.** Same as `slice_dispatch`, plus `RepInScene.clip_state()` / `clip_set()`. `set_edit_mode` relies on `slice_set()`/`clip_set()` re-evaluating widget gating inside `_apply`.

**Gotchas.** `set_edit_mode`'s mechanism is subtle: an **all-None** `slice_set()`/`clip_set()` still triggers `_apply`, which re-evaluates whether the rep should own the plane widget — that's how flipping `ui_plane_edit_mode` between "slice"/"clip"/None creates or tears down the interactive 3D widget. Both calls are wrapped in `try/except` so a failure on one filter doesn't block the other.

---

### `fespp_on_trame/app/core/engine/threshold_dispatch.py`

**Responsibility.** Threshold-chain dispatch routing both IjkGrid and non-IjkGrid (UnstructuredGrid) ops through `SceneRegistry` per `(view, rep)`. Publishes the active chain into `ui_threshold_chain` (depth-decorated + DFS-reordered) and forwards UI add/delete/set_range/set_visible events. Handles the multi-realization VTK-array-name resolution.

**Key classes / functions.**
- `_render_and_push(state, controller, fallback_view)` — local copy of the slicer helper (deliberately not imported from the sibling) resolving the target panel's `pv_view`.
- `_active_view_id(state)` — `drawer_target_view_id` → `fespp_active_panel_id`.
- `_find_property_path_by_title(tree, rep_path, array_title)` — walks the rep subtree for a property node whose (sanitized via `make_valid_vtk_name`) title or `propTitle` (for MR nodes) matches; returns the tree path. Recognizes node kinds containing `"Property"` plus `TimeSeries`/`MultiRealization`/`MultiRealizationTimeSeries`.
- `_resolve_vtk_array_name(state, tree, view_id, rep_path, array_title)` — **the MR-suffixing resolver.** Maps `state.active_color_array_name` (a property TITLE, e.g. `"VOIL"`) to the actual VTK array. For non-MR returns the sanitized title; for MR returns `<sanitized_title>_real_<idx>` where `idx` comes from `realization_dispatch.get_active_realization_for_view`. If MR but no realization picked yet, auto-picks `default_realization_for` AND persists it via `set_active_realization_for_view`. Falls back to the eye-binding's `ui_active_array_by_rep_by_view[view][rep]` array_path when the title walk misses.
- `threshold_provider(state, scene_registry, source_registry, view_id=None)` → `(provider, rep_path)`. For `rep_type in ("IjkGrid", "UnstructuredGrid")` prefers `scene_registry.get_rep(vid, grid_path)` (a `RepInScene`). If the scene **exists** but the rep isn't synced yet, returns `(None, None)` (publishes an empty chain silently, no legacy fallback, no `[DEPRECATED]` print). Otherwise falls back to `source_registry.get_ijk_grid` or `source_registry` itself.
- `hide_unused_scalar_bars()` — compat shim delegating to `source_resolver.hide_unused_scalar_bars`.
- `_is_per_view_provider(provider)` — `True` unless the provider has a `get_ijk_grid` attribute (i.e. `SourceRegistry` is the only legacy provider; its compat methods take `rep_path` first).
- `publish_threshold_chain(...)` — gets `provider.get_chain()` (or `get_chain(rep_path)` for legacy), computes `_depth` per entry from `parent_name`, then DFS-reorders so each child emits right after its parent's subtree; writes `state.ui_threshold_chain`. **Idempotent.**
- `refresh_threshold_ui_for_active_grid(...)` — **bails early** (clearing `ui_threshold_chain` + `ui_threshold_arrays_available`) when `state.fespp_data_selectors` is empty, then republishes arrays + chain.
- `threshold_add(state, controller, scene_registry, source_registry, activator, view, parent_name=None, array=None, view_id=None, tree=None)` — defaults `array` to `state.active_color_array_name`, runs MR resolution when `tree` is passed, calls `provider.add_threshold(...)`, republishes, refreshes the activator, hides unused scalar bars, renders.
- `sync_blocked_wellbore_chains(scene_registry, provider, rep_path, view_id)` — mirrors the grid's threshold chain onto its LOADED BlockedWellbores, the well-side twin of the colour mirror: FESPP puts the grid's CELL arrays on every loaded wellbore (same names, crossed-cells subset), so the grid's ranges apply verbatim and the wells keep only matching cells. Declarative reconcile — replays the grid's `snapshot_threshold_chain()` through `apply_threshold_chain` (full replace, idempotent) on each wellbore `RepInScene`, so all four ops reduce to the same call. Hooked into `threshold_add` / `threshold_delete` / `threshold_set_range` / `threshold_set_visible`, into boot's single-rep threshold copy-from-view, and into `data_load`'s fresh-wellbore block (a BW checked after the filter was set inherits the chain). Guards: only wellbores with an EXISTING per-view rep (an unchecked one is never materialised); no-ops on legacy providers (no `scene` attribute). Cost: one proxy teardown+rebuild per (loaded BW, entry) per op.
- `threshold_delete` / `threshold_set_range` / `threshold_set_visible` — forward to the provider's `delete_threshold` / `set_range` / `set_visible` (with the per-view-vs-legacy `rep_path` asymmetry), republish, render.
- `on_threshold_pending_action(state, action, threshold_add, threshold_delete, threshold_set_range, threshold_set_visible)` — single-entry-point dispatcher: reads `action["action"]` (`add`/`delete`/`set_range`/`set_visible`), calls the matching passed-in controller closure, then **clears `state.ui_threshold_pending_action`** in a `finally` (so identical repeat actions still fire past Trame's no-op-write collapse).

**State.** Writes `ui_threshold_chain`, `ui_threshold_arrays_available`, `ui_threshold_pending_action` (cleared). Reads `ui_active_node_reservoir_type_rep`, `active_representation_path`, `active_color_array_name`, `fespp_data_selectors`, `ui_active_array_by_rep_by_view`, `drawer_target_view_id`, `fespp_active_panel_id`. Also reads/writes `ui_active_realization_by_array_by_view` indirectly via `realization_dispatch`.

**Collaborators.** `realization_dispatch` (MR detection + suffixing), `make_valid_vtk_name`, `source_resolver.hide_unused_scalar_bars`, `paraview.simple`. Providers: `RepInScene` (per-view, including its `_ijk_provider()` delegation for IjkGrid) and `SourceRegistry` (legacy). Entry points are boot.py closures; `on_threshold_pending_action` is the UI's funnel.

**Gotchas.**
- **The MR title-vs-array trap.** `state.active_color_array_name` carries the property **title**, not the VTK array name. For MR properties the real array is `<title>_real_<idx>`. Without `_resolve_vtk_array_name`, `RepInScene._add_threshold_local` fails at `_resolve_assoc(title)` and the threshold silently never appears (the 2026-05-27 smoke-test bug). `threshold_add` only runs the resolver when `tree` is passed — callers MUST pass `tree` or MR thresholds silently miss.
- `_find_property_path_by_title` was added because the old `ui_active_array_by_rep_by_view` bucket only tracks eye clicks; tree-activating a new property without an eye click left a stale path → MR suffixing with the wrong realization idx → a nonexistent array name.
- `refresh_threshold_ui_for_active_grid`'s early bail is a **segfault guard**: reading a provider after `source_registry.sync` Delete()'d the underlying PV source crashes inside `vtkPVRenderView` with no Python traceback.
- The uniform provider call convention (`provider.<op>(name/parent/...)`, no `rep_path`) collapses the dispatcher branching to "per-view provider vs legacy `SourceRegistry`" — detected solely by `_is_per_view_provider`.

---

### `fespp_on_trame/app/core/engine/marker_dispatch.py`

**Responsibility.** Global wellbore-marker display options (orientation + size) plus the marker-specific Z handling used by `apply_z_scale`. FESPP exposes two **global** properties on the EPC collector — `MarkerOrientation` (oriented DISK by RESQML dip/dip-direction vs plain SPHERE) and `MarkerSize` (radius) — applying to every marker.

**Key classes / functions.**
- `marker_proxy_ids(scene_registry)` — returns a `set[int]` of `SMProxy.GetGlobalID()` for every per-`(marker, view)` extractor in `scene.reps()[*]._marker_extractors`. Lets a raw `view.Representations` iteration recognize a marker glyph. Empty set on any failure.
- **`is_marker_proxy(proxy)`** — **name-based, scene-registry-free** marker detection. Gets `proxy.SMProxy` (or `proxy`), queries the `paraview.servermanager.ProxyManager()` for the registration name in groups `"filters"` then `"sources"`, and returns `True` when the name **starts with `"mrk_"`**. Robust everywhere a marker surfaces (scene proxies OR legacy). Used by `slicer_dispatch.apply_z_scale`.
- **`apply_marker_z(disp, source, zs)`** — places a marker glyph at its Z-scaled depth **without stretching it**. Computes `z_center` from `source.GetDataInformation().GetBounds()` (UNSCALED extractor bounds — Position/Scale don't bake into geometry, so re-reading is stable across z-scale changes), only when `zs != 1.0`. Saves the solid tint + LUT (`DiffuseColor`, `AmbientColor`, `ColorArrayName`, `LookupTable`, `Opacity`), sets `disp.Scale = [1,1,1]`, then **translates** by `[0, 0, (zs-1)*z_center]`, then restores the saved attrs. See Gotchas for the Position→Translation handling.
- `apply_marker_options(collector, scene_registry, controller, orientation, size)` — sets `MarkerOrientation` (`1`/`0`) and `MarkerSize` (int) on `collector.get_source()` via `SetPropertyWithName`, calls `UpdatePipelineInformation()`+`UpdatePipeline()`, then for every scene re-clones (`scene.clone`) and re-extracts every shown marker (`ris._marker_extractors.values()` where `ris._is_marker_frame()`), renders each `scene.pv_view`, and finally pushes a fresh frame to **every** panel via `controller.view_update_for(vid)` (falling back to `view_update()`).

**State.** None directly. Reads scene/rep structures (`_marker_extractors`, `_is_marker_frame`, `clone`, `pv_view`) and the controller push methods.

**Collaborators.** `paraview.simple` (`Render`); `paraview.servermanager.ProxyManager`; the collector (`get_source`, `SetPropertyWithName`); `scene_registry.all_scenes()` / `view_ids()`; `RepInScene._marker_extractors` / `_is_marker_frame()`. Called by `slicer_dispatch.apply_z_scale` (`is_marker_proxy`, `apply_marker_z`) and by a boot.py closure (`apply_marker_options`).

**Gotchas.**
- **PV6 Position→Translation.** ParaView 5.13+ renamed the display **`Position`** property to **`Translation`**. On those builds, even `hasattr(disp, "Position")` raises a `NotSupportedException` (it propagates), so you cannot probe it safely. `apply_marker_z` therefore loops `for attr_name in ("Translation", "Position")` and `setattr`s inside a `try/except`, breaking on first success — modern name first, legacy fallback.
- **`is_marker_proxy` is purely name-based** (`mrk_` prefix), intentionally avoiding the scene registry so it works in both the per-view and legacy z-scale paths. Markers are symbolic; never scale their display Z (that yields an "olive"), always translate.
- `apply_marker_z` saves/restores the solid tint because a transform write can reset the rep's coloring on some PV builds (markers carry a `SolidColor`).
- `apply_marker_options` is **heavy**: changing either property + `UpdatePipeline` re-runs the collector's `RequestData` over the WHOLE cumulative selection (each marker node hits the C++ `changeOrientationAndSize`). Call on slider **release**, not per step. Per-marker / per-view variants would need C++ work (the clone doesn't rebuild markers); this is the global Phase 1.

---

### `fespp_on_trame/app/core/engine/realization_dispatch.py`

**Responsibility.** Per-view multi-realization choice — owns `state.ui_active_realization_by_array_by_view` and derives the per-panel / global realization-picker specs. Orthogonal to `active_array.py` (which owns the property choice). No reconcile with the plugin: loading is handled by tree selection; the picker only drives ColorBy.

**Key classes / functions.**
- `_MR_TYPES = frozenset({"MultiRealization", "MultiRealizationTimeSeries"})` — module constant.
- `is_multirealization_property(tree, array_path) -> bool` — `True` iff the node type is in `_MR_TYPES`.
- `available_realization_indices(tree, array_path) -> list[int]` — parses the node's `realization_indices` CSV attribute into a sorted int list (skipping non-ints).
- `default_realization_for(state, tree, array_path) -> Optional[int]` — the smallest available index (no global cursor anymore).
- `set_active_realization_for_view(state, panel_id, array_path, idx)` / `clear_active_realization_for_view(...) -> bool` / `get_active_realization_for_view(...) -> Optional[int]` — get/set/clear into the nested map `ui_active_realization_by_array_by_view[panel_id][array_path]`. The setter/clearer rebuild the dicts top-down (fresh inner dicts) so trame's state sync picks up the mutation.
- `suffixed_array_name(base_array_name, idx) -> str` — the single source of truth for the naming convention: `f"{base}_real_{idx}"`.
- `recompute_panel_has_mr(state) -> dict` — `{panel_id: bool}` from `ui_panel_active_mr_specs_by_id` (a panel has MR iff its spec list is non-empty).
- `recompute_global_mr_specs(state) -> list` — aggregates per-panel specs by `array_path`, taking the **union** of available indices, computing `current_idx` as the **mode** across panels, and setting `mixed=True` when panels disagree. Sorted alphabetically by title.
- `resolve_global_selected(state) -> tuple` — validates `ui_global_mr_selected_path` against `ui_global_mr_specs`; falls back to the first spec when stale; returns `("", None)` when no MR property exists.
- `recompute_panel_mr_specs(state, tree) -> dict` — builds `{panel_id: [{array_path, title, available_indices, current_idx}]}` from `ui_active_array_by_rep_by_view` (skipping non-MR / no-available-index paths, deduping by path). Title comes from `propTitle` → tree title → last path segment; specs sorted by title.

**State.** Writes `ui_active_realization_by_array_by_view`. Reads it plus `ui_panel_active_mr_specs_by_id`, `ui_global_mr_specs`, `ui_global_mr_selected_path`, `ui_active_array_by_rep_by_view`. The `recompute_*`/`resolve_*` functions return new values and **leave the write-back to the caller**.

**Collaborators.** The engine `Tree` API (`find_node_id`, `find_type`, `find_attribute_value`, `find_title`). Consumed by `threshold_dispatch._resolve_vtk_array_name`, `stats_dispatch`, `distribution_dispatch`, and the per-view/global RealizationPicker UI (via boot.py closures).

**Gotchas.** All map mutators rebuild dicts top-down because trame's state sync sometimes drops mutations through shared inner references (a recurring pattern across this codebase). The "global" picker reconciles divergent panels by taking the union of available indices and the mode of current indices, surfacing disagreement via the `mixed` flag. There is intentionally **no global realization cursor** anymore — the choice is strictly per-`(view, array_path)`.

---

### `fespp_on_trame/app/core/engine/distribution_dispatch.py`

**Responsibility.** Compute a Plotly histogram `Figure` for one Stats row (or an overlay for several). Replaces the noNaN-Threshold→DescriptiveStatistics chain with a single `numpy.histogram` (continuous) or `np.unique` (discrete/categorical) on the raw VTK array, pushing only a small binned trace over the WebSocket.

**Key classes / functions.**
- Constants: `_DEFAULT_NBINS=50`; display modes `_MODE_BARS/_LINE/_CURVE` (`_VALID_MODES`); norms `_NORM_COUNT/_DENSITY/_PROBABILITY` (`_VALID_NORMS`); `_DEFAULTS` dict; `_COLORWAY` (10-color Vuetify-aligned palette).
- `_numpy_imports()` / `_go_imports()` — **lazy** imports of numpy/`vtk_to_numpy` and `plotly.graph_objects` so engine boot survives a stale venv missing these.
- `_drill_to_inner(vtk_out)` — unwraps a `vtkPartitionedDataSetCollection` (mirrors the stats version).
- `_get_named_array(source, vtk_name)` — `UpdatePipeline` + locate the array by name on Cell/Point/FieldData.
- `_is_discrete_kind(prop_kind)` — `True` if the kind string contains `"discrete"` or `"categorical"`.
- `_apply_norm(counts, total, widths, norm)` — density = `counts/(total*widths)`; probability = `counts/total`; else raw.
- `_shape_trace_for_mode(centers, heights, widths, mode, color)` — builds the Plotly trace dict (bar / `scatter` step `shape="hv"` / `scatter` spline `shape="spline"` with fill).
- `_build_continuous_trace(...)` / `_build_discrete_trace(...)` — drop NaN pre-binning, optionally `np.cumsum` then `_apply_norm`; return `(trace, kept_count, finite_values, bin_centers, bin_heights, bin_widths)`.
- `_stats_overlay_shapes(np, finite_values)` / `_stats_overlay_annotations(np, finite_values, log_y)` — paper-anchored vertical lines + labels for Q1/median/mean/Q3.
- `_resolve_view_source(scene_registry, source_registry, rep_path, view_id)` — mirrors `stats_dispatch._resolve_rendered_inputs` + `_append_if_multiple`; returns `((merged, owns_merged), pv_view)` — **caller must Delete `merged` if `owns_merged`**.
- `_resolve_options(**kwargs)` — merges caller kwargs over `_DEFAULTS`, validating mode/norm and clamping `nbins` to `1..500`.
- `compute_histogram_figure(state, tree, scene_registry, source_registry, array_path, row_kind, row_id, *, nbins, display_mode, log_y, show_stats, cumulative, norm, return_meta=False)` — the main per-row compute. `row_kind` ∈ {`"original"`, `"view"`}; `row_id` is `"default"`/`"custom-N"` (original) or `panel_id` (view). Resolves the source (view rows via `_resolve_view_source` at the view's active realization + `ViewTime`; original rows via `stats_dispatch._original_source_and_name` at the entry's `real_idx`/`ts_idx`), reads the array, builds the trace, and returns a `go.Figure` (or `(fig, meta)` when `return_meta=True`).
- `compute_compare_figure(...)` — aggregates `selection_keys` (`{array_path}|{row_kind}|{row_id}`) into one overlay figure (`barmode="overlay"` / stacked scatters), per-trace color from `_COLORWAY` and opacity by mode. Returns `None` (or `(None, None)`) when fewer than 2 traces resolve. Stats overlay forced off.
- `build_csv_from_meta(meta)` / `_csv_escape` / `_csv_num` — render a CSV (single-row 3-column or compare side-by-side per-trace) from the meta dict.

**State.** Reads `ui_stats_panel_state`, `fespp_render_panels`, and (via `realization_dispatch`) `ui_active_realization_by_array_by_view`. Writes none directly — returns figures/CSV to the caller.

**Collaborators.** `stats_dispatch` (heavily: `_resolve_rendered_inputs`, `_append_if_multiple`, `_title_and_kind`, `_prop_kind_for_array_path`, `_rep_path_for_array_path`, `_resolve_vtk_name`, `_original_source_and_name`, `_default_real_idx`, `_ts_label_for_idx`, `_unit_for_array_path`, `_DEFAULT_ORIGINAL_ENTRY`), `realization_dispatch`, `time_realization.label_for_time_value`, lazy numpy/plotly, `paraview.simple`. Consumed by the distribution panel via boot.py closures.

**Gotchas.**
- **PV-globals snapshot/restore.** `compute_histogram_figure` snapshots `GetActiveSource()`/`GetActiveView()` on entry and restores them in a `finally`, plus deletes any `owns_merged` AppendDatasets and calls `_restore_channel()` — so a transient merge or a mid-function exception cannot leak its active source/view into the main render path (which would trigger fan-out handlers on the wrong proxy).
- **Time handling differs by row kind.** Original TS rows temporarily move `TimeKeeper.Time` to the entry's `ts_idx` (restored in `finally`, re-executing the source at the restored time); view rows read the authoritative `pv_view.ViewTime`.
- Wellbore-channel arrays live only on the per-view extractor and are raw-named — `_orig_real_name` overrides `vtk_name` accordingly.
- The compare figure intentionally never draws per-row mean/median overlays (they'd clutter); the toggle is a visual no-op on a compare panel.

---

### `fespp_on_trame/app/core/engine/stats_dispatch.py`

**Responsibility.** Descriptive-statistics multi-property table ("Brique B"). Builds `state.ui_stats_tables` (one card per pinned property, with Original rows + one View row per render panel coloring by the property), manages the per-property panel state, and powers the side-by-side compare cart.

**Key classes / functions.**
- VTK plumbing: `_drill_to_inner`, `_resolve_rendered_inputs(scene_registry, source_registry, rep_path, view_id)` (returns visible-only sources for a `(rep, view)`, **augmented** with the rep's clip/slice outputs), `_resolve_assoc(source, array_name)` ("CELLS"/"POINTS"), `_table_row_to_dict`, `_total_count_for_assoc`, `_append_if_multiple(sources) -> (merged, owns_merged)`.
- `_compute_one_variable(input_source, array_name)` — the core compute: `Threshold(Between -1e308..+1e308)` (drops NaN, since any NaN comparison is False) → `DescriptiveStatistics`, reads primary+derived blocks, adds `Q1`/`Median`/`Q3` via numpy percentiles on the threshold output, `variable`, and `NaN_count = total − Cardinality`. Deletes both transient proxies in `finally`.
- Tree/state resolution: `_rep_path_for_array_path`, `_rep_title_for_array_path`, `_title_and_kind`, `_prop_kind_for_array_path`, `_unit_for_array_path` (always `""` until a UOM attribute lands — see its TODO), `_resolve_vtk_name(tree, array_path, real_idx)` (MR → `<sanitized>_real_<idx>`), `_default_real_idx`, `_ts_label_for_idx`.
- Row builders: `_original_source_and_name(...)` (channel-aware: wellbore-frame channels read the per-channel extractor, not the legacy frame source); `_build_original_row(...)` (unfiltered source, auto-resolves real/ts, temporary TimeKeeper shift); `_build_view_row(...)` (rendered output; returns None when the view doesn't color the rep by this property; reads `pv_view.ViewTime`).
- Publish: `_compute_ts_items(tree)`, `_available_realizations_for`, `_build_table_for_path(...)`, **`publish_descriptive_stats(state, scene_registry, source_registry, tree, view_id=None)`** — recomputes `ui_stats_tables` for every pinned path; `view_id` is ignored (property-driven model).
- Panel-state mutators: `toggle_stats_pinned`, `_patch_original_entry`, `set_original_real_idx`, `set_original_ts_idx`, `pin_original` (snapshots the `default` row into a new `custom-<n>` and resets default to auto; **no-ops when the same (real, ts) combo is already pinned** — `_pinned_combos`), `unpin_original` (can't remove `default`), `pin_all_originals(state, array_path, 'real'|'ts')` (bulk-pin one row per available realization at the current time step / per time step at the current realization, values read from the PUBLISHED `ui_stats_tables[..].available_*`; idempotent, skips existing combos), `unpin_all_originals` (drops every custom row, default survives). Card-header buttons "Pin all reals" / "Pin all steps" / "Unpin all" trigger them (`stats_pin_all` / `stats_unpin_all`).
- Compare cart: `publish_compare_items(...)` (resolves `ui_stats_compare[array_path]` keys to `{key, row, propertyTitle, column_label}` items + tags numeric `extrema` min/max), `toggle_compare`, `clear_compare`, `_toggle_per_property_cart`, `_clear_per_property_cart`.

**State.** Writes `ui_stats_tables`, `ui_stats_publish_version`, `ui_descriptive_stats` (legacy, cleared), `ui_stats_panel_state`, `ui_stats_pinned_paths`, `ui_stats_compare`, `ui_stats_compare_items`. Reads `ui_stats_pinned_paths`, `ui_stats_panel_state`, `fespp_render_panels`, `ui_active_array_by_rep_by_view`, `time_index`.

**Collaborators.** `source_resolver` (`sources_for_rep_path`, `channel_source_for`), `realization_dispatch`, `time_realization.label_for_time_value`, `make_valid_vtk_name`, `tree_icons.get_primary_icon`, `paraview.simple`, vtk numpy support. Entry point: `boot._refresh_descriptive_stats`; mutators and compare via boot.py closures. Consumed by `distribution_dispatch`.

**Gotchas.**
- **`publish_descriptive_stats` neutralizes the active view.** It snapshots both the active source and active view, then `SetActiveView(None)` for the whole compute (and toggles `vtkObject.GlobalWarningDisplayOff()`), restoring everything in `finally`. Reason: each transient `Threshold`/`DescriptiveStatistics`/`AppendDatasets` calls `SetActiveSource(self)`; deleting them leaves the active source dangling, and the active-source change would otherwise be treated as user navigation (re-running `apply_color_array`, wiring a scalar bar). The warning-display toggle silences the expected "No active view found" spam during that window.
- **NaN strategy** — `Threshold(Between -inf..+inf)` is the canonical NaN drop so kurtosis/skewness stay meaningful; `NaN_count` is reconstructed as `total − Cardinality`.
- **All panel-state mutators rebuild dicts top-down** (same trame-sync caveat as `realization_dispatch`). `ui_stats_publish_version` is bumped on every publish so Vue remounts rows (stable keys with new dict refs otherwise keep stale cells mounted).
- Wellbore channels are the special source case: the legacy frame source lacks the channel array, so `_original_source_and_name` reads the channel's own persistent extractor.
- Compare carts are per-property (`ui_stats_compare[array_path]`), so mixing units across properties is structurally impossible; the same cart feeds both the numeric compare panel and the distribution overlay.

---

### `fespp_on_trame/app/core/engine/time_realization.py`

**Responsibility.** Global TimeKeeper labelling for the UI. Keeps `state.ui_time_label` (and per-view label vars) aligned with the tree-attached `timeXXX.XXXXXX` label (or formatted raw float). Realization handling was moved out to `realization_dispatch`.

**Key classes / functions.**
- `_ISO_DATE_RE` + `_shorten_time_label(label)` — trims ISO datetime labels (`2019-12-31T23:00:00Z`) to the date prefix (`2019-12-31`); passes everything else through.
- `label_for_time_value(tree, time_value)` — reads `tree.find_attribute_value(0, f"time{time_value:.6f}")` (attribute on the assembly root), shortens it, or falls back to `f"time{time_value:.6f}"`. **This is the shared label resolver** used by the global TC, per-view TCs, stats dropdowns, and distribution chart labels.
- `change_time_label(state, tree)` — sets `state.ui_time_label` from `GetTimeKeeper().TimestepValues[state.time_index]`; `""` on failure.
- `register_per_view_time_label(state, tree, time_value_var, label_var)` — wires a `state.change(time_value_var)` handler that recomputes `label_var` and bumps `state.ui_per_view_time_pulse`; seeds once immediately.

**State.** Writes `ui_time_label`, the dynamic per-view `label_var`, and `ui_per_view_time_pulse`. Reads `time_index` and the dynamic `time_value_var`.

**Collaborators.** `paraview.simple.GetTimeKeeper`; the engine `Tree.find_attribute_value`. Called by boot.py (`change_time_label`) and `FesppMultiView` (when it creates a per-view TimeControl). The label helper is imported by `stats_dispatch` and `distribution_dispatch`.

**Gotchas.** `time_value_<panel_id>` is dynamic per view, so the stats trigger list can't watch it directly — `ui_per_view_time_pulse` is a single fixed monotonic counter every per-view TC pokes so the stats dispatcher can recompute View rows when any per-view time moves. The legacy global realization cursor (`ui_slices_real` → `collector.set_realization_index`) is **gone**; per-view realization lives entirely in `realization_dispatch`.

---

### `fespp_on_trame/app/core/engine/compare_matrix.py`

**Responsibility.** Pure (no PV/state) primitives for the floating Compare-stats panel: metric visibility filter, sort, highlight annotations (extrema/baseline-delta/heatmap), distribution profile classification, and CSV export. Operates only on item dicts produced by `stats_dispatch.publish_compare_items`.

**Key classes / functions.**
- `_METRIC_KEYS` (canonical order, 16 metrics) + `_METRIC_LABELS` (display names; note `Cardinality`→"Value count", `NaN_count`→"No value count").
- `visible_metric_keys(hidden_metrics)` — canonical order minus hidden.
- `sort_items(items, sort_key, sort_asc)` — stable sort by a metric key; None/non-numeric sink to the bottom via the `(1, 0.0)` tuple key.
- `highlight_annotations(items, mode, baseline_key=None, normalize=False)` — returns `{metric_key: {item_idx: tag}}`. Modes: `"extrema"` (`'min'`/`'max'`), `"baseline"` (`'pos'`/`'neg'`/`'eq'` sign of delta vs the baseline-keyed item), `"heatmap"` (float 0..1 — per-metric min/max rescale, or z-score clipped ±3σ mapped to [0,1] when `normalize=True`; σ=0 collapses to 0.5).
- `items_to_csv(items, hidden_metrics=None)` — matrix CSV (`row` + visible metrics in canonical order).
- `profile_tag(skewness, kurtosis)` — classifies `symmetric`/`skewed_right`/`skewed_left`/`heavy_tail` (treats kurtosis as excess, centered on 0); `""` on missing/non-numeric.
- `highlight_annotations_for_items(items, mode, baseline_key=None, normalize=False)` — wrapper that drills into `item["row"]` for metrics; for baseline mode rebuilds the dict by **index** (the row dict lacks the cart `key`) and stashes absolute + relative deltas under the `"_deltas"` sub-key.
- `_csv_escape` / `_csv_num`.

**State.** None (pure module).

**Collaborators.** Consumes `stats_dispatch.publish_compare_items` output. Consumed by the `stats_compare` panel UI (via boot.py closures). No PV, no trame state.

**Gotchas.** Two highlight entry points exist: `highlight_annotations` (operates on flat dicts where metrics are top-level keys) vs `highlight_annotations_for_items` (operates on the wrapper items, drilling into `["row"]`). The wrapper calls the flat version with `baseline_key=None` and then **rebuilds baseline mode from scratch using `base_idx`** — because baseline lookup needs the cart key that only the wrapper carries. The kurtosis convention assumption ("treat value as excess, centered on 0") matters: if a pipeline ever returns raw (non-excess) kurtosis, `profile_tag`'s `heavy_tail` threshold would misfire.

---

### `fespp_on_trame/app/core/engine/diff.py`

**Responsibility.** Diff-view dispatch — pick two properties on the same grid and render A − B into a dedicated diff panel via a `PythonCalculator`. Extracted from `boot.initialize_fespp_engine`.

**Key classes / functions.**
- `build_array_choice(tree, array_path)` — resolves a tree path to `{title: "<rep_title> / <array_name>", value, rep_path, array_name}` (using `propTitle`→title and the ancestor rep node); None when unresolvable.
- `refresh_diff_choices(state, tree, ui_loaded_array_paths)` — rebuilds `state.diff_array_choices` from the loaded-array list.
- `refresh_diff_b_choices(state, diff_array_a_path, diff_array_choices)` — filters `diff_array_b_choices` to "same rep as A, different from A".
- `compute_diff(state, controller, server, source_registry)` — validates A/B (both set, known, same rep, source loaded), gets/creates the diff view via `server.context.multi_view.get_or_create_diff_view()`, sets `fespp_diff_computing=True` + flushes, snapshots active view/source, sets the diff view active, deletes any existing `fespp_diff` calc, creates a `PythonCalculator` (`Expression = "A - B"`, `ArrayName = "fespp_diff_value"`, `ArrayAssociation = "Cell Data"`), hides the calc in non-diff views, hides everything else in the diff view, shows + `ColorBy(("CELLS","fespp_diff_value"))` + scalar bar + reset camera + render, updates the html view, sets `fespp_diff_ready=True`, optionally refreshes the diff color editor; restores active view/source and `fespp_diff_computing=False` in `finally`.

**State.** Writes `diff_array_choices`, `diff_array_b_choices`, `diff_compute_error`, `fespp_diff_computing`, `fespp_diff_ready`. Reads `diff_array_a_path`, `diff_array_b_path`, `diff_array_choices`, `diff_colors_dialog_visible`.

**Collaborators.** `paraview.simple` (`PythonCalculator`, `FindSource`, `Show`/`Hide`, `ColorBy`, `ResetCamera`, `Render`), the engine `Tree`, `server.context.multi_view` (`get_or_create_diff_view`, `_pv_internal`, `_html_views`), `source_registry.get`, `controller.refresh_diff_color_editor`. Entry points are boot.py closures.

**Gotchas.** The active view/source snapshot+restore is essential: subsequent tree clicks act on `pvsimple.GetActiveView()`, so without restoring them the diff view would silently retarget. The handler switches the active view to the diff view *before* creating the calc so any implicit pvsimple side-effects target the diff view, and defensively `Hide`s the calc in every non-diff view (`mv._pv_internal`). Errors are surfaced via `state.diff_compute_error` rather than raised. Note the reach into multi-view privates (`_pv_internal`, `_html_views`) — tight coupling to `FesppMultiView` internals.

---

### `fespp_on_trame/app/core/engine/etp.py`

**Responsibility.** ETP/OSDU connection lifecycle plus a shared `update_data_information` that re-parses the live `vtkDataAssembly` into the engine `Tree` (works for both Collector and ETPConnector). Extracted from `boot.initialize_fespp_engine`.

**Key classes / functions.**
- `connect_to_etp(state, etp_connector, etp_url, data_partition, token, token_type="Bearer", proxy_url=None, proxy_token=None, proxy_token_type="Bearer")` — calls `etp_connector.connect(...)`; on success sets `state.etp_dataspaces = etp_connector.get_dataspaces()`, else `[]`.
- `select_etp_dataspace(etp_connector, dataspace)` — `etp_connector.set_dataspace(dataspace)` when connected.
- `force_etp_refresh(state, etp_connector, collector, tree)` — runs `UpdatePipelineInformation()` **twice with a 0.5s sleep between** (to surface late-arriving ETP entries when the server defers dataspace enumeration), then calls `update_data_information`.
- `update_data_information(etp_connector, collector, tree)` — picks the live source (ETP source when connected, else collector), then resolves the assembly preferring `GetLiveAssembly()` (the repository's `_output->GetDataAssembly()` directly), falling back to `GetAssembly()` and finally `GetOutput().GetDataAssembly()`; calls `tree.set_tree(assembly)`.

**State.** Writes `etp_dataspaces`. Reads none.

**Collaborators.** `paraview.simple` (imported), `time.sleep`, the `ETPConnector` (`connect`, `is_connected`, `get_dataspaces`, `set_dataspace`, `get_source`), the `collector` (`get_source`), the engine `Tree.set_tree`. Entry points are boot.py closures.

**Gotchas.** `GetLiveAssembly` is the **preferred** getter because after `rebuildAssembly()` (a TreeHierarchyMode change) the live assembly is mutated without re-running RequestData, so the pipeline output's deep copy is stale. `GetAssembly()` exists on the parent class but isn't always wrapped to Python through the override; `GetLiveAssembly` is unique and always wrapped. The double-`UpdatePipelineInformation` + sleep is an empirical workaround for background dataspace enumeration on the ETP server side.

---

### `fespp_on_trame/app/core/engine/vtk_log.py`

**Responsibility.** Capture VTK/ParaView C-level stderr (fd 2, via vtkLogger — invisible to Python `print`/`logging`) and tee it to both docker logs and an in-memory queue the UI surfaces via `state.vtk_log_messages`.

**Key classes / functions.**
- Module state: `_vtk_log_queue` (list), `_vtk_stderr_tee_done` (bool), `_ANSI_RE`, `_VTK_LINE_RE` (parses `(  29.2s) [thread] file.cxx:67  ERR| message` into level tag + text), `_SUPPRESS_PATTERNS` (currently just `"No active view found"`).
- `setup_stderr_tee() -> None` — **idempotent.** Creates an `os.pipe()`, dups the original fd 2 aside, redirects fd 2 to the pipe write end, and starts a daemon `_reader` thread that drains whole lines, strips ANSI, applies `_SUPPRESS_PATTERNS` (suppressing in **both** docker logs and the queue), forwards non-suppressed raw lines (ANSI intact) to the original fd 2, and appends `{text, level}` dicts (level from the `ERR`/`WARN` tag) to `_vtk_log_queue`.
- `capture_vtk_messages(state, max_messages=500)` — context manager that records `start_seq = len(queue)` on entry; in `finally` sleeps `0.05s` (let the reader flush the pipe), slices `queue[start_seq:]`, and appends to `state.vtk_log_messages` (capped to the last `max_messages`).

**State.** Writes `vtk_log_messages` (in `capture_vtk_messages`).

**Collaborators.** Stdlib only (`os`, `threading`, `re`, `contextlib`, `sys`, `time`). `setup_stderr_tee` is called once at boot (after ParaView init); `capture_vtk_messages` wraps engine blocks whose VTK output should reach the UI log panel.

**Gotchas.** `setup_stderr_tee()` **must run AFTER ParaView init** or startup noise floods the queue. Module-level singletons (`_vtk_log_queue`, the tee thread) are intentional — there is exactly one stderr fd per process, so the queue is sliced by index (`start_seq`) so a single tee thread serves multiple concurrent sessions. The reader buffers and splits on `\n` so the suppression decision is per-line (a raw 1024-byte read may straddle a line boundary). Suppressed lines are dropped from docker logs too — add a narrow `_SUPPRESS_PATTERNS` entry rather than silencing a broad category. The `"No active view found"` suppression specifically covers the window where `stats_dispatch.publish_descriptive_stats` holds the active view at None.
