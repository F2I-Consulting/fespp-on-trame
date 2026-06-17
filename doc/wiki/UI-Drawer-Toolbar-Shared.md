# UI — Drawer, Toolbar & Shared

## Overview

This subsystem renders everything on the left edge of the FESPP-on-Trame window and the chrome shared across the whole app. The **Drawer** (`fespp_on_trame/app/ui/drawer/`) is the heart of it: a left navigation drawer split into two equal-height cards — a **Data Explorer** (three tabbed `VTreeview`s for Reservoir / Surface / Well, with custom tri-state checkboxes and per-render-view "eye" chips) and an **Attributes** card (per-representation edit panels: IJK slicers, plane Slice/Clip, value-based Thresholds, Representation type, and Colors & Opacity / solid color / Marker display). The **Toolbar** (`fespp_on_trame/app/ui/toolbar/`) is a thin top app-bar that hosts the Import dialog (remote URL / local upload / OSDU-ETP). The **Shared** package (`fespp_on_trame/app/ui/shared/`) holds reusable card builders, injected global CSS / client JavaScript, and bottom snackbars.

Two cross-cutting design decisions pervade this code and a forker must internalize them. (1) **Selection vs. visibility are orthogonal.** Checking a tree node decides what gets *loaded* into the pipeline (driven by `ui_select_node_*`); the per-view eye chips decide what is *shown/colored* in each render panel (`ui_hidden_rep_paths_by_view`, `ui_active_array_by_rep_by_view`, `ui_visible_marker_paths_by_view`). The drawer never uses Vuetify's built-in `selectable` propagation — it sets `selectable=False` and renders its own checkbox icon so a label click *activates* a node (opens its Attributes) without toggling its checkbox. (2) **Per-view everything.** The backend keeps a separate filter/LUT/source per (representation, render view); the Attributes panels edit whichever view is named by `drawer_target_view_id` (which either follows the active panel or is pinned). Most panel mutations therefore route through `source_resolver.render_and_push_target(...)` rather than a plain `Render()`, because a naive render would refresh the focused panel instead of the pinned target.

---

### `fespp_on_trame/app/ui/drawer/drawer.py`
**Responsibility.** Lays out the entire drawer body: the upload overlay, the right-edge resize handle, the **Data Explorer** card (title bar + three tabs + the matching tree), and the **Attributes** card (target-view strip + per-tab expansion panels).

**Key classes / functions.**
- `class Drawer` — top-level drawer builder. `__init__(self, tv)` stores a `TreeViews` instance (not owned — the engine also references it for assembly walking) and seeds `state.setdefault("tab", "reservoir")` so `v_show` matches on first paint.
- `render(self)` — entry point; call inside a `with layout.drawer:` context. Renders `UploadOverlay().render()`, the resize handle, then the two cards inside a full-height flex `VContainer`.
- `_render_resize_handle(self)` — a 16px transparent `VSheet` with class `fespp-drawer-resize-handle` and `right: -8px`, `z-index: 2000`. The actual drag logic is pure JS in `shared/scripts.py`; this only provides the grab target.
- `_render_data_explorer_card` / `_render_data_explorer_title` / `_render_data_explorer_tabs` / `_render_data_explorer_body` — the title toolbar hosts a **Load** button (`v_if="load_mode === 'manual'"`, click → `controller.apply_pending_selection`) and a cog (click → `controller.drawer_options_open`). Tabs are a `VTabs` bound to `state.tab`; each tab label shows a live count, e.g. `Reservoir ({{ ui_subtree_reservoir.length }})`. The body mounts all three trees simultaneously, toggled with `v_show` (`self._tv.reservoir_tree()` etc.) so each tree keeps its expansion/selection/scroll state across tab switches.
- `_render_attributes_card(self)` — second card. Renders `_render_target_view_strip()` then three `v_show`-gated blocks (reservoir / surface / well). Each wraps a `VExpansionPanels` containing the per-rep panels: reservoir gets `SlicersPanel(with_ijk=True)` + `ThresholdPanel()` + `RepresentationTypePanel()` + `SolidColorPanel()`; surface and well get `SlicersPanel(with_ijk=False)` + `RepresentationTypePanel()` + `SolidColorPanel()` (no IJK, no Threshold).
- `_render_target_view_strip(self)` — the "Target view:" row at the top of the Attributes body. A pin button toggles `drawer_target_view_pinned`; in *follow* mode it shows a passive label with the active panel's title, in *pinned* mode a `VSelect` over `fespp_render_panels` bound to `drawer_target_view_id`. The pin button is hidden until `(fespp_render_panels || []).length > 1`.

**State.** Writes/seeds: `tab`. Reads: `load_mode`, `ui_subtree_reservoir/surface/well` (counts), `ui_active_node_reservoir/surface/well`, `ui_select_node_surface/well`, `drawer_target_view_pinned`, `drawer_target_view_id`, `fespp_render_panels`, `fespp_active_panel_id`.

**Collaborators.** Imports the four attribute panels + `UploadOverlay`. Calls `controller.apply_pending_selection` and `controller.drawer_options_open`. Entry point is the app layout (`with layout.drawer:`).

**Gotchas.** The reservoir Attributes block gates on `ui_active_node_reservoir.length > 0` alone, but surface/well *additionally* require the active node to still be in the per-tab selection (`ui_select_node_surface.includes(...)`) — an asymmetry worth knowing. `min-height: 0` on the flex card bodies is mandatory (a flex item's default `min-height: auto` would let a tall tree push the title/tabs off-screen instead of scrolling). The comment block notes Statistics no longer live in this card — they moved to a singleton dockview "stats" panel.

---

### `fespp_on_trame/app/ui/drawer/tree_views.py`
**Responsibility.** The largest and most important file in the subsystem. Owns the three `VTreeview`s, the custom tri-state checkbox, the dependency-cascade logic (checking a node auto-selects/deselects its dependencies), the select→active wiring, and the per-row append slots: color chips, the Stats toggle, and the per-view eye chips.

**Key module-level functions.**
- `_expand_selection_with_deps(curr_ids, prev_ids, tree) -> list` — the dependency cascade. **Additions:** checking a grouping kind adds all its *selectable* descendants; checking a `WellboreChannel`/`WellboreMarker` adds the sibling `WellboreTrajectory`; checking any node under a representation adds that representation (`tree.find_representation_node`). **Removals:** unchecking a representation or a grouping drops every descendant. Implicit additions are deliberately ordered *before* `curr_ids` so the user's last explicit click stays at the tail (consumed by `_wire_select_to_active` as `new_ones[-1]`).
- `_wire_select_to_active(select_var, active_var, prev_var)` — registers a `@_state.change(select_var)` handler that sets `active_var` to the newly-added node (or falls back to a remaining node when the active one is unchecked). Needed because Vuetify's `update_selected` always emits the *full* array, so binding active to `$event[0]` would pick the first-ever-selected node, not the last clicked.
- `_wire_dependency_expansion(select_var, prev_var, active_var, tree)` — a single `@_state.change(select_var, active_var)` handler that (1) guards against a Vuetify label-click quirk that would drop the just-activated node and (2) drives `_expand_selection_with_deps` over the selection delta. Uses a module-level `_prev_active_seen` dict because Trame exposes no pre-flush snapshot of `active`.
- `_select_checkbox_icon(select_var) -> str` / `_select_checkbox_color(select_var) -> str` — Vue ternary expressions producing the checkbox icon/color. Tri-state on groupings (`item.is_grouping` with `item.descendant_ids`): `mdi-checkbox-marked` when *all* descendants selected, `mdi-minus-box` when *some*, `mdi-checkbox-blank-outline` otherwise; binary on `item.id` for everything else.
- `_chip_slot()` — renders the color chip beside a node label, driven by `tree_chip_color_by_path[item.path]`: rainbow gradient for the `"PROPERTY"` sentinel (rep colored by an array), conic gradient for `"MULTICOLOR"` (a `MarkerFrame` whose markers carry 2+ distinct colors), solid `mdi-circle` for a hex color, nothing when absent.
- `_stats_slot(controller, select_var)` — the `mdi-chart-box(-outline)` toggle on property nodes (types in `_PROPERTY_TYPES_JS`) that are *currently checked*. Flips when `item.path` is in `ui_stats_pinned_paths`; click → `controller.toggle_stats_display(item.path)`.
- `_eye_slot(controller)` — the per-view visibility/coloring chips, gated on the server-computed `item.eye` token (`'rep'` / `'array'` / `'marker'`, absent on Frame/MarkerFrame folders and groupings). Three independent blocks:
  - **Rep eye** (`item.eye === 'rep'`, path in `ui_loaded_rep_paths`): one `mdi-eye`/`mdi-eye-closed` per render panel (blue when shown in SolidColor, grey when hidden in `ui_hidden_rep_paths_by_view`, dimmed when that panel has an active array). Click → `controller.toggle_rep_visibility([item.path, panel.id])`.
  - **Array eye** (`item.eye === 'array'`, path in `ui_loaded_array_paths`): purple `mdi-eye` when the panel colors by this array (`ui_active_array_by_rep_by_view[panel.id][item.rep_path] === item.path`), outline otherwise. Click → `controller.toggle_dataarray_color([item.path, panel.id])`.
  - **Marker eye** (`item.eye === 'marker'`, path in `ui_loaded_marker_paths`): multi-select visibility via `ui_visible_marker_paths_by_view`; deep-orange `mdi-eye` when visible. Click → `controller.toggle_marker_visibility([item.path, panel.id])`.
  - Each block has a **collapsed mode** (only when `fespp_render_panels.length > 1`): when every panel uniformly hides the rep / has the array inactive / hides the marker, the per-panel row folds into a single unlabelled chip whose click targets the active panel (the controller method called with only `[item.path]`, no panel id).
- `class TreeViews` — `__init__(self, controller, state, tree=None)` registers the controller callbacks and wires all the handlers:
  - `controller.tree_toggle_select(node_id, select_var)` — the custom checkbox click handler. Partial nodes are no-ops; grouping nodes cycle "some/none → all" then "all → none" over `find_all_selectable_descendant_ids`; leaves/reps plain-toggle. Kept in lockstep with `_expand_selection_with_deps`.
  - `controller.init_opened_nodes(tree_data)` — returns first-level node ids to seed each tree's `opened` list.
  - `_init_grid_selections(self)` — ensures a `ui_selected_grid_<id>` state var exists per top-level reservoir grid.
  - `reservoir_tree()` / `surface_tree()` / `well_tree()` — render one `VTreeview` each (`item_value="id"`, `activatable=True`, `active_strategy="single-independent"`, `selectable=False`, `open_on_click=False`). The prepend slot renders the custom checkbox icon (hidden for `item.disabled` partials), the primary `{{item.icon}}`, the `mdi-timeline-clock` badge for `item.is_ts`, the `MR` chip for `item.is_mr`, then `_chip_slot()`. The append slot renders `_stats_slot(...)` then `_eye_slot(...)`. The reservoir tree differs only in `density="comfortable"` (+ `item_props=True`, `indent_lines="default"`).

**State.** Writes: `ui_select_node_*`, `ui_active_node_*`, `_prev_select_*`, `ui_opened_*`, `ui_selected_grid_<id>`. Reads (in templates): `ui_subtree_*`, `tree_chip_color_by_path`, `ui_stats_pinned_paths`, `ui_loaded_rep_paths`, `ui_loaded_array_paths`, `ui_loaded_marker_paths`, `ui_hidden_rep_paths_by_view`, `ui_active_array_by_rep_by_view`, `ui_visible_marker_paths_by_view`, `fespp_render_panels`.

**Collaborators.** Depends on a `tree` object (`fespp_on_trame/app/core/tree.py`) for `find_type`, `find_path`, `find_representation_node`, `find_parent_node_id_with_type`, `find_first_child_of_type`, `find_all_(selectable_)descendant_ids`. Eye/stats/visibility clicks call `controller.toggle_rep_visibility`, `toggle_dataarray_color`, `toggle_marker_visibility`, `toggle_stats_display`. Instantiated by the engine and passed to `Drawer`.

**Gotchas.** `_GROUPING_KINDS` (`Collection`, `Wellbore`, `Partial`, `Feature`, `Interpretation`, `Frame`, `MarkerFrame`) governs *tree selection / tri-state only* — it is independent of C++ source creation (a `Frame`/`MarkerFrame` is a selection folder but still owns a per-view rendering anchor). The whole custom-checkbox apparatus exists because Vuetify 3 `selectable=True` makes the entire row toggle selection with no opt-out, which collided with label-click activation. `_PROPERTY_TYPES_JS` lists the six property kinds the Stats toggle and array-eye logic recognize.

---

### `fespp_on_trame/app/ui/drawer/config/tree_icons.py`
**Responsibility.** Material Design icon map for tree node kinds + lookup helpers.

**Key classes / functions.**
- `TREE_ICONS: dict[str,str]` — kind → mdi icon name (e.g. `"IjkGrid": "mdi-axis-arrow-info"`, `"MarkerFrame": "mdi-flag-outline"`).
- `get_icon_for_type(node_type) -> str` — exact lookup, then substring fallback (so `"ContinuousProperty"` can inherit `"Property"`), finally `"mdi-folder"`.
- `get_primary_icon(node_type, prop_kind=None) -> str` — the function actually used by `tree.py`. For synthetic wrapper kinds in `_SYNTHETIC_PROPERTY_TYPES` (`TimeSeries`, `MultiRealization`, `MultiRealizationTimeSeries`) it returns the icon for the underlying `prop_kind` so the leaf shows the real property type; the TS/MR aspect is conveyed by the secondary badges in the treeview.
- `get_icon_expression(type_field="item.type") -> str` — builds an inline Vue ternary from `TREE_ICONS`.

**Collaborators.** `get_primary_icon` is imported by `fespp_on_trame/app/core/tree.py` (sets `treeview["icon"]`) and mirrored by `stats_dispatch.py`.

**Gotchas.** `get_icon_expression` is **buggy and unused**: it indexes `config['icon']` and `TREE_ICONS['default']['icon']`, but `TREE_ICONS` maps to plain strings and has no `"default"` key, so calling it would raise `TypeError`/`KeyError`. It is dead code kept for "templates that resolve icons inline" — no production caller exists. Icons are normally precomputed server-side into `item.icon`.

---

### `fespp_on_trame/app/ui/drawer/config/tree_selection.py`
**Responsibility.** Per-tab whitelist of selectable node kinds, with a helper that builds a Vue `item_props` callback toggling `selectable`.

**Key classes / functions.**
- `SELECTABLE_TYPES: dict` — `reservoir` → property kinds; `surface` → `TriangulatedSet`/`PolylineSet`; `well` → `WellboreTrajectory`/`WellboreFrame`/`WellboreMarker`.
- `get_item_props_js(tree_category="reservoir") -> str` — returns `item => ({ selectable: <ORed includes() conditions> })`.

**Collaborators.** Only `tests/unit/test_tree_selection.py` imports it.

**Gotchas.** This module is effectively **legacy / not wired into the live trees**: `tree_views.py` renders all three `VTreeview`s with `selectable=False` and a custom checkbox, so the `item_props` selectable whitelist is never applied at runtime. A forker should treat this as a leftover from an earlier selection model.

---

### `fespp_on_trame/app/ui/drawer/dialog/display_options_dialog.py`
**Responsibility.** The modal opened by the Data Explorer cog: Load Mode and Tree Hierarchy toggles.

**Key classes / functions.**
- `class DisplayOptionsDialog` — `__init__` seeds `drawer_options_dialog_visible=False` and exposes `controller.drawer_options_open = self.open`.
- `open()` / `close()` — flip `drawer_options_dialog_visible`.
- `render()` — a `VDialog` with a title bar, then `_render_load_mode()`, `_render_tree_hierarchy()`, `_render_hierarchy_warning()`.
- `_render_load_mode` — `VBtnToggle` bound to `load_mode` (`auto` / `manual`). Manual lets the user batch checkbox picks and push them via the drawer's Load button.
- `_render_tree_hierarchy` — `VBtnToggle` bound to `tree_hierarchy_mode` (`flat` / `by_interpretation` / `by_feature_and_interpretation`).
- `_render_hierarchy_warning` — inline orange caption warning that switching mode clears all state.

**State.** Writes/seeds `drawer_options_dialog_visible`; binds `load_mode`, `tree_hierarchy_mode`.

**Collaborators.** Registers `controller.drawer_options_open`, consumed by `drawer.py`'s cog. The hierarchy change is handled elsewhere (engine) and confirmed by `HierarchySnackbar`.

**Gotchas.** Changing `tree_hierarchy_mode` rebuilds the C++ assembly and **resets every selection / visibility / coloring state** — the warning text and the bottom snackbar exist precisely because the wipe is destructive.

---

### `fespp_on_trame/app/ui/drawer/widget/upload_overlay.py`
**Responsibility.** Full-drawer modal overlay shown during a file upload.

**Key classes / functions.**
- `class UploadOverlay` — `render()` draws an absolutely-positioned semi-transparent overlay (`v_show="upload_uploading"`) with a `VProgressCircular` (`indeterminate` when `upload_progress === 0`) and a status line.

**State.** Reads `upload_uploading`, `upload_progress`.

**Collaborators.** Rendered first in `Drawer.render()`. State is driven by the import dialog's inline upload JS.

**Gotchas.** `upload_progress === 0` is overloaded to mean "indeterminate phase"; the status string is partly French (`'Transfert en cours…'`).

---

### `fespp_on_trame/app/ui/drawer/panel/representation_type_panel.py`
**Responsibility.** Wraps ptc's `RepresentBy` widget in an expansion panel so the user can change a representation's display type (Surface / Wireframe / Points / …).

**Key classes / functions.**
- `class RepresentationTypePanel(html.Div)` — constructed with `v_if="active_representation_path && active_representation_path.length > 0"`. Builds a `VExpansionPanels` (`rt_panels`, default `[0]`) whose title shows the current `representation_active` in a chip (`v_if="representation_show"`) and whose body embeds `ptc.RepresentBy(...)`.

**State.** Reads `active_representation_path`, `representation_active`, `representation_show`; binds `rt_panels`.

**Collaborators.** `ptc.RepresentBy` targets the ParaView active source and re-syncs via `controller.on_active_proxy_change`.

**Gotchas.** Per-rep behavior relies entirely on `SetActiveSource(rep_source)` running when the active resqml representation changes (handled in the engine's `fespp_active`). This panel adds no per-view logic of its own — it inherits ptc's active-source model.

---

### `fespp_on_trame/app/ui/drawer/panel/slicers_panel.py`
**Responsibility.** The unified "Slicers" `VExpansionPanel` that groups the three geometry-cut variants (IJK / Slice / Clip) into internal `VTabs`.

**Key classes / functions.**
- `class SlicersPanel` — `__init__(self, *, with_ijk=True)`; `with_ijk=False` drops the IJK tab for surface/well. `render()` builds the panel: the title shows at-a-glance chips (`Slice` when `ui_slice_enabled`, `Clip` when `ui_clip_enabled`, an `IJK slice`/`IJK range` chip for IjkGrid). The body is a `VTabs` bound to `ui_slicers_tab` (`mandatory`), with tab bodies rendered via `v_show` (not `v_if`) so local UI state survives tab switches: `SlicerControls().render_body()`, `SlicePlanePanel().render_body()`, `ClipPlanePanel().render_body()`.

**State.** Reads/binds `ui_slicers_tab`, `ui_slice_enabled`, `ui_clip_enabled`, `ui_active_node_reservoir_type_rep`, `ui_slices_range_mode`.

**Collaborators.** Imports `SlicerControls`, `IJK_TAB_VISIBLE`, `SlicePlanePanel`, `ClipPlanePanel`. Instantiated by `Drawer`.

**Gotchas.** The IJK tab is hidden unless the active rep is an `IjkGrid` (`IJK_TAB_VISIBLE`); `VTabs mandatory` then falls back to the first available tab. The module docstring documents a known limitation: the UI binds the *global* `ui_slice_*`/`ui_clip_*` vars which mirror the *active* panel's filter, so switching panel shows the last edit until the dispatchers re-publish.

---

### `fespp_on_trame/app/ui/drawer/panel/slicers.py`
**Responsibility.** The IJK slicer body: an axis crop ("range" mode) and per-axis multi-position cuts ("slice" mode), for `IjkGrid` reps only.

**Key classes / functions.**
- `IJK_TAB_VISIBLE = "ui_active_node_reservoir_type_rep === 'IjkGrid'"` — exported for `SlicersPanel`.
- `class SlicerControls` (`_mode_var = "ui_slices_range_mode"`):
  - `render_body(self)` — gated on IjkGrid. Header row: a `VSwitch` toggling range/slice mode + `render_copy_menu("ijk_slicers")`. In range mode, a single "Volume" eye toggling `ui_slices_volume_visible`. Then `RangeSlider("i"/"j"/"k")` and `MultiSlider("i"/"j"/"k")`.
  - `RangeSlider(self, index)` — a `VRangeSlider` (visible in range mode) over `ui_range_<axis>`, bound to `ui_slices_range_<axis>`, with a refresh button (reset to full range) and min/max `VTextField`s editable on blur/Enter.
  - `MultiSlider(self, index)` — visible in slice mode; manages `ui_slices_<axis>_list` (positions) and `ui_slices_<axis>_visible_list` (per-slicer eyes). A `+` button appends a slicer at mid-range (and a `true` visibility entry); each row has a `VSlider`, a numeric field, an eye toggle, and a delete button — all manipulated via inline JS `.map`/`.filter`/`.concat`.

**State.** Binds `ui_slices_range_mode`, `ui_slices_volume_visible`, `ui_range_<axis>`, `ui_slices_range_<axis>`, `ui_slices_<axis>_list`, `ui_slices_<axis>_visible_list`. Reads `ui_active_node_reservoir_type_rep`.

**Collaborators.** `render_copy_menu` from `copy_from_view_menu`. Backend consumes the list/range state (slicer dispatch).

**Gotchas.** All add/remove/edit are inline-JS array ops on the client (the `RangeSlider` blur/keydown handlers write the range state directly in the Vue expression). Threshold and Realization controls were intentionally moved out of this file (Threshold → `ThresholdPanel`; Realization → per-view picker), per the class docstring. `vuetify3.enable_lab()` is called at import time (needed for `VSlider`/`VRangeSlider` lab features).

---

### `fespp_on_trame/app/ui/drawer/panel/slice_plane_panel.py`
**Responsibility.** Single-plane slice controls + an "Edit 3D" toggle that owns the shared 3D-widget channel; plus the server triggers that forward to the controller.

**Key classes / functions.**
- `class SlicePlanePanel` — `render_body(self)`: top row with the `Enabled` `VSwitch` (`update_modelValue="trigger('slice_set_enabled', [$event])"`), an "Edit 3D" button toggling `ui_plane_edit_mode` between `'slice'` and `null`, and `render_copy_menu("slice")`. Then a `VBtnToggle` for normal axis (X/Y/Z → `trigger('slice_set_axis', ...)`) and an offset `VSlider` (`trigger('slice_set_offset', ...)` on release).
- `_wire_slice_set_triggers()` (module-scope, called at import) — registers `slice_set_enabled`, `slice_set_axis`, `slice_set_offset`, `plane_edit_mode_set`. Each defensively `getattr`s the controller method (`controller.slice_set`, `controller.plane_edit_mode_set`). Enabling the slice auto-focuses Edit on it if `ui_plane_edit_mode` is currently `None`. `plane_edit_mode_set` normalizes Vue's `"null"`/`""`/`None` to Python `None`.

**State.** Binds `ui_slice_enabled`, `ui_slice_axis`, `ui_slice_offset` (domain `ui_slice_offset_min/max/step`, `ui_slice_bounds`), `ui_plane_edit_mode`.

**Collaborators.** `controller.slice_set(...)`, `controller.plane_edit_mode_set(...)`, `render_copy_menu`. Body hosted by `SlicersPanel`.

**Gotchas.** Slice and Clip **share the single `ui_plane_edit_mode` widget channel** — only one filter's 3D widget is visible at a time, though both can be enabled simultaneously. Values are pushed through per-field `trigger(...)` calls because Vue's inline object-literal payload trips its v-on parser in some versions.

---

### `fespp_on_trame/app/ui/drawer/panel/clip_plane_panel.py`
**Responsibility.** The clip analog of `SlicePlanePanel` — same shape, plus an "Invert side" toggle.

**Key classes / functions.**
- `class ClipPlanePanel` — `render_body(self)`: `Enabled` switch (`clip_set_enabled`), Edit 3D toggle on `ui_plane_edit_mode === 'clip'`, `render_copy_menu("clip")`, X/Y/Z axis toggle (`clip_set_axis`), offset slider (`clip_set_offset`), and an "Invert side" `VSwitch` bound to `ui_clip_inside_out` (`clip_set_inside_out`).
- `_wire_clip_triggers()` (called at import) — registers `clip_set_enabled` (auto-focus Edit when nothing else is being edited), `clip_set_axis`, `clip_set_offset`, `clip_set_inside_out`, each forwarding to `controller.clip_set(...)`.

**State.** Binds `ui_clip_enabled`, `ui_clip_axis`, `ui_clip_offset` (`ui_clip_offset_min/max/step`), `ui_clip_inside_out`, `ui_plane_edit_mode`.

**Collaborators.** `controller.clip_set(...)`, `controller.plane_edit_mode_set(...)`, `render_copy_menu`.

**Gotchas.** Same shared `ui_plane_edit_mode` channel as the slice panel.

---

### `fespp_on_trame/app/ui/drawer/panel/threshold_panel.py`
**Responsibility.** Per-rep, value-based threshold *chain* editor (a tree of union/intersection range filters), for `IjkGrid` and `UnstructuredGrid` only.

**Key classes / functions.**
- `THRESHOLD_PANEL_VISIBLE` — visibility expression for IjkGrid/UnstructuredGrid.
- `class ThresholdPanel` — `render()` builds the `VExpansionPanel` (`v_if=THRESHOLD_PANEL_VISIBLE`); the title shows a `{{ ui_threshold_chain.length }} active` chip + `render_copy_menu("threshold")`.
- `_render_body(self)` — header with a root "Add union" button (`mdi-set-all`, disabled until `active_color_array_name` is set) that emits `ui_threshold_pending_action = { action: 'add', parent: null }`. Then a `v_for` over `ui_threshold_chain`: each entry row (indented by `entry._depth * 12px`) has a visibility eye (`set_visible`), the array name + `[low .. high]`, an "Add intersection" button (`{ action: 'add', parent: entry.name }`), and a delete button. Below each row, one of three `VRangeSlider`s by `entry.kind`: **Discrete** (integer `step=1`), **Categorical** (`step=1` with labeled `ticks` from `entry.labels`, `show-ticks="always"`), or **Continuous** (fine `step = range/1000`). All emit `{ action: 'set_range', name, low, high }` on release.

**State.** Reads `ui_threshold_chain`, `active_color_array_name`. Writes the sentinel `ui_threshold_pending_action`.

**Collaborators.** The engine's threshold dispatch consumes `ui_threshold_pending_action`, applies the add/delete/set_range/set_visible action, then resets the sentinel. `render_copy_menu`.

**Gotchas.** All chain mutations flow through the single `ui_threshold_pending_action` state var (a consume-and-reset sentinel) rather than separate events. Threshold is deliberately *not* a geometry cut and lives apart from Slice/Clip/IJK. The chain is per-rep, even across reps sharing a property name.

---

### `fespp_on_trame/app/ui/drawer/panel/copy_from_view_menu.py`
**Responsibility.** The reusable "Copy <concern> from view X" dropdown used in the slice / clip / threshold / IJK-slicer headers (Phase 3c per-concern on-demand state copy).

**Key classes / functions.**
- `_VALID_CONCERNS = ("threshold", "slice", "clip", "ijk_slicers")`.
- `render_copy_menu(concern) -> None` — emits a `VBtn` + `VMenu` + `VList` into the current container; raises `ValueError` for an unknown concern. The button is hidden unless `(fespp_render_panels || []).length > 1`. The list shows every *other* panel; clicking one fires `trigger('copy_<concern>_from_view', [p.id])`.
- `_wire_triggers_once()` (called at import) — idempotently (guarded by a server flag `_fespp_copy_from_view_triggers_wired`) registers one trigger per concern, forwarding to the controller method in `_METHODS` (`copy_threshold_chain_from`, `copy_slice_from`, `copy_clip_from`, `copy_ijk_slicers_from`) as `fn(src_view=...)`.

**State.** Reads `fespp_render_panels`, `fespp_active_panel_id`.

**Collaborators.** Called by `slicers.py`, `slice_plane_panel.py`, `clip_plane_panel.py`, `threshold_panel.py`. Calls the four controller `copy_*_from` methods.

**Gotchas.** The destination is implicitly the active panel (resolved controller-side), so only the *source* view id is passed. `"threshold"` is the naming odd-one-out (`copy_threshold_chain_from`).

---

### `fespp_on_trame/app/ui/drawer/panel/color_editor.py`
**Responsibility.** The continuous-property LUT/PWF color-opacity editor (subclass of ptc's editor) with an added hexa NaN-color picker, and the per-view scoped-LUT plumbing for it.

**Key classes / functions.**
- `_apply_nan_color_to_lut(lut)` — applies `state.nan_color` (`#RRGGBB[AA]`) to `lut.NanColor` / `lut.NanOpacity`.
- `class _FesppColorOpacityEditor(ptc.ColorOpacityEditor)`:
  - `__init__` — forces hexa format and seeds `nan_color="#FF000000"` (red, alpha 00 → NaN transparent by default).
  - `build_content` — lays out preset select, the `ColorOpacityEditor` widget, the NaN-color `VColorPicker` (hexa), and two collapsible color/opacity transfer-function tables.
  - `_should_apply_state_change() -> bool` — returns `not state.diff_colors_dialog_visible`; the drawer editor must NOT write `state.colors`/`opacities` while the diff-colors dialog owns them.
  - `update_scalar_range()` — overrides ptc: resolves the *base* array name (MR title → `_real_<idx>` via `source_resolver`), then queries the **per-view scene's `RepInScene.source()`** (channel source for wellbore channels, else the scene-registry rep source) for the data range. Forces a full `UpdatePipeline()` (not just info) and falls back to `self.source_proxy`. Widens degenerate ranges via `source_resolver.nondegenerate_range`.
  - `@change("colors") on_colors_changed`, `@change("preset_name") on_preset_name_changed`, `@change("opacities") on_opacities_changed`, `@change("nan_color") on_nan_color_changed` — each guarded by `_should_apply_state_change()`, calls the parent, then `source_resolver.render_and_push_target(...)`. `on_preset_name_changed` preserves the NaN alpha (parent drops it). `on_opacities_changed` toggles `EnableOpacityMapping` based on whether any node alpha < 1.0 (VTK forces NaN to opaque when EOM=1).

**State.** Reads/writes `nan_color`, `scalar_range`, `active_color_array_name`, `active_color_array_path`, `active_representation_path`, `drawer_target_view_id`, `fespp_active_panel_id`, `diff_colors_dialog_visible`, `colors`, `opacities`, `preset_name`.

**Collaborators.** `ptc.ColorOpacityEditor`, `source_resolver` (`resolve_target_scoped_lut`, `channel_source_for`, `nondegenerate_range`, `render_and_push_target`), `scene_registry` from server context, `pvsimple`. Instantiated by `SolidColorPanel` for continuous properties.

**Gotchas.** The override of `update_scalar_range` exists because ptc's `self.source_proxy` is `GetActiveSource()` = the legacy shared `ExtractBlock`, which lacks MR `_real_<idx>` arrays; the per-view IjkGrid extractor must be force-updated with a full pipeline pass or `GetDataInformation()` reports zero cells. ptc's writers mutate proxies without calling `Render`, hence the explicit `render_and_push_target` in every handler.

---

### `fespp_on_trame/app/ui/drawer/panel/categorical_color_editor.py`
**Responsibility.** The Discrete/Categorical alternative to the continuous editor: one color row per distinct integer value, bound to the LUT's `IndexedColors` / `IndexedOpacities`.

**Key classes / functions.**
- SMProxy helpers `_set_int_property`, `_set_double_list_property`, `_set_string_list_property` — set LUT proxy properties via `lut.SMProxy.GetProperty(...).SetElement(...)` because pvsimple's wrapper rejects unknown attribute names on PV6's `PVLookupTable`.
- Color helpers `_rgb01_to_hex`, `_hex_to_rgba01`, `_default_color_for_index` (golden-ratio HSV palette), `_find_array_in_store` (with `make_valid_vtk_name` fallback).
- `class CategoricalColorEditor(html.Div)`:
  - `__init__` — seeds `categorical_entries=[]` and the sentinel `cce_pending_change=None`; builds the per-category row UI (a `VMenu`+`VColorPicker` per entry, hexa+alpha). Registers three watchers: `@change("active_color_array_name","active_property_kind")` (refresh when kind is Discrete/Categorical else clear); `@change("drawer_target_view_id","ui_active_realization_by_array_by_view")` (re-pull palette from the new target's scoped LUT); `@change("cce_pending_change")` (apply a picker change then reset the sentinel).
  - `_refresh(self, array_name)` — scans the active source's VTK array for unique integer values, reads the per-view scoped LUT's `Annotations`/`IndexedColors`/`IndexedOpacities`, seeds a categorical preset on first activation (tries `"Categorical 1"`, `"Set 1"`, …), builds `categorical_entries`, then pushes `IndexedLookup=1` + `EnableOpacityMapping=1` + colors/opacities/annotations back. Deliberately does **not** call `Render` (the activation handler renders).
  - `_apply_color_change(self, index, hex_color)` — writes one slot of `IndexedColors`/`IndexedOpacities` on the target scoped LUT, re-asserts the indexed-lookup flags, re-binds `display.LookupTable`/`ColorArrayName` on every display using the LUT (PV caches the LUT snapshot), updates the entry, then `render_and_push_target`.

**State.** Reads `active_color_array_name`, `active_property_kind`, `active_color_array_path`, `drawer_target_view_id`, `ui_active_realization_by_array_by_view`; writes `categorical_entries`, `cce_pending_change`.

**Collaborators.** `source_resolver.resolve_target_scoped_lut` / `render_and_push_target`, `pvsimple`, `make_valid_vtk_name`. Instantiated by `SolidColorPanel`.

**Gotchas.** Per-category alpha only renders when `IndexedLookup=1` AND `EnableOpacityMapping=1` AND each display re-binds its LUT — all three re-asserted on every edit. Per-view LUT isolation means the same categorical property can show different palettes in different views. The pending-change sentinel must be reset after applying so the next click of the *same* color re-triggers the watcher (Trame ignores no-change writes).

---

### `fespp_on_trame/app/ui/drawer/panel/solid_color_panel.py`
**Responsibility.** The "Colors & Opacity" panel — mode auto-selected from the active node type (rep → solid color picker; data-array → embedded LUT/PWF or categorical editor) — plus the GLOBAL "Marker display" sub-panel (orientation + size), per-marker recoloring, and the tree color-chip computation.

**Key classes / functions.**
- Hex helpers `_hex_to_rgb01`, `_hex_to_alpha`.
- `_displays_for_rep(rep_path)` — resolves the per-view displays that actually paint the rep in the drawer-target view (via `source_resolver.displays_for_rep_path` over the context `source_registry`), NOT the legacy shared ExtractBlock (which is hidden).
- `_apply_solid(rep_path, color_hex)` — pushes `DiffuseColor`/`AmbientColor`/`Opacity` onto every such display; for a MarkerFrame it additionally fans the tint onto each *visible per-marker* extractor (`ris.visible_marker_displays()`), then `render_and_push_target`. Never touches `ColorArrayName`.
- Marker helpers `_engine_tree()`, `_active_marker_path()` (returns the path only when the active well node is a single `Marker`), `_is_marker_frame_path(path)`, `_markers_of_frame(frame_path)`, `_apply_marker_solid(rep_path, marker_path, color_hex)` (recolor one marker via `ris.set_marker_color`).
- `class SolidColorPanel(html.Div)`:
  - `__init__` — `v_if="active_representation_path && ... length > 0"`; seeds `active_representation_path`, `active_representation_has_properties`, `solid_color_by_rep`, `solid_color_by_marker`, `solid_color_next_idx`, `solid_color="#808080FF"`, `tree_chip_color_by_path`, `sc_active_is_marker`. Mode selector `_is_array_active` = "`active_color_array_name` non-empty". Builds two expansion panels: **Colors & Opacity** (solid `VColorPicker` when no array; else `_FesppColorOpacityEditor` for continuous or `CategoricalColorEditor` for Discrete/Categorical), and **Marker display** (`v_if="sc_active_is_marker"`) with a `marker_orientation` switch and a `marker_size` slider whose `end` calls `controller.apply_marker_options`.
  - Inside `__init__` it monkey-patches the COE: `coe.get_representation_color_array_name = _get_array_name_from_state` and assigns `controller.update_color_editor = _update_color_editor`. Nested helpers: `_target_panel_id`, `_target_scene`, `_resolve_base_array_name` (title → real/MR-suffixed VTK name), `_resolve_coe_lut` (→ base name, per-scene LUT, scoped registration name), `_get_array_name_from_state` (returns `["CELLS", scoped]` for ptc writeback), `_data_range_for_active_array`, and `_update_color_editor(array_name)` (rescales a fresh scope LUT/PWF to the data range only when still at default `[0,1]`, then pushes `RGBPoints`/PWF points into COE state).
  - Watchers: `@change("drawer_target_view_id","ui_active_realization_by_array_by_view","ui_active_array_by_rep_by_view")` re-pushes the COE; `@change("active_representation_path","ui_active_node_well")` sets `sc_active_is_marker` and re-seeds the `solid_color` wheel from the active node's stored color; `@change("solid_color")` writes the tint to the right scope (single marker → `solid_color_by_marker[marker]`; MarkerFrame → all its markers uniformly + `solid_color_by_rep[frame]`; else `solid_color_by_rep[rep]`) and applies it; `@change("solid_color_by_rep","ui_active_array_by_rep","solid_color_by_marker")` recomputes `tree_chip_color_by_path` (`"PROPERTY"` when colored by array, `"MULTICOLOR"` for a MarkerFrame with 2+ distinct effective marker colors, else the hex).

**State.** Seeds/writes `active_representation_path`, `solid_color`, `solid_color_by_rep`, `solid_color_by_marker`, `sc_active_is_marker`, `tree_chip_color_by_path`, `active_color_array_name`, `marker_orientation`, `marker_size`. Reads `active_property_kind`, `active_color_array_path`, `ui_active_node_well`, `ui_loaded_marker_paths`, `ui_active_array_by_rep`, `drawer_target_view_id`/`fespp_active_panel_id`, `ui_active_realization_by_array_by_view`, `ui_active_array_by_rep_by_view`.

**Collaborators.** `_FesppColorOpacityEditor`, `CategoricalColorEditor`, `source_resolver` (display resolution, `_scene_rep_for_view`, `real_base_name`, `render_and_push_target`, `target_view_and_panel`), `realization_dispatch`, the engine `_tree`, `scene_registry`/`source_registry` from context, `controller.apply_marker_options`. Provides `controller.update_color_editor` (called by the engine on activation).

**Gotchas.** Solid color sets `DiffuseColor` only and never `ColorArrayName` — when an array eye is open ColorBy wins and the solid tint is dormant. The MarkerFrame path must fan onto separate per-marker extractors because the frame's main extractor is permanently hidden; markers shown *later* pick up the persisted `solid_color_by_marker`/`solid_color_by_rep` at creation in `MarkerFrameRep._create_child_extractor`. The COE array-name override exists because MR properties carry a *title* (`"VOIL"`) in state but the LUT is keyed by the *suffixed* name (`"VOIL_real_23"`); read and writeback must resolve to the *same* scoped LUT or the editor clobbers the real LUT's range. The "Marker display" panel is GLOBAL (orientation + size apply to every marker in every view) and its labels are French. `marker_size` applies on slider release only because rebuilding markers re-runs the collector over the whole selection.

---

### `fespp_on_trame/app/ui/toolbar/toolbar.py`
**Responsibility.** The top app-bar: a collapse chevron and the "Import data" button that opens the import dialog.

**Key classes / functions.**
- `class Toolbar` — `__init__(self, local_file_manager, import_dialog)` stores both. `render()` draws a left chevron (`click="toolbar_visible = false"`) and a right-side "Import data" `VBtn` (`click="dialog_visible = true"`), then calls `self.import_dialog.render()`.

**State.** Writes `toolbar_visible`, `dialog_visible` (both via inline JS).

**Collaborators.** Holds an `ImportDialog` (renders it). The mirror show-button for `toolbar_visible` lives in `app_layout.py`.

**Gotchas.** `local_file_manager` is stored but unused here — local upload is handled entirely by the import dialog's inline JS. The Load button and view actions deliberately live elsewhere (drawer band / content area), per the docstring.

---

### `fespp_on_trame/app/ui/toolbar/dialog/import_dialog.py`
**Responsibility.** The Import modal and its `execute_action` handler. Three import paths: remote URL list (HTTP download), local file upload (multipart POST via inline JS), and OSDU/ETP connection.

**Key classes / functions.**
- `_IMPORT_CLICK_JS` (module constant) — the inline JS bound to the Import button. On the "files" tab it reads the accumulated `File` objects off the `#fesppFileInput` element (`_fesppFiles`, falling back to `input.files`), filters them against `upload_file_names`, builds a `FormData`, and `XMLHttpRequest`-POSTs to `/api/<sid>/upload` (or `/upload`), setting `upload_uploading`/`upload_progress`. On the "osdu" tab it just sets `execute_action=true`. Reaches `window` via `ownerDocument.defaultView` to bypass Vue 3's template whitelist.
- `class ImportDialog` — `__init__(self, state, controller)` registers `_on_execute_action` on `execute_action`, seeds OSDU token-type/`import_tab` defaults, and registers `_update_import_button_state` and `_on_dataspace_selected`.
  - `_update_import_button_state` — disables Import on the OSDU tab until a dataspace is selected.
  - `_on_dataspace_selected` — calls `controller.select_etp_dataspace(...)`.
  - `_on_execute_action(execute_action, ...)` — on True: OSDU tab → `_handle_osdu_import`; else if `remote_files_location` set → split on `|`, `download_file_from_url` each into a temp dir, `controller.load_epc_file` each `.epc`. Always resets `execute_action=False` at the end.
  - `_handle_osdu_connect` / `_handle_osdu_import` — validate inputs and call `controller.connect_to_etp(...)` / `controller.force_etp_refresh()`.
  - `render()` — the `VDialog` with Files / OSDU tabs: remote-URL field, a drag-and-drop file zone (`#fesppFileInput` with a `change` handler that accumulates de-duped files into `_fesppFiles`), a selected-files list with per-file remove, a progress bar, and the full OSDU/ETP + proxy form. Footer has Cancel and Import (`click=_IMPORT_CLICK_JS`, `disabled` bound to `import_button_disabled`).

**State.** Reads/writes `dialog_visible`, `execute_action`, `import_tab`, `import_button_disabled`, `remote_files_location`, `upload_*` (file_names/count/uploading/progress/session_id/debug), `osdu_*` and `etp_*` vars.

**Collaborators.** `download_file_from_url` (io), `controller.load_epc_file` / `connect_to_etp` / `force_etp_refresh` / `select_etp_dataspace`. The server-side `/upload` route consumes the POST.

**Gotchas.** The remote-URL placeholder/label says `&` but the parser actually splits on `|` (`remote_files_location.split('|')`) — a mismatch a forker will trip over. Local upload deliberately does NOT go through `_on_execute_action`; the inline JS bypasses the WebSocket to avoid base64-over-socket. A native `<input type=file>` replaces its FileList per pick, so files are accumulated manually on the element and de-duped by name+size; the remove button must splice both `_fesppFiles` and `upload_file_names`. Progress text is partly French.

---

### `fespp_on_trame/app/ui/shared/helpers.py`
**Responsibility.** A single factory for a styled, vertically-resizable card.

**Key classes / functions.**
- `create_card(title, icon, height=None)` — returns the `VCardText` (so the caller populates it in a `with` block) of a flat `VCard` with a styled toolbar title. `height` overrides the default `min-height: 250px`.

**Collaborators.** Used by content-area widgets (e.g. `tools_band.py`, `multi_view.py`).

**Gotchas.** The returned `VCardText` is created but not entered — the caller must `with create_card(...):`. The card has `resize: vertical` so the user can drag-resize it.

---

### `fespp_on_trame/app/ui/shared/scripts.py`
**Responsibility.** A single blob of pure client-side JavaScript injected once into the layout (footer hiding, VTK-log auto-scroll, drawer resize handle, Stats-panel window-state mirroring).

**Key classes / functions.**
- `_CLIENT_JS` (constant) — IIFE with `hideEl`, `setupLogScroll` (MutationObserver keeps `#vtk-log-container` scrolled to bottom), `setupDrawerResize` (document-delegated mousedown/move/up on `.fespp-drawer-resize-handle`, clamps width to `[200, 900]`, pushes `drawer_width` via `window.trame.state.set` so Vuetify recomputes layout), and `setupStatsMinimize` (polls `ui_stats_panel_minimized`/`ui_stats_panel_maximized` every 150ms and toggles matching body classes).
- `inject_client_scripts()` — wraps `_CLIENT_JS` in `trame_client.Script` (a real executable `<script>`, unlike `html.Script`).

**State.** Reads/writes (client-side, via `window.trame.state`): `drawer_width`, `ui_stats_panel_minimized`, `ui_stats_panel_maximized`.

**Collaborators.** Pairs with `styles.py` (which reads the body classes set here) and `drawer.py` (the resize handle element).

**Gotchas.** Resize uses event delegation on `document` because Vue can re-mount the handle and orphan a directly-attached listener. Stats window-state is mirrored by a 150ms polling `setInterval` (not a reactive subscription) because there's no client-side reactive hook here. `drawer.py`'s resize handle and these listeners are coupled by the `fespp-drawer-resize-handle` class name.

---

### `fespp_on_trame/app/ui/shared/styles.py`
**Responsibility.** Injects the global CSS the app depends on (ptc fixes, footer hiding, dockview overflow/theme overrides, floating Stats minimize/maximize geometry).

**Key classes / functions.**
- `inject_global_styles()` — emits several `trame_client.Style` blocks: a ptc row-alignment fix; footer hiding + `--v-layout-bottom: 0`; `overflow: visible` on dockview content containers (so per-panel chrome can overflow upward into the tab row); the `body.fespp-stats-minimized` / `body.fespp-stats-maximized` geometry rules (using `:has(.fespp-stats-panel)`); and a dockview tab-row theme override pinning tab colors to blue-grey-darken-2 (`#455A64`) across all `dv-theme-*`.

**Collaborators.** The Stats classes are set by `scripts.py`'s `setupStatsMinimize`. `trame_client.Style` (real `<style>` in the head).

**Gotchas.** The Stats rules rely on the CSS `:has()` selector (modern browsers only). Resize handles are explicitly disabled (`pointer-events: none`) in min/max states so the user can't drag a stale inline size that would break restore. The dockview theme override widens the selector with `.dv-dockview` so it wins regardless of which theme prop ptc passes.

---

### `fespp_on_trame/app/ui/shared/widget/hierarchy_snackbar.py`
**Responsibility.** Bottom snackbar confirming that changing the tree-hierarchy mode wiped a non-empty selection.

**Key classes / functions.**
- `class HierarchySnackbar` — `render()` draws a 4500ms orange `VSnackbar` bound to `tree_hierarchy_snackbar_visible` with a fixed message.

**State.** Reads `tree_hierarchy_snackbar_visible`.

**Collaborators.** Visibility is driven by the engine when `tree_hierarchy_mode` changes (see `DisplayOptionsDialog`).

---

### `fespp_on_trame/app/ui/shared/widget/empty_color_snackbar.py`
**Responsibility.** Bottom snackbar shown when a tree eye-toggle activates a property that resolves to no VTK array on the rep's rendered source (empty/partial property, or a log on a discarded partition).

**Key classes / functions.**
- `class EmptyColorSnackbar` — `render()` draws a 4000ms blue-grey `VSnackbar` bound to `empty_color_snackbar_visible`, body text from the dynamic `empty_color_snackbar_text`.

**State.** Reads `empty_color_snackbar_visible`, `empty_color_snackbar_text`.

**Collaborators.** Both state vars are set by the engine's color/visibility logic when a ColorBy resolves to nothing.
