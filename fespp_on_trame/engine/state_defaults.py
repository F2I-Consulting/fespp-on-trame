"""Trame state defaults for the FESPP engine.

`init_state_defaults(state)` runs once at engine boot. It seeds every
state variable that the rest of the engine and the UI assume to exist:
selection, visibility and colouring tracking, diff / upload / view
status flags, the VTK log mirror, and so on. The groups roughly follow
the data flow (selection → loaded → visible → coloured / threshold /
diff)."""


def z_scale_of(state, vid):
    """The vertical exaggeration of 3D view `vid`, 1 when it has none."""
    try:
        return float(getattr(state, f"ui_scale_z__{vid}", None) or 1.0) or 1.0
    except (TypeError, ValueError) as exc:
        print(f"[fespp] the exaggeration of {vid} not read ({exc})", flush=True)
        return 1.0


def init_state_defaults(state):
    # --- Per-tab selection state -----------------------------------
    state.setdefault("ui_select_node_reservoir", [])
    state.setdefault("ui_select_node_surface", [])
    state.setdefault("ui_select_node_well", [])

    state.setdefault("fespp_data_selectors", [])

    # --- Camera links between render views -------------------------
    # Symmetric groups (view_link_menu.toggle_link); the broadcast is
    # MultiView._sync_camera_from on each view's EndAnimation.
    state.setdefault("view_links", {})
    state.setdefault("fespp_render_panels", [])
    state.setdefault("fespp_link_panels", [])
    # "New 3D view" asks what the view starts from (empty, or a copy of an
    # open one) instead of deciding: widgets/newview
    state.setdefault("ui_newview_open", False)
    # Whether the FESPP build answers the relationship query (what
    # DESIGNATES an object, which is in no object's XML). Probed on every
    # explorer update; false by default so a build without the query says
    # so rather than showing an empty graph that reads as "related to
    # nothing".
    state.setdefault("ui_xml_relations_ok", False)
    # The 3D view the user last worked in (MultiView._set_active): the one a
    # colour or an eye set is routed to while a panel of another kind —
    # Statistics, the well-log — is the active one
    # (view_routing.resolve_active_render_panel).
    state.setdefault("fespp_last_render_panel_id", "")

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
    state.setdefault("ui_active_node_reservoir_array_name", "")
    # Per-tab scoped active-property sets: the shared
    # active_color_array_name / active_property_kind /
    # active_representation_path / active_color_array_path /
    # active_representation_has_properties are PROJECTED from the visible
    # tab's set by activator.project_shared_from_tab().
    for _tab in ("reservoir", "surface", "well"):
        state.setdefault(f"ui_active_node_{_tab}_array_name", "")
        state.setdefault(f"ui_active_node_{_tab}_rep_path", "")
        state.setdefault(f"ui_active_node_{_tab}_property_kind", "")
        state.setdefault(f"ui_active_node_{_tab}_array_path", "")
        state.setdefault(f"ui_active_node_{_tab}_rep_has_props", False)
    state.setdefault("ui_active_node_reservoir_pending", False)
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
    # *active* panel's hidden set, for the consumers that read a flat set
    # (active_array, ExtractBlock's chain visibility). The per-view map
    # is the source of truth, driven by tree eye clicks that carry an
    # explicit panel_id.
    state.setdefault("ui_hidden_rep_paths_by_view", {})
    # Per-rep display type ("Surface" / "Wireframe" / …) — the
    # Attributes panel toggle writes the ACTIVE rep's entry only
    # (keyed by MARKER path when a single marker is active).
    state.setdefault("ui_rep_type_by_rep", {})
    # The files the import endpoint handed to the reader: [{name, size_mb,
    # objects, failed}] — Data health lists them.
    state.setdefault("ui_loaded_files", [])
    # Nodes whose rendering failed (unreadable dataset) — a warning badge
    # in the tree; filled by `vtk_log._flag_invalid_nodes`. The errors map
    # keeps FESAPI's own message per node (str(node_id) keys) for the
    # badge tooltip and the snackbar.
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
    # properties does not show a useless TimeControl.
    state.setdefault("panel_has_ts_by_id", {})

    # Per-view realization choice for MultiRealization properties.
    # Shape: {panel_id: {array_path: realization_index}}. Each panel
    # tracks which realization is active for each MR property it colors
    # by. The plugin loads every realization selected in the tree (the
    # MR parent is a grouping that propagates to children); this map only
    # drives which suffixed VTK array `<title>_real_<idx>` the panel's
    # ColorBy binds to. Empty for non-MR properties.
    state.setdefault("ui_active_realization_by_array_by_view", {})



    # --- Tree hierarchy --------------------------------------------

    # --- ETP connection --------------------------------------------
    state.setdefault("etp_dataspaces", [])

    # --- View / app status -----------------------------------------
    state.setdefault("has_data_loaded_once", False)
    state.setdefault("view_update", False)
    state.setdefault("view_reset_camera", False)
    state.setdefault("view_loading_message", "Loading... Please wait.")

    # --- VTK log panel ---------------------------------------------
    state.setdefault("vtk_log_messages", [])

    # Filled in on_server_ready once the port is known: each
    # process looks up its own port in proxy-mapping.txt to build
    # /api/{sid}/upload.
    state.setdefault("upload_session_id", "")

    # --- Slice plane (single axis-aligned plane per rep) ----------
    # Mirror of the active rep's `SlicePlane` state, written by
    # `SlicePlane._publish_state_vars` (engine/sources/slice_plane).
    state.setdefault("ui_slice_axis", "X")
    state.setdefault("ui_slice_offset", 0.0)
    state.setdefault("ui_slice_bounds", [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    # Server-resolved slider domain for the active axis, computed from
    # (axis, bounds) by the same publisher so a slider binds directly to
    # these scalars instead of evaluating a Vue template ternary (which
    # has parser quirks around `:` in certain contexts).
    state.setdefault("ui_slice_offset_min", 0.0)
    state.setdefault("ui_slice_offset_max", 1.0)
    state.setdefault("ui_slice_offset_step", 0.001)

    # --- Clip plane (single plane per rep, mirrors SlicePlane) ----
    state.setdefault("ui_clip_axis", "X")
    state.setdefault("ui_clip_offset", 0.0)
    state.setdefault("ui_clip_inside_out", False)
    state.setdefault("ui_clip_bounds", [0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
    state.setdefault("ui_clip_offset_min", 0.0)
    state.setdefault("ui_clip_offset_max", 1.0)
    state.setdefault("ui_clip_offset_step", 0.001)

    # --- Plane editor focus ----------------------------------------
    # Which filter the 3D plane widget is bound to: "slice", "clip", or
    # None (no widget shown). Slice and Clip can both be applied at
    # once, but only one is editable at a time.
    state.setdefault("ui_plane_edit_mode", None)

    # --- IJK slicer panel ------------------------------------------
    # Per-axis crop ranges + multi-slicer position lists, threshold
    # chain state.
    state.setdefault("ui_range_i", [0, 0])
    state.setdefault("ui_range_j", [0, 0])
    state.setdefault("ui_range_k", [0, 0])
    state.setdefault("ui_slices_i_list", [0])
    state.setdefault("ui_slices_j_list", [0])
    state.setdefault("ui_slices_k_list", [0])
    state.setdefault("ui_slices_range_mode", "full")
    state.setdefault("ui_slices_i_visible_list", [True])
    state.setdefault("ui_slices_j_visible_list", [True])
    state.setdefault("ui_slices_k_visible_list", [True])
    # Range-mode volume crops: per-volume [[i0,i1],[j0,j1],[k0,k1]]
    # ranges + per-volume eye. The active grid seeds one full-extent
    # volume; the UI's "+" grows the lists.
    state.setdefault("ui_volumes_list", [])
    state.setdefault("ui_volumes_visible_list", [])
    state.setdefault("ui_threshold_chain", [])
    state.setdefault("ui_threshold_arrays_available", [])
    state.setdefault("ui_threshold_pending_action", None)

    # --- The Statistics view ----------------------------------------
    # the parts of a grid whose eye is open in the view's tree (a
    # sub-representation, a blocked wellbore, a selection extract): their rows
    # follow the items of their grid (engine/compare_rows)
    state.setdefault("ui_compare_parts", [])
    # the 3D views' selection extracts as that tree lists them
    state.setdefault("ui_compare_session_rows", [])

    # Monotonic counter bumped (see `time_realization.register_per_view_time_label`)
    # whenever any per-view TimeControl moves. Watched by the Statistics view
    # so the 3D views' rows recompute (and their labels
    # re-resolve via the human time-label helper). Per-view time values
    # live in dynamic state vars `time_value_<panel_id>` — too dynamic
    # for a static `@state.change` declaration to enumerate, so they
    # are funnelled through this single pulse.
    state.setdefault("ui_per_view_time_pulse", 0)

    # Attributes drawer target view — `drawer_target_view_id` is the
    # render panel id the edit panels (slice / clip / threshold / IJK
    # slicers) operate on. Decoupled from `fespp_active_panel_id` so a
    # view's state can be edited without first focusing it; empty means
    # "follow the active panel" (see `source_resolver.target_view_and_panel`).
    state.setdefault("drawer_target_view_id", "")

