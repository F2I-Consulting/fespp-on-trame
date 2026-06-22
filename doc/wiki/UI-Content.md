# UI — Content area (views, dialogs, panels)

## Overview

The **content area** is everything in the main window below the top AppBar and to the right of the drawer. It is built by `fespp_on_trame/app/ui/content/content.py` (`Content`), which is mounted by the top-level layout orchestrator `fespp_on_trame/app/ui/app_layout.py`. The content area is a vertical flex column with three bands: a **tools band** at the top (global TimeControl, global RealizationPicker, Stats button, global-settings cog), the **multi-view** in the middle (a dockview-based grid of resizable / floating panels), and a collapsible **VTK log panel** at the bottom. A full-content busy overlay sits on top, and a thin progress strip sits at the bottom of the multi-view.

The heart of the subsystem is `FesppMultiView` (`content/view/multi_view.py`), a subclass of `ptc.MultiView` (itself a `trame_dockview.DockView`). It manages a set of dockview **panels**, each of which is one of five **kinds**: `render` (a ParaView `RenderView` with the loaded scene), `diff` (an A−B difference view computed inside the panel), and three HTML-only analytics panels — `stats`, `distribution`, `stats_compare`. Render panels carry per-view chrome (TimeControl, RealizationPicker, camera toolbar, view-link magnet, settings cog) and a large amount of per-view state bookkeeping so that splitting/replicating a view copies visibility, coloring, thresholds, slices, markers, and LUTs. Cross-cutting concerns layered around the multi-view are: **scope-aware editors** (Z-scale, background, orientation) shared between the *global* settings dialog and the *per-view* settings dialog; **camera linking** between views via a per-panel magnet menu; and per-view vs legacy-global state mirroring so the older flat-state consumers keep working while the new per-(rep, view) model is phased in.

A recurring architectural pattern to internalize before forking: many editors and toolbars are **scope-aware**. A single class (e.g. `TransformationEditor`, `BackgroundEditor`, `OrientationEditor`) is instantiated twice — once bound to `state.settings_scope` (locked to `"global"`) for `GlobalSettingsDialog`, and once bound to `state.view_settings_target_id` (a panel id) for `ViewSettingsDialog`. The class reads the scope state var at call time and decides whether to fan out to every render view or target a single panel. There is also a persistent **legacy-vs-per-view duality**: older flat state vars (`ui_hidden_rep_paths`, `ui_active_array_by_rep`, `time_index`, `interaction_mode`) coexist with per-view dict variants (`ui_hidden_rep_paths_by_view`, `ui_active_array_by_rep_by_view`, namespaced `time_index_<panel>`). `FesppMultiView._mirror_active_hidden_state` copies the active panel's per-view buckets back onto the flat globals on every panel switch.

---

### `fespp_on_trame/app/ui/app_layout.py`
**Responsibility.** Top-level UI orchestrator. Declares layout-wide state defaults, injects global styles + client scripts, and mounts the four UI zones (toolbar / drawer / content) plus shared snackbars inside a `SinglePageWithDrawerLayout`.

**Key classes / functions.**
- `ui(server: Server, **kwargs) -> None` — module-level builder (not a class). Creates a `LocalFileManager` over `PUBLIC_PATH` and registers the `logo` asset. Opens `SinglePageWithDrawerLayout(server, width=("drawer_width", 500))`, sets the title to `TRAME_APP_TITLE`, calls `inject_global_styles()`. Constructs the **owned dialogs** `ImportDialog(state, controller)` (referenced by the toolbar's import button) and `DisplayOptionsDialog()` (cog lives in the drawer band but rendered at layout level so it overlays the whole window). Builds the single shared `TreeViews(controller, state, engine._tree)` instance — the same `engine._tree` is reused so the engine can walk the assembly for dependency expansion. Mounts `Toolbar(local_file_manager, import_dialog).render()` into `layout.toolbar`, `Drawer(tv).render()` into `layout.drawer`, and `Content(server, state, controller).render()` into `layout.content`. Sets `layout.toolbar.v_if = ("toolbar_visible", True)` so the AppBar fully **unmounts** when hidden (so Vuetify recomputes `--v-layout-top` to 0 and `VMain` reclaims the space — a `display:none` would not). Renders the floating "show top toolbar" chevron `VBtn` at the layout root (double-down `mdi-chevron-double-down`, position:fixed top-right, `v_if="!toolbar_visible"`; same corner as the toolbar's double-up collapse chevron), then `display_options_dialog.render()`, `inject_client_scripts()`, `HierarchySnackbar().render()`, `EmptyColorSnackbar().render()`. Returns `layout`.

**State.**
- **Writes (module-level defaults):** `dialog_visible` (=True — boot with the Import Data dialog open), `execute_action`, `ui_time_label`, `drawer_width` (=500), `init_height_dataexplorer` (`"50vh"`), `init_height_attribute` (`"600px"`), `toolbar_visible` (=True).
- **Reads (in templates):** `toolbar_visible`, `drawer_width`.

**Collaborators.** Imports `engine` (for `engine._tree`), the zone classes `Toolbar`, `Drawer`, `TreeViews`, `Content`, the layout-level dialogs `ImportDialog` / `DisplayOptionsDialog`, the shared `inject_global_styles` / `inject_client_scripts`, and the snackbars. Entry point: this `ui()` is the function passed to the trame server as the UI builder.

**Gotchas.**
- Comment in the file documents the dialog-ownership split: `ImportDialog` + drawer-band `DisplayOptionsDialog` are owned here (their triggers live elsewhere but they must overlay the window); the **five content dialogs live inside `Content`**, not here.
- The drawer width is set once; live resize is done client-side (`shared/scripts.py`) to avoid a trame round-trip per drag step.
- The floating show-toolbar chevron is anchored at the **viewport top-right** specifically because the drawer always occupies the left edge — that's the only spot guaranteed not to be clipped by the drawer/VMain/dockview. Its presence at top-right is why several per-panel chrome elements (`_render_panel_actions`, the settings cog) reactively shift left by ~48px when `toolbar_visible` is false.

---

### `fespp_on_trame/app/ui/content/content.py`
**Responsibility.** Builds the entire content area below the toolbar and wires the multi-view's controller hooks. Owns the five content-area dialogs.

**Key classes / functions.**
- `class Content` — `__init__(self, server, state, controller)` stashes `server` and constructs the five owned dialogs: `AddViewDialog()`, `DiffColorsDialog()`, `GlobalSettingsDialog(state, controller)`, `ViewSettingsDialog()`, `NewViewContentDialog()`.
- `render(self)` — renders `BusyOverlay()`, then a flex-column `html.Div` (height/width 100%) containing `ToolsBand().render()`, `self._render_view_area()`, and `VtkLogPanel().render()`.
- `_render_view_area(self)` — wraps the multi-view in a `position:relative; overflow:hidden; min-height:0` div. Instantiates `FesppMultiView(ctx_name="multi_view", ready=lambda: self._server.context.multi_view.add_view())` — `ctx_name="multi_view"` registers the instance on `server.context.multi_view` (how every other file reaches it), and the `ready` callback fires the first `add_view()` once the dockview client is ready. Then renders the five dialogs and `BusyProgressBar()`. Finally wires controller hooks: `ctrl.view_replace = multi_view.replace_active`, `ctrl.view_update = multi_view.update_active`, `ctrl.view_update_all = multi_view.update_all`, `ctrl.view_reset_camera = multi_view.reset_camera_active`, and `ctrl.on_server_ready.add(ctrl.view_update)`.

**State.** None directly (delegates to children).

**Collaborators.** Imports `FesppMultiView`, the five dialogs, and the widgets `ToolsBand`, `BusyOverlay`, `BusyProgressBar`, `VtkLogPanel`. Called by `app_layout.ui()` inside `with layout.content:`.

**Gotchas.**
- The multi-view's `ready` callback creates the **first** panel — that first `add_view()` adopts the pre-existing active RenderView (created at engine import) rather than spawning a new one (see `FesppMultiView`).
- The controller hooks created here (`view_update`, `view_update_all`, etc.) are the canonical way server-side code pushes fresh frames to clients; `view_update` targets only the **active** panel while `view_update_all` broadcasts to every panel.

---

### `fespp_on_trame/app/ui/content/view/multi_view.py`
**Responsibility.** The dockview-backed multi-panel viewport manager. Owns panel lifecycle (create/close/activate), the five panel kinds, scene replication, per-view state seeding/mirroring, camera-link broadcast, and all per-panel overlay chrome.

**Key classes / functions.**
- `ViewKind = Literal["render", "diff", "stats", "distribution", "stats_compare"]` — the five panel kinds.
- `class FesppMultiView(ptc.MultiView)` — `__init__(self, namespace_prefix="time_view", **kwargs)` initializes per-panel registries `_html_views`, `_panel_titles`, `_panel_kinds` (dicts keyed by panel id), `_active_panel_id`, `_first_view_adopted` (False), `_diff_panel_id`, `_stats_panel_id`. Calls `super().__init__` then `setdefault`s the public state vars `fespp_render_panels` (list, drives the tree's per-render eye chips), `fespp_active_panel_id`, `fespp_active_panel_title`, `view_links` (camera-link groups). The base class registers dockview events `active_panel → _on_view_activated` and `remove_panel → _on_view_closed`.
- `add_view(self, kind="render", replicate=None, title=None, direction="within", reference_panel_id=None)` — the central factory. Increments `self._view_count`, derives `panel_id = f"ptc_view_{N}"` + `template_name`. Default titles per kind ("Diff"/"Stats"/"Distribution"/"Compare stats"/`"View {N}"`). **Branches early** to `_add_stats_panel` / `_add_distribution_panel` / `_add_stats_compare_panel` for the HTML-only kinds (no PV view). For render/diff: the very first call adopts `pvsimple.GetActiveViewOrCreate("RenderView")` (sets `_first_view_adopted`); subsequent calls pick the reference view from `reference_panel_id` → `_active_panel_id` → first known, and `pvsimple.CreateRenderView()`. Registers `pv_view` in `_pv_internal[panel_id]`, calls `MakeRenderWindowInteractor(True)`. Hooks `scene_registry.add_view(panel_id, pv_view)` + `sync_loaded_reps(...)`. Default `replicate = (kind=="render")`. When replicating, calls `_replicate_visibility(ref_view, pv_view)` and `scene_registry.replicate_view(...)`; for empty render views calls `_force_hide_all_sources(pv_view)`. Seeds per-view buckets via `_seed_per_view_hidden_state(...)` and `scene_registry.apply_visible_markers(panel_id)`. Records title/kind; for diff sets `_diff_panel_id` + `state.fespp_diff_panel_id`. Builds the panel template inside a `DivLayout(self.server, template_name)`: a `paraview.VtkRemoteView` (interactive_ratio 0.5, quality 60, **namespaced** per view, listening on the vtk.js `EndAnimation` event → `_sync_camera_from(panel_id)`), the active-panel chrome (blue inset border + "ACTIVE" pill, reactive on `fespp_active_panel_id`), and either `_render_diff_chrome` (diff) or `_render_panel_time_control` + `_render_panel_realization_picker` + `_render_panel_camera_chrome` (render). Render panels also get `_render_panel_actions`. Positions the panel via `self.add_panel(...)` — `direction != "within"` passes `position={"direction", "referencePanel"}` to dockview. First panel sets active state. When replicate+render, calls `controller.apply_panel_coloring(panel_id)`, mirrors LUT/PWF via `scene.replicate_tfs_from`, re-enforces visibility via `_enforce_view_visibility_from_ref`, then renders + pushes a frame. Ends with `_publish_panels_state()`. Returns `panel_id`.
- `_publish_panels_state(self)` — rebuilds `state.fespp_render_panels` (render kind only) and `state.fespp_settings_scopes` (`Global` + every render/diff panel). Keeps `fespp_active_panel_title` in sync after a rename. Empty render panels are still listed (their chips appear closed).
- `_seed_per_view_hidden_state(self, panel_id, ref_panel_id, kind="render", replicate=True)` — initializes the four per-view buckets for a new panel: `ui_hidden_rep_paths_by_view`, `ui_active_array_by_rep_by_view`, `ui_active_realization_by_array_by_view`, `ui_visible_marker_paths_by_view`. Diff → all empty; empty render (`replicate=False`) → hidden bucket = **every loaded rep** (so all tree chips appear closed); replicate-from-ref → copy the ref's buckets; first view → seed from the legacy flat vars (`ui_hidden_rep_paths`, `ui_active_array_by_rep`).
- `_add_stats_panel / _add_distribution_panel / _add_stats_compare_panel` — build the HTML-only kinds as **floating** dockview overlays. Stats is a **singleton** (tracks `_stats_panel_id` + `state.fespp_stats_panel_id`, floating 1400×450, has minimize/maximize chrome bound to `ui_stats_panel_minimized` / `ui_stats_panel_maximized`); Distribution is **multi-instance** (floating 900×550, no singleton tracking; body `DistributionPanel(panel_id)`); Compare-stats is **multi-instance singleton-per-property** (floating 1100×600; body `StatsComparePanel(panel_id)`; dedup handled by `boot._open_compare_stats` via `state.ui_stats_compare_panel[array_path]`).
- `_on_view_closed(self, panel_id)` — overrides the base; **captures `panel_kind` before popping** (a prior bug popped first, so kind-gated cleanup never ran). Pops the registries, calls `scene_registry.remove_view`, drops the panel's per-view buckets and its `view_links` entries (symmetrically), reassigns `_active_panel_id`, clears `_diff_panel_id` / `_stats_panel_id` + their state vars, and for distribution/stats_compare nulls out every per-panel suffixed state var, the singleton maps (`ui_distribution_contexts`, `ui_stats_compare_dist_panel`, `ui_stats_compare_panel`) and the registered controller method. Calls `_publish_panels_state()` then `super()._on_view_closed(panel_id)`.
- `_on_view_activated(self, panel_id)` — sets `_active_panel_id` and publishes `fespp_active_panel_id` / `fespp_active_panel_title`. **Returns early** (no PV-active sync, no legacy mirror) for diff / stats / distribution / stats_compare panels. For render panels: `_mirror_active_hidden_state()` then `super()._on_view_activated(panel_id)`.
- `_mirror_active_hidden_state(self)` — copies the active panel's `ui_hidden_rep_paths_by_view[active]` → flat `ui_hidden_rep_paths` and `ui_active_array_by_rep_by_view[active]` → flat `ui_active_array_by_rep`, so legacy flat-state consumers see the active view.
- `get_or_create_diff_view(self, direction="within", reference_panel_id=None) -> (panel_id, pv_view)` — returns the singleton diff panel, creating it if absent (`direction`/`reference_panel_id` honored only on first creation).
- `get_pv_view(panel_id)` / `get_html_view(panel_id)` / `active_html_view()` / `active_pv_view()` — public accessors.
- `update_active / update_all / reset_camera_active / replace_active` — the controller-hook implementations (active-only vs broadcast frame pushes; camera reset; view replace).
- `_sync_camera_from(self, panel_id, *_)` — bound to each view's `EndAnimation` (mouse release). Copies `CameraPosition`, `CameraFocalPoint`, `CameraViewUp`, `CameraParallelScale`, `CameraViewAngle`, **and `CenterOfRotation`** from `panel_id`'s view to every view in `state.view_links[panel_id]`, then renders + pushes each. No-op when there's no link or fewer than 2 views.
- `_REPLICATED_DISPLAY_PROPS` (tuple) + `_copy_display_props(src_disp, dst_disp)` — field-wise copy of non-color display props (Representation, Opacity, colors, Scale, BlockSelectors, opacity arrays, etc.). **Deliberately omits** `ColorArrayName` / `LookupTable` / `ScalarOpacityFunction` / `MapScalars` (copying them field-wise leaves PV6 in a hybrid SolidColor+outline state; full coloring is re-applied by `apply_panel_coloring`).
- `_is_per_view_source(src_name) -> bool` — name-based detection of per-view proxies (substring match against any tracked panel id) so they're never wired into another view's display list (avoids phantom outlines).
- `_force_hide_all_sources(new_view)` / `_enforce_view_visibility_from_ref(ref_view, new_view)` / `_replicate_visibility(ref_view, new_view)` — visibility plumbing for empty / replicated views. `_replicate_visibility` does it in **two phases** (create displays + copy non-color props, then enforce Visibility in a second pass) so a Show/Hide side effect can't flip a sibling. All three skip `fespp_diff*` sources and per-view proxies.
- `_render_panel_realization_picker / _render_panel_time_control / _render_panel_camera_chrome / _render_panel_actions / _render_diff_chrome` — per-panel overlay builders (described under Gotchas).

**State.**
- **Writes:** `fespp_render_panels`, `fespp_settings_scopes`, `fespp_active_panel_id`, `fespp_active_panel_title`, `view_links`, `fespp_diff_panel_id`, `fespp_diff_ready`, `fespp_stats_panel_id`, `ui_hidden_rep_paths_by_view`, `ui_active_array_by_rep_by_view`, `ui_active_realization_by_array_by_view`, `ui_visible_marker_paths_by_view`, the flat mirrors `ui_hidden_rep_paths` / `ui_active_array_by_rep`, per-panel `show_panel_tc_<id>` / `show_panel_mr_<id>`, and (on close) the distribution/compare per-panel suffixed vars + singleton maps.
- **Reads:** `ui_loaded_rep_paths`, the legacy flat hidden/active maps (for first-view seeding), `view_links`, the per-view buckets, and (in templates) `panel_has_ts_by_id`, `panel_has_mr_by_id`, `ui_panel_active_mr_specs_by_id`, `toolbar_visible`, `fespp_diff_*`.

**Collaborators.** Subclass of `ptc.MultiView` (→ `trame_dockview.DockView`, providing `add_panel`, `set_panel_title`, `active_panel`/`remove_panel` events). Reaches `server.context.scene_registry` for per-(rep, view) state. Calls controllers `apply_panel_coloring`, `register_per_view_time_label`, `compute_diff` (via `self.ctrl`), `view_update_all`. Composes the widgets `FesppTimeControl`, `PerViewRealizationPicker`, `ViewLinkMenu`, `PerViewCameraToolbar`, and the panel bodies `DescriptiveStatsPanel` / `DistributionPanel` / `StatsComparePanel` (lazy-imported to avoid circular imports at module load). Instantiated by `Content._render_view_area` with `ctx_name="multi_view"`.

**Gotchas.**
- **First-view adoption:** the first `add_view()` adopts the engine's pre-existing RenderView (so `engine._view` stays panel 1). Forgetting this and calling `CreateRenderView` instead would orphan the engine's captured view.
- **Camera sync is manual, on mouse release** (`EndAnimation`), not `AddCameraLink` — the SM camera link forces a per-frame re-render of every linked view and is unusable interactively. `CenterOfRotation` *must* be part of the copied params or rotation pivots desync.
- **Per-view proxy phantom outlines:** calling `GetDisplayProperties(per_view_src, view=other_view)` lazily creates a default `Visibility=1 Representation='Outline'` display in the wrong view. `_is_per_view_source` guards every visibility loop against this. This is why `_copy_display_props` omits color props and `apply_panel_coloring` re-applies them through `pvsimple.ColorBy`.
- **Diff panel is never PV's active view.** `_on_view_activated` short-circuits for the diff panel so tree eye-clicks keep acting on render views; pushing the diff panel's empty buckets onto the flat globals would clear ColorBy on the previous render panel (visible as a render view going SolidColor when clicking the diff tab).
- **HTML-only panels have no `pv_view`** — `_on_view_activated`/`_on_view_closed` must special-case them or `super()` dereferences a missing view and crashes.
- **`_render_panel_actions` buttons overflow up into the dockview tab row** (negative `top`, relying on an `overflow: visible` CSS rule forced on `.dv-content-container` in `shared/styles.py`). They `stopPropagation` on `mousedown`/`click` so dockview doesn't interpret the click as a tab-activation. The "Split right/below" buttons are commented out — the grid-split add-view path is WIP.
- **Per-panel TC/MR overlays** are reactive on `panel_has_ts_by_id` / `panel_has_mr_by_id` (recomputed engine-side) AND a per-panel user toggle `show_panel_tc_<id>` / `show_panel_mr_<id>`. The MR picker's vertical position depends on whether the TC is showing (top:52px vs top:4px).
- **`set_panel_title`** (called from `ViewSettingsDialog`) is provided by the dockview base widget, not defined in this file; the rename hook also mutates `_panel_titles` directly + re-publishes.
- The `_seed_per_view_hidden_state` docstring warns: the active-realization bucket *must* mirror the active-array bucket on replicate, or an MR property carried over without its idx makes `apply_color_array` look up the unsuffixed name (gone — MRs are suffixed `_real_<idx>`) and the view falls back to SolidColor.

---

### `fespp_on_trame/app/ui/content/dialog/add_view_dialog.py`
**Responsibility.** Single-step picker (triggered by the floating "+" button) choosing the kind of panel to add (render / diff) and where to place it relative to the active panel.

**Key classes / functions.**
- Module constants: `_KIND_RENDER="render"`, `_KIND_DIFF="diff"`, positions `_POS_TAB="within"`, `_POS_RIGHT="right"`, `_POS_BELOW="below"`.
- `class AddViewDialog` — `__init__` grabs server/state/controller and `setdefault`s `add_view_dialog_visible` (False), `add_view_kind` (render), `add_view_position` (within).
- `render(self)` — a `VDialog` (max 420) with a `VRadioGroup` (Render / Diff — Diff disabled when fewer than 2 loaded properties), a `VBtnToggle` for Tab/Right/Below position, and Cancel / Add buttons. Add → `_on_add`.
- `_on_add(self)` — reads `add_view_kind` + `add_view_position`. For diff: resets `diff_array_a_path`/`diff_array_b_path`/`diff_compute_error`/`fespp_diff_ready` then calls `multi_view.get_or_create_diff_view(direction=...)`. Otherwise `multi_view.add_view(kind="render", direction=...)`. Closes the dialog.

**State.** Writes `add_view_dialog_visible`, `add_view_kind`, `add_view_position`, and (diff reset) `diff_array_a_path`, `diff_array_b_path`, `diff_compute_error`, `fespp_diff_ready`. Reads `diff_array_choices` (in template, for the disable gate).

**Collaborators.** `server.context.multi_view` (`add_view` / `get_or_create_diff_view`). Rendered by `Content`. The "+" trigger lives in the dockview right-header actions (`ptc-multiview-add`) defined in the ptc base.

**Gotchas.** Diff radio + the diff path here are partially superseded by `NewViewContentDialog` (the per-panel `+Right`/`+Below` flow), but `AddViewDialog` remains the floating "+" entry. The diff option needs ≥2 loaded properties on the same grid.

---

### `fespp_on_trame/app/ui/content/dialog/diff_colors_dialog.py`
**Responsibility.** A dialog wrapping a full color/opacity editor bound to the diff calculator's output array `fespp_diff_value`, for tuning the diff view's LUT/PWF.

**Key classes / functions.**
- Constants `_DIFF_ARRAY_NAME="fespp_diff_value"`, `_DIFF_CALC_NAME="fespp_diff"`.
- `class _DiffColorOpacityEditor(_FesppColorOpacityEditor)` — overrides `get_representation_color_array_name()` → `["CELLS", "fespp_diff_value"]`; `_should_apply_state_change()` → only while `diff_colors_dialog_visible` (inverse of the drawer editor's gate, so the two never both write a shared LUT in one mutation); `update_scalar_range()` → defensive variant returning `[0,0]` when `fespp_diff_value` doesn't yet exist on the active source.
- `class DiffColorsDialog` — `__init__` stores `_coe`, `_prev_active_view`, `_prev_active_source`. `render(self)` builds the `VDialog` (`diff_colors_dialog_visible`, max 720, scrollable), instantiates `self._coe = _DiffColorOpacityEditor()`, and registers two handlers:
  - `controller.refresh_diff_color_editor` (`_refresh`) — pulls `fespp_diff_value`'s LUT/OTF into the editor state vars (`update_scalar_range`, `update_colors`, `update_opacities`, `_apply_nan_color_to_lut`). Called after `compute_diff` and on dialog open.
  - `@state.change("diff_colors_dialog_visible")` (`_on_visible`) — on open, snapshots the current active view/source, then sets PV active source = the `fespp_diff` calculator and active view = the diff panel's PV view (`mv._diff_panel_id` → `mv._pv_internal[...]`), then `refresh_diff_color_editor()`. On close, restores the snapshotted active view/source.

**State.** Reads/writes `diff_colors_dialog_visible`; the embedded editor manages `scalar_range`, color/opacity state vars.

**Collaborators.** `_FesppColorOpacityEditor` + `_apply_nan_color_to_lut` from the drawer's `color_editor`. `pvsimple` for LUT/OTF + active proxy management. `server.context.multi_view` for the diff panel's PV view. Opened by the diff panel's palette button (`diff_colors_dialog_visible = true`).

**Gotchas.** The embedded editor reads its scalar range / RGBPoints off `GetActiveSource`/`GetActiveView`, so the dialog **must** repoint those to the diff calc + diff view while open and **restore** them on close — otherwise subsequent tree clicks silently keep acting on the diff view. Reaches private members `mv._diff_panel_id` / `mv._pv_internal`.

---

### `fespp_on_trame/app/ui/content/dialog/global_settings_dialog.py`
**Responsibility.** Modal (from the tools-band cog) hosting the three scope-aware editors locked to **global** scope — Transformation (Z-scale), Orientation, Background. No dialog-level Apply/Cancel; each editor commits on its own.

**Key classes / functions.**
- Constants `_SCOPE_VAR="settings_scope"`, `_GLOBAL="global"`.
- `class GlobalSettingsDialog` — `__init__(self, state, controller)` `setdefault`s `global_settings_dialog_visible` (False) and `settings_scope` (`"global"`), registers `controller.global_settings_open = self.open`, and constructs `TransformationEditor(scope_var="settings_scope")`, `OrientationEditor(scope_var="settings_scope")`, `BackgroundEditor(scope_var="settings_scope")`.
- `open(self)` — re-asserts `settings_scope="global"` then shows the dialog.
- `close(self)` — hides it.
- `render(self)` — `VDialog` (max 560) with a title bar (× → close) and the three editors separated by dividers.

**State.** Writes `global_settings_dialog_visible`, `settings_scope`.

**Collaborators.** The three editors. Opened by `ToolsBand._render_settings_cog` via `controller.global_settings_open`.

**Gotchas.** `settings_scope` is **hardcoded** to `"global"` (the old per-view VSelect was removed); `open()` re-asserts it every time so a stale per-view value can't leak. Per-view variants of these settings live in `ViewSettingsDialog`.

---

### `fespp_on_trame/app/ui/content/dialog/new_view_content_dialog.py`
**Responsibility.** Content picker for a newly-spawned (split) view: Copy parent scene / Empty scene / Diff scene. Opened by the per-panel `+Right`/`+Below` buttons.

**Key classes / functions.**
- `class NewViewContentDialog` — `__init__` `setdefault`s `new_view_dialog_visible` (False), `new_view_dialog_direction` ("right"), `new_view_dialog_reference_id` (""), `new_view_dialog_reference_title` (""), and registers `controller.open_new_view_dialog = self.open_for`.
- `open_for(self, direction, reference_panel_id)` — pre-fills direction + reference id, looks up the reference title from `mv._panel_titles`, shows the dialog.
- `close(self)` — hides it.
- `_multi_view(self)` — `server.context.multi_view`.
- `_add_copy / _add_empty / _add_diff` — each closes the dialog after calling `mv.add_view(kind="render", replicate=True/False, direction, reference_panel_id)` or `mv.get_or_create_diff_view(direction, reference_panel_id)` (diff also resets the diff selection/error/ready state vars first).
- `render(self)` — `VDialog` (max 500) with a dynamic title ("Add view below/to the right of '<ref>'") and three block buttons (each is the action — no Apply). The Diff button is disabled when fewer than 2 loaded properties.

**State.** Writes `new_view_dialog_visible`, `new_view_dialog_direction`, `new_view_dialog_reference_id`, `new_view_dialog_reference_title`, and (diff) `diff_array_a_path`/`diff_array_b_path`/`diff_compute_error`/`fespp_diff_ready`. Reads `diff_array_choices` (template gate).

**Collaborators.** `server.context.multi_view`. Opened via `controller.open_new_view_dialog` — but note the per-panel `+Right`/`+Below` trigger buttons in `multi_view._render_panel_actions` are **currently commented out**, so this dialog is wired but not reachable from the UI in the current build.

**Gotchas.** When a diff panel already exists, `get_or_create_diff_view` reuses it and ignores `direction`/`reference_panel_id` (by design). Because the split buttons are disabled, this is effectively dormant code path kept for the WIP grid-split feature.

---

### `fespp_on_trame/app/ui/content/dialog/view_settings_dialog.py`
**Responsibility.** Per-panel settings dialog (opened by each panel's ⚙). Rename field + per-view variants of Transformation / Orientation / Background, all scoped to the target panel.

**Key classes / functions.**
- Constant `_SCOPE_VAR="view_settings_target_id"`.
- `class ViewSettingsDialog` — `__init__` `setdefault`s `view_settings_dialog_visible` (False), `view_settings_target_id` (""), `view_settings_rename_value` (""), `view_settings_target_title` (""). Registers `controller.open_view_settings = self.open_for`. Constructs `TransformationEditor(scope_var="view_settings_target_id")`, `OrientationEditor(scope_var="view_settings_target_id", mode_var="orientation_mode_view")`, `BackgroundEditor(scope_var="view_settings_target_id")`.
- `open_for(self, panel_id)` — looks up the title from `mv._panel_titles`, pre-fills `view_settings_target_id` / `view_settings_target_title` / `view_settings_rename_value`, shows the dialog.
- `close(self)` — hides it.
- `apply_rename(self)` — commits the rename: empty → no-op; otherwise calls `mv.set_panel_title(target, new_title)`, syncs `mv._panel_titles[target]`, calls `mv._publish_panels_state()`, and updates `view_settings_target_title` live.
- `render(self)` — `VDialog` (max 560), title shows `view_settings_target_title || view_settings_target_id`, then `_render_rename()` + the three editors.
- `_render_rename(self)` — a `VTextField` (autofocus) + Apply button, both committing via `apply_rename` (Enter and Apply commit **without** closing so the user can keep editing).

**State.** Writes `view_settings_dialog_visible`, `view_settings_target_id`, `view_settings_target_title`, `view_settings_rename_value`. The editors read `view_settings_target_id` as scope.

**Collaborators.** The three editors; `server.context.multi_view` (`set_panel_title`, `_panel_titles`, `_publish_panels_state`). Opened via `controller.open_view_settings` from `multi_view._render_panel_actions` (the ⚙ button).

**Gotchas.** The per-view `OrientationEditor` **must** use a distinct `mode_var` (`orientation_mode_view`); the global one uses the default `orientation_mode`. If they shared the var, both editors would react to the same `state.change` and the global one would broadcast to every view whenever the per-view toggle is touched. Same hazard exists implicitly for all three editors via the differing `scope_var`.

---

### `fespp_on_trame/app/ui/content/widget/background_editor.py`
**Responsibility.** Scope-aware "Background" section. Global scope → ParaView palette picker; per-view scope → ParaView-Properties-style controls (use-palette checkbox, color mode, color pickers) writing directly to the target view.

**Key classes / functions.**
- `_rgb_to_hex(rgb)` / `_hex_to_rgb(hex_str)` — convert between PV's 0–1 RGB triples and the `#rrggbb` strings `VColorPicker` emits.
- `class BackgroundEditor` — `SCOPE_GLOBAL="global"`. `__init__(self, scope_var="settings_scope")` `setdefault`s `bg_use_palette` (True), `bg_mode` ("Single Color"), `bg_color1` (`#5c6c7a`), `bg_color2` (`#1133aa`), and registers `state.change` handlers on `scope_var` + each `bg_*` var. `_syncing` re-entrancy guard.
- `_current_scope / _multi_view / _pv_view / _html_view / _render_and_push` — resolve the target view/html-view for the current scope and push a fresh frame.
- `_on_scope_change` — reads the target view's `UseColorPaletteForBackground` / `BackgroundColorMode` / `Background` / `Background2` and pushes them onto the `bg_*` state vars (guarded by `_syncing`).
- `_on_use_palette_change / _on_mode_change / _on_color1_change / _on_color2_change` — write the corresponding property back to the target view (`view.UseColorPaletteForBackground`, `view.BackgroundColorMode`, `view.Background`, `view.Background2`), `UpdateVTKObjects()`, then `_render_and_push()`. Each early-returns when `_syncing` or no per-view target.
- `render(self)` — emits the section header, a global subtree (`v_if scope==='global'`) hosting `ptc.PalettePicker`, and a per-view subtree (`v_if scope!=='global'`) with the checkbox + (when not using palette) the mode select + `_color_row` pickers.
- `_color_row(self, label, color_state)` — labelled `VColorPicker` popover (`close_on_content_click=False`, `mode="hex"`).

**State.** Writes/reads `bg_use_palette`, `bg_mode`, `bg_color1`, `bg_color2`; reads the scope var (`settings_scope` or `view_settings_target_id`).

**Collaborators.** `ptc.PalettePicker` (global), `pvsimple` (render), `server.context.multi_view` (per-view view lookup). Composed by both settings dialogs.

**Gotchas.** Global palette is applied via `simple.LoadPalette` (a global ParaView setting) and broadcast by the existing `on_data_change` handler — that's why the global subtree carries no per-view write logic. The `_syncing` flag is essential: without it, the scope-change read-back would re-trigger the per-var write handlers in a loop. Color pickers commit live (no debounce) while dragging because `close_on_content_click=False` keeps the popover open.

---

### `fespp_on_trame/app/ui/content/widget/orientation_editor.py`
**Responsibility.** Scope-aware "Orientation" section: a mutually-exclusive toggle between the **Camera Orientation Widget** and the **Orientation Axes** (XYZ marker), applied globally or to one panel.

**Key classes / functions.**
- `_safe_set(view, name, value)` — `setattr` swallowing exceptions (camera-widget property names vary across PV versions).
- `class OrientationEditor` — `SCOPE_GLOBAL="global"`, `MODE_CAMERA_WIDGET="camera_widget"`, `MODE_AXES="axes"`, `_WIDGET_DEFAULT_LOCATION="Bottom Left"`. `__init__(self, scope_var="settings_scope", mode_var="orientation_mode")` `setdefault`s `mode_var` (camera widget) and registers `state.change` on both `scope_var` and `mode_var`; `_syncing` guard.
- `_current_scope / _multi_view / _target_views` — yield `(panel_id, view)` for the views to apply to (global → every **render** panel, excluding diff/HTML kinds via `_panel_kinds`; per-view → the single targeted panel).
- `_read_mode(view)` — best-effort read (camera widget `Visible` takes precedence, else `OrientationAxesVisibility`).
- `_apply_mode(view, mode)` — sets one visibility on / the other off (`view.Visible`, `view.Location`, `view.OrientationAxesVisibility`) + `UpdateVTKObjects()`.
- `_render_and_push(panel_id=None)` — render + push to the matching client(s) (broadcast in global scope, single in per-view).
- `_on_scope_change` — pre-fills `mode_var` from a representative view (guarded by `_syncing`).
- `_on_mode_change` — applies the mode to every target view then `_render_and_push()`.
- `render(self)` — header + a 2-option `VBtnToggle` bound to `mode_var`.

**State.** Reads/writes `mode_var` (`orientation_mode` global / `orientation_mode_view` per-view); reads scope var.

**Collaborators.** `pvsimple`, `server.context.multi_view`, controllers `view_update` / `view_update_all`. Composed by both settings dialogs.

**Gotchas.** Per-instance `mode_var` is mandatory (see `ViewSettingsDialog`) — shared mode vars cause the global editor to broadcast on per-view toggles. Keeping both aids on at once is explicitly out of scope. Diff/HTML panels are excluded from `_target_views`.

---

### `fespp_on_trame/app/ui/content/widget/transformation_editor.py`
**Responsibility.** Scope-aware "Transformation" section: the Z-scale (vertical exaggeration) editor, wrapping `ptc.TransformEditor` with a FESPP-custom Apply that preserves coloring and handles markers specially.

**Key classes / functions.**
- `SCOPE_GLOBAL="global"`.
- `class TransformationEditor` — `__init__(self, scope_var="settings_scope")`. `render(self)` builds `ptc.TransformEditor(show_translation=False, show_scale=True, …, show_apply_button=True)`, hides the X/Y scale knobs (only Z matters), and binds `_apply_z_scale` to the Apply button.
- `_current_scope / _target_views` — resolve target views by scope (global → every render panel; per-view → one).
- `_proxy_reg_name(proxy)` (static) — registration name of a proxy across the `filters`/`sources` groups (per-(marker,view) extractors are registered `mrk_…`).
- `_rep_is_marker(rep, marker_ids)` (classmethod) — True when a representation is a marker glyph (input GlobalID in the scene-registry marker set OR registration name starts with `mrk_`).
- `_apply_z_scale(self)` — reads the editor's Scale, **persists** the Z value to `state.ui_scale_z` (so later-created sources inherit it), then for every visible rep on every target view: markers are **translated** in Z (`marker_dispatch.apply_marker_z`) not scaled (scaling turns a sphere into an "olive"); all other reps get `rep.Scale` / `rep.DataAxesGrid.Scale` / `rep.PolarAxes.Scale` set, with `ColorArrayName` + `LookupTable` saved and restored around the write. Finishes with render + `view_update_all` (or `view_update`).

**State.** Writes `ui_scale_z`; reads scope var.

**Collaborators.** `ptc.TransformEditor`, `pvsimple`, `server.context.scene_registry`, `marker_dispatch` (`marker_proxy_ids`, `apply_marker_z`), controllers `view_update` / `view_update_all`. Composed by both settings dialogs.

**Gotchas.** The save/restore of color around the `Scale` write exists because the Scale write was observed to clobber the active `ColorArrayName`/`LookupTable`. `ui_scale_z` is the **single global source of truth** for Z exaggeration — creation hooks and on-load re-apply read it; nothing wrote it before this widget existed, which is why later-loaded objects used to stay flat. Markers must never be scaled (see commit history about "olive").

---

### `fespp_on_trame/app/ui/content/widget/time_control.py`
**Responsibility.** Multi-view-aware TimeControl. Subclasses `ptc.TimeControl` but rebuilds its UI so every state binding is namespaced; two scopes (global = TimeKeeper, view = per-view `ViewTime`).

**Key classes / functions.**
- `_suffix(namespace)` — `""` → no suffix (ptc-default names, back-compat); `"panel_2"` → `_panel_2`.
- `class FesppTimeControl(ptc.TimeControl)` — class-level `_instances` registry of every live instance. `__init__(self, namespace="", scope="global", target_pv_view=None, target_html_view=None, time_expression=…, show_var="ptc_show_vcr", **kwargs)` validates scope, computes namespaced state-var names (`_sv_index`, `_sv_nb`, `_sv_value`, `_sv_play`, `_sv_speed`), **skips** `ptc.TimeControl.__init__` and calls `VCard.__init__` directly, builds the VCR buttons + speed menu + readout + slider (+ mixed-badge resync button on the global TC), registers `_on_index_change` on `_sv_index`, adds `refresh_from_keeper` to `on_data_loaded`, appends to `_instances`, and calls `refresh_from_keeper()`.
- `time_values` (property) — `GetTimeKeeper().TimestepValues`.
- `update(self, **_)` — overridden to a **no-op** (the ptc base's decorated handlers would re-fire on every instance and write the wrong scope's time).
- `_on_index_change` — `refresh_from_keeper(apply=True)`.
- `refresh_from_keeper(self, apply=False)` — recomputes `_sv_nb` / `_sv_value`, clamps `_sv_index`, and (if apply) calls `_write_time` + `on_data_change`.
- `_write_time(self, t)` — global: sets `TimeKeeper.Time`, broadcasts via `view_update_all`, syncs peer indices, clears `ptc_global_mixed`. view: skips if the view is already at `t`, else sets `view.ViewTime`, renders, pushes to that view's html-view, then sets `ptc_global_mixed = self._compute_mixed()`.
- `_compute_mixed()` — True iff any view-scope instance's `ViewTime` differs from `TimeKeeper.Time`.
- `resync_all()` — (global only) re-broadcasts the global index to every view.
- `_sync_peer_indices(index)` — pushes the index into every view-scope sibling's slider state.
- `first / last / previous / next / play / stop / _play_animation` — navigation against the namespaced state.

**State.** Writes/reads the namespaced `time_index{sfx}` / `time_nb{sfx}` / `time_value{sfx}` / `time_play{sfx}` / `speed_scale{sfx}`, plus `ptc_global_mixed`. The global instance (`namespace=""`) keeps the legacy unsuffixed names that `changeTimeLabel`/TimeSeries read.

**Collaborators.** `ptc.TimeControl` (grandparent `VCard`), `pvsimple` (TimeKeeper / view.ViewTime), controllers `on_data_loaded`, `on_data_change`, `view_update_all`. Instantiated globally by `ToolsBand` and per-panel by `multi_view._render_panel_time_control`. The per-view variant is registered with the engine via `controller.register_per_view_time_label`.

**Gotchas.** The default `time_expression` has a JS operator-precedence bug (`idx + 1` becomes string concat without parens) which this class fixes locally for namespaced vars without touching ptc. `_instances` is never cleaned up on panel close — iterating a stale instance only writes a dead state var (harmless). The view-scope `_write_time` short-circuit (skip if already at `t`) is what prevents an infinite loop when a global write propagates through `TimeKeeper` and triggers the per-view `_on_index_change`.

---

### `fespp_on_trame/app/ui/content/widget/realization_picker.py`
**Responsibility.** Multi-realization (MR) pickers — a per-view variant (one row per active MR property in a panel) and a global variant (one row dispatching to every panel that has the selected MR property active).

**Key classes / functions.**
- `class PerViewRealizationPicker` — `__init__(self, panel_id)`. `render(self)` builds a TimeControl-styled `VCard` bound to `ui_panel_active_mr_specs_by_id[panel_id]`; one row per spec with skip/prev/next/skip-last buttons, a direct-jump `VSelect`, and a `VSlider`. All controls fire `trigger('set_view_realization', [panel_id, spec.array_path, idx])`.
- `class GlobalRealizationPicker` — `render(self)` builds a single-row card: a property `VSelect` bound to `ui_global_mr_selected_path` (items from `ui_global_mr_specs`, orange when `mixed`), and buttons/index-select/slider bound to `ui_global_mr_selected_spec`, all firing `trigger('set_global_realization', [array_path, idx])`.

**State.** Reads `ui_panel_active_mr_specs_by_id`, `ui_global_mr_specs`, `ui_global_mr_selected_path`, `ui_global_mr_selected_spec`. Mutations go through the triggers (engine-side).

**Collaborators.** Triggers `set_view_realization` / `set_global_realization` (engine `boot`/`realization_dispatch`). Per-view instance composed by `multi_view._render_panel_realization_picker`; global by `ToolsBand._render_global_realization_picker`.

**Gotchas.** The realization domain may be **non-contiguous** (e.g. `{23, 24}`), so the **slider value is the position in `spec.available_indices`**, not the raw idx — the actual idx is looked up via `spec.available_indices[position]` before the trigger. The dropdown bypasses the position layer (items are raw indices). The global selector surfaces cross-panel divergence by coloring mixed items orange in both the closed-state and open menu (via slot templates).

---

### `fespp_on_trame/app/ui/content/widget/per_view_camera_toolbar.py`
**Responsibility.** Per-panel camera toolbar (reset / +X / +Y / +Z / 2D↔3D), scoped to a panel and every panel linked to it via `state.view_links`.

**Key classes / functions.**
- `class PerViewCameraToolbar` — `__init__(self, panel_id)` `setdefault`s `interaction_mode` ("3D").
- `_target_panel_ids()` — self + every linked panel that still exists in `_pv_internal` (filters orphaned link entries).
- `_iter_target_views()` — yields `(panel_id, pv_view, html_view)` for the broadcast group.
- `_reset_camera()` / `_orient(orient_call)` / `_orient_x/_y/_z` — apply the action to every target view (PV render + `html_view.reset_camera()`); `_orient` uses `view.ResetActiveCameraToPositiveX/Y/Z`.
- `_set_interaction_mode(mode)` — sets `pv_view.InteractionMode` on every target view, pushes frames, and writes the single global `state.interaction_mode`.
- `render(self)` — a vertical column of icon buttons; the 2D/3D toggle swaps icon based on `interaction_mode`.
- `_btn(...)` — one tooltipped icon button.

**State.** Writes/reads `interaction_mode`; reads `view_links`.

**Collaborators.** `pvsimple`, `server.context.multi_view` (`_pv_internal`, `_html_views`, `view_links`). Composed by `multi_view._render_panel_camera_chrome`, paired with `ViewLinkMenu`.

**Gotchas.** `interaction_mode` is **deliberately a single global var** (per-view tracking was judged not worth the UI cost) even though the mode write fans out per-view. The toolbar reaches the multi-view's private `_pv_internal` / `_html_views`.

---

### `fespp_on_trame/app/ui/content/widget/view_link_menu.py`
**Responsibility.** The magnet button + checklist menu that defines a render panel's camera-broadcast group by maintaining the symmetric `state.view_links` adjacency map.

**Key classes / functions.**
- `class ViewLinkMenu` — `__init__(self, panel_id)` `setdefault`s `view_links` ({}).
- `toggle_link(state, panel_a, panel_b)` (static) — symmetric add/remove of the A↔B link on both sides; prunes empty entries. Static so the engine can call it (e.g. to drop dangling links on close).
- `_on_toggle(other_panel_id)` — `toggle_link(self._state, self._panel_id, other_panel_id)`.
- `render(self)` — a `VMenu` whose activator is a magnet `VBtn` (blue when any link exists), listing one `VCheckbox` per *other* render panel (from `fespp_render_panels`), each bound to membership in `view_links[panel_id]` and toggling via `_on_toggle`.

**State.** Writes/reads `view_links`; reads `fespp_render_panels` (for the checkbox list).

**Collaborators.** Consumed by `PerViewCameraToolbar` and `multi_view._sync_camera_from` (which read `view_links`). Composed by `multi_view._render_panel_camera_chrome`. `_publish_panels_state` keeps `fespp_render_panels` current.

**Gotchas.** The symmetric invariant (A in `view_links[B]` ⇒ B in `view_links[A]`) is maintained here; orphan entries (referencing a closed panel) are filtered by consumers, and `_on_view_closed` also prunes them. The checkbox `v_for` sits on an outer `html.Div` (not the `VCheckbox`) so `p` stays reactive when Vue re-evaluates `model_value` on every `view_links` mutation.

---

### `fespp_on_trame/app/ui/content/widget/tools_band.py`
**Responsibility.** Top tools band above the multi-view holding only **global** widgets: centered global TimeControl + global RealizationPicker, right-aligned Stats button + global-settings cog.

**Key classes / functions.**
- Module-level `server` / `controller`.
- `class ToolsBand` — `render(self)` builds a flex row (spacers center the time/MR group), then `_render_global_time_control`, `_render_global_realization_picker`, `_render_stats_button`, `_render_settings_cog`.
- `_render_global_time_control()` — `FesppTimeControl(scope="global", namespace="", time_expression="ui_time_label")` inside a slot gated on `ptc_show_vcr`.
- `_render_global_realization_picker()` — `GlobalRealizationPicker().render()` gated on `ui_global_mr_specs.length > 0`.
- `_render_stats_button()` — a chart-box button (→ `controller.open_stats_panel`) shown only when `ui_stats_pinned_paths` is non-empty.
- `_render_settings_cog()` — the cog (→ `controller.global_settings_open`); `margin-right` shifts left 48px when `toolbar_visible` is false.

**State.** Reads `ptc_show_vcr`, `ui_global_mr_specs`, `ui_stats_pinned_paths`, `toolbar_visible`.

**Collaborators.** `FesppTimeControl`, `GlobalRealizationPicker`; controllers `open_stats_panel`, `global_settings_open`. Composed by `Content.render`.

**Gotchas.** The global TC uses `namespace=""` to preserve the legacy `time_index`/`time_value` names that `changeTimeLabel`/TimeSeries still read. The whole TC slot is `v_if`-collapsed when no TS is in play so the spacers don't leave a gap. The Stats button only appears once at least one property is pinned (otherwise the panel would just show its empty state).

---

### `fespp_on_trame/app/ui/content/widget/busy_overlay.py`
**Responsibility.** Full-content dim overlay blocking input during a trame state flush.

**Key classes / functions.**
- `class BusyOverlay` — `render(self)` emits a `VOverlay` bound to `trame__busy` (persistent, 70%-black scrim, centered).

**State.** Reads `trame__busy` (toggled automatically by trame).

**Collaborators.** Rendered by `Content.render` (first child). Companion of `BusyProgressBar`.

**Gotchas.** None beyond: `trame__busy` is trame-managed; this is the heavyweight cue (the progress bar is the lightweight one).

---

### `fespp_on_trame/app/ui/content/widget/busy_progress_bar.py`
**Responsibility.** Lightweight bottom progress strip inside the multi-view area (two indeterminate progress lines + an info alert), the lighter complement of `BusyOverlay`.

**Key classes / functions.**
- `class BusyProgressBar` — `render(self)` emits an absolutely-positioned bottom strip (`v_if trame__busy`) with two `ptc.VProgressLinear` + a `ptc.VAlert` showing `{{ view_loading_message }}`.

**State.** Reads `trame__busy`, `view_loading_message`.

**Collaborators.** Rendered by `Content._render_view_area` (inside the multi-view container so it overlays the 3D view, not the whole window).

**Gotchas.** Both this and `BusyOverlay` react to `trame__busy`; the difference is footprint (a few px at the bottom vs the full window).

---

### `fespp_on_trame/app/ui/content/widget/vtk_log_panel.py`
**Responsibility.** Collapsible bottom panel surfacing VTK/ParaView stderr messages captured by the engine's stderr tee.

**Key classes / functions.**
- `class VtkLogPanel` — `render(self)` emits a dark container (`v_show` on `vtk_log_messages.length > 0`) holding `_render_clear_button` + `_render_expansion_panel`.
- `_render_clear_button()` — an absolutely-positioned "Clear" button (`vtk_log_messages = []; $event.stopPropagation()`).
- `_render_expansion_panel()` — `VExpansionPanels` bound to `log_panel_open`.
- `_render_title()` — error/warning counts computed client-side via `filter()`.
- `_render_body()` — scrollable list (`id="vtk-log-container"`) of `vtk_log_messages` colored by `msg.level`.

**State.** Reads/writes `vtk_log_messages`; reads/writes `log_panel_open`.

**Collaborators.** Engine populates `vtk_log_messages` via its stderr tee. Auto-scroll handled by a MutationObserver in `shared/scripts.py` on `#vtk-log-container`. Rendered by `Content.render`.

**Gotchas.** The Clear button is an absolute child overlapping the expansion title; `$event.stopPropagation()` keeps clicking Clear from collapsing the panel. Counts are filtered client-side to avoid a round-trip per message.

---

### `fespp_on_trame/app/ui/content/panel/descriptive_stats_panel.py`
**Responsibility.** Body of the singleton Stats dockview tab — one card per pinned property, each with a multi-row stats table (Originals + per-view rows) and per-row controls (Real/Timestep dropdowns, pin, compare-cart toggle, histogram).

**Key classes / functions.**
- Module data: `_COLUMNS` (16 numeric stat columns), `_HAS_MR_KIND` / `_HAS_TS_KIND` (Vue gates), `_COL_WIDTHS` + `_NUMERIC_COL_WIDTH` (fixed px widths so cards line up under `table-layout: fixed`), `_TH_STYLE_BASE`.
- `_cell_expr(key)` — JS expression: NaN/null → `–`, integers intact, floats `toFixed(3)`.
- `_stat_columns_th()` / `_stat_columns_td()` — render the header `<th>` set (Cmp/Source/Realization Index/Time Step + numeric) and per-row numeric `<td>` cells.
- `class DescriptiveStatsPanel` — `render(self)` → `_render_empty_state` + (when `ui_stats_pinned_paths` non-empty) `_render_property_cards`.
- `_render_empty_state()` — hint shown when nothing is pinned.
- `_render_property_cards()` — `VCard` `v_for` over `ui_stats_pinned_paths`; reads `ui_stats_tables[array_path]`.
- `_render_card_header()` — title + kind icon/chips (TS clock, MR chip), a **Compare** button (`trigger('open_compare_stats', [array_path])`, disabled with <2 in cart), cart-count chip, row-count chip, and unpin `×` (`trigger('toggle_stats_display', [array_path])`).
- `_render_stats_table()` — header row + one body `<tr>` per `ui_stats_tables[array_path].rows`, keyed on `ui_stats_publish_version + row.kind + row.id` (forces Vue to see fresh values after each recompute).
- `_render_row_compare_cell()` — Cmp `⊕`/`✓` toggle (`trigger('stats_compare_toggle', …)`); only on MR/TS cards.
- `_render_row_source_cell()` — `row.label` + histogram button (`trigger('open_row_histogram', …)`) + pin/unpin (`trigger('stats_pin_original' / 'stats_unpin_original', …)`).
- `_render_row_realization_cell()` / `_render_row_timestep_cell()` — editable dropdowns on the default Original row of MR/TS cards (`trigger('stats_set_original_real_idx' / '…_ts_idx', …)`), static value elsewhere.

**State.** Reads `ui_stats_pinned_paths`, `ui_stats_tables`, `ui_stats_compare`, `ui_stats_publish_version`. All mutations go through triggers.

**Collaborators.** Triggers handled in the engine (`stats_dispatch`, `boot`); recompute via `stats_dispatch.publish_descriptive_stats`. Rendered by `multi_view._add_stats_panel`.

**Gotchas.** Realization Index and Time Step columns are **always** rendered (so cards align vertically), with the dropdown vs static value gated inside the cell. The `key` includes `ui_stats_publish_version` so the cell text bindings AND the `VSelect` v-models stay in sync after a server recompute without forcing a tab re-focus. The pin/unpin icons only appear on pinnable (MR/TS) cards.

---

### `fespp_on_trame/app/ui/content/panel/distribution_panel.py`
**Responsibility.** Body of one floating Distribution overlay — a Plotly histogram + a per-panel options toolbar. Multi-instance: every Hist/Compare-histograms click spawns a fresh instance with state vars suffixed by the panel id.

**Key classes / functions.**
- `class DistributionPanel` — `__init__(self, panel_id)`.
- Property accessors returning per-panel suffixed state-var names: `state_var` (`ui_distribution_figure_<id>`, the `{data,layout}` payload), `ctrl_method` (`update_distribution_figure_<id>`, the registered Plotly-react controller method), `mode_var`, `nbins_var`, `log_y_var`, `show_stats_var`, `cumulative_var`, `norm_var`, `meta_var` (NaN/kept/total badge), `csv_var` (base64 data-URL for export), `is_compare_var`.
- `render(self)` — `VContainer/VRow/VCol` wrapper (the Kitware-verified minimum) hosting `_render_toolbar()` + a `plotly.Figure(state_variable_name=self.state_var, …)`; registers `setattr(server.controller, self.ctrl_method, widget.update)`.
- `_render_toolbar()` — one-row toolbar: mode toggle (bars/line/curve), bins slider (5→500), log-Y switch, stats overlay switch (hidden on compare panels), cumulative switch, normalisation toggle (count/density/probability), NaN/kept `VChip` badge, CSV download `VBtn` (rendered as `<a>` via `href`).

**State.** Reads/writes all the per-panel suffixed vars above. A `@state.change` watcher registered in `multi_view._add_distribution_panel` re-runs compute on toolbar changes and pushes a new figure via `ctrl_method`.

**Collaborators.** `trame.widgets.plotly`; the spawner `multi_view._add_distribution_panel`; the compute/watcher engine code (distribution dispatch). Cleanup of the vars + controller method happens in `multi_view._on_view_closed`.

**Gotchas.** The Plotly wrapper **must** be the Vuetify `VContainer/VRow/VCol` chain — a raw `html.Div` with flex + `min-height:0` collapses Plotly to 0×0 inside the dockview floating shell (whose layout settles asynchronously). Per-instance scoping is essential or all Distribution panels clobber the same vars and only the last-updated one renders. The CSV export uses a data URL (no server round-trip on click).

---

### `fespp_on_trame/app/ui/content/panel/stats_compare_panel.py`
**Responsibility.** Body of one floating Compare-stats panel — a comparison matrix of the cart rows for a single property, with baseline/transpose/sort/highlight/visible-metrics/drag-reorder controls. Singleton-per-property; per-panel suffixed state vars.

**Key classes / functions.**
- `class StatsComparePanel` — `__init__(self, panel_id)`.
- Property accessors for the per-panel suffixed vars: `array_path_var`, `items_var` (resolved cart rows with numeric stats), `visible_metrics_var`, `baseline_var`, `transposed_var`, `sort_key_var`, `sort_asc_var`, `csv_var`, `order_var` (drag-reorder result), `annotations_var` (min/max/pos/neg/eq tags + `_deltas`).
- `render(self)` — `VContainer` with an inline `html.Style` (highlight cell classes + sticky-left anchors), `_render_toolbar()`, and the scroll-host `VRow/VCol` → `_render_table()`.
- `_render_toolbar()` — a property/row badge chip, baseline `VSelect` (with a "(no baseline)" sentinel), a Metrics-visibility `VMenu` (presets + per-metric toggles), a transpose toggle, a "Show distributions" button (`trigger('open_compare_distributions', [array_path])`), and a CSV download.
- `_render_table()` — builds `METRIC_LIST_JS`, `visible_metrics_expr`, `sorted_items_expr` (client-side numeric sort by `sort_key_var`), then renders **Layout A** (items as columns, metrics as rows; `v_if !transposed`) and **Layout B** (transposed; `v_if transposed`). Both use sticky-left Metric/baseline anchors, drag-and-drop column/row reordering writing `order_var`, per-cell highlight via `:class` raw_attrs from `annotations_var`, and baseline-delta arrows.

**State.** Reads/writes the per-panel suffixed vars; reads `ui_stats_tables` (badge) and `ui_stats_compare` (row count). The cart membership lives in `ui_stats_compare` (managed by the stats panel).

**Collaborators.** Triggers `open_compare_distributions`; server-side `publish_compare_items` / compare-matrix engine code populates `items_var` / `annotations_var`. Rendered by `multi_view._add_stats_compare_panel`; singleton tracked in `ui_stats_compare_panel`. Cleanup in `multi_view._on_view_closed`.

**Gotchas.** Heavy reliance on `raw_attrs=[':class=…', ':style=…', '@drop=…']` to emit raw Vue directives, because trame's `html.Th`/`html.Td`/`html.Span` renderers **did not honor** the `classes=`/CSS-class path for dynamic bindings under Vuetify's table reset — so sticky-left anchors, highlight classes, and arrow colors are all **inline** styles instead. `border-collapse: separate` (not `collapse`) is mandatory for `position: sticky` on table cells. The flex chain carries `min-width: 0` + `overflow: hidden` at each level so the inner table's `width: max-content` triggers the inner Div's horizontal scrollbar (which the sticky-left baseline anchor depends on).
