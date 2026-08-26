# Core (root), IO & Utils

## Overview

This page covers the "glue" layer of the Trame app: the small root-level core classes that translate UI tree interactions into ParaView/FESPP actions (`selector.py`, `activator.py`, `tree.py`, plus the per-node companion objects `timeseries.py` and `wellhead.py`), the IO subsystem that gets EPC/H5 files into the process (`http_download.py`, `upload_endpoint.py`, `temp_dir.py`, `session_hooks.py`), the stateless string/color/tree utilities (`naming.py`, `color_palette.py`, `search_node.py`), the global constants module, and the process entry point (`__main__.py`).

The central data structure is a C++-built `vtkDataAssembly` exposed through `Tree` (`tree.py`). The tree drives three parallel UI tabs — **reservoir**, **surface**, **well** — each with its own `ui_select_node_*` (checkbox state) and `ui_active_node_*` (clicked/active node) state variables. `Selector` reads the checkbox lists and produces `state.fespp_data_selectors` (the list of assembly paths FESPP loads); `Activator` reacts to active-node changes to refresh the Attributes/color panels and re-apply ColorBy. A recurring theme across these files is the **legacy-vs-current duality**: comments repeatedly call out that older "collapse to parent path" / "auto-load descendants" assumptions no longer hold under `ExplicitSelection=1` (set at boot in `engine.py`), and that `search_node.py` is an older flat-dict tree walker superseded by `Tree`'s assembly-backed lookups. Several files (the IO modules, `__main__.py`) are import-time-side-effecting and contain monkey-patching of aiohttp internals; read the Gotchas carefully before forking.

---

### `fespp_on_trame/app/core/selector.py`
**Responsibility.** Translates the per-tab `ui_select_node_*` checkbox ID lists into assembly paths and writes the concatenated result into `state.fespp_data_selectors`. Also creates/destroys the per-kind companion objects (`Wellhead`, `TimeSeries`) tied to specific node kinds in the current selection.

**Key classes / functions.**
- `class Selector` — Holds three private per-tab path lists (`_selection_path_reservoir`, `_selection_path_surface`, `_selection_path_well`), a list of live `Wellhead`s (`_wellheads`), and a per-tab dict of live `TimeSeries` companions (`_timeseries = {tab: TimeSeries}`). `state.fespp_data_selectors` is always rebuilt as `reservoir + surface + well` so order is stable.
  - `__init__(self, tree: Tree)` — stores the `Tree`, initializes the empty path/companion lists, and `state.setdefault("first_selection", True)`.
  - `apply_z_scale(self, zscale)` — forwards the global Z exaggeration to every live `Wellhead` (the `Selector` owns them). Wellheads are Text reps with no `Scale` and absolute anchors, so the z-scale fan-out skips them and they need this explicit re-anchor — see `Wellhead.apply_z_scale`. Called from the `@state.change("ui_scale_z")` handler in `boot.py`, which covers BOTH z-scale entry points (the `TransformationEditor` persists its value into `ui_scale_z` before applying).
  - `optimize_tree_selection(self, selected_items)` — **Identity function now** (returns `list(selected_items)` or `[]`). It used to collapse "all children selected" groups to their parent path; that behavior is disabled under `ExplicitSelection=1`. The UI-side dependency expansion (auto-checking a Trajectory when a Channel/Marker is checked, auto-checking grouping descendants) happens in `tree_views.py` *before* this runs, so the input is already complete.
  - `select_node_surface(self)` — calls `_reset_timeseries("surface", ...)` (re-creates THIS tab's `TimeSeries` companion from its selection; other tabs keep theirs, and the time label deleted alongside it is restored from any surviving companion), resolves each ID to a path via `tree.find_path`, stores into `_selection_path_surface`, rebuilds `fespp_data_selectors`, flips `first_selection` False, sets `view_update = True`.
  - `select_node_well(self)` — same shape; additionally deletes and re-creates `Wellhead` companions for every checked `Trajectory` node (rebuilds `_wellheads` from scratch each call), and resets the WELL tab's `TimeSeries` slot via `_reset_timeseries`.
  - `select_node_reservoir(self)` — same shape; forwards every checked path explicitly (no descendant auto-expansion). IjkGrid teardown on empty selection is NOT done here — it is handled by the `fespp_data_selectors` change handler (`_on_change_fespp_data_selectors_impl`) elsewhere.

**State.** Reads `state.ui_select_node_surface`, `state.ui_select_node_well`, `state.ui_select_node_reservoir`, `state.first_selection`. Writes `state.fespp_data_selectors`, `state.first_selection`, `state.view_update`.

**Collaborators.** Imports/instantiates `Wellhead`, `TimeSeries`, `Tree`. Calls `tree.find_type` and `tree.find_path`. Entry points are the three `select_node_*` methods, called from the tree UI / selection-change wiring. `optimize_tree_selection` is internal but public.

**Gotchas.**
- `optimize_tree_selection` is intentionally a no-op now; do not "restore" the collapse behavior without re-checking the `ExplicitSelection` flag — sending only a parent path silently drops checked child properties.
- `select_node_well` rebuilds the *entire* `_wellheads` list on every call (delete-all then re-create), so each call is O(checked-trajectories), not incremental.
- `_timeseries` is a per-tab dict: a selection change on one tab only resets ITS OWN companion — the LUT lock and `ui_time_label` of a TimeSeries checked on another tab survive (`TimeSeries.refresh_label` republishes the label from a surviving companion).
- `if state.first_selection == True` uses `==` rather than `is`/truthiness — harmless but stylistically inconsistent.

---

### `fespp_on_trame/app/core/timeseries.py`
**Responsibility.** Companion object for a `TimeSeries` tree node. Locks the property's color LUT range to the series' `(minvalue, maxvalue)` so the colormap is comparable across timesteps, and refreshes `state.ui_time_label` from the current ParaView TimeKeeper value.

**Key classes / functions.**
- `class TimeSeries`
  - `__init__(self, tree: Tree, node_id)` — reads `title`, `minvalue`, `maxvalue` attributes from the node. When both min/max exist, calls `pvsimple.GetColorTransferFunction(title)` and `RescaleTransferFunction(float(min), float(max))`. Then calls `refresh_label()`.
  - `refresh_label(self)` — using `state.time_index`, looks up a per-timestep label attribute on the root node (id `0`) named `f"time{TimestepValues[index]:.6f}"`; if found, sets `state.ui_time_label` to it, otherwise to the raw `f"time{...:.6f}"` string. Also used by `Selector._reset_timeseries` to restore the label from a surviving companion after another tab's companion was deleted.
  - `delete(self)` — clears `state.ui_time_label = ""`.

**State.** Reads `state.time_index`. Writes `state.ui_time_label`.

**Collaborators.** `pvsimple.GetColorTransferFunction`, `pvsimple.GetTimeKeeper().TimestepValues`. Uses `Tree.find_title` and `Tree.find_attribute_value`. Constructed/deleted by `Selector`.

**Gotchas.**
- `self._source` is set to `None` in `__init__` and never assigned — unlike `Wellhead`, this companion creates no ParaView proxy; it only mutates a LUT and a label.
- `from ...sources.collector import Collector` is imported but unused (dead import).
- The per-timestep label attribute lives on the **root assembly node (id 0)**, keyed by the formatted timestep value — a non-obvious convention the C++ side must emit for labels to resolve.
- No bounds check on `state.time_index` vs `TimestepValues`; an out-of-range index would raise inside `__init__`.

---

### `fespp_on_trame/app/core/wellhead.py`
**Responsibility.** Renders a flagpole text label at the MD datum of a `WellboreTrajectory`, colored from the wellbore's `colorRGB` when available.

**Key classes / functions.**
- `class Wellhead`
  - `__init__(self, tree: Tree, node_id)` — reads the node's `title` and `mdDatumPosition` attributes. When `mdDatumPosition` exists, creates a `pvsimple.Text(registrationName=title + "_mdDatum")` proxy with `Text = 'A'`, shows it in the active view, sets `display.TextPropMode = 'Flagpole Actor'`, parses the comma-separated `mdDatumPosition` into `BasePosition`/`TopPosition` (raising the top Z by `0.01`), sets `FlagSize = 1.5`, and — if `tree.find_parent_attribute_value(node_id, "colorRGB")` returns a value — converts the `r,g,b` 0–255 triple to 0–1 floats and sets `display.Color`. Calls `pvsimple.Show(...)` a second time at the end.
  - `apply_z_scale(self, zscale)` — re-anchors the flagpole (`BasePosition` / `TopPosition`) and the billboard (`BillboardPosition`) at `z * zscale`, always re-derived from the UNSCALED `mdDatumPosition` baseline kept in `_position`. Called by `Selector.apply_z_scale` (driven by the `ui_scale_z` handler in `boot.py`) and once at the end of `__init__`, so a wellhead created while an exaggeration is already active lands on the scaled trajectory instead of the raw datum.
  - `delete(self)` — `pvsimple.Delete(self._source)` if a source was created; also drops the `_head` / `_label` rep handles (they point at proxies just deleted).

**State.** Reads `state.ui_scale_z` (at construction, to land on the current exaggeration). Otherwise operates on ParaView proxies, not Trame state.

**Collaborators.** `pvsimple.Text`, `pvsimple.Show`, `pvsimple.GetActiveView`, `pvsimple.Delete`. `Tree.find_title`, `Tree.find_attribute_value`, `Tree.find_parent_attribute_value`. Constructed/deleted by `Selector.select_node_well`.

**Gotchas.**
- **A wellhead cannot ride the z-scale fan-out — it must be re-anchored.** A `TextSourceRepresentation` carries **no `Scale` property at all** (setting it raises `AttributeError`, which the fan-out's `except AttributeError: pass` swallows silently), and `BasePosition` / `TopPosition` / `BillboardPosition` are ABSOLUTE world coordinates that a representation transform never moves. Its trajectory is real geometry and DOES stretch to `z * zs`, so left alone the head stays at the raw datum and the two visibly drift apart. Hence `apply_z_scale` recomputes the anchors, and `_position` must stay the UNSCALED baseline (never overwrite it with a scaled value, or the exaggeration compounds).
- The text content is the literal `'A'` (the flag glyph), not the well title — the title is only used for the registration name suffix `_mdDatum`.
- `pvsimple.Show` is called twice (lines 26 and 38) on the same proxy/view — the second call appears redundant.
- `colorRGB` is resolved via `find_parent_attribute_value` (walks up ancestors), so the color comes from the enclosing wellbore/feature, not the trajectory node itself.
- `from ...sources.collector import Collector` is imported but unused (dead import).
- If `mdDatumPosition` is absent, `self._source` stays `None` and `delete()` is a no-op — the object is constructed but renders nothing.

---

### `fespp_on_trame/app/core/activator.py`
**Responsibility.** Reacts to active-node changes in the three trees (`ui_active_node_reservoir/surface/well`), updates the Attributes panel + LUT/PWF/scalar-bar for the active node, and re-applies ColorBy when the per-rep "eye" is open. It deliberately does NOT own ColorBy itself — that is owned by `state.ui_active_array_by_rep` (the eye state); this class only refreshes panel state and re-applies coloring as a side effect.

**Per-tab scoping & projection.** Each tab's activation path writes ONLY its own `ui_active_node_<tab>_*` scoped set; the legacy shared vars every colour consumer reads (`active_color_array_name` / `active_property_kind` / `active_representation_path` / `active_color_array_path` / `active_representation_has_properties`) are re-computed from the VISIBLE tab's set by the module-level `project_shared_from_tab()` (also fired by a `@state.change("tab")` watcher, re-firing `update_color_editor` when the projected array changes so COE/categorical panels repopulate on tab return). Another tab's activity can therefore never clobber what the displayed tab's panels show; explicit `update_color_editor` calls in the activation paths are guarded on `state.tab == tab` for the same reason. Additional reservoir-side rules: a **BlockedWellbore** activation remaps the reservoir rep to its supporting grid (thresholds/slicers panels stay bound to the grid, read-only); `ui_active_node_reservoir_pending` publishes "selected but not loaded yet" (recomputed by `refresh_active()` after every load); the reservoir array name is best-effort seeded from the sanitized node title at activation, then upgraded to the array actually found on the data by the editor refresh.

**Key classes / functions.**
- Module helpers:
  - `_find_array_in_store(store, name)` — VTK array lookup with a fallback to `make_valid_vtk_name(name)`, because C++ sanitizes array names while the tree keeps the original RESQML title.
  - `_nan_opacity_from_state()` — parses `state.nan_color` (`#RRGGBBAA`) and returns the alpha as a 0–1 NaN opacity (default `0.0` = transparent).
  - `_all_displays_for_rep(rep_block_path, rep_type, view, target_source=None, target_display=None, source_registry=None, ijk_lookup=None)` — enumerates every display proxy rendering a rep so ColorBy can fan out to chain/slicer proxies. UG path pulls chain proxies from `source_registry.all_chain_proxies`; IJK path enumerates `ijk.all_render_sources()` per-grid; both then add the `rep<sanitized_path>` ExtractBlock filter. Dedupes by `id()`.
  - `_drill_to_inner(vtk_out)` — if the output is a `vtkPartitionedDataSetCollection`, returns its first inner partition; otherwise returns the object unchanged.
  - `_GROUPING_KINDS` — tuple of grouping kinds duplicated from `tree_views.py`/C++ `enum.h` to avoid a circular import; includes `Frame`/`MarkerFrame` (folders-for-selection that activate via a checked child).
- `class Activator`
  - `__init__(self, tree: Tree, source_registry=None, ijk_lookup=None)` — stores the tree, the source registry, and `ijk_lookup` (a callable `rep_path → IjkGrid | None`). Initializes `_current_array_by_rep` (per-rep "which array is colored" map, used for scalar-bar reaping). `setdefault`s many `ui_active_node_*` / `active_*` state vars and registers three `@state.change` handlers.
  - `_is_node_active_able(self, node_id, select_list)` → bool — the authorization gate: a **property leaf** (`*Property*` / `TimeSeries` / `MultiRealization*`) is activatable ONLY when its own id is checked; a **rep/grouping/intermediate** node is activatable when checked, under a checked grouping/rep, or has a checked descendant. Prevents unchecked sibling properties from activating (a fixed bug).
  - `_handle_reservoir_change(self, ui_active_node_reservoir)` — the heavy reservoir handler. Clears state on empty; rejects un-activatable nodes (resets `ui_active_node_reservoir = []`); resolves type/title; computes `is_property`, `is_multireal`, `is_ts_property`, `property_kind`; publishes a batch of `state.update(...)`; calls `_activate_reservoir_rep`; and for property nodes calls `_apply_color_for_active_property`. Wrapped in a `try/finally` that prints a `[PERF active.reservoir]` timing breakdown.
  - `_activate_reservoir_rep(self, node_id)` → `(rep_block_path, rep_type, rep_source)` — resolves the rep node, sets `active_representation_path` / `active_representation_has_properties`, and (non-IjkGrid only) `SetActiveSource(rep_source)` + `controller.on_active_proxy_change()`. IjkGrid keeps its slicer flow and is never `SetActiveSource`d here.
  - `_resolve_color_target_source(self, rep_block_path, rep_type, rep_source, active_view)` — picks the *visible* source to color. Non-IJK: prefers `rep_source`, falling back to the deepest visible threshold (`all_visible_thresholds`). IJK: per-grid priority order — visible threshold → `rep_data` extractor (`_src_extract_init`) → per-axis slicers (`_all_slice_sources`) → `slicervolume` (`_src_volumes`).
  - `_apply_color_for_active_property(...)` → timing tuple — the core ColorBy/LUT routine. Forces MTime advance + `UpdatePipelineInformation`/`UpdatePipeline`, queries the client-side VTK object directly for the array (Cell vs Point), re-applies ColorBy to all rep displays **only when the eye is open for this exact array** (`ui_active_array_by_rep[rep_block_path] == array_node_path`), swaps displays to per-view scene-scoped LUT/PWF via `source_resolver.swap_to_scene_tfs`, configures the scalar bar, and **rescales the LUT range LAST** directly from the VTK array (because other callers' internal rescale uses a stale proxy info cache and falls back to `[0,1]`).
  - `_debug_missing_array(...)` — diagnostic dump (cell/point array names, cell counts, extents, upstream input arrays) for the "array not found" case.
  - `_publish_active_color_state(self, node_id)` — for WELL/SURFACE tabs, publishes `active_color_array_name` / `active_property_kind` / `active_color_array_path` (and calls `update_color_editor`) so a wellbore LOG channel shows in colormap mode; clears them for non-property nodes. Does NOT re-color (the eye does that).
  - `_handle_surface_change(...)` / `_handle_well_change(...)` — lighter handlers: reject if not activatable, set the per-tab `*_type` state, call `_activate_rep_source` + `_publish_active_color_state`, or clear on empty.
  - `notify_active_reps(self, current_rep_paths)` — hides stale scalar bars for reps that dropped out of the selection, only when no remaining rep still uses the same array.
  - `refresh_active(self)` — re-runs the active-node handlers after a manual Show (when the rep didn't exist at `@state.change` time), guarded by `_is_node_active_able` to avoid wasted reject→reset→cleared→property churn.
  - `_activate_rep_source(self, node_id)` — surface/well version of `_activate_reservoir_rep`: sets rep path/has-properties and `SetActiveSource` on the registry source (IjkGrid never expected here).

**State.** Writes (many): `ptc_show_vcr`, `active_color_array_name`, `active_color_array_path`, `active_property_kind`, `coe_panels`, `active_representation_path`, `active_representation_has_properties`, `ui_active_node_reservoir_type_rep/type/title`, `ui_active_node_surface_type`, `ui_active_node_well_type`, and resets `ui_active_node_*` lists on rejection. Reads `ui_active_node_*`, `ui_select_node_*`, `ui_active_array_by_rep`, `nan_color`, `coe_panels`.

**Collaborators.** `Tree` (extensive `find_*` calls), `source_resolver` (from `engine`) for `scene_lut_for_view` / `swap_to_scene_tfs`, the injected `source_registry` and `ijk_lookup`, `pvsimple` (ColorBy/LUT/scalar bar/active source), `controller.on_active_proxy_change` / `on_data_loaded` / `update_color_editor`, and `make_valid_vtk_name`. Triggered by Trame `@state.change` on the three `ui_active_node_*` vars and by `refresh_active()`.

**Gotchas.**
- ColorBy ownership is the single biggest gotcha: activation does NOT color the geometry; the eye state (`ui_active_array_by_rep`) does. The handler re-applies ColorBy only when the eye is already open for that exact array — otherwise it just publishes panel state.
- Two long inline `NOTE:` comments warn against raw-writing `scalar_bar.Visibility` (lines ~598 and ~626): raw writes bypass `vtkSMTransferFunctionManager` bookkeeping and leave stale/duplicate bars on *other* views under per-view LUT scope. Bar visibility must go through `SetScalarBarVisibility` / the manager.
- The LUT range MUST be rescaled last and directly from the VTK array — the proxy info cache is stale for arrays added in-place by the C++ pipeline, so any earlier `RescaleTransferFunctionToDataRange` silently yields `[0,1]` (renders like Solid mode).
- `on_data_loaded()` is only called for time-series properties because it does expensive Vue work (~50–100 ms) only useful for resetting the time slider.
- `_GROUPING_KINDS` is duplicated here on purpose to avoid a circular import with `tree_views.py`; keep the two lists in sync.
- IJK source resolution deliberately never globs `pvsimple.GetSources()` — it goes through `ijk_lookup` per grid to avoid latching onto a sibling grid's slicer.
- Rejecting a node sets `ui_active_node_* = []`, which re-fires the handler on the next Trame flush through the "cleared" branch (two handler passes per rejection).

---

### `fespp_on_trame/app/core/tree.py`
**Responsibility.** Wraps the C++-built `vtkDataAssembly` and exposes Python lookup helpers. `set_tree()` re-parses the live assembly into the three Trame state lists (`ui_subtree_reservoir/surface/well`); everything else is read-only navigation.

**Key classes / functions.**
- Module helpers:
  - `_sibling_sort_key(node)` — case-insensitive, accent-stripped (NFKD), natural (numeric-aware) sort key by display title, with the `!!!PARTIAL!!!` prefix stripped. **Presentational only** — node identity everywhere else is by `id`/`path`, never list position.
  - `_eye_field(element_type)` — maps an `ElementType` to its eye token (`'rep'`/`'array'`/`'marker'`/`None`) via `element_type.eye_descriptor()`. Single source of truth replacing scattered JS `item.type !== 'Frame'` gates.
- `class Tree`
  - `__init__(self, data_assembly)` — stores the assembly, initializes the three hierarchy lists, and defines `_representation_type_in` — the list of kinds that count as "representations" (have a VTK source): `IjkGrid, Sub, UnstructuredGrid, Trajectory, Completion, Perfo, Frame, MarkerFrame, WellboreMarker, SeismicWellboreFrame, Grid2d, PointSet, Polyline, PolylineSet, TriangulatedSet, partial`. Note `Wellbore` is deliberately NOT a representation (it is a pure folder).
  - `add_subtreeview_data(self, parent_id, child_index, treeview_type, disabled=False)` — recursive walker building one child's nested treeview dict (`{"treeview": {...}, "treeview_type": str}`); reads `label`/`title`/`kind`/`propKind`/path, marks partials, routes unknown tab type from `kind` (or `supporttype` for partials), computes `rep_path`, `is_grouping`, `eye`, primary icon, `is_ts`/`is_mr` badges, `descendant_ids` (groupings only), and `disabled`. Sorts children with `_sibling_sort_key`. Skips internals of `MultiRealization`/`MultiRealizationTimeSeries` (they are leaves).
  - `_resolve_dispatch_kind(self, node_id)` — recurses into `Feature`/`Interpretation` grouping subtrees to find the first non-grouping descendant kind, used to route an alternate-hierarchy-mode top-level grouping to the right tab.
  - `set_tree(self, data_assembly)` — rebuilds the three `_data_hierarchy_*` lists from the assembly root, dispatching each top-level node to reservoir/surface/well (via `dispatch_kind`, resolving Feature/Interpretation through `_resolve_dispatch_kind`), then sorts and writes `state.ui_subtree_reservoir/well/surface`. Top-level items carry the SAME `is_grouping` / `descendant_ids` fields as `add_subtreeview_data`'s — `set_tree` used to omit them, so every top-level envelope (Wellbore folders, the GridContainer) rendered a plain binary checkbox while its nested folders showed the tri-state.
  - Navigation helpers (all read-only, return `None`/default for `node_id == 0` or null assembly): `find_ijkgrid(node_id)` (label of nearest IjkGrid ancestor), `find_parent_node_id_with_type(node_id, type)`, `find_first_child_of_type(node_id, type)`, `find_all_descendant_ids(node_id)`, `find_all_selectable_descendant_ids(node_id)` (excludes partials), `find_ijkgrid_property_name(node_label, list_selected)`, `find_path(node_id)`, `find_type(node_id)` (returns `kind`), `find_title(node_id)`, `find_label(node_id)`, `find_node_id(path)`, `find_representation_node(node_id)` (walk up to a `_representation_type_in` kind), `find_representation_type(node_id)`, `has_property_descendant(node_id)` (bool), `find_attribute_value(node_id, attr)`, `find_parent_attribute_value(node_id, attr)` (walk up).

**State.** `setdefault`s and writes `state.ui_subtree_reservoir`, `state.ui_subtree_surface`, `state.ui_subtree_well`.

**Collaborators.** `element_type` (`_et.for_kind`, `is_grouping`, `eye_descriptor`), `tree_icons.get_primary_icon`. The underlying `vtkDataAssembly` API (`GetChild`, `GetParent`, `GetAttributeOrDefault`, `GetNodePath`, `GetFirstNodeByPath`, `GetNumberOfChildren`). Used pervasively by `Selector`, `Activator`, the UI tree views, and the source/data layer.

**Gotchas.**
- `Wellbore` is intentionally excluded from `_representation_type_in` (it is a folder/grouping), while `Frame`/`MarkerFrame` ARE representations even though they render as folders in the tree ("folder for the tree, representation for the source") — this is the per-view source anchor for child logs/markers.
- `disabled` must be reset per top-level iteration in `set_tree` (a previous partial sibling must not latch `disabled=True` onto following siblings); `add_subtreeview_data` uses a per-node local `node_is_partial` flag so a partial rep's real descendants aren't wrongly disabled.
- Partial nodes (`kind in ('partial','Partial')`) get a `!!!PARTIAL!!!` title prefix and `disabled=True`; they are excluded from `find_all_selectable_descendant_ids` so a grouping's tri-state can still reach "all selected".
- `eye` in `set_tree` is keyed on the node's own `kind`, NOT `dispatch_kind` (dispatch_kind is only for tab routing).
- Many `find_*` methods silently return `None` for `node_id == 0` (the root) — callers must treat the root specially.
- Sorting only reorders the emitted dicts; do not assume sibling order matches the C++ assembly walk order.

---

### `fespp_on_trame/app/io/http_download.py`
**Responsibility.** Stream-download a single remote file into a directory and return the saved path.

**Key classes / functions.**
- `download_file_from_url(url: str, tmp_dir: str) -> str` — `requests.get(url, stream=True, timeout=60)`, `raise_for_status()`, derives the file name from `Content-Disposition` (regex on `filename`/`filename*`, URL-unquoted) or falls back to the last URL path segment (or `"downloaded_file"`), and `shutil.copyfileobj(r.raw, f)` into `Path(tmp_dir)/file_name`. Returns the path string.

**State.** None.

**Collaborators.** `requests`, `shutil`, `urllib.parse.urlparse`, `pathlib.Path`. Called from `__main__.py` in `remote_file` mode.

**Gotchas.**
- **Signature mismatch with its only caller.** This function expects a directory string `tmp_dir`, but `__main__.py` calls `download_file_from_url(app.remote_epc_file_location, epc_file_handle)` passing an **open file handle**, not a directory. `Path(file_handle)` will raise, so the remote-file download path in `__main__.py` is effectively broken as written — flag this before relying on remote mode.
- 60-second timeout applies to the connection/read; large files rely on streaming, not the timeout.
- `shutil.copyfileobj(r.raw, ...)` reads the raw stream and may not honor `Content-Encoding` decompression (a known `requests` caveat) — fine for already-binary EPC/H5.

---

### `fespp_on_trame/app/io/session_hooks.py`
**Responsibility.** Trame client-session lifecycle accounting: counts connected clients and drops the shared upload temp directory when the last one disconnects.

**Key classes / functions.**
- Module global `_active_clients` (int) — connected-client counter.
- `on_client_connected(**kwargs)` — increments the counter, prints status.
- `on_client_exited(**kwargs)` — decrements (floored at 0); when it hits 0, prints and calls `cleanup_temp_dir()` from `temp_dir`.

**State.** None (uses a module-global counter, not Trame state).

**Collaborators.** `temp_dir.cleanup_temp_dir`. Wired up in `engine.py` via `controller.on_client_connected.add(...)` / `controller.on_client_exited.add(...)`.

**Gotchas.**
- The counter is a process-global module variable — correct only for a single-process, single-`temp_dir` server. The module docstring notes `atexit` + SIGTERM/SIGINT handlers in `temp_dir.py` are the belt-and-suspenders for an unclean kill.
- Dropping the temp dir on last-disconnect means a reconnecting client would lose previously uploaded files.

---

### `fespp_on_trame/app/io/temp_dir.py`
**Responsibility.** Process-level boot side effects for file uploads: create the shared temp directory, register cleanup on shutdown signals/atexit, and tune the process for multi-GB EPC uploads.

**Key classes / functions.**
- Module global `temp_dir = mkdtemp()` — **created at import time**; shared by the upload endpoint (writer) and the engine's `load_epc_file` (reader).
- `cleanup_temp_dir()` — `shutil.rmtree(temp_dir, ignore_errors=True)` if it still exists, with logging.
- `_signal_handler(sig, frame)` — calls `cleanup_temp_dir()` then `sys.exit(0)`.
- `_setup_for_large_files()` — sets `PYTHONUNBUFFERED=1`, raises `RLIMIT_AS` soft limit to 8 GiB (only if hard is infinite or larger), and loosens GC via `gc.set_threshold(50, 5, 5)` + `gc.enable()`.
- Import-time side effects (bottom of file): `atexit.register(cleanup_temp_dir)`, `signal.signal(SIGTERM/SIGINT, _signal_handler)`, `_setup_for_large_files()`.

**State.** None.

**Collaborators.** `tempfile.mkdtemp`, `shutil`, `atexit`, `signal`, `resource` (POSIX-only, guarded by try/except), `gc`. `temp_dir` is imported by `upload_endpoint.register_upload_route`; `cleanup_temp_dir` is imported by `session_hooks`.

**Gotchas.**
- Merely importing this module creates a temp directory and installs SIGTERM/SIGINT handlers — non-obvious for a module named `temp_dir`. Forking code that imports it inherits these handlers.
- `resource` is Linux/macOS-only; on Windows the import fails and is swallowed by `except Exception` (prints an error but continues). The whole module is geared toward the Linux/Trame-container deployment.
- `RLIMIT_AS` is *lowered* to 8 GiB if the existing hard limit is higher/infinite — read this as a cap, not just a lift; multi-GB workloads near that ceiling could OOM.

---

### `fespp_on_trame/app/io/upload_endpoint.py`
**Responsibility.** Registers an aiohttp HTTP multipart endpoint (`/upload` and `/paraview/upload`) for uploading large EPC+H5 files into the shared temp dir, with live progress reporting and automatic EPC loading; also resolves the per-session upload URL prefix.

**Key classes / functions.**
- `register_upload_route(server) -> bool` — installs the endpoint via two patching strategies and a middleware. Internals:
  - `handle_upload(request)` (async) — sets `state.upload_uploading = True` / `upload_progress = 0`, streams each multipart field in 512 KiB chunks to `Path(temp_dir)/filename` (skipping existing files), updates `state.upload_progress` (capped at 99 during transfer) with `state.flush()`, collects `.epc` paths, sets progress to 100, then calls `controller.load_epc_file(path)` for each EPC. Returns JSON `{status, epc_paths}` or a 500 with the error message.
  - `upload_middleware(request, handler)` (aiohttp middleware) — routes `POST /upload` and `POST /paraview/upload` to `handle_upload`, else passes through. Logs each request with the app `id`.
  - **Patch 1** — monkey-patches `aiohttp_web.Application.__init__` so every future `Application` gets `upload_middleware` inserted as its first middleware (guarded against double-patching via `_fespp_orig_init`).
  - **Patch 2** — monkey-patches `aiohttp.web_runner.AppRunner.setup` to inject the middleware into the *effective serving app* (via the private `app._middlewares` tuple, since the public list is frozen) AND register the routes directly on the router (temporarily unfreezing `router._frozen`), as belt-and-suspenders. Guarded via `_fespp_orig_setup`.
  - Module global `_registered_handler` — holds the current `handle_upload` so Patch 2's route registration can reuse it.
- `resolve_upload_session_id(server) -> None` — reads `/opt/trame/proxy-mapping.txt`, finds the line whose second column ends with `:{port}` (port from `server._running_port` or `server.port`), and sets `state.upload_session_id` to that session id (empty if not found / file missing). The client uses this to build `/api/{sid}/upload`, falling back to `/upload`.

**State.** Writes `state.upload_uploading`, `state.upload_progress`, `state.upload_session_id`. Reads `server.state` / `server.controller` (specifically `controller.load_epc_file`).

**Collaborators.** `aiohttp.web` (`Application`, `AppRunner`, middleware/router internals), `temp_dir.temp_dir`, `controller.load_epc_file`. `register_upload_route` and `resolve_upload_session_id` are called from `engine.py`/server startup.

**Gotchas.**
- Heavy monkey-patching of aiohttp internals (`Application.__init__`, `AppRunner.setup`, `app._middlewares` tuple, `router._frozen`). The module docstring explains *why*: Trame creates several `aiohttp.Application` instances during startup and only the one `AppRunner.setup` wires up actually serves requests, so both a "patch all future apps" and a "patch the effective serving app" strategy are needed. This is brittle across aiohttp versions — a likely first break point on a dependency bump.
- Re-uploading a file that already exists in `temp_dir` is silently skipped (logged, but not re-saved or refreshed).
- Progress is intentionally capped at 99% during transfer and only set to 100 after all fields are read; the client must not treat 99 as complete.
- `state.flush()` is called inside the async upload loop to push progress mid-request — required because the normal Trame flush cycle wouldn't run during a long blocking upload.
- The session-id lookup is container-specific (`/opt/trame/proxy-mapping.txt`); outside the container it silently leaves `upload_session_id` empty.

---

### `fespp_on_trame/app/utils/search_node.py`
**Responsibility.** Stateless recursive lookups over a **flat/nested plain-dict tree** (the `ui_subtree_*`-style dicts), independent of the `vtkDataAssembly`.

**Key classes / functions.**
- `find_parent_id(tree, node_id)` — returns the `parent_id` of the node matching `node_id`.
- `find_item_node_id(tree, node_id)` — returns the matching node dict (top-level only — see gotcha).
- `node_id_to_path(tree, node_id)` — returns the node's `path`.
- `node_id_to_title(tree, node_id)` — returns the node's `title`.
- `node_id_to_type(tree, node_id)` — returns the node's `type`.
- `find_ijkgrid(tree, node_id)` — walks up via `find_parent_id` until it finds a node of type `IjkGrid`, returns its id.

**State.** None.

**Collaborators.** Operates purely on dict structures (the `treeview` dicts produced by `Tree`). No ParaView/Trame imports.

**Gotchas.**
- This is the older dict-walking sibling of `Tree`'s assembly-backed `find_*` methods; the assembly versions are authoritative. Prefer `Tree` for new code.
- `find_parent_id` and `find_item_node_id` are subtly buggy: `find_parent_id` recurses into `children` of the *first* node that has children even if the target isn't in that subtree (early `return` instead of continuing the loop), and `find_item_node_id` only checks top-level items (it does not recurse into `children` at all). `node_id_to_path/title/type` are written correctly (they continue scanning siblings). Audit before reuse.
- No file-level docstring; the comment banners are the only documentation.

---

### `fespp_on_trame/app/utils/color_palette.py`
**Responsibility.** Generate visually distinct solid colors for per-representation coloring, keyed by an integer index.

**Key classes / functions.**
- `color_for_index(i: int) -> str` — returns a `#RRGGBBAA` hex (alpha always `ff`). Hue is `(i * _GOLDEN_ANGLE) % 1.0` (golden-angle 137.508°/360 so successive multiples never align), saturation cycles through `_S_LEVELS = (0.85, 0.70, 0.95)` by `i % 3`, value through `_V_LEVELS = (0.85, 0.95, 0.75)` by `(i // 3) % 3`. Converts via `colorsys.hsv_to_rgb`.

**State.** None.

**Collaborators.** `colorsys`. Called by whatever assigns per-rep solid colors (the source/data layer).

**Gotchas.**
- The S/V cycle has period 9 (3×3) before reusing an (S,V) pair, but hue keeps advancing by the golden angle, so colors stay distinct well past 9; only after very large N do hues begin to crowd visually.
- Alpha is hard-coded opaque (`ff`); callers needing transparency must rewrite the last two hex chars.

---

### `fespp_on_trame/app/utils/naming.py`
**Responsibility.** Centralized name-sanitization for two *opposite* purposes — finding C++-produced VTK array names vs generating readable ParaView SM proxy registration names.

**Key classes / functions.**
- `make_valid_vtk_name(name: str) -> str` — **STRIPS** every char outside `[-.0-9A-Z_a-z]`, then prepends `_` when the result is empty or its first surviving char is a digit/`-`/`.`. Byte-for-byte mirror of FESPP C++ `MakeValidNodeName` (`ResqmlPropertyToVtkDataArray.cxx` / `...PartitionedDataSetCollection`). Returns `""` for empty/None. Use this to round-trip a RESQML title to its actual VTK array name (e.g. `"Pressure (PRESSURE)"` → `"PressurePRESSURE"`, `"123abc"` → `"_123abc"`).
- `sanitize_proxy_name(name: str) -> str` — **REPLACES** every char outside `[-.0-9A-Z_a-z]` with `_`. NOT a C++ mirror; for generating human-readable PV proxy registration names only.
- Module-level `_INVALID_CHAR_RE = re.compile(r"[^\-.0-9A-Z_a-z]")` shared by both.

**State.** None.

**Collaborators.** `re`. `make_valid_vtk_name` is used by `activator._find_array_in_store` and array-lookup code; `sanitize_proxy_name` by proxy-registration code in the source layer.

**Gotchas.**
- The two functions look almost identical but behave oppositely (strip vs replace). Mixing them up causes silent mismatches that only surface much later at array lookup or proxy registration. The module docstring is explicit: use `make_valid_vtk_name` for anything that must round-trip with a C++ name, `sanitize_proxy_name` ONLY for fresh proxy names you own.
- Do not add a third "compatibility" variant — the docstring deliberately forbids it.

---

### `fespp_on_trame/constants.py`
**Responsibility.** Hold a handful of process-wide constants.

**Key classes / functions.**
- `TRAME_APP_TITLE = "FESPP on TRAME"` — the browser/app title.
- `SOURCES_PATH = Path(__file__).parent` — the package root directory (`fespp_on_trame/`).
- `PUBLIC_PATH = Path("/deploy/public")` — absolute static-assets path (deployment-container-specific).

**State.** None.

**Collaborators.** `pathlib.Path`. `TRAME_APP_TITLE` is imported by `__main__.py` (set on `state.trame__title`); `SOURCES_PATH`/`PUBLIC_PATH` are consumed by the UI/static-serving layer.

**Gotchas.**
- `PUBLIC_PATH = Path("/deploy/public")` is a hard-coded absolute Unix path — it only exists in the deployment container. A fork running elsewhere must override it (or whatever serves statics from it will not find assets).

---

### `fespp_on_trame/__main__.py`
**Responsibility.** Process entry point and CLI: parses args, constructs the `App`, initializes the FESPP engine + UI, and (in remote mode) fetches EPC/H5 files before starting the Trame server.

**Key classes / functions.**
- `decode_url_base64(encoded_url)` — URL-safe base64-decodes a string to a UTF-8 URL (used to decode the `--remote-*-file-location` args).
- `@TrameApp() class App`
  - Type-annotated attributes: `local_epc_file_path: Path`, `remote_h5_file_location: str | None`, `remote_epc_file_location: str | None`, `mode: Literal["remote_file", "local_file"]`.
  - `__init__(self, server=None, *, fespp_plugin_path, local_epc_file_path, remote_h5_file_location, remote_epc_file_location)` — `get_server(server, client_type="vue3")`, sets `state.trame__title`, asserts the local EPC path exists, decides `mode` (remote requires *both* remote locations and asserts they differ; otherwise local), and calls `initialize_fespp_engine(server, fespp_plugin_path=...)`.
- `server_ready(**state)` — prints a ready banner; registered on `controller.on_server_ready`.
- `if __name__ == "__main__":` — builds the CLI (`--local-epc-file-path`, `--remote-epc-file-location`, `--remote-h5-file-location`, `--fespp-plugin-path` [required]), parses known args, registers `server_ready`, constructs `App`, and — in `remote_file` mode — uses a `contextlib.ExitStack` + `TemporaryDirectory` to open EPC/H5 file handles, download both via `download_file_from_url`, and call `controller.load_epc_file(epc_file_handle.name)`. In `local_file` mode the `load_epc_file` call is commented out. Finally calls `ui(app.server)` and `app.server.start()`.

**State.** Writes `state.trame__title` (via `App.__init__`).

**Collaborators.** `paraview.web.venv` (import-only, enables ParaView-in-a-venv), `initialize_fespp_engine`, `download_file_from_url`, `ui` (app layout), `TRAME_APP_TITLE`, `trame.app.get_server`, `trame_server.Server`, `trame.decorators.TrameApp`.

**Gotchas.**
- `App.__init__` calls `initialize_fespp_engine(server, ...)` passing the **parameter `server`** (which is `None` when invoked from the `__main__` block, since `App(app_server, ...)` is passed positionally as `server`) — wait: `app = App(app_server, ...)` passes `app_server` as the `server` positional arg, so `server` is non-None here. But note `initialize_fespp_engine` receives the raw `server` arg, NOT `self.server` (the `get_server(server, client_type="vue3")` result). If the engine relies on the vue3-configured server object, passing the raw arg is a latent inconsistency worth verifying against `engine.py`.
- The remote-file branch calls `download_file_from_url(url, epc_file_handle)` passing an **open file handle** where the function expects a directory string (`tmp_dir`). As written this raises — see `http_download.py`. Remote mode is effectively non-functional without a fix.
- The local-file load is commented out (`# app_server.controller.load_epc_file(...)`); local files are evidently loaded another way (e.g. via the upload endpoint) rather than at boot.
- The CLI treats the literal sentinels `${remote_h5_file_location}` / `${remote_epc_file_location}` (un-substituted template placeholders) as "not provided" (`None`) — a deployment-template artifact.
- `--local-epc-file-path` is not marked `required`, but `App.__init__` asserts it exists, so omitting it raises an `AssertionError` (or `AttributeError` on `None.exists()`).
