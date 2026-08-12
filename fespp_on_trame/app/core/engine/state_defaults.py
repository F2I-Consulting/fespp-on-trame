"""Trame state defaults for the FESPP engine.

`init_state_defaults(state)` runs once at engine boot. It seeds every
state variable that the rest of the engine + UI assume to exist:
selection / visibility / coloring tracking, diff / upload / view
status flags, VTK log mirror, etc. Group order roughly matches
data-flow stages (selection → loaded → visible → coloured / threshold
/ diff)."""


def init_state_defaults(state):
    # --- Per-tab selection state -----------------------------------
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])

    state.setdefault("animation_delay", 0.1)

    state.setdefault("fespp_data_selectors", [])

    # --- Per-tab active (highlighted) node -------------------------
    # The node currently activated in each tree tab. Activation drives the
    # Attributes panel ONLY (never the 3D view — coloring is owned by the
    # eye / active-array path).
    state.setdefault("ui_active_node_reservoir", [])
    state.setdefault("ui_active_node_surface", [])
    state.setdefault("ui_active_node_well", [])
    state.setdefault("ui_active_node_reservoir_type_rep", "")
    state.setdefault("ui_active_node_reservoir_type", "")
    state.setdefault("ui_active_node_reservoir_title", "")
    # Rep path of the RESERVOIR tab's active node. The reservoir-scoped
    # Threshold / IJK-slicer panels resolve their rep through THIS var rather
    # than the global active_representation_path, which any tab (surface /
    # well) or an eye-click channel activation can overwrite.
    state.setdefault("ui_active_node_reservoir_rep_path", "")
    # Underlying property kind of the active node — drives the editor switch
    # in solid_color_panel (continuous LUT vs categorical list).
    state.setdefault("active_property_kind", "")
    state.setdefault("active_representation_has_properties", False)

    # --- Visibility tracking ---------------------------------------
    # ui_loaded_rep_paths: rep paths currently materialised in
    #   ParaView (eye icon rendered next to those tree nodes).
    # ui_hidden_rep_paths: subset whose display.Visibility was
    #   toggled off via the eye. Loaded but not in this set →
    #   visible.
    state.setdefault("ui_loaded_rep_paths", [])
    state.setdefault("ui_hidden_rep_paths", [])
    # Per-view visibility: ui_hidden_rep_paths is an alias mirroring the
    # *active* panel's hidden set (so consumers like the
    # source_registry auto-reload logic keep working). The per-view map
    # is the source of truth, driven by tree eye clicks that carry an
    # explicit panel_id.
    state.setdefault("ui_hidden_rep_paths_by_view", {})
    # Per-rep display type ("Surface" / "Wireframe" / …) — the
    # Attributes panel toggle writes the ACTIVE rep's entry only
    # (keyed by MARKER path when a single marker is active).
    state.setdefault("ui_rep_type_by_rep", {})
    # Nodes whose rendering failed (unreadable dataset) — ⚠ badge in
    # the tree; filled by `vtk_log._flag_invalid_nodes`. The errors map
    # keeps FESAPI's own message per node (str(node_id) keys) for the
    # badge tooltip + snackbar.
    state.setdefault("ui_invalid_node_ids", [])
    state.setdefault("ui_invalid_node_errors", {})

    # --- Coloring tracking -----------------------------------------
    # ui_loaded_array_paths: data-array tree nodes whose data is
    #   loaded (Property / TimeSeries / MultiRealization selectors).
    # ui_active_array_by_rep: at most one entry per rep — the array
    #   currently coloring it. Absent entry → SolidColor. Mirrors the
    #   *active panel's* per-view entry so consumers (Activator,
    #   solid_color_panel) that read the flat map see the active view.
    state.setdefault("ui_loaded_array_paths", [])
    state.setdefault("ui_active_array_by_rep", {})
    # Per-rep solid-color chip assignment: data_load reserves a distinct
    # color per loaded rep, with a round-robin cursor over the palette.
    state.setdefault("solid_color_by_rep", {})
    state.setdefault("solid_color_next_idx", 0)
    # Per-view active arrays — source of truth for the tree's
    # per-panel eye annotation. Shape:
    #   {panel_id: {rep_path: array_path}}
    # Absence (or null) of (panel_id, rep_path) → SolidColor in
    # that view.
    state.setdefault("ui_active_array_by_rep_by_view", {})
    # Markers (WellboreMarkerFrame children) display MULTIPLE at a time,
    # each independently toggleable — unlike single-select log channels.
    #   ui_loaded_marker_paths: marker leaf node paths that currently
    #     carry a per-marker eye (their MarkerFrame rep is loaded).
    #   ui_visible_marker_paths_by_view: {panel_id: [marker_path, ...]}
    #     — which markers are SHOWN in each view. Each shown marker
    #     renders via its own per-(rep, view) EnergisticsExtractor.
    state.setdefault("ui_loaded_marker_paths", [])
    state.setdefault("ui_visible_marker_paths_by_view", {})
    # Per-panel "has TimeSeries property currently active" flag,
    # derived from ui_active_array_by_rep_by_view via the change
    # handler in active_array.py. Drives the per-view TimeControl
    # visibility in FesppMultiView so a panel rendering only static
    # properties doesn't show a useless TC.
    state.setdefault("panel_has_ts_by_id", {})

    # Per-view realization choice for MultiRealization properties.
    # Shape: {panel_id: {array_path: realization_index}}. Each panel
    # tracks which realization is active for each MR property it colors
    # by. The plugin loads every realization selected in the tree (the
    # MR parent is a grouping that propagates to children); this map only
    # drives which suffixed VTK array `<title>_real_<idx>` the panel's
    # ColorBy binds to. Empty for non-MR properties.
    state.setdefault("ui_active_realization_by_array_by_view", {})

    # Per-panel specs of active MR properties, computed from the maps
    # above by `realization_dispatch.recompute_panel_mr_specs`. Drives
    # the per-view RealizationPicker widget. Shape:
    #   {panel_id: [{
    #       "array_path": str,
    #       "title": str,
    #       "available_indices": [int, ...],
    #       "current_idx": int,
    #   }, ...]}
    # Empty for panels with no MR property active. Recomputed on
    # changes to ui_active_array_by_rep_by_view or
    # ui_active_realization_by_array_by_view.
    state.setdefault("ui_panel_active_mr_specs_by_id", {})

    # Per-panel "has at least one MR property active" flag — derived
    # from `ui_panel_active_mr_specs_by_id` by
    # `realization_dispatch.recompute_panel_has_mr`. Drives the
    # per-view MR toggle button's enabled state in the panel action
    # bar (disabled when the panel has no MR active to toggle).
    state.setdefault("panel_has_mr_by_id", {})

    # Aggregated MR specs across every panel — drives the global
    # RealizationPicker in the tools band. Shape mirrors
    # `ui_panel_active_mr_specs_by_id` entries but adds a `mixed` flag,
    # set when panels disagree on the active index for a given property.
    # Computed by `realization_dispatch.recompute_global_mr_specs`.
    state.setdefault("ui_global_mr_specs", [])

    # User pick in the global RealizationPicker's property dropdown.
    # Falls back to the first available spec when empty / stale;
    # clamping happens server-side in
    # `realization_dispatch.resolve_global_selected`.
    state.setdefault("ui_global_mr_selected_path", "")

    # Selected spec resolved from (ui_global_mr_specs,
    # ui_global_mr_selected_path). The widget binds every control
    # (buttons / index dropdown / slider) to this spec so the whole
    # row reflects the currently-picked property. None when no MR is
    # available.
    state.setdefault("ui_global_mr_selected_spec", None)

    # --- Diff feature ----------------------------------------------
    state.setdefault("diff_array_a_path", None)
    state.setdefault("diff_array_b_path", None)
    state.setdefault("diff_array_choices", [])
    state.setdefault("diff_array_b_choices", [])
    state.setdefault("diff_compute_error", "")

    state.setdefault("fespp_diff_ready", False)
    state.setdefault("fespp_diff_computing", False)
    state.setdefault("diff_colors_dialog_visible", False)
    state.setdefault("fespp_diff_panel_id", None)
    state.setdefault("add_view_dialog_visible", False)
    state.setdefault("add_view_kind", "render")

    # --- Tree hierarchy --------------------------------------------
    state.setdefault("tree_hierarchy_mode", "flat")

    # --- ETP connection --------------------------------------------
    state.setdefault("etp_dataspaces", [])
    state.setdefault("etp_selected_dataspace", None)

    # --- View / app status -----------------------------------------
    state.setdefault("has_data_loaded_once", False)
    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    state.setdefault("view_loading_message", "Loading... Please wait.")

    # --- VTK log panel ---------------------------------------------
    state.setdefault("vtk_log_messages", [])
    state.setdefault("vtk_log_visible", False)

    # --- Upload progress -------------------------------------------
    state.setdefault("upload_uploading", False)
    state.setdefault("upload_parsing", False)
    state.setdefault("upload_progress", 0)
    state.setdefault("upload_file_count", 0)
    state.setdefault("upload_file_names", [])
    state.setdefault("upload_debug", "")
    # Filled in on_server_ready once the port is known: each
    # process looks up its own port in proxy-mapping.txt to build
    # /api/{sid}/upload.
    state.setdefault("upload_session_id", "")

    # --- Slice plane (single axis-aligned plane per rep) ----------
    # Mirror of the active rep's `SlicePlane` state. The slice panel
    # binds to these; user edits round-trip through controller
    # `slice_set` which writes back here via `publish_slice_state`.
    state.setdefault("ui_slice_enabled", False)
    state.setdefault("ui_slice_axis", "X")
    state.setdefault("ui_slice_offset", 0.0)
    state.setdefault("ui_slice_bounds", [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    # Server-resolved slider domain for the active axis. Computed by
    # `publish_slice_state` from (axis, bounds) so the slider widget
    # binds directly to these scalars instead of evaluating a Vue
    # template ternary (which has parser quirks around `:` in
    # certain contexts).
    state.setdefault("ui_slice_offset_min", 0.0)
    state.setdefault("ui_slice_offset_max", 1.0)
    state.setdefault("ui_slice_offset_step", 0.001)

    # --- Clip plane (single plane per rep, mirrors SlicePlane) ----
    state.setdefault("ui_clip_enabled", False)
    state.setdefault("ui_clip_axis", "X")
    state.setdefault("ui_clip_offset", 0.0)
    state.setdefault("ui_clip_inside_out", False)
    state.setdefault("ui_clip_bounds", [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    state.setdefault("ui_clip_offset_min", 0.0)
    state.setdefault("ui_clip_offset_max", 1.0)
    state.setdefault("ui_clip_offset_step", 0.001)

    # --- Plane editor focus ----------------------------------------
    # Which filter the 3D plane widget is currently bound to: "slice",
    # "clip", or None (no widget shown). Slice and Clip can both be
    # applied simultaneously, but only one is editable at a time —
    # the panel's per-filter "Edit" toggle writes here.
    state.setdefault("ui_plane_edit_mode", None)

    # --- IJK slicer panel ------------------------------------------
    # Per-axis crop ranges + multi-slicer position lists, threshold
    # chain state.
    state.setdefault("ui_range_i", [0, 0])
    state.setdefault("ui_range_j", [0, 0])
    state.setdefault("ui_range_k", [0, 0])
    state.setdefault("ui_slices_i_active", False)
    state.setdefault("ui_slices_i_list", [0])
    state.setdefault("ui_slices_j_active", False)
    state.setdefault("ui_slices_j_list", [0])
    state.setdefault("ui_slices_k_active", False)
    state.setdefault("ui_slices_k_list", [0])
    state.setdefault("ui_slices_range_active", False)
    state.setdefault("ui_slices_range_i", [0, 0])
    state.setdefault("ui_slices_range_j", [0, 0])
    state.setdefault("ui_slices_range_k", [0, 0])
    state.setdefault("ui_slices_range_mode", "slice")
    state.setdefault("ui_slices_i_visible_list", [True])
    state.setdefault("ui_slices_j_visible_list", [True])
    state.setdefault("ui_slices_k_visible_list", [True])
    state.setdefault("ui_slices_volume_visible", True)
    state.setdefault("ui_threshold_chain", [])
    state.setdefault("ui_threshold_arrays_available", [])
    state.setdefault("ui_threshold_pending_action", None)
    state.setdefault("ui_threshold_local_ranges", {})

    # Descriptive statistics.
    #
    # The singleton stats dockview tab (created lazily on first pin by
    # `multi_view._add_stats_panel`) renders one VCard per property the
    # user has pinned via the tree's "Display stats" button (a property
    # toggle independent of the active-node or eye state). Each card's
    # table has:
    #
    #   - 1+ "Original" rows: a `default` row (uses the property's first
    #     available realization / time step) plus zero or more `custom`
    #     rows the user pinned via a per-row pin icon, each with its own
    #     real / ts selection. Original rows compute on the unfiltered
    #     rep_data — independent of any view's slicer / clip / threshold.
    #
    #   - 1 row per render view: stats on the view's post-threshold
    #     output (what the user actually sees) at that view's
    #     realization / time pick.
    #
    # `ui_descriptive_stats` is the legacy single-table state; the
    # current model uses `ui_stats_tables` below.
    state.setdefault("ui_descriptive_stats", [])

    # Property paths whose stats are pinned in the drawer panel.
    # Order matters (rendered top-to-bottom). Toggled via the
    # tree's "Display stats" button.
    state.setdefault("ui_stats_pinned_paths", [])

    # Per-pinned-property panel state:
    #   {array_path: {"originals": [{"id", "pinned", "real_idx", "ts_idx"}, ...]}}
    # The first entry of `originals` is always `{"id": "default",
    # "pinned": False, "real_idx": None, "ts_idx": None}` — its
    # selectors default to the first available indices and are not
    # persisted. Pin icon on the row turns `pinned=True` and copies
    # the current indices into a new `custom-<n>` entry, leaving
    # the default row free to follow defaults again. Custom entries
    # are deletable.
    state.setdefault("ui_stats_panel_state", {})

    # Computed stats tables, one entry per pinned property.
    # Shape:
    #   {
    #     array_path: {
    #         "title": "VOIL",
    #         "rows": [
    #             {
    #                 "kind": "original" | "view",
    #                 "id": <stable id used by the UI v-for key>,
    #                 "label": "Original (real_23, t0)" | "View 1 (real_23)",
    #                 "real_idx": int | null,  # for selectors / UI display
    #                 "ts_idx": int | null,
    #                 "pinned": bool,  # only meaningful for kind=='original'
    #                 # vtkDescriptiveStatistics output:
    #                 "Cardinality": int, "Minimum": float, ...
    #             }, ...
    #         ],
    #     }, ...
    #   }
    state.setdefault("ui_stats_tables", {})
    # Monotonic counter bumped by `publish_descriptive_stats` on every
    # recompute. Used as a tie-breaker in the panel's v-for `:key` so Vue
    # always treats rows as new after a recompute, even when their
    # structural content is identical (e.g. a TS picker change on a
    # static-time array).
    state.setdefault("ui_stats_publish_version", 0)
    # Monotonic counter bumped by `time_realization.register_per_view_time_label`
    # whenever any per-view TC moves. Watched by the stats trigger
    # list so the View rows recompute (and their labels re-resolve
    # via the human time-label helper). Per-view time values live
    # in dynamic state vars `time_value_<panel_id>` — too dynamic
    # for the static `@state.change` declaration to enumerate, so
    # we funnel them through this single pulse.
    state.setdefault("ui_per_view_time_pulse", 0)

    # Per-property compare cart. ONE cart per property — drives both
    # the floating Compare-stats panel (numeric table) and the
    # Compare-distribution overlay. Mixing properties in the same cart
    # is structurally impossible (the cart is keyed by array_path; the
    # UI only renders the Cmp column / Compare button on cards whose
    # property is MR or TS). Maps array_path -> list[item_key] where
    # item_key is "<array_path>|<row_kind>|<row_id>".
    state.setdefault("ui_stats_compare", {})
    # Singleton tracker for the floating Compare-stats panel
    # (dockview kind="stats_compare"). Maps array_path -> panel_id.
    state.setdefault("ui_stats_compare_panel", {})
    # Singleton tracker for the floating Compare-distribution panel.
    # Maps array_path -> panel_id.
    state.setdefault("ui_stats_compare_dist_panel", {})
    # Pre-resolved comparison items — `[{key, row, propertyTitle}, …]`
    # computed by `stats_dispatch.publish_compare_items` from the active
    # `ui_stats_compare[array_path]` cart × `ui_stats_tables`. The
    # dialog's v-for iterates this directly instead of a complex inline
    # JS lookup (Vue's template parser balks at deeply nested arrow
    # functions and object literals after `return ? :`). Stale entries
    # whose row no longer exists are filtered out of the list.
    state.setdefault("ui_stats_compare_items", [])

    # Attributes drawer target view — `drawer_target_view_id` is the
    # render panel id the edit panels (slice / clip / threshold / IJK
    # slicers) operate on. Decoupled from `fespp_active_panel_id` so the
    # user can edit a view's state without first focusing it.
    #
    # When `drawer_target_view_pinned` is False (default), the target
    # follows the active panel automatically. When True, the user has
    # explicitly picked a view via the picker and the target stays put
    # across active-panel switches; if the pinned view is closed, the
    # auto-depin handler reverts to follow-active.
    state.setdefault("drawer_target_view_id", "")
    state.setdefault("drawer_target_view_pinned", False)

    # Panel id of the singleton stats dockview tab (see
    # `multi_view._add_stats_panel`). Empty string when no stats tab is
    # currently open. Driven by `multi_view.add_view(kind="stats")` and
    # cleared on `_on_view_closed`. Read by the tree's chart icon
    # handler to decide whether to focus an existing tab or create a
    # new one.
    state.setdefault("fespp_stats_panel_id", "")

    # Floating Stats overlay collapsed-to-tabstrip flag. When True, the
    # JS watcher in ui/shared/scripts.py mirrors it to a
    # fespp-stats-minimized class on <body>; CSS in ui/shared/styles.py
    # then collapses the floating window's .dv-resize-container shell to
    # a single tabstrip row. Per-session — not persisted across reload.
    state.setdefault("ui_stats_panel_minimized", False)
    # Mutex companion to ui_stats_panel_minimized. When True, scripts.py
    # adds the `fespp-stats-maximized` class to <body> and styles.py
    # pins the floating Stats shell to cover the full multi-view content
    # area. The two flags are mutually exclusive — toggling one clears
    # the other. Clearing the class restores the original inline geometry.
    state.setdefault("ui_stats_panel_maximized", False)

    # Distribution panels are multi-instance — each open spawns a fresh
    # floating dockview group with its own per-panel state var
    # `ui_distribution_figure_<panel_id>` plus per-panel option vars
    # (mode / nbins / log_y / show_stats / cumulative / norm) seeded by
    # `boot._spawn_distribution_panel`. This lookup maps panel id → row
    # context (single row vs compare selection) so the per-panel option
    # watcher can re-run the same compute on every option change; cleared
    # by `multi_view._on_view_closed` when the panel is dismissed.
    state.setdefault("ui_distribution_contexts", {})

    # Active inner tab of the SlicersPanel. Single state var across
    # all main tabs (reservoir / surface / well) — VTabs mandatory
    # mode auto-falls-back to the first available tab when the value
    # doesn't match a rendered VTab.
    state.setdefault("ui_slicers_tab", "ijk")

    # --- Misc UI ---------------------------------------------------
    state.setdefault("ui_scale_z", 1.0)
    state.setdefault("load_mode", "auto")
