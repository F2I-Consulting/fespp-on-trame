"""Trame state defaults for the FESPP engine.

`init_state_defaults(state)` runs once at engine boot. It seeds every
state variable that the rest of the engine + UI assume to exist:
selection / visibility / coloring tracking, diff / upload / view
status flags, VTK log mirror, etc.

Centralised here so `boot.py` stays focused on lifecycle (object
construction + handler wiring) and so adding a new state var doesn't
require scrolling through hundreds of lines of handlers to find the
init block. Group order roughly matches data-flow stages
(selection → loaded → visible → coloured / threshold / diff)."""


def init_state_defaults(state):
    # --- Per-tab selection state -----------------------------------
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])

    state.setdefault("animation_delay", 0.1)

    state.setdefault("fespp_data_selectors", [])

    # --- Visibility tracking ---------------------------------------
    # ui_loaded_rep_paths: rep paths currently materialised in
    #   ParaView (eye icon rendered next to those tree nodes).
    # ui_hidden_rep_paths: subset whose display.Visibility was
    #   toggled off via the eye. Loaded but not in this set →
    #   visible.
    state.setdefault("ui_loaded_rep_paths", [])
    state.setdefault("ui_hidden_rep_paths", [])
    # Per-view visibility: ui_hidden_rep_paths is kept as a compat
    # alias mirroring the *active* panel's hidden set (so existing
    # consumers — source_registry auto-reload logic, the legacy
    # tree render binding — keep working). The per-view map is the
    # source of truth driven by tree eye clicks that carry an
    # explicit panel_id.
    state.setdefault("ui_hidden_rep_paths_by_view", {})

    # --- Coloring tracking -----------------------------------------
    # ui_loaded_array_paths: data-array tree nodes whose data is
    #   loaded (Property / TimeSeries / MultiRealization selectors).
    # ui_active_array_by_rep: at most one entry per rep — the array
    #   currently coloring it. Absent entry → SolidColor. Kept as a
    #   mirror of the *active panel's* per-view entry so legacy
    #   consumers (Activator, solid_color_panel) keep working with
    #   the active view's state.
    state.setdefault("ui_loaded_array_paths", [])
    state.setdefault("ui_active_array_by_rep", {})
    # Per-view active arrays — source of truth for the tree's
    # per-panel eye annotation. Shape:
    #   {panel_id: {rep_path: array_path}}
    # Absence (or null) of (panel_id, rep_path) → SolidColor in
    # that view.
    state.setdefault("ui_active_array_by_rep_by_view", {})
    # Per-panel "has TimeSeries property currently active" flag,
    # derived from ui_active_array_by_rep_by_view via the change
    # handler in active_array.py. Drives the per-view TimeControl
    # visibility in FesppMultiView so a panel rendering only static
    # properties doesn't show a useless TC.
    state.setdefault("panel_has_ts_by_id", {})

    # Per-view realization choice for MultiRealization properties.
    # Shape: {panel_id: {array_path: realization_index}}. Each panel
    # tracks which realization is active for each MR property it
    # currently colors by. The plugin loads every realization that's
    # selected in the tree (the MR parent is a grouping that
    # propagates to children); this map only drives which suffixed
    # VTK array `<title>_real_<idx>` the panel's ColorBy binds to.
    # Empty for non-MR properties (their realization choice is N/A).
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
    # `ui_panel_active_mr_specs_by_id` entries but uses a single
    # synthetic "_global" bucket key and adds a `mixed` flag set when
    # panels disagree on the active index for a given property. Empty
    # when no panel has an MR active. Computed by
    # `realization_dispatch.recompute_global_mr_specs`.
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
    state.setdefault("upload_progress", 0)
    state.setdefault("upload_file_count", 0)
    state.setdefault("upload_file_names", [])
    state.setdefault("upload_debug", "")
    # Filled in on_server_ready once the port is known: each
    # process looks up its own port in proxy-mapping.txt to build
    # /api/{sid}/upload.
    state.setdefault("upload_session_id", "")

    # --- Slice plane (MVP: single axis-aligned plane per rep) -----
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
    # chain state. Previously set by `SlicerControls.__init__`; moved
    # here so the new SlicersPanel parent (with tabs) doesn't need to
    # instantiate the legacy class just to seed defaults.
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
    state.setdefault("ui_slices_range_mode", "range")
    state.setdefault("ui_slices_i_visible_list", [True])
    state.setdefault("ui_slices_j_visible_list", [True])
    state.setdefault("ui_slices_k_visible_list", [True])
    state.setdefault("ui_slices_volume_visible", True)
    state.setdefault("ui_threshold_chain", [])
    state.setdefault("ui_threshold_arrays_available", [])
    state.setdefault("ui_threshold_pending_action", None)
    state.setdefault("ui_threshold_local_ranges", {})

    # Active inner tab of the SlicersPanel. Single state var across
    # all main tabs (reservoir / surface / well) — VTabs mandatory
    # mode auto-falls-back to the first available tab when the value
    # doesn't match a rendered VTab.
    state.setdefault("ui_slicers_tab", "ijk")

    # --- Misc UI ---------------------------------------------------
    state.setdefault("ui_scale_z", 1.0)
    state.setdefault("load_mode", "auto")
